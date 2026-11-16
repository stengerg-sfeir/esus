"""A confirmed create is one record, so its call appears once.

A live `create_member` body called `create` twice; the unique email refused
the second call at the first `member add`. The gate only checked that the
named call appeared at all.
"""

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import generator  # noqa: E402

CONTRACT = {"creates": [{"class": "Member",
                         "call": "MemberRepository.create"}]}


def complaints(body):
    return generator._contract_complaints(ast.parse(body), CONTRACT)


class CreateOnceTests(unittest.TestCase):
    def test_one_call_is_accepted(self):
        self.assertEqual(complaints(
            "self._repos['MemberRepository'].create(name=name)\n"), [])

    def test_a_second_call_is_refused_with_the_count(self):
        found = complaints(
            "member_id = self._repos['MemberRepository'].create(name=name)\n"
            "self._repos['MemberRepository'].create(name=name)\n")
        self.assertEqual(found, [
            "the confirmed contract creates one `Member` through "
            "`MemberRepository.create(...)`, but the body calls "
            "`MemberRepository.create` 2 times"])

    def test_no_call_is_still_refused(self):
        self.assertEqual(len(complaints("pass\n")), 1)


class KeywordMessageTests(unittest.TestCase):
    def test_a_method_without_parameters_says_so(self):
        found = generator._keyword_call_complaints(
            ast.parse("self._repos['LoanRepository'].read_all(book_id=1)"),
            "class LoanRepository:\n"
            "    def read_all(self) -> list[models.Loan]:\n        pass\n")
        self.assertEqual(len(found), 1)
        self.assertIn("none: it takes no parameters", found[0])
        self.assertNotIn("one of ;", found[0])


if __name__ == "__main__":
    unittest.main()
