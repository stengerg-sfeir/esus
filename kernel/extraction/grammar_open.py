"""Unconstrained grammars, used when a predecessor produced no usable values.

These are the historical grammars with two changes that apply unconditionally:
whitespace is bounded, and the adapter's `transform` is coupled to
`lookup_entity` so the two can no longer disagree. Everything else is left free
— these grammars are the degraded path, taken only when chaining has nothing to
carry forward, and a run that uses them logs that fact.
"""

from kernel.extraction.grammar import (
    GENERIC_TYPE_RULE,
    MAX_ADAPTERS,
    MAX_CRUD_ENTITIES,
    MAX_ENTITIES,
    MAX_EXTERNAL_ACCESS,
    MAX_FIELDS,
    MAX_INDEXES,
    MAX_INPUT_FIELDS,
    MAX_METHODS,
    MAX_SERVICES,
    grammar,
    json_literal,
    json_list,
    json_object,
    json_object_tail,
    rule,
)

NULL = '"null"'

# JSON booleans are bare GBNF literals. Passing them through json_literal()
# would quote them into the strings "true"/"false", and a non-empty string is
# truthy — which silently marked every field as a primary key.
BOOLEAN_TRUE = '"true"'
BOOLEAN_FALSE = '"false"'


def _enum(*values):
    return f"( {' | '.join(json_literal(value) for value in values)} )"


EXPLICIT_STATUS = _enum("explicit", "deduced")
RELATIONSHIPS = _enum("many_to_one", "one_to_one", "one_to_many")
OPERATIONS = _enum("create", "read_one", "read_all", "update", "delete")
FACADE_TYPES = _enum("cli", "api", "gui")

# (rule suffix, transform value, lookup_entity grammar). Only LOOKUP_ID may
# carry an entity; every other transform must emit JSON null, which is what
# stops the "sets lookup_entity X but transform is DIRECT" class of defect.
TRANSFORMS = (
    ("direct", "DIRECT", NULL),
    ("lookup", "LOOKUP_ID", "identifier"),
    ("decimal", "DECIMAL_TO_CENTS", NULL),
    ("iso-date", "ISO_DATE", NULL),
    ("csv", "CSV_LIST", NULL),
    ("enum", "ENUM_LOOKUP", NULL),
)


def method_rules():
    """The method block shared by service contracts and repositories."""
    return (
        rule("method-list", json_list("method", 1, MAX_METHODS)),
        rule(
            "method",
            json_object(
                [
                    ("name", "identifier"),
                    ("description", "string"),
                    ("params", "param-list"),
                    ("return_type", "string"),
                ]
            ),
        ),
        rule("param-list", json_list("param")),
        rule("param", json_object([("name", "identifier"), ("type", "string")])),
    )


def _field(is_primary):
    return json_object(
        [
            ("name", "identifier"),
            ("type", "generic-type"),
            ("primary_key", BOOLEAN_TRUE if is_primary else BOOLEAN_FALSE),
            ("nullable", BOOLEAN_FALSE if is_primary else "boolean"),
            ("unique", "boolean"),
            ("foreign_key", f'( {NULL} | foreign-key-obj )'),
            ("status", EXPLICIT_STATUS),
        ]
    )


def data_models():
    """Step B: the domain model, with the first field forced to be the key."""
    return grammar(
        [
            rule("root", json_object([("data_models", "entity-list")])),
            # Minimum 0: a program with nothing to store has no entities, and a
            # minimum of 1 forced the model to invent a domain instead. The same
            # mistake as the whitespace bound of §9.6, in the other direction.
            rule("entity-list", json_list("entity", 0, MAX_ENTITIES)),
            rule("entity", json_object([("name", "identifier"), ("fields", "field-list")])),
            rule(
                "field-list",
                f'"[" ws pk-field ( ws "," ws field ){{0,{MAX_FIELDS - 1}}} ws "]"',
            ),
            rule("pk-field", _field(True)),
            rule("field", _field(False)),
            rule(
                "foreign-key-obj",
                json_object(
                    [
                        ("target_entity", "identifier"),
                        ("target_field", "identifier"),
                        ("relationship", RELATIONSHIPS),
                    ]
                ),
            ),
            GENERIC_TYPE_RULE,
        ]
    )


def components():
    """Step D: facade, persistence choice, external access and CRUD services."""
    return grammar(
        [
            rule("root", json_object([("components", "components-object")])),
            rule(
                "components-object",
                json_object(
                    [
                        ("facade", "facade-obj"),
                        ("persistence", "persistence-obj"),
                        ("external_access", "external-list"),
                        ("crud_services", "crud-list"),
                    ]
                ),
            ),
            rule("facade-obj", json_object([("type", FACADE_TYPES), ("technology", "string")])),
            rule(
                "persistence-obj",
                json_object([("required", "boolean"), ("technology", "string")]),
            ),
            rule("external-list", json_list("string", 0, MAX_EXTERNAL_ACCESS)),
            rule("crud-list", json_list("crud-item", 0, MAX_CRUD_ENTITIES)),
            rule(
                "crud-item",
                json_object([("entity", "identifier"), ("operations", "operation-list")]),
            ),
            rule("operation-list", json_list("operation", 1, len(OPERATIONS.split(" | ")))),
            rule("operation", OPERATIONS),
        ]
    )


def service_contracts():
    """Step E: business service method signatures."""
    return grammar(
        [
            rule("root", json_object([("service_contracts", "contract-list")])),
            # Minimum 0 for the same reason as entity-list: no entities means no
            # services, and "at least one" turned that into an invented
            # UserService/PostService for a Hello-World script.
            rule("contract-list", json_list("contract", 0, MAX_SERVICES)),
            rule(
                "contract",
                json_object([("service_name", "identifier"), ("methods", "method-list")]),
            ),
            *method_rules(),
        ]
    )


def _transform_rules():
    """The transform/lookup tail of an input field, one rule per transform."""
    rules = [
        rule(
            "transform-branch",
            " | ".join(f"tf-{suffix}" for suffix, _, _ in TRANSFORMS),
        )
    ]
    for suffix, transform, lookup in TRANSFORMS:
        rules.append(
            rule(
                f"tf-{suffix}",
                json_object_tail(
                    [
                        ("transform", json_literal(transform)),
                        ("lookup_entity", lookup),
                        ("required", "boolean"),
                    ]
                ),
            )
        )
    return tuple(rules)


def adapters():
    """Step G: interaction adapters, with transform and lookup kept in step."""
    head = (
        f'{json_literal("field_name")} ws ":" ws identifier ws "," ws '
        f'{json_literal("target_param")} ws ":" ws identifier ws "," ws'
    )
    return grammar(
        [
            rule("root", json_object([("interaction_adapters", "adapter-list")])),
            rule("adapter-list", json_list("adapter", 0, MAX_ADAPTERS)),
            rule(
                "adapter",
                json_object(
                    [
                        ("action_name", "identifier"),
                        ("target_service", "identifier"),
                        ("target_method", "identifier"),
                        ("input_fields", "input-list"),
                    ]
                ),
            ),
            rule("input-list", json_list("input-field", 0, MAX_INPUT_FIELDS)),
            rule("input-field", f'"{{" ws {head} transform-branch'),
            *_transform_rules(),
        ]
    )


def persistence_ports():
    """Step H: repositories and entity mappings."""
    return grammar(
        [
            rule("root", json_object([("persistence_ports", "ports-object")])),
            rule(
                "ports-object",
                json_object(
                    [
                        ("repositories", "repository-list"),
                        ("entity_mappings", "mapping-list"),
                    ]
                ),
            ),
            rule("repository-list", json_list("repository", 1, MAX_ENTITIES)),
            rule(
                "repository",
                json_object(
                    [
                        ("entity", "identifier"),
                        ("interface_name", "identifier"),
                        ("methods", "method-list"),
                    ]
                ),
            ),
            rule("mapping-list", json_list("mapping", 1, MAX_ENTITIES)),
            rule(
                "mapping",
                json_object(
                    [
                        ("entity", "identifier"),
                        ("table", "identifier"),
                        ("primary_key", "identifier"),
                        ("indexes", "index-list"),
                    ]
                ),
            ),
            rule("index-list", json_list("identifier", 0, MAX_INDEXES)),
            *method_rules(),
        ]
    )


def phrase_list(document_key, maximum=40):
    """Step A: a document holding a flat list of sentences."""
    return grammar(
        [
            rule("root", json_object([(document_key, "string-list")])),
            rule("string-list", json_list("string", 0, maximum)),
        ]
    )


# Step C's two kinds of invariant. "rule" constrains behaviour — it relates two
# fields, holds only in one state, or bounds an aggregate — and is worth
# classifying into a kernel pattern. "schema" restates a field's own declaration
# (its type, nullability, uniqueness, key or allowed values): there is no
# operation in it and no pattern can be right, so step F skips it. The value is
# closed here, so the tag is a decision the grammar enforces rather than one a
# later step has to infer from the prose.
INVARIANT_KINDS = _enum("rule", "schema")


def invariant_list(document_key="invariants", maximum=40):
    """Step C: a list of tagged invariants, each a rule or a schema declaration."""
    return grammar(
        [
            rule("root", json_object([(document_key, "invariant-list")])),
            rule("invariant-list", json_list("invariant", 0, maximum)),
            rule(
                "invariant",
                json_object([("text", "string"), ("kind", INVARIANT_KINDS)]),
            ),
        ]
    )
