"""The canonical verifier keeps passing legacy cases and confirmed intents."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_verifier_cases  # noqa: E402


class VerifierMergeTests(unittest.TestCase):
    def test_passed_legacy_cases_and_confirmed_intents_are_merged(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "prompt_x"
            project.mkdir()
            (project / "requirements.txt").write_text(
                "A task can be created.\nA task can be listed.", encoding="utf-8")
            (project / "oracle_cases.json").write_text(json.dumps({"cases": [
                {"id": "legacy_pass", "source": "A task can be created.",
                 "given": {"task": {"title": "x"}},
                 "when": {"action": "create_task"}, "then": {"rows": {"Task": 1}},
                 "status": "confirmed"},
                {"id": "legacy_unbound", "source": "A task can be listed.",
                 "given": {"task": {"title": "x"}},
                 "when": {"action": "list_tasks"}, "then": {"rows": {"Task": 1}},
                 "status": "unbound"},
            ]}), encoding="utf-8")
            (project / "oracle_report.json").write_text(json.dumps({
                "results": [
                    {"case": "legacy_pass", "status": "passed"},
                    {"case": "legacy_unbound", "status": "unbound",
                     "reason": "missing setup"},
                ]}), encoding="utf-8")
            (project / "oracle_cases_intents.json").write_text(json.dumps({
                "cases": [
                    {"id": "intent_pass", "source": "A task can be listed.",
                     "given": {"task": {"title": "x"}},
                     "when": {"action": "list_tasks"}, "then": {"rows": {"Task": 1}},
                     "status": "confirmed"},
                    {"id": "intent_assumed", "source": "A task can be created.",
                     "given": {"task": {"title": "x"}},
                     "when": {"action": "create_task"}, "then": {},
                     "status": "assumed"},
                ]}), encoding="utf-8")
            merged, retired = build_verifier_cases.build_project(project)
            self.assertEqual([item["id"] for item in merged],
                             ["legacy_pass", "intent_pass"])
            self.assertEqual(len(retired), 1)
            self.assertEqual(retired[0]["case"]["id"], "legacy_unbound")
            saved = json.loads(
                (project / "oracle_cases_merged.json").read_text(encoding="utf-8"))
            self.assertEqual(len(saved["cases"]), 2)
            audit = json.loads(
                (project / "oracle_cases_retired.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["counts"]["retired"], 1)


if __name__ == "__main__":
    unittest.main()
