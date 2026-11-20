"""Writer-side effects read from the requirements, not from a prompt id."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import generator  # noqa: E402


def repo(entity, methods):
    return {"entity": entity, "interface_name": f"{entity}Repository",
            "methods": methods}


def domains(*models):
    return [{"name": name, "fields": fields} for name, fields in models]


class SoftDeleteTests(unittest.TestCase):
    def test_soft_delete_sets_the_flag_and_hides_the_row_from_read_all(self):
        ctx = {
            "models": domains(
                ("Project", [
                    {"name": "project_id", "type": "int", "primary_key": True},
                    {"name": "name", "type": "string"},
                    {"name": "is_deleted", "type": "boolean"}]),
            ),
            "entity_names": ["Project"],
            "requirements": ("Deleting a project is a soft delete: the project "
                             "remains in the database."),
            "errors": [],
            "services": [], "mappings": {}, "match_index": {},
            "adapters": [], "components": {},
            "repositories": [repo("Project", [
                {"name": "read_all", "params": [],
                 "return_type": "List[Project]"},
                {"name": "delete", "params": [
                    {"name": "project_id", "type": "int"}],
                 "return_type": "None"},
            ])],
        }
        text = generator.emit_repositories(ctx, {
            "source": "t", "implemented": 0, "stubs": 0, "stub_reasons": []})
        self.assertIn("'is_deleted': True", text)
        self.assertIn("criteria.append(('is_deleted', 'eq', False))", text)
        self.assertNotIn("self._store.delete", text)

    def test_without_the_requirement_delete_stays_hard(self):
        ctx = {
            "models": domains(
                ("Project", [
                    {"name": "project_id", "type": "int", "primary_key": True},
                    {"name": "is_deleted", "type": "boolean"}]),
            ),
            "entity_names": ["Project"],
            "requirements": "CRUD for projects.",
            "errors": [], "services": [], "mappings": {}, "match_index": {},
            "adapters": [], "components": {},
            "repositories": [repo("Project", [
                {"name": "delete", "params": [
                    {"name": "project_id", "type": "int"}],
                 "return_type": "None"}])],
        }
        text = generator.emit_repositories(ctx, {
            "source": "t", "implemented": 0, "stubs": 0, "stub_reasons": []})
        self.assertIn("self._store.delete", text)
        self.assertNotIn("'is_deleted': True", text)


class AuditTests(unittest.TestCase):
    def ctx(self):
        return {
            "models": domains(
                ("Customer", [
                    {"name": "id", "type": "int", "primary_key": True},
                    {"name": "email", "type": "string"}]),
                ("AuditLog", [
                    {"name": "id", "type": "int", "primary_key": True},
                    {"name": "operation", "type": "string"},
                    {"name": "customer_id", "type": "int", "foreign_key": {
                        "target_entity": "Customer", "target_field": "id"}},
                    {"name": "timestamp", "type": "datetime"}]),
            ),
            "entity_names": ["Customer", "AuditLog"],
            "requirements": ("Every creation, update and deletion must also "
                             "produce an audit record."),
            "errors": [], "services": [], "mappings": {}, "match_index": {},
            "adapters": [], "components": {},
            "repositories": [
                repo("Customer", [
                    {"name": "create", "params": [
                        {"name": "email", "type": "str"}],
                     "return_type": "Customer"},
                    {"name": "update", "params": [
                        {"name": "id", "type": "int"},
                        {"name": "email", "type": "str"}],
                     "return_type": "Customer"},
                    {"name": "delete", "params": [
                        {"name": "id", "type": "int"}],
                     "return_type": "None"},
                ]),
                repo("AuditLog", [
                    {"name": "read_all", "params": [],
                     "return_type": "List[AuditLog]"},
                ]),
            ],
        }

    def test_create_update_and_delete_write_audit_rows(self):
        text = generator.emit_repositories(self.ctx(), {
            "source": "t", "implemented": 0, "stubs": 0, "stub_reasons": []})
        self.assertEqual(text.count("self._store.add('AuditLog'"), 3)
        self.assertIn("'operation': 'create'", text)
        self.assertIn("'operation': 'update'", text)
        self.assertIn("'operation': 'delete'", text)

    def test_delete_audit_precedes_the_hard_delete(self):
        text = generator.emit_repositories(self.ctx(), {
            "source": "t", "implemented": 0, "stubs": 0, "stub_reasons": []})
        audit = text.index("'operation': 'delete'")
        delete = text.index("self._store.delete(self.ENTITY", audit)
        self.assertLess(audit, delete)

    def test_without_audit_in_the_requirements_no_row_is_written(self):
        ctx = self.ctx()
        ctx["requirements"] = "CRUD for customers."
        text = generator.emit_repositories(ctx, {
            "source": "t", "implemented": 0, "stubs": 0, "stub_reasons": []})
        self.assertNotIn("self._store.add('AuditLog'", text)


if __name__ == "__main__":
    unittest.main()
