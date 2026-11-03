"""The store's criteria operators, in the contract, the gate and the prompt.

Overdue is `due_date < today`. With only `eq`, `ge` and `le` the nearest
operator counted a loan due today as overdue, so strict `lt`/`gt` exist and
every place that lists the operators agrees.
"""

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import generator  # noqa: E402
from kernel.store_contract import DEFAULT_STORE  # noqa: E402


def complaints(operator):
    return generator._store_operator_complaints(ast.parse(
        f"records = self._store.select(self.ENTITY, "
        f"[('due_date', '{operator}', today)])"))


class StoreOperatorTests(unittest.TestCase):
    def test_the_contract_lists_the_strict_operators(self):
        self.assertEqual(set(DEFAULT_STORE.criteria_operators),
                         {"eq", "ge", "le", "gt", "lt"})

    def test_the_gate_accepts_every_contract_operator(self):
        for operator in DEFAULT_STORE.criteria_operators:
            self.assertEqual(complaints(operator), [], operator)

    def test_the_gate_still_refuses_an_unknown_operator(self):
        self.assertEqual(len(complaints("contains")), 1)

    def test_an_operator_added_to_a_named_list_is_checked(self):
        found = generator._store_operator_complaints(ast.parse(
            "criteria = []\n"
            "criteria.append(('due_date', 'lt', today))\n"
            "criteria.append(('return_date', 'is', None))\n"
            "records = self._store.select(self.ENTITY, criteria)\n"))
        self.assertEqual(len(found), 1)
        self.assertIn("`is`", found[0])
        self.assertIn("`lt`", found[0])

    def test_a_synonym_says_which_operator_to_write(self):
        found = complaints("is")
        self.assertIn("write `eq` (a null test is `eq` with `None`)", found[0])
        self.assertIn("write `lt`", complaints("<")[0])

    def test_an_unknown_operator_gets_no_synonym_hint(self):
        self.assertNotIn("write `", complaints("contains")[0])

    def test_every_way_of_filling_a_named_list_is_checked(self):
        for fill in ("criteria = [('f', 'is', 1)]",
                     "criteria = []\ncriteria += [('f', 'is', 1)]",
                     "criteria = []\ncriteria.extend([('f', 'is', 1)])",
                     "criteria = []\ncriteria.insert(0, ('f', 'is', 1))"):
            found = generator._store_operator_complaints(ast.parse(
                fill + "\nself._store.select(self.ENTITY, criteria)\n"))
            self.assertEqual(len(found), 1, fill)

    def test_a_named_list_of_supported_operators_is_accepted(self):
        self.assertEqual(generator._store_operator_complaints(ast.parse(
            "criteria = []\n"
            "criteria.append(('due_date', 'lt', today))\n"
            "criteria.append(('return_date', 'eq', None))\n"
            "records = self._store.select(self.ENTITY, criteria)\n")), [])

    def test_the_services_twin_implements_the_strict_operators(self):
        text = "\n".join(
            line for line in Path(generator.__file__).read_text().splitlines()
            if "return actual is not None and actual" in line)
        self.assertIn("actual < expected", text)
        self.assertIn("actual > expected", text)


if __name__ == "__main__":
    unittest.main()
