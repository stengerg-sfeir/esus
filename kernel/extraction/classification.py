"""Step F: classify invariants and contract methods into kernel patterns.

This step used to be silent and dominated run time. It now reports one line per
item, which both removes the appearance of a hang and makes the per-item cost
visible in the run log.
"""

from kernel.classifier.hierarchical_classifier import classify_requirement_2step, load_catalog

FALLBACK_PATTERN = "CUSTOM_OR_STANDARD_CRUD"


def classify_documents(classifier, documents, log):
    """Classify every invariant and contract method; return the matches."""
    catalog = load_catalog()
    items = classification_items(documents)

    if not items:
        log.write("[ok] step patterns: nothing to classify")
        return []

    matches = []
    total = len(items)
    for index, (source, text) in enumerate(items, start=1):
        result = classify_requirement_2step(classifier, text, catalog)
        pattern_id = result["pattern_id"]
        confidence = result["confidence"]
        log.write(f"  [{index}/{total}] {source} -> {pattern_id} ({confidence:.2f})")

        if pattern_id != FALLBACK_PATTERN:
            matches.append(
                {
                    "source": source,
                    "text": text,
                    "domain": result["domain"],
                    "pattern_id": pattern_id,
                    "confidence": round(confidence, 4),
                }
            )
    return matches


def classification_items(documents):
    """The (source label, text) pairs to classify, in document order."""
    items = []
    for invariant in _string_list(documents.get("invariants")):
        items.append(("invariant", invariant))
    for contract in _dict_list(documents.get("service_contracts")):
        service = contract.get("service_name") or ""
        for method in _dict_list(contract.get("methods")):
            name = method.get("name") or ""
            description = method.get("description") or ""
            items.append((f"contract:{service}.{name}", f"{name}: {description}"))
    return items


def _string_list(value):
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _dict_list(value):
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
