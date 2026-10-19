#!/usr/bin/env python3
"""Ask the user about surface nodes and flags no repair may decide alone.

A subcommand can duplicate a top-level command (`expense → category` beside
`category`): the model read one requirements line two ways, and only the
requirements author knows which node is real. Deleting either is a judgment —
deterministic repairs only ever remove what contradicts the rest of the
document — so this asks, records `{command, subcommand, keep}` in
`surface_decisions.json` beside the documents (prompt-sha stamped, like
pattern decisions and field aliases), and applies the drop to the on-disk
components immediately plus on every future run while the prompt stands.

A declared flag can also parse and select nothing (`member list
-active-only` printed every member): its leaf binds a parameterless read,
and the service's other parameterless reads are the finite candidates.
The human names the one the flag selects; that lands as a `kind: "route"`
record in the same file, and the generator emits the dispatch.

Usage:
    python review_surface.py out/expenses          # ask open questions
    python review_surface.py out/expenses --list   # show open questions only

Keeping the parent drops the subcommand; keeping the sub drops the top-level
command; keeping both records the pair as resolved without touching it.
`skip` leaves a question open. Whatever the probe still reports afterwards
(uncovered fields, unbound leaves) stays reported — this removes a node or
routes a flag, never a finding.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import generator  # noqa: E402
from kernel import codegen  # noqa: E402
from kernel.consistency.checks_surface import COMMAND_VERB_STEMS  # noqa: E402
from kernel.consistency.loader import load_documents, load_requirements  # noqa: E402
from kernel.consistency.naming import normalize  # noqa: E402
from kernel.consistency.report import Report  # noqa: E402
from kernel.extraction.decisions import requirements_sha  # noqa: E402

SURFACE_DECISIONS_NAME = generator.SURFACE_DECISIONS_NAME
SURFACE_DECISIONS_KEY = generator.SURFACE_DECISIONS_KEY
ROUTE_KIND = generator.SURFACE_ROUTE_KIND

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


def _usable(ctx, holder, method):
    """Mechanical, or fully answered by slots: a routed read must run."""
    entry = generator._match_entry(ctx, holder, method.get("name"))
    strategy, _detail = codegen.plan_method(method, entry, ctx["entity_names"])
    if strategy.startswith("crud:"):
        return True
    pattern, slots = generator._slot_pattern(ctx, holder, method)
    return bool(pattern) and generator._slots_usable(pattern, slots, method,
                                                     True)


def _route_candidates(ctx, service, base_method_name):
    """Parameterless collection reads on the leaf's own service.

    `(service, method)` pairs, the base read excluded, stubs excluded —
    routing a flag to a stub moves the stub, it does not fix it.
    """
    wanted = normalize(service or "")
    candidates = []
    pools = []
    for repo in ctx["repositories"]:
        names = {normalize(repo.get("interface_name") or ""),
                 normalize(repo.get("entity") or "")}
        if wanted in names:
            pools.append((repo.get("interface_name") or repo.get("entity"),
                          repo.get("methods") or []))
    for svc in ctx["services"]:
        if normalize(svc.get("service_name") or "") == wanted:
            pools.append((svc.get("service_name"), svc.get("methods") or []))
    for holder, methods in pools:
        for method in methods:
            if not isinstance(method, dict) or not method.get("name"):
                continue
            if method["name"] == base_method_name or method.get("params"):
                continue
            if generator._return_shape(ctx, method.get("return_type")) \
                    not in ("collection", "entity"):
                continue
            if not _usable(ctx, holder, method):
                continue
            candidates.append((service, method["name"]))
    return sorted(set(candidates))


def collect_routes(output_dir):
    """`(questions, context)`: dead flags that could select a read.

    A declared flag whose adapter fields never consume it parses and does
    nothing (`member list -active-only`). The leaf's own bound method must
    be a parameterless read; its service's other parameterless read
    methods are the finite candidates. The human says which one the flag
    selects — no name rule may — and the generator emits that dispatch on
    every run while the prompt stands.
    """
    ctx = generator.load_context(output_dir)
    invocation = (ctx["components"].get("facade") or {}).get("invocation") or {}
    bindings, _unmapped = codegen.bind_commands(ctx["adapters"], invocation,
                                               COMMAND_VERB_STEMS)
    leaves, actions, _argv, _targets, _assembled = generator._leaf_scan(
        ctx, bindings, {})
    # Only a record that still resolves closes its question: one pointing at
    # a method the documents no longer carry must reopen, not silently hide.
    decided = set()
    for record in ctx.get("routes") or []:
        if generator._service_method(ctx, record.get("service"),
                                     record.get("method")) is None:
            continue
        decided.add((record.get("command"), record.get("subcommand"),
                     record.get("flag")))
    questions = []
    for leaf in leaves:
        if leaf["choices"] is None:
            continue
        where = (leaf["command"], leaf["subcommand"])
        base_action = leaf["choices"][-1][0]
        spec = actions.get(base_action) or {}
        service = spec.get("target_service")
        base_method = generator._service_method(ctx, service,
                                                spec.get("target_method"))
        if base_method is None or base_method.get("params"):
            continue
        for dest, flag, kind in leaf["dead"]:
            if kind != "truthy":
                continue  # a valued flag selects nothing by itself
            if (where[0], where[1], dest) in decided:
                continue
            candidates = _route_candidates(ctx, service,
                                           base_method.get("name"))
            if not candidates:
                continue
            questions.append({
                "command": where[0],
                "subcommand": where[1],
                "flag": dest,
                "flag_name": flag,
                "service": service,
                "reads": base_method.get("name"),
                "candidates": candidates,
            })
    context = {"prompt_sha": requirements_sha(load_requirements(output_dir))}
    return questions, context


def describe_route(index, total, question):
    """The stranded flag, the unfiltered read it rides on, the candidates."""
    leaf = question["command"]
    if question["subcommand"]:
        leaf += f" {question['subcommand']}"
    lines = [
        f"--- question {index}/{total} ---",
        f"FLAG SELECTING A READ: '{leaf} {question['flag_name']}' parses today "
        f"and does nothing.",
        f"  the command reads {question['service']}.{question['reads']} "
        f"(no arguments) when the flag is passed.",
        "  candidate methods:",
    ]
    for number, (service, method) in enumerate(question["candidates"], start=1):
        lines.append(f"    {number}) {service}.{method}")
    lines += [
        "  The documents link the flag to none of them; only you can say",
        "  which one it selects. skip leaves the flag reported.",
    ]
    return lines


def ask_route(question, input_fn=input):
    """One candidate number (or name); None on skip."""
    shown = ", ".join(str(n) for n in range(1, len(question["candidates"]) + 1))
    try:
        answer = input_fn(f"choose {shown}, or skip: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return None
    if answer.isdigit():
        index = int(answer) - 1
        if 0 <= index < len(question["candidates"]):
            return question["candidates"][index]
    for service, method in question["candidates"]:
        if answer in (method.lower(), f"{service.lower()}.{method.lower()}"):
            return (service, method)
    return None


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
    """Ask every open duplicate and stranded flag; return (asked, answered)."""
    duplicates, context = collect_duplicates(output_dir)
    routes, _route_context = collect_routes(output_dir)
    questions = ([("duplicate", question) for question in duplicates]
                 + [("route", question) for question in routes])
    if not questions:
        out_fn("no duplicated surface nodes or stranded flags — nothing to decide")
        return 0, 0
    records = load_surface_decisions(output_dir)
    answered = 0
    for number, (kind, question) in enumerate(questions, start=1):
        if kind == "duplicate":
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
        else:
            for line in describe_route(number, len(questions), question):
                out_fn(line)
            picked = ask_route(question, input_fn)
            if picked is None:
                out_fn("skipped — left open")
                continue
            service, method = picked
            record = {
                "kind": ROUTE_KIND,
                "command": question["command"],
                "subcommand": question["subcommand"],
                "flag": question["flag"],
                "service": service,
                "method": method,
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
        duplicates, _ = collect_duplicates(args[0])
        routes, _ = collect_routes(args[0])
        total = len(duplicates) + len(routes)
        if not total:
            print("no duplicated surface nodes or stranded flags — nothing to decide")
            return 0
        for number, question in enumerate(duplicates, start=1):
            for line in describe_question(number, total, question):
                print(line)
        for number, question in enumerate(routes, start=len(duplicates) + 1):
            for line in describe_route(number, total, question):
                print(line)
        return 0
    asked, _ = run_review(args[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
