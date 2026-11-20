"""The oracle builder prompt and parser are independent of extraction."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_oracle_cases  # noqa: E402


class OracleBuilderTests(unittest.TestCase):
    def test_the_prompt_contains_the_schema_and_requirements(self):
        prompt = build_oracle_cases.build_prompt("A counter must increment.")
        self.assertIn("status", prompt)
        self.assertIn("A counter must increment.", prompt)
        self.assertIn('"cases"', prompt)

    def test_a_fenced_json_reply_is_parsed(self):
        payload = build_oracle_cases.parse_payload(
            '```json\n{"cases": [{"id": "x"}]}\n```')
        self.assertEqual(payload["cases"][0]["id"], "x")

    def test_non_json_is_refused(self):
        self.assertIsNone(build_oracle_cases.parse_payload("I think it works."))


if __name__ == "__main__":
    unittest.main()
