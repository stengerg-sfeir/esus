#!/usr/bin/env python3
"""Ask the user about adapter fields no rule can map.

Some fields name a value no spelling rule reaches: `file_path` where the
leaf offers `--output`, `copies` where the model declares
`available_copies`. Only the requirements author knows they name one thing.
This asks about exactly those pairs — required-but-unsuppliable fields and
entity-targeted fields spelling no model field — and records each answer as
`{action, field, flag}` in `field_aliases.json`, stamped with the prompt sha
like pattern decisions.

Usage:
    python review_aliases.py out/expenses          # ask open questions
    python review_aliases.py out/expenses --list   # show open questions only

Each question shows the action, the field, its target, the bound leaf with
its flags, and numbered suggestions (leaf flags the field resembles); answer
with a number, a flag name of your own, or skip. Answers apply to the on-disk
adapters immediately (the field takes the flag's spelling, its target
unchanged) and to every future run while the prompt stands. `skip` leaves a
pair open — the probe keeps reporting it.
"""

import json
import os
import sys
from difflib import SequenceMatcher

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kernel import codegen  # noqa: E402
from kernel.consistency.checks_surface import COMMAND_VERB_STEMS  # noqa: E402
from kernel.consistency.loader import load_documents, load_requirements  # noqa: E402
from kernel.consistency.report import Report  # noqa: E402
from kernel.extraction.aliases import (  # noqa: E402
    apply_aliases,
    load_aliases,
    save_aliases,
)
from kernel.extraction.decisions import requirements_sha  # noqa: E402

SUGGESTION_LIMIT = 5

# CLI option types mapped to model field types, for inferring a creatable
# field. `list` maps to nothing: a new multi-valued model field is never
# inferred — its shape is a design decision, not a derivation.
OPTION_TO_MODEL_TYPES = {"int": "int", "str": "string", "float": "float",
                         "bool": "boolean"}


def collect_questions(output_dir):
    """Open `(action, field)` pairs needing a mapping, with answering context.

    Returns `(questions, context)` where each question carries its target,
    entity, bound leaves and leaf flags. Assembly markers, optional fields
    and already-recorded pairs are excluded — what remains cannot be reached
    by any rule.
    """
    report = Report("review")
    documents = load_documents(output_dir, report)
    adapters = documents.get("interaction_adapters") or []
    services = documents.get("service_contracts") or []
    ports = documents.get("persistence_ports")
    repositories = []
    if isinstance(ports, dict) and isinstance(ports.get("repositories"), list):
        repositories = ports["repositories"]
    models = documents.get("data_models") or []
    entity_names = [m.get("name") for m in models
                    if isinstance(m, dict) and m.get("name")]
    invocation = ((documents.get("components") or {}).get("facade") or {}).get("invocation")
    targets = codegen.action_targets(adapters, services, repositories, entity_names)
    bindings, _ = codegen.bind_commands(adapters, invocation, COMMAND_VERB_STEMS)
    leaf_of = {}
    for (command, sub), bound in bindings.items():
        if bound is not None:
            leaf_of.setdefault(bound[0], []).append((command, sub))
    argv = codegen.action_argv(adapters, bindings, invocation)
    model_fields = {}
    pk_of = {}
    for model in models or []:
        if isinstance(model, dict) and model.get("name"):
            fields = [f for f in model.get("fields") or [] if isinstance(f, dict)]
            model_fields[model["name"]] = [
                f.get("name") for f in fields if f.get("name")]
            for f in fields:
                if f.get("primary_key") and f.get("name") and model["name"] not in pk_of:
                    pk_of[model["name"]] = f["name"]
    decided = set()
    for r in load_aliases(output_dir):
        if isinstance(r, dict):
            # Both ends: the recorded field (already answered) and the flag
            # it became (already renamed) — else every review re-asks the
            # renamed pair it just created. Deliberately final: a recorded
            # pair that still fires (mapped, yet unsupplied) needs surface
            # or model work, not another mapping answer — and the probe keeps
            # reporting it, so nothing goes silent.
            decided.add((r.get("action"), r.get("field")))
            decided.add((r.get("action"), r.get("flag")))

    questions = []
    seen = set()
    for action, field, entity in codegen.unknown_model_fields(
            adapters, services, repositories, models):
        if (action, field) not in decided and (action, field) not in seen:
            seen.add((action, field))
            questions.append(_question(adapters, leaf_of, argv, invocation,
                                       action, field, entity, "model",
                                       model_fields, pk_of))
    for action, field in codegen.uncovered_required_fields(adapters, invocation, targets):
        if (action, field) not in decided and (action, field) not in seen:
            seen.add((action, field))
            question = _question(adapters, leaf_of, argv, invocation,
                                 action, field, None, "flag",
                                 model_fields, pk_of)
            if _askable(question):
                questions.append(question)
    questions.sort(key=lambda q: (q["action"], q["field"]))
    context = {"adapters": adapters, "prompt_sha": requirements_sha(load_requirements(output_dir))}
    return questions, context


def _data_flags(leaf_flags):
    """Leaf flags minus argparse-owned help/version: the answerable ones."""
    return [flag for flag in (leaf_flags or [])
            if flag.strip().lstrip("-").lower() not in ("help", "version")]


def _askable(question):
    """False when no answer could work: a flag question on flagless leaves.

    Renaming the field to a typed-in name cannot help — no flag exists to
    take the spelling — so asking poses an impossible choice (expenses asked
    which flag on `expense category` supplies `category_id` when that leaf
    declares nothing but `-help`; the real `--category` lives on
    `expense list`). The defect is surface — a missing or duplicated command
    for rerun/repair — and the probe keeps reporting it, so skipping the
    question silences nothing.
    """
    if question.get("kind") != "flag":
        return True
    if question.get("suggestions"):
        return True
    return bool(_data_flags(question.get("leaf_flags")))


def _question(adapters, leaf_of, argv, invocation, action, field,
              entity, kind, model_fields=(), pk_of=None):
    """One askable pair, stated as a contract, not internals.

    kind 'model' asks which model field the value fills (the adapter names
    no declared one); kind 'flag' asks which flag supplies a required value
    no leaf flag covers. Either way the answer renames the adapter field
    only — service, method and parameter are shown qualified so the human
    sees exactly what maps to where.
    """
    adapter = next((a for a in adapters
                    if isinstance(a, dict) and a.get("action_name") == action), {})
    entry = next((f for f in adapter.get("input_fields") or []
                  if isinstance(f, dict) and f.get("field_name") == field), {})
    service = adapter.get("target_service")
    method = adapter.get("target_method")
    target = entry.get("target_param")
    leaves = leaf_of.get(action, [])
    leafpaths = [" ".join(part for part in leaf if part) for leaf in leaves]
    leaf_flags = []
    for command, sub in leaves:
        for option in codegen.leaf_options(invocation, command, sub):
            if isinstance(option, dict) and option.get("name"):
                if option["name"] not in leaf_flags:
                    leaf_flags.append(option["name"])
    supplied = []
    dest = (argv.get(action) or {}).get(field)
    if dest:
        for (command, sub), leafpath in zip(leaves, leafpaths):
            for option in codegen.leaf_options(invocation, command, sub):
                if (isinstance(option, dict)
                        and codegen.option_dest(option) == dest
                        and option.get("name")):
                    triple = (leafpath, option["name"], option.get("type"))
                    if triple not in supplied:
                        supplied.append(triple)
    problems = []
    if kind == "model" and entity:
        problems.append(
            f"{entity} declares no '{field}' field, so building it fails.")
    if kind == "flag":
        where = leafpaths[0] if len(leafpaths) == 1 else "its command"
        problems.append(
            f"no flag on '{where}' supplies this required value — "
            f"the action parses but can never run.")
    if kind == "model" and entity:
        question_line = f"Which {entity} field does this value fill?"
        suggestions = suggest_model_fields(model_fields, entity, field)
    else:
        question_line = "Which flag supplies this value?"
        suggestions = suggest_flags(
            sorted({d for d in (argv.get(action) or {}).values() if d}), field)
    spellings = {}
    for command, sub in leaves:
        for option in codegen.leaf_options(invocation, command, sub):
            if isinstance(option, dict) and option.get("name"):
                known = codegen.option_dest(option)
                if known and known not in spellings:
                    spellings[known] = option["name"]
    declared = sorted(model_fields.get(entity, [])) if isinstance(model_fields, dict) else []
    create = None
    if kind == "model" and entity:
        create = infer_new_field(entry, supplied, pk_of, model_fields, entity, field)
    return {
        "action": action,
        "field": field,
        "service": service,
        "method": method,
        "target": target,
        "transform": entry.get("transform"),
        "entity": entity,
        "kind": kind,
        "leaves": leafpaths,
        "flags": sorted({d for d in (argv.get(action) or {}).values() if d}),
        "leaf_flags": leaf_flags,
        "supplied": supplied,
        "model_fields": declared,
        "create": create,
        "problem": problems,
        "question": question_line,
        "suggestions": suggestions,
        "spellings": spellings,
    }

def suggest_flags(dests, field, limit=SUGGESTION_LIMIT):
    """Leaf flags resembling the field, most similar first (deterministic)."""
    from kernel.consistency.naming import normalize

    wanted = normalize(field or "")
    if not wanted:
        return []
    scored = []
    for dest in dests:
        flat = normalize(dest)
        if not flat or flat == wanted:
            continue
        if flat in wanted or wanted in flat:
            scored.append((0, dest))
        else:
            ratio = SequenceMatcher(None, wanted, flat).ratio()
            if ratio >= 0.5:
                scored.append((1 - ratio, dest))
    scored.sort(key=lambda item: (item[0], item[1] or ""))
    return [dest for _, dest in scored[:limit]]


def infer_new_field(entry, supplied, pk_of, model_fields, entity, field):
    """A creatable field spec, or None when any piece is underivable.

    Type comes from the supplying flag's declared CLI type, else int for
    LOOKUP_ID (an identifier by definition) — anything else untyped stays
    uninferable rather than guessed. The foreign key resolves only through
    the adapter's lookup_entity naming a declared entity with a known
    primary key. Nullable follows the adapter contract (a value always
    supplied holds); unique is never inferred; provenance is `deduced`.
    """
    from kernel.consistency.naming import normalize

    if not isinstance(model_fields, dict):
        return None
    declared = {normalize(n) for n in model_fields.get(entity, []) or []}
    if normalize(field or "") in declared:
        return None
    ftype = None
    provenance = None
    for _, spelling, otype in supplied:
        mapped = OPTION_TO_MODEL_TYPES.get((otype or "").strip().lower())
        if mapped:
            ftype, provenance = mapped, f"flag '{spelling}' : {otype}"
            break
    if ftype is None and (entry.get("transform") or "") == "LOOKUP_ID":
        ftype, provenance = "int", "LOOKUP_ID transform"
    if ftype is None:
        return None
    foreign_key = None
    lookup = entry.get("lookup_entity")
    if isinstance(lookup, str) and isinstance(pk_of, dict):
        target = next((m for m in model_fields if normalize(m) == normalize(lookup)), None)
        if target is not None and pk_of.get(target):
            foreign_key = {"target_entity": target, "target_field": pk_of[target],
                           "relationship": "many_to_one"}
    spec = {"entity": entity, "name": field, "type": ftype,
            "nullable": not bool(entry.get("required", True)),
            "unique": False, "foreign_key": foreign_key, "status": "deduced"}
    if provenance:
        spec["provenance"] = provenance
    return spec


def suggest_model_fields(model_fields, entity, field):
    """Target-entity model fields containing the name, sorted, deterministic.

    Offered only when no leaf flag resembles the field: answering one of
    these renames the value into a real model field, which is what
    unblocks construction. Forward containment only, like the rename
    repair — suggesting `id` for `author_id` would repoint an author
    reference at the record itself, so reverse matches are never offered.
    """
    from kernel.consistency.naming import normalize

    wanted = normalize(field or "")
    names = model_fields.get(entity or "", []) if isinstance(model_fields, dict) else []
    return sorted({name for name in names if name and wanted
                   and wanted in normalize(name)})


def describe_question(index, total, question):
    """One pair stated as a contract: what maps to where, what answering does.

    Every line is qualified — adapter and method names, the transform, the
    exact problem, where the value arrives from today, and what an answer
    changes (the adapter field only; the method parameter is untouched).
    Missing keys degrade to the older terse lines, so hand-built questions
    in tests still render.
    """
    get = question.get
    lines = [
        f"--- question {index}/{total} ---",
        f"ADAPTER '{get('action')}' feeds CLI input into "
        f"{get('service')}.{get('method')}.",
        f"  field '{get('field')}' ---({get('transform')})---> "
        f"parameter '{get('target')}'"
        + (f", which must be a {get('entity')}" if get("entity") else ""),
    ]
    for problem in get("problem") or []:
        lines.append(f"  Problem: {problem}")
    supplied = get("supplied") or []
    if supplied:
        lines.append("  The value arrives via " + ", ".join(
            f"flag '{item[1]}' on '{item[0]}'" for item in supplied) + ".")
    elif get("leaves"):
        lines.append("  No bound flag supplies it; flags on "
                     + ", ".join(f"'{leaf}'" for leaf in get("leaves") or [])
                     + ": " + (", ".join(f"'{flag}'" for flag in get("leaf_flags") or [])
                                or "none declared") + ".")
    else:
        lines.append("  No command reaches this action.")
    lines.append(f"  {get('question') or 'What does this value map to?'}")
    spellings = get("spellings") or {}
    if get("entity"):
        lines.append(f"  {get('entity')} declares: "
                     + (", ".join(get("model_fields") or []) or "nothing") + ".")
    create = get("create")
    for number, suggestion in enumerate(get("suggestions") or [], start=1):
        shown = spellings.get(suggestion, suggestion)
        lines.append(f"  {number}) {suggestion}" + (f" (as flag '{shown}')" if shown != suggestion else ""))
    if create:
        lines.append(f"  {len(get('suggestions') or []) + 1}) create {create['entity']}.{create['name']} "
                     f": {create['type']}"
                     + (f", FK → {create['foreign_key']['target_entity']}."
                        f"{create['foreign_key']['target_field']}" if create.get("foreign_key") else "")
                     + (f" (from {create['provenance']})" if create.get("provenance") else ""))
    if not (get("suggestions") or []) and not create and get("entity"):
        lines.append(f"  (type the {get('entity')} field it fills, or skip)")
    elif not (get("suggestions") or []) and not create:
        lines.append("  (type a flag name, or skip — without a declared flag it stays blocked)")
    if get("kind") == "flag":
        lines.append(f"  Answering renames the adapter field to the flag's spelling; "
                     f"parameter '{get('target')}' is untouched either way.")
    else:
        lines.append(f"  Answering renames the adapter field, or creates the model field; "
                     f"parameter '{get('target')}' is untouched either way.")
    return lines


def ask(question, input_fn=input):
    """Pose one pair; return `("rename", name)`, `("create", spec)`, or `(None, None)`.

    Numbers address suggestions first, then the create offer when one is
    shown. Free text only ever renames: typing the offered create name still
    renames rather than creates, because creation changes the schema and
    must stay an explicit, numbered choice — never something a stray
    keystroke implies.
    """
    suggestions = question.get("suggestions") or []
    create = question.get("create")
    options = [("rename", name) for name in suggestions]
    if create:
        options.append(("create", create))
    try:
        answer = input_fn("choose a number, type a name, or skip: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None, None
    if answer.lower() in ("skip", "s", ""):
        return None, None
    if answer.isdigit():
        index = int(answer) - 1
        if 0 <= index < len(options):
            return options[index]
        return None, None
    cleaned = answer.lstrip("-")
    return ("rename", cleaned) if cleaned else (None, None)


def run_review(output_dir, input_fn=input, out_fn=print):
    """Ask every open pair; return (asked, answered)."""
    questions, context = collect_questions(output_dir)
    if not questions:
        out_fn("no open field mappings — nothing to decide")
        return 0, 0
    aliases = load_aliases(output_dir)
    answered = 0
    for number, question in enumerate(questions, start=1):
        for line in describe_question(number, len(questions), question):
            out_fn(line)
        kind, value = ask(question, input_fn)
        if kind is None:
            out_fn("skipped — left open")
            continue
        if kind == "rename" and value == question["field"]:
            # Answering the name it already has renames nothing: record
            # nothing, ask nothing again later — the pair stays open.
            out_fn("that changes nothing — skipped, left open")
            continue
        if kind == "create":
            if _model_has_field(output_dir, value["entity"], value["name"]):
                # A rerun declared it meanwhile: the create is moot, but the
                # mapping still stands — record it as a plain rename.
                out_fn(f"{value['entity']}.{value['name']} is declared now — "
                        f"recording a rename instead")
                record = {
                    "action": question["action"],
                    "field": question["field"],
                    "flag": value["name"],
                    "decided_by": "user",
                }
            elif not _apply_create(output_dir, value, out_fn):
                continue
            else:
                record = {
                    "action": question["action"],
                    "field": question["field"],
                    "flag": value["name"],
                    "create": value,
                    "decided_by": "user",
                }
        else:
            record = {
                "action": question["action"],
                "field": question["field"],
                "flag": value,
                "decided_by": "user",
            }
        if context["prompt_sha"] is not None:
            record["requirements_sha"] = context["prompt_sha"]
        aliases.append(record)
        answered += 1
    save_aliases(output_dir, aliases)
    matches_path = os.path.join(output_dir, "interaction_adapters.json")
    try:
        with open(matches_path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as error:
        out_fn(f"error: cannot read {matches_path}: {error}")
        return len(questions), answered
    payload["interaction_adapters"] = apply_aliases(
        payload.get("interaction_adapters"), aliases)
    with open(matches_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    out_fn(f"answered {answered} of {len(questions)}; mappings in field_aliases.json")
    return len(questions), answered


def _model_has_field(output_dir, entity, name):
    """True when the archived model already declares the field."""
    try:
        with open(os.path.join(output_dir, "data_models.json"), encoding="utf-8") as handle:
            models = json.load(handle).get("data_models")
    except (OSError, ValueError, AttributeError):
        return False
    if not isinstance(models, list):
        return False
    return any(isinstance(m, dict) and m.get("name") == entity
               and any(isinstance(f, dict) and f.get("name") == name
                       for f in m.get("fields") or [])
               for m in models)


def _apply_create(output_dir, spec, out_fn):
    """Append a reviewed field to its model's data_models.json; True on change.

    The entity must still exist and lack the field — a rerun may have healed
    or moved it meanwhile, in which case there is nothing to create and the
    answer falls back to a plain rename at the call site.
    """
    path = os.path.join(output_dir, "data_models.json")
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as error:
        out_fn(f"error: cannot read {path}: {error}")
        return False
    models = payload.get("data_models")
    if not isinstance(models, list):
        return False
    for model in models:
        if isinstance(model, dict) and model.get("name") == spec["entity"]:
            fields = model.get("fields")
            if not isinstance(fields, list):
                return False
            if any(isinstance(f, dict) and f.get("name") == spec["name"] for f in fields):
                return False
            fields.append({
                "name": spec["name"],
                "type": spec["type"],
                "primary_key": False,
                "nullable": spec["nullable"],
                "unique": False,
                "foreign_key": spec["foreign_key"],
                "status": "deduced",
            })
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            out_fn(f"created {spec['entity']}.{spec['name']} in data_models.json")
            return True
    return False


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    list_only = "--list" in args
    args = [a for a in args if a != "--list"]
    if len(args) != 1:
        print(__doc__.splitlines()[0], file=sys.stderr)
        print("usage: python review_aliases.py OUT_DIR [--list]", file=sys.stderr)
        return 2
    if list_only:
        questions, _ = collect_questions(args[0])
        if not questions:
            print("no open field mappings — nothing to decide")
            return 0
        for number, question in enumerate(questions, start=1):
            for line in describe_question(number, len(questions), question):
                print(line)
        return 0
    asked, _ = run_review(args[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
