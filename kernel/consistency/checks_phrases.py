"""Consistency checks for the free-text requirement lists.

`intentions` is a list of bare sentences. `invariants` holds `{text, kind}`
objects, because step C tags each one `rule` or `schema` — a rule constrains
behaviour and is classified into a kernel pattern; a schema statement restates a
field's own declaration and is not. Both are lists of sentences with no
cross-references, so both need only type, emptiness and duplication checks, and
`phrase_text` gives a check the sentence whichever shape it came from.
"""

from kernel.consistency.methods import is_missing

EMPTY_LIST_NOTE = "list is empty (valid when the requirements state none)"


def phrase_text(item):
    """The sentence an entry holds, or None when it holds no usable text.

    Accepts a bare string (intentions, and any output written before invariants
    were tagged) and a `{text, ...}` object (invariants now). The readers are
    deliberately tolerant because the backed-up output on disk is still the old
    shape; only the writer is strict.
    """
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        text = item.get("text")
        if isinstance(text, str):
            return text
    return None


def check_phrase_list(items, label, report):
    """Validate one list of requirement phrases."""
    if items is None:
        return
    if not items:
        # A note, not a warning: an empty intentions or invariants list is the
        # correct extraction when the requirements state none, and the checker
        # cannot see the requirements to tell the two apart.
        report.note("empty_section", f"{label}: {EMPTY_LIST_NOTE}")
        return

    seen = {}
    for item in items:
        text = phrase_text(item)
        if text is None or is_missing(text):
            report.error("invalid_value", f"{label}: an entry holds no text")
            continue
        key = text.strip().lower()
        if key in seen:
            report.warning("duplicate_entry", f"{label}: duplicate entry {seen[key]!r}")
            continue
        seen[key] = text
