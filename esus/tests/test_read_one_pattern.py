"""`READ_ONE_BY_ID`: one record by its key is a pattern, not a gap.

The catalogue had `READ_ALL` and filters but nothing for `read_book_by_id`, so
the classifier claimed `READ_ALL`, the shape check refused it (a list is not an
entity), and four methods were reported as missing patterns and left to the
model. Each test pins a decision, refusals included.
"""

import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import generator  # noqa: E402
from kernel import codegen, pattern_shapes  # noqa: E402
from kernel.extraction.classification import _attribute  # noqa: E402

ENTRY = {"pattern_id": "READ_ONE_BY_ID", "decision": "decided"}


def method(name="read_book_by_id", params=None, returns="Book | None"):
    return {"name": name, "return_type": returns, "description": "one",
            "params": [{"name": "book_id", "type": "int"}]
            if params is None else params}


class CatalogueTests(unittest.TestCase):
    def entry(self):
        items = json.loads(
            (ROOT / "kernel/repo_patterns/patterns.json").read_text("utf-8"))
        return next(i for i in items if i["pattern_id"] == "READ_ONE_BY_ID")

    def test_the_entry_is_a_repository_pattern_returning_an_entity(self):
        entry = self.entry()
        self.assertEqual(entry["layer"], "repository")
        self.assertEqual(entry["returns"], ["entity"])

    def test_the_entry_carries_every_field_its_siblings_do(self):
        items = json.loads(
            (ROOT / "kernel/repo_patterns/patterns.json").read_text("utf-8"))
        wanted = set(items[0])
        self.assertEqual(set(self.entry()), wanted)

    def test_a_record_or_none_is_a_possible_return(self):
        for returns in ("Book", "Book | None", "models.Book | None",
                        "Optional[Book]"):
            self.assertIsNone(pattern_shapes.rejection_reason(
                "READ_ONE_BY_ID", returns), returns)

    def test_a_list_a_count_or_a_flag_is_not(self):
        for returns in ("List[Book]", "list[models.Book]", "int", "bool"):
            self.assertIsNotNone(pattern_shapes.rejection_reason(
                "READ_ONE_BY_ID", returns), returns)

    def test_only_the_single_record_patterns_return_one_record(self):
        self.assertTrue(pattern_shapes.returns_one_record("READ_ONE_BY_ID"))
        for other in ("READ_ALL", "FILTER_BY_FIELD", "AGGREGATE_BY_FK",
                      "EXISTS_BY_UNIQUE_COMPOSITE", "STANDARD_CRUD"):
            self.assertFalse(pattern_shapes.returns_one_record(other), other)

    def test_read_all_is_still_refused_for_a_single_record(self):
        self.assertIsNotNone(pattern_shapes.rejection_reason(
            "READ_ALL", "Book | None"))


class ClassifierTests(unittest.TestCase):
    def attribute(self, claimed, probabilities, returns):
        return _attribute({
            "pattern_id": claimed, "step2_probabilities": probabilities,
            "step1_probabilities": {"REPO_QUERY": 1.0},
            "domain": "REPO_QUERY"}, returns)

    def test_a_refused_read_all_claim_is_corrected_to_it(self):
        pattern_id, claimed, rejection = self.attribute(
            "READ_ALL", {"READ_ALL": 0.62, "READ_ONE_BY_ID": 0.31,
                         "FILTER_BY_FIELD": 0.07}, "Book | None")
        self.assertEqual((pattern_id, claimed), ("READ_ONE_BY_ID", "READ_ALL"))
        self.assertIsNotNone(rejection)

    def test_it_is_chosen_directly_when_the_model_chooses_it(self):
        pattern_id, claimed, rejection = self.attribute(
            "READ_ONE_BY_ID", {"READ_ONE_BY_ID": 0.8, "READ_ALL": 0.2},
            "Book | None")
        self.assertEqual((pattern_id, claimed, rejection),
                         ("READ_ONE_BY_ID", "READ_ONE_BY_ID", None))

    def test_a_boolean_method_is_not_rescued_into_it(self):
        pattern_id, _, _ = self.attribute(
            "FILTER_WITH_PAGINATION", {"FILTER_WITH_PAGINATION": 0.4,
                                       "READ_ONE_BY_ID": 0.3}, "bool")
        self.assertEqual(pattern_id, "NO_PATTERN_IN_DOMAIN")

    def test_a_list_return_is_never_corrected_into_it(self):
        pattern_id, _, _ = self.attribute(
            "AGGREGATE_BY_FK", {"AGGREGATE_BY_FK": 0.6,
                                "READ_ONE_BY_ID": 0.3}, "List[Book]")
        self.assertNotEqual(pattern_id, "READ_ONE_BY_ID")


class PlanTests(unittest.TestCase):
    def plan(self, target):
        return codegen.plan_method(target, ENTRY, ["Book"])

    def test_scalar_key_and_entity_return_is_a_mechanical_read_one(self):
        self.assertEqual(self.plan(method()),
                         ("crud:read_one", "READ_ONE_BY_ID"))

    def test_the_method_name_does_not_matter(self):
        self.assertEqual(self.plan(method(name="fetch_book"))[0],
                         "crud:read_one")

    def test_a_list_return_is_a_stub(self):
        strategy, detail = self.plan(method(returns="List[Book]"))
        self.assertEqual(strategy, "stub")
        self.assertIn("READ_ONE_BY_ID", detail)

    def test_no_parameter_is_a_stub(self):
        self.assertEqual(self.plan(method(params=[]))[0], "stub")

    def test_an_entity_parameter_is_a_stub(self):
        self.assertEqual(self.plan(method(
            params=[{"name": "book", "type": "Book"}]))[0], "stub")


class EmissionTests(unittest.TestCase):
    def ctx(self, repository_methods):
        return {
            "models": [{"name": "Book", "fields": [
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "title", "type": "string"}]}],
            "errors": [], "entity_names": ["Book"],
            "services": [{"service_name": "BookService", "methods": [
                method()]}],
            "repositories": [{"entity": "Book",
                              "interface_name": "BookRepository",
                              "methods": repository_methods}],
            "mappings": {}, "adapters": [], "components": {},
            "match_index": {"contract:BookService.read_book_by_id": ENTRY},
        }

    def emit(self, ctx):
        stats = {"source": "t", "implemented": 0, "stubs": 0,
                 "stub_reasons": []}
        return generator.emit_services(
            ctx, generator._repo_index(ctx), stats), stats

    def run_service(self, text, repository):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "store", ROOT / "kernel" / "codegen_store_template.py")
        store = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(store)
        models = types.ModuleType("models")
        # The emitted services name the entity in their return annotations
        # (`-> models.Book | None`), so the replacement module needs the class
        # the fixture declared, even though no test body constructs one.
        models.Book = type("Book", (), {})
        modules = {"models": models,
                   "errors": types.ModuleType("errors"), "store": store}
        with mock.patch.dict(sys.modules, modules):
            namespace = dict(modules)
            exec(compile(text, "services.py", "exec"), namespace)  # noqa: S102
        return namespace["BookService"]({"BookRepository": repository})

    def test_a_service_reads_one_through_the_repositorys_read_one(self):
        text, stats = self.emit(self.ctx([method(name="read_one")]))
        self.assertIn("delegates to BookRepository.read_one", text)
        self.assertEqual((stats["implemented"], stats["stubs"]), (1, 0))

        class Repository:
            def read_one(self, book_id=None):
                return {"id": book_id}

        self.assertEqual(
            self.run_service(text, Repository()).read_book_by_id(7),
            {"id": 7})

    def test_a_standard_wrapper_with_optional_service_return_is_mechanical(self):
        ctx = self.ctx([method(name="read_one", returns="Book")])
        ctx["errors"] = [{"name": "BookNotFoundError"}]
        text, stats = self.emit(ctx)
        self.assertIn("except errors.BookNotFoundError:", text)
        self.assertIn("return None", text)
        self.assertEqual((stats["implemented"], stats["stubs"]), (1, 0))

    def test_without_a_matching_read_one_the_method_stays_a_stub(self):
        other = method(name="read_one",
                       params=[{"name": "isbn", "type": "str"}])
        text, stats = self.emit(self.ctx([other]))
        self.assertEqual((stats["implemented"], stats["stubs"]), (0, 1))
        self.assertNotIn("delegates to", text)

    def test_a_read_all_is_never_a_read_one_target(self):
        text, stats = self.emit(self.ctx([method(
            name="read_all", params=[], returns="List[Book]")]))
        self.assertEqual(stats["stubs"], 1)


if __name__ == "__main__":
    unittest.main()
