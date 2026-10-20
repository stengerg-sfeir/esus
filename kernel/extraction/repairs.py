"""The two contradictions a grammar cannot express, removed deterministically.

The project's rule is consistency *by construction*: a value that must not exist
is made unrepresentable in the GBNF, and a prompt sentence is the second line of
defence, not the first. Three defects stay outside both, because they are global
properties of the document rather than the shape of any one field:

- **Two declared errors for one missing thing.** `CategoryNotFoundError` and
  `MissingCategoryError` are the same failure; whether two names mean one thing is
  a comparison *between* entries, and GBNF cannot express "distinct subjects over
  an unbounded alphabet" any more than it can express "distinct method names"
  (§9.7). The prompt says one name per failure and the model wrote two.
- **A create that reports a not-found of what it creates.** `create_product`
  raising `ProductNotFoundError` needs the method's *verb* and its *noun* to be
  compared against the error's noun; the contract grammar leaves both names free,
  so it cannot.
- **A transform that does not fit the field's name.** `DECIMAL_TO_CENTS` on
  `copies` needs the field's *name* and its *transform* to agree on a kind of
  value; the adapter grammar closes `transform` to an enum and `field_name` to
  free text, so the pair is not a regular property either.
- **A field sent past its own parameter.** `category_id` mapped into `data`
  while the method declares a `category_id` needs the field's *name* and the
  method's *parameter list* to be compared; neither the prompt block nor the
  grammar relates the two, so it cannot.

This is the same move as `dedupe.py` (§9.7): a *removal* of something that
contradicts the rest of the document, never the invention or rewriting of a
value. Every decision is logged, and the predicates are imported from
`kernel.consistency` — the checker is the single definition of each
contradiction, so a repair and the rule that reports it can never disagree. Run
after every step that produces the documents it touches, and before writing.
"""

import re

from kernel.consistency import checks_adapters, checks_errors, checks_models
from kernel.consistency import checks_surface as surface_checks
from kernel.consistency.methods import PLACEHOLDER_VALUES, param_names
from kernel.consistency.naming import normalize
from kernel.codegen import bind_field, is_entity_type, option_dest


def repair_errors(errors, services, log):
    """Remove the two error-registry contradictions; return `(errors, services)`.

    The order matters: duplicates are resolved (and their `raises` references
    redirected) *before* the create/not-found raises are dropped, so a reference
    that becomes contradictory only after a redirect is still caught.

    Doing nothing to a document that cannot hold the defect is deliberate: a
    program with no services and a clean registry passes through untouched.
    """
    errors, services = _resolve_duplicate_subjects(errors, services, log)
    services = _drop_contradictory_raises(services, log)
    return errors, services


# --- a declared error nothing raises and the requirements never name ---------------

# Too common to prove an error is grounded on their own: every name ends in one,
# and "invalid" is the shape this repair exists to remove, not evidence for it.
_GROUNDING_STOPWORDS = frozenset(
    {"error", "exception", "found", "not", "the", "invalid", "missing"}
)

# The validation shapes `ERRORS_SYSTEM` forbids: a class named for an input check
# rather than a failure the program must handle.
_VALIDATION_PREFIXES = ("invalid", "malformed", "bad", "unrecognized", "unexpected")
_VALIDATION_MARKERS = ("validation", "parse", "format")


def repair_unraised_errors(errors, services, requirements, log):
    """Drop an error no method raises and the requirements never name.

    An error type that no method raises is a class the generator would emit and
    never use. Whether it belongs is decided by the requirements, the only
    authority on the program's failures:

    - **Kept when a method raises it** — nothing to repair.
    - **Kept when the requirements spell it out** — `CategoryNotFoundError` in
      inventory is named character for character, and the registry must carry it.
    - **Kept when a distinctive word of its name is grounded** — cli_tool's
      `MalformedCSVError` is warranted by "malformed CSV", and library's
      `OverdueLoanFoundError` by "overdue"; their being unraised is a gap in the
      contracts, not in the registry, so the registry stays faithful and the
      checker reports the gap.
    - **Dropped otherwise** — and always dropped when the name is a validation
      shape (`Invalid*`, `Malformed*`), which `ERRORS_SYSTEM` forbids outright
      unless the requirements name it.

    Measured on library: `InvalidInputError` and `MalformedCSVError` (neither
    grounded, both validation-shaped) are dropped, `OverdueLoanFoundError`
    (grounded) is kept.
    """
    # With no requirements text there is no authority to judge against, so the
    # registry is left exactly as generated.
    if not isinstance(errors, list) or not errors or not requirements:
        return errors
    lowered = requirements.lower()
    raised = _raised_names(services)
    kept = []
    for item in errors:
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str) or not name.strip():
            kept.append(item)
            continue
        if _should_keep_error(name, raised, lowered):
            kept.append(item)
            continue
        if log is not None:
            why = "a validation shape the requirements never name" if _is_validation_error(
                name
            ) else "named nowhere in the requirements"
            log.write(
                f"[ok] step errors: no method raises '{name}' and it is {why} — dropped"
            )
    return kept


def _should_keep_error(name, raised, lowered_requirements):
    """True when an error must survive the unraised-error repair."""
    if name.strip().lower() in raised:
        return True
    if name.strip().lower() in lowered_requirements:
        return True
    if _is_validation_error(name):
        # A validation class is warranted only when the requirements describe
        # that failure — cli_tool's "malformed CSV" grounds `MalformedCSVError`,
        # while nothing in library or expenses grounds `InvalidInputError` or
        # `InvalidBudgetAmountError`. Its own validation word must be present.
        return _validation_word_grounded(name, lowered_requirements)
    return _is_grounded(name, lowered_requirements)


def _is_validation_error(name):
    """True when the name is a validation shape rather than a failure."""
    lowered = name.strip().lower()
    if lowered.startswith(_VALIDATION_PREFIXES):
        return True
    return any(marker in lowered for marker in _VALIDATION_MARKERS)


def _validation_word_grounded(name, lowered_requirements):
    """True when the requirements use the validation word the name is built on.

    Only the leading validation word is consulted: `MalformedCSVError` is kept
    when the requirements say "malformed", `InvalidInputError` is dropped when
    they never say "invalid". A marker such as "format" is deliberately not used
    as grounding — it appears in ordinary prose about dates and rarely describes
    a failure.
    """
    lowered = name.strip().lower()
    return any(
        lowered.startswith(prefix) and prefix in lowered_requirements
        for prefix in _VALIDATION_PREFIXES
    )


def _is_grounded(name, lowered_requirements):
    """True when a distinctive word of the error's name appears in the requirements.

    The name is a CamelCase identifier, so its words are recovered by separating a
    capital that follows a lowercase before lowering — `OverdueLoanFoundError` is
    `overdue`, `loan`, `found`, `error`, not one token. Only a distinctive word
    can prove grounding: the stopwords every name shares (`error`, `found`, `not`)
    carry no subject.
    """
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    for word in re.findall(r"[a-z]+", spaced.lower()):
        if word in _GROUNDING_STOPWORDS or len(word) < 4:
            continue
        if word in lowered_requirements:
            return True
    return False


# --- one name per missing subject -------------------------------------------------


def _resolve_duplicate_subjects(errors, services, log):
    """Keep one error per missing subject; redirect the others' references to it.

    The kept name is the one a method actually raises, so the registry follows
    the code rather than the code following the registry. When neither is raised
    the first declared wins — a deterministic tie-break, logged, so the choice is
    visible rather than silent.
    """
    if not isinstance(errors, list):
        return errors, services

    subjects = {}
    for index, item in enumerate(errors):
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        subject = checks_errors._missing_subject(name)
        if subject:
            subjects.setdefault(subject, []).append(index)

    raised = _raised_names(services)
    redirect = {}
    dropped_indexes = set()
    for subject, indexes in sorted(subjects.items()):
        if len(indexes) < 2:
            continue
        names = [errors[index].get("name") for index in indexes]
        keep_name = next(
            (name for name in names if isinstance(name, str) and name.strip().lower() in raised),
            names[0],
        )
        kept_index = next(
            index for index in indexes
            if errors[index].get("name") == keep_name
        )
        for index in indexes:
            if index == kept_index:
                continue
            drop_name = errors[index].get("name")
            dropped_indexes.add(index)
            if isinstance(drop_name, str):
                redirect[drop_name.strip().lower()] = keep_name
            if log is not None:
                log.write(
                    f"[ok] step errors: '{drop_name}' and '{keep_name}' name one missing "
                    f"record ({subject}) — dropped '{drop_name}', kept '{keep_name}'"
                )

    if not dropped_indexes:
        return errors, services

    kept_errors = [item for index, item in enumerate(errors) if index not in dropped_indexes]
    _redirect_raises(services, redirect)
    return kept_errors, services


def _raised_names(services):
    """Every error name any method raises, lowercased."""
    raised = set()
    if not isinstance(services, list):
        return raised
    for service in services:
        if not isinstance(service, dict):
            continue
        for method in service.get("methods") or []:
            if isinstance(method, dict):
                for target in method.get("raises") or []:
                    if isinstance(target, str):
                        raised.add(target.strip().lower())
    return raised


def _redirect_raises(services, redirect):
    """Point every `raises` entry at the kept spelling of its subject."""
    if not redirect or not isinstance(services, list):
        return services
    for service in services:
        if not isinstance(service, dict):
            continue
        for method in service.get("methods") or []:
            if not isinstance(method, dict) or not isinstance(method.get("raises"), list):
                continue
            method["raises"] = [
                redirect.get(target.strip().lower(), target)
                if isinstance(target, str) else target
                for target in method["raises"]
            ]
    return services


# --- a create cannot fail to find what it creates ---------------------------------


def _drop_contradictory_raises(services, log):
    """Remove a not-found raise from the create-like method that contradicts it.

    The predicate is the checker's: the created noun and the absent noun must be
    the same, so `add_stock(product_id, ...)` keeping `ProductNotFoundError` is
    left alone while `add_product` raising it is not.
    """
    if not isinstance(services, list):
        return services
    for service in services:
        if not isinstance(service, dict):
            continue
        owner = service.get("service_name")
        for method in service.get("methods") or []:
            if not isinstance(method, dict) or not isinstance(method.get("raises"), list):
                continue
            name = method.get("name")
            kept = [
                target for target in method["raises"]
                if not (isinstance(target, str)
                        and checks_errors.is_contradictory_raise(name, target))
            ]
            if len(kept) != len(method["raises"]):
                for target in method["raises"]:
                    if target not in kept and log is not None:
                        log.write(
                            f"[ok] step contracts: {owner}.{name} is a create and cannot fail to "
                            f"find what it creates — dropped raises '{target}'"
                        )
                method["raises"] = kept
    return services


# --- a field sent past its own parameter ----------------------------------------

def repair_adapter_targets(adapters, services, log):
    """Redirect a field to the parameter spelled like the field itself.

    A field whose own name is a parameter of the target method belongs to that
    parameter — the method has already said where the value goes. Sending it
    into an aggregate beside it silently drops the value (expenses'
    `add_expense` sent `category_id` into `data` while the method declares a
    `category_id` of its own; `update_budget` sent `month` into `budget` while
    a `month` parameter exists). The predicate is the checker's
    (`_check_target_param`), so the repair and `misplaced_field` share one
    definition of "belongs". An adapter whose service or method cannot be
    resolved is left alone: the checker reports the unknown reference, and
    there is no honest target to redirect to.
    """
    if not isinstance(adapters, list):
        return adapters
    index = _service_method_index(services)
    for adapter in adapters:
        if not isinstance(adapter, dict):
            continue
        action = adapter.get("action_name")
        method = _resolve_adapter_method(adapter, index)
        if method is None:
            continue
        declared = {}
        for name in param_names(method):
            if isinstance(name, str) and name.strip():
                declared.setdefault(normalize(name), name)
        if not declared:
            continue
        for field_entry in adapter.get("input_fields") or []:
            if not isinstance(field_entry, dict):
                continue
            field_name = field_entry.get("field_name")
            target_param = field_entry.get("target_param")
            if not isinstance(field_name, str) or not isinstance(target_param, str):
                continue
            if normalize(field_name) in declared and normalize(field_name) != normalize(target_param):
                honest = declared[normalize(field_name)]
                if log is not None:
                    log.write(
                        f"[ok] step adapters: {action}.{field_name} went to "
                        f"'{target_param}' while the method declares '{honest}' — "
                        f"redirected to '{honest}'"
                    )
                field_entry["target_param"] = honest
    return adapters


def _service_method_index(services):
    """Map (normalized service, normalized method) to the method object."""
    index = {}
    if not isinstance(services, list):
        return index
    for service in services:
        if not isinstance(service, dict):
            continue
        service_name = service.get("service_name")
        if not isinstance(service_name, str) or not service_name.strip():
            continue
        methods = index.setdefault(normalize(service_name), {})
        for method in service.get("methods") or []:
            if not isinstance(method, dict):
                continue
            method_name = method.get("name")
            if isinstance(method_name, str) and method_name.strip():
                methods.setdefault(normalize(method_name), method)
    return index


def _resolve_adapter_method(adapter, index):
    """The service-contract method an adapter targets, or None when unknown."""
    target_service = adapter.get("target_service")
    target_method = adapter.get("target_method")
    if not isinstance(target_service, str) or not isinstance(target_method, str):
        return None
    return index.get(normalize(target_service), {}).get(normalize(target_method))


# --- a subcommand named as a placeholder ------------------------------------------

def repair_placeholder_subcommands(components, log):
    """Drop a subcommand whose name is a placeholder.

    A subcommand named `none` states that the command takes no subcommand —
    library's bare `` `library overdue` `` line came back as command `overdue`
    with subcommand `none`, which no method can serve and no CLI framework can
    route. The grammar leaves subcommand names free text, so presence of a
    placeholder cannot be unrepresentable; it is removed here, leaving the
    command with no subcommands, which is what the requirements describe. Only
    the placeholder entries go: real siblings are untouched, and every removal
    is logged.
    """
    if not isinstance(components, dict):
        return components
    facade = components.get("facade")
    if not isinstance(facade, dict):
        return components
    invocation = facade.get("invocation")
    if not isinstance(invocation, dict):
        return components
    commands = invocation.get("commands")
    if not isinstance(commands, list):
        return components
    for command in commands:
        if not isinstance(command, dict):
            continue
        subcommands = command.get("subcommands")
        if not isinstance(subcommands, list):
            continue
        kept = [
            sub for sub in subcommands
            if not (isinstance(sub, dict) and _is_placeholder_name(sub.get("name")))
        ]
        removed = len(subcommands) - len(kept)
        if removed:
            if log is not None:
                log.write(
                    f"[ok] step components: command '{command.get('name')}' had "
                    f"{removed} placeholder subcommand(s) meaning no subcommand — "
                    f"dropped"
                )
            command["subcommands"] = kept
    return components


def _is_placeholder_name(name):
    """True when a command name is junk rather than a word of the requirements."""
    return normalize(name) in PLACEHOLDER_VALUES if isinstance(name, str) else False


def repair_flat_command_duplicates(components, log):
    """Drop a flat `a_b` command duplicating a declared `a b` pair.

    The model sometimes emits both the spaced pair (command `member` with
    subcommand `history`, carrying the flags) and a flat single command
    (`member_history`, with no subcommands and no method behind it). The
    flat form is the same path spelled twice: it adds no flags, serves no
    method, and the checker reports it as `unbacked_command` while the
    spaced form passes. Only the flat duplicate goes — kept is the form
    carrying the subcommand — and only when the spaced pair exists, so a
    genuinely flat command is never touched. Every removal is logged.

    Ordering matters: run this after `repair_missing_surface`, because the
    pair it matches may itself have been repaired in — a retry body can
    lack `member history` while keeping a flat `member_history`, and an
    earlier pass would find no pair and keep the flat form.
    """
    if not isinstance(components, dict):
        return components
    facade = components.get("facade")
    if not isinstance(facade, dict):
        return components
    invocation = facade.get("invocation")
    if not isinstance(invocation, dict):
        return components
    commands = invocation.get("commands")
    if not isinstance(commands, list):
        return components

    def parts(name):
        return [p for p in re.split(r"[_\-\s]+", name.strip().lower()) if p] \
            if isinstance(name, str) else []

    paired = set()
    for command in commands:
        if not isinstance(command, dict):
            continue
        name = command.get("name")
        subs = command.get("subcommands")
        if not isinstance(name, str) or not isinstance(subs, list):
            continue
        for sub in subs:
            if isinstance(sub, dict) and isinstance(sub.get("name"), str):
                paired.add((name.strip().lower(),
                            sub["name"].strip().lower()))

    kept = []
    for command in commands:
        if not isinstance(command, dict):
            kept.append(command)
            continue
        name = command.get("name")
        subs = command.get("subcommands")
        if (isinstance(name, str) and (not subs)
                and len(parts(name)) == 2
                and tuple(parts(name)) in paired):
            if log is not None:
                first, second = parts(name)
                log.write(
                    f"[ok] step components: dropped flat '{name}' duplicating "
                    f"'{first} {second}' — kept the form carrying the subcommand"
                )
            continue
        kept.append(command)
    invocation["commands"] = kept
    return components


def repair_primary_key_uniqueness(models, log):
    """Set `unique=true` on primary-key fields declaring `unique=false`.

    A primary key is unique by definition; the predicate is the checker's own
    (`checks_models.key_uniqueness_contradicted`), so repair and rule cannot
    disagree. Only the contradicted flag is touched — a nullable primary key
    is left alone (auto-incremented ids are declared optional-None by several
    prompts, so nullability is modeling, not noise). Every fix is logged.
    """
    if not isinstance(models, list):
        return models
    fixed = 0
    for model in models:
        if not isinstance(model, dict):
            continue
        for field in model.get("fields") or []:
            if checks_models.key_uniqueness_contradicted(field):
                field["unique"] = True
                fixed += 1
                if log is not None:
                    log.write(
                        f"[ok] step data_models: {model.get('name')}.{field.get('name')} "
                        f"is a primary key — unique=false contradicts it, set true"
                    )
    return models


# --- a transform that does not fit the field's name -------------------------------

def repair_adapter_transforms(adapters, log):
    """Replace a transform whose kind contradicts the field's name with DIRECT.

    A transform states how a value's representation changes; the field's name is
    the only evidence of what kind of value it is. When the two disagree — a
    count converted to cents, a single name read as a list, a description parsed
    as a date — the transform is wrong for the field, and `DIRECT` is the honest
    replacement: copy the value unchanged. The hint sets and the comparison come
    from the checker, so the repair and `mismatched_transform` share one
    definition of "fits".
    """
    if not isinstance(adapters, list):
        return adapters
    for adapter in adapters:
        if not isinstance(adapter, dict):
            continue
        action = adapter.get("action_name")
        for field_entry in adapter.get("input_fields") or []:
            if not isinstance(field_entry, dict):
                continue
            replacement = _fitter_transform(field_entry)
            if replacement is None:
                continue
            field_name = field_entry.get("field_name")
            if log is not None:
                log.write(
                    f"[ok] step adapters: {action}.{field_name} was '{field_entry.get('transform')}' "
                    f"but its name describes no such value — replaced with DIRECT"
                )
            field_entry["transform"] = replacement
    return adapters


# Which transform claims a kind of value, and the hints its field name must carry.
_TRANSFORM_HINTS = (
    ("DECIMAL_TO_CENTS", checks_adapters.MONEY_FIELD_HINTS),
    ("CSV_LIST", checks_adapters.CSV_FIELD_HINTS),
    ("ISO_DATE", checks_adapters.DATE_FIELD_HINTS),
)


def _fitter_transform(field_entry):
    """`DIRECT` when the field's transform contradicts its name, else None."""
    transform = field_entry.get("transform")
    field_name = field_entry.get("field_name")
    if not isinstance(field_name, str):
        return None
    lowered = field_name.strip().lower()
    for claimed, hints in _TRANSFORM_HINTS:
        if transform == claimed and not checks_adapters._mentions(lowered, hints):
            return "DIRECT"
    return None


# --- a required flag the requirements pass and the leaf does not declare ----

OPTION_TYPES_BY_MODEL = {
    "int": "int",
    "string": "str",
    "text": "str",
    "boolean": "bool",
    "float": "float",
    "decimal": "float",
    "datetime": "str",
    "date": "str",
}


def repair_missing_surface(components, requirements, models, log):
    """Ensure every attributable command line exists on the surface.

    The model omits whole commands (`member` with add/history/list) that no
    retry recovers; the lines themselves are parseable without it, so the
    structure is built here and only judgment stays modeled. For each
    attributed line the command and subcommand are created when absent
    (requirements spelling, empty options), then `repair_missing_flags`
    fills the flags it can type — one function, one pass, no divergence.
    Never deletes or restructures model content: a bare line against a
    nested command (`borrow` filed with subcommands) is left for the probe,
    as is anything the lines never resolve to. Idempotent: a healed surface
    comes back unchanged and unlogged.
    """
    from kernel.extraction import command_lines

    if not isinstance(components, dict) or not requirements:
        return repair_missing_flags(components, requirements, models, log)
    facade = components.get("facade")
    if not isinstance(facade, dict):
        return components
    invocation = facade.get("invocation")
    if not isinstance(invocation, dict):
        return components
    entities = {m.get("name") for m in (models or [])
                if isinstance(m, dict) and m.get("name")}
    spans = command_lines.extract_command_lines(requirements)
    attributed = command_lines.attribute_lines(spans, entities)
    if len(attributed) != len(spans) and log is not None:
        log.write(
            f"[!] step components: {len(spans) - len(attributed)} command line(s) "
            f"need judgment, left to the model"
        )
    for command, sub, _flags in attributed:
        entry = _ensure_command(invocation, command, log)
        if entry is None:
            continue
        if sub is not None:
            _ensure_subcommand(entry, command, sub, log)
    return repair_missing_flags(components, requirements, models, log)


def _ensure_command(invocation, command, log):
    """The named command entry, created with empty options when absent."""
    commands = invocation.get("commands")
    if not isinstance(commands, list):
        return None
    for entry in commands:
        if isinstance(entry, dict) and normalize(entry.get("name") or "") == normalize(command):
            return entry
    entry = {"name": command, "options": [], "subcommands": []}
    commands.append(entry)
    if log is not None:
        log.write(f"[ok] step components: added command '{command}' the requirements name")
    return entry


def _ensure_subcommand(entry, command, sub, log):
    """The named subcommand entry, created with empty options when absent."""
    subcommands = entry.get("subcommands")
    if not isinstance(subcommands, list):
        return
    for item in subcommands:
        if isinstance(item, dict) and normalize(item.get("name") or "") == normalize(sub):
            return
    subcommands.append({"name": sub, "options": []})
    if log is not None:
        log.write(f"[ok] step components: added '{command} {sub}' the requirements name")


def repair_missing_flags(components, requirements, models, log):
    """Add a requirements flag the owning leaf does not declare.

    Inventory's `product add` carried only `-help`/`-version` while the
    requirements pass `--sku --name --category --price`: the verb check passes
    and the path is still stranded. Both halves of the addition are grounded
    elsewhere — the flag name in the requirements' own command line, the
    option type in the data model field it uniquely binds to — so nothing is
    invented: a flag with no unique model field, an unmappable type, or a
    missing leaf is left for the retry and the probe, and every addition is
    logged.

    An optional (bracketed) flag is added too when its type is grounded:
    either it binds a unique model field (`[--stock]` to `Product.stock_qty`)
    or its name is a boolean selector (`[--available-only]`, `[--low-only]`).
    The old rule skipped every optional flag, which left inventory's
    `stock_qty` adapter field with no CLI flag — a run that parsed and could
    never complete. An optional flag with neither grounding (`[--icon]`) is
    still left for the retry and the probe.
    """
    if not isinstance(components, dict) or not requirements:
        return components
    facade = components.get("facade")
    if not isinstance(facade, dict):
        return components
    invocation = facade.get("invocation")
    if not isinstance(invocation, dict):
        return components
    commands = surface_checks._commands_by_name(invocation)
    if not commands:
        return components
    program = surface_checks._program_name(requirements)
    fields = _model_fields(models)
    if not fields:
        return components
    seen = set()
    for span in re.findall(r"`([^`]*)`", requirements):
        target = surface_checks._resolve_span(span, program, commands)
        if target is None:
            continue
        command, sub = target
        leaf = _find_leaf(invocation, command, sub)
        if leaf is None:
            continue
        for flag, bracketed in surface_checks._flags_in(span):
            if (command, sub, flag) in seen:
                continue
            seen.add((command, sub, flag))
            if _leaf_has_flag(leaf, flag):
                continue
            if _collides_with_subcommand(leaf, flag):
                # The leaf already has this word as a subcommand (`borrow`
                # carries `member_id` while the requirements pass
                # `--member-id`): adding the flag would make one word both a
                # flag and a command, a defect of its own. Yield to the model
                # text — the probe reports the unbacked subcommand instead.
                if log is not None:
                    log.write(
                        f"[ok] step components: '--{flag}' matches subcommand "
                        f"'{flag}' of {command} {sub or ''} — flag not added".rstrip()
                    )
                continue
            match = _typed_model_field(fields, flag)
            if match is None and bracketed and _boolean_flag(flag):
                label, option_type = "boolean flag name", "bool"
            elif match is not None:
                label, option_type = match
            else:
                continue
            leaf.setdefault("options", []).append({
                "name": f"--{flag}",
                "short": None,
                "type": option_type,
                "required": not bracketed,
                "default": None,
            })
            if log is not None:
                qualifier = "optional " if bracketed else ""
                log.write(
                    f"[ok] step components: {command} {sub or ''} lacked "
                    f"{qualifier}'--{flag}' the requirements pass — added as "
                    f"{option_type} (typed from {label})".rstrip()
                )
    return components


def _model_fields(models):
    """`[(model, field, type)]` for every declared model field."""
    found = []
    if not isinstance(models, list):
        return found
    for model in models:
        if not isinstance(model, dict) or not model.get("name"):
            continue
        for field in model.get("fields") or []:
            if isinstance(field, dict) and field.get("name"):
                found.append((model["name"], field["name"], field.get("type")))
    return found


def _find_leaf(invocation, command, sub):
    """The command or subcommand dict owning a leaf, or None."""
    for entry in invocation.get("commands") or []:
        if not isinstance(entry, dict) or entry.get("name") != command:
            continue
        if sub is None:
            return entry
        for item in entry.get("subcommands") or []:
            if isinstance(item, dict) and item.get("name") == sub:
                return item
    return None


def _collides_with_subcommand(leaf, flag):
    """True when the flag normalizes to an existing subcommand name."""
    wanted = normalize(flag or "")
    return any(isinstance(sub, dict) and normalize(sub.get("name")) == wanted
               for sub in leaf.get("subcommands") or [])


def _leaf_has_flag(leaf, flag):
    """True when any declared option already supplies the flag (aliases count)."""
    dests = [dest for dest in (option_dest(o) for o in leaf.get("options") or []) if dest]
    return bind_field(dests, flag) is not None


def _typed_model_field(fields, flag):
    """`(label, option_type)` for a flag, or None when ungrounded.

    The flag must bind at least one model field, and every binding must agree
    on the option type (`--name` matches `Category.name` and `Product.name`,
    both strings). A flag matching nothing, or fields of different types, is
    left for the retry and the probe — typing it would be invention.
    """
    matched = [(model, name) for model, name, _ in fields
               if bind_field([flag], name) == flag]
    if not matched:
        return None
    typed = {OPTION_TYPES_BY_MODEL.get(_field_type(fields, model, name))
             for model, name in matched}
    typed.discard(None)
    if len(typed) != 1:
        return None
    [option_type] = typed
    if len(matched) == 1:
        label = f"{matched[0][0]}.{matched[0][1]}"
    else:
        label = f"{len(matched)} models agreeing on {option_type}"
    return label, option_type


def _field_type(fields, model, name):
    for candidate_model, candidate_name, candidate_type in fields:
        if candidate_model == model and candidate_name == name:
            return (candidate_type or "").strip().lower()
    return ""


# Words in a flag name that make it a boolean selector rather than a value.
# This is only used for *optional* flags with no model field to type them;
# an optional value flag (`[--author]`) has no such word and stays with the
# retry/probe. The list is deliberately small and semantic, not a model of
# the prompt: `only`, `all`, `active`, `available`, `include`, `force`,
# `quiet`, `verbose`, `dry` describe switches, not data.
_BOOLEAN_FLAG_TOKENS = frozenset({
    "only", "all", "active", "available", "include", "force", "quiet",
    "verbose", "dry", "no",
})


def _boolean_flag(flag):
    """True when a flag's own name says it is a switch, not a value."""
    tokens = [token for token in re.split(r"[-_]+", str(flag or "").lower())
              if token]
    return any(token in _BOOLEAN_FLAG_TOKENS for token in tokens)


# --- a required adapter field the bound leaf does not expose -----------------


def repair_missing_adapter_flags(components, adapters, services, models, log):
    """Add an optional CLI flag for every required adapter field it lacks.

    The surface step and the adapter step are generated independently. An
    adapter can require a value the surface never declares (`stock_qty` with
    only `--sku --name --category --price`, or `customer_id` on a search
    leaf), and then the command parses and can never invoke its method. The
    field name and the method's parameter type are already documented; this
    repair exposes them as an optional flag on every leaf that binds the
    action. It adds no value the documents do not already require: the
    adapter names the field, the method names its type.
    """
    if not isinstance(components, dict) or not isinstance(adapters, list):
        return components
    facade = components.get("facade")
    if not isinstance(facade, dict):
        return components
    invocation = facade.get("invocation")
    if not isinstance(invocation, dict):
        return components
    from kernel.codegen import bind_commands
    from kernel.consistency.checks_surface import COMMAND_VERB_STEMS

    bindings, _unmapped = bind_commands(adapters, invocation, COMMAND_VERB_STEMS)
    by_name = {a.get("action_name"): a for a in adapters
               if isinstance(a, dict) and a.get("action_name")}
    index = _service_method_index(services)
    for (command, sub), bound in bindings.items():
        if bound is None:
            continue
        action_name = bound[0]
        adapter = by_name.get(action_name)
        if adapter is None:
            continue
        method = _resolve_adapter_method(adapter, index)
        if method is None:
            continue
        ptypes = {normalize(p.get("name")): p.get("type")
                  for p in method.get("params") or []
                  if isinstance(p, dict) and p.get("name")}
        leaf = _find_leaf(invocation, command, sub)
        if leaf is None:
            continue
        dests = [dest for dest in
                 (option_dest(option) for option in leaf.get("options") or [])
                 if dest]
        for field_entry in adapter.get("input_fields") or []:
            if not isinstance(field_entry, dict):
                continue
            field_name = field_entry.get("field_name")
            if not isinstance(field_name, str) or not field_name.strip():
                continue
            if not field_entry.get("required"):
                continue
            if bind_field(dests, field_name) is not None:
                continue
            option_type = _option_type(ptypes.get(normalize(field_name)))
            option = {
                "name": "--" + field_name.replace("_", "-"),
                "short": None,
                "type": option_type,
                "required": False,
                "default": None,
            }
            leaf.setdefault("options", []).append(option)
            dests.append(option_dest(option))
            if log is not None:
                log.write(
                    f"[ok] step adapters: {command} {sub or ''} lacked "
                    f"'--{field_name.replace('_', '-')}' required by "
                    f"'{action_name}' — added as {option_type}"
                )
    return components


# Boolean selectors whose name only narrows a result set; the remaining
# noun is what has to meet the filter method's parameter (`available-only`
# meets `min_available_copies`).
SELECTOR_STOPWORDS = frozenset({"only", "all", "is", "has", "with", "show"})


def repair_missing_filter_actions(components, adapters, services, models, log):
    """Wire a boolean selector to a one-parameter filter on the same service.

    A requirements line can say ``book list [--available-only]`` while the
    adapter document only contains the unfiltered ``read_all_books`` call and
    the filter method ``filter_books_by_available_copies(min_available_copies)``.
    The flag then parses and is ignored. When the selector's noun occurs in
    exactly that method's parameter, the action is grounded on both documents:
    it selects the filter, and ``BOOL_TO_ONE`` supplies the minimum count the
    selector means. A selector with no same-service parameter match (such as a
    bare ``--author`` whose method lives on another service) is left for the
    human surface review, not guessed.
    """
    if (not isinstance(components, dict) or not isinstance(adapters, list)
            or not isinstance(services, list)):
        return adapters
    facade = components.get("facade")
    invocation = (facade or {}).get("invocation") if isinstance(facade, dict) else None
    if not isinstance(invocation, dict):
        return adapters
    from kernel.codegen import bind_commands
    from kernel.consistency.checks_surface import COMMAND_VERB_STEMS

    bindings, _unmapped = bind_commands(adapters, invocation, COMMAND_VERB_STEMS)
    by_name = {a.get("action_name"): a for a in adapters
               if isinstance(a, dict) and a.get("action_name")}
    index = _service_method_index(services)
    existing_targets = {
        (normalize(a.get("target_service")), normalize(a.get("target_method")))
        for a in adapters
        if isinstance(a, dict) and a.get("action_name")
        and _adapter_fields_are_parameters(a, index)
    }
    for (command, sub), bound in sorted(bindings.items(), key=lambda item: str(item[0])):
        if bound is None:
            continue
        adapter = by_name.get(bound[0])
        if adapter is None:
            continue
        base_method = _resolve_adapter_method(adapter, index)
        if base_method is None or base_method.get("params"):
            continue
        service_name = adapter.get("target_service")
        methods = index.get(normalize(service_name), {})
        leaf = _find_leaf(invocation, command, sub)
        if leaf is None:
            continue
        dests = [dest for dest in
                 (option_dest(option) for option in leaf.get("options") or [])
                 if dest]
        for option in leaf.get("options") or []:
            if not isinstance(option, dict) or option.get("type") != "bool":
                continue
            dest = option_dest(option)
            if not dest:
                continue
            if _selector_already_consumed(adapters, dest):
                continue
            tokens = {word for word in re.findall(r"[a-z0-9]+", dest.lower())
                      if word not in SELECTOR_STOPWORDS}
            if not tokens:
                continue
            match = _filter_method_for(service_name, methods, tokens,
                                       existing_targets, base_method)
            if match is None:
                continue
            method_name, method = match
            param = method["params"][0]["name"]
            action_name = method_name
            while action_name in by_name:
                action_name += "_filter"
            action = {
                "action_name": action_name,
                "target_service": service_name,
                "target_method": method_name,
                "input_fields": [{
                    "field_name": param,
                    "flag": dest,
                    "target_param": param,
                    "transform": "BOOL_TO_ONE",
                    "lookup_entity": None,
                    "required": False,
                }],
            }
            adapters.append(action)
            by_name[action_name] = action
            existing_targets.add((normalize(service_name), normalize(method_name)))
            if log is not None:
                log.write(
                    f"[ok] step adapters: {command} {sub or ''} selector "
                    f"'--{dest.replace('_', '-')}' has no action — wired to "
                    f"{service_name}.{method_name} as BOOL_TO_ONE"
                )
            break
    return adapters


def _adapter_fields_are_parameters(adapter, index):
    """True when every field on the action names a target-method parameter."""
    method = _resolve_adapter_method(adapter, index)
    if method is None:
        return False
    params = {p.get("name") for p in method.get("params") or []
              if isinstance(p, dict) and isinstance(p.get("name"), str)}
    fields = [f for f in adapter.get("input_fields") or []
              if isinstance(f, dict) and f.get("field_name")]
    return bool(fields) and all(f["field_name"] in params for f in fields)


def _selector_already_consumed(adapters, dest):
    """True when any adapter field already binds this selector dest."""
    for adapter in adapters:
        if not isinstance(adapter, dict):
            continue
        for field in adapter.get("input_fields") or []:
            if not isinstance(field, dict):
                continue
            source = field.get("flag") or field.get("field_name")
            if isinstance(source, str) and bind_field([dest], source) == dest:
                return True
    return False


def _filter_method_for(service, methods, tokens, existing_targets, base_method):
    """The first one-parameter filter method whose parameter matches tokens."""
    prefixes = ("filter", "find", "search", "list")
    for method_name, method in sorted(methods.items()):
        if method is base_method or not isinstance(method, dict):
            continue
        if not method_name.startswith(prefixes):
            continue
        params = [p for p in method.get("params") or []
                  if isinstance(p, dict) and isinstance(p.get("name"), str)]
        if len(params) != 1:
            continue
        if (normalize(service), normalize(method.get("name"))) in existing_targets:
            continue
        param_tokens = set(re.findall(r"[a-z0-9]+", params[0]["name"].lower()))
        if param_tokens & set(tokens):
            return method.get("name"), method
    return None


def _option_type(ptype):
    """A CLI option type for a documented parameter type, defaulting to str."""
    text = str(ptype or "").strip().lower()
    text = re.sub(r"optional\[|\]|list\[|union\[|\s+", "", text)
    for spelling, option_type in (
            ("bool", "bool"), ("boolean", "bool"),
            ("int", "int"), ("integer", "int"),
            ("float", "float"), ("decimal", "float"),
            ("str", "str"), ("string", "str"), ("text", "str"),
    ):
        if text == spelling or text.startswith(spelling):
            return option_type
    return "str"


# --- an entity-targeted field spelled like the flag, not the model field -----

# Transforms that carry unit evidence: DECIMAL_TO_CENTS turns flag dollars
# into model cents, LOOKUP_ID turns a flag value into a foreign-key id. A
# field renamed under either keeps its meaning — the value was already that
# unit. DIRECT carries no unit evidence (flag `amount` in dollars into a
# cents field would silently change money), so it is never renamed.
RENAMEABLE_TRANSFORMS = frozenset({"DECIMAL_TO_CENTS", "LOOKUP_ID"})


def repair_adapter_field_names(adapters, services, models, log):
    """Rename an entity-targeted field to the model field it uniquely contains.

    The generator builds `Model(**fields)`, so a field targeting an entity
    parameter must spell a declared model field — yet adapters are written
    from the command line outward and spell flag names (`amount` for
    `amount_cents`, `category` for `category_id`). When the spelling is
    contained in exactly one model field, no sibling already holds that name,
    and the transform proves the units, the rename is grounded on all three
    sides. Anything else — DIRECT transforms, ambiguous or colliding names,
    unresolvable methods — is left for the retry and the probe.
    """
    if not isinstance(adapters, list):
        return adapters
    index = _service_method_index(services)
    model_fields = {}
    for model in models or []:
        if isinstance(model, dict) and model.get("name"):
            model_fields[normalize(model["name"])] = [
                f.get("name") for f in model.get("fields") or []
                if isinstance(f, dict) and f.get("name")
            ]
    for adapter in adapters:
        if not isinstance(adapter, dict):
            continue
        action = adapter.get("action_name")
        method = _resolve_adapter_method(adapter, index)
        if method is None:
            continue
        ptypes = {normalize(p.get("name")): p.get("type")
                  for p in method.get("params") or []
                  if isinstance(p, dict) and p.get("name")}
        for field_entry in adapter.get("input_fields") or []:
            if not isinstance(field_entry, dict):
                continue
            renamed = _rename_to_model_field(
                adapter, field_entry, ptypes, model_fields)
            if renamed is not None and log is not None:
                old, new = renamed
                log.write(
                    f"[ok] step adapters: {action}.{old} targets an entity but "
                    f"spells no model field — renamed to '{new}'"
                )
    return adapters


def _rename_to_model_field(adapter, field_entry, ptypes, model_fields):
    """The `(old, new)` spelling fix for one field, or None to leave it."""
    field_name = field_entry.get("field_name")
    target = field_entry.get("target_param")
    if not isinstance(field_name, str) or not isinstance(target, str):
        return None
    entity = _entity_of(ptypes.get(normalize(target)), model_fields)
    if entity is None:
        return None
    fields = model_fields[entity]
    if normalize(field_name) in {normalize(name) for name in fields}:
        return None
    if field_entry.get("transform") not in RENAMEABLE_TRANSFORMS:
        return None
    # Forward containment only: the flag abbreviates the model field
    # (`amount` in `amount_cents`). The reverse (`id` in `author_id`) matches
    # a different concept sharing a suffix — renaming `author_id` to `id`
    # silently repoints an author reference at the record itself — so it is
    # never a rename, however unique.
    candidates = [name for name in fields
                  if normalize(field_name) in normalize(name)]
    if len(candidates) != 1:
        return None
    if any(isinstance(other, dict) and other is not field_entry
           and normalize(other.get("field_name")) == normalize(candidates[0])
           for other in adapter.get("input_fields") or []):
        return None
    field_entry["field_name"] = candidates[0]
    return field_name, candidates[0]


def _entity_of(ptype, model_fields):
    """The normalized entity a type spelling names, or None."""
    if not isinstance(ptype, str):
        return None
    tokens = {normalize(token) for token in ptype.replace("[", " ").replace("]", " ").split()}
    for entity in model_fields:
        if entity in tokens:
            return entity
    return None
