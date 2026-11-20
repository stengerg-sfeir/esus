"""A parent-plus-children lookup is emitted from the model FK graph."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import generator  # noqa: E402


class RelatedCollectionTests(unittest.TestCase):
    def ctx(self):
        return {
            "mappings": {},
            "entity_names": ["Project", "Task"],
            "models": [
                {"name": "Project", "fields": [
                    {"name": "project_id", "primary_key": True},
                    {"name": "title"}]},
                {"name": "Task", "fields": [
                    {"name": "task_id", "primary_key": True},
                    {"name": "project_id", "foreign_key": {
                        "target_entity": "Project", "target_field": "project_id"}},
                    {"name": "title"}]},
            ],
            "errors": [{"name": "ProjectNotFoundError"}],
        }

    def test_parent_and_children_are_loaded(self):
        body = generator._repo_related_collection_body(
            self.ctx(), "Project", "models.Project",
            {"name": "get_project_with_tasks",
             "params": [{"name": "project_id", "type": "int"}],
             "return_type": "tuple[models.Project, list[models.Task]]"})
        self.assertIsNotNone(body)
        text = "\n".join(body)
        self.assertIn("self._store.get", text)
        self.assertIn("'project_id', 'eq'", text)
        self.assertIn("models.Task", text)

    def test_a_non_list_return_is_not_this_shape(self):
        self.assertIsNone(generator._repo_related_collection_body(
            self.ctx(), "Project", "models.Project",
            {"name": "get_project", "params": [{"name": "project_id"}],
             "return_type": "models.Project"}))


if __name__ == "__main__":
    unittest.main()
