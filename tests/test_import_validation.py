"""Imported collection validation is derived from the model's required fields."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import generator  # noqa: E402


class ImportValidationTests(unittest.TestCase):
    def ctx(self):
        return {
            "mappings": {}, "entity_names": ["Task"],
            "models": [{"name": "Task", "fields": [
                {"name": "id", "primary_key": True, "nullable": False},
                {"name": "title", "nullable": False},
                {"name": "status", "nullable": False},
                {"name": "priority", "nullable": False},
                {"name": "created_at", "type": "datetime", "nullable": False}]}],
            "services": [], "repositories": [], "errors": [],
        }

    def test_required_fields_produce_validation_errors(self):
        body = generator._service_validate_collection_body(
            self.ctx(), "TaskService",
            {"name": "validate_imported_tasks", "description": "Validate imports",
             "return_type": "list[str]"}, [("tasks_data", "tasks_data", "list")],
            "list[str]")
        self.assertIsNotNone(body)
        text = "\n".join(body)
        self.assertIn("Task.title is required", text)
        self.assertIn("Task.status is required", text)
        self.assertNotIn("Task.created_at is required", text)

    def test_a_non_list_return_is_not_this_shape(self):
        self.assertIsNone(generator._service_validate_collection_body(
            self.ctx(), "TaskService",
            {"name": "validate_imported_tasks", "return_type": "bool"},
            [("tasks_data", "tasks_data", "list")], "bool"))


if __name__ == "__main__":
    unittest.main()
