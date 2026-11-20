"""Case binding uses extraction only for invocation, never for expectations."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kernel.oracle import binder  # noqa: E402


DOCS = {
    "models": [
        {"name": "Order", "fields": [
            {"name": "id", "type": "int", "primary_key": True},
            {"name": "status", "type": "string"}]},
        {"name": "Product", "fields": [
            {"name": "id", "type": "int", "primary_key": True},
            {"name": "stock_quantity", "type": "int"}]},
    ],
    "services": [{"service_name": "OrderService", "methods": [{
        "name": "cancel_order",
        "params": [{"name": "order_id", "type": "int"}]}]}],
    "repos": [],
}


def case(**overrides):
    value = {
        "id": "cancel",
        "source": "Cancelling a confirmed order releases its stock.",
        "given": {"order": {"status": "confirmed"}},
        "when": {"action": "cancel_order", "args": ["order.id"]},
        "then": {"state": {"order.status": "cancelled"}},
        "status": "confirmed",
    }
    value.update(overrides)
    return value


class OracleBinderTests(unittest.TestCase):
    def test_a_service_case_becomes_the_existing_scenario_shape(self):
        scenario, reason = binder.bind_case(case(), DOCS)
        self.assertIsNone(reason)
        self.assertEqual(scenario["setup"][0]["entity"], "Order")
        self.assertEqual(scenario["when"]["service"], "OrderService")
        self.assertEqual(scenario["when"]["args"], [{"ref": "order.id"}])
        self.assertEqual(scenario["expect"]["fields"],
                         {"order.status": "cancelled"})

    def test_an_unknown_action_is_unbound(self):
        scenario, reason = binder.bind_case(
            case(when={"action": "invented_action"}), DOCS)
        self.assertIsNone(scenario)
        self.assertIn("no generated method", reason)

    def test_a_state_alias_binds_to_the_models_status_field(self):
        docs = {
            "models": [{"name": "Order", "fields": [
                {"name": "id", "primary_key": True},
                {"name": "status"}]}],
            "services": [{"service_name": "OrderService", "methods": [{
                "name": "cancel_order", "params": []}]}],
            "repos": [],
        }
        scenario, reason = binder.bind_case(
            case(given={"order": {"state": "confirmed"}},
                 then={"state": {"order.state": "cancelled"}}), docs)
        self.assertIsNone(reason)
        # The worker resolves state/status at execution time; the case keeps
        # the prompt's spelling and the binder does not rewrite the expectation.
        self.assertEqual(scenario["expect"]["fields"],
                         {"order.state": "cancelled"})


if __name__ == "__main__":
    unittest.main()
