"""Grammars for the split components step.

The first call produces only the surface plan: facade metadata, positional and
global options, and the top-level command names.  One further call produces
each command's subtree.  The plan grammar deliberately prevents the model from
emitting subcommands or command-specific options, so a repetition-prone model
cannot fill the whole CLI surface in one unbounded document.
"""

from __future__ import annotations

from kernel.extraction import grammar_open
from kernel.extraction.grammar import (
    MAX_CLI_COMMANDS,
    grammar,
    json_list,
    json_literal,
    json_object,
    rule,
)
from kernel.extraction.grammar_builders import distinct_entity_list

NULL = '"null"'


def plan(vocabulary, paths=False):
    entity_names = vocabulary.entity_names
    rules = [
        rule("root", json_object([("components", "plan-components")])),
        rule(
            "plan-components",
            json_object(
                [
                    ("facade", "plan-facade"),
                    ("persistence", "persistence-obj"),
                    ("external_access", "external-list"),
                    ("crud_services", "crud-list"),
                ]
            ),
        ),
        rule(
            "plan-facade",
            json_object(
                [
                    ("type", "facade-type"),
                    ("technology", "string"),
                    ("invocation", f"( {NULL} | plan-invocation )"),
                ]
            ),
        ),
        rule(
            "plan-invocation",
            json_object(
                [
                    ("positional", "cli-arg-list"),
                    ("options", "cli-option-list"),
                    ("commands", "plan-command-list"),
                ]
            ),
        ),
        rule("plan-command-list", json_list("plan-command", 0, MAX_CLI_COMMANDS)),
        rule("plan-command", json_object([("name", "identifier")])),
        rule(
            "facade-type",
            " | ".join(json_literal(value) for value in ("cli", "api", "gui")),
        ),
        rule(
            "persistence-obj",
            json_object([("required", "boolean"), ("technology", "string")]),
        ),
        rule("external-list", json_list("string", 0, 10)),
        *(
            distinct_entity_list("crud", entity_names, "operation-list")
            if entity_names else
            (rule("crud-list", '"[" ws "]"'),)
        ),
        rule("operation-list", json_list("operation", 1, 5)),
        rule("operation", grammar_open.OPERATIONS),
        # Reuse the option/argument/command-shape rules from the normal facade
        # grammar.  They are harmless in the plan even though the plan's own
        # command list is name-only.
        *grammar_open.facade_rules(paths),
    ]
    return grammar(rules)


def command_group(paths=False, subcommands=None):
    """The subtree of one already-chosen top-level command.

    When the requirements name this group's subcommands, pass them in: the
    grammar then makes a different subcommand name unrepresentable.  Prose-only
    prompts pass None and let the model choose.
    """
    flat_subcommands = json_list("cli-subcommand", 0, 0)
    group_rule = "group-command-nested" if subcommands else         "( group-command-nested | group-command-flat )"
    return grammar(
        [
            rule("root", json_object([("command_group", "group-command")])),
            rule("group-command", group_rule),
            rule(
                "group-command-nested",
                json_object(
                    [
                        ("options", "cli-global-option-list"),
                        ("subcommands", "cli-subcommand-list-nonempty"),
                    ]
                ),
            ),
            rule(
                "group-command-flat",
                json_object(
                    [
                        ("options", "cli-option-list"),
                        ("subcommands", flat_subcommands),
                    ]
                ),
            ),
            *grammar_open.facade_rules(paths, subcommands=subcommands),
        ]
    )
