"""Unit tests for the generic runtime harness rules.

These cover the data-driven parts of `tests/runtime/worker.py` and the CLI
scenario generator. They do not import a generated package.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "runtime"))
sys.path.insert(0, str(ROOT / "scripts"))

import generate_cli_scenarios  # noqa: E402
import worker  # noqa: E402


class LeafPathTests(unittest.TestCase):
    def test_multi_word_subcommand_is_split_into_argv_tokens(self):
        components = {"facade": {"invocation": {"commands": [
            {"name": "expense", "subcommands": [
                {"name": "category add", "options": []},
                {"name": "list", "options": []},
            ]},
        ]}}}
        paths = [path for path, _node in worker._leaf_entries(components)]
        self.assertEqual(paths, [("expense", "category", "add"),
                                 ("expense", "list")])


class ProjectDiscoveryTests(unittest.TestCase):
    def _project(self, path):
        (path / "generated").mkdir(parents=True)
        (path / "data_models.json").write_text('{"data_models": []}')
        return path

    def test_prompt_layout_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._project(root / "prompt_01")
            self._project(root / "named")
            self.assertEqual([path.name for path in
                              worker.discover_projects(root)], ["prompt_01"])

    def test_esus_bench_layout_is_discovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._project(root / "esus_bench" / "library")
            self._project(root / "speed_timing" / "library")
            self.assertEqual([path.name for path in
                              worker.discover_projects(root)], ["library"])

    def test_direct_named_projects_are_discovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._project(root / "hello")
            self.assertEqual([path.name for path in
                              worker.discover_projects(root)], ["hello"])


class FixtureTests(unittest.TestCase):
    def test_positive_precondition_values(self):
        contract = {"preconditions": [
            {"check": "item.state == 'ready'", "raise_when": "false"},
            {"check": "item.owner is not None", "raise_when": "false"},
            {"check": "item.kind in ('a', 'b')", "raise_when": "false"},
        ]}
        values = worker._precondition_values(contract, "item")
        self.assertEqual(values["state"], "ready")
        self.assertIs(values["owner"], worker._NON_NULL)
        self.assertEqual(values["kind"], "a")

    def test_forbidden_non_null_seeds_null(self):
        contract = {"preconditions": [
            {"check": "loan.return_date is not None or loan.status == 'returned'",
             "raise_when": "true"},
        ]}
        values = worker._precondition_values(contract, "loan")
        self.assertIsNone(values["return_date"])

    def test_composite_unique_fields_from_invariant(self):
        docs = {
            "models": [{"name": "Budget", "fields": [
                {"name": "category_id"}, {"name": "month"},
                {"name": "amount_limit_cents"},
            ]}],
            "invariants": [{"text": "Budget must have a unique constraint on "
                                    "(category_id, month)"}],
        }
        self.assertEqual(worker._composite_unique_fields(docs, "Budget"),
                         {"category_id", "month"})

    def test_plural_id_option_gets_a_scalar_id_fixture(self):
        docs = {"models": [{"name": "Product", "fields": [
            {"name": "id", "type": "int", "primary_key": True}]}]}
        self.assertEqual(worker._cli_value(docs, "--product-ids", "str", 1), "1")

    def test_option_resolves_entity_to_foreign_key(self):
        docs = {"models": [{"name": "Expense", "fields": [
            {"name": "category_id", "type": "int",
             "foreign_key": {"target_entity": "Category"}},
        ]}]}
        fields = worker._option_field(docs, "category")
        self.assertEqual(fields[0][1]["name"], "category_id")

    def test_comparison_invariant_adjusts_numeric_fixture(self):
        docs = {
            "models": [{"name": "Wine", "fields": [
                {"name": "cost_price", "type": "decimal"},
                {"name": "selling_price", "type": "decimal"},
            ]}],
            "invariants": [{"text": "The selling price of a wine bottle must "
                                    "always be strictly greater than its cost "
                                    "price."}],
        }
        values = worker._satisfy_comparisons(
            docs, "Wine", {"cost_price": 2.0, "selling_price": 2.0})
        self.assertGreater(values["selling_price"], values["cost_price"])

    def test_bare_file_placeholder_is_replaced_even_if_it_exists(self):
        docs = {"models": [{"name": "Contact", "fields": [
            {"name": "id", "type": "int"},
            {"name": "first_name", "type": "string"},
        ]}]}
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                Path("value1").write_text("stale")
                args = worker._materialize_file_args(
                    docs, ["Contact", "import", "--file-path", "value1"])
            finally:
                os.chdir(previous)
            self.assertNotEqual(args[-1], "value1")
            header = Path(args[-1]).read_text().splitlines()[0]
            self.assertEqual(header, "id,first_name")

    def test_output_placeholder_is_materialised_outside_the_worktree(self):
        docs = {"models": [{"name": "Expense", "fields": [
            {"name": "id", "type": "int"},
        ]}]}
        args = worker._materialize_file_args(
            docs, ["expense", "export", "--output", "value1"])
        self.assertNotEqual(args[-1], "value1")
        self.assertTrue(Path(args[-1]).is_absolute())


class ScenarioGenerationTests(unittest.TestCase):
    def test_update_seed_overrides_track_filter_fields(self):
        docs = {"models": [{"name": "Budget", "fields": [
            {"name": "id", "type": "int", "primary_key": True},
            {"name": "category_id", "type": "int",
             "foreign_key": {"target_entity": "Category"}},
            {"name": "month", "type": "string"},
            {"name": "amount_limit_cents", "type": "int"},
        ]}]}
        overrides = generate_cli_scenarios._update_seed_overrides(
            docs, ["budget", "update"],
            ["budget", "update", "--category-id", "1", "--month", "2024-01",
             "--amount", "2"])
        self.assertEqual(overrides, {"category_id": 1, "month": "2024-01"})


if __name__ == "__main__":
    unittest.main()
