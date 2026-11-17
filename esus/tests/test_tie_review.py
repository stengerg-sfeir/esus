"""Recorded tie decisions settle a question permanently.

Applying an empty or stale record set is the identity; a record patches the
entry with its exact text and marks it decided-by-user, which is what stops
the review from asking again. The review flow itself is pinned without a
human: scripted answers write `decisions.json` and patch the document, and a
second run finds nothing open.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.extraction import decisions  # noqa: E402
from review_ties import ask, collect_questions, describe_question, run_review  # noqa: E402


class Log:
    def __init__(self):
        self.lines = []

    def write(self, text):
        self.lines.append(text)


GUARD_TIE = {
    "text": "copies must not exceed",
    "source": "invariant",
    "pattern_id": "BUDGET_OVERFLOW_GUARD",
    "runner_up_pattern_id": "QUOTA_CAPACITY_GUARD",
    "confidence": 0.376,
    "margin": 0.0023,
    "decision": "undecided",
    "undecided_stage": "pattern",
}

FILTER_TIE = {
    "text": "find things",
    "pattern_id": "FILTER_BY_FIELD",
    "runner_up_pattern_id": "FILTER_WITH_PAGINATION",
    "confidence": 0.3,
    "margin": 0.05,
    "decision": "undecided",
    "undecided_stage": "pattern",
}


class ApplyDecisionsTests(unittest.TestCase):
    def test_a_recorded_answer_patches_its_exact_text(self):
        records = [{"text": "copies must not exceed", "chosen_pattern_id": "QUOTA_CAPACITY_GUARD"}]
        patched = decisions.apply_decisions([dict(GUARD_TIE)], records)
        self.assertEqual(patched[0]["pattern_id"], "QUOTA_CAPACITY_GUARD")
        self.assertEqual(patched[0]["decision"], "decided")
        self.assertEqual(patched[0]["decided_by"], "user")

    def test_an_override_moves_the_rejected_side_to_runner_up(self):
        """Choosing the alternative must not record the winner against itself.

        The classifier wrote BUDGET with QUOTA as runner-up; the human chose
        QUOTA. The patched entry names BUDGET (the rejected side) as runner-up
        and drops the margin and stage — a softmax gap against the rejected
        pattern cannot decide anything once a human has. Leaving QUOTA as its
        own runner-up is the exact `invalid_value` the checker reports.
        """
        records = [{"text": "copies must not exceed", "chosen_pattern_id": "QUOTA_CAPACITY_GUARD"}]
        patched = decisions.apply_decisions([dict(GUARD_TIE)], records)
        self.assertEqual(patched[0]["runner_up_pattern_id"], "BUDGET_OVERFLOW_GUARD")
        self.assertEqual(patched[0]["runner_up_confidence"], 0.376)
        self.assertIsNone(patched[0]["margin"])
        self.assertIsNone(patched[0]["undecided_stage"])

    def test_keeping_the_recorded_winner_leaves_the_verdict_alone(self):
        records = [{"text": "copies must not exceed", "chosen_pattern_id": "BUDGET_OVERFLOW_GUARD"}]
        patched = decisions.apply_decisions([dict(GUARD_TIE)], records)
        self.assertEqual(patched[0]["pattern_id"], "BUDGET_OVERFLOW_GUARD")
        self.assertEqual(patched[0]["runner_up_pattern_id"], "QUOTA_CAPACITY_GUARD")
        self.assertEqual(patched[0]["margin"], 0.0023)
        self.assertIsNone(patched[0]["undecided_stage"])

    def test_reapplication_is_stable(self):
        """A second pass over patched docs changes nothing (same winner)."""
        records = [{"text": "copies must not exceed", "chosen_pattern_id": "QUOTA_CAPACITY_GUARD"}]
        once = decisions.apply_decisions([dict(GUARD_TIE)], records)
        twice = decisions.apply_decisions(once, records)
        self.assertEqual(twice, once)

    def test_other_entries_pass_through_untouched(self):
        records = [{"text": "copies must not exceed", "chosen_pattern_id": "QUOTA_CAPACITY_GUARD"}]
        patched = decisions.apply_decisions([dict(GUARD_TIE), dict(FILTER_TIE)], records)
        self.assertEqual(patched[1], FILTER_TIE)

    def test_empty_and_stale_records_are_the_identity(self):
        self.assertEqual(decisions.apply_decisions([dict(GUARD_TIE)], []), [GUARD_TIE])
        stale = [{"text": "no run produces this any more", "chosen_pattern_id": "X"}]
        self.assertEqual(
            decisions.apply_decisions([dict(GUARD_TIE)], stale), [GUARD_TIE]
        )

    def test_malformed_records_are_ignored(self):
        records = [{"text": "copies must not exceed"}, {"chosen_pattern_id": "X"}, "nope"]
        patched = decisions.apply_decisions([dict(GUARD_TIE)], records)
        self.assertEqual(patched, [GUARD_TIE])


class CollectQuestionsTests(unittest.TestCase):
    def test_only_unresolved_ties_without_answers_are_questions(self):
        decided = dict(GUARD_TIE, decision="decided")
        self.assertEqual(
            collect_questions([GUARD_TIE, FILTER_TIE, decided], set()), [GUARD_TIE]
        )

    def test_a_recorded_answer_removes_the_question(self):
        self.assertEqual(
            collect_questions([GUARD_TIE], {"copies must not exceed"}), []
        )


class AskTests(unittest.TestCase):
    def test_one_keeps_the_recorded_pattern(self):
        self.assertEqual(ask(GUARD_TIE, lambda _: "1"), "BUDGET_OVERFLOW_GUARD")

    def test_two_takes_the_alternative(self):
        self.assertEqual(ask(GUARD_TIE, lambda _: "2"), "QUOTA_CAPACITY_GUARD")

    def test_skip_and_garbage_answer_nothing(self):
        self.assertIsNone(ask(GUARD_TIE, lambda _: "skip"))
        self.assertIsNone(ask(GUARD_TIE, lambda _: "3"))


class DescribeQuestionTests(unittest.TestCase):
    def test_a_corrected_claim_explains_a_zero_confidence(self):
        entry = dict(
            FILTER_TIE,
            confidence=0.0,
            margin=0.0,
            domain_margin=1.0,
            claimed_pattern_id="COUNT_ACTIVE_BY_FK",
            claimed_confidence=0.99999,
            rejection=("COUNT_ACTIVE_BY_FK returns scalar, but this method "
                       "returns collection (List[Loan])"),
        )
        text = "\n".join(describe_question(1, 1, entry))
        self.assertIn("corrected from: COUNT_ACTIVE_BY_FK", text)
        self.assertIn("COUNT_ACTIVE_BY_FK returns scalar", text)
        self.assertIn("confidence is below 0.0001", text)
        self.assertIn("domain margin: 1.0", text)

    def test_an_uncorrected_entry_has_no_correction_lines(self):
        text = "\n".join(describe_question(1, 1, dict(FILTER_TIE)))
        self.assertNotIn("corrected from:", text)
        self.assertNotIn("reason:", text)


class ReviewFlowTests(unittest.TestCase):
    def write_matches(self, directory, entries):
        path = Path(directory) / "pattern_matches.json"
        path.write_text(
            json.dumps({"pattern_matches": entries}, indent=2), encoding="utf-8"
        )
        return path

    def test_scripted_answers_are_recorded_and_patched(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write_matches(directory, [dict(GUARD_TIE), dict(FILTER_TIE)])
            asked, answered = run_review(
                directory, input_fn=lambda _: "2", out_fn=lambda _: None
            )
            self.assertEqual((asked, answered), (1, 1))
            saved = decisions.load_decisions(directory)
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["chosen_pattern_id"], "QUOTA_CAPACITY_GUARD")
            self.assertEqual(
                saved[0]["candidates"],
                ["BUDGET_OVERFLOW_GUARD", "QUOTA_CAPACITY_GUARD"],
            )
            patched = json.loads(
                (Path(directory) / "pattern_matches.json").read_text(encoding="utf-8")
            )["pattern_matches"]
            self.assertEqual(patched[0]["decision"], "decided")
            self.assertEqual(patched[0]["pattern_id"], "QUOTA_CAPACITY_GUARD")

    def test_a_second_run_finds_nothing_open(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write_matches(directory, [dict(GUARD_TIE)])
            run_review(directory, input_fn=lambda _: "1", out_fn=lambda _: None)
            asked, answered = run_review(
                directory, input_fn=lambda _: "1", out_fn=lambda _: None
            )
            self.assertEqual((asked, answered), (0, 0))

    def test_skip_leaves_the_question_open(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write_matches(directory, [dict(GUARD_TIE)])
            asked, answered = run_review(
                directory, input_fn=lambda _: "skip", out_fn=lambda _: None
            )
            self.assertEqual((asked, answered), (1, 0))
            self.assertEqual(decisions.load_decisions(directory), [])


class PromptChangeTests(unittest.TestCase):
    """A decision only applies while its prompt stands.

    Re-asking every run would kill automation for no benefit when nothing
    changed; applying blindly would honor answers given under different
    words. The requirements sha splits the difference: same prompt, silent
    re-application; changed prompt, the tie reopens and is re-asked.
    """

    RECORD = {"text": "t", "chosen_pattern_id": "P",
              "requirements_sha": decisions.requirements_sha("prompt v1")}

    def match(self):
        return {"text": "t", "pattern_id": "Q", "decision": "undecided",
                "undecided_stage": "pattern", "runner_up_pattern_id": "R"}

    def test_a_matching_prompt_applies_silently(self):
        log = Log()
        patched = decisions.apply_decisions(
            [dict(self.match())], [dict(self.RECORD)], log,
            requirements_text="prompt v1")
        self.assertEqual(patched[0]["pattern_id"], "P")
        self.assertFalse([line for line in log.lines if line.startswith("[!]")])

    def test_a_changed_prompt_drops_the_record_with_a_log_line(self):
        log = Log()
        patched = decisions.apply_decisions(
            [dict(self.match())], [dict(self.RECORD)], log,
            requirements_text="prompt v2 rewritten")
        self.assertEqual(patched[0]["pattern_id"], "Q")
        self.assertEqual(patched[0]["decision"], "undecided")
        self.assertTrue(any("predates a prompt change" in line for line in log.lines))

    def test_a_legacy_record_without_a_stamp_keeps_applying(self):
        legacy = {"text": "t", "chosen_pattern_id": "P"}
        patched = decisions.apply_decisions(
            [dict(self.match())], [legacy], Log(),
            requirements_text="anything at all")
        self.assertEqual(patched[0]["pattern_id"], "P")

    def test_without_requirements_text_nothing_is_judged(self):
        patched = decisions.apply_decisions(
            [dict(self.match())], [dict(self.RECORD)], Log())
        self.assertEqual(patched[0]["pattern_id"], "P")

    def test_whitespace_does_not_invalidate(self):
        patched = decisions.apply_decisions(
            [dict(self.match())], [dict(self.RECORD)], Log(),
            requirements_text="  prompt v1\n")
        self.assertEqual(patched[0]["pattern_id"], "P")

    def test_review_stamps_new_records_with_the_prompt_sha(self):
        import tempfile
        from review_ties import run_review
        entry = dict(GUARD_TIE)
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "pattern_matches.json").write_text(
                json.dumps({"pattern_matches": [entry]}), encoding="utf-8")
            Path(directory, "requirements.txt").write_text(
                "the prompt", encoding="utf-8")
            run_review(directory, input_fn=lambda _: "1", out_fn=lambda _: None)
            saved = decisions.load_decisions(directory)
            self.assertEqual(len(saved), 1)
            self.assertEqual(
                saved[0]["requirements_sha"],
                decisions.requirements_sha("the prompt"))


if __name__ == "__main__":
    unittest.main()
