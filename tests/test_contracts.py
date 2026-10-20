"""The contract record is data: load it, validate it, and propose one without
knowing whether the application is a library or a factory."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import generator  # noqa: E402
import review_contracts  # noqa: E402
from kernel.extraction import contracts  # noqa: E402
from kernel.extraction.decisions import requirements_sha  # noqa: E402


class ContractStorageTests(unittest.TestCase):
    def test_stale_records_are_dropped_and_current_ones_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            requirements = "InventoryService consumes material.\n"
            (Path(directory) / "requirements.txt").write_text(
                requirements, encoding="utf-8")
            current = requirements_sha(requirements)
            payload = {"method_contracts": [
                {"holder": "InventoryService", "method": "consume",
                 "decided_by": "user", "requirements_sha": current,
                 "effects": [{"target": "stock.stock_qty",
                              "op": "decrement", "by": "qty",
                              "write": "StockRepository.update_stock"}]},
                {"holder": "InventoryService", "method": "old",
                 "decided_by": "user", "requirements_sha": "not-current",
                 "effects": [{"target": "stock.stock_qty",
                              "op": "decrement"}]},
            ]}
            (Path(directory) / contracts.METHOD_CONTRACTS_NAME).write_text(
                json.dumps(payload), encoding="utf-8")
            records, dropped = contracts.load_method_contracts(
                directory, requirements)
            self.assertEqual(dropped, 1)
            self.assertEqual([record["method"] for record in records],
                             ["consume"])
            self.assertEqual(records[0]["effects"][0]["target"],
                             "stock.stock_qty")

    def test_a_malformed_effect_is_not_applied(self):
        record = contracts.normalize_contract({
            "holder": "S", "method": "m",
            "effects": [{"target": "stock.stock_qty", "op": "explode"},
                        {"target": "stock.stock_qty", "op": "decrement"}],
            "unknown": "dropped",
        })
        self.assertEqual(record["effects"],
                         [{"target": "stock.stock_qty", "op": "decrement"}])
        self.assertNotIn("unknown", record)


STOCK_CONTEXT = {
    "entity_names": ["Stock", "Consumption"],
    "models": [
        {"name": "Stock", "fields": [
            {"name": "id", "type": "int", "primary_key": True},
            {"name": "stock_qty", "type": "int"}]},
        {"name": "Consumption", "fields": [
            {"name": "id", "type": "int", "primary_key": True},
            {"name": "stock_id", "type": "int"},
            {"name": "qty", "type": "int"}]},
    ],
    "repositories": [
        {"entity": "Stock", "interface_name": "StockRepository",
         "methods": [
             {"name": "read_one_stock"},
             {"name": "update_stock"},
         ]},
        {"entity": "Consumption",
         "interface_name": "ConsumptionRepository",
         "methods": [{"name": "create_consumption"}]},
    ],
    "invariants": [],
}


class ContractProposalTests(unittest.TestCase):
    def method(self):
        return {
            "name": "consume_material",
            "description": ("Consumes material from stock: decrements "
                            "stock_qty, creates a consumption record."),
            "params": [{"name": "stock_id", "type": "int"},
                       {"name": "qty", "type": "int"}],
            "raises": ["StockNotFoundError", "InsufficientStockError"],
        }

    def test_a_factory_contract_is_proposed_without_library_vocabulary(self):
        proposal = review_contracts._propose(
            STOCK_CONTEXT, "InventoryService", self.method(), "service",
            "- consume_material(stock_id, qty): decrements stock_qty")
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal["effects"][0]["target"],
                         "stock.stock_qty")
        self.assertEqual(proposal["effects"][0]["write"],
                         "StockRepository.update_stock")
        self.assertEqual(proposal["creates"][0]["call"],
                         "ConsumptionRepository.create_consumption")
        self.assertIn("stock exists",
                      [item["check"] for item in proposal["preconditions"]])
        text = json.dumps(proposal).lower()
        for word in ("book", "copies", "return_date", "due_date", "loan"):
            self.assertNotIn(word, text)

    def test_an_open_error_question_shows_its_documented_description(self):
        ctx = dict(STOCK_CONTEXT)
        ctx["errors"] = [{"name": "InsufficientStockError",
                          "description": "Raised when stock is below the "
                                         "requested quantity."}]
        proposal = review_contracts._propose(
            ctx, "InventoryService", self.method(), "service", "")
        question = next(item for item in proposal["questions"]
                        if item["id"] == "precondition:InsufficientStockError")
        self.assertIn("stock is below the requested quantity",
                      question["prompt"])
        self.assertIn("InsufficientStockError", question["prompt"])

    def test_answers_become_a_generic_record(self):
        proposal = review_contracts._propose(
            STOCK_CONTEXT, "InventoryService", self.method(), "service",
            "- consume_material(stock_id, qty): decrements stock_qty")
        answers = {
            "keep_preconditions": "keep",
            "effect:0": "qty",
            "keep_creates": "keep",
            "precondition:InsufficientStockError": "stock.stock_qty >= qty",
            "order": "create_first",
        }
        record = review_contracts._finalize(
            proposal, answers, None, STOCK_CONTEXT)
        self.assertEqual(record["effects"][0]["by"], "qty")
        self.assertEqual(record["creates"][0]["class"], "Consumption")
        self.assertEqual(record["order"], [
            "preconditions",
            "ConsumptionRepository.create_consumption",
            "StockRepository.update_stock",
        ])
        self.assertIn({"check": "stock.stock_qty >= qty",
                       "error": "InsufficientStockError"},
                      record["preconditions"])
        self.assertEqual(record["decided_by"], "user")


if __name__ == "__main__":
    unittest.main()
