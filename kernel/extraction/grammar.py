"""GBNF primitives shared by every extraction grammar.

The grammars in llama.cpp are compiled lazily: `LlamaGrammar.from_string`
stores the text and only parses it when generation starts, so a malformed
grammar built at runtime would not fail until minutes into a run. Everything
assembled from these primitives is therefore passed through
`kernel.extraction.grammar_check` before it reaches the model.
"""

# Whitespace is bounded so a stall cannot consume a whole document (RC6a:
# library's components.json ended in 19 841 bytes of tabs). The bound must be
# *generous*, though: a model that cannot lay out its output changes what it
# writes, not just how it formats.
#
# Measured twice, on the two steps that show it most clearly. Intentions, on the
# library prompt:
#
#     {0,2} ->  0    {0,8} ->  9    {0,16} ->  9    {0,32} -> 14
#     {0,64} -> 10    *    -> 12
#
# Filled method parameters in service_contracts, on the inventory prompt:
#
#     {0,2} -> 17    {0,8} ->  9    {0,16} ->  0    {0,64} -> 16    * -> 17
#
# `{0,16}` is the bad spot in both: tight enough to change the model's strategy
# yet loose enough to look plausible, where `{0,2}` at least fails loudly. A
# generous bound keeps the anti-stall property — a run is capped at 64 characters
# per `ws`, so chained whitespace wastes little — and measures the same as
# unbounded. `\r` is included because the pre-change grammars accepted it.
WS_RULE = r"ws ::= [ \t\n\r]{0,64}"

BOOLEAN_RULE = r'boolean ::= "true" | "false"'

# The unescaped branch excludes control characters. Without that exclusion the
# model can emit a raw newline or tab inside a string, and the document it
# returns is not JSON at all — `Invalid control character at: line 12`. A
# control character must be written as the escape sequence it stands for.
STRING_RULE = (
    r'string ::= "\"" ([^"\\\n\r\t] | "\\" ["\\/bfnrt] | "\\u" [0-9a-fA-F] '
    r'[0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F])* "\""'
)

GENERIC_TYPE_RULE = (
    r'generic-type ::= "\"int\"" | "\"string\"" | "\"boolean\"" | "\"decimal\"" | '
    r'"\"datetime\"" | "\"date\"" | "\"text\"" | "\"float\""'
)

# A name is an identifier, not free text. Every grammar wrote names as `string`,
# so the model could emit the key's own colon as the value — one library run
# produced a method named `': '`, which the checker rejected as a method with no
# name, and parameter names of `': '` and `'return_type: '`. Restricting names to
# [A-Za-z_][A-Za-z0-9_]* makes all three unrepresentable. Fields that hold prose
# (descriptions, return types, technologies, external service names) keep
# `string`, because a type may be `Optional[Member]` or `datetime.date`.
IDENTIFIER_RULE = r'identifier ::= "\"" [a-zA-Z_] [a-zA-Z0-9_]* "\""'

SHARED_RULES = (STRING_RULE, BOOLEAN_RULE, IDENTIFIER_RULE, WS_RULE)

# Repetition caps. A closed vocabulary bounds which items can appear but not
# how many, so every list is capped to keep a model that loops from filling the
# token budget with a valid-but-endless document.
MAX_ENTITIES = 20
MAX_FIELDS = 40
MAX_CRUD_ENTITIES = 20
MAX_SERVICES = 20
# A cap must never truncate legitimate output: a prompt that describes 13
# methods must yield 13. This is a ceiling against runaway generation only, and
# repeated method names are removed deterministically instead (see
# pipeline._deduplicate) — a length bound cannot fix a loop, it can only cut it
# short, and cutting it short is what would lose the 13th method.
MAX_METHODS = 30
MAX_PARAMS = 12
MAX_ADAPTERS = 40
MAX_INPUT_FIELDS = 12
MAX_INDEXES = 10
MAX_EXTERNAL_ACCESS = 10


def json_literal(text):
    """A GBNF literal matching `text` as a JSON string, e.g. '"\"Wine\""'."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return '"\\"' + escaped + '\\""'


def alternation(values):
    """A GBNF alternation of JSON string literals, or None when empty."""
    if not values:
        return None
    return " | ".join(json_literal(value) for value in values)


def rule(name, body):
    """Render `name ::= body`."""
    return f"{name} ::= {body}"


def json_list(item, minimum=0, maximum=None, separator='ws "," ws'):
    """A JSON array of `item`.

    `minimum` of 1 forbids the empty list; `maximum` caps the length so a model
    that loops cannot emit an endless, valid document.
    """
    if maximum is None:
        if minimum == 0:
            return f'"[" ws ( {item} ( {separator} {item} )* )? ws "]"'
        return f'"[" ws {item} ( {separator} {item} )* ws "]"'

    tail = maximum - minimum
    if minimum == 0:
        if maximum == 0:
            return '"[" ws "]"'
        return f'"[" ws ( {item} ( {separator} {item} ){{0,{tail}}} )? ws "]"'
    if tail == 0:
        return f'"[" ws {item} ws "]"'
    return f'"[" ws {item} ( {separator} {item} ){{0,{tail}}} ws "]"'


def grammar(body_rules):
    """Join a set of rule strings into one grammar document."""
    lines = list(body_rules) + list(SHARED_RULES)
    return "\n".join(lines)


def json_object(pairs):
    """A JSON object grammar from (key, value-grammar) pairs.

    Building objects from key/value pairs keeps the quoting of JSON keys in one
    place instead of spread across a hundred hand-escaped literals.
    """
    parts = ['"{" ws']
    for index, (key, value) in enumerate(pairs):
        if index:
            parts.append('ws "," ws')
        parts.append(f'{json_literal(key)} ws ":" ws {value}')
    parts.append('ws "}"')
    return " ".join(parts)


def string_choice(values):
    """An alternation of JSON string literals, or `string` when empty."""
    text = alternation(values)
    return f"( {text} )" if text else "string"


def json_object_tail(pairs):
    """The tail of an already-open JSON object: its pairs, then the brace.

    A rule that continues an object must not open a second `{`. Building such a
    tail with json_object() emits a leading brace, which silently produces
    malformed JSON — `"target_param": "id", {"transform": ...` — rather than a
    grammar error.
    """
    parts = []
    for index, (key, value) in enumerate(pairs):
        if index:
            parts.append('ws "," ws')
        parts.append(f'{json_literal(key)} ws ":" ws {value}')
    parts.append('ws "}"')
    return " ".join(parts)
