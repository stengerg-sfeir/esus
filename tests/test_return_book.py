"""Returning a book closes the active record and restores availability."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import generator  # noqa: E402


class ReturnBookTests(unittest.TestCase):
    def ctx(self):
        return {
            "mappings": {}, "entity_names": ["Book", "Member", "BorrowRecord"],
            "models": [
                {"name": "Book", "fields": [
                    {"name": "book_id", "primary_key": True},
                    {"name": "available_status", "type": "bool"}]},
                {"name": "Member", "fields": [
                    {"name": "member_id", "primary_key": True}]},
                {"name": "BorrowRecord", "fields": [
                    {"name": "borrow_id", "primary_key": True},
                    {"name": "book_id", "foreign_key": {
                        "target_entity": "Book", "target_field": "book_id"}},
                    {"name": "member_id", "foreign_key": {
                        "target_entity": "Member", "target_field": "member_id"}},
                    {"name": "return_date", "type": "datetime"},
                    {"name": "is_returned", "type": "bool"}]},
            ],
            "errors": [{"name": "BorrowRecordNotFoundError"}],
            "repositories": [
                {"entity": "Book", "interface_name": "BookRepository",
                 "methods": [{"name": "update", "params": [
                     {"name": "book_id"}, {"name": "available_status"}]}]},
                {"entity": "BorrowRecord", "interface_name": "BorrowRecordRepository",
                 "methods": [{"name": "read_all", "params": [
                     {"name": "book_id"}, {"name": "member_id"}]},
                     {"name": "update", "params": [
                         {"name": "borrow_id"}, {"name": "return_date"},
                         {"name": "is_returned"}]}]},
            ],
        }

    def test_return_body_closes_the_record_and_marks_the_book(self):
        body = generator._service_return_book_body(
            self.ctx(), "BorrowService",
            {"name": "return_book", "params": [
                {"name": "member_id"}, {"name": "book_id"}],
             "return_type": "None"},
            [("member_id", "member_id", "int"),
             ("book_id", "book_id", "int")], "None")
        self.assertIsNotNone(body)
        text = "\n".join(body)
        self.assertIn("read_all", text)
        self.assertIn("is_returned=True", text)
        self.assertIn("available_status=True", text)


if __name__ == "__main__":
    unittest.main()
