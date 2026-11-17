"""Structural check: can the grammar's literal braces ever close?

`grammar_check` validates rule syntax and catches undefined rules, but not a
grammar whose JSON literals cannot balance — for example an adapter rule that
opens `{` and never emits `}`. llama.cpp accepts such a grammar happily; the
only consequence is that the model can never finish a real object and takes the
empty-list escape instead.

This module expands the grammar (first alternative of each rule, bounded depth)
and counts the brackets in the literals it produces. It is a heuristic, but it
catches exactly the two defects that produced empty interaction_adapters: a
missing closing brace and a spurious opening brace.
"""

import re

IDENTIFIER_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9-]*")
REPETITION_PATTERN = re.compile(r"^\{\d+(,\d*)?\}")

PAIRS = (("{", "}"), ("[", "]"))
MAX_DEPTH = 16
MAX_VISITS = 400


def check(text):
    """Return a list of structural problems; empty means the braces balance."""
    definitions = definitions_of(text)
    if "root" not in definitions:
        return []

    budget = [MAX_VISITS]
    literals = expand("root", definitions, MAX_DEPTH, frozenset(), budget)
    if literals is None:
        return ["could not expand 'root' to check bracket balance"]

    problems = []
    for open_char, close_char in PAIRS:
        opened = literals.count(open_char)
        closed = literals.count(close_char)
        if opened != closed:
            problems.append(
                f"unbalanced {open_char}{close_char} in expanded literals: "
                f"{opened} '{open_char}' vs {closed} '{close_char}'"
            )
    return problems


def definitions_of(text):
    """Map each rule name to its body."""
    definitions = {}
    pattern = re.compile(r"^([A-Za-z][A-Za-z0-9-]*)\s*::=\s*(.*)$")
    for line in text.splitlines():
        match = pattern.match(line.strip())
        if match:
            definitions[match.group(1)] = match.group(2).strip()
    return definitions


def expand(name, definitions, depth, visiting, budget):
    """Concatenate the literal characters `name` can produce (first branch)."""
    if depth <= 0 or budget[0] <= 0 or name in visiting:
        return ""
    budget[0] -= 1
    body = definitions.get(name)
    if body is None:
        return ""

    return expand_body(body, definitions, depth - 1, visiting | {name}, budget)


def expand_body(body, definitions, depth, visiting, budget):
    """Expand one rule body, keeping only the literal characters."""
    body = first_alternative(body)
    produced = []
    index = 0

    while index < len(body):
        char = body[index]
        if char == '"':
            index, literal = read_literal(body, index)
            produced.append(literal)
        elif char == "[":
            index = skip_class(body, index)
        elif char == "(":
            index, skipped = skip_group(body, index)
            produced.append(
                expand_body(skipped, definitions, depth, visiting, budget)
            )
        elif char == "{":
            match = REPETITION_PATTERN.match(body[index:])
            index += match.end() if match else 1
        elif char.isalpha():
            match = IDENTIFIER_PATTERN.match(body[index:])
            reference = match.group(0)
            index += match.end()
            produced.append(
                expand(reference, definitions, depth, visiting, budget)
            )
        else:
            index += 1

    return "".join(produced)


def first_alternative(body):
    """The part of `body` before the first top-level `|`."""
    index = 0
    while index < len(body):
        char = body[index]
        if char == '"':
            index, _ = read_literal(body, index)
        elif char == "[":
            index = skip_class(body, index)
        elif char == "(":
            index, _ = skip_group(body, index)
        elif char == "|":
            return body[:index]
        else:
            index += 1
    return body


def read_literal(body, index):
    """Read the literal starting at a quote; return (next index, its content)."""
    index += 1
    content = []
    while index < len(body):
        char = body[index]
        if char == "\\":
            content.append(body[index : index + 2])
            index += 2
            continue
        if char == '"':
            return index + 1, unescape("".join(content))
        content.append(char)
        index += 1
    return len(body), unescape("".join(content))


def unescape(content):
    """Turn GBNF escapes into the characters they stand for."""
    result = content.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t")
    return result.replace("\\\\", "\\")


def skip_class(body, index):
    """Return the index just past the character class at `index`."""
    index += 1
    if index < len(body) and body[index] == "^":
        index += 1
    while index < len(body):
        if body[index] == "\\":
            index += 2
            continue
        if body[index] == "]":
            return index + 1
        index += 1
    return len(body)


def skip_group(body, index):
    """Return (index past the group, the group's contents)."""
    start = index + 1
    depth = 1
    index += 1
    while index < len(body):
        char = body[index]
        if char == '"':
            index, _ = read_literal(body, index)
            continue
        if char == "[":
            index = skip_class(body, index)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index + 1, body[start:index]
        index += 1
    return len(body), body[start:]
