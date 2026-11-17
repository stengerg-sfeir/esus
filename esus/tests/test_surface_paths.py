"""Nested command groups become path subcommands, and only where a prompt nests.

`expense category add --name` is three words below the program; the surface
holds a command and one level of subcommands, so the subcommand is named by a
path: `expense` / `category add`. Everything is gated on `uses_paths`, so the
prompts that never nest (library, inventory) are read exactly as before. Each
test pins a decision, silence included.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kernel.extraction import command_lines  # noqa: E402

EXPENSES = [
    "expense category add --name --description [--budget] [--icon]",
    "expense category list",
    "budget add --category-id --month --amount",
    "expense add --amount --description --category",
    "expense report monthly --month",
    "expense report yearly --year",
    "expense recurring detect",
]
LIBRARY = [
    "library book add --title --isbn --author-id",
    "library book list [--author] [--available-only]",
    "library borrow --member-id --book-id",
    "library overdue",
    "library member history --member-id",
]
INVENTORY = [
    "product add --sku --name",
    "product report --low-only",
    "category list",
]


class ProgramWordTests(unittest.TestCase):
    def test_a_first_word_on_every_line_is_the_program(self):
        self.assertEqual(command_lines.program_word(LIBRARY), "library")

    def test_a_first_word_some_line_lacks_is_a_group(self):
        self.assertIsNone(command_lines.program_word(EXPENSES))

    def test_one_line_cannot_say(self):
        self.assertIsNone(command_lines.program_word(["library overdue"]))
        self.assertIsNone(command_lines.program_word([]))


class UsesPathsTests(unittest.TestCase):
    def test_three_words_below_a_group_nest(self):
        self.assertTrue(command_lines.uses_paths(EXPENSES))

    def test_library_never_nests(self):
        # `library book add` is three words, but `library` is the program.
        self.assertFalse(command_lines.uses_paths(LIBRARY))

    def test_inventory_never_nests(self):
        self.assertFalse(command_lines.uses_paths(INVENTORY))

    def test_a_single_line_is_not_enough_to_decide(self):
        self.assertFalse(command_lines.uses_paths(
            ["expense category add --name"]))


class AttributionTests(unittest.TestCase):
    def attributed(self, spans, entities=("Expense", "Category", "Budget")):
        return [(c, s, [f for f, _ in flags])
                for c, s, flags in command_lines.attribute_lines(
                    spans, list(entities))]

    def test_a_nesting_prompt_files_the_rest_of_the_line_as_a_path(self):
        self.assertEqual(self.attributed(EXPENSES), [
            ("expense", "category add", ["name", "description", "budget", "icon"]),
            ("expense", "category list", []),
            ("budget", "add", ["category-id", "month", "amount"]),
            ("expense", "add", ["amount", "description", "category"]),
            ("expense", "report monthly", ["month"]),
            ("expense", "report yearly", ["year"]),
            ("expense", "recurring detect", []),
        ])

    def test_library_is_attributed_as_it_always_was(self):
        self.assertEqual(self.attributed(LIBRARY, ("Book", "Member", "Loan")), [
            ("book", "add", ["title", "isbn", "author-id"]),
            ("book", "list", ["author", "available-only"]),
            ("borrow", None, ["member-id", "book-id"]),
            ("overdue", None, []),
            ("member", "history", ["member-id"]),
        ])

    def test_inventory_is_attributed_as_it_always_was(self):
        self.assertEqual(self.attributed(INVENTORY, ("Product", "Category")), [
            ("product", "add", ["sku", "name"]),
            ("product", "report", ["low-only"]),
            ("category", "list", []),
        ])

    def test_an_isolated_line_keeps_the_old_rule(self):
        # The old rule (two leading entities drop the first) still reads one
        # line on its own; only a prompt with several lines can nest.
        self.assertEqual(
            command_lines.attribute_lines(
                ["expense category add --name"], ["Expense", "Category"]),
            [("category", "add", [("name", True)])])


class ExtractionTests(unittest.TestCase):
    NESTING = ("Use `expense category add --name` and `expense category list`, "
               "then `expense report monthly --month`, `budget list` and "
               "`expense recurring detect`.")

    def test_flagless_paths_are_enumerated_when_the_prompt_nests(self):
        self.assertEqual(command_lines.extract_command_lines(self.NESTING), [
            "expense category add --name",
            "expense category list",
            "expense report monthly --month",
            "budget list",
            "expense recurring detect",
        ])

    def test_a_flagless_three_word_line_whose_command_is_known_is_kept(self):
        text = "Run `product add --sku` and `product report low-stock`."
        self.assertEqual(command_lines.extract_command_lines(text),
                         ["product add --sku", "product report low-stock"])

    def test_a_three_word_span_of_an_unknown_command_stays_out(self):
        text = self.NESTING + " Also `some unrelated phrase`."
        self.assertNotIn("some unrelated phrase",
                         command_lines.extract_command_lines(text))


def option(name):
    return {"name": name, "short": None, "type": "str", "required": True,
            "default": None}


def sub(name, *flags):
    return {"name": name, "options": [option(f) for f in flags]}


def surface(**commands):
    return {"facade": {"type": "cli", "technology": "click", "invocation": {
        "positional": [], "options": [],
        "commands": [{"name": name, "options": [], "subcommands": subs}
                     for name, subs in commands.items()]}}}


EXPENSES_TEXT = (
    "`expense category add --name --description` `expense category list` "
    "`expense category delete --id` `budget list [--month]` "
    "`expense add --amount` `expense report monthly --month` "
    "`expense report yearly --year` `expense recurring detect`")
NESTED = surface(
    expense=[sub("category add", "--name", "--description"),
             sub("category list"), sub("category delete", "--id"),
             sub("add", "--amount"), sub("report monthly", "--month"),
             sub("report yearly", "--year"), sub("recurring detect")],
    budget=[sub("list", "--month")])


class CheckerTests(unittest.TestCase):
    def findings(self, components, text=EXPENSES_TEXT, services=None):
        from kernel.consistency import checks_surface
        from kernel.consistency.report import Report
        report = Report("t")
        checks_surface.check_surface_coverage(components, text, report)
        checks_surface.check_flag_coverage(components, text, report)
        if services is not None:
            checks_surface.check_command_backing(components, services, report)
        return [(f.rule, f.message) for f in report.findings]

    def test_a_surface_that_holds_every_path_has_no_finding(self):
        self.assertEqual(self.findings(NESTED), [])

    def test_a_missing_path_flag_is_still_reported(self):
        broken = surface(
            expense=[sub("category add", "--name"), sub("category list"),
                     sub("category delete", "--id"), sub("add", "--amount"),
                     sub("report monthly", "--month"),
                     sub("report yearly"), sub("recurring detect")],
            budget=[sub("list", "--month")])
        found = self.findings(broken)
        self.assertEqual([rule for rule, _ in found], ["missing_flag"] * 2)
        self.assertTrue(any("--year" in m and "report yearly" in m
                            for _r, m in found))

    def test_a_flattened_surface_is_reported_against_a_path_prompt(self):
        flat = surface(
            category=[sub("add", "--name", "--description"), sub("list"),
                      sub("delete", "--id")],
            expense=[sub("add", "--amount"), sub("report", "--month", "--year"),
                     sub("recurring")],
            budget=[sub("list", "--month")])
        found = [m for r, m in self.findings(flat) if r == "missing_command"]
        for path in ("category add", "category list", "category delete",
                     "report monthly", "report yearly", "recurring detect"):
            self.assertTrue(any(f"'{path}' subcommand" in m for m in found), path)
        # the lines that do match are not reported
        self.assertFalse(any("'expense add'" in m for m in found))

    def test_a_prompt_that_never_nests_is_not_judged_by_paths(self):
        library = surface(book=[sub("add", "--title")], borrow=[])
        text = "`library book add --title` `library borrow --member-id`"
        # (the flag rule may still speak about this bare fixture; paths must not)
        self.assertEqual([r for r, _ in self.findings(library, text)
                          if r == "missing_command"], [])

    def test_every_path_is_backed_by_a_method(self):
        services = [{"service_name": "S", "methods": [
            {"name": "create_category"}, {"name": "read_all_categories"},
            {"name": "delete_category"}, {"name": "add_expense"},
            {"name": "get_monthly_report"}, {"name": "get_yearly_summary"},
            {"name": "detect_recurring"}, {"name": "read_all_budgets"}]}]
        self.assertEqual(self.findings(NESTED, services=services), [])

    def test_a_path_no_method_could_serve_is_reported(self):
        services = [{"service_name": "S", "methods": [
            {"name": "create_category"}, {"name": "read_all_categories"},
            {"name": "delete_category"}, {"name": "add_expense"},
            {"name": "get_monthly_report"}, {"name": "get_yearly_summary"},
            {"name": "read_all_budgets"}]}]
        found = self.findings(NESTED, services=services)
        self.assertEqual([rule for rule, _ in found], ["unbacked_command"])
        self.assertIn("recurring detect", found[0][1])


class BinderTests(unittest.TestCase):
    ADAPTERS = [
        {"action_name": name, "target_service": service, "target_method": method}
        for name, service, method in (
            ("create_category", "CategoryService", "create_category"),
            ("read_all_categories", "CategoryService", "read_all_categories"),
            ("delete_category", "CategoryService", "delete_category"),
            ("add_expense", "ExpenseService", "add_expense"),
            ("list_expenses", "ExpenseService", "list_expenses"),
            ("monthly", "ExpenseService", "get_monthly_report"),
            ("yearly", "ExpenseService", "get_yearly_summary"),
            ("recurring", "ExpenseService", "detect_recurring"),
            ("export", "ExpenseService", "export_to_csv"),
        )]

    def bind(self):
        from kernel import codegen
        from kernel.consistency.checks_surface import COMMAND_VERB_STEMS
        bindings, unmapped = codegen.bind_commands(
            self.ADAPTERS, NESTED["facade"]["invocation"], COMMAND_VERB_STEMS)
        return {key: (value[0] if value else None)
                for key, value in bindings.items()}, unmapped

    def test_a_path_is_bound_by_the_thing_it_names(self):
        bound, _unmapped = self.bind()
        self.assertEqual(bound[("expense", "category add")], "create_category")
        self.assertEqual(bound[("expense", "category list")], "read_all_categories")
        self.assertEqual(bound[("expense", "category delete")], "delete_category")

    def test_a_plain_subcommand_of_the_same_command_is_bound_as_before(self):
        bound, _unmapped = self.bind()
        self.assertEqual(bound[("expense", "add")], "add_expense")

    def test_a_qualifier_picks_the_report(self):
        bound, _unmapped = self.bind()
        self.assertEqual(bound[("expense", "report monthly")], "monthly")
        self.assertEqual(bound[("expense", "report yearly")], "yearly")
        self.assertEqual(bound[("expense", "recurring detect")], "recurring")

    def test_nothing_is_left_unbound(self):
        _bound, unmapped = self.bind()
        self.assertEqual(unmapped, [])


sys.path.insert(0, str(ROOT / "tests"))
import test_generator  # noqa: E402


class EmissionTests(unittest.TestCase):
    """The emitted CLI is run, for both backends, against stand-in repositories."""

    def setUp(self):
        self.helper = test_generator.CliChoiceTests(
            "test_recorded_route_wins_when_its_flag_is_passed")

    def ctx(self, technology):
        def field(name):
            return {"field_name": name, "target_param": name,
                    "transform": "DIRECT", "required": True}

        adapters = [
            {"action_name": "create_category",
             "target_service": "CategoryRepository",
             "target_method": "create_category", "input_fields": [field("name")]},
            {"action_name": "monthly_report",
             "target_service": "ExpenseRepository",
             "target_method": "get_monthly_report", "input_fields": [field("month")]},
            {"action_name": "add_expense",
             "target_service": "ExpenseRepository",
             "target_method": "add_expense", "input_fields": [field("amount")]},
        ]
        invocation = surface(
            expense=[sub("category add", "--name"), sub("report monthly", "--month"),
                     sub("add", "--amount")])["facade"]["invocation"]
        for command in invocation["commands"]:
            for leaf in command["subcommands"]:
                for opt in leaf["options"]:
                    opt["required"] = False
        return {
            "models": [{"name": "Category", "fields": [
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "name", "type": "string"}]}],
            "errors": [], "services": [],
            "repositories": [
                {"entity": "Category", "interface_name": "CategoryRepository",
                 "methods": [{"name": "create_category",
                              "params": [{"name": "name", "type": "str"}],
                              "return_type": "None"}]},
                {"entity": "Expense", "interface_name": "ExpenseRepository",
                 "methods": [
                     {"name": "get_monthly_report",
                      "params": [{"name": "month", "type": "str"}],
                      "return_type": "None"},
                     {"name": "add_expense",
                      "params": [{"name": "amount", "type": "int"}],
                      "return_type": "None"}]}],
            "mappings": {}, "match_index": {}, "adapters": adapters,
            "entity_names": ["Category", "Expense"],
            "components": {"facade": {"technology": technology,
                                      "invocation": invocation}},
            "routes": [],
        }

    def run_path(self, technology, *argv):
        text, stats = self.helper.emitted(self.ctx(technology))
        calls = []

        class Category:
            def __init__(self, store):
                pass

            def create_category(self, name=None):
                calls.append(("category", name))

        class Expense:
            def __init__(self, store):
                pass

            def get_monthly_report(self, month=None):
                calls.append(("report", month))

            def add_expense(self, amount=None):
                calls.append(("add", amount))

        code, output = self.helper.run_cli(
            text, {"CategoryRepository": Category, "ExpenseRepository": Expense},
            ["--db", ":memory:", *argv], models=("Category", "Expense"))
        return code, calls, text, stats

    def check_both(self, argv, expected):
        for technology in ("click", "argparse"):
            code, calls, _text, _stats = self.run_path(technology, *argv)
            self.assertEqual((code, calls), (0, expected), technology)

    def test_a_path_reaches_the_method_it_names(self):
        self.check_both(["expense", "category", "add", "--name", "Food"],
                        [("category", "Food")])

    def test_a_qualified_path_reaches_its_own_report(self):
        self.check_both(["expense", "report", "monthly", "--month", "2024-01"],
                        [("report", "2024-01")])

    def test_a_plain_subcommand_beside_the_paths_still_works(self):
        self.check_both(["expense", "add", "--amount", "5"], [("add", "5")])

    def test_the_click_tree_nests_the_path_into_groups(self):
        _code, _calls, text, _stats = self.run_path(
            "click", "expense", "add", "--amount", "1")
        self.assertIn("'category': {'subcommands': {'add':", text.replace("\n", " ")
                      .replace("  ", " "))

    def test_every_path_is_bound_and_nothing_is_unmapped(self):
        _code, _calls, text, stats = self.run_path(
            "click", "expense", "add", "--amount", "1")
        self.assertEqual(stats["unmapped"], [])
        self.assertIn("('expense', 'category add')", text)

    def test_a_surface_without_paths_emits_the_same_tree_as_before(self):
        flat = surface(expense=[sub("add", "--amount")])["facade"]["invocation"]
        from generator import _click_commands
        tree = _click_commands(flat, [])
        self.assertEqual(tree, {"expense": {"subcommands": {
            "add": {"binding": ("expense", "add"), "plans": []}}}})


class ResolveSpanTests(unittest.TestCase):
    def resolve(self, span, program, commands):
        from kernel.consistency import checks_surface
        return checks_surface._resolve_span(span, program, commands)

    COMMANDS = {"expense": {"category add", "category list", "add",
                            "report monthly", "report yearly"},
                "budget": {"list", "add"}}

    def test_a_path_resolves_to_the_command_and_its_path(self):
        self.assertEqual(self.resolve(
            "expense category add --name", "expense", self.COMMANDS),
            ("expense", "category add"))
        self.assertEqual(self.resolve(
            "expense report monthly --month", "expense", self.COMMANDS),
            ("expense", "report monthly"))

    def test_a_plain_subcommand_resolves_as_before(self):
        self.assertEqual(self.resolve(
            "expense add --amount", "expense", self.COMMANDS),
            ("expense", "add"))
        self.assertEqual(self.resolve(
            "budget list --month", "expense", self.COMMANDS),
            ("budget", "list"))

    def test_a_surface_without_paths_resolves_exactly_as_before(self):
        library = {"book": {"add", "list"}, "member": {"add", "history"},
                   "borrow": set()}
        self.assertEqual(self.resolve(
            "library book add --title", "library", library), ("book", "add"))
        self.assertEqual(self.resolve(
            "library borrow --member-id", "library", library), ("borrow", None))
        self.assertIsNone(self.resolve(
            "library book frobnicate --x", "library", library))

    def test_an_unknown_path_is_skipped_not_guessed(self):
        self.assertIsNone(self.resolve(
            "expense report weekly --week", "expense", self.COMMANDS))


class Log:
    def __init__(self):
        self.lines = []

    def write(self, line):
        self.lines.append(line)


def typed(name, otype="str", required=False):
    return {"name": name, "short": None, "type": otype, "required": required,
            "default": None}


def flat_surface():
    """What a small model returns for the expenses lines: the nesting flattened."""
    return {"facade": {"type": "cli", "technology": "click", "invocation": {
        "positional": [], "options": [], "commands": [
            {"name": "category", "options": [], "subcommands": [
                {"name": "add", "options": [typed("--name"), typed("--description"),
                                            typed("--budget", "int"), typed("--icon")]},
                {"name": "list", "options": []},
                {"name": "update", "options": [typed("--id", "int")]},
                {"name": "delete", "options": [typed("--id", "int")]}]},
            {"name": "budget", "options": [], "subcommands": [
                {"name": "list", "options": [typed("--month")]}]},
            {"name": "expense", "options": [], "subcommands": [
                {"name": "add", "options": [typed("--amount", "int")]},
                {"name": "report", "options": [typed("--monthly"),
                                               typed("--yearly", "int")]},
                {"name": "recurring", "options": []}]},
        ]}}}


NESTING_TEXT = (
    "`expense category add --name --description [--budget] [--icon]` "
    "`expense category list` `expense category update --id` "
    "`expense category delete --id` `budget list [--month]` "
    "`expense add --amount` `expense report monthly --month` "
    "`expense report yearly --year` `expense recurring detect`")


def tree(components):
    invocation = components["facade"]["invocation"]
    return {c["name"]: {sub["name"]: [(o["name"], o["type"], o["required"])
                                       for o in sub["options"]]
                        for sub in c.get("subcommands", [])}
            for c in invocation["commands"]}


class RepairTests(unittest.TestCase):
    def repair(self, components=None, text=NESTING_TEXT):
        from kernel.extraction import repairs
        components = components or flat_surface()
        log = Log()
        repairs.repair_nested_paths(components, text, log)
        return components, log

    def test_the_lines_become_path_leaves_typed_from_the_models_own_flags(self):
        components, _log = self.repair()
        built = tree(components)
        self.assertEqual(built["expense"]["category add"], [
            ("--name", "str", True), ("--description", "str", True),
            ("--budget", "int", False), ("--icon", "str", False)])
        self.assertEqual(built["expense"]["category delete"], [("--id", "int", True)])
        # a flag the model spelled differently stands for the one the line names
        self.assertEqual(built["expense"]["report monthly"], [("--month", "str", True)])
        self.assertEqual(built["expense"]["report yearly"], [("--year", "int", True)])
        self.assertEqual(built["expense"]["recurring detect"], [])

    def test_the_flat_form_is_folded_away(self):
        components, log = self.repair()
        built = tree(components)
        self.assertNotIn("category", built)
        self.assertEqual(sorted(built), ["budget", "expense"])
        self.assertEqual(sorted(built["expense"]), [
            "add", "category add", "category delete", "category list",
            "category update", "recurring detect", "report monthly",
            "report yearly"])
        self.assertTrue(any("folded flat 'category add'" in line for line in log.lines))
        self.assertTrue(any("dropped the emptied flat command 'category'" in line
                            for line in log.lines))

    def test_a_leaf_beside_its_own_paths_is_kept_when_a_line_names_it(self):
        text = NESTING_TEXT + " `expense report --month`"
        components, _log = self.repair(text=text)
        self.assertIn("report", tree(components)["expense"])

    def test_a_flat_subcommand_no_line_covers_is_not_deleted(self):
        components = flat_surface()
        components["facade"]["invocation"]["commands"][0]["subcommands"].append(
            {"name": "archive", "options": [typed("--id", "int")]})
        built = tree(self.repair(components)[0])
        self.assertEqual(list(built["category"]), ["archive"])

    def test_a_flag_with_no_donor_is_left_for_the_typing_repair(self):
        components = flat_surface()
        components["facade"]["invocation"]["commands"][2]["subcommands"][1][
            "options"] = []
        built = tree(self.repair(components)[0])
        self.assertNotIn("--year", [o[0] for o in built["expense"]["report yearly"]])

    def test_running_it_twice_changes_nothing(self):
        from kernel.extraction import repairs
        components, _log = self.repair()
        before = tree(components)
        again = Log()
        repairs.repair_nested_paths(components, NESTING_TEXT, again)
        self.assertEqual(tree(components), before)
        self.assertEqual(again.lines, [])

    def test_a_prompt_that_does_not_nest_is_not_touched(self):
        import copy
        from kernel.extraction import repairs
        library = surface(book=[sub("add", "--title")], member=[sub("list")])
        before = copy.deepcopy(library)
        log = Log()
        repairs.repair_nested_paths(
            library, "`library book add --title` `library member list` "
                     "`library borrow --member-id`", log)
        self.assertEqual(library, before)
        self.assertEqual(log.lines, [])


class GrammarTests(unittest.TestCase):
    def grammar(self, paths):
        from kernel.extraction import grammar_builders, vocabulary
        entities = tuple(vocabulary.EntitySignature(
            name=name, fields=("id",), primary_key="id")
            for name in ("Expense", "Category"))
        return str(grammar_builders.components(
            vocabulary.Vocabulary(entities=entities), paths=paths))

    def test_the_default_grammar_has_no_path_rule(self):
        self.assertNotIn("cli-path", self.grammar(False))

    def test_a_nesting_prompt_may_name_a_subcommand_by_a_path(self):
        text = self.grammar(True)
        self.assertIn("cli-path ::=", text)
        subcommand = next(line for line in text.splitlines()
                          if line.startswith("cli-subcommand ::="))
        self.assertIn("cli-path", subcommand)

    def test_a_command_keeps_the_plain_identifier(self):
        text = self.grammar(True)
        nested = next(line for line in text.splitlines()
                      if line.startswith("cli-command-nested ::="))
        self.assertNotIn("cli-path", nested)

    def test_the_open_grammar_takes_the_same_switch(self):
        from kernel.extraction import grammar_open
        self.assertNotIn("cli-path", str(grammar_open.components()))
        self.assertIn("cli-path", str(grammar_open.components(paths=True)))


class PromptBlockTests(unittest.TestCase):
    def block(self, spans):
        from kernel.extraction import prompts
        return prompts.command_lines_block(spans)

    def test_a_nesting_prompt_gets_every_line_already_filed(self):
        text = self.block(EXPENSES)
        self.assertIn("filed exactly as shown", text)
        self.assertIn("`expense category add --name --description [--budget] "
                      "[--icon]` -> command `expense`, subcommand `category add` "
                      "(--name --description [--budget] [--icon])", text)
        self.assertIn("`expense category list` -> command `expense`, "
                      "subcommand `category list` (no flags)", text)
        self.assertIn("`budget add --category-id --month --amount` -> command "
                      "`budget`, subcommand `add`", text)
        self.assertIn("Never turn a word of the path into a command of its own",
                      text)

    def test_library_and_inventory_get_the_block_they_always_had(self):
        for spans in (LIBRARY, INVENTORY):
            text = self.block(spans)
            self.assertNotIn("filed exactly as shown", text)
            self.assertNotIn("->", text)

    def test_a_program_word_is_not_a_command(self):
        spans = ["tool user create admin --x", "tool user delete --id"]
        self.assertIn("-> command `user`, subcommand `create admin`",
                      self.block(spans))


if __name__ == "__main__":
    unittest.main()
