"""Agreement between a stated invariant and the field it names.

An invariant is free prose, so it cannot be checked in general — but a few of
them make a claim about a single field attribute that the data model also
declares, and those can be compared. Measured on the corpus, the pair that
occurs is `<field> must be unique` against that field's `unique` flag, and
`<field> must be nullable|optional` against its `nullable` flag. Most of those
agree; where they do not, one of the two documents is wrong.

The rule is deliberately narrow. A field name that appears in more than one
model is skipped, because the invariant does not say which model it means and
guessing would manufacture findings. An invariant naming a field that no model
declares is skipped too, because a program with no data model legitimately
states rules about records it does not model — cli_tool's "isbn must be unique
across all records" is the whole of its invariants, and its data model is
correctly empty.
"""

import re

from kernel.consistency.checks_phrases import phrase_text

# "sku must be unique", "category.name must be unique": the name is the token
# before the claim, with an optional model prefix that is stripped.
_UNIQUE = re.compile(r"\b([a-z_][a-z0-9_]*)\b[^.]*?\bmust be unique\b", re.I)
_NULLABLE = re.compile(r"\b([a-z_][a-z0-9_]*)\b[^.]*?\bmust be (?:nullable|optional)\b", re.I)

CLAIMS = (
    (_UNIQUE, "unique", "unique"),
    (_NULLABLE, "nullable", "nullable"),
)


def check_invariant_claims(invariants, index, report):
    """Report each invariant that contradicts the attribute it names.

    Every invariant is read, `rule` or `schema`: a `rule` never contains a
    "must be unique" or "must be nullable" claim, so scanning both loses nothing
    and keeps the rule's coverage independent of how step C tags a statement.
    `phrase_text` reads the sentence from either document shape.
    """
    if not isinstance(invariants, list) or not index.models:
        return

    declared = _fields_by_name(index)
    for invariant in invariants:
        text = phrase_text(invariant)
        if text is None:
            continue
        for regex, attribute, wording in CLAIMS:
            match = regex.search(text)
            if match is None:
                continue
            field_name = match.group(1)
            candidates = declared.get(field_name, [])
            if len(candidates) != 1:
                # Unknown here, or named by several models: the invariant does
                # not identify which field it means, so there is nothing to
                # compare rather than something to report.
                continue
            model_name, field = candidates[0]
            if field.get(attribute) is True:
                continue
            report.warning(
                "inconsistent_invariant",
                f"invariants: '{field_name} must be {wording}' but "
                f"{model_name}.{field_name} declares {attribute}={field.get(attribute)}",
            )


def _fields_by_name(index):
    """Every declared field, keyed by name, with the models that declare it."""
    declared = {}
    for model in index.models:
        model_name = model.get("name")
        for field in model.get("fields", []):
            if isinstance(field, dict) and field.get("name"):
                declared.setdefault(field["name"], []).append((model_name, field))
    return declared
