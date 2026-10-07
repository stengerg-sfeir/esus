"""The five rules that compare a document with what the requirements asked for.

Four of them judge a document against another document or against a name it
states itself; the fifth (`missing_command`) is the only rule in the checker that
reads the requirements prose. Each test pins a decision, and — where a rule
deliberately stays silent — pins that silence too, because a rule that fires on a
correct document is worse than no rule.
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
from kernel.consistency.checks_surface import check_surface_coverage  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
