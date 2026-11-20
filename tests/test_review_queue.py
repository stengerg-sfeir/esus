"""The review queue exposes unresolved questions without answering them."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import review_queue  # noqa: E402


class ReviewQueueTests(unittest.TestCase):
    def test_an_item_names_its_prompt_source_and_resolver(self):
        item = review_queue._item(
            "prompt_x", "contracts", "OrderService.cancel_order",
            {"holder": "OrderService", "method": "cancel_order"})
        self.assertEqual(item["prompt"], "prompt_x")
        self.assertEqual(item["source"], "OrderService.cancel_order")
        self.assertIn("review_contracts.py", item["review_command"])

    def test_markdown_omits_prompts_with_no_questions(self):
        report = {
            "summary": {"open": 1},
            "prompts": [
                {"prompt": "prompt_empty", "items": []},
                {"prompt": "prompt_open", "items": [
                    review_queue._item("prompt_open", "ties", "text",
                                       {"text": "choose"})]},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "queue.md"
            review_queue.write_markdown(report, path)
            text = path.read_text(encoding="utf-8")
        self.assertNotIn("prompt_empty", text)
        self.assertIn("prompt_open", text)

    def test_an_empty_tree_reports_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            report = review_queue.collect_for_directory(directory)
        self.assertEqual(report, [])

    def test_an_assumed_oracle_case_stays_out_of_the_human_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "oracle_cases.json").write_text(
                '{"cases": [{"id": "stock_case", "status": "assumed", '
                '"assumptions": ["stock starts at 3"]}]}')
            report = review_queue.collect_for_directory(root)
        self.assertEqual(report, [])

    def test_a_behavior_finding_enters_the_queue_as_one_group(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "oracle_cases.json").write_text(
                '{"cases": [{"id": "a", "status": "confirmed", '
                '"triage": "behavior: state value", "needs_review": true, '
                '"execution": {"status": "failed", "reason": "x"}}, '
                '{"id": "b", "status": "confirmed", '
                '"triage": "behavior: state value", "needs_review": true, '
                '"execution": {"status": "failed", "reason": "y"}}]}')
            report = review_queue.collect_for_directory(root)
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0]["group"], "oracle")
        self.assertEqual(report[0]["source"], "behavior: state value")
        self.assertEqual(len(report[0]["candidates"]), 2)

    def test_an_inferred_unique_field_enters_the_uniqueness_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data_models.json").write_text(
                '{"data_models": [{"name": "Contact", "fields": ['
                '{"name": "email", "unique": true, '
                '"unique_status": "inferred"}]}]}')
            (root / "requirements.txt").write_text("A contact has an email.")
            report = review_queue.collect_for_directory(root)
        self.assertEqual(report[0]["group"], "uniqueness")
        self.assertEqual(report[0]["source"], "Contact.email")
        self.assertIn("review_uniqueness.py", report[0]["review_command"])

    def test_main_groups_unique_fields_under_one_root_question(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("prompt_a", "prompt_b"):
                prompt = root / name
                prompt.mkdir()
                (prompt / "data_models.json").write_text(
                    '{"data_models": [{"name": "Contact", "fields": ['
                    '{"name": "email", "unique": true, '
                    '"unique_status": "inferred"}]}]}')
                (prompt / "requirements.txt").write_text(
                    "A contact has an email.")
            output = root / "queue.json"
            with contextlib.redirect_stdout(io.StringIO()):
                review_queue.main([str(root), "--output", str(output)])
            report = json.loads(output.read_text())
        groups = [item["group"] for prompt in report["prompts"]
                  for item in prompt["items"]]
        self.assertEqual(groups.count("uniqueness"), 1)
        self.assertEqual(report["summary"]["groups"]["uniqueness"], 1)
        unique = next(item for prompt in report["prompts"]
                      for item in prompt["items"]
                      if item["group"] == "uniqueness")
        self.assertTrue(all(not candidate.startswith("None:")
                            for candidate in unique["candidates"]))

    def test_an_inferred_artifact_enters_the_provenance_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data_models.json").write_text(
                '{"data_models": [{"name": "The", '
                '"status": "inferred from prose", "review_required": true}]}')
            report = review_queue.collect_for_directory(root)
        self.assertEqual(report[0]["group"], "provenance")
        self.assertEqual(report[0]["source"], "The")


if __name__ == "__main__":
    unittest.main()
