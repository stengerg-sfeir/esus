"""--quiet shows the plan, one result line per step, and the verdict.

The full detail always stays in run.log: quiet only changes what is echoed
to the terminal. These tests pin that contract without a model.
"""

import io
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import extract_arch  # noqa: E402
from kernel.extraction import runner, writer  # noqa: E402


class QuietModelLoadTests(unittest.TestCase):
    """--quiet redirects the C layer's loader banners to devnull.

    `verbose=False` (already set) only gates the wrapper's Python logs; the
    `ggml_metal_*` compile banners bypass it with direct fd writes, so the
    construction is wrapped in the binding's own fd-level redirect.
    """

    def test_quiet_wraps_construction_in_fd_suppression(self):
        events = []

        class Ctx:
            def __enter__(self):
                events.append("enter")
                return self

            def __exit__(self, *args):
                events.append("exit")
                return False

        with mock.patch.object(runner, "Llama",
                               side_effect=lambda **kw: events.append("Llama") or mock.MagicMock()), \
             mock.patch.object(runner, "suppress_stdout_stderr",
                               side_effect=lambda disable: events.append(("suppress", disable)) or Ctx()), \
             mock.patch.object(runner, "resolve_gpu_layers",
                               side_effect=lambda: events.append("probe") or -1):
            runner.load_model("m.gguf", quiet=True)
        self.assertEqual(events[0], ("suppress", False))
        self.assertEqual(events[-1], "exit")
        # The offload probe initialises the Metal backend (the actual source
        # of the banners), so it must run inside the redirect with the load.
        self.assertLess(events.index("enter"), events.index("probe"))
        self.assertLess(events.index("probe"), events.index("Llama"))

    def test_loud_load_constructs_without_suppression(self):
        with mock.patch.object(runner, "Llama") as llama, \
             mock.patch.object(runner, "suppress_stdout_stderr") as suppress:
            buf = io.StringIO()
            with redirect_stderr(buf):
                runner.load_model("m.gguf", quiet=False)
        suppress.assert_not_called()
        _, kwargs = llama.call_args
        self.assertFalse(kwargs["verbose"])
        self.assertIn("[model]", buf.getvalue())


class QuietLogTests(unittest.TestCase):
    def test_quiet_buffers_without_echo_but_loud_echoes(self):
        loud = writer.RunLog()
        buf = io.StringIO()
        with redirect_stderr(buf):
            loud.write("[ok] hello")
        self.assertIn("[ok] hello", buf.getvalue())
        self.assertEqual(loud.lines, ["[ok] hello"])

        quiet = writer.RunLog(quiet=True)
        buf = io.StringIO()
        with redirect_stderr(buf):
            quiet.write("[ok] hello")
        self.assertEqual(buf.getvalue(), "")
        self.assertEqual(quiet.lines, ["[ok] hello"])

    def test_quiet_results_keep_only_generations_and_totals(self):
        class Log:
            lines = [
                "[run] requirements: 10 characters",
                "[model] loaded in 1.2s",
                "[components] 2310 tokens in 76.3s (30.3 tok/s)",
                "[ok] step components: dropped flat 'x' duplicating 'y z'",
                "[write] out/library/components.json",
                "[run] 11 steps, 18409 generated tokens in 621.2s",
            ]

        shown = []
        extract_arch.print_quiet_results(Log(), out_fn=shown.append)
        self.assertEqual(shown, [Log.lines[2], Log.lines[5]])

    def test_step_plan_names_every_document_step(self):
        shown = []
        extract_arch.print_step_plan(out_fn=shown.append)
        names = [line.split(":")[0].strip("- ")
                 for line in shown[1:]]
        for expected in ("intentions", "data_models", "errors", "invariants",
                         "components", "service_contracts", "pattern_matches",
                         "interaction_adapters", "persistence_ports"):
            self.assertIn(expected, names)

    def test_step_plan_stays_silent_on_a_resume(self):
        shown = []
        extract_arch.print_step_plan(out_fn=shown.append, start="components")
        self.assertEqual(shown, [])

    def test_parser_accepts_quiet(self):
        args = extract_arch.build_parser().parse_args(
            ["--model", "m.gguf", "--output", "out/x", "--quiet"])
        self.assertTrue(args.quiet)

    def test_resume_forwards_quiet_to_the_child(self):
        import subprocess

        seen = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0)

        args = type("Args", (), {"model": "m.gguf", "context": 8192,
                                 "quiet": True})()
        with mock.patch("subprocess.run", side_effect=fake_run):
            extract_arch.resume_in_subprocess(args, "out/shop", "components")
        self.assertIn("--quiet", seen["cmd"])

    def test_resume_without_quiet_adds_no_flag(self):
        import subprocess

        seen = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0)

        args = type("Args", (), {"model": "m.gguf", "context": 8192})()
        with mock.patch("subprocess.run", side_effect=fake_run):
            extract_arch.resume_in_subprocess(args, "out/shop", "components")
        self.assertNotIn("--quiet", seen["cmd"])

    def test_resume_disables_nested_chat(self):
        """A child that defaulted to chat on a terminal would nest the loop."""
        import subprocess

        seen = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0)

        args = type("Args", (), {"model": "m.gguf", "context": 8192})()
        with mock.patch("subprocess.run", side_effect=fake_run):
            extract_arch.resume_in_subprocess(args, "out/shop", "components")
        self.assertIn("--resume-round", seen["cmd"])
        self.assertNotIn("--no-chat", seen["cmd"])


class StepProgressTests(unittest.TestCase):
    """Each step announces what it produced: `components: 9 command(s)`.

    Counts come from the documents, not token timings — the user asked how
    many intentions/entities came out. A missing document says so instead
    of reporting zero.
    """

    def test_descriptions_count_document_contents(self):
        from kernel.extraction import pipeline as pipe

        documents = {
            "intentions": ["a", "b"],
            "data_models": [{"name": "Book", "fields": [{}, {}, {}]}],
            "errors": [{"name": "E"}],
            "invariants": ["i1", "i2", "i3"],
            "components": {"facade": {"invocation": {"commands": [{}, {}]}}},
            "service_contracts": [{"service_name": "S", "methods": [{}, {}]}],
            "pattern_matches": [{}, {}, {}],
            "interaction_adapters": [{}],
            "persistence_ports": {"repositories": [{}, {}]},
        }
        self.assertEqual(pipe.describe_step("intentions", documents), "2 phrase(s)")
        self.assertEqual(pipe.describe_step("data_models", documents),
                         "1 entities, 3 field(s)")
        self.assertEqual(pipe.describe_step("errors", documents), "1 error(s)")
        self.assertEqual(pipe.describe_step("invariants", documents), "3 invariant(s)")
        self.assertEqual(pipe.describe_step("components", documents), "2 command(s)")
        self.assertEqual(pipe.describe_step("service_contracts", documents),
                         "1 service(s), 2 method(s)")
        self.assertEqual(pipe.describe_step("errors_repair", documents),
                         "1 error(s), 1 service(s) after repair")
        self.assertEqual(pipe.describe_step("pattern_matches", documents), "3 item(s)")
        self.assertEqual(pipe.describe_step("interaction_adapters", documents),
                         "1 adapter(s)")
        self.assertEqual(pipe.describe_step("persistence_ports", documents),
                         "2 repositor(y/ies)")

    def test_missing_documents_say_so(self):
        from kernel.extraction import pipeline as pipe

        self.assertEqual(pipe.describe_step("components", {}), "no usable document")
        self.assertEqual(pipe.describe_step("components", {"components": None}),
                         "no usable document")
        self.assertEqual(pipe.describe_step("errors_repair", {}), "no usable documents")

    def test_gui_facade_without_invocation_is_a_surface_not_a_failure(self):
        from kernel.extraction import pipeline as pipe

        body = {"facade": {"type": "gui", "technology": "pyimgui",
                           "invocation": None},
                "crud_services": [{}, {}, {}]}
        self.assertEqual(pipe.describe_step("components", {"components": body}),
                         "3 crud service(s), gui facade (no CLI surface)")

    def test_run_calls_progress_after_each_step_in_order(self):
        from kernel.extraction import pipeline as pipe

        class Log:
            def write(self, message):
                pass

        seen = []
        runner_pipeline = pipe.Pipeline(
            llm=None, log=Log(),
            progress_fn=lambda name, summary: seen.append((name, summary)))
        bodies = {
            "_step_intentions": ("intentions", ["a"]),
            "_step_data_models": ("data_models", []),
            "_step_errors": ("errors", []),
            "_step_invariants": ("invariants", []),
            "_step_components": (
                "components", {"facade": {"invocation": {"commands": []}}}),
            "_step_contracts": ("service_contracts", []),
            "_step_patterns": ("pattern_matches", []),
            "_step_adapters": ("interaction_adapters", []),
            "_step_persistence": (
                "persistence_ports", {"repositories": []}),
        }
        for method, (key, body) in bodies.items():
            runner_pipeline.__dict__[method] = (
                lambda key=key, body=body: lambda req=None: runner_pipeline.documents.update({key: body}))()
        runner_pipeline._repair_errors = lambda: runner_pipeline.documents.update(
            {"errors": [], "service_contracts": []})
        runner_pipeline.run("requirements")
        self.assertEqual([name for name, _ in seen],
                         ["intentions", "data_models", "errors", "invariants",
                          "components", "service_contracts", "errors_repair",
                          "pattern_matches", "interaction_adapters",
                          "persistence_ports"])
        self.assertEqual(seen[0], ("intentions", "1 phrase(s)"))

    def test_parse_diagnostics_go_through_the_log(self):
        from kernel.extraction import pipeline as pipe

        class Log:
            def __init__(self):
                self.lines = []

            def write(self, message):
                self.lines.append(message)

        log = Log()
        buf = io.StringIO()
        with redirect_stderr(buf):
            self.assertIsNone(pipe._parse_document("{nope", "components", log))
        self.assertEqual(buf.getvalue(), "")
        self.assertEqual(len(log.lines), 1)
        self.assertIn("JSON error", log.lines[0])


if __name__ == "__main__":
    unittest.main()
