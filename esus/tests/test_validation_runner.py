"""The validation runner's parsing and classification, pinned."""

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "esus_validation_runner", ROOT / "scripts" / "run_validation.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


DIRECT = """==== SUMMARY ====
review: none — the documents are unreviewed
blockers: 0, open tie(s): 0
GENERATABLE: YES (UNREVIEWED) — `generator.py` can run
"""

REVIEW = """==== SUMMARY ====
review: none — the documents are unreviewed
blockers: 1, open tie(s): 0
GENERATABLE: NO — `generator.py` will refuse this output
  - [open_human_review] 2 unanswered method contracts; run the attended review
"""

TIE = """==== SUMMARY ====
review: none — the documents are unreviewed
blockers: 0, open tie(s): 1
GENERATABLE: NO — `generator.py` will refuse this output
  - 1 tie(s) still need a human answer (`review_ties.py`)
"""

HARD = """==== SUMMARY ====
review: none — the documents are unreviewed
blockers: 1, open tie(s): 0
GENERATABLE: NO — `generator.py` will refuse this output
  - [missing_command] the requirements name `report` but no command implements it
"""


class SummaryTests(unittest.TestCase):
    def test_direct_summary_is_parsed(self):
        summary = runner.parse_summary(DIRECT)
        self.assertEqual((summary["generatable"], summary["blockers"],
                          summary["open_ties"]), (True, 0, 0))
        self.assertEqual(runner.classify(summary, 0, False), "direct")

    def test_reviewable_blocker_is_review(self):
        summary = runner.parse_summary(REVIEW)
        self.assertEqual(summary["rules"][0]["rule"], "open_human_review")
        self.assertEqual(runner.classify(summary, 0, False), "review")

    def test_open_ties_alone_are_review(self):
        summary = runner.parse_summary(TIE)
        self.assertEqual(runner.classify(summary, 0, False), "review")

    def test_hard_blocker_is_not_generatable(self):
        summary = runner.parse_summary(HARD)
        self.assertEqual(runner.classify(summary, 0, False), "not_generatable")

    def test_crash_or_timeout_is_not_generatable(self):
        self.assertEqual(runner.classify(None, 1, False), "not_generatable")
        self.assertEqual(runner.classify(None, 0, True), "not_generatable")


class TokenTests(unittest.TestCase):
    def test_token_lines_sum_output_prompt_and_decode_time(self):
        text = (
            "[intentions] 100 tokens in 2.0s (50.0 tok/s, 20.0 decode, 300 prompt)\n"
            "[data_models] 50 tokens in 1.0s (50.0 tok/s, 10.0 decode, 200 prompt)\n"
        )
        parsed = runner.parse_tokens(text)
        self.assertEqual(parsed["calls"], 2)
        self.assertEqual(parsed["tokens_out"], 150)
        self.assertEqual(parsed["tokens_prompt"], 500)
        self.assertEqual(parsed["decode_seconds"], 10.0)


if __name__ == "__main__":
    unittest.main()
