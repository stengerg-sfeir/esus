"""The review queue exposes unresolved questions without answering them."""

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


if __name__ == "__main__":
    unittest.main()
