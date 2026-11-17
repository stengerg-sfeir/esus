"""Agreement between the two documents that declare the same repository.

Step E writes repositories as *services* in `service_contracts`; step H writes
them as *ports* in `persistence_ports`. Both call them `XxxRepository`, and
nothing in either document's own checks relates them: the adapter checks resolve
against `service_contracts`, while a code generator would implement
`persistence_ports`. A divergence therefore means the two halves of the
architecture describe different classes under one name — the adapters would
target methods the implementation does not have.

Only same-named interfaces are compared, matched on the checker's `normalize`,
so a `WineService` is never confused with a `WineRepository`.
"""

from kernel.consistency.methods import collect_methods
from kernel.consistency.naming import normalize


def check_interface_agreement(documents, report):
    """Report every repository whose declared methods differ between documents."""
    services = documents.get("service_contracts")
    ports = documents.get("persistence_ports")
    if not isinstance(services, list) or not isinstance(ports, dict):
        return

    repositories = ports.get("repositories")
    if not isinstance(repositories, list):
        return

    declared = {}
    for service in services:
        if isinstance(service, dict) and service.get("service_name"):
            declared[normalize(service["service_name"])] = service

    for repository in repositories:
        if not isinstance(repository, dict):
            continue
        service = declared.get(normalize(repository.get("interface_name")))
        if service is None:
            continue

        in_service = _method_names(service)
        in_ports = _method_names(repository)
        if set(in_service) == set(in_ports):
            continue

        report.warning(
            "inconsistent_interface",
            f"{repository.get('interface_name')} ({repository.get('entity')}) is declared with "
            f"different methods in service_contracts and persistence_ports: only in "
            f"service_contracts {_summary(in_service, in_ports)}, only in persistence_ports "
            f"{_summary(in_ports, in_service)}",
        )


def _method_names(container):
    """Map each normalised method name to the spelling the document declares.

    Keying by the normalised form compares the two documents leniently, while the
    value keeps the message readable: `get_all_wines`, not `getallwines`.
    """
    names = {}
    for method in collect_methods(container):
        name = method.get("name")
        if isinstance(name, str) and name.strip():
            names.setdefault(normalize(name), name)
    return names


def _summary(source, other):
    """The declared names present in `source` and absent from `other`."""
    return sorted(source[key] for key in source if key not in other) or "none"
