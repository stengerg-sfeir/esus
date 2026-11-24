"""CLI scenarios pass one argv list, not a stringified list."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "runtime"))

import worker  # noqa: E402


class WorkerCliTests(unittest.TestCase):
    def test_cli_arguments_are_unpacked_as_separate_argv_entries(self):
        captured = []

        def fake_run(argv, *args, **kwargs):
            captured.append(argv)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        scenario = {
            "name": "oracle:borrow",
            "setup": [],
            "when": {"cli": ["borrow", "--member-id", "1",
                             "--book-id", "1"]},
            "expect": {"exit_code": 0},
        }
        with mock.patch.object(worker.subprocess, "run", side_effect=fake_run):
            result = worker._run_scenario(
                {"models": []}, {}, None, scenario, 1,
                cli_path=Path("cli.py"), db=Path("db.sqlite3"),
                cli_module=None)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(captured[0][-4:], ["--member-id", "1",
                                           "--book-id", "1"])
        self.assertNotIn("['borrow'", " ".join(captured[0]))


if __name__ == "__main__":
    unittest.main()
