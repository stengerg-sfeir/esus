"""Does the recorded CLI surface contain the commands the requirements name?

Every other check compares one document with another. This one compares a
document with the prose it was extracted from, which is the distinction that
matters here: `invocation` was previously checked against the parser technology
and against itself, so a command the requirements name and the surface omits was
invisible. expenses recorded `category` and `budget` with **no subcommands at
all** while its requirements name three each, and nothing could see it.

The comparison is deliberately narrow. It reads the one notation every prompt in
the corpus uses — `<noun> <verb> --flag` — and it only reports a pair when the
noun is a command the surface already has. When the noun is not a command, the
pair is skipped rather than guessed at: `library borrow book` puts the *program*
name before the verb, and a rule that could not tell a tool name from a command
would report a finding for correct output.
"""

import re

# `<noun> <verb> --flag`: the token before a flag is the verb, and the token
# before that is the thing it acts on.
COMMAND_PAIR = re.compile(r"\b([a-z][a-z_-]*)\s+([a-z][a-z_-]*)\s+--[a-z]")

# Global flags are not verbs, and a command is free to declare them.
GLOBAL_FLAGS = ("help", "version")


def check_surface_coverage(components, requirements, report):
    """Report commands and subcommands the requirements name and the surface lacks.

    Returns the number of checks performed, so a caller can tell "the surface
    agrees with the requirements" from "there was nothing to compare".
    """
    if not requirements or not isinstance(components, dict):
        return 0
    facade = components.get("facade")
    if not isinstance(facade, dict):
        return 0
    invocation = facade.get("invocation")
    if not isinstance(invocation, dict):
        # A program with no arguments declares `invocation: null`, and it is a
        # valid recorded answer rather than a gap to report.
        return 0

    commands = _commands_by_name(invocation)
    if not commands:
        return 0

    pairs = sorted({(noun, verb) for noun, verb in COMMAND_PAIR.findall(requirements)})
    checkable = 0
    for noun, verb in pairs:
        if noun not in commands:
            # The noun is not a command. Either the requirements named the
            # program itself (`library borrow book`) or they are describing
            # something that is not a command line at all; neither is evidence
            # of a missing command.
            continue
        checkable += 1
        if verb in commands[noun] or verb in GLOBAL_FLAGS:
            continue
        report.warning(
            "missing_command",
            f"components.facade.invocation: the requirements name '{noun} {verb}' but the "
            f"command '{noun}' declares no '{verb}' subcommand (it declares: "
            f"{', '.join(sorted(commands[noun])) or 'none'})",
        )
    return checkable


def _commands_by_name(invocation):
    """Map each command to the set of its subcommand names."""
    commands = {}
    entries = invocation.get("commands")
    if not isinstance(entries, list):
        return commands
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        subcommands = entry.get("subcommands")
        names = set()
        if isinstance(subcommands, list):
            for sub in subcommands:
                if isinstance(sub, dict) and isinstance(sub.get("name"), str):
                    names.add(sub["name"])
        commands[name.strip()] = names
    return commands
