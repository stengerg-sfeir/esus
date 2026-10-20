"""Human-confirmed behavior contracts for methods the emitter cannot derive.

The generator already checks a body against the API it was shown: names,
fields, return types, imports, and the generic create/update ordering. Those
checks cannot know what a method is *supposed* to change. "Return a book"
might mean setting a date and incrementing a stock field; "consume material"
might mean creating a consumption record and decrementing a different field.
Encoding either meaning in the generator would make it library-shaped or
factory-shaped and useless for the other.

This module stores the missing layer as data beside the extraction documents.
The review proposes a contract from the requirement and the emitted models,
the human confirms or edits it, and the generator compiles that record into
the prompt and the body checks. The vocabulary is domain-neutral:

    effects       a field set/incremented/decremented and the write that saves it
    creates       a model class created through a named repository call
    preconditions a check and whether a named error is raised when it is
                  true or when it is false
    order         the required order of the preconditions/create/write steps
    forbid        a field assignment that must not read another field

A record carries the same `requirements_sha` stamp as the slot and surface
decisions. A record from before a requirement change is dropped and its
question reopens; no stale answer is applied silently.
"""

import json
from pathlib import Path

from kernel.extraction.decisions import requirements_sha

METHOD_CONTRACTS_NAME = "method_contracts.json"
METHOD_CONTRACTS_KEY = "method_contracts"
CONTRACT_DECIDED_BY = "user"
OPS = ("set", "increment", "decrement")


def load_method_contracts(output_dir, requirements_text=None):
    """`(records, dropped)` from beside the documents, stale records removed.

    Missing or malformed files are simply no contracts. A record stamped
    with a different prompt sha is dropped rather than applied: the human
    answered it under words the run no longer uses, so the review must ask
    again. Records from before hashes existed keep applying.
    """
    try:
        payload = json.loads(
            (Path(output_dir) / METHOD_CONTRACTS_NAME).read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return [], 0
    if not isinstance(payload, dict):
        return [], 0
    current = requirements_sha(requirements_text)
    records, dropped = [], 0
    for raw in payload.get(METHOD_CONTRACTS_KEY) or []:
        record = normalize_contract(raw)
        if record is None:
            continue
        stamped = record.get("requirements_sha")
        if (current is not None and isinstance(stamped, str)
                and stamped != current):
            dropped += 1
            continue
        records.append(record)
    return records, dropped


def save_method_contracts(output_dir, records):
    """Write confirmed records beside the documents."""
    path = Path(output_dir) / METHOD_CONTRACTS_NAME
    path.write_text(
        json.dumps({METHOD_CONTRACTS_KEY: records}, indent=2,
                   ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def contract_for(records, holder, method):
    """The record for one holder/method, or None."""
    for record in records or []:
        if (isinstance(record, dict)
                and record.get("holder") == holder
                and record.get("method") == method):
            return record
    return None


def contract_index(records):
    """`{(holder, method): record}` for the generator's context."""
    return {(record["holder"], record["method"]): record
            for record in records or []
            if isinstance(record, dict)
            and isinstance(record.get("holder"), str)
            and isinstance(record.get("method"), str)}


def normalize_contract(raw):
    """One usable record, or None when it is not a contract at all.

    Unknown keys are dropped, but a malformed entry inside a known list is
    kept only when it carries the fields the generator can use. A record
    with no behavior at all is still valid: it means "this method has no
    confirmed effects", and it lets a review suppress a stale proposal.
    """
    if not isinstance(raw, dict):
        return None
    holder, method = raw.get("holder"), raw.get("method")
    if not (isinstance(holder, str) and isinstance(method, str)
            and holder and method):
        return None
    record = {"holder": holder, "method": method}
    if isinstance(raw.get("decided_by"), str):
        record["decided_by"] = raw["decided_by"]
    if isinstance(raw.get("requirements_sha"), str):
        record["requirements_sha"] = raw["requirements_sha"]

    effects = []
    for effect in raw.get("effects") or []:
        if not (isinstance(effect, dict)
                and isinstance(effect.get("target"), str)
                and effect.get("target")
                and effect.get("op") in OPS):
            continue
        item = {"target": effect["target"], "op": effect["op"]}
        if isinstance(effect.get("by"), (int, float, str)) \
                and not isinstance(effect.get("by"), bool):
            item["by"] = effect["by"]
        if isinstance(effect.get("value"), (str, int, float, bool)):
            item["value"] = effect["value"]
        if isinstance(effect.get("write"), str) and effect["write"]:
            item["write"] = effect["write"]
        effects.append(item)
    if effects:
        record["effects"] = effects

    creates = []
    for create in raw.get("creates") or []:
        if not isinstance(create, dict):
            continue
        item = {}
        for key in ("class", "call"):
            if isinstance(create.get(key), str) and create[key]:
                item[key] = create[key]
        if item:
            creates.append(item)
    if creates:
        record["creates"] = creates

    preconditions = []
    for precondition in raw.get("preconditions") or []:
        if not isinstance(precondition, dict):
            continue
        check = precondition.get("check")
        if not (isinstance(check, str) and check):
            continue
        item = {"check": check}
        if isinstance(precondition.get("error"), str) \
                and precondition["error"]:
            item["error"] = precondition["error"]
        if precondition.get("raise_when") in ("true", "false"):
            item["raise_when"] = precondition["raise_when"]
        preconditions.append(item)
    if preconditions:
        record["preconditions"] = preconditions

    order = [step for step in (raw.get("order") or [])
             if isinstance(step, str) and step]
    if order:
        record["order"] = order

    forbid = []
    for rule in raw.get("forbid") or []:
        if not (isinstance(rule, dict)
                and isinstance(rule.get("target"), str)
                and isinstance(rule.get("reads"), str)):
            continue
        item = {"target": rule["target"], "reads": rule["reads"]}
        if isinstance(rule.get("message"), str) and rule["message"]:
            item["message"] = rule["message"]
        forbid.append(item)
    if forbid:
        record["forbid"] = forbid
    return record
