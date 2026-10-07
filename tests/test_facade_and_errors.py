"""The CLI surface, the error registry, and the `raises` reference between them.

Two contracts were added because a generator needs what they record: what a
program accepts on its command line, and what it raises when it fails. Each test
below pins a decision, and — where a rule deliberately stays silent — pins that
silence too.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.consistency.checks_components import _check_facade  # noqa: E402
from kernel.consistency.checks_errors import check_errors, check_raises  # noqa: E402
from kernel.consistency.report import Report  # noqa: E402
from kernel.extraction import grammar_check, grammar_open  # noqa: E402


def facade(**overrides):
    value = {"type": "cli", "technology": "argparse", "invocation": None}
    value.update(overrides)
    return value


def rules(report):
    return [finding.rule for finding in report.findings]


class FacadeTests(unittest.TestCase):
    def test_a_parser_with_no_arguments_is_reported(self):
        """The hello-world defect: `argparse` declared for a script taking nothing."""
        report = Report("t")
        _check_facade(facade(technology="argparse", invocation=None), report)
        self.assertIn("inconsistent_facade", rules(report))

    def test_a_parser_with_arguments_is_not_reported(self):
        report = Report("t")
        _check_facade(
            facade(
                technology="argparse",
                invocation={"positional": [{"name": "path"}], "options": [], "commands": []},
            ),
            report,
        )
        self.assertNotIn("inconsistent_facade", rules(report))

    def test_an_argument_list_with_no_technology_is_reported(self):
        report = Report("t")
        _check_facade(
            facade(
                technology="none",
                invocation={
                    "positional": [],
                    "options": [{"name": "--out"}],
                    "commands": [],
                },
            ),
            report,
        )
        self.assertIn("inconsistent_facade", rules(report))

    def test_a_document_without_an_invocation_key_is_not_reported(self):
        """A document from before the surface existed cannot be judged on it."""
        report = Report("t")
        _check_facade({"type": "cli", "technology": "argparse"}, report)
        self.assertNotIn("inconsistent_facade", rules(report))

    def test_no_arguments_and_no_parser_is_consistent(self):
        report = Report("t")
        _check_facade(facade(technology="none", invocation=None), report)
        self.assertNotIn("inconsistent_facade", rules(report))

    def test_a_cli_with_technology_none_is_not_a_placeholder(self):
        """Caught in the field: making `none` the right answer for a program with
        no arguments turned it into a warning, because the placeholder test had
        always counted the string as unfilled. It is a value now."""
        report = Report("t")
        _check_facade(facade(technology="none", invocation=None), report)
        self.assertEqual(rules(report), [], "`none` is a legitimate technology, not junk")

    def test_a_technology_placeholder_is_still_reported(self):
        """Relaxing `none` must not stop catching what a model leaves behind."""
        report = Report("t")
        _check_facade(facade(technology="undefined", invocation=None), report)
        self.assertIn("invalid_value", rules(report))


def surface(**parts):
    value = {"positional": [], "options": [], "commands": []}
    value.update(parts)
    return value


class CliSurfaceTests(unittest.TestCase):
    """The shape of the surface itself, which the first run got wrong twice."""

    def test_a_verb_recorded_as_an_option_is_reported(self):
        """inventory: `category update --id` became an option `-update` of type dict."""
        report = Report("t")
        _check_facade(
            facade(
                technology="click",
                invocation=surface(
                    commands=[
                        {
                            "name": "category",
                            "options": [{"name": "-update", "type": "dict"}],
                            "subcommands": [],
                        }
                    ]
                ),
            ),
            report,
        )
        self.assertIn("unsupported_value", rules(report))

    def test_a_list_typed_option_is_not_reported(self):
        """`--fields name price` is legitimate, and the grammar names it `list`."""
        report = Report("t")
        _check_facade(
            facade(
                technology="argparse",
                invocation=surface(
                    options=[{"name": "--fields", "type": "list"}],
                    positional=[{"name": "p", "type": "str"}],
                ),
            ),
            report,
        )
        self.assertEqual(rules(report), [])

    def test_an_unknown_option_type_is_reported(self):
        """The set is the grammar's, so anything outside it is not a CLI value."""
        report = Report("t")
        _check_facade(
            facade(
                technology="argparse",
                invocation=surface(
                    options=[{"name": "--ratio", "type": "ratio"}],
                    positional=[{"name": "p", "type": "str"}],
                ),
            ),
            report,
        )
        self.assertIn("unsupported_value", rules(report))

    def test_an_unknown_positional_type_is_reported(self):
        report = Report("t")
        _check_facade(
            facade(
                technology="argparse",
                invocation=surface(positional=[{"name": "p", "type": "dict"}]),
            ),
            report,
        )
        self.assertIn("unsupported_value", rules(report))

    def test_a_repeated_command_name_is_reported(self):
        """library lists `member` twice, once with [add, list] and once with [history]."""
        report = Report("t")
        _check_facade(
            facade(
                technology="click",
                invocation=surface(
                    commands=[
                        {"name": "member", "options": [], "subcommands": [{"name": "add", "options": []}]},
                        {"name": "Member", "options": [], "subcommands": [{"name": "history", "options": []}]},
                    ]
                ),
            ),
            report,
        )
        self.assertIn("duplicate_entry", rules(report))

    def test_a_repeated_subcommand_name_is_reported(self):
        report = Report("t")
        _check_facade(
            facade(
                technology="click",
                invocation=surface(
                    commands=[
                        {
                            "name": "product",
                            "options": [],
                            "subcommands": [{"name": "list", "options": []}, {"name": "list", "options": []}],
                        }
                    ]
                ),
            ),
            report,
        )
        self.assertIn("duplicate_entry", rules(report))

    def test_a_verb_kept_as_an_option_is_reported(self):
        """inventory after the noun/verb fix: `product` has subcommand `add` *and* option `-add`.

        `tool product add --sku` and `tool product -add` cannot both be how a
        product is added.
        """
        report = Report("t")
        _check_facade(
            facade(
                technology="click",
                invocation=surface(
                    commands=[
                        {
                            "name": "product",
                            "options": [{"name": "-add", "type": "str"}, {"name": "--verbose", "type": "bool"}],
                            "subcommands": [{"name": "add", "options": []}, {"name": "list", "options": []}],
                        }
                    ]
                ),
            ),
            report,
        )
        self.assertIn("invalid_value", rules(report))

    def test_an_option_unrelated_to_a_subcommand_is_not_reported(self):
        report = Report("t")
        _check_facade(
            facade(
                technology="click",
                invocation=surface(
                    commands=[
                        {
                            "name": "product",
                            "options": [{"name": "--verbose", "type": "bool"}],
                            "subcommands": [{"name": "add", "options": []}],
                        }
                    ]
                ),
            ),
            report,
        )
        self.assertEqual(rules(report), [])

    def test_a_repeated_option_name_is_reported_once_per_list(self):
        report = Report("t")
        _check_facade(
            facade(
                technology="click",
                invocation=surface(
                    options=[{"name": "--out", "type": "str"}, {"name": "--out", "type": "str"}],
                    positional=[{"name": "p"}],
                ),
            ),
            report,
        )
        self.assertIn("duplicate_entry", rules(report))

    def test_the_correct_shape_is_accepted(self):
        """expenses got it right: the noun is the command, the verb a subcommand."""
        report = Report("t")
        _check_facade(
            facade(
                technology="click",
                invocation=surface(
                    commands=[
                        {
                            "name": "category",
                            "options": [],
                            "subcommands": [
                                {"name": "add", "options": [{"name": "--name", "type": "str"}]},
                                {"name": "list", "options": []},
                            ],
                        }
                    ]
                ),
            ),
            report,
        )
        self.assertEqual(rules(report), [])


class ErrorRegistryTests(unittest.TestCase):
    def test_a_well_formed_registry_reports_nothing_and_returns_its_names(self):
        report = Report("t")
        names = check_errors(
            [
                {"name": "CategoryNotFoundError", "base": "LookupError", "description": "x"},
                {"name": "MalformedCsvError", "base": "ValueError", "description": "y"},
            ],
            report,
        )
        self.assertEqual(rules(report), [])
        self.assertEqual(names, ("CategoryNotFoundError", "MalformedCsvError"))

    def test_a_bad_base_is_reported(self):
        report = Report("t")
        check_errors([{"name": "OopsError", "base": "SomethingMadeUp", "description": "x"}], report)
        self.assertIn("unsupported_value", rules(report))

    def test_a_missing_name_is_an_error(self):
        report = Report("t")
        check_errors([{"base": "ValueError", "description": "x"}], report)
        self.assertIn("invalid_identifier", rules(report))

    def test_a_duplicate_name_is_reported(self):
        report = Report("t")
        check_errors(
            [
                {"name": "OopsError", "base": "ValueError", "description": "x"},
                {"name": "oopserror", "base": "ValueError", "description": "y"},
            ],
            report,
        )
        self.assertIn("duplicate_entry", rules(report))

    def test_an_empty_registry_is_valid(self):
        report = Report("t")
        self.assertEqual(check_errors([], report), ())
        self.assertEqual(rules(report), [])

    def test_a_non_list_registry_is_an_error(self):
        report = Report("t")
        check_errors({"errors": []}, report)
        self.assertIn("invalid_value", rules(report))

    def test_an_absent_registry_is_silent(self):
        """Caught in the field: a missing file was reported twice, once as a
        missing document and once as a wrong type. The loader owns the absence."""
        report = Report("t")
        check_errors(None, report)
        self.assertEqual(rules(report), [], "an absent registry must not be a type error")


def service(name, method, raises):
    return {"service_name": name, "methods": [{"name": method, "raises": raises}]}


class RaisesTests(unittest.TestCase):
    def test_a_raise_of_a_registered_error_is_accepted(self):
        report = Report("t")
        check_raises(
            [service("CategoryRepository", "get_category_by_id", ["CategoryNotFoundError"])],
            ("CategoryNotFoundError",),
            report,
        )
        self.assertEqual(rules(report), [])

    def test_a_raise_of_an_unregistered_error_is_reported(self):
        report = Report("t")
        check_raises(
            [service("CategoryRepository", "get_category_by_id", ["MadeUpError"])],
            ("CategoryNotFoundError",),
            report,
        )
        self.assertIn("unknown_reference", rules(report))

    def test_a_declared_error_nothing_raises_is_a_note(self):
        report = Report("t")
        check_raises(
            [service("CategoryRepository", "read_all_categories", [])],
            ("CategoryNotFoundError",),
            report,
        )
        self.assertIn("unused_error", rules(report))
        self.assertEqual(report.counts, (0, 0), "an unused error must not count as a defect")

    def test_unused_errors_are_not_reported_without_services(self):
        """A CSV converter's errors belong to its CLI layer, not to a service."""
        report = Report("t")
        check_raises([], ("MalformedCsvError",), report)
        self.assertNotIn("unused_error", rules(report))

    def test_an_empty_raise_entry_is_reported(self):
        report = Report("t")
        check_raises(
            [service("CategoryRepository", "get_category_by_id", [""])],
            ("CategoryNotFoundError",),
            report,
        )
        self.assertIn("invalid_value", rules(report))

    def test_a_create_raising_not_found_is_reported(self):
        """The inventory case: `create_product` declaring `ProductNotFoundError`.
        A create has no lookup in it, so that error belongs to a different method."""
        report = Report("t")
        check_raises(
            [service("ProductRepository", "create_product", ["ProductNotFoundError"])],
            ("ProductNotFoundError",),
            report,
        )
        self.assertIn("contradictory_raise", rules(report))

    def test_a_read_raising_not_found_is_not_reported(self):
        """The rule must not fire on the method the error actually describes."""
        report = Report("t")
        check_raises(
            [service("ProductRepository", "read_one_product", ["ProductNotFoundError"])],
            ("ProductNotFoundError",),
            report,
        )
        self.assertNotIn("contradictory_raise", rules(report))

    def test_a_create_raising_validation_is_not_reported(self):
        """A create really can fail validation, so only not-found is contradictory."""
        report = Report("t")
        check_raises(
            [service("ProductRepository", "create_product", ["InvalidPriceError"])],
            ("InvalidPriceError",),
            report,
        )
        self.assertNotIn("contradictory_raise", rules(report))

    def test_adding_to_an_existing_record_may_raise_not_found(self):
        """`add` alone is not enough: `add_stock(product_id)` must find the product
        it adds stock to, so its ProductNotFoundError is correct. Only the noun the
        method creates decides."""
        report = Report("t")
        check_raises(
            [service("InventoryService", "add_stock", ["ProductNotFoundError"])],
            ("ProductNotFoundError",),
            report,
        )
        self.assertNotIn("contradictory_raise", rules(report))

    def test_adding_the_thing_itself_is_still_reported(self):
        report = Report("t")
        check_raises(
            [service("InventoryService", "add_product", ["ProductNotFoundError"])],
            ("ProductNotFoundError",),
            report,
        )
        self.assertIn("contradictory_raise", rules(report))

    def test_the_same_error_on_a_different_subject_is_not_reported(self):
        """`create_category` raising ProductNotFoundError is a different mistake —
        a wrong error for the entity, not a contradiction — so this rule stays quiet."""
        report = Report("t")
        check_raises(
            [service("CategoryRepository", "create_category", ["ProductNotFoundError"])],
            ("ProductNotFoundError",),
            report,
        )
        self.assertNotIn("contradictory_raise", rules(report))


class ErrorsGrammarTests(unittest.TestCase):
    def test_the_errors_grammar_is_valid_and_references_its_base_rule(self):
        text = grammar_open.errors()
        grammar_check.assert_valid(text, label="errors")
        self.assertIn("base-error", text)

    def test_the_contracts_grammar_carries_raises(self):
        text = grammar_open.service_contracts()
        grammar_check.assert_valid(text, label="service_contracts")
        self.assertIn("raises", text)

    def test_a_repository_method_does_not_carry_raises(self):
        """Only the service declares behaviour; the port implements the storage."""
        text = grammar_open.persistence_ports()
        self.assertNotIn("raises-list", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
