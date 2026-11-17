"""Consistency checks for the persistence ports.

Covers the repositories (their entity names, interface names and methods) and
the entity mappings (table names and primary keys), which are the documents
that must agree with both data_models and components.
"""

from kernel.consistency.methods import check_method_list, is_missing
from kernel.consistency.naming import CLASS_SUFFIXES, MATCH_NONE, MATCH_VARIANT, normalize
from kernel.consistency.report import with_suggestions


def check_persistence_presence(documents, report):
    """An absent persistence_ports.json only matters if persistence was requested."""
    if "persistence_ports" not in documents.missing:
        return
    if _persistence_required(documents.get("components")):
        report.error(
            "missing_document",
            "MISSING: persistence_ports.json (components declare persistence.required=true)",
        )


def check_persistence_ports(ports, facts, report):
    """Validate the repositories, the entity mappings, and their agreement."""
    if not isinstance(ports, dict):
        return

    repositories = ports.get("repositories")
    mappings = ports.get("entity_mappings")

    if not isinstance(repositories, list) or not repositories:
        report.error("empty_section", "persistence_ports.repositories is empty")
    if not isinstance(mappings, list) or not mappings:
        report.error("empty_section", "persistence_ports.entity_mappings is empty")

    declared = _check_repositories(repositories, facts, report)
    _check_mappings(mappings, facts, report, declared)
    _check_crud_coverage(facts.crud_entities, declared, report)


def _persistence_required(components):
    if not isinstance(components, dict):
        return False
    persistence = components.get("persistence")
    return isinstance(persistence, dict) and persistence.get("required") is True


def _check_repositories(repositories, facts, report):
    """Check the repository list; return {normalized entity: declared entity}."""
    declared = {}
    if not isinstance(repositories, list):
        return declared

    seen_entities = {}
    seen_interfaces = {}

    for repository in repositories:
        if not isinstance(repository, dict):
            report.error("invalid_value", "persistence_ports: a repository entry is not an object")
            continue

        entity = repository.get("entity")
        interface = repository.get("interface_name")
        if is_missing(entity):
            report.error("invalid_identifier", "persistence_ports: a repository has no entity")
            continue

        label = interface if not is_missing(interface) else entity
        if is_missing(interface):
            report.error("invalid_identifier", f"persistence_ports: repository for '{entity}' has no interface_name")
        else:
            interface_key = interface.strip().lower()
            if interface_key in seen_interfaces:
                report.warning(
                    "duplicate_entry",
                    f"persistence_ports: interface '{interface}' is declared more than once",
                )
            seen_interfaces[interface_key] = interface

        entity_key = normalize(entity)
        if entity_key in seen_entities:
            report.error("duplicate_entry", f"persistence_ports: entity '{entity}' has more than one repository")
        seen_entities[entity_key] = entity
        declared[entity_key] = entity

        _check_repository_entity(entity, facts, report)
        check_method_list(repository.get("methods"), f"persistence_ports: {label}", report)

    return declared


def _check_repository_entity(entity, facts, report):
    if entity.endswith(CLASS_SUFFIXES):
        report.error(
            "class_name_entity",
            f"persistence_ports: repository entity '{entity}' is a class name, not a domain entity",
        )
        return
    if not facts.entities.names:
        return

    tier, resolved = facts.entities.resolve(entity)
    if tier is MATCH_NONE:
        report.warning(
            "unknown_reference",
            with_suggestions(
                f"persistence_ports: repository entity '{entity}' not found in data_models",
                facts.entities.suggest(entity),
            ),
        )
    elif tier is MATCH_VARIANT:
        report.warning(
            "name_variant",
            f"persistence_ports: repository entity '{entity}' is spelled '{resolved}' in data_models",
        )


def _check_mappings(mappings, facts, report, declared):
    if not isinstance(mappings, list):
        return

    mapped = {}
    seen_tables = {}
    seen_entities = set()

    for mapping in mappings:
        if not isinstance(mapping, dict):
            report.error("invalid_value", "persistence_ports: an entity_mapping is not an object")
            continue

        entity = mapping.get("entity")
        if is_missing(entity):
            report.error("invalid_identifier", "persistence_ports: an entity_mapping has no entity")
            continue

        entity_key = normalize(entity)
        if entity_key in seen_entities:
            report.error("duplicate_entry", f"persistence_ports: entity_mappings lists '{entity}' more than once")
        seen_entities.add(entity_key)
        mapped[entity_key] = entity

        table = mapping.get("table")
        if is_missing(table):
            report.error("invalid_identifier", f"persistence_ports: mapping for '{entity}' has no table")
        else:
            table_key = table.strip().lower()
            if table_key in seen_tables:
                report.warning("duplicate_entry", f"persistence_ports: table '{table}' is mapped more than once")
            seen_tables[table_key] = table

        _check_mapping_primary_key(mapping, entity, facts, report)

    _check_mapping_coverage(declared, mapped, report)


def _check_mapping_coverage(declared, mapped, report):
    for entity_key, entity in declared.items():
        if entity_key not in mapped:
            report.error("no_mapping", f"persistence_ports: repository entity '{entity}' has no entity_mapping")
        elif mapped[entity_key] != entity:
            report.warning(
                "name_variant",
                f"persistence_ports: repository entity '{entity}' is spelled "
                f"'{mapped[entity_key]}' in entity_mappings",
            )


def _check_mapping_primary_key(mapping, entity, facts, report):
    primary_key = mapping.get("primary_key")
    if is_missing(primary_key):
        report.error("invalid_identifier", f"persistence_ports: mapping for '{entity}' has no primary_key")
        return

    _, resolved = facts.entities.resolve(entity)
    declared_fields = facts.entities.fields_of(resolved or entity)
    if not declared_fields:
        return

    declared_keys = facts.entities.primary_keys(resolved or entity)
    if primary_key in declared_fields:
        if declared_keys and primary_key not in declared_keys:
            report.warning(
                "primary_key_mismatch",
                f"persistence_ports: mapping for '{entity}' keys on '{primary_key}' but the model marks "
                f"'{', '.join(declared_keys)}' as primary",
            )
        return

    if declared_keys and _is_composite_spelling(primary_key, declared_keys):
        return

    if declared_keys:
        report.error(
            "primary_key_mismatch",
            f"persistence_ports: mapping for '{entity}' uses primary_key '{primary_key}', which is not a "
            f"field of the entity (fields: {', '.join(declared_fields)}; "
            f"declared primary key: {', '.join(declared_keys)})",
        )
    else:
        report.warning(
            "missing_primary_key",
            f"persistence_ports: mapping for '{entity}' uses primary_key '{primary_key}' but the model "
            f"declares no primary key",
        )


def _is_composite_spelling(primary_key, primary_keys):
    """True when a key name is the declared keys joined, like 'a_b_composite'."""
    target = normalize(primary_key)
    for joined in {normalize("_".join(primary_keys)), normalize("_".join(sorted(primary_keys)))}:
        if joined and target.startswith(joined):
            return True
    return False


def _check_crud_coverage(crud_entities, declared, report):
    if not crud_entities or not declared:
        return

    covered = set(declared)
    for entity in crud_entities:
        if normalize(entity) not in covered:
            report.warning(
                "no_repository",
                f"consistency: crud_services entity '{entity}' has no matching repository in persistence_ports",
            )
