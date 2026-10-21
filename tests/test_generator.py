"""The generator writes runnable programs, and refuses when the probe blames us.

A synthetic Shop (two entities, CRUD, one filter, one gap, one ruled tie, one
delegating service method) is generated into a temp dir, imported, and driven:
CRUD round-trips, FK and not-found failures use the registered errors, the gap
stub refuses with its work order, and the CLI dispatches add/list/remove. The
gate is pinned too: a document the probe rejects produces no `generated/`.
"""

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import generator  # noqa: E402
from kernel import codegen  # noqa: E402


def fixture(ghost_raise=False):
    """A complete Shop extraction output as `{filename: body}` (no wrappers)."""
    def method(name, params=(), returns="None", raises=(), description=""):
        return {"name": name, "description": description or name,
                "params": [{"name": n, "type": t} for n, t in params],
                "return_type": returns, "raises": list(raises)}

    bodies = {
        "data_models": [
            {"name": "Category", "fields": [
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "name", "type": "string"}]},
            {"name": "Product", "fields": [
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "name", "type": "string"},
                {"name": "price_cents", "type": "int"},
                {"name": "tags", "type": "string", "nullable": True},
                {"name": "category_id", "type": "int",
                 "foreign_key": {"target_entity": "Category", "target_field": "id",
                                 "relationship": "many_to_one"}}]},
        ],
        "errors": [
            {"name": "CategoryNotFoundError", "base": "LookupError", "description": "no such category"},
            {"name": "ProductNotFoundError", "base": "LookupError", "description": "no such product"}],
        "service_contracts": [
            {"service_name": "CategoryRepository", "methods": [
                method("create_category", [("data", "Category")], "Category", [], "Create it."),
                method("read_one_category", [("id", "int")], "Category", ["CategoryNotFoundError"]),
                method("delete_category", [("id", "int")], "None", ["CategoryNotFoundError"])]},
            {"service_name": "ProductRepository", "methods": [
                method("create_product", [("data", "Product")], "Product"),
                method("read_one_product", [("id", "int")], "Product", ["ProductNotFoundError"]),
                method("read_all_products", [], "List[Product]"),
                method("update_product", [("id", "int"), ("data", "Product")], "Product", ["ProductNotFoundError"]),
                method("delete_product", [("id", "int")], "None",
                       ["GhostError"] if ghost_raise else ["ProductNotFoundError"]),
                method("find_products_by_category", [("category_id", "int")], "List[Product]"),
                method("export_products", [("file_path", "str")], "None")]},
            {"service_name": "ShopService", "methods": [
                method("read_all_products", [], "List[Product]", [], "Delegate."),
                method("price_report", [], "int", [], "A custom aggregate. […]")]}],
        "persistence_ports": {
            "repositories": [
                {"entity": "Category", "interface_name": "CategoryRepository", "methods": [
                    method("create_category", [("data", "Category")], "Category"),
                    method("read_one_category", [("id", "int")], "Category", ["CategoryNotFoundError"]),
                    method("delete_category", [("id", "int")], "None", ["CategoryNotFoundError"])]},
                {"entity": "Product", "interface_name": "ProductRepository", "methods": [
                    method("create_product", [("data", "Product")], "Product"),
                    method("read_one_product", [("id", "int")], "Product", ["ProductNotFoundError"]),
                    method("read_all_products", [], "List[Product]"),
                    method("update_product", [("id", "int"), ("data", "Product")], "Product", ["ProductNotFoundError"]),
                    method("delete_product", [("id", "int")], "None",
                           ["GhostError"] if ghost_raise else ["ProductNotFoundError"]),
                    method("find_products_by_category", [("category_id", "int")], "List[Product]"),
                    method("export_products", [("file_path", "str")], "None")]}],
            "entity_mappings": [
                {"entity": "Category", "table": "categories", "primary_key": "id", "indexes": []},
                {"entity": "Product", "table": "products", "primary_key": "id", "indexes": []}]},
        "intentions": ["Sell products across categories"],
        "invariants": [],
        "pattern_matches": [
            {"source": "contract:CategoryRepository.create_category", "text": "c",
             "pattern_id": "STANDARD_CRUD", "confidence": 0.8, "decision": "decided"},
            {"source": "contract:CategoryRepository.read_one_category", "text": "c",
             "pattern_id": "STANDARD_CRUD", "confidence": 0.8, "decision": "decided"},
            {"source": "contract:CategoryRepository.delete_category", "text": "c",
             "pattern_id": "STANDARD_CRUD", "confidence": 0.8, "decision": "decided"},
            {"source": "contract:ProductRepository.create_product", "text": "c",
             "pattern_id": "STANDARD_CRUD", "confidence": 0.8, "decision": "decided"},
            {"source": "contract:ProductRepository.read_one_product", "text": "c",
             "pattern_id": "STANDARD_CRUD", "confidence": 0.8, "decision": "decided"},
            {"source": "contract:ProductRepository.read_all_products", "text": "c",
             "pattern_id": "READ_ALL", "confidence": 0.8, "decision": "decided"},
            {"source": "contract:ProductRepository.update_product", "text": "c",
             "pattern_id": "STANDARD_CRUD", "confidence": 0.8, "decision": "decided"},
            {"source": "contract:ProductRepository.delete_product", "text": "c",
             "pattern_id": "STANDARD_CRUD", "confidence": 0.8, "decision": "decided"},
            {"source": "contract:ProductRepository.find_products_by_category", "text": "c",
             "pattern_id": "FILTER_BY_FIELD", "runner_up_pattern_id": "FILTER_WITH_PAGINATION",
             "confidence": 0.3, "margin": 0.05, "decision": "undecided", "undecided_stage": "pattern"},
            {"source": "contract:ProductRepository.export_products", "text": "export them",
              "pattern_id": "NO_PATTERN_IN_DOMAIN", "confidence": 0.0008, "decision": "undefined",
             "claimed_pattern_id": "FILTER_WITH_PAGINATION",
             "rejection": "FILTER_WITH_PAGINATION returns collection, but this method returns none (None)"},
            {"source": "contract:ShopService.read_all_products", "text": "c",
             "pattern_id": "READ_ALL", "confidence": 0.8, "decision": "decided"},
            { "source": "contract:ShopService.price_report", "text": "c",
             "pattern_id": "NO_PATTERN_IN_DOMAIN", "confidence": 0.001, "decision": "undefined"}],
        "interaction_adapters": [
            {"action_name": "add_category", "target_service": "CategoryRepository",
             "target_method": "create_category",
             "input_fields": [
                 {"field_name": "name", "target_param": "data", "transform": "DIRECT", "lookup_entity": None, "required": True}]},
            {"action_name": "add_product", "target_service": "ProductRepository",
             "target_method": "create_product",
             "input_fields": [
                 {"field_name": "name", "target_param": "data", "transform": "DIRECT", "lookup_entity": None, "required": True},
                 {"field_name": "price_cents", "target_param": "data", "transform": "DECIMAL_TO_CENTS", "lookup_entity": None, "required": True},
                 {"field_name": "category_id", "target_param": "data", "transform": "LOOKUP_ID", "lookup_entity": "Category", "required": True},
                 {"field_name": "tags", "target_param": "data", "transform": "CSV_LIST", "lookup_entity": None, "required": False}]},
            {"action_name": "get_product", "target_service": "ProductRepository",
             "target_method": "read_one_product",
             "input_fields": [
                 {"field_name": "id", "target_param": "id", "transform": "DIRECT", "lookup_entity": None, "required": True}]},
            {"action_name": "list_products", "target_service": "ProductRepository",
             "target_method": "read_all_products", "input_fields": []},
            {"action_name": "remove_product", "target_service": "ProductRepository",
             "target_method": "delete_product",
             "input_fields": [
                 {"field_name": "id", "target_param": "id", "transform": "DIRECT", "lookup_entity": None, "required": True}]}],
        "components": {
            "facade": {"type": "cli", "technology": "argparse",
                       "invocation": {"positional": [], "options": [],
                                      "commands": [
                                          {"name": "category", "options": [],
                                           "subcommands": [
                                               {"name": "add", "options": [
                                                   {"name": "--name", "short": "-n", "type": "str", "required": True, "default": None}]}]},
                                          {"name": "product", "options": [],
                                           "subcommands": [
                                               {"name": "add", "options": [
                                                   {"name": "--name", "short": "-n", "type": "str", "required": True, "default": None},
                                                   {"name": "--price", "short": "-p", "type": "float", "required": True, "default": None},
                                                   {"name": "--category", "short": "-c", "type": "int", "required": True, "default": None},
                                                   {"name": "--tags", "short": "-t", "type": "list", "required": False, "default": None}]},
                                               {"name": "get", "options": [
                                                   {"name": "--id", "short": "-i", "type": "int", "required": True, "default": None}]},
                                               {"name": "list", "options": []},
                                               {"name": "remove", "options": [
                                                   {"name": "--id", "short": "-i", "type": "int", "required": True, "default": None}]}]}]}},
            "persistence": {"required": True, "technology": "sqlite"},
            "external_access": [],
            "crud_services": [
                {"entity": "Category", "operations": ["create", "read_one", "delete"]},
                {"entity": "Product", "operations": ["create", "read_one", "read_all", "update", "delete"]}]},
    }
    return bodies


def write_out(directory, bodies):
    """Bodies as `{name}.json` files shaped like the extractor's (`{name: body}`)."""
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    for name, body in bodies.items():
        (path / f"{name}.json").write_text(json.dumps({name: body}, indent=2), encoding="utf-8")
    return str(path)


class GateTests(unittest.TestCase):
    def test_a_document_the_probe_rejects_produces_nothing(self):
        """`delete_product` raises an unregistered error: the gate refuses."""
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            out = write_out(Path(directory) / "shop", fixture(ghost_raise=True))
            with io.StringIO() as buffer, redirect_stdout(buffer):
                self.assertEqual(generator.main([out]), 1)
            self.assertFalse((Path(out) / "generated").exists())

    def test_degenerate_without_model_stops_instead_of_empty_shell(self):
        """Clean but empty documents need --model; exit 2 writes nothing."""
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "hello"
            target.mkdir()
            (target / "requirements.txt").write_text(
                'Print "Hello, World!".', encoding="utf-8")
            for name in ("intentions", "invariants", "data_models", "errors",
                         "service_contracts", "pattern_matches",
                         "interaction_adapters"):
                (target / f"{name}.json").write_text(
                    json.dumps({name: []}), encoding="utf-8")
            # Shaped like a real no-persistence run: no persistence_ports.json
            # at all (present-but-empty trips empty_section), facade typed.
            (target / "components.json").write_text(json.dumps(
                {"components": {"facade": {"type": "cli", "technology": "none",
                                           "invocation": None},
                                "persistence": {"required": False,
                                                "technology": "none"},
                                "external_access": [], "crud_services": []}}),
                encoding="utf-8")
            with io.StringIO() as buffer, redirect_stdout(buffer):
                self.assertEqual(generator.main([str(target)]), 2)
                self.assertIn("--model", buffer.getvalue())
            self.assertFalse((target / "generated").exists())


class DegenerateFallbackTests(unittest.TestCase):
    """Clean-but-empty documents get one LLM-written app.py, said aloud."""

    def empty_ctx(self):
        return {"models": [], "errors": [], "services": [],
                "repositories": [], "mappings": {}, "match_index": {},
                "adapters": [],
                "components": {"facade": {"invocation": None}},
                "entity_names": []}

    def test_empty_context_is_degenerate(self):
        self.assertTrue(generator.is_degenerate(self.empty_ctx()))

    def test_any_content_disables_the_fallback(self):
        for key, value in (
                ("models", [{"name": "M"}]),
                ("services", [{"service_name": "S"}]),
                ("repositories", [{"entity": "E"}]),
                ("adapters", [{"action_name": "a"}])):
            ctx = self.empty_ctx()
            ctx[key] = value
            self.assertFalse(generator.is_degenerate(ctx), key)
        ctx = self.empty_ctx()
        ctx["components"] = {"facade": {"invocation": {"commands": [{"name": "x"}]}}}
        self.assertFalse(generator.is_degenerate(ctx), "commands")

    def test_prompt_carries_requirements_and_errors(self):
        prompt = generator.fallback_prompt(
            "Convert CSV to JSON.",
            [{"name": "MalformedCSVError", "base": "ValueError",
              "description": "bad csv"}])
        self.assertIn("Convert CSV to JSON.", prompt)
        self.assertIn("MalformedCSVError(ValueError): bad csv", prompt)
        self.assertIn("ONLY Python code", prompt)

    def test_prompt_without_errors_has_no_error_section(self):
        self.assertNotIn("Registered application errors",
                         generator.fallback_prompt("Hi.", []))

    def test_fences_are_tolerated_but_bare_code_passes_through(self):
        code = 'def main():\n    print("hi")'
        self.assertEqual(generator.strip_code_fences(code), code)
        self.assertEqual(
            generator.strip_code_fences("```python\n" + code + "\n```"), code)

    def test_prose_around_a_fence_does_not_leak_into_app(self):
        """Hello narrated first and fenced second: take the fenced block."""
        code = 'def main():\n    print("hi")'
        text = ("- Use only standard library modules.\n\n```python\n"
                + code + "\n```")
        self.assertEqual(generator.extract_code(text), code)

    def test_unparseable_code_is_refused_not_written(self):
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "hello"
            target.mkdir()
            (target / "requirements.txt").write_text("Hi.", encoding="utf-8")
            result = mock.Mock(text="- just prose, no code at all\n", tokens=8,
                               seconds=0.5)
            with mock.patch.object(generator.runner, "load_model",
                                    return_value=mock.Mock()), \
                 mock.patch.object(generator.runner, "generate_free",
                                    return_value=result):
                with io.StringIO() as buffer, redirect_stdout(buffer):
                    self.assertEqual(
                        generator.generate_fallback(str(target), "m.gguf"), 1)
                    self.assertIn("does not parse", buffer.getvalue())
            self.assertFalse((target / "generated" / "app.py").exists())

    def test_fallback_writes_only_app_py_with_header(self):
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "hello"
            target.mkdir()
            (target / "requirements.txt").write_text(
                'Print "Hello, World!".', encoding="utf-8")
            result = mock.Mock(text='def main():\n    print("hi")\n',
                               tokens=10, seconds=1.0)
            with mock.patch.object(generator.runner, "load_model",
                                    return_value=mock.Mock()) as loaded, \
                 mock.patch.object(generator.runner, "generate_free",
                                    return_value=result) as generated:
                with io.StringIO() as buffer, redirect_stdout(buffer):
                    self.assertEqual(
                        generator.generate_fallback(str(target), "m.gguf"), 0)
                    output = buffer.getvalue()
            loaded.assert_called_once_with("m.gguf", logits_all=False)
            self.assertEqual(generated.call_count, 1)
            self.assertIn("LLM fallback", output)
            written = sorted(p.name for p in (target / "generated").iterdir())
            self.assertEqual(written, ["app.py"])
            body = (target / "generated" / "app.py").read_text(encoding="utf-8")
            self.assertIn("LLM-generated fallback", body)
            self.assertIn('print("hi")', body)
            compile(body, "app.py", "exec")

    def test_empty_model_answer_is_an_error_not_an_empty_file(self):
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "hello"
            target.mkdir()
            (target / "requirements.txt").write_text("Hi.", encoding="utf-8")
            result = mock.Mock(text="```\n```\n", tokens=3, seconds=0.5)
            with mock.patch.object(generator.runner, "load_model",
                                    return_value=mock.Mock()), \
                 mock.patch.object(generator.runner, "generate_free",
                                    return_value=result):
                with io.StringIO(), redirect_stdout(io.StringIO()):
                    self.assertEqual(
                        generator.generate_fallback(str(target), "m.gguf"), 1)
            self.assertFalse((target / "generated" / "app.py").exists())


class GenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls._tmp = tempfile.TemporaryDirectory()
        out = write_out(Path(cls._tmp.name) / "shop", fixture())
        with io.StringIO(), redirect_stdout(io.StringIO()):
            assert generator.main([out]) == 0, "fixture must generate cleanly"
        cls.out = out
        cls.generated = str(Path(out) / "generated")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def mods(self):
        """All generated modules, imported by real name off the generated dir.

        The emitted files import each other as siblings (`import models`), so
        they are loaded the way the CLI loads them: the directory on
        `sys.path`, names evicted first so reruns never see a stale package.
        """
        sys.path.insert(0, self.generated)
        try:
            for name in ("store", "models", "errors", "repositories",
                         "services", "cli"):
                sys.modules.pop(name, None)
            import store
            import models
            import errors
            import repositories
            import services
            import cli
            return store, models, errors, repositories, services, cli
        finally:
            sys.path.remove(self.generated)

    def test_all_files_are_written(self):
        for filename in ("__init__.py", "models.py", "errors.py", "store.py",
                         "repositories.py", "services.py", "cli.py"):
            self.assertTrue((Path(self.generated) / filename).is_file(), filename)

    def test_crud_round_trip_with_registered_errors(self):
        store, models, errors, repositories, _, _ = self.mods()
        backend = store.Store()
        categories = repositories.CategoryRepository(backend)
        products = repositories.ProductRepository(backend)
        category = categories.create_category(models.Category(name="food"))
        self.assertEqual(category.id, 1)
        with self.assertRaises(errors.CategoryNotFoundError):
            products.create_product(models.Product(name="x", price_cents=1, category_id=999))
        item = products.create_product(
            models.Product(name="apple", price_cents=150, category_id=category.id))
        self.assertEqual(products.read_one_product(item.id).name, "apple")
        with self.assertRaises(errors.ProductNotFoundError):
            products.read_one_product(999)
        self.assertEqual(len(products.read_all_products()), 1)
        self.assertEqual(products.find_products_by_category(category.id)[0].id, item.id)
        changed = products.update_product(item.id, models.Product(price_cents=200))
        self.assertEqual(changed.price_cents, 200)
        self.assertEqual(changed.name, "apple")
        products.delete_product(item.id)
        self.assertEqual(products.read_all_products(), [])

    def test_gap_and_aggregate_stubs_refuse_with_their_work_order(self):
        store, _, _, repositories, services, _ = self.mods()
        backend = store.Store()
        repos = {"ProductRepository": repositories.ProductRepository(backend)}
        with self.assertRaises(NotImplementedError) as ctx:
            repositories.ProductRepository(backend).export_products("out.csv")
        self.assertIn("NO_PATTERN_IN_DOMAIN", str(ctx.exception))
        self.assertIn("FILTER_WITH_PAGINATION",
                      repositories.ProductRepository.export_products.__doc__)
        with self.assertRaises(NotImplementedError):
            services.ShopService(repos).price_report()

    def test_service_delegation_reaches_the_repository(self):
        store, _, _, repositories, services, _ = self.mods()
        backend = store.Store()
        dictionary = {"ProductRepository": repositories.ProductRepository(backend)}
        self.assertEqual(services.ShopService(dictionary).read_all_products(), [])

    def test_single_param_lookup_by_non_pk_goes_through_criteria(self):
        """`read_x_by_email(email)` must not search `PK == email`.

        Only a parameter mapping to the PK with `eq` keeps the direct
        lookup; anything else goes through criteria (and the uniqueness
        check), so a miss reports no match instead of a wrong miss.
        """
        pk_path = generator._read_one_body(
            [("id", "id", "int")], "Product", None, ["id", "name"], "id",
            "LookupError")
        self.assertTrue(any("self._store.get(self.ENTITY, self.PK" in line
                            for line in pk_path))
        criteria_path = generator._read_one_body(
            [("email", "email", "str")], "Product", None, ["id", "email"],
            "id", "LookupError")
        self.assertFalse(any("self._store.get(self.ENTITY, self.PK" in line
                             for line in criteria_path))
        self.assertTrue(any("criteria" in line for line in criteria_path))

    def session(self):
        """One parser plus dependencies sharing a single store."""
        _, _, _, _, _, cli = self.mods()
        parser, deps = cli.build_cli()
        return parser, deps, cli

    def test_cli_dispatches_add_list_remove(self):
        parser, deps, cli = self.session()
        run = lambda argv: cli.dispatch(parser, parser.parse_args(argv), deps)
        self.assertEqual(run(["category", "add", "--name", "food"]), 0)
        self.assertEqual(run(["product", "add", "--name", "apple",
                              "--price", "1.50", "--category", "1",
                              "--tags", "a,b"]), 0)
        with io.StringIO() as buffer, redirect_stdout(buffer):
            self.assertEqual(run(["product", "list"]), 0)
            self.assertIn("apple", buffer.getvalue())
            self.assertIn("150", buffer.getvalue())
        self.assertEqual(run(["product", "remove", "--id", "1"]), 0)
        with io.StringIO() as buffer, redirect_stdout(buffer):
            self.assertEqual(run(["product", "list"]), 0)
            self.assertNotIn("apple", buffer.getvalue())

    def test_cli_reports_domain_errors_without_traceback(self):
        parser, deps, cli = self.session()
        with io.StringIO() as buffer, redirect_stdout(buffer):
            self.assertEqual(
                cli.dispatch(parser, parser.parse_args(["product", "get", "--id", "999"]), deps), 1)
            self.assertIn("error:", buffer.getvalue())

    def test_cli_help_parses(self):
        _, _, _, _, _, cli = self.mods()
        with self.assertRaises(SystemExit) as ctx:
            cli.main(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_cli_db_flag_persists_across_processes(self):
        """Two main() calls sharing --db see one store: the FK that failed
        across processes now resolves, and records survive."""
        import tempfile
        _, _, _, _, _, cli = self.mods()
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / "shop.db")
            with io.StringIO(), redirect_stdout(io.StringIO()):
                self.assertEqual(
                    cli.main(["--db", db, "category", "add", "--name", "food"]), 0)
                self.assertEqual(
                    cli.main(["--db", db, "product", "add", "--name", "apple",
                              "--price", "1.50", "--category", "1"]), 0)
            self.assertTrue((Path(directory) / "shop.db").is_file())


class StorePersistenceTests(unittest.TestCase):
    """Same interface, durable: file-backed behavior equals memory."""

    def template(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "store", "kernel/codegen_store_template.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.Store

    def test_memory_is_still_the_default(self):
        Store = self.template()
        store = Store()
        self.assertIsNone(store._db)
        store.add("E", "id", {"name": "x"})
        self.assertEqual(store.get("E", "id", 1)["name"], "x")

    def test_file_round_trip_keeps_records_counters_and_fks(self):
        import tempfile
        Store = self.template()
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "t.db")
            first = Store(path)
            first.add("Category", "id", {"name": "food"})
            first.add("Product", "id", {"name": "a", "price_cents": 100,
                                        "category_id": 1},
                      check_fk=[("category_id", "Category", "id", None)])
            first.close()
            second = Store(path)
            self.assertEqual(second.get("Category", "id", 1)["name"], "food")
            self.assertEqual(len(second.select("Product", [])), 1)
            third = second.add("Product", "id", {"name": "b"})
            self.assertEqual(third["id"], 2)
            with self.assertRaises(KeyError):
                second.add("Product", "id", {"name": "c", "category_id": 999},
                           check_fk=[("category_id", "Category", "id", None)])
            second.delete("Product", "id", 1)
            second.close()
            fourth = Store(path)
            self.assertEqual(len(fourth.select("Product", [])), 1)

    def test_int_and_str_keys_stay_distinct(self):
        import tempfile
        Store = self.template()
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "t.db")
            store = Store(path)
            store.add("E", "id", {"id": 1, "name": "int"})
            store.add("E", "id", {"id": "1", "name": "str"})
            store.close()
            reopened = Store(path)
            self.assertEqual(reopened.get("E", "id", 1)["name"], "int")
            self.assertEqual(reopened.get("E", "id", "1")["name"], "str")

    def test_date_values_enter_as_iso_strings_for_memory_and_file(self):
        """A body that stores `datetime.date.today()` must not blow up the
        JSON write, and memory must read back exactly what a reload gives:
        dates normalize at the door, records and criteria alike."""
        import datetime
        import tempfile
        Store = self.template()
        store = Store()
        record = store.add("Loan", "id", {
            "loan_date": datetime.date(2026, 10, 5),
            "due_date": datetime.datetime(2026, 10, 19, 12, 30)})
        self.assertEqual(record["loan_date"], "2026-10-05")
        self.assertEqual(record["due_date"], "2026-10-19T12:30:00")
        self.assertEqual(
            store.select("Loan",
                         [("due_date", "le",
                           datetime.datetime(2026, 10, 19, 12, 30))]),
            [record])
        self.assertEqual(
            store.select("Loan",
                         [("loan_date", "ge", datetime.date(2026, 10, 1))]),
            [record])
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "t.db")
            filed = Store(path)
            filed.add("Loan", "id", {
                "loan_date": datetime.date(2026, 10, 5),
                "due_date": datetime.datetime(2026, 10, 19, 12, 30)})
            filed.update("Loan", "id", 1,
                         {"return_date": datetime.date(2026, 10, 18)})
            filed.close()
            reopened = Store(path)
            self.assertEqual(reopened.get("Loan", "id", 1), {
                "id": 1, "loan_date": "2026-10-05",
                "due_date": "2026-10-19T12:30:00",
                "return_date": "2026-10-18"})


class PlanTests(unittest.TestCase):
    def test_match_param_covers_prefixes_and_rejects_noise(self):
        self.assertEqual(codegen.match_param(["expense_date"], "start_date"),
                         ("expense_date", "ge"))
        self.assertEqual(codegen.match_param(["id"], "id"), ("id", "eq"))
        self.assertIsNone(codegen.match_param(["name"], "total"))

    def test_match_param_reads_pk_aliases_and_bound_prefixes(self):
        """`author_id` names the own `id`; `min_`/`max_` are range bounds.

        The extraction spells primary keys `<entity>_id` as often as `id`;
        without the alias every read_one/update/delete by that parameter
        raised at runtime. Exact fields still win (`book_id` on a Loan
        stays the foreign key). A prefix remainder matching several fields
        refuses — first-match-wins would filter the wrong field.
        """
        self.assertEqual(codegen.match_param(["id", "name"], "author_id"),
                         ("id", "eq"))
        self.assertEqual(codegen.match_param(["id", "book_id"], "book_id"),
                         ("book_id", "eq"))
        self.assertEqual(
            codegen.match_param(["available_copies"], "min_available_copies"),
            ("available_copies", "ge"))
        self.assertEqual(
            codegen.match_param(["available_copies"], "max_available_copies"),
            ("available_copies", "le"))
        self.assertIsNone(
            codegen.match_param(["expense_date", "payment_date"], "start_date"))

    def test_match_alternatives_need_every_part_to_map(self):
        self.assertEqual(
            codegen.match_alternatives(["id", "isbn"], "book_id_or_isbn"),
            [("id", "eq"), ("isbn", "eq")])
        self.assertIsNone(codegen.match_alternatives(["id"], "id"))
        self.assertIsNone(codegen.match_alternatives(["id"], "id_or_title"))
        self.assertIsNone(
            codegen.match_alternatives(["id", "title"], "start_id_or_title"))

    def test_filter_with_pagination_plans_by_shape_when_signature_is_a_filter(self):
        """A date-range read claimed as FILTER_WITH_PAGINATION but carrying no
        pagination parameters describes a filter exactly — the filter body is
        the whole method. Pagination parameters (limit, offset) map to no
        field and the emitter refuses those bodies at generation time."""
        entry = {"pattern_id": "FILTER_WITH_PAGINATION", "decision": "decided"}
        method = {"name": "read_expenses_by_date_range",
                  "params": [{"name": "start_date", "type": "str"},
                             {"name": "end_date", "type": "str"}],
                  "return_type": "List[Expense]"}
        strategy, detail = codegen.plan_method(method, entry, ["Expense"])
        self.assertEqual(strategy, "crud:filter")
        self.assertIn("FILTER_WITH_PAGINATION", detail)

    def test_model_types_spell_str_bool_and_dict(self):
        self.assertEqual(codegen.map_type("str"), "str")
        self.assertEqual(codegen.map_type("bool"), "bool")
        self.assertEqual(codegen.map_type("dict"), "Dict[str, Any]")

    def test_filter_pattern_without_filter_name_plans_by_shape(self):
        """`read_expenses_by_category` matches no name prefix, yet describes
        a filter exactly: list return, scalar-only params."""
        entry = {"pattern_id": "FILTER_BY_FIELD", "decision": "decided"}
        method = {"name": "read_expenses_by_category",
                  "params": [{"name": "category_id", "type": "int"}],
                  "return_type": "List[Expense]"}
        strategy, detail = codegen.plan_method(method, entry, ["Expense"])
        self.assertEqual(strategy, "crud:filter")
        self.assertIn("FILTER_BY_FIELD", detail)

    def test_shape_fallback_needs_list_return_and_params(self):
        entry = {"pattern_id": "FILTER_BY_FIELD", "decision": "decided"}
        base = {"name": "read_stuff", "params": [{"name": "id", "type": "int"}]}
        kind, _ = codegen.plan_method(dict(base, return_type="None"), entry, ["E"])
        self.assertEqual(kind, "stub")
        kind, _ = codegen.plan_method(
            {"name": "read_stuff", "params": [], "return_type": "List[E]"},
            entry, ["E"])
        self.assertEqual(kind, "stub")

    def test_filter_pattern_without_filter_name_plans_by_shape(self):
        """`read_expenses_by_category` matches no name prefix, yet describes
        a filter exactly: list return, scalar-only params."""
        entry = {"pattern_id": "FILTER_BY_FIELD", "decision": "decided"}
        method = {"name": "read_expenses_by_category",
                  "params": [{"name": "category_id", "type": "int"}],
                  "return_type": "List[Expense]"}
        strategy, detail = codegen.plan_method(method, entry, ["Expense"])
        self.assertEqual(strategy, "crud:filter")
        self.assertIn("FILTER_BY_FIELD", detail)

    def test_shape_fallback_needs_list_return_and_params(self):
        entry = {"pattern_id": "FILTER_BY_FIELD", "decision": "decided"}
        base = {"name": "read_stuff", "params": [{"name": "id", "type": "int"}]}
        kind, _ = codegen.plan_method(dict(base, return_type="None"), entry, ["E"])
        self.assertEqual(kind, "stub")
        kind, _ = codegen.plan_method(
            {"name": "read_stuff", "params": [], "return_type": "List[E]"},
            entry, ["E"])
        self.assertEqual(kind, "stub")

    def test_entity_typed_params_disqualify_the_shape(self):
        """A record-carrying parameter is a create/update shape, not a filter."""
        entry = {"pattern_id": "FILTER_BY_FIELD", "decision": "decided"}
        method = {"name": "read_stuff",
                  "params": [{"name": "data", "type": "Expense"}],
                  "return_type": "List[Expense]"}
        kind, _ = codegen.plan_method(method, entry, ["Expense"])
        self.assertEqual(kind, "stub")

    def test_parameterless_filter_names_are_stubs_not_select_alls(self):
        """`find_active_members` with no status argument cannot filter: its
        old body returned every record, silently dropping the constraint."""
        for entry in ({"pattern_id": "FILTER_BY_FIELD", "decision": "decided"},
                      {"pattern_id": "READ_ALL", "decision": "decided"},
                      None):
            method = {"name": "find_active_members", "params": [],
                      "return_type": "List[Member]"}
            kind, detail = codegen.plan_method(method, entry, ["Member"])
            self.assertEqual(kind, "stub")
            self.assertIn("no parameters", detail)

    def test_other_patterns_keep_name_only_planning(self):
        entry = {"pattern_id": "THRESHOLD_SCAN", "decision": "decided"}
        method = {"name": "read_old_ones",
                  "params": [{"name": "days", "type": "int"}],
                  "return_type": "List[E]"}
        kind, _ = codegen.plan_method(method, entry, ["E"])
        self.assertEqual(kind, "stub")

    def test_refused_claim_with_single_entity_shape_reads_as_read_one(self):
        """The gap refused the AGGREGATE claim, not the signature: a single
        Budget over scalar params is the unique lookup the criteria body
        already implements. List returns stay refused."""
        method = {"name": "read_budget_by_category_and_month",
                  "params": [{"name": "category_id", "type": "int"},
                             {"name": "month", "type": "str"}],
                  "return_type": "Budget"}
        entry = {"pattern_id": "NO_PATTERN_IN_DOMAIN", "decision": "decided",
                 "claimed_pattern_id": "AGGREGATE_BY_FK_AND_DATE",
                 "rejection": "returns entity (Budget)"}
        strategy, detail = codegen.plan_method(
            method, entry, ["Budget", "Expense"])
        self.assertEqual(strategy, "crud:read_one")
        self.assertIn("NO_PATTERN_IN_DOMAIN", detail)
        self.assertIn("parameter shape", detail)
        listed = dict(method, return_type="List[Budget]")
        kind, _ = codegen.plan_method(listed, entry, ["Budget", "Expense"])
        self.assertEqual(kind, "stub")


class ServiceCompositionTests(unittest.TestCase):
    """Services compose from repo methods; the rest stay stubs.

    Rename delegation (`get_X_by_id` → `read_X_by_id`) needs identical
    parameters and returns onto a mechanical target — delegating past a
    guard or into a stub would move the refusal. Filter composition runs a
    FILTER service over the entity's read-all with the kernel's own
    criteria; entity-typed or unmappable parameters stay stubs.
    """

    def ctx(self):
        match = {"pattern_id": "FILTER_BY_FIELD", "decision": "decided"}
        service_methods = [
            {"name": "get_widget_by_id",
             "params": [{"name": "widget_id", "type": "int"}],
             "return_type": "Widget", "description": "get one"},
            {"name": "find_widgets_by_title",
             "params": [{"name": "title", "type": "str"}],
             "return_type": "List[Widget]", "description": "find"},
            {"name": "find_widgets_by_color",
             "params": [{"name": "color", "type": "str"}],
             "return_type": "List[Widget]", "description": "unmappable"},
            {"name": "read_widgets_by_blueprint",
             "params": [{"name": "blueprint", "type": "Widget"}],
             "return_type": "List[Widget]", "description": "entity param"},
            {"name": "delete_everything", "params": [],
             "return_type": "None", "description": "custom"},
            {"name": "list_widgets", "params": [],
             "return_type": "List[Widget]", "description": "passthrough"},
        ]
        matches = {
            "contract:WidgetService.get_widget_by_id":
                {"pattern_id": "STANDARD_CRUD", "decision": "decided"},
            "contract:WidgetService.find_widgets_by_name": dict(match),
            "contract:WidgetService.find_widgets_by_color": dict(match),
            "contract:WidgetService.read_widgets_by_blueprint": dict(match),
        }
        return {
            "models": [{"name": "Widget", "fields": [
                {"name": "widget_id", "type": "int", "primary_key": True},
                {"name": "title", "type": "string"}]}],
            "errors": [], "entity_names": ["Widget"],
            "services": [{"service_name": "WidgetService",
                          "methods": service_methods}],
            "repositories": [{"entity": "Widget",
                              "interface_name": "WidgetRepository",
                              "methods": [
                                  {"name": "read_widget_by_id",
                                   "params": [{"name": "widget_id", "type": "int"}],
                                   "return_type": "Widget"},
                                  {"name": "read_all_widgets", "params": [],
                                   "return_type": "List[Widget]"}]}],
            "mappings": {}, "match_index": matches, "adapters": [],
            "components": {},
        }

    def exec_services(self, text):
        import importlib.util
        import types
        from unittest import mock
        spec = importlib.util.spec_from_file_location(
            "store", "kernel/codegen_store_template.py")
        store = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(store)
        mods = {"models": types.ModuleType("models"),
                "errors": types.ModuleType("errors"),
                "store": store}
        mods["models"].Widget = lambda **kw: kw
        with mock.patch.dict(sys.modules, mods):
            namespace = dict(mods)
            exec(compile(text, "services.py", "exec"), namespace)
        return namespace

    def test_rename_and_filter_run_unmappable_and_custom_refuse(self):
        import types
        ctx = self.ctx()
        stats = {"source": "t", "implemented": 0, "stubs": 0,
                 "stub_reasons": []}
        text = generator.emit_services(
            ctx, generator._repo_index(ctx), stats)
        namespace = self.exec_services(text)

        calls = []

        class FakeRepo:
            def read_widget_by_id(self, widget_id=None):
                calls.append(("one", widget_id))
                return {"widget_id": widget_id, "title": "w"}

            def read_all_widgets(self):
                calls.append(("all", None))
                return [{"widget_id": 1, "title": "a"},
                        {"widget_id": 2, "title": "b"}]

        service = namespace["WidgetService"]({"WidgetRepository": FakeRepo()})
        self.assertEqual(service.get_widget_by_id(1)["title"], "w")
        self.assertEqual(calls[-1], ("one", 1))
        found = service.find_widgets_by_title("a")
        self.assertEqual([r["widget_id"] for r in found], [1])
        self.assertEqual(len(service.list_widgets()), 2)
        with self.assertRaises(NotImplementedError):
            service.find_widgets_by_color("red")
        with self.assertRaises(NotImplementedError):
            service.read_widgets_by_blueprint({"x": 1})
        with self.assertRaises(NotImplementedError):
            service.delete_everything()
        kinds = {m["method"]: (m["implemented"], m["how"])
                 for m in stats["methods"]}
        self.assertEqual(kinds["get_widget_by_id"], (True, "rename"))
        self.assertTrue(kinds["find_widgets_by_title"][0])
        self.assertTrue(kinds["find_widgets_by_title"][1].startswith("compose:"))
        self.assertFalse(kinds["find_widgets_by_color"][0])
        self.assertFalse(kinds["read_widgets_by_blueprint"][0])
        self.assertFalse(kinds["delete_everything"][0])
        self.assertTrue(kinds["list_widgets"][0])

    def test_sanitize_never_returns_a_non_identifier(self):
        for raw in ["", "9lives", "a b-c", "none"]:
            ident = codegen.sanitize(raw)
            self.assertTrue(ident.isidentifier(), raw)

    def test_a_flag_string_taken_twice_degrades_gracefully(self):
        """`book list` gives `-a` to two options: the second keeps its long flag."""
        stats = {}
        lines = generator._emit_options("", "p", [
            {"name": "-author", "short": "-a", "type": "bool", "required": False, "default": None},
            {"name": "-author-only", "short": "-a", "type": "bool", "required": False, "default": None},
        ], stats)
        second = next(line for line in lines if "author-only" in line)
        self.assertIn("'-author-only'", second)
        self.assertNotIn("'-a',", second)

    def test_a_declared_option_no_field_reads_is_reported(self):
        """`member list -active-only` parsed and did nothing: a finding, and
        a consumed sibling flag proves the check has no false positives."""
        from kernel.consistency.checks_surface import COMMAND_VERB_STEMS
        adapters = [
            {"action_name": "list_members", "target_service": "MemberRepository",
             "target_method": "read_all_members", "input_fields": []},
            {"action_name": "find_members", "target_service": "MemberRepository",
             "target_method": "find_members_by_name",
             "input_fields": [
                 {"field_name": "name", "target_param": "name",
                  "transform": "DIRECT", "required": False}]}]
        invocation = {"commands": [
            {"name": "member", "options": [], "subcommands": [
                {"name": "list", "options": [
                    {"name": "-active-only", "short": "-a", "type": "bool",
                     "required": False, "default": None}]},
                {"name": "find", "options": [
                    {"name": "-name", "type": "str", "required": False,
                     "default": None}]}]}]}
        bindings, _ = codegen.bind_commands(adapters, invocation,
                                            COMMAND_VERB_STEMS)
        ctx = {
            "repositories": [{"entity": "Member",
                              "interface_name": "MemberRepository",
                              "methods": [
                                  {"name": "read_all_members", "params": [],
                                   "return_type": "List[Member]"},
                                  {"name": "find_members_by_name",
                                   "params": [{"name": "name", "type": "str"}],
                                   "return_type": "List[Member]"}]}],
            "services": [],
            "models": [{"name": "Member", "fields": [
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "name", "type": "string"}]}],
            "adapters": adapters, "entity_names": ["Member"],
            "components": {"facade": {"invocation": invocation}},
        }
        stats = {"prog": "member", "unmapped": []}
        text = generator.emit_cli(ctx, bindings, stats)
        # The surface keeps declaring the flag; the finding says it is dead.
        self.assertIn("'-active-only'", text)
        self.assertEqual(
            stats["dead_options"],
            ["member list: -active-only — no adapter field reads it"])

    def test_scoring_prefers_the_command_own_entity(self):
        """`budget add` reaches the budget creator, not `add_category`."""
        from kernel.consistency.checks_surface import COMMAND_VERB_STEMS
        adapters = [
            {"action_name": "add_category", "target_service": "CategoryRepository",
             "target_method": "create_category", "input_fields": []},
            {"action_name": "create_budget", "target_service": "BudgetRepository",
             "target_method": "create_budget", "input_fields": []},
        ]
        invocation = {"commands": [{"name": "budget",
                                    "subcommands": [{"name": "add", "options": []}]}]}
        bindings, unmapped = codegen.bind_commands(adapters, invocation, COMMAND_VERB_STEMS)
        self.assertEqual(bindings[("budget", "add")][0], "create_budget")
        self.assertEqual(unmapped, [])

    def test_field_binding_folds_abbreviations_and_date_aliases(self):
        dests = ["name", "price", "category", "from_date", "to_date", "method"]
        self.assertEqual(codegen.bind_field(dests, "price_cents"), "price")
        self.assertEqual(codegen.bind_field(dests, "category_id"), "category")
        self.assertEqual(codegen.bind_field(dests, "start_date"), "from_date")
        self.assertEqual(codegen.bind_field(dests, "end_date"), "to_date")
        self.assertEqual(codegen.bind_field(dests, "payment_method"), "method")
        self.assertIsNone(codegen.bind_field(dests, "file_path"))
        self.assertIsNone(codegen.bind_field(["start_date", "end_date"], "date"))

    def test_uncovered_fields_judge_bound_leaves_only(self):
        """A required flag missing on the owning leaf strands the action;
        orphan actions and sibling-assembled `data` do not."""
        adapters = [
            {"action_name": "do_it", "target_service": "S", "target_method": "do_it",
             "input_fields": [
                 {"field_name": "name", "target_param": "name", "transform": "DIRECT", "required": True},
                 {"field_name": "amount", "target_param": "amount", "transform": "DIRECT", "required": True}]},
            {"action_name": "orphan", "target_service": "S", "target_method": "orphan",
             "input_fields": [
                 {"field_name": "ghost", "target_param": "ghost", "transform": "DIRECT", "required": True}]},
            {"action_name": "wrap", "target_service": "S", "target_method": "wrap",
             "input_fields": [
                 {"field_name": "data", "target_param": "data", "transform": "DIRECT", "required": True},
                 {"field_name": "name", "target_param": "data", "transform": "DIRECT", "required": True}]},
        ]
        invocation = {"commands": [
            {"name": "thing", "options": [],
             "subcommands": [{"name": "do", "options": [
                 {"name": "--name", "type": "str", "required": True, "default": None}]}]},
            {"name": "wrap", "options": [],
             "subcommands": [{"name": "wrap", "options": [
                 {"name": "--name", "type": "str", "required": True, "default": None}]}]}]}
        targets = {"wrap": {"data": "Thing"}}
        uncovered = codegen.uncovered_required_fields(adapters, invocation, targets)
        self.assertIn(("do_it", "amount"), uncovered)
        self.assertNotIn(("do_it", "name"), [tuple(u) for u in uncovered])
        self.assertFalse([u for u in uncovered if u[0] == "orphan"])
        self.assertFalse([u for u in uncovered if u[0] == "wrap"])

    def test_fields_assembling_unknown_model_fields_are_reported(self):
        """`author_id` into a `Book` with no such field always fails construction."""
        adapters = [{"action_name": "add_book", "target_service": "R",
                     "target_method": "create_book",
                     "input_fields": [
                         {"field_name": "title", "target_param": "book",
                          "transform": "DIRECT", "required": True},
                         {"field_name": "author_id", "target_param": "book",
                          "transform": "DIRECT", "required": True}]}]
        services = [{"service_name": "R", "methods": [
            {"name": "create_book", "params": [{"name": "book", "type": "Book"}]}]}]
        models = [{"name": "Book", "fields": [{"name": "title", "type": "string"}]}]
        unknown = codegen.unknown_model_fields(adapters, services, [], models)
        self.assertEqual(unknown, [("add_book", "author_id", "Book")])

    def test_scalar_targets_and_known_fields_are_silent(self):
        adapters = [{"action_name": "get", "target_service": "R",
                     "target_method": "read_one",
                     "input_fields": [
                         {"field_name": "id", "target_param": "id",
                          "transform": "DIRECT", "required": True}]}]
        services = [{"service_name": "R", "methods": [
            {"name": "read_one", "params": [{"name": "id", "type": "int"}]}]}]
        models = [{"name": "Book", "fields": [{"name": "id", "type": "int"}]}]
        self.assertEqual(codegen.unknown_model_fields(adapters, services, [], models), [])


class CliChoiceTests(unittest.TestCase):
    """One leaf, several possible methods: flags pick, partial flags name gaps.

    A recorded route (`member list -active-only` → `find_active_members`)
    wins when its flag is passed. A mechanical alternate (`budget list
    -category -month`) must have every one of its flags, and a partial set
    names the missing flag instead of quietly reading everything. A leaf
    whose own method takes arguments is nobody's fallback: `product remove
    -id` may never redirect to the read that shares the flag.
    """

    def emitted(self, ctx):
        from kernel.consistency.checks_surface import COMMAND_VERB_STEMS
        bindings, _unmapped = codegen.bind_commands(
            ctx["adapters"],
            (ctx["components"].get("facade") or {}).get("invocation") or {},
            COMMAND_VERB_STEMS)
        stats = {"prog": "app", "unmapped": []}
        return generator.emit_cli(ctx, bindings, stats), stats

    def run_cli(self, text, repository_factories, argv,
                models=("Member", "Budget", "Product")):
        """Execute the emitted CLI with stand-in modules; `(rc, stdout)`."""
        import types
        from unittest import mock

        class NullStore:
            def close(self):
                pass

        modules = {}
        for name in ("models", "errors", "store", "repositories", "services"):
            modules[name] = types.ModuleType(name)
        for name in models:
            setattr(modules["models"], name, type(name, (), {}))
        modules["store"].Store = lambda path=None: NullStore()
        for name, factory in repository_factories.items():
            setattr(modules["repositories"], name, factory)
        with mock.patch.dict(sys.modules, modules):
            namespace = {}
            exec(compile(text, "cli.py", "exec"), namespace)  # noqa: S102
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = namespace["main"](argv)
        return code, buffer.getvalue()

    @staticmethod
    def member_ctx(routes):
        adapters = [
            {"action_name": "list_members", "target_service": "MemberRepository",
             "target_method": "read_all_members", "input_fields": []}]
        invocation = {"commands": [{"name": "member", "options": [], "subcommands": [
            {"name": "list", "options": [
                {"name": "-active-only", "short": "-a", "type": "bool",
                 "required": False, "default": None}]}]}]}
        return {
            "models": [{"name": "Member", "fields": [
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "name", "type": "string"},
                {"name": "is_active", "type": "boolean"}]}],
            "errors": [], "services": [],
            "repositories": [{"entity": "Member",
                              "interface_name": "MemberRepository",
                              "methods": [
                                  {"name": "read_all_members", "params": [],
                                   "return_type": "List[Member]"},
                                  {"name": "find_active_members", "params": [],
                                   "return_type": "List[Member]"}]}],
            "mappings": {}, "match_index": {}, "adapters": adapters,
            "entity_names": ["Member"],
            "components": {"facade": {"invocation": invocation}},
            "routes": routes,
        }

    def test_recorded_route_wins_when_its_flag_is_passed(self):
        route = {"kind": "route", "command": "member", "subcommand": "list",
                 "flag": "active_only", "service": "MemberRepository",
                 "method": "find_active_members", "decided_by": "user"}
        text, stats = self.emitted(self.member_ctx([route]))
        line = next(l for l in text.splitlines() if "('member', 'list')" in l)
        self.assertLess(line.index("'find_active_members'"),
                        line.index("'list_members'"))
        self.assertNotIn("dead_options", stats)
        self.assertEqual(stats["choice_routes"],
                         ["member list: -active-only -> find_active_members"])

        class MemberRepository:
            def __init__(self, store):
                pass

            def read_all_members(self):
                return ["all-members"]

            def find_active_members(self):
                return ["active-members"]

        code, output = self.run_cli(text, {"MemberRepository": MemberRepository},
                                    ["--db", ":memory:", "member", "list",
                                     "-active-only"])
        self.assertEqual(code, 0)
        self.assertIn("active-members", output)
        code, output = self.run_cli(text, {"MemberRepository": MemberRepository},
                                    ["--db", ":memory:", "member", "list"])
        self.assertEqual(code, 0)
        self.assertIn("all-members", output)

    def test_an_unrouted_flag_stays_declared_and_reported(self):
        """The surface is the documents': the flag keeps parsing, and the
        finding — not a guess — is what says nothing reads it."""
        text, stats = self.emitted(self.member_ctx([]))
        self.assertIn("'-active-only'", text)
        self.assertEqual(
            stats["dead_options"],
            ["member list: -active-only — no adapter field reads it"])

        class MemberRepository:
            def __init__(self, store):
                pass

            def read_all_members(self):
                return ["all-members"]

            def find_active_members(self):
                return ["active-members"]

        code, output = self.run_cli(text, {"MemberRepository": MemberRepository},
                                    ["--db", ":memory:", "member", "list",
                                     "-active-only"])
        self.assertEqual(code, 0)
        self.assertIn("all-members", output)

    @staticmethod
    def author_ctx(routes):
        adapters = [
            {"action_name": "list_books", "target_service": "BookRepository",
             "target_method": "read_all_books", "input_fields": []}]
        invocation = {"commands": [{"name": "book", "options": [], "subcommands": [
            {"name": "list", "options": [
                {"name": "--author", "short": "-a", "type": "int",
                 "required": False, "default": None}]}]}]}
        return {
            "models": [{"name": "Book", "fields": [
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "title", "type": "string"},
                {"name": "author_id", "type": "int"}]}],
            "errors": [], "services": [],
            "repositories": [
                {"entity": "Book", "interface_name": "BookRepository",
                 "methods": [
                     {"name": "read_all_books", "params": [],
                      "return_type": "List[Book]"}]},
                {"entity": "Author", "interface_name": "AuthorRepository",
                 "methods": [
                     {"name": "find_books_by_author",
                      "params": [{"name": "author_id", "type": "int"}],
                      "return_type": "List[Book]"}]}],
            "mappings": {}, "match_index": {}, "adapters": adapters,
            "entity_names": ["Book", "Author"],
            "components": {"facade": {"invocation": invocation}},
            "routes": routes,
        }

    def test_value_route_supplies_the_chosen_parameter(self):
        route = {"kind": "route", "command": "book", "subcommand": "list",
                 "flag": "author", "service": "AuthorRepository",
                 "method": "find_books_by_author", "target_param": "author_id",
                 "option_type": "int", "transform": "DIRECT",
                 "decided_by": "user"}
        text, stats = self.emitted(self.author_ctx([route]))
        line = next(l for l in text.splitlines() if "('book', 'list')" in l)
        self.assertLess(line.index("'find_books_by_author_author'"),
                        line.index("'list_books'"))
        self.assertIn("'author_id', ('author_id', 'DIRECT', True)",
                      text)
        self.assertNotIn("dead_options", stats)

        class BookRepository:
            def __init__(self, store):
                pass

            def read_all_books(self):
                return ["all-books"]

        class AuthorRepository:
            def __init__(self, store):
                pass

            def find_books_by_author(self, author_id=None):
                return [f"author:{author_id}"]

        code, output = self.run_cli(
            text, {"BookRepository": BookRepository,
                   "AuthorRepository": AuthorRepository},
            ["--db", ":memory:", "book", "list", "--author", "7"],
            models=("Book", "Author"))
        self.assertEqual(code, 0)
        self.assertIn("author:7", output)
        code, output = self.run_cli(
            text, {"BookRepository": BookRepository,
                   "AuthorRepository": AuthorRepository},
            ["--db", ":memory:", "book", "list"], models=("Book", "Author"))
        self.assertEqual(code, 0)
        self.assertIn("all-books", output)

    @staticmethod
    def budget_ctx():
        adapters = [
            {"action_name": "read_all_budgets",
             "target_service": "BudgetRepository",
             "target_method": "read_all_budgets", "input_fields": []},
            {"action_name": "read_budget_by_category_and_month",
             "target_service": "BudgetRepository",
             "target_method": "read_budget_by_category_and_month",
             "input_fields": [
                 {"field_name": "category_id", "target_param": "category_id",
                  "transform": "DIRECT", "required": True},
                 {"field_name": "month", "target_param": "month",
                  "transform": "DIRECT", "required": True}]}]
        invocation = {"commands": [{"name": "budget", "options": [], "subcommands": [
            {"name": "list", "options": [
                {"name": "-category", "short": "-c", "type": "int",
                 "required": False, "default": None},
                {"name": "-month", "short": "-m", "type": "str",
                 "required": False, "default": None}]}]}]}
        return {
            "models": [{"name": "Budget", "fields": [
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "category_id", "type": "int"},
                {"name": "month", "type": "string"},
                {"name": "amount_limit_cents", "type": "int"}]}],
            "errors": [], "services": [],
            "repositories": [{"entity": "Budget",
                              "interface_name": "BudgetRepository",
                              "methods": [
                                  {"name": "read_all_budgets", "params": [],
                                   "return_type": "List[Budget]"},
                                  {"name": "read_budget_by_category_and_month",
                                   "params": [
                                       {"name": "category_id", "type": "int"},
                                       {"name": "month", "type": "str"}],
                                   "return_type": "Budget"}]}],
            "mappings": {}, "match_index": {}, "adapters": adapters,
            "entity_names": ["Budget"],
            "components": {"facade": {"invocation": invocation}},
            "routes": [],
        }

    def test_alternate_needs_every_flag_and_names_the_missing_one(self):
        text, stats = self.emitted(self.budget_ctx())
        line = next(l for l in text.splitlines() if "('budget', 'list')" in l)
        self.assertLess(line.index("'read_budget_by_category_and_month'"),
                        line.index("'read_all_budgets'"))
        self.assertNotIn("dead_options", stats)
        self.assertEqual(
            stats["choice_routes"],
            ["budget list: -category -month -> read_budget_by_category_and_month"])

        class BudgetRepository:
            def __init__(self, store):
                pass

            def read_all_budgets(self):
                return ["all-budgets"]

            def read_budget_by_category_and_month(self, category_id=None,
                                                  month=None):
                return [f"filtered:{category_id}:{month}"]

        code, output = self.run_cli(
            text, {"BudgetRepository": BudgetRepository},
            ["--db", ":memory:", "budget", "list", "-category", "1",
             "-month", "2026-10"])
        self.assertEqual(code, 0)
        self.assertIn("filtered:1:2026-10", output)
        code, output = self.run_cli(text, {"BudgetRepository": BudgetRepository},
                                    ["--db", ":memory:", "budget", "list"])
        self.assertEqual(code, 0)
        self.assertIn("all-budgets", output)
        code, output = self.run_cli(text, {"BudgetRepository": BudgetRepository},
                                    ["--db", ":memory:", "budget", "list",
                                     "-category", "1"])
        self.assertEqual(code, 1)
        self.assertIn("also needs -month", output)

    @staticmethod
    def product_ctx():
        adapters = [
            {"action_name": "remove_product",
             "target_service": "ProductRepository",
             "target_method": "delete_product",
             "input_fields": [
                 {"field_name": "id", "target_param": "id",
                  "transform": "DIRECT", "required": True}]},
            {"action_name": "get_product",
             "target_service": "ProductRepository",
             "target_method": "read_one_product",
             "input_fields": [
                 {"field_name": "id", "target_param": "id",
                  "transform": "DIRECT", "required": True}]}]
        invocation = {"commands": [{"name": "product", "options": [], "subcommands": [
            {"name": "remove", "options": [
                {"name": "-id", "short": "-i", "type": "int",
                 "required": True, "default": None}]}]}]}
        return {
            "models": [{"name": "Product", "fields": [
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "name", "type": "string"}]}],
            "errors": [], "services": [],
            "repositories": [{"entity": "Product",
                              "interface_name": "ProductRepository",
                              "methods": [
                                  {"name": "delete_product", "params": [
                                      {"name": "id", "type": "int"}],
                                   "return_type": "None"},
                                  {"name": "read_one_product", "params": [
                                      {"name": "id", "type": "int"}],
                                   "return_type": "Product"}]}],
            "mappings": {}, "match_index": {}, "adapters": adapters,
            "entity_names": ["Product"],
            "components": {"facade": {"invocation": invocation}},
            "routes": [],
        }

    def test_a_flag_never_redirects_a_write_to_a_read(self):
        """`product remove -id` is a delete with a required argument — the
        read sharing the flag is not a filtered version of it."""
        text, _stats = self.emitted(self.product_ctx())
        line = next(l for l in text.splitlines() if "('product', 'remove')" in l)
        self.assertIn("'remove_product'", line)
        self.assertNotIn("'get_product'", line)

        deleted = []

        class ProductRepository:
            def __init__(self, store):
                pass

            def delete_product(self, id=None):
                deleted.append(id)

            def read_one_product(self, id=None):
                return f"read:{id}"

        code, output = self.run_cli(text, {"ProductRepository": ProductRepository},
                                    ["--db", ":memory:", "product", "remove",
                                     "-id", "7"])
        self.assertEqual(code, 0)
        self.assertEqual(deleted, [7])
        self.assertNotIn("read:7", output)


class StubFillTests(unittest.TestCase):
    """`--model` fills refused stubs, under mechanical guards.

    The answer is a body, not a vote: it replaces the raise only when the
    module still compiles and the body touches no `self.<name>` or store
    method the module never defined. Accepted bodies are tagged and still
    counted as stubs — reading them is the review.
    """

    @staticmethod
    def rendered():
        ctx = {
            "models": [{"name": "Widget", "fields": [
                {"name": "widget_id", "type": "int", "primary_key": True},
                {"name": "title", "type": "string"}]}],
            "errors": [], "entity_names": ["Widget"],
            "services": [{"service_name": "WidgetService", "methods": [
                {"name": "custom_total", "params": [], "return_type": "int",
                 "description": "A custom aggregate."}]}],
            "repositories": [{"entity": "Widget",
                              "interface_name": "WidgetRepository",
                              "methods": [
                                  {"name": "read_all_widgets", "params": [],
                                   "return_type": "List[Widget]"},
                                  {"name": "export_widgets",
                                   "params": [{"name": "file_path",
                                               "type": "str"}],
                                   "return_type": "None"}]}],
            "mappings": {}, "match_index": {}, "adapters": [],
            "components": {},
        }
        stats = {"prog": "widgets", "source": "out/widgets", "unmapped": [],
                 "implemented": 0, "stubs": 0, "stub_reasons": []}
        return generator.render_program(ctx, stats), stats

    def fill(self, files, answers):
        """`fill_stubs` with a stand-in model answering body by body."""
        from unittest import mock
        replies = [mock.Mock(text=text, tokens=9, seconds=0.1, budget=3584,
                             finish_reason="stop", truncated=False)
                   for text in answers]
        with mock.patch.object(generator.runner, "load_model",
                               return_value=object()), \
                mock.patch.object(generator.runner, "generate_free",
                                  side_effect=replies):
            return generator.fill_stubs(files, "fake.gguf", "requirements text",
                                        out=lambda _line: None)

    def test_written_bodies_land_indented_marked_and_imported(self):
        files, _stats = self.rendered()
        # The model writes in the style of the module it was shown — 4-space
        # members, 8-space bodies. Losing the first line's indent to a strip
        # was the first live run's bug: every answer, all five, arrived at
        # the wrong depth and was refused as "unexpected indent".
        rows = self.fill(files, [
            "    rows = self._store.all(self.ENTITY)\n"
            "    with open(file_path, \"w\") as handle:\n"
            "        handle.write(json.dumps(rows))\n"
            "    return [json.dumps(record) for record in rows]",
            "        return 0",
        ])
        self.assertEqual(rows, [
            ("WidgetRepository.export_widgets", "written", "added import json"),
            ("WidgetService.custom_total", "written", ""),
        ])
        repos = files["repositories.py"]
        self.assertIn("        rows = self._store.all(self.ENTITY)", repos)
        self.assertIn("        return [json.dumps(record) for record in rows]",
                      repos)
        self.assertIn("import json", repos)
        self.assertIn("[llm-written by fake.gguf — review]", repos)
        self.assertNotIn("no pattern entry and an ambiguous method name", repos)
        compile(repos, "repositories.py", "exec")
        services = files["services.py"]
        self.assertIn("        return 0", services)
        self.assertIn("[llm-written by fake.gguf — review]", services)
        compile(services, "services.py", "exec")

    def test_whole_method_answers_are_unwrapped(self):
        """`def` line, echoed docstring and fences are the model's packaging:
        they are dropped, the body lands at the stub's depth."""
        files, _stats = self.rendered()
        rows = self.fill(files, [
            "    def export_widgets(self, file_path: str = None) -> None:\n"
            '        """Writes widgets to a file."""\n'
            "        rows = self._store.all(self.ENTITY)\n"
            '        with open(file_path, "w") as handle:\n'
            "            handle.write(str(rows))\n",
            "```python\n"
            "    return 0\n"
            "```",
        ])
        self.assertEqual(rows, [
            ("WidgetRepository.export_widgets", "written", ""),
            ("WidgetService.custom_total", "written", ""),
        ])
        repos = files["repositories.py"]
        self.assertIn('        with open(file_path, "w") as handle:', repos)
        self.assertIn("            handle.write(str(rows))", repos)
        self.assertNotIn('"""Writes widgets to a file."""', repos)
        compile(repos, "repositories.py", "exec")
        compile(files["services.py"], "services.py", "exec")

    def test_a_lone_closing_fence_is_packaging_not_code(self):
        """The prompt opens the fence; the model only closes it. That
        ``` line sat at indent 0, dragged min-indent to zero, and refused
        every first live answer — this is the shape that did it."""
        files, _stats = self.rendered()
        rows = self.fill(files, [
            "    def export_widgets(self, file_path: str = None) -> None:\n"
            "        rows = self._store.all(self.ENTITY)\n"
            "        with open(file_path, \"w\") as handle:\n"
            "            handle.write(str(rows))\n"
            "        return None\n"
            "```",
            "return 0",
        ])
        self.assertEqual(rows, [
            ("WidgetRepository.export_widgets", "written", ""),
            ("WidgetService.custom_total", "written", ""),
        ])
        repos = files["repositories.py"]
        self.assertIn("        rows = self._store.all(self.ENTITY)", repos)
        self.assertNotIn("```", repos)
        compile(repos, "repositories.py", "exec")

    def test_a_continuation_answer_takes_the_models_own_python_block(self):
        """The Qwen3 raw shape: it echoes the stub inside the prompt's open
        fence, closes the fence, reasons, and writes the body in a
        ```python block of its own. The old parse read the closing fence as
        the next block's opener and returned the prose between the two."""
        answer = (
            "    def export_widgets(self, file_path: str = None) -> None:\n"
            '        """Writes widgets. [rule plain-method]"""\n'
            "        raise NotImplementedError(\n"
            '            "plain-method")\n'
            "```\n"
            "\n"
            "We are to write the body — an em-dash, U+2014.\n"
            "A first attempt follows:\n"
            "\n"
            "```python\n"
            "rows = self._store.all(self.ENTITY)\n"
            "return None\n"
            "```\n"
        )
        self.assertEqual(
            generator._clean_body(answer),
            ["rows = self._store.all(self.ENTITY)", "return None"])

    def test_a_narrated_front_keeps_the_fenced_block(self):
        """Prose inside the prompt's fence is not a body; the model's own
        fenced block wins, as it does outside a continuation."""
        self.assertEqual(
            generator._clean_body("Sure:\n```python\n    return 0\n```"),
            ["return 0"])
        self.assertEqual(
            generator.extract_code("Sure:\n```python\nreturn 0\n```",
                                   open_fence=True),
            "return 0")

    def test_clean_body_dedents_the_answers_own_base(self):
        self.assertEqual(
            generator._clean_body("    if value:\n        return value\n"
                                  "    return None\n"),
            ["if value:", "    return value", "return None"])
        self.assertEqual(
            generator._clean_body("```python\n    x = 1\n```"),
            ["x = 1"])
        self.assertEqual(
            generator._clean_body('def f():\n    """Doc.\n\n    More."""\n'
                                  "    return 1\n"),
            ["return 1"])

    def test_an_answer_that_keeps_talking_after_the_body_is_flagged(self):
        self.assertTrue(generator._answer_continued(
            "    return 1\n```\n\nWait — no.\n\n```python\n"
            "    return 2\n```\n"))
        self.assertFalse(generator._answer_continued(
            "    return 1\n```"))
        self.assertFalse(generator._answer_continued(
            "```python\n    return 1\n```"))
        self.assertEqual(
            generator._last_code_block(
                "    return 1\n```\n\nWait — no.\n\n```python\n"
                "    return 2\n```\n"),
            "    return 2")

    def test_a_deliberating_answer_uses_its_final_block(self):
        """The exact-context return body: draft, closing fence, reasoning,
        final block. The final block is the answer the model arrived at;
        the draft must not land, and no repair call is needed."""
        from unittest import mock
        files, _stats = self.rendered()
        seen = []

        def answer(llm, prompt, label, **kwargs):
            seen.append(label)
            if label == "stub:WidgetService.custom_total":
                text = ("        return 1\n```\n\nWait — no.\n\n"
                        "```python\n        return 2\n```\n")
                return mock.Mock(text=text, tokens=9, seconds=0.1,
                                 budget=3584, finish_reason="stop",
                                 truncated=False)
            return mock.Mock(text="        return None\n", tokens=9,
                             seconds=0.1, budget=3584,
                             finish_reason="stop", truncated=False)

        with mock.patch.object(generator.runner, "load_model",
                               return_value=object()), \
                mock.patch.object(generator.runner, "generate_free",
                                  side_effect=answer):
            rows = generator.fill_stubs(files, "fake.gguf",
                                        "requirements text",
                                        out=lambda _line: None)
        by_label = {label: (status, note) for label, status, note in rows}
        status, note = by_label["WidgetService.custom_total"]
        self.assertEqual(status, "written")
        self.assertIn("used the final block", note)
        self.assertFalse([label for label in seen
                          if label == "stub:WidgetService.custom_total:repair"])
        self.assertIn("        return 2", files["services.py"])
        self.assertNotIn("        return 1", files["services.py"])

    def test_a_bad_final_block_is_repaired_from_that_block(self):
        """The final block is the draft to repair even when it is wrong:
        the first block was already rejected, so quoting it again would
        invite the same draft back."""
        from unittest import mock
        files, _stats = self.rendered()
        seen = []

        def answer(llm, prompt, label, **kwargs):
            seen.append((label, prompt))
            if label == "stub:WidgetService.custom_total":
                text = ("        return 1\n```\n\nWait — no.\n\n"
                        "```python\n        return (((\n```\n")
                return mock.Mock(text=text, tokens=9, seconds=0.1,
                                 budget=3584, finish_reason="stop",
                                 truncated=False)
            if label == "stub:WidgetService.custom_total:repair":
                return mock.Mock(text="        return 2\n", tokens=9,
                                 seconds=0.1, budget=3584,
                                 finish_reason="stop", truncated=False)
            return mock.Mock(text="        return None\n", tokens=9,
                             seconds=0.1, budget=3584,
                             finish_reason="stop", truncated=False)

        with mock.patch.object(generator.runner, "load_model",
                               return_value=object()), \
                mock.patch.object(generator.runner, "generate_free",
                                  side_effect=answer):
            rows = generator.fill_stubs(files, "fake.gguf",
                                        "requirements text",
                                        out=lambda _line: None)
        by_label = {label: (status, note) for label, status, note in rows}
        status, note = by_label["WidgetService.custom_total"]
        self.assertEqual(status, "written")
        self.assertIn("repaired: the body does not compile", note)
        repair = next(prompt for label, prompt in seen
                      if label == "stub:WidgetService.custom_total:repair")
        self.assertIn("return (((", repair)
        self.assertNotIn("return 1", repair)
        self.assertIn("        return 2", files["services.py"])
        self.assertNotIn("        return (((\n", files["services.py"])

    def test_a_body_that_does_not_compile_keeps_the_stub(self):
        files, _stats = self.rendered()
        rows = self.fill(files, ["return (((", "return (((", "return 0"])
        label, status, note = rows[0]
        self.assertEqual((label, status),
                         ("WidgetRepository.export_widgets", "kept"))
        self.assertTrue(
            note.startswith("still refused: the body does not compile"),
            note)
        self.assertIn("raise NotImplementedError(", files["repositories.py"])
        self.assertNotIn("[llm-written", files["repositories.py"])

    def test_a_body_that_adds_an_import_does_not_shift_the_next_stub(self):
        """Bodies fill bottom-up; an import added for one lands at the top
        of the file and moves every stub above it, so each splice must
        re-find its span in the current text. Trusting the original span
        cut one line short and left the stub's own reason line behind —
        the live `borrow_book` refusal was this shift, blamed on the
        model."""
        text = (
            '"""Repositories."""\n'
            "\n"
            "import models\n"
            "import errors\n"
            "\n"
            "\n"
            "class WidgetRepository:\n"
            '    ENTITY = "Widget"\n'
            "\n"
            "    def __init__(self, store):\n"
            "        self._store = store\n"
            "\n"
            "    def export_widgets(self, file_path: str = None) -> None:\n"
            '        """Writes widgets. [rule plain-method: method needs '
            'custom logic]"""\n'
            "        raise NotImplementedError(\n"
            '            "WidgetRepository.export_widgets: rule plain-method: '
            'method needs custom logic")\n'
            "\n"
            "    def stamp_widgets(self) -> None:\n"
            '        """Stamps widgets. [rule plain-method: method needs '
            'custom logic]"""\n'
            "        raise NotImplementedError(\n"
            '            "WidgetRepository.stamp_widgets: rule plain-method: '
            'method needs custom logic")\n'
        )
        files = {
            "repositories.py": text,
            "store.py": "class Store:\n"
                        "    def all(self, entity):\n"
                        "        return []\n",
        }
        rows = self.fill(files, [
            "rows = self._store.all(self.ENTITY)\n"
            "return datetime.date.today()",
            "handle = open(file_path, \"w\")\n"
            "handle.close()\n"
            "return None",
        ])
        self.assertEqual(rows, [
            ("WidgetRepository.stamp_widgets", "written",
             "added import datetime"),
            ("WidgetRepository.export_widgets", "written", ""),
        ])
        module = files["repositories.py"]
        compile(module, "repositories.py", "exec")
        self.assertIn("import datetime", module)
        self.assertNotIn("raise NotImplementedError(", module)
        self.assertLess(module.index("def export_widgets"),
                        module.index("return None"))
        self.assertLess(module.index("return None"),
                        module.index("def stamp_widgets"))
        self.assertLess(module.index("def stamp_widgets"),
                        module.index("datetime.date.today()"))

    def test_an_invented_name_keeps_the_stub(self):
        cases = [
            ("return self.helper()",
             "calls self.helper, which the module does not define"),
            ("return self._store.frobnicate(self.ENTITY)",
             "calls self._store.frobnicate, which the store does not define"),
            ("return models.date_today()",
             "calls models.date_today, which models.py does not define"),
            ("raise errors.BookUnavailableError('no')",
             "calls errors.BookUnavailableError, which errors.py does not "
             "define"),
            ('raise NotImplementedError("no idea")',
             "the model kept it unimplemented"),
            ("", "the model returned nothing"),
        ]
        for answer, expected in cases:
            files, _stats = self.rendered()
            rows = self.fill(files, [answer, answer, "return 0"])
            self.assertEqual(rows[0], ("WidgetRepository.export_widgets",
                                       "kept",
                                       "still refused: " + expected))
            self.assertIn("raise NotImplementedError(",
                          files["repositories.py"])

    def test_prompt_names_fields_record_types_and_error_classes(self):
        """The module cannot show what the sibling modules define — the
        fields, the error classes. The first live run guessed them all
        (`book.get`, `book.author`, `models.date_today`)."""
        from unittest import mock
        files, _stats = self.rendered()
        captured = []

        def answer(llm, prompt, label, **kwargs):
            captured.append(prompt)
            return mock.Mock(text="        return None\n", tokens=3,
                             seconds=0.1, budget=3584, finish_reason="stop",
                             truncated=False)

        with mock.patch.object(generator.runner, "load_model",
                               return_value=object()), \
                mock.patch.object(generator.runner, "generate_free",
                                  side_effect=answer):
            generator.fill_stubs(files, "fake.gguf", "req",
                                 out=lambda _line: None)
        prompt = captured[0]
        self.assertIn("Widget(widget_id: int, title: str)", prompt)
        self.assertIn('record.get("field")', prompt)
        self.assertIn("errors.py defines only these: AppError", prompt)
        self.assertIn("stdlib modules", prompt)
        # The shapes bare names hid: a live body stored a `datetime` the
        # store could not serialize, another called pydantic's `.copy`.
        self.assertIn("no `copy(...)` with keyword updates", prompt)
        self.assertIn('- Date fields hold ISO strings (`"2026-10-05"`):',
                      prompt)
        # The service prompt must not teach the store a service lacks: the
        # live `search_books` refusal copied exactly that example.
        service_prompt = captured[-1]
        self.assertIn("Widget(widget_id: int, title: str)", service_prompt)
        self.assertIn("A service body has no", service_prompt)
        self.assertNotIn('record.get("field")', service_prompt)

    def test_nothing_to_fill_never_loads_the_model(self):
        from unittest import mock
        ctx = {
            "models": [], "errors": [], "entity_names": [],
            "services": [], "repositories": [], "mappings": {},
            "match_index": {}, "adapters": [], "components": {},
        }
        stats = {"prog": "empty", "source": "out/empty", "unmapped": [],
                 "implemented": 0, "stubs": 0, "stub_reasons": []}
        files = generator.render_program(ctx, stats)
        with mock.patch.object(generator.runner, "load_model") as loader:
            self.assertEqual(generator.fill_stubs(files, "fake.gguf", "req"),
                             [])
            loader.assert_not_called()

    def test_the_stub_pass_uses_the_chat_template_when_the_model_has_one(self):
        """The ask is a conversation. Raw completion made the instruct model
        reason at the document instead of answering it (Qwen3 probe: every
        raw budget filled, the chat template stopped at 220 tokens of code)."""
        from unittest import mock
        files, _stats = self.rendered()
        model = mock.Mock(metadata={"tokenizer.chat_template": "{{ prompt }}"})
        replies = [
            mock.Mock(text="rows = self._store.all(self.ENTITY)\n"
                           "with open(file_path, \"w\") as handle:\n"
                           "    handle.write(str(rows))\n"
                           "return None",
                      tokens=9, seconds=0.1, budget=3584,
                      finish_reason="stop", truncated=False),
            mock.Mock(text="return 0", tokens=9, seconds=0.1, budget=3584,
                      finish_reason="stop", truncated=False),
        ]
        with mock.patch.object(generator.runner, "load_model",
                               return_value=model), \
                mock.patch.object(generator.runner, "generate_chat",
                                  side_effect=replies) as chat, \
                mock.patch.object(generator.runner, "generate_free") as raw:
            rows = generator.fill_stubs(files, "fake.gguf", "req",
                                        out=lambda _line: None)
        self.assertEqual(rows, [
            ("WidgetRepository.export_widgets", "written", ""),
            ("WidgetService.custom_total", "written", ""),
        ])
        chat.assert_called()
        raw.assert_not_called()

    def test_a_truncated_answer_is_retried_then_kept_not_spliced(self):
        """A cut-off body compiles and can still be wrong. The first attempt
        stops at `MAX_NEW_TOKENS`; the retry gets the room the prompt left,
        and an answer truncated even then never lands."""
        from unittest import mock
        files, _stats = self.rendered()

        class Model:
            metadata = {"tokenizer.chat_template": "{{ prompt }}"}

            def n_ctx(self):
                return 8192

            def tokenize(self, data):
                return []

        def cut(budget):
            return mock.Mock(text="rows = self._store.all(", tokens=budget,
                             seconds=1.0, budget=budget,
                             finish_reason="length", truncated=True)

        replies = [cut(3584), cut(8128),
                   mock.Mock(text="return 0", tokens=3, seconds=0.1,
                             budget=8128, finish_reason="stop",
                             truncated=False)]
        with mock.patch.object(generator.runner, "load_model",
                               return_value=Model()), \
                mock.patch.object(generator.runner, "generate_chat",
                                  side_effect=replies) as chat:
            rows = generator.fill_stubs(files, "fake.gguf", "req",
                                        out=lambda _line: None)
        self.assertEqual(rows, [
            ("WidgetRepository.export_widgets", "kept",
             "the answer was cut off at the 8128-token ceiling"),
            ("WidgetService.custom_total", "written", ""),
        ])
        labels = [call.args[2] for call in chat.call_args_list]
        self.assertEqual(labels, ["stub:WidgetRepository.export_widgets",
                                  "stub:WidgetRepository.export_widgets:retry",
                                  "stub:WidgetService.custom_total"])
        self.assertEqual(chat.call_args_list[1].kwargs["max_new_tokens"], 8128)
        self.assertIn("raise NotImplementedError(", files["repositories.py"])
        self.assertNotIn("[llm-written", files["repositories.py"])

    def test_minimal_stub_context_omits_the_api_and_references(self):
        """The experiment knob: rules, requirements and the module stay; the
        repository signatures and API facts go, so a run shows which facts
        the model actually needed."""
        from unittest import mock
        files, _stats = self.rendered()
        captured = []

        def answer(llm, prompt, label, **kwargs):
            captured.append(prompt)
            return mock.Mock(text="        return None\n", tokens=3,
                             seconds=0.1, budget=3584, finish_reason="stop",
                             truncated=False)

        with mock.patch.object(generator.runner, "load_model",
                               return_value=object()), \
                mock.patch.object(generator.runner, "generate_free",
                                  side_effect=answer):
            generator.fill_stubs(files, "fake.gguf", "requirements text",
                                 out=lambda _line: None, context="minimal")
        prompt = captured[0]
        self.assertIn("requirements:", prompt)
        self.assertIn("module (repositories.py):", prompt)
        self.assertIn("Reply with ONLY the replacement", prompt)
        self.assertNotIn("Methods this module may lean on:", prompt)
        self.assertNotIn("The data the sibling modules hand you", prompt)
        # Minimal drops the reference list, so the service rule must not
        # tell the model to call "the methods listed below" - there are none.
        service_prompt = next(p for p in captured
                              if "module (services.py):" in p)
        self.assertNotIn("methods listed below", service_prompt)
        self.assertIn("read through the repositories", service_prompt)

        files, _stats = self.rendered()
        captured.clear()
        with mock.patch.object(generator.runner, "load_model",
                               return_value=object()), \
                mock.patch.object(generator.runner, "generate_free",
                                  side_effect=answer):
            generator.fill_stubs(files, "fake.gguf", "requirements text",
                                 out=lambda _line: None)
        full_service = next(p for p in captured
                            if "module (services.py):" in p)
        self.assertIn("methods listed below", full_service)

    def test_honest_stub_context_replaces_the_full_facts(self):
        """The corrected block keeps the surfaces the minimal run proved
        load-bearing (references, fields, errors) but stops the two lies a
        live answer acted on: nullable `read_one_*` and ISO-string dates."""
        from unittest import mock
        files, _stats = self.rendered()
        captured = []

        def answer(llm, prompt, label, **kwargs):
            captured.append(prompt)
            return mock.Mock(text="        return None\n", tokens=3,
                             seconds=0.1, budget=3584, finish_reason="stop",
                             truncated=False)

        with mock.patch.object(generator.runner, "load_model",
                               return_value=object()), \
                mock.patch.object(generator.runner, "generate_free",
                                  side_effect=answer):
            generator.fill_stubs(files, "fake.gguf", "requirements text",
                                 out=lambda _line: None, context="honest")
        service = next(p for p in captured
                       if "module (services.py):" in p)
        self.assertIn("Methods this module may lean on:", service)
        self.assertIn("`read_one_*` raises", service)
        self.assertIn("delegate to it", service)
        self.assertIn("space-separated text does not match", service)
        self.assertNotIn("Date fields hold ISO strings", service)

    def test_honest_facts_treat_errors_as_a_vocabulary(self):
        files = {
            "models.py": "class Widget:\n    widget_id: int = None\n",
            "errors.py": "class WidgetNotFoundError(LookupError):\n    pass\n",
        }
        text = "\n".join(
            generator._honest_api_reference(files, "services.py"))
        self.assertIn("WidgetNotFoundError", text)
        self.assertIn("vocabulary, not a work order", text)
        self.assertIn("not add checks", text)

    def test_honest_search_rule_says_fields_are_independent(self):
        info = {"cls": "BookRepository",
                "def": "def search_books_by_title_author_isbn(self, query):",
                "reason": "test", "file": "repositories.py"}
        module = "class BookRepository:\n    pass\n"
        honest = generator.stub_prompt("requirements", module, info,
                                       context="honest")
        self.assertIn("`elif` chain", honest)
        minimal = generator.stub_prompt("requirements", module, info,
                                        context="minimal")
        self.assertNotIn("`elif` chain", minimal)

    def test_exact_stub_context_shows_models_as_code_and_repeats_the_contract(self):
        """The compressed field line becomes the real source, and the
        method's signature and return class sit above the ask."""
        from unittest import mock
        files, _stats = self.rendered()
        captured = []

        def answer(llm, prompt, label, **kwargs):
            captured.append(prompt)
            return mock.Mock(text="        return None\n", tokens=3,
                             seconds=0.1, budget=3584, finish_reason="stop",
                             truncated=False)

        with mock.patch.object(generator.runner, "load_model",
                               return_value=object()), \
                mock.patch.object(generator.runner, "generate_free",
                                  side_effect=answer):
            generator.fill_stubs(files, "fake.gguf", "requirements text",
                                 out=lambda _line: None, context="exact")
        service = next(p for p in captured
                       if "module (services.py):" in p)
        self.assertIn("models.py, exactly as defined", service)
        self.assertIn("@dataclass", service)
        self.assertIn("class Widget:", service)
        self.assertNotIn("Widget(widget_id: int", service)
        self.assertIn("The method you are writing:", service)
        self.assertIn("def custom_total", service)
        self.assertLess(service.index("module (services.py):"),
                        service.index("The method you are writing:"))
        self.assertLess(service.index("The method you are writing:"),
                        service.index("Now write the body"))
        self.assertIn("Changing a dataclass does not save it", service)

    def test_exact_contract_repeats_the_returned_dataclass(self):
        info = {"cls": "LibraryService",
                "def": ("def return_book(self, loan_id: int = None)"
                        " -> models.Loan:"),
                "file": "services.py"}
        files = {"models.py":
                 "from dataclasses import dataclass\n\n"
                 "@dataclass\nclass Loan:\n    id: int = None\n"
                 "    book_id: int = None\n"}
        text = "\n".join(generator._target_contract(info, files))
        self.assertIn("def return_book", text)
        self.assertIn("@dataclass", text)
        self.assertIn("class Loan:", text)
        self.assertIn("book_id: int", text)
        self.assertIn("update_*", text)
        self.assertNotIn("class Book:", text)

    def test_exact_contract_repeats_the_target_requirement(self):
        info = {"cls": "LibraryService",
                "def": ("def borrow_book(self, member_id: int = None, "
                        "book_id: int = None) -> models.Loan:"),
                "file": "services.py"}
        files = {"models.py":
                 "from dataclasses import dataclass\n\n"
                 "@dataclass\nclass Loan:\n    id: int = None\n"}
        requirements = (
            "9. **LibraryService** — business logic:\n"
            "   - borrow_book(member_id, book_id): checks availability, "
            "creates loan, decrements copies\n"
            "   - return_book(loan_id): sets return_date, updates status, "
            "increments copies\n")
        text = "\n".join(generator._target_contract(info, files,
                                                    requirements))
        self.assertIn("The requirement for this method:", text)
        self.assertIn("checks availability, creates loan, decrements copies",
                      text)
        self.assertNotIn("sets return_date", text)
        self.assertNotIn("Set `return_date`", text)
        self.assertNotIn("The order is:", text)
        self.assertLess(text.index("The requirement for this method:"),
                        text.index("The method you are writing:"))

    def test_exact_contract_renders_the_human_confirmed_facts(self):
        info = {"cls": "LibraryService",
                "def": ("def return_book(self, loan_id: int = None)"
                        " -> models.Loan:"),
                "file": "services.py"}
        files = {"models.py":
                 "from dataclasses import dataclass\n\n"
                 "@dataclass\nclass Loan:\n    id: int = None\n"
                 "    book_id: int = None\n"}
        contract = {
            "holder": "LibraryService", "method": "return_book",
            "preconditions": [{"check": "loan exists",
                               "error": "LoanNotFoundError"}],
            "effects": [
                {"target": "loan.return_date", "op": "set",
                 "value": "now", "write": "LoanRepository.update_loan"},
                {"target": "book.available_copies", "op": "increment",
                 "by": "1", "write": "BookRepository.update_book"},
            ],
            "forbid": [{"target": "loan.return_date",
                        "reads": "loan.due_date",
                        "message": "the return date is when it comes back"}],
            "order": ["preconditions", "BookRepository.update_book"],
        }
        text = "\n".join(generator._target_contract(
            info, files, "return_book(loan_id): sets return_date",
            contract=contract))
        self.assertIn("The human-confirmed contract for this method:", text)
        self.assertIn("`loan.return_date`", text)
        self.assertIn("to `now`", text)
        self.assertIn("`BookRepository.update_book(...)`", text)
        self.assertIn("must not read `loan.due_date`", text)
        self.assertIn("order: `preconditions` -> "
                      "`BookRepository.update_book`", text)
        self.assertLess(text.index("The human-confirmed contract"),
                        text.index("The method you are writing:"))

    def test_a_raise_when_contract_renders_its_polarity(self):
        info = {"cls": "LibraryService",
                "def": ("def return_book(self, loan_id: int = None)"
                        " -> models.Loan:"),
                "file": "services.py"}
        files = {"models.py":
                 "from dataclasses import dataclass\n\n"
                 "@dataclass\nclass Loan:\n    id: int = None\n"
                 "    status: str = None\n"}
        contract = {
            "holder": "LibraryService", "method": "return_book",
            "preconditions": [{
                "check": "loan.status == 'returned'",
                "error": "InvalidReturnDateError",
                "raise_when": "true",
            }],
        }
        text = "\n".join(generator._target_contract(
            info, files, contract=contract))
        self.assertIn(
            "raise `InvalidReturnDateError` when `loan.status == "
            "'returned'` is true", text)
        self.assertNotIn("otherwise raise `InvalidReturnDateError`", text)

    def test_main_model_flag_fills_the_fixture_stubs(self):
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as directory:
            out = write_out(Path(directory) / "shop", fixture())
            writes = ("rows = self._store.all(self.ENTITY)\n"
                      "with open(file_path, \"w\") as handle:\n"
                      "    handle.write(str(rows))\n"
                      "return None")
            replies = [mock.Mock(text=writes, tokens=3, seconds=0.1,
                                 budget=3584, finish_reason="stop",
                                 truncated=False),
                       mock.Mock(text="return 0", tokens=3, seconds=0.1,
                                 budget=3584, finish_reason="stop",
                                 truncated=False)]
            with mock.patch.object(generator.runner, "load_model",
                                   return_value=object()), \
                    mock.patch.object(generator.runner, "generate_free",
                                      side_effect=replies), \
                    io.StringIO() as buffer, redirect_stdout(buffer):
                self.assertEqual(generator.main([out, "--model", "fake.gguf"]), 0)
                printed = buffer.getvalue()
            self.assertIn("llm written: ProductRepository.export_products",
                          printed)
            self.assertIn("llm written: ShopService.price_report", printed)
            self.assertNotIn("still refused", printed)
            self.assertNotIn("one repair ask", printed)
            text = (Path(out) / "generated" / "repositories.py").read_text()
            self.assertIn("[llm-written by fake.gguf — review]", text)
            dump = (Path(out) / "llm_stub_answers.json").read_text()
            self.assertIn('"ProductRepository.export_products"', dump)
            self.assertIn('"ShopService.price_report"', dump)

    def test_main_stub_context_minimal_reaches_the_ask(self):
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as directory:
            out = write_out(Path(directory) / "shop", fixture())
            captured = []

            def answer(llm, prompt, label, **kwargs):
                captured.append(prompt)
                return mock.Mock(text="        return None\n", tokens=3,
                                 seconds=0.1, budget=3584,
                                 finish_reason="stop", truncated=False)

            with mock.patch.object(generator.runner, "load_model",
                                   return_value=object()), \
                    mock.patch.object(generator.runner, "generate_free",
                                      side_effect=answer), \
                    io.StringIO() as buffer, redirect_stdout(buffer):
                self.assertEqual(
                    generator.main([out, "--model", "fake.gguf",
                                    "--stub-context", "minimal"]), 0)
                printed = buffer.getvalue()
            self.assertIn("minimal context: requirements + module only",
                          printed)
            self.assertNotIn("Methods this module may lean on:", captured[0])

    def test_main_stub_context_honest_reaches_the_ask(self):
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as directory:
            out = write_out(Path(directory) / "shop", fixture())
            captured = []

            def answer(llm, prompt, label, **kwargs):
                captured.append(prompt)
                return mock.Mock(text="        return None\n", tokens=3,
                                 seconds=0.1, budget=3584,
                                 finish_reason="stop", truncated=False)

            with mock.patch.object(generator.runner, "load_model",
                                   return_value=object()), \
                    mock.patch.object(generator.runner, "generate_free",
                                      side_effect=answer), \
                    io.StringIO() as buffer, redirect_stdout(buffer):
                self.assertEqual(
                    generator.main([out, "--model", "fake.gguf",
                                    "--stub-context", "honest"]), 0)
                printed = buffer.getvalue()
            self.assertIn("honest context: references + corrected facts",
                          printed)
            service = next(p for p in captured
                           if "module (services.py):" in p)
            self.assertIn("`read_one_*` raises", service)

    def test_main_stub_context_exact_reaches_the_ask(self):
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as directory:
            out = write_out(Path(directory) / "shop", fixture())
            captured = []

            def answer(llm, prompt, label, **kwargs):
                captured.append(prompt)
                return mock.Mock(text="        return None\n", tokens=3,
                                 seconds=0.1, budget=3584,
                                 finish_reason="stop", truncated=False)

            with mock.patch.object(generator.runner, "load_model",
                                   return_value=object()), \
                    mock.patch.object(generator.runner, "generate_free",
                                      side_effect=answer), \
                    io.StringIO() as buffer, redirect_stdout(buffer):
                self.assertEqual(
                    generator.main([out, "--model", "fake.gguf",
                                    "--stub-context", "exact"]), 0)
                printed = buffer.getvalue()
            self.assertIn("exact context: models as code + local contract",
                          printed)
            service = next(p for p in captured
                           if "module (services.py):" in p)
            self.assertIn("models.py, exactly as defined", service)

    def test_a_refused_body_is_repaired_once_and_lands(self):
        """The repair ask quotes the complaint; a corrected answer passes
        the same checks and lands like any other accepted body."""
        files, _stats = self.rendered()
        rows = self.fill(files, [
            "return None",
            "with open(file_path, \"w\") as handle:\n"
            "    handle.write(\"\")\n"
            "return None",
            "return 0",
        ])
        self.assertEqual(rows, [
            ("WidgetRepository.export_widgets", "written",
             "repaired: parameter `file_path` is never used in the body"),
            ("WidgetService.custom_total", "written", ""),
        ])
        repos = files["repositories.py"]
        self.assertIn('with open(file_path, "w") as handle:', repos)
        self.assertNotIn("raise NotImplementedError(", repos)
        self.assertIn("[llm-written by fake.gguf — review]", repos)
        compile(repos, "repositories.py", "exec")

    def test_a_second_refusal_keeps_the_stub(self):
        files, _stats = self.rendered()
        rows = self.fill(files, ["return None", "return None", "return 0"])
        self.assertEqual(rows[0],
                         ("WidgetRepository.export_widgets", "kept",
                          "still refused: parameter `file_path` is never "
                          "used in the body"))
        self.assertIn("raise NotImplementedError(", files["repositories.py"])
        self.assertNotIn("[llm-written", files["repositories.py"])

    def test_the_repair_prompt_shows_the_refused_answer(self):
        from unittest import mock
        files, _stats = self.rendered()
        replies = [
            mock.Mock(text="return None", tokens=3, seconds=0.1, budget=3584,
                      finish_reason="stop", truncated=False),
            mock.Mock(text="handle = open(file_path, \"w\")\n"
                           "handle.close()\nreturn None",
                      tokens=3, seconds=0.1, budget=3584,
                      finish_reason="stop", truncated=False),
            mock.Mock(text="return 0", tokens=3, seconds=0.1, budget=3584,
                      finish_reason="stop", truncated=False),
        ]
        with mock.patch.object(generator.runner, "load_model",
                               return_value=object()), \
                mock.patch.object(generator.runner, "generate_free",
                                  side_effect=replies) as ask:
            generator.fill_stubs(files, "fake.gguf", "requirements text",
                                 out=lambda _line: None)
        repair = ask.call_args_list[1].args[1]
        self.assertIn("Your previous answer to this method was refused:",
                      repair)
        self.assertIn("  - parameter `file_path` is never used in the body",
                      repair)
        self.assertIn("The refused answer was:", repair)
        self.assertIn("return None", repair)

    def test_a_confirmed_contract_reaches_the_prompt_and_the_check(self):
        """A record from method_contracts.json is passed into the exact ask
        and the same record refuses a body that omits its fact. The generator
        sees only the contract vocabulary, not the application's words."""
        from unittest import mock
        files, _stats = self.rendered()
        contract = {
            "holder": "WidgetService", "method": "custom_total",
            "preconditions": [{"check": "the total is valid",
                               "error": "AppError"}],
        }
        replies = [
            mock.Mock(text='with open(file_path, "w") as handle:\n'
                           '    handle.write("")\nreturn None',
                      tokens=3, seconds=0.1, budget=3584,
                      finish_reason="stop", truncated=False),
            mock.Mock(text="return 0", tokens=3, seconds=0.1, budget=3584,
                      finish_reason="stop", truncated=False),
            mock.Mock(text='raise errors.AppError("invalid")\nreturn 0',
                      tokens=3, seconds=0.1, budget=3584,
                      finish_reason="stop", truncated=False),
        ]
        with mock.patch.object(generator.runner, "load_model",
                               return_value=object()), \
                mock.patch.object(generator.runner, "generate_free",
                                  side_effect=replies) as ask:
            rows = generator.fill_stubs(
                files, "fake.gguf", "requirements text",
                out=lambda _line: None, context="exact",
                contracts=[contract])
        self.assertEqual(rows[1][:2],
                         ("WidgetService.custom_total", "written"))
        self.assertIn("confirmed contract requires", rows[1][2])
        first_custom = ask.call_args_list[1].args[1]
        self.assertIn("The human-confirmed contract for this method:",
                      first_custom)
        self.assertIn("the total is valid", first_custom)
        repair = ask.call_args_list[2].args[1]
        self.assertIn(
            "the confirmed contract requires `the total is valid` to raise "
            "`AppError`", repair)

    def test_the_repair_ask_quotes_the_judged_body_not_the_raw_transcript(self):
        """The raw transcript is what made the live repair ask overflow the
        context (Qwen3's echo-and-reason answer was 13 kB); the complaints
        are about the body, so the body is what goes back."""
        from unittest import mock
        files, _stats = self.rendered()
        first = ("    def export_widgets(self, file_path: str = None) -> None:\n"
                 '        """Writes widgets."""\n'
                 "        raise NotImplementedError(\n"
                 '            "plain-method")\n'
                 "```\n"
                 "\n"
                 "Reasoning that is not the answer, with an em-dash.\n"
                 "\n"
                 "```python\n"
                 "return None\n"
                 "```\n")
        replies = [
            mock.Mock(text=first, tokens=30, seconds=0.1, budget=3584,
                      finish_reason="stop", truncated=False),
            mock.Mock(text="handle = open(file_path, \"w\")\n"
                           "handle.close()\nreturn None",
                      tokens=3, seconds=0.1, budget=3584,
                      finish_reason="stop", truncated=False),
            mock.Mock(text="return 0", tokens=3, seconds=0.1, budget=3584,
                      finish_reason="stop", truncated=False),
        ]
        with mock.patch.object(generator.runner, "load_model",
                               return_value=object()), \
                mock.patch.object(generator.runner, "generate_free",
                                  side_effect=replies) as ask:
            generator.fill_stubs(files, "fake.gguf", "requirements text",
                                 out=lambda _line: None)
        repair = ask.call_args_list[1].args[1]
        self.assertIn("The refused answer was:", repair)
        self.assertIn("return None", repair)
        self.assertNotIn("Reasoning that is not the answer", repair)

    def test_the_dump_records_both_attempts_when_repaired(self):
        import tempfile
        from unittest import mock
        files, _stats = self.rendered()
        with tempfile.TemporaryDirectory() as directory:
            dump = Path(directory) / "llm_stub_answers.json"
            replies = [
                mock.Mock(text="return None", tokens=3, seconds=0.1,
                          budget=3584, finish_reason="stop", truncated=False),
                mock.Mock(text="handle = open(file_path, \"w\")\n"
                               "handle.close()\nreturn None",
                          tokens=3, seconds=0.1, budget=3584,
                          finish_reason="stop", truncated=False),
                mock.Mock(text="return 0", tokens=3, seconds=0.1, budget=3584,
                          finish_reason="stop", truncated=False),
            ]
            with mock.patch.object(generator.runner, "load_model",
                                   return_value=object()), \
                    mock.patch.object(generator.runner, "generate_free",
                                      side_effect=replies):
                generator.fill_stubs(files, "fake.gguf", "requirements text",
                                     out=lambda _line: None,
                                     dump_path=str(dump))
            data = json.loads(dump.read_text())
        self.assertEqual(data[0]["label"], "WidgetRepository.export_widgets")
        self.assertEqual(data[0]["status"], "written")
        self.assertEqual(
            data[0]["complaints"],
            ["parameter `file_path` is never used in the body"])
        self.assertEqual(data[0]["first_answer"], "return None")
        self.assertIn("handle = open(file_path", data[0]["answer"])
        # The attempt facts a truncation is judged by, per attempt.
        self.assertEqual(data[0]["finish_reason"], "stop")
        self.assertFalse(data[0]["truncated"])
        self.assertEqual(data[0]["first_finish_reason"], "stop")
        self.assertFalse(data[0]["first_truncated"])
        self.assertEqual(data[0]["tokens"], 3)
        self.assertEqual(data[0]["context"], "full")


class BodyRefusalTests(unittest.TestCase):
    """A compiling answer can still import outside the prompt's surface."""

    def test_an_import_outside_the_allowed_modules_is_refused(self):
        self.assertEqual(
            generator._body_refusal(
                ["import numpy as np", "return None"],
                frozenset({"fetch"}), frozenset()),
            "imports `numpy`, which is not one of the modules the prompt "
            "allows")

    def test_an_allowed_inline_import_is_fine(self):
        self.assertIsNone(
            generator._body_refusal(
                ["from datetime import datetime, timedelta", "return None"],
                frozenset({"fetch"}), frozenset()))


class ContractComplaintTests(unittest.TestCase):
    """The API facts a compiling body can still break, as complaints.

    Each shape here shipped in a live run and compiled: a book with no
    `author` attribute (the fields were listed in the prompt), a
    `dict.keys()[0]` subscript, a `year` parameter never read, a name read
    before its assignment, and a service returning the updated book from
    a method declared `-> models.Loan`.
    """

    module = (
        "import models\n"
        "import errors\n"
        "\n"
        "\n"
        "class BookRepository:\n"
        '    ENTITY = "Book"\n'
        "\n"
        "    def read_all_books(self) -> List[models.Book]:\n"
        "        return []\n"
        "\n"
        "    def update_book(self) -> models.Book:\n"
        "        return None\n"
        "\n"
        "    def fetch(self) -> models.Book:\n"
        '        raise NotImplementedError("refused")\n'
    )
    models = ("class Book:\n"
              "    id: int = 0\n"
              '    title: str = ""\n'
              "    author_id: int = 0\n")

    def complaints(self, body, info=None, module=None, models=None,
                   references="", requirement="", contract=None):
        files = {"models.py": self.models if models is None else models}
        info = info or {"cls": "BookRepository",
                        "def": "def fetch(self) -> List[models.Book]:",
                        "reason": "refused"}
        return generator._body_complaints(
            body, info, self.module if module is None else module,
            references, files, requirement=requirement, contract=contract)

    def test_an_unknown_name_is_a_complaint(self):
        self.assertEqual(
            self.complaints(["return frobnicate(1)"]),
            ["uses `frobnicate`, which neither the module nor the body "
             "binds"])

    def test_a_body_level_import_binds_its_names(self):
        info = {"cls": "BookRepository",
                "def": "def fetch(self) -> None:",
                "reason": "refused"}
        body = ["from datetime import datetime, timedelta",
                "loan_date = datetime.now()",
                "due_date = loan_date + timedelta(days=14)",
                "return None"]
        self.assertEqual(self.complaints(body, info=info), [])

    def test_a_field_the_model_lacks_names_the_real_fields(self):
        self.assertEqual(
            self.complaints(["book = models.Book()",
                             "return book.author"]),
            ["`book.author`: Book has no field `author` "
             "(fields: id, title, author_id)"])

    def test_a_repository_read_is_typed_for_field_checks(self):
        info = {"cls": "BookRepository",
                "def": "def fetch(self, book_id: int = None) "
                       "-> models.Book:",
                "reason": "refused"}
        module = self.module + (
            "\n    def read_one_book(self, book_id: int = None) "
            "-> models.Book | None:\n        return None\n")
        self.assertEqual(
            self.complaints(["loan = self.read_one_book(book_id)",
                             "loan.loan_date = 1",
                             "return loan"], info=info, module=module),
            ["`loan.loan_date`: Book has no field `loan_date` "
             "(fields: id, title, author_id)",
             "`loan.loan_date` is changed, but `loan` is never passed to "
             "an update_* method; a dataclass is a copy, so the change is "
             "lost"])

    def test_a_changed_repository_read_must_be_updated(self):
        info = {"cls": "BookRepository",
                "def": "def fetch(self, book_id: int = None) "
                       "-> models.Book:",
                "reason": "refused"}
        module = self.module + (
            "\n    def read_one_book(self, book_id: int = None) "
            "-> models.Book | None:\n        return None\n")
        body = ["book = self.read_one_book(book_id)",
                "book.title = 'new'",
                "return book"]
        self.assertEqual(
            self.complaints(body, info=info, module=module),
            ["`book.title` is changed, but `book` is never passed to an "
             "update_* method; a dataclass is a copy, so the change is lost"])
        self.assertEqual(
            self.complaints(body[:2] + ["self.update_book(book_id, book)"]
                            + body[2:], info=info, module=module),
            [])

    def test_a_create_before_a_refusal_is_a_complaint(self):
        info = {"cls": "BookRepository",
                "def": "def fetch(self, book_id: int = None) "
                       "-> List[models.Book]:",
                "reason": "refused"}
        body = ["loan = self._repos['LoanRepository'].create_loan("
                "models.Loan())",
                "book = self._repos['BookRepository'].read_one_book(book_id)",
                "if book is None:",
                "    raise errors.BookNotFoundError(book_id)",
                "if book.available_copies <= 0:",
                "    raise errors.InsufficientCopiesError(book_id)",
                "return loan"]
        self.assertEqual(
            self.complaints(body, info=info),
            ["`create_loan(...)` runs before `raise BookNotFoundError(...)`; "
             "the record is stored even when the operation is refused — "
             "validate first, create, then update; do not move the update "
             "ahead of the create",
             "`create_loan(...)` runs before "
             "`raise InsufficientCopiesError(...)`; the record is stored "
             "even when the operation is refused — validate first, create, "
             "then update; do not move the update ahead of the create"])

    def test_validation_before_the_create_is_clean(self):
        info = {"cls": "BookRepository",
                "def": "def fetch(self, book_id: int = None) "
                       "-> List[models.Book]:",
                "reason": "refused"}
        body = ["book = self._repos['BookRepository'].read_one_book(book_id)",
                "if book is None:",
                "    raise errors.BookNotFoundError(book_id)",
                "loan = self._repos['LoanRepository'].create_loan("
                "models.Loan())",
                "return loan"]
        self.assertEqual(self.complaints(body, info=info), [])

    def test_a_create_in_the_other_branch_is_not_blamed(self):
        info = {"cls": "BookRepository",
                "def": "def fetch(self, book_id: int = None) "
                       "-> List[models.Book]:",
                "reason": "refused"}
        body = ["if book_id:",
                "    loan = self._repos['LoanRepository'].create_loan("
                "models.Loan())",
                "else:",
                "    raise errors.BookNotFoundError(book_id)",
                "return models.Book()"]
        self.assertEqual(self.complaints(body, info=info), [])

    def test_an_update_before_the_create_is_a_complaint(self):
        info = {"cls": "BookRepository",
                "def": "def fetch(self, book_id: int = None) "
                       "-> List[models.Book]:",
                "reason": "refused"}
        body = ["book = self._repos['BookRepository'].read_one_book(book_id)",
                "book.available_copies -= 1",
                "self._repos['BookRepository'].update_book(book_id, book)",
                "loan = self._repos['LoanRepository'].create_loan("
                "models.Loan())",
                "return loan"]
        self.assertEqual(
            self.complaints(body, info=info),
            ["`update_book(...)` runs before `create_loan(...)`; if the "
             "create fails, the change is kept without the new record — "
             "create first, then update"])

    def test_the_create_before_the_update_is_clean(self):
        info = {"cls": "BookRepository",
                "def": "def fetch(self, book_id: int = None) "
                       "-> List[models.Book]:",
                "reason": "refused"}
        body = ["book = self._repos['BookRepository'].read_one_book(book_id)",
                "book.available_copies -= 1",
                "loan = self._repos['LoanRepository'].create_loan("
                "models.Loan())",
                "self._repos['BookRepository'].update_book(book_id, book)",
                "return loan"]
        self.assertEqual(self.complaints(body, info=info), [])

    def test_a_confirmed_forbid_catches_a_forbidden_source(self):
        info = {"cls": "LibraryService",
                "def": "def return_book(self, loan_id: int = None) "
                       "-> models.Loan:",
                "file": "services.py"}
        models = ("class Loan:\n"
                  "    id: int = 0\n"
                  "    book_id: int = 0\n"
                  "    return_date: datetime = None\n"
                  "    due_date: datetime = None\n"
                  "    status: str = ''\n")
        body = [
            "loan = self._repos['LoanRepository'].read_one_loan(loan_id)",
            "if not loan:",
            "    raise errors.LoanNotFoundError(loan_id)",
            "loan.return_date = datetime.datetime.fromisoformat("
            "loan.due_date)",
            "loan.status = 'returned'",
            "updated_loan = self._repos['LoanRepository'].update_loan("
            "loan_id, loan)",
            "return updated_loan",
        ]
        contract = {
            "holder": "LibraryService", "method": "return_book",
            "effects": [{"target": "loan.return_date", "op": "set",
                         "write": "LoanRepository.update_loan"}],
            "forbid": [{"target": "loan.return_date",
                        "reads": "loan.due_date",
                        "message": "the return date is when the book comes "
                                   "back, not when it was due"}],
        }
        self.assertEqual(
            self.complaints(body, info=info, models=models,
                            contract=contract),
            ["the return date is when the book comes back, not when it was "
             "due"])

    def test_a_confirmed_now_effect_is_clean(self):
        info = {"cls": "LibraryService",
                "def": "def return_book(self, loan_id: int = None) "
                       "-> models.Loan:",
                "file": "services.py"}
        models = ("class Loan:\n"
                  "    id: int = 0\n"
                  "    book_id: int = 0\n"
                  "    return_date: datetime = None\n"
                  "    due_date: datetime = None\n"
                  "    status: str = ''\n")
        body = [
            "loan = self._repos['LoanRepository'].read_one_loan(loan_id)",
            "if not loan:",
            "    raise errors.LoanNotFoundError(loan_id)",
            "loan.return_date = datetime.datetime.now()",
            "loan.status = 'returned'",
            "updated_loan = self._repos['LoanRepository'].update_loan("
            "loan_id, loan)",
            "return updated_loan",
        ]
        contract = {
            "holder": "LibraryService", "method": "return_book",
            "effects": [{"target": "loan.return_date", "op": "set",
                         "value": "now",
                         "write": "LoanRepository.update_loan"}],
            "forbid": [{"target": "loan.return_date",
                        "reads": "loan.due_date"}],
        }
        self.assertEqual(
            self.complaints(body, info=info, models=models,
                            contract=contract), [])

    def test_a_confirmed_raise_when_true_rejects_the_inverted_guard(self):
        info = {"cls": "LibraryService",
                "def": "def return_book(self, loan_id: int = None) "
                       "-> models.Loan:",
                "file": "services.py"}
        models = ("class Loan:\n"
                  "    id: int = 0\n"
                  "    status: str = ''\n"
                  "    return_date: datetime = None\n")
        module = ("import models\n"
                  "import errors\n"
                  "\n"
                  "class LoanRepository:\n"
                  "    def read_one_loan(self, loan_id: int = None) "
                  "-> models.Loan | None:\n"
                  "        return None\n")
        contract = {
            "holder": "LibraryService", "method": "return_book",
            "preconditions": [{
                "check": "loan.status == 'returned'",
                "error": "InvalidReturnDateError",
                "raise_when": "true",
            }],
        }
        body = [
            "loan = self._repos['LoanRepository'].read_one_loan(loan_id)",
            "if loan.status != 'returned':",
            "    raise errors.InvalidReturnDateError('already returned')",
            "return loan",
        ]
        self.assertEqual(
            self.complaints(body, info=info, module=module, models=models,
                            contract=contract),
            ["raises `InvalidReturnDateError` when `loan.status == "
             "'returned'` is false; the confirmed contract raises it when "
             "the condition is true"])
        body[1] = "if loan.status == 'returned':"
        self.assertEqual(
            self.complaints(body, info=info, module=module, models=models,
                            contract=contract), [])

    def test_a_repository_keyword_outside_the_signature_is_a_complaint(self):
        info = {"cls": "BookService",
                "def": "def fetch(self, book_id: int = None) "
                       "-> models.Book:",
                "file": "services.py"}
        references = (
            "BookRepository.read_one_book(self, book_id_or_isbn: "
            "Union[str, int] = None) -> models.Book | None")
        body = [
            "book = self._repos['BookRepository'].read_one_book("
            "book_id=book_id)",
            "return book",
        ]
        self.assertEqual(
            self.complaints(body, info=info, references=references),
            ["calls `BookRepository.read_one_book(book_id=...)`; the "
             "declared parameter is `book_id_or_isbn`; pass the value "
             "positionally or use the declared keyword; write "
             "`self._repos['BookRepository'].read_one_book(book_id)`"])

    def test_a_repository_keyword_is_checked_against_the_module_source(self):
        info = {"cls": "BookService",
                "def": "def fetch(self, book_id: int = None) "
                       "-> models.Book:",
                "file": "services.py"}
        references = (
            "class BookRepository:\n"
            "    ENTITY = \"Book\"\n"
            "\n"
            "    def read_one_book(self, book_id_or_isbn: "
            "Union[str, int] = None) -> models.Book | None:\n"
            "        return None\n")
        body = [
            "book = self._repos['BookRepository'].read_one_book("
            "book_id=book_id)",
            "return book",
        ]
        self.assertEqual(
            self.complaints(body, info=info, references=references),
            ["calls `BookRepository.read_one_book(book_id=...)`; the "
             "declared parameter is `book_id_or_isbn`; pass the value "
             "positionally or use the declared keyword; write "
             "`self._repos['BookRepository'].read_one_book(book_id)`"])

    def test_a_repository_keyword_matching_the_signature_is_clean(self):
        info = {"cls": "BookService",
                "def": "def fetch(self, book_id: int = None) "
                       "-> models.Book:",
                "file": "services.py"}
        references = (
            "BookRepository.read_one_book(self, book_id_or_isbn: "
            "Union[str, int] = None) -> models.Book | None")
        body = [
            "book = self._repos['BookRepository'].read_one_book("
            "book_id_or_isbn=book_id)",
            "return book",
        ]
        self.assertEqual(
            self.complaints(body, info=info, references=references), [])

    def test_a_confirmed_literal_value_is_checked(self):
        info = {"cls": "LibraryService",
                "def": "def return_book(self, loan_id: int = None) "
                       "-> models.Loan:",
                "file": "services.py"}
        models = ("class Loan:\n"
                  "    id: int = 0\n"
                  "    book_id: int = 0\n"
                  "    return_date: datetime = None\n"
                  "    due_date: datetime = None\n"
                  "    status: str = ''\n")
        body = [
            "loan = self._repos['LoanRepository'].read_one_loan(loan_id)",
            "if not loan:",
            "    raise errors.LoanNotFoundError(loan_id)",
            "loan.status = 'active'",
            "updated_loan = self._repos['LoanRepository'].update_loan("
            "loan_id, loan)",
            "return updated_loan",
        ]
        contract = {
            "holder": "LibraryService", "method": "return_book",
            "effects": [{"target": "loan.status", "op": "set",
                         "value": "returned",
                         "write": "LoanRepository.update_loan"}],
        }
        self.assertEqual(
            self.complaints(body, info=info, models=models,
                            contract=contract),
            ["the confirmed contract sets `loan.status` to `returned`, but "
             "the body does not use that value"])

    def test_a_confirmed_effect_requires_a_field_write(self):
        info = {"cls": "LibraryService",
                "def": "def return_book(self, loan_id: int = None) "
                       "-> models.Loan:",
                "file": "services.py"}
        models = (
            "class Book:\n"
            "    id: int = 0\n"
            "    title: str = ''\n"
            "    available_copies: int = 0\n"
            "    author_id: int = 0\n"
            "\n"
            "class Loan:\n"
            "    id: int = 0\n"
            "    book_id: int = 0\n"
            "    return_date: datetime = None\n"
            "    due_date: datetime = None\n"
            "    status: str = ''\n")
        body = [
            "loan = self._repos['LoanRepository'].read_one_loan(loan_id)",
            "if not loan:",
            "    raise errors.LoanNotFoundError(loan_id)",
            "loan.return_date = datetime.datetime.now()",
            "loan.status = 'returned'",
            "updated_loan = self._repos['LoanRepository'].update_loan("
            "loan_id, loan)",
            "return updated_loan",
        ]
        contract = {
            "holder": "LibraryService", "method": "return_book",
            "effects": [{"target": "book.available_copies", "op": "increment",
                         "by": "1",
                         "write": "BookRepository.update_book"}],
        }
        self.assertEqual(
            self.complaints(body, info=info, models=models,
                            contract=contract),
            ["the confirmed contract changes `book.available_copies`, but "
             "the body never writes `available_copies`"])

    def test_confirmed_effects_are_satisfied_by_the_body(self):
        info = {"cls": "LibraryService",
                "def": "def return_book(self, loan_id: int = None) "
                       "-> models.Loan:",
                "file": "services.py"}
        models = (
            "class Book:\n"
            "    id: int = 0\n"
            "    title: str = ''\n"
            "    available_copies: int = 0\n"
            "    author_id: int = 0\n"
            "\n"
            "class Loan:\n"
            "    id: int = 0\n"
            "    book_id: int = 0\n"
            "    return_date: datetime = None\n"
            "    due_date: datetime = None\n"
            "    status: str = ''\n")
        body = [
            "loan = self._repos['LoanRepository'].read_one_loan(loan_id)",
            "if not loan:",
            "    raise errors.LoanNotFoundError(loan_id)",
            "loan.return_date = datetime.datetime.now()",
            "loan.status = 'returned'",
            "updated_loan = self._repos['LoanRepository'].update_loan("
            "loan_id, loan)",
            "book = self._repos['BookRepository'].read_one_book("
            "loan.book_id)",
            "if not book:",
            "    raise errors.BookNotFoundError(loan.book_id)",
            "book.available_copies += 1",
            "self._repos['BookRepository'].update_book("
            "loan.book_id, book)",
            "return updated_loan",
        ]
        contract = {
            "holder": "LibraryService", "method": "return_book",
            "effects": [
                {"target": "loan.return_date", "op": "set", "value": "now",
                 "write": "LoanRepository.update_loan"},
                {"target": "loan.status", "op": "set", "value": "returned",
                 "write": "LoanRepository.update_loan"},
                {"target": "book.available_copies", "op": "increment",
                 "by": "1", "write": "BookRepository.update_book"},
            ],
            "forbid": [{"target": "loan.return_date",
                        "reads": "loan.due_date"}],
        }
        self.assertEqual(
            self.complaints(body, info=info, models=models,
                            contract=contract), [])

    def test_a_requirement_alone_is_not_a_contract(self):
        info = {"cls": "LibraryService",
                "def": "def return_book(self, loan_id: int = None) "
                       "-> models.Loan:",
                "file": "services.py"}
        models = ("class Loan:\n"
                  "    id: int = 0\n"
                  "    book_id: int = 0\n"
                  "    return_date: datetime = None\n"
                  "    due_date: datetime = None\n"
                  "    status: str = ''\n")
        requirement = ("   - return_book(loan_id): sets return_date, "
                       "updates status")
        body = [
            "loan = self._repos['LoanRepository'].read_one_loan(loan_id)",
            "if not loan:",
            "    raise errors.LoanNotFoundError(loan_id)",
            "loan.return_date = datetime.datetime.now()",
            "loan.status = 'returned'",
            "updated_loan = self._repos['LoanRepository'].update_loan("
            "loan_id, loan)",
            "return updated_loan",
        ]
        self.assertEqual(
            self.complaints(body, info=info, models=models,
                            requirement=requirement),
            [])

    def stock_fixture(self):
        module = (
            "import models\n"
            "import errors\n"
            "\n"
            "class StockRepository:\n"
            "    def read_one_stock(self, stock_id: int = None) "
            "-> models.Stock | None:\n"
            "        return None\n"
            "    def update_stock(self, stock_id: int = None, "
            "stock: models.Stock = None) -> models.Stock:\n"
            "        return None\n"
            "\n"
            "class ConsumptionRepository:\n"
            "    def create_consumption(self, consumption: "
            "models.Consumption = None) -> models.Consumption:\n"
            "        return None\n"
            "\n"
            "class InventoryService:\n"
            "    def consume_material(self, stock_id: int = None, "
            "qty: int = None) -> models.Consumption:\n"
            "        raise NotImplementedError('refused')\n"
        )
        models = (
            "class Stock:\n"
            "    id: int = 0\n"
            "    stock_qty: int = 0\n"
            "\n"
            "class Consumption:\n"
            "    id: int = 0\n"
            "    stock_id: int = 0\n"
            "    qty: int = 0\n"
        )
        info = {"cls": "InventoryService",
                "def": ("def consume_material(self, stock_id: int = None, "
                        "qty: int = None) -> models.Consumption:"),
                "file": "services.py"}
        contract = {
            "holder": "InventoryService", "method": "consume_material",
            "preconditions": [{"check": "stock.stock_qty >= qty",
                               "error": "InsufficientStockError",
                               "raise_when": "false"}],
            "creates": [{"class": "Consumption",
                         "call": "ConsumptionRepository.create_consumption"}],
            "effects": [{"target": "stock.stock_qty", "op": "decrement",
                         "by": "qty",
                         "write": "StockRepository.update_stock"}],
            "order": ["preconditions",
                      "ConsumptionRepository.create_consumption",
                      "StockRepository.update_stock"],
        }
        return info, module, models, contract

    def test_a_stock_contract_renders_without_library_vocabulary(self):
        info, _module, models, contract = self.stock_fixture()
        text = "\n".join(generator._target_contract(
            info, {"models.py": models}, "", contract=contract))
        self.assertIn("stock.stock_qty", text)
        self.assertIn("ConsumptionRepository.create_consumption", text)
        self.assertIn("StockRepository.update_stock", text)
        self.assertIn("InsufficientStockError", text)
        for word in ("book", "copies", "return_date", "due_date", "Loan"):
            self.assertNotIn(word, text)

    def test_a_stock_contract_passes_a_correct_body(self):
        info, module, models, contract = self.stock_fixture()
        body = [
            "stock = self._repos['StockRepository'].read_one_stock(stock_id)",
            "if not stock:",
            "    raise errors.StockNotFoundError(stock_id)",
            "if stock.stock_qty < qty:",
            "    raise errors.InsufficientStockError(stock_id)",
            "consumption = self._repos['ConsumptionRepository']"
            ".create_consumption(models.Consumption("
            "stock_id=stock_id, qty=qty))",
            "stock.stock_qty -= qty",
            "self._repos['StockRepository'].update_stock(stock_id, stock)",
            "return consumption",
        ]
        self.assertEqual(
            self.complaints(body, info=info, module=module, models=models,
                            contract=contract), [])

    def test_a_stock_contract_catches_a_missing_save(self):
        info, module, models, contract = self.stock_fixture()
        body = [
            "stock = self._repos['StockRepository'].read_one_stock(stock_id)",
            "if not stock:",
            "    raise errors.StockNotFoundError(stock_id)",
            "if stock.stock_qty < qty:",
            "    raise errors.InsufficientStockError(stock_id)",
            "consumption = self._repos['ConsumptionRepository']"
            ".create_consumption(models.Consumption("
            "stock_id=stock_id, qty=qty))",
            "stock.stock_qty -= qty",
            "return consumption",
        ]
        complaints = self.complaints(body, info=info, module=module,
                                     models=models, contract=contract)
        self.assertIn(
            "the confirmed contract saves `stock.stock_qty` with "
            "`StockRepository.update_stock(...)`, but the body never calls "
            "`update_stock`", complaints)

    def test_an_unused_declared_parameter_is_a_complaint(self):
        info = {"cls": "BookRepository",
                "def": "def fetch(self, year: str = None) "
                       "-> List[models.Book]:",
                "reason": "refused"}
        self.assertEqual(
            self.complaints(["return []"], info=info),
            ["parameter `year` is never used in the body"])
        self.assertEqual(self.complaints(["return [year]"], info=info), [])

    def test_indexing_a_dict_view_is_a_complaint(self):
        self.assertEqual(
            self.complaints(["months = {}",
                             "first = months.keys()[0]",
                             "return first"]),
            ["indexes a dict view (`dict.keys()[i]` is not subscriptable); "
             "wrap it in `list(...)` or iterate"])

    def test_an_unsupported_store_operator_is_a_complaint(self):
        self.assertEqual(
            self.complaints([
                "rows = self._store.select('Book', "
                "[('title', 'like', 'emma')])",
                "return rows",
            ]),
            ["calls `self._store.select` with operator `like`; the store "
             "supports only `eq`, `ge`, `le`"])

    def test_a_name_read_before_its_assignment_is_a_complaint(self):
        self.assertEqual(
            self.complaints(["total = count", "count = 1",
                             "return total"]),
            ["reads `count` (line 2) before it is assigned (line 3)"])

    def test_returning_another_models_class_is_a_complaint(self):
        info = {"cls": "BookRepository",
                "def": "def fetch(self) -> models.Loan:",
                "reason": "refused"}
        self.assertEqual(
            self.complaints(["book = self.update_book()", "return book"],
                            info=info),
            ["returns `book` from `update_book(...)` (a Book) but the "
             "method is declared `-> models.Loan`"])

    def test_a_missing_value_return_is_a_complaint(self):
        info = {"cls": "BookService",
                "def": "def fetch(self) -> models.Book:",
                "file": "services.py"}
        self.assertEqual(
            self.complaints(["book = None"], info=info),
            ["the method is declared `-> models.Book`, but the body never "
             "returns a value"])

    def test_a_generator_for_a_list_method_is_a_complaint(self):
        info = {"cls": "BookService",
                "def": "def fetch(self) -> List[models.Book]:",
                "file": "services.py"}
        body = [
            "books = self._repos['BookRepository'].read_all_books()",
            "for book in books:",
            "    yield book",
        ]
        self.assertEqual(
            self.complaints(body, info=info),
            ["the body uses `yield`, but the method is declared "
             "`-> List[models.Book]`; a generator function does not return "
             "that value"])

    def test_a_clean_body_has_no_complaints(self):
        self.assertEqual(
            self.complaints(["pairs = [(1, 2)]",
                             "ordered = sorted(pairs, "
                             "key=lambda pair: pair[0])",
                             "return ordered"]),
            [])
        # The dict comprehension reads its target in the key expression
        # while the `for` clause that binds it is on the next line.
        self.assertEqual(
            self.complaints(["authors = {name: name.lower()",
                             "           for name in ['Ada', 'Bob']}",
                             "return authors"]),
            [])


class GuiBackendTests(unittest.TestCase):
    """A gui facade gets gui.py from its declared backend, nothing else does."""

    def ctx(self, facade):
        return {"models": [], "errors": [], "services": [], "repositories": [],
                "mappings": {}, "match_index": {}, "adapters": [],
                "components": {"facade": facade}, "entity_names": []}

    def test_declared_pyimgui_dispatches(self):
        kind, tech, note = generator.gui_backend(
            self.ctx({"type": "gui", "technology": "pyimgui"}))
        self.assertEqual((kind, tech, note), ("gui", "pyimgui", ""))

    def test_override_wins_over_declaration(self):
        kind, tech, _ = generator.gui_backend(
            self.ctx({"type": "gui", "technology": "tkinter"}),
            override="pyimgui")
        self.assertEqual((kind, tech), ("gui", "pyimgui"))

    def test_unknown_backend_is_a_skip_with_a_reason(self):
        kind, tech, note = generator.gui_backend(
            self.ctx({"type": "gui", "technology": "tkinter"}))
        self.assertIsNone(kind)
        self.assertIn("tkinter", note)

    def test_cli_facade_is_silent_without_override(self):
        self.assertEqual(
            generator.gui_backend(self.ctx({"type": "cli"})),
            (None, None, ""))

    def test_pyimgui_emitter_wires_crud_per_entity(self):
        import ast
        ctx = {
            "models": [{"name": "Wine", "fields": [
                {"name": "wine_id", "type": "int", "primary_key": True},
                {"name": "title", "type": "string"}]}],
            "errors": [], "services": [],
            "repositories": [{"entity": "Wine",
                              "interface_name": "WineRepository",
                              "methods": [
                                  {"name": "create_wine",
                                   "params": [{"name": "wine", "type": "Wine"}],
                                   "return_type": "Wine"},
                                  {"name": "read_all_wines", "params": [],
                                   "return_type": "List[Wine]"},
                                  {"name": "update_wine",
                                   "params": [{"name": "wine_id", "type": "int"},
                                              {"name": "wine", "type": "Wine"}],
                                   "return_type": "Wine"},
                                  {"name": "delete_wine",
                                   "params": [{"name": "wine_id", "type": "int"}],
                                   "return_type": "None"}]}],
            "mappings": {}, "match_index": {}, "adapters": [],
            "components": {"facade": {"type": "gui", "technology": "pyimgui"}},
            "entity_names": ["Wine"],
        }
        stats = {}
        text = generator.emit_gui_pyimgui(ctx, stats)
        ast.parse(text)
        self.assertIn("import imgui", text)
        self.assertIn("GlfwRenderer", text)
        self.assertIn("OPENGL_CORE_PROFILE", text)
        self.assertIn('sys.platform == "darwin"', text)
        self.assertIn("No bespoke screens", text)
        self.assertIn("one window per modeled entity", text)
        self.assertIn("_draw_toolbar", text)
        self.assertIn("TOOLBAR_WIDTH", text)
        self.assertIn("set_next_window_size", text)
        self.assertIn("records:", text)
        self.assertNotIn("Reload", text)
        for name in ("Wine", "WineRepository", "create_wine",
                     "read_all_wines", "update_wine", "delete_wine"):
            self.assertIn(name, text)
        self.assertEqual(stats["gui_panels"], ["Wine"])

    def test_gui_crud_roundtrip_headless(self):
        """Drive the emitted logic with stubbed windowing: only declared params.

        Gui methods take scalars (no entity param), and models may declare
        fields no method takes — passing those top-level broke every call
        with unexpected-kwarg errors. The id box serves pk-keyed methods.
        """
        import sys
        import types
        from unittest import mock

        ctx = {
            "models": [{"name": "Widget", "fields": [
                {"name": "widget_id", "type": "int", "primary_key": True},
                {"name": "name", "type": "string"},
                {"name": "note", "type": "string"}]}],
            "errors": [], "services": [],
            "repositories": [{"entity": "Widget",
                              "interface_name": "WidgetRepository",
                              "methods": [
                                  {"name": "create_widget",
                                   "params": [{"name": "name", "type": "str"}],
                                   "return_type": "Widget"},
                                  {"name": "read_all_widgets", "params": [],
                                   "return_type": "List[Widget]"},
                                  {"name": "update_widget",
                                   "params": [{"name": "widget_id", "type": "int"},
                                              {"name": "name", "type": "str"}],
                                   "return_type": "Widget"},
                                  {"name": "delete_widget",
                                   "params": [{"name": "widget_id", "type": "int"}],
                                   "return_type": "None"}]}],
            "mappings": {}, "match_index": {}, "adapters": [],
            "components": {"facade": {"type": "gui", "technology": "pyimgui"}},
            "entity_names": ["Widget"],
        }
        text = generator.emit_gui_pyimgui(ctx, {})

        calls = []

        class FakeRepo:
            def __init__(self, store):
                pass

            def create_widget(self, name=None):
                assert name is not None
                calls.append(("create", {"name": name}))
                return {"widget_id": 1, "name": name}

            def read_all_widgets(self):
                calls.append(("list", {}))
                return [{"widget_id": 1, "name": "x"}]

            def update_widget(self, widget_id=None, name=None):
                calls.append(("update", {"widget_id": widget_id, "name": name}))
                return {"widget_id": widget_id, "name": name}

            def delete_widget(self, widget_id=None):
                calls.append(("delete", {"widget_id": widget_id}))

        def modules():
            mods = {}
            for name in ("imgui", "glfw", "OpenGL", "OpenGL.GL",
                         "imgui.integrations", "imgui.integrations.glfw",
                         "models", "errors", "store", "repositories"):
                mods[name] = types.ModuleType(name)
            mods["imgui.integrations.glfw"].GlfwRenderer = object
            mods["models"].Widget = lambda **kw: kw
            mods["store"].Store = object
            mods["repositories"].WidgetRepository = FakeRepo
            return mods

        with mock.patch.dict(sys.modules, modules()):
            namespace = {"__name__": "gui_under_test"}
            exec(compile(text, "gui.py", "exec"), namespace)

        panel = namespace["PANELS"][0]
        repo = FakeRepo(None)
        state = namespace["_new_state"]()
        state["inputs"] = {"name": "x", "note": "undeclared-field"}
        namespace["_invoke"](panel, repo, state, "create")
        self.assertEqual(state["message"], "create ok")
        self.assertEqual(calls[-2], ("create", {"name": "x"}))
        self.assertEqual(calls[-1], ("list", {}))  # mutation reloads the list
        namespace["_refresh"](panel, repo, state)
        self.assertEqual(len(state["rows"]), 1)
        state["id"] = "1"
        state["inputs"] = {"name": "y"}
        namespace["_invoke"](panel, repo, state, "update")
        self.assertEqual(calls[-2], ("update", {"widget_id": 1, "name": "y"}))
        self.assertEqual(calls[-1], ("list", {}))
        namespace["_invoke"](panel, repo, state, "delete")
        self.assertEqual(calls[-2], ("delete", {"widget_id": 1}))
        self.assertEqual(calls[-1], ("list", {}))


class QualifyTests(unittest.TestCase):
    """Entity references become `models.X`, never `models.X.Y`.

    Gui contracts spell qualified refs (`wine.Wine`); prefixing the head
    yields `models.wine.Wine`, which resolves against nothing and crashed
    the gui import. The head is replaced, with the same `sanitize` call
    `emit_models` uses for the class name.
    """

    def test_qualified_head_is_replaced_not_prefixed(self):
        self.assertEqual(
            generator._qualify("List[wine.Wine]", ["wine"]),
            "List[models.wine]")

    def test_bare_names_still_prefix(self):
        self.assertEqual(generator._qualify("Wine", ["Wine"]), "models.Wine")
        self.assertEqual(generator._qualify("List[Wine]", ["Wine"]),
                         "List[models.Wine]")

    def test_already_qualified_models_refs_are_untouched(self):
        self.assertEqual(generator._qualify("models.Wine", ["Wine"]),
                         "models.Wine")

    def test_plurals_do_not_match(self):
        self.assertEqual(generator._qualify("wines", ["wine"]), "wines")


class EmittedImportsTests(unittest.TestCase):
    """Emitted files import what their annotations use.

    Lowercase model types map to `Any`, which repositories.py and services.py
    once used without importing — the gui crashed at import with NameError
    while the Shop suite (capitalized types) stayed green.
    """

    def test_repositories_and_services_exec_with_lowercase_types(self):
        import types
        from unittest import mock
        ctx = {
            "models": [{"name": "Wine", "fields": [
                {"name": "wine_id", "type": "int", "primary_key": True},
                {"name": "title", "type": "string"}]}],
            "errors": [{"name": "WineNotFoundError", "base": "LookupError",
                        "description": "no such wine"}],
            "services": [],
            "repositories": [{"entity": "Wine",
                              "interface_name": "WineRepository",
                              "methods": [
                                  {"name": "create_wine",
                                   "params": [{"name": "name", "type": "str"}],
                                   "return_type": "Wine"},
                                  {"name": "read_all_wines", "params": [],
                                   "return_type": "List[Wine]"}]}],
            "mappings": {}, "match_index": {}, "adapters": [],
            "components": {}, "entity_names": ["Wine"],
        }
        stats = {"source": "t", "implemented": 0, "stubs": 0,
                 "stub_reasons": []}
        repos_text = generator.emit_repositories(ctx, stats)
        services_text = generator.emit_services(
            ctx, generator._repo_index(ctx), stats)
        mods = {}
        for name in ("models", "errors", "store"):
            mods[name] = types.ModuleType(name)
        mods["store"].Store = object
        mods["store"].match_criterion = lambda *a: None
        mods["models"].Wine = type("Wine", (), {})
        mods["models"].Budget = type("Budget", (), {})
        namespace = dict(mods)
        with mock.patch.dict(sys.modules, mods):
            exec(compile(repos_text, "repositories.py", "exec"), namespace)
            exec(compile(services_text, "services.py", "exec"), namespace)
        self.assertIn("WineRepository", namespace)
        self.assertTrue(any(line.startswith("from typing import") and "Union" in line
                            for line in repos_text.splitlines()))


class MappingEmissionTests(unittest.TestCase):
    """Emitted bodies resolve parameters the way the kernel says.

    Every case here was a live defect: `read_one_book(book_id_or_isbn)`
    raised on every call, `find_books_by_author` read the Author table and
    returned Authors while annotated `List[Book]`, and
    `search_books_by_title_author_isbn(query)` pretended to be mechanical
    while raising `cannot filter Book by 'query'` — counted as done, dead
    when called.
    """

    def ctx(self):
        def method(name, params=(), returns="None", raises=(), description=""):
            return {"name": name, "description": description or name,
                    "params": [{"name": n, "type": t} for n, t in params],
                    "return_type": returns, "raises": list(raises)}

        return {
            "models": [
                {"name": "Author", "fields": [
                    {"name": "id", "type": "int", "primary_key": True},
                    {"name": "name", "type": "string"}]},
                {"name": "Book", "fields": [
                    {"name": "id", "type": "int", "primary_key": True},
                    {"name": "title", "type": "string"},
                    {"name": "isbn", "type": "string"},
                    {"name": "author_id", "type": "int",
                     "foreign_key": {"target_entity": "Author",
                                     "target_field": "id"}}]}],
            "errors": [
                {"name": "BookNotFoundError", "base": "LookupError",
                 "description": "no such book"},
                {"name": "AuthorNotFoundError", "base": "LookupError",
                 "description": "no such author"}],
            "services": [],
            "repositories": [
                {"entity": "Author", "interface_name": "AuthorRepository",
                 "methods": [
                     method("read_one_author", [("author_id", "int")],
                            "Author", ["AuthorNotFoundError"]),
                     method("find_books_by_author", [("author_id", "int")],
                            "List[Book]")]},
                {"entity": "Book", "interface_name": "BookRepository",
                 "methods": [
                     method("read_one_book",
                            [("book_id_or_isbn", "Union[str, int]")],
                            "Book | None", ["BookNotFoundError"]),
                     method("update_book",
                            [("book_id_or_isbn", "Union[str, int]"),
                             ("data", "Book")],
                            "Book", ["BookNotFoundError"]),
                     method("delete_book",
                            [("book_id_or_isbn", "Union[str, int]")],
                            "None", ["BookNotFoundError"]),
                     method("search_books_by_title_author_isbn",
                            [("query", "str")], "List[Book]")]}],
            "mappings": {}, "match_index": {}, "adapters": [],
            "components": {}, "entity_names": ["Author", "Book"],
        }

    def exec_repositories(self, ctx):
        """Emit and run the repositories against the real store template."""
        import importlib.util
        import types
        from unittest import mock
        spec = importlib.util.spec_from_file_location(
            "store", "kernel/codegen_store_template.py")
        store = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(store)
        models = types.ModuleType("models")
        # Real `models.py` entities are dataclasses; these stand-ins are
        # dicts so the assertions can index records. They must be *classes*:
        # with eager annotations (3.12) `models.Book | None` evaluates at
        # class creation, and a lambda cannot be unioned — lazy 3.14
        # annotations hid that until the suite ran here.
        models.Author = type("Author", (dict,), {
            "__init__": lambda self, **kw: dict.__init__(self, kw)})
        models.Book = type("Book", (dict,), {
            "__init__": lambda self, **kw: dict.__init__(self, kw)})
        errors = types.ModuleType("errors")
        for name in ("BookNotFoundError", "AuthorNotFoundError"):
            setattr(errors, name, type(name, (LookupError,), {}))
        mods = {"models": models, "errors": errors, "store": store}
        stats = {"source": "t", "implemented": 0, "stubs": 0,
                 "stub_reasons": []}
        text = generator.emit_repositories(ctx, stats)
        with mock.patch.dict(sys.modules, mods):
            namespace = dict(mods)
            exec(compile(text, "repositories.py", "exec"), namespace)
        return namespace, store, stats

    def test_identifiers_scan_every_alternative(self):
        """`book_id_or_isbn` finds by id and by isbn, updating and deleting
        through the same scan; a miss reports not-found, not a crash."""
        namespace, store, _ = self.exec_repositories(self.ctx())
        backend = store.Store()
        backend.add("Book", "id", {"id": 1, "title": "T", "isbn": "X",
                                   "author_id": 1})
        books = namespace["BookRepository"](backend)
        self.assertEqual(books.read_one_book(1)["title"], "T")
        self.assertEqual(books.read_one_book("X")["title"], "T")
        updated = books.update_book("X", {"title": "T2"})
        self.assertEqual(updated["title"], "T2")
        with self.assertRaises(namespace["errors"].BookNotFoundError):
            books.read_one_book(99)
        books.delete_book(1)
        self.assertEqual(backend.select("Book", []), [])

    def test_pk_alias_reads_the_own_id(self):
        namespace, store, _ = self.exec_repositories(self.ctx())
        backend = store.Store()
        backend.add("Author", "id", {"id": 7, "name": "A"})
        authors = namespace["AuthorRepository"](backend)
        self.assertEqual(authors.read_one_author(7)["name"], "A")

    def test_cross_entity_filter_reads_the_returned_entity(self):
        """`find_books_by_author` returns Books: the query reads the Book
        table with the borrowed `author_id` parameter, not the Author table."""
        namespace, store, _ = self.exec_repositories(self.ctx())
        backend = store.Store()
        backend.add("Author", "id", {"id": 7, "name": "A"})
        backend.add("Book", "id", {"id": 1, "title": "T", "isbn": "X",
                                   "author_id": 7})
        authors = namespace["AuthorRepository"](backend)
        found = authors.find_books_by_author(7)
        self.assertEqual([book["title"] for book in found], ["T"])
        self.assertEqual(authors.find_books_by_author(8), [])

    def test_unmappable_filter_parameter_refuses_with_a_stub(self):
        namespace, store, stats = self.exec_repositories(self.ctx())
        books = namespace["BookRepository"](store.Store())
        with self.assertRaises(NotImplementedError) as caught:
            books.search_books_by_title_author_isbn("T")
        self.assertIn("maps to no field", str(caught.exception))
        self.assertTrue(any("search_books_by_title_author_isbn" in reason
                            for reason in stats["stub_reasons"]))
        kinds = {m["method"]: m["implemented"] for m in stats["methods"]}
        self.assertFalse(kinds["search_books_by_title_author_isbn"])
        self.assertTrue(kinds["read_one_book"])


if __name__ == "__main__":
    unittest.main()
