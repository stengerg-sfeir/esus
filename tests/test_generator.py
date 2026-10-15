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


class PlanTests(unittest.TestCase):
    def test_match_param_covers_prefixes_and_rejects_noise(self):
        self.assertEqual(codegen.match_param(["expense_date"], "start_date"),
                         ("expense_date", "ge"))
        self.assertEqual(codegen.match_param(["id"], "id"), ("id", "eq"))
        self.assertIsNone(codegen.match_param(["name"], "total"))

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


if __name__ == "__main__":
    unittest.main()
