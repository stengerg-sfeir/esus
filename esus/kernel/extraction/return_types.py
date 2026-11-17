"""Replace the generic `dict[str, object]` return type with the entity it stands for.

A signature is a specification, not a body: a generator emitting
`create_category(...) -> dict[str, object]` produces a repository whose declared
return type contradicts the entity the method operates on, and no generation can
repair that without overriding the contract it was handed.

**Measured before writing this:** 28 of the corpus's 225 methods carry the
generic spelling — 17 in step E and 11 in step H — and every one is in
**inventory**. `gui`, `expenses`, `60`, `library` and the two no-domain prompts
name their entities (`List[Book]`, `Wine`, `Loan | None`) throughout. So this is
a narrow repair for one prompt's habit, not a systemic signature problem.

**Where the entity comes from**, in order, with every choice logged:

1. **The method's own name**, when it mentions exactly one entity —
   `add_product` returns a `Product` whether or not the service is named for one.
   This is the reading that covers `InventoryService`, whose name resolves to no
   entity at all (`inventory` is neither `Category` nor `Product`).
2. **The holder**: `repositories[].entity` for a port, or the service name with
   its role suffix stripped (`CategoryRepository` -> `Category`) for a contract.
   Used when the method name mentions no entity (`read_all_categories`) or more
   than one.
3. **Nothing**, and the method is left alone with a log line: `restock` and
   `low_stock_report` name no entity and sit on a service that names none, so
   there is no honest answer to record.

A method name that mentions a *different* entity from its holder is logged as a
**conflict** as well as repaired: `CategoryRepository.get_products_by_category`
returns products, not categories, and a generator implementing the declared
signature would have returned the wrong type. That is a defect in the document
which this repair surfaces rather than hides.

**The entity is read from the name *before* its `_by_` marker.**
`get_products_by_category` returns the products matching a category, so the
object is `get_products` and the `_by_` tail is the filter. Without that cut the
name mentions both `Product` and `Category`, and deferring to the holder answered
`Category` — measured, and wrong, which is how this rule was found. The
convention is already load-bearing in this codebase:
`methods._missing_arguments_reason` reads `_by_<key>` suffixes for the same
reason.

The test is containment on the normalized names, and it does **not** fold
plurals: `Product` is found inside `products`, while `Category` is *not* found
inside `categories`, so a plural-named entity falls through to the holder. Every
decision — repaired, skipped, or disagreeing with the holder — is logged, so a
wrong one appears in `run.log` rather than silently in the JSON.

**What this does not touch.** 60 spells its entities in lowercase plural
(`orders`, `invoices`) while its methods return `Order`, `List[Invoice]`. That is
pre-existing (`BLIND_SPOTS.md` §7) and is a naming defect rather than a
return-type one; rewriting only the repaired methods to the model's spelling
would leave two spellings of one entity inside one document.
"""

from kernel.consistency.naming import MATCH_NONE, match_known, normalize, strip_role_suffix

# The spellings that mean "a record of the holder's entity". Both bracket styles
# appear in the corpus (`List[X]` and `list[X]`): the prompt fixes neither.
GENERIC_RETURNS = {
    "dict[str, object]": "{entity}",
    "Dict[str, object]": "{entity}",
    "dict[str,object]": "{entity}",
    "list[dict[str, object]]": "list[{entity}]",
    "List[dict[str, object]]": "List[{entity}]",
    "dict[str, object] | None": "{entity} | None",
    "Optional[dict[str, object]]": "Optional[{entity}]",
}


def repair_contract_returns(services, models, log):
    """Step E: every generic return names the entity its method is about."""
    repaired, summary = _repair(services, models, _contract_entity)
    if log is not None:
        _log(log, "contracts", summary)
    return repaired


def repair_port_returns(ports, models, log):
    """Step H: same, with each repository's own `entity` as the holder answer."""
    if not isinstance(ports, dict):
        return ports
    repositories = ports.get("repositories")
    if not isinstance(repositories, list):
        return ports
    repaired, summary = _repair(repositories, models, _repository_entity)
    if log is not None:
        _log(log, "persistence", summary)
    return {**ports, "repositories": repaired}


def _repair(holders, models, holder_entity):
    """Rewrite every holder's generic returns; return `(holders, summary)`."""
    names = _entity_names(models)
    if not isinstance(holders, list) or not names:
        return holders, {"changed": 0, "skipped": [], "conflicts": []}

    rewritten = []
    changed = 0
    skipped = []
    conflicts = []
    for holder in holders:
        if not isinstance(holder, dict) or not isinstance(holder.get("methods"), list):
            rewritten.append(holder)
            continue
        declared = holder_entity(holder, names)
        corrected = []
        for method in holder.get("methods") or []:
            replacement = (
                GENERIC_RETURNS.get(method.get("return_type"))
                if isinstance(method, dict)
                else None
            )
            if replacement is None:
                corrected.append(method)
                continue

            named = _single_entity_in(method.get("name"), names)
            entity = named or declared
            if entity is None:
                skipped.append(f"{_label(holder)}.{method.get('name')}")
                corrected.append(method)
                continue
            if named and declared and normalize(named) != normalize(declared):
                conflicts.append(
                    f"{_label(holder)}.{method.get('name')} returns {named} "
                    f"but its holder is {declared}"
                )
            corrected.append({**method, "return_type": replacement.format(entity=entity)})
            changed += 1
        rewritten.append({**holder, "methods": corrected})

    return rewritten, {"changed": changed, "skipped": skipped, "conflicts": conflicts}


def _log(log, step, summary):
    if summary["changed"]:
        log.write(
            f"[ok] step {step}: {summary['changed']} generic return type(s) now name their entity"
        )
    for conflict in summary["conflicts"]:
        log.write(f"[!] step {step}: {conflict}")
    for skipped in summary["skipped"]:
        log.write(
            f"[!] step {step}: {skipped} returns a bare object and names no entity — left as it is"
        )


def _label(holder):
    return holder.get("interface_name") or holder.get("service_name") or "?"


def _entity_names(models):
    if not isinstance(models, list):
        return []
    return [
        model.get("name")
        for model in models
        if isinstance(model, dict) and model.get("name")
    ]


# The marker separating a method's object from the key it filters on.
BY_MARKER = "_by_"


def _object_part(method_name):
    """The method name up to its first `_by_`, which is the part naming the object.

    `get_products_by_category` returns products, not categories: the `_by_` tail
    states the filter. Cutting there is what stops the name from mentioning two
    entities and deferring to the holder — which answered `Category` for this
    method and was wrong.
    """
    if not isinstance(method_name, str):
        return ""
    position = method_name.lower().find(BY_MARKER)
    return method_name if position < 0 else method_name[:position]


def _single_entity_in(method_name, names):
    """The one entity the object part of a method name mentions, or None.

    None means none or several — `get_category_products` mentions two and is left
    to the holder rather than decided by position, which would be a guess dressed
    as a rule.
    """
    part = _object_part(method_name)
    if not part:
        return None
    normalized = normalize(part)
    mentioned = [name for name in names if normalize(name) in normalized]
    return mentioned[0] if len(mentioned) == 1 else None


def _repository_entity(repository, names):
    """The entity a port declares, as the data model spells it."""
    entity = repository.get("entity")
    if not isinstance(entity, str) or not entity.strip():
        return None
    tier, resolved = match_known(entity, names)
    return resolved if tier is not MATCH_NONE else None


def _contract_entity(service, names):
    """The entity a contract's service name is about, or None.

    `CategoryRepository` strips to `Category`; `InventoryService` strips to
    `inventory`, which names no entity, so its methods are decided from their own
    names or left alone.
    """
    name = service.get("service_name")
    if not isinstance(name, str) or not name.strip():
        return None
    tier, resolved = match_known(strip_role_suffix(name), names)
    return resolved if tier is not MATCH_NONE else None
