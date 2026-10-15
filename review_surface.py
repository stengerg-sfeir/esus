#!/usr/bin/env python3
"""Ask the user about duplicated surface nodes no repair may remove.

A subcommand can duplicate a top-level command (`expense → category` beside
`category`): the model read one requirements line two ways, and only the
requirements author knows which node is real. Deleting either is a judgment —
deterministic repairs only ever remove what contradicts the rest of the
document — so this asks, records `{command, subcommand, keep}` in
`surface_decisions.json` beside the documents (prompt-sha stamped, like
pattern decisions and field aliases), and applies the drop to the on-disk
components immediately plus on every future run while the prompt stands.

Usage:
    python review_surface.py out/expenses          # ask open questions
    python review_surface.py out/expenses --list   # show open questions only

Keeping the parent drops the subcommand; keeping the sub drops the top-level
command; keeping both records the pair as resolved without touching it.
`skip` leaves the pair open. Whatever the probe still reports afterwards
(uncovered fields, unbound leaves) stays reported — this removes a node,
never a finding.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kernel import codegen  # noqa: E402
from kernel.consistency.loader import load_documents, load_requirements  # noqa: E402
from kernel.consistency.naming import normalize  # noqa: E402
from kernel.consistency.report import Report  # noqa: E402
from kernel.extraction.decisions import requirements_sha  # noqa: E402

SURFACE_DECISIONS_NAME = "surface_decisions.json"
SURFACE_DECISIONS_KEY = "decisions"

KEEP_PARENT = "parent"
KEEP_SUB = "sub"
KEEP_BOTH = "both"


def load_surface_decisions(output_dir):
    """The recorded surface decisions, or [] when there are none."""
    try:
        with open(os.path.join(output_dir, SURFACE_DECISIONS_NAME),
                  encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    records = payload.get(SURFACE_DECISIONS_KEY)
    return [item for item in records] if isinstance(records, list) else []


def save_surface_decisions(output_dir, decisions):
    """Write the surface decision records beside the documents."""
    path = os.path.join(output_dir, SURFACE_DECISIONS_NAME)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({SURFACE_DECISIONS_KEY: decisions}, indent=2,
                                ensure_ascii=False) + "\n")
    return path


def collect_duplicates(output_dir):
    """`(questions, context)`: subcommands duplicating a top-level command.

    Each question carries both nodes' flags and the requirements lines
    naming both words, so the human sees the two readings. Already-decided
    pairs never reopen while the prompt stands.
    """
    report = Report("review")
    documents = load_documents(output_dir, report)
    components = documents.get("components") or {}
    invocation = ((components.get("facade") or {}).get("invocation") or {})
    commands = invocation.get("commands")
    if not isinstance(commands, list):
        return [], {"prompt_sha": requirements_sha(load_requirements(output_dir))}
    tops = {}
    for command in commands:
        if isinstance(command, dict) and isinstance(command.get("name"), str):
            tops.setdefault(normalize(command["name"]), command)
    decided = set()
    for record in load_surface_decisions(output_dir):
        if isinstance(record, dict):
            decided.add((record.get("command"), record.get("subcommand")))
    requirements = load_requirements(output_dir) or ""
    questions = []
    for command in commands:
        if not isinstance(command, dict) or not isinstance(command.get("name"), str):
            continue
        for sub in command.get("subcommands") or []:
            if not isinstance(sub, dict) or not isinstance(sub.get("name"), str):
                continue
            top = tops.get(normalize(sub["name"]))
            if top is None or top is command:
                continue
            pair = (command["name"], sub["name"])
            if pair in decided:
                continue
            questions.append({
                "command": command["name"],
                "subcommand": sub["name"],
                "leaf_flags": [
                    o.get("name") for o in
                    codegen.leaf_options(invocation, command["name"], sub["name"])
                    if isinstance(o, dict) and o.get("name")],
                "top_subs": [
                    (s.get("name"),
                     [o.get("name") for o in (s.get("options") or [])
                      if isinstance(o, dict) and o.get("name")])
                    for s in (top.get("subcommands") or [])
                    if isinstance(s, dict) and isinstance(s.get("name"), str)],
                "evidence": _evidence(requirements, command["name"], sub["name"]),
            })
    context = {"prompt_sha": requirements_sha(requirements)}
    return questions, context


def _evidence(requirements, command, subcommand):
    """Backtick spans naming both words: the two readings, verbatim."""
    wanted = {normalize(command), normalize(subcommand)}
    lines = []
    for span in re.findall(r"`([^`]*)`", requirements or ""):
        tokens = {normalize(token) for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]*", span)}
        if wanted <= tokens and span.strip() not in lines:
            lines.append(span.strip())
    return lines


def describe_question(index, total, question):
    """Both nodes, their flags, and what each answer removes."""
    lines = [
        f"--- question {index}/{total} ---",
        f"DUPLICATE NODE: subcommand '{question['command']} {question['subcommand']}' "
        f"duplicates top-level command '{question['subcommand']}'.",
        f"  leaf '{question['command']} {question['subcommand']}' flags: "
        + (", ".join(f"'{f}'" for f in question["leaf_flags"]) or "none declared") + ".",
        f"  top-level '{question['subcommand']}' subcommands: "
        + (", ".join(
            f"{name} [{', '.join(flags) if flags else 'no flags'}]"
            for name, flags in question["top_subs"]) or "none") + ".",
    ]
    for span in question["evidence"]:
        lines.append(f"  requirements: `{span}`")
    lines += [
        f"  1) keep both (no change)",
        f"  2) keep '{question['command']}' — drop the subcommand",
        f"  3) keep '{question['subcommand']}' — drop the top-level command",
        "  Deleting is the one thing no deterministic repair may do unasked;",
        "  the probe keeps reporting whatever remains afterwards.",
    ]
    return lines


def ask(question, input_fn=input):
    """Pose one duplicate; return 'both', 'parent', 'sub', or None."""
    try:
        answer = input_fn("choose 1, 2, 3, or skip: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return None
    if answer in ("1", "both", "keep both"):
        return KEEP_BOTH
    if answer in ("2", "parent", "top"):
        return KEEP_PARENT
    if answer in ("3", "sub", "subcommand"):
        return KEEP_SUB
    return None


def apply_surface_decisions(components, records, log=None, requirements_text=None):
    """Drop human-rejected surface nodes; return the components.

    Records the pair resolved without touching it on `both`. Stale pairs
    (nodes a rerun no longer produces) and predated prompts are skipped
    with a log line each — a deletion for vanished words applies to nothing.
    """
    if not isinstance(components, dict):
        return components
    current = requirements_sha(requirements_text) if requirements_text else None
    kept = []
    for record in records or []:
        if not (isinstance(record, dict)
                and isinstance(record.get("command"), str)
                and isinstance(record.get("subcommand"), str)
                and record.get("keep") in (KEEP_PARENT, KEEP_SUB, KEEP_BOTH)):
            continue
        stamped = record.get("requirements_sha")
        if (current is not None and isinstance(stamped, str)
                and stamped != current):
            if log is not None:
                log.write(
                    f"[!] step components: surface decision for "
                    f"'{record['command']} {record['subcommand']}' "
                    f"predates a prompt change — dropped, will be re-asked"
                )
            continue
        kept.append(record)
    if not kept:
        return components
    invocation = ((components.get("facade") or {}).get("invocation") or {})
    commands = invocation.get("commands")
    if not isinstance(commands, list):
        return components
    applied = 0
    for record in kept:
        command, sub, keep = record["command"], record["subcommand"], record["keep"]
        if keep == KEEP_BOTH:
            applied += 1
            continue
        if keep == KEEP_PARENT:
            parent = next((c for c in commands
                           if isinstance(c, dict) and c.get("name") == command), None)
            subs = (parent.get("subcommands")
                    if isinstance(parent, dict) else None)
            if isinstance(subs, list) and any(
                    isinstance(s, dict) and s.get("name") == sub for s in subs):
                parent["subcommands"] = [
                    s for s in subs
                    if not (isinstance(s, dict) and s.get("name") == sub)]
                applied += 1
                if log is not None:
                    log.write(
                        f"[ok] step components: dropped subcommand '{command} {sub}' "
                        f"duplicating top-level '{sub}' (human decision)")
        else:
            if any(isinstance(c, dict) and c.get("name") == sub for c in commands):
                invocation["commands"] = [
                    c for c in commands
                    if not (isinstance(c, dict) and c.get("name") == sub)]
                commands = invocation["commands"]
                applied += 1
                if log is not None:
                    log.write(
                        f"[ok] step components: dropped top-level command '{sub}' "
                        f"(human decision)")
    return components


def run_review(output_dir, input_fn=input, out_fn=print):
    """Ask every open duplicate; return (asked, answered)."""
    questions, context = collect_duplicates(output_dir)
    if not questions:
        out_fn("no duplicated surface nodes — nothing to decide")
        return 0, 0
    records = load_surface_decisions(output_dir)
    answered = 0
    for number, question in enumerate(questions, start=1):
        for line in describe_question(number, len(questions), question):
            out_fn(line)
        keep = ask(question, input_fn)
        if keep is None:
            out_fn("skipped — left open")
            continue
        record = {
            "command": question["command"],
            "subcommand": question["subcommand"],
            "keep": keep,
            "decided_by": "user",
        }
        if context["prompt_sha"] is not None:
            record["requirements_sha"] = context["prompt_sha"]
        records.append(record)
        answered += 1
    save_surface_decisions(output_dir, records)
    path = os.path.join(output_dir, "components.json")
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as error:
        out_fn(f"error: cannot read {path}: {error}")
        return len(questions), answered
    payload["components"] = apply_surface_decisions(
        payload.get("components"), records)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    out_fn(f"answered {answered} of {len(questions)}; decisions in {SURFACE_DECISIONS_NAME}")
    return len(questions), answered


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    list_only = "--list" in args
    args = [a for a in args if a != "--list"]
    if len(args) != 1:
        print(__doc__.splitlines()[0], file=sys.stderr)
        print("usage: python review_surface.py OUT_DIR [--list]", file=sys.stderr)
        return 2
    if list_only:
        questions, _ = collect_duplicates(args[0])
        if not questions:
            print("no duplicated surface nodes — nothing to decide")
            return 0
        for number, question in enumerate(questions, start=1):
            for line in describe_question(number, len(questions), question):
                print(line)
        return 0
    asked, _ = run_review(args[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
