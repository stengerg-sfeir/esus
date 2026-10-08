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
would report a finding for correct output. The rule was widened after library
showed its cost: it read only `<noun> <verb> --flag`, so a bracketed optional
flag (`<verb> [--flag]`) hid the verb entirely, and it only ever compared a noun
the surface already had, so a whole command group the surface omitted was
invisible. library declares one command (`book`) where the requirements name
nine lines; the old rule reported one of them.
"""

import re
from collections import Counter

# `<noun> <verb> --flag` or `<noun> <verb> [--flag`: the token before a flag is
# the verb, and the token before that is the thing it acts on. The optional `[`
# accepts the prompts' `<verb> [--optional-flag]` notation, which the first
# version of this rule read as no flag at all and so never compared.
COMMAND_PAIR = re.compile(r"\b([a-z][a-z0-9_-]*)\s+([a-z][a-z0-9_-]*)\s+\[?-{1,2}[a-z]")

# The word a command line starts with inside its backticks — the program name on
# every prompt in the corpus (`library book add` starts with `library`).
COMMAND_START = re.compile(r"`\s*([a-z][a-z0-9_-]*)")

# Global flags are not verbs, and a command is free to declare them.
GLOBAL_FLAGS = ("help", "version")

# A noun that precedes this many distinct verbs is a command group the surface
# omitted; a noun seen once is passed over.
MISSING_COMMAND_THRESHOLD = 2


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

    verbs_by_noun = {}
    for noun, verb in COMMAND_PAIR.findall(requirements):
        verbs_by_noun.setdefault(noun, set()).add(verb)

    # The program name is not a command, and a subcommand of any command is
    # already part of the surface; neither is a missing command. Without these
    # two exclusions the rule reported `library` (the program) and `report` (a
    # subcommand of `expense`) as missing commands.
    program = _program_name(requirements)
    known_subcommands = {sub for subs in commands.values() for sub in subs}

    checkable = 0
    for noun, verbs in sorted(verbs_by_noun.items()):
        if noun in commands:
            checkable += 1
            for verb in sorted(verbs):
                if verb in commands[noun] or verb in GLOBAL_FLAGS:
                    continue
                report.warning(
                    "missing_command",
                    f"components.facade.invocation: the requirements name '{noun} {verb}' but "
                    f"the command '{noun}' declares no '{verb}' subcommand (it declares: "
                    f"{', '.join(sorted(commands[noun])) or 'none'})",
                )
            continue
        if noun == program or noun in known_subcommands:
            continue
        if len(verbs) >= MISSING_COMMAND_THRESHOLD:
            # The noun is not a command the surface declares, yet the
            # requirements use it before several different verbs: a whole
            # command group the surface omitted, not the program name and not a
            # stray phrase. Reported once, as a missing command.
            checkable += 1
            report.warning(
                "missing_command",
                f"components.facade.invocation: the requirements name the command '{noun}' "
                f"(for {', '.join(sorted(verbs))}) but the surface declares no such command "
                f"(it declares: {', '.join(sorted(commands)) or 'none'})",
            )
    return checkable


def _program_name(requirements):
    """The word the command lines start with, or None.

    Every prompt writes a command line as `<program> ...`, and the program
    appears on every line, so it is the most common first word inside the
    backticks. It is excluded from the missing-command check: a program name is
    not a command, and on library's single-word lines (`library borrow --x`) it
    is the noun the pair rule sees.
    """
    starts = COMMAND_START.findall(requirements)
    if not starts:
        return None
    return Counter(starts).most_common(1)[0][0]


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


# The verbs a CLI exposes and the method-name stems that can serve them. A
# command and its method rarely share a spelling — `book add` is `create_book`,
# `book list` is `read_all_books` — so a verb is matched by a family of stems
# rather than by equality. The map is deliberately generous: this rule reports a
# command nothing could plausibly implement, not one whose method is spelled
# differently but recognisably serves it.
COMMAND_VERB_STEMS = {
    "add": ("add", "create", "save", "insert", "new"),
    "create": ("add", "create", "save", "insert", "new"),
    "list": ("all", "list"),
    "search": ("search", "query", "find", "filter"),
    "update": ("update", "edit", "set"),
    "delete": ("delete", "remove"),
    "remove": ("delete", "remove"),
    "get": ("get", "find", "read"),
    "show": ("get", "find", "read"),
    "report": ("report", "summary", "stats", "value"),
    "export": ("export", "write", "dump"),
    "confirm": ("confirm",),
    "cancel": ("cancel",),
    "restock": ("restock",),
    "borrow": ("borrow", "loan"),
    "return": ("return",),
    "renew": ("renew",),
    "detect": ("detect",),
    "assign": ("assign",),
    "history": ("history",),
}


def check_command_backing(components, services, report):
    """Report a CLI verb no service method could implement.

    This is the second half of the CLI-surface check and the one a code
    generator needs most: `missing_command` compares the surface with the
    *requirements*, and this compares it with the *methods*. A command the
    surface declares and no method serves is a command the generator cannot
    write — it would have to invent the call — and nothing else in the checker
    can see it, because a command resolves against no other document.

    A **note**, not a warning: the match is by name stem, and the checker cannot
    prove no method serves the verb, only that none is named for it. `order
    confirm` on 60 is reported beside `cancel_order` (which the same run
    declares), so the note points at the method to add rather than asserting one
    is absent.

    Returns the number of command verbs checked.
    """
    if not isinstance(components, dict) or not isinstance(services, list):
        return 0
    facade = components.get("facade")
    if not isinstance(facade, dict):
        return 0
    invocation = facade.get("invocation")
    if not isinstance(invocation, dict):
        return 0

    methods = _method_names(services)
    if not methods:
        return 0

    checked = 0
    for command, verb in _command_verbs(invocation):
        checked += 1
        stems = COMMAND_VERB_STEMS.get(verb, (verb,))
        if _served_by_stems(stems, methods):
            continue
        report.note(
            "unbacked_command",
            f"components.facade.invocation: the command '{command} {verb}' has no method behind "
            f"it — no service method name matches, so a generator cannot write the call",
        )
    return checked


def _method_names(services):
    """Every method name across the services, normalised for a substring match."""
    names = []
    for service in services:
        if not isinstance(service, dict):
            continue
        for method in service.get("methods") or []:
            if isinstance(method, dict) and isinstance(method.get("name"), str):
                names.append(_normalise(method["name"]))
    return names


def _command_verbs(invocation):
    """Yield (command, verb) for each subcommand, or the command when it has none.

    A flat command (`expense report`) exposes the verb as its subcommand; a
    command with subcommands is not itself a verb, so it is not checked — the
    verbs are.
    """
    entries = invocation.get("commands")
    if not isinstance(entries, list):
        return
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        subcommands = [
            sub.get("name")
            for sub in (entry.get("subcommands") or [])
            if isinstance(sub, dict) and isinstance(sub.get("name"), str)
        ]
        if subcommands:
            for sub in subcommands:
                yield name.strip(), sub.strip().lower()
        else:
            yield name.strip(), name.strip().lower()


def _served_by_stems(stems, methods):
    return any(any(stem in method for stem in stems) for method in methods)


def _normalise(value):
    return value.replace("_", "").replace("-", "").lower()
