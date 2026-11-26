"""Schema and validation for prompt-derived behavioral cases.

A case is evidence, not a test result. `confirmed` cases may run as behavioral
checks; assumptions, ambiguities and contradictions stay visible for review.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from kernel.consistency.naming import normalize

STATUSES = ("confirmed", "assumed", "ambiguous", "contradictory", "unbound",
            "under_specified", "case_defect")
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
    if token in normalize(requirements):
        return True
    words = set()
    for word in re.findall(r"[a-z][a-z0-9_]*", str(requirements).lower()):
        if word.endswith("ies") and len(word) > 4:
            word = word[:-3] + "y"
        elif word.endswith("s") and not word.endswith("ss") and len(word) > 3:
            word = word[:-1]
        words.add(word)
    if token in words or token + "s" in words:
        return True
    if token.endswith("ies"):
        singular = token[:-3] + "y"
        if singular in words or singular + "s" in words:
            return True
    return False


def _is_app_case(when):
    return isinstance(when, dict) and when.get("app") is True


def _invalid_when(when):
    if not isinstance(when, dict):
        return "when must be an object"
    if _is_app_case(when):
        args = when.get("args")
        if args is not None and not isinstance(args, list):
            return "when.args must be a list"
        stdin = when.get("stdin")
        if stdin is not None and not isinstance(stdin, str):
            return "when.stdin must be a string"
        files = when.get("files")
        if files is not None:
            if not isinstance(files, dict):
                return "when.files must be a mapping"
            for name, content in files.items():
                if not isinstance(name, str) or not isinstance(content, str):
                    return "when.files entries must be string paths and content"
        return None
    if not _known(when.get("action")) and not (
            isinstance(when.get("cli"), list) and when["cli"]):
        return "when needs action, cli or app"
    return None


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
    stdout = then.get("stdout_contains")
    if stdout is not None and not isinstance(stdout, str):
        return "then.stdout_contains must be a string"
    code = then.get("exit_code")
    if code is not None and (isinstance(code, bool) or not isinstance(code, int)):
        return "then.exit_code must be an integer"
    return None


def _normalise_then(then, status, ambiguities, requirements=""):
    """Drop schema placeholders/nulls and flag non-class error names."""
    then = dict(then)
    error = then.get("error")
    if isinstance(error, str):
        lowered = error.strip().lower()
        if lowered in ("", "none", "null", "no error", "omit", "omitted",
                       "errorname or omit"):
            then.pop("error", None)
        elif not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", error.strip()):
            ambiguities.append(f"error is not a class name: {error!r}")
            status = "assumed"
            then.pop("error", None)
        elif normalize(error) not in normalize(requirements):
            # The prompt describes the failure, but does not name this class.
            # Keeping it as confirmed would make an implementation choice look
            # like a requirement.
            ambiguities.append(
                f"error class {error!r} is not named in the requirements")
            status = "assumed"
    rows = then.get("rows")
    if isinstance(rows, dict):
        then["rows"] = {key: value for key, value in rows.items()
                        if value is not None}
    return then, status


def _invalid_semantics(when, given, then):
    """Reject cases whose expectations contradict their own setup."""
    action = str((when or {}).get("action") or "").lower()
    normalized = "".join(ch for ch in action if ch.isalnum())
    rows = (then or {}).get("rows")
    if isinstance(rows, dict):
        for entity, count in rows.items():
            try:
                if int(count) < 0:
                    return f"row count for {entity} is negative"
            except (TypeError, ValueError):
                if str(count).strip() not in (">=0", ">0", "<=0", "<0", "!=0", "==0"):
                    return f"row count for {entity} is not a count"
    state = (then or {}).get("state")
    aliases = set(given) if isinstance(given, dict) else set()
    if isinstance(state, dict):
        if "delete" in normalized or "remove" in normalized:
            return "delete case must assert rows, not state of a deleted row"
        for target in state:
            alias, _, field = str(target).partition(".")
            if alias and aliases and alias not in aliases:
                return f"expected state references unseeded alias {alias!r}"
            if not field:
                return f"expected state target {target!r} is not alias.field"
    if "update" in normalized and isinstance(state, dict) and isinstance(given, dict):
        changed = False
        for target, expected in state.items():
            alias, _, field = str(target).partition(".")
            current = (given.get(alias) or {}).get(field)
            if current != expected:
                changed = True
                break
        if not changed:
            return "update case supplies no new value"
    if isinstance(rows, dict) and isinstance(given, dict):
        args = (when or {}).get("args")
        if "search" in normalized and not args:
            return "search case supplies no query or filter argument"
        if "list" in normalized and not args:
            for alias, count in rows.items():
                try:
                    exact = int(count)
                except (TypeError, ValueError):
                    continue
                entity = normalize(str(alias))
                seeded = sum(1 for name in given
                             if normalize(name).startswith(entity))
                if exact < seeded:
                    return ("list case expects fewer rows than its setup but "
                            "performs no delete or filter action")
    if "create" in normalized and isinstance(state, dict) and isinstance(given, dict):
        for target, expected in state.items():
            alias, _, field = str(target).partition(".")
            current = (given.get(alias) or {}).get(field)
            if current is not None and expected != current:
                return (f"create case expects {target} = {expected!r} but "
                        f"supplies {current!r}")
    return None


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
        when = item.get("when")
        bad_when = _invalid_when(when)
        if bad_when:
            errors.append(f"{label}: {bad_when}")
            continue
        given = item.get("given")
        if not isinstance(given, dict):
            errors.append(f"{label}: given must be an alias mapping")
            continue
        if not given and not _is_app_case(when):
            errors.append(f"{label}: given must be a non-empty alias mapping")
            continue
        bad_given = _invalid_given(given, requirements)
        if bad_given:
            errors.append(f"{label}: {bad_given}")
            continue
        then = item.get("then")
        if not isinstance(then, dict) or not any(
                key in then for key in ("state", "error", "rows",
                                        "stdout_contains", "exit_code")):
            errors.append(f"{label}: then needs an observable outcome")
            continue
        bad_then = _invalid_then(then)
        if bad_then:
            errors.append(f"{label}: {bad_then}")
            continue
        bad_semantics = _invalid_semantics(when, given, then)
        if bad_semantics:
            errors.append(f"{label}: {bad_semantics}")
            continue
        status = str(item.get("status") or "assumed")
        if status not in STATUSES:
            errors.append(f"{label}: unknown status {status!r}")
            continue
        assumptions = [str(x) for x in item.get("assumptions") or []
                       if _known(x)]
        ambiguities = [str(x) for x in item.get("ambiguities") or []
                       if _known(x)]
        then, status = _normalise_then(
            then, status, ambiguities, requirements)
        base_status = item.get("base_status") or (
            "assumed" if assumptions or ambiguities else status)
        if base_status == "contradictory":
            base_status = "assumed"
        case = {
            "id": case_id,
            "source": " ".join(source.split()),
            "given": given,
            "when": when,
            "then": then,
            "status": base_status,
            "base_status": base_status,
            "assumptions": assumptions,
            "ambiguities": ambiguities,
        }
        if prompt_sha:
            case["prompt_sha"] = prompt_sha
        cases.append(case)

    # Opposite outcomes for the same action, setup and arguments are a
    # contradiction, not two independent tests. Start from the recoverable
    # base status so stale contradictions clear on revalidation.
    for case in cases:
        case["status"] = case["base_status"]
    for left in cases:
        for right in cases:
            if left is right or _is_app_case(left["when"]) \
                    or _is_app_case(right["when"]) \
                    or left["when"].get("action") != right["when"].get("action"):
                continue
            if not _same(left["given"], right["given"]):
                continue
            # Different arguments are different scenarios, not contradictions.
            if not _same(left["when"].get("args"), right["when"].get("args")):
                continue
            # Assumed/ambiguous alternatives are candidate readings, not a
            # proven contradiction. Only two confirmed readings conflict.
            if {left.get("base_status"), right.get("base_status")} != {"confirmed"}:
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
    open_cases = []
    for case in cases:
        if case.get("status") == "unbound" and not case.get("needs_review"):
            continue
        if (case.get("status") != "confirmed"
                or case.get("assumptions") or case.get("ambiguities")
                or case.get("needs_review")):
            open_cases.append(case)
    return open_cases
