"""Mutable model instances are not set members or dict keys.

A live search body collected `models.Book(...)` objects with `.append` and
deduplicated them with `dict.fromkeys(results)`; the dataclass is
unhashable, so every search raised `TypeError`. The gate knew `set()` over a
comprehension but not a list filled by `append`, nor the other hashing forms.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import generator  # noqa: E402

MODULE = ("import models\n\n\nclass BookRepository:\n"
          "    def search(self, query: str = None) -> list[models.Book]:\n"
          '        raise NotImplementedError("refused")\n')
MODELS = "class Book:\n    id: int = 0\n    title: str = ''\n"
INFO = {"cls": "BookRepository",
        "def": "def search(self, query: str = None) -> list[models.Book]:",
        "reason": "refused"}
BUILD = ("results = []\n"
         "for row in self._store.all(self.ENTITY):\n"
         "    results.append(models.Book(**row))\n")


def complaints(tail):
    body = (BUILD + tail + "\nquery\n").splitlines()
    return [item for item in generator._body_complaints(
        body, INFO, MODULE, "", {"models.py": MODELS})
        if "mutable" in item]


class HashedModelTests(unittest.TestCase):
    def test_dict_fromkeys_over_an_appended_list_is_refused(self):
        found = complaints("return list(dict.fromkeys(results))")
        self.assertEqual(len(found), 1)
        self.assertIn("dict.fromkeys()", found[0])
        self.assertIn("`Book`", found[0])

    def test_set_over_an_appended_list_is_refused(self):
        self.assertIn("set()", complaints("return list(set(results))")[0])

    def test_frozenset_is_refused(self):
        self.assertIn("frozenset()",
                      complaints("return list(frozenset(results))")[0])

    def test_a_set_comprehension_of_models_is_refused(self):
        self.assertIn("builds a set of mutable `Book`",
                      complaints("return list({book for book in results})")[0])

    def test_a_dict_keyed_by_models_is_refused(self):
        self.assertIn("keys a dict by mutable `Book`", complaints(
            "return list({book: 1 for book in results})")[0])

    def test_deduplicating_by_a_stable_key_is_accepted(self):
        self.assertEqual(complaints(
            "seen = set()\nunique = []\nfor book in results:\n"
            "    if book.id not in seen:\n        seen.add(book.id)\n"
            "        unique.append(book)\nreturn unique"), [])

    def test_a_plain_list_return_is_accepted(self):
        self.assertEqual(complaints("return results"), [])


if __name__ == "__main__":
    unittest.main()
