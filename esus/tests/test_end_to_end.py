"""The attended loop as one chain, with the model stubbed out.

Every unit suite passed while a real session lost `decisions.json` — the
contracts *between* components were untested: what survives a write cycle,
what a review answers, what the probe then reports. These tests run the
real loader, checker, probe, repairs and reviews against temp output dirs,
stubbing only the model (`input_fn`) and, where noted, nothing at all.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.consistency.loader import load_documents  # noqa: E402
from kernel.consistency.report import Report  # noqa: E402
from kernel.extraction import writer  # noqa: E402
from probe_readiness import check_prompt  # noqa: E402
from review_aliases import run_review  # noqa: E402


def write_doc(directory, name, body):
    path = Path(directory) / f"{name}.json"
    path.write_text(json.dumps({name: body}, indent=2) + "\n", encoding="utf-8")
    return path


def shop_documents():
    """A complete, probe-clean-except-one-pair Shop (see module docstring)."""
    return {
        "intentions": ["Sell books"],
        "invariants": [],
        "data_models": [
            {"name": "Book", "fields": [
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "title", "type": "string"},
                {"name": "available_copies", "type": "int"}]},
            {"name": "Author", "fields": [
                {"name": "id", "type": "int", "primary_key": True}]},
        ],
        "errors": [{"name": "BookNotFoundError", "base": "LookupError",
                    "description": "no such book"}],
        "components": {
            "facade": {"type": "cli", "technology": "argparse",
                       "invocation": {"commands": [
                           {"name": "book", "options": [],
                            "subcommands": [
                                {"name": "add", "options": [
                                    {"name": "--copies", "type": "int",
                                     "required": True, "default": None}]}]}]}},
            "persistence": {"required": False, "technology": "none"},
            "external_access": [],
            "crud_services": [{"entity": "Book", "operations": ["create"]}],
        },
        "service_contracts": [
            {"service_name": "BookRepo", "methods": [
                {"name": "create_book", "description": "Create a book.",
                 "params": [{"name": "book", "type": "Book"}],
                 "return_type": "Book", "raises": []},
                {"name": "read_book", "description": "Read a book.",
                 "params": [{"name": "id", "type": "int"}],
                 "return_type": "Book", "raises": ["BookNotFoundError"]}]}],
        "pattern_matches": [],
        "interaction_adapters": [
            {"action_name": "add_book", "target_service": "BookRepo",
             "target_method": "create_book",
             "input_fields": [
                 {"field_name": "copies", "target_param": "book",
                  "transform": "DIRECT", "lookup_entity": None,
                  "required": True}]}],
    }


class AuxiliaryFilesSurviveTests(unittest.TestCase):
    """The write cycle must never touch non-document files.

    A session once lost `decisions.json` with every suite green: nothing
    asserted what `write_documents`/`clear_documents` leave alone. Human
    answers, run logs and the archived requirements are not documents and
    must round-trip byte-identical.
    """

    def test_write_cycle_preserves_answers_logs_and_requirements(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            for name, content in (
                ("decisions.json", '{"decisions": []}'),
                ("field_aliases.json", '{"aliases": []}'),
                ("requirements.txt", "words"),
                ("run.log", "[run] x"),
            ):
                (path / name).write_text(content, encoding="utf-8")
            before = {name: (path / name).read_bytes()
                      for name in ("decisions.json", "field_aliases.json",
                                   "requirements.txt", "run.log")}
            writer.write_documents(
                path, {"components": {"facade": {"type": "cli"}}})
            for name, content in before.items():
                self.assertEqual((path / name).read_bytes(), content,
                                 f"{name} must survive a write cycle")

    def test_second_write_cycle_is_stable(self):
        """Two consecutive writes leave prior documents and files alone."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "decisions.json").write_text("{}", encoding="utf-8")
            writer.write_documents(path, {"components": {"a": 1}})
            writer.write_documents(path, {"components": {"a": 1}})
            self.assertEqual((path / "decisions.json").read_text(encoding="utf-8"),
                             "{}")


class AttendedLoopTests(unittest.TestCase):
    """Probe reports, review answers, probe confirms — on real documents."""

    def setup_dir(self, directory):
        for name, body in shop_documents().items():
            write_doc(directory, name, body)
        Path(directory, "requirements.txt").write_text(
            "Run `book add --copies`.", encoding="utf-8")
        return str(directory)

    def blocker_rules(self, output_dir):
        blockers, _, _ = check_prompt("shop", output_dir)
        return [finding.rule for finding in blockers]

    def test_probe_review_probe_closes_the_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            out = self.setup_dir(directory)
            before = self.blocker_rules(out)
            self.assertIn("unknown_model_field", before)
            asked, answered = run_review(
                out, input_fn=lambda _: "available_copies",
                out_fn=lambda _: None)
            self.assertEqual((asked, answered), (1, 1))
            after = self.blocker_rules(out)
            self.assertNotIn("unknown_model_field", after)
            self.assertNotIn("uncovered_field", after)

    def test_loader_sees_the_reviewed_documents(self):
        """The checker judges what the review wrote, not a stale copy."""
        with tempfile.TemporaryDirectory() as directory:
            out = self.setup_dir(directory)
            run_review(out, input_fn=lambda _: "available_copies",
                       out_fn=lambda _: None)
            documents = load_documents(out, Report("shop"))
            adapters = documents.get("interaction_adapters")
            self.assertEqual(adapters[0]["input_fields"][0]["field_name"],
                             "available_copies")
            self.assertNotIn("interaction_adapters", documents.missing)


if __name__ == "__main__":
    unittest.main()
