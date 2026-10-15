"""Backfilling grounded flags heals old documents without a model call.

Applies the pipeline's own repair to an archived components.json and writes
it back byte-identical when nothing is grounded (same indent and trailing
newline as the writer, so a no-op leaves the file untouched). A missing
requirements.txt or components.json is an error, not a guess.
"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backfill_flags import backfill  # noqa: E402


def setup(directory, components, requirements, models):
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    (path / "components.json").write_text(
        json.dumps({"components": components}, indent=2) + "\n", encoding="utf-8")
    (path / "requirements.txt").write_text(requirements, encoding="utf-8")
    (path / "data_models.json").write_text(
        json.dumps({"data_models": models}, indent=2) + "\n", encoding="utf-8")
    return str(path)


def surface(options):
    return {
        "facade": {"type": "cli", "technology": "click",
                   "invocation": {"commands": [
                       {"name": "product", "options": [],
                        "subcommands": [{"name": "add", "options": options}]}]}}
    }


def option(name):
    return {"name": name, "type": "str"}


class BackfillTests(unittest.TestCase):
    MODELS = [{"name": "Product", "fields": [{"name": "sku", "type": "string"}]}]

    def test_a_grounded_flag_is_written_back(self):
        with tempfile.TemporaryDirectory() as directory:
            out = setup(directory, surface([]),
                        "Run `product add --sku`.", self.MODELS)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(backfill(out), 1)
            options = json.loads((Path(out) / "components.json").read_text("utf-8")
                                 )["components"]["facade"]["invocation"]["commands"][0]
            names = [o["name"] for o in options["subcommands"][0]["options"]]
            self.assertIn("--sku", names)

    def test_a_second_run_is_a_no_op(self):
        """Idempotent: healing once heals, and the file is then untouched."""
        with tempfile.TemporaryDirectory() as directory:
            out = setup(directory, surface([option("--sku")]),
                        "Run `product add --sku`.", self.MODELS)
            before = (Path(out) / "components.json").read_bytes()
            with redirect_stdout(io.StringIO()):
                self.assertEqual(backfill(out), 0)
            self.assertEqual((Path(out) / "components.json").read_bytes(), before)

    def test_nothing_grounded_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            out = setup(directory, surface([]),
                        "Run `product add --frob`.", self.MODELS)
            before = (Path(out) / "components.json").read_bytes()
            with redirect_stdout(io.StringIO()):
                self.assertEqual(backfill(out), 0)
            self.assertEqual((Path(out) / "components.json").read_bytes(), before)

    def test_missing_requirements_is_an_error_not_a_guess(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "components.json").write_text('{"components": {}}', encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(backfill(str(path)), 0)


if __name__ == "__main__":
    unittest.main()
