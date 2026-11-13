"""The one-letter domain triage that can skip extraction."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import extract_arch  # noqa: E402
from kernel.extraction import triage  # noqa: E402
from kernel.extraction.runner import StepResult  # noqa: E402
from kernel.extraction.writer import RunLog  # noqa: E402


class ClassifyTests(unittest.TestCase):
    def test_the_prompt_carries_the_requirements_and_the_three_answers(self):
        prompt = triage.prompt_for("Print hello.")
        self.assertIn("Print hello.", prompt)
        self.assertIn("domain data model", prompt)
        self.assertIn("Y", prompt)
        self.assertIn("N", prompt)
        self.assertIn("U", prompt)

    def test_an_answer_is_one_of_the_three_letters(self):
        for text, expected in (("N", "N"), (" y\n", "Y"), ("maybe", "U"),
                               ("", "U")):
            with mock.patch.object(
                    triage.runner, "generate",
                    return_value=StepResult("triage", text, 2, 0.2, "stop")):
                result = triage.classify(None, "Print hello.")
            self.assertEqual(result.answer, expected)
            self.assertEqual(result.tokens, 2)

    def test_the_grammar_allows_only_one_letter(self):
        self.assertIn('root ::= "Y" | "N" | "U"', triage.GRAMMAR)

    def test_the_shortcut_writes_the_minimal_documents(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            log = RunLog(path / "run.log", quiet=True)
            args = mock.Mock(quiet=True, check=False)
            outcome = triage.TriageResult("N", 0.2, 2, 150)
            code = extract_arch.triage_shortcut(
                path, "Print hello.", log, args, outcome)
            self.assertEqual(code, 0)
            for name in ("components", "data_models", "errors", "intentions",
                         "invariants", "service_contracts",
                         "interaction_adapters", "pattern_matches"):
                self.assertTrue((path / f"{name}.json").is_file(), name)
            self.assertTrue((path / "requirements.txt").is_file())
            components = (path / "components.json").read_text(encoding="utf-8")
            self.assertIn('"required": false', components)


if __name__ == "__main__":
    unittest.main()
