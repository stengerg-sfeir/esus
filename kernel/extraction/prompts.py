"""The extraction step prompts, each carrying an authoritative name block.

The block is produced from the previous step's output by
`kernel.extraction.vocabulary`, and the same vocabulary builds that step's
grammar, so the prompt and the grammar always agree about which names exist.
"""

NAMES_HEADING = (
    "Authoritative names produced by the previous extraction step. "
    "Use only these names, copied character for character. "
    "Do not invent, abbreviate, rename or translate any of them."
)

INTENTIONS_SYSTEM = (
    "Extract core intentions (use cases/services). Do not list details. "
    'Output in English as JSON: {"intentions": []}.'
)
INVARIANTS_SYSTEM = (
    "Identify the business and data invariants explicitly stated or directly implied by the "
    "requirements. Each invariant must be a single, unique, concrete rule (e.g. 'isbn must be "
    "unique', 'available_copies must be >= 0'). Do not repeat, paraphrase, or generalize the same "
    "rule. Do not invent rules not grounded in the requirements. Stop as soon as all distinct "
    "rules are listed. "
    "The data model listed above is authoritative: an invariant must agree with it. Never call a "
    "field unique or nullable when the model declares otherwise, and never state a rule about an "
    "entity or field the model does not define — a rule about a field that is not there cannot be "
    "enforced. Where an invariant and a declared attribute would disagree, the attribute is what "
    "the model says and the invariant must not contradict it. "
    'Output strictly in English as JSON: {"invariants": ["...", "..."]}.'
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
    "If the requirements define no records to store — a program that only computes, prints, "
    "parses or transforms and keeps nothing of its own — emit an empty list: "
    '{"data_models": []}. Never invent an entity the requirements do not mention. '
    "Output strictly in English as JSON."
)
COMPONENTS_SYSTEM = (
    "Classify the technology components. Facade type is one of cli, api, gui; if the requirements "
    "name none, use cli with technology argparse. If an api is requested but no technology is "
    "named, use flask; a gui without one, pyimgui. If the requirements store data but name no "
    "database, use sqlite. If the requirements store nothing at all — a program that only "
    "computes or prints, with no records to keep — then set required=false, technology=none, and "
    "leave crud_services empty; never add a database, a repository or an entity that the "
    "requirements do not ask for. external_access lists only the cloud services the requirements "
    "name. crud_services lists each bare domain entity the requirements ask to store (e.g. "
    "'Book', 'Expense') at most once, each with a subset of "
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
    "Never emit a placeholder such as 'none', 'None', 'void', 'NoneType' or ':' as a parameter "
    "name or type. "
    "If the authoritative list is empty, or the requirements describe no domain entities at all, "
    'emit {"service_contracts": []} — never invent a service just to have something to write. '
    'Output strictly in English as JSON: {"service_contracts": [{"service_name": "...", "methods": '
    '[{"name": "...", "description": "...", "params": [{"name": "...", "type": "..."}], '
    '"return_type": "..."}]}]}.'
)
ADAPTERS_SYSTEM = (
    "Extract abstract interaction adapters mapping external input actions onto the domain service "
    "methods listed above. target_service and target_method MUST be copied exactly from that list, "
    "and target_param MUST be one of the parameters of the method you chose. Transforms: 'DIRECT', "
    "'LOOKUP_ID', 'DECIMAL_TO_CENTS', 'ISO_DATE', 'CSV_LIST', 'ENUM_LOOKUP'. Set 'lookup_entity' "
    "to an entity name when the transform is 'LOOKUP_ID', and to null for every other transform. "
    'Output strictly in English as JSON: {"interaction_adapters": [{"action_name": "...", '
    '"target_service": "...", "target_method": "...", "input_fields": [{"field_name": "...", '
    '"target_param": "...", "transform": "...", "lookup_entity": null, "required": true}]}]}.'
)
PERSISTENCE_SYSTEM = (
    "You are a software architect. Produce the persistence ports for the entities listed above. "
    "The repository list and the entity mappings are already fixed: emit one entry for each listed "
    "entity, in the order given, using exactly those entity names and, for each mapping, exactly "
    "the primary key shown. You choose the interface_name, the table name and the method bodies. "
    "A repository holds the methods for its own entity only — never a method named after, or "
    "belonging to, any other entity in the list, and never an entity name used as a method name. "
    "The operations listed for an entity below are a MINIMUM, not a maximum: provide a method "
    "for every one of them, and then include the other standard CRUD methods that entity needs "
    "— reading one record by its key, listing, updating, deleting — plus the custom queries and "
    "aggregates the requirements mention for that entity. Emit four to eight methods per "
    "repository, and close the list once the requirements are covered: do not pad it, and do not "
    "repeat a method you have already declared. Give each method a real description and return "
    "type. Declare the parameters a method's own name "
    "requires: a create or an update needs the fields it writes, a delete needs the key it "
    "removes, and a method that reads one record by a key, a name, an email or a date needs that "
    "key — never emit such a method with an empty params list. Emit an empty params list [] only "
    "for a method that genuinely takes no argument, such as one that lists every record or "
    "reports an aggregate. Give every parameter the real name and type the requirements imply. "
    "Never emit a placeholder name or type such as 'none', 'None', 'void', 'NoneType' or ':'. "
    'Output strictly in English as JSON: {"persistence_ports": {"repositories": [{"entity": "...", '
    '"interface_name": "...", "methods": [{"name": "...", "description": "...", "params": '
    '[{"name": "...", "type": "..."}], "return_type": "..."}]}], "entity_mappings": [{"entity": '
    '"...", "table": "...", "primary_key": "...", "indexes": ["..."]}]}}.'
)


def intentions(requirements):
    return _prompt(INTENTIONS_SYSTEM, requirements)


def data_models(requirements):
    return _prompt(DATA_MODELS_SYSTEM, requirements)


def invariants(requirements, names=None):
    return _prompt(INVARIANTS_SYSTEM, requirements, names)


def components(requirements, names):
    return _prompt(COMPONENTS_SYSTEM, requirements, names)


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
    if not sections:
        return None
    return f"{NAMES_HEADING}\n" + "\n".join(sections)


def _prompt(system, requirements, names=None):
    names_section = f"\n\n{names}\n" if names else "\n"
    return (
        f"<|im_start|>system\n{system}{names_section}<|im_end|>\n"
        f"<|im_start|>user\n{requirements}<|im_end|>\n<|im_start|>assistant\n"
    )
