"""The meter scores generation without generating: BLOCKED, DEGENERATE, or a row."""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import meter_coverage  # noqa: E402


def degenerate_dir(parent):
    """Gate-clean but empty, shaped like a real no-domain run."""
    target = Path(parent) / "hello"
    target.mkdir()
    (target / "requirements.txt").write_text("Print hi.", encoding="utf-8")
    for name in ("intentions", "invariants", "data_models", "errors",
                 "service_contracts", "pattern_matches",
                 "interaction_adapters"):
        (target / f"{name}.json").write_text(json.dumps({name: []}),
                                             encoding="utf-8")
    (target / "components.json").write_text(json.dumps(
        {"components": {"facade": {"type": "cli", "technology": "none",
                                   "invocation": None},
                        "persistence": {"required": False,
                                        "technology": "none"},
                        "external_access": [], "crud_services": []}}),
        encoding="utf-8")
    return str(target)


class MeasureTests(unittest.TestCase):
    def test_degenerate_reports_degenerate_not_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            row = meter_coverage.measure(degenerate_dir(directory))
            self.assertTrue(row.get("degenerate"))
            self.assertNotIn("blocked", row)

    def test_render_mixes_rows_and_totals_only_generatable(self):
        rows = [
            {"name": "library", "total": 10, "implemented": 7, "stubs": 3,
             "coverage": 0.7, "reasons": {"x": 3}},
            {"name": "broken", "blocked": "refusing: 1 blocker(s)"},
            {"name": "hello", "degenerate": True},
        ]
        with io.StringIO() as buffer, redirect_stdout(buffer):
            text = meter_coverage.render(rows)
        self.assertIn("library", text)
        self.assertIn("70%", text)
        self.assertIn("BLOCKED", text)
        self.assertIn("DEGENERATE", text)
        self.assertIn("TOTAL", text)
        self.assertIn("stub ledger:", text)


if __name__ == "__main__":
    unittest.main()
