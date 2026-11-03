"""A confirmed contract can say returned records carry a value, unsaved.

Overdue is derived on read while the stored status stays `active`. The
proposal comes from the model's declared values, the returned entity and the
method's own words; the gate checks the body sets the value on what it
returns and never saves it. Each test pins a decision, silence included.
"""

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import generator  # noqa: E402
import review_contracts  # noqa: E402
from kernel.extraction import contracts  # noqa: E402


def field(name, primary_key=False):
    return {"name": name, "type": "int" if primary_key else "string",
            "primary_key": primary_key, "foreign_key": None}


CTX = {
    "entity_names": ["Loan"],
    "models": [{"name": "Loan", "fields": [field("id", True),
                                           field("status")]}],
    "invariants": [{"text": "Loan.status must be one of 'active', "
                            "'returned', 'overdue'"}],
    "repositories": [],
}

OVERDUE = {"name": "get_overdue_loans", "return_type": "list[Loan]",
           "description": "Returns loans that are overdue.", "params": [],
           "raises": []}


def propose(method=OVERDUE, role="service"):
    return review_contracts._propose(CTX, "LoanService", method, role, "")


DERIVE = {"target": "loan.status", "value": "overdue"}


def complaints(body):
    return generator._contract_complaints(ast.parse(body),
                                          {"derives": [DERIVE]})


class SchemaTests(unittest.TestCase):
    def test_a_derive_is_kept_and_a_malformed_one_dropped(self):
        record = contracts.normalize_contract({
            "holder": "H", "method": "m",
            "derives": [DERIVE, {"target": "loan.status"}, "junk",
                        {"target": "x.y", "value": True}]})
        self.assertEqual(record["derives"], [DERIVE])


class ProposalTests(unittest.TestCase):
    def test_a_declared_value_the_text_names_is_proposed(self):
        proposal = propose()
        self.assertEqual(proposal["derives"], [DERIVE])
        self.assertIn("keep_derives",
                      [question["id"] for question in proposal["questions"]])

    def test_text_naming_no_declared_value_proposes_nothing(self):
        self.assertIsNone(propose(dict(OVERDUE, description="Returns loans.")))

    def test_a_method_returning_no_entity_proposes_nothing(self):
        self.assertIsNone(propose(dict(OVERDUE, return_type="None")))

    def test_a_method_with_effects_is_not_a_derive(self):
        method = dict(OVERDUE, name="return_loan", return_type="Loan",
                      description="Sets status to returned.")
        proposal = propose(method)
        self.assertEqual(proposal["derives"] if proposal else [], [])


class FinalizeTests(unittest.TestCase):
    def finalize(self, answers):
        return review_contracts._finalize(propose(), answers, "sha", CTX)

    def test_a_kept_derive_reaches_the_record(self):
        self.assertEqual(self.finalize({"keep_derives": "keep"})["derives"],
                         [DERIVE])

    def test_a_dropped_derive_does_not(self):
        self.assertEqual(self.finalize({"keep_derives": "drop"})["derives"],
                         [])


class GateTests(unittest.TestCase):
    def test_assigning_the_value_on_each_record_is_accepted(self):
        self.assertEqual(complaints(
            "loans = self._repos['LoanRepository'].find_overdue_loans()\n"
            "for loan in loans:\n    loan.status = 'overdue'\n"
            "return loans\n"), [])

    def test_replacing_with_a_keyword_is_accepted(self):
        self.assertEqual(complaints(
            "import dataclasses\n"
            "return [dataclasses.replace(loan, status='overdue') "
            "for loan in loans]\n"), [])

    def test_never_setting_the_value_is_refused(self):
        found = complaints("return self._repos['LoanRepository']"
                           ".find_overdue_loans()\n")
        self.assertEqual(found, [
            "the confirmed contract derives `loan.status` = 'overdue' on "
            "the returned records, but the body never sets it"])

    def test_saving_the_derived_value_is_refused(self):
        found = complaints(
            "for loan in loans:\n    loan.status = 'overdue'\n"
            "    self._repos['LoanRepository'].update(loan_id=loan.id, "
            "status='overdue')\n")
        self.assertEqual(found, [
            "the confirmed contract derives `loan.status` in memory only, "
            "but the body calls `update`, which saves it"])


class PromptTests(unittest.TestCase):
    def test_the_prompt_says_in_memory_only(self):
        text = "\n".join(generator._contract_lines({"derives": [DERIVE]}))
        self.assertIn("`loan.status` = 'overdue'", text)
        self.assertIn("do not save it", text)


if __name__ == "__main__":
    unittest.main()
