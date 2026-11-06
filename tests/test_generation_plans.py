"""Extraction-side generation plans keep semantic choices out of the generator.

An ordinary service aggregate has a unique entity, date field, numeric target
and aggregate function; it becomes a plan. A report or a service CRUD method
with custom errors becomes a question instead of a guessed plan.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.extraction import generation_plans  # noqa: E402


def _documents():
    return {
        "data_models": [{
            "name": "Expense",
            "fields": [
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "amount_cents", "type": "int"},
                {"name": "expense_date", "type": "date"},
                {"name": "category_id", "type": "int",
                 "foreign_key": {"target_entity": "Category"}},
            ],
        }],
        "persistence_ports": {"repositories": [{
            "entity": "Expense",
            "interface_name": "ExpenseRepository",
            "methods": [{"name": "read_all", "params": [], "return_type": "list[Expense]"}],
        }]},
        "service_contracts": [{
            "service_name": "ExpenseService",
            "methods": [
                {"name": "get_category_spending",
                 "params": [
                     {"name": "category_id", "type": "int"},
                     {"name": "start_date", "type": "str"},
                     {"name": "end_date", "type": "str"},
                 ],
                 "return_type": "dict[str, any]"},
                {"name": "get_monthly_report",
                 "params": [{"name": "month", "type": "str"}],
                 "return_type": "dict[str, any]"},
            ],
        }],
        "pattern_matches": [
            {"source": "contract:ExpenseService.get_category_spending",
             "pattern_id": "AGGREGATE_BY_FK_AND_DATE"},
            {"source": "contract:ExpenseService.get_monthly_report",
             "pattern_id": "AGGREGATE_BY_FK_AND_DATE"},
        ],
    }


class GenerationPlanTests(unittest.TestCase):
    def test_a_unique_service_aggregate_becomes_a_plan(self):
        plan = generation_plans.build(_documents())
        self.assertEqual(len(plan["plans"]), 1)
        self.assertEqual(plan["plans"][0]["method"], "get_category_spending")
        self.assertEqual(plan["plans"][0]["slots"]["target_field"],
                         "amount_cents")

    def test_a_report_is_a_question_not_a_mechanical_plan(self):
        plan = generation_plans.build(_documents())
        self.assertEqual(
            [q["method"] for q in plan["questions"]],
            ["get_monthly_report"],
        )


if __name__ == "__main__":
    unittest.main()
