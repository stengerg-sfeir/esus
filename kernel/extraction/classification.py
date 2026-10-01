"""Step F: classify invariants and contract methods into kernel patterns.

This step used to be silent and dominated run time. It now reports one line per
item, which both removes the appearance of a hang and makes the per-item cost
visible in the run log.

**Nothing is discarded here.** Until this change the stage-1 "no domain fits"
answer was filtered out before the document was written, so 62 of the 191 items
across the seven prompts were classified and then thrown away — every one of them
ordinary CRUD, which the classifier had identified correctly. The answers are all
kept now. The gap ids (`NO_MATCH`, `NO_PATTERN_IN_DOMAIN`) are the coverage
report: their count and their texts say which pattern the vocabulary is missing.
`STANDARD_CRUD` is a legitimate answer recording what no named pattern needs to
describe, and is never a finding.
"""

from kernel.classifier.hierarchical_classifier import classify_requirement_2step, load_catalog
from kernel.pattern_catalog import GAP_PATTERN_IDS, STANDARD_CRUD


def classify_documents(classifier, documents, log):
    """Classify every invariant and contract method; return every match."""
    catalog = load_catalog()
    items = classification_items(documents)

    if not items:
        log.write("[ok] step patterns: nothing to classify")
        return []

    matches = []
    gaps = []
    standard_crud = 0
    total = len(items)

    for index, (source, text) in enumerate(items, start=1):
        result = classify_requirement_2step(classifier, text, catalog)
        pattern_id = result["pattern_id"]
        confidence = result["confidence"]

        marker = ""
        if pattern_id in GAP_PATTERN_IDS:
            gaps.append((source, pattern_id, text))
            marker = "  <- GAP: no pattern for this"
        elif pattern_id == STANDARD_CRUD:
            standard_crud += 1

        log.write(f"  [{index}/{total}] {source} -> {pattern_id} ({confidence:.2f}){marker}")

        matches.append(
            {
                "source": source,
                "text": text,
                "domain": result["domain"],
                "pattern_id": pattern_id,
                "confidence": round(confidence, 4),
            }
        )

    log.write(
        f"[ok] step patterns: {total} item(s) — {standard_crud} standard CRUD, "
        f"{total - standard_crud - len(gaps)} pattern(s), {len(gaps)} gap(s)"
    )
    for source, pattern_id, text in gaps:
        log.write(f"    gap [{pattern_id}] {source}: {text}")

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
