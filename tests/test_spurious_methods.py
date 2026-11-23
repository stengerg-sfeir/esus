"""Ungrounded methods are removed before adapters and surface generation."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kernel.extraction import repairs  # noqa: E402


class SpuriousMethodTests(unittest.TestCase):
    def docs(self):
        return {
            "data_models": [
                {"name": "Task", "fields": [
                    {"name": "task_id", "primary_key": True},
                    {"name": "title"}]},
                {"name": "Project", "fields": [
                    {"name": "project_id", "primary_key": True},
                    {"name": "title"}]},
            ],
            "service_contracts": [
                {"service_name": "TaskService", "methods": [
                    {"name": "create_task", "params": []},
                    {"name": "confirm_order", "params": []},
                ]},
                {"service_name": "ProjectRepository", "methods": [
                    {"name": "get_projects_by_status",
                     "params": [{"name": "status", "type": "str"}]},
                ]},
            ],
            "persistence_ports": {"repositories": []},
            "interaction_adapters": [
                {"target_service": "TaskService",
                 "target_method": "confirm_order"},
                {"target_service": "TaskService",
                 "target_method": "create_task"},
            ],
            "pattern_matches": [
                {"source": "contract:TaskService.confirm_order"},
                {"source": "contract:TaskService.create_task"},
            ],
        }

    def test_ungrounded_methods_are_dropped_and_grounded_ones_kept(self):
        docs = self.docs()
        drops = repairs.repair_ungrounded_methods(
            docs, "A task application. Users create tasks.", ["create tasks"])
        methods = {m["name"] for m in docs["service_contracts"][0]["methods"]}
        self.assertIn("create_task", methods)
        self.assertNotIn("confirm_order", methods)
        # The project status filter is dropped because Project has no status.
        self.assertFalse(any(
            method.get("name") == "get_projects_by_status"
            for service in docs["service_contracts"]
            for method in service.get("methods") or []))
        self.assertTrue(any(method == "confirm_order" for _h, method, _r in drops))
        self.assertEqual(
            [a["target_method"] for a in docs["interaction_adapters"]],
            ["create_task"])
        self.assertEqual(
            [m["source"] for m in docs["pattern_matches"]],
            ["contract:TaskService.create_task"])

    def test_a_payload_parameter_is_not_a_missing_model_field(self):
        docs = {
            "data_models": [{"name": "Task", "fields": [
                {"name": "task_id", "primary_key": True},
                {"name": "title"}]}],
            "service_contracts": [{"service_name": "TaskService", "methods": [{
                "name": "validate_imported_tasks",
                "params": [{"name": "tasks_data", "type": "list"}]}]}],
            "persistence_ports": {"repositories": []},
            "interaction_adapters": [],
            "pattern_matches": [],
        }
        repairs.repair_ungrounded_methods(
            docs, "A task application. Import tasks and validate the input.")
        self.assertEqual(len(docs["service_contracts"][0]["methods"]), 1)

    def test_a_dimension_absent_from_prompt_and_model_is_dropped(self):
        docs = {
            "data_models": [{"name": "Customer", "fields": [
                {"name": "customer_id", "primary_key": True},
                {"name": "name"}]}],
            "service_contracts": [{"service_name": "CustomerRepository",
                                   "methods": [{
                "name": "get_customer_count_by_region", "params": []}]}],
            "persistence_ports": {"repositories": []},
            "interaction_adapters": [],
            "pattern_matches": [],
        }
        repairs.repair_ungrounded_methods(
            docs, "A shop application. Keep track of customers.")
        self.assertFalse(docs["service_contracts"])

    def test_an_undeclared_return_dto_is_dropped(self):
        docs = {
            "data_models": [{"name": "Order", "fields": [
                {"name": "order_id", "primary_key": True}]}],
            "service_contracts": [{"service_name": "OrderRepository",
                                   "methods": [{
                "name": "get_orders_with_customer_name",
                "params": [{"name": "customer_id"}],
                "return_type": "List[OrderWithCustomerName]"}]}],
            "persistence_ports": {"repositories": []},
            "interaction_adapters": [],
            "pattern_matches": [],
        }
        repairs.repair_ungrounded_methods(
            docs, "A customer and order application.")
        self.assertFalse(docs["service_contracts"])

    def test_a_repository_import_twin_is_dropped(self):
        docs = {
            "data_models": [{"name": "Task", "fields": [
                {"name": "task_id", "primary_key": True}]}],
            "service_contracts": [
                {"service_name": "TaskService", "methods": [
                    {"name": "import_tasks_from_json", "params": []}]},
                {"service_name": "TaskRepository", "methods": [
                    {"name": "import_tasks_from_json", "params": []}]},
            ],
            "persistence_ports": {"repositories": [{
                "entity": "Task", "interface_name": "TaskRepository",
                "methods": [{"name": "import_tasks_from_json", "params": []}]}]},
            "interaction_adapters": [], "pattern_matches": [],
        }
        repairs.repair_ungrounded_methods(
            docs, "A task application. Import tasks from JSON.")
        self.assertFalse(any(
            m.get("name") == "import_tasks_from_json"
            for repo in docs["persistence_ports"]["repositories"]
            for m in repo.get("methods") or []))

    def test_a_missing_repository_list_is_treated_as_empty(self):
        docs = {
            "data_models": [],
            "service_contracts": [{"service_name": "S", "methods": [
                {"name": "invented", "params": []}]}],
            "persistence_ports": {"repositories": None},
            "interaction_adapters": [],
            "pattern_matches": [],
        }
        drops = repairs.repair_ungrounded_methods(
            docs, "Create things.", None)
        self.assertEqual(len(drops), 1)

    def test_a_model_grounded_return_is_kept(self):
        docs = {
            "data_models": [{"name": "Book", "fields": [
                {"name": "book_id", "primary_key": True},
                {"name": "available", "type": "bool"}]}],
            "service_contracts": [{"service_name": "BorrowService", "methods": [{
                "name": "return_book",
                "params": [{"name": "book_id", "type": "int"}]}]}],
            "persistence_ports": {"repositories": []},
            "interaction_adapters": [],
            "pattern_matches": [],
        }
        repairs.repair_ungrounded_methods(
            docs, "A library application. Books can be borrowed and returned.")
        self.assertEqual(len(docs["service_contracts"][0]["methods"]), 1)


if __name__ == "__main__":
    unittest.main()
