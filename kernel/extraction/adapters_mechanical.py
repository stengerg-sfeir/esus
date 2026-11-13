"""Derive interaction adapters mechanically from a command surface.

Step G maps an external action onto a service method and its parameters.  When
the requirements state the whole command surface, most of that mapping is a
fact of the documents rather than a judgement: the leaf names the action, the
method list names the candidates, the flag list names the values, and the data
model says which value is a foreign key, a date or money.

This module derives those adapters without the model.  It is deliberately
conservative: a leaf whose target method is ambiguous, or whose flags do not
all resolve to parameters, makes the whole derivation fail and the caller asks
the model exactly as before.  That keeps the uncertain choices — semantic
aliases such as ``--output`` feeding ``file_path`` where no lexical relation
exists, unusual verbs, and the action choice for a prose-only prompt — with
the model or the human review, and gives the mechanical pass only the cases
the documents prove.

For a prose-only prompt, ``allow_prose`` accepts the surface step D chose: the
model makes the semantic action choices, and this pass fills their targets and
fields from the service signatures and the data model.

The result is used only when ``ESUS_MECHANICAL_ADAPTERS=1``; the ordinary path
is unchanged.
"""

import re

from kernel.codegen import bind_field, is_mapping_type, option_dest
from kernel.consistency.checks_adapters import DATE_FIELD_HINTS, MONEY_FIELD_HINTS
from kernel.consistency.checks_surface import COMMAND_VERB_STEMS
from kernel.consistency.naming import normalize

# `--available-only` and `--active-only` name a selector, not a field.  The
# remaining noun is what the method parameter has to meet.
SELECTOR_STOPWORDS = frozenset({"only", "all", "is", "has", "with", "show"})


def derive_adapters(components, services, models, requirements,
                    allow_prose=False):
    """`(adapters, reason)`; adapters is None when the documents cannot prove it.

    With ``allow_prose`` the surface produced by step D is accepted even when
    the requirements name no command lines: the model chose the actions (the
    semantic, risky half), and this pass only fills their targets and fields
    from the service signatures and the data model.  Without it a prose-only
    prompt declines rather than inventing a surface.
    """
    from kernel.extraction import command_lines

    if not command_lines.extract_command_lines(requirements or "") and not allow_prose:
        return None, "no explicit command lines"
    leaves = _leaves(components)
    if not leaves:
        return None, "no CLI leaves"
    method_index = _method_index(services)
    if not method_index:
        return None, "no service methods"
    model_fields = _model_fields(models)

    adapters = []
    used_actions = set()
    for command, sub, options in leaves:
        choice, reason = _pick_method(method_index, command, sub, options)
        if choice is None:
            return None, f"{_leaf_name(command, sub)}: {reason}"
        service_name, method = choice
        fields, reason = _fields_for(
            options, method, service_name, model_fields)
        if fields is None:
            return None, f"{_leaf_name(command, sub)}: {reason}"
        action = _action_name(command, sub, used_actions)
        used_actions.add(action)
        adapters.append({
            "action_name": action,
            "target_service": service_name,
            "target_method": method["name"],
            "input_fields": fields,
        })
    return adapters, None


# --- the surface ---------------------------------------------------------


def _leaves(components):
    """`(command, subcommand_or_None, options)` for every CLI leaf."""
    facade = components.get("facade") if isinstance(components, dict) else None
    invocation = facade.get("invocation") if isinstance(facade, dict) else None
    if not isinstance(invocation, dict):
        return []
    leaves = []
    for command in invocation.get("commands") or []:
        if not isinstance(command, dict) or not command.get("name"):
            continue
        subs = [sub for sub in (command.get("subcommands") or [])
                if isinstance(sub, dict) and sub.get("name")]
        if not subs:
            leaves.append((command["name"], None, _options(command)))
            continue
        for sub in subs:
            leaves.append((command["name"], sub["name"], _options(sub)))
    return leaves


def _options(node):
    return [option for option in (node.get("options") or [])
            if isinstance(option, dict) and option_dest(option)]


def _leaf_name(command, sub):
    return f"{command} {sub}" if sub else command


def _action_name(command, sub, used):
    base = normalize("".join([command] + (sub or "").split()))
    base = re.sub(r"[^a-z0-9_]", "", base) or "action"
    if not base[0].isalpha():
        base = "action_" + base
    name = base
    while name in used:
        name += "_2"
    return name


# --- choosing the method -------------------------------------------------


def _method_index(services):
    """`[(service_name, method, service_tokens, method_tokens, is_repo)]`."""
    index = []
    for service in services or []:
        if not isinstance(service, dict) or not service.get("service_name"):
            continue
        service_name = service["service_name"]
        service_tokens = set(_tokens(service_name))
        is_repo = "repository" in service_tokens or "repo" in service_tokens
        for method in service.get("methods") or []:
            if not isinstance(method, dict) or not method.get("name"):
                continue
            index.append((
                service_name,
                method,
                service_tokens,
                set(_tokens(method["name"])),
                is_repo,
            ))
    return index


def _pick_method(index, command, sub, options):
    """The one method the leaf names, or `(None, reason)` when it is a tie."""
    words = _path_words(command, sub)
    verb = next((word for word in reversed(words)
                 if word in COMMAND_VERB_STEMS), None)
    if verb is None:
        verb = words[-1]
    stems = COMMAND_VERB_STEMS.get(verb, (verb,))
    nouns = [word for word in words if word != verb] or [normalize(command)]

    scored = []
    for service_name, method, service_tokens, method_tokens, is_repo in index:
        if not method_tokens.intersection(stems):
            continue
        flat = "".join(_tokens(service_name) + _tokens(method["name"]))
        noun_hits = sum(
            1 for noun in nouns
            if noun in service_tokens
            or noun in method_tokens
            or noun in flat
        )
        # The flags the leaf carries are evidence too: `order search
        # --customer-id` names the customer search, not the status search,
        # even though both spell `search` and `order`.  Coverage breaks that
        # tie without letting a generic method outrank an entity match.
        coverage = _coverage(options, method)
        score = 5 * noun_hits + 2 + (0 if is_repo else 3) + 3 * coverage
        scored.append((score, is_repo, service_name, method))

    if not scored:
        return None, f"no method matches the verb '{verb}'"
    scored.sort(key=lambda item: (-item[0], item[1], item[2], item[3]["name"]))
    top = scored[0]
    rivals = [item for item in scored[1:] if item[0] == top[0]]
    # A repository and its service wrapper can both answer the same leaf; the
    # service is the public entry point, so it wins the tie (the repository
    # methods remain reachable when no wrapper exists).
    rivals = [item for item in rivals if item[1] == top[1]]
    if rivals:
        names = ", ".join(f"{item[2]}.{item[3]['name']}"
                          for item in [top] + rivals[:3])
        return None, f"ambiguous methods: {names}"
    return (top[2], top[3]), None


def _path_words(command, sub):
    words = (sub or "").split() or [command]
    return [normalize(word) for word in words if word]


def _coverage(options, method):
    """How many of the leaf's flags the method can consume."""
    params = [param["name"] for param in (method.get("params") or [])
              if isinstance(param, dict) and param.get("name")]
    used = set()
    covered = 0
    unmatched = 0
    for option in options:
        dest = option_dest(option)
        available = [name for name in params if name not in used]
        target = bind_field(available, dest) or _selector_param(available, dest)
        if target is None:
            unmatched += 1
            continue
        used.add(target)
        covered += 1
    if unmatched:
        mapping = next(
            (param for param in (method.get("params") or [])
             if isinstance(param, dict) and param.get("name") not in used
             and is_mapping_type(param.get("type"))),
            None,
        )
        if mapping is not None:
            covered += unmatched
    return covered


def _tokens(value):
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value or ""))
    return [normalize(token)
            for token in re.split(r"[^A-Za-z0-9]+", text)
            if token]


# --- mapping flags to parameters ----------------------------------------


def _fields_for(options, method, service_name, model_fields):
    """The adapter fields for one leaf, or `(None, reason)` when a flag is lost."""
    params = [param for param in (method.get("params") or [])
              if isinstance(param, dict) and param.get("name")]
    param_names = [param["name"] for param in params]
    entity = _entity_of(service_name, model_fields)
    fields = []
    used_params = set()
    unmatched = []

    for option in options:
        dest = option_dest(option)
        available = [name for name in param_names if name not in used_params]
        target = bind_field(available, dest)
        if target is None:
            target = _selector_param(available, dest)
        if target is None:
            unmatched.append((dest, option))
            continue
        used_params.add(target)
        fields.append(_field(dest, target, option, entity, model_fields))

    if unmatched:
        mapping = next(
            (param["name"] for param in params
             if param["name"] not in used_params
             and is_mapping_type(param.get("type"))),
            None,
        )
        if mapping is not None:
            # A `data: dict` update takes the leaf's remaining flags as its
            # keys.  The generator groups them into one dict; the adapter
            # names the parameter once so every value has a home.
            for dest, option in unmatched:
                fields.append(_field(dest, mapping, option, entity, model_fields))
            unmatched = []
        elif (len(unmatched) == 1
              and len([name for name in param_names
                       if name not in used_params]) == 1):
            # A single residual flag and a single residual parameter: the
            # documents leave no choice (expenses' `--output` -> file_path).
            dest, option = unmatched[0]
            target = [name for name in param_names
                      if name not in used_params][0]
            fields.append(_field(dest, target, option, entity, model_fields))
            unmatched = []

    # An optional flag no parameter can consume is not a reason to refuse the
    # whole leaf: library's prose leftover `overdue --overdue` is a duplicate
    # selector the surface review drops.  It is left out of the adapter; if
    # the surface keeps it, the readiness probe reports it as an ignored
    # option.  A *required* flag has no such safe reading.
    missing_required = [dest for dest, option in unmatched
                        if option.get("required")]
    if missing_required:
        dest = missing_required[0]
        return None, f"flag '--{dest.replace('_', '-')}' maps to no parameter"
    return fields, None


def _selector_param(param_names, dest):
    """A boolean selector's noun meeting exactly one parameter."""
    tokens = [token for token in re.split(r"[_-]+", dest.lower())
              if token and token not in SELECTOR_STOPWORDS]
    if not tokens:
        return None
    matches = []
    for name in param_names:
        flat = normalize(name)
        if any(token in flat for token in tokens):
            matches.append(name)
    return matches[0] if len(matches) == 1 else None


def _field(field_name, target_param, option, entity, model_fields):
    field = {
        "field_name": field_name,
        "target_param": target_param,
        "transform": "DIRECT",
        "lookup_entity": None,
        "required": bool(option.get("required")),
    }
    declared = model_fields.get(entity, {}).get(field_name) \
        or model_fields.get(entity, {}).get(target_param)
    lookup = (declared or {}).get("foreign_key") or {}
    target_entity = lookup.get("target_entity") if isinstance(lookup, dict) else None
    target_type = str((declared or {}).get("type") or "").lower()

    if target_entity and str(target_param).endswith("_id"):
        field["transform"] = "LOOKUP_ID"
        field["lookup_entity"] = target_entity
    elif _is_money(field_name, target_param, target_type):
        field["transform"] = "DECIMAL_TO_CENTS"
    elif (_is_date(field_name, target_param)
          and target_type not in ("int", "integer", "float", "decimal",
                                  "bool", "boolean")):
        field["transform"] = "ISO_DATE"
    elif option.get("type") == "bool" and target_type in ("int", "integer"):
        field["transform"] = "BOOL_TO_ONE"
    return field


def _is_date(field_name, target_param):
    """The transform the checker will accept for a date-valued field.

    The checker reads the field's name, not its target type: `created_at` and
    `expense_date` describe a date, while `generated_at` and `confirmed_at`
    do not, and `month`/`year` are labels rather than ISO dates.  Using the
    same predicate here keeps the mechanical document from emitting a
    transform the first repair would immediately replace.
    """
    lowered = str(field_name or "").strip().lower()
    if normalize(field_name) in ("month", "year"):
        return False
    return any(hint in lowered for hint in DATE_FIELD_HINTS)


def _is_money(field_name, target_param, target_type):
    lowered = str(field_name or "").lower()
    target = str(target_param or "").lower()
    if target_type in ("decimal", "money"):
        return True
    if "cents" in target and "cents" not in lowered:
        return True
    return any(hint in lowered for hint in MONEY_FIELD_HINTS) \
        and any(hint in target for hint in MONEY_FIELD_HINTS + ("cents",))


def _entity_of(service_name, model_fields):
    base = service_name
    for suffix in ("Service", "Repository"):
        if base.endswith(suffix):
            base = base[:-len(suffix)]
    for name in model_fields:
        if normalize(name) == normalize(base):
            return name
    return None


def _model_fields(models):
    fields = {}
    for model in models or []:
        if not isinstance(model, dict) or not model.get("name"):
            continue
        fields[model["name"]] = {
            field["name"]: field
            for field in (model.get("fields") or [])
            if isinstance(field, dict) and field.get("name")
        }
    return fields
