#!/usr/bin/env python3
"""Ask the human for behavior facts a method needs and no document states.

The generator can check a body against the API it was shown, but it cannot
know that returning a book means setting `return_date` to now, incrementing
one field and saving two repositories. Putting that knowledge in the
generator would make it library-shaped; putting it in the requirements would
make every test a wording test. It belongs in a human-confirmed record beside
the documents.

This review reads the existing `out/...` documents (no model run needed),
proposes the domain-neutral parts it can see — fields changed by verb, model
created, declared-error preconditions, the repository calls that save them —
and asks the human only for the values an English sentence does not settle:
the amount, the date/status value, the order, and any condition behind an
error such as `InvalidReturnDateError`. The answers are written to
`method_contracts.json`, stamped with the requirements sha; `generator.py`
reads them on every run. Skipping a required value records nothing, so the
stub stays and the question reopens.

Usage:
    python review_contracts.py out/library          # ask open contracts
    python review_contracts.py out/library --list   # show proposals only

This is deliberately a separate pass from extraction. `extract_arch.py
--chat` runs it at the end when asked; a full extraction is not required to
create the file for an existing tree.
"""

import ast
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import generator  # noqa: E402
from kernel.consistency.loader import load_requirements  # noqa: E402
from kernel.consistency.naming import normalize  # noqa: E402
from kernel.extraction import contracts as contract_rules  # noqa: E402
from kernel.extraction.decisions import requirements_sha  # noqa: E402

DATE_TYPES = ("date", "datetime")
DATE_NAME_HINTS = ("date", "month", "year", "day", "time", "created",
                   "updated")
BOOL_TYPES = ("bool", "boolean")

# The verbs that mean "write this field". The noun after the verb is matched
# against model fields; the parser never sees a domain name of its own.
EFFECT_VERBS = (
    (r"increments?|increases?|raises?", "increment"),
    (r"decrements?|decreases?|reduces?|removes?|subtracts?", "decrement"),
    (r"sets?|updates?|changes?|toggles?", "set"),
)
CREATE_VERBS = r"creates?|adds?"
# English number words are not field names; make quantity/qty one term so a
# factory description ("stock quantity") can reach a `stock_qty` field.
SYNONYMS = (("quantities", "qty"), ("quantity", "qty"),
            ("count", "qty"), ("copies", "copies"))


def _fields(ctx):
    """`[(class, field, type, field_dict)]` for every model."""
    rows = []
    for model in ctx.get("models") or []:
        class_name = model.get("name")
        for field in model.get("fields") or []:
            if isinstance(field, dict) and field.get("name"):
                rows.append((class_name, field["name"],
                             (field.get("type") or "").strip().lower(),
                             field))
    return rows


def _params(method):
    return [param["name"] for param in method.get("params") or []
            if isinstance(param, dict) and isinstance(param.get("name"), str)]


def _synonym_text(text):
    lowered = str(text).lower()
    for word, replacement in SYNONYMS:
        lowered = re.sub(rf"\b{re.escape(word)}\b", replacement, lowered)
    return lowered


def _match_field(noun, fields):
    """The model field a noun phrase names, or None.

    The longest field whose normalized name appears in the phrase wins, so
    "is_active status" reaches `is_active` rather than the shorter `status`
    (which belongs to another model). A field name that contains the phrase
    also matches ("copies" -> `available_copies`).
    """
    phrase = normalize(_synonym_text(noun))
    if not phrase:
        return None
    best = None
    for class_name, field_name, field_type, field in fields:
        field_norm = normalize(field_name)
        if not field_norm:
            continue
        if field_norm in phrase:
            score = len(field_norm)
        elif len(phrase) >= 4 and phrase in field_norm:
            score = len(phrase)
        else:
            continue
        if best is None or score > best[0]:
            best = (score, class_name, field_name, field_type, field)
    if best is None:
        return None
    _score, class_name, field_name, field_type, field = best
    return class_name, field_name, field_type, field


def _match_class(noun, ctx):
    """The model class a noun phrase names, or None."""
    phrase = normalize(noun)
    best = None
    for name in ctx.get("entity_names") or []:
        normalized = normalize(name)
        if normalized and normalized in phrase:
            if best is None or len(normalized) > len(normalize(best)):
                best = name
    return best


def _repo_for(ctx, entity):
    for repo in ctx.get("repositories") or []:
        if repo.get("entity") == entity:
            return repo
    return None


def _repo_call(ctx, entity, prefix):
    """`Interface.method` for the entity's create/update, or None."""
    repo = _repo_for(ctx, entity)
    if not repo:
        return None
    wanted = prefix + str(entity).lower()
    methods = [method for method in repo.get("methods") or []
               if isinstance(method, dict) and method.get("name")]
    for method in methods:
        if method["name"] == wanted:
            return f"{repo['interface_name']}.{method['name']}"
    for method in methods:
        if method["name"].startswith(prefix):
            return f"{repo['interface_name']}.{method['name']}"
    return None


def _write_call(ctx, entity, role):
    if role == "repository":
        return "self._store.update"
    return _repo_call(ctx, entity, "update_")


def _create_call(ctx, entity, role):
    if role == "repository":
        return "self._store.insert"
    return _repo_call(ctx, entity, "create_")


def _invariant_values(ctx, entity, field):
    """The documented vocabulary for a field, from an invariant, or []."""
    pattern = re.compile(
        rf"\b{re.escape(entity)}\.{re.escape(field)}\s+must\s+be\s+one\s+of\s+"
        r"(\[[^\]]+\])", re.I)
    for invariant in ctx.get("invariants") or []:
        text = invariant.get("text") if isinstance(invariant, dict) else ""
        match = pattern.search(text or "")
        if not match:
            continue
        try:
            values = ast.literal_eval(match.group(1))
        except (ValueError, SyntaxError):
            continue
        if isinstance(values, (list, tuple)):
            return [str(value) for value in values]
    return []


def _date_fields(ctx, entity, exclude=None):
    rows = []
    for class_name, field_name, field_type, field in _fields(ctx):
        if class_name != entity or field_name == exclude:
            continue
        if field_type in DATE_TYPES or (
                field_type in ("str", "string")
                and any(hint in normalize(field_name)
                        for hint in DATE_NAME_HINTS)):
            rows.append((class_name, field_name))
    return rows


def _value_choices(ctx, entity, field_name):
    """`[(label, value)]` for a set effect, from facts, not a name guess."""
    fields = [(cls, name, ftype, field)
              for cls, name, ftype, field in _fields(ctx)
              if cls == entity and name == field_name]
    field_type = fields[0][2] if fields else ""
    choices = []
    if field_type in DATE_TYPES or any(hint in normalize(field_name)
                                      for hint in DATE_NAME_HINTS):
        choices.append(("now", "now"))
        for cls, other in _date_fields(ctx, entity, exclude=field_name):
            choices.append((f"{cls.lower()}.{other}", f"{cls.lower()}.{other}"))
    elif field_type in BOOL_TYPES:
        choices += [(f"not {field_name}", f"not {field_name}"),
                    ("True", True), ("False", False)]
    else:
        for value in _invariant_values(ctx, entity, field_name):
            choices.append((value, value))
    return choices


def _effect_questions(ctx, index, effect, params):
    target = effect["target"]
    variable, field_name = target.split(".", 1)
    entity = next((name for name in ctx.get("entity_names") or []
                   if name.lower() == variable), variable.capitalize())
    choices = []
    prompt = ""
    if effect["op"] in ("increment", "decrement"):
        prompt = (f"By how much should `{target}` "
                  f"{effect['op']}?")
        choices = [("1", "1")]
        choices += [(name, name) for name in params]
    else:
        prompt = f"What value should `{target}` be set to?"
        choices = _value_choices(ctx, entity, field_name)
        choices += [(name, name) for name in params]
    # Deduplicate while preserving order.
    seen, unique = set(), []
    for label, value in choices:
        key = (label, repr(value))
        if key not in seen:
            seen.add(key)
            unique.append((label, value))
    if not unique:
        return {
            "id": f"effect:{index}", "kind": "text", "required": True,
            "prompt": prompt,
            "apply": "value" if effect["op"] == "set" else "by",
        }
    return {
        "id": f"effect:{index}", "kind": "choice", "required": True,
        "prompt": prompt, "choices": unique,
        "apply": "value" if effect["op"] == "set" else "by",
    }


def _error_description(ctx, error):
    for item in ctx.get("errors") or []:
        if isinstance(item, dict) and item.get("name") == error:
            description = item.get("description")
            if isinstance(description, str) and description.strip():
                return description.strip()
    return ""


def _obvious_preconditions(ctx, raises, fields, method):
    """Preconditions the declared errors imply, plus the open ones.

    `NotFound` means the named entity exists; `InsufficientCopies` means the
    copies field is positive; `InvalidStockQty` means a `qty` parameter is
    positive. Everything else is an open human question because its name
    does not settle the condition.
    """
    obvious, open_errors = [], []
    params = set(_params(method))
    for error in raises or []:
        name = str(error).rsplit(".", 1)[-1]
        match = re.match(r"(\w+?)NotFoundError$", name)
        if match:
            entity = match.group(1)
            obvious.append({"check": f"{entity.lower()} exists",
                            "error": name, "raise_when": "false"})
            continue
        if "InsufficientCopies" in name:
            copies = [row for row in fields
                      if "copies" in normalize(row[1])
                      or "stock" in normalize(row[1])
                      or "quantity" in normalize(row[1])]
            if copies:
                entity, field_name = copies[0][0], copies[0][1]
                obvious.append({
                    "check": f"{entity.lower()}.{field_name} > 0",
                    "error": name,
                    "raise_when": "false",
                })
                continue
        if "InvalidStockQty" in name and "qty" in params:
            obvious.append({"check": "qty > 0", "error": name,
                            "raise_when": "false"})
            continue
        open_errors.append(name)
    return obvious, open_errors


def _propose(ctx, holder, method, role, requirement):
    """One proposal from the method's description/requirement, or None."""
    description = method.get("description") or ""
    text = " ".join(part for part in (description, requirement) if part)
    fields = _fields(ctx)
    params = _params(method)
    effects, creates = [], []
    seen_effects, seen_creates = set(), set()

    def add_effect(entity, field_name, op, write):
        key = (f"{entity.lower()}.{field_name}", op)
        if key in seen_effects:
            return
        seen_effects.add(key)
        item = {"target": f"{entity.lower()}.{field_name}", "op": op}
        if op in ("increment", "decrement"):
            item["by"] = "1"
        if write:
            item["write"] = write
        effects.append(item)

    for clause in re.split(r"[,;]|\band\b|\.", text):
        clause = clause.strip()
        if not clause:
            continue
        for verb, op in EFFECT_VERBS:
            match = re.search(rf"\b(?:{verb})\s+(.+)$", clause, re.I)
            if not match:
                continue
            noun = match.group(1).strip().strip(".")
            if op in ("increment", "decrement"):
                noun = re.split(r"\bby\b", noun, maxsplit=1)[0].strip()
            found = _match_field(noun, fields)
            if found:
                entity, field_name = found[0], found[1]
                add_effect(entity, field_name, op,
                           _write_call(ctx, entity, role))
                break
        match = re.search(
            rf"\b(?:{CREATE_VERBS})\s+(?:a\s+|an\s+|the\s+|new\s+)?(.+)$",
            clause, re.I)
        if match:
            entity = _match_class(match.group(1).strip().strip("."), ctx)
            if entity:
                call = _create_call(ctx, entity, role)
                key = (entity, call)
                if key not in seen_creates:
                    seen_creates.add(key)
                    creates.append({"class": entity, "call": call} if call
                                   else {"class": entity})
    if not effects and not creates:
        return None

    preconditions, open_errors = _obvious_preconditions(
        ctx, method.get("raises") or [], fields, method)
    questions = []
    if preconditions:
        questions.append({
            "id": "keep_preconditions", "kind": "choice", "required": True,
            "prompt": "Keep the preconditions implied by the declared errors?",
            "choices": [("keep", "keep"), ("drop", "drop")],
            "apply": "keep_preconditions",
        })
    for index, effect in enumerate(effects):
        question = _effect_questions(ctx, index, effect, params)
        question["effect"] = effect["target"]
        questions.append(question)
    if creates:
        questions.append({
            "id": "keep_creates", "kind": "choice", "required": True,
            "prompt": "Keep the proposed create call(s)?",
            "choices": [("keep", "keep"), ("drop", "drop")],
            "apply": "keep_creates",
        })
    for error in open_errors:
        description = _error_description(ctx, error)
        prompt = f"What condition should raise `{error}`?"
        if description:
            prompt += f" The error description says: {description}"
        prompt += " (free text, or skip to leave it out)"
        questions.append({
            "id": f"precondition:{error}", "kind": "text", "required": False,
            "prompt": prompt,
            "error": error, "apply": "precondition",
        })
    if creates and effects:
        writes = []
        for effect in effects:
            if effect.get("write") and effect["write"] not in writes:
                writes.append(effect["write"])
        if writes:
            questions.append({
                "id": "order", "kind": "choice", "required": True,
                "prompt": "Must the create happen before the update(s)?",
                "choices": [("create first", "create_first"),
                            ("update first", "update_first")],
                "apply": "order", "writes": writes,
                "create": creates[0].get("call") or "create",
            })
    return {
        "holder": holder, "method": method.get("name") or "?",
        "role": role, "entity": method.get("entity"),
        "description": description, "requirement": requirement,
        "effects": effects, "creates": creates,
        "preconditions": preconditions, "order": [], "forbid": [],
        "open_preconditions": open_errors,
        "questions": questions,
    }


def collect_contracts(output_dir):
    """`(proposals, context)` for stubs without a current contract."""
    ctx = generator.load_context(output_dir)
    requirements = load_requirements(output_dir)
    stats = {"source": output_dir, "implemented": 0, "stubs": 0,
             "stub_reasons": [], "prog": os.path.basename(output_dir)}
    files = generator.render_program(ctx, stats)
    existing, _dropped = contract_rules.load_method_contracts(
        output_dir, requirements)
    decided = {(record.get("holder"), record.get("method"))
               for record in existing}
    services = {}
    for service in ctx.get("services") or []:
        for method in service.get("methods") or []:
            if isinstance(method, dict) and method.get("name"):
                services[(service.get("service_name"), method["name"])] = method
    repos = {}
    for repo in ctx.get("repositories") or []:
        for method in repo.get("methods") or []:
            if isinstance(method, dict) and method.get("name"):
                repos[(repo.get("interface_name"), method["name"])] = method
    proposals = []
    for filename, role in (("services.py", "service"),
                           ("repositories.py", "repository")):
        for _start, _end, info in generator.find_stub_spans(
                files.get(filename) or ""):
            holder = info.get("cls")
            method_name = generator._stub_method(info)
            if (holder, method_name) in decided:
                continue
            method = (services if role == "service" else repos).get(
                (holder, method_name))
            if method is None:
                continue
            requirement = generator._requirements_line(
                requirements, method_name)
            proposal = _propose(ctx, holder, method, role, requirement)
            if proposal is not None:
                proposals.append(proposal)
    context = {"prompt_sha": requirements_sha(requirements)}
    return proposals, context


def _describe_effect(effect):
    target, op = effect["target"], effect["op"]
    if op == "set" and "value" in effect:
        detail = f" = {effect['value']}"
    elif op in ("increment", "decrement") and "by" in effect:
        detail = f" by {effect['by']}"
    else:
        detail = " = ?" if op == "set" else " by ?"
    suffix = f" via {effect['write']}" if effect.get("write") else ""
    return f"{op} {target}{detail}{suffix}"


def describe_proposal(index, total, proposal, questions=True):
    lines = [
        f"--- contract {index}/{total} ---",
        f"CONTRACT for {proposal['holder']}.{proposal['method']}",
    ]
    if proposal["description"]:
        lines.append(f"  {proposal['description']}")
    if proposal["requirement"]:
        lines.append(f"  requirement: {proposal['requirement']}")
    if proposal["effects"]:
        lines.append("  proposed effects:")
        lines += [f"    - {_describe_effect(effect)}"
                  for effect in proposal["effects"]]
    if proposal["creates"]:
        lines.append("  proposed creates:")
        for create in proposal["creates"]:
            call = f" via {create['call']}" if create.get("call") else ""
            lines.append(f"    - {create.get('class')}{call}")
    if proposal["preconditions"]:
        lines.append("  preconditions from declared errors:")
        for item in proposal["preconditions"]:
            when = item.get("raise_when")
            suffix = f" (raise when {when})" if when else ""
            lines.append(
                f"    - {item['check']} -> {item['error']}{suffix}")
    if questions:
        for question in proposal["questions"]:
            if question["kind"] == "choice":
                choices = ", ".join(label for label, _value
                                    in question["choices"])
                lines.append(f"  {question['prompt']} [{choices}]")
            else:
                lines.append(f"  {question['prompt']}")
    return lines


def _ask_choice(prompt, choices, input_fn):
    shown = ", ".join(f"{number}) {label}" for number, (label, _value)
                      in enumerate(choices, start=1))
    try:
        answer = input_fn(f"{prompt} [{shown}] or skip: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if answer.lower() in ("", "skip", "s"):
        return None
    if answer.isdigit():
        index = int(answer) - 1
        if 0 <= index < len(choices):
            return choices[index][1]
        return None
    for label, value in choices:
        if answer.lower() == label.lower():
            return value
    return None


def ask_proposal(proposal, input_fn=input, out_fn=print):
    """Ask every open question; return the answers dict, or None on skip."""
    answers = {}
    for question in proposal["questions"]:
        if question["kind"] == "choice":
            answer = _ask_choice(question["prompt"], question["choices"],
                                 input_fn)
        else:
            out_fn(question["prompt"])
            try:
                answer = input_fn("> ").strip()
            except (EOFError, KeyboardInterrupt):
                answer = ""
            if answer.lower() in ("", "skip", "s"):
                answer = None
        if answer is None and question.get("required", True):
            return None
        answers[question["id"]] = answer
    return answers


def _finalize(proposal, answers, prompt_sha, ctx):
    """Turn the confirmed answers into a generator-ready record."""
    effects = []
    for index, effect in enumerate(proposal["effects"]):
        item = dict(effect)
        value = answers.get(f"effect:{index}")
        if value is None:
            return None
        if item["op"] in ("increment", "decrement"):
            item["by"] = value
        else:
            item["value"] = value
        effects.append(item)
    creates = []
    if answers.get("keep_creates", "keep") != "drop":
        creates = [dict(create) for create in proposal["creates"]
                   if create.get("call")]
    preconditions = []
    if answers.get("keep_preconditions", "keep") != "drop":
        preconditions = [dict(item) for item in proposal["preconditions"]]
    for question in proposal["questions"]:
        if question.get("apply") != "precondition":
            continue
        answer = answers.get(question["id"])
        if answer:
            preconditions.append({"check": answer, "error": question["error"],
                                  "raise_when": "true"})
    order = []
    writes = []
    for effect in effects:
        if effect.get("write") and effect["write"] not in writes:
            writes.append(effect["write"])
    if creates and writes:
        choice = answers.get("order")
        create_call = creates[0].get("call")
        if choice == "create_first" and create_call:
            order = ["preconditions", create_call] + writes
        elif choice == "update_first" and create_call:
            order = ["preconditions"] + writes + [create_call]
    forbid = []
    by_lower = {name.lower(): name for name in ctx.get("entity_names") or []}
    for effect in effects:
        if effect["op"] != "set" or str(effect.get("value")) != "now":
            continue
        target = effect["target"]
        variable, field_name = target.split(".", 1)
        entity = by_lower.get(variable, variable.capitalize())
        for _cls, other in _date_fields(ctx, entity, exclude=field_name):
            forbid.append({
                "target": target,
                "reads": f"{variable}.{other}",
                "message": f"`{target}` is set to now, not another date field",
            })
    record = {
        "holder": proposal["holder"],
        "method": proposal["method"],
        "decided_by": "user",
        "effects": effects,
        "creates": creates,
        "preconditions": preconditions,
        "order": order,
        "forbid": forbid,
    }
    if prompt_sha is not None:
        record["requirements_sha"] = prompt_sha
    return record


def run_review(output_dir, input_fn=input, out_fn=print):
    """Ask every open contract; return `(asked, answered)`."""
    proposals, context = collect_contracts(output_dir)
    if not proposals:
        out_fn("no open method contracts — nothing to decide")
        return 0, 0
    records, _dropped = contract_rules.load_method_contracts(
        output_dir, load_requirements(output_dir))
    ctx = generator.load_context(output_dir)
    answered = 0
    for number, proposal in enumerate(proposals, start=1):
        for line in describe_proposal(number, len(proposals), proposal,
                                      questions=False):
            out_fn(line)
        answers = ask_proposal(proposal, input_fn, out_fn)
        if answers is None:
            out_fn("skipped — left open")
            continue
        record = _finalize(proposal, answers, context["prompt_sha"], ctx)
        if record is None:
            out_fn("skipped — a required value is unanswered")
            continue
        records = [item for item in records
                   if (item.get("holder"), item.get("method"))
                   != (record["holder"], record["method"])]
        records.append(record)
        answered += 1
    contract_rules.save_method_contracts(output_dir, records)
    out_fn(f"answered {answered} of {len(proposals)}; contracts in "
           f"{contract_rules.METHOD_CONTRACTS_NAME}")
    return len(proposals), answered


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    list_only = "--list" in args
    args = [a for a in args if a != "--list"]
    if len(args) != 1:
        print(__doc__.splitlines()[0], file=sys.stderr)
        print("usage: python review_contracts.py OUT_DIR [--list]",
              file=sys.stderr)
        return 2
    if list_only:
        proposals, _context = collect_contracts(args[0])
        if not proposals:
            print("no open method contracts — nothing to decide")
            return 0
        for number, proposal in enumerate(proposals, start=1):
            for line in describe_proposal(number, len(proposals), proposal):
                print(line)
        return 0
    run_review(args[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
