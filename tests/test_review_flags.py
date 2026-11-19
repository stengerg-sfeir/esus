"""An ambiguous flag is a review decision, not a name-based guess."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import review_flags  # noqa: E402
from kernel.extraction import repairs  # noqa: E402


class FlagRepairTests(unittest.TestCase):
    def components(self):
        return {"facade": {"invocation": {"commands": [{
            "name": "report", "options": [], "subcommands": [{
                "name": "yearly", "options": []}]}]}}}

    def services(self):
        return [{"service_name": "ReportService", "methods": [
            {"name": "get_yearly_summary", "params": [
                {"name": "year", "type": "int"}]},
            {"name": "get_yearly_report", "params": [
                {"name": "year", "type": "int"}]},
        ]}]

    def test_an_ambiguous_flag_is_left_open(self):
        components = self.components()
        repairs.repair_missing_method_flags(
            components, "`report yearly --year`", self.services())
        leaf = components["facade"]["invocation"]["commands"][0]["subcommands"][0]
        self.assertEqual(leaf["options"], [])

    def test_a_recorded_decision_supplies_the_flag(self):
        components = self.components()
        decisions = [{
            "command": "report", "subcommand": "yearly", "flag": "year",
            "service": "ReportService", "method": "get_yearly_summary",
            "param": "year", "option_type": "int",
            "decided_by": "user",
        }]
        repairs.repair_missing_method_flags(
            components, "`report yearly --year`", self.services(),
            decisions=decisions)
        leaf = components["facade"]["invocation"]["commands"][0]["subcommands"][0]
        self.assertEqual(leaf["options"][0]["name"], "--year")
        self.assertEqual(leaf["options"][0]["type"], "int")

    def test_candidate_collection_keeps_both_methods(self):
        candidates = review_flags._candidates(self.services(), "year")
        self.assertEqual({item["method"] for item in candidates},
                         {"get_yearly_summary", "get_yearly_report"})


if __name__ == "__main__":
    unittest.main()
