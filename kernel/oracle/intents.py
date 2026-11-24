"""Test intents: what to test, not concrete rows or values.

An intent is the verifier equivalent of an extraction document. The model
chooses the operation, target entity, lookup fields, changes and expected
observable outcome. The mechanical fixture planner and emitters will supply
concrete rows, IDs and dependency ordering later.

Expected outcomes remain prompt-derived. The intent schema deliberately has no
generated code, service bodies or extracted contracts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from kernel.consistency.naming import normalize

INTENTS_NAME = "test_intents.json"
KINDS = frozenset({
    "create", "update", "delete", "list", "aggregate", "error", "cli", "app",
})
STATUSES = frozenset({"confirmed", "assumed", "ambiguous"})
PLACEHOLDERS = frozenset({
    "today", "tomorrow", "none", "null", "unknown", "auto", "tbd", "n/a",
})

INTENT_SCHEMA = """{
  "intents": [
    {
      "id": "short_unique_id",
      "source": "exact target clause from the requirements",
      "kind": "create | update | delete | list | aggregate | error | cli | app",
      "entity": "Product",
      "action": "add_product",
      "setup_entities": [
        {"alias": "product", "entity": "Product", "role": "target"}
      ],
      "setup_values": {"product.stock_qty": 5},
      "lookup": ["product.sku"],
      "where": {"product.active": true},
      "args": ["product.sku", 3],
      "changes": {"product.stock_qty": 3},
      "cli": ["library", "book", "add", "--title=Example"],
      "app": {"args": ["2", "+", "3"], "stdin": "",
              "files": {"input.csv": "a,b\\n1,2\\n"}},
      "expect": {
        "state": {"product.stock_qty": 8},
        "rows": {"Product": 1},
        "error": null,
        "stdout_contains": "8",
        "exit_code": 0
      },
      "status": "confirmed | assumed | ambiguous",
      "assumptions": [],
      "ambiguities": []
    }
  ]
}"""


def _known(value):
    return isinstance(value, str) and bool(value.strip())


def _source_present(source, requirements):
    def clean(value):
        text = str(value or "").replace("`", "").replace("*", "")
        return " ".join(text.split()).strip().casefold().rstrip(" .;:")
    wanted = clean(source)
    return bool(wanted) and wanted in clean(requirements)


def _placeholder(value):
    return isinstance(value, str) and value.strip().lower() in PLACEHOLDERS


def _alias_ref(value, aliases):
    if not isinstance(value, str) or "." not in value:
        return None
    head, _, field = value.partition(".")
    if normalize(head) not in aliases or not field:
        return None
    return head, field


def _validate_ref_map(values, aliases, label, errors, values_matter=True):
    if not isinstance(values, dict):
        errors.append(f"{label} must be a mapping")
        return
    for key, value in values.items():
        if _alias_ref(key, aliases) is None:
            errors.append(f"{label} reference {key!r} has no setup alias")
        if values_matter and _placeholder(value):
            errors.append(f"{label} value for {key!r} is a placeholder")


def validate_intents(raw, requirements):
    """`(intents, errors)` for prompt-derived test intents."""
    if isinstance(raw, dict):
        raw = raw.get("intents")
    if not isinstance(raw, list):
        return [], ["intent payload has no 'intents' list"]
    intents, errors = [], []
    seen = set()
    for index, item in enumerate(raw, start=1):
        label = f"intent {index}"
        errors_before = len(errors)
        if not isinstance(item, dict):
            errors.append(f"{label}: not an object")
            continue
        intent_id = str(item.get("id") or "").strip()
        if not intent_id:
            errors.append(f"{label}: missing id")
            continue
        if intent_id in seen:
            errors.append(f"{label}: duplicate id {intent_id!r}")
            continue
        seen.add(intent_id)
        source = item.get("source")
        if not _known(source) or not _source_present(source, requirements):
            errors.append(f"{label}: source is not a prompt span")
            continue
        kind = str(item.get("kind") or "").strip().lower()
        if kind not in KINDS:
            errors.append(f"{label}: unknown kind {kind!r}")
            continue
        setup = item.get("setup_entities") or []
        if not isinstance(setup, list):
            errors.append(f"{label}: setup_entities must be a list")
            continue
        if item.get("app") and kind != "app":
            errors.append(f"{label}: app input is only valid for kind 'app'")
            continue
        if item.get("cli") and kind != "cli":
            errors.append(f"{label}: cli input is only valid for kind 'cli'")
            continue
        entities = {}
        for step in setup:
            if not isinstance(step, dict) or not _known(step.get("alias")) \
                    or not _known(step.get("entity")):
                errors.append(f"{label}: setup entity needs alias and entity")
                continue
            alias = step["alias"]
            if alias in entities:
                errors.append(f"{label}: duplicate setup alias {alias!r}")
            entities[alias] = step["entity"]
        aliases = {normalize(alias) for alias in entities}
        expect = item.get("expect")
        if not isinstance(expect, dict) or not any(
                key in expect for key in
                ("rows", "state", "error", "stdout_contains", "exit_code")):
            errors.append(f"{label}: expect needs an observable outcome")
            continue
        error = expect.get("error")
        if error not in (None, "") and not re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_.]*", str(error).strip()):
            errors.append(
                f"{label}: expect.error must be an exception class name or null")
            continue
        if kind == "app":
            if setup:
                errors.append(f"{label}: app intent must not setup entities")
                continue
            app = item.get("app")
            if not isinstance(app, dict) or not isinstance(app.get("args"), list):
                errors.append(f"{label}: app intent needs app.args")
                continue
            if not any(key in expect for key in ("stdout_contains", "exit_code")):
                errors.append(f"{label}: app intent needs stdout or exit_code")
                continue
        else:
            if not _known(item.get("entity")) or not _known(item.get("action")):
                errors.append(f"{label}: domain intent needs entity and action")
                continue
            rows = expect.get("rows")
            if rows is not None and not isinstance(rows, dict):
                errors.append(f"{label}: expect.rows must be a mapping")
                continue
            state = expect.get("state")
            if state is not None:
                _validate_ref_map(state, aliases, "expect.state", errors)
            lookup = item.get("lookup") or []
            if not isinstance(lookup, list):
                errors.append(f"{label}: lookup must be a list")
                continue
            for value in lookup:
                if _alias_ref(value, aliases) is None:
                    errors.append(f"{label}: lookup {value!r} has no setup alias")
            changes = item.get("changes") or {}
            setup_values = item.get("setup_values") or {}
            where = item.get("where") or {}
            _validate_ref_map(changes, aliases, "changes", errors)
            _validate_ref_map(setup_values, aliases, "setup_values", errors)
            _validate_ref_map(where, aliases, "where", errors)
            args = item.get("args") or []
            if not isinstance(args, list):
                errors.append(f"{label}: args must be a list")
                continue
            cli = item.get("cli") or []
            if not isinstance(cli, list):
                errors.append(f"{label}: cli must be a list")
                continue
            if kind == "cli" and not cli:
                errors.append(f"{label}: cli intent needs a cli command")
                continue
        status = str(item.get("status") or "assumed")
        if status not in STATUSES:
            errors.append(f"{label}: unknown status {status!r}")
            continue
        if len(errors) != errors_before:
            continue
        intents.append({
            "id": intent_id,
            "source": " ".join(source.split()),
            "kind": kind,
            "entity": item.get("entity"),
            "action": item.get("action"),
            "setup_entities": setup,
            "setup_values": dict(item.get("setup_values") or {}),
            "lookup": list(item.get("lookup") or []),
            "where": dict(item.get("where") or {}),
            "args": list(item.get("args") or []),
            "changes": dict(item.get("changes") or {}),
            "cli": list(item.get("cli") or []),
            "app": dict(item.get("app") or {}),
            "expect": dict(expect),
            "status": status,
            "assumptions": [str(x) for x in item.get("assumptions") or []
                            if _known(x)],
            "ambiguities": [str(x) for x in item.get("ambiguities") or []
                            if _known(x)],
        })
    return intents, errors


def _strip_json_comments(raw):
    """Remove // comments outside strings, a common small-model habit."""
    out = []
    in_string = False
    escaped = False
    index = 0
    while index < len(raw):
        char = raw[index]
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < len(raw) and raw[index + 1] == "/":
            while index < len(raw) and raw[index] not in "\r\n":
                index += 1
            continue
        out.append(char)
        index += 1
    return "".join(out)


def parse_payload(text):
    """Extract the first JSON object from a model reply."""
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    candidate = _strip_json_comments(raw[start:end + 1])
    candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
    try:
        return json.loads(candidate)
    except ValueError:
        return None


def _mentions(term, text):
    if not isinstance(term, str) or not term.strip():
        return False
    wanted = normalize(term)
    if not wanted:
        return False
    return wanted in normalize(text)


def ground_intents(intents, requirements):
    """Downgrade `confirmed` intents whose expected literal is not in their clause.

    The clause is the evidence boundary. A class, date or output copied from a
    neighbouring requirement is still useful, but it is an assumption about
    this behavior and must run as advisory evidence.
    """
    grounded = []
    for source in intents:
        intent = dict(source)
        reasons = list(intent.get("assumptions") or [])
        clause = intent.get("source") or ""
        expect = intent.get("expect") or {}
        error = expect.get("error")
        if isinstance(error, str) and error.strip() and not _mentions(error, clause):
            if _mentions(error, requirements):
                reasons.append(
                    f"error class {error!r} is only stated in another requirement")
            else:
                reasons.append(
                    f"error class {error!r} is not stated in the target clause")
        for value in (expect.get("state") or {}).values():
            if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[T ].*)?", value) \
                    and not _mentions(value, clause):
                reasons.append(f"expected date {value!r} is not stated in the target clause")
        if intent.get("kind") in ("app", "cli"):
            app = intent.get("app") or {}
            for arg in app.get("args") or intent.get("args") or intent.get("cli") or []:
                if isinstance(arg, str) and arg and not _mentions(arg, clause):
                    reasons.append(f"argument {arg!r} is not stated in the target clause")
            text = expect.get("stdout_contains")
            if isinstance(text, str) and text.strip() and not _mentions(text, clause):
                reasons.append("expected stdout is not stated in the target clause")
        if reasons and intent.get("status") == "confirmed":
            intent["status"] = "assumed"
        intent["assumptions"] = list(dict.fromkeys(reasons))
        grounded.append(intent)
    return grounded
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    values = payload.get("intents") if isinstance(payload, dict) else payload
    return [item for item in values or [] if isinstance(item, dict)]


def load_intents(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    values = payload.get("intents") if isinstance(payload, dict) else payload
    return [item for item in values or [] if isinstance(item, dict)]


def save_intents(path, intents):
    path = Path(path)
    path.write_text(
        json.dumps({"intents": intents}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return path
