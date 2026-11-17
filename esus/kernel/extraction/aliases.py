"""Human-asserted field mappings: `{action, field}` means `{flag}`.

Some adapter fields no rule can map: `file_path` where the leaf offers
`--output`, `copies` where the model declares `available_copies`. No
containment, no shared spelling — only the requirements author knows they
name one value. The review (`review_aliases.py`) asks about exactly those
pairs, and the answer persists here beside the documents.

Application is a rename, not a ruling: the adapter field takes the flag's
spelling while its target parameter stays put (`file_path` becomes `output`
into `file_path`). Everything downstream — the probe's uncovered and
unknown-field rules, the generator's flag binding — then judges the renamed
adapter with no special cases. A record whose action or field a run no
longer produces is skipped visibly, never applied blindly.

Like pattern decisions, each record carries the prompt sha it was decided
under and is only re-applied while the prompt stands; a record predating a
prompt change is dropped with a log line and its pair reopens for review.
"""

import json
from pathlib import Path

from kernel.extraction.decisions import requirements_sha

ALIASES_NAME = "field_aliases.json"
ALIASES_KEY = "aliases"
DECIDED_BY_USER = "user"


def load_aliases(output_dir):
    """The recorded mappings, or [] when there are none or the file is unusable."""
    try:
        payload = json.loads((Path(output_dir) / ALIASES_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    records = payload.get(ALIASES_KEY)
    return [item for item in records] if isinstance(records, list) else []


def save_aliases(output_dir, aliases):
    """Write the mapping records beside the documents."""
    path = Path(output_dir) / ALIASES_NAME
    path.write_text(
        json.dumps({ALIASES_KEY: aliases}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def apply_aliases(adapters, aliases, log=None, requirements_text=None):
    """Rename recorded fields to their asserted flag spellings.

    Returns the adapters (mutated in place, like the other repairs): every
    `{action, field}` the run still produces and whose prompt still stands
    takes the recorded flag name. Stale pairs and predated prompts are
    skipped with a log line each — an approval for vanished words applies to
    nothing.
    """
    if not isinstance(adapters, list):
        return adapters
    current = requirements_sha(requirements_text) if requirements_text else None
    applied = 0
    for record in aliases or []:
        if not (isinstance(record, dict)
                and isinstance(record.get("action"), str)
                and isinstance(record.get("field"), str)
                and isinstance(record.get("flag"), str)):
            continue
        stamped = record.get("requirements_sha")
        if (current is not None and isinstance(stamped, str)
                and stamped != current):
            if log is not None:
                log.write(
                    f"[!] step adapters: alias {record['action']}.{record['field']} "
                    f"predates a prompt change — dropped, will be re-asked"
                )
            continue
        if isinstance(record.get("create"), dict):
            # A creation record asserts a model field, not a rename: the
            # adapter field keeps its name by design, and apply_model_fields
            # owns the model side. Routing it through the rename below would
            # report a collision against itself.
            continue
        for adapter in adapters:
            if not (isinstance(adapter, dict)
                    and adapter.get("action_name") == record["action"]):
                continue
            fields = [f for f in adapter.get("input_fields") or []
                      if isinstance(f, dict)]
            target = next((f for f in fields
                           if f.get("field_name") == record["field"]), None)
            if target is None:
                continue
            if record["field"] == record["flag"]:
                continue
            if any(f is not target and f.get("field_name") == record["flag"]
                   for f in fields):
                if log is not None:
                    log.write(
                        f"[!] step adapters: alias {record['action']}.{record['field']} "
                        f"collides with an existing '{record['flag']}' — skipped"
                    )
                continue
            target["field_name"] = record["flag"]
            applied += 1
    if applied and log is not None:
        log.write(f"[ok] step adapters: applied {applied} recorded field alias(es)")
    return adapters


def apply_model_fields(models, aliases, log=None, requirements_text=None):
    """Ensure every reviewed-created field exists on its model.

    The review writes the field immediately; reruns regenerate the model
    from requirements and would drop it, so each run re-applies the
    recorded creations first. Entries without a `create` spec, stale
    entities, present fields and predated prompts are skipped — creation
    answers once, it does not insist.
    """
    if not isinstance(models, list):
        return models
    current = requirements_sha(requirements_text) if requirements_text else None
    applied = 0
    for record in aliases or []:
        if not isinstance(record, dict):
            continue
        spec = record.get("create")
        if not isinstance(spec, dict):
            continue
        stamped = record.get("requirements_sha")
        if (current is not None and isinstance(stamped, str)
                and stamped != current):
            if log is not None:
                log.write(
                    f"[!] step data_models: created field "
                    f"{spec.get('entity')}.{spec.get('name')} "
                    f"predates a prompt change — dropped, will be re-asked"
                )
            continue
        for model in models:
            if not (isinstance(model, dict) and model.get("name") == spec.get("entity")):
                continue
            fields = model.get("fields")
            if not isinstance(fields, list):
                continue
            if any(isinstance(f, dict) and f.get("name") == spec.get("name")
                   for f in fields):
                continue
            fields.append({
                "name": spec.get("name"),
                "type": spec.get("type"),
                "primary_key": False,
                "nullable": bool(spec.get("nullable", True)),
                "unique": bool(spec.get("unique", False)),
                "foreign_key": spec.get("foreign_key"),
                "status": "deduced",
            })
            applied += 1
    if applied and log is not None:
        log.write(f"[ok] step data_models: applied {applied} recorded created field(s)")
    return models
