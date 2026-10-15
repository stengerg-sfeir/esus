#!/usr/bin/env python3
"""Ask the user for pattern slots no document provides.

Some patterns are correctly classified but unwritable: an aggregate needs
to know *what* to sum, a threshold scan *which* field crosses *what bound*.
No rule derives those slots — the requirements author knows them cold, and
the options are enumerable. This asks, records `{holder, method, pattern,
slots}` in `method_slots.json` beside the documents (prompt-sha stamped,
like every other human answer), and the generator emits the body from the
recorded slots on every run while the prompt stands.

Usage:
    python review_slots.py out/expenses          # ask open questions
    python review_slots.py out/expenses --list   # show open questions only

Only slottable patterns are asked (`generator.SLOT_PATTERNS` — aggregates
and threshold scans). Guards and custom logic have no finite options to
offer; those stay stubs for the LLM pass. Skipping any slot records
nothing — the probe keeps reporting the stub and the question reopens.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import generator  # noqa: E402
from kernel import codegen  # noqa: E402
from kernel.consistency.loader import load_requirements  # noqa: E402
from kernel.consistency.naming import normalize  # noqa: E402
from kernel.extraction.decisions import requirements_sha  # noqa: E402

AGGREGATE_FUNCS = ("SUM", "COUNT", "AVG", "MIN", "MAX")
OPERATORS = ("<", "<=", ">", ">=", "=")
NUMERIC_TYPES = ("int", "integer", "float", "double", "decimal", "number",
                 "money")
DATE_TYPES = ("date", "datetime")
# Name fragments marking a string field as date-carrying. Deliberately tight:
# loose fragments like "at"/"on" match `description`, `person`, `button`.
DATE_NAME_HINTS = ("date", "month", "year", "day", "time", "created",
                   "updated")


def load_method_slots(output_dir):
    """The recorded slot answers, or [] when there are none."""
    try:
        with open(os.path.join(output_dir, generator.METHOD_SLOTS_NAME),
                  encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    records = payload.get(generator.METHOD_SLOTS_KEY)
    return [item for item in records] if isinstance(records, list) else []


def save_method_slots(output_dir, records):
    """Write the slot records beside the documents."""
    path = os.path.join(output_dir, generator.METHOD_SLOTS_NAME)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({generator.METHOD_SLOTS_KEY: records},
                                indent=2, ensure_ascii=False) + "\n")
    return path


def collect_slots(output_dir):
    """`(questions, context)`: stub repo methods with answerable slots.

    A question carries one candidate list per slot, in ask order. Methods
    whose slots are recorded complete, whose pattern is not slottable, and
    service methods (which follow their repository twin via realized
    delegation) are never asked.
    """
    ctx = generator.load_context(output_dir)
    stats = {"source": output_dir, "implemented": 0, "stubs": 0,
             "stub_reasons": [], "prog": os.path.basename(output_dir)}
    generator.render_program(ctx, stats)
    decided = {(r.get("holder"), r.get("method")) for r in load_method_slots(output_dir)
               if isinstance(r, dict)}
    questions = []
    for repo in ctx["repositories"]:
        holder = repo.get("interface_name") or repo.get("entity")
        for method in repo.get("methods") or []:
            if not isinstance(method, dict) or not method.get("name"):
                continue
            if (holder, method["name"]) in decided:
                continue
            pattern, slots = generator._slot_pattern(ctx, holder, method)
            if pattern is None:
                continue
            if generator._slots_usable(pattern, slots, method, True):
                continue
            if pattern == "BUDGET_OVERFLOW_GUARD" and not _is_bool_return(method):
                # A status vocabulary would be invented — only bool checks
                # are asked.
                continue
            options = _slot_options(ctx, repo, method, pattern)
            if options is None:
                continue
            questions.append({
                "holder": holder, "method": method["name"],
                "pattern": pattern, "entity": repo.get("entity"),
                "description": method.get("description") or "",
                "options": options, "role": "repository",
            })
    for service in ctx["services"]:
        holder = service.get("service_name")
        if not isinstance(holder, str):
            continue
        for method in service.get("methods") or []:
            if not isinstance(method, dict) or not method.get("name"):
                continue
            if (holder, method["name"]) in decided:
                continue
            pattern, slots = generator._slot_pattern(ctx, holder, method)
            if pattern != "BUDGET_OVERFLOW_GUARD":
                continue
            if generator._slots_usable(pattern, slots, method, False):
                continue
            options = _guard_options(ctx, holder, method)
            if options is None:
                continue
            questions.append({
                "holder": holder, "method": method["name"],
                "pattern": pattern, "entity": None,
                "description": method.get("description") or "",
                "options": options, "role": "service",
            })
    context = {"prompt_sha": requirements_sha(load_requirements(output_dir))}
    return questions, context


def _is_bool_return(method):
    """True when a check method answers yes/no rather than a vocabulary."""
    return normalize(method.get("return_type") or "") in ("bool", "boolean")


def _model_fields(ctx, entity):
    """`[(name, type, field)]` for an entity's model, or []."""
    model = generator.model_of(ctx, entity)
    if model is None:
        return []
    out = []
    for field in model.get("fields") or []:
        if isinstance(field, dict) and field.get("name"):
            out.append((field["name"], (field.get("type") or "").strip().lower(),
                        field))
    return out


def _slot_options(ctx, repo, method, pattern):
    """`[(slot, [candidates])]` in ask order, or None when unaskable.

    Every slot needs at least one candidate: a question with an empty
    option list is the old impossible choice in a new file.
    """
    entity = repo.get("entity")
    fields = _model_fields(ctx, entity)
    params = [p.get("name") for p in method.get("params") or []
              if isinstance(p, dict) and isinstance(p.get("name"), str)]
    numeric = [name for name, ftype, field in fields
               if ftype in NUMERIC_TYPES and not field.get("primary_key")]
    dates = [name for name, ftype, field in fields
             if ftype in DATE_TYPES
             or (ftype in ("str", "string")
                 and any(hint in normalize(name) for hint in DATE_NAME_HINTS))]
    if pattern.startswith("AGGREGATE"):
        options = []
        fk_fields = {normalize(f["name"]) for _, _, f in fields
                     if isinstance(f.get("foreign_key"), dict)}
        fk_candidates = [p for p in params if normalize(p) in fk_fields]
        if fk_candidates:
            options.append(("fk_field", fk_candidates[:6]))
        options.append(("aggregate_func", list(AGGREGATE_FUNCS)))
        targets = numeric
        if not targets:
            return None
        options.append(("target_field", targets[:6]))
        if pattern == "AGGREGATE_BY_FK_AND_DATE":
            if not dates:
                return None
            options.append(("date_field", dates[:6]))
        return options
    if pattern == "THRESHOLD_SCAN":
        pooled = [(n, t) for n, t, _ in fields
                  if t in NUMERIC_TYPES or t in DATE_TYPES or n in dates]
        if not pooled:
            return None
        scalar_params = [p for p in params if not _param_is_entity(ctx, method, p)]
        dated = [n for n, t in pooled
                 if t in DATE_TYPES or n in dates]
        if not dated and not scalar_params:
            # No date field for `today`, no parameter for a bound: nothing
            # to offer, so no question — the stub stands.
            return None
        options = [("comparison_field", [name for name, _ in pooled][:6]),
                   ("operator", list(OPERATORS))]
        # The bound depends on the chosen field (`today` only means
        # something for dates), so it is asked after, from recomputed
        # options — never from a stale precomputed list.
        options.append(("threshold", None))
        return options
    if pattern == "BUDGET_OVERFLOW_GUARD":
        entity = repo.get("entity")
        own_numeric = [name for name, ftype, field in _model_fields(ctx, entity)
                       if ftype in NUMERIC_TYPES and not field.get("primary_key")]
        if not own_numeric:
            return None

        def spendable(name):
            fields = _model_fields(ctx, name)
            has_number = any(ft in NUMERIC_TYPES and not f.get("primary_key")
                             for _, ft, f in fields)
            has_date = any(ft in DATE_TYPES
                           or (ft in ("str", "string")
                               and any(h in normalize(fn) for h in DATE_NAME_HINTS))
                           for fn, ft, _ in fields)
            return has_number and has_date

        candidates = [n for n in ctx["entity_names"]
                      if isinstance(n, str) and n != entity and spendable(n)]
        if not candidates:
            return None
        return [("spend_entity", candidates[:6]),
                ("limit_field", own_numeric[:6]),
                ("target_field", None),
                ("date_field", None)]
    return None


def _param_is_entity(ctx, method, name):
    """True when a parameter carries a record rather than a scalar."""
    ptype = next((q.get("type") for q in method.get("params") or []
                  if isinstance(q, dict) and q.get("name") == name), None)
    return codegen.is_entity_type(ptype, ctx["entity_names"])


def _guard_options(ctx, holder, method):
    """`[(slot, [candidates])]` for a service budget guard, or None.

    Creation, scope, amount and error candidates enumerate upfront; the
    limit waits on the chosen budget read (deferred). Aggregates count as
    candidates once usable *or* answerable this session — a fresh aggregate
    wires up the moment its own slots land, validated again at generation.
    """
    acted = generator._guard_entity_param(ctx, method)
    if acted is None:
        return None
    _, _, entity = acted
    entity_name = next((n for n in ctx["entity_names"]
                        if codegen.is_entity_type(entity, [n])), None)
    if entity_name is None:
        return None
    creates = [m["name"] for _, m in generator._mechanical_creates(ctx, entity_name)]
    if not creates:
        return None
    fields = _model_fields(ctx, entity_name)
    dates = [n for n, t, _ in fields
             if t in DATE_TYPES
             or (t in ("str", "string")
                 and any(h in normalize(n) for h in DATE_NAME_HINTS))]
    amounts = [n for n, t, f in fields
               if t in NUMERIC_TYPES and not f.get("primary_key")]
    if not dates or not amounts:
        return None
    aggregates = []
    for agg_cls, agg_method in _candidate_aggregates(ctx, entity_name):
        feed = generator._aggregate_feed(ctx, entity_name, dates[0], agg_method)
        if feed is not None:
            aggregates.append(agg_method["name"])
    budgets = _budget_read_options(ctx, entity_name)
    errors = [e["name"] for e in ctx["errors"]
              if isinstance(e, dict) and e.get("name")
              and ("budget" in normalize(e["name"])
                   or "exceed" in normalize(e["name"]))]
    if not aggregates or not budgets or not errors:
        return None
    return [("create_method", creates[:6]),
            ("aggregate_method", aggregates[:6]),
            ("budget_method", budgets[:6]),
            ("amount_field", amounts[:6]),
            ("date_field", dates[:6]),
            ("limit_field", None),
            ("error", errors[:6])]


def _candidate_aggregates(ctx, entity):
    """Usable aggregates plus ones whose slots could be answered now."""
    seen = {}
    for agg_cls, agg_method in generator._usable_aggregates(ctx, entity):
        seen[agg_method["name"]] = (agg_cls, agg_method)
    for repo in ctx["repositories"]:
        if repo.get("entity") != entity:
            continue
        holder = repo.get("interface_name") or entity
        for method in repo.get("methods") or []:
            if not isinstance(method, dict) or not method.get("name"):
                continue
            if method["name"] in seen:
                continue
            pattern, _ = generator._slot_pattern(ctx, holder, method)
            if pattern is not None and pattern.startswith("AGGREGATE"):
                seen[method["name"]] = (holder, method)
    return list(seen.values())


def _budget_read_options(ctx, entity):
    """Repo reads returning one record with numeric fields, feedable scope."""
    out = []
    for repo in ctx["repositories"]:
        holder = repo.get("interface_name") or repo.get("entity")
        for method in repo.get("methods") or []:
            if not isinstance(method, dict) or not method.get("name"):
                continue
            returns = (method.get("return_type") or "")
            words = {normalize(token) for token in
                     re.findall(r"[A-Za-z_][A-Za-z0-9_]*", returns)}
            if "list" in words:
                continue
            target = next(
                (n for n in ctx["entity_names"]
                 if isinstance(n, str) and normalize(n) in words
                 and normalize(n) not in ("dict", "optional", "none")),
                None)
            if target is None:
                continue
            if not any(t in NUMERIC_TYPES and not f.get("primary_key")
                       for _, t, f in _model_fields(ctx, target)):
                continue
            out.append(method["name"])
    return out


def _resolve_deferred(ctx, question, method, slot, answers):
    """Candidates for a deferred slot from the answers so far, or [].

    Covers the threshold bound (follows the comparison field), the repo
    check's target/date (follow the spending entity) and the service
    guard's limit (follows the chosen budget read).
    """
    if slot == "threshold":
        return _threshold_options(ctx, question["entity"], method,
                                  answers.get("comparison_field"))
    if slot in ("target_field", "date_field") and question.get("role") == "repository":
        spend = answers.get("spend_entity")
        if not spend:
            return []
        if slot == "target_field":
            return [n for n, t, f in _model_fields(ctx, spend)
                    if t in NUMERIC_TYPES and not f.get("primary_key")][:6]
        return [n for n, t, _ in _model_fields(ctx, spend)
                if t in DATE_TYPES
                or (t in ("str", "string")
                    and any(h in normalize(n) for h in DATE_NAME_HINTS))][:6]
    if slot == "limit_field" and question.get("role") == "service":
        budget_method = answers.get("budget_method")
        if not budget_method:
            return []
        for repo in ctx["repositories"]:
            for cand in repo.get("methods") or []:
                if isinstance(cand, dict) and cand.get("name") == budget_method:
                    returns = (cand.get("return_type") or "")
                    words = {normalize(token) for token in
                             re.findall(r"[A-Za-z_][A-Za-z0-9_]*",
                                        returns)}
                    target = next(
                        (n for n in ctx["entity_names"]
                         if isinstance(n, str) and normalize(n) in words), None)
                    if target is None:
                        return []
                    return [n for n, t, f in _model_fields(ctx, target)
                            if t in NUMERIC_TYPES and not f.get("primary_key")][:6]
        return []
    return []


def _param_is_entity(ctx, method, name):
    """True when a parameter carries a record rather than a scalar."""
    ptype = next((q.get("type") for q in method.get("params") or []
                  if isinstance(q, dict) and q.get("name") == name), None)
    return codegen.is_entity_type(ptype, ctx["entity_names"])


def _is_date_field(ctx, entity, name):
    """True when a model field is date-typed or date-named."""
    for fname, ftype, _ in _model_fields(ctx, entity):
        if fname == name:
            return ftype in DATE_TYPES \
                or any(hint in normalize(fname) for hint in DATE_NAME_HINTS)
    return False


def _threshold_options(ctx, entity, method, comparison_field):
    """Bound candidates once the field is known: params plus date logic."""
    params = [p.get("name") for p in method.get("params") or []
              if isinstance(p, dict) and isinstance(p.get("name"), str)]
    bounds = [p for p in params if not _param_is_entity(ctx, method, p)]
    if _is_date_field(ctx, entity, comparison_field):
        bounds = ["today"] + bounds
    return bounds[:6]


def describe_question(index, total, question):
    """The method, its pattern, and one numbered list per slot."""
    lines = [
        f"--- question {index}/{total} ---",
        f"SLOTS for {question['holder']}.{question['method']} "
        f"[{question['pattern']}]",
    ]
    if question["description"]:
        lines.append(f"  {question['description']}")
    for slot, candidates in question["options"]:
        if candidates is None:
            lines.append(f"  {slot}: (offered after the earlier slots are answered)")
        else:
            lines.append(f"  {slot}: " + ", ".join(
                f"{number}) {candidate}"
                for number, candidate in enumerate(candidates, start=1)))
    lines.append("  Answer each slot by number, or skip the question — "
                 "a skipped slot records nothing.")
    return lines


def ask(question, input_fn=input, resolve=None):
    """Pose every slot; return the slots dict, or None on any skip.

    A slot with `None` candidates is resolved from the answers so far
    (`resolve(slot, answers)`), so later options can depend on earlier
    ones — the threshold bound follows the chosen comparison field.
    """
    slots = {}
    for slot, candidates in question["options"]:
        if candidates is None and resolve is not None:
            candidates = resolve(slot, slots)
        if not candidates:
            return None
        shown = ", ".join(candidates)
        try:
            answer = input_fn(f"{slot} [{shown}] or skip: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None
        if answer in ("skip", "s", ""):
            return None
        pick = None
        if answer.isdigit():
            index = int(answer) - 1
            if 0 <= index < len(candidates):
                pick = candidates[index]
        else:
            exact = [c for c in candidates if c.lower() == answer]
            pick = exact[0] if exact else None
        if pick is None:
            return None
        slots[slot] = pick
    return slots


def run_review(output_dir, input_fn=input, out_fn=print):
    """Ask every open slot question; return (asked, answered)."""
    questions, context = collect_slots(output_dir)
    if not questions:
        out_fn("no open pattern slots — nothing to decide")
        return 0, 0
    ctx = generator.load_context(output_dir)
    by_method = {}
    for repo in ctx["repositories"]:
        for method in repo.get("methods") or []:
            if isinstance(method, dict) and method.get("name"):
                by_method.setdefault(method["name"], method)
    records = load_method_slots(output_dir)
    answered = 0
    for number, question in enumerate(questions, start=1):
        for line in describe_question(number, len(questions), question):
            out_fn(line)
        method = by_method.get(question["method"], {})

        def resolve(slot, answers, _q=question, _m=method):
            return _resolve_deferred(ctx, _q, _m, slot, answers)

        slots = ask(question, input_fn, resolve)
        if slots is None:
            out_fn("skipped — left open")
            continue
        record = {
            "holder": question["holder"],
            "method": question["method"],
            "pattern": question["pattern"],
            "slots": slots,
            "decided_by": "user",
        }
        if context["prompt_sha"] is not None:
            record["requirements_sha"] = context["prompt_sha"]
        records.append(record)
        answered += 1
    save_method_slots(output_dir, records)
    out_fn(f"answered {answered} of {len(questions)}; slots in {generator.METHOD_SLOTS_NAME}")
    return len(questions), answered


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    list_only = "--list" in args
    args = [a for a in args if a != "--list"]
    if len(args) != 1:
        print(__doc__.splitlines()[0], file=sys.stderr)
        print("usage: python review_slots.py OUT_DIR [--list]", file=sys.stderr)
        return 2
    if list_only:
        questions, _ = collect_slots(args[0])
        if not questions:
            print("no open pattern slots — nothing to decide")
            return 0
        for number, question in enumerate(questions, start=1):
            for line in describe_question(number, len(questions), question):
                print(line)
        return 0
    asked, _ = run_review(args[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
