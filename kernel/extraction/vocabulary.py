"""Authoritative name sets carried from one extraction step to the next.

A document produced by step n is turned into signatures here, and those
signatures drive both the prompt block of step n+1 and the GBNF rules that
close its naming fields. Keeping one representation for both is what stops the
prompt and the grammar from drifting apart.
"""

from dataclasses import dataclass

PLACEHOLDER_NAMES = frozenset(
    {"", "none", "null", "nil", "n/a", "na", "unknown", "todo", "tbd", "undefined"}
)

PRIMARY_KEY_FALLBACK = "id"


def clean(value):
    """Return a stripped name, or None when it is missing or a placeholder."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() in PLACEHOLDER_NAMES:
        return None
    return cleaned


@dataclass(frozen=True)
class MethodSignature:
    """One method of a service contract."""

    name: str
    params: tuple


@dataclass(frozen=True)
class EntitySignature:
    """One domain entity with its fields and its declared primary key."""

    name: str
    fields: tuple
    primary_key: str

    def summary(self):
        marked = [
            f"{field} pk" if field == self.primary_key else field for field in self.fields
        ]
        return f"{self.name}({', '.join(marked)})"


@dataclass(frozen=True)
class ServiceSignature:
    """One service contract with the methods it declares."""

    name: str
    methods: tuple

    def summary_lines(self):
        lines = []
        for method in self.methods:
            lines.append(f"{self.name}.{method.name}({', '.join(method.params)})")
        return lines or [f"{self.name}.<no methods>"]


@dataclass(frozen=True)
class CrudRequirement:
    """One entity and the operations its owner must provide."""

    entity: str
    operations: tuple

    def summary(self):
        return f"{self.entity}: {', '.join(self.operations)}"


@dataclass(frozen=True)
class Vocabulary:
    """Everything the next step may refer to by name."""

    entities: tuple = ()
    services: tuple = ()
    crud_entities: tuple = ()
    crud_operations: tuple = ()

    @property
    def entity_names(self):
        return tuple(entity.name for entity in self.entities)

    @property
    def primary_key_of(self):
        return {entity.name: entity.primary_key for entity in self.entities}

    @property
    def is_empty(self):
        return not (self.entities or self.services or self.crud_entities)

    def entity_block(self):
        return "\n".join(entity.summary() for entity in self.entities)

    def service_block(self):
        lines = []
        for service in self.services:
            lines.extend(service.summary_lines())
        return "\n".join(lines)

    def operations_block(self):
        return "\n".join(item.summary() for item in self.crud_operations)


def entities_from(data_models):
    """Build entity signatures from a parsed data_models list."""
    signatures = []
    for model in _dicts(data_models):
        name = clean(model.get("name"))
        if not name:
            continue
        fields = _field_names(model)
        if not fields:
            continue
        signatures.append(EntitySignature(name, fields, _primary_key(model, fields)))
    return tuple(signatures)


def _field_names(model):
    names = []
    for item in _dicts(model.get("fields")):
        field_name = clean(item.get("name"))
        if field_name:
            names.append(field_name)
    return tuple(names)


def _primary_key(model, fields):
    for item in _dicts(model.get("fields")):
        if item.get("primary_key") and clean(item.get("name")):
            return clean(item.get("name"))
    if PRIMARY_KEY_FALLBACK in fields:
        return PRIMARY_KEY_FALLBACK
    return fields[0]


def services_from(service_contracts):
    """Build service signatures from a parsed service_contracts list."""
    signatures = []
    for service in _dicts(service_contracts):
        name = clean(service.get("service_name"))
        if not name:
            continue
        methods = []
        for method in _dicts(service.get("methods")):
            method_name = clean(method.get("name"))
            if not method_name:
                continue
            methods.append(MethodSignature(method_name, _param_names(method)))
        if methods:
            signatures.append(ServiceSignature(name, tuple(methods)))
    return tuple(signatures)


def _param_names(method):
    names = []
    for param in _dicts(method.get("params")):
        param_name = clean(param.get("name"))
        if param_name:
            names.append(param_name)
    return tuple(names)


def crud_entity_names(components):
    """The bare entity names declared in components.crud_services."""
    if not isinstance(components, dict):
        return ()
    names = []
    for item in _dicts(components.get("crud_services")):
        entity = clean(item.get("entity"))
        if entity and entity not in names:
            names.append(entity)
    return tuple(names)


def crud_requirements(components):
    """Each stored entity and the operations step D says it must support.

    Step D decides which operations an entity supports; the interface that owns
    it has to provide them. Carrying the pair forward is what lets step E and
    step H be told what to implement instead of guessing from a four-word
    adjective like "standard CRUD" — which is how every `delete` went missing.
    """
    if not isinstance(components, dict):
        return ()
    requirements = []
    for item in _dicts(components.get("crud_services")):
        entity = clean(item.get("entity"))
        if not entity:
            continue
        operations = []
        for operation in item.get("operations") or []:
            if isinstance(operation, str) and operation.strip():
                operations.append(operation.strip())
        requirements.append(CrudRequirement(entity, tuple(operations)))
    return tuple(requirements)


def _dicts(value):
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
