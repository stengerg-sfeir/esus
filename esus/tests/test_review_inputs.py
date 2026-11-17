"""The preserved review inputs keep their schema and authorship labels."""

import json
import unittest
from pathlib import Path

from kernel.extraction.decisions import requirements_sha

ROOT = Path(__file__).resolve().parent.parent
REVIEW = ROOT / "backup" / "review-inputs-2026-11-10"


class ReviewInputTests(unittest.TestCase):
    def test_every_program_record_is_assistant_authored(self):
        paths = sorted(REVIEW.glob("*/method_programs.json"))
        self.assertTrue(paths, "the preserved review inputs are missing")
        for path in paths:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data.get("schema"), "method_programs/1", path)
            self.assertTrue(data.get("requirements_sha"), path)
            for record in data.get("programs") or []:
                self.assertEqual(record.get("decided_by"), "assistant", path)

    def test_requirements_sha_matches_the_preserved_output(self):
        for path in sorted(REVIEW.glob("*/method_programs.json")):
            output = path.parent.name
            requirements = ROOT / "out" / output / "requirements.txt"
            if not requirements.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                data["requirements_sha"],
                requirements_sha(requirements.read_text(encoding="utf-8")),
                output)


if __name__ == "__main__":
    unittest.main()
