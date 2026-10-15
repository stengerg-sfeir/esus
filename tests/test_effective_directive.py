"""The generator's contract with the classifier: one import, no reimplementation.

`effective_directive` is the only thing the code generator calls per match.
Decided matches implement their pattern; ruled ties implement the rule (both
sides compile to the same body, pinned by the generator's swap tests); gaps
carry their context for the LLM; open ties escalate instead of guessing.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel import tie_rules  # noqa: E402


def decided(pattern_id="FILTER_BY_FIELD"):
    return {
        "text": "t", "source": "contract:S.m", "pattern_id": pattern_id,
        "confidence": 0.9, "decision": "decided",
    }


class EffectiveDirectiveTests(unittest.TestCase):
    def test_a_decided_match_implements_its_pattern(self):
        self.assertEqual(
            tie_rules.effective_directive(decided("READ_ALL")), ("pattern", "READ_ALL")
        )

    def test_plan_method_stubs_a_decided_aggregate(self):
        """Aggregates read real data but have no mechanical body: stub, not fake."""
        from kernel import codegen
        method = {"name": "get_monthly_spending",
                  "params": [{"name": "month", "type": "str"}],
                  "return_type": "int", "raises": []}
        strategy, detail = codegen.plan_method(method, decided("AGGREGATE_BY_FK_AND_DATE"))
        self.assertEqual(strategy, "stub")
        self.assertIn("AGGREGATE_BY_FK_AND_DATE", detail)

    def test_a_human_decision_implements_the_chosen_pattern(self):
        entry = decided("QUOTA_CAPACITY_GUARD")
        entry["decided_by"] = "user"
        self.assertEqual(
            tie_rules.effective_directive(entry), ("pattern", "QUOTA_CAPACITY_GUARD")
        )

    def test_a_ruled_tie_implements_the_rule_not_the_winner(self):
        """Swapping winner and runner-up must not change this directive."""
        forward = {
            "text": "t", "pattern_id": "FILTER_BY_FIELD",
            "runner_up_pattern_id": "FILTER_WITH_PAGINATION",
            "confidence": 0.3, "margin": 0.05,
            "decision": "undecided", "undecided_stage": "pattern",
        }
        swapped = dict(forward, pattern_id="FILTER_WITH_PAGINATION",
                       runner_up_pattern_id="FILTER_BY_FIELD")
        self.assertEqual(
            tie_rules.effective_directive(forward), ("rule", "signature-pagination")
        )
        self.assertEqual(
            tie_rules.effective_directive(swapped), ("rule", "signature-pagination")
        )

    def test_a_gap_carries_its_context_for_the_llm(self):
        entry = {
            "text": "export it", "source": "contract:S.export_to_csv",
            "pattern_id": "NO_PATTERN_IN_DOMAIN", "decision": "undefined",
            "claimed_pattern_id": "FILTER_WITH_PAGINATION",
            "rejection": "returns collection, but this method returns none",
        }
        kind, payload = tie_rules.effective_directive(entry)
        self.assertEqual(kind, "llm-gap")
        self.assertEqual(payload["claimed_pattern_id"], "FILTER_WITH_PAGINATION")
        self.assertIn("returns none", payload["rejection"])

    def test_an_open_tie_escalates_with_both_candidates(self):
        """A skipped review is a refusal to generate, never a silent guess."""
        entry = {
            "text": "t", "pattern_id": "BUDGET_OVERFLOW_GUARD",
            "runner_up_pattern_id": "QUOTA_CAPACITY_GUARD",
            "confidence": 0.3, "margin": 0.05,
            "decision": "undecided", "undecided_stage": "pattern",
        }
        kind, payload = tie_rules.effective_directive(entry)
        self.assertEqual(kind, "llm-tie")
        self.assertEqual(
            payload["candidates"], ["BUDGET_OVERFLOW_GUARD", "QUOTA_CAPACITY_GUARD"]
        )


if __name__ == "__main__":
    unittest.main()
