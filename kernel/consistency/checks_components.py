"""Consistency checks for the extracted technology components.

Covers the facade and persistence choices, the external access list, and the
crud_services list whose entities must be bare domain model names.
"""

from kernel.consistency.methods import is_missing, is_placeholder
from kernel.consistency.naming import CLASS_SUFFIXES, MATCH_NONE, MATCH_VARIANT
from kernel.consistency.report import with_suggestions

CRUD_OPERATIONS = ("create", "read_one", "read_all", "update", "delete")
FACADE_TYPES = ("cli", "api", "gui")
NO_TECHNOLOGY = {"", "none"}


def check_components(components, index, report):
    """Validate components; return the crud_services entity names."""
    if not isinstance(components, dict):
        return ()

    _check_facade(components.get("facade"), report)
    _check_persistence(components.get("persistence"), report)
    _check_external_access(components.get("external_access"), report)
    entities = _check_crud_services(components.get("crud_services"), index, report)
    _check_persistence_has_something_to_store(components.get("persistence"), entities, report)
    return entities


def _check_facade(facade, report):
    if not isinstance(facade, dict):
        report.error("invalid_value", "components.facade should be an object")
        return
    facade_type = facade.get("type")
    if facade_type not in FACADE_TYPES:
        report.error(
            "unsupported_value",
            f"components.facade: type '{facade_type}' is not one of {', '.join(FACADE_TYPES)}",
        )
    if is_missing(facade.get("technology")) or is_placeholder(facade.get("technology")):
        report.warning("invalid_value", f"components.facade: type '{facade_type}' has no technology")


def _check_persistence(persistence, report):
    if not isinstance(persistence, dict):
        report.error("invalid_value", "components.persistence should be an object")
        return
    required = persistence.get("required")
    if not isinstance(required, bool):
        report.error("invalid_value", f"components.persistence: required should be a boolean, found {required!r}")
        return

    technology = persistence.get("technology")
    if required and _normalized_technology(technology) in NO_TECHNOLOGY:
        report.warning("invalid_value", f"components.persistence: required=true but technology is {technology!r}")
    if not required and _normalized_technology(technology) not in NO_TECHNOLOGY:
        report.warning("invalid_value", f"components.persistence: required=false but technology is {technology!r}")


def _normalized_technology(technology):
    return technology.strip().lower() if isinstance(technology, str) else ""


def _check_persistence_has_something_to_store(persistence, entities, report):
    """required=true with no crud entity is self-contradictory.

    The two fields disagree about whether anything is stored at all: persistence
    says it must be, crud_services names nothing to store. Nothing checked that
    pair, and the consequence is worse than silent — step H falls back to
    persisting every modelled entity when crud_services is empty, so the
    contradiction manufactures a repository list from entities the requirements
    never mentioned. That is what produced the CSV-to-JSON prompt's invented
    e-commerce schema: it declared sqlite, named no entity, and step H then
    emitted repositories for the four entities step B had made up.
    """
    if not isinstance(persistence, dict) or persistence.get("required") is not True:
        return
    if entities:
        return
    report.warning(
        "invalid_value",
        "components: persistence.required=true but crud_services is empty — "
        "nothing is named to persist",
    )


def _check_external_access(external_access, report):
    if external_access is None:
        return
    if not isinstance(external_access, list):
        report.error("invalid_value", "components.external_access should be a list")
        return
    for item in external_access:
        if is_missing(item):
            report.error("invalid_value", "components.external_access contains an entry that is not a string")
        elif is_placeholder(item):
            report.warning("placeholder_value", f"components.external_access contains the placeholder {item!r}")


def _check_crud_services(crud_services, index, report):
    if not isinstance(crud_services, list):
        report.error("invalid_value", "components.crud_services should be a list")
        return ()

    entities = []
    seen = set()
    for item in crud_services:
        if not isinstance(item, dict):
            report.error("invalid_value", "components.crud_services contains an entry that is not an object")
            continue
        entity = item.get("entity")
        if is_missing(entity):
            report.error("invalid_identifier", "components.crud_services has an entry with no entity")
            continue

        key = entity.strip().lower()
        if key in seen:
            report.warning("duplicate_entry", f"components.crud_services: '{entity}' is listed more than once")
        seen.add(key)
        entities.append(entity)

        _check_crud_entity(entity, index, report)
        _check_crud_operations(item.get("operations"), entity, report)

    return tuple(entities)


def _check_crud_entity(entity, index, report):
    if entity.endswith(CLASS_SUFFIXES):
        report.error(
            "class_name_entity",
            f"components.crud_services: '{entity}' is a class name, not a domain entity",
        )
        return
    if not index.names:
        return

    tier, resolved = index.resolve(entity)
    if tier is MATCH_NONE:
        report.warning(
            "unknown_reference",
            with_suggestions(
                f"components.crud_services: '{entity}' not found in data_models",
                index.suggest(entity),
            ),
        )
    elif tier is MATCH_VARIANT:
        report.warning(
            "name_variant",
            f"components.crud_services: '{entity}' is spelled '{resolved}' in data_models",
        )


def _check_crud_operations(operations, entity, report):
    if not isinstance(operations, list):
        report.error("invalid_value", f"components.crud_services: '{entity}' operations should be a list")
        return
    if not operations:
        report.warning("empty_section", f"components.crud_services: '{entity}' declares no operations")
        return
    for operation in operations:
        if operation not in CRUD_OPERATIONS:
            report.error(
                "unsupported_value",
                f"components.crud_services: '{entity}' declares unknown operation '{operation}'",
            )
