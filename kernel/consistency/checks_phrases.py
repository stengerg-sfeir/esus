"""Consistency checks for the free-text requirement lists.

intentions and invariants are plain lists of phrases with no cross-references,
so they only need type, emptiness and duplication checks.
"""

from kernel.consistency.methods import is_missing

EMPTY_LIST_NOTE = "list is empty (valid when the requirements state none)"


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
        if is_missing(item):
            report.error("invalid_value", f"{label}: an entry is not a string")
            continue
        key = item.strip().lower()
        if key in seen:
            report.warning("duplicate_entry", f"{label}: duplicate entry {seen[key]!r}")
            continue
        seen[key] = item
