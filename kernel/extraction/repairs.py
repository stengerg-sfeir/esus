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

import json
import re
from pathlib import Path

from kernel.consistency import checks_adapters, checks_errors, checks_models
from kernel.consistency import checks_surface as surface_checks
from kernel.consistency.methods import PLACEHOLDER_VALUES, param_names
from kernel.consistency.naming import normalize
from kernel.codegen import (
    bind_field, is_entity_type, is_mapping_type, option_dest,
    pagination_params,
)


def repair_nested_declarations(holders, log, document="document"):
    """Drop class declarations the model nested inside another holder's methods.

    A service document is a list of services and a persistence document a list
    of repositories; a method named like a sibling holder, with no parameters
    and no return type, is a declaration that landed one level too deep. The
    grammar permits it because method names are free text — library's
    `BookRepository` ended up with `AuthorRepository`, `MemberRepository`,
    `LoanRepository` and `LibraryService` as "methods", which then became
    zero-argument stubs and LLM targets of their own. A real method is never
    named after a sibling class, so dropping the entry cannot lose a callable.
    """
    if not isinstance(holders, list):
        return holders
    declared = set()
    for holder in holders:
        if not isinstance(holder, dict):
            continue
        name = holder.get("service_name") or holder.get("interface_name")
        if isinstance(name, str) and name.strip():
            declared.add(normalize(name))
    for holder in holders:
        if not isinstance(holder, dict):
            continue
        methods = holder.get("methods")
        if not isinstance(methods, list):
            continue
        owner = (holder.get("service_name")
                 or holder.get("interface_name") or "?")
        kept = []
        for method in methods:
            name = method.get("name") if isinstance(method, dict) else None
            if (isinstance(name, str) and normalize(name) in declared
                    and name.endswith(("Repository", "Service"))
                    and not method.get("params")
                    and method.get("return_type") in (None, "", "None")):
                if log is not None:
                    log.write(
                        f"[ok] step {document}: dropped nested declaration "
                        f"'{name}' from {owner}.methods")
                continue
            kept.append(method)
        holder["methods"] = kept
    return holders


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


def repair_unknown_raises(errors, services, requirements, log):
    """Make every raised error name resolvable.

    A service contract may name an error the registry does not declare. That
    is a hard generator blocker, not a review decision. Two generic outcomes
    are safe:

    - a validation-shaped name (`Invalid…`) the requirements never ground is
      removed from `raises`, because the prompt does not establish that check;
    - any other raised name is registered as a small error class, preserving
      the declared failure surface.
    """
    if not isinstance(services, list):
        return errors, services
    registry = errors if isinstance(errors, list) else []
    names = {
        item.get("name") for item in registry
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    lowered = (requirements or "").lower()
    for service in services:
        if not isinstance(service, dict):
            continue
        service_name = service.get("service_name") or "Service"
        for method in service.get("methods") or []:
            if not isinstance(method, dict):
                continue
            method_name = method.get("name") or "method"
            raises = method.get("raises")
            if not isinstance(raises, list):
                continue
            kept = []
            for raw in raises:
                if not isinstance(raw, str) or not raw.strip():
                    kept.append(raw)
                    continue
                name = raw.rsplit(".", 1)[-1]
                if name in names:
                    kept.append(raw)
                    continue
                if _is_validation_error(name) and not _validation_word_grounded(
                        name, lowered):
                    if log is not None:
                        log.write(
                            f"[ok] step errors: dropped unregistered validation "
                            f"raise '{name}' from {service_name}.{method_name}")
                    continue
                registry.append({
                    "name": name,
                    "base": _base_for_error(name),
                    "description": (
                        f"Raised by {service_name}.{method_name} when the "
                        "requested operation is not valid."
                    ),
                })
                names.add(name)
                kept.append(raw)
                if log is not None:
                    log.write(
                        f"[ok] step errors: registered raised error '{name}' "
                        f"from {service_name}.{method_name}")
            method["raises"] = kept
    return registry, services


def _base_for_error(name):
    """A conservative Python base for a raised-but-undeclared error name."""
    lowered = name.lower()
    if "notfound" in lowered or "missing" in lowered:
        return "LookupError"
    if "permission" in lowered or "forbidden" in lowered:
        return "PermissionError"
    if "invalid" in lowered or "stock" in lowered or "price" in lowered \
            or "name" in lowered:
        return "ValueError"
    if "state" in lowered or "transition" in lowered:
        return "RuntimeError"
    return "RuntimeError"


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
        seen_targets = set()
        kept = []
        for field_entry in adapter.get("input_fields") or []:
            if not isinstance(field_entry, dict):
                kept.append(field_entry)
                continue
            field_name = field_entry.get("field_name")
            target_param = field_entry.get("target_param")
            if not isinstance(field_name, str) or not isinstance(target_param, str):
                kept.append(field_entry)
                continue
            wanted_field = normalize(field_name)
            wanted_target = normalize(target_param)
            if wanted_target not in declared:
                if wanted_field in declared:
                    honest = declared[wanted_field]
                    if log is not None:
                        log.write(
                            f"[ok] step adapters: {action}.{field_name} targets "
                            f"undeclared '{target_param}' while the method "
                            f"declares '{honest}' — redirected"
                        )
                    field_entry["target_param"] = honest
                    wanted_target = normalize(honest)
                else:
                    if log is not None:
                        log.write(
                            f"[ok] step adapters: {action}.{field_name} targets "
                            f"'{target_param}', which the method does not "
                            f"declare — dropped"
                        )
                    continue
            if wanted_field in declared and wanted_field != wanted_target:
                honest = declared[wanted_field]
                if log is not None:
                    log.write(
                        f"[ok] step adapters: {action}.{field_name} went to "
                        f"'{target_param}' while the method declares '{honest}' — "
                        f"redirected to '{honest}'"
                    )
                field_entry["target_param"] = honest
                wanted_target = normalize(honest)
            # A scalar parameter takes one value. A second field aimed at it is
            # a duplicate binding (library sent both isbn and author_id to
            # `isbn`); aggregate parameters such as `data` intentionally collect
            # several fields, so they are exempt.
            ptype = _param_type(method, field_entry.get("target_param"))
            if (ptype and _is_scalar_type(ptype)
                    and wanted_target in seen_targets
                    and wanted_field != wanted_target):
                if log is not None:
                    log.write(
                        f"[ok] step adapters: {action}.{field_name} duplicates "
                        f"the scalar parameter '{field_entry.get('target_param')}' "
                        f"already filled — dropped"
                    )
                continue
            seen_targets.add(wanted_target)
            kept.append(field_entry)
        adapter["input_fields"] = kept
    return adapters


def _is_scalar_type(ptype):
    """True for a parameter type that holds one value, not a record/list."""
    text = str(ptype or "").strip().lower()
    if any(token in text for token in ("list", "dict", "set", "tuple")):
        return False
    return any(token in text for token in (
        "int", "str", "bool", "float", "decimal", "date", "time", "object",
        "any", "string", "text", "integer", "number"))


def _service_method_index(services):
    """Map (normalized service, normalized method) to the method object."""
    index = {}
    if not isinstance(services, list):
        return index
    for service in services:
        if not isinstance(service, dict):
            continue
        service_name = service.get("service_name") or service.get("interface_name")
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


def repair_misread_flat_commands(components, log):
    """Fix a top-level command misread as nested: `borrow member_id` with flag `--book-id`
    should be flat `borrow` with flags `--member-id` `--book-id`.

    The model misreads `<program> <verb> --flag1 --flag2` as command `<verb>`
    with subcommand `<flag1>` carrying `<flag2>`. This repair detects a command
    with exactly one subcommand whose name looks like a flag (ends with `_id`
    or is a known flag name), has no subcommands of its own, and whose options
    are the flags that belong on the parent. It promotes the subcommand's
    options to the parent, renames the first flag from the subcommand name,
    and drops the subcommand.

    Also handles the case where the parent already has some data options
    (e.g., `borrow` has `--book-id` on both parent and subcommand) — the
    missing flag from the subcommand name is added, duplicates are removed,
    and the subcommand is dropped.
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

    def flag_from_subcommand_name(name):
        """Convert a misread subcommand name to the flag it represents."""
        if not isinstance(name, str):
            return None
        n = name.strip().lower()
        # member_id → --member-id, loan_id → --loan-id, book_id → --book-id
        # member_history → --member-id (history is the verb, member is the entity)
        if n == "member_history":
            return "--member-id"
        if n.endswith("_id"):
            return f"--{n[:-3]}-id"
        if n.endswith("_date"):
            return f"--{n[:-5]}-date"
        return None

    for command in commands:
        if not isinstance(command, dict):
            continue
        subs = command.get("subcommands")
        if not isinstance(subs, list) or len(subs) != 1:
            continue
        sub = subs[0]
        if not isinstance(sub, dict):
            continue
        sub_name = sub.get("name")
        flag_from_sub = flag_from_subcommand_name(sub_name)
        if flag_from_sub is None:
            continue
        parent_opts = command.get("options") or []
        sub_opts = sub.get("options") or []
        if not sub_opts:
            continue
        # Collect existing parent data option names (excluding globals)
        parent_data_names = {o.get("name") for o in parent_opts
                             if isinstance(o, dict) and o.get("name")
                             and o.get("name") not in ("--help", "--version", "-h", "-v")}
        # Build the corrected options for the parent
        promoted = []
        # First flag comes from the subcommand name (if not already present)
        if flag_from_sub not in parent_data_names:
            promoted.append({
                "name": flag_from_sub,
                "short": None,
                "type": "int",  # IDs are integers
                "required": True,
                "default": None
            })
        # Remaining flags come from the subcommand's options
        for opt in sub_opts:
            if not isinstance(opt, dict):
                continue
            opt_name = opt.get("name")
            if opt_name and opt_name.startswith("--"):
                # Avoid duplicating flags already on parent or from subcommand name
                if opt_name not in parent_data_names and opt_name != flag_from_sub:
                    promoted.append(opt)
        if not promoted:
            continue  # Nothing to add
        if log is not None:
            log.write(
                f"[ok] step components: fixed misread flat command '{command.get('name')}' "
                f"(had subcommand '{sub_name}') — promoted {len(promoted)} flag(s) to parent, "
                f"dropped subcommand"
            )
        command["options"] = parent_opts + promoted
        command["subcommands"] = []
    return components


def repair_primary_key_shapes(models, log):
    """Normalize a placeholder/non-integer primary key to the store's `id`.

    `primary_key` is a shape word, not a model field name; the GUI prompt says
    "unique identifier" and the extractor wrote a string field literally named
    `primary_key`.  The generated schema then made it a TEXT primary key and
    the store's auto-increment insert looked up an integer rowid, so every
    create failed with KeyError.  The store only supports an integer
    auto-incremented surrogate key; when the key field is placeholder-named or
    non-integer, rename it to `id` and retarget every foreign key that named
    the placeholder.  Field names are data, never inferred from prose.
    """
    if not isinstance(models, list):
        return models
    placeholders = {"primarykey", "pk", "identifier", "key"}
    renames = []
    for model in models:
        if not isinstance(model, dict):
            continue
        fields = [field for field in model.get("fields") or []
                  if isinstance(field, dict) and field.get("name")]
        pks = [field for field in fields if field.get("primary_key")]
        if not pks:
            # The prompt's "unique identifier" is the surrogate key the store
            # already supplies; without one, every model create has no key.
            if not any(normalize(field["name"]) == "id" for field in fields):
                fields.insert(0, {"name": "id", "type": "int",
                                  "primary_key": True, "nullable": False,
                                  "unique": True, "foreign_key": None,
                                  "status": "explicit"})
                model["fields"] = fields
                if log is not None:
                    log.write(f"[ok] step data_models: {model.get('name')} had "
                              "no primary key — added integer id")
            continue
        for field in pks:
            declared = str(field.get("type") or "").strip().lower()
            if normalize(field["name"]) in placeholders \
                    or declared not in ("int", "integer"):
                old = field["name"]
                if normalize(old) != "id":
                    field["name"] = "id"
                    renames.append((normalize(model.get("name")), normalize(old),
                                    "id"))
                field["type"] = "int"
                field["primary_key"] = True
                field["unique"] = True
                field["nullable"] = False
                field["foreign_key"] = None
                if log is not None:
                    log.write(
                        f"[ok] step data_models: {model.get('name')}.{old} "
                        "became the integer primary key id")
    for model in models:
        if not isinstance(model, dict):
            continue
        for field in model.get("fields") or []:
            if not isinstance(field, dict):
                continue
            foreign = field.get("foreign_key")
            if not isinstance(foreign, dict):
                continue
            target = normalize(foreign.get("target_entity") or "")
            target_field = normalize(foreign.get("target_field") or "")
            for entity, old, new in renames:
                if target == entity and target_field == old:
                    foreign["target_field"] = new
    return models


def repair_foreign_key_types(models, log=None):
    """Make a foreign-key field's scalar type agree with its target key.

    A GUI extraction described the storage-location field as `string` while
    the target's new primary key is an integer.  The store compares the FK to
    the target key directly, so `'1'` never equals `1` and the assignment
    reads back as a stale string.  The target model is the authority for the
    key type; only the contradicted source field changes.
    """
    if not isinstance(models, list):
        return models
    by_name = {normalize(model.get("name")): model for model in models
               if isinstance(model, dict) and model.get("name")}
    for model in models:
        if not isinstance(model, dict):
            continue
        for field in model.get("fields") or []:
            if not isinstance(field, dict) or not field.get("name"):
                continue
            foreign = field.get("foreign_key")
            if not isinstance(foreign, dict):
                continue
            target_model = by_name.get(normalize(foreign.get("target_entity")))
            if target_model is None:
                continue
            target_field = next(
                (item for item in target_model.get("fields") or []
                 if isinstance(item, dict)
                 and normalize(item.get("name"))
                 == normalize(foreign.get("target_field") or "id")),
                None)
            if target_field is None:
                continue
            target_type = str(target_field.get("type") or "").strip().lower()
            source_type = str(field.get("type") or "").strip().lower()
            if target_type in ("int", "integer") \
                    and source_type not in ("int", "integer"):
                field["type"] = "int"
                if log is not None:
                    log.write(
                        f"[ok] step data_models: {model.get('name')}."
                        f"{field['name']} retyped to int for its "
                        f"{foreign.get('target_entity')} key")
    return models


def repair_primary_key_foreign_key_names(models, log=None):
    """Rename `<Entity> primary_key` FK fields to the conventional `<entity>_id`.

    The extraction sometimes records a relationship as `book_primary_key` or
    `member_primary_key`.  The field is a foreign key, not a second primary key;
    repositories and relation filters look for `book_id`/`member_id`. Rename
    only when the target is unambiguous and the conventional name is free.
    """
    if not isinstance(models, list):
        return models
    for model in models:
        if not isinstance(model, dict):
            continue
        fields = model.get("fields")
        if not isinstance(fields, list):
            continue
        existing = {normalize(field.get("name") or "")
                    for field in fields if isinstance(field, dict)}
        for field in fields:
            if not isinstance(field, dict):
                continue
            foreign = field.get("foreign_key")
            if not isinstance(foreign, dict):
                continue
            target = foreign.get("target_entity")
            name = field.get("name")
            if not isinstance(target, str) or not isinstance(name, str):
                continue
            wanted = f"{target.lower()}_id"
            family = {
                normalize(f"{target.lower()}_primary_key"),
                normalize(f"{target.lower()}_key"),
                normalize(f"{target.lower()}_pk"),
            }
            if normalize(name) not in family or normalize(wanted) in existing:
                continue
            field["name"] = wanted
            existing.add(normalize(wanted))
            if log is not None:
                log.write(
                    f"[ok] step data_models: renamed {model.get('name')}.{name} "
                    f"to {wanted} (foreign key to {target})")
    return models


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


def repair_period_field_types(models, requirements, log, invariants=None):
    """A `month`/`year` field the requirements call a string is not a date.

    `"2024-01"` is a period label, not a point in time: `date.fromisoformat`
    rejects it, and a generated CLI that validates the flag as an ISO date
    cannot run `budget add --month 2024-01`. The model reads the word "month"
    as a date even when the requirements write `month (str like "2024-01")`
    or an invariant says `Budget.month must be a string in the format
    'YYYY-MM'`. Only the two period names are corrected, and only when the
    document states the string form; every other date field is left alone.
    """
    if not isinstance(models, list):
        return models
    text = requirements or ""
    invariants_text = " ".join(
        item.get("text") or "" for item in (invariants or [])
        if isinstance(item, dict))
    fixed = 0
    for model in models:
        if not isinstance(model, dict):
            continue
        entity = model.get("name") or ""
        for field in model.get("fields") or []:
            if not isinstance(field, dict):
                continue
            name = field.get("name")
            if not isinstance(name, str) or normalize(name) not in ("month", "year"):
                continue
            declared = str(field.get("type") or "").strip().lower()
            if declared not in ("date", "datetime", "timestamp"):
                continue
            if not _period_is_declared_text(name, entity, text, invariants_text):
                continue
            field["type"] = "string"
            fixed += 1
            if log is not None:
                log.write(
                    f"[ok] step data_models: {entity}.{name} is a period label "
                    f"declared as text — type date changed to string")
    return models


def _period_is_declared_text(name, entity, requirements, invariants):
    """Whether the documents spell this period field as text or `YYYY-MM`."""
    patterns = (
        r"\b" + re.escape(name) + r"\s*\(([^)]*)\)",
        r"\b" + re.escape(entity) + r"\." + re.escape(name) + r"\b([^\n.;]*)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, requirements, re.IGNORECASE):
            detail = match.group(1).lower()
            if re.search(r"\bstr(?:ing)?\b", detail) or "yyyy-mm" in detail:
                return True
    wanted = normalize(entity)
    for match in re.finditer(
            r"\b" + re.escape(entity) + r"\s*\.\s*" + re.escape(name)
            + r"\b([^\n;]*)", invariants, re.IGNORECASE):
        detail = match.group(1).lower()
        if re.search(r"\bstr(?:ing)?\b", detail) or "yyyy-mm" in detail:
            return True
    for sentence in re.split(r"[.;\n]", invariants):
        if wanted and wanted not in normalize(sentence):
            continue
        if normalize(name) not in normalize(sentence):
            continue
        if re.search(r"\bstr(?:ing)?\b", sentence, re.IGNORECASE) \
                or "yyyy-mm" in sentence.lower():
            return True
    return False


def repair_primary_key_foreign_keys(models, log):
    """Move a foreign key attached to a primary key into its own FK field.

    A surrogate primary key (`id`) identifies the entity itself; attaching a
    foreign key to it (e.g. `Book.id -> Author.id`) conflates the entity's key
    with a relationship. The foreign key belongs on its own column (`author_id`),
    leaving `id` as an independent auto-increment key.
    """
    if not isinstance(models, list):
        return models
    for model in models:
        if not isinstance(model, dict):
            continue
        entity = model.get("name") or ""
        fields = model.get("fields")
        if not isinstance(fields, list):
            continue
        new_fields = []
        for field in fields:
            if not isinstance(field, dict):
                continue
            fk = field.get("foreign_key")
            if field.get("primary_key") and isinstance(fk, dict):
                target_entity = fk.get("target_entity")
                if target_entity and normalize(target_entity) != normalize(entity):
                    field["foreign_key"] = None
                    fk_col = f"{target_entity.lower()}_id"
                    if not any(normalize(f.get("name")) == normalize(fk_col)
                               for f in fields if isinstance(f, dict)):
                        new_fields.append({
                            "name": fk_col,
                            "type": "int",
                            "primary_key": False,
                            "nullable": False,
                            "unique": False,
                            "foreign_key": {
                                "target_entity": target_entity,
                                "target_field": fk.get("target_field") or "id",
                                "relationship": "many_to_one",
                            },
                            "status": "explicit",
                        })
                        if log is not None:
                            log.write(
                                f"[ok] step data_models: {entity}.{field.get('name')} was a primary "
                                f"key carrying an FK to {target_entity} — moved to {entity}.{fk_col}"
                            )
        fields.extend(new_fields)
    return models


def repair_missing_relation_filters(models, repositories, log=None):
    """Add the FK a repository list filter needs to read its entity.

    A repository method such as `read_all_for_invoice(invoice_id)` filters the
    entity by a related entity, but the model may omit that FK column
    (`InvoiceLine` without `invoice_id`). The method and the related model are
    the evidence: add the missing column with the related model's primary key
    as its target. A field already present is left alone for the checker.
    """
    if not isinstance(models, list) or not isinstance(repositories, list):
        return models
    model_by_name = {normalize(model.get("name")): model
                     for model in models
                     if isinstance(model, dict) and model.get("name")}
    for repository in repositories:
        if not isinstance(repository, dict):
            continue
        entity = repository.get("entity")
        model = model_by_name.get(normalize(entity))
        if model is None:
            continue
        fields = model.get("fields")
        if not isinstance(fields, list):
            continue
        existing = {normalize(field.get("name")) for field in fields
                    if isinstance(field, dict) and field.get("name")}
        for method in repository.get("methods") or []:
            if not isinstance(method, dict):
                continue
            returns = normalize(method.get("return_type") or "")
            if "list" not in returns or normalize(entity) not in returns:
                continue
            for param in method.get("params") or []:
                if not isinstance(param, dict):
                    continue
                match = re.fullmatch(r"(.+)_id", str(param.get("name") or ""),
                                     re.I)
                if not match:
                    continue
                related = model_by_name.get(normalize(match.group(1)))
                if related is None or normalize(related.get("name")) == normalize(entity):
                    continue
                fk_name = f"{match.group(1)}_id"
                if normalize(fk_name) in existing:
                    continue
                related_pk = next(
                    (field.get("name") for field in related.get("fields") or []
                     if isinstance(field, dict) and field.get("primary_key")
                     and field.get("name")), "id")
                fields.append({
                    "name": fk_name,
                    "type": "int",
                    "primary_key": False,
                    "nullable": False,
                    "unique": False,
                    "foreign_key": {
                        "target_entity": related.get("name"),
                        "target_field": related_pk,
                        "relationship": "many_to_one",
                    },
                    "status": "deduced",
                })
                existing.add(normalize(fk_name))
                if log is not None:
                    log.write(
                        f"[ok] step persistence: {method.get('name')} filters "
                        f"{entity} by {match.group(1)} ID — added "
                        f"{entity}.{fk_name} as an FK to {related.get('name')}")
    return models


# --- a create whose description names a field its parameters omit -----------------

_PORT_TYPES = {"string": "str", "text": "str", "integer": "int",
               "boolean": "bool"}


_DOMAIN_STOPWORDS = frozenset({
    "python", "application", "system", "program", "tool", "simple", "basic",
    "management", "manager", "service", "services", "data", "model",
    "the", "a", "an", "this", "that", "these", "those", "its", "their",
})


def _domain_candidates(text):
    """Singular nouns a prose prompt names as the application's subject."""
    found = []
    for pattern in (
            r"\b([a-z][a-z0-9_]*)\s+(?:application|management|manager|tracker)\b",
            r"\b(?:managing|manage|management of)\s+([a-z][a-z0-9_]*)\b",
            r"\b([a-z][a-z0-9_]*)\s+records?\b",
    ):
        for match in re.finditer(pattern, text, re.IGNORECASE):
            noun = match.group(1).lower()
            if noun.endswith("ies"):
                noun = noun[:-3] + "y"
            elif noun.endswith("s") and not noun.endswith("ss"):
                noun = noun[:-1]
            if len(noun) < 3 or noun in _DOMAIN_STOPWORDS:
                continue
            if noun not in found:
                found.append(noun)
    return found


def repair_empty_domain(models, requirements, intentions=None, log=None):
    """Build a minimal persisted entity when extraction yields no data model.

    A prose prompt such as "an order application that confirms orders" names a
    real domain record but contains no field list, so step B can legitimately
    return `[]`.  That is not a no-domain utility: the prompt asks for state and
    a notification around an order.  Infer the single subject noun from the
    application phrase and give it the smallest useful record: an integer key,
    a status when the prose describes a transition, and timestamps only when
    the requirements do.  The model is marked as inferred, so a reviewer can
    see that no field was copied from a nonexistent specification.
    """
    if models:
        return models
    text = " ".join([requirements or ""] + [
        str(item) for item in (intentions or [])])
    candidates = _domain_candidates(text)
    if not candidates:
        return models
    noun = candidates[0]
    name = noun.replace("_", " ").title().replace(" ", "")
    fields = [
        {"name": "id", "type": "int", "primary_key": True,
         "nullable": False, "unique": True, "foreign_key": None,
         "status": "inferred"},
        {"name": "status", "type": "string", "primary_key": False,
         "nullable": False, "unique": False, "foreign_key": None,
         "status": "inferred"},
    ]
    if re.search(r"\b(?:created|creation|opened)\b", text, re.IGNORECASE):
        fields.append({"name": "created_at", "type": "datetime",
                       "primary_key": False, "nullable": False, "unique": False,
                       "foreign_key": None, "status": "inferred"})
    model = {"name": name, "fields": fields,
             "status": "inferred from prose",
             "provenance": "empty_domain_repair",
             "review_required": True}
    if log is not None:
        log.write(
            f"[ok] step data_models: no model was extracted; inferred "
            f"{name} from the application phrase"
        )
    return [model]


def repair_empty_domain_components(components, models, log=None):
    """Give an inferred persisted entity the standard CRUD service set."""
    if not isinstance(components, dict) or not isinstance(models, list):
        return components
    if not any(isinstance(model, dict)
               and model.get("status") == "inferred from prose"
               for model in models):
        return components
    persistence = components.get("persistence")
    if not isinstance(persistence, dict):
        persistence = {"required": False, "technology": None}
        components["persistence"] = persistence
    if persistence.get("required") is not True:
        # The inferred record exists to hold order state; a service cannot act
        # on it if the persistence step is skipped. The prose named no database,
        # so SQLite is the generator's default store.
        persistence["required"] = True
        persistence["provenance"] = "empty_domain_repair"
        persistence["review_required"] = True
        if str(persistence.get("technology") or "").strip().lower() in (
                "none", "null", ""):
            persistence["technology"] = "sqlite"
        if log is not None:
            log.write(
                "[ok] step components: inferred entity needs a store — "
                "enabled persistence"
            )
    facade = components.get("facade")
    if isinstance(facade, dict) and facade.get("invocation") is None:
        # The prose-only components step often leaves no command graph. The
        # adapter pass can derive one, but only if the invocation object
        # exists to receive it and a concrete CLI backend parses it.
        facade["invocation"] = {"positional": [], "options": [],
                                "commands": []}
        if str(facade.get("technology") or "").strip().lower() in (
                "none", "null", ""):
            facade["technology"] = "argparse"
    elif isinstance(facade, dict) and facade.get("invocation") is not None \
            and str(facade.get("technology") or "").strip().lower() in (
                "none", "null", ""):
        facade["technology"] = "argparse"
    if components.get("crud_services"):
        return components
    added = []
    for model in models:
        if not isinstance(model, dict) or not isinstance(model.get("name"), str):
            continue
        components.setdefault("crud_services", []).append({
            "entity": model["name"],
            "operations": ["create", "read_one", "read_all", "update"],
            "provenance": "empty_domain_repair",
            "review_required": True,
        })
        added.append(model["name"])
    if added and log is not None:
        log.write(
            f"[ok] step components: inferred CRUD services for "
            f"{', '.join(added)}"
        )
    return components


def _split_type_arguments(text):
    """Split generic arguments at top-level commas."""
    parts = []
    depth = 0
    current = []
    for char in text:
        if char in "<[(":
            depth += 1
        elif char in ">])":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        parts.append("".join(current).strip())
    return parts


def _python_type(text, entity_names):
    """Turn Java-shaped `List<T>`/`Map<K,V>` spellings into Python types."""
    if not isinstance(text, str):
        return text
    value = text.strip()
    match = re.match(r"^([A-Za-z_]\w*)\s*<(.+)>$", value)
    if match:
        base = match.group(1).lower()
        args = [_python_type(part, entity_names)
                for part in _split_type_arguments(match.group(2))]
        if base in ("list", "arraylist", "collection"):
            return "list[" + ", ".join(args) + "]"
        if base == "set":
            return "set[" + ", ".join(args) + "]"
        if base in ("map", "hashmap", "dictionary", "dict"):
            return "dict[" + ", ".join(args) + "]"
        if base == "optional":
            return "Optional[" + ", ".join(args) + "]"
        return f"{match.group(1)}[" + ", ".join(args) + "]"
    key = normalize(value)
    if key in entity_names:
        return "models." + entity_names[key]
    return {"string": "str", "integer": "int", "boolean": "bool",
            "double": "float"}.get(value.lower(), value)


def repair_generic_type_spellings(services, models, log=None):
    """Normalize method annotations emitted from Java-shaped type prose.

    The model occasionally writes `List<Entity>` or `Map<string, int>` into a
    contract. Those are valid in the source language but syntax errors in
    Python; the same names are already Python types (`list`, `dict`) and model
    classes are qualified as `models.<Entity>`.
    """
    if isinstance(services, dict):
        holders = services.get("repositories") or services.get("service_contracts") or []
    elif isinstance(services, list):
        holders = services
    else:
        return services
    entity_names = {
        normalize(model.get("name")): model.get("name")
        for model in models or []
        if isinstance(model, dict) and isinstance(model.get("name"), str)
    }
    changed = 0
    for service in holders:
        if not isinstance(service, dict):
            continue
        for method in service.get("methods") or []:
            if not isinstance(method, dict):
                continue
            original = method.get("return_type")
            method["return_type"] = _python_type(original, entity_names)
            if method["return_type"] != original:
                changed += 1
            for param in method.get("params") or []:
                if not isinstance(param, dict):
                    continue
                before = param.get("type")
                param["type"] = _python_type(before, entity_names)
                if param["type"] != before:
                    changed += 1
    if changed and log is not None:
        log.write(
            f"[ok] step contracts: normalized {changed} generic type "
            "spelling(s) to Python annotations"
        )
    return services


def repair_persistence_consistency(components, log=None):
    """Normalize the one persistence contradiction we can settle without a model.

    A component block that says persistence is required while its technology is
    `none` describes no store at all. The prompt may legitimately ask for an
    in-memory application, so the safe interpretation is "no persistence
    required", not inventing a persistence port. Technology `none` is the
    explicit signal; a non-empty technology is left untouched.
    """
    if not isinstance(components, dict):
        return components
    persistence = components.get("persistence")
    if not isinstance(persistence, dict):
        return components
    technology = str(persistence.get("technology") or "").strip().lower()
    if persistence.get("required") is True and technology in ("none", "null", ""):
        persistence["required"] = False
        if log is not None:
            log.write(
                "[ok] step components: persistence required with technology "
                f"'{technology or 'empty'}' — marked not required")
    return components


def repair_create_missing_fields(ports, models, log):
    """Add the required field a create describes but does not take.

    `LoanRepository.create` described itself as taking `due_date` and
    `status` and listed neither as a parameter; the table declares both
    NOT NULL, so every create failed at the store. The method's own
    description is the evidence: a required, non-key model field it names
    is added as a parameter, typed from the model. A field the description
    does not name is left alone — nothing is invented, and the probe
    reports any required field no create can still reach.
    """
    repositories = ports.get("repositories") if isinstance(ports, dict) else None
    if not isinstance(repositories, list) or not isinstance(models, list):
        return ports
    for repository in repositories:
        if not isinstance(repository, dict):
            continue
        model = next((m for m in models if isinstance(m, dict)
                      and m.get("name") == repository.get("entity")), None)
        if model is None:
            continue
        for method in repository.get("methods") or []:
            if not isinstance(method, dict) or method.get("name") != "create":
                continue
            params = method.get("params")
            if not isinstance(params, list):
                continue
            if any(is_entity_type(p.get("type"), [m.get("name") for m in models
                                                  if isinstance(m, dict)])
                   for p in params if isinstance(p, dict)):
                continue
            taken = {normalize(p.get("name")) for p in params
                     if isinstance(p, dict)}
            description = str(method.get("description") or "").lower()
            for field in model.get("fields") or []:
                if not isinstance(field, dict) or not field.get("name"):
                    continue
                name = field["name"]
                if (field.get("primary_key") or field.get("nullable")
                        or normalize(name) in taken):
                    continue
                spelled = "(?:" + "|".join(
                    re.escape(form) for form in (name.lower(),
                                                 name.lower().replace("_", " "))
                ) + ")"
                if not re.search(r"\b" + spelled + r"\b", description):
                    continue
                declared = str(field.get("type") or "").strip()
                params.append({
                    "name": name,
                    "type": _PORT_TYPES.get(declared.lower(), declared),
                    "status": _field_status(field)})
                taken.add(normalize(name))
                if log is not None:
                    log.write(
                        f"[ok] step persistence: "
                        f"{repository.get('interface_name') or repository.get('entity')}"
                        f".create describes '{name}' but takes no such "
                        f"parameter — added as {params[-1]['type']}")
    return ports


# --- a transform that does not fit the field's name -------------------------------

def _is_mapping_type(type_name):
    """A request/DTO-shaped parameter already carries the model fields."""
    if not isinstance(type_name, str):
        return False
    normalized = normalize(type_name)
    return normalized.endswith(("data", "request", "input", "dto", "payload"))


def _field_status(field):
    """The provenance to carry when a model field is propagated."""
    status = field.get("status") if isinstance(field, dict) else None
    return status if isinstance(status, str) and status else "explicit"


def repair_required_create_fields(ports, models, log=None):
    """Add every required model field a plain create method cannot receive.

    `repair_create_missing_fields` adds only fields the description names.  A
    repository create with no entity/mapping parameter still cannot insert a
    NOT NULL field that is absent from its signature; this pass adds those
    fields mechanically from the model, which is the same authority the CREATE
    emitter already uses.  Entity/mapping-style creates are left alone.
    """
    repositories = ports.get("repositories") if isinstance(ports, dict) else None
    if not isinstance(repositories, list) or not isinstance(models, list):
        return ports
    model_names = [m.get("name") for m in models if isinstance(m, dict)]
    for repository in repositories:
        if not isinstance(repository, dict):
            continue
        model = next((m for m in models if isinstance(m, dict)
                      and m.get("name") == repository.get("entity")), None)
        if model is None:
            continue
        for method in repository.get("methods") or []:
            if not isinstance(method, dict) or method.get("name") != "create":
                continue
            params = method.get("params")
            if not isinstance(params, list):
                continue
            if any(is_entity_type(p.get("type"), model_names)
                   or _is_mapping_type(p.get("type"))
                   for p in params if isinstance(p, dict)):
                continue
            taken = {normalize(p.get("name")) for p in params
                     if isinstance(p, dict)}
            for field in model.get("fields") or []:
                if not isinstance(field, dict) or not field.get("name"):
                    continue
                name = field["name"]
                if (field.get("primary_key") or field.get("nullable")
                        or normalize(name) in taken):
                    continue
                declared = str(field.get("type") or "").strip()
                params.append({
                    "name": name,
                    "type": _PORT_TYPES.get(declared.lower(), declared),
                    "status": _field_status(field)})
                taken.add(normalize(name))
                if log is not None:
                    log.write(
                        f"[ok] step persistence: "
                        f"{repository.get('interface_name') or repository.get('entity')}"
                        f".create cannot receive required '{name}' — added as "
                        f"{params[-1]['type']}")
    return ports


def repair_mapping_create_params(services, models, log=None):
    """Replace a create/update DTO parameter with the model fields it carries.

    A contract can describe a create as `create_customer(customer_data: dict)`
    even when the model declares name/email/phone/address.  The generated CRUD
    body then tries to insert the dictionary as a column named `customer_data`.
    The mapping's own name identifies its model; expanding it keeps the
    documented operation while making the body and the CLI surface concrete.
    """
    if not isinstance(services, list):
        return services
    models_by_name = {normalize(m.get("name")): m for m in models or []
                      if isinstance(m, dict) and m.get("name")}
    changed = 0
    for service in services:
        if not isinstance(service, dict):
            continue
        owner = normalize(str(service.get("service_name") or ""))
        for suffix in ("repository", "service"):
            if owner.endswith(suffix):
                owner = owner[:-len(suffix)]
                break
        for method in service.get("methods") or []:
            if not isinstance(method, dict):
                continue
            params = method.get("params")
            if not isinstance(params, list):
                continue
            replacement = []
            for param in params:
                if not isinstance(param, dict):
                    replacement.append(param)
                    continue
                name = str(param.get("name") or "")
                prefix = normalize(name)
                name_hint = any(prefix.endswith(suffix) for suffix in
                                ("data", "request", "input", "dto", "payload"))
                type_text = str(param.get("type") or "").strip().lower()
                # Only an actually untyped mapping can be expanded from the
                # model. A named DTO (`OrderCreationData`) is a structured
                # aggregate whose fields need not be that entity's columns.
                if not (name_hint and type_text in (
                        "dict", "dict[str, any]", "mapping", "object")):
                    replacement.append(param)
                    continue
                for suffix in ("data", "request", "input", "dto", "payload"):
                    if prefix.endswith(suffix):
                        prefix = prefix[:-len(suffix)]
                        break
                model = models_by_name.get(prefix) or models_by_name.get(owner)
                if model is None:
                    replacement.append(param)
                    continue
                fields = [field for field in model.get("fields") or []
                          if isinstance(field, dict) and field.get("name")
                          and not field.get("primary_key")]
                if not fields:
                    replacement.append(param)
                    continue
                for field in fields:
                    declared = str(field.get("type") or "").strip()
                    replacement.append({
                        "name": field["name"],
                        "type": _PORT_TYPES.get(declared.lower(), declared),
                        "status": _field_status(field),
                    })
                changed += 1
            method["params"] = replacement
    if changed and log is not None:
        log.write(f"[ok] step contracts: expanded {changed} mapping parameter(s) "
                  "into model fields")
    return services


def repair_id_param_types(services, models, log=None):
    """A `*_id` method parameter is integer when its model key is.

    Matching the exact field name covers ordinary foreign keys.  A service
    method often names its own entity key `order_id` while the model calls the
    key `id`, and a repository key can be a composite (`OrderProduct.order_id`).
    Both cases are resolved from the model's primary key so a string id does
    not reach an integer store lookup.
    """
    if not isinstance(services, list):
        return services
    fields = {}
    models_by_name = {}
    for model in models or []:
        if not isinstance(model, dict) or not model.get("name"):
            continue
        name = normalize(model["name"])
        models_by_name[name] = model
        for field in model.get("fields") or []:
            if isinstance(field, dict) and field.get("name"):
                fields[normalize(field["name"])] = field

    def int_key(model):
        if not isinstance(model, dict):
            return False
        key = next((field for field in model.get("fields") or []
                    if isinstance(field, dict)
                    and (field.get("primary_key")
                         or normalize(field.get("name") or "") == "id")),
                   None)
        if key is None:
            key = next((field for field in model.get("fields") or []
                        if isinstance(field, dict)
                        and normalize(field.get("name") or "")
                        == normalize(str(model.get("name") or "") + "_id")),
                       None)
        return (isinstance(key, dict)
                and str(key.get("type") or "").strip().lower()
                in ("int", "integer"))

    changed = 0
    for service in services:
        if not isinstance(service, dict):
            continue
        holder = normalize(str(service.get("service_name") or ""))
        owner = holder
        for suffix in ("repository", "service"):
            if owner.endswith(suffix):
                owner = owner[:-len(suffix)]
                break
        for method in service.get("methods") or []:
            if not isinstance(method, dict):
                continue
            for param in method.get("params") or []:
                if not isinstance(param, dict):
                    continue
                name = param.get("name")
                if not isinstance(name, str) or not normalize(name).endswith("id"):
                    continue
                if str(param.get("type") or "").strip().lower() not in (
                        "str", "string", "text", "uuid"):
                    continue
                field = fields.get(normalize(name))
                if field is not None:
                    is_int = str(field.get("type") or "").strip().lower() in (
                        "int", "integer")
                else:
                    prefix = normalize(name)[:-2] if normalize(name).endswith("id") else ""
                    is_int = int_key(models_by_name.get(prefix))
                if (field is None and not is_int
                        and normalize(name) in (
                            normalize(owner) + "id", "id")):
                    # A service's own key may omit the entity spelling
                    # (`OrderService.confirm_order(order_id)` for `Order.id`),
                    # but a declared field spelling wins: `Order.order_id` is
                    # a string order number, not the integer primary key.
                    is_int = int_key(models_by_name.get(owner))
                if is_int:
                    param["type"] = "int"
                    changed += 1
    if changed and log is not None:
        log.write(f"[ok] step contracts: retyped {changed} id parameter(s) to int")
    return services


def repair_adapter_id_transforms(adapters, services, log=None):
    """A flag naming an integer/UUID key must use LOOKUP_ID, not DIRECT.

    The CLI parser hands strings to adapters; a method declared
    `update(user_id: int)` cannot match the store key if DIRECT leaves it as
    `"1"`. Only fields whose name is an id and whose target parameter is
    integer-like are changed.
    """
    if not isinstance(adapters, list):
        return adapters
    index = _service_method_index(services)
    for adapter in adapters:
        if not isinstance(adapter, dict):
            continue
        method = _resolve_adapter_method(adapter, index)
        if method is None:
            continue
        ptypes = {normalize(p.get("name")): p.get("type")
                  for p in method.get("params") or []
                  if isinstance(p, dict) and p.get("name")}
        for field in adapter.get("input_fields") or []:
            if not isinstance(field, dict) or field.get("transform") not in (
                    "DIRECT", "LOOKUP_ID"):
                continue
            name = str(field.get("field_name") or "")
            if not (normalize(name).endswith("id") or normalize(name) == "id"):
                continue
            declared = str(ptypes.get(normalize(field.get("target_param"))) or "").lower()
            if declared not in ("int", "integer", "uuid"):
                continue
            field["transform"] = "LOOKUP_ID"
            if not field.get("lookup_entity"):
                base = name[:-3] if normalize(name).endswith("id") else ""
                if not base:
                    target = str(field.get("target_param") or "")
                    base = target[:-3] if normalize(target).endswith("id") else ""
                if not base:
                    # A bare `id` names no entity. The repository/service that
                    # owns the method does: CategoryRepository -> Category.
                    holder = str(adapter.get("target_service") or "")
                    for suffix in ("Repository", "Service"):
                        if holder.endswith(suffix):
                            holder = holder[:-len(suffix)]
                            break
                    base = holder
                if base and base.lower() not in ("", "id"):
                    field["lookup_entity"] = base[:1].upper() + base[1:]
            if log is not None:
                log.write(
                    f"[ok] step adapters: {adapter.get('action_name')}.{name} "
                    f"targets an integer key — changed DIRECT to LOOKUP_ID")
    return adapters


_LOOKUP_STOPWORDS = frozenset({
    "add", "create", "delete", "remove", "update", "save", "set", "read",
    "get", "fetch", "find", "list", "one", "all", "by", "id", "service",
    "repository", "controller", "handler",
})


def _lookup_entity_candidates(adapter, method, field):
    """Names a LOOKUP_ID field could resolve to, most specific first."""
    candidates = []
    for text in (
            field.get("target_param"),
            (method or {}).get("name"),
            adapter.get("action_name"),
            adapter.get("target_service"),
    ):
        for token in re.findall(r"[A-Za-z][A-Za-z0-9]*", str(text or "")):
            if normalize(token) not in _LOOKUP_STOPWORDS:
                candidates.append(token)
    return candidates


def repair_adapter_lookup_entities(adapters, services, repositories, models,
                                   log=None):
    """Resolve a LOOKUP_ID entity that names no declared model.

    A weaker extractor can write the service name (`Inventory`) where the
    model entity (`Product`) belongs. The target parameter, method name,
    command action and owning service are all evidence of the entity; use
    them when the recorded lookup name does not resolve to a model. Leave
    truly unknown names in place for the checker to report.
    """
    if not isinstance(adapters, list):
        return adapters
    index = _service_method_index(list(services or []) + list(repositories or []))
    entities = {
        normalize(model.get("name")): model.get("name")
        for model in models or []
        if isinstance(model, dict) and model.get("name")
    }
    if not entities:
        return adapters
    for adapter in adapters:
        if not isinstance(adapter, dict):
            continue
        method = _resolve_adapter_method(adapter, index)
        for field in adapter.get("input_fields") or []:
            if not isinstance(field, dict) or field.get("transform") != "LOOKUP_ID":
                continue
            lookup = field.get("lookup_entity")
            if isinstance(lookup, str) and normalize(lookup) in entities:
                continue
            resolved = next((entities[normalize(candidate)]
                             for candidate in _lookup_entity_candidates(
                                 adapter, method, field)
                             if normalize(candidate) in entities), None)
            if resolved is None:
                continue
            field["lookup_entity"] = resolved
            if log is not None:
                log.write(
                    f"[ok] step adapters: {adapter.get('action_name')}."
                    f"{field.get('field_name')} lookup entity {lookup!r} "
                    f"resolved to {resolved}")
    return adapters


def repair_paginated_patterns(matches, services, repositories, log=None):
    """Classify a page-parameter read from its signature, not its DTO shape.

    A method returning a page wrapper (`PaginatedCustomerList`) has no entity
    in its return annotation, so the classifier can call it READ_ONE_BY_ID
    even when it takes page/page_size. The signature is decisive.
    """
    if not isinstance(matches, list):
        return matches
    index = _service_method_index(list(services or []) + list(repositories or []))
    for entry in matches:
        if not isinstance(entry, dict):
            continue
        source = entry.get("source")
        if not isinstance(source, str) or not source.startswith("contract:"):
            continue
        holder, _, method_name = source[len("contract:"):].partition(".")
        method = index.get(normalize(holder), {}).get(normalize(method_name))
        if method is None or pagination_params(method) is None:
            continue
        if entry.get("pattern_id") == "FILTER_WITH_PAGINATION":
            continue
        entry["pattern_id"] = "FILTER_WITH_PAGINATION"
        entry["decision"] = "decided"
        entry["undecided_stage"] = None
        entry["rejection"] = None
        entry["claimed_pattern_id"] = "FILTER_WITH_PAGINATION"
        entry["claimed_confidence"] = 1.0
        if log is not None:
            log.write(
                f"[ok] step patterns: {holder}.{method_name} classified as "
                "FILTER_WITH_PAGINATION from its page parameters")
    return matches


def repair_contract_write_methods(contracts, repositories, models, log=None):
    """Add a standard update method a contract names but the repository omits.

    `confirm_order` may write `OrderRepository.update` while the extraction
    omitted that operation from the Order repository. The update signature is
    still fully determined by the Order model; the contract cannot be compiled
    or checked without it.
    """
    if not isinstance(contracts, list) or not isinstance(repositories, list):
        return repositories
    by_name = {
        normalize(repo.get("interface_name") or repo.get("entity") or ""): repo
        for repo in repositories if isinstance(repo, dict)
    }
    model_by_name = {
        normalize(model.get("name") or ""): model
        for model in models or [] if isinstance(model, dict) and model.get("name")
    }
    for contract in contracts:
        if not isinstance(contract, dict):
            continue
        for effect in contract.get("effects") or []:
            if not isinstance(effect, dict):
                continue
            write = effect.get("write")
            if not isinstance(write, str) or "." not in write:
                continue
            repo_name, method_name = write.split(".", 1)
            repo = by_name.get(normalize(repo_name))
            if repo is None or normalize(method_name) != "update":
                continue
            methods = repo.setdefault("methods", [])
            if any(isinstance(method, dict)
                   and normalize(method.get("name") or "") == "update"
                   for method in methods):
                continue
            entity = repo.get("entity")
            model = model_by_name.get(normalize(entity or ""))
            if model is None:
                continue
            fields = [field for field in model.get("fields") or []
                      if isinstance(field, dict) and field.get("name")]
            primary = next((field["name"] for field in fields
                            if field.get("primary_key")), "id")
            params = [{"name": primary, "type": "int"}]
            for field in fields:
                if field["name"] == primary:
                    continue
                params.append({
                    "name": field["name"],
                    "type": {
                        "int": "int", "integer": "int", "string": "str",
                        "text": "str", "boolean": "bool", "bool": "bool",
                        "float": "float", "decimal": "int",
                        "date": "datetime.date", "datetime": "datetime.datetime",
                        "timestamp": "datetime.datetime",
                    }.get(str(field.get("type") or "").strip().lower(), "str"),
                    "status": _field_status(field),
                })
            methods.append({
                "name": "update",
                "description": f"Updates an existing {entity}.",
                "params": params,
                "return_type": entity,
                "raises": [],
                "provenance": "contract_write",
                "review_required": True,
            })
            if log is not None:
                log.write(
                    f"[ok] step contracts: added {repo_name}.update for "
                    f"{entity} named by a contract")
    return repositories


def ungrounded_methods(services, repositories, models, requirements,
                       intentions=None):
    """`[(holder, method, reason)]` for methods with no prompt/model evidence.

    Two safe signals are used: the existing grounding report (verb has no
    requirement support) and a method parameter that names a field the owning
    model does not declare. Standard CRUD wrappers and special transport
    parameters are exempt.
    """
    from kernel.extraction import grounding

    reasons = {}
    report = grounding.report(requirements or "", intentions or [], services or [])
    for item in report.get("extra_methods") or []:
        reasons[(item.get("holder"), item.get("method"))] = item.get("reason")

    special = {
        "id", "ids", "page", "pagesize", "limit", "offset", "query", "data",
        "payload", "json", "jsondata", "file", "filepath", "path", "output",
        "start", "startdate", "end", "enddate", "from", "fromdate", "to",
        "todate", "month", "year", "sort", "order", "filter",
    }
    model_by_name = {normalize(model.get("name")): model
                     for model in models or []
                     if isinstance(model, dict) and model.get("name")}

    def model_for(holder):
        base = normalize(holder or "")
        for suffix in ("repository", "service", "manager"):
            if base.endswith(suffix):
                base = base[:-len(suffix)]
                break
        return model_by_name.get(base)

    def inspect(holder, method):
        if not isinstance(method, dict) or not isinstance(method.get("name"), str):
            return
        name = method.get("name")
        key = (holder, name)
        if key in reasons:
            return
        model = model_for(holder)
        if model is None:
            return
        fields = {normalize(field.get("name"))
                  for field in model.get("fields") or []
                  if isinstance(field, dict) and field.get("name")}
        if not fields:
            return
        returns = str(method.get("return_type") or "")
        known_types = set(model_by_name) | {
            "list", "dict", "tuple", "set", "optional", "union", "any",
            "none", "str", "int", "float", "bool", "datetime", "date",
        }
        for token in re.findall(r"[A-Z][A-Za-z0-9_]*", returns):
            key_type = normalize(token)
            if key_type in known_types or key_type in normalize(requirements):
                continue
            reasons[key] = (
                f"return type {token!r} is not a declared model or prompt type")
            return
        # A `..._by_region`/`..._by_dimension` name needs that dimension in
        # either the prompt or the model. This catches parameterless methods
        # that a parameter-only check cannot see.
        for dimension in re.findall(r"_by_([a-z][a-z0-9_]*)",
                                    str(name).lower()):
            dimension = normalize(dimension)
            if dimension not in fields and dimension not in normalize(requirements):
                reasons[key] = (
                    f"grouping dimension {dimension!r} is not in the prompt "
                    f"or {model.get('name')} fields")
                return
        method_key = normalize(name)
        if method_key.startswith(("create", "read", "update", "delete")):
            return
        for param in method.get("params") or []:
            if not isinstance(param, dict) or not param.get("name"):
                continue
            raw = str(param["name"])
            key_name = normalize(raw)
            if key_name in fields or key_name in special \
                    or key_name.endswith(("id", "ids", "data", "payload",
                                          "request", "input", "dto")):
                continue
            reasons[key] = (
                f"parameter {raw!r} names no {model.get('name')} field")
            return

    for service in services or []:
        if not isinstance(service, dict):
            continue
        holder = service.get("service_name")
        for method in service.get("methods") or []:
            inspect(holder, method)
    service_high_level = {
        normalize(method.get("name"))
        for service in services or [] if isinstance(service, dict)
        for method in service.get("methods") or []
        if isinstance(method, dict)
        and normalize(method.get("name") or "").startswith(("import", "export"))
    }
    for repo in repositories or []:
        if not isinstance(repo, dict):
            continue
        holder = repo.get("interface_name") or repo.get("entity")
        for method in repo.get("methods") or []:
            inspect(holder, method)
            name = method.get("name") if isinstance(method, dict) else None
            if isinstance(name, str) and normalize(name).startswith(
                    ("import", "export")) \
                    and normalize(name) in service_high_level:
                reasons[(holder, name)] = (
                    "repository duplicates the higher-level service operation")
    return [(holder, method, reason) for (holder, method), reason in reasons.items()]


def repair_ungrounded_methods(documents, requirements, intentions=None, log=None):
    """Remove methods with no prompt/model evidence and cascade references."""
    services = documents.get("service_contracts") or []
    ports = documents.get("persistence_ports") or {}
    repositories = ports.get("repositories") if isinstance(ports, dict) else []
    models = documents.get("data_models") or []
    drops = ungrounded_methods(services, repositories, models, requirements,
                               intentions)
    if not drops:
        return []
    dropped = {(normalize(holder), normalize(method))
               for holder, method, _reason in drops}

    def keep_method(holder, method):
        return (normalize(holder or ""), normalize(method or "")) not in dropped

    kept_services = []
    for service in services:
        methods = [m for m in service.get("methods") or []
                   if isinstance(m, dict)
                   and keep_method(service.get("service_name"), m.get("name"))]
        if methods:
            service = dict(service)
            service["methods"] = methods
            kept_services.append(service)
    documents["service_contracts"] = kept_services

    if isinstance(ports, dict):
        kept_repos = []
        for repo in repositories:
            methods = [m for m in repo.get("methods") or []
                       if isinstance(m, dict)
                       and keep_method(repo.get("interface_name") or repo.get("entity"),
                                       m.get("name"))]
            if methods:
                repo = dict(repo)
                repo["methods"] = methods
                kept_repos.append(repo)
        ports = dict(ports)
        ports["repositories"] = kept_repos
        documents["persistence_ports"] = ports

    available = {
        (normalize(service.get("service_name")), normalize(m.get("name")))
        for service in kept_services for m in service.get("methods") or []
        if isinstance(m, dict)
    }
    available.update({
        (normalize(repo.get("interface_name") or repo.get("entity")),
         normalize(m.get("name")))
        for repo in (ports.get("repositories") if isinstance(ports, dict) else [])
        for m in repo.get("methods") or [] if isinstance(m, dict)
    })
    adapters = [adapter for adapter in documents.get("interaction_adapters") or []
                if isinstance(adapter, dict)
                and (normalize(adapter.get("target_service")),
                     normalize(adapter.get("target_method"))) in available]
    documents["interaction_adapters"] = adapters
    matches = []
    for match in documents.get("pattern_matches") or []:
        source = str(match.get("source") or "") if isinstance(match, dict) else ""
        source = source.removeprefix("contract:")
        holder, _, method = source.partition(".")
        if keep_method(holder, method):
            matches.append(match)
    documents["pattern_matches"] = matches
    if log is not None:
        for holder, method, reason in drops:
            log.write(f"[ok] step grounding: dropped {holder}.{method} — {reason}")
    return drops


def _transition_evidence(requirements):
    """`(entity, target) -> source states` stated by the requirements.

    A prompt can say "An order starts in pending and can become confirmed,
    shipped or cancelled." The extraction has no structured transition table,
    so the sentence is read here. A missing sentence leaves the method's
    conventional source state as the fallback.
    """
    evidence = {}
    text = requirements if isinstance(requirements, str) else ""
    for sentence in re.split(r"[.;\n]", text):
        match = re.search(
            r"\b([A-Za-z_][A-Za-z0-9_]*)\s+starts?\s+in\s+"
            r"(?:the\s+)?`?([A-Za-z_][A-Za-z0-9_]*)`?\s+(?:state\s+)?"
            r"and\s+can\s+become\s+([^.;\n]+)",
            sentence, re.IGNORECASE)
        if not match:
            continue
        entity = normalize(match.group(1))
        source = match.group(2).lower()
        targets = []
        for quoted, single, bare in re.findall(
                r"`([^`]+)`|'([^']+)'|\b([A-Za-z_][A-Za-z0-9_]*)\b",
                match.group(3)):
            word = (quoted or single or bare).strip().lower()
            if word and word not in ("or", "and", "the", "state", "states"):
                targets.append(word)
        for target in targets:
            evidence.setdefault((entity, normalize(target)), set()).add(source)
    return evidence


def repair_contracts(contracts, services, repositories, models, requirements="",
                     log=None):
    """Repair generic contract holes the model can infer from the prompt.

    Two structural mistakes recur when the contract review is answered
    automatically:

    - an effect on a cancellation/return says `decrement` even though the
      prompt says the stock or copy count is restored;
    - the contract names an entity in a precondition/effect but carries no
      binding for the `<entity>_id` parameter that reads it.

    Both are document defects, not code-generation defects. The repair is
    limited to words present in the prompt, and it only adds bindings to
    repositories whose `read_one` method exists.
    """
    if not isinstance(contracts, list):
        return contracts
    text = (requirements or "").lower()
    restore_intent = any(phrase in text for phrase in (
        "restore", "restored", "release", "released", "add back",
        "increments", "increment", "return to stock"))
    returned_intent = "returned" in text
    cancelled_intent = "cancelled" in text or "canceled" in text
    index = _service_method_index(list(services or []) + list(repositories or []))
    repos_by_entity = {}
    for repo in repositories or []:
        if not isinstance(repo, dict):
            continue
        entity = repo.get("entity")
        interface = repo.get("interface_name") or entity
        if not isinstance(entity, str) or not isinstance(interface, str):
            continue
        methods = {normalize(method.get("name"))
                   for method in repo.get("methods") or []
                   if isinstance(method, dict) and method.get("name")}
        if "readone" in methods:
            repos_by_entity.setdefault(normalize(entity), interface)
    model_names = {normalize(model.get("name")): model.get("name")
                   for model in models or []
                   if isinstance(model, dict) and model.get("name")}
    known = {(record.get("holder"), record.get("method"))
             for record in contracts if isinstance(record, dict)}
    # A state transition may have a service method and human description but
    # no contract at all (ship_order is the common case). Synthesize the
    # single, unambiguous status write from the method verb and its `<x>_id`
    # parameter; the contract compiler can then emit it mechanically.
    state_verbs = {
        "ship": ("shipped", "confirmed"),
        "confirm": ("confirmed", "pending"),
        "cancel": ("cancelled", "confirmed"),
        "return": ("returned", None),
    }
    transition_evidence = _transition_evidence(requirements)
    for service in services or []:
        if not isinstance(service, dict):
            continue
        holder = service.get("service_name") or ""
        if normalize(holder).endswith("repository"):
            continue
        for method in service.get("methods") or []:
            if not isinstance(method, dict) or not method.get("name"):
                continue
            method_name = method.get("name")
            verb = next((word for word in state_verbs
                         if normalize(method_name).startswith(word)), None)
            if verb is None or (holder, method_name) in known:
                continue
            params = [param.get("name") for param in method.get("params") or []
                      if isinstance(param, dict) and param.get("name")]
            entity = next((model_names[normalize(name[:-3])]
                           for name in params
                           if normalize(name).endswith("id")
                           and normalize(name[:-3]) in model_names), None)
            if entity is None:
                continue
            entity_param = next(name for name in params
                                if normalize(name[:-3]) == normalize(entity)
                                and normalize(name).endswith("id"))
            interface = repos_by_entity.get(normalize(entity))
            if interface is None:
                continue
            value, expected = state_verbs[verb]
            sources = transition_evidence.get(
                (normalize(entity), normalize(value)), set()).copy()
            if expected:
                sources.add(expected)
            binding_name = normalize(entity)
            error = next((item.get("name") for item in models or []
                          if isinstance(item, dict)
                          and "status" in normalize(item.get("name") or "")),
                         None) or "ValueError"
            record = {
                "holder": holder,
                "method": method_name,
                "decided_by": "auto",
                "bindings": [{
                    "name": binding_name,
                    "repository": interface,
                    "method": "read_one",
                    "args": [entity_param],
                }],
                "effects": [{
                    "target": f"{binding_name}.status",
                    "op": "set",
                    "value": f"'{value}'",
                    "write": f"{interface}.update",
                }],
            }
            if sources:
                ordered_sources = sorted(sources)
                if len(ordered_sources) == 1:
                    check = (f"{binding_name}.status == "
                             f"'{ordered_sources[0]}'")
                else:
                    check = (f"{binding_name}.status in "
                             "{" + ", ".join(repr(item) for item in ordered_sources) + "}")
                record["preconditions"] = [{
                    "check": check,
                    "raise_when": "false",
                    "error": error,
                }]
            contracts.append(record)
            known.add((holder, method_name))
            if log is not None:
                log.write(
                    f"[ok] step contracts: synthesized {holder}.{method_name} "
                    f"status {value} from its {verb} verb")
    for record in contracts:
        if not isinstance(record, dict):
            continue
        holder = record.get("holder")
        method_name = record.get("method")
        method = index.get(normalize(holder or ""), {}).get(
            normalize(method_name or ""))
        if method is None:
            continue
        params = [param.get("name") for param in method.get("params") or []
                  if isinstance(param, dict) and isinstance(param.get("name"), str)]
        bindings = record.setdefault("bindings", [])
        bound = {normalize(item.get("name")) for item in bindings
                 if isinstance(item, dict) and item.get("name")}
        referenced = []
        for effect in record.get("effects") or []:
            target = effect.get("target") if isinstance(effect, dict) else None
            if isinstance(target, str) and "." in target:
                referenced.append(target.split(".", 1)[0])
        for precondition in record.get("preconditions") or []:
            check = precondition.get("check") if isinstance(precondition, dict) else None
            if isinstance(check, str):
                match = re.fullmatch(r"([A-Za-z_]\w*)\s+exists", check.strip())
                if match:
                    referenced.append(match.group(1))
        for entity in referenced:
            key = normalize(entity)
            if key in bound:
                continue
            interface = repos_by_entity.get(key)
            if interface is None:
                continue
            param = next((name for name in params
                          if normalize(name) == normalize(entity) + "id"), None)
            if param is None:
                continue
            bindings.append({
                "name": entity,
                "repository": interface,
                "method": "read_one",
                "args": [param],
            })
            bound.add(key)
            if log is not None:
                log.write(
                    f"[ok] step contracts: {holder}.{method_name} bound "
                    f"{entity} to {interface}.read_one({param})")
        # A method parameter `<entity>_id` is itself a read even when the
        # effect only names a child (`cancel_order(order_id)` changes the
        # order's products). Bind it before the contract compiler and the
        # acceptance fixture look for the parent record.
        for param in params:
            if not param.lower().endswith("_id"):
                continue
            entity = param[:-3]
            key = normalize(entity)
            if key in bound or key not in repos_by_entity:
                continue
            bindings.append({
                "name": entity,
                "repository": repos_by_entity[key],
                "method": "read_one",
                "args": [param],
            })
            bound.add(key)
            if log is not None:
                log.write(
                    f"[ok] step contracts: {holder}.{method_name} bound "
                    f"{entity} from parameter {param}")
        normalized_method = normalize(method_name or "")
        cancelling = "cancel" in normalized_method
        returning = normalized_method.startswith("return") \
            or normalized_method.startswith("returnbook")
        if cancelling or returning:
            for effect in record.get("effects") or []:
                if not isinstance(effect, dict):
                    continue
                target = normalize(effect.get("target") or "")
                if restore_intent and ("stock" in target or "availablecopies" in target) \
                        and effect.get("op") == "decrement":
                    effect["op"] = "increment"
                    if log is not None:
                        log.write(
                            f"[ok] step contracts: {holder}.{method_name} "
                            f"restores {effect.get('target')} (increment)")
                if returning and target.endswith(("status", "state")) \
                        and effect.get("op") == "set" \
                        and str(effect.get("value")).strip("'\"").lower() in ("active", "open") \
                        and returned_intent:
                    effect["value"] = "'returned'"
                    if log is not None:
                        log.write(
                            f"[ok] step contracts: {holder}.{method_name} "
                            f"sets {effect.get('target')} to returned")
        if "confirm" in normalized_method and "invoice" in text:
            has_invoice = any(
                isinstance(create, dict)
                and "invoice" in normalize(create.get("class") or "")
                for create in record.get("creates") or [])
            if not has_invoice:
                invoice = next((model for model in models or []
                                if isinstance(model, dict)
                                and "invoice" in normalize(model.get("name") or "")),
                               None)
                repo = next((item for item in repositories or []
                             if isinstance(item, dict)
                             and "invoice" in normalize(item.get("entity") or "")
                             and any(isinstance(method, dict)
                                     and normalize(method.get("name") or "") == "create"
                                     for method in item.get("methods") or [])),
                            None)
                order_binding = next(
                    (item for item in bindings
                     if isinstance(item, dict)
                     and isinstance(item.get("args"), list)
                     and item["args"]), None)
                if invoice and repo and order_binding:
                    fields = {}
                    for field in invoice.get("fields") or []:
                        if not isinstance(field, dict) or field.get("primary_key"):
                            continue
                        name = field.get("name")
                        kind = str(field.get("type") or "").lower()
                        if "id" in normalize(name or ""):
                            fields[name] = f"param:{order_binding['args'][0]}"
                        elif kind in ("datetime", "timestamp", "date"):
                            fields[name] = "now"
                        elif kind in ("int", "integer", "float", "double",
                                      "decimal", "money"):
                            fields[name] = "0"
                        elif not field.get("nullable"):
                            fields[name] = "''"
                    if fields:
                        record["creates"] = [{
                            "class": invoice.get("name"),
                            "call": f"{repo.get('interface_name') or repo.get('entity')}.create",
                            "fields": fields,
                        }]
                        if log is not None:
                            log.write(
                                f"[ok] step contracts: {holder}.{method_name} "
                                "creates the model named by the prompt")
        if cancelling and cancelled_intent:
            has_status = any(
                isinstance(effect, dict)
                and normalize(effect.get("target") or "").endswith(("status", "state"))
                for effect in record.get("effects") or [])
            order_binding = next(
                (item for item in bindings
                 if isinstance(item, dict)
                 and normalize(item.get("name")) == "order"), None)
            if not has_status and order_binding:
                value = "'cancelled'" if "cancelled" in text else "'canceled'"
                record.setdefault("effects", []).append({
                    "target": f"{order_binding['name']}.status",
                    "op": "set",
                    "value": value,
                    "write": f"{order_binding['repository']}.update",
                })
                if log is not None:
                    log.write(
                        f"[ok] step contracts: {holder}.{method_name} "
                        f"sets {order_binding['name']}.status to {value}")
        unique = []
        seen = set()
        for effect in record.get("effects") or []:
            if not isinstance(effect, dict):
                continue
            key = (effect.get("target"), effect.get("op"),
                   effect.get("value"), effect.get("by"), effect.get("write"))
            if key in seen:
                continue
            seen.add(key)
            unique.append(effect)
        if unique:
            record["effects"] = unique
    repair_contract_write_methods(contracts, repositories, models, log)
    return contracts


def repair_adapter_mapping_fields(adapters, services, log=None):
    """Retarget per-field adapter inputs at a method's mapping parameter.

    A method such as `update_customer(customer_id, updated_data: dict)` has
    one mapping parameter. The adapter may still carry model-field names as
    its target params (`name`, `email`, ...); the CLI then passes those as
    keyword arguments and the repository rejects them. When the method has
    exactly one mapping parameter, fields whose targets are not method
    parameters belong inside that mapping.
    """
    if not isinstance(adapters, list):
        return adapters
    index = _service_method_index(services)
    for adapter in adapters:
        if not isinstance(adapter, dict):
            continue
        method = _resolve_adapter_method(adapter, index)
        if method is None:
            continue
        params = [param for param in method.get("params") or []
                  if isinstance(param, dict) and param.get("name")]
        mapping_params = [param for param in params
                          if is_mapping_type(param.get("type"))]
        if len(mapping_params) != 1:
            continue
        mapping_name = mapping_params[0].get("name")
        param_names = {normalize(param.get("name")) for param in params}
        for field in adapter.get("input_fields") or []:
            if not isinstance(field, dict):
                continue
            target = field.get("target_param")
            if not isinstance(target, str) or not target:
                continue
            if normalize(target) in param_names:
                continue
            field["target_param"] = mapping_name
            if log is not None:
                log.write(
                    f"[ok] step adapters: {adapter.get('action_name')}."
                    f"{field.get('field_name')} moved into {mapping_name}")
    return adapters


def repair_adapter_transforms(adapters, log, services=None):
    """Replace a transform whose kind contradicts the field or target type.

    A transform states how a value's representation changes; the field's name
    and the target parameter's type are the evidence of what kind of value it
    is. When they disagree — a year parsed as a date, an ISBN looked up as an
    integer id, a count converted to cents — the transform is wrong, and
    `DIRECT` is the honest replacement: copy the value unchanged. The hint sets
    and the comparison come from the checker, so the repair and
    `mismatched_transform` share one definition of "fits".
    """
    if not isinstance(adapters, list):
        return adapters
    index = _service_method_index(services)
    for adapter in adapters:
        if not isinstance(adapter, dict):
            continue
        action = adapter.get("action_name")
        method = _resolve_adapter_method(adapter, index)
        for field_entry in adapter.get("input_fields") or []:
            if not isinstance(field_entry, dict):
                continue
            if (field_entry.get("transform") == "DIRECT"
                    and field_entry.get("lookup_entity") is not None):
                # A lookup entity is the record LOOKUP_ID resolves; DIRECT
                # copies the value unchanged and has nothing to resolve.
                field_entry["lookup_entity"] = None
                if log is not None:
                    log.write(
                        f"[ok] step adapters: {action}.{field_entry.get('field_name')} "
                        f"kept a lookup entity with DIRECT — cleared")
            replacement = _fitter_transform(field_entry, method)
            if replacement is None:
                continue
            field_name = field_entry.get("field_name")
            if log is not None:
                log.write(
                    f"[ok] step adapters: {action}.{field_name} was '{field_entry.get('transform')}' "
                    f"but its name or target type describes no such value — replaced with DIRECT"
                )
            field_entry["transform"] = replacement
            if replacement == "DIRECT":
                field_entry["lookup_entity"] = None
    return adapters


# Which transform claims a kind of value, and the hints its field name must carry.
_TRANSFORM_HINTS = (
    ("DECIMAL_TO_CENTS", checks_adapters.MONEY_FIELD_HINTS),
    ("CSV_LIST", checks_adapters.CSV_FIELD_HINTS),
    ("ISO_DATE", checks_adapters.DATE_FIELD_HINTS),
)


def _fitter_transform(field_entry, method=None):
    """`DIRECT` when the transform contradicts the field or target type."""
    transform = field_entry.get("transform")
    field_name = field_entry.get("field_name")
    if not isinstance(field_name, str):
        return None
    lowered = field_name.strip().lower()
    # `2024-01` is a month label, not an ISO date. The model routinely tags a
    # `month`/`year` flag ISO_DATE because the field name carries a date hint,
    # and the generated validator then rejects the only value the prompt
    # allows (`Invalid isoformat string: '2024-01'`).
    if transform == "ISO_DATE" and normalize(field_name) in ("month", "year"):
        return "DIRECT"
    for claimed, hints in _TRANSFORM_HINTS:
        if transform == claimed and not checks_adapters._mentions(lowered, hints):
            return "DIRECT"
    ptype = _param_type(method, field_entry.get("target_param"))
    if not ptype:
        return None
    kind = str(ptype).strip().lower()
    scalar = any(token in kind for token in (
        "int", "integer", "str", "string", "text", "float", "double",
        "decimal", "money", "date", "datetime", "timestamp", "bool",
        "boolean", "object", "any"))
    if not scalar:
        # A DTO/mapping parameter carries the sibling fields; its declared
        # class name says nothing about each field's representation. A
        # boolean count still cannot feed an object parameter.
        if transform == "BOOL_TO_ONE":
            return "DIRECT"
        return None
    if transform == "ISO_DATE" and not any(
            token in kind for token in
            ("date", "time", "str", "string", "text", "object")):
        return "DIRECT"
    if transform == "CSV_LIST" and kind in ("str", "string", "text"):
        # The target method takes one string, not a list. Splitting the CLI
        # value into a list here makes a generated body call `.split()` on a
        # list; the method itself owns the string parsing.
        return "DIRECT"
    if transform == "LOOKUP_ID" and not any(
            token in kind for token in
            ("int", "integer", "float", "decimal")):
        return "DIRECT"
    if transform == "DECIMAL_TO_CENTS" and not any(
            token in kind for token in
            ("int", "integer", "float", "decimal")):
        return "DIRECT"
    if transform == "BOOL_TO_ONE" and kind in ("bool", "boolean"):
        # A presence flag onto a boolean parameter is the value itself;
        # BOOL_TO_ONE only supplies a count for an integer threshold.
        return "DIRECT"
    if transform == "ENUM_LOOKUP" and kind in ("bool", "boolean"):
        # A boolean model field is not an enum key.  The option already carries
        # a boolean value, so copying it is the only valid transform.
        return "DIRECT"
    if transform == "BOOL_TO_ONE" and kind not in (
            "int", "integer", "float", "decimal"):
        # BOOL_TO_ONE is only the count/threshold adapter.  On a scalar bool or
        # an entity parameter it is a type mismatch, not a conversion.
        return "DIRECT"
    return None


def _param_type(method, name):
    """The declared type of a method parameter, or None."""
    if not isinstance(method, dict) or not isinstance(name, str):
        return None
    wanted = normalize(name)
    for param in method.get("params") or []:
        if (isinstance(param, dict)
                and isinstance(param.get("name"), str)
                and normalize(param["name"]) == wanted):
            return param.get("type")
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


def repair_option_defaults(components, models, log=None, requirements=""):
    """Make a flag optional when the requirements or model give it a default.

    The requirements block writes ``--copies`` without brackets, but the
    prose says it defaults to one. The data model may carry that default; when
    it does not, the same sentence is the record. A split component group saw
    only its own command line and wrote the flag as required. A flag bound to
    a documented default is optional and uses it, exactly as the create
    emitter does.
    """
    if not isinstance(components, dict) or not isinstance(models, list):
        return components
    field_defaults = []
    for model in models:
        if not isinstance(model, dict):
            continue
        for field in model.get("fields") or []:
            if not isinstance(field, dict) or not field.get("name"):
                continue
            if field.get("default") is None or field.get("primary_key"):
                continue
            field_defaults.append((field["name"], field["default"]))

    def prose_default(flag):
        """`(optional, default)` the requirements sentence states for flag."""
        if not isinstance(requirements, str) or not flag:
            return False, None
        for sentence in re.split(r"(?<=[.;])\s+|\n", requirements):
            if not re.search(rf"(?<!\w){re.escape(flag)}(?!\w)", sentence):
                continue
            # Only what follows the flag can describe that flag: the member
            # sentence "membership_date defaults to today ... add --name
            # --email is sufficient" must not make --name default to today.
            tail = sentence.split(flag, 1)[1]
            optional = bool(re.search(r"\boptional\b", tail, re.I))
            match = re.search(
                r"\bdefaults?\s+to\s+([A-Za-z0-9_.-]+)", tail, re.I)
            value = match.group(1).rstrip(".,;:") if match else None
            if value is not None:
                words = {"one": "1", "two": "2", "three": "3", "zero": "0",
                         "true": "True", "false": "False"}
                value = words.get(value.lower(), value)
            if optional or value is not None:
                return True, value
        return False, None

    invocation = (components.get("facade") or {}).get("invocation") or {}
    commands = invocation.get("commands") if isinstance(invocation, dict) else None
    if not isinstance(commands, list):
        return components

    def visit(node):
        for option in node.get("options") or []:
            if not isinstance(option, dict) or not option.get("name"):
                continue
            if option.get("default") is not None:
                continue
            dest = option_dest(option)
            matches = [default for name, default in field_defaults
                       if bind_field([dest], name) is not None]
            optional, default = prose_default(option["name"])
            if len(matches) == 1:
                optional, default = True, matches[0]
            elif not optional:
                continue
            if default is None:
                continue
            option["required"] = False
            option["default"] = default
            if log is not None:
                log.write(
                    f"[ok] step components: '{option['name']}' is optional "
                    f"with default {default!r} (requirements/model default)")
        for child in node.get("subcommands") or []:
            visit(child)

    for command in commands:
        if isinstance(command, dict):
            visit(command)
    return components


def repair_flat_prose_surface(components, services, models, requirements, log=None):
    """Derive a backed CLI surface from services when prose names no command.

    A prose-only prompt (no backticked command lines) leaves the components
    splitter with action names such as ``add_customer``.  Asked for one group,
    the model tends to repeat every action as a subcommand of every group, so
    the merged surface becomes a Cartesian product no service can back.  When
    the requirements name no command lines, the service contract is the
    authority for the operations: group its methods by model noun and verb
    (``create_customer`` -> ``customer add``), and give each leaf that
    method's parameters as flags.  Explicit command lines never take this path.
    """
    from kernel.extraction import command_lines

    if not isinstance(components, dict) or not isinstance(services, list):
        return components
    if command_lines.extract_command_lines(requirements or ""):
        return components
    facade = components.get("facade")
    if not isinstance(facade, dict) or (facade.get("type") or "").lower() != "cli":
        return components
    invocation = facade.get("invocation")
    if not isinstance(invocation, dict) or not isinstance(invocation.get("commands"), list):
        return components

    entities = [model.get("name") for model in models or []
                if isinstance(model, dict) and isinstance(model.get("name"), str)]
    if not entities:
        return components

    methods = []
    for service in services:
        if not isinstance(service, dict):
            continue
        for method in service.get("methods") or []:
            if isinstance(method, dict) and isinstance(method.get("name"), str):
                methods.append(method)
    if not methods:
        return components

    type_names = {
        "int": "int", "integer": "int", "bool": "bool", "boolean": "bool",
        "float": "float", "double": "float", "decimal": "float",
        "money": "float", "str": "str", "string": "str", "text": "str",
        "datetime": "str", "date": "str", "list": "str", "dict": "str",
    }
    verbs = {
        "create": "add", "add": "add", "read_all": "list", "list": "list",
        "read_one": "get", "get": "get", "find": "find", "search": "search",
        "update": "update", "delete": "delete", "remove": "delete",
        "confirm": "confirm", "cancel": "cancel", "ship": "ship",
        "export": "export", "report": "report", "summary": "report",
        "stock": "stock", "restock": "restock",
    }

    def entity_for(name):
        flat = normalize(name)
        found = []
        for entity in entities:
            token = normalize(entity)
            index = flat.find(token)
            if index >= 0:
                found.append((index, -len(token), entity))
        return min(found)[2] if found else None

    def verb_for(name):
        tokens = [token for token in re.split(r"[^a-z0-9]+", name.lower())
                  if token]
        for token in tokens:
            if token in verbs:
                return verbs[token]
        return None

    def options_for(method, verb):
        params = [param for param in method.get("params") or []
                  if isinstance(param, dict) and param.get("name")]
        optional = verb in ("search", "find", "list", "get", "update")
        options = []
        for index, param in enumerate(params):
            raw = param["name"]
            declared = str(param.get("type") or "").strip().lower()
            required = (not optional and index == 0) or (
                not optional and verb in ("add", "delete", "confirm",
                                          "cancel", "ship", "restock",
                                          "export", "report"))
            options.append({
                "name": "--" + raw.replace("_", "-"),
                "short": None,
                "type": type_names.get(declared, "str"),
                "required": required,
                "default": None,
            })
        return options

    groups = {}
    order = []
    for method in methods:
        name = method["name"]
        entity = entity_for(name)
        verb = verb_for(name)
        if entity is None or verb is None or verb in ("find", "get"):
            # Repository `find_*`/`get_*` variants are implementation filters,
            # not necessarily distinct user commands; `search`/`list` carry
            # the prompt-facing lookup when one exists.  Keeping a `get` leaf
            # with no options made the CLI bind it to a method that requires
            # an id.
            continue
        key = normalize(entity)
        if key not in groups:
            groups[key] = {"name": entity, "options": [], "subcommands": []}
            order.append(key)
        group = groups[key]
        if any(sub.get("name") == verb for sub in group["subcommands"]):
            continue
        group["subcommands"].append({
            "name": verb,
            "options": options_for(method, verb),
        })
    repaired = [groups[key] for key in order if groups[key]["subcommands"]]
    if not repaired:
        return components
    invocation["commands"] = repaired
    if log is not None:
        log.write(
            f"[ok] step adapters: derived {len(repaired)} command group(s) "
            f"from {len(methods)} service method(s)")
    return components

def repair_supported_gui_tech(components, log=None):
    """Use a GUI backend the generator can actually emit.

    The requirements name a GUI but not a toolkit; the extractor can write
    `tkinter` or another plausible word while `generator.py` has one concrete
    backend (`pyimgui`).  An unsupported word would otherwise drop `gui.py`
    entirely, leaving the prompt's central surface missing.  Normalizing the
    declaration is a capability choice, not a domain decision: the panels,
    fields and CRUD wiring still come from the documents.
    """
    if not isinstance(components, dict):
        return components
    facade = components.get("facade")
    if not isinstance(facade, dict) or (facade.get("type") or "").lower() != "gui":
        return components
    supported = {"pyimgui"}
    tech = str(facade.get("technology") or "").strip().lower()
    if tech in supported:
        return components
    facade["technology"] = "pyimgui"
    if log is not None:
        log.write(
            f"[ok] step components: GUI technology {tech or '(none)'!r} has no "
            "emitter — using the supported pyimgui backend for the same panels")
    return components


_CAPABILITY_STEMS = {
    "search": ("search", "find"),
    "export": ("export",),
    "import": ("import",),
    "report": ("report", "summary"),
    "stock": ("stock",),
    "confirm": ("confirm",),
}


def _capability_verb(name):
    """The capability verb an action/method name states, or None."""
    normalized = normalize(name or "")
    # `update_product_stock` is an ordinary create/update action, not a
    # separate stock capability; only a capability-shaped leading verb is
    # repaired here.
    if normalized.startswith(("create", "update", "delete", "read", "list",
                              "add", "remove", "edit", "set")):
        return None
    for verb, stems in _CAPABILITY_STEMS.items():
        if any(stem in normalized for stem in stems):
            return verb
    return None


def _capability_entity(name, models):
    """The longest declared entity contained in a service/action name."""
    normalized = normalize(name or "")
    found = [(len(normalize(model.get("name"))), model.get("name"))
             for model in models or []
             if isinstance(model, dict) and isinstance(model.get("name"), str)
             and normalize(model.get("name")) in normalized]
    return max(found)[1] if found else None


def _capability_service(services, name):
    wanted = normalize(name)
    for service in services or []:
        if isinstance(service, dict) and normalize(service.get("service_name")) == wanted:
            return service
    service = {"service_name": name, "methods": []}
    services.append(service)
    return service


def _capability_param_type(field_name, models, method=None):
    if isinstance(method, dict):
        for param in method.get("params") or []:
            if (isinstance(param, dict)
                    and normalize(param.get("name")) == normalize(field_name)):
                declared = str(param.get("type") or "").strip()
                if declared:
                    return declared
    for model in models or []:
        if not isinstance(model, dict):
            continue
        for field in model.get("fields") or []:
            if (isinstance(field, dict)
                    and normalize(field.get("name")) == normalize(field_name)):
                declared = str(field.get("type") or "").strip().lower()
                return _PORT_TYPES.get(declared, field.get("type") or "str")
    return "str"


def _add_capability_method(service, name, adapter, entity, verb, models, log):
    """Add and return one capability method, or complete the existing one."""
    fields = []
    seen = set()
    for item in adapter.get("input_fields") or []:
        if not isinstance(item, dict) or not item.get("field_name"):
            continue
        field_name = item["field_name"]
        key = normalize(field_name)
        if key in seen:
            continue
        seen.add(key)
        fields.append({
            "name": field_name,
            "type": _capability_param_type(field_name, models),
        })
    for method in service.get("methods") or []:
        if isinstance(method, dict) and normalize(method.get("name")) == normalize(name):
            params = method.setdefault("params", [])
            taken = {normalize(param.get("name")) for param in params
                     if isinstance(param, dict)}
            for field in fields:
                if normalize(field["name"]) not in taken:
                    params.append(field)
            return method
    if verb == "search":
        returns = (f"list[{entity}]" if entity else "list")
    elif verb == "import":
        returns = "int"
    else:
        returns = "None"
    method = {
        "name": name,
        "description": f"{name.replace('_', ' ').capitalize()}.",
        "params": fields,
        "return_type": returns,
        "raises": [],
        "provenance": "capability_adapter",
        "review_required": True,
    }
    service.setdefault("methods", []).append(method)
    if log is not None:
        log.write(
            f"[ok] step adapters: added capability method "
            f"{service.get('service_name')}.{name} ({verb})"
        )
    return method


def repair_capability_adapters(components, services, adapters, models,
                               requirements, log=None):
    """Give capability actions a method and expose import when prose asks for it.

    A search/export/import action can be fully described by its adapter, yet
    the service contract names only the CRUD method it delegates to (`read_all`).
    The CLI leaf then has no method whose name states the capability, and the
    readiness checker correctly refuses to generate it.  Add the missing
    capability method on the service that owns the entity; export/import get a
    service rather than a repository because their generated body writes a file.
    The adapter is retargeted to that method, so the surface and the call agree.
    """
    if not isinstance(services, list) or not isinstance(adapters, list):
        return components
    for adapter in list(adapters):
        if not isinstance(adapter, dict):
            continue
        action = adapter.get("action_name")
        verb = _capability_verb(action)
        if verb is None:
            continue
        target_service = adapter.get("target_service")
        target_method = adapter.get("target_method")
        if not isinstance(target_service, str) or not target_service:
            continue
        entity = _capability_entity(action, models) \
            or _capability_entity(target_service, models)
        declared = next((service for service in services
                         if isinstance(service, dict)
                         and normalize(service.get("service_name")) == normalize(target_service)),
                        None)
        existing = any(
            isinstance(method, dict)
            and normalize(method.get("name")) == normalize(action)
            for method in (declared or {}).get("methods") or [])
        owns_target = (entity is None
                       or normalize(entity) in normalize(target_service)
                       or existing)
        if verb in ("export", "import") and target_service.endswith("Repository"):
            service_name = (entity or target_service[:-len("Repository")]) + "Service"
        elif owns_target:
            service_name = target_service
        else:
            owner = next((service.get("service_name") for service in services
                          if isinstance(service, dict)
                          and isinstance(service.get("service_name"), str)
                          and entity is not None
                          and normalize(entity) in normalize(service["service_name"])
                          and normalize(service["service_name"]).endswith("service")),
                         None)
            if owner is None:
                if log is not None:
                    log.write(
                        f"[!] step adapters: '{action}' names {entity} but no "
                        "owning service declares it; adapter removed rather "
                        "than attached to the wrong service")
                adapters.remove(adapter)
                continue
            service_name = owner
        if target_service != service_name:
            adapter["target_service"] = service_name
        method = _add_capability_method(
            _capability_service(services, service_name), action, adapter,
            entity, verb, models, log)
        adapter["target_method"] = method["name"]

    # A prose import requirement has no action yet. Add the command, method and
    # adapter together; the command is the surface the prompt asks for.
    text = requirements or ""
    if not re.search(r"\bimport\b", text, re.IGNORECASE):
        return components
    fmt = "json" if re.search(r"\bjson\b", text, re.IGNORECASE) else "csv"
    if not re.search(rf"\b{fmt}\b", text, re.IGNORECASE):
        return components
    if not isinstance(components, dict):
        return components
    facade = components.get("facade")
    invocation = (facade or {}).get("invocation") if isinstance(facade, dict) else None
    commands = invocation.get("commands") if isinstance(invocation, dict) else None
    if not isinstance(commands, list):
        return components
    for command in commands:
        if not isinstance(command, dict):
            continue
        for sub in command.get("subcommands") or []:
            if isinstance(sub, dict) and normalize(sub.get("name")) == "import":
                return components
    group = next((command for command in commands
                  if isinstance(command, dict)
                  and _capability_entity(command.get("name"), models)), None)
    if group is None:
        # Prefer a group the requirements name.
        group = next((command for command in commands
                      if isinstance(command, dict)
                      and normalize(command.get("name")) in normalize(text)), None)
    if group is None:
        return components
    entity = _capability_entity(group.get("name"), models)
    if entity is None:
        return components
    service_name = (entity + "Service")
    service = _capability_service(services, service_name)
    action = f"import_{entity.lower()}s_from_{fmt}"
    adapter = {
        "action_name": action,
        "target_service": service_name,
        "target_method": action,
        "provenance": "capability_adapter",
        "review_required": True,
        "input_fields": [{
            "field_name": "file_path",
            "target_param": "file_path",
            "transform": "DIRECT",
            "lookup_entity": None,
            "required": True,
        }],
    }
    _add_capability_method(service, action, adapter, entity, "import",
                           models, log)
    adapters.append(adapter)
    group.setdefault("subcommands", []).append({
        "name": "import",
        "options": [{
            "name": "--file-path",
            "short": None,
            "type": "str",
            "required": True,
            "default": None,
        }],
    })
    if log is not None:
        log.write(
            f"[ok] step adapters: exposed prose import as "
            f"{group.get('name')} import"
        )
    return components


def repair_surface_from_adapters(components, adapters, models, services, requirements, log=None):
    """Rebuild a prose-derived CLI surface from the adapters that actually run.

    After the adapter step, every action has a concrete service method and a
    field list.  Using the service list directly can name a leaf whose adapter
    was never emitted (``product delete`` beside ``delete_order``) or whose
    flag target belongs to a different method.  This pass groups the adapters
    by model noun and verb and takes the flags from each adapter's own input
    fields, so every leaf has a call behind it.  Explicit command lines are
    never rewritten.
    """
    from kernel.extraction import command_lines

    if not isinstance(components, dict) or not isinstance(adapters, list):
        return components
    if command_lines.extract_command_lines(requirements or ""):
        return components
    facade = components.get("facade")
    if not isinstance(facade, dict) or (facade.get("type") or "").lower() != "cli":
        return components
    invocation = facade.get("invocation")
    if not isinstance(invocation, dict) or not isinstance(invocation.get("commands"), list):
        return components
    entities = [model.get("name") for model in models or []
                if isinstance(model, dict) and isinstance(model.get("name"), str)]
    if not entities or not adapters:
        return components

    method_params = {}
    for service in services or []:
        if not isinstance(service, dict):
            continue
        for method in service.get("methods") or []:
            if isinstance(method, dict) and method.get("name"):
                method_params[(normalize(service.get("service_name")),
                               normalize(method["name"]))] = {
                    normalize(param.get("name")): param.get("type")
                    for param in method.get("params") or []
                    if isinstance(param, dict) and param.get("name")}
    types = {}
    for model in models or []:
        if not isinstance(model, dict):
            continue
        for field in model.get("fields") or []:
            if isinstance(field, dict) and field.get("name"):
                declared = str(field.get("type") or "").strip().lower()
                types[field["name"]] = {
                    "int": "int", "integer": "int", "bool": "bool",
                    "boolean": "bool", "float": "float", "double": "float",
                    "decimal": "float", "money": "float", "str": "str",
                    "string": "str", "text": "str", "datetime": "str",
                    "date": "str", "list": "str", "dict": "str",
                }.get(declared, "str")

    verbs = {
        "create": "add", "add": "add", "read_all": "list", "list": "list",
        "read_one": "get", "get": "get", "find": "find", "search": "search",
        "update": "update", "delete": "delete", "remove": "delete",
        "confirm": "confirm", "cancel": "cancel", "ship": "ship",
        "export": "export", "report": "report", "summary": "report",
        "stock": "stock", "restock": "restock",
    }

    def entity_for(name):
        flat = normalize(name)
        found = []
        for entity in entities:
            token = normalize(entity)
            index = flat.find(token)
            if index >= 0:
                found.append((index, -len(token), entity))
        return min(found)[2] if found else None

    def verb_for(name):
        for token in re.split(r"[^a-z0-9]+", name.lower()):
            if token in verbs:
                return verbs[token]
        return None

    groups = {}
    order = []
    selected_actions = set()
    for adapter in adapters:
        if not isinstance(adapter, dict) or not adapter.get("target_method"):
            continue
        method = adapter["target_method"]
        entity = entity_for(adapter.get("action_name") or method) \
            or entity_for(method)
        verb = verb_for(adapter.get("action_name") or method) \
            or verb_for(method)
        if entity is None or verb is None or verb in ("find", "get"):
            # Repository `find_*`/`get_*` variants are implementation filters,
            # not necessarily distinct user commands; `search`/`list` carry
            # the prompt-facing lookup when one exists.  Keeping a `get` leaf
            # with no options made the CLI bind it to a method that requires
            # an id.
            continue
        key = normalize(entity)
        if key not in groups:
            groups[key] = {"name": entity, "options": [], "subcommands": []}
            order.append(key)
        group = groups[key]
        if any(sub.get("name") == verb for sub in group["subcommands"]):
            continue
        selected_actions.add(adapter.get("action_name"))
        options = []
        seen_options = set()
        for item in adapter.get("input_fields") or []:
            if not isinstance(item, dict) or not item.get("field_name"):
                continue
            field = item["field_name"]
            if field in seen_options:
                continue
            seen_options.add(field)
            target_type = method_params.get(
                (normalize(adapter.get("target_service")),
                 normalize(adapter.get("target_method"))), {}).get(
                     normalize(item.get("target_param") or field))
            declared = str(target_type or types.get(field, "str")).strip().lower()
            options.append({
                "name": "--" + field.replace("_", "-"),
                "short": None,
                "type": {"int": "int", "integer": "int",
                         "bool": "bool", "boolean": "bool",
                         "float": "float", "double": "float",
                         "decimal": "float", "money": "float",
                         "str": "str", "string": "str", "text": "str",
                         "datetime": "str", "date": "str"}.get(declared, "str"),
                "required": bool(item.get("required")),
                "default": None,
            })
        group["subcommands"].append({"name": verb, "options": options})
    repaired = [groups[key] for key in order if groups[key]["subcommands"]]
    if not repaired:
        return components
    invocation["commands"] = repaired
    # Keep only the adapter that the surface actually exposes.  A second
    # adapter for the same noun/verb (find by status versus find by customer
    # and status) would otherwise demand a flag no kept command can supply.
    adapters[:] = [
        adapter for adapter in adapters
        if isinstance(adapter, dict)
        and adapter.get("action_name") in selected_actions
    ]
    if log is not None:
        log.write(
            f"[ok] step adapters: rebuilt prose-derived surface from "
            f"{len(adapters)} adapter(s)")
    return components


def repair_program_word_subcommands(components, requirements, log=None):
    """Fold a flat command misread as `<command> <program> --flag`.

    A model reading a flat requirements line such as ``library overdue`` can
    turn it into top-level ``overdue`` with a subcommand named after the
    program word (``overdue library --overdue``).  The program word is not a
    command path; it is the executable.  When the requirements have
    ``<program> <command>`` and no line names ``<program> <command>
    <program>``, promote the subcommand's options to the command and remove
    the bogus subcommand.  This is deterministic: the words and flags come
    from the requirements surface, not from domain inference.
    """
    from kernel.extraction import command_lines

    if not isinstance(components, dict) or not requirements:
        return components
    spans = command_lines.extract_command_lines(requirements)
    if not spans:
        return components
    parts = [span.split() for span in spans if isinstance(span, str)]
    programs = {words[0].lower() for words in parts if words}
    facade = components.get("facade")
    invocation = facade.get("invocation") if isinstance(facade, dict) else None
    commands = invocation.get("commands") if isinstance(invocation, dict) else None
    if not isinstance(commands, list):
        return components
    for command in commands:
        if not isinstance(command, dict):
            continue
        name = command.get("name")
        subs = command.get("subcommands")
        if (not isinstance(name, str) or not isinstance(subs, list)
                or len(subs) != 1):
            continue
        sub = subs[0]
        if not isinstance(sub, dict):
            continue
        sub_name = sub.get("name")
        if not isinstance(sub_name, str) or sub_name.lower() not in programs:
            continue
        # The flat line must exist, and no path may explicitly nest the
        # program word under this command.
        flat = any(len(words) >= 2
                   and words[0].lower() == sub_name.lower()
                   and words[1].lower() == name.lower()
                   for words in parts)
        nested = any(len(words) >= 3
                     and words[0].lower() == sub_name.lower()
                     and words[1].lower() == name.lower()
                     and words[2].lower() == sub_name.lower()
                     for words in parts)
        if not flat or nested:
            continue
        existing = {option.get("name") for option in command.get("options") or []
                    if isinstance(option, dict)}
        for option in sub.get("options") or []:
            if not isinstance(option, dict) or not option.get("name"):
                continue
            if option.get("name") not in existing:
                command.setdefault("options", []).append(option)
                existing.add(option.get("name"))
        command["subcommands"] = []
        if log is not None:
            log.write(
                f"[ok] step components: folded accidental subcommand "
                f"'{name} {sub_name}' into flat '{name}' (the program word "
                "is not a command path)"
            )
    return components


def repair_long_option_names(components, log=None):
    """Normalize a multi-character single-dash option to `--name`.

    The requirements spell long flags with two dashes (`--title`), and the
    command-line parser accepts only that spelling. A model sometimes writes
    `-title` (a long name with a short flag's arity); the destination and
    review decisions are unchanged, only the spelling is repaired. A true
    short flag (`-t`) is left alone. Idempotent.
    """
    if not isinstance(components, dict):
        return components
    facade = components.get("facade")
    invocation = facade.get("invocation") if isinstance(facade, dict) else None
    if not isinstance(invocation, dict):
        return components

    def visit(node):
        if not isinstance(node, dict):
            return
        for option in node.get("options") or []:
            if not isinstance(option, dict):
                continue
            name = option.get("name")
            if (isinstance(name, str) and name.startswith("-")
                    and not name.startswith("--") and len(name) > 2):
                option["name"] = "--" + name[1:]
                if log is not None:
                    log.write(
                        f"[ok] step components: normalized option '{name}' "
                        f"to '{option['name']}'")
        for child in node.get("subcommands") or []:
            visit(child)
        for child in node.get("commands") or []:
            visit(child)

    visit(invocation)
    return components


def repair_nested_paths(components, requirements, log):
    """File a nesting prompt's lines as path leaves and fold the flat form away.

    A prompt that nests command groups (`expense category add --name`) names
    its subcommands by a path (`category add` under `expense`). A small model
    asked for that surface flattens it: `category` becomes a command of its own
    and `report monthly`/`report yearly` merge into one `report`. The lines are
    authoritative and the model is good at typing flags, so each line becomes
    the leaf it names, takes the flags the model already typed on its flat
    leaves (matched as flags are matched everywhere, by name or unique
    containment: a `--yearly` stands for `--year`), and the flat nodes the paths
    supersede are folded away. Nothing is invented: the paths come from the
    requirements and the option types from the model's own output; a flag with
    no donor is left for `repair_missing_flags`. Every step is logged, and a
    prompt that does not nest is not touched.
    """
    from kernel.extraction import command_lines

    if not isinstance(components, dict) or not requirements:
        return components
    spans = command_lines.extract_command_lines(requirements)
    if not command_lines.uses_paths(spans):
        return components
    facade = components.get("facade")
    invocation = facade.get("invocation") if isinstance(facade, dict) else None
    if not isinstance(invocation, dict) or not isinstance(invocation.get("commands"), list):
        return components
    attributed = command_lines.path_attribution(spans)
    paths = [(command, path, flags) for command, path, flags in attributed
             if path and " " in path]

    def leaf_options(leaf):
        return [o for o in (leaf or {}).get("options") or [] if isinstance(o, dict)]

    def flat(command, sub):
        return _find_leaf(invocation, command, sub)

    # 1. each path becomes a leaf, typed from the model's own flat leaves
    for command, path, flags in paths:
        first, *rest = path.split()
        donors = [flat(first, rest[0]) if rest else None,   # `category` / `add`
                  flat(command, first),                      # `report` under `expense`
                  flat(first, None)]
        entry = _ensure_command(invocation, command, log)
        if entry is None:
            continue
        _ensure_subcommand(entry, command, path, log)
        leaf = _find_leaf(invocation, command, path)
        if leaf is None:
            continue
        for flag, required in flags:
            if _leaf_has_flag(leaf, flag):
                continue
            for donor in filter(None, donors):
                match = next((o for o in leaf_options(donor)
                              if bind_field([option_dest(o)], flag) is not None), None)
                if match is None:
                    continue
                leaf.setdefault("options", []).append({
                    "name": f"--{flag}", "short": None,
                    "type": match.get("type"), "required": required,
                    "default": match.get("default")})
                if log is not None:
                    log.write(
                        f"[ok] step components: '{command} {path}' lacked '--{flag}' "
                        f"the requirements pass — added as {match.get('type')} "
                        f"(typed like the model's own '{match.get('name')}')")
                break

    # 2. fold away the flat nodes the paths supersede
    line_commands = {command for command, _path, _flags in attributed}
    bare = {(command, path) for command, path, _flags in attributed if path}
    commands = invocation["commands"]
    for command, path, _flags in paths:
        first, *rest = path.split()
        # a top-level `category` whose `add` is now `expense` / `category add`
        if first not in line_commands and rest:
            holder = next((c for c in commands if isinstance(c, dict)
                           and c.get("name") == first), None)
            if holder is not None:
                subs = holder.get("subcommands") or []
                kept = [x for x in subs if not (isinstance(x, dict)
                        and x.get("name") == rest[0])]
                if len(kept) != len(subs):
                    holder["subcommands"] = kept
                    if log is not None:
                        log.write(f"[ok] step components: folded flat '{first} {rest[0]}' "
                                  f"into '{command} {path}' (the requirements nest it)")
                if not kept and not holder.get("options"):
                    commands.remove(holder)
                    if log is not None:
                        log.write(f"[ok] step components: dropped the emptied flat "
                                  f"command '{first}'")
        # a leaf `report` beside `report monthly` and `report yearly`
        owner = next((c for c in commands if isinstance(c, dict)
                      and c.get("name") == command), None)
        if owner is not None and (command, first) not in bare:
            subs = owner.get("subcommands") or []
            kept = [x for x in subs if not (isinstance(x, dict)
                    and x.get("name") == first)]
            if len(kept) != len(subs):
                owner["subcommands"] = kept
                if log is not None:
                    log.write(f"[ok] step components: folded flat '{command} {first}' "
                              f"into its paths such as '{command} {path}'")
    return components


FLAG_DECISIONS_NAME = "flag_decisions.json"


def load_flag_decisions(output_dir):
    """The recorded answers for ambiguous method-backed flags."""
    try:
        with open(Path(output_dir) / FLAG_DECISIONS_NAME,
                  encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return []
    records = payload.get("decisions") if isinstance(payload, dict) else payload
    return [record for record in records or [] if isinstance(record, dict)]


def save_flag_decisions(output_dir, records):
    """Persist the ambiguous-flag review answers."""
    path = Path(output_dir) / FLAG_DECISIONS_NAME
    path.write_text(json.dumps({"decisions": records}, indent=2,
                               ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def repair_missing_method_flags(components, requirements, services, log=None,
                                decisions=None):
    """Add a required flag whose type is grounded in a service parameter.

    `expense report yearly --year` has no model field called `year`; the
    method `get_yearly_summary(year: int)` is the only proof of its type.
    An unambiguous method/parameter pair is used directly. When several
    methods can satisfy the same flag, the choice must be recorded in
    `flag_decisions.json`; the repair never picks one by name alone.
    """
    if not isinstance(components, dict) or not requirements:
        return components
    facade = components.get("facade")
    invocation = facade.get("invocation") if isinstance(facade, dict) else None
    if not isinstance(invocation, dict):
        return components
    commands = surface_checks._commands_by_name(invocation)
    program = surface_checks._program_name(requirements)
    for span in re.findall(r"`([^`]*)`", requirements):
        target = surface_checks._resolve_span(span, program, commands)
        if target is None:
            continue
        command, sub = target
        leaf = _find_leaf(invocation, command, sub)
        if leaf is None:
            continue
        for flag, bracketed in surface_checks._flags_in(span):
            if _leaf_has_flag(leaf, flag):
                continue
            candidates = []
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
                            candidates.append((service, method, param))
            chosen = None
            if len(candidates) == 1:
                chosen = candidates[0]
            elif decisions:
                for candidate in candidates:
                    service, method, param = candidate
                    for record in decisions:
                        if (normalize(record.get("command") or "") != normalize(command)
                                or normalize(record.get("subcommand") or "")
                                != normalize(sub or "")
                                or normalize(record.get("flag") or "") != normalize(flag)
                                or normalize(record.get("service") or "")
                                != normalize(service.get("service_name") or "")
                                or normalize(record.get("method") or "")
                                != normalize(method.get("name") or "")
                                or normalize(record.get("param") or "")
                                != normalize(param.get("name") or "")):
                            continue
                        chosen = candidate
                        break
                    if chosen is not None:
                        break
            if chosen is None:
                if log is not None:
                    shown = f"[--{flag}]" if bracketed else f"--{flag}"
                    candidates = ", ".join(
                        f"{service.get('service_name')}.{method.get('name')}"
                        f"({param.get('name')}: {param.get('type')})"
                        for service, method, param in candidates)
                    log.write(
                        f"[!] step components: {command} {sub or ''} lacks "
                        f"'{shown}' but several methods can satisfy it "
                        f"({candidates}); record one in "
                        f"{FLAG_DECISIONS_NAME} before generation")
                continue
            _service, _method, param = chosen
            option_type = _option_type(param.get("type"))
            leaf.setdefault("options", []).append({
                "name": f"--{flag}",
                "short": None,
                "type": option_type,
                "required": not bracketed,
                "default": None,
            })
            if log is not None:
                shown = f"[--{flag}]" if bracketed else f"--{flag}"
                source = "human decision" if len(candidates) > 1 else "requirements"
                log.write(
                    f"[ok] step components: {command} {sub or ''} lacked "
                    f"'{shown}' the requirements pass — added as {option_type} "
                    f"({source}: {_service.get('service_name')}. "
                    f"{_method.get('name')})")
    return components


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


def repair_delete_surface(components, log=None):
    """Only the key is required on a delete verb.

    A delete repository method takes the key plus optional narrowing fields.
    Extraction often copies every model field onto the command as required, so
    `delete --id 1` is rejected for lack of a timestamp that the method can
    leave out. The key named by the leaf is enough; every other filter becomes
    optional, exactly as the generated delete body treats it.
    """
    if not isinstance(components, dict):
        return components
    invocation = ((components.get("facade") or {}).get("invocation")
                  if isinstance(components.get("facade"), dict) else None)
    changed = 0
    def walk(nodes):
        nonlocal changed
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            subcommands = node.get("subcommands")
            if isinstance(subcommands, list) and subcommands:
                walk(subcommands)
                continue
            if str(node.get("name") or "").lower() not in ("delete", "remove"):
                continue
            options = node.get("options") or []
            key = None
            for option in options:
                if not isinstance(option, dict):
                    continue
                dest = normalize(str(option.get("name") or "").lstrip("-"))
                if dest == "id" or dest.endswith("id"):
                    key = option
                    break
            if key is None:
                continue
            for option in options:
                if option is key or not isinstance(option, dict):
                    continue
                if option.get("required"):
                    option["required"] = False
                    changed += 1
    if isinstance(invocation, dict):
        walk(invocation.get("commands"))
    if changed and log is not None:
        log.write(f"[ok] step surface: made {changed} delete filter(s) optional")
    return components


def repair_delete_adapter_fields(adapters, log=None):
    """Make non-key fields optional on an adapter bound to delete."""
    if not isinstance(adapters, list):
        return adapters
    changed = 0
    for adapter in adapters:
        if not isinstance(adapter, dict):
            continue
        if str(adapter.get("target_method") or "").lower() not in (
                "delete", "remove"):
            continue
        fields = [field for field in adapter.get("input_fields") or []
                  if isinstance(field, dict)]
        key = next((field for field in fields
                    if str(field.get("field_name") or "").lower().endswith("id")),
                   None)
        if key is None:
            continue
        for field in fields:
            if field is not key and field.get("required"):
                field["required"] = False
                changed += 1
    if changed and log is not None:
        log.write(f"[ok] step adapters: made {changed} delete field(s) optional")
    return adapters


def repair_aggregate_create_adapters(components, adapters, services, repositories,
                                     models, log=None):
    """Fall back to a plain create when an aggregate cannot consume its flags.

    A command surface may expose only the line fields of an aggregate create
    (`Order add --product-id --quantity ...`) while the service takes a named
    DTO (`OrderCreationData`) and the store creates `Order`. The bound method
    can never consume those flags, so the emitted command would always fail.
    Expose the entity's own plain create instead: it is the only create whose
    parameters the model can supply. The action name stays for the review
    trail; the adapter is pointed at the repository/service `create` method.
    """
    if not isinstance(adapters, list):
        return adapters
    all_methods = list(services or []) + list(repositories or [])
    index = _service_method_index(all_methods)
    models_by_name = {normalize(m.get("name")): m for m in models or []
                      if isinstance(m, dict) and m.get("name")}
    repo_by_entity = {}
    for repo in repositories or []:
        if isinstance(repo, dict) and repo.get("entity"):
            repo_by_entity.setdefault(normalize(repo["entity"]), repo)
    changed = 0
    for adapter in adapters:
        if not isinstance(adapter, dict):
            continue
        method = _resolve_adapter_method(adapter, index)
        if method is None or not str(method.get("name") or "").startswith("create"):
            continue
        params = [p for p in method.get("params") or [] if isinstance(p, dict)]
        mapping_names = {
            normalize(p.get("name")) for p in params
            if p.get("name") and (
                _is_mapping_type(p.get("type"))
                or str(p.get("type") or "").strip().lower().startswith("list"))}
        targets = {
            normalize(f.get("target_param"))
            for f in adapter.get("input_fields") or []
            if isinstance(f, dict) and f.get("target_param")}
        if not targets or not targets <= mapping_names:
            continue
        returned = normalize(str(method.get("return_type") or ""))
        returned = returned.replace("models", "").replace("list[", "").replace("]", "")
        entity = next((name for key, name in models_by_name.items()
                       if key and (key in returned or returned in key)), None)
        if entity is None:
            owner = normalize(str(adapter.get("target_service") or ""))
            for suffix in ("repository", "service"):
                if owner.endswith(suffix):
                    owner = owner[:-len(suffix)]
                    break
            entity = models_by_name.get(owner)
        if entity is None:
            continue
        entity_name = entity.get("name")
        model_fields = {
            normalize(f.get("name")) for f in entity.get("fields") or []
            if isinstance(f, dict) and f.get("name")}
        exposed = {
            normalize(f.get("field_name"))
            for f in adapter.get("input_fields") or []
            if isinstance(f, dict) and f.get("field_name")}
        if exposed and exposed <= model_fields:
            continue
        repo = repo_by_entity.get(normalize(entity_name))
        candidates = []
        if repo is not None:
            for candidate in repo.get("methods") or []:
                if isinstance(candidate, dict) and \
                        normalize(candidate.get("name")) == "create":
                    candidates.append(
                        (repo.get("interface_name") or entity_name, candidate))
        for service in services or []:
            if not isinstance(service, dict):
                continue
            name = normalize(service.get("service_name") or "")
            if not name.endswith(normalize(entity_name)):
                continue
            for candidate in service.get("methods") or []:
                if isinstance(candidate, dict) and \
                        normalize(candidate.get("name")) == "create":
                    candidates.append((service.get("service_name"), candidate))
        if not candidates:
            continue
        owner, create = candidates[0]
        adapter["target_service"] = owner
        adapter["target_method"] = create.get("name")
        adapter["input_fields"] = []
        adapter["_surface_retargeted"] = True
        changed += 1
        _prune_leaf_options(components, adapter)
    if changed and log is not None:
        log.write(
            f"[ok] step adapters: retargeted {changed} aggregate create "
            "adapter(s) to plain create")
    return adapters


def _prune_leaf_options(components, adapter):
    """Remove flags the retargeted adapter no longer reads."""
    if not isinstance(components, dict):
        return
    facade = components.get("facade")
    invocation = facade.get("invocation") if isinstance(facade, dict) else None
    if not isinstance(invocation, dict):
        return
    from kernel.codegen import bind_commands
    from kernel.consistency.checks_surface import COMMAND_VERB_STEMS
    bindings, _ = bind_commands([adapter], invocation, COMMAND_VERB_STEMS)
    action = adapter.get("action_name")
    for (command, sub), bound in bindings.items():
        if bound is None or bound[0] != action:
            continue
        leaf = _find_leaf(invocation, command, sub)
        if leaf is not None:
            leaf["options"] = []


def repair_create_adapter_fields(adapters, services, models, log=None):
    """Expose every required model field a create adapter does not map.

    Adapters and persistence ports are written in different steps.  A port can
    correctly require `quantity` or `customer_id` while the adapter still maps
    only the visible scalar field, leaving the generated create to insert a
    NULL.  The model's NOT NULL fields are the authority; only plain create
    methods are extended, and only fields their signatures already accept.
    """
    if not isinstance(adapters, list):
        return adapters
    index = _service_method_index(services)
    models_by_name = {}
    for model in models or []:
        if isinstance(model, dict) and model.get("name"):
            models_by_name[normalize(model["name"])] = model
    changed = 0
    for adapter in adapters:
        if not isinstance(adapter, dict):
            continue
        method = _resolve_adapter_method(adapter, index)
        if method is None or not str(method.get("name") or "").startswith("create"):
            continue
        target = normalize(str(adapter.get("target_service") or ""))
        for suffix in ("repository", "service"):
            if target.endswith(suffix):
                target = target[:-len(suffix)]
                break
        model = models_by_name.get(target)
        if model is None:
            returned = normalize(str(method.get("return_type") or ""))
            returned = returned.replace("list[", "").replace("]", "")
            model = models_by_name.get(returned)
        if model is None:
            continue
        params = {normalize(p.get("name")): p for p in method.get("params") or []
                  if isinstance(p, dict) and p.get("name")}
        mapped = set()
        for field in adapter.get("input_fields") or []:
            if not isinstance(field, dict):
                continue
            for key in ("field_name", "target_param"):
                if field.get(key):
                    mapped.add(normalize(field[key]))
        for field in model.get("fields") or []:
            if not isinstance(field, dict) or not field.get("name"):
                continue
            name = field["name"]
            if (field.get("primary_key") or field.get("nullable")
                    or normalize(name) not in params
                    or normalize(name) in mapped):
                continue
            declared = str(field.get("type") or "").strip().lower()
            if declared in ("bool", "boolean"):
                # Booleans usually have a false/default at the store; exposing
                # every one as a required create flag is not a NOT NULL fix.
                continue
            transform = "DIRECT"
            lookup = None
            if declared in ("int", "integer") and normalize(name).endswith("id"):
                transform = "LOOKUP_ID"
                base = name[:-3]
                lookup = base[:1].upper() + base[1:]
            elif declared in ("datetime", "date", "time", "datetime.datetime"):
                transform = "ISO_DATE"
            elif declared in ("decimal", "float", "money"):
                transform = "DECIMAL_TO_CENTS"
            adapter.setdefault("input_fields", []).append({
                "field_name": name,
                "target_param": name,
                "transform": transform,
                "lookup_entity": lookup,
                "required": True,
                "status": _field_status(field),
            })
            mapped.add(normalize(name))
            changed += 1
    if changed and log is not None:
        log.write(f"[ok] step adapters: added {changed} required create field(s)")
    return adapters


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
            options = leaf.get("options")
            if not isinstance(options, list):
                options = []
                leaf["options"] = options
            options.append(option)
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
    ptype = ptypes.get(normalize(target))
    entity = _entity_of(ptype, model_fields)
    if entity is None and is_mapping_type(ptype):
        # `update(id, data: dict[str, any])` carries the entity only in the
        # service name (`CategoryRepository`), not in the mapping's type.
        owner = normalize(adapter.get("target_service") or "")
        matches = [name for name in model_fields if owner.startswith(name)]
        if len(matches) == 1:
            entity = matches[0]
    if entity is None:
        return None
    fields = model_fields[entity]
    if normalize(field_name) in {normalize(name) for name in fields}:
        return None
    transform = field_entry.get("transform")
    if transform not in RENAMEABLE_TRANSFORMS and transform != "DIRECT":
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
    if transform == "DIRECT":
        # DIRECT carries no unit evidence. A qualifier that changes the
        # concept (`budget` -> `monthly_budget`) is still grounded by the
        # field's own name; a unit or identity suffix (`amount` ->
        # `amount_cents`, `author` -> `author_id`) is not, because the flag's
        # value may use the other unit.
        extra = normalize(candidates[0]).replace(normalize(field_name), "")
        if any(marker in extra for marker in (
                "cent", "id", "date", "time", "price", "amount", "cost",
                "quantity", "count")):
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
