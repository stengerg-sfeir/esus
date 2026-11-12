"""`main.py`: one prompt in, extract then generate, quiet, with logs kept.

The wrapper reads the two scripts' output instead of trusting exit codes
(`extract_arch.py` exits 0 on `GENERATABLE: NO`), hides that output behind a
spinner, and saves all of it in the output folder. Each test pins a decision,
failure paths included. The pipeline tests run fake scripts, so no model or
server is needed.
"""

import http.server
import io
import os
import sys
import tempfile
import textwrap
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main  # noqa: E402

YES_UNREVIEWED = textwrap.dedent("""\
    ==== SUMMARY ====
    review: none — the documents are unreviewed
    blockers: 0, open tie(s): 0
    GENERATABLE: YES (UNREVIEWED) — `generator.py` can run, but no human review ran
    """)
NO_WITH_REASONS = textwrap.dedent("""\
    ==== SUMMARY ====
    review: none — the documents are unreviewed
    blockers: 2, open tie(s): 1
    GENERATABLE: NO — `generator.py` will refuse this output
      - [ignored_cli_option] interaction_adapters: borrow: --book-id is ignored
      - [unbacked_command] components.facade.invocation: 'overdue' has no method
    """)


class VerdictTests(unittest.TestCase):
    def test_an_unreviewed_yes(self):
        verdict = main.parse_verdict(YES_UNREVIEWED)
        self.assertEqual(
            (verdict["generatable"], verdict["unreviewed"],
             verdict["blockers"], verdict["ties"], verdict["reasons"]),
            (True, True, 0, 0, []))

    def test_a_reviewed_yes(self):
        verdict = main.parse_verdict(
            "==== SUMMARY ====\nblockers: 0, open tie(s): 0\n"
            "GENERATABLE: YES — `generator.py` can run on this output\n")
        self.assertEqual((verdict["generatable"], verdict["unreviewed"]),
                         (True, False))

    def test_a_no_carries_its_blockers(self):
        verdict = main.parse_verdict(NO_WITH_REASONS)
        self.assertFalse(verdict["generatable"])
        self.assertEqual((verdict["blockers"], verdict["ties"]), (2, 1))
        self.assertEqual(verdict["reasons"], [
            "[ignored_cli_option] interaction_adapters: borrow: --book-id is ignored",
            "[unbacked_command] components.facade.invocation: 'overdue' has no method"])

    def test_only_the_last_summary_counts(self):
        verdict = main.parse_verdict(NO_WITH_REASONS + "\nchat: round 2\n"
                                     + YES_UNREVIEWED)
        self.assertTrue(verdict["generatable"])
        self.assertEqual(verdict["reasons"], [])

    def test_no_summary_is_no_verdict(self):
        self.assertIsNone(main.parse_verdict("[run] 9 steps\nnothing else\n"))


class ProgressTests(unittest.TestCase):
    def test_finished_steps_are_counted(self):
        done = set()
        self.assertEqual(
            main.extract_progress("[data_models] 1296 tokens in 37.5s (34 tok/s)", done),
            "1 step done")
        main.extract_progress("[ok] step patterns: 49 item(s)", done)
        self.assertEqual(main.extract_progress(
            "[errors] 701 tokens in 20.5s", done), "3 steps done")

    def test_a_step_is_not_counted_twice(self):
        done = set()
        main.extract_progress("[errors] 7 tokens in 1s", done)
        self.assertEqual(main.extract_progress("[errors] 9 tokens in 2s", done),
                         "1 step done")

    def test_other_lines_are_ignored(self):
        self.assertIsNone(main.extract_progress("[write] out/x/components.json", set()))


class CountMethodsTests(unittest.TestCase):
    def test_methods_model_bodies_and_stubs_are_counted(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "repositories.py").write_text(textwrap.dedent('''\
                class BookRepository:
                    def __init__(self, store):
                        self._store = store

                    def read_one(self, book_id):
                        """Reads one. [crud:read_one]"""
                        return None

                    def _helper(self):
                        raise NotImplementedError("private, not counted")
                '''))
            (Path(directory) / "services.py").write_text(textwrap.dedent('''\
                class BookService:
                    def create_book(self, title):
                        """Creates. [llm-written by server - review]"""
                        return title

                    def delete_book(self, book_id):
                        """Deletes."""
                        raise NotImplementedError(
                            "BookService.delete_book: stub")
                '''))
            self.assertEqual(main.count_methods(directory), (3, 1, 1))

    def test_a_missing_package_counts_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(main.count_methods(directory), (0, 0, 0))


class GeneratedSummaryTests(unittest.TestCase):
    def test_a_package_is_described_by_its_methods(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "services.py").write_text(
                "class S:\n    def a(self):\n        return 1\n")
            self.assertEqual(main.generated_summary(directory),
                             (True, "1 methods, 0 written by the model "
                                    "(provisional), 0 stubs left"))

    def test_an_empty_architecture_gives_a_single_app_file(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "app.py").write_text("print('hi')\n")
            ok, detail = main.generated_summary(directory)
            self.assertTrue(ok)
            self.assertIn("app.py written directly from the requirements", detail)

    def test_nothing_generated_is_a_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(main.generated_summary(directory),
                             (False, "the generator produced no program files"))


class NamingTests(unittest.TestCase):
    def test_the_default_output_drops_the_prompt_prefix(self):
        self.assertEqual(main.default_output("prompts/initial/prompt_hello_world.txt"),
                         ROOT / "out" / "hello_world")
        self.assertEqual(main.default_output("elsewhere/my_spec.txt"),
                         ROOT / "out" / "my_spec")

    def test_durations(self):
        self.assertEqual([main.duration(s) for s in (5, 75, 3725)],
                         ["5s", "1m 15s", "1h 02m"])


class DisplayTests(unittest.TestCase):
    def test_plain_output_has_no_escape_codes(self):
        out = io.StringIO()
        display = main.Display(out, tty=False)
        display.begin("Extract architecture")
        display.end(True, "9/9 steps")
        display.begin("Generate code")
        display.end(False, "exited with 2")
        text = out.getvalue()
        self.assertNotIn("\033", text)
        self.assertIn("[ ok ] Extract architecture", text)
        self.assertIn("[ KO ] Generate code", text)
        self.assertIn("9/9 steps", text)

    def test_a_terminal_gets_a_rolling_spinner_and_a_restored_cursor(self):
        out = io.StringIO()
        display = main.Display(out, tty=True, color=False, interval=0.01)
        display.begin("Extract architecture")
        display.set_detail("3/9 steps")
        time.sleep(0.15)
        display.end(True, "done")
        text = out.getvalue()
        self.assertIn("\r\033[K", text)
        self.assertIn("Extract architecture  3/9 steps", text)
        self.assertGreaterEqual(len({c for c in text if c in "|/-\\"}), 2)
        self.assertTrue(text.rstrip().endswith("done"))
        self.assertIn("\033[?25h", text)

    def test_color_marks_ok_green_and_ko_red(self):
        out = io.StringIO()
        display = main.Display(out, tty=False, color=True)
        display.begin("a"), display.end(True)
        display.begin("b"), display.end(False)
        self.assertIn("\033[32;1mok", out.getvalue())
        self.assertIn("\033[31;1mKO", out.getvalue())


class FakeHealth(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"status":"ok"}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class CheckInputsTests(unittest.TestCase):
    def prompt(self, directory, text="Make a thing."):
        path = Path(directory) / "prompt.txt"
        path.write_text(text, encoding="utf-8")
        return path

    def test_a_missing_or_empty_prompt_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            ok, detail = main.check_inputs(Path(directory) / "no.txt", "server", "x")
            self.assertFalse(ok)
            self.assertIn("not found", detail)
            ok, detail = main.check_inputs(self.prompt(directory, "  \n"), "server", "x")
            self.assertFalse(ok)
            self.assertIn("empty", detail)

    def test_an_unreachable_server_says_how_to_fix_it(self):
        with tempfile.TemporaryDirectory() as directory:
            ok, detail = main.check_inputs(self.prompt(directory), "server",
                                           "http://127.0.0.1:9")
            self.assertFalse(ok)
            self.assertIn("not reachable", detail)
            self.assertIn("--model PATH.gguf", detail)

    def test_a_ready_server_is_accepted(self):
        server = http.server.HTTPServer(("127.0.0.1", 0), FakeHealth)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                url = f"http://127.0.0.1:{server.server_port}"
                ok, detail = main.check_inputs(self.prompt(directory), "server", url)
                self.assertTrue(ok)
                self.assertIn(url, detail)
        finally:
            server.shutdown()

    def test_a_model_file_must_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            ok, detail = main.check_inputs(self.prompt(directory),
                                           str(Path(directory) / "m.gguf"), "x")
            self.assertFalse(ok)
            self.assertIn("model file not found", detail)


def child(code):
    return [sys.executable, "-u", "-c", textwrap.dedent(code)]


class RunCommandTests(unittest.TestCase):
    def run_it(self, code, **kwargs):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "child.log"
            lines, chunks = [], []
            result = main.run_command(child(code), log, lines.append,
                                      echo=chunks.append, **kwargs)
            return result, lines, chunks, log.read_text("utf-8")

    def test_everything_the_child_prints_is_logged_and_streamed(self):
        (code, tail), lines, _chunks, log = self.run_it(
            "import sys; print('one'); sys.stderr.write('warn\\n'); print('two')")
        self.assertEqual(code, 0)
        self.assertEqual(lines, ["one", "warn", "two"])
        self.assertTrue(log.startswith("$ "))
        for line in ("one", "warn", "two"):
            self.assertIn(line, log)

    def test_the_exit_code_comes_back(self):
        (code, tail), *_ = self.run_it("import sys; print('boom'); sys.exit(3)")
        self.assertEqual(code, 3)
        self.assertEqual(tail[-1], "boom")

    def test_a_prompt_without_a_newline_is_echoed_when_it_arrives(self):
        (code, tail), _lines, chunks, _log = self.run_it(
            "print('question', end='')")
        self.assertIn("question", "".join(chunks))
        self.assertEqual(tail[-1], "question")

    def test_interrupting_stops_the_child(self):
        with tempfile.TemporaryDirectory() as directory:
            seen = []

            def on_line(line):
                seen.append(line)
                raise KeyboardInterrupt

            with self.assertRaises(KeyboardInterrupt):
                main.run_command(
                    child("import os, time; print(os.getpid(), flush=True); "
                          "time.sleep(60)"),
                    Path(directory) / "log", on_line)
            pid = int(seen[0])
            for _ in range(60):
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.1)
            else:
                self.fail("the child is still running after the interrupt")


FAKE_EXTRACT = '''
import sys
for line in (
    "[intentions] 541 tokens in 15.3s",
    "[data_models] 1296 tokens in 37.5s",
    "[ok] step patterns: 49 item(s)",
    "[run] 3 steps, 2000 generated tokens in 61.0s",
):
    print(line)
print({summary!r})
sys.exit({code})
'''
FAKE_GENERATE = '''
import sys, pathlib
output = pathlib.Path(sys.argv[1])
print("llm: 2 refused stub(s) - the model writes them")
print("llm: BookService.create_book ...")
print("llm: BookService.delete_book ...")
if {nothing}:
    sys.exit({code})
(output / "generated").mkdir(parents=True, exist_ok=True)
(output / "generated" / "services.py").write_text(
    "class BookService:\\n"
    "    def create_book(self, t):\\n"
    "        \\"\\"\\"x [llm-written by server - review]\\"\\"\\"\\n"
    "        return t\\n"
    "    def delete_book(self, i):\\n"
    "        raise NotImplementedError('stub')\\n")
sys.exit({code})
'''


class PipelineTests(unittest.TestCase):
    """The whole wrapper on fake children, so only its own logic is tested."""

    def run_pipeline(self, extract_summary=YES_UNREVIEWED, extract_code=0,
                     generate_code=0, review=False, verbose=False,
                     writes_nothing=False):
        directory = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, directory, True)
        base = Path(directory)
        (base / "prompt.txt").write_text("Make a thing.", encoding="utf-8")
        (base / "fake_extract.py").write_text(
            FAKE_EXTRACT.format(summary=extract_summary, code=extract_code))
        (base / "fake_generate.py").write_text(
            FAKE_GENERATE.format(code=generate_code, nothing=writes_nothing))
        out = io.StringIO()
        display = main.Display(out, tty=False)
        args = types.SimpleNamespace(
            prompt=str(base / "prompt.txt"), output=str(base / "out"),
            model="server", server_url="http://x", review=review,
            verbose=verbose)
        seen = {}

        def extract_command(prompt, output, model, review):
            seen["review"] = review
            return [sys.executable, "-u", str(base / "fake_extract.py")]

        with mock.patch.object(main, "check_inputs",
                               return_value=(True, "model: fake")), \
                mock.patch.object(main, "build_extract_command", extract_command), \
                mock.patch.object(main, "build_generate_command",
                                  lambda output, model: [
                                      sys.executable, "-u",
                                      str(base / "fake_generate.py"), str(output)]):
            code = main.run_pipeline(args, display)
        return code, out.getvalue(), base / "out", seen

    def test_a_full_run_reports_every_step_and_keeps_the_logs(self):
        code, text, output, seen = self.run_pipeline()
        self.assertEqual(code, 0)
        for line in ("[ ok ] Check inputs", "[ ok ] Extract architecture",
                     "[ ok ] Readiness", "[ ok ] Generate code"):
            self.assertIn(line, text)
        self.assertIn("3 steps, 2,000 tokens", text)
        self.assertIn("0 blockers (unreviewed", text)
        self.assertIn("2 methods, 1 written by the model (provisional), 1 stubs left",
                      text)
        self.assertNotIn("[intentions]", text)       # the child's output is hidden
        self.assertIn("[intentions] 541 tokens",
                      (output / "logs" / "extract.log").read_text("utf-8"))
        self.assertIn("llm: BookService.create_book",
                      (output / "logs" / "generate.log").read_text("utf-8"))
        self.assertIn("Done in", (output / "logs" / "summary.txt").read_text("utf-8"))
        self.assertFalse(seen["review"])

    def test_review_runs_the_extraction_in_chat_mode(self):
        with mock.patch.object(sys, "stdout", io.StringIO()):
            _code, _text, _output, seen = self.run_pipeline(review=True)
        self.assertTrue(seen["review"])

    def test_verbose_shows_the_scripts_output(self):
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout):
            code, _text, _output, _seen = self.run_pipeline(verbose=True)
        self.assertEqual(code, 0)
        self.assertIn("[intentions] 541 tokens", stdout.getvalue())

    def test_a_failed_extraction_stops_with_ko_and_the_log_path(self):
        code, text, output, _seen = self.run_pipeline(extract_code=1)
        self.assertEqual(code, 1)
        self.assertIn("[ KO ] Extract architecture", text)
        self.assertIn("full log:", text)
        self.assertNotIn("Generate code", text)
        self.assertFalse((output / "generated").exists())

    def test_a_no_verdict_stops_even_though_the_exit_code_is_zero(self):
        code, text, output, _seen = self.run_pipeline(
            extract_summary=NO_WITH_REASONS)
        self.assertEqual(code, 1)
        self.assertIn("[ KO ] Readiness", text)
        self.assertIn("2 blocker(s), 1 open tie(s)", text)
        self.assertIn("[ignored_cli_option]", text)
        self.assertIn("--review", text)
        self.assertNotIn("Generate code", text)

    def test_a_missing_verdict_is_a_ko(self):
        code, text, _output, _seen = self.run_pipeline(extract_summary="")
        self.assertEqual(code, 1)
        self.assertIn("no verdict", text)

    def test_a_failed_generation_is_exit_two(self):
        code, text, output, _seen = self.run_pipeline(generate_code=1)
        self.assertEqual(code, 2)
        self.assertIn("[ KO ] Generate code", text)
        self.assertIn("generate.log", text)

    def test_a_generator_that_writes_no_program_is_a_ko(self):
        code, text, _output, _seen = self.run_pipeline(writes_nothing=True)
        self.assertEqual(code, 2)
        self.assertIn("[ KO ] Generate code", text)
        self.assertIn("produced no program files", text)

    def test_bad_inputs_are_exit_three_and_leave_no_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            args = types.SimpleNamespace(
                prompt=str(Path(directory) / "missing.txt"),
                output=str(Path(directory) / "out"), model="server",
                server_url="http://127.0.0.1:9", review=False, verbose=False)
            out = io.StringIO()
            code = main.run_pipeline(args, main.Display(out, tty=False))
            self.assertEqual(code, 3)
            self.assertIn("[ KO ] Check inputs", out.getvalue())
            self.assertFalse((Path(directory) / "out").exists())


class FailTests(unittest.TestCase):
    def render(self, reasons):
        out = io.StringIO()
        main.fail(main.Display(out, tty=False), "blocked", reasons, "x.log")
        return out.getvalue()

    def test_up_to_five_reasons_are_listed_with_the_log(self):
        text = self.render([f"reason {n}" for n in range(5)])
        for n in range(5):
            self.assertIn(f"reason {n}", text)
        self.assertNotIn("more", text)
        self.assertIn("full log: x.log", text)

    def test_more_than_five_say_how_many_are_hidden(self):
        text = self.render([f"reason {n}" for n in range(8)])
        self.assertIn("reason 4", text)
        self.assertNotIn("reason 5", text)
        self.assertIn("... and 3 more (see the log)", text)


class MainTests(unittest.TestCase):
    def test_an_interrupt_is_exit_130(self):
        with mock.patch.object(main, "run_pipeline", side_effect=KeyboardInterrupt), \
                mock.patch.object(sys, "stdout", io.StringIO()) as out:
            self.assertEqual(main.main(["prompt.txt"]), 130)
            self.assertIn("interrupted", out.getvalue())

    def test_pipeline_environment_uses_the_reviewed_extraction_flags(self):
        env = main.pipeline_env("http://x")
        self.assertEqual(env["LLAMA_SERVER_URL"], "http://x")
        self.assertEqual(env["ESUS_COMPONENTS_SPLIT"], "1")
        self.assertEqual(env["ESUS_MECHANICAL_SCHEMA"], "1")
        self.assertEqual(env["ESUS_MECHANICAL_SERVICES"], "1")

    def test_the_commands_use_the_requested_model_and_mode(self):
        extract = main.build_extract_command(
            Path("p.txt"), Path("out/x"), "server", review=False)
        self.assertIn("--no-chat", extract)
        self.assertNotIn("--chat", extract)
        self.assertEqual(extract[extract.index("--model") + 1], "server")
        self.assertIn("--chat", main.build_extract_command(
            Path("p.txt"), Path("out/x"), "m.gguf", review=True))
        generate = main.build_generate_command(Path("out/x"), "server")
        self.assertEqual(generate[generate.index("--model") + 1], "server")
        self.assertIn("--stub-context", generate)
        self.assertIn("exact", generate)
        self.assertIn("--reuse-reviewed-bodies", generate)


if __name__ == "__main__":
    unittest.main()
