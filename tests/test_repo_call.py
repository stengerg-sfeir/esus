"""A contract names the repository call that creates or saves a model.

Repositories that declare plain `create`/`update` lost both in the record:
the lookup only matched `create_<entity>`/`update_<entity>`, so a create the
human confirmed was dropped, its save went unnamed, and a two-write method
was not wrapped in a transaction.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import review_contracts  # noqa: E402


def ctx(*names):
    return {"repositories": [{
        "entity": "Loan", "interface_name": "LoanRepository",
        "methods": [{"name": name} for name in names]}]}


class RepoCallTests(unittest.TestCase):
    def test_the_plain_verb_is_the_call(self):
        c = ctx("read_one", "create", "update")
        self.assertEqual(review_contracts._create_call(c, "Loan", "service"),
                         "LoanRepository.create")
        self.assertEqual(review_contracts._write_call(c, "Loan", "service"),
                         "LoanRepository.update")

    def test_an_entity_named_method_still_wins(self):
        c = ctx("create", "create_loan")
        self.assertEqual(review_contracts._create_call(c, "Loan", "service"),
                         "LoanRepository.create_loan")

    def test_any_prefixed_method_still_beats_the_plain_verb(self):
        c = ctx("create", "create_record")
        self.assertEqual(review_contracts._create_call(c, "Loan", "service"),
                         "LoanRepository.create_record")

    def test_no_such_method_is_none(self):
        self.assertIsNone(review_contracts._create_call(
            ctx("read_one"), "Loan", "service"))

    def test_a_repository_role_writes_through_the_store(self):
        self.assertEqual(review_contracts._create_call(
            ctx("create"), "Loan", "repository"), "self._store.add")


if __name__ == "__main__":
    unittest.main()
