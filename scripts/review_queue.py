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
from kernel.extraction.decisions import load_decisions  # noqa: E402


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
    }.get(group, "")


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
    for directory in directories:
        prompts.append({"prompt": directory.name,
                        "items": collect_for_directory(directory)})
    report = {
        "root": str(root),
        "summary": {
            "prompts": len(prompts),
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
