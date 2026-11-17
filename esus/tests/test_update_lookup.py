"""An update finds its record by key and patches the rest.

`update(book_id=1, available_copies=0)` looked the book up by id *and* by its
new copy count, found none, and refused the last borrow with "matched 0
records". The parameters naming the key identify the record; the others are
the change.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import generator  # noqa: E402


def field(name, primary_key=False, type_="int"):
    return {"name": name, "type": type_, "primary_key": primary_key,
            "nullable": False, "unique": False, "foreign_key": None}


CTX = {
    "entity_names": ["Book"], "errors": [], "invariants": [],
    "requirements": "",
    "models": [{"name": "Book", "fields": [
        field("id", True), field("title", type_="string"),
        field("available_copies")]}],
}
FIELDS = ["id", "title", "available_copies"]


def body(params):
    return "\n".join(generator._update_body(
        CTX, {"name": "update"}, params, "Book", "models.Book", FIELDS,
        "errors.BookNotFoundError"))


class UpdateLookupTests(unittest.TestCase):
    def test_only_the_key_selects_the_record(self):
        text = body([("book_id", "book_id", "int"),
                     ("available_copies", "available_copies", "int")])
        self.assertIn("('id', 'eq', book_id)", text)
        self.assertNotIn("('available_copies', 'eq'", text)

    def test_the_other_parameters_are_the_patch(self):
        text = body([("book_id", "book_id", "int"),
                     ("available_copies", "available_copies", "int")])
        self.assertIn("patch['available_copies'] = available_copies", text)

    def test_without_a_key_parameter_every_parameter_selects(self):
        text = body([("title", "title", "str"),
                     ("available_copies", "available_copies", "int")])
        self.assertIn("('title', 'eq', title)", text)
        self.assertIn("('available_copies', 'eq', available_copies)", text)


if __name__ == "__main__":
    unittest.main()
