"""Extraction-side detection of methods a generator can emit mechanically.

The generator must not guess which service method is ordinary CRUD, which
repository it delegates to, or which fields an aggregate sums. Those are
architecture facts, so they are detected here, beside the documents, and
written to `method_plans.json`.

Only unambiguous plans are recorded. A method whose pattern, target or slots
are ambiguous becomes a question: the human answers it through the existing
review workflow, and the generator then consumes the answer rather than
inferring anything.
"""

from __future__ import annotations

import json
import os

from kernel import codegen
from kernel.consistency.naming import normalize
from kernel.extraction.decisions import requirements_sha

METHOD_PLANS_NAME = "method_plans.json"


def _models(documents):
    return [model for model in (documents.get("data_models") or [])
            if isinstance(model, dict) and model.get("name")]


def _repositories(documents):
    ports = documents.get("persistence_ports")
    if not isinstance(ports, dict):
        return []
    return [repo for repo in (ports.get("repositories") or [])
            if isinstance(repo, dict) and repo.get("entity")]


def _methods(service):
    return [method for method in (service.get("methods") or [])
            if isinstance(method, dict) and method.get("name")]


def _match_entry(documents, service_name, method_name):
    wanted = f"contract:{service_name}.{method_name}"
    for entry in documents.get("pattern_matches") or []:
        if isinstance(entry, dict) and entry.get("source") == wanted:
            return entry
    return None


def _entity_for_service(service_name, models):
    """The one model a `XService` name owns, or None when ambiguous."""
    wanted = normalize(service_name)
    matches = []
    for model in models:
        entity = model["name"]
        candidate = normalize(f"{entity}Service")
        if wanted == candidate or wanted.startswith(candidate):
            matches.append(entity)
    return matches[0] if len(matches) == 1 else None


def _repo_for(repositories, entity):
    matches = [repo for repo in repositories if repo.get("entity") == entity]
    return matches[0] if len(matches) == 1 else None


def _method_in_repo(repo, operation):
    for method in repo.get("methods") or []:
        if isinstance(method, dict) and codegen.classify_crud(
                method.get("name") or "") == operation:
            return method
    return None


def _fields(model):
    return [field for field in (model.get("fields") or [])
            if isinstance(field, dict) and field.get("name")]


def _aggregate_slots(model, method, pattern):
    """`(slots, None)` when every slot is unique, else `(None, question)`."""
    params = [param.get("name") for param in method.get("params") or []
              if isinstance(param, dict) and param.get("name")]
    fields = _fields(model)
    dates = [field["name"] for field in fields
             if str(field.get("type") or "").lower() in ("date", "datetime")]
    numbers = [field["name"] for field in fields
               if str(field.get("type") or "").lower() in
               ("int", "integer", "float", "decimal", "number")
               and not field.get("primary_key")
               and not isinstance(field.get("foreign_key"), dict)]
    fks = [field["name"] for field in fields
           if isinstance(field.get("foreign_key"), dict)]
    if len(dates) != 1 or len(numbers) != 1:
        return None, {
            "reason": "aggregate target or date field is ambiguous",
            "candidates": {"date_field": dates, "target_field": numbers},
        }
    if pattern == "AGGREGATE_BY_FK_AND_DATE":
        fk = [param for param in params
              if normalize(param) in {normalize(name) for name in fks}]
        if len(fk) > 1:
            return None, {"reason": "several foreign-key parameters",
                          "candidates": fk}
        fk_field = fk[0] if fk else None
    else:
        fk_field = None
    return {
        "fk_field": fk_field,
        "date_field": dates[0],
        "target_field": numbers[0],
        "aggregate_func": "SUM",
    }, None


def build(documents, requirements=""):
    """Return `{plans, questions}` for the current documents."""
    models = _models(documents)
    repositories = _repositories(documents)
    plans, questions = [], []
    for service in documents.get("service_contracts") or []:
        if not isinstance(service, dict) or not service.get("service_name"):
            continue
        service_name = service["service_name"]
        if normalize(service_name).endswith("repository"):
            continue
        entity = _entity_for_service(service_name, models)
        repo = _repo_for(repositories, entity) if entity else None
        for method in _methods(service):
            name = method["name"]
            entry = _match_entry(documents, service_name, name)
            pattern = entry.get("pattern_id") if isinstance(entry, dict) else None
            if pattern is None:
                continue
            if pattern == "STANDARD_CRUD":
                operation = codegen.classify_crud(name)
                if operation in ("create", "read_one", "read_all",
                                  "update", "delete"):
                    target = _method_in_repo(repo, operation) if repo else None
                    if target is not None and not method.get("raises"):
                        plans.append({
                            "holder": service_name,
                            "method": name,
                            "strategy": "delegate",
                            "pattern": pattern,
                            "entity": entity,
                            "target_service": repo.get("interface_name"),
                            "target_method": target["name"],
                        })
                    else:
                        questions.append({
                            "holder": service_name,
                            "method": name,
                            "pattern": pattern,
                            "reason": "no unambiguous CRUD target"
                                      if target is None else
                                      "CRUD method declares custom errors",
                        })
                continue
            if pattern.startswith("AGGREGATE"):
                if any(word in normalize(name) for word in ("report", "summary")):
                    questions.append({
                        "holder": service_name, "method": name,
                        "pattern": pattern,
                        "reason": "report structure needs human review",
                    })
                    continue
                if entity is None:
                    questions.append({
                        "holder": service_name, "method": name,
                        "pattern": pattern,
                        "reason": "service does not map to one entity",
                    })
                    continue
                slots, question = _aggregate_slots(
                    next(model for model in models if model["name"] == entity),
                    method, pattern)
                if slots is None:
                    question.update({"holder": service_name, "method": name,
                                     "pattern": pattern})
                    questions.append(question)
                else:
                    plans.append({
                        "holder": service_name,
                        "method": name,
                        "strategy": "mechanical",
                        "pattern": pattern,
                        "entity": entity,
                        "slots": slots,
                    })
    return {"plans": plans, "questions": questions}


def write(output_dir, documents, requirements=""):
    payload = build(documents, requirements)
    sha = requirements_sha(requirements)
    if sha is not None:
        payload["requirements_sha"] = sha
    path = os.path.join(output_dir, METHOD_PLANS_NAME)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return path, payload
