"""Chat mode: one entry point, probe, ask what needs a human, re-probe.

`--chat` refuses piped requirements (questions arrive over stdin — a pipe
would EOF every answer into a silent skip), resolves requirements from file
or terminal, runs each review only when its questions exist, and reports
structural blockers without asking: no typed answer fixes those.
"""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import extract_arch  # noqa: E402


class ResolveRequirementsTests(unittest.TestCase):
    def args(self, **overrides):
        values = {"requirements": None}
        values.update(overrides)
        return type("Args", (), values)()

    def test_stdin_requirements_are_read(self):
        with mock.patch.object(sys.stdin, "read", return_value="  words  "):
            self.assertEqual(
                extract_arch.resolve_requirements(self.args()), "words")

    def test_empty_stdin_is_an_error_not_an_empty_run(self):
        with mock.patch.object(sys.stdin, "read", return_value="   "):
            with io.StringIO() as buffer, redirect_stdout(buffer):
                self.assertIsNone(extract_arch.resolve_requirements(self.args()))

    def test_a_requirements_file_is_read(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prompt.txt"
            path.write_text("  words  ", encoding="utf-8")
            self.assertEqual(
                extract_arch.resolve_requirements(self.args(requirements=str(path))),
                "words")

    def test_a_missing_requirements_file_is_an_error(self):
        with io.StringIO() as buffer, redirect_stdout(buffer):
            self.assertIsNone(
                extract_arch.resolve_requirements(self.args(requirements="/nope.txt")))


class ChatFlowTests(unittest.TestCase):
    def flow(self, directory, ties=0, pairs=(), blockers=(), tie_run=None,
             alias_run=None, contracts=(), contract_run=None,
             duplicates=(), routes=(), slots=(), slot_run=None,
             surface_run=None):
        from kernel.consistency.report import Finding

        lines = []
        with mock.patch("probe_readiness.check_prompt") as checked, \
             mock.patch("probe_readiness.open_questions") as opened, \
             mock.patch("review_aliases.collect_questions") as collected, \
             mock.patch("review_contracts.collect_contracts") as contract_collected, \
             mock.patch("review_slots.collect_slots") as slot_collected, \
             mock.patch("review_surface.collect_duplicates") as duplicate_collected, \
             mock.patch("review_surface.collect_routes") as route_collected:
            checked.return_value = (
                [Finding("warning", "uncovered_field", b) for b in blockers], [], None)
            opened.return_value = ties
            collected.return_value = (list(pairs), {})
            contract_collected.return_value = (list(contracts), {})
            slot_collected.return_value = (list(slots), {})
            duplicate_collected.return_value = (list(duplicates), {})
            route_collected.return_value = (list(routes), {})
            remaining = extract_arch.chat_flow(
                directory, out_fn=lines.append,
                tie_runner=tie_run, alias_runner=alias_run,
                slot_runner=slot_run, surface_runner=surface_run,
                contract_runner=contract_run)
        return remaining, lines

    def test_a_clean_output_asks_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            remaining, lines = self.flow(directory)
            self.assertEqual(remaining, [])
            self.assertTrue(any("0 blocker(s) remain" in line for line in lines))

    def test_ties_run_only_the_tie_review(self):
        asked = []

        def tie_runner(path):
            asked.append(("ties", path))
            return 1, 1

        with tempfile.TemporaryDirectory() as directory:
            remaining, _ = self.flow(directory, ties=2, tie_run=tie_runner,
                                     alias_run=lambda p: asked.append(("aliases", p)) or (0, 0))
            self.assertEqual(asked, [("ties", directory)])
            self.assertEqual(remaining, [])

    def test_pairs_run_only_the_alias_review(self):
        asked = []

        def run_aliases(path):
            asked.append(("aliases", path))
            return 1, 1

        with tempfile.TemporaryDirectory() as directory:
            remaining, _ = self.flow(
                directory,
                pairs=[{"action": "a", "field": "f", "suggestions": []}],
                tie_run=lambda p: asked.append(("ties", p)) or (0, 0),
                alias_run=run_aliases)
            self.assertEqual(asked, [("aliases", directory)])
            self.assertEqual(remaining, [])

    def test_a_stranded_flag_runs_the_surface_review(self):
        asked = []

        def run_surface(path):
            asked.append(("surface", path))
            return 1, 1

        with tempfile.TemporaryDirectory() as directory:
            remaining, lines = self.flow(
                directory,
                routes=[{"command": "member", "subcommand": "list",
                         "flag": "active_only"}],
                surface_run=run_surface)
            self.assertEqual(asked, [("surface", directory)])
            self.assertEqual(remaining, [])
            self.assertTrue(any("surface node/flag(s) need a human" in line
                                for line in lines))

    def test_slots_run_before_surface_routes(self):
        """A stub method becomes a route candidate only after its slot
        answer; asking the surface review first offers a false drop-only."""
        asked = []

        def run_slots(path):
            asked.append("slots")
            return 1, 1

        def run_surface(path):
            asked.append("surface")
            return 1, 1

        with tempfile.TemporaryDirectory() as directory:
            remaining, _ = self.flow(
                directory,
                slots=[{"holder": "MemberRepository",
                        "method": "find_active_members"}],
                routes=[{"command": "member", "subcommand": "list",
                         "flag": "active_only"}],
                slot_run=run_slots, surface_run=run_surface)
            self.assertEqual(asked, ["slots", "surface"])
            self.assertEqual(remaining, [])

    def test_contract_questions_run_the_contract_review(self):
        asked = []

        def run_contracts(path):
            asked.append(("contracts", path))
            return 1, 1

        with tempfile.TemporaryDirectory() as directory:
            remaining, lines = self.flow(
                directory, contracts=[{"holder": "S", "method": "m"}],
                contract_run=run_contracts)
            self.assertEqual(asked, [("contracts", directory)])
            self.assertEqual(remaining, [])
            self.assertTrue(any("method contract(s) need a human" in line
                                for line in lines))

    def test_structural_blockers_are_reported_never_asked(self):
        asked = []
        with tempfile.TemporaryDirectory() as directory:
            remaining, lines = self.flow(
                directory, blockers=["surface omits it"],
                tie_run=lambda p: asked.append(1) or (0, 0),
                alias_run=lambda p: asked.append(1) or (0, 0))
            self.assertEqual(asked, [])
            self.assertEqual(len(remaining), 1)
            self.assertTrue(any("surface omits it" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
