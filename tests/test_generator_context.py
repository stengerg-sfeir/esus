"""Gap context is assembled from the same evidence every time.

Each test pins one section of the bundle — the method with its contract
facts, the entities it is about, the intentions, the constraining rules, the
refused claim, the decided neighbours — and pins the silences too: an
unresolvable source or a missing document thins the bundle rather than
raising, because the generator must still decide.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel import generator_context  # noqa: E402


def documents():
    return {
        "service_contracts": [
            {
                "service_name": "ExpenseRepository",
                "methods": [
                    {
                        "name": "export_expenses_to_csv",
                        "description": "Exports filtered expenses to a CSV file.",
                        "params": [
                            {"name": "file_path", "type": "str"},
                            {"name": "category_id", "type": "Optional[int]"},
                        ],
                        "return_type": "None",
                        "raises": [],
                    },
                    {
                        "name": "list_expenses",
                        "description": "Lists all expenses.",
                        "params": [],
                        "return_type": "List[Expense]",
                        "raises": [],
                    },
                ],
            }
        ],
        "data_models": [
            {
                "name": "Expense",
                "fields": [
                    {"name": "id", "type": "int"},
                    {"name": "amount_cents", "type": "int"},
                ],
            },
            {
                "name": "Category",
                "fields": [{"name": "id", "type": "int"}],
            },
        ],
        "intentions": ["Track spending across categories"],
        "invariants": [
            {"text": "Expense.category_id must reference an existing Category", "kind": "schema"},
            {"text": "Monthly spending must not exceed the budget", "kind": "rule"},
            {"text": "An expense cannot be deleted after export", "kind": "rule"},
        ],
        "pattern_matches": [
            {
                "source": "contract:ExpenseRepository.list_expenses",
                "text": "list_expenses() -> List[Expense]",
                "pattern_id": "FILTER_BY_FIELD",
                "decision": "decided",
            },
            {
                "source": "contract:ExpenseRepository.export_expenses_to_csv",
                "text": "export it",
                "pattern_id": "NO_PATTERN_IN_DOMAIN",
                "decision": "undefined",
            },
        ],
    }


def gap_entry():
    return {
        "source": "contract:ExpenseRepository.export_expenses_to_csv",
        "text": "export_expenses_to_csv(file_path: str, ...) -> None: Exports filtered expenses to a CSV file.",
        "pattern_id": "NO_PATTERN_IN_DOMAIN",
        "decision": "undefined",
        "claimed_pattern_id": "FILTER_WITH_PAGINATION",
        "rejection": "FILTER_WITH_PAGINATION returns collection, but this method returns none (None)",
    }


class BuildContextTests(unittest.TestCase):
    def test_the_method_carries_its_contract_facts(self):
        bundle = generator_context.build_gap_context(documents(), gap_entry())
        self.assertEqual(bundle["method"]["return_type"], "None")
        self.assertEqual(
            [p["name"] for p in bundle["method"]["params"]],
            ["file_path", "category_id"],
        )

    def test_the_method_lends_its_entity_but_not_the_rest(self):
        """`export_expenses_to_csv` names Expense; Category stays out."""
        bundle = generator_context.build_gap_context(documents(), gap_entry())
        self.assertEqual(
            [entity["name"] for entity in bundle["entities"]], ["Expense"]
        )

    def test_only_rules_about_its_entities_travel(self):
        """Schema restatements live in the models; unrelated rules constrain nothing."""
        bundle = generator_context.build_gap_context(documents(), gap_entry())
        self.assertEqual(
            bundle["invariants"], ["An expense cannot be deleted after export"]
        )

    def test_the_refused_claim_travels_with_its_reason(self):
        bundle = generator_context.build_gap_context(documents(), gap_entry())
        self.assertEqual(bundle["claimed"]["pattern_id"], "FILTER_WITH_PAGINATION")
        self.assertIn("returns none", bundle["claimed"]["rejection"])

    def test_decided_neighbours_show_the_service_conventions(self):
        bundle = generator_context.build_gap_context(documents(), gap_entry())
        self.assertEqual(
            bundle["neighbours"],
            [("list_expenses() -> List[Expense]", "FILTER_BY_FIELD")],
        )

    def test_an_unresolvable_source_thins_but_never_raises(self):
        entry = dict(gap_entry(), source="invariant")
        bundle = generator_context.build_gap_context(documents(), entry)
        self.assertEqual(bundle["method"]["params"], [])
        self.assertEqual(bundle["entities"], [])

    def test_missing_documents_thin_but_never_raise(self):
        bundle = generator_context.build_gap_context({}, gap_entry())
        self.assertEqual(bundle["intentions"], [])
        self.assertEqual(bundle["neighbours"], [])
        rendered = generator_context.render_gap_context(bundle)
        self.assertIn("Exports filtered expenses", rendered)


class RenderTests(unittest.TestCase):
    def test_the_rendered_section_states_the_decision_evidence(self):
        rendered = generator_context.render_gap_context(
            generator_context.build_gap_context(documents(), gap_entry())
        )
        self.assertIn("export_expenses_to_csv", rendered)
        self.assertIn("Entity Expense: id, amount_cents", rendered)
        self.assertIn("Track spending across categories", rendered)
        self.assertIn("Refused pattern FILTER_WITH_PAGINATION", rendered)
        self.assertIn("list_expenses() -> List[Expense] -> FILTER_BY_FIELD", rendered)


if __name__ == "__main__":
    unittest.main()
