#!/usr/bin/env python3
"""Ask the human for behavior facts a method needs and no document states.

The generator can check a body against the API it was shown, but it cannot
know that returning a book means setting `return_date` to now, incrementing
one field and saving two repositories. Putting that knowledge in the
generator would make it library-shaped; putting it in the requirements would
make every test a wording test. It belongs in a human-confirmed record beside
the documents.

This review reads the existing `out/...` documents (no model run needed),
proposes the domain-neutral parts it can see — fields changed by verb, model
created, declared-error preconditions, the repository calls that save them —
and asks the human only for the values an English sentence does not settle:
the amount, the date/status value, the order, and any condition behind an
error such as `InvalidReturnDateError`. The answers are written to
`method_contracts.json`, stamped with the requirements sha; `generator.py`
reads them on every run. Skipping a required value records nothing, so the
stub stays and the question reopens.

Usage:
    python review_contracts.py out/library          # ask open contracts
    python review_contracts.py out/library --list   # show proposals only

This is deliberately a separate pass from extraction. `extract_arch.py
--chat` runs it at the end when asked; a full extraction is not required to
create the file for an existing tree.
"""

import ast
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import generator  # noqa: E402
from kernel.consistency.loader import load_requirements  # noqa: E402
from kernel.consistency.naming import normalize  # noqa: E402
from kernel.extraction import contracts as contract_rules  # noqa: E402
from kernel.extraction.decisions import requirements_sha  # noqa: E402

DATE_TYPES = ("date", "datetime")
DATE_NAME_HINTS = ("date", "month", "year", "day", "time", "created",
                   "updated")
BOOL_TYPES = ("bool", "boolean")

# The verbs that mean "write this field". The noun after the verb is matched
# against model fields; the parser never sees a domain name of its own.
EFFECT_VERBS = (
    (r"increments?|increases?|raises?", "increment"),
    (r"decrements?|decreases?|reduces?|removes?|subtracts?", "decrement"),
    (r"sets?|updates?|changes?|toggles?", "set"),
)
CREATE_VERBS = r"creates?|adds?|records?"
# English number words are not field names; make quantity/qty one term so a
# factory description ("stock quantity") can reach a `stock_qty` field.
SYNONYMS = (("quantities", "qty"), ("quantity", "qty"),
            ("count", "qty"), ("copies", "copies"))


def _fields(ctx):
    """`[(class, field, type, field_dict)]` for every model."""
    rows = []
    for model in ctx.get("models") or []:
        class_name = model.get("name")
        for field in model.get("fields") or []:
            if isinstance(field, dict) and field.get("name"):
                rows.append((class_name, field["name"],
                             (field.get("type") or "").strip().lower(),
                             field))
    return rows


def _params(method):
    return [param["name"] for param in method.get("params") or []
            if isinstance(param, dict) and isinstance(param.get("name"), str)]


def _synonym_text(text):
    lowered = str(text).lower()
    for word, replacement in SYNONYMS:
        lowered = re.sub(rf"\b{re.escape(word)}\b", replacement, lowered)
    return lowered


def _match_field(noun, fields, entity_hint=None):
    """The model field a noun phrase names, or None.

    The longest field whose normalized name appears in the phrase wins, so
    "is_active status" reaches `is_active` rather than the shorter `status`
    (which belongs to another model). An entity named in the phrase scopes the
    search to that model, and boolean fields can match their predicate word
    ("active status" -> `is_active`). A field name that contains the phrase
    also matches ("copies" -> `available_copies`).
    """
    phrase = normalize(_synonym_text(noun))
    if not phrase:
        return None
    best = None
    candidates = [row for row in fields
                  if not entity_hint or row[0] == entity_hint]
    for class_name, field_name, field_type, field in candidates:
        field_norm = normalize(field_name)
        if not field_norm:
            continue
        aliases = [field_norm]
        if field_type in BOOL_TYPES:
            for prefix in ("is", "has", "can", "was", "were", "should"):
                if field_norm.startswith(prefix) and len(field_norm) > len(prefix) + 1:
                    aliases.append(field_norm[len(prefix):])
                    break
        scores = [len(alias) for alias in aliases if alias in phrase]
        scores += [len(phrase) for alias in aliases
                   if len(phrase) >= 4 and phrase in alias]
        if not scores:
            continue
        score = max(scores)
        if best is None or score > best[0]:
            best = (score, class_name, field_name, field_type, field)
    if best is None:
        return None
    _score, class_name, field_name, field_type, field = best
    return class_name, field_name, field_type, field


def _match_class(noun, ctx):
    """The model class a noun phrase names, or None."""
    phrase = normalize(noun)
    best = None
    for name in ctx.get("entity_names") or []:
        normalized = normalize(name)
        if normalized and normalized in phrase:
            if best is None or len(normalized) > len(normalize(best)):
                best = name
    return best


def _repo_for(ctx, entity):
    for repo in ctx.get("repositories") or []:
        if repo.get("entity") == entity:
            return repo
    return None


def _repo_call(ctx, entity, prefix):
    """`Interface.method` for the entity's create/update, or None."""
    repo = _repo_for(ctx, entity)
    if not repo:
        return None
    wanted = prefix + str(entity).lower()
    methods = [method for method in repo.get("methods") or []
               if isinstance(method, dict) and method.get("name")]
    for method in methods:
        if method["name"] == wanted:
            return f"{repo['interface_name']}.{method['name']}"
    for method in methods:
        if method["name"].startswith(prefix):
            return f"{repo['interface_name']}.{method['name']}"
    # A repository owns one entity, so its plain `create`/`update` is the
    # call; without this a contract lost its create and its save, and the
    # method was not wrapped in a transaction.
    for method in methods:
        if method["name"] == prefix.rstrip("_"):
            return f"{repo['interface_name']}.{method['name']}"
    return None


def _write_call(ctx, entity, role):
    if role == "repository":
        return "self._store.update"
    return _repo_call(ctx, entity, "update_")


def _create_call(ctx, entity, role):
    if role == "repository":
        return "self._store.add"
    return _repo_call(ctx, entity, "create_")


def _invariant_values(ctx, entity, field):
    """The documented vocabulary for a field, from an invariant, or []."""
    pattern = re.compile(
        rf"\b{re.escape(entity)}\.{re.escape(field)}\s+must\s+be\s+one\s+of\b",
        re.I)
    for invariant in ctx.get("invariants") or []:
        text = invariant.get("text") if isinstance(invariant, dict) else ""
        match = pattern.search(text or "")
        if not match:
            continue
        tail = text[match.end():].strip().rstrip(".")
        list_match = re.match(r"(\[[^\]]+\])", tail)
        if list_match:
            try:
                values = ast.literal_eval(list_match.group(1))
            except (ValueError, SyntaxError):
                values = []
            if isinstance(values, (list, tuple)):
                return [str(value) for value in values]

        # Invariants are also commonly written as prose, for example
        # `Loan.status must be one of 'active', 'returned', 'overdue'`.
        # Extract the stated values instead of requiring Python-list syntax.
        quoted = re.findall(r"(['\"])(.*?)\1", tail)
        if quoted:
            return [value for _quote, value in quoted]

        # Accept a plainly enumerated vocabulary too (`one of active, returned
        # or overdue`), while avoiding arbitrary trailing prose.
        bare = re.sub(r"^the following\s*:?\s*", "", tail, flags=re.I)
        candidates = re.split(r",\s*|\s+(?:or|and)\s+", bare)
        candidates = [item.strip(" `'“”\t") for item in candidates]
        if candidates and all(re.fullmatch(r"[\w.-]+", item)
                              for item in candidates):
            return candidates
    return []


def _date_fields(ctx, entity, exclude=None):
    rows = []
    for class_name, field_name, field_type, field in _fields(ctx):
        if class_name != entity or field_name == exclude:
            continue
        if field_type in DATE_TYPES or (
                field_type in ("str", "string")
                and any(hint in normalize(field_name)
                        for hint in DATE_NAME_HINTS)):
            rows.append((class_name, field_name))
    return rows


def _value_choices(ctx, entity, field_name):
    """`[(label, value)]` for a set effect, from facts, not a name guess."""
    fields = [(cls, name, ftype, field)
              for cls, name, ftype, field in _fields(ctx)
              if cls == entity and name == field_name]
    field_type = fields[0][2] if fields else ""
    choices = []
    if field_type in DATE_TYPES or any(hint in normalize(field_name)
                                      for hint in DATE_NAME_HINTS):
        choices.append(("now", "now"))
        for cls, other in _date_fields(ctx, entity, exclude=field_name):
            choices.append((f"{cls.lower()}.{other}", f"{cls.lower()}.{other}"))
    elif field_type in BOOL_TYPES:
        choices += [(f"not {field_name}", f"not {field_name}"),
                    ("True", True), ("False", False)]
    else:
        for value in _invariant_values(ctx, entity, field_name):
            choices.append((value, value))
    return choices


def _effect_params(field_name, params, op):
    """Return parameters whose names can plausibly supply this field value."""
    field_norm = normalize(field_name)
    field_terms = set(re.findall(r"[a-z0-9]+", str(field_name).lower()))
    generic_terms = {"date", "time", "value", "new", "old", "current",
                     "previous", "updated", "created"}
    meaningful_terms = field_terms - generic_terms
    quantity_terms = {"copies", "count", "qty", "quantity", "stock"}
    amount_terms = quantity_terms | {"amount", "delta"}
    quantity_field = bool(field_terms & quantity_terms)
    relevant = []
    for name in params:
        param_norm = normalize(name)
        param_terms = set(re.findall(r"[a-z0-9]+", str(name).lower()))
        matches_name = bool(
            param_norm and field_norm
            and (param_norm == field_norm or field_norm in param_norm
                 or (len(param_norm) >= 4 and param_norm in field_norm)))
        matches_term = bool(meaningful_terms & param_terms)
        matches_amount = (op in ("increment", "decrement")
                          and quantity_field
                          and bool(param_terms & amount_terms))
        if matches_name or matches_term or matches_amount:
            relevant.append(name)
    return relevant


def _effect_questions(ctx, index, effect, params):
    target = effect["target"]
    variable, field_name = target.split(".", 1)
    entity = next((name for name in ctx.get("entity_names") or []
                   if name.lower() == variable), variable.capitalize())
    choices = []
    prompt = ""
    if effect["op"] in ("increment", "decrement"):
        prompt = (f"By how much should `{target}` "
                  f"{effect['op']}?")
        choices = [("1", "1")]
        if isinstance(effect.get("by"), str):
            choices.insert(0, (effect["by"], effect["by"]))
        choices += [(name, name) for name in _effect_params(
            field_name, params, effect["op"])]
    else:
        prompt = f"What value should `{target}` be set to?"
        choices = _value_choices(ctx, entity, field_name)
        choices += [(name, name) for name in _effect_params(
            field_name, params, effect["op"])]
    # Deduplicate while preserving order.
    seen, unique = set(), []
    for label, value in choices:
        key = (label, repr(value))
        if key not in seen:
            seen.add(key)
            unique.append((label, value))
    if not unique:
        return {
            "id": f"effect:{index}", "kind": "text", "required": True,
            "prompt": prompt,
            "apply": "value" if effect["op"] == "set" else "by",
        }
    return {
        "id": f"effect:{index}", "kind": "choice", "required": True,
        "prompt": prompt, "choices": unique,
        "apply": "value" if effect["op"] == "set" else "by",
    }


def _error_description(ctx, error):
    for item in ctx.get("errors") or []:
        if isinstance(item, dict) and item.get("name") == error:
            description = item.get("description")
            if isinstance(description, str) and description.strip():
                return description.strip()
    return ""


def _invalid_error_has_input(ctx, error, method, effects):
    """Whether an ``Invalid<Field>Error`` can inspect a value this method has.

    A method that only accepts `member_id` and `book_id` cannot receive an
    invalid loan status to validate. A scalar parameter, a typed model
    parameter, or an explicit effect on the named field can supply the value;
    without one, asking for a validation condition would invent an input the
    method does not have. Unknown error concepts remain open for human review.
    """
    match = re.match(r"(?i)^Invalid(.+?)Error$", str(error).rsplit(".", 1)[-1])
    if not match:
        return True
    concept = normalize(match.group(1))
    if not concept:
        return True

    params = [param for param in method.get("params") or []
              if isinstance(param, dict)]
    param_names = [normalize(param.get("name") or "") for param in params]
    if any(name and (name in concept or concept in name)
           for name in param_names):
        return True

    matching_fields = [
        (class_name, field_name)
        for class_name, field_name, _field_type, _field in _fields(ctx)
        if normalize(field_name) and normalize(field_name) in concept
    ]
    # When the error names an entity, use that entity to avoid treating a
    # same-named field on another model as its validation target.
    entity_matches = [
        row for row in matching_fields
        if normalize(row[0]) in concept
    ]
    if entity_matches:
        matching_fields = entity_matches
    if not matching_fields:
        # The error concept has no modeled field to trace; preserve the
        # question because the method may validate an unmodeled input such as
        # a query string or file format.
        return True

    for class_name, field_name in matching_fields:
        field_norm = normalize(field_name)
        if field_norm in param_names:
            return True
        class_norm = normalize(class_name)
        # An ID parameter lets the method inspect that existing entity's
        # state, even though the validated field is not itself an argument.
        if class_norm and f"{class_norm}id" in param_names:
            return True
        for param in params:
            param_type = normalize(param.get("type") or "")
            if class_norm and class_norm in param_type:
                return True
        for effect in effects or []:
            if not isinstance(effect, dict):
                continue
            target = str(effect.get("target") or "")
            if "." not in target:
                continue
            target_entity, target_field = target.rsplit(".", 1)
            if (normalize(target_field) == field_norm
                    and normalize(target_entity) == class_norm):
                return True
    return False


def _obvious_preconditions(ctx, raises, fields, method, effects=None):
    """Preconditions the declared errors imply, plus the open ones.

    `NotFound` means the named entity exists; `InsufficientCopies` means the
    copies field is positive; `InvalidStockQty` means a `qty` parameter is
    positive. Other errors stay open unless an invalid-value error names a
    field this method cannot receive, inspect by entity ID, or explicitly
    change.
    """
    obvious, open_errors = [], []
    params = set(_params(method))
    for error in raises or []:
        name = str(error).rsplit(".", 1)[-1]
        match = re.match(r"(\w+?)NotFoundError$", name)
        if match:
            entity = match.group(1)
            obvious.append({"check": f"{entity.lower()} exists",
                            "error": name, "raise_when": "false"})
            continue
        if "InsufficientCopies" in name:
            copies = [row for row in fields
                      if "copies" in normalize(row[1])
                      or "stock" in normalize(row[1])
                      or "quantity" in normalize(row[1])]
            if copies:
                entity, field_name = copies[0][0], copies[0][1]
                obvious.append({
                    "check": f"{entity.lower()}.{field_name} > 0",
                    "error": name,
                    "raise_when": "false",
                })
                continue
        if "InvalidStockQty" in name and "qty" in params:
            obvious.append({"check": "qty > 0", "error": name,
                            "raise_when": "false"})
            continue
        if (name.lower().startswith("invalid")
                and not _invalid_error_has_input(ctx, name, method, effects)):
            # Do not ask for a validation condition on an invalid value this
            # method cannot receive or explicitly change. It can still
            # propagate the lower-level error if another method raises it.
            continue
        open_errors.append(name)
    return obvious, open_errors


def _related_reads(ctx, holder, text):
    """Fields of a related model that a repository method's own words name.

    A search described as matching "author name" must read the related
    `Author`'s `name`; comparing the query with the `author_id` key matches
    nothing a person typed. The relation comes from the foreign keys of the
    holder's own model, and the field only from the text: an entity named
    without one of its fields ("author") proposes nothing, because there is
    no way to tell which field was meant.
    """
    repo = next((item for item in ctx.get("repositories") or []
                 if item.get("interface_name") == holder), None)
    if not repo:
        return []
    models = {model.get("name"): model for model in ctx.get("models") or []
              if isinstance(model, dict)}
    own = models.get(repo.get("entity"))
    if not own:
        return []
    lowered = str(text).lower()
    found, seen = [], set()
    for fk_field in own.get("fields") or []:
        link = fk_field.get("foreign_key") if isinstance(fk_field, dict) else None
        target = link.get("target_entity") if isinstance(link, dict) else None
        related = models.get(target)
        if not related or target == repo.get("entity"):
            continue
        for field in related.get("fields") or []:
            if not isinstance(field, dict) or not field.get("name") \
                    or field.get("primary_key"):
                continue
            words = r"[\s_-]+".join(
                re.escape(word) for word in field["name"].lower().split("_"))
            if not re.search(
                    rf"\b{re.escape(str(target).lower())}(?:'s|s)?[\s_-]+"
                    rf"{words}\b", lowered):
                continue
            key = (target, field["name"])
            if key in seen:
                continue
            seen.add(key)
            item = {"entity": target, "field": field["name"],
                    "via": f"{repo.get('entity')}.{fk_field['name']}"}
            related_repo = _repo_for(ctx, target)
            if related_repo and related_repo.get("interface_name"):
                item["repository"] = related_repo["interface_name"]
            found.append(item)
    return found


def _derived_values(ctx, method, text):
    """Declared values of the returned entity's fields that the text names.

    A read described as returning "overdue" loans reports `Loan.status` as
    `overdue` while the stored value stays `active`. The values come from
    the model's own vocabulary (`_invariant_values`); the entity comes from
    the declared return type; the text only picks which value is meant. The
    human decides whether the records must carry it, so a filter that merely
    mentions a value ("active members") is dropped at the question.
    """
    returned = str(method.get("return_type") or "")
    entity = next((name for name in ctx.get("entity_names") or []
                   if re.search(rf"\b{re.escape(name)}\b", returned)), None)
    if not entity:
        return []
    found = []
    for class_name, field_name, _type, field in _fields(ctx):
        if class_name != entity or field.get("primary_key"):
            continue
        for value in _invariant_values(ctx, entity, field_name):
            if re.search(rf"\b{re.escape(str(value))}\b", text, re.I):
                found.append({"target": f"{entity.lower()}.{field_name}",
                              "value": value})
    return found


def _state_transition(ctx, holder, method, text):
    """A generic state-transition binding/effect/precondition proposal.

    The description is the only source of the transition: `from pending to
    confirmed`, `from pending or confirmed to cancelled`. The entity and the
    `status`/`state` field come from the model; the key parameter and the
    repository `read_one` come from the signature. No domain noun is hardcoded.
    """
    entity = _match_class(holder, ctx) or _match_class(text, ctx)
    if not entity:
        return None
    fields = [(name, ftype, field) for cls, name, ftype, field in _fields(ctx)
              if cls == entity]
    state_field = next((name for name, _ftype, _field in fields
                        if name.lower() in ("status", "state")), None)
    if state_field is None:
        return None
    match = re.search(
        r"\bfrom\s+(?:the\s+)?([a-z_]+(?:\s*(?:,|or)\s+[a-z_]+)*)\s+to\s+"
        r"(?:the\s+)?([a-z_]+)", text, re.IGNORECASE)
    starts, target = [], None
    if match:
        starts = [part.strip().strip(".'") for part in
                  re.split(r"\s*(?:,|or)\s*", match.group(1).lower())
                  if part.strip()]
        target = match.group(2).strip().strip(".'").lower()
    else:
        # "the order status is updated to 'confirmed'" is the same transition
        # without the source state spelled as `from ... to ...`.
        updated = re.search(
            r"\b(?:status\s+(?:is\s+)?(?:updated|set|changed)|"
            r"(?:updates?|sets?|changes?)\s+(?:the\s+)?(?:order\s+)?status)"
            r"\s+to\s+['\"]?([a-z_]+)", text, re.IGNORECASE)
        if updated:
            target = updated.group(1).strip(".'").lower()
            source = re.search(r"\b(?:a|an)\s+([a-z_]+)\s+order\b",
                               text, re.IGNORECASE)
            if source:
                starts = [source.group(1).lower()]
    if not target:
        return None
    params = _params(method)
    key_param = next((param for param in params if param.endswith("_id")), None)
    repo = _repo_for(ctx, entity)
    if key_param is None or repo is None:
        return None
    read_one = next((item.get("name") for item in repo.get("methods") or []
                     if isinstance(item, dict)
                     and normalize(item.get("name") or "") == "readone"), None)
    if read_one is None:
        return None
    raises = [str(name).rsplit(".", 1)[-1]
              for name in (method.get("raises") or [])]
    not_found = next((name for name in raises if name.endswith("NotFoundError")), None)
    state_error = next((name for name in raises
                        if not name.endswith("NotFoundError")), None)
    binding = entity.lower()
    binding_record = {
        "name": binding,
        "repository": repo.get("interface_name"),
        "method": read_one,
        "args": [key_param],
    }
    if not_found:
        binding_record["error"] = not_found
    effect = {
        "target": f"{binding}.{state_field}",
        "op": "set",
        # A status vocabulary is string data; quote it so the closed
        # contract compiler can distinguish it from a parameter name.
        "value": repr(target),
        "write": _repo_call(ctx, entity, "update_"),
    }
    already = next((name for name in raises
                    if normalize(f"Already{target}") in normalize(name)),
                   None)
    if starts:
        if len(starts) == 1:
            check = f"{binding}.{state_field} == {starts[0]!r}"
        else:
            check = (f"{binding}.{state_field} in "
                     f"({', '.join(repr(item) for item in starts)})")
        precondition = {"check": check, "raise_when": "false"}
    elif already:
        # `OrderAlreadyConfirmedError` means the target state is forbidden;
        # the check is the state that triggers it, so raise_when is true.
        precondition = {
            "check": f"{binding}.{state_field} == {target!r}",
            "raise_when": "true",
            "error": already,
        }
    else:
        precondition = None
    if precondition is not None and state_error:
        precondition.setdefault("error", state_error)
    return {
        "entity": entity,
        "binding": binding_record,
        "effect": effect,
        "precondition": precondition,
    }


def _stock_reservation_effect(ctx, role, text):
    """A generic `reserve stock` description as a decrement contract effect.

    The field name comes from the model (any numeric field whose name contains
    `stock`), the entity from that model, and the amount from the related
    `quantity` the prose names. The exact loop remains model-written; the
    contract tells the body what must change.
    """
    if role != "service" or "stock" not in text.lower():
        return None
    if not re.search(r"\b(reserv|decreas|reduc|deduct)", text, re.IGNORECASE):
        return None
    for class_name, field_name, field_type, field in _fields(ctx):
        if "stock" not in normalize(field_name):
            continue
        if field_type not in ("int", "integer", "float", "double",
                              "decimal", "number"):
            continue
        return {
            "target": f"{class_name.lower()}.{field_name}",
            "op": "decrement",
            "by": "quantity",
            "write": _repo_call(ctx, class_name, "update_"),
        }
    return None


def _collection_create(ctx, method):
    """A collection parameter's related entity, when the model names it."""
    for param in method.get("params") or []:
        if not isinstance(param, dict) or not param.get("name"):
            continue
        name = str(param["name"])
        if not name.endswith("s") or len(name) < 4:
            continue
        singular = name[:-1].rstrip("_")
        entity = next((item for item in ctx.get("entity_names") or []
                       if normalize(item) == normalize(singular)), None)
        if not entity:
            continue
        call = _create_call(ctx, entity, "service")
        if call:
            return {"class": entity, "call": call}
    return None


def _record_create(ctx, method):
    """A method named `record_*` returning an entity is a creation."""
    name = normalize(method.get("name") or "")
    if not name.startswith("record"):
        return None
    returns = str(method.get("return_type") or "")
    entity = next((item for item in ctx.get("entity_names") or []
                   if re.search(rf"\b{re.escape(item)}\b", returns)), None)
    if not entity:
        return None
    call = _create_call(ctx, entity, "repository")
    return {"class": entity, "call": call} if call else {"class": entity}


def add_inferred_record_creates(output_dir):
    ctx = generator.load_context(str(output_dir))
    records, _dropped = contract_rules.load_method_contracts(
        str(output_dir), load_requirements(str(output_dir)))
    changed = 0
    for group in (ctx.get("repositories") or [], ctx.get("services") or []):
        for holder in group:
            if not isinstance(holder, dict):
                continue
            name = holder.get("interface_name") or holder.get("service_name")
            for method in holder.get("methods") or []:
                if not isinstance(method, dict) or not method.get("name"):
                    continue
                create = _record_create(ctx, method)
                if not create:
                    continue
                record = next((item for item in records
                               if item.get("holder") == name
                               and item.get("method") == method["name"]), None)
                if record is None:
                    record = {"holder": name, "method": method["name"],
                              "decided_by": "inferred", "effects": [],
                              "creates": [], "bindings": [], "reads": [],
                              "derives": [], "preconditions": [], "order": [],
                              "forbid": []}
                    records.append(record)
                creates = record.setdefault("creates", [])
                if not any(item.get("class") == create["class"] for item in creates):
                    creates.append(create)
                    changed += 1
    if changed:
        contract_rules.save_method_contracts(str(output_dir), records)
    return changed


def add_inferred_collection_creates(output_dir):
    """Persist a collection parameter's create contract on existing methods.

    `place_order(customer_id, order_items)` names the related `OrderItem`
    collection; the review can derive the create call from the signature and
    the model, without a domain noun in the generator. The body still has to
    create one row per item, which the LLM pass then checks against the
    contract.
    """
    ctx = generator.load_context(str(output_dir))
    records, _dropped = contract_rules.load_method_contracts(
        str(output_dir), load_requirements(str(output_dir)))
    changed = 0
    for service in ctx.get("services") or []:
        if not isinstance(service, dict):
            continue
        holder = service.get("service_name")
        for method in service.get("methods") or []:
            if not isinstance(method, dict) or not method.get("name"):
                continue
            create = _collection_create(ctx, method)
            if not create:
                continue
            record = next((item for item in records
                           if item.get("holder") == holder
                           and item.get("method") == method["name"]), None)
            if record is None:
                record = {"holder": holder, "method": method["name"],
                          "decided_by": "inferred", "effects": [], "creates": [],
                          "bindings": [], "reads": [], "derives": [],
                          "preconditions": [], "order": [], "forbid": []}
                records.append(record)
            creates = record.setdefault("creates", [])
            if not any(item.get("class") == create["class"] for item in creates):
                creates.append(create)
                changed += 1
    if changed:
        contract_rules.save_method_contracts(str(output_dir), records)
    return changed


def _propose(ctx, holder, method, role, requirement):
    """One proposal from the method's description/requirement, or None."""
    description = method.get("description") or ""
    text = " ".join(part for part in (description, requirement) if part)
    fields = _fields(ctx)
    params = _params(method)
    effects, creates = [], []
    bindings = []
    seen_effects, seen_creates = set(), set()
    transition = _state_transition(ctx, holder, method, text) if role == "service" else None

    def add_effect(entity, field_name, op, write):
        key = (f"{entity.lower()}.{field_name}", op)
        if key in seen_effects:
            return
        seen_effects.add(key)
        item = {"target": f"{entity.lower()}.{field_name}", "op": op}
        if op in ("increment", "decrement"):
            item["by"] = "1"
        if write:
            item["write"] = write
        effects.append(item)

    for clause in re.split(r"[,;]|\band\b|\.", text):
        clause = clause.strip()
        if not clause:
            continue
        for verb, op in EFFECT_VERBS:
            match = re.search(rf"\b(?:{verb})\s+(.+)$", clause, re.I)
            if not match:
                continue
            noun = match.group(1).strip().strip(".")
            if op in ("increment", "decrement"):
                noun = re.split(r"\bby\b", noun, maxsplit=1)[0].strip()
            found = _match_field(noun, fields, _match_class(noun, ctx))
            if found:
                entity, field_name = found[0], found[1]
                # Repository update IDs identify the row to load; they are
                # never mutable effects. Model the same rule generically for
                # any field explicitly marked as a primary key, including
                # fixtures whose key is not named ``id``.
                field = found[3]
                if field.get("primary_key") or normalize(field_name) == "id":
                    continue
                add_effect(entity, field_name, op,
                           _write_call(ctx, entity, role))
                break
        match = re.search(
            rf"\b(?:{CREATE_VERBS})\s+(?:a\s+|an\s+|the\s+|new\s+)?(.+)$",
            clause, re.I)
        if match:
            entity = _match_class(match.group(1).strip().strip("."), ctx)
            if entity:
                call = _create_call(ctx, entity, role)
                key = (entity, call)
                if key not in seen_creates:
                    seen_creates.add(key)
                    creates.append({"class": entity, "call": call} if call
                                   else {"class": entity})
    if transition:
        target = transition["effect"]["target"]
        if not any(effect.get("target") == target for effect in effects):
            effects.append(transition["effect"])
        bindings.append(transition["binding"])
    stock_effect = _stock_reservation_effect(ctx, role, text)
    if stock_effect and not any(
            effect.get("target") == stock_effect["target"]
            and effect.get("op") == "decrement" for effect in effects):
        effects.append(stock_effect)
    reads = _related_reads(ctx, holder, text) if role == "repository" else []
    derives = [] if effects or creates else _derived_values(ctx, method, text)
    if not effects and not creates and not reads and not derives:
        return None

    preconditions, open_errors = _obvious_preconditions(
        ctx, method.get("raises") or [], fields, method, effects)
    if transition:
        if transition.get("precondition"):
            preconditions.append(transition["precondition"])
            # The state error is already represented by this concrete check;
            # do not also ask for an abstract expression for the same class.
            open_errors = [error for error in open_errors
                           if error != transition["precondition"].get("error")]
    questions = []
    if preconditions:
        questions.append({
            "id": "keep_preconditions", "kind": "choice", "required": True,
            "prompt": "Keep the preconditions implied by the declared errors?",
            "choices": [("keep", "keep"), ("drop", "drop")],
            "apply": "keep_preconditions",
        })
    for index, effect in enumerate(effects):
        question = _effect_questions(ctx, index, effect, params)
        question["effect"] = effect["target"]
        if transition and effect.get("target") == transition["effect"]["target"]:
            value = transition["effect"]["value"]
            choices = question.get("choices") or []
            if not any(choice[1] == value for choice in choices):
                choices = [(str(value), value)] + choices
            if choices:
                question["kind"] = "choice"
                question["choices"] = choices
        questions.append(question)
    if creates:
        questions.append({
            "id": "keep_creates", "kind": "choice", "required": True,
            "prompt": "Keep the proposed create call(s)?",
            "choices": [("keep", "keep"), ("drop", "drop")],
            "apply": "keep_creates",
        })
    if reads:
        shown = ", ".join(f"`{item['entity']}.{item['field']}`"
                          for item in reads)
        questions.append({
            "id": "keep_reads", "kind": "choice", "required": True,
            "prompt": f"The description names {shown} (a related model); "
                      "must the body read it?",
            "choices": [("keep", "keep"), ("drop", "drop")],
            "apply": "keep_reads",
        })
    if derives:
        shown = ", ".join(f"`{item['target']}` = {item['value']!r}"
                          for item in derives)
        questions.append({
            "id": "keep_derives", "kind": "choice", "required": True,
            "prompt": f"The description names {shown}; must the returned "
                      "records carry it (derived, never saved)?",
            "choices": [("keep", "keep"), ("drop", "drop")],
            "apply": "keep_derives",
        })
    for error in open_errors:
        description = _error_description(ctx, error)
        prompt = f"What Python condition should raise `{error}`?"
        if description:
            prompt += f" The error description says: {description}"
        prompt += (" (enter a Python boolean expression, not prose; "
                   "type 'skip' to allow the operation with no check)")
        questions.append({
            "id": f"precondition:{error}", "kind": "text", "required": False,
            "prompt": prompt,
            "error": error, "apply": "precondition",
        })
    if creates and effects:
        writes = []
        for effect in effects:
            if effect.get("write") and effect["write"] not in writes:
                writes.append(effect["write"])
        if writes:
            questions.append({
                "id": "order", "kind": "choice", "required": True,
                "prompt": "Must the create happen before the update(s)?",
                "choices": [("create first", "create_first"),
                            ("update first", "update_first")],
                "apply": "order", "writes": writes,
                "create": creates[0].get("call") or "create",
            })
    return {
        "holder": holder, "method": method.get("name") or "?",
        "role": role, "entity": method.get("entity"),
        "description": description, "requirement": requirement,
        "effects": effects, "creates": creates, "bindings": bindings,
        "reads": reads, "derives": derives,
        "preconditions": preconditions, "order": [], "forbid": [],
        "open_preconditions": open_errors,
        "questions": questions,
    }


def collect_contracts(output_dir):
    """`(proposals, context)` for stubs without a current contract."""
    ctx = generator.load_context(output_dir)
    requirements = load_requirements(output_dir)
    stats = {"source": output_dir, "implemented": 0, "stubs": 0,
             "stub_reasons": [], "prog": os.path.basename(output_dir)}
    files = generator.render_program(ctx, stats)
    existing, _dropped = contract_rules.load_method_contracts(
        output_dir, requirements)
    decided = {(record.get("holder"), record.get("method"))
               for record in existing}
    services = {}
    for service in ctx.get("services") or []:
        for method in service.get("methods") or []:
            if isinstance(method, dict) and method.get("name"):
                services[(service.get("service_name"), method["name"])] = method
    repos = {}
    for repo in ctx.get("repositories") or []:
        for method in repo.get("methods") or []:
            if isinstance(method, dict) and method.get("name"):
                repos[(repo.get("interface_name"), method["name"])] = method
    proposals = []
    for filename, role in (("services.py", "service"),
                           ("repositories.py", "repository")):
        for _start, _end, info in generator.find_stub_spans(
                files.get(filename) or ""):
            holder = info.get("cls")
            method_name = generator._stub_method(info)
            if (holder, method_name) in decided:
                continue
            method = (services if role == "service" else repos).get(
                (holder, method_name))
            if method is None:
                continue
            requirement = generator._requirements_line(
                requirements, method_name)
            proposal = _propose(ctx, holder, method, role, requirement)
            if proposal is not None:
                proposals.append(proposal)
    context = {"prompt_sha": requirements_sha(requirements)}
    return proposals, context


def _describe_effect(effect):
    target, op = effect["target"], effect["op"]
    if op == "set" and "value" in effect:
        detail = f" = {effect['value']}"
    elif op in ("increment", "decrement") and "by" in effect:
        detail = f" by {effect['by']}"
    else:
        detail = " = ?" if op == "set" else " by ?"
    suffix = f" via {effect['write']}" if effect.get("write") else ""
    return f"{op} {target}{detail}{suffix}"


def describe_proposal(index, total, proposal, questions=True):
    lines = [
        f"--- contract {index}/{total} ---",
        f"CONTRACT for {proposal['holder']}.{proposal['method']}",
    ]
    if proposal["description"]:
        lines.append(f"  {proposal['description']}")
    if proposal["requirement"]:
        lines.append(f"  requirement: {proposal['requirement']}")
    if proposal["effects"]:
        lines.append("  proposed effects:")
        lines += [f"    - {_describe_effect(effect)}"
                  for effect in proposal["effects"]]
    if proposal["creates"]:
        lines.append("  proposed creates:")
        for create in proposal["creates"]:
            call = f" via {create['call']}" if create.get("call") else ""
            lines.append(f"    - {create.get('class')}{call}")
    if proposal.get("derives"):
        lines.append("  proposed derived values (never saved):")
        for item in proposal["derives"]:
            lines.append(f"    - {item['target']} = {item['value']!r}")
    if proposal.get("reads"):
        lines.append("  proposed reads:")
        for item in proposal["reads"]:
            lines.append(f"    - {item['entity']}.{item['field']} "
                         f"(related through {item['via']})")
    if proposal["preconditions"]:
        lines.append("  preconditions from declared errors:")
        for item in proposal["preconditions"]:
            when = item.get("raise_when")
            suffix = f" (raise when {when})" if when else ""
            lines.append(
                f"    - {item['check']} -> {item['error']}{suffix}")
    if questions:
        for question in proposal["questions"]:
            if question["kind"] == "choice":
                choices = ", ".join(label for label, _value
                                    in question["choices"])
                lines.append(f"  {question['prompt']} [{choices}]")
            else:
                lines.append(f"  {question['prompt']}")
    return lines


def _ask_choice(prompt, choices, input_fn):
    shown = ", ".join(f"{number}) {label}" for number, (label, _value)
                      in enumerate(choices, start=1))
    try:
        answer = input_fn(f"{prompt} [{shown}] or skip: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if answer.lower() in ("", "skip", "s"):
        return None
    if answer.isdigit():
        index = int(answer) - 1
        if 0 <= index < len(choices):
            return choices[index][1]
        return None
    for label, value in choices:
        if answer.lower() == label.lower():
            return value
    return None


def ask_proposal(proposal, input_fn=input, out_fn=print):
    """Ask every open question; return the answers dict, or None on skip."""
    answers = {}
    for question in proposal["questions"]:
        if question["kind"] == "choice":
            answer = _ask_choice(question["prompt"], question["choices"],
                                 input_fn)
        else:
            while True:
                out_fn(question["prompt"])
                try:
                    answer = input_fn("> ").strip()
                except (EOFError, KeyboardInterrupt):
                    answer = ""
                if answer.lower() in ("", "skip", "s"):
                    answer = None
                    break
                if question.get("apply") == "precondition":
                    try:
                        ast.parse(answer, mode="eval")
                    except SyntaxError:
                        out_fn("Enter a valid Python expression, or type 'skip'.")
                        continue
                break
        if answer is None and question.get("required", True):
            return None
        answers[question["id"]] = answer
    return answers


def _finalize(proposal, answers, prompt_sha, ctx):
    """Turn the confirmed answers into a generator-ready record."""
    effects = []
    for index, effect in enumerate(proposal["effects"]):
        item = dict(effect)
        value = answers.get(f"effect:{index}")
        if value is None:
            return None
        if item["op"] in ("increment", "decrement"):
            item["by"] = value
        else:
            item["value"] = value
        effects.append(item)
    creates = []
    if answers.get("keep_creates", "keep") != "drop":
        creates = [dict(create) for create in proposal["creates"]
                   if create.get("call")]
    derives = []
    if answers.get("keep_derives", "keep") != "drop":
        derives = [dict(item) for item in proposal.get("derives") or []]
    reads = []
    if answers.get("keep_reads", "keep") != "drop":
        reads = [dict(item) for item in proposal.get("reads") or []]
    bindings = [dict(item) for item in proposal.get("bindings") or []]
    preconditions = []
    if answers.get("keep_preconditions", "keep") != "drop":
        preconditions = [dict(item) for item in proposal["preconditions"]]
    for question in proposal["questions"]:
        if question.get("apply") != "precondition":
            continue
        answer = answers.get(question["id"])
        if answer:
            preconditions.append({"check": answer, "error": question["error"],
                                  "raise_when": "true"})
    order = []
    writes = []
    for effect in effects:
        if effect.get("write") and effect["write"] not in writes:
            writes.append(effect["write"])
    if creates and writes:
        choice = answers.get("order")
        create_call = creates[0].get("call")
        if choice == "create_first" and create_call:
            order = ["preconditions", create_call] + writes
        elif choice == "update_first" and create_call:
            order = ["preconditions"] + writes + [create_call]
    forbid = []
    by_lower = {name.lower(): name for name in ctx.get("entity_names") or []}
    for effect in effects:
        if effect["op"] != "set" or str(effect.get("value")) != "now":
            continue
        target = effect["target"]
        variable, field_name = target.split(".", 1)
        entity = by_lower.get(variable, variable.capitalize())
        for _cls, other in _date_fields(ctx, entity, exclude=field_name):
            forbid.append({
                "target": target,
                "reads": f"{variable}.{other}",
                "message": f"`{target}` is set to now, not another date field",
            })
    record = {
        "holder": proposal["holder"],
        "method": proposal["method"],
        "decided_by": "user",
        "effects": effects,
        "creates": creates,
        "bindings": bindings,
        "reads": reads,
        "derives": derives,
        "preconditions": preconditions,
        "order": order,
        "forbid": forbid,
    }
    if prompt_sha is not None:
        record["requirements_sha"] = prompt_sha
    return record


def add_inferred_stock_effects(output_dir):
    """Append a stock reservation/decrement effect to existing contracts.

    This is the review's deterministic consequence of a prose invariant:
    `reserves the stock ... by the quantity` names a field (from the model)
    and an operation (decrement), not a free-form behavior. It is stored in
    the normal contract sidecar, so regeneration sees it and the body is
    checked against it.
    """
    ctx = generator.load_context(str(output_dir))
    records, _dropped = contract_rules.load_method_contracts(
        str(output_dir), load_requirements(str(output_dir)))
    changed = 0
    for service in ctx.get("services") or []:
        if not isinstance(service, dict):
            continue
        holder = service.get("service_name")
        for method in service.get("methods") or []:
            if not isinstance(method, dict) or not method.get("name"):
                continue
            effect = _stock_reservation_effect(
                ctx, "service", method.get("description") or "")
            if effect is None:
                continue
            record = next((item for item in records
                           if item.get("holder") == holder
                           and item.get("method") == method["name"]), None)
            if record is None:
                record = {"holder": holder, "method": method["name"],
                          "decided_by": "inferred",
                          "effects": [], "creates": [], "bindings": [],
                          "reads": [], "derives": [], "preconditions": [],
                          "order": [], "forbid": []}
                records.append(record)
            effects = record.setdefault("effects", [])
            if any(item.get("target") == effect["target"]
                   and item.get("op") == "decrement" for item in effects):
                continue
            effects.append(effect)
            changed += 1
    if changed:
        contract_rules.save_method_contracts(str(output_dir), records)
    return changed


def run_review(output_dir, input_fn=input, out_fn=print):
    """Ask every open contract; return `(asked, answered)`."""
    proposals, context = collect_contracts(output_dir)
    if not proposals:
        out_fn("no open method contracts — nothing to decide")
        return 0, 0
    records, _dropped = contract_rules.load_method_contracts(
        output_dir, load_requirements(output_dir))
    ctx = generator.load_context(output_dir)
    answered = 0
    for number, proposal in enumerate(proposals, start=1):
        for line in describe_proposal(number, len(proposals), proposal,
                                      questions=False):
            out_fn(line)
        answers = ask_proposal(proposal, input_fn, out_fn)
        if answers is None:
            out_fn("skipped — left open")
            continue
        record = _finalize(proposal, answers, context["prompt_sha"], ctx)
        if record is None:
            out_fn("skipped — a required value is unanswered")
            continue
        records = [item for item in records
                   if (item.get("holder"), item.get("method"))
                   != (record["holder"], record["method"])]
        records.append(record)
        answered += 1
    contract_rules.save_method_contracts(output_dir, records)
    out_fn(f"answered {answered} of {len(proposals)}; contracts in "
           f"{contract_rules.METHOD_CONTRACTS_NAME}")
    return len(proposals), answered


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    list_only = "--list" in args
    args = [a for a in args if a != "--list"]
    if len(args) != 1:
        print(__doc__.splitlines()[0], file=sys.stderr)
        print("usage: python review_contracts.py OUT_DIR [--list]",
              file=sys.stderr)
        return 2
    if list_only:
        proposals, _context = collect_contracts(args[0])
        if not proposals:
            print("no open method contracts — nothing to decide")
            return 0
        for number, proposal in enumerate(proposals, start=1):
            for line in describe_proposal(number, len(proposals), proposal):
                print(line)
        return 0
    run_review(args[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
