"""Align verifier concepts with extracted documents without changing outcomes.

The verifier may call a concept `Client` while the extracted model calls it
`Customer`, or `PurchaseOrder` while the prompt says `order`. Treating every
such difference as a verifier hallucination or an extraction defect is wrong.
This module classifies the difference before binding:

- aligned       exact concept;
- alias         same concept, different spelling;
- ambiguous     several plausible concepts;
- coverage_gap  prompt names it, no extracted candidate;
- invented      no prompt evidence and no extracted candidate;
- under_specified prompt cannot decide what the concept means.

Only names and setup structure are aligned here. Expected outcomes are never
taken from the extracted documents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from kernel import codegen
from kernel.consistency.naming import normalize

_GENERIC = frozenset({
    "entity", "record", "row", "item", "thing", "object", "data", "value",
    "number", "result", "response", "file", "input", "output",
})

_FIELD_ALIASES = {
    "phone": ("phone_number", "phonenumber"),
    "phonenumber": ("phone",),
    "stockquantity": ("stock_qty", "quantity"),
    "stockqty": ("stock_quantity", "quantity"),
    "quantity": ("qty", "stock_quantity", "stock_qty"),
    "name": ("title", "description"),
    "title": ("name", "description"),
    "sku": ("code", "product_code"),
    "maxcapacity": ("maximum_capacity",),
    "maximumcapacity": ("max_capacity",),
    "totalstock": ("stock_quantity",),
}


@dataclass
class Alignment:
    status: str
    canonical: str | None
    score: float
    evidence: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)


def _models(docs):
    return [model for model in docs.get("models") or []
            if isinstance(model, dict) and model.get("name")]


def _fields(model):
    return [field.get("name") for field in model.get("fields") or []
            if isinstance(field, dict) and field.get("name")]


def _field_set(model):
    return {normalize(name) for name in _fields(model)}


def _singular(value):
    value = normalize(value)
    if value.endswith("ies") and len(value) > 4:
        return value[:-3] + "y"
    if value.endswith("s") and not value.endswith("ss") and len(value) > 3:
        return value[:-1]
    return value


def _tokens(value):
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value or ""))
    return {_singular(word) for word in re.findall(r"[A-Za-z0-9]+", text)
            if word}


def _prompt_mentions(term, text):
    if not isinstance(term, str) or not term.strip():
        return False
    wanted = normalize(term)
    if wanted and wanted in normalize(text):
        return True
    tokens = _tokens(text)
    return any(token and token in tokens for token in _tokens(term))


def _name_score(alias, model_name):
    left, right = normalize(alias), normalize(model_name)
    if left == right:
        return 10.0
    if _singular(alias) == _singular(model_name):
        return 8.0
    left_tokens, right_tokens = _tokens(alias), _tokens(model_name)
    overlap = left_tokens & right_tokens
    if overlap:
        return 5.0 + min(2.0, float(len(overlap)))
    if left and (left in right or right in left):
        return 4.0
    return 0.0


def align_entity(alias, fields, source, requirements, docs):
    """Align one verifier entity alias against the extracted models."""
    if not isinstance(alias, str) or not alias.strip():
        return Alignment("under_specified", None, 0.0,
                         ["empty entity alias"])
    fields = {normalize(item) for item in fields or () if isinstance(item, str)}
    original_count = max(1, len(fields))
    expanded = set(fields)
    for name in list(fields):
        for field_alias in _FIELD_ALIASES.get(name, ()):
            expanded.add(normalize(field_alias))
    scored = []
    for model in _models(docs):
        name = model["name"]
        score = _name_score(alias, name)
        model_fields = _field_set(model)
        if fields and model_fields:
            # Alias expansion only helps matching; it must not dilute the
            # fraction by adding alternative names to the denominator.
            overlap = len(expanded & model_fields) / original_count
            score += 4.0 * overlap
        if _prompt_mentions(name, source):
            score += 1.0
        if score > 0:
            scored.append((score, name))
    scored.sort(key=lambda item: (-item[0], item[1]))
    if not scored:
        evidence_alias = _prompt_mentions(alias, source) or _prompt_mentions(
            alias, requirements)
        if normalize(alias) in _GENERIC or not evidence_alias:
            return Alignment("invented", None, 0.0,
                             [f"no extracted entity matches {alias!r}",
                              "no prompt evidence for the alias"])
        return Alignment("coverage_gap", None, 0.0,
                         [f"prompt mentions {alias!r}",
                          "no extracted entity matches it"])
    best_score, best_name = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    if best_score >= 8.0 and best_score - second >= 2.0:
        status = "aligned" if normalize(alias) == normalize(best_name) else "alias"
        return Alignment(status, best_name, best_score,
                         [f"name/fields match {best_name}",
                          f"score {best_score:.1f}"],
                         [name for _score, name in scored[1:4]])
    if best_score >= 4.0 and best_score - second >= 2.0:
        return Alignment("alias", best_name, best_score,
                         [f"weak name but strong field overlap with {best_name}",
                          f"score {best_score:.1f}"],
                         [name for _score, name in scored[1:4]])
    if best_score >= 4.0:
        return Alignment("ambiguous", best_name, best_score,
                         [f"multiple plausible entities; best is {best_name}",
                          f"score {best_score:.1f}, runner-up {second:.1f}"],
                         [name for _score, name in scored[:4]])
    if _prompt_mentions(alias, source) or _prompt_mentions(alias, requirements):
        return Alignment("coverage_gap", None, best_score,
                         [f"prompt mentions {alias!r}",
                          "no sufficiently close extracted entity"])
    return Alignment("invented", None, best_score,
                     [f"no prompt evidence for {alias!r}",
                      "no sufficiently close extracted entity"])


def align_field(model_name, field_name, source, requirements, docs):
    if not isinstance(field_name, str) or not field_name.strip():
        return Alignment("under_specified", None, 0.0, ["empty field name"])
    model = next((item for item in _models(docs)
                  if normalize(item.get("name")) == normalize(model_name)), None)
    if model is None:
        return Alignment("coverage_gap", None, 0.0,
                         [f"entity {model_name!r} is not extracted"])
    names = {normalize(name): name for name in _fields(model)}
    wanted = normalize(field_name)
    if wanted in names:
        return Alignment("aligned", names[wanted], 10.0,
                         [f"{model_name}.{names[wanted]} exists"])
    for alias in _FIELD_ALIASES.get(wanted, ()):
        if normalize(alias) in names:
            return Alignment("alias", names[normalize(alias)], 8.0,
                             [f"{field_name!r} aliases {alias!r}"])
    if wanted + "id" in names:
        return Alignment("alias", names[wanted + "id"], 7.0,
                         [f"{field_name!r} maps to the id field"])
    if _prompt_mentions(field_name, source) or _prompt_mentions(
            field_name, requirements):
        return Alignment("coverage_gap", None, 0.0,
                         [f"prompt mentions field {field_name!r}",
                          f"not declared on {model_name}"])
    return Alignment("invented", None, 0.0,
                     [f"no prompt evidence for field {field_name!r}",
                      f"not declared on {model_name}"])


def _methods(docs):
    found = []
    for key, name_key in (("services", "service_name"),
                          ("repos", "interface_name")):
        for holder in docs.get(key) or []:
            if not isinstance(holder, dict):
                continue
            holder_name = holder.get(name_key)
            for method in holder.get("methods") or []:
                if isinstance(method, dict) and method.get("name"):
                    found.append((holder_name, method))
    return found


def _dedupe_methods(items):
    seen = set()
    out = []
    for holder, method in items:
        key = (holder, method.get("name"))
        if key in seen:
            continue
        seen.add(key)
        out.append((holder, method))
    return out


_ACTION_STOP = frozenset({
    "add", "create", "list", "read", "all", "search", "filter", "get",
    "update", "delete", "remove", "view", "check", "the", "on", "to", "of",
    "for", "by", "with",
})


def _singular_token(token):
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("s") and not token.endswith(("ss", "us", "is")) \
            and len(token) > 3:
        return token[:-1]
    return token


def _last_action_token(action):
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(action or ""))
    tokens = [normalize(word) for word in re.split(r"[^A-Za-z0-9]+", text)
              if normalize(word) and normalize(word) not in _ACTION_STOP]
    return _singular_token(tokens[-1]) if tokens else ""


def _method_mentions(method, token):
    if not token:
        return True
    name = normalize(method.get("name"))
    if token in name or _singular(token) in name:
        return True
    params = normalize(" ".join(
        str(param.get("name") or "") for param in method.get("params") or []
        if isinstance(param, dict)))
    return bool(params) and (token in params or _singular(token) in params)


def _action_score(action, holder, method):
    """Rank a method by how specifically its name matches the action."""
    action_tokens = _tokens(action)
    method_tokens = _tokens(method.get("name"))
    holder_tokens = _tokens(holder)
    score = 3 * len(action_tokens & method_tokens)
    score += len(action_tokens & holder_tokens)
    for left in action_tokens:
        for right in method_tokens:
            if left != right and min(len(left), len(right)) >= 4 and (
                    left.startswith(right) or right.startswith(left)):
                # cancelled/cancel, returned/return
                score += 1
    return score


def align_action(action, source, requirements, docs):
    if not isinstance(action, str) or not action.strip():
        return Alignment("under_specified", None, 0.0, ["empty action"])
    exact = _dedupe_methods(
        (holder, method) for holder, method in _methods(docs)
        if normalize(method["name"]) == normalize(action))
    if len(exact) == 1:
        holder, method = exact[0]
        return Alignment("aligned", f"{holder}.{method['name']}", 10.0,
                         ["exact generated method"])
    kind = codegen.classify_crud(action)
    words = _tokens(action)
    last_token = _last_action_token(action)
    candidates = []
    for holder, method in _methods(docs):
        if kind is not None and codegen.classify_crud(method["name"]) != kind:
            continue
        if not _method_mentions(method, last_token):
            # A CRUD operation may use the entity from its holder
            # (`create_product` -> ProductRepository.create), but a domain
            # operation such as `get_stock_status` may not drift to an
            # unrelated method that only shares its holder.
            holder_ok = (kind is not None and last_token
                         and last_token in normalize(str(holder))
                         and codegen.classify_crud(method["name"]) == kind)
            if not holder_ok:
                continue
        flat = normalize(str(method["name"]) + " " + str(holder) + " " +
                         " ".join(str(param.get("name") or "")
                                  for param in method.get("params") or []
                                  if isinstance(param, dict)))
        if words and not any(word in flat for word in words):
            continue
        candidates.append((holder, method))
    candidates = _dedupe_methods(candidates)
    if "page" in normalize(source) or "paginat" in normalize(source):
        paginated = []
        for holder, method in candidates:
            names = {normalize(param.get("name"))
                     for param in method.get("params") or []
                     if isinstance(param, dict) and param.get("name")}
            if names & {"page", "pagenumber", "pagesize", "perpage",
                        "limit", "offset"}:
                paginated.append((holder, method))
        if paginated:
            candidates = paginated
    scored = sorted(
        ((_action_score(action, holder, method), holder, method)
         for holder, method in candidates),
        key=lambda item: (-item[0], item[1], item[2].get("name") or ""))
    if len(scored) == 1:
        score, holder, method = scored[0]
        return Alignment("alias", f"{holder}.{method['name']}", float(score),
                         ["same operation with a different name"])
    if scored:
        best_score, holder, method = scored[0]
        runner_up = scored[1][0]
        alternatives = [f"{h}.{m['name']}" for _score, h, m in scored[1:5]]
        if best_score > runner_up:
            return Alignment("alias", f"{holder}.{method['name']}",
                             float(best_score),
                             ["highest action-name specificity"],
                             alternatives)
        return Alignment("ambiguous", f"{holder}.{method['name']}",
                         float(best_score),
                         ["several generated methods have the same action score"],
                         [f"{h}.{m['name']}" for _score, h, m in scored[:4]])
    if _prompt_mentions(action, source) or _prompt_mentions(
            action, requirements):
        return Alignment("coverage_gap", None, 0.0,
                         ["prompt names the action", "no generated method matches"])
    return Alignment("invented", None, 0.0,
                     ["no prompt evidence for the action",
                      "no generated method matches"])


def align_case(case, docs, requirements=""):
    """Align all entity/field/action concepts referenced by one case."""
    given = case.get("given") if isinstance(case.get("given"), dict) else {}
    state = (case.get("then") or {}).get("state") or {}
    source = case.get("source") or ""
    entities = {}
    for alias, values in given.items():
        fields = list(values) if isinstance(values, dict) else []
        entities[alias] = align_entity(
            alias, fields, source, requirements, docs)
    for target in state:
        alias, _, field = str(target).partition(".")
        if not alias:
            continue
        if alias not in entities:
            entities[alias] = align_entity(
                alias, [field], source, requirements, docs)
    fields = {}
    for target in state:
        alias, _, field = str(target).partition(".")
        alignment = entities.get(alias)
        if alignment and alignment.canonical:
            fields[target] = align_field(
                alignment.canonical, field, source, requirements, docs)
    action = (case.get("when") or {}).get("action")
    action_alignment = align_action(action, source, requirements, docs) \
        if action else None
    return {"entities": entities, "fields": fields,
            "action": action_alignment}
