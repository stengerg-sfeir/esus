"""Consistency checks for the interaction adapters.

Each adapter maps an external action onto a domain service call, so every
field it declares must resolve against service_contracts (service and method)
and data_models (lookup entity).
"""

from dataclasses import dataclass, field

from kernel.consistency.methods import collect_methods, is_missing, is_placeholder, param_names
from kernel.consistency.naming import (
    MATCH_NONE,
    MATCH_VARIANT,
    SUGGESTION_LIMIT,
    match_known,
    normalize,
    suggest,
)
from kernel.consistency.report import with_suggestions

TRANSFORMS = ("DIRECT", "LOOKUP_ID", "DECIMAL_TO_CENTS", "ISO_DATE", "CSV_LIST", "ENUM_LOOKUP")
ADAPTER_AGGREGATION_THRESHOLD = 3
LOOKUP_TRANSFORM = "LOOKUP_ID"


@dataclass
class ServiceIndex:
    """The declared service contracts, addressable by name and method."""

    declared: dict = field(default_factory=dict)
    methods: dict = field(default_factory=dict)

    @classmethod
    def from_services(cls, services):
        index = cls()
        if not isinstance(services, list):
            return index
        for service in services:
            if not isinstance(service, dict):
                continue
            name = service.get("service_name")
            if is_missing(name):
                continue
            key = normalize(name)
            index.declared.setdefault(key, name)
            collected = index.methods.setdefault(key, {})
            for method in collect_methods(service):
                if method.get("name"):
                    collected.setdefault(normalize(method["name"]), method)
        return index

    @property
    def names(self):
        return sorted(set(self.declared.values()))

    def resolve(self, candidate):
        """Return (match_tier, declared_service_name_or_None)."""
        return match_known(candidate, self.names, strip_roles=True)

    def method(self, service_key, method_name):
        return self.methods.get(service_key, {}).get(normalize(method_name))

    def method_labels(self, service_key):
        methods = self.methods.get(service_key, {})
        return [method.get("name") for method in methods.values() if method.get("name")]

    def label(self, service_key):
        return self.declared.get(service_key, service_key)

    def suggest(self, candidate, limit=SUGGESTION_LIMIT):
        return suggest(candidate, self.names, limit)

    def suggest_method(self, service_key, candidate, limit=SUGGESTION_LIMIT):
        return suggest(candidate, self.method_labels(service_key), limit)


def check_interaction_adapters(adapters, services, facts, report):
    """Validate every adapter against the services and entities it references."""
    if adapters is None:
        return
    if not adapters:
        # A note, like data_models and service_contracts: a program whose data
        # model is empty has nothing for an adapter to invoke, and an empty
        # adapter list is the correct answer rather than a defect.
        report.note("empty_section", "interaction_adapters: list is empty")
        return

    service_index = ServiceIndex.from_services(services)
    unresolved = []
    checkable = 0

    for adapter in adapters:
        if not isinstance(adapter, dict):
            report.error("invalid_value", "interaction_adapters: an entry is not an object")
            continue

        action = adapter.get("action_name")
        if is_missing(action) or is_placeholder(action):
            report.error("invalid_identifier", "interaction_adapters: an adapter has no action_name")
            continue

        service_key, target_service = _resolve_target_service(adapter, action, service_index, report)
        if not is_missing(target_service):
            checkable += 1
        if service_key is None and not is_missing(target_service):
            unresolved.append((action, target_service))

        method = _check_target_method(adapter, action, service_key, service_index, report)
        _check_input_fields(adapter, action, method, facts, report)

    _report_unresolved_targets(unresolved, checkable, service_index, report)


def _resolve_target_service(adapter, action, service_index, report):
    """Return (normalized service key or None, raw target_service value)."""
    target_service = adapter.get("target_service")
    if is_missing(target_service):
        report.error("invalid_value", f"interaction_adapters: '{action}' has no target_service")
        return None, target_service

    tier, resolved = service_index.resolve(target_service)
    if tier is MATCH_NONE:
        return None, target_service

    if tier is MATCH_VARIANT:
        report.warning(
            "name_variant",
            f"interaction_adapters: '{action}' targets service '{target_service}' which is spelled "
            f"'{resolved}' in service_contracts",
        )
    return normalize(resolved), target_service


def _check_target_method(adapter, action, service_key, service_index, report):
    """Validate target_method; return the resolved method object when known."""
    target_method = adapter.get("target_method")
    if is_missing(target_method):
        report.error("invalid_value", f"interaction_adapters: '{action}' has no target_method")
        return None
    if service_key is None:
        return None

    method = service_index.method(service_key, target_method)
    if method is None:
        report.warning(
            "unknown_reference",
            with_suggestions(
                f"interaction_adapters: '{action}' targets method '{target_method}' which "
                f"{service_index.label(service_key)} does not declare",
                service_index.suggest_method(service_key, target_method),
            ),
        )
    return method


def _check_input_fields(adapter, action, method, facts, report):
    input_fields = adapter.get("input_fields")
    if not isinstance(input_fields, list):
        report.error("invalid_value", f"interaction_adapters: '{action}' input_fields should be a list")
        return
    # An action that takes no input legitimately declares an empty list.
    declared_params = set(param_names(method)) if method else None
    seen = set()

    for field_entry in input_fields:
        if not isinstance(field_entry, dict):
            report.error("invalid_value", f"interaction_adapters: '{action}' has an input field that is not an object")
            continue

        field_name = field_entry.get("field_name")
        if is_missing(field_name):
            report.error(
                "invalid_identifier",
                f"interaction_adapters: '{action}' has an input field with no field_name",
            )
            continue

        if normalize(field_name) in seen:
            report.warning(
                "duplicate_entry",
                f"interaction_adapters: '{action}' declares input field '{field_name}' more than once",
            )
        seen.add(normalize(field_name))

        _check_transform(field_entry, action, field_name, facts, report)
        _check_target_param(field_entry, action, field_name, declared_params, report)

        required = field_entry.get("required")
        if not isinstance(required, bool):
            report.error(
                "invalid_value",
                f"interaction_adapters: '{action}.{field_name}' required should be a boolean, found {required!r}",
            )


def _check_transform(field_entry, action, field_name, facts, report):
    transform = field_entry.get("transform")
    if transform not in TRANSFORMS:
        report.error(
            "unsupported_value",
            f"interaction_adapters: '{action}.{field_name}' transform '{transform}' is not one of "
            f"{', '.join(TRANSFORMS)}",
        )

    lookup_entity = field_entry.get("lookup_entity")
    if transform == LOOKUP_TRANSFORM and is_missing(lookup_entity):
        report.warning(
            "inconsistent_adapter",
            f"interaction_adapters: '{action}.{field_name}' uses LOOKUP_ID but sets no lookup_entity",
        )
        return
    if transform != LOOKUP_TRANSFORM and not is_missing(lookup_entity):
        report.warning(
            "inconsistent_adapter",
            f"interaction_adapters: '{action}.{field_name}' sets lookup_entity '{lookup_entity}' but its "
            f"transform is '{transform}'",
        )
        return
    if not is_missing(lookup_entity) and facts.entities.names:
        tier, resolved = facts.entities.resolve(lookup_entity)
        if tier is MATCH_NONE:
            report.warning(
                "unknown_reference",
                with_suggestions(
                    f"interaction_adapters: '{action}.{field_name}' looks up unknown entity '{lookup_entity}'",
                    facts.entities.suggest(lookup_entity),
                ),
            )
        elif tier is MATCH_VARIANT:
            report.warning(
                "name_variant",
                f"interaction_adapters: '{action}.{field_name}' looks up '{lookup_entity}' which is spelled "
                f"'{resolved}' in data_models",
            )


def _check_target_param(field_entry, action, field_name, declared_params, report):
    target_param = field_entry.get("target_param")
    if is_missing(target_param):
        report.error("invalid_value", f"interaction_adapters: '{action}.{field_name}' has no target_param")
        return
    if declared_params is None or target_param in declared_params:
        return

    tier, resolved = match_known(target_param, sorted(declared_params))
    if tier is MATCH_VARIANT:
        report.warning(
            "name_variant",
            f"interaction_adapters: '{action}.{field_name}' maps to param '{target_param}' which the method "
            f"spells '{resolved}'",
        )
    else:
        report.warning(
            "unknown_reference",
            with_suggestions(
                f"interaction_adapters: '{action}.{field_name}' maps to param '{target_param}' which the "
                f"target method does not declare",
                suggest(target_param, sorted(declared_params)),
            ),
        )


def _report_unresolved_targets(unresolved, checkable, service_index, report):
    if not unresolved:
        return

    targets = sorted({target for _, target in unresolved})
    if len(unresolved) >= ADAPTER_AGGREGATION_THRESHOLD:
        report.warning(
            "unresolved_adapter_target",
            f"interaction_adapters: {len(unresolved)} of {checkable} adapters target a service that "
            f"service_contracts does not declare ({', '.join(targets)}); service_contracts declares "
            f"{', '.join(service_index.names) or 'nothing'} — steps E and G name services differently.",
        )
        return

    for action, target in unresolved:
        report.warning(
            "unresolved_adapter_target",
            with_suggestions(
                f"interaction_adapters: '{action}' targets unknown service '{target}'",
                service_index.suggest(target),
            ),
        )
