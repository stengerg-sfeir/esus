"""Adopt step E's interface for every repository step H declares a second time.

Steps E and H both declare repositories — E as service contracts, H as
persistence ports — and they name them identically (`WineRepository`), because
that is the class the requirements describe. But H is told to *choose* the
interface and the method bodies, so it re-derives a method set that need not
match E's. Measured on the last run, every domain prompt diverged: gui's
`WineRepository` had `delete_wine` only in E and `save_wine`, `update_wine_price`,
`update_stock_quantity`, `get_wines_by_type` and `get_wines_by_country` only in H.

Two documents cannot describe one class two ways. The interaction adapters
resolve their targets against E, and H is what a code generator would implement,
so a divergence means the adapters call methods the implementation lacks.

E owns the interface: it is generated first and holds the contract the
requirements name. So a repository that E already declares adopts E's methods
verbatim and keeps what only H produces — the table, the primary key and the
indexes. This is the same principle as the closed grammars elsewhere in the
pipeline: the shared fact has one owner, so there is nothing to reconcile.
"""

import re

# Mirrors kernel.consistency.naming.normalize, which the checker uses to pair the
# two documents. tests/test_interfaces.py asserts the two agree, so a change to
# either is caught rather than silently producing a rule that never fires.
_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")


def normalize(identifier):
    """Comparable form of an interface name ('WineRepository' -> 'winerepository')."""
    return _NON_ALPHANUMERIC.sub("", str(identifier).lower())


def unify_repository_interfaces(ports, services, log):
    """Return `ports` with every doubly-declared repository taking E's methods.

    `ports` is the step-H document and `services` the step-E one. A repository
    whose interface no service declares is returned untouched, so a
    persistence-layer invention — 60's `CategoryRepository`, which E never
    declares because its requirements name services rather than repositories —
    keeps the method set step H chose.
    """
    repositories = ports.get("repositories") if isinstance(ports, dict) else None
    if not isinstance(repositories, list):
        return ports

    declared = _declared_interfaces(services)
    if not declared:
        return ports

    adopted = []
    replaced = 0
    for repository in repositories:
        service = _matching_service(repository, declared)
        if service is None:
            adopted.append(repository)
            continue
        interface = dict(repository)
        # E's spelling as well as E's methods: with both documents using one
        # name character for character, a generator can pair them without help.
        interface["interface_name"] = service["service_name"]
        interface["methods"] = service["methods"]
        adopted.append(interface)
        replaced += 1

    if log is not None and replaced:
        log.write(
            f"[ok] step persistence: {replaced} repository interface(s) adopted from "
            f"service_contracts, so both documents declare one method set"
        )
    return {**ports, "repositories": adopted}


def _declared_interfaces(services):
    """The services of step E that declare at least one method, keyed by name."""
    if not isinstance(services, list):
        return {}
    declared = {}
    for service in services:
        if not isinstance(service, dict):
            continue
        name = service.get("service_name")
        methods = service.get("methods")
        if name and isinstance(methods, list) and methods:
            declared[normalize(name)] = service
    return declared


def _matching_service(repository, declared):
    """The step-E service declaring this repository's interface, or None."""
    if not isinstance(repository, dict):
        return None
    return declared.get(normalize(repository.get("interface_name")))


def complete_missing_repositories(ports, services, log=None):
    """Add a persistence port for a repository only the service document has.

    A repair can add an entity to the surface after step H ran (library's
    `Author` command), so step E gains an `AuthorRepository` while the ports
    document still lists only Book/Member/Loan.  Adding a second entry with a
    different key spelling (or calling the service-contract completion on a
    ports list) creates duplicates; this copies the missing interface once,
    under the same `interface_name` the other document uses.
    """
    if not isinstance(ports, dict):
        return ports
    repositories = ports.get("repositories")
    if not isinstance(repositories, list):
        return ports
    existing = {
        normalize(repository.get("interface_name") or repository.get("service_name"))
        for repository in repositories
        if isinstance(repository, dict)
        and (repository.get("interface_name") or repository.get("service_name"))
    }
    added = []
    for service in services or []:
        if not isinstance(service, dict):
            continue
        name = service.get("service_name")
        if not isinstance(name, str) or not name.endswith("Repository"):
            continue
        if normalize(name) in existing:
            continue
        entity = name[:-len("Repository")]
        repositories.append({
            "entity": entity,
            "interface_name": name,
            "methods": service.get("methods") or [],
        })
        existing.add(normalize(name))
        added.append(name)
    if added and log is not None:
        log.write(
            f"[ok] step persistence: completed {len(added)} missing "
            f"repository port(s): {', '.join(added[:8])}")
    return ports


def merge_repository_methods(services, ports, log=None):
    """Add methods only step H discovered to the matching step-E repository.

    Mechanical repository shells give E the required CRUD methods, but custom
    aggregates are still discovered by step H.  E is written first, so H cannot
    hand them forward before execution; this merge keeps them in the service
    contract that code generation reads.  Existing E methods win on a name
    collision.
    """
    repositories = ports.get("repositories") if isinstance(ports, dict) else None
    if not isinstance(services, list) or not isinstance(repositories, list):
        return services
    declared = _declared_interfaces(services)
    added = 0
    for repository in repositories:
        if not isinstance(repository, dict):
            continue
        service = declared.get(normalize(repository.get("interface_name")))
        if service is None:
            continue
        methods = service.setdefault("methods", [])
        names = {
            method.get("name")
            for method in methods
            if isinstance(method, dict) and method.get("name")
        }
        for method in repository.get("methods") or ():
            if not isinstance(method, dict) or not method.get("name"):
                continue
            if method["name"] in names:
                continue
            methods.append(method)
            names.add(method["name"])
            added += 1
    if log is not None and added:
        log.write(
            f"[ok] step persistence: merged {added} custom repository method(s) "
            f"into service_contracts"
        )
    return services
