"""Ordinary repository CRUD is classified without asking the model.

The logprobs classifier is still used for aggregates, guards and services,
but a repository method whose name and return shape already agree has one
mechanical answer. These tests pin which items are skipped and that the
remaining items still reach the classifier.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.extraction import classification  # noqa: E402


class _Log:
    def __init__(self):
        self.lines = []

    def write(self, message):
        self.lines.append(message)


def _documents():
    return {
        "data_models": [{
            "name": "Book",
            "fields": [
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "title", "type": "string"},
            ],
        }],
        "service_contracts": [{
            "service_name": "BookRepository",
            "methods": [
                {"name": "create_book", "params": [], "return_type": "Book"},
                {"name": "read_all_books", "params": [], "return_type": "List[Book]"},
                {"name": "find_books_by_author",
                 "params": [{"name": "author_id", "type": "int"}],
                 "return_type": "List[Book]"},
                {"name": "read_book_by_id",
                 "params": [{"name": "book_id", "type": "int"}],
                 "return_type": "Book"},
                {"name": "get_monthly_total", "params": [], "return_type": "int"},
                {"name": "read_all_filtered",
                 "params": [{"name": "status", "type": "str"}],
                 "return_type": "List[Book]"},
            ],
        }],
    }


class DeterministicClassificationTests(unittest.TestCase):
    def test_repository_crud_is_answered_without_the_classifier(self):
        calls = []

        def fake_classifier(llm, text, catalog):
            calls.append(text)
            return {
                "target_text": text,
                "domain": "REPO_QUERY",
                "pattern_id": "AGGREGATE_BY_FK",
                "confidence": 0.9,
                "step1_probabilities": {"REPO_QUERY": 0.9},
                "step2_probabilities": {"AGGREGATE_BY_FK": 0.9},
            }

        log = _Log()
        with mock.patch.object(
            classification, "classify_requirement_2step", fake_classifier
        ):
            matches = classification.classify_documents(
                object(), _documents(), log)

        by_source = {match["source"]: match for match in matches}
        self.assertEqual(
            by_source["contract:BookRepository.create_book"]["pattern_id"],
            "STANDARD_CRUD",
        )
        self.assertEqual(
            by_source["contract:BookRepository.read_all_books"]["pattern_id"],
            "READ_ALL",
        )
        self.assertEqual(
            by_source["contract:BookRepository.find_books_by_author"]["pattern_id"],
            "FILTER_BY_FIELD",
        )
        self.assertEqual(
            by_source["contract:BookRepository.read_book_by_id"]["pattern_id"],
            "READ_ONE_BY_ID",
        )
        self.assertEqual(
            by_source["contract:BookRepository.read_all_filtered"]["pattern_id"],
            "FILTER_BY_FIELD",
        )
        self.assertEqual(
            by_source["contract:BookRepository.get_monthly_total"]["pattern_id"],
            "AGGREGATE_BY_FK",
        )
        self.assertEqual(len(calls), 1)
        self.assertIn("get_monthly_total", calls[0])
        self.assertTrue(any("deterministic (repository CRUD)" in line
                            for line in log.lines))


if __name__ == "__main__":
    unittest.main()
