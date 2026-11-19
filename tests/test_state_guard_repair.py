"""A missing contract must not turn a state guard into deleted business logic.

`repair_invented_state_guards` can only remove a guard when a human-confirmed
contract for that method explicitly declares no preconditions. An absent,
inferred or auto contract preserves the guard and leaves the doubt visible.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import generator  # noqa: E402

SERVICES = '''class OrderService:
    def cancel_order(self, order_id: int = None) -> None:
        order = self._repos["OrderRepository"].read_one(order_id)
        if order.status != "pending":
            raise errors.InvalidOrderStatusError()
        self._repos["OrderRepository"].update(order_id, status="cancelled")
'''


def repaired(contracts):
    files = {"services.py": SERVICES}
    return generator.repair_invented_state_guards(
        files, {"contracts": contracts})["services.py"]


class StateGuardRepairTests(unittest.TestCase):
    def test_no_contract_preserves_the_guard(self):
        self.assertIn("if order.status", repaired([]))

    def test_an_inferred_or_auto_contract_preserves_the_guard(self):
        for decided_by in ("inferred", "auto"):
            with self.subTest(decided_by=decided_by):
                text = repaired([{
                    "holder": "OrderService",
                    "method": "cancel_order",
                    "decided_by": decided_by,
                    "preconditions": [],
                }])
                self.assertIn("if order.status", text)

    def test_a_confirmed_contract_without_preconditions_removes_it(self):
        text = repaired([{
            "holder": "OrderService",
            "method": "cancel_order",
            "decided_by": "user",
            "preconditions": [],
        }])
        self.assertNotIn("if order.status", text)
        self.assertIn("self._repos", text)

    def test_a_confirmed_precondition_preserves_it(self):
        text = repaired([{
            "holder": "OrderService",
            "method": "cancel_order",
            "decided_by": "user",
            "preconditions": [{"check": "order.status == 'confirmed'",
                               "error": "InvalidOrderStatusError",
                               "raise_when": "false"}],
        }])
        self.assertIn("if order.status", text)

    def test_another_methods_contract_does_not_authorize_removal(self):
        text = repaired([{
            "holder": "OrderService",
            "method": "ship_order",
            "decided_by": "user",
            "preconditions": [],
        }])
        self.assertIn("if order.status", text)


if __name__ == "__main__":
    unittest.main()
