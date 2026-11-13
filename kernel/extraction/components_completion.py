"""Complete the CRUD entities of step D from the data model.

Step D is a model call, and its ``crud_services`` list can omit an entity the
data model already declares — prompt_60's prose components call dropped
``OrderItem`` while keeping its two foreign keys.  A persisted entity with a
foreign key is not a judgement call: losing its repository also loses the
queries that its parent services call, and the generated program fails at run
time even though every document is structurally valid.

This pass adds the missing entry with the smallest useful operation set
(create, read_one, read_all).  It never touches an entity step D declared, and
it runs only when the components document says persistence is required.  The
repository itself, its entity mapping and its child query are then completed
by the existing mechanical passes.
"""

from kernel.consistency.naming import normalize

CHILD_OPERATIONS = ("create", "read_one", "read_all")


def complete_crud_entities(components, data_models, log=None):
    """Add one CRUD entry per persisted entity with a foreign key."""
    if not isinstance(components, dict):
        return components
    persistence = components.get("persistence")
    if not isinstance(persistence, dict) or not persistence.get("required"):
        return components
    declared = set()
    for item in components.get("crud_services") or []:
        if isinstance(item, dict) and isinstance(item.get("entity"), str):
            declared.add(normalize(item["entity"]))
    added = []
    for model in data_models or []:
        if not isinstance(model, dict) or not isinstance(model.get("name"), str):
            continue
        name = model["name"]
        if normalize(name) in declared:
            continue
        fields = [field for field in (model.get("fields") or [])
                  if isinstance(field, dict)]
        if not any(field.get("foreign_key") for field in fields):
            continue
        components.setdefault("crud_services", []).append({
            "entity": name,
            "operations": list(CHILD_OPERATIONS),
        })
        declared.add(normalize(name))
        added.append(name)
    if added and log is not None:
        log.write(
            f"[ok] step components: added {len(added)} persisted dependent "
            f"entity(ies) to crud_services: {', '.join(added)}"
        )
    return components
