"""The chat loop terminates well: clean, stuck, crashed, or out of rounds.

Each test pins one exit with the model and the probe mocked — the loop's
contract is about orchestration (findings, snapshot, rerun, compare), never
about generation itself: it keeps a strictly better state or rolls back,
and it always terminates. Snapshots use real temp dirs throughout.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import extract_arch  # noqa: E402
from kernel.consistency.report import Finding  # noqa: E402


def finding(rule):
    return Finding("warning", rule, f"rule {rule} fired")


class ResumeStepForTests(unittest.TestCase):
    def test_earliest_healable_step_wins(self):
        step = extract_arch.resume_step_for(
            [finding("uncovered_field"), finding("missing_flag")])
        self.assertEqual(step, "components")

    def test_contracts_outranks_adapters(self):
        step = extract_arch.resume_step_for(
            [finding("unknown_model_field"), finding("unmet_crud_operation")])
        self.assertEqual(step, "service_contracts")

    def test_structural_rules_have_no_step(self):
        self.assertIsNone(extract_arch.resume_step_for([finding("invalid_value")]))
        self.assertIsNone(extract_arch.resume_step_for([finding("placeholder_value")]))

    def test_no_findings_means_no_step(self):
        self.assertIsNone(extract_arch.resume_step_for([]))


class SnapshotTests(unittest.TestCase):
    def test_snapshot_and_rollback_restore_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "out"
            target.mkdir()
            (target / "a.json").write_text("before", encoding="utf-8")
            snapshot = extract_arch.snapshot_output(str(target))
            (target / "a.json").write_text("after", encoding="utf-8")
            (target / "b.json").write_text("new", encoding="utf-8")
            extract_arch.restore_snapshot(snapshot, str(target))
            self.assertEqual((target / "a.json").read_text(encoding="utf-8"), "before")
            self.assertFalse((target / "b.json").exists())
            self.assertTrue(Path(snapshot).is_dir(), "snapshot stays as evidence")


class ChatLoopTests(unittest.TestCase):
    def loop(self, **stubs):
        """Run the loop with scripted flows (findings per round) and checks."""
        directory = tempfile.mkdtemp()
        calls = {"rerun": []}
        params = {"max_rounds": 3, "flows": [[]], "checks": [],
                  "crash": False, **stubs}
        flows = [list(items) for items in params["flows"]]
        checks = [list(items) for items in params["checks"]]

        def fake_flow(path, out_fn=None, tie_runner=None, alias_runner=None,
                      surface_runner=None, slot_runner=None, **kwargs):
            return flows.pop(0)

        def fake_check(name, path):
            if checks:
                return checks.pop(0), [], None
            return [], [], None

        crashes_left = [params["crash"] if isinstance(params["crash"], int)
                        else (1 if params["crash"] else 0)]

        def fake_rerun(start):
            calls["rerun"].append(start)
            if crashes_left[0] > 0:
                crashes_left[0] -= 1
                raise RuntimeError("llama_decode returned -3")
            Path(directory, "marker.txt").write_text("rerun touched this",
                                                     encoding="utf-8")

        with mock.patch.object(extract_arch, "chat_flow", side_effect=fake_flow), \
             mock.patch("probe_readiness.check_prompt", side_effect=fake_check):
            for filename, content in dict(params.get("writes", {})).items():
                Path(directory, filename).write_text(content, encoding="utf-8")
            remaining = extract_arch.chat_loop(
                directory, fake_rerun, out_fn=lambda _: None,
                max_rounds=params["max_rounds"])
        return remaining, calls, directory

    def snapshot_of(self, directory):
        return Path(directory).parent / f".chat_snapshot_{Path(directory).name}"

    def test_clean_first_round_asks_nothing_reruns_nothing(self):
        remaining, calls, directory = self.loop(flows=[[]])
        self.assertEqual(remaining, 0)
        self.assertEqual(calls["rerun"], [])
        self.assertFalse(self.snapshot_of(directory).exists())

    def test_improvement_keeps_the_new_state(self):
        remaining, calls, directory = self.loop(
            flows=[[finding("uncovered_field")], []],
            checks=[[]],
            writes={"marker.txt": "before"})
        self.assertEqual(remaining, 0)
        self.assertEqual(calls["rerun"], ["interaction_adapters"])
        self.assertFalse(self.snapshot_of(directory).exists())

    def test_regression_rolls_back_and_keeps_evidence(self):
        remaining, calls, directory = self.loop(
            flows=[[finding("uncovered_field"), finding("missing_flag")]],
            checks=[[finding("uncovered_field")] * 3],
            writes={"marker.txt": "before"})
        self.assertEqual(remaining, 2)
        self.assertEqual((Path(directory) / "marker.txt").read_text(encoding="utf-8"),
                         "before")
        self.assertTrue(self.snapshot_of(directory).is_dir())

    def test_unmapped_rules_never_rerun(self):
        remaining, calls, _ = self.loop(flows=[[finding("invalid_value")]])
        self.assertEqual(remaining, 1)
        self.assertEqual(calls["rerun"], [])

    def test_a_crash_rolls_back_and_reports(self):
        remaining, calls, directory = self.loop(
            flows=[[finding("uncovered_field")]], crash=2,
            writes={"marker.txt": "before"})
        self.assertEqual(remaining, 1)
        self.assertEqual((Path(directory) / "marker.txt").read_text(encoding="utf-8"),
                         "before")

    def test_rounds_are_bounded(self):
        remaining, calls, _ = self.loop(
            max_rounds=2,
            flows=[[finding("uncovered_field")] * 3,
                   [finding("uncovered_field")] * 2,
                   [finding("uncovered_field")]],
            checks=[[finding("uncovered_field")] * 2,
                    [finding("uncovered_field")]])
        self.assertEqual(remaining, 1)
        self.assertEqual(len(calls["rerun"]), 2)


class ResumeRetryTests(unittest.TestCase):
    """A crashed resume is retried before the session gives up.

    Both crashes seen in real runs landed in classifier decode (transient
    Metal state) and succeeded on the next attempt — aborting the whole
    session on the first flake wastes the triage answers already recorded.
    """

    def test_a_flaky_resume_succeeds_on_retry(self):
        from kernel.consistency.report import Finding

        state = {"failed": False}

        def fake_rerun(start):
            if not state["failed"]:
                state["failed"] = True
                raise RuntimeError("llama_decode returned -3")
            calls["reruns"].append(start)

        calls = {"reruns": []}
        with tempfile.TemporaryDirectory() as directory:
            with unittest.mock.patch("probe_readiness.check_prompt") as checked:
                one = [Finding("warning", "uncovered_field", "x")]
                checked.side_effect = [(one, [], None), (one, [], None),
                                       ([], [], None), ([], [], None),
                                       ([], [], None), ([], [], None),
                                       ([], [], None)]
                remaining = extract_arch.chat_loop(
                    directory, fake_rerun, out_fn=lambda _: None,
                    max_rounds=3)
            self.assertEqual(remaining, 0)
            self.assertEqual(calls["reruns"], ["interaction_adapters"])

    def test_a_repeated_crash_rolls_back(self):
        from kernel.consistency.report import Finding

        def always_crash(start):
            raise RuntimeError("llama_decode returned -3")

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out"
            target.mkdir()
            (target / "marker.txt").write_text("before", encoding="utf-8")
            with unittest.mock.patch("probe_readiness.check_prompt") as checked:
                one = [Finding("warning", "uncovered_field", "x")]
                checked.side_effect = [(one, [], None), (one, [], None),
                                       ([], [], None)]
                lines = []
                remaining = extract_arch.chat_loop(
                    str(target), always_crash, out_fn=lines.append,
                    max_rounds=3)
            self.assertEqual(remaining, 1)
            self.assertEqual((target / "marker.txt").read_text(encoding="utf-8"),
                             "before")
            self.assertTrue(any("crashed twice" in line for line in lines))

    def test_attempt_resume_runs_once_when_healthy(self):
        calls = []
        extract_arch.attempt_resume(calls.append, "components", out_fn=lambda _: None)
        self.assertEqual(calls, ["components"])


class ResumeSubprocessTests(unittest.TestCase):
    """Resume rounds are isolated child processes, not in-process reruns.

    The failure that motivated this: a crashed classifier decode left Metal
    state unusable, and the in-process retry's fresh model load failed with
    pressure errors. A child inherits stdio (logs stream live) and takes any
    corruption down with it; the snapshot decides what survives.
    """

    def args(self):
        return type("Args", (), {"model": "m.gguf", "context": 8192})()

    def test_success_returns_quietly_with_the_right_command(self):
        import subprocess

        seen = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"] = cmd
            seen["cwd"] = kwargs.get("cwd")
            return subprocess.CompletedProcess(cmd, 0)

        with unittest.mock.patch("subprocess.run", side_effect=fake_run):
            self.assertIsNone(extract_arch.resume_in_subprocess(
                self.args(), "out/shop", "components"))
        self.assertEqual(seen["cmd"][:2], [sys.executable, unittest.mock.ANY])
        self.assertTrue(str(seen["cmd"][1]).endswith("extract_arch.py"))
        for flag, value in [("--model", "m.gguf"), ("--output", "out/shop"),
                            ("--context", "8192"),
                            ("--from-step", "components")]:
            self.assertIn(flag, seen["cmd"])
            self.assertIn(value, seen["cmd"])

    def test_failure_raises_with_the_exit_code(self):
        import subprocess

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1)

        with unittest.mock.patch("subprocess.run", side_effect=fake_run):
            with self.assertRaises(RuntimeError) as ctx:
                extract_arch.resume_in_subprocess(
                    self.args(), "out/shop", "components")
        self.assertIn("1", str(ctx.exception))

    def test_a_killed_child_raises_like_any_failure(self):
        import subprocess

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, -9)

        with unittest.mock.patch("subprocess.run", side_effect=fake_run):
            with self.assertRaises(RuntimeError):
                extract_arch.resume_in_subprocess(
                    self.args(), "out/shop", "components")


class VerdictTests(unittest.TestCase):
    """A clean probe is not a review; the tail must say which one it had."""

    @staticmethod
    def verdict(reviewed):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch("probe_readiness.check_prompt",
                           return_value=([], [], None)), \
                mock.patch("probe_readiness.open_questions", return_value=0):
            lines = []
            extract_arch.report_verdict(
                directory, out_fn=lines.append, reviewed=reviewed)
        return "\n".join(lines)

    def test_unreviewed_verdict_says_the_code_may_be_wrong(self):
        text = self.verdict(False)
        self.assertIn("review: none", text)
        self.assertIn("GENERATABLE: YES (UNREVIEWED)", text)
        self.assertIn("may be incomplete or wrong", text)

    def test_reviewed_verdict_keeps_the_plain_yes(self):
        text = self.verdict(True)
        self.assertIn("review: human review ran", text)
        self.assertIn("GENERATABLE: YES —", text)
        self.assertNotIn("(UNREVIEWED)", text)


if __name__ == "__main__":
    unittest.main()
