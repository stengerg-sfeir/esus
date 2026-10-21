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
-active-only` printed every member, `book list --author` is ignored): its
leaf binds a parameterless read, and methods in the command's CRUD family
are the finite route candidates. A candidate whose result fits the command
and whose signature one flag can carry is proposed with its full
signature; choosing it records the target parameter and retypes the flag
(e.g. `--author` becomes an integer author id). A dead option with no
candidate is still asked; the deterministic answer there is `drop`,
recorded as `kind: "drop-flag"` beside the route records and applied to the
surface.

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
DROP_FLAG_KIND = "drop-flag"

KEEP_PARENT = "parent"
KEEP_SUB = "sub"
KEEP_BOTH = "both"
DROP_FLAG = "drop"


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


def _emitted_methods(ctx):
    """`{(holder, method): implemented}` from the mechanical emitters.

    A planned `crud:` strategy is not enough: a filter whose parameter maps
    no field, or a service with no same-name repository to delegate to,
    still emits a stub. Route candidates must be methods that actually run,
    so ask the emitters once and use their rows.
    """
    cached = ctx.get("_review_emitted")
    if isinstance(cached, dict):
        return cached
    stats = {"implemented": 0, "stubs": 0, "stub_reasons": [], "methods": []}
    generator.emit_repositories(ctx, stats)
    generator.emit_services(ctx, generator._repo_index(ctx), stats)
    index = {(row.get("holder"), row.get("method")): bool(row.get("implemented"))
             for row in stats.get("methods") or [] if isinstance(row, dict)}
    ctx["_review_emitted"] = index
    return index


def _usable(ctx, holder, method):
    """The method's emitted body runs (mechanical, slots, or delegation)."""
    index = _emitted_methods(ctx)
    return index.get((holder, method.get("name")), False)


# Command verb -> operation family. A route is offered only when the method
# belongs to the family the command promises: `book list` may select a read,
# `book add` a create, `book delete` a delete. This uses the same CRUD
# vocabulary as the generator; it is a name/pattern classification, not a
# claim that every domain verb folds into CRUD.
COMMAND_FAMILIES = {
    "add": "create", "create": "create", "insert": "create",
    "save": "create", "new": "create", "register": "create",
    "list": "read", "search": "read", "get": "read", "show": "read",
    "history": "read", "report": "read", "export": "read",
    "overdue": "read", "detect": "read",
    "update": "update", "edit": "update", "set": "update",
    "delete": "delete", "remove": "delete",
    "borrow": "create", "return": "update", "renew": "update",
    "confirm": "update", "cancel": "update", "assign": "update",
    "restock": "update",
}

CRUD_FAMILIES = {
    "create": "create",
    "read_one": "read", "read_all": "read", "filter": "read",
    "update": "update",
    "delete": "delete",
}

# A routed method may consume the flag itself. One flag supplies one
# parameter, so only signatures with zero or one scalar parameter are
# routable. The option is retyped to the parameter's type; nothing is
# guessed for entities, decimals, or unknown spellings.
ROUTE_PARAM_TYPES = {
    "int": ("int", "DIRECT"), "integer": ("int", "DIRECT"),
    "str": ("str", "DIRECT"), "string": ("str", "DIRECT"),
    "text": ("str", "DIRECT"),
    "float": ("float", "DIRECT"), "double": ("float", "DIRECT"),
    "number": ("float", "DIRECT"),
    "bool": ("bool", "DIRECT"), "boolean": ("bool", "DIRECT"),
    "date": ("str", "ISO_DATE"), "datetime": ("str", "ISO_DATE"),
}

_LIST_PARAM_TYPES = {
    "int": "INT_LIST", "integer": "INT_LIST",
    "str": "DIRECT", "string": "DIRECT", "text": "DIRECT",
}


def _route_param_option(ctx, param):
    """`{param, param_type, option_type, transform}` for a routable parameter.

    The CLI can carry one value; a scalar maps directly, a date is parsed by
    its transform, and a list becomes argparse's list. Entity-typed and
    unknown parameters return None — silently converting those would be a
    guess, not an adaptation.
    """
    ptype = param.get("type") if isinstance(param, dict) else None
    if not isinstance(ptype, str) or not ptype.strip():
        return None
    text = ptype.strip()
    if codegen.is_entity_type(text, ctx["entity_names"]):
        return None
    optional = re.fullmatch(r"(?i)optional\s*\[(.+)\]", text)
    if optional:
        return _route_param_option(ctx, {"type": optional.group(1).strip()})
    listed = re.fullmatch(r"(?i)list\s*\[(.+)\]", text)
    if listed:
        item = listed.group(1).strip()
        if codegen.is_entity_type(item, ctx["entity_names"]):
            return None
        lowered = item.lower()
        transform = _LIST_PARAM_TYPES.get(lowered)
        if transform is None:
            return None
        option_type = "list"
    else:
        union = re.fullmatch(r"(?i)union\s*\[(.+)\]", text)
        if union:
            parts = [part.strip() for part in union.group(1).split(",")]
            if any(codegen.is_entity_type(part, ctx["entity_names"])
                   for part in parts):
                return None
            kinds = {part.lower() for part in parts}
            if kinds & {"str", "string", "text"}:
                option_type, transform = "str", "DIRECT"
            elif kinds <= {"int", "integer"}:
                option_type, transform = "int", "DIRECT"
            else:
                return None
        else:
            option_type, transform = ROUTE_PARAM_TYPES.get(text.lower(),
                                                           (None, None))
    if option_type is None:
        return None
    return {"param": param.get("name"), "param_type": ptype,
            "option_type": option_type, "transform": transform}


def _route_candidate_detail(ctx, service, method_name):
    """The routable signature of a candidate, or None when one flag cannot
    carry it."""
    method = generator._service_method(ctx, service, method_name)
    if method is None:
        return None
    params = [p for p in method.get("params") or [] if isinstance(p, dict)]
    if not params:
        return {"param": None, "param_type": None, "option_type": None,
                "transform": None, "signature": _method_signature(method)}
    if len(params) != 1:
        return None
    option = _route_param_option(ctx, params[0])
    if option is None:
        return None
    option["param"] = params[0].get("name")
    option["param_type"] = params[0].get("type")
    option["signature"] = _method_signature(method)
    return option


def _method_signature(method):
    params = ", ".join(
        f"{p.get('name')}: {p.get('type')}" for p in method.get("params") or []
        if isinstance(p, dict))
    return (f"{method.get('name')}({params}) -> "
            f"{method.get('return_type') or 'None'}")


def _return_entity(ctx, returns):
    """The modeled entity named by a return type, or None."""
    if not isinstance(returns, str):
        return None
    words = {normalize(token) for token in
             re.findall(r"[A-Za-z_][A-Za-z0-9_]*", returns)}
    for entity in ctx["entity_names"]:
        if isinstance(entity, str) and normalize(entity) in words:
            return entity
    return None


def _service_entity(ctx, service):
    """The entity of a repository/service reference, when it names one."""
    wanted = normalize(service or "")
    for repo in ctx["repositories"]:
        names = {normalize(repo.get("interface_name") or ""),
                 normalize(repo.get("entity") or "")}
        if wanted in names:
            return repo.get("entity")
    return None


def _command_family(verb):
    """The CRUD family a command's verb promises, or None when unknown."""
    return COMMAND_FAMILIES.get(normalize(verb or ""))


def _method_family(ctx, holder, method):
    """The CRUD family of a method, from its plan then its name.

    The planned strategy is authoritative when the pattern step classified
    the method. Otherwise the shared `classify_crud` prefixes decide; an
    unrecognized method is `None`, never guessed into a family.
    """
    entry = generator._match_entry(ctx, holder, method.get("name"))
    strategy, _detail = codegen.plan_method(
        method, entry, ctx["entity_names"])
    if strategy.startswith("crud:"):
        kind = strategy.split(":", 1)[1]
    else:
        kind = codegen.classify_crud(method.get("name"))
    return CRUD_FAMILIES.get(kind)


def _route_candidates(ctx, service, base_method_name, command_verb=None,
                      flag_kind=None):
    """Methods in the command's family that one flag can actually carry.

    The old rule demanded a parameterless method. A flag can also supply a
    single parameter, so a read command may select `find_books_by_author(
    author_id: int)` and retype `--author` to an integer. What still gates a
    candidate:

    - same CRUD family (`list` never selects a create or delete);
    - the result displays like the command's base result (a list command
      selects a list, a get selects one entity);
    - the same modeled entity (a book command never selects authors);
    - zero or one scalar/list parameter, and no entity/unknown parameter;
    - a mechanical or fully-slotted body (`_usable`).

    Reads may cross from the leaf's repository to a service returning the
    same entity (`AuthorRepository.find_books_by_author`); writes stay on
    the leaf's own service.
    """
    family = _command_family(command_verb)
    if family is None:
        return []
    base_method = generator._service_method(ctx, service, base_method_name)
    if base_method is None:
        return []
    base_shape = generator._return_shape(ctx, base_method.get("return_type"))
    base_entity = (_return_entity(ctx, base_method.get("return_type"))
                   or _service_entity(ctx, service))
    wanted = normalize(service or "")
    candidates = []
    pools = []
    repo_names = {normalize(repo.get("interface_name") or "")
                  for repo in ctx["repositories"]}
    for repo in ctx["repositories"]:
        holder = repo.get("interface_name") or repo.get("entity")
        pools.append((holder, repo.get("methods") or []))
    for svc in ctx["services"]:
        if normalize(svc.get("service_name") or "") in repo_names:
            continue  # the persistence emitter already owns this holder
        pools.append((svc.get("service_name"), svc.get("methods") or []))
    for holder, methods in pools:
        if not isinstance(holder, str):
            continue
        same_service = normalize(holder) == wanted
        for method in methods:
            if not isinstance(method, dict) or not method.get("name"):
                continue
            if (same_service and method["name"] == base_method_name):
                continue
            if _method_family(ctx, holder, method) != family:
                continue
            detail = _route_candidate_detail(ctx, holder, method["name"])
            if detail is None:
                continue
            if detail["param"] is None and flag_kind != "truthy":
                # A valued flag cannot be a switch: it would parse a value
                # and then discard it.
                continue
            if detail["param"] is not None and flag_kind == "value" \
                    and detail["option_type"] == "bool":
                # Retyping a valued flag into a switch would make its current
                # value syntax invalid; keep the two forms distinct.
                continue
            shape = generator._return_shape(ctx, method.get("return_type"))
            if base_shape and shape != base_shape:
                continue
            entity = _return_entity(ctx, method.get("return_type"))
            if base_entity and entity is not None and entity != base_entity:
                continue
            if family == "read" and not same_service \
                    and (entity is None or base_entity is None):
                continue
            if family != "read" and not same_service:
                continue
            if not _usable(ctx, holder, method):
                continue
            candidates.append((holder, method["name"]))
    return sorted(set(candidates))


def _route_record_valid(ctx, record):
    """True while a recorded route still names a method and parameter.

    A prompt stamp is not enough: the same prompt can re-extract a changed
    signature. A route whose parameter vanished must reopen, not dispatch
    into a stale call.
    """
    if not isinstance(record, dict):
        return False
    method = generator._service_method(ctx, record.get("service"),
                                       record.get("method"))
    if method is None:
        return False
    target = record.get("target_param")
    if target is None:
        return True
    params = [p for p in method.get("params") or [] if isinstance(p, dict)]
    if len(params) != 1:
        return False
    if normalize(params[0].get("name") or "") != normalize(target):
        return False
    detail = _route_candidate_detail(ctx, record.get("service"),
                                     record.get("method"))
    if detail is None:
        return False
    recorded_type = record.get("option_type")
    return isinstance(recorded_type, str) and recorded_type == detail["option_type"]


def collect_routes(output_dir):
    """`(questions, context)`: every dead flag, with any read candidates.

    A declared flag whose adapter fields never consume it parses and does
    nothing (`member list -active-only`, `book list --author`). Every such
    option is a question: methods in the command's CRUD family that return
    a compatible result and take zero or one flag-sized parameter are the
    finite route candidates. A flag with no candidate — an unsupported
    signature, a multi-parameter method, or a valued flag the adapter
    ignores — is still asked, with `drop` as its only deterministic
    resolution. The human says which method a selector selects, or removes
    the flag; the generator emits a route on every run while the prompt
    stands. A parameterized choice also retypes the flag and records the
    target parameter, so the chosen method receives the value.
    """
    ctx = generator.load_context(output_dir)
    invocation = (ctx["components"].get("facade") or {}).get("invocation") or {}
    bindings, _unmapped = codegen.bind_commands(ctx["adapters"], invocation,
                                               COMMAND_VERB_STEMS)
    leaves, actions, _argv, _targets, _assembled = generator._leaf_scan(
        ctx, bindings, {})
    # Only a record that still resolves closes its question: one pointing at
    # a method the documents no longer carry must reopen, not silently hide.
    current = requirements_sha(load_requirements(output_dir))
    decided = set()
    for record in ctx.get("routes") or []:
        if not _route_record_valid(ctx, record):
            continue
        decided.add((record.get("command"), record.get("subcommand"),
                     record.get("flag")))
    for record in load_surface_decisions(output_dir):
        if not (isinstance(record, dict)
                and record.get("kind") == DROP_FLAG_KIND
                and record.get("command") and record.get("flag")):
            continue
        stamped = record.get("requirements_sha")
        if current is not None and isinstance(stamped, str) and stamped != current:
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
        if base_method is None:
            continue
        for dest, flag, kind in leaf["dead"]:
            if (where[0], where[1], dest) in decided:
                continue
            # Every dead option is a question. The family filter decides
            # which methods can implement the verb; the signature filter
            # decides which of those one flag can carry. A flag on a method
            # that already takes arguments is still reported (and can be
            # dropped), but it is not an unfiltered fallback to route.
            verb = where[1] or where[0]
            candidates = (_route_candidates(
                ctx, service, base_method.get("name"), verb, kind)
                if not base_method.get("params")
                else [])
            details = {}
            for candidate_service, candidate_method in candidates:
                detail = _route_candidate_detail(
                    ctx, candidate_service, candidate_method)
                if detail is not None:
                    details[f"{candidate_service}.{candidate_method}"] = detail
            questions.append({
                "command": where[0],
                "subcommand": where[1],
                "flag": dest,
                "flag_name": flag,
                "kind": kind,
                "service": service,
                "reads": base_method.get("name"),
                "reads_params": [
                    p.get("name") for p in base_method.get("params") or []
                    if isinstance(p, dict) and p.get("name")],
                "candidates": candidates,
                "candidate_details": details,
            })
    context = {"prompt_sha": requirements_sha(load_requirements(output_dir))}
    return questions, context


def describe_route(index, total, question):
    """The dead option, the unfiltered read it rides on, the candidates."""
    leaf = question["command"]
    if question["subcommand"]:
        leaf += f" {question['subcommand']}"
    lines = [
        f"--- question {index}/{total} ---",
        f"DEAD OPTION: '{leaf} {question['flag_name']}' parses today "
        f"and does nothing.",
        f"  the command reads {question['service']}.{question['reads']}"
        + (f"({', '.join(question['reads_params'])})"
           if question.get("reads_params") else " (no arguments)")
        + " when the flag is passed.",
    ]
    details = question.get("candidate_details") or {}
    if question["candidates"]:
        lines.append("  candidate methods (one flag supplies one value):")
        adapted = False
        for number, (service, method) in enumerate(question["candidates"], start=1):
            detail = details.get(f"{service}.{method}") or {}
            signature = detail.get("signature") or method
            lines.append(f"    {number}) {service}.{signature}")
            if detail.get("param"):
                adapted = True
                lines.append(
                    f"       retypes '{question['flag_name']}' to "
                    f"{detail.get('option_type')} for "
                    f"{detail.get('param')}")
        lines.append(
            "  The documents link the flag to none of them; only you can say "
            "which one it selects.")
        if adapted:
            lines.append(
                "  Choosing a parameterized route changes the switch into a "
                "value option; the method receives that value.")
    else:
        lines.append(
            "  no method in this command's family has a signature one flag "
            "can carry"
            + (" (a valued flag needs a zero- or one-parameter method)"
               if question.get("kind") != "truthy"
               else " (zero or one scalar parameter)") + ".")
    lines.append(
        "  drop removes the flag from the surface; skip leaves it reported.")
    return lines


def ask_route(question, input_fn=input):
    """One candidate number/name, `drop`, or None on skip."""
    shown = ", ".join(str(n) for n in range(1, len(question["candidates"]) + 1))
    choices = f"choose {shown}, drop, or skip: " if shown else "drop or skip: "
    try:
        answer = input_fn(choices).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return None
    if answer in (DROP_FLAG, "d", "drop flag", "remove"):
        return DROP_FLAG
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
        if not isinstance(record, dict) or not isinstance(record.get("command"), str):
            continue
        is_duplicate = (isinstance(record.get("subcommand"), str)
                        and record.get("keep") in (KEEP_PARENT, KEEP_SUB, KEEP_BOTH))
        is_drop = (record.get("kind") == DROP_FLAG_KIND
                   and isinstance(record.get("flag"), str))
        is_route = (record.get("kind") == ROUTE_KIND
                    and isinstance(record.get("flag"), str)
                    and isinstance(record.get("service"), str)
                    and isinstance(record.get("method"), str))
        if not (is_duplicate or is_drop or is_route):
            continue
        stamped = record.get("requirements_sha")
        if (current is not None and isinstance(stamped, str)
                and stamped != current):
            if log is not None:
                subject = (record.get("subcommand")
                           if record.get("keep") else record.get("flag"))
                log.write(
                    f"[!] step components: surface decision for "
                    f"'{record['command']} {subject}' "
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
        if record.get("kind") == DROP_FLAG_KIND:
            command, sub = record["command"], record.get("subcommand")
            leaf = next((c for c in commands
                         if isinstance(c, dict) and c.get("name") == command), None)
            if sub is not None and isinstance(leaf, dict):
                leaf = next((s for s in leaf.get("subcommands") or []
                             if isinstance(s, dict) and s.get("name") == sub), None)
            options = leaf.get("options") if isinstance(leaf, dict) else None
            if isinstance(options, list):
                kept_options = [
                    option for option in options
                    if codegen.option_dest(option) != record["flag"]
                ]
                if len(kept_options) != len(options):
                    leaf["options"] = kept_options
                    applied += 1
                    if log is not None:
                        where = f"{command} {sub}" if sub else command
                        log.write(
                            f"[ok] step components: dropped flag "
                            f"'{record['flag']}' from '{where}' (human decision)"
                        )
            continue
        if record.get("kind") == ROUTE_KIND:
            command, sub = record["command"], record.get("subcommand")
            leaf = next((c for c in commands
                         if isinstance(c, dict) and c.get("name") == command), None)
            if sub is not None and isinstance(leaf, dict):
                leaf = next((s for s in leaf.get("subcommands") or []
                             if isinstance(s, dict) and s.get("name") == sub), None)
            options = leaf.get("options") if isinstance(leaf, dict) else None
            option = next((item for item in options or []
                           if codegen.option_dest(item) == record["flag"]), None)
            option_type = record.get("option_type")
            if isinstance(option, dict) and option_type \
                    and option.get("type") != option_type:
                option["type"] = option_type
                option["required"] = False
                option["default"] = None
                applied += 1
                if log is not None:
                    where = f"{command} {sub}" if sub else command
                    log.write(
                        f"[ok] step components: retyped flag '{record['flag']}' "
                        f"to {option_type} for {record['service']}."
                        f"{record['method']} (human decision) in '{where}'")
            continue
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
    """Ask every open duplicate and dead option; return (asked, answered)."""
    duplicates, context = collect_duplicates(output_dir)
    routes, _route_context = collect_routes(output_dir)
    questions = ([("duplicate", question) for question in duplicates]
                 + [("route", question) for question in routes])
    if not questions:
        out_fn("no duplicated surface nodes or dead options — nothing to decide")
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
            if picked == DROP_FLAG:
                record = {
                    "kind": DROP_FLAG_KIND,
                    "command": question["command"],
                    "subcommand": question["subcommand"],
                    "flag": question["flag"],
                    "decided_by": "user",
                }
            else:
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
                detail = (question.get("candidate_details") or {}).get(
                    f"{service}.{method}") or {}
                if detail.get("param"):
                    record["target_param"] = detail["param"]
                    record["option_type"] = detail["option_type"]
                    record["transform"] = detail["transform"]
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
            print("no duplicated surface nodes or dead options — nothing to decide")
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
