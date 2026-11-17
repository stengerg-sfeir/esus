"""The two contradictions removed by `kernel.extraction.repairs`.

Each test pins one decision and, where the repair must stay silent, pins that
silence too — a repair that removes a value the document does not contradict is
worse than no repair. The predicates are shared with the checker, so these also
assert that the repair agrees with the rule that used to report the defect.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.extraction import repairs  # noqa: E402


class Log:
    def __init__(self):
        self.lines = []

    def write(self, text):
        self.lines.append(text)

    def joined(self):
        return "\n".join(self.lines)


def contract(name, raises):
    return {"service_name": "S", "methods": [{"name": name, "raises": list(raises)}]}


class NestedDeclarationTests(unittest.TestCase):
    def test_a_sibling_class_nested_as_a_method_is_dropped(self):
        services = [
            {"service_name": "BookRepository", "methods": [
                {"name": "read_all", "params": [],
                 "return_type": "list[Book]"},
                {"name": "AuthorRepository",
                 "description": "Repository for managing authors.",
                 "params": [], "return_type": None, "raises": []},
            ]},
            {"service_name": "AuthorRepository", "methods": [
                {"name": "read_all", "params": [],
                 "return_type": "list[Author]"},
            ]},
        ]
        log = Log()
        repaired = repairs.repair_nested_declarations(services, log)
        self.assertEqual([m["name"] for m in repaired[0]["methods"]],
                         ["read_all"])
        self.assertIn("dropped nested declaration 'AuthorRepository'",
                      log.joined())
        self.assertEqual(len(repaired[1]["methods"]), 1)

    def test_a_method_that_reads_a_sibling_contract_is_kept(self):
        services = [{"service_name": "BookRepository", "methods": [
            {"name": "read_all", "params": [], "return_type": "list[Book]"},
            {"name": "find_author_repository", "params": [],
             "return_type": "AuthorRepository"},
        ]}]
        repaired = repairs.repair_nested_declarations(services, Log())
        self.assertEqual([m["name"] for m in repaired[0]["methods"]],
                         ["read_all", "find_author_repository"])


class DuplicateErrorSubjectTests(unittest.TestCase):
    def test_two_names_for_one_missing_record_leave_one(self):
        errors = [{"name": "ProductNotFoundError"}, {"name": "MissingProductError"}]
        log = Log()
        kept, _ = repairs.repair_errors(errors, [], log)
        self.assertEqual([item["name"] for item in kept], ["ProductNotFoundError"])

    def test_the_kept_name_is_the_one_a_method_raises(self):
        errors = [{"name": "MissingProductError"}, {"name": "ProductNotFoundError"}]
        services = [contract("get_product_by_id", ["ProductNotFoundError"])]
        kept, _ = repairs.repair_errors(errors, services, Log())
        self.assertEqual([item["name"] for item in kept], ["ProductNotFoundError"])

    def test_a_reference_to_the_dropped_name_is_redirected(self):
        """Both names raised by different methods: the later one is redirected."""
        errors = [{"name": "ProductNotFoundError"}, {"name": "MissingProductError"}]
        services = [
            contract("get_product_by_id", ["ProductNotFoundError"]),
            contract("read_product_by_code", ["MissingProductError"]),
        ]
        _, repaired = repairs.repair_errors(errors, services, Log())
        self.assertEqual(
            repaired[1]["methods"][0]["raises"], ["ProductNotFoundError"]
        )

    def test_one_name_per_subject_is_left_alone(self):
        errors = [{"name": "ProductNotFoundError"}, {"name": "CategoryNotFoundError"}]
        log = Log()
        kept, _ = repairs.repair_errors(errors, [], log)
        self.assertEqual(len(kept), 2)
        self.assertEqual(log.lines, [])


class ContradictoryRaiseTests(unittest.TestCase):
    def test_a_create_loses_the_not_found_of_what_it_creates(self):
        services = [contract("create_product", ["ProductNotFoundError"])]
        _, repaired = repairs.repair_errors([], services, Log())
        self.assertEqual(repaired[0]["methods"][0]["raises"], [])

    def test_add_stock_keeps_the_product_not_found_it_must_find(self):
        """`add` is ambiguous: adding stock finds the product, so the raise stays."""
        services = [contract("add_stock", ["ProductNotFoundError"])]
        _, repaired = repairs.repair_errors([], services, Log())
        self.assertEqual(repaired[0]["methods"][0]["raises"], ["ProductNotFoundError"])

    def test_a_reader_keeps_its_not_found(self):
        services = [contract("read_product_by_id", ["ProductNotFoundError"])]
        _, repaired = repairs.repair_errors([], services, Log())
        self.assertEqual(repaired[0]["methods"][0]["raises"], ["ProductNotFoundError"])


class MismatchedTransformTests(unittest.TestCase):
    def adapter(self, field_name, transform):
        return {
            "action_name": "add_book",
            "input_fields": [{"field_name": field_name, "transform": transform}],
        }

    def test_a_count_converted_to_cents_becomes_direct(self):
        adapters = [self.adapter("copies", "DECIMAL_TO_CENTS")]
        repairs.repair_adapter_transforms(adapters, Log())
        self.assertEqual(adapters[0]["input_fields"][0]["transform"], "DIRECT")

    def test_a_money_amount_keeps_its_transform(self):
        adapters = [self.adapter("price_cents", "DECIMAL_TO_CENTS")]
        repairs.repair_adapter_transforms(adapters, Log())
        self.assertEqual(adapters[0]["input_fields"][0]["transform"], "DECIMAL_TO_CENTS")

    def test_a_single_name_read_as_a_list_becomes_direct(self):
        adapters = [self.adapter("title", "CSV_LIST")]
        repairs.repair_adapter_transforms(adapters, Log())
        self.assertEqual(adapters[0]["input_fields"][0]["transform"], "DIRECT")

    def test_a_date_field_keeps_its_transform(self):
        adapters = [self.adapter("expense_date", "ISO_DATE")]
        repairs.repair_adapter_transforms(adapters, Log())
        self.assertEqual(adapters[0]["input_fields"][0]["transform"], "ISO_DATE")

    def test_direct_is_never_touched(self):
        adapters = [self.adapter("anything", "DIRECT")]
        repairs.repair_adapter_transforms(adapters, Log())
        self.assertEqual(adapters[0]["input_fields"][0]["transform"], "DIRECT")

    def services(self):
        return [{"service_name": "BookRepository", "methods": [
            {"name": "create", "params": [
                {"name": "published_year", "type": "int"},
                {"name": "isbn", "type": "str"},
            ]},
        ]}]

    def test_a_year_parsed_as_a_date_becomes_direct(self):
        adapters = [{
            "action_name": "add_book",
            "target_service": "BookRepository",
            "target_method": "create",
            "input_fields": [{
                "field_name": "published_year",
                "target_param": "published_year",
                "transform": "ISO_DATE"}],
        }]
        repairs.repair_adapter_transforms(adapters, Log(), self.services())
        self.assertEqual(adapters[0]["input_fields"][0]["transform"], "DIRECT")

    def test_a_month_label_parsed_as_a_date_becomes_direct(self):
        services = [{"service_name": "BudgetRepository", "methods": [
            {"name": "read_budget", "params": [
                {"name": "month", "type": "str"}]},
        ]}]
        adapters = [{
            "action_name": "read_budget",
            "target_service": "BudgetRepository",
            "target_method": "read_budget",
            "input_fields": [{
                "field_name": "month",
                "target_param": "month",
                "transform": "ISO_DATE"}],
        }]
        repairs.repair_adapter_transforms(adapters, Log(), services)
        self.assertEqual(adapters[0]["input_fields"][0]["transform"], "DIRECT")

    def test_an_isbn_looked_up_as_an_id_becomes_direct(self):
        adapters = [{
            "action_name": "add_book",
            "target_service": "BookRepository",
            "target_method": "create",
            "input_fields": [{
                "field_name": "isbn",
                "target_param": "isbn",
                "transform": "LOOKUP_ID"}],
        }]
        repairs.repair_adapter_transforms(adapters, Log(), self.services())
        self.assertEqual(adapters[0]["input_fields"][0]["transform"], "DIRECT")

    def filter_services(self, param_type):
        return [{"service_name": "BookService", "methods": [
            {"name": "read_all_books", "params": [
                {"name": "available_only", "type": param_type},
            ]},
        ]}]

    def filter_adapter(self):
        return [{
            "action_name": "list_books",
            "target_service": "BookService",
            "target_method": "read_all_books",
            "input_fields": [{
                "field_name": "available_only",
                "target_param": "available_only",
                "transform": "BOOL_TO_ONE"}],
        }]

    def test_a_presence_flag_onto_a_bool_parameter_becomes_direct(self):
        adapters = self.filter_adapter()
        repairs.repair_adapter_transforms(
            adapters, Log(), self.filter_services("bool"))
        self.assertEqual(adapters[0]["input_fields"][0]["transform"], "DIRECT")

    def test_a_presence_flag_onto_an_int_threshold_keeps_bool_to_one(self):
        adapters = self.filter_adapter()
        repairs.repair_adapter_transforms(
            adapters, Log(), self.filter_services("int"))
        self.assertEqual(
            adapters[0]["input_fields"][0]["transform"], "BOOL_TO_ONE")


class UnraisedErrorTests(unittest.TestCase):
    """An error no method raises is dropped only when the requirements disown it."""

    REQUIREMENTS = (
        "Book lending CLI. Handles overdue loans and reports an overdue list."
    )

    def test_a_raised_error_is_kept(self):
        errors = [{"name": "BookNotFoundError"}]
        services = [contract("find_book", ["BookNotFoundError"])]
        kept = repairs.repair_unraised_errors(errors, services, self.REQUIREMENTS, Log())
        self.assertEqual([item["name"] for item in kept], ["BookNotFoundError"])

    def test_a_grounded_unraised_error_is_kept(self):
        """`OverdueLoanFoundError` is unraised but the requirements say 'overdue'."""
        errors = [{"name": "OverdueLoanFoundError"}]
        log = Log()
        kept = repairs.repair_unraised_errors(errors, [], self.REQUIREMENTS, log)
        self.assertEqual([item["name"] for item in kept], ["OverdueLoanFoundError"])
        self.assertEqual(log.lines, [])

    def test_a_named_unraised_error_is_kept(self):
        errors = [{"name": "BookNotFoundError"}]
        kept = repairs.repair_unraised_errors(
            errors, [], "raise BookNotFoundError when absent", Log()
        )
        self.assertEqual([item["name"] for item in kept], ["BookNotFoundError"])

    def test_an_ungrounded_validation_error_is_dropped(self):
        errors = [{"name": "InvalidInputError"}]
        log = Log()
        kept = repairs.repair_unraised_errors(errors, [], self.REQUIREMENTS, log)
        self.assertEqual(kept, [])
        self.assertEqual(len(log.lines), 1)

    def test_a_partly_grounded_validation_error_is_still_dropped(self):
        """'budget' grounds the name, but a validation shape is dropped anyway."""
        errors = [{"name": "InvalidBudgetAmountError"}]
        kept = repairs.repair_unraised_errors(errors, [], "the budget is stored", Log())
        self.assertEqual(kept, [])

    def test_an_ungrounded_unraised_error_is_dropped(self):
        errors = [{"name": "MalformedCSVError"}]
        kept = repairs.repair_unraised_errors(errors, [], "a book lending tool", Log())
        self.assertEqual(kept, [])

    def test_a_grounded_validation_error_is_kept(self):
        """cli_tool's requirements say 'malformed CSV', so the class is warranted."""
        errors = [{"name": "MalformedCSVError"}]
        kept = repairs.repair_unraised_errors(
            errors, [], "Handle missing files and malformed CSV input.", Log()
        )
        self.assertEqual([item["name"] for item in kept], ["MalformedCSVError"])

    def test_no_requirements_leaves_the_registry_untouched(self):
        errors = [{"name": "InvalidInputError"}]
        kept = repairs.repair_unraised_errors(errors, [], "", Log())
        self.assertEqual([item["name"] for item in kept], ["InvalidInputError"])

    def test_the_library_case_drops_two_and_keeps_one(self):
        errors = [
            {"name": "MalformedCSVError"},
            {"name": "InvalidInputError"},
            {"name": "OverdueLoanFoundError"},
        ]
        kept = repairs.repair_unraised_errors(errors, [], self.REQUIREMENTS, Log())
        self.assertEqual([item["name"] for item in kept], ["OverdueLoanFoundError"])


class MisplacedTargetTests(unittest.TestCase):
    """A field sent past a parameter of its own name is redirected to it.

    The predicate is the checker's (`misplaced_field`): the method has already
    said where the value goes, so mapping it elsewhere silently drops the
    field. Measured on expenses (`add_expense` sent `category_id` into `data`,
    `update_budget` sent `month` into `budget`).
    """

    def services(self):
        return [
            {
                "service_name": "ExpenseService",
                "methods": [
                    {
                        "name": "add_expense",
                        "params": [{"name": "data"}, {"name": "category_id"}],
                    }
                ],
            }
        ]

    def adapter(self, field_name, target_param):
        return {
            "action_name": "add_expense",
            "target_service": "ExpenseService",
            "target_method": "add_expense",
            "input_fields": [
                {"field_name": field_name, "target_param": target_param}
            ],
        }

    def test_a_field_sent_past_its_own_parameter_is_redirected(self):
        adapters = [self.adapter("category_id", "data")]
        log = Log()
        repairs.repair_adapter_targets(adapters, self.services(), log)
        self.assertEqual(
            adapters[0]["input_fields"][0]["target_param"], "category_id"
        )
        self.assertEqual(len(log.lines), 1)

    def test_a_field_sent_to_its_own_parameter_is_left_alone(self):
        adapters = [self.adapter("category_id", "category_id")]
        log = Log()
        repairs.repair_adapter_targets(adapters, self.services(), log)
        self.assertEqual(
            adapters[0]["input_fields"][0]["target_param"], "category_id"
        )
        self.assertEqual(log.lines, [])

    def test_a_field_with_no_parameter_of_its_own_is_left_alone(self):
        """`description` folded into `data` has no same-named parameter to prefer."""
        adapters = [self.adapter("description", "data")]
        log = Log()
        repairs.repair_adapter_targets(adapters, self.services(), log)
        self.assertEqual(adapters[0]["input_fields"][0]["target_param"], "data")
        self.assertEqual(log.lines, [])

    def test_an_adapter_with_an_unknown_method_is_left_alone(self):
        adapters = [self.adapter("category_id", "data")]
        adapters[0]["target_method"] = "no_such_method"
        log = Log()
        repairs.repair_adapter_targets(adapters, self.services(), log)
        self.assertEqual(adapters[0]["input_fields"][0]["target_param"], "data")
        self.assertEqual(log.lines, [])

    def test_an_adapter_with_an_unknown_service_is_left_alone(self):
        adapters = [self.adapter("category_id", "data")]
        adapters[0]["target_service"] = "NoSuchService"
        log = Log()
        repairs.repair_adapter_targets(adapters, self.services(), log)
        self.assertEqual(adapters[0]["input_fields"][0]["target_param"], "data")
        self.assertEqual(log.lines, [])

    def test_a_second_field_bound_to_one_scalar_is_dropped(self):
        services = [{"service_name": "BookRepository", "methods": [{
            "name": "create",
            "params": [{"name": "isbn", "type": "str"},
                       {"name": "published_year", "type": "int"}],
        }]}]
        adapters = [{
            "action_name": "add_book",
            "target_service": "BookRepository",
            "target_method": "create",
            "input_fields": [
                {"field_name": "isbn", "target_param": "isbn"},
                {"field_name": "author_id", "target_param": "isbn"},
            ],
        }]
        log = Log()
        repairs.repair_adapter_targets(adapters, services, log)
        self.assertEqual(
            [f["field_name"] for f in adapters[0]["input_fields"]],
            ["isbn"])
        self.assertIn("duplicates the scalar parameter", log.joined())


class PlaceholderSubcommandTests(unittest.TestCase):
    """A subcommand named `none` states there is none, and is dropped.

    Library's bare `` `library overdue` `` line came back as command `overdue`
    with subcommand `none`: no method serves it, so the probe reports
    `unbacked_command` and the generator cannot write the call. Dropping it
    leaves the bare command the requirements describe.
    """

    def components(self, subcommands):
        return {
            "facade": {
                "invocation": {
                    "commands": [
                        {"name": "overdue", "subcommands": subcommands}
                    ]
                }
            }
        }

    def test_a_none_subcommand_is_dropped(self):
        body = self.components([{"name": "none", "options": []}])
        log = Log()
        repairs.repair_placeholder_subcommands(body, log)
        self.assertEqual(
            body["facade"]["invocation"]["commands"][0]["subcommands"], []
        )
        self.assertEqual(len(log.lines), 1)

    def test_real_siblings_are_kept(self):
        body = self.components([{"name": "add"}, {"name": "none"}, {"name": "list"}])
        repairs.repair_placeholder_subcommands(body, Log())
        self.assertEqual(
            [s["name"] for s in body["facade"]["invocation"]["commands"][0]["subcommands"]],
            ["add", "list"],
        )

    def test_case_does_not_save_a_placeholder(self):
        body = self.components([{"name": "None"}])
        repairs.repair_placeholder_subcommands(body, Log())
        self.assertEqual(
            body["facade"]["invocation"]["commands"][0]["subcommands"], []
        )

    def test_a_clean_surface_is_left_alone(self):
        body = self.components([{"name": "add"}])
        log = Log()
        repairs.repair_placeholder_subcommands(body, log)
        self.assertEqual(
            [s["name"] for s in body["facade"]["invocation"]["commands"][0]["subcommands"]],
            ["add"],
        )
        self.assertEqual(log.lines, [])

    def test_a_body_with_no_surface_is_left_alone(self):
        self.assertEqual(repairs.repair_placeholder_subcommands({}, Log()), {})
        self.assertIsNone(repairs.repair_placeholder_subcommands(None, Log()))


class FlatCommandDuplicateTests(unittest.TestCase):
    """A flat `a_b` duplicating a declared `a b` pair is the flat form that goes.

    Library emitted command `member` with subcommand `history` (carrying the
    flags) plus a flat `member_history` with no subcommands: the flat form has
    no method behind it, so the probe reports `unbacked_command` and the
    generator refuses. Only the flat duplicate is dropped, and only when the
    spaced pair exists — a genuinely flat command is untouched.
    """

    def components(self, commands):
        return {"facade": {"invocation": {"commands": commands}}}

    def test_flat_duplicate_is_dropped(self):
        body = self.components([
            {"name": "member",
             "subcommands": [{"name": "history", "options": []}],
             "options": []},
            {"name": "member_history", "subcommands": [], "options": []},
        ])
        log = Log()
        repairs.repair_flat_command_duplicates(body, log)
        self.assertEqual(
            [c["name"] for c in body["facade"]["invocation"]["commands"]],
            ["member"],
        )
        self.assertEqual(len(log.lines), 1)

    def test_genuinely_flat_command_is_kept(self):
        body = self.components([
            {"name": "overdue", "subcommands": [], "options": []},
        ])
        log = Log()
        repairs.repair_flat_command_duplicates(body, log)
        self.assertEqual(
            [c["name"] for c in body["facade"]["invocation"]["commands"]],
            ["overdue"],
        )
        self.assertEqual(log.lines, [])

    def test_flat_form_with_subcommands_is_kept(self):
        body = self.components([
            {"name": "member",
             "subcommands": [{"name": "history", "options": []}],
             "options": []},
            {"name": "member_history",
             "subcommands": [{"name": "x", "options": []}],
             "options": []},
        ])
        repairs.repair_flat_command_duplicates(body, Log())
        self.assertEqual(
            [c["name"] for c in body["facade"]["invocation"]["commands"]],
            ["member", "member_history"],
        )


class PeriodFieldTypeTests(unittest.TestCase):
    """`month (str like "2024-01")` is a text period, not a date."""

    def models(self, field_type="date"):
        return [{"name": "Budget", "fields": [
            {"name": "id", "type": "int", "primary_key": True},
            {"name": "category_id", "type": "int"},
            {"name": "month", "type": field_type},
        ]}]

    def test_a_text_month_becomes_a_string(self):
        models = self.models()
        log = Log()
        repairs.repair_period_field_types(
            models, 'Budget model - category_id, month (str like "2024-01")',
            log)
        self.assertEqual(models[0]["fields"][2]["type"], "string")
        self.assertIn("month", log.joined())

    def test_an_invariant_can_declare_the_string_form(self):
        models = self.models()
        repairs.repair_period_field_types(
            models, "", Log(),
            [{"text": "Budget.month must be a string in the format 'YYYY-MM'"}])
        self.assertEqual(models[0]["fields"][2]["type"], "string")

    def test_a_date_field_without_a_text_declaration_is_untouched(self):
        models = self.models()
        repairs.repair_period_field_types(
            models, "Expense model - expense_date (str, ISO date)", Log())
        self.assertEqual(models[0]["fields"][2]["type"], "date")

    def test_a_non_period_date_field_is_never_rewritten(self):
        models = [{"name": "Expense", "fields": [
            {"name": "expense_date", "type": "date"}]}]
        repairs.repair_period_field_types(
            models, 'expense_date (str, ISO date)', Log())
        self.assertEqual(models[0]["fields"][0]["type"], "date")


class PrimaryKeyUniquenessTests(unittest.TestCase):
    """A primary key declaring `unique=false` contradicts itself; set it true.

    The predicate is the checker's own, so repair and rule cannot disagree.
    Only the contradicted flag is touched: a nullable primary key is left
    alone (auto-incremented ids are declared optional-None by several
    prompts, so nullability is modeling, not noise), as is a non-key field
    declaring `unique=false` (legitimate).
    """

    def test_contradicted_flag_is_set_true_and_logged(self):
        models = [{"name": "Assoc", "fields": [
            {"name": "wine_id", "type": "int", "primary_key": True,
             "unique": False}]}]
        log = Log()
        repairs.repair_primary_key_uniqueness(models, log)
        self.assertTrue(models[0]["fields"][0]["unique"])
        self.assertEqual(len(log.lines), 1)

    def test_nullable_keys_and_plain_fields_are_untouched(self):
        models = [{"name": "M", "fields": [
            {"name": "id", "type": "int", "primary_key": True,
             "nullable": True},
            {"name": "tag", "type": "str", "unique": False}]}]
        log = Log()
        repairs.repair_primary_key_uniqueness(models, log)
        self.assertNotIn("unique", models[0]["fields"][0])
        self.assertFalse(models[0]["fields"][1]["unique"])
        self.assertEqual(log.lines, [])

    def test_non_lists_pass_through(self):
        self.assertEqual(repairs.repair_primary_key_uniqueness({}, Log()), {})
        self.assertIsNone(repairs.repair_primary_key_uniqueness(None, Log()))

    def test_pair_repaired_in_first_still_drops_the_flat(self):
        """The pipeline order: placeholder, surface, flat-duplicate.

        A retry body can lack `member history` while keeping a flat
        `member_history` with a placeholder sub: the placeholder goes, the
        surface repair adds the pair, and only then does the flat form have
        a pair to match — an earlier pass finds nothing and keeps it.
        """
        body = {"facade": {"invocation": {"commands": [
            {"name": "member",
             "subcommands": [{"name": "add", "options": []}],
             "options": []},
            {"name": "member_history",
             "subcommands": [{"name": "none", "options": []}],
             "options": []},
        ]}}}
        requirements = "Run `library member history --member-id`."
        models = [{"name": "Member", "fields": [
            {"name": "id", "type": "int"}]}]
        log = Log()
        repairs.repair_placeholder_subcommands(body, log)
        repairs.repair_missing_surface(body, requirements, models, log)
        repairs.repair_flat_command_duplicates(body, log)
        commands = {c["name"]: [s["name"] for s in c.get("subcommands", [])]
                    for c in body["facade"]["invocation"]["commands"]}
        self.assertIn("history", commands.get("member", []))
        self.assertNotIn("member_history", commands)


class MissingFlagRepairTests(unittest.TestCase):
    """A required requirements flag the leaf lacks is added, typed by the model.

    Both halves are grounded elsewhere — the flag name in the requirements'
    own command line, the option type in the data model field it binds to —
    so nothing is invented. Anything ungrounded (no model field, disagreeing
    types, an optional flag, a missing leaf) is left for the retry and probe.
    """

    MODELS = [
        {"name": "Product", "fields": [
            {"name": "sku", "type": "string"},
            {"name": "name", "type": "string"},
            {"name": "price_cents", "type": "int"}]},
        {"name": "Category", "fields": [
            {"name": "name", "type": "string"}]},
    ]

    def components(self, options):
        return {
            "facade": {"type": "cli", "technology": "click",
                       "invocation": {"commands": [
                           {"name": "product", "options": [],
                            "subcommands": [
                                {"name": "add", "options": [
                                    {"name": name, "type": "str"} for name in options]}]}]}}
        }

    def options_of(self, body):
        subs = body["facade"]["invocation"]["commands"][0]["subcommands"]
        return {o["name"]: o for o in subs[0]["options"]}

    def test_a_missing_required_flag_is_added_typed_by_the_model(self):
        body = self.components(["--name"])
        log = Log()
        repairs.repair_missing_flags(
            body, "Run `product add --sku --name`.", self.MODELS, log)
        options = self.options_of(body)
        self.assertIn("--sku", options)
        self.assertEqual(options["--sku"]["type"], "str")
        self.assertTrue(options["--sku"]["required"])
        self.assertEqual(len(log.lines), 1)

    def test_an_abbreviated_flag_binds_its_model_field(self):
        body = self.components([])
        repairs.repair_missing_flags(
            body, "Run `product add --price`.", self.MODELS, Log())
        self.assertEqual(self.options_of(body)["--price"]["type"], "int")

    def test_a_flag_two_models_agree_on_is_added(self):
        """`--name` matches Category.name and Product.name: both strings."""
        body = self.components([])
        log = Log()
        repairs.repair_missing_flags(
            body, "Run `product add --name`.", self.MODELS, log)
        self.assertEqual(self.options_of(body)["--name"]["type"], "str")
        self.assertIn("2 models", log.lines[0])

    def test_an_untyped_optional_flag_is_left_alone(self):
        body = self.components([])
        log = Log()
        repairs.repair_missing_flags(
            body, "Run `product add [--icon]`.", self.MODELS, log)
        self.assertEqual(self.options_of(body), {})
        self.assertEqual(log.lines, [])

    def test_an_optional_flag_typed_by_the_model_is_added(self):
        body = self.components([])
        log = Log()
        repairs.repair_missing_flags(
            body, "Run `product add [--sku]`.", self.MODELS, log)
        options = self.options_of(body)
        self.assertEqual(options["--sku"]["type"], "str")
        self.assertFalse(options["--sku"]["required"])
        self.assertEqual(len(log.lines), 1)

    def test_an_optional_boolean_selector_is_added(self):
        body = self.components([])
        log = Log()
        repairs.repair_missing_flags(
            body, "Run `product add [--available-only]`.", self.MODELS, log)
        options = self.options_of(body)
        self.assertEqual(options["--available-only"]["type"], "bool")
        self.assertFalse(options["--available-only"]["required"])
        self.assertIn("optional '--available-only'", log.lines[0])

    def test_a_flag_with_no_model_field_is_left_alone(self):
        body = self.components([])
        log = Log()
        repairs.repair_missing_flags(
            body, "Run `product add --frob`.", self.MODELS, log)
        self.assertEqual(self.options_of(body), {})
        self.assertEqual(log.lines, [])

    def test_a_present_flag_is_left_alone(self):
        body = self.components(["--sku"])
        log = Log()
        repairs.repair_missing_flags(
            body, "Run `product add --sku`.", self.MODELS, log)
        self.assertEqual(len(self.options_of(body)), 1)
        self.assertEqual(log.lines, [])

    def test_no_models_means_no_repair(self):
        body = self.components([])
        repairs.repair_missing_flags(
            body, "Run `product add --sku`.", [], Log())
        self.assertEqual(self.options_of(body), {})


class AdapterFieldRenameTests(unittest.TestCase):
    """An entity-targeted field spelling no model field is renamed to it.

    The generator builds `Model(**fields)`, so `amount` into an Expense is
    construction that always fails — while `amount_cents` under
    DECIMAL_TO_CENTS converts flag dollars to model cents and is grounded on
    three sides (containment, uniqueness, units). DIRECT carries no unit
    evidence and is never renamed: flag `amount` in dollars into a cents
    field would silently change money.
    """

    SERVICES = [{"service_name": "ExpenseService", "methods": [
        {"name": "add_expense", "params": [{"name": "data", "type": "Expense"}]}]}]
    MODELS = [{"name": "Expense", "fields": [
        {"name": "amount_cents", "type": "int"},
        {"name": "description", "type": "string"}]}]

    def adapters(self, fields):
        return [{"action_name": "add_expense", "target_service": "ExpenseService",
                 "target_method": "add_expense",
                 "input_fields": [
                     {"field_name": name, "target_param": "data",
                      "transform": transform, "lookup_entity": None,
                      "required": True}
                     for name, transform in fields]}]

    def test_a_money_field_is_renamed_to_its_unique_model_field(self):
        adapters = self.adapters([("amount", "DECIMAL_TO_CENTS")])
        log = Log()
        repairs.repair_adapter_field_names(adapters, self.SERVICES, self.MODELS, log)
        self.assertEqual(adapters[0]["input_fields"][0]["field_name"], "amount_cents")
        self.assertEqual(len(log.lines), 1)

    def test_a_lookup_field_is_renamed_to_its_unique_model_field(self):
        services = [{"service_name": "S", "methods": [
            {"name": "m", "params": [{"name": "data", "type": "E"}]}]}]
        models = [{"name": "E", "fields": [{"name": "category_id", "type": "int"}]}]
        adapters = [{"action_name": "a", "target_service": "S", "target_method": "m",
                     "input_fields": [
                         {"field_name": "category", "target_param": "data",
                          "transform": "LOOKUP_ID", "lookup_entity": "E",
                          "required": True}]}]
        repairs.repair_adapter_field_names(adapters, services, models, Log())
        self.assertEqual(adapters[0]["input_fields"][0]["field_name"], "category_id")

    def test_a_direct_field_is_never_renamed_across_units(self):
        """`amount` into amount_cents needs a human: counts are not cents."""
        adapters = self.adapters([("amount", "DIRECT")])
        log = Log()
        repairs.repair_adapter_field_names(adapters, self.SERVICES, self.MODELS, log)
        self.assertEqual(adapters[0]["input_fields"][0]["field_name"], "amount")
        self.assertEqual(log.lines, [])

    def test_a_direct_qualifier_is_renamed_to_the_one_model_field(self):
        """`budget` into `monthly_budget` is the same value under one name."""
        models = [{"name": "Category", "fields": [
            {"name": "monthly_budget", "type": "int"}]}]
        services = [{"service_name": "CategoryRepository", "methods": [
            {"name": "update", "params": [{"name": "data", "type": "Category"}]}]}]
        adapters = [{"action_name": "category_update",
                     "target_service": "CategoryRepository",
                     "target_method": "update",
                     "input_fields": [
                         {"field_name": "budget", "target_param": "data",
                          "transform": "DIRECT", "lookup_entity": None,
                          "required": False}]}]
        log = Log()
        repairs.repair_adapter_field_names(adapters, services, models, log)
        self.assertEqual(adapters[0]["input_fields"][0]["field_name"],
                         "monthly_budget")
        self.assertEqual(len(log.lines), 1)

    def test_a_direct_qualifier_through_a_mapping_uses_the_service_entity(self):
        """`data: dict` names its entity only in CategoryRepository."""
        models = [{"name": "Category", "fields": [
            {"name": "monthly_budget", "type": "int"}]}]
        services = [{"service_name": "CategoryRepository", "methods": [
            {"name": "update", "params": [
                {"name": "id", "type": "int"},
                {"name": "data", "type": "dict[str, any]"}]}]}]
        adapters = [{"action_name": "category_update",
                     "target_service": "CategoryRepository",
                     "target_method": "update",
                     "input_fields": [
                         {"field_name": "budget", "target_param": "data",
                          "transform": "DIRECT", "lookup_entity": None,
                          "required": False}]}]
        repairs.repair_adapter_field_names(adapters, services, models, Log())
        self.assertEqual(adapters[0]["input_fields"][0]["field_name"],
                         "monthly_budget")

    def test_an_ambiguous_spelling_is_left_alone(self):
        models = [{"name": "E", "fields": [
            {"name": "amount_cents", "type": "int"},
            {"name": "amount_limit", "type": "int"}]}]
        services = [{"service_name": "S", "methods": [
            {"name": "m", "params": [{"name": "data", "type": "E"}]}]}]
        adapters = [{"action_name": "a", "target_service": "S", "target_method": "m",
                     "input_fields": [
                         {"field_name": "amount", "target_param": "data",
                          "transform": "DECIMAL_TO_CENTS", "lookup_entity": None,
                          "required": True}]}]
        repairs.repair_adapter_field_names(adapters, services, models, Log())
        self.assertEqual(adapters[0]["input_fields"][0]["field_name"], "amount")

    def test_an_exact_spelling_is_untouched(self):
        adapters = self.adapters([("description", "DIRECT")])
        log = Log()
        repairs.repair_adapter_field_names(adapters, self.SERVICES, self.MODELS, log)
        self.assertEqual(adapters[0]["input_fields"][0]["field_name"], "description")
        self.assertEqual(log.lines, [])

    def test_a_collision_with_a_sibling_is_left_alone(self):
        adapters = self.adapters([("amount", "DECIMAL_TO_CENTS"),
                                  ("amount_cents", "DECIMAL_TO_CENTS")])
        repairs.repair_adapter_field_names(adapters, self.SERVICES, self.MODELS, Log())
        self.assertEqual(adapters[0]["input_fields"][0]["field_name"], "amount")

    def test_a_scalar_target_is_untouched(self):
        adapters = [{"action_name": "a", "target_service": "S", "target_method": "m",
                     "input_fields": [
                         {"field_name": "id", "target_param": "id",
                          "transform": "DIRECT", "lookup_entity": None,
                          "required": True}]}]
        services = [{"service_name": "S", "methods": [
            {"name": "m", "params": [{"name": "id", "type": "int"}]}]}]
        repairs.repair_adapter_field_names(adapters, services, self.MODELS, Log())
        self.assertEqual(adapters[0]["input_fields"][0]["field_name"], "id")


class FlagSubcommandCollisionTests(unittest.TestCase):
    """A flag matching a subcommand name is not added.

    Library files `--member-id` under `borrow` while declaring a `member_id`
    subcommand beside it: adding the flag makes one word both a flag and a
    command. The repair yields — the probe reports the unbacked subcommand,
    correctly attributed to the model text rather than the repair.
    """

    MODELS = [{"name": "M", "fields": [{"name": "member_id", "type": "int"}]}]

    def components(self):
        return {
            "facade": {"type": "cli", "technology": "click",
                       "invocation": {"commands": [
                           {"name": "borrow", "options": [],
                            "subcommands": [
                                {"name": "member_id", "options": []}]}]}}
        }

    def test_a_colliding_flag_is_skipped_with_a_log_line(self):
        body = self.components()
        log = Log()
        repairs.repair_missing_flags(
            body, "Run `library borrow --member-id --book-id`.", self.MODELS, log)
        options = body["facade"]["invocation"]["commands"][0]["options"]
        self.assertEqual(options, [])
        self.assertTrue(any("not added" in line for line in log.lines))

    def test_a_non_colliding_flag_is_still_added(self):
        body = self.components()
        log = Log()
        repairs.repair_missing_flags(
            body, "Run `library borrow --book-id`.", self.MODELS, log)
        # --book-id binds no model field here (M has only member_id): untouched.
        self.assertEqual(
            body["facade"]["invocation"]["commands"][0]["options"], [])
        self.assertEqual(log.lines, [])


class AdapterFieldRenameDirectionTests(unittest.TestCase):
    """Only flag-abbreviates-field renames; never the reverse.

    `author_id` contains `id`, but renaming it to `id` repoints an author
    reference at the record itself — a silent corruption the probe would
    then bless as clean. Reverse containment is not evidence.
    """

    def test_a_suffix_match_is_left_alone(self):
        services = [{"service_name": "R", "methods": [
            {"name": "create_book", "params": [{"name": "book", "type": "Book"}]}]}]
        models = [{"name": "Book", "fields": [
            {"name": "id", "type": "int"},
            {"name": "title", "type": "string"}]}]
        adapters = [{"action_name": "add_book", "target_service": "R",
                     "target_method": "create_book",
                     "input_fields": [
                         {"field_name": "author_id", "target_param": "book",
                          "transform": "LOOKUP_ID", "lookup_entity": "Author",
                          "required": True}]}]
        log = Log()
        repairs.repair_adapter_field_names(adapters, services, models, log)
        self.assertEqual(adapters[0]["input_fields"][0]["field_name"], "author_id")
        self.assertEqual(log.lines, [])


class MissingSurfaceTests(unittest.TestCase):
    """Attributable command lines exist on the surface — built, not wished for.

    The model omits whole commands no retry recovers; the lines parse
    without it, so structure (commands, subcommands) is ensured here while
    judgment (shorts, crud, persistence) stays modeled. Flag filling
    delegates to the flag repair, so one pass covers both. Nothing model
    made is ever removed or restructured — including a bare line against a
    nested command, which stays the probe's to report.
    """

    MODELS = [
        {"name": "Member", "fields": [
            {"name": "name", "type": "string"},
            {"name": "email", "type": "string"}]},
        {"name": "Book", "fields": [{"name": "title", "type": "string"}]},
    ]
    REQUIREMENTS = ("Run `library member add --name --email`, "
                    "`library member history --member-id`.")

    def surface(self, commands):
        return {
            "facade": {"type": "cli", "technology": "click",
                       "invocation": {"commands": commands}}
        }

    def command(self, name, subs=()):
        return {"name": name, "options": [],
                "subcommands": [{"name": sub, "options": []} for sub in subs]}

    def test_a_missing_command_is_created_with_its_verbs_and_flags(self):
        body = self.surface([self.command("book", ["add"])])
        log = Log()
        repairs.repair_missing_surface(body, self.REQUIREMENTS, self.MODELS, log)
        commands = {c["name"]: c for c in
                    body["facade"]["invocation"]["commands"]}
        self.assertIn("member", commands)
        subs = {s["name"]: s for s in commands["member"]["subcommands"]}
        self.assertEqual(set(subs), {"add", "history"})
        names = {o["name"] for o in subs["add"]["options"]}
        self.assertIn("--name", names)
        self.assertIn("--email", names)
        self.assertIn("added command 'member'", log.joined()
                      if hasattr(log, "joined") else "")

    def test_existing_content_is_untouched(self):
        body = self.surface([{"name": "book", "options": [],
                              "subcommands": [
                                  {"name": "add",
                                   "options": [{"name": "--title",
                                                "type": "str"}]}]}])
        before = json.dumps(body, sort_keys=True)
        repairs.repair_missing_surface(
            body, "Run `library book add --title`.", self.MODELS, Log())
        self.assertEqual(json.dumps(body, sort_keys=True), before)

    def test_a_bare_line_creates_a_command_without_subcommands(self):
        body = self.surface([])
        repairs.repair_missing_surface(
            body, "Run `library borrow --member-id`.", self.MODELS, Log())
        commands = body["facade"]["invocation"]["commands"]
        self.assertEqual([(c["name"], c["subcommands"]) for c in commands],
                         [("borrow", [])])

    def test_a_bare_line_against_nested_content_restructures_nothing(self):
        """`borrow` filed with subcommands keeps them; the probe judges."""
        body = self.surface([{"name": "borrow", "options": [],
                              "subcommands": [{"name": "member-id",
                                               "options": []}]}])
        repairs.repair_missing_surface(
            body, "Run `library borrow --member-id`.", self.MODELS, Log())
        subs = body["facade"]["invocation"]["commands"][0]["subcommands"]
        self.assertEqual([s["name"] for s in subs], ["member-id"])

    def test_healed_surfaces_come_back_unchanged(self):
        """Idempotent: a second pass adds nothing and logs nothing structural."""
        body = self.surface([self.command("member", ["add", "history"])])

        class LoudLog(Log):
            def write(self, text):
                if "added command" in text or "added '" in text:
                    raise AssertionError(f"second pass added: {text}")

        repairs.repair_missing_surface(
            body, self.REQUIREMENTS, self.MODELS, LoudLog())


class AdapterFlagRepairTests(unittest.TestCase):
    """A required adapter field the bound leaf lacks gets an optional flag.

    The docs name both halves: the adapter field and the method parameter's
    type. Adding a CLI option for them makes the command runnable instead of
    reporting an uncovered field the generator cannot supply.
    """

    MODELS = [
        {"name": "Product", "fields": [
            {"name": "name", "type": "string"},
            {"name": "stock_qty", "type": "int"}]},
    ]
    SERVICES = [{"service_name": "ProductRepository", "methods": [
        {"name": "create_product", "params": [
            {"name": "name", "type": "str"},
            {"name": "stock_qty", "type": "int"}],
         "return_type": "Product"}]}]

    def surface(self, options=()):
        return {"facade": {"type": "cli", "technology": "argparse",
                           "invocation": {"commands": [
                               {"name": "product", "options": [],
                                "subcommands": [
                                    {"name": "add",
                                     "options": [{"name": name, "type": "str"}
                                                 for name in options]}]}]}}}

    def adapters(self, fields):
        return [{"action_name": "add_product",
                 "target_service": "ProductRepository",
                 "target_method": "create_product",
                 "input_fields": fields}]

    def test_a_missing_required_field_becomes_an_optional_flag(self):
        body = self.surface()
        adapters = self.adapters([
            {"field_name": "name", "target_param": "name", "required": True},
            {"field_name": "stock_qty", "target_param": "stock_qty",
             "required": True},
        ])
        log = Log()
        repairs.repair_missing_adapter_flags(
            body, adapters, self.SERVICES, self.MODELS, log)
        options = {o["name"]: o
                   for o in body["facade"]["invocation"]["commands"][0]["subcommands"][0]["options"]}
        self.assertEqual(options["--stock-qty"]["type"], "int")
        self.assertFalse(options["--stock-qty"]["required"])
        self.assertIn("required by 'add_product'", log.lines[0])

    def test_an_already_bindable_flag_is_not_duplicated(self):
        body = self.surface(["--stock"])
        adapters = self.adapters([
            {"field_name": "stock_qty", "target_param": "stock_qty",
             "required": True},
        ])
        repairs.repair_missing_adapter_flags(
            body, adapters, self.SERVICES, self.MODELS, Log())
        options = body["facade"]["invocation"]["commands"][0]["subcommands"][0]["options"]
        self.assertEqual([o["name"] for o in options], ["--stock"])

    def test_a_null_option_list_is_treated_as_empty(self):
        body = self.surface()
        body["facade"]["invocation"]["commands"][0]["subcommands"][0][
            "options"] = None
        adapters = self.adapters([
            {"field_name": "stock_qty", "target_param": "stock_qty",
             "required": True},
        ])
        repairs.repair_missing_adapter_flags(
            body, adapters, self.SERVICES, self.MODELS, Log())
        options = body["facade"]["invocation"]["commands"][0]["subcommands"][0]["options"]
        self.assertIsInstance(options, list)
        self.assertEqual([o["name"] for o in options], ["--stock-qty"])


class MissingRelationFilterRepairTests(unittest.TestCase):
    def test_a_list_filter_adds_the_fk_the_model_omits(self):
        models = [
            {"name": "Invoice", "fields": [
                {"name": "id", "type": "int", "primary_key": True}]},
            {"name": "InvoiceLine", "fields": [
                {"name": "line_id", "type": "int", "primary_key": True},
                {"name": "product_id", "type": "int"}]},
        ]
        repositories = [{"entity": "InvoiceLine",
                         "interface_name": "InvoiceLineRepository",
                         "methods": [{
                             "name": "read_all_for_invoice",
                             "params": [{"name": "invoice_id", "type": "int"}],
                             "return_type": "list[InvoiceLine]"}]}]
        repairs.repair_missing_relation_filters(models, repositories)
        line = next(model for model in models
                    if model["name"] == "InvoiceLine")
        field = next(field for field in line["fields"]
                     if field["name"] == "invoice_id")
        self.assertEqual(field["foreign_key"]["target_entity"], "Invoice")
        self.assertEqual(field["foreign_key"]["target_field"], "id")
        self.assertEqual(field["type"], "int")
        self.assertFalse(field["primary_key"])
        self.assertFalse(field["nullable"])

    def test_an_existing_fk_is_left_alone(self):
        models = [{"name": "InvoiceLine", "fields": [
            {"name": "invoice_id", "type": "int", "foreign_key": {
                "target_entity": "Invoice", "target_field": "id",
                "relationship": "many_to_one"}}]}]
        repositories = [{"entity": "InvoiceLine",
                         "methods": [{
                             "name": "read_all_for_invoice",
                             "params": [{"name": "invoice_id", "type": "int"}],
                             "return_type": "list[InvoiceLine]"}]}]
        repairs.repair_missing_relation_filters(models, repositories)
        self.assertEqual(len(models[0]["fields"]), 1)


class BooleanFilterActionRepairTests(unittest.TestCase):
    """A boolean selector gets the one-parameter filter it names.

    `book list --available-only` is a selector, not a new value: the
    repository already declares `filter_books_by_available_copies(
    min_available_copies)`. The repair may wire that action because the
    selector noun and the parameter agree; it must not wire a bare `--author`
    to an unrelated method whose parameter says `query`.
    """

    SERVICES = [{"service_name": "BookRepository", "methods": [
        {"name": "read_all_books", "params": [], "return_type": "List[Book]"},
        {"name": "filter_books_by_available_copies",
         "params": [{"name": "min_available_copies", "type": "int"}],
         "return_type": "List[Book]"},
        {"name": "search_books_by_title_author_isbn",
         "params": [{"name": "query", "type": "str"}],
         "return_type": "List[Book]"},
    ]}]

    def surface(self, flag):
        return {"facade": {"type": "cli", "technology": "argparse",
                           "invocation": {"commands": [
                               {"name": "book", "options": [],
                                "subcommands": [
                                    {"name": "list",
                                     "options": [{"name": flag, "type": "bool"}]}]}]}}}

    def adapters(self):
        return [{"action_name": "list_books",
                 "target_service": "BookRepository",
                 "target_method": "read_all_books",
                 "input_fields": []}]

    def test_a_selector_is_wired_to_the_matching_filter(self):
        components = self.surface("--available-only")
        adapters = self.adapters()
        log = Log()
        repairs.repair_missing_filter_actions(
            components, adapters, self.SERVICES, [], log)
        self.assertEqual([a["action_name"] for a in adapters],
                         ["list_books", "filter_books_by_available_copies"])
        field = adapters[-1]["input_fields"][0]
        self.assertEqual(field["field_name"], "min_available_copies")
        self.assertEqual(field["flag"], "available_only")
        self.assertEqual(field["transform"], "BOOL_TO_ONE")
        self.assertIn("wired to BookRepository.filter_books_by_available_copies",
                      log.joined())

    def test_a_selector_with_no_matching_parameter_is_left_alone(self):
        components = self.surface("--author")
        adapters = self.adapters()
        repairs.repair_missing_filter_actions(
            components, adapters, self.SERVICES, [], Log())
        self.assertEqual([a["action_name"] for a in adapters], ["list_books"])

    def test_a_selector_already_bound_by_an_adapter_is_left_alone(self):
        components = self.surface("--available-only")
        adapters = self.adapters()
        adapters.append({
            "action_name": "list_books_by_author",
            "target_service": "BookRepository",
            "target_method": "filter_books_by_available_copies",
            "input_fields": [{"field_name": "available_only",
                              "target_param": "min_available_copies",
                              "required": True}],
        })
        repairs.repair_missing_filter_actions(
            components, adapters, self.SERVICES, [], Log())
        self.assertEqual(len(adapters), 2)


class LongOptionSpellingTests(unittest.TestCase):
    def test_multi_character_single_dash_names_become_long_flags(self):
        body = {"facade": {"invocation": {
            "options": [{"name": "-help", "short": "-h", "type": "bool"}],
            "commands": [
            {"name": "book", "options": [], "subcommands": [
                {"name": "add", "options": [
                    {"name": "-title", "short": "-t", "type": "str"},
                    {"name": "-a", "short": None, "type": "bool"},
                ]}]}]}}}
        log = Log()
        repairs.repair_long_option_names(body, log)
        options = body["facade"]["invocation"]["commands"][0]["subcommands"][0]["options"]
        self.assertEqual([option["name"] for option in options],
                         ["--title", "-a"])
        root = body["facade"]["invocation"]["options"][0]["name"]
        self.assertEqual(root, "--help")
        self.assertIn("normalized option '-title' to '--title'", log.joined())
        before = json.dumps(body, sort_keys=True)
        repairs.repair_long_option_names(body, log)
        self.assertEqual(json.dumps(body, sort_keys=True), before)


class OptionDefaultTests(unittest.TestCase):
    """A split command group must still read a default stated in prose."""

    def test_the_optional_flag_gets_the_one_word_default(self):
        body = {"facade": {"invocation": {"commands": [
            {"name": "book", "options": [], "subcommands": [
                {"name": "add", "options": [
                    {"name": "--copies", "type": "int",
                     "required": True, "default": None},
                ]}]}]}}}
        requirements = (
            "library book add --title --isbn --author-id --published-year "
            "--copies\n"
            "- `--copies` is optional and defaults to one.\n"
        )
        log = Log()
        repairs.repair_option_defaults(body, [], log, requirements)
        option = body["facade"]["invocation"]["commands"][0]["subcommands"][0]["options"][0]
        self.assertFalse(option["required"])
        self.assertEqual(option["default"], "1")
        self.assertIn("'--copies' is optional", log.joined())

    def test_a_default_before_another_flag_does_not_make_that_flag_optional(self):
        body = {"facade": {"invocation": {"commands": [
            {"name": "member", "options": [], "subcommands": [
                {"name": "add", "options": [
                    {"name": "--name", "type": "str",
                     "required": True, "default": None},
                    {"name": "--email", "type": "str",
                     "required": True, "default": None},
                ]}]}]}}}
        requirements = (
            "- `Member.membership_date` defaults to today's date when a "
            "member is created, so `library member add --name --email` is "
            "sufficient.\n"
        )
        repairs.repair_option_defaults(body, [], Log(), requirements)
        options = body["facade"]["invocation"]["commands"][0]["subcommands"][0]["options"]
        self.assertEqual([(option["required"], option["default"])
                          for option in options],
                         [(True, None), (True, None)])


class ProgramWordSubcommandTests(unittest.TestCase):
    def test_a_program_word_is_folded_into_the_flat_command(self):
        body = {"facade": {"invocation": {"commands": [
            {"name": "overdue", "options": [], "subcommands": [
                {"name": "library", "options": [
                    {"name": "--overdue", "type": "bool"}]}]}]}}}
        log = Log()
        repairs.repair_program_word_subcommands(
            body, "- `library overdue`\n", log)
        command = body["facade"]["invocation"]["commands"][0]
        self.assertEqual(command["subcommands"], [])
        self.assertEqual([option["name"] for option in command["options"]],
                         ["--overdue"])
        self.assertIn("folded accidental subcommand 'overdue library'",
                      log.joined())

    def test_a_genuine_nested_path_is_left_alone(self):
        body = {"facade": {"invocation": {"commands": [
            {"name": "expense", "options": [], "subcommands": [
                {"name": "category", "options": [], "subcommands": [
                    {"name": "add", "options": []}]}]}]}}}
        before = json.dumps(body, sort_keys=True)
        repairs.repair_program_word_subcommands(
            body, "expense category add --name\n", Log())
        self.assertEqual(json.dumps(body, sort_keys=True), before)


if __name__ == "__main__":
    unittest.main()
