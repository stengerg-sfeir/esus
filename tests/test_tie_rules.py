"""Ties the generator resolves by rule, and ties that need a human.

Each test pins one pair: the five pairs that compile to the same body stay
automatic, with the rule that resolves them, and anything else undecided —
including an undecided entry with a missing side, whose harmlessness cannot
be shown — goes to the user. Decided entries and gaps are never questions.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel import tie_rules  # noqa: E402


def pattern_tie(first, second, **extra):
    entry = {
        "text": "t",
        "pattern_id": first,
        "runner_up_pattern_id": second,
        "confidence": 0.3,
        "margin": 0.05,
        "decision": "undecided",
        "undecided_stage": "pattern",
    }
    entry.update(extra)
    return entry


def domain_tie(first, second):
    return {
        "text": "t",
        "pattern_id": "STANDARD_CRUD",
        "domain": first,
        "domain_runner_up": second,
        "confidence": 0.3,
        "domain_margin": 0.05,
        "decision": "undecided",
        "undecided_stage": "domain",
    }


class EquivalentPairTests(unittest.TestCase):
    def test_crud_against_a_query_is_a_plain_method(self):
        entry = domain_tie("STANDARD_CRUD", "REPO_QUERY")
        self.assertFalse(tie_rules.needs_user(entry))
        self.assertEqual(tie_rules.resolution_rule(entry), "plain-method")

    def test_filter_against_pagination_follows_the_signature(self):
        entry = pattern_tie("FILTER_BY_FIELD", "FILTER_WITH_PAGINATION")
        self.assertFalse(tie_rules.needs_user(entry))
        self.assertEqual(tie_rules.resolution_rule(entry), "signature-pagination")

    def test_either_aggregate_spelling_is_an_fk_check(self):
        entry = pattern_tie("AGGREGATE_BY_FK", "AGGREGATE_BY_FK_AND_DATE")
        self.assertFalse(tie_rules.needs_user(entry))
        self.assertEqual(tie_rules.resolution_rule(entry), "fk-exists")

    def test_either_existence_spelling_is_an_fk_check(self):
        entry = pattern_tie("EXISTS_BY_UNIQUE_COMPOSITE", "AGGREGATE_BY_FK")
        self.assertFalse(tie_rules.needs_user(entry))
        self.assertEqual(tie_rules.resolution_rule(entry), "fk-exists")

    def test_a_read_against_a_threshold_scan_lists_matches(self):
        entry = pattern_tie("READ_ALL", "THRESHOLD_SCAN")
        self.assertFalse(tie_rules.needs_user(entry))
        self.assertEqual(tie_rules.resolution_rule(entry), "list-matching")


class AskTheUserTests(unittest.TestCase):
    def test_two_guards_are_a_question(self):
        entry = pattern_tie("BUDGET_OVERFLOW_GUARD", "QUOTA_CAPACITY_GUARD")
        self.assertTrue(tie_rules.needs_user(entry))
        self.assertIsNone(tie_rules.resolution_rule(entry))

    def test_a_transition_against_a_quota_is_a_question(self):
        entry = pattern_tie("STATE_TRANSITION_GUARD", "QUOTA_CAPACITY_GUARD")
        self.assertTrue(tie_rules.needs_user(entry))

    def test_a_guard_domain_against_plain_is_a_question(self):
        entry = domain_tie("SERVICE_GUARD", "STANDARD_CRUD")
        self.assertTrue(tie_rules.needs_user(entry))

    def test_an_undecided_entry_with_no_other_side_is_a_question(self):
        """Harmlessness cannot be shown without both sides, so it is asked."""
        entry = pattern_tie("FILTER_BY_FIELD", None)
        self.assertTrue(tie_rules.needs_user(entry))

    def test_a_decided_entry_is_never_a_question(self):
        entry = pattern_tie("FILTER_BY_FIELD", "FILTER_WITH_PAGINATION")
        entry["decision"] = "decided"
        self.assertFalse(tie_rules.needs_user(entry))

    def test_a_gap_is_never_a_question(self):
        entry = {
            "text": "t", "pattern_id": "NO_PATTERN_IN_DOMAIN",
            "decision": "undefined",
        }
        self.assertFalse(tie_rules.needs_user(entry))


class AlternativeTests(unittest.TestCase):
    def test_a_pattern_tie_names_its_runner_up(self):
        entry = pattern_tie("BUDGET_OVERFLOW_GUARD", "QUOTA_CAPACITY_GUARD")
        self.assertEqual(
            tie_rules.alternative_of(entry), "QUOTA_CAPACITY_GUARD"
        )

    def test_a_domain_tie_to_a_plain_domain_names_it(self):
        """STANDARD_CRUD is itself a legitimate pattern id: the plain outcome."""
        entry = domain_tie("SERVICE_GUARD", "STANDARD_CRUD")
        self.assertEqual(tie_rules.alternative_of(entry), "STANDARD_CRUD")

    def test_a_domain_tie_to_a_guard_names_nothing(self):
        """The other guard domain was never classified: no pattern to offer."""
        entry = domain_tie("STANDARD_CRUD", "SERVICE_GUARD")
        self.assertIsNone(tie_rules.alternative_of(entry))

    def test_a_decided_entry_has_no_alternative(self):
        entry = pattern_tie("BUDGET_OVERFLOW_GUARD", "QUOTA_CAPACITY_GUARD")
        entry["decision"] = "decided"
        self.assertIsNone(tie_rules.alternative_of(entry))


if __name__ == "__main__":
    unittest.main()
