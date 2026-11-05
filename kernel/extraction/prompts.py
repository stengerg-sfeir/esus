"""The extraction step prompts, each carrying an authoritative name block.

The block is produced from the previous step's output by
`kernel.extraction.vocabulary`, and the same vocabulary builds that step's
grammar, so the prompt and the grammar always agree about which names exist.
"""

import os

NAMES_HEADING = (
    "Authoritative names produced by the previous extraction step. "
    "Use only these names, copied character for character. "
    "Do not invent, abbreviate, rename or translate any of them."
)

# Putting the complete requirements in a fixed first system turn gives every
# extraction prompt the same long prefix. The backend can then reuse its KV
# cache for that prefix instead of re-prefilling 3.3k characters at every step.
# It is opt-in until it has passed the same acceptance runs as the old layout.
SHARED_CONTEXT = os.environ.get("ESUS_SHARED_CONTEXT") == "1"
SHARED_CONTEXT_SYSTEM = (
    "You are a software architect. The complete requirements are in this "
    "message. Use only facts stated here; the next message names the "
    "extraction task and the JSON shape to return."
)

# Shown to step B, the only step nothing constrains — see `intentions_block`.
# The closing warning matters as much as the list: step A's phrases name
# services, repositories and interfaces too, and B must not read those as
# entities.
INTENTIONS_HEADING = (
    "The use cases extracted from the requirements. They are the program's own "
    "words for what it does: read them for the things it keeps, and for the "
    "things it only passes through. They are NOT a data model — do not turn a "
    "use case, a service, a repository or an interface named here into an entity."
)

INTENTIONS_SYSTEM = (
    "Extract core intentions (use cases/services). Do not list details. "
    'Output in English as JSON: {"intentions": []}.'
)
ERRORS_SYSTEM = (
    "List the application error types the requirements need. Each entry is an exception class "
    "the program will raise: give it a 'name' ending in 'Error', a 'base' naming the built-in it "
    "derives from, and a one-sentence 'description' saying when it is raised. "
    "When the requirements NAME a type, use that exact name — a requirement that says "
    "'CategoryNotFoundError' means a class of exactly that name, character for character. When "
    "the requirements only DESCRIBE a failure without naming it — 'error handling for missing "
    "files', 'malformed CSV', 'invalid input' — give it a clear name of your own in the same "
    "style. "
    "Use only these bases: LookupError (a value that does not exist), ValueError (a value of the "
    "wrong kind or shape), KeyError (a missing key), PermissionError, OSError (a file or the "
    "system), RuntimeError (a state the program cannot proceed from), TypeError, Exception. "
    "If the requirements look a record up by its key, a name or another identifier, register a "
    "not-found error for that entity — one per entity that is looked up — so the method that "
    "reads it has a name for the case where it is missing. This is the commonest gap: a registry "
    "holding an error for a missing order but none for a missing invoice leaves the invoice "
    "lookup naming an error that no document declares. "
    "Do not invent an error for a failure the requirements never mention, and do not turn a "
    "validation rule into an error class: a row that is malformed and skipped is not an "
    "exception unless the requirements say the program must fail on it. "
    "A program whose requirements describe no failure at all has no errors: emit an empty list. "
    'Output strictly in English as JSON: {"errors": [{"name": "...", "base": "LookupError", '
    '"description": "..."}]}.'
)
INVARIANTS_SYSTEM = (
    "Identify the business and data invariants explicitly stated or directly implied by the "
    "requirements. Each invariant must be a single, unique, concrete statement. Do not repeat, "
    "paraphrase or generalize the same statement. Do not invent any not grounded in the "
    "requirements. Stop as soon as all distinct statements are listed. "
    "The examples below are shapes, not facts about this program: never output "
    "an example unless the requirements state it. "
    "Give every invariant a 'kind', which is exactly one of 'schema' or 'rule'. "
    "Use 'schema' when the invariant only restates how a single field is declared — its type, "
    "whether it is nullable or optional, whether it is unique, whether it is the primary key or "
    "a foreign key, or the set of values it may take. ALL of the following are 'schema', however "
    "they are worded: a field is optional, nullable or required; a field must be a boolean, an "
    "integer, a string, a date or a timestamp; a field must be a non-null date or a non-null "
    "timestamp; a field must be a non-negative or positive integer, or must be >= 0, or must be "
    ">= 1; a field must be unique; a field is a primary key or an auto-incremented key; a field "
    "must be one of a fixed set of values; a field's value must exist in another entity, whether "
    "written as 'must reference an existing X', 'must match Y in Z' or 'must be valid (exists in "
    "X)'. A condition attached to a type, nullability or numeric bound does not change this: "
    "'reorder_threshold must be a non-negative integer if provided' is 'schema', and "
    "'price_cents must be a positive integer' is 'schema'. "
    "Use 'rule' when the invariant constrains behaviour rather than one field: it relates two "
    "different fields to each other, it makes a claim that holds only in a named state, or it "
    "bounds an aggregate or a total. Examples of 'rule': 'wine.selling_price must be strictly "
    "greater than wine.cost_price', 'the total number of bottles assigned to a StorageLocation "
    "must not exceed its max_bottle_capacity', 'loan.return_date must be null if loan.status is "
    "active', 'shipment.delivered_at must be after shipment.shipped_at', 'stock_quantity must be >= 0 when "
    "the order is confirmed', 'book.available_copies must not exceed the number of copies added "
    "for that book'. A comparison between two different fields, or a limit on a sum or a total, "
    "makes an invariant a 'rule'. A conditional clause (if/when) makes it a 'rule' ONLY when the "
    "claim itself is about another field, an aggregate, or a state named in the data model — a "
    "bare type, nullability or numeric bound stays 'schema' even when a condition is attached. "
    "The data model listed above is authoritative: an invariant must agree with it. Never call a "
    "field unique or nullable when the model declares otherwise, and never state a rule about an "
    "entity or field the model does not define — a rule about a field that is not there cannot be "
    "enforced. Where an invariant and a declared attribute would disagree, the attribute is what "
    "the model says and the invariant must not contradict it. "
    'Output strictly in English as JSON: {"invariants": [{"text": "...", "kind": "schema"}, '
    '{"text": "...", "kind": "rule"}]}.'
)
DATA_MODELS_SYSTEM = (
    "Extract the data model. The FIRST field of every entity must be its primary key: set "
    "'primary_key' to true for it and false for every other field, set its 'unique' to true "
    "because a primary key is unique by definition, and never mark the primary key nullable. Set "
    "'unique' to true for every other field the requirements say must not repeat — a code, a "
    "number, an email, an ISBN or a reference that identifies one record — and false for the "
    "rest. A field a business rule calls unique is unique in the model too: the two are the same "
    "fact, and a model that says false while the rule says true contradicts itself. Use "
    "ONLY these types: 'int', 'string', 'boolean', 'decimal', 'datetime', 'date', "
    "'text', 'float'. For 'foreign_key' use null, or an object "
    '{"target_entity": "...", "target_field": "...", "relationship": "many_to_one"|"one_to_one"|'
    '"one_to_many"}. Give every field a status of "explicit" or "deduced". '
    "An entity is a thing the program KEEPS: it has a lifetime beyond one operation, because "
    "the program stores it, looks it up by an identifier, lists it, updates it, or reports "
    "totals over it. Data that is read from an input and written straight to an output is NOT "
    "an entity: a row that is parsed and re-emitted, a line that is transformed and passed on, "
    "a value that is only computed and printed — nothing stores these and nothing looks them "
    "up. If nothing in the requirements is kept, looked up or aggregated over, there is no "
    "entity to model and the correct answer is an empty list: "
    '{"data_models": []}. '
    "Never invent an entity the requirements do not name or describe: it must be possible to "
    "point at the requirements' own words for it, in whatever language they are written, and "
    "to say which stored thing those words describe. "
    "Output strictly in English as JSON."
)
COMPONENTS_SYSTEM = (
    "Classify the technology components. Facade type is one of cli, api, gui. "
    "For a cli facade you must describe the command-line surface the requirements ask for in "
    "'invocation', and then choose 'technology' to match that surface — the surface decides the "
    "technology, never the other way round. "
    "Set 'invocation' to null when the program accepts no arguments at all: a script whose whole "
    "job is to print or compute something from nothing takes nothing in, and inventing a parser "
    "for it is a defect rather than a default. "
    "Otherwise 'invocation' is an object with three lists. 'positional' holds arguments given by "
    "position, each with a name, a type and whether it is required. 'options' holds the flags a "
    "user passes; write a long option name with two dashes ('--output') and its short form with "
    "one ('-o'), and give each option a name, an optional short form, a type, whether it is "
    "required, and a default or null. 'commands' holds subcommands, each with a name, its own "
    "options, and its own 'subcommands'. "
    "A flat CLI — 'tool --opt value --opt2 value' — leaves 'commands' empty and lists its "
    "options directly. A hierarchical CLI — 'tool command --opt value', or "
    "'tool command subcommand --opt value' — names each command in 'commands' and any second "
    "level in that command's 'subcommands'. "
    "A command is the thing the program acts on — 'product', 'category' — and a subcommand is "
    "the verb it performs — 'add', 'list', 'update', 'delete'. When the requirements write "
    "'<thing> <verb>', the thing becomes a command and the verb becomes one of that command's "
    "subcommands; the verb is NEVER also an option of the command. "
    "Every command line the requirements list must appear in the surface, and each distinct "
    "thing the requirements act on is a command of its own: if they name 'book add', 'book "
    "list', 'book search', 'member add', 'member list' and 'borrow', the surface declares both "
    "'book' and 'member' as commands, and 'borrow' as a command in its own right — never as a "
    "subcommand of whichever thing was written first, and never omitted. A line whose form is "
    "'<program> <verb> --flag', with a single word between the program name and the first flag, "
    "makes that word a top-level command carrying its own options. A command that has "
    "subcommands carries no options of its own except the global ones ('-help', '-version'): "
    "the flags a verb needs ('--sku', '--name', '--id') belong to that verb's subcommand, not "
    "to the command that holds it. The same word must never appear both in a command's "
    "'options' and in that command's 'subcommands' — 'product add --sku' and 'product -add' "
    "cannot both be how a product is added. An option is a flag carrying one value, so its type "
    "is that value's shape ('str', 'int', 'bool', 'float', 'list'); 'dict' or 'object' is not "
    "an option type. Name each command once. "
    "Technology follows the surface: no arguments at all means 'none', because a plain main() "
    "needs no parser; positional arguments and no options means 'sys.argv'; any option means "
    "'argparse'; nested commands mean 'click'. If the requirements name a technology, use the "
    "name they give. If an api is requested but no technology is named, use flask; a gui "
    "without one, pyimgui. If the requirements store data but name no database, use sqlite. If "
    "the requirements store nothing at all — a program that only computes or prints, with no "
    "records to keep — then set required=false, technology=none, and leave crud_services empty; "
    "never add a database, a repository or an entity that the requirements do not ask for. "
    "external_access lists only the cloud services the requirements name. crud_services lists "
    "each bare domain entity the requirements ask to store (e.g. 'Book', 'Expense') at most "
    "once, each with a subset of "
    '["create", "read_one", "read_all", "update", "delete"]. Output strictly in English as JSON.'
)
CONTRACTS_SYSTEM = (
    "Extract high-level business service method signatures with parameters and return types. "
    "Include domain services and repository custom aggregates (e.g. "
    "get_total_by_category_and_month). Name each service exactly as the authoritative list does. "
    "Declare each method once, and give every method the parameters the requirements imply — a "
    "method that reads or writes an entity needs that entity's key and the fields it acts on. "
    "Where the operations block below names operations for an entity, the interface that owns "
    "that entity must declare a method for every one of them: a 'delete' needs a delete method "
    "that takes the entity's key, an 'update' needs an update method that takes the key and the "
    "fields it writes, and a 'create' needs a create or add method that takes the fields it "
    "writes. Do not declare an operation as supported and then omit the method that provides it. "
    "Those operations are a MINIMUM and not a maximum: having covered them, also declare the "
    "other methods the requirements imply for that entity — reading one record by its key, "
    "listing, and the custom queries, counts and aggregates the requirements describe. Do not "
    "stop at the operations list if the requirements ask for more. "
    "When the requirements describe a capability in prose rather than listing it, declare the "
    "method that provides it: 'customers should be able to search their orders and invoices' "
    "needs a search method that takes what is searched for and returns the matches, and "
    "'administrators can filter products by category' needs a filter method. A capability the "
    "CLI exposes but no method provides cannot be implemented. "
    "A state change the requirements describe needs the method that performs the transition, "
    "named for it: 'confirming an order reserves stock' needs a 'confirm_order', and "
    "'cancelling a confirmed order releases the reserved stock' needs a 'cancel_order'. A "
    "generic status setter is not a substitute — it does not say which transition it performs, "
    "so nothing the CLI names is implemented by a method of that name. "
    "Never emit a placeholder such as 'none', 'None', 'void', 'NoneType' or ':' as a parameter "
    "name or type. "
    "Where the requirements describe a failure a method can produce, name it in that method's "
    "'raises' list, copied exactly from the registered error types listed below; use an empty "
    "list for a method that raises none. Never name an error that is not registered, and never "
    "invent one here — the registry is the authoritative list. "
    "A method that creates a record cannot fail to find it: a create or an add performs no "
    "lookup, so never give a create-like method a not-found error. That error belongs to the "
    "read, update or delete method that really does look the record up. "
    "If the authoritative list is empty, or the requirements describe no domain entities at all, "
    'emit {"service_contracts": []} — never invent a service just to have something to write. '
    'Output strictly in English as JSON: {"service_contracts": [{"service_name": "...", "methods": '
    '[{"name": "...", "description": "...", "params": [{"name": "...", "type": "..."}], '
    '"return_type": "..."}]}]}.'
)
ADAPTERS_SYSTEM = (
    "Extract abstract interaction adapters mapping external input actions onto the domain service "
    "methods listed above. target_service and target_method MUST be copied exactly from that list, "
    "and target_param MUST be one of the parameters of the method you chose. When the method "
    "declares a parameter whose name is the input field's own name, map the field to THAT "
    "parameter: a field named 'category_id' goes to a parameter named 'category_id', never into "
    "an entity object beside it, because the method has already said where the value goes. "
    "Transforms: 'DIRECT', 'LOOKUP_ID', 'DECIMAL_TO_CENTS', 'ISO_DATE', 'CSV_LIST', 'ENUM_LOOKUP', 'BOOL_TO_ONE'. "
    "Choose the transform that matches the field's own name and type: 'DECIMAL_TO_CENTS' is for a "
    "money amount ('price', 'cost', 'amount', 'total', 'budget', 'limit'), never for a count, a "
    "quantity, a boolean or a description; 'CSV_LIST' is for a field that holds several values "
    "separated by commas, never for a single name, a description or a flag; 'ISO_DATE' is for a "
    "date or timestamp; 'LOOKUP_ID' is for a foreign-key identifier that must be resolved to an "
    "entity. Use 'BOOL_TO_ONE' only when a boolean presence flag supplies one for an integer threshold. Set 'lookup_entity' "
    "to an entity name when the transform is 'LOOKUP_ID', and to null for every other transform. "
    'Output strictly in English as JSON: {"interaction_adapters": [{"action_name": "...", '
    '"target_service": "...", "target_method": "...", "input_fields": [{"field_name": "...", '
    '"target_param": "...", "transform": "...", "lookup_entity": null, "required": true}]}]}.'
)
PERSISTENCE_SYSTEM = (
    "You are a software architect. Produce the persistence mappings for the entities listed above and "
    "the CUSTOM repository methods those requirements describe. "
    "Repository interfaces and their standard CRUD methods — create, read_one, read_all, update, "
    "delete — are generated mechanically, so do NOT emit those methods here. "
    "The repository list and the entity mappings are already fixed: emit one entry for each listed "
    "entity, in the order given, using exactly those entity names and, for each mapping, exactly "
    "the primary key shown. You choose the table name and, for each repository, only the additional "
    "query and aggregate methods the requirements actually describe. An empty methods list is "
    "correct when an entity has no such method. "
    "A repository holds the methods for its own entity only — never a method named after, or "
    "belonging to, any other entity in the list, and never an entity name used as a method name. "
    "Do not pad the list, and do not repeat a method you have already declared. Give each custom "
    "method a real description and return type. Declare the parameters the method's own name "
    "requires: a method that reads one record by a key, a name, an email or a date needs that "
    "key. Emit an empty params list [] only for a method that genuinely takes no argument, such "
    "as one that lists every record or reports an aggregate. Give every parameter the real name "
    "and type the requirements imply. "
    "Never emit a placeholder name or type such as 'none', 'None', 'void', 'NoneType' or ':'. "
    'Output strictly in English as JSON: {"persistence_ports": {"repositories": [{"entity": "...", '
    '"interface_name": "...", "methods": [{"name": "...", "description": "...", "params": '
    '[{"name": "...", "type": "..."}], "return_type": "..."}]}], "entity_mappings": [{"entity": '
    '"...", "table": "...", "primary_key": "...", "indexes": ["..."]}]}}.'
)


REPOSITORY_METHODS_SYSTEM = (
    "You are a software architect. Repository interfaces and their standard CRUD methods "
    "— create, read_one, read_all, update, delete — are generated mechanically from the "
    "data model. Produce only the CUSTOM query and aggregate methods the requirements "
    "describe for the listed repositories. The repository list and the entity names are "
    "fixed: emit one entry for each listed entity, in the order given. An empty methods "
    "list is correct when an entity has no custom method. Do not emit CRUD methods, do not "
    "invent a repository, do not repeat a method, and never use an entity name as a method "
    "name. Give each custom method a real description and return type. Declare the "
    "parameters the method's own name requires: a method that reads one record by a key, "
    "a name, an email or a date needs that key. Emit an empty params list [] only for a "
    "method that genuinely takes no argument. Never emit a placeholder name or type such "
    "as 'none', 'None', 'void', 'NoneType' or ':'. "
    'Output strictly in English as JSON: {"persistence_ports": {"repositories": ['
    '{"entity": "...", "interface_name": "...", "methods": [{"name": "...", '
    '"description": "...", "params": [{"name": "...", "type": "..."}], '
    '"return_type": "..."}]}]}}.'
)


def repository_methods(requirements, names):
    return _prompt(REPOSITORY_METHODS_SYSTEM, requirements, names)


def intentions(requirements):
    return _prompt(INTENTIONS_SYSTEM, requirements)


def data_models(requirements, names=None):
    return _prompt(DATA_MODELS_SYSTEM, requirements, names)


def intentions_block(intentions):
    """Step A's phrases, shown to step B — grounding, not a vocabulary.

    Step B is the only step with nothing to be constrained by. Every other step's
    grammar is generated from the names an earlier step produced, so it *cannot*
    invent one; A emits prose, which cannot become a vocabulary. B therefore ran
    on the raw requirements with an open grammar, and for a CSV-to-JSON converter
    — a program that models nothing — it filled the required shape from priors
    and invented `users, products, orders, order_items`.

    The phrases cannot close a grammar, but they can be **shown**: they are
    grounded in the requirements, so they supply the program's own words and
    remove the vacuum the priors filled. Show, don't constrain.

    Measured on the corpus, the two cases are exactly what this is for — expenses'
    phrases name **Category**, **Expense** and **Budget**; cli_tool's name a
    `main()` function, type hints and an `if __name__` guard, and nothing
    storable at all.
    """
    phrases = [
        phrase.strip()
        for phrase in (intentions or [])
        if isinstance(phrase, str) and phrase.strip()
    ]
    if not phrases:
        return None
    listed = "\n".join(f"- {phrase}" for phrase in phrases)
    return f"{INTENTIONS_HEADING}\n{listed}"


def invariants(requirements, names=None):
    return _prompt(INVARIANTS_SYSTEM, requirements, names)


COMPONENT_PLAN_SYSTEM = (
    "You are a software architect. Return only the CLI surface PLAN for this "
    "program. The full command subtrees are generated separately; do not emit "
    "them here. "
    "The plan has these fields: "
    "facade.type is cli, api or gui; facade.technology matches that surface. "
    "facade.invocation is null ONLY when the program accepts no arguments at "
    "all. Otherwise it is an object with positional arguments, global options, "
    "and a commands list. Each command in that list has only its name; do not "
    "emit command-specific options or subcommands in this plan. "
    "If the requirements name CLI commands, invocation must not be null and the "
    "command names must be present. A command with subcommands carries no "
    "command-specific options here. "
    "persistence says whether storage is required and its technology. "
    "external_access lists only named cloud services. "
    "crud_services lists each stored entity at most once, copied from the "
    "authoritative entity list, with a subset of create, read_one, read_all, "
    "update and delete. "
    "Do not invent an entity or a database. "
    'Output strictly in English as JSON. Use null for invocation only when '
    'there are no arguments; otherwise use an object with positional, options '
    'and commands. The commands are objects containing only a name. Include '
    'persistence, external_access and crud_services.'
)


def component_plan(requirements, names, extra=None):
    return _prompt(COMPONENT_PLAN_SYSTEM, requirements, names, extra)


def component_group(requirements, group, names, extra=None):
    text = (
        f"Top-level command: `{group}`.\n"
        "Use the requirements and authoritative names below. "
        "Fill only this command's subtree."
    )
    return _prompt(text, requirements, names, extra)


def components(requirements, names, extra=None):
    return _prompt(COMPONENTS_SYSTEM, requirements, names, extra)


def errors(requirements, names=None):
    return _prompt(ERRORS_SYSTEM, requirements, names)


def components_block(vocabulary):
    """The entity names step D may use, framed as a constraint, not a mandate.

    Presenting the entity list as a plain fact ("here are the entities") reads
    as evidence that there is a domain to persist, and flips
    components.persistence.required to true. The conditional wording keeps the
    list purely a closed vocabulary.
    """
    if not vocabulary.entity_names:
        return None
    return (
        "If, and only if, the requirements ask for stored data, crud_services may use "
        "only the entity names listed here, copied exactly. If the requirements ask for "
        "no stored data, leave crud_services empty and set persistence.required=false.\n"
        f"Entities:\n{vocabulary.entity_block()}"
    )


def command_lines_block(spans):
    """The enumerated command lines step D must cover, or None when empty.

    Each span is quoted verbatim — brackets included, so `[--stock]` still
    reads as optional — preceded by how to file it: `<thing> <verb> --flag`
    becomes command `<thing>` with subcommand `<verb>` carrying those flags,
    `<program> <verb> --flag` becomes a top-level command `<verb>` carrying
    its own. Not exhaustive by design: unparseable lines stay the model's
    judgment, and the checker (which parses with the same rules) verifies.
    """
    if not spans:
        return None
    listed = "\n".join(f"{number}. `{span}`" for number, span in enumerate(spans, start=1))
    block = (
        "Each of the following command lines must appear in the surface. "
        "Go through them one by one: a line `<thing> <verb> --flag` becomes "
        "command `<thing>` with subcommand `<verb>` carrying those flags, and "
        "a line `<program> <verb> --flag` becomes a top-level command `<verb>` "
        "carrying its own flags:\n" + listed
    )
    from kernel.extraction import command_lines

    if command_lines.uses_paths(spans):
        return _filed_block(spans)
    return block


def _filed_block(spans):
    """The command lines of a prompt that nests groups, each already filed.

    A small model asked to work out the nesting from a rule flattens it
    (`category` becomes a command of its own), but it transcribes well, so
    each line is shown with the command, the subcommand path and the flags it
    becomes. Used only for such a prompt; every other prompt's block is the
    text it always was.
    """
    from kernel.extraction import command_lines

    filed = []
    for number, (span, (command, path, flags)) in enumerate(
            zip(spans, command_lines.path_attribution(spans)), start=1):
        flag_text = " ".join(f"{'--' + name if required else '[--' + name + ']'}"
                             for name, required in flags) or "no flags"
        target = (f"command `{command}`, subcommand `{path}`" if path
                  else f"command `{command}`")
        filed.append(f"{number}. `{span}` -> {target} ({flag_text})")
    return (
        "Each of the following command lines must appear in the surface, filed "
        "exactly as shown: the command, then ONE subcommand whose name is the "
        "path written after it (words separated by a single space, such as "
        "`category add`), carrying exactly those flags. Never turn a word of "
        "the path into a command of its own.\n" + "\n".join(filed)
    )


def service_contracts(requirements, names):
    return _prompt(CONTRACTS_SYSTEM, requirements, names)


def adapters(requirements, names):
    return _prompt(ADAPTERS_SYSTEM, requirements, names)


def persistence_ports(requirements, names):
    return _prompt(PERSISTENCE_SYSTEM, requirements, names)


def entity_block(vocabulary):
    """The authoritative entity list, primary key marked."""
    return f"{NAMES_HEADING}\nEntities:\n{vocabulary.entity_block()}"


def service_block(vocabulary):
    """The authoritative service list with each method's parameters."""
    return f"{NAMES_HEADING}\nServices:\n{vocabulary.service_block()}"


def combined_block(vocabulary):
    """Entities and services, for a step that needs both (step G)."""
    sections = []
    if vocabulary.service_block():
        sections.append(f"Services:\n{vocabulary.service_block()}")
    if vocabulary.entity_block():
        sections.append(f"Entities:\n{vocabulary.entity_block()}")
    return f"{NAMES_HEADING}\n" + "\n".join(sections)


def requirements_block(vocabulary):
    """The entities step B produced and the operations step D requires.

    Steps E and H both own method sets — E for the repositories it declares, H
    for the rest — and neither was ever told which operations an entity is
    supposed to support. `components` said a `Category` supports a `delete`;
    nothing carried that to the step writing the methods, so no repository in
    inventory or library ever had one.
    """
    sections = []
    if vocabulary.entity_block():
        sections.append(f"Entities:\n{vocabulary.entity_block()}")
    if vocabulary.operations_block():
        sections.append(f"Required operations:\n{vocabulary.operations_block()}")
    if vocabulary.errors_block():
        sections.append(f"Registered error types:\n{vocabulary.errors_block()}")
    if not sections:
        return None
    return f"{NAMES_HEADING}\n" + "\n".join(sections)


def _prompt(system, requirements, names=None, extra=None):
    names_section = f"\n\n{names}\n" if names else "\n"
    if extra:
        names_section += f"\n{extra}\n"
    if SHARED_CONTEXT:
        return (
            f"<|im_start|>system\n{SHARED_CONTEXT_SYSTEM}\n"
            f"{requirements}<|im_end|>\n"
            f"<|im_start|>user\n{system}{names_section}<|im_end|>\n"
            "<|im_start|>assistant\n"
        )
    return (
        f"<|im_start|>system\n{system}{names_section}<|im_end|>\n"
        f"<|im_start|>user\n{requirements}<|im_end|>\n<|im_start|>assistant\n"
    )
