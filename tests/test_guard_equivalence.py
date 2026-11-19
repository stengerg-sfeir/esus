"""A confirmed precondition may be met by a different but equal guard.

The structural comparison accepts the contract's own text. When it refuses a
guard that is not the same expression, a judge reads the whole body against
the confirmed condition; only a clear YES accepts, and opposite polarity is
never sent to the judge.
"""

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import generator  # noqa: E402

PRECONDITION = {
    "check": "getattr(self._repos['LoanRepository'].read_one(loan_id), "
             "'return_date', None) is not None",
    "error": "AlreadyReturnedLoanError", "raise_when": "true"}

EQUAL_BODY = (
    "loan = self._repos['LoanRepository'].read_one(loan_id=loan_id)\n"
    "if getattr(loan, 'return_date', None) is not None:\n"
    "    raise errors.AlreadyReturnedLoanError('returned')\n")

OPPOSITE_BODY = (
    "if not (getattr(self._repos['LoanRepository'].read_one(loan_id), "
    "'return_date', None) is not None):\n"
    "    raise errors.AlreadyReturnedLoanError('returned')\n")

INVERTED_BODY = (
    "if getattr(self._repos['LoanRepository'].read_one(loan_id), "
    "'return_date', None) is None:\n"
    "    raise errors.AlreadyReturnedLoanError('returned')\n")

SAME_TEXT_BODY = (
    "if getattr(self._repos['LoanRepository'].read_one(loan_id), "
    "'return_date', None) is not None:\n"
    "    raise errors.AlreadyReturnedLoanError('returned')\n")


class Judge:
    def __init__(self, verdict):
        self.verdict, self.calls = verdict, 0

    def __call__(self, precondition, body_text):
        self.calls += 1
        return self.verdict


def complaints(body, judge=None):
    return generator._raise_when_complaints(
        ast.parse(body), PRECONDITION, judge, body)


ALIASED_PRECONDITION = {
    "check": "event.status == 'pending'",
    "error": "ValueError",
    "raise_when": "false",
}

ALIASED_BODY = (
    "if registration.status != 'pending':\n"
    "    raise ValueError('registration is not pending')\n")


class GuardEquivalenceTests(unittest.TestCase):
    def test_a_different_guard_is_refused_without_a_judge(self):
        self.assertEqual(len(complaints(EQUAL_BODY)), 1)

    def test_a_local_alias_is_accepted_without_a_judge(self):
        found = generator._raise_when_complaints(
            ast.parse(ALIASED_BODY), ALIASED_PRECONDITION, None, ALIASED_BODY)
        self.assertEqual(found, [])

    def test_an_alias_does_not_hide_a_different_field(self):
        body = ("if registration.state != 'pending':\n"
                "    raise ValueError('registration is not pending')\n")
        found = generator._raise_when_complaints(
            ast.parse(body), ALIASED_PRECONDITION, None, body)
        self.assertEqual(len(found), 1)

    def test_a_judge_yes_accepts_the_different_guard(self):
        judge = Judge((True, "same truth value"))
        self.assertEqual(complaints(EQUAL_BODY, judge), [])
        self.assertEqual(judge.calls, 1)

    def test_a_judge_no_refuses_and_says_why(self):
        found = complaints(EQUAL_BODY, Judge((False, "it checks status")))
        self.assertEqual(len(found), 1)
        self.assertIn("it checks status", found[0])

    def test_the_contracts_own_text_never_asks_the_judge(self):
        judge = Judge((False, "never read"))
        self.assertEqual(complaints(SAME_TEXT_BODY, judge), [])
        self.assertEqual(judge.calls, 0)

    def test_opposite_polarity_is_not_sent_to_the_judge(self):
        judge = Judge((True, "never read"))
        found = complaints(OPPOSITE_BODY, judge)
        self.assertEqual(len(found), 1)
        self.assertIn("when the condition is true", found[0])
        self.assertEqual(judge.calls, 0)


    def test_an_inverted_guard_in_another_form_reaches_the_judge(self):
        # The polarity check is structural; `is None` is not recognised as
        # the negation of `is not None`, so only the judge can refuse it.
        judge = Judge((False, "it raises when the date is missing"))
        self.assertEqual(len(complaints(INVERTED_BODY, judge)), 1)
        self.assertEqual(judge.calls, 1)


class VerdictParsingTests(unittest.TestCase):
    def test_a_clear_yes(self):
        self.assertEqual(
            generator._parse_equivalence("VERDICT: YES\nREASON: same."),
            (True, "same."))

    def test_a_clear_no(self):
        self.assertEqual(
            generator._parse_equivalence("verdict: no\nreason: looser"),
            (False, "looser"))

    def test_anything_unclear_is_no(self):
        for reply in ("", None, "Probably yes", "VERDICT: MAYBE"):
            self.assertFalse(generator._parse_equivalence(reply)[0])

    def test_the_prompt_names_the_error_condition_and_body(self):
        prompt = generator._equivalence_prompt(PRECONDITION, EQUAL_BODY)
        for needed in ("AlreadyReturnedLoanError", "return_date", "VERDICT"):
            self.assertIn(needed, prompt)


if __name__ == "__main__":
    unittest.main()
