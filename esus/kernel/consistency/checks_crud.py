"""Whether the operations a component claims are actually provided by a method.

`components.crud_services` says which operations each entity supports, and
nothing checked that any method provides them: the operations were validated
for spelling only, against a five-word list. Measured on the corpus, every
entity that declares `delete` has no method for it — inventory's two
repositories and library's four all declare `delete` and none of them can
delete anything.

The check is confined to the two operations whose names map unambiguously onto
methods: `create` (a method named create_*/add_*/insert_*/save_*), and `delete`
(delete_*/remove_*/drop_*). `read_one` and `read_all` share prefixes with each
other and with domain queries, and `update` is routinely folded into a create —
so those three are left alone rather than guessed at, which is why the rule
under-reports rather than over-reports.
"""

from kernel.consistency.methods import collect_methods
from kernel.consistency.naming import normalize, strip_role_suffix

# The method-name prefixes that implement each operation.
OP_PREFIXES = {
    "create": ("create", "add", "insert", "save", "new", "make", "register"),
    "delete": ("delete", "remove", "drop", "destroy", "discard"),
}


def check_crud_coverage(components, documents, report):
    """Report each claimed operation that no reachable method implements."""
    if not isinstance(components, dict):
        return
    crud_services = components.get("crud_services")
    if not isinstance(crud_services, list):
        return

    for entry in crud_services:
        if not isinstance(entry, dict):
            continue
        entity = entry.get("entity")
        operations = entry.get("operations")
        if not isinstance(entity, str) or not isinstance(operations, list):
            continue

        methods = _methods_for(entity, documents)
        if not methods:
            # No repository is reachable for this entity, so there is nothing to
            # compare against; `no_repository` already covers that case.
            continue

        for operation in operations:
            prefixes = OP_PREFIXES.get(operation)
            if prefixes is None:
                continue
            if any(name.lower().startswith(prefixes) for name in methods):
                continue
            report.warning(
                "unmet_crud_operation",
                f"components.crud_services: '{entity}' declares '{operation}' but no method "
                f"of {sorted(methods)} does it",
            )


def _methods_for(entity, documents):
    """Every method declared for `entity`, from its repository or its services."""
    names = set()
    wanted = normalize(entity)

    services = documents.get("service_contracts")
    if isinstance(services, list):
        for service in services:
            if not isinstance(service, dict) or not service.get("service_name"):
                continue
            if strip_role_suffix(service["service_name"]) == wanted:
                names |= _declared_names(service)

    ports = documents.get("persistence_ports")
    repositories = ports.get("repositories") if isinstance(ports, dict) else None
    if isinstance(repositories, list):
        for repository in repositories:
            if isinstance(repository, dict) and normalize(repository.get("entity")) == wanted:
                names |= _declared_names(repository)

    return names


def _declared_names(container):
    return {
        method["name"]
        for method in collect_methods(container)
        if isinstance(method.get("name"), str) and method["name"].strip()
    }
