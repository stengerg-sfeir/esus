#!/usr/bin/env python3
"""Ask about a flag that several service methods could satisfy.

`repair_missing_method_flags` can type a missing flag only when exactly one
method/parameter pair matches it. When several methods match, the choice
changes the operation and the flag's type; this review asks for the chosen
service, method, parameter and option type and records them in
`flag_decisions.json`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import generator  # noqa: E402
from kernel.consistency import checks_surface as surface_checks  # noqa: E402
from kernel.consistency.naming import normalize  # noqa: E402
from kernel.extraction import repairs  # noqa: E402
from kernel.extraction.decisions import requirements_sha  # noqa: E402


def _decisions(directory):
    return repairs.load_flag_decisions(str(directory))


def _candidates(services, flag):
    found = []
    for service in services or []:
        if not isinstance(service, dict):
            continue
        for method in service.get("methods") or []:
            if not isinstance(method, dict) or not method.get("name"):
                continue
            if normalize(flag) not in normalize(method["name"]):
                continue
            for param in method.get("params") or []:
                if (isinstance(param, dict)
                        and normalize(param.get("name") or "") == normalize(flag)):
                    found.append({
                        "service": service.get("service_name"),
                        "method": method.get("name"),
                        "param": param.get("name"),
                        "type": param.get("type"),
                        "option_type": repairs._option_type(param.get("type")),
                    })
    return found


def _covered(decisions, command, sub, flag, candidates):
    for record in decisions:
        if (normalize(record.get("command") or "") != normalize(command)
                or normalize(record.get("subcommand") or "") != normalize(sub or "")
                or normalize(record.get("flag") or "") != normalize(flag)):
            continue
        for candidate in candidates:
            if (normalize(candidate["service"]) == normalize(record.get("service") or "")
                    and normalize(candidate["method"]) == normalize(record.get("method") or "")
                    and normalize(candidate["param"]) == normalize(record.get("param") or "")):
                return True
    return False


def collect_questions(output_dir):
    """`(questions, context)` for ambiguous missing flags."""
    directory = Path(output_dir)
    ctx = generator.load_context(str(directory))
    requirements = (directory / "requirements.txt").read_text(encoding="utf-8") \
        if (directory / "requirements.txt").is_file() else ""
    if not requirements:
        return [], {"requirements_sha": requirements_sha("")}
    facade = ctx.get("components", {}).get("facade") or {}
    invocation = facade.get("invocation") if isinstance(facade, dict) else None
    if not isinstance(invocation, dict):
        return [], {"requirements_sha": requirements_sha(requirements)}
    commands = surface_checks._commands_by_name(invocation)
    program = surface_checks._program_name(requirements)
    decisions = _decisions(directory)
    questions = []
    for span in re.findall(r"`([^`]*)`", requirements):
        target = surface_checks._resolve_span(span, program, commands)
        if target is None:
            continue
        command, sub = target
        leaf = repairs._find_leaf(invocation, command, sub)
        if leaf is None:
            continue
        for flag, bracketed in surface_checks._flags_in(span):
            if repairs._leaf_has_flag(leaf, flag):
                continue
            candidates = _candidates(ctx.get("services") or [], flag)
            if len(candidates) <= 1 or _covered(
                    decisions, command, sub, flag, candidates):
                continue
            questions.append({
                "command": command,
                "subcommand": sub,
                "flag": flag,
                "bracketed": bracketed,
                "source": span,
                "candidates": candidates,
                "requirements_sha": requirements_sha(requirements),
            })
    return questions, {"requirements_sha": requirements_sha(requirements)}


def describe_question(index, total, question):
    lines = [
        f"--- flag question {index}/{total} ---",
        f"source: {question.get('source')}",
        f"missing: --{question.get('flag')}",
        "candidates:",
    ]
    for number, candidate in enumerate(question.get("candidates") or [], start=1):
        lines.append(
            f"  {number}) {candidate.get('service')}."
            f"{candidate.get('method')}({candidate.get('param')}: "
            f"{candidate.get('type')}) -> {candidate.get('option_type')}")
    return lines


def ask(question, input_fn=input):
    candidates = question.get("candidates") or []
    try:
        answer = input_fn("choose a candidate number, or skip: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if answer.lower() in ("", "skip", "s"):
        return None
    try:
        index = int(answer) - 1
    except ValueError:
        return None
    return candidates[index] if 0 <= index < len(candidates) else None


def run_review(output_dir, input_fn=input, out_fn=print):
    questions, context = collect_questions(output_dir)
    if not questions:
        out_fn("no ambiguous method-backed flags — nothing to decide")
        return 0, 0
    records = _decisions(output_dir)
    answered = 0
    for number, question in enumerate(questions, start=1):
        for line in describe_question(number, len(questions), question):
            out_fn(line)
        chosen = ask(question, input_fn)
        if chosen is None:
            out_fn("skipped — left open")
            continue
        record = {
            "command": question["command"],
            "subcommand": question["subcommand"],
            "flag": question["flag"],
            "service": chosen["service"],
            "method": chosen["method"],
            "param": chosen["param"],
            "option_type": chosen["option_type"],
            "decided_by": "user",
            "requirements_sha": context["requirements_sha"],
        }
        records = [item for item in records
                   if not (normalize(item.get("command") or "") == normalize(record["command"])
                           and normalize(item.get("subcommand") or "") == normalize(record["subcommand"] or "")
                           and normalize(item.get("flag") or "") == normalize(record["flag"]))]
        records.append(record)
        answered += 1
    repairs.save_flag_decisions(str(output_dir), records)
    out_fn(f"answered {answered} of {len(questions)}; decisions in "
           f"{repairs.FLAG_DECISIONS_NAME}")
    return len(questions), answered


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("output_dir")
    args = parser.parse_args(argv)
    questions, _context = collect_questions(args.output_dir)
    if not questions:
        print("no ambiguous method-backed flags — nothing to decide")
        return 0
    input_fn = input
    run_review(args.output_dir, input_fn=input_fn)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
