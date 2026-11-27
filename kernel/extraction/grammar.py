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

# Role suffixes the rest of the pipeline relies on. The checker pairs a
# service with its repository by name, the not-found repair looks for
# `<Entity>NotFoundError`, and the generator decides whether a holder is a
# service or a repository from its name. Leaving the suffix free made those
# relationships depend on the model remembering an English convention. These
# rules make a name without its role suffix unrepresentable.
#
# `Error` and `Exception` are both accepted because the requirements name both
# spellings (`CategoryNotFoundError`, `BudgetExceededException`); the suffix
# itself is what carries the meaning, not one particular word.
ERROR_NAME_RULE = (
    r'error-name ::= "\"" [a-zA-Z_] [a-zA-Z0-9_]* ("Error" | "Exception") "\""'
)
SERVICE_NAME_RULE = (
    r'service-name ::= "\"" [a-zA-Z_] [a-zA-Z0-9_]* ("Service" | "Repository") "\""'
)
REPOSITORY_NAME_RULE = (
    r'repository-name ::= "\"" [a-zA-Z_] [a-zA-Z0-9_]* "Repository" "\""'
)

# A subcommand name that is a path of one to three words ("category add"). Only
# the grammar of a prompt that nests command groups includes it (see
# `grammar_open.facade_rules`); `identifier` stays the name rule everywhere else.
PATH_NAME_RULE = (
    r'cli-path ::= "\"" [a-zA-Z_] [a-zA-Z0-9_]* '
    r'( " " [a-zA-Z_] [a-zA-Z0-9_]* )? ( " " [a-zA-Z_] [a-zA-Z0-9_]* )? "\""'
)

# A command-line option is written with its dashes ("--output", "-o"), which
# `identifier` cannot express because it must start with a letter. One leading
# dash followed by an alphanumeric keeps "-", "--" and "- " unrepresentable, so
# an option always has a name of its own.
OPTION_NAME_RULE = r'option-name ::= "\"" "-" [a-zA-Z0-9] [a-zA-Z0-9-]* "\""'

# The only options a command that *has* subcommands may declare. One word used as
# both a flag and a subcommand of the same command is the defect this closes:
# inventory listed `-add, -list, -update, -delete, -restock, -report` beside the
# subcommands `add, list, ...`, and 60 repeated `-search` and `-update` the same
# way — the same word twice in one command. Two prompt sentences asking for it not
# to were both ignored, so the shape is closed instead: `facade_rules` builds a
# command as an alternation in which one branch has subcommands and only these
# option names, and the other has no subcommands and any options. No alternative
# is left that could hold both. The same closure as `OPTION_TYPE_RULE`, applied to
# a name.
GLOBAL_OPTION_NAME_RULE = (
    r'global-option-name ::= "\"-help\"" | "\"--help\"" | '
    r'"\"-version\"" | "\"--version\""'
)

# What an option carries. Leaving this as `string` let the model write `dict`,
# `none` and even `positional` as an option's type, and then loop: inventory came
# back with an options list of twenty-one entries that were all named `-add`, the
# type changing on each one (`none`, `dict`, `positional`, `str`, `int`) — a
# generation that never terminates because nothing was left to decide. An option
# carries one value and the value has one of a few shapes, so the field is closed
# the way `generic-type` closes a field's type.
OPTION_TYPE_RULE = (
    r'option-type ::= "\"str\"" | "\"int\"" | "\"float\"" | "\"bool\"" | "\"list\""'
)

# The built-in an application error derives from. Closed to the Python builtins a
# domain error realistically subclasses, so the generated class has a real base
# and not prose: `"whatever seems right"` is not a base class.
BASE_ERROR_RULE = (
    r'base-error ::= "\"LookupError\"" | "\"ValueError\"" | "\"KeyError\"" | '
    r'"\"RuntimeError\"" | "\"PermissionError\"" | "\"OSError\"" | '
    r'"\"TypeError\"" | "\"Exception\""'
)

SHARED_RULES = (
    STRING_RULE,
    BOOLEAN_RULE,
    IDENTIFIER_RULE,
    ERROR_NAME_RULE,
    SERVICE_NAME_RULE,
    REPOSITORY_NAME_RULE,
    WS_RULE,
)

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
# Caps for the CLI surface. `commands` nests exactly one level
# (`command ... subcommand ...`), which is what the prompts describe; a deeper
# grammar would need a recursive rule for no case the corpus contains.
MAX_CLI_ARGS = 12
MAX_CLI_OPTIONS = 20
MAX_CLI_COMMANDS = 20
MAX_CLI_SUBCOMMANDS = 20
# Error types one program declares, and the number a single method may raise.
MAX_ERRORS = 20
MAX_RAISES = 6


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
