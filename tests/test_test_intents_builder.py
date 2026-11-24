"""The prompt-only intent builder emits schema-validated intents."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_test_intents  # noqa: E402


REQUIREMENTS = """Products have a SKU and a stock quantity.
Add stock to a product by its SKU.
"""


class _Result:
    truncated = False

    def __init__(self, text):
        self.text = text


class IntentPromptTests(unittest.TestCase):
    def test_the_prompt_contains_the_target_and_schema(self):
        prompt = build_test_intents.build_intent_prompt(
            REQUIREMENTS, "Add stock to a product by its SKU.")
        self.assertIn("Add stock to a product by its SKU.", prompt)
        self.assertIn('"setup_entities"', prompt)
        self.assertIn("Do not use or infer an extracted architecture", prompt)
        self.assertIn("A standalone one-file program", prompt)

    def test_clause_matching_tolerates_surrounding_punctuation(self):
        clause = "Add stock to a product by its SKU."
        self.assertTrue(build_test_intents._same_clause(clause, clause))
        self.assertTrue(build_test_intents._same_clause(
            "add stock to a product by its sku", clause))
        self.assertFalse(build_test_intents._same_clause(
            "Delete a product.", clause))

    def test_an_over_broad_model_source_is_anchored_to_the_clause(self):
        clause = "Add stock to a product by its SKU."
        payload = {"intents": [{"source": REQUIREMENTS.strip()}]}
        anchored = build_test_intents._anchor_source(payload, clause)
        self.assertEqual(anchored["intents"][0]["source"], clause)


class IntentBuildTests(unittest.TestCase):
    def test_a_valid_model_reply_is_written_as_an_intent_sidecar(self):
        payload = {
            "intents": [{
                "id": "add_stock",
                "source": "Add stock to a product by its SKU.",
                "kind": "update",
                "entity": "Product",
                "action": "add_stock",
                "setup_entities": [
                    {"alias": "product", "entity": "Product", "role": "target"},
                ],
                "setup_values": {"product.stock_qty": 5},
                "lookup": ["product.sku"],
                "args": ["product.sku", 3],
                "changes": {"product.stock_qty": 3},
                "expect": {"state": {"product.stock_qty": 8}},
                "status": "confirmed",
            }]
        }

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "prompt_x"
            project.mkdir()
            (project / "requirements.txt").write_text(
                REQUIREMENTS, encoding="utf-8")
            with mock.patch.object(build_test_intents.runner, "load_model",
                                   return_value=object()), \
                    mock.patch.object(build_test_intents.runner,
                                      "has_chat_template", return_value=True), \
                    mock.patch.object(build_test_intents.runner,
                                      "generate_chat",
                                      return_value=_Result(json.dumps(payload))):
                selected, path = build_test_intents.build_one(
                    project, "server",
                    coverage=["Add stock to a product by its SKU."],
                    repair_attempts=0)
            self.assertEqual(len(selected), 1)
            written = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(written["intents"][0]["id"], "add_stock")
            meta = json.loads(
                (project / "test_intents_meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["rejected"], [])

    def test_a_rejected_intent_is_recorded(self):
        payload = {"intents": [{
            "id": "bad",
            "source": "This source is not in the requirements.",
            "kind": "update",
            "setup_entities": [],
            "expect": {},
        }]}

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "prompt_x"
            project.mkdir()
            (project / "requirements.txt").write_text(
                REQUIREMENTS, encoding="utf-8")
            with mock.patch.object(build_test_intents.runner, "load_model",
                                   return_value=object()), \
                    mock.patch.object(build_test_intents.runner,
                                      "has_chat_template", return_value=True), \
                    mock.patch.object(build_test_intents.runner,
                                      "generate_chat",
                                      return_value=_Result(json.dumps(payload))):
                selected, _path = build_test_intents.build_one(
                    project, "server",
                    coverage=["Add stock to a product by its SKU."],
                    repair_attempts=0)
            self.assertEqual(selected, [])
            meta = json.loads(
                (project / "test_intents_meta.json").read_text(encoding="utf-8"))
            self.assertIn("source is not a prompt span",
                          meta["rejected"][0]["errors"][0])

    def test_append_runs_keep_intent_ids_unique(self):
        existing = {
            "id": "same_id",
            "source": "Products have a SKU and a stock quantity.",
            "kind": "list",
            "entity": "Product",
            "action": "list_products",
            "setup_entities": [],
            "expect": {"rows": {"Product": 1}},
            "status": "assumed",
        }
        new = {
            "id": "same_id",
            "source": "Add stock to a product by its SKU.",
            "kind": "update",
            "entity": "Product",
            "action": "add_stock",
            "setup_entities": [],
            "expect": {"rows": {"Product": 1}},
            "status": "assumed",
        }
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "prompt_x"
            project.mkdir()
            (project / "requirements.txt").write_text(
                REQUIREMENTS, encoding="utf-8")
            (project / build_test_intents.intent_rules.INTENTS_NAME).write_text(
                json.dumps({"intents": [existing]}), encoding="utf-8")
            with mock.patch.object(build_test_intents.runner, "load_model",
                                   return_value=object()), \
                    mock.patch.object(build_test_intents.runner,
                                      "has_chat_template", return_value=True), \
                    mock.patch.object(build_test_intents.runner,
                                      "generate_chat",
                                      return_value=_Result(json.dumps(
                                          {"intents": [new]}))):
                selected, _path = build_test_intents.build_one(
                    project, "server",
                    coverage=["Add stock to a product by its SKU."],
                    repair_attempts=0, append=True)
            self.assertEqual(len(selected), 2)
            self.assertEqual(len({item["id"] for item in selected}), 2)


if __name__ == "__main__":
    unittest.main()
