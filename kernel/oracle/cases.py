"""Schema and validation for prompt-derived behavioral cases.

A case is evidence, not a test result. `confirmed` cases may run as behavioral
checks; assumptions, ambiguities and contradictions stay visible for review.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from kernel.consistency.naming import normalize

STATUSES = ("confirmed", "assumed", "ambiguous", "contradictory", "unbound")
CASES_NAME = "oracle_cases.json"
PLACEHOLDERS = frozenset({
    "today", "tomorrow", "now", "none", "null", "auto_incremented_int",
    "unknown", "authenticated", "auto", "tbd", "n/a",
})


def _known(value):
    return isinstance(value, str) and bool(value.strip())


def _same(a, b):
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _source_present(source, requirements):
    def clean(value):
        text = str(value or "").replace("`", "").replace("*", "")
        text = re.sub(r"\s+", " ", text).strip().casefold()
        return text.rstrip(" .;:")

    wanted = clean(source)
    haystack = clean(requirements)
    return bool(wanted) and wanted in haystack


def _placeholder(value):
    return isinstance(value, str) and value.strip().lower() in PLACEHOLDERS


def _entity_named(alias, requirements):
    token = re.sub(r"_?\d+$", "", normalize(alias))
    if not token:
        return False
    words = {re.sub(r"s$", "", word) for word in
             re.findall(r"[a-z][a-z0-9_]*", str(requirements).lower())}
    return token in words or token + "s" in words


def _invalid_given(given, requirements):
    for alias, values in given.items():
        if not _entity_named(alias, requirements):
            return f"given.{alias} is not an entity named in the requirements"
        if not isinstance(values, dict) or not values:
            return f"given.{alias} must be a non-empty field mapping"
        for field, value in values.items():
            if isinstance(value, dict):
                if set(value) != {"ref"} or not _known(value.get("ref")):
                    return f"given.{alias}.{field} is nested; use a flat value or ref"
                continue
            if isinstance(value, (list, dict)):
                return f"given.{alias}.{field} is composite; use a flat value"
            if _placeholder(value):
                return f"given.{alias}.{field} is a placeholder {value!r}"
    return None


def _invalid_then(then):
    state = then.get("state")
    if state is not None:
        if not isinstance(state, dict):
            return "then.state must be a flat mapping"
        for key, value in state.items():
            if isinstance(value, (dict, list)):
                return f"then.state.{key} is nested; expected a scalar"
            if _placeholder(value):
                return f"then.state.{key} is a placeholder {value!r}"
    rows = then.get("rows")
    if rows is not None and not isinstance(rows, dict):
        return "then.rows must be a mapping"
    return None


def _normalise_then(then, status, ambiguities):
    """Drop schema placeholders/nulls and flag non-class error names."""
    then = dict(then)
    error = then.get("error")
    if isinstance(error, str):
        lowered = error.strip().lower()
        if lowered in ("", "none", "null", "no error", "errorname or omit"):
            then.pop("error", None)
        elif not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", error.strip()):
            ambiguities.append(f"error is not a class name: {error!r}")
            status = "assumed"
            then.pop("error", None)
    rows = then.get("rows")
    if isinstance(rows, dict):
        then["rows"] = {key: value for key, value in rows.items()
                        if value is not None}
    return then, status


def validate_cases(raw, requirements, prompt_sha=None):
    """`(cases, errors)`: valid normalized cases and human-readable refusals."""
    if isinstance(raw, dict):
        raw = raw.get("cases")
    if not isinstance(raw, list):
        return [], ["oracle payload has no 'cases' list"]
    cases, errors = [], []
    seen = set()
    for index, item in enumerate(raw, start=1):
        label = f"case {index}"
        if not isinstance(item, dict):
            errors.append(f"{label}: not an object")
            continue
        case_id = str(item.get("id") or "").strip()
        if not case_id:
            errors.append(f"{label}: missing id")
            continue
        label = f"{label} ({case_id})"
        if case_id in seen:
            errors.append(f"{label}: duplicate id")
            continue
        seen.add(case_id)
        source = item.get("source")
        if not _known(source):
            errors.append(f"{label}: missing source")
            continue
        if not _source_present(source, requirements):
            errors.append(f"{label}: source is not a prompt span")
            continue
        given = item.get("given")
        if not isinstance(given, dict) or not given:
            errors.append(f"{label}: given must be a non-empty alias mapping")
            continue
        bad_given = _invalid_given(given, requirements)
        if bad_given:
            errors.append(f"{label}: {bad_given}")
            continue
        when = item.get("when")
        if not isinstance(when, dict):
            errors.append(f"{label}: when must be an object")
            continue
        if not _known(when.get("action")) and not (
                isinstance(when.get("cli"), list) and when["cli"]):
            errors.append(f"{label}: when needs action or cli")
            continue
        then = item.get("then")
        if not isinstance(then, dict) or not any(
                key in then for key in ("state", "error", "rows")):
            errors.append(f"{label}: then needs state, error or rows")
            continue
        bad_then = _invalid_then(then)
        if bad_then:
            errors.append(f"{label}: {bad_then}")
            continue
        status = str(item.get("status") or "assumed")
        if status not in STATUSES:
            errors.append(f"{label}: unknown status {status!r}")
            continue
        assumptions = [str(x) for x in item.get("assumptions") or []
                       if _known(x)]
        ambiguities = [str(x) for x in item.get("ambiguities") or []
                       if _known(x)]
        then, status = _normalise_then(then, status, ambiguities)
        case = {
            "id": case_id,
            "source": " ".join(source.split()),
            "given": given,
            "when": when,
            "then": then,
            "status": status,
            "assumptions": assumptions,
            "ambiguities": ambiguities,
        }
        if prompt_sha:
            case["prompt_sha"] = prompt_sha
        cases.append(case)

    # Opposite outcomes for the same action and setup are a contradiction,
    # not two independent tests.
    for left in cases:
        for right in cases:
            if left is right or left["when"].get("action") != right["when"].get("action"):
                continue
            if not _same(left["given"], right["given"]):
                continue
            if not _same(left["then"], right["then"]):
                left["status"] = "contradictory"
                right["status"] = "contradictory"
                left["ambiguities"].append(
                    f"contradicts case {right['id']}")
                right["ambiguities"].append(
                    f"contradicts case {left['id']}")
    return cases, errors


def load_cases(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    value = payload.get("cases") if isinstance(payload, dict) else payload
    return value if isinstance(value, list) else []


def save_cases(path, cases, *, prompt_sha=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"prompt_sha": prompt_sha, "cases": cases}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path


def open_questions(cases):
    """Cases a human must resolve before they can become behavioral proof."""
    return [case for case in cases
            if case.get("status") != "confirmed"
            or case.get("assumptions") or case.get("ambiguities")]
