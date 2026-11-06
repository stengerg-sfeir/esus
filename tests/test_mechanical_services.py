"""Standard service CRUD is generated from the data model, custom methods stay.

The model writes guards, state transitions and other custom methods. The
ordinary create/read/list/update/delete wrappers are fixed by the entity list,
so this pass completes them without touching a model-written method.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.extraction import service_contracts  # noqa: E402


class _Requirement:
    def __init__(self, entity, operations):
        self.entity = entity
        self.operations = operations


DOCUMENTS = {
    "data_models": [{
        "name": "Book",
        "fields": [
            {"name": "id", "type": "int", "primary_key": True},
            {"name": "title", "type": "string"},
            {"name": "isbn", "type": "string"},
        ],
    }],
}


class MechanicalServiceTests(unittest.TestCase):
    def complete(self, services):
        return service_contracts.complete(
            services, DOCUMENTS["data_models"],
            [_Requirement("Book", ["create", "read_one", "read_all",
                                   "update", "delete"])],
            [],
        )

    def test_missing_standard_methods_are_added_and_custom_methods_kept(self):
        services = [{"service_name": "BookService", "methods": [{
            "name": "search_books", "params": [{"name": "query", "type": "str"}],
            "return_type": "list[Book]", "description": "search"}]}]
        result = self.complete(services)
        names = [method["name"] for method in result[0]["methods"]]
        self.assertEqual(names, [
            "search_books", "create_book", "read_book_by_id",
            "read_all_books", "update_book", "delete_book",
        ])
        self.assertEqual(result[0]["methods"][1]["return_type"], "None")

    def test_existing_crud_spellings_are_not_duplicated(self):
        services = [{"service_name": "BookService", "methods": [
            {"name": "add_book", "params": [], "return_type": "None"},
            {"name": "get_book_by_id", "params": [], "return_type": "Book | None"},
            {"name": "list_books", "params": [], "return_type": "list[Book]"},
            {"name": "update_book", "params": [], "return_type": "None"},
            {"name": "delete_book", "params": [], "return_type": "None"},
        ]}]
        result = self.complete(services)
        names = [method["name"] for method in result[0]["methods"]]
        self.assertEqual(names, ["add_book", "get_book_by_id", "list_books",
                                 "update_book", "delete_book"])

    def test_a_missing_entity_service_is_not_invented(self):
        self.assertEqual(self.complete([]), [])


if __name__ == "__main__":
    unittest.main()
