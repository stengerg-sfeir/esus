"""The shape rule: an attribution that cannot be right is refused, not kept.

Why this exists: the classifier never chooses "none of these" (measured at 0.000
on 30 of 34 expenses methods), so a requirement no pattern fits arrives as the
*nearest* pattern instead — an aggregate claimed for a method returning
`List[Expense]`, a guard claimed for one returning an entity. The catch-all is
therefore decided from the item's own return type, outside the model, and these
tests pin the two halves that matter: the provable refusals fire, and nothing
else does.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel import pattern_shapes  # noqa: E402


class ReturnShapeTests(unittest.TestCase):
    def test_collections(self):
        for return_type in ("List[Expense]", "list[Expense]", "Set[int]", "Sequence[Book]"):
            self.assertEqual(pattern_shapes.return_shape(return_type), pattern_shapes.COLLECTION)

    def test_an_optional_collection_is_still_a_collection(self):
        self.assertEqual(
            pattern_shapes.return_shape("Optional[List[Loan]]"),
            pattern_shapes.COLLECTION,
        )
        self.assertEqual(
            pattern_shapes.return_shape("Union[List[Loan], None]"),
            pattern_shapes.COLLECTION,
        )

    def test_mappings_and_scalars_and_booleans(self):
        self.assertEqual(pattern_shapes.return_shape("dict"), pattern_shapes.MAPPING)
        self.assertEqual(pattern_shapes.return_shape("Dict[int, int]"), pattern_shapes.MAPPING)
        self.assertEqual(pattern_shapes.return_shape("int"), pattern_shapes.SCALAR)
        self.assertEqual(pattern_shapes.return_shape("Optional[float]"), pattern_shapes.SCALAR)
        self.assertEqual(pattern_shapes.return_shape("bool"), pattern_shapes.BOOLEAN)
        self.assertEqual(pattern_shapes.return_shape("None"), pattern_shapes.NONE)

    def test_an_entity_is_its_own_shape(self):
        for return_type in ("Expense", "Budget", "Wine", "Member"):
            self.assertEqual(pattern_shapes.return_shape(return_type), pattern_shapes.ENTITY)

    def test_the_outer_type_decides(self):
        """`List[Dict[...]]` is a collection; `Dict[int, List[...]]` is a mapping."""
        self.assertEqual(
            pattern_shapes.return_shape("List[Dict[str, int]]"), pattern_shapes.COLLECTION
        )
        self.assertEqual(
            pattern_shapes.return_shape("Dict[int, List[int]]"), pattern_shapes.MAPPING
        )

    def test_an_empty_type_is_unjudgeable(self):
        self.assertIsNone(pattern_shapes.return_shape(""))
        self.assertIsNone(pattern_shapes.return_shape(None))


class RejectionTests(unittest.TestCase):
    def test_an_aggregate_cannot_return_records(self):
        reason = pattern_shapes.rejection_reason("AGGREGATE_BY_FK_AND_DATE", "List[Expense]")
        self.assertIsNotNone(reason)
        self.assertIn("collection", reason)

    def test_an_aggregate_can_return_a_scalar(self):
        self.assertIsNone(
            pattern_shapes.rejection_reason("AGGREGATE_BY_FK_AND_DATE", "int")
        )

    def test_an_aggregate_can_return_a_report_mapping(self):
        self.assertIsNone(
            pattern_shapes.rejection_reason("AGGREGATE_BY_FK_AND_DATE", "dict")
        )

    def test_a_guard_cannot_return_an_entity(self):
        reason = pattern_shapes.rejection_reason("BUDGET_OVERFLOW_GUARD", "Expense")
        self.assertIsNotNone(reason)
        self.assertIn("boolean", reason)

    def test_a_guard_can_return_a_verdict(self):
        self.assertIsNone(pattern_shapes.rejection_reason("BUDGET_OVERFLOW_GUARD", "bool"))

    def test_a_filter_cannot_return_a_boolean(self):
        self.assertIsNotNone(
            pattern_shapes.rejection_reason("FILTER_WITH_PAGINATION", "bool")
        )

    def test_a_read_all_cannot_return_a_single_entity(self):
        """The gui case: `get_wine_by_name` claimed READ_ALL and returns a Wine."""
        self.assertIsNotNone(pattern_shapes.rejection_reason("READ_ALL", "Wine"))

    def test_a_read_all_can_return_records(self):
        self.assertIsNone(pattern_shapes.rejection_reason("READ_ALL", "List[Wine]"))

    def test_a_count_returns_a_scalar(self):
        self.assertIsNone(pattern_shapes.rejection_reason("COUNT_ACTIVE_BY_FK", "int"))
        self.assertIsNotNone(
            pattern_shapes.rejection_reason("COUNT_ACTIVE_BY_FK", "List[Loan]")
        )

    def test_sentinels_are_never_judged(self):
        """STANDARD_CRUD and the gaps are answers, not patterns with a shape."""
        self.assertIsNone(pattern_shapes.rejection_reason("STANDARD_CRUD", "Expense"))
        self.assertIsNone(pattern_shapes.rejection_reason("NO_PATTERN_IN_DOMAIN", "Expense"))

    def test_an_unreadable_type_is_never_rejected(self):
        """The check must not refuse a claim because it could not read the type."""
        self.assertIsNone(pattern_shapes.rejection_reason("READ_ALL", ""))
        self.assertIsNone(pattern_shapes.rejection_reason("READ_ALL", None))

    def test_the_declared_shapes_cover_both_catalogues(self):
        declared = pattern_shapes.declared_shapes()
        for pattern_id in (
            "READ_ALL",
            "FILTER_BY_FIELD",
            "AGGREGATE_BY_FK",
            "COUNT_ACTIVE_BY_FK",
            "EXISTS_BY_UNIQUE_COMPOSITE",
            "THRESHOLD_SCAN",
            "BUDGET_OVERFLOW_GUARD",
            "STATE_TRANSITION_GUARD",
        ):
            self.assertIn(pattern_id, declared, f"{pattern_id} declares no return shape")


class AttributionTests(unittest.TestCase):
    """What is recorded when the model's claim cannot be right.

    The refusal is about the claim, not the domain: when a shape-compatible
    candidate exists it is the answer, and only when none exists is the item a
    gap. These pin both outcomes, because the difference is the whole value of
    the mechanism — a corrected read versus a missing kernel feature.
    """

    def attribute(self, claimed, step2_probabilities, return_type):
        from kernel.extraction.classification import _attribute

        result = {
            "pattern_id": claimed,
            "step2_probabilities": step2_probabilities,
            "step1_probabilities": {"REPO_QUERY": 1.0},
            "domain": "REPO_QUERY",
        }
        return _attribute(result, return_type)

    def test_an_impossible_claim_is_replaced_by_the_next_possible_one(self):
        """The expenses case: an aggregate claimed, a filter possible."""
        pattern_id, claimed, rejection = self.attribute(
            "AGGREGATE_BY_FK",
            {"AGGREGATE_BY_FK": 0.58, "FILTER_BY_FIELD": 0.39, "READ_ALL": 0.03},
            "List[Expense]",
        )
        self.assertEqual(pattern_id, "FILTER_BY_FIELD")
        self.assertEqual(claimed, "AGGREGATE_BY_FK")
        self.assertIsNotNone(rejection)

    def test_no_possible_candidate_becomes_a_gap(self):
        """A method returning a single record by composite key has no pattern."""
        pattern_id, claimed, rejection = self.attribute(
            "AGGREGATE_BY_FK_AND_DATE",
            {"AGGREGATE_BY_FK_AND_DATE": 0.74, "AGGREGATE_BY_FK": 0.20},
            "Budget",
        )
        self.assertEqual(pattern_id, "NO_PATTERN_IN_DOMAIN")
        self.assertEqual(claimed, "AGGREGATE_BY_FK_AND_DATE")
        self.assertIsNotNone(rejection)

    def test_a_candidate_from_another_return_family_is_not_used(self):
        """The export case: a boolean-shaped pattern must not rescue a `bool`.

        `export_to_csv(...) -> bool` claimed `FILTER_WITH_PAGINATION` (a
        collection — impossible) and was first "corrected" to
        `EXISTS_BY_UNIQUE_COMPOSITE`, which is also boolean and therefore
        shape-valid and plainly wrong. Correcting into a different return family
        is a guess, so the item is a gap: the catalogue has no pattern for an
        export.
        """
        pattern_id, claimed, rejection = self.attribute(
            "FILTER_WITH_PAGINATION",
            {
                "FILTER_WITH_PAGINATION": 0.34,
                "EXISTS_BY_UNIQUE_COMPOSITE": 0.21,
                "AGGREGATE_BY_FK": 0.18,
            },
            "bool",
        )
        self.assertEqual(pattern_id, "NO_PATTERN_IN_DOMAIN")
        self.assertEqual(claimed, "FILTER_WITH_PAGINATION")
        self.assertIsNotNone(rejection)

    def test_a_possible_claim_is_recorded_untouched(self):
        pattern_id, claimed, rejection = self.attribute(
            "AGGREGATE_BY_FK_AND_DATE",
            {"AGGREGATE_BY_FK_AND_DATE": 0.95, "AGGREGATE_BY_FK": 0.04},
            "int",
        )
        self.assertEqual(pattern_id, "AGGREGATE_BY_FK_AND_DATE")
        self.assertEqual(claimed, "AGGREGATE_BY_FK_AND_DATE")
        self.assertIsNone(rejection)

    def test_an_unreadable_signature_leaves_the_claim_alone(self):
        pattern_id, _, rejection = self.attribute(
            "READ_ALL", {"READ_ALL": 0.9, "FILTER_BY_FIELD": 0.1}, None
        )
        self.assertEqual(pattern_id, "READ_ALL")
        self.assertIsNone(rejection)

    def test_a_short_circuited_answer_is_untouched(self):
        pattern_id, claimed, rejection = self.attribute(
            "STANDARD_CRUD", {}, "Expense"
        )
        self.assertEqual(pattern_id, "STANDARD_CRUD")
        self.assertIsNone(rejection)


class CorrectedClaimNoteTests(unittest.TestCase):
    def report_for(self, entry):
        from kernel.consistency import checks_patterns
        from kernel.consistency.report import Report

        report = Report("test")
        checks_patterns._check_claim(entry, report)
        return report

    def test_a_corrected_claim_is_reported(self):
        report = self.report_for(
            {
                "pattern_id": "FILTER_BY_FIELD",
                "claimed_pattern_id": "AGGREGATE_BY_FK",
                "rejection": "AGGREGATE_BY_FK returns mapping/scalar, but this method returns collection",
                "text": "find_expenses_by_category(category_id: int) -> List[Expense]",
            }
        )
        self.assertEqual(len(report.notes), 1)
        self.assertEqual(report.notes[0].rule, "corrected_claim")
        self.assertIn("FILTER_BY_FIELD", report.notes[0].message)

    def test_a_gap_is_not_reported_twice(self):
        """`_report_gaps` owns the gap; the claim note must not repeat it."""
        report = self.report_for(
            {
                "pattern_id": "NO_PATTERN_IN_DOMAIN",
                "claimed_pattern_id": "AGGREGATE_BY_FK",
                "rejection": "AGGREGATE_BY_FK returns mapping/scalar, but this method returns entity",
                "text": "read_budget_by_category_month(category_id: int, month: str) -> Budget",
            }
        )
        self.assertEqual(report.notes, [])

    def test_an_untouched_match_is_silent(self):
        report = self.report_for(
            {"pattern_id": "READ_ALL", "claimed_pattern_id": "READ_ALL", "rejection": None}
        )
        self.assertEqual(report.notes, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
