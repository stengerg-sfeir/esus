"""Intent planning produces a sidecar case set without model calls."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_intent_cases  # noqa: E402
from kernel.oracle import intents  # noqa: E402


REQUIREMENTS = """Customers can cancel their orders.
"""
DOCS = {"data_models": [
    {"name": "Customer", "fields": [
        {"name": "id", "type": "int", "primary_key": True,
         "nullable": False},
        {"name": "name", "type": "string", "nullable": False},
        {"name": "email", "type": "string", "nullable": False, "unique": True},
    ]},
    {"name": "Order", "fields": [
        {"name": "id", "type": "int", "primary_key": True,
         "nullable": False},
        {"name": "customer_id", "type": "int", "nullable": False,
         "foreign_key": {"target_entity": "Customer",
                          "target_field": "id"}},
        {"name": "status", "type": "string", "nullable": False},
    ]},
]}
INTENTS = [{
    "id": "cancel_order",
    "source": "Customers can cancel their orders.",
    "kind": "update",
    "entity": "Order",
    "action": "cancel_order",
    "setup_entities": [
        {"alias": "order", "entity": "Order", "role": "target"},
    ],
    "setup_values": {"order.status": "pending"},
    "changes": {"order.status": "cancelled"},
    "expect": {"state": {"order.status": "cancelled"},
               "rows": {"Order": 1}},
    "status": "confirmed",
}]


class IntentCaseBuildTests(unittest.TestCase):
    def test_a_planned_intent_becomes_a_valid_case_sidecar(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "prompt_x"
            project.mkdir()
            (project / "requirements.txt").write_text(
                REQUIREMENTS, encoding="utf-8")
            (project / "data_models.json").write_text(
                json.dumps(DOCS), encoding="utf-8")
            (project / intents.INTENTS_NAME).write_text(
                json.dumps({"intents": INTENTS}), encoding="utf-8")
            valid, path = build_intent_cases.build_one(project)
            self.assertEqual(len(valid), 1)
            written = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(written["cases"][0]["id"], "cancel_order")
            self.assertEqual(list(written["cases"][0]["given"]),
                             ["customer", "order"])
            plans = json.loads(
                (project / "oracle_intent_plans.json").read_text(
                    encoding="utf-8"))
            self.assertEqual(plans["rejected"], [])
            self.assertEqual(len(plans["plans"]), 1)

    def test_a_plan_failure_is_reported_not_written(self):
        bad = dict(INTENTS[0])
        bad["setup_values"] = {"order.unknown": "x"}
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "prompt_x"
            project.mkdir()
            (project / "requirements.txt").write_text(
                REQUIREMENTS, encoding="utf-8")
            (project / "data_models.json").write_text(
                json.dumps(DOCS), encoding="utf-8")
            (project / intents.INTENTS_NAME).write_text(
                json.dumps({"intents": [bad]}), encoding="utf-8")
            valid, _path = build_intent_cases.build_one(project)
            self.assertEqual(valid, [])
            plans = json.loads(
                (project / "oracle_intent_plans.json").read_text(
                    encoding="utf-8"))
            self.assertEqual(len(plans["rejected"]), 1)
            self.assertIn("unknown", plans["rejected"][0]["errors"][0])


if __name__ == "__main__":
    unittest.main()
