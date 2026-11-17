"""Schema invariants derived from the data model, without a model call.

Step C used to ask the small model for both business rules and field-level
facts: a field's type, nullability, uniqueness, primary key, foreign key,
default and allowed values. Those facts are already in `data_models.json`;
asking for them again spends output tokens and lets the model contradict the
model it is supposed to describe.

`SCHEMA` text is the kind the collector already skips in step F, so these
entries cost nothing downstream. The model keeps the part only it can write:
rules relating fields, aggregates, states and operations.
"""

import re

_TYPE_WORDS = {
    "int": "integer",
    "integer": "integer",
    "float": "number",
    "double": "number",
    "decimal": "number",
    "str": "string",
    "string": "string",
    "text": "string",
    "bool": "boolean",
    "boolean": "boolean",
    "date": "date",
    "datetime": "datetime",
    "timestamp": "datetime",
}


def _field_names(entity):
    return [field.get("name") for field in entity.get("fields") or []
            if isinstance(field, dict) and isinstance(field.get("name"), str)]


def _composite_groups(entity, requirements):
    """Composite unique keys named by the requirements for one entity."""
    names = {name.lower() for name in _field_names(entity)}
    if len(names) < 2 or not isinstance(requirements, str):
        return []
    groups = []

    def add(tokens):
        resolved = []
        for token in tokens:
            lowered = str(token).lower()
            if lowered in names and lowered not in resolved:
                resolved.append(lowered)
        if len(resolved) >= 2 and tuple(resolved) not in groups:
            groups.append(tuple(resolved))

    for match in re.finditer(r"UNIQUE\s*\(([^)]*)\)", requirements, re.I):
        add(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", match.group(1)))
    for match in re.finditer(
            r"unique\s+(?:constraint\s+)?(?:on|over|for)\s*\(([^)]*)\)",
            requirements, re.I):
        add(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", match.group(1)))
    for match in re.finditer(
            r"([A-Za-z_][A-Za-z0-9_]*(?:\s*(?:,|and)\s*[A-Za-z_][A-Za-z0-9_]*)+)"
            r"\s+must\s+be\s+unique\s+together", requirements, re.I):
        add(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", match.group(1)))
    return [tuple(name for name in group) for group in groups]



def _enum_values(field_name, requirements):
    """The slash/`one of` vocabulary a requirement gives one field, or []."""
    if not isinstance(requirements, str):
        return []
    field = re.escape(field_name)
    match = re.search(rf"\b{field}\b\s*\(([^)]*/[^)]*)\)", requirements, re.I)
    if match:
        return [value.strip(" `'\"") for value in match.group(1).split("/")
                if value.strip(" `'\"")]
    match = re.search(
        rf"\b{field}\b[^.\n]*?must be one of\s*([^.\n]+)", requirements, re.I)
    if match:
        values = re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))
        if values:
            return values
    return []

def _numeric_bound(entity_name, field_name, requirements):
    """`(word, value)` for a documented non-negative/positive bound, or None."""
    if not isinstance(requirements, str):
        return None
    field = re.escape(field_name)
    patterns = (
        (rf"\b{field}\b[^.\n]*?\bnon-negative\b", ("non-negative", "0")),
        (rf"\b{field}\b[^.\n]*?\bpositive\b", ("positive", "1")),
        (rf"\b{field}\b[^.\n]*?>=\s*0\b", (">=", "0")),
        (rf"\b{field}\b[^.\n]*?>\s*0\b", (">", "0")),
    )
    for pattern, bound in patterns:
        if re.search(pattern, requirements, re.I):
            return bound
    return None


def schema_invariants(documents, requirements=""):
    """`[{text, kind: 'schema'}]` derived from the data models."""
    entries = []
    seen = set()

    def add(text):
        key = " ".join(text.lower().split())
        if key not in seen:
            seen.add(key)
            entries.append({"text": text, "kind": "schema"})

    for entity in documents.get("data_models") or []:
        if not isinstance(entity, dict):
            continue
        entity_name = entity.get("name")
        if not isinstance(entity_name, str) or not entity_name.strip():
            continue
        fields = [field for field in entity.get("fields") or []
                  if isinstance(field, dict) and field.get("name")]
        for field in fields:
            name = field["name"]
            declared = str(field.get("type") or "").strip().lower()
            type_word = _TYPE_WORDS.get(declared)
            if field.get("primary_key"):
                add(f"{entity_name}.{name} must be an auto-incremented "
                    f"integer primary key with default value None")
            elif type_word:
                article = "an" if type_word[0] in "aeiou" else "a"
                add(f"{entity_name}.{name} must be {article} {type_word}")
            if not field.get("primary_key") and field.get("nullable") is False:
                add(f"{entity_name}.{name} must not be null")
            if not field.get("primary_key") and field.get("unique"):
                add(f"{entity_name}.{name} must be unique")
            enum_values = _enum_values(name, requirements)
            if enum_values:
                add(f"{entity_name}.{name} must be one of "
                    + ", ".join(repr(value) for value in enum_values))
            foreign = field.get("foreign_key")
            if isinstance(foreign, dict) and foreign.get("target_entity"):
                target = foreign["target_entity"]
                target_field = foreign.get("target_field") or "id"
                add(f"{entity_name}.{name} must reference an existing "
                    f"{target}.{target_field}")
            if field.get("default") is not None and not field.get("primary_key"):
                add(f"{entity_name}.{name} must default to {field['default']}")
            bound = _numeric_bound(entity_name, name, requirements)
            if bound is not None:
                word, value = bound
                if word in (">=", ">"):
                    add(f"{entity_name}.{name} must be {word} {value}")
                else:
                    add(f"{entity_name}.{name} must be {word}")

        for group in _composite_groups(entity, requirements):
            add(f"{entity_name} must have a unique constraint on "
                f"({', '.join(group)})")
    return entries


def merge_invariants(schema, rules):
    """Schema first, then the model's rules, with exact duplicates removed."""
    merged = []
    seen = set()
    for item in list(schema) + list(rules or []):
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        key = " ".join(text.lower().split())
        if key in seen:
            continue
        seen.add(key)
        merged.append({"text": text.strip(),
                       "kind": item.get("kind") if item.get("kind") in
                       ("schema", "rule") else "rule"})
    return merged
