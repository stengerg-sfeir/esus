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
    MAX_CLI_OPTIONS,
    grammar,
    json_list,
    json_literal,
    json_object,
    rule,
    string_choice,
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


def command_group(paths=False, subcommands=None, option_specs=None):
    """The subtree of one already-chosen top-level command.

    When the requirements name this group's subcommands, pass them in: the
    grammar then makes a different subcommand name unrepresentable.  When they
    also name its flags, `option_specs` closes each leaf's option names as well;
    a model cannot replace `--amount` with `--amt` and leave the required flag
    missing.  Prose-only prompts pass None and let the model choose.
    """
    option_specs = option_specs or {}
    flat_subcommands = json_list("cli-subcommand", 0, 0)
    rules = [
        rule("root", json_object([("command_group", "group-command")])),
    ]

    def option_rules(prefix, flags):
        names = [f"--{flag}" for flag in flags]
        if not names:
            return [rule(f"{prefix}-list", json_list(f"{prefix}-option", 0, 0))]
        return [
            rule(f"{prefix}-list", json_list(f"{prefix}-option", 0, len(names))),
            rule(
                f"{prefix}-option",
                json_object([
                    ("name", string_choice(names)),
                    ("short", f"( {NULL} | option-name )"),
                    ("type", "option-type"),
                    ("required", "boolean"),
                    ("default", f"( {NULL} | string )"),
                ]),
            ),
        ]

    if subcommands:
        rules.extend([
            rule("group-command", "group-command-nested"),
            rule(
                "group-command-nested",
                json_object([
                    ("options", "cli-global-option-list"),
                    ("subcommands", "group-subcommand-list"),
                ]),
            ),
            rule("group-subcommand-list", fixed_sequence("group-subcommand", len(subcommands))),
        ])
        for index, path in enumerate(subcommands):
            flags = option_specs.get(path, ())
            rules.extend(option_rules(f"group-options-{index}", flags))
            rules.append(
                rule(
                    f"group-subcommand-{index}",
                    json_object([
                        ("name", json_literal(path)),
                        ("options", f"group-options-{index}-list"),
                    ]),
                )
            )
    else:
        flags = option_specs.get(None, ())
        rules.extend(option_rules("group-options-flat", flags))
        rules.extend([
            rule("group-command", "( group-command-nested | group-command-flat )"),
            rule(
                "group-command-nested",
                json_object([
                    ("options", "cli-global-option-list"),
                    ("subcommands", "cli-subcommand-list-nonempty"),
                ]),
            ),
            rule(
                "group-command-flat",
                json_object([
                    ("options", "group-options-flat-list"),
                    ("subcommands", flat_subcommands),
                ]),
            ),
        ])
    rules.extend(grammar_open.facade_rules(paths, subcommands=subcommands))
    return grammar(rules)


def fixed_sequence(prefix, count):
    parts = ['"[" ws', f"{prefix}-0"]
    for index in range(1, count):
        parts.append(f'ws "," ws {prefix}-{index}')
    parts.append('ws "]"')
    return " ".join(parts)
