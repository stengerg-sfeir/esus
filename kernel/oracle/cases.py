"""Schema and validation for prompt-derived behavioral cases.

A case is evidence, not a test result. `confirmed` cases may run as behavioral
checks; assumptions, ambiguities and contradictions stay visible for review.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

STATUSES = ("confirmed", "assumed", "ambiguous", "contradictory", "unbound")
CASES_NAME = "oracle_cases.json"


def _known(value):
    return isinstance(value, str) and bool(value.strip())


def _same(a, b):
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _source_present(source, requirements):
    wanted = " ".join(str(source or "").split())
    haystack = " ".join(str(requirements or "").split())
    return bool(wanted) and wanted in haystack


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
        if not isinstance(given, (dict, list)) or not given:
            errors.append(f"{label}: given must be a non-empty object or list")
            continue
        when = item.get("when")
        if not isinstance(when, dict) or not _known(when.get("action")):
            errors.append(f"{label}: when.action is required")
            continue
        then = item.get("then")
        if not isinstance(then, dict) or not any(
                key in then for key in ("state", "error", "rows")):
            errors.append(f"{label}: then needs state, error or rows")
            continue
        status = str(item.get("status") or "assumed")
        if status not in STATUSES:
            errors.append(f"{label}: unknown status {status!r}")
            continue
        case = {
            "id": case_id,
            "source": " ".join(source.split()),
            "given": given,
            "when": when,
            "then": then,
            "status": status,
            "assumptions": [str(x) for x in item.get("assumptions") or []
                            if _known(x)],
            "ambiguities": [str(x) for x in item.get("ambiguities") or []
                            if _known(x)],
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
