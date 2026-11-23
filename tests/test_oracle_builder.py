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

    def test_json_comments_and_trailing_commas_are_tolerated(self):
        payload = build_oracle_cases.parse_payload(
            '{"cases": [{"id": "x", // note\n "status": "assumed",},]}')
        self.assertEqual(payload["cases"][0]["id"], "x")

    def test_schema_validation_keeps_only_nouns_and_relationships(self):
        schema, errors = build_oracle_cases.validate_schema({
            "entities": [{"name": "Product", "fields": [
                {"name": "name", "type": "string", "required": True},
                {"name": "category_id", "type": "int", "required": True,
                 "references": "Category.id"}]}]})
        self.assertEqual(errors, [])
        self.assertEqual(schema["entities"][0]["fields"][1]["references"],
                         "Category.id")

    def test_schema_prompt_excludes_behavior_and_code(self):
        prompt = build_oracle_cases.build_schema_prompt("Products have a name.")
        self.assertIn("Do not include services, methods", prompt)
        self.assertIn("Products have a name.", prompt)

    def test_plan_validation_rejects_unseeded_references(self):
        plans, errors = build_oracle_cases.validate_plans({
            "plans": [{
                "id": "x", "source": "A counter must increment.",
                "when": {"action": "increment", "args": ["counter.id"]},
                "setup_entities": [],
                "expect": {"rows": {"Counter": 1}},
            }]}, "A counter must increment.")
        self.assertEqual(plans, [])
        self.assertTrue(any("no setup alias" in error for error in errors))
        self.assertTrue(any("no setup entities" in error for error in errors))

    def test_plan_validation_accepts_app_plans(self):
        plans, errors = build_oracle_cases.validate_plans({
            "plans": [{
                "id": "hello", "source": "It prints hello.",
                "when": {"app": True, "args": []},
                "setup_entities": [],
                "expect": {"stdout_contains": "hello", "exit_code": 0},
            }]}, "It prints hello.")
        self.assertEqual(errors, [])
        self.assertEqual(len(plans), 1)

    def test_non_json_is_refused(self):
        self.assertIsNone(build_oracle_cases.parse_payload("I think it works."))


if __name__ == "__main__":
    unittest.main()
