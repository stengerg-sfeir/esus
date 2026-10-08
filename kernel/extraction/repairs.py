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

This is the same move as `dedupe.py` (§9.7): a *removal* of something that
contradicts the rest of the document, never the invention or rewriting of a
value. Every decision is logged, and the predicates are imported from
`kernel.consistency` — the checker is the single definition of each
contradiction, so a repair and the rule that reports it can never disagree. Run
after every step that produces the documents it touches, and before writing.
"""

import re

from kernel.consistency import checks_adapters, checks_errors


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
