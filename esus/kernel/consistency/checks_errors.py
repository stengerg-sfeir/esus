"""Consistency checks for the application error registry (step E').

This is the one document whose entries another document references by name: a
contract method's `raises` list names an error from the registry. That makes two
opposite defects checkable — a name that is raised but never declared (a dangling
reference) and a name that is declared but never raised (a declaration nothing
uses) — and neither could be seen before the registry existed, because there was
no name to resolve against and no field to carry it.
"""

from kernel.consistency.methods import is_missing
from kernel.consistency.naming import normalize

# The verbs that mean a method brings a record into existence. A method that
# creates cannot then report that it failed to find what it is creating, so a
# create-like name raising the not-found error *of that same thing* is
# self-contradictory. The rule was written because the corpus produced it twice
# independently: inventory's `ProductRepository.create_product` and expenses'
# `ExpenseRepository.create_expense` both declared a `*NotFoundError` for the
# record they were making.
CREATE_VERBS = ("create", "add", "save", "insert", "register", "make", "new")

# The noun is compared, not just the verb, because `add` is ambiguous:
# `add_stock(product_id, ...)` must find the product it adds stock to, so its
# `ProductNotFoundError` is correct, while `add_product` creating one cannot.
# Matching `add_stock`'s subject ("stock") against the error's ("product") leaves
# the first alone and still catches the second.
NOT_FOUND_MARKER = "notfound"
# `Missing<Entity>Error` is the other way the corpus spells the same idea, and
# inventory and expenses each declared *both* spellings for one entity.
MISSING_MARKER = "missing"
ERROR_NAME_SUFFIXES = ("error", "exception")

# The verbs that mean a method looks a record up by its key. Such a method is
# where that record's not-found error belongs, which is what makes the rules
# below checkable rather than a judgement call.
READ_VERBS = ("read", "get", "find", "fetch", "load", "lookup")
KEY_MARKERS = ("byid", "byemail", "byname", "bysku", "byisbn", "bycode", "bykey", "bynumber")

# The built-ins an application error may derive from. Closed by the grammar, so a
# value outside this set means the document was hand-edited or produced by an
# older build rather than by the model.
BASE_ERRORS = (
    "LookupError",
    "ValueError",
    "KeyError",
    "RuntimeError",
    "PermissionError",
    "OSError",
    "TypeError",
    "Exception",
)


def check_errors(errors, report):
    """Validate the registry; return the declared names.

    An absent document returns nothing and says nothing: `loader` has already
    reported it as `missing_document`, and reporting the type here as well tells
    the reader the registry holds the wrong kind of value when in fact there is no
    registry at all — the same finding twice, the second time misleading.
    """
    if errors is None:
        return ()
    if not isinstance(errors, list):
        report.error("invalid_value", "errors should be a list")
        return ()

    names = []
    seen = set()
    for item in errors:
        if not isinstance(item, dict):
            report.error("invalid_value", "errors contains an entry that is not an object")
            continue
        name = item.get("name")
        if is_missing(name):
            report.error("invalid_identifier", "errors has an entry with no name")
            continue

        key = name.strip().lower()
        if key in seen:
            report.warning("duplicate_entry", f"errors: '{name}' is declared more than once")
        seen.add(key)
        names.append(name)

        _check_base(name, item.get("base"), report)
        _check_description(name, item.get("description"), report)

    return tuple(names)


def _check_base(name, base, report):
    if is_missing(base):
        report.warning("invalid_value", f"errors: '{name}' declares no base class")
        return
    if base not in BASE_ERRORS:
        report.warning(
            "unsupported_value",
            f"errors: '{name}' derives from '{base}', which is not one of {', '.join(BASE_ERRORS)}",
        )


def _check_description(name, description, report):
    if is_missing(description):
        report.warning(
            "empty_section",
            f"errors: '{name}' has no description — nothing says when it is raised",
        )


def check_raises(services, error_names, report):
    """Resolve every method's `raises` against the registry.

    An unregistered name is reported whichever way the document is wrong: either
    the method invents an error, or the registry is missing one it should hold.
    A registered error that no method raises is a **note**, not a defect — a class
    the generated program may still need for a failure raised outside the service
    layer — and it is only reported when services exist at all, because a program
    with no services (a CSV converter, whose errors belong to its CLI layer)
    would otherwise have every one of its errors called unused, which is true and
    useless.
    """
    declared = {name.strip().lower() for name in error_names}
    raised = set()
    has_services = False

    if isinstance(services, list):
        for service in services:
            if not isinstance(service, dict):
                continue
            owner = service.get("service_name")
            for method in service.get("methods") or []:
                if not isinstance(method, dict):
                    continue
                has_services = True
                for target in method.get("raises") or []:
                    label = f"{owner}.{method.get('name')}"
                    if not isinstance(target, str) or not target.strip():
                        report.warning(
                            "invalid_value",
                            f"service_contracts: {label} has an empty entry in raises",
                        )
                        continue
                    raised.add(target.strip().lower())
                    if target.strip().lower() not in declared:
                        report.warning(
                            "unknown_reference",
                            f"service_contracts: {label} raises '{target}', "
                            f"which no registered error declares",
                        )
                    elif is_contradictory_raise(method.get("name"), target):
                        report.warning(
                            "contradictory_raise",
                            f"service_contracts: {label} raises '{target}', but a method "
                            f"that creates a record cannot fail to find it",
                        )

    if not has_services:
        return
    for name in error_names:
        if name.strip().lower() not in raised:
            report.note(
                "unused_error",
                f"errors: '{name}' is declared but no method raises it",
            )


def is_contradictory_raise(method_name, error_name):
    """True when a create-like method claims to raise the not-found error of the
    very thing it creates.

    The test is on names because that is where the evidence is: the method's own
    name states what it brings into existence, and the error's name states what
    was not found. They have to agree for the pair to contradict itself.
    """
    created = _created_subject(method_name)
    if not created:
        return False
    absent = _absent_subject(error_name)
    return bool(absent) and created == absent


def _created_subject(method_name):
    """The noun a create-like method name claims to bring into existence."""
    if not isinstance(method_name, str):
        return None
    method = normalize(method_name)
    for verb in CREATE_VERBS:
        if method.startswith(verb) and len(method) > len(verb):
            return method[len(verb):]
    return None


def _absent_subject(error_name):
    """The noun a not-found error name says was missing, or None."""
    if not isinstance(error_name, str):
        return None
    name = normalize(error_name)
    if NOT_FOUND_MARKER not in name:
        return None
    for suffix in ERROR_NAME_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name.replace(NOT_FOUND_MARKER, "")


def _missing_subject(error_name):
    """The noun a `Missing<Entity>Error` name says was absent, or None.

    The corpus spells the same failure two ways, so both have to be read: a rule
    that knew only `NotFound` would treat `MissingCategoryError` and
    `CategoryNotFoundError` as unrelated names for one missing category.
    """
    absent = _absent_subject(error_name)
    if absent:
        return absent
    if not isinstance(error_name, str):
        return None
    name = normalize(error_name)
    for suffix in ERROR_NAME_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    if name.startswith(MISSING_MARKER) and len(name) > len(MISSING_MARKER):
        return name[len(MISSING_MARKER):]
    return None


def check_unreachable_not_found(errors, services, error_names, report):
    """A not-found error nothing raises while its own reader is declared.

    `unused_error` notes every declared error no method raises, and it is a note
    because the checker cannot tell a failure raised outside the service layer
    from one the service forgot to raise. This is the case it *can* tell: the
    document declares a method that looks that very thing up by its key, so the
    method is exactly where the error belongs, and nothing raising it means the
    lookup cannot report what the registry says it can. Measured on the corpus it
    finds inventory's `MissingProductError` (`get_product_by_id` raises nothing)
    and expenses' `MissingCategoryError` (`read_category_by_id` likewise), and
    stays silent on every error whose subject no method reads.
    """
    if not isinstance(services, list) or not services:
        return

    raised = set()
    readers = []
    for service in services:
        if not isinstance(service, dict):
            continue
        for method in service.get("methods") or []:
            if not isinstance(method, dict):
                continue
            name = method.get("name")
            if not isinstance(name, str):
                continue
            raised.update(
                target.strip().lower()
                for target in method.get("raises") or []
                if isinstance(target, str)
            )
            if _is_key_reader(name):
                readers.append(name)

    for name in error_names:
        subject = _missing_subject(name)
        if not subject or name.strip().lower() in raised:
            continue
        reader = next(
            (candidate for candidate in readers if subject in normalize(candidate)),
            None,
        )
        if reader is None:
            continue
        report.warning(
            "unreachable_error",
            f"errors: '{name}' is declared but no method raises it, while '{reader}' looks "
            f"that record up by its key — the error for a missing record belongs to the method "
            f"that reads it",
        )


def check_duplicate_error_subject(errors, error_names, report):
    """Two declared errors naming one missing thing.

    `CategoryNotFoundError` and `MissingCategoryError` are the same failure under
    two names, and a registry holding both makes the generator emit two exception
    classes for one condition. The check is exact because it compares what each
    name *says is absent*, not how it is spelled.
    """
    subjects = {}
    for name in error_names:
        subject = _missing_subject(name)
        if subject:
            subjects.setdefault(subject, []).append(name)
    for subject, names in sorted(subjects.items()):
        if len(names) > 1:
            report.warning(
                "duplicate_error_subject",
                f"errors: {', '.join(names)} all name the same missing record ({subject}) — "
                f"one failure should have one error type",
            )


def _is_key_reader(method_name):
    """True when a method name reads one record by a key."""
    normalized = normalize(method_name)
    if not normalized.startswith(READ_VERBS):
        return False
    return any(marker in normalized for marker in KEY_MARKERS)
