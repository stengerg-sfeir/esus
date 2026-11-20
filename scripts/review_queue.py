#!/usr/bin/env python3
"""Build the attended-review queue for one validation tree.

Every review module already knows its own open questions. This script puts
them in one place, with the prompt, source, candidate evidence and the
review command that can resolve each item. It never answers anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import review_aliases  # noqa: E402
import review_flags  # noqa: E402
import review_contracts  # noqa: E402
import review_grounding  # noqa: E402
import review_slots  # noqa: E402
import review_surface  # noqa: E402
import review_ties  # noqa: E402
import review_uniqueness  # noqa: E402
from kernel.extraction.decisions import load_decisions  # noqa: E402
from kernel.oracle import cases as oracle_cases  # noqa: E402


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _item(prompt, group, source, question, candidates=None):
    return {
        "prompt": prompt,
        "group": group,
        "source": source,
        "question": question,
        "candidates": candidates or [],
        "review_command": _review_command(group),
    }


def _review_command(group):
    return {
        "ties": "python review_ties.py PROMPT_DIR",
        "slots": "python review_slots.py PROMPT_DIR",
        "surface": "python review_surface.py PROMPT_DIR",
        "aliases": "python review_aliases.py PROMPT_DIR",
        "grounding": "python review_grounding.py PROMPT_DIR",
        "contracts": "python review_contracts.py PROMPT_DIR",
        "flags": "python review_flags.py PROMPT_DIR",
        "uniqueness": "python review_uniqueness.py PROMPT_DIR",
        "provenance": "review the inferred artifact and record a decision",
        "oracle": "python scripts/review_oracle.py PROMPT_DIR",
    }.get(group, "")


def _provenance_questions(directory):
    """Artifacts marked inferred/review-required by extraction repairs."""
    questions = []
    for filename, key, label_key in (
            ("data_models.json", "data_models", "name"),
            ("interaction_adapters.json", "interaction_adapters", "action_name"),
            ("persistence_ports.json", "persistence_ports", None)):
        payload = _read_json(directory / filename)
        records = payload.get(key) if isinstance(payload, dict) else None
        if key == "persistence_ports":
            records = (records or {}).get("repositories") if isinstance(records, dict) else []
        for record in records or []:
            if not isinstance(record, dict) or not record.get("review_required"):
                continue
            if key == "persistence_ports":
                for method in record.get("methods") or []:
                    if isinstance(method, dict) and method.get("review_required"):
                        questions.append({
                            "kind": "inferred method",
                            "artifact": f"{record.get('interface_name') or record.get('entity')}.{method.get('name')}",
                            "provenance": method.get("provenance"),
                            "review_required": True,
                        })
                continue
            questions.append({
                "kind": "inferred artifact",
                "artifact": record.get(label_key) or record.get("name"),
                "provenance": record.get("provenance"),
                "review_required": True,
            })
    components = _read_json(directory / "components.json").get("components") or {}
    for key in ("persistence", "facade"):
        value = components.get(key)
        if isinstance(value, dict) and value.get("review_required"):
            questions.append({
                "kind": "inferred component",
                "artifact": key,
                "provenance": value.get("provenance"),
                "review_required": True,
            })
    for service in components.get("crud_services") or []:
        if isinstance(service, dict) and service.get("review_required"):
            questions.append({
                "kind": "inferred component",
                "artifact": f"crud:{service.get('entity')}",
                "provenance": service.get("provenance"),
                "review_required": True,
            })
    return questions


def collect_for_directory(directory, prompt=None):
    """Every unresolved question for one prompt directory."""
    directory = Path(directory)
    prompt = prompt or directory.name
    items = []

    matches = _read_json(directory / "pattern_matches.json").get(
        "pattern_matches")
    if isinstance(matches, list):
        decided = {record.get("text") for record in load_decisions(str(directory))
                   if isinstance(record, dict)}
        for entry in review_ties.collect_questions(matches, decided):
            items.append(_item(
                prompt, "ties", entry.get("text") or "pattern tie", entry,
                [entry.get("pattern_id"), entry.get("claimed_pattern_id"),
                 entry.get("alternative")]))

    slots, _context = review_slots.collect_slots(str(directory))
    for question in slots:
        items.append(_item(
            prompt, "slots", f"{question.get('holder')}.{question.get('method')}",
            question, question.get("options")))

    duplicates, _context = review_surface.collect_duplicates(str(directory))
    for question in duplicates:
        items.append(_item(
            prompt, "surface", f"{question.get('command')} {question.get('subcommand')}",
            question))
    routes, _context = review_surface.collect_routes(str(directory))
    for question in routes:
        if question.get("kind") == "upstream-gap":
            # It is still a review item, but the module labels it as an
            # extraction gap rather than a route choice.
            pass
        items.append(_item(
            prompt, "surface",
            f"{question.get('command')} {question.get('subcommand') or ''} "
            f"{question.get('flag') or ''}".strip(), question,
            question.get("candidate_details")))

    aliases, _context = review_aliases.collect_questions(str(directory))
    for question in aliases:
        items.append(_item(
            prompt, "aliases", f"{question.get('action')}.{question.get('field')}",
            question))

    for question in review_grounding.collect_questions(str(directory)):
        items.append(_item(
            prompt, "grounding", question.get("holder") or question.get("kind"),
            question, question.get("methods")))

    flag_questions, _context = review_flags.collect_questions(str(directory))
    for question in flag_questions:
        items.append(_item(
            prompt, "flags",
            f"{question.get('command')} {question.get('subcommand') or ''} "
            f"--{question.get('flag')}".strip(),
            question, question.get("candidates")))

    for question in _provenance_questions(directory):
        items.append(_item(
            prompt, "provenance", question.get("artifact"), question))

    unique_questions, _unique_context = review_uniqueness.collect_questions(
        str(directory))
    for question in unique_questions:
        fields = question.get("fields") or []
        for field in fields:
            field.setdefault("prompt", prompt)
        items.append(_item(
            prompt, "uniqueness",
            ", ".join(f"{field.get('entity')}.{field.get('field')}"
                      for field in fields),
            question,
            [f"{field.get('entity')}.{field.get('field')}"
             for field in fields]))

    oracle_groups = {}
    for case in oracle_cases.open_questions(
            oracle_cases.load_cases(directory / oracle_cases.CASES_NAME)):
        triage = str(case.get("triage") or "")
        if triage.startswith("behavior"):
            key = (prompt, triage)
        elif case.get("status") == "contradictory":
            key = (prompt, "contradictory")
        else:
            # Candidate assumptions are not human questions until execution
            # produces evidence. They stay in oracle_cases.json.
            continue
        oracle_groups.setdefault(key, []).append(case)
    for (prompt_name, kind), cases in sorted(oracle_groups.items()):
        items.append(_item(
            prompt_name, "oracle", kind,
            {
                "kind": kind,
                "cases": [
                    {"id": case.get("id"), "execution": case.get("execution")}
                    for case in cases
                ],
            },
            [case.get("id") for case in cases]))

    contracts, _context = review_contracts.collect_contracts(str(directory))
    for proposal in contracts:
        items.append(_item(
            prompt, "contracts",
            f"{proposal.get('holder')}.{proposal.get('method')}",
            proposal, proposal.get("questions")))
    return items


def write_markdown(report, path):
    lines = ["# ESUS review queue", "",
             f"Open questions: **{report['summary']['open']}**", ""]
    for prompt in report["prompts"]:
        if not prompt["items"]:
            continue
        lines.append(f"## {prompt['prompt']}")
        lines.append("")
        for item in prompt["items"]:
            lines.append(f"### {item['group']}")
            lines.append("")
            lines.append(f"- source: `{item['source']}`")
            if item.get("candidates"):
                lines.append("- candidates: "
                             + json.dumps(item["candidates"], ensure_ascii=False))
            lines.append("- question: "
                         + json.dumps(item["question"], ensure_ascii=False))
            lines.append(f"- resolve: `{item['review_command']}`")
            lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", help="validation root containing prompt_* directories")
    parser.add_argument("--output", default=None,
                        help="JSON output (default: <root>/review_queue.json)")
    parser.add_argument("--markdown", default=None,
                        help="optional Markdown output path")
    parser.add_argument("--fail-on-open", action="store_true",
                        help="exit 1 when the queue is non-empty")
    args = parser.parse_args(argv)
    root = Path(args.root)
    directories = sorted(path for path in root.glob("prompt_*") if path.is_dir())
    prompts = []
    unique_fields = []
    for directory in directories:
        items = collect_for_directory(directory)
        kept = []
        for item in items:
            if item["group"] == "uniqueness":
                unique_fields.extend(
                    (item.get("question") or {}).get("fields") or [])
            else:
                kept.append(item)
        prompts.append({"prompt": directory.name, "items": kept})
    if unique_fields:
        policies = {}
        for field in unique_fields:
            policies[field.get("policy")] = policies.get(
                field.get("policy"), 0) + 1
        global_item = _item(
            str(root), "uniqueness", f"{len(unique_fields)} inferred field(s)",
            {"kind": "inferred_unique", "fields": unique_fields,
             "policy_counts": policies},
            [f"{field.get('prompt')}:{field.get('entity')}.{field.get('field')}"
             for field in unique_fields])
        global_item["review_command"] = (
            f"python review_uniqueness.py --root {root}")
        prompts.append({"prompt": f"{root.name} (all prompts)",
                        "items": [global_item]})
    report = {
        "root": str(root),
        "summary": {
            "prompts": len(directories),
            "open": sum(len(item["items"]) for item in prompts),
            "groups": {},
        },
        "prompts": prompts,
    }
    for prompt in prompts:
        for item in prompt["items"]:
            groups = report["summary"]["groups"]
            groups[item["group"]] = groups.get(item["group"], 0) + 1
    output = Path(args.output) if args.output else root / "review_queue.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    if args.markdown:
        write_markdown(report, Path(args.markdown))
    print(json.dumps(report["summary"], indent=2))
    if args.fail_on_open and report["summary"]["open"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
