"""Human-confirmed decisions that are part of the accepted requirements.

Only current, user-decided sidecar records are included. Extracted documents,
inferred contracts and generated code are deliberately excluded.
"""

from __future__ import annotations

import json
from pathlib import Path

from kernel.extraction.decisions import requirements_sha

DECISION_FILES = (
    "decisions.json",
    "method_contracts.json",
    "surface_decisions.json",
    "grounding_decisions.json",
    "flag_decisions.json",
)


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _records(payload, key):
    value = payload.get(key) if isinstance(payload, dict) else payload
    return value if isinstance(value, list) else []


def collect(project):
    """`[decision dicts]` for one prompt, current and human-confirmed only."""
    project = Path(project)
    requirements = (project / "requirements.txt").read_text(encoding="utf-8") \
        if (project / "requirements.txt").is_file() else ""
    sha = requirements_sha(requirements)
    decisions = []

    def current(record):
        stamped = record.get("requirements_sha")
        return (record.get("decided_by") == "user"
                and (not stamped or stamped == sha))

    for record in _records(_read(project / "decisions.json"), "decisions"):
        if isinstance(record, dict) and current(record):
            decisions.append({
                "kind": "classification",
                "source": record.get("text"),
                "chosen": record.get("chosen_pattern_id"),
                "candidates": record.get("candidates") or [],
                "provenance": "decisions.json",
            })

    for record in _records(_read(project / "method_contracts.json"),
                           "method_contracts"):
        if not isinstance(record, dict) or not current(record):
            continue
        decisions.append({
            "kind": "method_contract",
            "source": f"{record.get('holder')}.{record.get('method')}",
            "chosen": {
                key: record[key] for key in
                ("effects", "creates", "preconditions", "reads", "derives",
                 "order", "forbid")
                if record.get(key)
            },
            "provenance": "method_contracts.json",
        })

    for filename, keys in (
            ("surface_decisions.json", ("decisions",)),
            ("grounding_decisions.json", ("decisions",)),
            ("flag_decisions.json", ("decisions",))):
        for record in _records(_read(project / filename), keys[0]):
            if not isinstance(record, dict) or not current(record):
                continue
            decisions.append({
                "kind": record.get("kind") or filename.split(".")[0],
                "source": " ".join(str(part) for part in (
                    record.get("command"), record.get("subcommand"),
                    record.get("flag"), record.get("holder"),
                    record.get("method")) if part),
                "chosen": {key: record[key] for key in (
                    "service", "method", "target_param", "option_type",
                    "transform", "keep") if record.get(key)},
                "provenance": filename,
            })
    return decisions, sha


def prompt_section(project):
    """A deterministic block for the verifier prompt."""
    decisions, sha = collect(project)
    if not decisions:
        return ""
    lines = ["", "CONFIRMED HUMAN DECISIONS (part of the requirements):"]
    for index, decision in enumerate(decisions, start=1):
        lines.append(
            f"{index}. [{decision['kind']}] {decision.get('source') or ''} "
            f"=> {json.dumps(decision.get('chosen'), ensure_ascii=False)}")
    lines.append("Do not generate a case that contradicts these decisions.")
    return "\n".join(lines)


def save(project, path=None):
    decisions, sha = collect(project)
    target = Path(path) if path else Path(project) / "oracle_spec.json"
    target.write_text(json.dumps({
        "requirements_sha": sha,
        "decisions": decisions,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target, len(decisions)
