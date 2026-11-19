"""The requirement trace reports coverage separately from acceptance.

It may map a sentence to design evidence, or leave it unmapped; it never turns
a lexical match into a behavioral pass.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import requirement_trace  # noqa: E402


class RequirementTraceTests(unittest.TestCase):
    def project(self, directory):
        root = Path(directory)
        (root / "requirements.txt").write_text(
            "Orders can be cancelled.\n"
            "The CLI must support `Order cancel --order-id`.\n"
            "The application must use SQLite.\n"
            "Send a carrier pigeon notification.\n",
            encoding="utf-8")
        (root / "data_models.json").write_text(json.dumps({
            "data_models": [{"name": "Order", "fields": [
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "status", "type": "string"}]}]}), encoding="utf-8")
        (root / "components.json").write_text(json.dumps({
            "facade": {"invocation": {"commands": [{
                "name": "Order", "options": [], "subcommands": [{
                    "name": "cancel",
                    "options": [{"name": "--order-id", "type": "int"}]}]}]}},
            "persistence": {"required": True, "technology": "sqlite"}}),
            encoding="utf-8")
        (root / "service_contracts.json").write_text(json.dumps({
            "service_contracts": [{
                "service_name": "OrderService", "methods": [{
                    "name": "cancel_order", "description": "Cancels an order.",
                    "params": [{"name": "order_id", "type": "int"}],
                    "return_type": "None", "raises": []}]}]}),
            encoding="utf-8")
        (root / "method_contracts.json").write_text(json.dumps({
            "method_contracts": [{
                "holder": "OrderService", "method": "cancel_order",
                "decided_by": "user", "effects": [{
                    "target": "order.status", "op": "set",
                    "value": "'cancelled'"}]}]}), encoding="utf-8")
        return root

    def test_trace_maps_cli_and_marks_it_tested(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.project(directory)
            checks = [{"name": "cli-leaf:Order cancel", "status": "passed"},
                      {"name": "contract:OrderService.cancel_order",
                       "status": "passed"}]
            trace = requirement_trace.trace_project(project, checks)
        by_text = {row["text"]: row for row in trace["rows"]}
        cli = next(row for text, row in by_text.items()
                   if "`Order cancel" in text)
        self.assertEqual(cli["status"], "mapped_tested")
        self.assertTrue(any(item["id"] == "command:Order cancel"
                            for item in cli["evidence"]))
        self.assertEqual(trace["requirements"], 4)

    def test_an_unrelated_sentence_stays_unmapped(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.project(directory)
            trace = requirement_trace.trace_project(project)
        pigeon = next(row for row in trace["rows"]
                      if "carrier pigeon" in row["text"])
        self.assertEqual(pigeon["status"], "unmapped")

    def test_sqlite_maps_to_the_persistence_component(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.project(directory)
            trace = requirement_trace.trace_project(project)
        sqlite = next(row for row in trace["rows"] if "SQLite" in row["text"])
        self.assertIn(sqlite["status"], ("mapped_untested", "mapped_tested"))
        self.assertTrue(any(item["id"].startswith("component:persistence")
                            for item in sqlite["evidence"]))

    def test_summary_counts_each_status(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self.project(directory)
            trace = requirement_trace.trace_project(project)
        summary = requirement_trace.summarize([trace])
        self.assertEqual(summary["projects"], 1)
        self.assertEqual(summary["requirements"], 4)
        self.assertEqual(sum(summary["counts"].values()), 4)


if __name__ == "__main__":
    unittest.main()
