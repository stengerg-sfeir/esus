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
    program = _program_name(requirements)

    checkable = _check_command_pairs(commands, requirements, program, report)
    return checkable + _check_top_level_commands(commands, requirements, report)


def _check_command_pairs(commands, requirements, program, report):
    verbs_by_noun = {}
    for noun, verb in COMMAND_PAIR.findall(requirements):
        verbs_by_noun.setdefault(noun, set()).add(verb)

    # The program name is not a command, and a subcommand of any command is
    # already part of the surface; neither is a missing command. Without these
    # two exclusions the rule reported `library` (the program) and `report` (a
    # subcommand of `expense`) as missing commands.
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
        if noun == program:
            continue
        if noun in known_subcommands:
            # A verb the surface filed under another command (`report` under
            # `expense`): a stray phrase stays silent. But a noun the
            # requirements act on with several *verb-like* words (`member`
            # with add, history and list, filed under `book`) is a command of
            # its own, misfiled — while selectors like monthly/yearly behind
            # `report` are values, not verbs, and stay silent.
            qualifying = {verb for verb in verbs
                          if verb in known_subcommands or verb in COMMAND_VERB_STEMS}
            if len(qualifying) < MISSING_COMMAND_THRESHOLD:
                continue
        elif len(verbs) < MISSING_COMMAND_THRESHOLD:
            continue
        # The noun is not a command the surface declares, yet the
        # requirements use it before several different verbs: a whole
        # command group the surface omitted, not the program name and not a
        # stray phrase — even when the word also appears as some other
        # command's subcommand (`member` filed under `book` while the
        # requirements act on it with add, history and list: it is a
        # command of its own, misfiled, not a covered subcommand).
        # Reported once, as a missing command.
        checkable += 1
        report.warning(
            "missing_command",
            f"components.facade.invocation: the requirements name the command '{noun}' "
            f"(for {', '.join(sorted(verbs))}) but the surface declares no such command "
            f"(it declares: {', '.join(sorted(commands)) or 'none'})",
        )
    return checkable


def _check_top_level_commands(commands, requirements, report):
    """Report program-led lines whose verb never became a command.

    A line with one command-like word between a leading non-command word and
    its flags (`library borrow --member-id --book-id`) makes that word a
    top-level command carrying its own options — the prompt's own rule for
    the shape. The pair rule cannot see these lines (it needs two words
    before a flag), so a vanished `borrow` was invisible: no missing command
    (the noun is the program), no unbacked command (undeclared verbs resolve
    against nothing). The leading word is tested structurally (it names no
    command), never by frequency — inventory writes `product add --sku`
    with no program word at all, and guessing `product` as one would report
    its verbs as missing commands. A bare line with no flags
    (`library overdue`) names no options and is left alone.
    """
    seen = set()
    checkable = 0
    for span in re.findall(r"`([^`]*)`", requirements):
        tokens = span.split()
        if len(tokens) < 3 or tokens[0] in commands:
            continue
        word = tokens[1].strip("[](),.;:")
        if not SPAN_WORD.fullmatch(word) or word in commands:
            continue
        flag = tokens[2].lstrip("[")
        if not flag.startswith("-"):
            continue
        if word in seen:
            continue
        seen.add(word)
        checkable += 1
        report.warning(
            "missing_command",
            f"components.facade.invocation: the requirements make '{word}' a "
            f"top-level command (`{span.strip()}`) but the surface declares "
            f"no such command (it declares: {', '.join(sorted(commands)) or 'none'})",
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
    "overdue": ("overdue",),
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


# A flag token inside backticks: `[--budget]`, `--from-date`, `[---category]`.
# Brackets mark an optional flag; the name is letters, digits, `_` and `-`.
# Three dashes are tolerated: a typo for an optional long flag, which must
# still resolve to the flag it means rather than vanish from the check.
FLAG_TOKEN = re.compile(r"\[?-{1,3}([a-z][a-z0-9_-]*)")

# A backtick span that can carry a command line at all: prose spans like
# `UNIQUE(category_id, month)` name no command and are skipped by shape, not
# by guessing.
SPAN_WORD = re.compile(r"[a-z][a-z0-9_-]*")


def check_flag_coverage(components, requirements, report):
    """Report flags the requirements pass and the surface cannot accept.

    `missing_command` compares verbs; this compares the flags behind them. A
    verb the surface declares with none of its data flags (inventory's
    `product add` carries only `-help`/`-version` while the requirements pass
    `--sku` and `--name`) parses and then can never run — the same stranded
    path as a missing command, one level down.

    Deliberately narrow, like the verb rule: only backtick spans are read, the
    program name is excluded, and a span whose command the surface never
    declared is skipped rather than guessed at. A span naming a subcommand
    first (`expense report monthly --month`, where `report` is a subcommand of
    `expense`) resolves to its owning command. A bare command line
    (`library borrow --member-id --book-id`, whose flags the document filed
    under the `book` subcommand) is judged against the command's own flags
    plus every subcommand's — the flags are somewhere the parser reaches.

    An unbracketed flag the leaf lacks is a warning; a bracketed (optional)
    one is a note. The generator can omit an optional; it cannot conjure a
    required value from nowhere.

    Returns the number of distinct (command, subcommand, flag) pairs examined.
    """
    if not requirements or not isinstance(components, dict):
        return 0
    facade = components.get("facade")
    if not isinstance(facade, dict):
        return 0
    invocation = facade.get("invocation")
    if not isinstance(invocation, dict):
        return 0

    commands = _commands_by_name(invocation)
    if not commands:
        return 0
    options = _options_by_leaf(invocation)
    program = _program_name(requirements)

    seen = set()
    for span in re.findall(r"`([^`]*)`", requirements):
        target = _resolve_span(span, program, commands)
        if target is None:
            continue
        command, sub = target
        for flag, bracketed in _flags_in(span):
            key = (command, sub, flag)
            if key in seen:
                continue
            seen.add(key)
            if _flag_covered(flag, command, sub, options):
                continue
            if bracketed:
                report.note(
                    "missing_flag",
                    f"components.facade.invocation: the requirements pass optional "
                    f"'--{flag}' to '{command} {sub}' but it declares no such flag",
                )
            else:
                report.warning(
                    "missing_flag",
                    f"components.facade.invocation: the requirements pass '--{flag}' "
                    f"to '{command} {sub}' but it declares no such flag",
                )
    return len(seen)


def _resolve_span(span, program, commands):
    """`(command, subcommand_or_None)` for a backtick span, or None to skip it.

    Two phases, because prompts differ in whether lines start with the program
    name. `expense category add --name` drops `expense` and resolves
    (`category`, `add`); `product add --sku`, with no program word at all,
    resolves as written (`product`, `add`). The drop is only taken when the
    remainder names a declared command followed by a flag, a known subcommand,
    or nothing — so `expense frobnicate --x` (program plus an unknown word)
    is skipped rather than misread as a flag check on bare `expense`.
    """
    tokens = span.split()
    if tokens and tokens[0] == program:
        hit = _resolve_tokens(tokens[1:], commands)
        if hit is not None:
            return hit
    return _resolve_tokens(tokens, commands)


def _resolve_tokens(tokens, commands):
    """Resolve already-program-stripped tokens, or None to skip them."""
    if not tokens:
        return None
    word = tokens[0].strip("[](),.;:")
    if not SPAN_WORD.fullmatch(word):
        # Not a command word at all (`UNIQUE(category_id, ...)`): skip it.
        return None
    if word in commands:
        rest = tokens[1:]
        if not rest or rest[0].startswith("-") or rest[0].startswith("["):
            return word, None
        candidate = rest[0].strip("[](),.;:")
        if SPAN_WORD.fullmatch(candidate) and candidate in commands[word]:
            return word, candidate
        # A declared command followed by an unknown word (`expense frobnicate
        # --x`): guessing a leaf would manufacture findings, so skip it.
        return None
    owners = [name for name, subs in commands.items() if word in subs]
    if len(owners) == 1:
        # A subcommand written first (`expense report monthly --month` names
        # `report`, a subcommand of `expense`): judge the owning leaf.
        return owners[0], word
    return None


def _flags_in(span):
    """Yield `(flag, bracketed)` for every flag token in a backtick span."""
    for token in span.split():
        bracketed = token.startswith("[")
        match = FLAG_TOKEN.match(token)
        if match is None:
            continue
        yield match.group(1), bracketed


def _options_by_leaf(invocation):
    """Map `(command, subcommand_or_None)` to its option dests."""
    from kernel.codegen import option_dest

    options = {}
    entries = invocation.get("commands")
    if not isinstance(entries, list):
        return options
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            continue
        name = entry["name"].strip()
        options[(name, None)] = _dests_of(entry.get("options"), option_dest)
        for sub in entry.get("subcommands") or []:
            if isinstance(sub, dict) and isinstance(sub.get("name"), str):
                options[(name, sub["name"])] = _dests_of(sub.get("options"), option_dest)
    return options


def _dests_of(entries, option_dest):
    if not isinstance(entries, list):
        return []
    return [dest for dest in (option_dest(item) for item in entries) if dest]


def _flag_covered(flag, command, sub, options):
    """True when a leaf's flags supply the requirements' flag (aliases count)."""
    from kernel.codegen import bind_field

    dests = list(options.get((command, sub)) or [])
    if sub is None:
        # A bare command line files its flags wherever the parser reaches:
        # the command's own flags plus every subcommand's.
        for (name, _), leaf_dests in options.items():
            if name == command:
                dests.extend(d for d in leaf_dests if d not in dests)
    return bind_field(dests, flag) is not None
