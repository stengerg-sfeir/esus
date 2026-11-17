"""The LLM context for a method no pattern covers: import this, don't rebuild it.

A `missing_pattern` gap (`NO_MATCH`, `NO_PATTERN_IN_DOMAIN`) is a method the
generator must implement without a pattern to follow. Guessing from the method
text alone repeats the classifier's failure with less evidence; the context
that exists — what the program is for (intentions), the rules it must honour
(invariants), the shape of the records (data models), what the classifier
reached for and why it was refused (claim + rejection), and how sibling
methods on the same service were implemented (neighbours) — is assembled here,
once, so every gap is decided from the same evidence.

`build_gap_context(documents, entry)` takes the extracted document bodies as a
plain `{name: body}` dict and one pattern_matches entry, and returns a bundle
dict. `render_gap_context(bundle)` renders it as the prompt section. Both are
total: an unresolvable source or a missing document yields thinner sections,
never an exception.
"""

from kernel.consistency.checks_phrases import phrase_text
from kernel.consistency.naming import normalize, strip_role_suffix

SOURCE_CONTRACT = "contract:"


def build_gap_context(documents, entry):
    """Assemble the decision context for a gap match."""
    documents = documents if isinstance(documents, dict) else {}
    entry = entry if isinstance(entry, dict) else {}
    service_name, method_name = _split_source(entry.get("source"))
    method = _find_method(documents.get("service_contracts"), service_name, method_name)
    entities = _entities_for(documents.get("data_models"), service_name, method_name)
    return {
        "method": {
            "source": entry.get("source"),
            "text": entry.get("text"),
            "params": list(method.get("params") or []) if method else [],
            "return_type": method.get("return_type") if method else None,
            "raises": list(method.get("raises") or []) if method else [],
            "description": method.get("description") if method else None,
        },
        "entities": entities,
        "intentions": _phrases(documents.get("intentions")),
        "invariants": _rule_invariants(documents.get("invariants"), entities),
        "claimed": {
            "pattern_id": entry.get("claimed_pattern_id"),
            "rejection": entry.get("rejection"),
        },
        "neighbours": _neighbours(
            documents.get("service_contracts"), documents.get("pattern_matches"),
            service_name, method_name,
        ),
    }


def render_gap_context(bundle):
    """Render a bundle as the LLM prompt section for one gap method."""
    lines = []
    method = bundle.get("method") or {}
    lines.append(f"Method: {method.get('text')}")
    if method.get("return_type") is not None:
        lines.append(f"Returns: {method.get('return_type')}")
    if method.get("raises"):
        lines.append(f"Raises: {', '.join(str(name) for name in method['raises'])}")
    for entity in bundle.get("entities") or []:
        fields = ", ".join(
            field.get("name", "?") for field in entity.get("fields", [])
            if isinstance(field, dict)
        )
        lines.append(f"Entity {entity.get('name')}: {fields}")
    intentions = bundle.get("intentions") or []
    if intentions:
        lines.append("Intentions:")
        lines.extend(f"- {text}" for text in intentions)
    invariants = bundle.get("invariants") or []
    if invariants:
        lines.append("Invariants:")
        lines.extend(f"- {text}" for text in invariants)
    claimed = bundle.get("claimed") or {}
    if claimed.get("pattern_id"):
        lines.append(
            f"Refused pattern {claimed['pattern_id']}: {claimed.get('rejection')}"
        )
    neighbours = bundle.get("neighbours") or []
    if neighbours:
        lines.append("Same-service methods and their patterns:")
        lines.extend(f"- {text} -> {pattern}" for text, pattern in neighbours)
    return "\n".join(lines)


def _split_source(source):
    """`(service, method)` from a `contract:Service.method` source, else `(None, None)`."""
    if not isinstance(source, str) or not source.startswith(SOURCE_CONTRACT):
        return None, None
    reference = source.split(":", 1)[1]
    if "." not in reference:
        return None, None
    service, method = reference.rsplit(".", 1)
    return service or None, method or None


def _find_method(services, service_name, method_name):
    """The contract method object, or None when unresolvable."""
    if not isinstance(services, list) or not service_name or not method_name:
        return None
    for service in services:
        if not isinstance(service, dict) or service.get("service_name") != service_name:
            continue
        for method in service.get("methods") or []:
            if isinstance(method, dict) and method.get("name") == method_name:
                return method
    return None


def _entities_for(data_models, service_name, method_name):
    """The data models the method is about: named in it or in its service."""
    if not isinstance(data_models, list):
        return []
    names = [
        model.get("name") for model in data_models
        if isinstance(model, dict) and model.get("name")
    ]
    mentioned = set()
    haystacks = [method_name, strip_role_suffix(service_name or "")]
    for name in names:
        key = normalize(name)
        if key and any(key in normalize(part or "") for part in haystacks if part):
            mentioned.add(name)
    if not mentioned:
        return []
    return [model for model in data_models
            if isinstance(model, dict) and model.get("name") in mentioned]


def _phrases(items):
    """Every phrase text, whatever document shape carries it."""
    if not isinstance(items, list):
        return []
    return [text for text in (phrase_text(item) for item in items) if text]


def _rule_invariants(invariants, entities):
    """The behaviour invariants constraining the method's entities.

    `schema` invariants restate field declarations the models already carry, so
    only `rule` ones travel; an invariant naming no model at all constrains
    nothing generatable and is skipped, as is everything when the method is
    about no known entity.
    """
    if not isinstance(invariants, list) or not entities:
        return []
    names = {normalize(entity.get("name") or "") for entity in entities}
    kept = []
    for invariant in invariants:
        if not isinstance(invariant, dict) or invariant.get("kind") != "rule":
            continue
        text = phrase_text(invariant)
        if not text:
            continue
        lowered = normalize(text)
        if any(name and name in lowered for name in names):
            kept.append(text)
    return kept


def _neighbours(services, matches, service_name, method_name):
    """Other methods of the same service with decided patterns, as `(text, id)`."""
    if not isinstance(matches, list) or not service_name:
        return []
    decided = {}
    for entry in matches:
        if not isinstance(entry, dict):
            continue
        source = entry.get("source") or ""
        if not source.startswith(f"{SOURCE_CONTRACT}{service_name}."):
            continue
        if entry.get("decision") != "decided":
            continue
        name = source.rsplit(".", 1)[-1]
        if name != method_name and entry.get("pattern_id"):
            decided[name] = (entry.get("text"), entry.get("pattern_id"))
    if not isinstance(services, list):
        return []
    ordered = []
    for service in services:
        if not isinstance(service, dict) or service.get("service_name") != service_name:
            continue
        for method in service.get("methods") or []:
            if isinstance(method, dict) and method.get("name") in decided:
                ordered.append(decided[method["name"]])
    return ordered
