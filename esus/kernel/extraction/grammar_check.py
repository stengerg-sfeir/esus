"""A preflight linter for generated GBNF grammars.

`LlamaGrammar.from_string` does not parse its argument: it stores the text and
compiles it when generation starts. A grammar assembled at runtime from a
vocabulary could therefore be malformed and only fail minutes into a run, after
the prompt has been prefilled — the worst possible moment. This module catches
that before the first token is generated.

It is deliberately conservative: it parses the same surface syntax llama.cpp
does (one `name ::= body` definition per line, literals in double quotes,
character classes in brackets, `{m,n}` repetition) and reports anything it
cannot account for.
"""

import re

from kernel.extraction.grammar_balance import check as check_balance

RULE_PATTERN = re.compile(r"^([A-Za-z][A-Za-z0-9-]*)\s*::=\s*(.*)$")
REPETITION_PATTERN = re.compile(r"^\{\d+(,\d*)?\}")
ROOT_RULE = "root"


class GrammarError(ValueError):
    """Raised when a generated grammar is malformed."""


def check(text):
    """Return a list of problems; an empty list means the grammar is usable."""
    problems = []
    definitions = {}

    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        match = RULE_PATTERN.match(stripped)
        if not match:
            problems.append(f"line {number}: not a rule definition: {stripped[:48]!r}")
            continue
        name, body = match.group(1), match.group(2).strip()
        if not body:
            problems.append(f"rule '{name}' has an empty body")
        elif name in definitions:
            problems.append(f"rule '{name}' is defined more than once")
        definitions[name] = body

    if ROOT_RULE not in definitions:
        problems.append("grammar defines no 'root' rule")

    for name, body in definitions.items():
        references, rule_problems = _scan_rule(name, body)
        problems.extend(rule_problems)
        for reference in references:
            if reference not in definitions:
                problems.append(f"rule '{name}' references undefined rule '{reference}'")

    # Rule syntax can be perfect while the literal braces never close, which is
    # what silently produced empty adapter lists.
    problems.extend(check_balance(text))

    return problems


def assert_valid(text, label="grammar"):
    """Raise GrammarError listing every problem found in `text`."""
    problems = check(text)
    if problems:
        detail = "\n  ".join(problems[:20])
        raise GrammarError(f"{label} is malformed ({len(problems)} problem(s)):\n  {detail}")


def _scan_rule(name, body):
    """Walk one rule body, returning (referenced rule names, problems)."""
    references = []
    problems = []
    index = 0
    length = len(body)

    while index < length:
        char = body[index]
        if char == '"':
            index, problem = _skip_literal(body, index)
            if problem:
                problems.append(f"rule '{name}': {problem}")
        elif char == "[":
            index, problem = _skip_class(body, index)
            if problem:
                problems.append(f"rule '{name}': {problem}")
        elif char == "{":
            match = REPETITION_PATTERN.match(body[index:])
            if not match:
                problems.append(f"rule '{name}': malformed repetition at {body[index:index + 12]!r}")
                index += 1
            else:
                index += match.end()
        elif char.isalpha():
            start = index
            while index < length and (body[index].isalnum() or body[index] == "-"):
                index += 1
            references.append(body[start:index])
        else:
            index += 1

    if body.rstrip().endswith("|"):
        problems.append(f"rule '{name}' ends with an unclosed alternation")

    return references, problems


def _skip_literal(body, index):
    """Advance past the double-quoted literal starting at `index`."""
    index += 1
    while index < len(body):
        char = body[index]
        if char == "\\":
            index += 2
            continue
        if char == '"':
            return index + 1, None
        index += 1
    return len(body), "unterminated string literal"


def _skip_class(body, index):
    """Advance past the character class starting at the bracket."""
    index += 1
    if index < len(body) and body[index] == "^":
        index += 1
    while index < len(body):
        char = body[index]
        if char == "\\":
            index += 2
            continue
        if char == "]":
            return index + 1, None
        index += 1
    return len(body), "unterminated character class"
