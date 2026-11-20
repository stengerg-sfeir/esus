"""The uniqueness review groups inferred fields and records decisions."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import review_uniqueness  # noqa: E402
from kernel.extraction import uniqueness  # noqa: E402


def write_prompt(directory, *fields):
    payload = {"data_models": [{"name": "Contact", "fields": [
        {"name": "id", "type": "int", "primary_key": True,
         "unique": True, "unique_status": "explicit"},
        *fields,
    ]}]}
    (directory / "data_models.json").write_text(
        json.dumps(payload), encoding="utf-8")
    (directory / "requirements.txt").write_text(
        "A contact has an email and a name.\n", encoding="utf-8")
    (directory / "invariants.json").write_text(
        json.dumps({"invariants": [
            {"text": "Contact.email must be unique", "kind": "schema"},
            {"text": "Contact.name must be unique", "kind": "schema"},
        ]}), encoding="utf-8")


class ReviewTests(unittest.TestCase):
    def test_inferred_fields_are_one_prompt_question(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_prompt(
                root,
                {"name": "email", "type": "string", "unique": True,
                 "unique_status": "inferred"},
                {"name": "name", "type": "string", "unique": True,
                 "unique_status": "inferred"})
            questions, _context = review_uniqueness.collect_questions(root)
        self.assertEqual(len(questions), 1)
        self.assertEqual(len(questions[0]["groups"]), 2)

    def test_confirm_all_records_each_field_and_adds_invariants(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_prompt(
                root,
                {"name": "email", "type": "string", "unique": True,
                 "unique_status": "inferred"})
            asked, answered = review_uniqueness.run_review(
                root, input_fn=lambda _prompt: "confirm",
                out_fn=lambda _line: None)
            records = uniqueness.load_decisions(root)
            models = json.loads(
                (root / "data_models.json").read_text())["data_models"]
            invariants = json.loads(
                (root / "invariants.json").read_text())["invariants"]
        self.assertEqual((asked, answered), (1, 1))
        self.assertEqual(records[0]["unique"], True)
        self.assertEqual(models[0]["fields"][1]["unique_status"],
                         uniqueness.CONFIRMED)
        self.assertTrue(any(item["text"] == "Contact.email must be unique"
                            for item in invariants))
        self.assertFalse(any(item["text"] == "Contact.name must be unique"
                             for item in invariants))

    def test_reject_all_records_rejection_and_removes_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_prompt(
                root,
                {"name": "email", "type": "string", "unique": True,
                 "unique_status": "inferred"})
            review_uniqueness.run_review(
                root, input_fn=lambda _prompt: "reject",
                out_fn=lambda _line: None)
            records = uniqueness.load_decisions(root)
            models = json.loads(
                (root / "data_models.json").read_text())["data_models"]
        self.assertEqual(records[0]["unique"], False)
        self.assertEqual(models[0]["fields"][1]["unique_status"],
                         uniqueness.REJECTED)
        self.assertFalse(models[0]["fields"][1]["unique"])

    def test_a_root_policy_decides_all_prompts_at_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("prompt_a", "prompt_b"):
                prompt = root / name
                prompt.mkdir()
                write_prompt(
                    prompt,
                    {"name": "email", "type": "string", "unique": True,
                     "unique_status": "inferred"})
            asked, answered = review_uniqueness.run_root_review(
                root, input_fn=lambda _prompt: "confirm",
                out_fn=lambda _line: None)
            policy = uniqueness.load_policies(root / "prompt_a")
            models = json.loads(
                (root / "prompt_a" / "data_models.json").read_text()
            )["data_models"]
        self.assertEqual((asked, answered), (1, 1))
        self.assertEqual(policy[0]["policy"], "conventional")
        self.assertEqual(models[0]["fields"][1]["unique_status"],
                         uniqueness.CONFIRMED)

    def test_skipping_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_prompt(
                root,
                {"name": "email", "type": "string", "unique": True,
                 "unique_status": "inferred"})
            asked, answered = review_uniqueness.run_review(
                root, input_fn=lambda _prompt: "skip",
                out_fn=lambda _line: None)
        self.assertEqual((asked, answered), (1, 0))
        self.assertFalse((root / "unique_decisions.json").is_file())


if __name__ == "__main__":
    unittest.main()
