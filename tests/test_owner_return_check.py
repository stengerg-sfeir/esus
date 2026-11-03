"""A returned read is typed by the repository the call goes through.

`read_all` exists on every repository. A service returning
`self._repos['MemberRepository'].read_all(...)` from a method declared
`-> list[models.Member]` was refused as returning "a Book" because the check
looked the method up by its bare name and found `BookRepository.read_all`.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import generator  # noqa: E402

REPOSITORIES = (
    "import models\n\n\n"
    "class BookRepository:\n"
    "    def read_all(self, author_id: int | None = None) "
    "-> list[models.Book]:\n        return []\n\n\n"
    "class MemberRepository:\n"
    "    def read_all(self, active_only: bool = None) "
    "-> list[models.Member]:\n        return []\n")

SERVICES = (
    "import models\n\n\n"
    "class MemberService:\n"
    "    def read_all_members(self, active_only: bool = None) "
    "-> list[models.Member]:\n"
    '        raise NotImplementedError("refused")\n')

MODELS = ("class Book:\n    id: int = 0\n\n\n"
          "class Member:\n    id: int = 0\n")

INFO = {"cls": "MemberService",
        "def": "def read_all_members(self, active_only: bool = None) "
               "-> list[models.Member]:",
        "reason": "refused"}


def complaints(body):
    return generator._body_complaints(
        body, INFO, SERVICES, REPOSITORIES, {"models.py": MODELS})


class OwnerReturnCheckTests(unittest.TestCase):
    def test_the_right_repository_is_accepted(self):
        body = ["records = self._repos['MemberRepository']"
                ".read_all(active_only=active_only)",
                "return records"]
        self.assertEqual(complaints(body), [])

    def test_the_wrong_repository_is_still_refused(self):
        body = ["records = self._repos['BookRepository'].read_all()",
                "return records"]
        self.assertTrue(any("(a Book)" in item for item in complaints(body)))


if __name__ == "__main__":
    unittest.main()
