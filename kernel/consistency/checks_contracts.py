"""Consistency checks for the service contracts.

Every method block is validated through kernel.consistency.methods; this module
adds the service-level checks (unique, non-empty service names).
"""

from kernel.consistency.methods import check_method_list, is_missing, is_placeholder


def check_service_contracts(services, report):
    """Validate service_contracts: service names plus every method block."""
    if services is None:
        return
    if not services:
        report.error("empty_section", "service_contracts: list is empty")
        return

    seen = set()
    for service in services:
        if not isinstance(service, dict):
            report.error("invalid_value", "service_contracts: an entry is not an object")
            continue
        name = service.get("service_name")
        if is_missing(name) or is_placeholder(name):
            report.error("invalid_identifier", "service_contracts: a service has no service_name")
            continue
        if name.strip().lower() in seen:
            report.warning("duplicate_entry", f"service_contracts: service '{name}' is declared more than once")
        seen.add(name.strip().lower())

    check_methods(services, report)


def check_methods(services, report):
    """Validate the method block of every declared service."""
    for service in services:
        if not isinstance(service, dict):
            continue
        label = service.get("service_name") or "<unnamed service>"
        check_method_list(service.get("methods"), f"service_contracts: {label}", report)
