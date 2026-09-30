"""Method and parameter checks shared by service contracts and repositories.

Both documents carry the same shape (a list of methods, each with named and
typed parameters), so the same contract is enforced in one place.
"""

from kernel.consistency.naming import normalize

PLACEHOLDER_VALUES = {"", "none", "null", "nil", "n/a", "na", "todo", "tbd", "undefined"}


def is_placeholder(value):
    """True for the junk values the extractor leaves in names and types."""
    return normalize(value) in PLACEHOLDER_VALUES


def is_missing(value):
    """True for empty strings and non-strings."""
    return not isinstance(value, str) or not value.strip()


def collect_methods(container):
    """Return the method objects of a service or repository entry."""
    methods = container.get("methods")
    if not isinstance(methods, list):
        return []
    return [method for method in methods if isinstance(method, dict)]


def param_names(method):
    """Return every declared parameter name of a method."""
    params = method.get("params")
    if not isinstance(params, list):
        return []
    return [param["name"] for param in params if isinstance(param, dict) and param.get("name")]


def check_method_list(methods, owner_label, report):
    """Validate the method block of one service or repository."""
    if not isinstance(methods, list) or not methods:
        report.warning("empty_section", f"{owner_label} declares no methods")
        return

    seen_names = set()
    for method in methods:
        if not isinstance(method, dict):
            report.error("invalid_value", f"{owner_label} contains a method that is not an object")
            continue
        _check_method(method, owner_label, seen_names, report)


def _check_method(method, owner_label, seen_names, report):
    name = method.get("name")
    if is_missing(name) or is_placeholder(name):
        report.error("invalid_identifier", f"{owner_label} has a method with no name")
        return

    if normalize(name) in seen_names:
        report.warning("duplicate_entry", f"{owner_label} declares method '{name}' more than once")
    seen_names.add(normalize(name))

    description = method.get("description")
    if is_missing(description) or is_placeholder(description):
        report.warning("placeholder_value", f"{owner_label}.{name} has no description")

    return_type = method.get("return_type")
    if is_missing(return_type):
        report.warning("placeholder_value", f"{owner_label}.{name} has no return_type")

    _check_params(method, owner_label, name, report)


def _check_params(method, owner_label, name, report):
    params = method.get("params")
    if not isinstance(params, list):
        report.error("invalid_value", f"{owner_label}.{name} params should be a list")
        return

    seen_names = set()
    for param in params:
        if not isinstance(param, dict):
            report.error("invalid_value", f"{owner_label}.{name} contains a parameter that is not an object")
            continue

        param_name = param.get("name")
        param_type = param.get("type")
        if is_missing(param_name) or is_placeholder(param_name) or is_placeholder(param_type):
            report.warning(
                "placeholder_value",
                f"{owner_label}.{name} has a placeholder parameter "
                f"(name={param_name!r}, type={param_type!r})",
            )
            continue

        if normalize(param_name) in seen_names:
            report.warning(
                "duplicate_entry",
                f"{owner_label}.{name} declares parameter '{param_name}' more than once",
            )
        seen_names.add(normalize(param_name))
