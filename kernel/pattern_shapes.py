"""Whether a claimed pattern is possible for the item it was claimed for.

The classifier chooses between patterns from the item's text, and measured over
one prompt it never once chose the "none of these" option: the sentinel's
probability was 0.000 on 30 of 34 expenses methods and never above 0.036. So the
sentinel cannot be the catch-all — offering it does not make the model use it —
and an answer that no pattern fits arrives as the *nearest* pattern instead.

The catch-all is therefore decided here, outside the model, from evidence the
model cannot misread: the item's own return type. A pattern that returns an
aggregate and a method that returns `List[Expense]` cannot both be right, and
which is which is not a matter of opinion:

    get_monthly_expenses(month: str) -> List[Expense]   claimed AGGREGATE_BY_FK_AND_DATE
    add_expense(...) -> Expense                         claimed BUDGET_OVERFLOW_GUARD
    export_to_csv(...) -> bool                          claimed FILTER_WITH_PAGINATION

Every one of those is rejected here — the aggregate returns a list of records,
the guard returns an entity, the filter returns a boolean — and the rejection
*is* the missing-feature report the gaps exist to produce. A rejection says "the
model wanted a pattern for this and the catalogue has none", which is exactly
what code generation needs to be told.

The shape each pattern may return is declared in the catalogue beside the
pattern (`"returns": [...]`), so a pattern's meaning and its return type cannot
drift apart, and this module adds no vocabulary of its own.

Invariants carry no signature, so nothing here can check them — a guard chosen
for an invariant is judged by the model alone, and that limit is stated rather
than hidden (the checker reports it as unverifiable).
"""

import json
from pathlib import Path

KERNEL_DIR = Path(__file__).resolve().parent

CATALOGUE_PATHS = (
    KERNEL_DIR / "repo_patterns" / "patterns.json",
    KERNEL_DIR / "service_patterns" / "patterns.json",
)

# The shapes a return type can have, as far as a pattern is concerned.
COLLECTION = "collection"
MAPPING = "mapping"
BOOLEAN = "boolean"
SCALAR = "scalar"
NONE = "none"
ENTITY = "entity"

# Return types that name each shape, matched on the *outer* type only, so
# `Dict[int, List[X]]` is a mapping and `List[Dict[...]]` is a collection.
COLLECTION_NAMES = frozenset({"list", "set", "frozenset", "sequence", "iterable", "collection", "list_"})
MAPPING_NAMES = frozenset({"dict", "mapping", "defaultdict", "ordereddict", "map", "dict_"})
BOOLEAN_NAMES = frozenset({"bool", "boolean", "bool_"})
NONE_NAMES = frozenset({"none", "void", "null", "nil", "unit"})
SCALAR_NAMES = frozenset({
    "int", "integer", "float", "double", "decimal", "number", "numeric",
    "money", "cents", "quantity", "count", "long", "short",
})
# Wrappers that do not change the shape of what they wrap, unwrapped in turn.
TRANSPARENT_WRAPPERS = frozenset({"optional", "union", "awaitable", "future"})

_CACHE = None


def return_shape(return_type):
    """The shape of a declared return type: one of the shape constants.

    `Unknown` is returned for an empty or unparseable type, and is treated as
    compatible with everything — the check must never reject a claim because it
    could not read the type, only because it read one that cannot fit.
    """
    text = (return_type or "").strip()
    if not text:
        return None
    return _shape_of(text.lower())


def _shape_of(text):
    outer = text.split("[", 1)[0].strip().rstrip("?")
    inner = _inside_brackets(text)

    if outer in TRANSPARENT_WRAPPERS and inner:
        # `Optional[X]` -> X; `Union[X, None]` -> X, keeping the non-None arm.
        arms = _split_arms(inner)
        for arm in arms:
            if arm.strip().lower() not in NONE_NAMES:
                return _shape_of(arm.strip().lower())
        return NONE
    if outer in COLLECTION_NAMES:
        return COLLECTION
    if outer in MAPPING_NAMES:
        return MAPPING
    if outer in BOOLEAN_NAMES:
        return BOOLEAN
    if outer in NONE_NAMES:
        return NONE
    if outer in SCALAR_NAMES:
        return SCALAR
    # A page wrapper is a collection in the only sense the pattern catalogue
    # cares about: it carries the selected records and is not one entity.
    if "paginat" in outer or outer.endswith(("page", "paged", "pageresult")):
        return COLLECTION
    return ENTITY


def _inside_brackets(text):
    start = text.find("[")
    if start == -1 or not text.endswith("]"):
        return ""
    return text[start + 1 : -1]


def _split_arms(inner):
    """Split on top-level commas, so `Dict[int, int]` stays one arm."""
    arms = []
    depth = 0
    current = ""
    for character in inner:
        if character == "[":
            depth += 1
        elif character == "]":
            depth -= 1
        if character == "," and depth == 0:
            arms.append(current)
            current = ""
        else:
            current += character
    if current:
        arms.append(current)
    return arms


def declared_shapes():
    """pattern_id -> the set of return shapes that pattern may have.

    Read from the catalogue files, so this cannot disagree with the patterns the
    classifier was given. Empty for `STANDARD_CRUD` and the gap ids, which are
    answers rather than patterns and are never checked.
    """
    shapes = {}
    for path in CATALOGUE_PATHS:
        with open(path, "r", encoding="utf-8") as handle:
            for entry in json.load(handle):
                pattern_id = entry.get("pattern_id")
                returns = entry.get("returns")
                if pattern_id and isinstance(returns, list):
                    shapes[pattern_id] = frozenset(returns)
    return shapes


def _declared_shapes_cached():
    global _CACHE
    if _CACHE is None:
        _CACHE = declared_shapes()
    return _CACHE


def returns_records(pattern_id):
    """True when `pattern_id` is declared to return a collection.

    Used to confine the correction to the defect that was actually observed —
    a record-returning read misnamed as an aggregate — rather than letting it
    swap one wrong answer for another. The distinction is not academic:
    `export_to_csv(...) -> bool` first came out corrected to
    `EXISTS_BY_UNIQUE_COMPOSITE`, which is also boolean and therefore
    shape-valid and semantically absurd. A shape-compatible candidate in a
    different return family is a guess, and a guess is what the gap exists to
    avoid.
    """
    return COLLECTION in _declared_shapes_cached().get(pattern_id, frozenset())


def returns_one_record(pattern_id):
    """True when `pattern_id` is declared to return a single record.

    The twin of `returns_records` for a read that finds one row by its key:
    a method returning one entity may be corrected into such a pattern, since
    both sit in the same return family. Booleans, scalars and mappings stay
    out, for the reason `returns_records` gives.
    """
    return ENTITY in _declared_shapes_cached().get(pattern_id, frozenset())


def rejection_reason(pattern_id, return_type):
    """Why `pattern_id` cannot be right for a method returning `return_type`.

    None when the claim is possible, and also when it cannot be judged — no
    declared shape for the pattern (a sentinel, or a catalogue without `returns`)
    or an unreadable return type.
    """
    if not pattern_id:
        return None
    allowed = _declared_shapes_cached().get(pattern_id)
    if not allowed:
        return None
    shape = return_shape(return_type)
    if shape is None:
        return None
    if shape in allowed:
        return None
    return (
        f"{pattern_id} returns {'/'.join(sorted(allowed))}, "
        f"but this method returns {shape} ({return_type})"
    )
