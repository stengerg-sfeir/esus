"""The rules that compare a document with what the requirements asked for.

Most judge a document against another document or against a name it states
itself; `missing_command` reads the requirements prose, and `unbacked_command`
reads the methods — a command the surface declares and no service implements.
Each test pins a decision, and — where a rule deliberately stays silent — pins
that silence too, because a rule that fires on a correct document is worse than
no rule.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.consistency.checks_adapters import (  # noqa: E402
    _check_target_param,
    _check_transform_fits_the_field,
)
from kernel.consistency.checks_errors import (  # noqa: E402
    check_duplicate_error_subject,
    check_unreachable_not_found,
)
from kernel.consistency.checks_surface import (  # noqa: E402
    check_command_backing,
    check_flag_coverage,
    check_surface_coverage,
)
from kernel.consistency.report import Report  # noqa: E402
from kernel.extraction import grammar_open  # noqa: E402


def rules(report):
    return [finding.rule for finding in report.findings]


def field(name, target, transform="DIRECT"):
    return {"field_name": name, "target_param": target, "transform": transform}


def surface(commands, positional=None, options=None):
    """A whole components document, because the check reads `components.facade`."""
    return {
        "facade": {
            "type": "cli",
            "technology": "click",
            "invocation": {
                "positional": positional or [],
                "options": options or [],
                "commands": commands,
            },
        }
    }


def command(name, subcommands=(), options=()):
    return {
        "name": name,
        "options": [{"name": option, "type": "bool"} for option in options],
        "subcommands": [{"name": sub, "options": []} for sub in subcommands],
    }


class MissingCommandTests(unittest.TestCase):
    def test_a_subcommand_the_requirements_name_is_reported(self):
        report = Report("t")
        components = surface([command("category", subcommands=["list"])])
        check_surface_coverage(components, "Use it as `category add --name` to add.", report)
        self.assertIn("missing_command", rules(report))

    def test_a_present_subcommand_is_not_reported(self):
        report = Report("t")
        components = surface([command("category", subcommands=["add"])])
        check_surface_coverage(components, "Use it as `category add --name` to add.", report)
        self.assertEqual(rules(report), [])

    def test_the_program_name_before_a_verb_is_not_reported(self):
        """`library borrow book` names the tool, not a command, so nothing is missing."""
        report = Report("t")
        components = surface([command("borrow", subcommands=["book"])])
        check_surface_coverage(components, "Run `library borrow book --id 3`.", report)
        self.assertEqual(rules(report), [])

    def test_a_null_invocation_is_not_reported(self):
        report = Report("t")
        components = {"type": "cli", "technology": "none", "invocation": None}
        check_surface_coverage(components, "Run `tool thing --flag`.", report)
        self.assertEqual(rules(report), [])

    def test_no_requirements_means_no_check(self):
        report = Report("t")
        components = surface([command("category")])
        check_surface_coverage(components, None, report)
        self.assertEqual(rules(report), [])


class CommandShapeTests(unittest.TestCase):
    """The command shape that makes `-add` beside subcommand `add` unrepresentable.

    Two prompt sentences failed to stop the collision, so it is closed in the
    grammar instead. These tests pin the closure structurally, which is all that
    can be checked without a model: the branch that admits subcommands and the
    branch that admits any option are different rules, so no single command can be
    built with both.
    """

    def grammar_text(self):
        """`components()` already returns the grammar document as one string."""
        return grammar_open.components()

    def line(self, prefix):
        return next(
            text for text in self.grammar_text().splitlines() if text.startswith(prefix)
        )

    def test_a_command_with_subcommands_admits_only_global_options(self):
        nested = self.line("cli-command-nested ::=")
        self.assertIn("cli-global-option-list", nested)
        self.assertNotIn("cli-option-list", nested)

    def test_a_command_without_subcommands_admits_any_option(self):
        flat = self.line("cli-command-flat ::=")
        self.assertIn("cli-option-list", flat)
        self.assertIn('"[" ws "]"', flat)

    def test_the_two_shapes_are_the_only_commands(self):
        rule_line = self.line("cli-command ::=")
        self.assertIn("cli-command-nested", rule_line)
        self.assertIn("cli-command-flat", rule_line)

    def test_a_global_option_name_is_one_of_four(self):
        rule_line = self.line("global-option-name ::=")
        for name in ("-help", "--help", "-version", "--version"):
            self.assertIn(f'\\"{name}\\"', rule_line)
        self.assertNotIn("add", rule_line)


class MismatchedTransformTests(unittest.TestCase):
    def test_a_count_converted_to_cents_is_reported(self):
        report = Report("t")
        _check_transform_fits_the_field(field("copies", "copies", "DECIMAL_TO_CENTS"), "add_book", "copies", report)
        self.assertIn("mismatched_transform", rules(report))

    def test_a_money_amount_converted_to_cents_is_not_reported(self):
        report = Report("t")
        _check_transform_fits_the_field(
            field("amount_cents", "amount_cents", "DECIMAL_TO_CENTS"), "add_expense", "amount_cents", report
        )
        self.assertEqual(rules(report), [])

    def test_a_single_name_read_as_a_list_is_reported(self):
        report = Report("t")
        _check_transform_fits_the_field(field("name", "name", "CSV_LIST"), "add_category", "name", report)
        self.assertIn("mismatched_transform", rules(report))

    def test_a_list_field_read_as_a_list_is_not_reported(self):
        report = Report("t")
        _check_transform_fits_the_field(
            field("tag_ids", "tag_ids", "CSV_LIST"), "add_book", "tag_ids", report
        )
        self.assertEqual(rules(report), [])

    def test_a_date_field_parsed_as_a_date_is_not_reported(self):
        report = Report("t")
        _check_transform_fits_the_field(
            field("expense_date", "expense_date", "ISO_DATE"), "add_expense", "expense_date", report
        )
        self.assertEqual(rules(report), [])

    def test_a_direct_transform_is_never_judged(self):
        report = Report("t")
        _check_transform_fits_the_field(field("anything", "anything", "DIRECT"), "do_it", "anything", report)
        self.assertEqual(rules(report), [])


class MisplacedFieldTests(unittest.TestCase):
    def test_a_field_sent_past_its_own_parameter_is_reported(self):
        """expenses' `update_budget`: field `month` goes into `budget` while `month` exists."""
        report = Report("t")
        _check_target_param(
            field("month", "budget"), "update_budget", "month",
            {"category_id", "month", "amount_limit_cents"}, report,
        )
        self.assertIn("misplaced_field", rules(report))

    def test_a_field_sent_to_its_own_parameter_is_not_reported(self):
        report = Report("t")
        _check_target_param(
            field("category_id", "category_id"), "add_expense", "category_id",
            {"expense", "category_id"}, report,
        )
        self.assertEqual(rules(report), [])

    def test_a_field_with_no_parameter_of_its_own_is_not_reported(self):
        """Description folded into an aggregate parameter has no same-named one to prefer."""
        report = Report("t")
        _check_target_param(
            field("description", "expense"), "add_expense", "description",
            {"expense", "category_id"}, report,
        )
        self.assertEqual(rules(report), [])


class UnreachableErrorTests(unittest.TestCase):
    def test_an_unraised_not_found_error_with_a_reader_is_reported(self):
        report = Report("t")
        services = [
            {
                "service_name": "ProductRepository",
                "methods": [{"name": "get_product_by_id", "raises": []}],
            }
        ]
        check_unreachable_not_found([{"name": "MissingProductError"}], services, ("MissingProductError",), report)
        self.assertIn("unreachable_error", rules(report))

    def test_a_not_found_error_the_reader_raises_is_not_reported(self):
        report = Report("t")
        services = [
            {
                "service_name": "ProductRepository",
                "methods": [{"name": "get_product_by_id", "raises": ["MissingProductError"]}],
            }
        ]
        check_unreachable_not_found([{"name": "MissingProductError"}], services, ("MissingProductError",), report)
        self.assertEqual(rules(report), [])

    def test_an_error_whose_subject_nothing_reads_is_not_reported(self):
        """`MalformedCSVError` belongs to a layer the checker does not model."""
        report = Report("t")
        services = [{"service_name": "FileService", "methods": [{"name": "load_file", "raises": []}]}]
        check_unreachable_not_found([{"name": "MalformedCSVError"}], services, ("MalformedCSVError",), report)
        self.assertEqual(rules(report), [])

    def test_no_services_means_no_check(self):
        report = Report("t")
        check_unreachable_not_found([{"name": "MissingProductError"}], [], ("MissingProductError",), report)
        self.assertEqual(rules(report), [])


class DuplicateErrorSubjectTests(unittest.TestCase):
    def test_two_names_for_one_missing_record_are_reported(self):
        report = Report("t")
        names = ("CategoryNotFoundError", "MissingCategoryError")
        check_duplicate_error_subject([{"name": name} for name in names], names, report)
        self.assertIn("duplicate_error_subject", rules(report))

    def test_one_name_per_missing_record_is_not_reported(self):
        report = Report("t")
        names = ("CategoryNotFoundError", "ProductNotFoundError")
        check_duplicate_error_subject([{"name": name} for name in names], names, report)
        self.assertEqual(rules(report), [])


class MisfiledCommandGroupTests(unittest.TestCase):
    """A noun the requirements act on belongs on top, not nested elsewhere.

    Library files `member` under `book` while the requirements use it with
    add, history and list: three verbs, so it is a command of its own that
    was misfiled — not a covered subcommand. A single stray verb filed
    elsewhere (`report monthly`) stays silent.
    """

    def commands(self, entries):
        return surface([command(name, subcommands=subs) for name, subs in entries])

    def test_a_noun_with_several_verbs_filed_elsewhere_is_reported(self):
        report = Report("t")
        components = self.commands([("book", ["add", "member", "history"])])
        check_surface_coverage(
            components,
            "Run `library member add --name`, `library member history --id`, "
            "`library member list`.",
            report)
        self.assertIn("missing_command", rules(report))

    def test_a_single_verb_filed_elsewhere_is_not_reported(self):
        report = Report("t")
        components = self.commands([("expense", ["report"])])
        check_surface_coverage(
            components, "Run `expense report monthly --month`.", report)
        self.assertEqual(rules(report), [])


class MisfiledValuesTests(unittest.TestCase):
    """Selectors behind a filed subcommand are values, not verbs.

    `expense report monthly --month` and `expense report yearly --year` give
    `report` two words that name no action — monthly/yearly select which
    report, so the filed `report` subcommand stands and nothing is missing.
    """

    def test_two_selectors_behind_a_filed_subcommand_are_silent(self):
        report = Report("t")
        components = surface([command("expense", subcommands=["report"])])
        check_surface_coverage(
            components,
            "Run `expense report monthly --month` and `expense report yearly --year`.",
            report)
        self.assertEqual(rules(report), [])


class TopLevelCommandTests(unittest.TestCase):
    """A program-led line with one verb makes that verb a command.

    The pair rule needs two words before a flag, so `library borrow
    --member-id` was invisible when `borrow` vanished: no missing command
    (the noun is the program), no unbacked command (undeclared verbs resolve
    against nothing). The leading word is tested structurally — inventory's
    program-less `product add --sku` must not read `product` as a program.
    """

    def surface(self, names):
        return {
            "facade": {
                "type": "cli",
                "technology": "click",
                "invocation": {"positional": [], "options": [],
                               "commands": [{"name": name, "options": [],
                                             "subcommands": []} for name in names]},
            }
        }

    def test_a_vanished_top_level_verb_is_reported(self):
        report = Report("t")
        check_surface_coverage(
            self.surface(["book"]), "Run `library borrow --member-id --book-id`.",
            report)
        self.assertIn("missing_command", rules(report))

    def test_a_present_top_level_verb_is_not_reported(self):
        report = Report("t")
        check_surface_coverage(
            self.surface(["book", "borrow"]), "Run `library borrow --member-id`.",
            report)
        self.assertEqual(rules(report), [])

    def test_a_programless_noun_is_not_mistaken_for_a_program(self):
        """Inventory writes `product add --sku` with no program word at all:
        `product` names a command, so the line is judged by the pair rule
        (whose verb is satisfied here), never as a program-led line."""
        report = Report("t")
        components = {
            "facade": {
                "type": "cli",
                "technology": "click",
                "invocation": {"positional": [], "options": [],
                               "commands": [
                                   {"name": "product", "options": [],
                                    "subcommands": [{"name": "add",
                                                     "options": []}]},
                                   {"name": "category", "options": [],
                                    "subcommands": []}]},
            }
        }
        check_surface_coverage(
            components, "Run `product add --sku`.", report)
        self.assertEqual(rules(report), [])

    def test_a_bare_line_with_no_flags_is_not_reported(self):
        report = Report("t")
        check_surface_coverage(self.surface(["book"]), "Run `library overdue`.",
                               report)
        self.assertEqual(rules(report), [])


class UnbackedCommandTests(unittest.TestCase):
    """A command the surface declares and no service method can implement.

    The second half of the surface check: `missing_command` compares the surface
    with the requirements, this compares it with the methods. A generator cannot
    write a call no method serves, and nothing else in the checker can see it.
    """

    def services(self, *method_names):
        return [
            {
                "service_name": "OrderService",
                "methods": [{"name": name, "description": name, "params": [], "return_type": "void"} for name in method_names],
            }
        ]

    def test_a_verb_no_method_serves_is_reported(self):
        report = Report("t")
        components = surface([command("order", subcommands=["confirm"])])
        check_command_backing(components, self.services("create_order", "cancel_order"), report)
        self.assertIn("unbacked_command", rules(report))

    def test_a_verb_served_by_a_synonym_is_not_reported(self):
        """`book add` is implemented by `create_book`; the rename is the generator's."""
        report = Report("t")
        components = surface([command("book", subcommands=["add", "list"])])
        check_command_backing(components, self.services("create_book", "read_all_books"), report)
        self.assertEqual(rules(report), [])

    def test_a_search_verb_is_served_by_a_search_method(self):
        report = Report("t")
        components = surface([command("order", subcommands=["search"])])
        check_command_backing(components, self.services("search_orders_by_customer_id"), report)
        self.assertEqual(rules(report), [])

    def test_a_null_invocation_is_not_reported(self):
        report = Report("t")
        components = {"facade": {"type": "cli", "technology": "none", "invocation": None}}
        check_command_backing(components, self.services("create_order"), report)
        self.assertEqual(rules(report), [])

    def test_no_services_means_no_check(self):
        report = Report("t")
        components = surface([command("order", subcommands=["confirm"])])
        check_command_backing(components, [], report)
        self.assertEqual(rules(report), [])

    def test_an_extra_service_does_not_hide_a_missing_one(self):
        report = Report("t")
        components = surface([command("invoice", subcommands=["confirm"])])
        check_command_backing(components, self.services("cancel_order"), report)
        self.assertIn("unbacked_command", rules(report))


class MissingFlagTests(unittest.TestCase):
    """A flag the requirements pass and the surface cannot accept.

    The flag-level half of the surface check: `missing_command` compares
    verbs, this compares the flags behind them. A verb the surface declares
    with none of its data flags parses and then can never run.
    """

    def leaf(self, options):
        return [{"name": name, "type": "str"} for name in options]

    def surface(self, leaves):
        """`leaves`: `{command: {subcommand_or_None: [option names]}}`."""
        commands = []
        for name, subs in leaves.items():
            commands.append({
                "name": name,
                "options": self.leaf(subs.get(None, [])),
                "subcommands": [
                    {"name": sub, "options": self.leaf(options)}
                    for sub, options in subs.items() if sub is not None
                ],
            })
        return {
            "facade": {
                "type": "cli",
                "technology": "click",
                "invocation": {"positional": [], "options": [], "commands": commands},
            }
        }

    def test_a_required_flag_the_leaf_lacks_is_reported(self):
        report = Report("t")
        components = self.surface({"product": {"add": ["name"]}})
        check_flag_coverage(components, "Run `product add --sku --name`.", report)
        self.assertIn("missing_flag", rules(report))
        self.assertTrue(report.warnings)

    def test_a_present_flag_is_not_reported(self):
        report = Report("t")
        components = self.surface({"product": {"add": ["sku", "name"]}})
        check_flag_coverage(components, "Run `product add --sku --name`.", report)
        self.assertEqual(rules(report), [])

    def test_a_bracketed_optional_flag_is_a_note_not_a_warning(self):
        """The generator can omit an optional; it cannot conjure a required value."""
        report = Report("t")
        components = self.surface({"product": {"add": ["name"]}})
        check_flag_coverage(components, "Run `product add --name [--icon]`.", report)
        self.assertIn("missing_flag", rules(report))
        self.assertFalse(report.warnings)

    def test_an_abbreviated_flag_satisfies_its_field(self):
        report = Report("t")
        components = self.surface({"expense": {"add": ["category"]}})
        check_flag_coverage(components, "Run `expense add --category-id`.", report)
        self.assertEqual(rules(report), [])

    def test_a_date_alias_satisfies_its_field(self):
        report = Report("t")
        components = self.surface({"expense": {"list": ["from-date"]}})
        check_flag_coverage(components, "Run `expense list --start-date`.", report)
        self.assertEqual(rules(report), [])

    def test_a_bare_command_reads_its_subcommands_flags(self):
        """`library borrow --member-id` files its flags under `book`."""
        report = Report("t")
        components = self.surface({"borrow": {"book": ["member-id", "book-id"]}})
        check_flag_coverage(
            components, "Run `library borrow --member-id --book-id`.", report)
        self.assertEqual(rules(report), [])

    def test_a_subcommand_written_first_resolves_to_its_owner(self):
        report = Report("t")
        components = self.surface({"expense": {"report": ["month"]}})
        check_flag_coverage(components, "Run `expense report monthly --month`.", report)
        self.assertEqual(rules(report), [])

    def test_a_subcommand_written_first_reports_its_miss(self):
        report = Report("t")
        components = self.surface({"expense": {"report": []}})
        check_flag_coverage(components, "Run `expense report monthly --month`.", report)
        self.assertIn("missing_flag", rules(report))

    def test_a_non_command_span_is_not_reported(self):
        report = Report("t")
        components = self.surface({"product": {"add": []}})
        check_flag_coverage(components, "With `UNIQUE(category_id, month)`.", report)
        self.assertEqual(rules(report), [])

    def test_an_unknown_command_span_is_not_reported(self):
        report = Report("t")
        components = self.surface({"product": {"add": []}})
        check_flag_coverage(components, "Run `frobnicate widget --x`.", report)
        self.assertEqual(rules(report), [])

    def test_a_repeated_line_is_reported_once(self):
        report = Report("t")
        components = self.surface({"product": {"add": []}})
        check_flag_coverage(
            components, "Run `product add --sku` or `product add --sku`.", report)
        self.assertEqual(len(report.warnings), 1)

    def test_no_requirements_means_no_check(self):
        report = Report("t")
        components = self.surface({"product": {"add": []}})
        check_flag_coverage(components, None, report)
        self.assertEqual(rules(report), [])

    def test_a_null_invocation_is_not_reported(self):
        report = Report("t")
        components = {"facade": {"type": "cli", "technology": "none", "invocation": None}}
        check_flag_coverage(components, "Run `product add --sku`.", report)
        self.assertEqual(rules(report), [])


class ProgramlessSpanTests(unittest.TestCase):
    """Lines with no program word resolve as written.

    Inventory writes `` `product add --sku` `` — no program name — so the
    program guess eats `product` and the remainder (`add`, in two commands'
    lists) resolves to nothing. The full tokens are therefore tried too.
    """

    def surface(self, leaves):
        commands = []
        for name, subs in leaves.items():
            commands.append({
                "name": name,
                "options": [],
                "subcommands": [
                    {"name": sub, "options": [{"name": o, "type": "str"} for o in options]}
                    for sub, options in subs.items()
                ],
            })
        return {
            "facade": {
                "type": "cli",
                "technology": "click",
                "invocation": {"positional": [], "options": [], "commands": commands},
            }
        }

    def test_a_programless_line_checks_its_flags(self):
        report = Report("t")
        components = self.surface({"product": {"add": ["name"]},
                                   "category": {"add": ["name"]}})
        check_flag_coverage(components, "Run `product add --sku --name`.", report)
        self.assertIn("missing_flag", rules(report))

    def test_a_program_word_plus_an_unknown_word_is_skipped(self):
        """`expense frobnicate --x` must not become a flag check on bare `expense`."""
        report = Report("t")
        components = self.surface({"expense": {"add": ["amount"]}})
        check_flag_coverage(components, "Run `expense frobnicate --x`.", report)
        self.assertEqual(rules(report), [])


if __name__ == "__main__":
    unittest.main()
