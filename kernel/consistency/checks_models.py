"""Consistency checks for the extracted data models.

Covers field-level defects (duplicate or unnamed fields, missing or nullable
primary keys) and foreign keys, which are the only cross-entity references
inside data_models.json.
"""

from kernel.consistency.methods import is_missing
from kernel.consistency.naming import EntityIndex, MATCH_NONE, MATCH_VARIANT
from kernel.consistency.report import with_suggestions

RELATIONSHIPS = ("many_to_one", "one_to_one", "one_to_many")


def check_data_models(models, report):
    """Validate data_models and return the EntityIndex built from it."""
    index = EntityIndex.from_models(models)
    if models is None:
        return index
    if not models:
        # A note, not an error: the checker cannot see the requirements, so it
        # cannot tell "this program has no records" from "the step failed". The
        # contradictory case — persistence required but nothing named to
        # persist — is caught in checks_components, which can see both fields.
        report.note("empty_section", "data_models: list is empty")
        return index

    seen = {}
    for model in models:
        if not isinstance(model, dict):
            report.error("invalid_value", "data_models: an entry is not an object")
            continue
        name = model.get("name")
        if is_missing(name):
            report.error("invalid_identifier", "data_models: a model has no name")
            continue
        key = name.strip().lower()
        if key in seen:
            report.error("duplicate_entry", f"data_models: duplicate model name '{name}'")
            continue
        seen[key] = name
        _check_model(model, name, index, report)

    return index


def _check_model(model, name, index, report):
    fields = model.get("fields")
    if not isinstance(fields, list):
        report.error("invalid_value", f"data_models: model '{name}' has no fields list")
        return
    if not fields:
        report.warning("empty_section", f"data_models: model '{name}' has no fields")

    field_names, primary_keys, fields_by_name = _collect_fields(fields, name, report)

    seen = {}
    for field_name in field_names:
        key = field_name.strip().lower()
        if key in seen:
            report.error(
                "duplicate_entry",
                f"data_models: model '{name}' declares field '{field_name}' more than once",
            )
        seen[key] = field_name

    _check_primary_keys(name, primary_keys, fields_by_name, report)
    _check_foreign_keys(name, fields_by_name, index, report)


def _collect_fields(fields, model_name, report):
    field_names = []
    primary_keys = []
    fields_by_name = {}

    for item in fields:
        if not isinstance(item, dict):
            report.error("invalid_value", f"data_models: model '{model_name}' has a field that is not an object")
            continue
        field_name = item.get("name")
        if is_missing(field_name):
            report.error("invalid_identifier", f"data_models: model '{model_name}' has a field with no name")
            continue
        field_names.append(field_name)
        fields_by_name[field_name] = item
        if item.get("primary_key"):
            primary_keys.append(field_name)

    return field_names, primary_keys, fields_by_name


def key_uniqueness_contradicted(field):
    """True when a primary-key field declares `unique=false`.

    A primary key is unique by definition, so the two flags contradict each
    other. The single definition shared by the checker
    (`_check_primary_keys`) and the repair
    (`repairs.repair_primary_key_uniqueness`).
    """
    return bool(isinstance(field, dict) and field.get("primary_key")) \
        and field.get("unique") is False


def _check_primary_keys(model_name, primary_keys, fields_by_name, report):
    if not primary_keys:
        report.warning("missing_primary_key", f"data_models: model '{model_name}' declares no primary key")
        return
    for key in primary_keys:
        field = fields_by_name.get(key, {})
        if field.get("nullable"):
            report.warning(
                "nullable_primary_key",
                f"data_models: {model_name}.{key} is a primary key but nullable=true",
            )
        if key_uniqueness_contradicted(field):
            # `unique` was never read anywhere in this package, so the value
            # was free to be wrong on every model.
            report.warning(
                "non_unique_primary_key",
                f"data_models: {model_name}.{key} is a primary key but unique=false",
            )


def _check_foreign_keys(model_name, fields_by_name, index, report):
    for field_name, field in fields_by_name.items():
        foreign_key = field.get("foreign_key")
        if not isinstance(foreign_key, dict):
            continue

        target = foreign_key.get("target_entity")
        if is_missing(target):
            report.error(
                "invalid_value",
                f"data_models: {model_name}.{field_name} has a foreign_key with no target_entity",
            )
            continue

        tier, resolved = index.resolve(target)
        if tier is MATCH_NONE and index.names:
            report.warning(
                "unknown_reference",
                with_suggestions(
                    f"data_models: {model_name}.{field_name} FK targets unknown entity '{target}'",
                    index.suggest(target),
                ),
            )
            continue
        if tier is MATCH_VARIANT:
            report.warning(
                "name_variant",
                f"data_models: {model_name}.{field_name} FK target '{target}' is spelled "
                f"'{resolved}' elsewhere",
            )

        _check_foreign_key_target_field(model_name, field_name, foreign_key, resolved or target, index, report)

        relationship = foreign_key.get("relationship")
        if relationship not in RELATIONSHIPS:
            report.error(
                "unsupported_value",
                f"data_models: {model_name}.{field_name} FK relationship '{relationship}' "
                f"is not one of {', '.join(RELATIONSHIPS)}",
            )


def _check_foreign_key_target_field(model_name, field_name, foreign_key, target_entity, index, report):
    target_field = foreign_key.get("target_field")
    if is_missing(target_field):
        report.error("invalid_value", f"data_models: {model_name}.{field_name} FK has no target_field")
    elif target_field not in index.fields_of(target_entity):
        report.warning(
            "unknown_reference",
            with_suggestions(
                f"data_models: {model_name}.{field_name} FK targets field '{target_field}' "
                f"which {target_entity} does not declare",
                index.suggest_field(target_entity, target_field),
            ),
        )
