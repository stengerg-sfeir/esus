"""Pattern slots: asked of a human, emitted mechanically, metered like all."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import generator  # noqa: E402
import review_slots  # noqa: E402
from review_slots import collect_slots, run_review  # noqa: E402


EXPENSE_MODEL = {"name": "Expense", "fields": [
    {"name": "id", "type": "int", "primary_key": True},
    {"name": "amount_cents", "type": "int"},
    {"name": "description", "type": "string"},
    {"name": "expense_date", "type": "string"},
    {"name": "category_id", "type": "int",
     "foreign_key": {"target_entity": "Category", "target_field": "id",
                     "relationship": "many_to_one"}},
    {"name": "payment_method", "type": "string"}]}

CATEGORY_MODEL = {"name": "Category", "fields": [
    {"name": "id", "type": "int", "primary_key": True},
    {"name": "name", "type": "string"}]}

BUDGET_MODEL = {"name": "Budget", "fields": [
    {"name": "id", "type": "int", "primary_key": True},
    {"name": "category_id", "type": "int",
     "foreign_key": {"target_entity": "Category", "target_field": "id",
                      "relationship": "many_to_one"}},
    {"name": "month", "type": "string"},
    {"name": "amount_limit_cents", "type": "int"}]}

BUDGET_ERRORS = [
    {"name": "BudgetExceededException", "base": "Exception",
     "description": "budget exceeded"},
    {"name": "ExpenseNotFoundError", "base": "LookupError",
     "description": "no such expense"}]


def repo_methods():
    return [
        {"name": "create_expense",
         "params": [{"name": "expense", "type": "Expense"}],
         "return_type": "None", "description": "create"},
        {"name": "read_all_expenses", "params": [],
         "return_type": "List[Expense]", "description": "all"},
        {"name": "get_monthly_expense_total",
         "params": [{"name": "month", "type": "str"}],
         "return_type": "int", "description": "monthly total"},
        {"name": "get_category_spending",
         "params": [{"name": "category_id", "type": "int"},
                    {"name": "start_date", "type": "str"},
                    {"name": "end_date", "type": "str"}],
         "return_type": "int", "description": "category spending"},
        {"name": "get_stale_expenses", "params": [],
         "return_type": "List[Expense]", "description": "stale"},
    ]


def writes(directory, methods=None, matches=None):
    """A gate-quiet out dir with one repository and slottable methods."""
    path = Path(directory)
    methods = repo_methods() if methods is None else methods
    (path / "data_models.json").write_text(json.dumps(
        {"data_models": [EXPENSE_MODEL, CATEGORY_MODEL]}), encoding="utf-8")
    (path / "service_contracts.json").write_text(json.dumps(
        {"service_contracts": []}), encoding="utf-8")
    (path / "persistence_ports.json").write_text(json.dumps(
        {"persistence_ports": {
            "repositories": [{"entity": "Expense",
                              "interface_name": "ExpenseRepository",
                              "methods": methods}],
            "entity_mappings": []}}), encoding="utf-8")
    if matches is None:
        matches = [
            {"source": "contract:ExpenseRepository.get_monthly_expense_total",
             "pattern_id": "AGGREGATE_BY_FK_AND_DATE", "decision": "decided"},
            {"source": "contract:ExpenseRepository.get_category_spending",
             "pattern_id": "AGGREGATE_BY_FK_AND_DATE", "decision": "decided"},
            {"source": "contract:ExpenseRepository.get_stale_expenses",
             "pattern_id": "THRESHOLD_SCAN", "decision": "decided"},
        ]
    (path / "pattern_matches.json").write_text(
        json.dumps({"pattern_matches": matches}), encoding="utf-8")
    (path / "components.json").write_text(json.dumps(
        {"components": {"facade": {"type": "cli", "technology": "argparse",
                                   "invocation": {"commands": []}},
                        "persistence": {"required": True,
                                        "technology": "sqlite"},
                        "external_access": [], "crud_services": []}}),
        encoding="utf-8")
    (path / "requirements.txt").write_text("expenses", encoding="utf-8")
    for name in ("errors", "intentions", "invariants",
                 "interaction_adapters"):
        (path / f"{name}.json").write_text(json.dumps({name: []}),
                                           encoding="utf-8")
    return str(path)


def budget_ctx(service_record=None, repo_records=None):
    """Hand ctx for guard tests: Budget repo + guard-patterned service."""
    decisively = lambda pid: {"pattern_id": pid, "decision": "decided"}
    repos = [{
        "entity": "Expense", "interface_name": "ExpenseRepository",
        "methods": [
            {"name": "create_expense",
             "params": [{"name": "expense", "type": "Expense"}],
             "return_type": "None", "description": "create"},
            {"name": "read_all_expenses", "params": [],
             "return_type": "List[Expense]", "description": "all"},
            {"name": "get_monthly_expense_total",
             "params": [{"name": "month", "type": "str"}],
             "return_type": "int", "description": "monthly total"},
        ]}, {
        "entity": "Budget", "interface_name": "BudgetRepository",
        "methods": [
            {"name": "create_budget",
             "params": [{"name": "budget", "type": "Budget"}],
             "return_type": "None", "description": "create"},
            {"name": "read_budget_by_category_and_month",
             "params": [{"name": "category_id", "type": "int"},
                        {"name": "month", "type": "str"}],
             "return_type": "Budget", "description": "one budget"},
            {"name": "check_budget_status",
             "params": [{"name": "category_id", "type": "int"},
                        {"name": "month", "type": "str"}],
             "return_type": "bool", "description": "within budget?"},
        ]}]
    matches = {
        "contract:ExpenseRepository.get_monthly_expense_total": decisively(
            "AGGREGATE_BY_FK_AND_DATE"),
        "contract:BudgetRepository.check_budget_status": decisively(
            "BUDGET_OVERFLOW_GUARD"),
        "contract:ExpenseService.add_expense": decisively(
            "BUDGET_OVERFLOW_GUARD"),
    }
    services = [{
        "service_name": "ExpenseService",
        "methods": [{
            "name": "add_expense",
            "params": [{"name": "expense", "type": "Expense"}],
            "return_type": "None", "description": "guarded add"}]}]
    slot_records = {
        ("ExpenseRepository", "get_monthly_expense_total"): {
            "holder": "ExpenseRepository",
            "method": "get_monthly_expense_total",
            "slots": {"aggregate_func": "SUM",
                      "target_field": "amount_cents",
                      "date_field": "expense_date"}},
    }
    slot_records.update(repo_records or {})
    if service_record is not None:
        slot_records[("ExpenseService", "add_expense")] = service_record
    return {
        "models": [EXPENSE_MODEL, CATEGORY_MODEL, BUDGET_MODEL],
        "errors": BUDGET_ERRORS, "entity_names": ["Expense", "Category",
                                                  "Budget"],
        "services": services, "repositories": repos,
        "mappings": {}, "match_index": matches, "adapters": [],
        "components": {}, "slots": slot_records,
    }


class GuardEmitterTests(unittest.TestCase):
    """Check-then-act runs; malformed records stay stubs."""

    def test_over_limit_raises_under_limit_creates_no_budget_proceeds(self):
        ctx = budget_ctx({"holder": "ExpenseService", "method": "add_expense",
            "slots": {"create_method": "create_expense",
                      "aggregate_method": "get_monthly_expense_total",
                      "budget_method": "read_budget_by_category_and_month",
                      "amount_field": "amount_cents",
                      "date_field": "expense_date",
                      "limit_field": "amount_limit_cents",
                      "error": "BudgetExceededException"}})
        repo_stats = {"source": "t", "implemented": 0, "stubs": 0,
                      "stub_reasons": []}
        repo_text = generator.emit_repositories(ctx, repo_stats)
        svc_stats = {"source": "t", "implemented": 0, "stubs": 0,
                     "stub_reasons": []}
        svc_text = generator.emit_services(
            ctx, generator._repo_index(ctx), svc_stats)
        self.assertIn("budget guard over", svc_text)
        namespace, store = _exec_repo_service(repo_text, svc_text)

        backend = store.Store()
        backend.add("Category", "id", {"name": "food"})
        repos = {"ExpenseRepository": namespace["ExpenseRepository"](backend),
                 "BudgetRepository": namespace["BudgetRepository"](backend)}
        svc = namespace["ExpenseService"](repos)
        Expense = namespace["models"].Expense
        Budget = namespace["models"].Budget
        repos["BudgetRepository"].create_budget(
            Budget(category_id=1, month="2024-01", amount_limit_cents=200))
        repos["ExpenseRepository"].create_expense(
            Expense(expense_date="2024-01-05", amount_cents=150,
                    category_id=1))
        # Under the limit: creates.
        svc.add_expense(Expense(expense_date="2024-01-10", amount_cents=40,
                                category_id=1))
        # Over the limit: the registered error, no write.
        with self.assertRaises(namespace["errors"].BudgetExceededException):
            svc.add_expense(Expense(expense_date="2024-01-12", amount_cents=50,
                                    category_id=1))
        # No budget record: no limit to exceed, proceeds.
        svc.add_expense(Expense(expense_date="2024-02-01", amount_cents=9999,
                                category_id=1))
        kinds = {m["method"]: (m["implemented"], m["how"])
                 for m in svc_stats["methods"]}
        self.assertTrue(kinds["add_expense"][0])
        self.assertEqual(kinds["add_expense"][1], "guard")

    def test_repo_check_answers_bool(self):
        _check = {("BudgetRepository", "check_budget_status"): {
            "holder": "BudgetRepository", "method": "check_budget_status",
            "slots": {"limit_field": "amount_limit_cents",
                      "target_field": "amount_cents",
                      "date_field": "expense_date",
                      "spend_entity": "Expense"}}}
        ctx = budget_ctx(repo_records=_check)
        stats = {"source": "t", "implemented": 0, "stubs": 0,
                 "stub_reasons": []}
        namespace, store = exec_repos(generator.emit_repositories(ctx, stats))
        backend = store.Store()
        backend.add("Category", "id", {"name": "food"})
        repos = {"ExpenseRepository": namespace["ExpenseRepository"](backend),
                 "BudgetRepository": namespace["BudgetRepository"](backend)}
        Expense = namespace["models"].Expense
        Budget = namespace["models"].Budget
        repos["BudgetRepository"].create_budget(
            Budget(category_id=1, month="2024-01", amount_limit_cents=200))
        repos["ExpenseRepository"].create_expense(
            Expense(expense_date="2024-01-05", amount_cents=150,
                    category_id=1))
        check = repos["BudgetRepository"].check_budget_status
        self.assertTrue(check(1, "2024-01"))
        repos["ExpenseRepository"].create_expense(
            Expense(expense_date="2024-01-10", amount_cents=100,
                    category_id=1))
        self.assertFalse(check(1, "2024-01"))
        self.assertTrue(check(9, "2024-01"))

    def test_guard_needs_complete_wellformed_records(self):
        ctx = budget_ctx()
        stats = {"source": "t", "implemented": 0, "stubs": 0,
                 "stub_reasons": []}
        text = generator.emit_services(
            ctx, generator._repo_index(ctx), stats)
        self.assertIn("raise NotImplementedError", text)
        kinds = {m["method"]: (m["implemented"], m["how"])
                 for m in stats["methods"]}
        self.assertFalse(kinds["add_expense"][0])

    def test_datetless_expense_refuses_instead_of_passing_silent(self):
        """The exact production incident: no `expense_date` means no month,
        which meant an empty scope that matched everything and skipped the
        check. Now the guard names the missing field loudly."""
        record = {"holder": "ExpenseService", "method": "add_expense",
                  "slots": {"create_method": "create_expense",
                            "aggregate_method": "get_monthly_expense_total",
                            "budget_method": "read_budget_by_category_and_month",
                            "amount_field": "amount_cents",
                            "date_field": "expense_date",
                            "limit_field": "amount_limit_cents",
                            "error": "BudgetExceededException"}}
        ctx = budget_ctx(record)
        stats = {"source": "t", "implemented": 0, "stubs": 0,
                 "stub_reasons": []}
        repo_text = generator.emit_repositories(ctx, stats)
        svc_text = generator.emit_services(
            ctx, generator._repo_index(ctx), stats)
        namespace, store = _exec_repo_service(repo_text, svc_text)
        backend = store.Store()
        backend.add("Category", "id", {"name": "food"})
        repos = {"ExpenseRepository": namespace["ExpenseRepository"](backend),
                 "BudgetRepository": namespace["BudgetRepository"](backend)}
        svc = namespace["ExpenseService"](repos)
        Expense = namespace["models"].Expense
        with self.assertRaises(ValueError) as raised:
            svc.add_expense(Expense(amount_cents=1, category_id=1))
        self.assertIn("expense_date", str(raised.exception))

    def test_monthless_check_refuses_instead_of_summing_all(self):
        """Same trap in the repo check: an empty month prefix-matches every
        record, so the check demands its scope up front."""
        rec = {("BudgetRepository", "check_budget_status"): {
            "holder": "BudgetRepository", "method": "check_budget_status",
            "slots": {"limit_field": "amount_limit_cents",
                      "target_field": "amount_cents",
                      "date_field": "expense_date",
                      "spend_entity": "Expense"}}}
        ctx = budget_ctx(repo_records=rec)
        stats = {"source": "t", "implemented": 0, "stubs": 0,
                 "stub_reasons": []}
        namespace, store = exec_repos(generator.emit_repositories(ctx, stats))
        backend = store.Store()
        backend.add("Category", "id", {"name": "food"})
        check = namespace["BudgetRepository"](backend).check_budget_status
        with self.assertRaises(ValueError):
            check(1, "")

    def test_id_only_budget_read_cannot_scope_a_guard(self):
        """`read_budget_by_id(expense.id)` looks scoped but is a cross-entity
        id collision: the feed constrains nothing, so the plan refuses and
        the guard stays a stub instead of guarding against one arbitrary row.
        """
        record = {"holder": "ExpenseService", "method": "add_expense",
                  "slots": {"create_method": "create_expense",
                            "aggregate_method": "get_monthly_expense_total",
                            "budget_method": "read_budget_by_id",
                            "amount_field": "amount_cents",
                            "date_field": "expense_date",
                            "limit_field": "amount_limit_cents",
                            "error": "BudgetExceededException"}}
        ctx = budget_ctx(record)
        ctx["repositories"][1]["methods"].append({
            "name": "read_budget_by_id",
            "params": [{"name": "id", "type": "int"}],
            "return_type": "Budget", "description": "one budget by id"})
        stats = {"source": "t", "implemented": 0, "stubs": 0,
                 "stub_reasons": []}
        text = generator.emit_services(
            ctx, generator._repo_index(ctx), stats)
        kinds = {m["method"]: (m["implemented"], m["how"])
                 for m in stats["methods"]}
        self.assertFalse(kinds["add_expense"][0])


def ctx_with(slots, methods=None):
    """Hand ctx for emitter tests: slots injected, no files."""
    if methods is None:
        methods = repo_methods()
    return {
        "models": [EXPENSE_MODEL, CATEGORY_MODEL], "errors": [],
        "services": [], "entity_names": ["Expense", "Category"],
        "repositories": [{"entity": "Expense",
                          "interface_name": "ExpenseRepository",
                          "methods": methods}],
        "mappings": {}, "match_index": {
            "contract:ExpenseRepository.get_monthly_expense_total":
                {"pattern_id": "AGGREGATE_BY_FK_AND_DATE", "decision": "decided"},
            "contract:ExpenseRepository.get_category_spending":
                {"pattern_id": "AGGREGATE_BY_FK_AND_DATE", "decision": "decided"},
            "contract:ExpenseRepository.get_stale_expenses":
                {"pattern_id": "THRESHOLD_SCAN", "decision": "decided"},
        },
        "adapters": [], "components": {},
        "slots": {("ExpenseRepository", name): {"holder": "ExpenseRepository",
                                                "method": name,
                                                "slots": spec}
                  for name, spec in slots.items()},
    }


def exec_repos(text):
    """Emitted repositories against a real in-memory store."""
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
    mods["models"].Expense = lambda **kw: kw
    mods["models"].Budget = lambda **kw: kw
    mods["models"].Widget = lambda **kw: kw
    with mock.patch.dict(sys.modules, mods):
        namespace = dict(mods)
        exec(compile(text, "repositories.py", "exec"), namespace)
    return namespace, store


def _exec_repo_service(repo_text, svc_text):
    """Emitted repositories plus services, sharing one namespace and store."""
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
    mods["models"].Expense = lambda **kw: kw
    mods["models"].Budget = lambda **kw: kw
    mods["errors"].BudgetExceededException = type(
        "BudgetExceededException", (Exception,), {})
    with mock.patch.dict(sys.modules, mods):
        namespace = dict(mods)
        exec(compile(repo_text, "repositories.py", "exec"), namespace)
        exec(compile(svc_text, "services.py", "exec"), namespace)
    return namespace, store


class CollectTests(unittest.TestCase):
    def test_slottable_stubs_are_collected_with_options(self):
        with tempfile.TemporaryDirectory() as directory:
            out = writes(directory)
            questions, _ = collect_slots(out)
            by_method = {q["method"]: q for q in questions}
            self.assertIn("get_monthly_expense_total", by_method)
            self.assertIn("get_category_spending", by_method)
            monthly = by_method["get_monthly_expense_total"]
            slots = dict(monthly["options"])
            self.assertIn("amount_cents", slots["target_field"])
            self.assertIn("SUM", slots["aggregate_func"])
            self.assertIn("expense_date", slots["date_field"])
            # No fk parameter on the method: no fk question.
            self.assertNotIn("fk_field", slots)
            category = by_method["get_category_spending"]
            self.assertIn("category_id",
                          dict(category["options"])["fk_field"])

    def test_recorded_methods_do_not_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            out = writes(directory)
            run_review(out, input_fn=lambda _: "1", out_fn=lambda _: None)
            remaining = [q["method"] for q in collect_slots(out)[0]]
            self.assertEqual(remaining, ["get_stale_expenses"])

    def test_threshold_defers_the_bound_until_the_field_is_known(self):
        with tempfile.TemporaryDirectory() as directory:
            out = writes(directory)
            questions, _ = collect_slots(out)
            stale = next(q for q in questions
                         if q["method"] == "get_stale_expenses")
            slots = dict(stale["options"])
            self.assertIn("expense_date", slots["comparison_field"])
            self.assertIn("<", slots["operator"])
            self.assertIsNone(slots["threshold"])
            # Date field chosen: `today` is offered; a numeric field: only params.
            ctx = generator.load_context(out)
            method = next(m for r in ctx["repositories"]
                          for m in r["methods"]
                          if m["name"] == "get_stale_expenses")
            self.assertEqual(
                review_slots._threshold_options(
                    ctx, "Expense", method, "expense_date"), ["today"])
            self.assertEqual(
                review_slots._threshold_options(
                    ctx, "Expense", method, "amount_cents"), [])

    def test_boundless_threshold_is_never_asked(self):
        """No date field, no parameters: no bound exists to offer."""
        import review_slots as slots_module
        ctx = {"models": [{"name": "W", "fields": [
                    {"name": "level", "type": "int"}]}],
               "entity_names": ["W"]}
        repo = {"entity": "W"}
        method = {"name": "low_stock", "params": []}
        self.assertIsNone(slots_module._slot_options(
            ctx, repo, method, "THRESHOLD_SCAN"))


WIDGET_MODEL = {"name": "Widget", "fields": [
    {"name": "id", "type": "int", "primary_key": True},
    {"name": "name", "type": "string"},
    {"name": "is_flagged", "type": "boolean"},
    {"name": "status", "type": "string"}]}

WIDGET_INVARIANTS = [
    {"kind": "schema",
     "text": "Widget.status must be one of ['draft', 'live']"}]


def criterion_ctx(slots=None, invariants=None):
    """Hand ctx for FILTER_CRITERION: a boolean field and a documented set."""
    ctx = {
        "models": [WIDGET_MODEL], "errors": [],
        "invariants": (WIDGET_INVARIANTS if invariants is None
                       else invariants),
        "services": [], "entity_names": ["Widget"],
        "repositories": [{"entity": "Widget",
                          "interface_name": "WidgetRepository",
                          "methods": [
                              {"name": "find_flagged_widgets", "params": [],
                               "return_type": "List[Widget]",
                               "description": "flagged"},
                              {"name": "find_live_widgets", "params": [],
                               "return_type": "List[Widget]",
                               "description": "live"},
                              {"name": "read_all_widgets", "params": [],
                               "return_type": "List[Widget]",
                               "description": "all"},
                          ]}],
        "mappings": {}, "match_index": {
            "contract:WidgetRepository.find_flagged_widgets":
                {"pattern_id": "READ_ALL", "decision": "decided"},
            "contract:WidgetRepository.find_live_widgets":
                {"pattern_id": "FILTER_BY_FIELD", "decision": "decided"},
            "contract:WidgetRepository.read_all_widgets":
                {"pattern_id": "READ_ALL", "decision": "decided"},
        },
        "adapters": [], "components": {}, "slots": {},
    }
    for name, spec in (slots or {}).items():
        ctx["slots"][("WidgetRepository", name)] = {
            "holder": "WidgetRepository", "method": name, "slots": spec}
    return ctx


class CriterionTests(unittest.TestCase):
    """Parameterless status filters: offered with documented candidates,
    emitted as real equality filters, refused when nothing grounds the
    literal — the generator never reads `active` off a method name."""

    def test_question_offers_documented_fields_only(self):
        ctx = criterion_ctx()
        repo = ctx["repositories"][0]
        method = repo["methods"][0]
        slots = dict(review_slots._slot_options(ctx, repo, method,
                                                "FILTER_CRITERION"))
        self.assertEqual(slots["criterion_field"], ["is_flagged", "status"])
        self.assertNotIn("name", slots["criterion_field"])
        self.assertIsNone(slots["criterion_value"])
        question = {"entity": "Widget", "role": "repository"}
        self.assertEqual(
            review_slots._resolve_deferred(
                ctx, question, method, "criterion_value",
                {"criterion_field": "is_flagged"}), ["True", "False"])
        self.assertEqual(
            review_slots._resolve_deferred(
                ctx, question, method, "criterion_value",
                {"criterion_field": "status"}), ["draft", "live"])

    def test_only_stubbed_filters_are_asked(self):
        ctx = criterion_ctx()
        flagged = ctx["repositories"][0]["methods"][0]
        read_all = ctx["repositories"][0]["methods"][2]
        self.assertEqual(generator._slot_pattern(
            ctx, "WidgetRepository", flagged)[0], "FILTER_CRITERION")
        # A genuine read-all plans mechanically: nothing to ask.
        self.assertIsNone(generator._slot_pattern(
            ctx, "WidgetRepository", read_all)[0])

    def test_a_rule_resolved_parameterless_filter_still_asks(self):
        """`signature-pagination` must not hide the missing criterion.

        The rule only decides pagination vs. a plain filter. With no
        parameter, the plan is still a stub; without the synthetic question
        `find_active_members` would never become usable, and the surface
        review could only offer the inverse `find_inactive_members`.
        """
        ctx = criterion_ctx()
        ctx["match_index"]["contract:WidgetRepository.find_flagged_widgets"] = {
            "pattern_id": "FILTER_BY_FIELD",
            "runner_up_pattern_id": "FILTER_WITH_PAGINATION",
            "decision": "undecided",
            "undecided_stage": "pattern",
        }
        flagged = ctx["repositories"][0]["methods"][0]
        self.assertEqual(generator._slot_pattern(
            ctx, "WidgetRepository", flagged)[0], "FILTER_CRITERION")

    def test_a_rule_resolved_parameterized_filter_is_not_asked(self):
        """With a parameter, `signature-pagination` is already mechanical."""
        ctx = criterion_ctx()
        method = {"name": "find_widgets_by_status",
                  "params": [{"name": "status", "type": "str"}],
                  "return_type": "List[Widget]", "description": "status"}
        ctx["repositories"][0]["methods"].append(method)
        ctx["match_index"]["contract:WidgetRepository.find_widgets_by_status"] = {
            "pattern_id": "FILTER_BY_FIELD",
            "runner_up_pattern_id": "FILTER_WITH_PAGINATION",
            "decision": "undecided",
            "undecided_stage": "pattern",
        }
        self.assertIsNone(generator._slot_pattern(
            ctx, "WidgetRepository", method)[0])

    def test_field_enum_reads_only_the_documented_line(self):
        ctx = criterion_ctx()
        self.assertEqual(generator._field_enum(ctx, "Widget", "status"),
                         ["draft", "live"])
        self.assertEqual(generator._field_enum(ctx, "Widget", "name"), [])
        self.assertEqual(generator._field_enum(ctx, "Missing", "status"), [])

    def test_answered_booleans_and_vocabulary_run(self):
        ctx = criterion_ctx({
            "find_flagged_widgets": {"criterion_field": "is_flagged",
                                     "criterion_value": "True"},
            "find_live_widgets": {"criterion_field": "status",
                                  "criterion_value": "live"}})
        stats = {"source": "t", "implemented": 0, "stubs": 0,
                 "stub_reasons": []}
        namespace, store = exec_repos(generator.emit_repositories(ctx, stats))
        # Two criteria plus the repo's plain mechanical read-all.
        self.assertEqual(stats["implemented"], 3)
        backend = store.Store()
        backend.add("Widget", "id", {"name": "a", "is_flagged": True,
                                     "status": "draft"})
        backend.add("Widget", "id", {"name": "b", "is_flagged": False,
                                     "status": "live"})
        backend.add("Widget", "id", {"name": "c", "is_flagged": False,
                                     "status": "draft"})
        repo = namespace["WidgetRepository"](backend)
        self.assertEqual([w["name"] for w in repo.find_flagged_widgets()],
                         ["a"])
        self.assertEqual([w["name"] for w in repo.find_live_widgets()],
                         ["b"])

    def test_undocumented_literals_refuse_to_emit(self):
        # A boolean field takes exactly True/False; a plain string field has
        # no vocabulary, so no value of it may be baked in.
        ctx = criterion_ctx({
            "find_flagged_widgets": {"criterion_field": "is_flagged",
                                     "criterion_value": "yes"},
            "find_live_widgets": {"criterion_field": "name",
                                  "criterion_value": "a"}})
        stats = {"source": "t", "implemented": 0, "stubs": 0,
                 "stub_reasons": []}
        text = generator.emit_repositories(ctx, stats)
        # Only the repo's plain mechanical read-all survives; the two
        # criterion methods refuse rather than filter on an invented value.
        self.assertEqual(stats["implemented"], 1)
        for name in ("find_flagged_widgets", "find_live_widgets"):
            body = text.split(f"def {name}")[1].split("    def ")[0]
            self.assertIn("NotImplementedError", body)


class ReviewFlowTests(unittest.TestCase):
    def test_answers_record_slots_with_pattern(self):
        with tempfile.TemporaryDirectory() as directory:
            out = writes(directory)
            # monthly: func=1/SUM, target=1/amount_cents, date=1/expense_date.
            # The stale threshold aborts (no bound offerable) and stays open.
            asked, answered = run_review(
                out, input_fn=lambda _: "1", out_fn=lambda _: None)
            self.assertEqual((asked, answered), (3, 2))
            saved = review_slots.load_method_slots(out)
            monthly = next(r for r in saved
                           if r["method"] == "get_monthly_expense_total")
            self.assertEqual(monthly["pattern"], "AGGREGATE_BY_FK_AND_DATE")
            self.assertEqual(monthly["slots"]["aggregate_func"], "SUM")
            self.assertEqual(monthly["slots"]["target_field"], "amount_cents")
            self.assertEqual(monthly["slots"]["date_field"], "expense_date")

    def test_skip_records_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            out = writes(directory)
            asked, answered = run_review(
                out, input_fn=lambda _: "skip", out_fn=lambda _: None)
            self.assertEqual((asked, answered), (3, 0))
            self.assertEqual(review_slots.load_method_slots(out), [])


class EmitterTests(unittest.TestCase):
    def test_monthly_sum_with_prefix_runs(self):
        ctx = ctx_with({"get_monthly_expense_total": {
            "aggregate_func": "SUM", "target_field": "amount_cents",
            "date_field": "expense_date"}})
        stats = {"source": "t", "implemented": 0, "stubs": 0,
                 "stub_reasons": []}
        namespace, store = exec_repos(generator.emit_repositories(ctx, stats))
        backend = store.Store()
        repo = namespace["ExpenseRepository"](backend)
        backend.add("Expense", "id", {"expense_date": "2024-01-05",
                                      "amount_cents": 150,
                                      "category_id": 1})
        backend.add("Expense", "id", {"expense_date": "2024-02-01",
                                      "amount_cents": 999,
                                      "category_id": 1})
        self.assertEqual(repo.get_monthly_expense_total("2024-01"), 150)
        self.assertEqual(repo.get_monthly_expense_total("2024-03"), 0)

    def test_category_range_sum_and_count_and_avg(self):
        ctx = ctx_with({"get_category_spending": {
            "fk_field": "category_id", "aggregate_func": "SUM",
            "target_field": "amount_cents", "date_field": "expense_date"}})
        stats = {"source": "t", "implemented": 0, "stubs": 0,
                 "stub_reasons": []}
        namespace, store = exec_repos(generator.emit_repositories(ctx, stats))
        backend = store.Store()
        repo = namespace["ExpenseRepository"](backend)
        backend.add("Expense", "id", {"expense_date": "2024-01-05",
                                      "amount_cents": 100, "category_id": 1})
        backend.add("Expense", "id", {"expense_date": "2024-01-20",
                                      "amount_cents": 200, "category_id": 1})
        backend.add("Expense", "id", {"expense_date": "2024-01-10",
                                      "amount_cents": 500, "category_id": 2})
        self.assertEqual(
            repo.get_category_spending(1, "2024-01-01", "2024-01-31"), 300)
        self.assertEqual(
            repo.get_category_spending(2, "2024-01-01", "2024-01-31"), 500)
        self.assertEqual(
            repo.get_category_spending(9, "2024-01-01", "2024-01-31"), 0)

    def test_threshold_today_filters_overdue(self):
        import datetime
        methods = repo_methods()
        stale = next(m for m in methods if m["name"] == "get_stale_expenses")
        stale["params"] = [{"name": "as_of", "type": "str"}]
        ctx = ctx_with({"get_stale_expenses": {
            "comparison_field": "expense_date", "operator": "<",
            "threshold": "today"}}, methods)
        stats = {"source": "t", "implemented": 0, "stubs": 0,
                 "stub_reasons": []}
        namespace, store = exec_repos(generator.emit_repositories(ctx, stats))
        backend = store.Store()
        repo = namespace["ExpenseRepository"](backend)
        backend.add("Expense", "id", {"expense_date": "2001-01-01",
                                      "amount_cents": 1})
        backend.add("Expense", "id", {"expense_date": "2999-01-01",
                                      "amount_cents": 2})
        rows = repo.get_stale_expenses("2999-06-01")
        self.assertEqual([r["amount_cents"] for r in rows], [1])
        today = datetime.date.today().isoformat()
        rows = repo.get_stale_expenses(today)
        self.assertEqual([r["amount_cents"] for r in rows], [1])

    def test_malformed_slots_stay_stubs(self):
        ctx = ctx_with({"get_monthly_expense_total": {
            "aggregate_func": "MEDIAN", "target_field": "amount_cents",
            "date_field": "expense_date"}})
        stats = {"source": "t", "implemented": 0, "stubs": 0,
                 "stub_reasons": []}
        text = generator.emit_repositories(ctx, stats)
        self.assertNotIn("for record in self._store.select", text)
        kinds = {m["method"]: (m["implemented"], m["how"])
                 for m in stats["methods"]}
        self.assertFalse(kinds["get_monthly_expense_total"][0])
        # The ordinary CRUD methods around it are unaffected.
        self.assertTrue(kinds["create_expense"][0])
        self.assertTrue(kinds["read_all_expenses"][0])


class ServiceRealizedTests(unittest.TestCase):
    """Same-name service methods delegate once their repo twin is mechanical."""

    def test_realized_delegation_runs(self):
        ctx = ctx_with({"get_category_spending": {
            "fk_field": "category_id", "aggregate_func": "SUM",
            "target_field": "amount_cents", "date_field": "expense_date"}})
        ctx["services"] = [{
            "service_name": "ExpenseService",
            "methods": [{
                "name": "get_category_spending",
                "params": [{"name": "category_id", "type": "int"},
                           {"name": "start_date", "type": "str"},
                           {"name": "end_date", "type": "str"}],
                "return_type": "int",
                "description": "spending"}]}]
        ctx["match_index"]["contract:ExpenseService.get_category_spending"] = {
            "pattern_id": "AGGREGATE_BY_FK_AND_DATE", "decision": "decided"}
        stats = {"source": "t", "implemented": 0, "stubs": 0,
                 "stub_reasons": []}
        text = generator.emit_services(
            ctx, generator._repo_index(ctx), stats)
        self.assertIn("pattern realized by target", text)

    def test_guard_services_never_delegate_past_the_check(self):
        ctx = ctx_with({"get_category_spending": {
            "fk_field": "category_id", "aggregate_func": "SUM",
            "target_field": "amount_cents", "date_field": "expense_date"}})
        ctx["services"] = [{
            "service_name": "ExpenseService",
            "methods": [{
                "name": "get_category_spending",
                "params": [{"name": "category_id", "type": "int"},
                           {"name": "start_date", "type": "str"},
                           {"name": "end_date", "type": "str"}],
                "return_type": "int",
                "description": "spending"}]}]
        ctx["match_index"]["contract:ExpenseService.get_category_spending"] = {
            "pattern_id": "BUDGET_OVERFLOW_GUARD", "decision": "decided"}
        stats = {"source": "t", "implemented": 0, "stubs": 0,
                 "stub_reasons": []}
        text = generator.emit_services(
            ctx, generator._repo_index(ctx), stats)
        self.assertNotIn("pattern realized by target", text)
        self.assertIn("raise NotImplementedError", text)


def budget_writes(directory):
    """Out dir with a guard-patterned service and check method."""
    path = Path(directory)
    (path / "data_models.json").write_text(json.dumps(
        {"data_models": [EXPENSE_MODEL, CATEGORY_MODEL, BUDGET_MODEL]}),
        encoding="utf-8")
    (path / "service_contracts.json").write_text(json.dumps(
        {"service_contracts": [{
            "service_name": "ExpenseService",
            "methods": [{
                "name": "add_expense",
                "params": [{"name": "expense", "type": "Expense"}],
                "return_type": "None",
                "description": "guarded add"}]}]}), encoding="utf-8")
    (path / "persistence_ports.json").write_text(json.dumps(
        {"persistence_ports": {
            "repositories": [
                {"entity": "Expense",
                 "interface_name": "ExpenseRepository",
                 "methods": [
                     {"name": "create_expense",
                      "params": [{"name": "expense", "type": "Expense"}],
                      "return_type": "None", "description": "create"},
                     {"name": "get_monthly_expense_total",
                      "params": [{"name": "month", "type": "str"}],
                      "return_type": "int", "description": "monthly"}]},
                {"entity": "Budget",
                 "interface_name": "BudgetRepository",
                 "methods": [
                     {"name": "create_budget",
                      "params": [{"name": "budget", "type": "Budget"}],
                      "return_type": "None", "description": "create"},
                     {"name": "read_budget_by_category_and_month",
                      "params": [{"name": "category_id", "type": "int"},
                                 {"name": "month", "type": "str"}],
                      "return_type": "Budget", "description": "one budget"},
                     {"name": "check_budget_status",
                      "params": [{"name": "category_id", "type": "int"},
                                 {"name": "month", "type": "str"}],
                      "return_type": "bool", "description": "within?"}],
                 }],
            "entity_mappings": []}}), encoding="utf-8")
    decisively = lambda pid: {"pattern_id": pid, "decision": "decided"}
    (path / "pattern_matches.json").write_text(json.dumps(
        {"pattern_matches": [
            {"source": "contract:ExpenseRepository.get_monthly_expense_total",
             **decisively("AGGREGATE_BY_FK_AND_DATE")},
            {"source": "contract:BudgetRepository.check_budget_status",
             **decisively("BUDGET_OVERFLOW_GUARD")},
            {"source": "contract:ExpenseService.add_expense",
             **decisively("BUDGET_OVERFLOW_GUARD")}]}), encoding="utf-8")
    (path / "components.json").write_text(json.dumps(
        {"components": {"facade": {"type": "cli", "technology": "argparse",
                                   "invocation": {"commands": []}},
                        "persistence": {"required": True,
                                        "technology": "sqlite"},
                        "external_access": [], "crud_services": []}}),
        encoding="utf-8")
    (path / "requirements.txt").write_text("budgets", encoding="utf-8")
    for name in ("errors", "intentions", "invariants",
                 "interaction_adapters"):
        (path / f"{name}.json").write_text(json.dumps({name: []}),
                                           encoding="utf-8")
    (path / "errors.json").write_text(json.dumps(
        {"errors": BUDGET_ERRORS}), encoding="utf-8")
    return str(path)


class GuardReviewTests(unittest.TestCase):
    """Guard questions enumerate the cast; the limit waits on its read."""

    def test_service_guard_question_lists_seven_slots(self):
        with tempfile.TemporaryDirectory() as directory:
            out = budget_writes(directory)
            questions, _ = collect_slots(out)
            guard = next(q for q in questions
                         if q["method"] == "add_expense")
            slots = dict(guard["options"])
            self.assertIn("create_expense", slots["create_method"])
            self.assertIn("get_monthly_expense_total",
                          slots["aggregate_method"])
            self.assertIn("read_budget_by_category_and_month",
                          slots["budget_method"])
            self.assertIn("amount_cents", slots["amount_field"])
            self.assertIn("expense_date", slots["date_field"])
            self.assertIsNone(slots["limit_field"])
            self.assertIn("BudgetExceededException", slots["error"])

    def test_repo_check_question_asks_spend_first(self):
        with tempfile.TemporaryDirectory() as directory:
            out = budget_writes(directory)
            questions, _ = collect_slots(out)
            check = next(q for q in questions
                         if q["method"] == "check_budget_status")
            slots = dict(check["options"])
            self.assertIn("Expense", slots["spend_entity"])
            self.assertIn("amount_limit_cents", slots["limit_field"])
            self.assertIsNone(slots["target_field"])
            self.assertIsNone(slots["date_field"])

    def test_foreign_keys_are_never_summed(self):
        """Summing `category_id` compiles but means nothing: FK fields are
        not offered as targets, amounts, or limits — the review once listed
        `category_id` beside `amount_cents` and a human picked it."""
        with tempfile.TemporaryDirectory() as directory:
            out = budget_writes(directory)
            questions, _ = collect_slots(out)
            monthly = next(q for q in questions
                           if q["method"] == "get_monthly_expense_total")
            self.assertEqual(dict(monthly["options"])["target_field"],
                             ["amount_cents"])
            guard = next(q for q in questions
                         if q["method"] == "add_expense")
            self.assertEqual(dict(guard["options"])["amount_field"],
                             ["amount_cents"])

    def test_full_guard_round_trip_records_and_reopens_nothing_answerable(self):
        with tempfile.TemporaryDirectory() as directory:
            out = budget_writes(directory)
            # Answered by name: monthly SUM/amount/date; check
            # spend/limit/target/date; guard create/aggregate/budget/amount/
            # date/limit/error.
            answers = iter([
                "SUM", "amount_cents", "expense_date",
                "Expense", "amount_limit_cents", "amount_cents",
                "expense_date",
                "create_expense", "get_monthly_expense_total",
                "read_budget_by_category_and_month", "amount_cents",
                "expense_date", "amount_limit_cents",
                "BudgetExceededException",
            ])
            asked, answered = run_review(
                out, input_fn=lambda _: next(answers), out_fn=lambda _: None)
            self.assertEqual((asked, answered), (3, 3))
            saved = { (r["holder"], r["method"]): r
                      for r in review_slots.load_method_slots(out) }
            guard = saved[("ExpenseService", "add_expense")]
            self.assertEqual(guard["slots"]["limit_field"],
                             "amount_limit_cents")
            self.assertEqual(collect_slots(out)[0], [])


if __name__ == "__main__":
    unittest.main()
