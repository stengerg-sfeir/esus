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

# What a field's own name has to say for a transform to be right for it. A
# transform describes how a value's *representation* changes, which no field
# declares, so the only evidence is the name — this is therefore a name-based
# rule like `missing_parameters`, and it is deliberately narrow: it judges only
# the three transforms whose meaning implies a kind of value, and stays silent on
# DIRECT, LOOKUP_ID and ENUM_LOOKUP. Measured on the corpus it finds eleven in
# expenses (`name` transformed as a comma-separated list, `description` converted
# to cents, `icon` as a list), one in inventory, one in gui (`stock_quantity` as a
# list) and one in library (`copies` to cents).
MONEY_FIELD_HINTS = (
    "price", "cost", "amount", "total", "cents", "balance", "salary", "budget",
    "limit", "spend", "income", "value", "fee", "payment", "revenue", "subtotal",
)
DATE_FIELD_HINTS = (
    "date", "day", "month", "year", "time", "timestamp", "due", "expiry", "expires",
    "created", "updated", "start", "end",
)
CSV_FIELD_HINTS = ("list", "ids", "tags", "items", "fields", "columns", "values", "names")


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
        _check_transform_fits_the_field(field_entry, action, field_name, report)
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


def _check_transform_fits_the_field(field_entry, action, field_name, report):
    """The transform must match the kind of value the field's name describes.

    A transform is a claim about a value's representation, and the document never
    records a field's representation — only its name and its type. So this is
    judged on the name, and only for the three transforms that name a kind of
    value. A count is not a money amount and a single name is not a list, which is
    what the rule catches.
    """
    transform = field_entry.get("transform")
    lowered = field_name.strip().lower()
    if transform == "DECIMAL_TO_CENTS" and not _mentions(lowered, MONEY_FIELD_HINTS):
        report.warning(
            "mismatched_transform",
            f"interaction_adapters: '{action}.{field_name}' is converted with DECIMAL_TO_CENTS, "
            f"which is for a money amount — the field's name does not describe one",
        )
    elif transform == "CSV_LIST" and not _mentions(lowered, CSV_FIELD_HINTS):
        report.warning(
            "mismatched_transform",
            f"interaction_adapters: '{action}.{field_name}' is read as a comma-separated list, "
            f"but the field's name describes one value",
        )
    elif transform == "ISO_DATE" and not _mentions(lowered, DATE_FIELD_HINTS):
        report.warning(
            "mismatched_transform",
            f"interaction_adapters: '{action}.{field_name}' is parsed as a date, but the field's "
            f"name describes something else",
        )


def _mentions(name, hints):
    return any(hint in name for hint in hints)


def _check_target_param(field_entry, action, field_name, declared_params, report):
    target_param = field_entry.get("target_param")
    if is_missing(target_param):
        report.error("invalid_value", f"interaction_adapters: '{action}.{field_name}' has no target_param")
        return
    if declared_params is None:
        return

    # A field whose own name is a parameter of the method belongs to that
    # parameter, and the check needs no judgement: the method has already said
    # where the value goes. Deciding otherwise silently drops the field —
    # expenses' `add_expense` sends `category_id` into the `expense` object while
    # the method declares a `category_id` of its own, and `update_budget` sends
    # `month` into `budget` while a `month` parameter exists. Both were accepted
    # because only "is this a parameter at all" was asked.
    declared = {normalize(name) for name in declared_params}
    if normalize(field_name) in declared and normalize(field_name) != normalize(target_param):
        report.warning(
            "misplaced_field",
            f"interaction_adapters: '{action}.{field_name}' maps to param '{target_param}', but the "
            f"target method declares a param named '{field_name}' — the field belongs to that one",
        )
        return

    if target_param in declared_params:
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
