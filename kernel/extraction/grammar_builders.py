"""Grammars whose naming fields are closed to what an earlier step produced.

The point of these builders is that an invented name is not merely discouraged
but unrepresentable: the grammar contains no token sequence that spells it. For
step G the service, the method and the method's parameters are one coupled
chain, so a target_method that does not belong to the chosen target_service
cannot be written at all.

Each builder falls back to its `grammar_open` counterpart when the vocabulary
is empty, so a run always has a usable grammar.
"""

from kernel.extraction import grammar_open
from kernel.extraction.grammar import (
    MAX_ADAPTERS,
    MAX_CRUD_ENTITIES,
    MAX_INPUT_FIELDS,
    grammar,
    json_literal,
    json_list,
    json_object,
    json_object_tail,
    rule,
    string_choice,
)

TRANSFORM_BRANCH = "transform-branch"
LOOKUP_TRANSFORM = "LOOKUP_ID"


def components(vocabulary):
    """Step D, with crud_services.entity closed to the entities of step B."""
    entity_names = vocabulary.entity_names
    if not entity_names:
        return grammar_open.components()

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
            *grammar_open.facade_rules(),
            rule(
                "persistence-obj",
                json_object([("required", "boolean"), ("technology", "string")]),
            ),
            rule("external-list", json_list("string", 0, 10)),
            *distinct_entity_list("crud", entity_names, "operation-list"),
            rule("operation-list", json_list("operation", 1, 5)),
            rule("operation", grammar_open.OPERATIONS),
        ]
    )


def distinct_entity_list(prefix, entity_names, operations_rule):
    """Rules for a list holding each entity at most once, in vocabulary order.

    A plain `entity ("," entity)*` with a closed vocabulary does not prevent
    repetition — the model looped on `Category, Product, Product, Product…` and
    every repeat was a duplicate. Here the tail rules stop offering an entity
    once it has been emitted, so a repeat is unrepresentable rather than
    merely discouraged.
    """
    count = len(entity_names)
    rules = [rule(f"{prefix}-list", f'"[" ws {prefix}-pick-0 ws "]"')]

    for index, name in enumerate(entity_names):
        rules.append(
            rule(
                f"{prefix}-item-{index}",
                json_object([("entity", json_literal(name)), ("operations", operations_rule)]),
            )
        )
        rules.append(
            rule(
                f"{prefix}-pick-{index}",
                f"{prefix}-item-{index} {prefix}-tail-{index + 1} | {prefix}-pick-{index + 1}",
            )
        )
        rules.append(
            rule(
                f"{prefix}-tail-{index}",
                f'( ws "," ws {prefix}-item-{index} {prefix}-tail-{index + 1} )'
                f" | {prefix}-tail-{index + 1}",
            )
        )

    # An empty literal is the terminating case; a blank rule body would not parse.
    rules.append(rule(f"{prefix}-pick-{count}", '""'))
    rules.append(rule(f"{prefix}-tail-{count}", '""'))
    return tuple(rules)


def adapters(vocabulary):
    """Step G, closing target_service, target_method, target_param and lookup."""
    if not vocabulary.services:
        return grammar_open.adapters()

    entity_grammar = string_choice(vocabulary.entity_names)
    rules = []
    service_choices = []

    for service_index, service in enumerate(vocabulary.services):
        method_choices = []
        for method_index, method in enumerate(service.methods):
            field_rule = f"field-{service_index}-{method_index}"
            method_rule = f"method-{service_index}-{method_index}"
            # A method that declares no parameters can take no input fields. Letting
            # `string_choice` fall back to a free `string` here (its behaviour on an
            # empty alternation) silently un-coupled target_param: the adapter could
            # then name a parameter the method does not declare, which is exactly the
            # unknown_reference class this builder exists to remove.
            if method.params:
                rules.append(rule(field_rule, _field_head(string_choice(method.params))))
                max_fields = MAX_INPUT_FIELDS
            else:
                max_fields = 0
            rules.append(rule(method_rule, _method_tail(method.name, field_rule, max_fields)))
            method_choices.append(method_rule)

        service_rule = f"service-{service_index}"
        rules.append(rule(service_rule, _service_head(service.name, method_choices)))
        service_choices.append(service_rule)

    return grammar(
        [
            rule("root", json_object([("interaction_adapters", "adapter-list")])),
            rule("adapter-list", json_list("adapter", 1, MAX_ADAPTERS)),
            rule("adapter", _adapter_head(service_choices)),
            *_transform_rules(entity_grammar),
            *rules,
        ]
    )


def _adapter_head(service_choices):
    return " ".join(
        [
            '"{" ws',
            f'{json_literal("action_name")} ws ":" ws identifier ws "," ws',
            f'( {" | ".join(service_choices)} )',
        ]
    )


def _service_head(service_name, method_choices):
    return " ".join(
        [
            f'{json_literal("target_service")} ws ":" ws {json_literal(service_name)} ws "," ws',
            f'{json_literal("target_method")} ws ":" ws ( {" | ".join(method_choices)} )',
        ]
    )


def _method_tail(method_name, field_rule, max_fields):
    """The method, its input_fields list, and the adapter's closing brace.

    The closing `}` matters: without it the adapter object can never be
    terminated, the only completable form is an empty adapter list, and the
    model reliably takes that escape — which is exactly what happened before
    this brace was added.

    `max_fields` is 0 when the method declares no parameters, which forces an
    empty list rather than an unconstrained one.
    """
    return " ".join(
        [
            f'{json_literal(method_name)} ws "," ws',
            f'{json_literal("input_fields")} ws ":" ws',
            json_list(field_rule, 0, max_fields),
            'ws "}"',
        ]
    )


def _field_head(param_grammar):
    return " ".join(
        [
            '"{" ws',
            f'{json_literal("field_name")} ws ":" ws identifier ws "," ws',
            f'{json_literal("target_param")} ws ":" ws {param_grammar} ws "," ws',
            TRANSFORM_BRANCH,
        ]
    )


def _transform_rules(entity_grammar):
    """The transform tail; only LOOKUP_ID may name an entity."""
    rules = [
        rule(
            TRANSFORM_BRANCH,
            " | ".join(f"tf-{suffix}" for suffix, _, _ in grammar_open.TRANSFORMS),
        )
    ]
    for suffix, transform, lookup in grammar_open.TRANSFORMS:
        resolved_lookup = entity_grammar if transform == LOOKUP_TRANSFORM else lookup
        rules.append(
            rule(
                f"tf-{suffix}",
                json_object_tail(
                    [
                        ("transform", json_literal(transform)),
                        ("lookup_entity", resolved_lookup),
                        ("required", "boolean"),
                    ]
                ),
            )
        )
    return tuple(rules)
