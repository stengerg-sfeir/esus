"""Oracle findings are grouped by cause, not by project order."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import summarize_oracle  # noqa: E402


class OracleSummaryTests(unittest.TestCase):
    def report(self):
        return {"results": [{"prompt": "prompt_x", "results": [
            {"case": "a", "status": "passed"},
            {"case": "b", "status": "failed",
             "reason": "raised CustomerNotFoundError: missing"},
            {"case": "c", "status": "failed",
             "reason": "expected InvalidAgeError, no error was raised"},
            {"case": "d", "status": "unbound",
             "reason": "no generated method matches 'sell_product'"},
            {"case": "e", "status": "unbound",
             "reason": "ambiguous action binding: A.x, B.x"},
        ]}]}

    def test_categories_are_separated(self):
        counts, groups = summarize_oracle.summarize(self.report())
        self.assertEqual(counts["passed"], 1)
        self.assertEqual(counts["case_defect: setup"], 1)
        self.assertEqual(counts["behavior: expected error missing"], 1)
        self.assertEqual(counts["coverage_gap: missing action"], 1)
        self.assertEqual(counts["coverage_gap: ambiguous action"], 1)

    def test_an_undeclared_expected_field_is_under_specified(self):
        self.assertEqual(
            summarize_oracle.category({
                "status": "unbound",
                "reason": "expected state field 'product.quantity' is not declared",
            }),
            "under_specified")

    def test_an_undeclared_field_named_by_the_prompt_is_a_schema_gap(self):
        self.assertEqual(
            summarize_oracle.category({
                "status": "unbound",
                "reason": "expected state field 'product.quantity' is not declared",
                "source": "The product quantity must be updated.",
            }),
            "coverage_gap: schema")

    def test_a_soft_delete_case_that_cannot_read_the_row_is_a_behavior_finding(self):
        self.assertEqual(
            summarize_oracle.category({
                "status": "failed",
                "reason": "cannot read Project: 'not found'",
                "source": ("Deleting a project must be implemented as a soft "
                           "delete: the project remains in the database"),
            }),
            "behavior: soft delete")

    def test_incomplete_case_payloads_are_classified(self):
        cases = (
            ("update case supplies no new value for 'user.role'",
             "case_defect: setup"),
            ("create case supplies no value for required field Order.order_date",
             "under_specified"),
            ("case passes parameter name 'query' as a literal value",
             "case_defect: setup"),
            ("list case expects fewer rows than its setup but performs no delete",
             "case_defect: setup"),
        )
        for reason, expected in cases:
            with self.subTest(reason=reason):
                self.assertEqual(
                    summarize_oracle.category({
                        "status": "unbound", "reason": reason}),
                    expected)

    def test_type_and_auto_id_mismatches_are_case_defects(self):
        for reason in (
                "note.creation_date is datetime.datetime(2023, 10, 1), expected '2023-10-01'",
                "note.id is 3, expected 1",
                "setup Product raised IntegrityError: datatype mismatch"):
            with self.subTest(reason=reason):
                self.assertEqual(
                    summarize_oracle.category({"status": "failed", "reason": reason}),
                    "case_defect: setup")

    def test_missing_primary_key_is_a_case_defect(self):
        self.assertEqual(
            summarize_oracle.category({
                "status": "unbound",
                "reason": "update/delete case supplies no primary-key argument",
            }),
            "case_defect: setup")

    def test_markdown_names_each_finding(self):
        text = summarize_oracle.markdown(self.report())
        self.assertIn("prompt_x", text)
        self.assertIn("case_defect: setup", text)
        self.assertIn("sell_product", text)


if __name__ == "__main__":
    unittest.main()
