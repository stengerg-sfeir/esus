"""Code-generation planning shared by the generator and its tests: import this.

A method body is decided in exactly one place. `plan_method` maps a contract
method plus its pattern_matches entry to a `(strategy, detail)` pair:

- `"crud:<kind>"` — mechanical in-memory implementation. Kinds: `create`,
  `read_one`, `read_all`, `update`, `delete`, `filter`. Reached two ways: the
  tie-breaker says so (`effective_directive` returns `pattern STANDARD_CRUD`,
  `READ_ALL`, `FILTER_BY_FIELD`, or a `rule`), or — when step F never saw the
  method (no entry at all) — the name alone is unambiguous.
- `"stub"` — anything else (aggregates, guards, exports, gaps, open ties).
  The generator emits `raise NotImplementedError` with the directive and the
  refusal reason in the docstring, never an invented body. A stub is a
  work order for the LLM pass, not a defect.

`MODEL_TYPES` maps the closed model-type vocabulary to Python spellings;
anything else passes through verbatim when it looks like a reference
(`Optional[`, `List[`, a declared entity) and becomes `Any` otherwise, so an
unknown spelling is visible in the signature rather than guessed at.
"""

from kernel import tie_rules
from kernel.consistency.naming import normalize

import re

MODEL_TYPES = {
    "int": "int",
    "string": "str",
    "boolean": "bool",
    "decimal": "Decimal",
    "datetime": "datetime.datetime",
    "date": "datetime.date",
    "text": "str",
    "float": "float",
}

# Method-name prefixes with an unambiguous mechanical reading. `get`/`find`
# are deliberately absent: `get_monthly_spending` aggregates while
# `get_product_by_id` reads, and a prefix rule cannot tell them apart — those
# stay stubs unless their pattern entry says otherwise.
CREATE_PREFIXES = ("create", "add", "insert", "save", "register", "make", "new")
READ_ONE_MARKERS = ("readone", "byid", "byemail", "byname", "bysku", "byisbn", "bycode")
READ_ALL_MARKERS = ("readall", "all", "list")
UPDATE_PREFIXES = ("update", "edit")
DELETE_PREFIXES = ("delete", "remove", "drop", "destroy")
FILTER_PREFIXES = ("find", "filter", "search", "query", "history")

MECHANICAL_PATTERNS = frozenset({"STANDARD_CRUD", "READ_ALL", "FILTER_BY_FIELD"})


def sanitize(identifier, fallback="unnamed"):
    """A valid Python identifier for any name string, or `fallback`."""
    cleaned = "".join(
        character if character.isalnum() or character == "_" else "_"
        for character in str(identifier or "")
    ).strip("_")
    if not cleaned:
        return fallback
    if cleaned[0].isdigit():
        cleaned = "_" + cleaned
    return cleaned or fallback


def map_type(spelling, entity_names=()):
    """A Python type spelling for a model or parameter type string."""
    if not isinstance(spelling, str) or not spelling.strip():
        return "Any"
    text = spelling.strip()
    lowered = text.lower()
    if lowered in MODEL_TYPES:
        return MODEL_TYPES[lowered]
    if lowered in ("none", "null", "void", "nonetype"):
        return "None"
    known = {normalize(name) for name in entity_names}
    bare = normalize(text.split("[", 1)[0].split("|", 1)[0])
    if text[:1].isupper() or "[" in text or "|" in text or "optional" in lowered:
        if bare and (not known or bare in known or "[" in text or "|" in text
                     or "optional" in lowered or text[:1].isupper()):
            return text
    return "Any"


def match_param(field_names, param):
    """Map a filter parameter to `(field, operator)` or None.

    The single definition of the rule; `codegen_store_template` carries a
    twin beside its user so generated programs stay dependency-free.
    Exact normalized equality is `eq`; a `start_`/`from_` prefix is `ge` and
    an `end_`/`to_` prefix is `le` against the field containing the remainder
    (`start_date` filters `expense_date`).
    """
    wanted = normalize(param or "")
    if not wanted:
        return None
    for field in field_names:
        if normalize(field) == wanted:
            return (field, "eq")
    for prefix, operator in (("start", "ge"), ("from", "ge"),
                             ("end", "le"), ("to", "le")):
        if wanted.startswith(prefix) and len(wanted) > len(prefix):
            rest = wanted[len(prefix):]
            for field in field_names:
                flat = normalize(field)
                if rest and (rest in flat or flat in rest):
                    return (field, operator)
    return None


def is_entity_type(text, entity_names):
    """True when a type spelling names a declared entity (unwrapping generics)."""
    if not isinstance(text, str):
        return False
    known = {normalize(name) for name in entity_names}
    tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text))
    return any(normalize(token) in known for token in tokens)


def classify_crud(method_name):
    """The mechanical CRUD kind of a method name, or None when ambiguous."""
    name = normalize(method_name or "")
    if not name:
        return None
    if name.startswith(CREATE_PREFIXES):
        return "create"
    if name.startswith(UPDATE_PREFIXES):
        return "update"
    if name.startswith(DELETE_PREFIXES):
        return "delete"
    if any(marker in name for marker in READ_ONE_MARKERS):
        return "read_one"
    if name.startswith(FILTER_PREFIXES):
        return "filter"
    if any(marker in name for marker in READ_ALL_MARKERS):
        return "read_all"
    return None


def plan_method(method, entry, entity_names=()):
    """Return `(strategy, detail)` for one contract method.

    `method` is the service_contracts/persistence_ports method object, `entry`
    its pattern_matches entry or None when step F never saw it. Detail is the
    CRUD kind, the rule id, or the stub reason — everything the emitter needs,
    nothing it must re-derive.
    """
    method = method if isinstance(method, dict) else {}
    name = method.get("name") if isinstance(method.get("name"), str) else ""
    if entry is not None:
        kind, payload = tie_rules.effective_directive(entry)
        if kind == "pattern":
            crud = classify_crud(name)
            if crud == "filter" and not _has_params(method):
                # A filter with no parameters filters nothing: `find_active`
                # with no status argument emitted a body returning every
                # record, silently dropping the constraint the name states.
                return ("stub", f"pattern {payload}: filter with no parameters filters nothing")
            if payload in MECHANICAL_PATTERNS and crud is not None:
                return (f"crud:{crud}", payload)
            if payload == "FILTER_BY_FIELD":
                shape = _filter_by_shape(method, entity_names)
                if shape is not None:
                    return (f"crud:{shape}", f"{payload}: by parameter shape")
            return ("stub", f"pattern {payload}: no mechanical reading")
        if kind == "rule":
            crud = classify_crud(name)
            if crud == "filter" and not _has_params(method):
                return ("stub", f"rule {payload}: filter with no parameters filters nothing")
            if crud is not None:
                return (f"crud:{crud}", payload)
            return ("stub", f"rule {payload}: method needs custom logic")
        if kind == "llm-gap":
            # A refused claim is about the claim, not the signature: a gap
            # refusing AGGREGATE for an entity return still reads as the
            # unique lookup its parameters describe (UNIQUE scopes read
            # exactly the read_one body). List returns stay refused — a
            # collection claim dismissed is not a filter earned.
            if _shape_crud(method, entity_names) == "read_one":
                return ("crud:read_one",
                        f"{_gap_reason(entry, payload)}; read-one by parameter shape")
            return ("stub", _gap_reason(entry, payload))
        return ("stub", _tie_reason(payload))
    crud = classify_crud(name)
    if crud == "filter" and not _has_params(method):
        return ("stub", "no pattern entry and a filter with no parameters")
    if crud is not None:
        return (f"crud:{crud}", "name-only: step F never saw this method")
    shape = _shape_crud(method, entity_names)
    if shape is not None:
        return (f"crud:{shape}",
                "name-only: step F never saw this method; by parameter shape")
    return ("stub", "no pattern entry and an ambiguous method name")


def _has_params(method):
    """True when the method declares at least one parameter."""
    return bool([p for p in (method.get("params") or []) if isinstance(p, dict)])


def _filter_by_shape(method, entity_names):
    """crud 'filter' from parameter shape, when the name says nothing.

    A FILTER_BY_FIELD method named `read_expenses_by_category` fails every
    name prefix yet describes a filter exactly: it returns a list and takes
    only scalar parameters, which `_select_body` turns into criteria (a
    parameter matching no field raises loudly at runtime instead of
    filtering wrong). Entity-typed parameters disqualify — that shape is a
    create/update carrying a record, not a filter over scalars.
    """
    if _shape_crud(method, entity_names) == "filter":
        return "filter"
    return None


def _shape_crud(method, entity_names):
    """`filter`, `read_one`, or None from parameter shape alone.

    List-of-entity returns with scalar-only parameters are filters;
    single-entity returns with scalar-only parameters are unique lookups
    (`read_budget_by_category_and_month` over a UNIQUE scope reads exactly
    the read_one body: criteria plus a loud complaint unless one record
    matches). Anything carrying a record, taking nothing, or returning
    nothing shaped is not a query shape at all.
    """
    params = [p for p in (method.get("params") or []) if isinstance(p, dict)]
    if not params:
        return None
    for param in params:
        if is_entity_type(param.get("type"), entity_names):
            return None
    returns = (method.get("return_type") or "")
    words = {normalize(token) for token in
             re.findall(r"[A-Za-z_][A-Za-z0-9_]*", returns)}
    entity = next((name for name in entity_names
                   if isinstance(name, str) and normalize(name) in words
                   and normalize(name) not in ("list", "dict", "optional",
                                               "none")), None)
    if entity is None:
        return None
    if "list" in words:
        return "filter"
    return "read_one"


def _gap_reason(entry, payload):
    gap = (entry or {}).get("pattern_id")
    claimed = (payload or {}).get("claimed_pattern_id")
    rejection = (payload or {}).get("rejection")
    if claimed:
        return f"gap {gap}: {claimed} refused ({rejection})"
    return f"gap {gap}: no pattern covers this method"


def _tie_reason(payload):
    candidates = payload.get("candidates") if isinstance(payload, dict) else None
    if candidates:
        return f"open tie between {' and '.join(candidates)}: review skipped"
    return "unclassifiable match entry"


def canon_tokens(text):
    """Lowercased `_`/`-`-separated tokens with CLI date synonyms folded.

    `--from-date` and `--start-date` name the same bound: leading `from`
    becomes `start` and leading `to` becomes `end`. Only the first token is
    folded, so `total` and `tomorrow` are untouched.
    """
    tokens = [t for t in re.split(r"[_-]+", str(text or "").lower()) if t]
    if tokens and tokens[0] == "from":
        tokens[0] = "start"
    if tokens and tokens[0] == "to":
        tokens[0] = "end"
    return tokens


def bind_field(dests, field):
    """An option dest for an adapter field: exact match, else unique containment.

    CLI flags abbreviate (`--price` for `price_cents`, `--category` for
    `category_id`, `--from-date` for `start_date`); containment in either
    direction resolves those, and an ambiguous or absent match is None.
    """
    wanted = "".join(canon_tokens(field))
    if not wanted:
        return None
    flats = {d: "".join(canon_tokens(d)) for d in dests}
    exact = [d for d, flat in flats.items() if flat == wanted]
    if len(exact) == 1:
        return exact[0]
    if exact:
        return None
    fuzzy = [d for d, flat in flats.items()
             if flat and (flat in wanted or wanted in flat)]
    return fuzzy[0] if len(fuzzy) == 1 else None


def surface_dests(invocation):
    """Every CLI option dest on the surface (global, command and subcommand)."""
    dests = []
    if not isinstance(invocation, dict):
        return dests

    def gather(options):
        if isinstance(options, list):
            for option in options:
                dest = option_dest(option)
                if dest:
                    dests.append(dest)

    gather(invocation.get("positional"))
    gather(invocation.get("options"))
    for command in invocation.get("commands") or []:
        if not isinstance(command, dict):
            continue
        gather(command.get("options"))
        for sub in command.get("subcommands") or []:
            if isinstance(sub, dict):
                gather(sub.get("options"))
    return dests


def option_dest(option):
    """The argparse dest for one option object, or None when it has none."""
    if not isinstance(option, dict):
        return None
    raw = (option.get("name") or option.get("short") or "").strip()
    if not raw.startswith("-"):
        raw = "--" + raw if raw else ""
    if not raw or raw.lstrip("-").lower() in ("help", "version"):
        return None
    return sanitize(raw.lstrip("-").replace("-", "_"), "opt")


def uncovered_required_fields(adapters, invocation):
    """Required adapter fields no CLI flag can supply, as `(action, field)`.

    A command the surface omits is `missing_command`; a *flag* it omits while
    an adapter requires the value strands the action: the CLI parses but can
    never invoke it. Optional fields are excluded — omitting those is correct.
    """
    if not isinstance(adapters, list):
        return []
    dests = surface_dests(invocation)
    uncovered = []
    for adapter in adapters:
        if not isinstance(adapter, dict):
            continue
        for field in adapter.get("input_fields") or []:
            if not isinstance(field, dict) or not field.get("field_name"):
                continue
            if not field.get("required"):
                continue
            if bind_field(dests, field["field_name"]) is None:
                uncovered.append((adapter.get("action_name"), field["field_name"]))
    return uncovered


def leaf_options(invocation, command, sub):
    """The option objects of a bare command or subcommand, or [] ."""
    if not isinstance(invocation, dict):
        return []
    for entry in invocation.get("commands") or []:
        if not isinstance(entry, dict) or entry.get("name") != command:
            continue
        if sub is None:
            options = entry.get("options")
            return options if isinstance(options, list) else []
        for item in entry.get("subcommands") or []:
            if isinstance(item, dict) and item.get("name") == sub:
                options = item.get("options")
                return options if isinstance(options, list) else []
    return []


def bind_commands(adapters, invocation, verb_stems):
    """Map `(command, subcommand_or_None)` to `(action_name, score)` or None.

    Entity affinity outranks verb spelling: `budget add` must reach the
    budget creator, not `add_category`, even though the latter spells the verb
    literally — implementing another entity's command is the failure this
    scoring exists to prevent.
    """
    bindings = {}
    unmapped = []
    if not isinstance(adapters, list):
        return bindings, unmapped
    commands = (invocation or {}).get("commands") if isinstance(invocation, dict) else None
    if not isinstance(commands, list):
        return bindings, unmapped
    for command in commands:
        if not isinstance(command, dict) or not command.get("name"):
            continue
        subs = [s for s in (command.get("subcommands") or [])
                if isinstance(s, dict) and s.get("name")]
        if not subs:
            bindings[(command["name"], None)] = _best_adapter(
                adapters, verb_stems, command["name"], None, unmapped)
        for sub in subs:
            bindings[(command["name"], sub["name"])] = _best_adapter(
                adapters, verb_stems, command["name"], sub["name"], unmapped)
    return bindings, unmapped


def _best_adapter(adapters, verb_stems, command, sub, unmapped):
    verb = (sub or command or "").lower()
    stems = verb_stems.get(verb, (verb,))
    scored = []
    for adapter in adapters:
        if not isinstance(adapter, dict):
            continue
        method = normalize(adapter.get("target_method") or "")
        action = normalize(adapter.get("action_name") or "")
        if verb and not any(stem in method for stem in stems):
            continue
        blob = (normalize(adapter.get("target_service") or "") + "|"
                + method + "|" + action)
        score = 0
        if command and normalize(command) in blob:
            score += 4
        if verb and verb in method:
            score += 2
        if verb and verb in action:
            score += 1
        scored.append((score, adapter.get("action_name"), adapter))
    if not scored:
        unmapped.append(f"{command} {sub}" if sub else f"{command}")
        return None
    scored.sort(key=lambda item: (-item[0], item[1] or ""))
    return (scored[0][1], scored[0][0])


def action_targets(adapters, services, repositories, entity_names):
    """`{action_name: {target_param: model_class_or_None}}` from signatures.

    An adapter field targeting `data` carries no type of its own; whether it
    is an entity comes from the target method's parameter of that name.
    Resolved here, baked into the CLI spec, so nothing guesses at runtime.
    """
    methods = {}
    for service in services or []:
        if not isinstance(service, dict):
            continue
        for method in service.get("methods") or []:
            if isinstance(method, dict) and method.get("name"):
                methods.setdefault((normalize(service.get("service_name") or ""),
                                    normalize(method["name"])), method)
    for repo in repositories or []:
        if not isinstance(repo, dict):
            continue
        holder = repo.get("interface_name") or repo.get("entity")
        for method in repo.get("methods") or []:
            if isinstance(method, dict) and method.get("name"):
                methods.setdefault((normalize(holder or ""),
                                    normalize(method["name"])), method)
    targets = {}
    for adapter in adapters or []:
        if not isinstance(adapter, dict):
            continue
        method = methods.get((normalize(adapter.get("target_service") or ""),
                              normalize(adapter.get("target_method") or "")))
        ptypes = {}
        if method:
            for param in method.get("params") or []:
                if isinstance(param, dict) and param.get("name"):
                    ptypes[normalize(param["name"])] = param.get("type")
        mapping = {}
        for field in adapter.get("input_fields") or []:
            if not isinstance(field, dict):
                continue
            target = field.get("target_param")
            model_cls = None
            ptype = ptypes.get(normalize(target)) if isinstance(target, str) else None
            if is_entity_type(ptype, entity_names):
                tokens = {normalize(t) for t in
                          re.findall(r"[A-Za-z_][A-Za-z0-9_]*", ptype or "")}
                for name in entity_names:
                    if normalize(name) in tokens:
                        model_cls = sanitize(name, "Model")
                        break
            if isinstance(target, str):
                mapping[target] = model_cls
        targets[adapter.get("action_name")] = mapping
    return targets


def is_assembly_field(adapter, field_name, targets):
    """True when a field is the assembled object, not a flaggable value.

    A field named exactly like its entity-typed target (`data` into `data`)
    carries the whole object its sibling fields build — no CLI flag supplies
    it, and none should. Lone (sibling-less) markers do not qualify: with
    nothing assembling the object, the value is genuinely unsuppliable.
    """
    if not isinstance(adapter, dict) or not isinstance(field_name, str):
        return False
    fields = [f for f in adapter.get("input_fields") or []
              if isinstance(f, dict) and f.get("field_name")]
    quede = [f for f in fields if normalize(f["field_name"]) == normalize(field_name)]
    if not quede:
        return False
    target = quede[0].get("target_param")
    if not isinstance(target, str) or normalize(field_name) != normalize(target):
        return False
    if targets.get(target) is None:
        return False
    siblings = [f for f in fields if f is not quede[0]
                and f.get("target_param") == target]
    return bool(siblings)


def action_argv(adapters, bindings, invocation):
    """`{action_name: {field_name: dest_or_None}}` over the bound leaves' flags."""
    leaves = {}
    for (command, sub), bound in bindings.items():
        if bound is None:
            continue
        dests = [d for d in (option_dest(o) for o in leaf_options(invocation, command, sub)) if d]
        leaves.setdefault(bound[0], []).append(dests)
    argv = {}
    for adapter in adapters or []:
        if not isinstance(adapter, dict):
            continue
        name = adapter.get("action_name")
        union = []
        for dests in leaves.get(name, []):
            union.extend(d for d in dests if d not in union)
        argv[name] = {}
        for field in adapter.get("input_fields") or []:
            if isinstance(field, dict) and field.get("field_name"):
                argv[name][field["field_name"]] = bind_field(union, field["field_name"])
    return argv


def uncovered_required_fields(adapters, invocation, targets=None):
    """`(action, field)` required pairs no bound CLI flag can supply.

    Only actions a command reaches are judged: orphan actions no leaf binds
    are dead weight, not stranded paths. Assembly markers (a `data` field its
    siblings build) need no flag. Optional fields are excluded — omitting
    those is correct.
    """
    if not isinstance(adapters, list):
        return []
    from kernel.consistency.checks_surface import COMMAND_VERB_STEMS
    targets = targets if isinstance(targets, dict) else {}
    bindings, _ = bind_commands(adapters, invocation, COMMAND_VERB_STEMS)
    argv = action_argv(adapters, bindings, invocation)
    by_name = {a.get("action_name"): a for a in adapters if isinstance(a, dict)}
    uncovered = []
    for (command, sub), bound in bindings.items():
        if bound is None:
            continue
        action, spec_argv = bound[0], argv.get(bound[0], {})
        adapter = by_name.get(action, {})
        for field in adapter.get("input_fields") or []:
            if not isinstance(field, dict) or not field.get("field_name"):
                continue
            if not field.get("required"):
                continue
            if is_assembly_field(adapter, field["field_name"], targets.get(action, {})):
                continue
            if spec_argv.get(field["field_name"]) is None:
                pair = (action, field["field_name"])
                if pair not in uncovered:
                    uncovered.append(pair)
    return uncovered


def unknown_model_fields(adapters, services, repositories, models):
    """`(action, field, entity)` triples assembling unknown model fields.

    An adapter field targeting an entity-typed parameter becomes a constructor
    keyword of that entity. A keyword the model does not declare (`author_id`
    into a `Book` with no such field) fails at runtime no matter what the CLI
    supplies — the adapter and the model disagree, and no flag fixes that.
    Assembly markers and scalar targets are excluded: only real keywords.
    """
    if not isinstance(adapters, list):
        return []
    entity_names = [m.get("name") for m in models or []
                    if isinstance(m, dict) and m.get("name")]
    fields_of = {}
    for model in models or []:
        if isinstance(model, dict) and model.get("name"):
            names = model.get("fields") if isinstance(model.get("fields"), list) else []
            fields_of[normalize(model["name"])] = {
                normalize(f.get("name")) for f in names
                if isinstance(f, dict) and f.get("name")}
    targets = action_targets(adapters, services, repositories, entity_names)
    by_name = {a.get("action_name"): a for a in adapters if isinstance(a, dict)}
    unknown = []
    for action, spec in targets.items():
        adapter = by_name.get(action, {})
        for target_param, model_cls in spec.items():
            if model_cls is None:
                continue
            known = fields_of.get(normalize(model_cls), set())
            for field in adapter.get("input_fields") or []:
                if not isinstance(field, dict) or not field.get("field_name"):
                    continue
                if field.get("target_param") != target_param:
                    continue
                if is_assembly_field(adapter, field["field_name"], spec):
                    continue
                if normalize(field["field_name"]) not in known:
                    unknown.append((action, field["field_name"], model_cls))
    return unknown
