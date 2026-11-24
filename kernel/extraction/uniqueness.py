"""Provenance for non-key unique fields.

A data model can mark a field `unique` because the requirements say so, or
because the model guessed from a field name (`email`, `title`).  The guess is
useful evidence, but it is not a requirement: enforcing it silently turns a
model prior into user-visible behaviour.  This module records the difference.

`unique_status` is stored on the field itself:

- `explicit`: the requirements state that this field is unique;
- `inferred`: the model guessed it, and the requirements do not state it;
- `confirmed`: a human accepted the inferred constraint;
- `rejected`: a human removed the inferred constraint.

Only `explicit` and `confirmed` are enforced by the generator.  `inferred`
fields keep their `unique=true` flag as evidence for the review sidecar; they
do not enter the schema or the create/update guards until a human confirms them.
Fields without a status predate this module and remain enforced, so archived
documents keep their existing meaning until `--repair` classifies them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from kernel.consistency.naming import normalize
from kernel.extraction.decisions import requirements_sha

DECISIONS_NAME = "unique_decisions.json"
DECISIONS_KEY = "decisions"
POLICY_NAME = "unique_policy.json"
POLICY_KEY = "policies"

EXPLICIT = "explicit"
INFERRED = "inferred"
CONFIRMED = "confirmed"
REJECTED = "rejected"
STATUSES = (EXPLICIT, INFERRED, CONFIRMED, REJECTED)
ENFORCED = (EXPLICIT, CONFIRMED)

_CONVENTIONAL = {
    "email", "username", "isbn", "sku", "code", "slug", "phone",
    "phone_number", "mobile", "phone_number", "serial_number",
    "license_plate", "national_id",
}
_DISPLAY = {"name", "title"}

_SENTENCE_SPLIT = re.compile(r"[.;\n]")


def classify_policy(field_name):
    """The review group for an inferred field name."""
    name = normalize(field_name)
    if name in {normalize(item) for item in _CONVENTIONAL}:
        return "conventional"
    if name in {normalize(item) for item in _DISPLAY}:
        return "display"
    return "other"


def _normalised_requirements(requirements):
    """Requirements text with dotted identifiers protected from splitting.

    `Contact.email must be unique` must stay one clause; splitting on the dot
    in `Contact.email` used to leave `email` and `unique` in different
    sentences.  "Unique identifier" describes a primary key, not every field
    near it, so that phrase is removed before the field check.
    """
    text = requirements if isinstance(requirements, str) else ""
    text = re.sub(r"\bunique\s+(?:identifier|id)\b", " ", text,
                  flags=re.IGNORECASE)
    return re.sub(
        r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*([A-Za-z_][A-Za-z0-9_]*)\b",
        r"\1 \2", text)


def has_explicit_evidence(entity, field_name, requirements):
    """True when the requirements state that this specific field is unique.

    The check is deliberately narrow.  It accepts forms that put the field in
    the same clause as "unique", and rejects the generic "unique identifier"
    phrase and composite keys (`UNIQUE(a, b)`, "unique together").  A field
    with no such sentence is inferred, never silently explicit.
    """
    if not isinstance(field_name, str) or not field_name.strip():
        return False
    text = _normalised_requirements(requirements)
    if not text:
        return False
    token = re.escape(field_name.strip())
    # Plurals are common in prose ("all wine names must be unique").
    token = rf"\b{token}(?:s|es)?\b"
    for sentence in _SENTENCE_SPLIT.split(text):
        lowered = sentence.lower()
        if "unique" not in lowered:
            continue
        if _composite_context(lowered):
            continue
        if re.search(
                token + r"\s*\(\s*unique\s*\)",
                sentence, re.IGNORECASE):
            return True
        if re.search(
                token + r"(?:\s+(?:address(?:es)?|value|field|column))?"
                r"\s+(?:must|should|has|have|needs|need|is|are)\b"
                r"[^.;\n]{0,30}\bunique\b",
                sentence, re.IGNORECASE):
            return True
        if re.search(
                r"\bunique\s+(?:[a-z][a-z0-9_-]*\s+){0,1}" + token,
                sentence, re.IGNORECASE):
            return True
        if re.search(
                r"\b(?:no\s+two|not\s+two|two)\b[^.;\n]{0,80}"
                r"\b(?:same|share|shared|duplicate)\b[^.;\n]{0,80}" + token,
                sentence, re.IGNORECASE):
            return True
        if re.search(
                token + r"\b[^.;\n]{0,40}\b(?:only\s+once|not\s+duplicated)\b",
                sentence, re.IGNORECASE):
            return True
    return False


def _composite_context(sentence):
    """A composite key is not a per-field uniqueness statement."""
    return bool(re.search(
        r"\bunique\s+(?:together|combination)\b|\bcombination\s+of\b"
        r"|unique\s*\([^)]*,|\bcomposite\b", sentence, re.IGNORECASE))


def field_status(field):
    """The effective status of one field, including legacy documents."""
    status = field.get("unique_status") if isinstance(field, dict) else None
    if status in STATUSES:
        return status
    return EXPLICIT if isinstance(field, dict) and field.get("unique") else None


def is_enforced(field):
    """Whether the generated program may enforce this field's uniqueness."""
    return bool(isinstance(field, dict) and field.get("unique")
                and field_status(field) in ENFORCED)


def classify_unique_fields(models, requirements, log=None):
    """Set `unique_status` on primary keys and non-key unique fields.

    A previous confirmation is not inferred again here: the sidecar
    (`unique_decisions.json`) is the authority for `confirmed`/`rejected`, and
    is applied immediately after this pass.  Every non-key `unique=true`
    without prompt evidence is marked `inferred`; its `unique` flag stays true
    as the evidence the review decides on.
    """
    if not isinstance(models, list):
        return models
    counts = {EXPLICIT: 0, INFERRED: 0}
    changed = 0
    for model in models:
        if not isinstance(model, dict):
            continue
        for field in model.get("fields") or []:
            if not isinstance(field, dict) or not field.get("unique"):
                continue
            if field.get("primary_key"):
                if field.get("unique_status") != EXPLICIT:
                    changed += 1
                field["unique_status"] = EXPLICIT
                counts[EXPLICIT] += 1
                continue
            if field_status(field) == REJECTED:
                # A human removed the inferred constraint. The legacy
                # `unique=true` evidence must not survive as an active flag.
                field["unique"] = False
                changed += 1
                continue
            entity = model.get("name") or ""
            status = (EXPLICIT if has_explicit_evidence(
                entity, field.get("name"), requirements) else INFERRED)
            if field.get("unique_status") != status:
                changed += 1
            field["unique_status"] = status
            counts[status] += 1
    if log is not None and changed:
        log.write(
            "[ok] step data_models: uniqueness provenance — "
            f"{counts[EXPLICIT]} explicit, {counts[INFERRED]} inferred "
            "(inferred fields are not enforced until confirmed)"
        )
    return models


def load_decisions(output_dir):
    """The recorded uniqueness decisions, or [] when absent/unusable."""
    try:
        payload = json.loads(
            (Path(output_dir) / DECISIONS_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    records = payload.get(DECISIONS_KEY)
    return [record for record in records or [] if isinstance(record, dict)]


def save_decisions(output_dir, records):
    """Write the uniqueness decisions beside the documents."""
    path = Path(output_dir) / DECISIONS_NAME
    path.write_text(
        json.dumps({DECISIONS_KEY: records}, indent=2,
                   ensure_ascii=False) + "\n",
        encoding="utf-8")
    return path


def load_policies(output_dir):
    """Policy decisions from this directory or its validation root."""
    path = Path(output_dir) / POLICY_NAME
    if not path.is_file() and Path(output_dir).parent.is_dir():
        path = Path(output_dir).parent / POLICY_NAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    records = payload.get(POLICY_KEY)
    return [record for record in records or [] if isinstance(record, dict)]


def save_policies(output_dir, records):
    """Write the grouped policy decisions at a validation root."""
    path = Path(output_dir) / POLICY_NAME
    path.write_text(
        json.dumps({POLICY_KEY: records}, indent=2,
                   ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def apply_policies(models, policies, log=None):
    """Apply grouped `conventional`/`display`/`other` decisions."""
    if not isinstance(models, list):
        return models
    chosen = {}
    for record in policies or []:
        if (isinstance(record, dict)
                and isinstance(record.get("policy"), str)
                and isinstance(record.get("unique"), bool)):
            chosen[record["policy"]] = record["unique"]
    if not chosen:
        return models
    applied = 0
    for model in models:
        if not isinstance(model, dict):
            continue
        for field in model.get("fields") or []:
            if (not isinstance(field, dict)
                    or field_status(field) != INFERRED):
                continue
            policy = classify_policy(field.get("name"))
            if policy not in chosen:
                continue
            field["unique"] = chosen[policy]
            field["unique_status"] = (CONFIRMED if chosen[policy]
                                      else REJECTED)
            applied += 1
    if applied and log is not None:
        log.write(f"[ok] step data_models: applied {applied} grouped "
                  "uniqueness decision(s)")
    return models


def _find_field(models, entity, field_name):
    wanted_entity = normalize(entity)
    wanted_field = normalize(field_name)
    for model in models or []:
        if not isinstance(model, dict):
            continue
        if normalize(model.get("name") or "") != wanted_entity:
            continue
        for field in model.get("fields") or []:
            if (isinstance(field, dict)
                    and normalize(field.get("name") or "") == wanted_field):
                return field
    return None


def apply_decisions(models, records, log=None, requirements_text=None):
    """Apply human decisions to the data models.

    Records are keyed by entity and field, and stamped with the requirements
    sha.  A record from a different prompt is skipped with a log line so a
    reworded prompt cannot inherit an answer about different requirements.
    """
    if not isinstance(models, list):
        return models
    current = requirements_sha(requirements_text) if requirements_text else None
    applied = 0
    for record in records or []:
        if not isinstance(record, dict):
            continue
        if not isinstance(record.get("unique"), bool):
            continue
        stamped = record.get("requirements_sha")
        if (current is not None and isinstance(stamped, str)
                and stamped != current):
            if log is not None:
                log.write(
                    "[!] step data_models: uniqueness decision for "
                    f"{record.get('entity')}.{record.get('field')} predates "
                    "a prompt change — dropped, will be re-asked")
            continue
        field = _find_field(models, record.get("entity"), record.get("field"))
        if field is None:
            continue
        field["unique"] = record["unique"]
        field["unique_status"] = CONFIRMED if record["unique"] else REJECTED
        applied += 1
    if applied and log is not None:
        log.write(f"[ok] step data_models: applied {applied} uniqueness "
                  "decision(s)")
    return models


def filter_invariants(models, invariants, log=None):
    """Remove schema uniqueness lines for inferred/rejected fields.

    The generated schema line is exact (`Entity.field must be unique`).  A
    model's broad rule is left untouched; only the field-level fact that this
    module controls is filtered.  Confirmed/explicit lines stay.
    """
    if not isinstance(invariants, list):
        return invariants
    statuses = {}
    for model in models or []:
        if not isinstance(model, dict):
            continue
        for field in model.get("fields") or []:
            if not isinstance(field, dict) or not field.get("name"):
                continue
            statuses[(normalize(model.get("name") or ""),
                      normalize(field["name"]))] = field_status(field)
    kept = []
    removed = 0
    pattern = re.compile(
        r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*"
        r"([A-Za-z_][A-Za-z0-9_]*)\s+must\s+be\s+unique\s*$",
        re.IGNORECASE)
    for invariant in invariants:
        text = invariant.get("text") if isinstance(invariant, dict) else None
        match = pattern.match(text) if isinstance(text, str) else None
        if match:
            key = (normalize(match.group(1)), normalize(match.group(2)))
            if statuses.get(key) not in ENFORCED:
                removed += 1
                continue
        kept.append(invariant)
    if removed and log is not None:
        log.write(f"[ok] step invariants: removed {removed} uniqueness "
                  "line(s) for inferred/rejected fields")
    return kept


def ensure_invariants(models, invariants, log=None):
    """Add the schema uniqueness line for explicit/confirmed fields."""
    if not isinstance(invariants, list):
        invariants = []
    seen = set()
    for invariant in invariants:
        text = invariant.get("text") if isinstance(invariant, dict) else None
        if isinstance(text, str):
            seen.add(" ".join(text.lower().split()))
    added = 0
    for model in models or []:
        if not isinstance(model, dict) or not model.get("name"):
            continue
        for field in model.get("fields") or []:
            if not is_enforced(field) or field.get("primary_key"):
                continue
            text = f"{model['name']}.{field['name']} must be unique"
            key = " ".join(text.lower().split())
            if key in seen:
                continue
            invariants.append({"text": text, "kind": "schema"})
            seen.add(key)
            added += 1
    if added and log is not None:
        log.write(f"[ok] step invariants: added {added} uniqueness line(s) "
                  "for explicit/confirmed fields")
    return invariants


def finalize(models, invariants, output_dir, requirements, log=None):
    """Classify, apply sidecar decisions, and align invariants."""
    classify_unique_fields(models, requirements, log)
    apply_decisions(models, load_decisions(output_dir), log,
                    requirements_text=requirements)
    apply_policies(models, load_policies(output_dir), log)
    invariants = filter_invariants(models, invariants, log)
    invariants = ensure_invariants(models, invariants, log)
    return models, invariants


def inferred_fields(models):
    """`[{entity, field, policy}]` for the attended uniqueness review."""
    fields = []
    for model in models or []:
        if not isinstance(model, dict) or not model.get("name"):
            continue
        for field in model.get("fields") or []:
            if (isinstance(field, dict) and field.get("unique")
                    and not field.get("primary_key")
                    and field_status(field) == INFERRED):
                fields.append({
                    "entity": model["name"],
                    "field": field["name"],
                    "policy": classify_policy(field["name"]),
                    "evidence": "field name; requirements do not state it",
                })
    return fields
