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

# Step C's tag for an invariant that states a behaviour, and so may map onto a
# kernel pattern. Its counterpart, `SCHEMA_KIND`, restates a field declaration
# and is not classified — see `classification_items`.
RULE_KIND = "rule"


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
    """The (source label, text) pairs to classify, in document order.

    Only invariants step C tagged `rule` are classified. A `schema` invariant
    restates a field's own declaration — its type, nullability, uniqueness, key
    or allowed values — so it names no operation and no pattern can be right for
    it: every answer the classifier gives is noise, and measured across the
    seven prompts most of that noise lands *above* the confidence floor and so
    was never even reported. Step C makes the distinction when it writes the
    invariant, where the grammar can enforce it, rather than leaving it to be
    guessed from prose here (`grammar_open.invariant_list`).
    """
    items = []
    for invariant in _rule_invariants(documents.get("invariants")):
        items.append(("invariant", invariant))
    for contract in _dict_list(documents.get("service_contracts")):
        service = contract.get("service_name") or ""
        for method in _dict_list(contract.get("methods")):
            name = method.get("name") or ""
            description = method.get("description") or ""
            items.append((f"contract:{service}.{name}", f"{name}: {description}"))
    return items


def _rule_invariants(value):
    """The text of every invariant tagged `rule`."""
    texts = []
    for item in _invariants(value):
        kind, text = item
        if kind == RULE_KIND:
            texts.append(text)
    return texts


def _invariants(value):
    """Every invariant as a (kind, text) pair, accepting either document shape.

    The tagged shape is what step C writes now. The bare-string shape is read
    too, so an output directory produced before this change still classifies
    instead of silently yielding nothing — there, every invariant was
    classified, which is the behaviour being replaced.
    """
    if not isinstance(value, list):
        return []
    pairs = []
    for item in value:
        if isinstance(item, str):
            if item.strip():
                pairs.append((RULE_KIND, item.strip()))
        elif isinstance(item, dict):
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                pairs.append((item.get("kind"), text.strip()))
    return pairs


def _string_list(value):
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _dict_list(value):
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
