#!/usr/bin/env python3
"""Review inferred unique fields before the generator enforces them.

The extractor records `unique_status=inferred` when a field is unique only
because of its name (`email`, `title`).  Inferred constraints are not enforced.
This review groups them by kind, asks one policy question per kind, and records
the answers in `unique_decisions.json`; the next repair or extraction applies
them to `data_models.json`.

Usage:
    python review_uniqueness.py OUT_DIR
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from kernel.extraction import uniqueness  # noqa: E402
from kernel.extraction.decisions import requirements_sha  # noqa: E402


def _read_models(output_dir):
    try:
        payload = json.loads(
            (Path(output_dir) / "data_models.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    models = payload.get("data_models") if isinstance(payload, dict) else None
    return models if isinstance(models, list) else []


def _requirements(output_dir):
    try:
        return (Path(output_dir) / "requirements.txt").read_text(
            encoding="utf-8")
    except OSError:
        return ""


def collect_questions(output_dir):
    """One prompt-level question, split into policy groups."""
    directory = Path(output_dir)
    decided = {record.get("policy") for record in
               uniqueness.load_policies(directory)}
    fields = [field for field in
              uniqueness.inferred_fields(_read_models(directory))
              if field.get("policy") not in decided]
    if not fields:
        return [], {"requirements_sha": requirements_sha(_requirements(directory))}
    groups = []
    by_policy = {}
    for field in fields:
        by_policy.setdefault(field["policy"], []).append(field)
    for policy in ("conventional", "display", "other"):
        if by_policy.get(policy):
            groups.append({"policy": policy, "fields": by_policy[policy]})
    return [{
        "kind": "inferred_unique",
        "groups": groups,
        "fields": fields,
        "requirements_sha": requirements_sha(_requirements(directory)),
    }], {"requirements_sha": requirements_sha(_requirements(directory))}


def collect_root_questions(root):
    """One grouped question for every inferred field under a validation root."""
    root = Path(root)
    decided = {record.get("policy") for record in
               uniqueness.load_policies(root)}
    fields = []
    for directory in sorted(path for path in root.glob("prompt_*")
                            if path.is_dir()):
        for field in uniqueness.inferred_fields(_read_models(directory)):
            if field.get("policy") not in decided:
                fields.append({**field, "prompt": directory.name})
    if not fields:
        return []
    groups = []
    by_policy = {}
    for field in fields:
        by_policy.setdefault(field["policy"], []).append(field)
    for policy in ("conventional", "display", "other"):
        if by_policy.get(policy):
            groups.append({"policy": policy, "fields": by_policy[policy]})
    return [{"kind": "inferred_unique", "groups": groups, "fields": fields}]


def _policy_label(policy):
    return {
        "conventional": "conventional identifiers (email, username, isbn, sku, code)",
        "display": "display names (name, title)",
        "other": "other inferred fields",
    }.get(policy, policy)


def describe_question(index, total, question):
    lines = [
        f"--- uniqueness question {index}/{total} ---",
        "The requirements do not state that these fields are unique:",
    ]
    for group in question.get("groups") or []:
        lines.append(f"  {_policy_label(group['policy'])}:")
        for field in group["fields"]:
            lines.append(f"    - {field['entity']}.{field['field']}")
    lines.append("  Inferred uniqueness is not enforced by default.")
    return lines


def ask(question, input_fn=input, group=None):
    """Return `True` (confirm all), `False` (reject all), or `None` (skip)."""
    label = ""
    if group is not None:
        names = ", ".join(
            f"{field['entity']}.{field['field']}"
            for field in group.get("fields") or [])
        label = f"  [{_policy_label(group.get('policy'))}: {names}]"
    try:
        answer = input_fn(
            (label + "\n  confirm all / reject all / skip "
             "[confirm/reject/skip]: ") if label else
            "  confirm all / reject all / skip [confirm/reject/skip]: "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return None
    if answer in ("confirm", "c", "yes", "y", "1"):
        return True
    if answer in ("reject", "r", "no", "n", "2"):
        return False
    return None


def run_root_review(root, input_fn=input, out_fn=print):
    """Ask one question per policy group for all prompts under a root."""
    root = Path(root)
    questions = collect_root_questions(root)
    if not questions:
        out_fn("no inferred unique fields — nothing to decide")
        return 0, 0
    records = uniqueness.load_policies(root)
    asked = answered = 0
    choices = {}
    for number, question in enumerate(questions, start=1):
        for line in describe_question(number, len(questions), question):
            out_fn(line)
        for group in question.get("groups") or []:
            asked += 1
            choice = ask(question, input_fn, group)
            if choice is None:
                out_fn("  skipped — left inferred and unenforced")
                continue
            answered += 1
            choices[group["policy"]] = choice
            record = {
                "policy": group["policy"],
                "unique": choice,
                "decided_by": "user",
            }
            records = [item for item in records
                       if item.get("policy") != record["policy"]]
            records.append(record)
    if choices:
        uniqueness.save_policies(root, records)
        for directory in sorted(path for path in root.glob("prompt_*")
                                if path.is_dir()):
            models = _read_models(directory)
            requirements = _requirements(directory)
            uniqueness.apply_policies(models, records)
            (directory / "data_models.json").write_text(
                json.dumps({"data_models": models}, indent=2,
                           ensure_ascii=False) + "\n", encoding="utf-8")
            path = directory / "invariants.json"
            if path.is_file():
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    payload = {}
                invariants = payload.get("invariants") if isinstance(
                    payload, dict) else None
                invariants = uniqueness.filter_invariants(
                    models, invariants or [])
                invariants = uniqueness.ensure_invariants(
                    models, invariants)
                if isinstance(payload, dict):
                    payload["invariants"] = invariants
                    path.write_text(
                        json.dumps(payload, indent=2,
                                   ensure_ascii=False) + "\n",
                        encoding="utf-8")
    out_fn(f"answered {answered} of {asked} group(s); policies in "
           f"{uniqueness.POLICY_NAME}")
    return asked, answered


def run_review(output_dir, input_fn=input, out_fn=print):
    questions, context = collect_questions(output_dir)
    if not questions:
        out_fn("no inferred unique fields — nothing to decide")
        return 0, 0
    records = uniqueness.load_decisions(output_dir)
    models = _read_models(output_dir)
    requirements = _requirements(output_dir)
    asked = answered = 0
    for number, question in enumerate(questions, start=1):
        for line in describe_question(number, len(questions), question):
            out_fn(line)
        for group in question.get("groups") or []:
            asked += 1
            choice = ask(question, input_fn, group)
            if choice is None:
                out_fn("  skipped — left inferred and unenforced")
                continue
            answered += 1
            for field in group["fields"]:
                record = {
                    "entity": field["entity"],
                    "field": field["field"],
                    "unique": choice,
                    "unique_status": uniqueness.CONFIRMED if choice
                                     else uniqueness.REJECTED,
                    "decided_by": "user",
                    "requirements_sha": context["requirements_sha"],
                }
                records = [
                    item for item in records
                    if not (
                        str(item.get("entity") or "").lower()
                        == str(record["entity"]).lower()
                        and str(item.get("field") or "").lower()
                        == str(record["field"]).lower()
                    )
                ]
                records.append(record)
    uniqueness.save_decisions(output_dir, records)
    uniqueness.apply_decisions(
        models, records, requirements_text=requirements)
    uniqueness.apply_policies(
        models, uniqueness.load_policies(output_dir), None)
    (Path(output_dir) / "data_models.json").write_text(
        json.dumps({"data_models": models}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    invariants_path = Path(output_dir) / "invariants.json"
    if invariants_path.is_file():
        try:
            payload = json.loads(invariants_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = {}
        invariants = payload.get("invariants") if isinstance(payload, dict) else None
        invariants = uniqueness.filter_invariants(models, invariants or [])
        invariants = uniqueness.ensure_invariants(models, invariants)
        if isinstance(payload, dict):
            payload["invariants"] = invariants
            invariants_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8")
    out_fn(f"answered {answered} of {asked} group(s); decisions in "
           f"{uniqueness.DECISIONS_NAME}")
    return asked, answered


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("output_dir", nargs="?")
    parser.add_argument("--root", default=None,
                        help="validation root: decide grouped policies for "
                             "all prompt_* directories")
    args = parser.parse_args(argv)
    if args.root:
        run_root_review(args.root, input_fn=input)
        return 0
    if not args.output_dir:
        parser.error("output_dir or --root is required")
    questions, _context = collect_questions(args.output_dir)
    if not questions:
        print("no inferred unique fields — nothing to decide")
        return 0
    run_review(args.output_dir, input_fn=input)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
