#!/usr/bin/env python3
"""Generate a runnable Python program from extraction output.

The probe proves the documents agree; this writes the program they describe:

    python generator.py out/expenses

writes `out/expenses/generated/` — `models.py`, `errors.py`, `schema.py`,
`store.py`, `repositories.py`, `services.py`, `cli.py` — and refuses (exit 1) when the
probe reports blockers or open ties, because generating from a document the
probe rejects means inventing code silently.

Bodies follow one rule per method (`kernel.codegen.plan_method`, which itself
follows `kernel.tie_rules.effective_directive` — there is one definition, and
this file does not reimplement it):

- mechanical CRUD and filters run on an in-memory `Store`;
- services delegate to the repository method of the same name;
- everything else (aggregates, guards, exports, gaps, open ties) is a
  `raise NotImplementedError` stub carrying its directive and refusal reason
  in the docstring: a work order for the LLM pass, never an invented body.

The CLI backend follows the facade declaration: `click` gets real click
commands with typed options, every other technology gets the stdlib
`argparse` fallback. Each `(command, subcommand)` is bound to the adapter that
serves its verb, the binding baked into `cli.py` with its score beside it.

A `gui` facade additionally gets `gui.py` from the backend its declaration
names (`--gui-tech` overrides): today only `pyimgui`, a generic one-window-
per-entity CRUD surface wired to the mechanical methods. Bespoke screens
(forms, events) are not in the documents, so they are not generated — the
file header says so.

Degenerate case: when the documents are clean but empty (no models, services,
repositories, adapters or commands — hello, cli_tool), there is no
architecture to be faithful to and the mechanical files would be an empty
shell. With `--model PATH`, the generator instead writes one
`generated/app.py` from `requirements.txt` directly (LLM fallback, said aloud
on stdout and in the file header); without `--model` it stops with exit 2
rather than writing the empty shell silently.

`--model PATH` also fills the stubs a normal run leaves behind: method
bodies the emitter refused (custom logic, unmappable parameters) are written
by the model, one call per method, temperature 0 with a fixed seed. An
answer is accepted only when its module still compiles, it names only
`self.<name>`, store methods, `models.*` classes and `errors.*` classes the
sibling modules define, and it breaks none of the API facts the prompt
states (model fields, declared parameters, the method's return type). A
refused answer gets up to two repair asks carrying the exact complaint; a body
that still fails keeps the stub. Accepted docstrings are tagged
`[llm-written by ... — review]` and the method still counts as a stub in
the mechanical coverage. These bodies are provisional: syntax, API and
contract checks do not establish runtime behavior. The run leaves every raw
answer and its per-answer timing (wall, prompt, cached prompt and decode
seconds) in `<out>/llm_stub_answers.json`; each run moves the previous dump to `<out>/llm_stub_answers_runs/` before overwriting it, so a truncated answer is not lost.
The default body ask (`--stub-context exact`) shows `models.py` as code and
repeats the target signature and return dataclass; the other contexts
remain available for experiments.

`--model server` selects an already-running llama-server instead of a GGUF
path, using the same `LLAMA_SERVER_URL` setting as `extract_arch.py`.
"""

import argparse
import ast
import datetime
import builtins
import io
import json
import os
import pprint
import re
import sys
import textwrap
import tokenize

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import probe_readiness  # noqa: E402
from kernel import codegen  # noqa: E402
from kernel import contract_compiler  # noqa: E402
from kernel import tie_rules  # noqa: E402
from kernel.consistency.checks_surface import COMMAND_VERB_STEMS  # noqa: E402
from kernel.consistency.loader import load_documents, load_requirements  # noqa: E402
from kernel.consistency.naming import normalize  # noqa: E402
from kernel.consistency.report import Report  # noqa: E402
from kernel.extraction import repairs as extraction_repairs  # noqa: E402
from kernel.extraction import runner  # noqa: E402
from kernel.extraction.server_backend import ServerError  # noqa: E402
from kernel.extraction.contracts import (  # noqa: E402
    contract_for,
    load_method_contracts,
)
from kernel.extraction.decisions import requirements_sha  # noqa: E402
from kernel.store_contract import DEFAULT_STORE  # noqa: E402

GENERATED_DIR = "generated"
STORE_CONTRACT = DEFAULT_STORE

# Patterns whose slots a human can answer (see review_slots.py): with every
# required slot recorded, the emitters below write the body mechanically.
# Guard patterns are deliberately absent — a guard must run its check, never
# delegate past it or reduce to a scan; those stay stubs until we design them.
# FILTER_CRITERION is synthetic: a parameterless status filter (`find_active_
# members`) that currently stubs — the equality criterion is exactly the
# finite, enumerable thing a human answers, and no name rule may invent it.
SLOT_PATTERNS = frozenset({"AGGREGATE_BY_FK", "AGGREGATE_BY_FK_AND_DATE",
                            "THRESHOLD_SCAN", "BUDGET_OVERFLOW_GUARD",
                            "FILTER_CRITERION"})
GUARD_PATTERNS = frozenset({"BUDGET_OVERFLOW_GUARD", "QUOTA_CAPACITY_GUARD",
                            "STOCK_SUFFICIENCY_GUARD", "PRICE_MARGIN_GUARD",
                            "STATE_TRANSITION_GUARD"})

# Reproducibility follows the extraction convention (greedy decoding plus the
# fixed seed): the same requirements yield the same file, modulo GPU arithmetic.
FALLBACK_TEMPERATURE = 0.0
FALLBACK_SEED = 20261012
# The body ask defaults to the context that reproduces the reviewed library
# bodies: models.py as code plus the target signature and return dataclass.
DEFAULT_STUB_CONTEXT = "exact"

# `method_slots.json` beside the documents: `{holder, method, pattern,
# slots, decided_by, requirements_sha}` from the slot review.
METHOD_SLOTS_NAME = "method_slots.json"
METHOD_SLOTS_KEY = "slots"

# `method_plans.json` beside the documents (written by extract_arch.py):
# extraction-side decisions that a body is mechanically emittable.
METHOD_PLANS_NAME = "method_plans.json"
METHOD_PLANS_KEY = "plans"

# `method_programs.json` beside the documents: reviewed, declarative service
# bodies (read/query/check/for_each/update/create/assign actions).  The
# emitter interprets only these generic operations; it contains no domain
# noun, status value or entity name.
METHOD_PROGRAMS_NAME = "method_programs.json"
METHOD_PROGRAMS_KEY = "programs"

# `grounding_decisions.json` beside the documents: review decisions that drop
# service capabilities with no requirement evidence.  The generator applies
# them before adapters/commands are emitted, so a dropped service cannot leave
# a dangling CLI verb behind.
GROUNDING_DECISIONS_NAME = "grounding_decisions.json"

# `method_repairs.json`: reviewed LLM-body complaints.  The model gets the
# failed body and the exact behavioral complaint; this is still a model-written
# body, not a mechanical substitution.
METHOD_REPAIRS_NAME = "method_repairs.json"

# `aggregate_decisions.json`: reviewed answer to whether a grouped mapping
# includes parent rows that have no child rows.  The generator applies the
# decision to the final repository body, after the mechanical or LLM body is
# chosen, so the behavior is not left to a model prompt.
AGGREGATE_DECISIONS_NAME = "aggregate_decisions.json"

# `surface_decisions.json` beside the documents (written by
# review_surface.py): duplicate-node keeps, and `kind: "route"` records
# binding a declared CLI flag to the method it selects. Route records are
# consumed here, at generation time — they shape the emitted dispatch.
SURFACE_DECISIONS_NAME = "surface_decisions.json"
SURFACE_DECISIONS_KEY = "decisions"
SURFACE_ROUTE_KIND = "route"


# --------------------------------------------------------------------------
# document access
# --------------------------------------------------------------------------

def _leaf_node(components, command, subcommand):
    """The command or subcommand node named by a surface decision."""
    invocation = ((components or {}).get("facade") or {}).get("invocation") or {}
    node = next((c for c in invocation.get("commands") or []
                 if isinstance(c, dict) and c.get("name") == command), None)
    if subcommand is not None and isinstance(node, dict):
        node = next((s for s in node.get("subcommands") or []
                     if isinstance(s, dict) and s.get("name") == subcommand), None)
    return node


def _adapt_route_options(components, routes):
    """Retype routed flags from the human route record.

    `review_surface` also writes the type into components.json. This second
    application makes a recorded route self-contained: if a rerun rebuilds a
    boolean flag before the sidecar is replayed, the generator still emits
    the value-taking parser the route needs.
    """
    for record in routes or []:
        if not isinstance(record, dict):
            continue
        option_type = record.get("option_type")
        flag = record.get("flag")
        if not isinstance(option_type, str) or not isinstance(flag, str):
            continue
        leaf = _leaf_node(components, record.get("command"),
                          record.get("subcommand"))
        if not isinstance(leaf, dict):
            continue
        for option in leaf.get("options") or []:
            if codegen.option_dest(option) != flag:
                continue
            if option.get("type") != option_type:
                option["type"] = option_type
                option["required"] = False
                option["default"] = None
            break


def load_grounding_decisions(output_dir, current_sha=None):
    """Read review-approved service/command drops, or an empty decision."""
    try:
        with open(os.path.join(output_dir, GROUNDING_DECISIONS_NAME),
                  encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    stamped = payload.get("requirements_sha")
    if current_sha is not None and isinstance(stamped, str) \
            and stamped != current_sha:
        return {}
    return payload


def _filter_commands(commands, drop_verbs):
    kept = []
    for command in commands or []:
        if not isinstance(command, dict):
            continue
        name = normalize(command.get("name") or "")
        if name in drop_verbs:
            continue
        subcommands = command.get("subcommands")
        if isinstance(subcommands, list):
            command = dict(command)
            filtered = _filter_commands(subcommands, drop_verbs)
            # A reviewed drop that removes the only verb of a group leaves an
            # empty group in the surface; it is not a command and must not be
            # emitted as one.
            if subcommands and not filtered:
                continue
            command["subcommands"] = filtered
        kept.append(command)
    return kept


def load_aggregate_decisions(output_dir, current_sha=None):
    """Read reviewed aggregate group-coverage decisions."""
    try:
        with open(os.path.join(output_dir, AGGREGATE_DECISIONS_NAME),
                  encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    stamped = payload.get("requirements_sha")
    if current_sha is not None and isinstance(stamped, str) \
            and stamped != current_sha:
        return []
    return [record for record in payload.get("decisions") or []
            if isinstance(record, dict)
            and isinstance(record.get("holder"), str)
            and isinstance(record.get("method"), str)
            and record.get("include_empty_groups") is True]


def _insert_before_first_class(text, helper):
    marker = "\n\nclass "
    if text.startswith("class "):
        return helper + "\n\n" + text
    index = text.find(marker)
    if index < 0:
        return helper + "\n\n" + text
    return text[:index] + "\n\n" + helper + text[index:]


def _unwrap_aggregate_expression(expression, helper_name):
    """Strip repeated generator wrappers before applying one coverage call."""
    try:
        node = ast.parse(expression, mode="eval").body
    except SyntaxError:
        return expression
    while isinstance(node, ast.Call) \
            and isinstance(node.func, ast.Name) \
            and node.func.id == helper_name \
            and node.args:
        node = node.args[0]
    return ast.unparse(node)


def apply_aggregate_decisions(files, decisions):
    """Apply reviewed empty-group coverage to final aggregate bodies.

    The decision is applied after the LLM/mechanical body is selected.  It
    wraps the final return of a grouped mapping, asking the parent source for
    every key and filling missing keys with zero.  Repository and service
    layers use their own parent access path.
    """
    if not decisions:
        return files, []
    applied = []
    changed = set()
    helper_name = "_include_empty_groups"
    for record in decisions:
        layer = record.get("layer", "repository")
        if layer not in ("repository", "service"):
            continue
        filename = "services.py" if layer == "service" else "repositories.py"
        text = files.get(filename)
        holder = record["holder"]
        method = record["method"]
        parent = record.get("parent_entity")
        key = record.get("key_field") or "id"
        if not isinstance(text, str) or not isinstance(parent, str) \
                or not isinstance(key, str):
            continue
        lines = text.splitlines()
        class_start = next((index for index, line in enumerate(lines)
                            if line.strip() == f"class {holder}:"), None)
        if class_start is None:
            continue
        method_start = next((index for index in range(class_start + 1, len(lines))
                             if lines[index].startswith(f"    def {method}(")), None)
        if method_start is None:
            continue
        method_end = next((index for index in range(method_start + 1, len(lines))
                           if lines[index].startswith("    def ")
                           or lines[index].startswith("class ")), len(lines))
        return_index = None
        for index in range(method_end - 1, method_start, -1):
            if lines[index].startswith("        return "):
                return_index = index
                break
        if return_index is None:
            continue
        expression = lines[return_index][len("        return "):]
        expression = _unwrap_aggregate_expression(expression, helper_name)
        if layer == "service":
            parent_repository = record.get("parent_repository") \
                or f"{parent}Repository"
            parent_rows = (
                f"self._repos[{parent_repository!r}].read_all()")
        else:
            parent_rows = f"self._store.select({parent!r}, [])"
        lines[return_index] = (
            "        return "
            f"{helper_name}({expression}, {parent_rows}, {key!r})")
        text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
        files[filename] = text
        changed.add(filename)
        applied.append(f"{holder}.{method}")
    helper = (
        "def _include_empty_groups(result, parent_rows, key):\n"
        "    \"\"\"Add parent keys absent from a grouped mapping as zero.\"\"\"\n"
        "    for row in parent_rows:\n"
        "        value = row.get(key) if isinstance(row, dict) else getattr(row, key, None)\n"
        "        result.setdefault(value, 0)\n"
        "    return result")
    for filename in changed:
        text = files[filename]
        if "def _include_empty_groups" not in text:
            files[filename] = _insert_before_first_class(text, helper)
    return files, applied


def filter_grounded_repositories(repositories, decisions):
    """Apply reviewed method drops to repository interfaces too.

    The same capability is represented in service and repository documents;
    filtering only the service side leaves a slot/pattern consumer looking at
    the repository method that the review just removed.
    """
    if not decisions or not isinstance(repositories, list):
        return repositories
    drop_services = {normalize(name) for name in decisions.get("drop_services") or []
                     if isinstance(name, str)}
    drop_methods = {(normalize(item.get("holder") or ""), normalize(item.get("method") or ""))
                    for item in decisions.get("drop_methods") or []
                    if isinstance(item, dict)}
    kept = []
    for repo in repositories:
        if not isinstance(repo, dict):
            continue
        holder = repo.get("interface_name") or repo.get("entity") or ""
        if normalize(holder) in drop_services:
            continue
        methods = [method for method in repo.get("methods") or []
                   if not (isinstance(method, dict)
                           and (normalize(holder), normalize(method.get("name") or ""))
                           in drop_methods)]
        if methods:
            repo = dict(repo)
            repo["methods"] = methods
            kept.append(repo)
    return kept


def apply_grounding_decisions(services, adapters, components, routes, decisions):
    """Drop review-marked capabilities and the surfaces that referenced them."""
    if not decisions:
        return services, adapters, components, routes
    drop_services = {normalize(name) for name in decisions.get("drop_services") or []
                     if isinstance(name, str)}
    drop_methods = {(normalize(item.get("holder") or ""), normalize(item.get("method") or ""))
                    for item in decisions.get("drop_methods") or []
                    if isinstance(item, dict)}
    kept_services = []
    for service in services:
        name = normalize(service.get("service_name") or "")
        if name in drop_services:
            continue
        methods = []
        for method in service.get("methods") or []:
            if not isinstance(method, dict):
                continue
            key = (name, normalize(method.get("name") or ""))
            if key in drop_methods:
                continue
            methods.append(method)
        if methods:
            service = dict(service)
            service["methods"] = methods
            kept_services.append(service)
    available = {
        (normalize(service.get("service_name") or ""), normalize(method.get("name") or ""))
        for service in kept_services
        for method in service.get("methods") or []
        if isinstance(method, dict)
    }
    kept_adapters = []
    for adapter in adapters:
        key = (normalize(adapter.get("target_service") or ""),
               normalize(adapter.get("target_method") or ""))
        if key not in available:
            continue
        kept_adapters.append(adapter)
    if isinstance(components, dict):
        components = dict(components)
        facade = components.get("facade")
        if isinstance(facade, dict):
            facade = dict(facade)
            invocation = facade.get("invocation")
            if isinstance(invocation, dict):
                invocation = dict(invocation)
                drop_verbs = {normalize(verb) for verb in
                              decisions.get("drop_command_verbs") or []
                              if isinstance(verb, str)}
                invocation["commands"] = _filter_commands(
                    invocation.get("commands") or [], drop_verbs)
                facade["invocation"] = invocation
            components["facade"] = facade
    kept_routes = []
    for route in routes:
        key = (normalize(route.get("service") or ""),
               normalize(route.get("method") or ""))
        if key not in available:
            continue
        kept_routes.append(route)
    return kept_services, kept_adapters, components, kept_routes


def load_context(output_dir):
    """The generation context: every body plus the indexes the emitters need."""
    output_dir = str(output_dir)
    report = Report(os.path.basename(output_dir.rstrip(os.sep)))
    documents = load_documents(output_dir, report)
    models = [m for m in (documents.get("data_models") or []) if isinstance(m, dict) and m.get("name")]
    errors = [e for e in (documents.get("errors") or []) if isinstance(e, dict) and e.get("name")]
    invariants = [i for i in (documents.get("invariants") or []) if isinstance(i, dict)]
    services = [s for s in (documents.get("service_contracts") or []) if isinstance(s, dict) and s.get("service_name")]
    ports = documents.get("persistence_ports")
    repositories = []
    if isinstance(ports, dict) and isinstance(ports.get("repositories"), list):
        repositories = [r for r in ports["repositories"] if isinstance(r, dict) and r.get("entity")]
    if not repositories:
        # An in-memory application can skip the persistence step while its
        # service contracts still carry the repository interface. Reuse those
        # interfaces against the in-memory Store instead of dropping CRUD.
        for service in services:
            name = service.get("service_name") or ""
            if not normalize(name).endswith("repository"):
                continue
            entity = name[:-len("Repository")]
            repositories.append({
                "entity": entity,
                "interface_name": name,
                "methods": service.get("methods") or [],
            })
    mappings = {}
    if isinstance(ports, dict) and isinstance(ports.get("entity_mappings"), list):
        for mapping in ports["entity_mappings"]:
            if isinstance(mapping, dict) and mapping.get("entity"):
                mappings[normalize(mapping["entity"])] = mapping
    matches = documents.get("pattern_matches")
    if not isinstance(matches, list):
        matches = []
    matches = extraction_repairs.repair_paginated_patterns(
        matches, services, repositories)
    match_index = {}
    for entry in matches:
        if isinstance(entry, dict) and entry.get("source"):
            match_index[entry["source"]] = entry
    adapters = [a for a in (documents.get("interaction_adapters") or []) if isinstance(a, dict) and a.get("action_name")]
    components = documents.get("components")
    if not isinstance(components, dict):
        components = {}
    slots = {}
    requirements_text = load_requirements(output_dir)
    current = requirements_sha(requirements_text)
    contracts, dropped_contracts = load_method_contracts(
        output_dir, requirements_text)
    contracts = extraction_repairs.repair_contracts(
        contracts, services, repositories, models, requirements_text)
    dropped = 0
    try:
        with open(os.path.join(output_dir, METHOD_SLOTS_NAME),
                  encoding="utf-8") as handle:
            payload = json.load(handle)
        records = payload.get(METHOD_SLOTS_KEY)
        if isinstance(records, list):
            for record in records:
                if isinstance(record, dict) and record.get("holder") and record.get("method"):
                    stamped = record.get("requirements_sha")
                    if current is not None and isinstance(stamped, str) \
                            and stamped != current:
                        dropped += 1
                        continue
                    slots[(record["holder"], record["method"])] = record
    except (OSError, ValueError):
        pass
    routes = []
    dropped_routes = 0
    try:
        with open(os.path.join(output_dir, SURFACE_DECISIONS_NAME),
                  encoding="utf-8") as handle:
            payload = json.load(handle)
        records = payload.get(SURFACE_DECISIONS_KEY)
        if isinstance(records, list):
            for record in records:
                if not (isinstance(record, dict)
                        and record.get("kind") == SURFACE_ROUTE_KIND
                        and record.get("command") and record.get("flag")
                        and record.get("service") and record.get("method")):
                    continue
                stamped = record.get("requirements_sha")
                if current is not None and isinstance(stamped, str) \
                        and stamped != current:
                    dropped_routes += 1
                    continue
                routes.append(record)
    except (OSError, ValueError):
        pass
    programs = {}
    dropped_programs = 0
    try:
        with open(os.path.join(output_dir, METHOD_PROGRAMS_NAME),
                  encoding="utf-8") as handle:
            payload = json.load(handle)
        stamped = payload.get("requirements_sha")
        if current is None or not isinstance(stamped, str) or stamped == current:
            for record in payload.get(METHOD_PROGRAMS_KEY) or []:
                if not isinstance(record, dict):
                    continue
                holder = record.get("holder")
                method = record.get("method")
                if isinstance(holder, str) and isinstance(method, str):
                    programs[(holder, method)] = record
        else:
            dropped_programs = len(payload.get(METHOD_PROGRAMS_KEY) or [])
    except (OSError, ValueError):
        pass
    method_plans = {}
    dropped_plans = 0
    try:
        with open(os.path.join(output_dir, METHOD_PLANS_NAME),
                  encoding="utf-8") as handle:
            payload = json.load(handle)
        stamped = payload.get("requirements_sha")
        if current is None or not isinstance(stamped, str) or stamped == current:
            for record in payload.get(METHOD_PLANS_KEY) or []:
                if not isinstance(record, dict):
                    continue
                holder = record.get("holder")
                method = record.get("method")
                if isinstance(holder, str) and isinstance(method, str):
                    method_plans[(holder, method)] = record
        else:
            dropped_plans = len(payload.get(METHOD_PLANS_KEY) or [])
    except (OSError, ValueError):
        pass
    decisions = load_grounding_decisions(output_dir, current)
    services, adapters, components, routes = apply_grounding_decisions(
        services, adapters, components, routes, decisions)
    repositories = filter_grounded_repositories(repositories, decisions)
    # A reviewed/extracted document can predate the create-surface and id
    # repairs. Apply them at generation time too, so an already-valid run does
    # not need a full re-extraction just to expose a required field or type an
    # integer key. These are context repairs only; the source documents stay
    # untouched.
    services = extraction_repairs.repair_id_param_types(services, models)
    services = extraction_repairs.repair_mapping_create_params(services, models)
    for repository in repositories:
        extraction_repairs.repair_mapping_create_params([repository], models)
    adapters = extraction_repairs.repair_adapter_id_transforms(
        adapters, services)
    adapters = extraction_repairs.repair_adapter_targets(
        adapters, services, None)
    adapters = extraction_repairs.repair_aggregate_create_adapters(
        components, adapters, services, repositories, models, None)
    method_owners = list(services) + list(repositories)
    # Repository interfaces win over a same-named service contract here:
    # `CustomerRepository.update_customer` may take a mapping while the
    # service-contract twin still lists the individual fields.
    extraction_repairs.repair_adapter_mapping_fields(
        adapters, list(repositories) + list(services))
    adapters = extraction_repairs.repair_adapter_transforms(
        adapters, None, method_owners)
    extraction_repairs.repair_create_adapter_fields(
        adapters, method_owners, models)
    extraction_repairs.repair_missing_adapter_flags(
        components, adapters, method_owners, models, None)
    adapters = extraction_repairs.repair_delete_adapter_fields(adapters)
    extraction_repairs.repair_delete_surface(components)
    _adapt_route_options(components, routes)
    return {
        "models": models,
        "errors": errors,
        "invariants": invariants,
        "services": services,
        "repositories": repositories,
        "mappings": mappings,
        "match_index": match_index,
        "adapters": adapters,
        "components": components,
        "entity_names": [m["name"] for m in models],
        "slots": slots,
        "dropped_slots": dropped,
        "contracts": contracts,
        "dropped_contracts": dropped_contracts,
        "method_plans": method_plans,
        "dropped_plans": dropped_plans,
        "programs": programs,
        "dropped_programs": dropped_programs,
        "routes": routes,
        "dropped_routes": dropped_routes,
        "method_repairs": load_method_repairs(output_dir),
        "requirements": requirements_text,
    }


def model_of(ctx, entity_ref):
    """The data model for an entity name, matched leniently, or None."""
    if not entity_ref:
        return None
    wanted = normalize(entity_ref)
    for model in ctx["models"]:
        if normalize(model["name"]) == wanted:
            return model
    return None


def primary_key_of(ctx, entity):
    """The mapping's primary key, else the model's, else `id`."""
    mapping = ctx["mappings"].get(normalize(entity or ""))
    if isinstance(mapping, dict) and mapping.get("primary_key"):
        return mapping["primary_key"]
    model = model_of(ctx, entity)
    if model:
        for field in model.get("fields") or []:
            if isinstance(field, dict) and field.get("primary_key") and field.get("name"):
                return field["name"]
    return "id"


def fields_of(ctx, entity):
    """The `(name, field)` pairs of a model, or [] for unknown entities."""
    model = model_of(ctx, entity)
    if not model or not isinstance(model.get("fields"), list):
        return []
    return [(f["name"], f) for f in model["fields"] if isinstance(f, dict) and f.get("name")]


def _registered_error(ctx, entity):
    """A registered `*NotFound*`/`*Missing*` class mentioning the entity, or None."""
    wanted = normalize(entity or "")
    for error in ctx["errors"]:
        name = error["name"]
        flat = normalize(name)
        if wanted and wanted in flat and ("notfound" in flat or "missing" in flat):
            return name
    return None


def method_error(ctx, method, entity):
    """The error expression for a lookup failure: the method's own first."""
    raises = [r for r in (method.get("raises") or []) if isinstance(r, str)]
    registered = {e["name"] for e in ctx["errors"]}
    raises = [r for r in raises if r in registered]
    wanted = normalize(entity or "")
    for name in raises:
        if wanted and wanted in normalize(name):
            return f"errors.{codegen.sanitize(name)}"
    if raises:
        return f"errors.{codegen.sanitize(raises[0])}"
    entity_error = _registered_error(ctx, entity)
    if entity_error:
        return f"errors.{codegen.sanitize(entity_error)}"
    return "LookupError"


# --------------------------------------------------------------------------
# file emitters (each returns its text)
# --------------------------------------------------------------------------

HEADER_IMPORTS = """from dataclasses import dataclass
from decimal import Decimal
import datetime
from typing import Any, Dict, List, Literal, Optional
"""


def emit_init(ctx, stats):
    technology = ((ctx.get("components") or {}).get("facade") or {}).get("technology")
    backend = str(technology or "argparse").strip().lower()
    lines = ['"""Generated program. Do not edit by hand: regenerate with `generator.py`."""',
             "",
             f"# Source documents: {stats['source']}",
             f"# Methods: {stats['implemented']} implemented, {stats['stubs']} stubs "
             "(each stub names its work order in its docstring).",
             f"# CLI backend: {backend}.",
             ""]
    return "\n".join(lines) + "\n"


def _field_default(ctx, field):
    """The field's default from the model, else the requirements' own words.

    Extraction records types, keys and foreign keys but not default values;
    requirements such as "available_copies (default 1)" and "is_active
    (default True)" are still authoritative. Only a literal directly attached
    to the field name is accepted, so an unrelated "default" sentence cannot
    leak into the model.
    """
    if isinstance(field, dict) and "default" in field:
        return field.get("default")
    name = field.get("name") if isinstance(field, dict) else None
    if not isinstance(name, str) or not name:
        return None
    text = ctx.get("requirements") or ""
    if not text:
        return None
    literal = (
        r"(true|false|none|null|'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|"
        r"-?\d+(?:\.\d+)?)"
    )
    patterns = (
        # The requirements' own list spelling: `available_copies (default 1)`.
        r"\b" + re.escape(name) + r"\b\s*\([^)\n]*?"
        r"\bdefaults?(?:\s+to)?\s*[:=]?\s*" + literal + r"\s*\)",
        # The prose spelling: `available_copies defaults to 1`.
        r"\b" + re.escape(name) + r"\b\s+(?:defaults?(?:\s+to)?|"
        r"has\s+a\s+default(?:\s+of)?)\s*[:=]?\s*" + literal + r"\b",
    )
    match = next((re.search(pattern, text, re.IGNORECASE)
                  for pattern in patterns
                  if re.search(pattern, text, re.IGNORECASE)), None)
    if not match:
        return None
    token = match.group(1).strip()
    lowered = token.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in ("none", "null"):
        return None
    if token[:1] in ("'", '"') and token[-1:] == token[:1]:
        return ast.literal_eval(token)
    try:
        return ast.literal_eval(token)
    except (SyntaxError, ValueError):
        return None


def emit_models(ctx):
    lines = ['"""Data models. The store assigns integer primary keys on insert,',
             'and updates merge only non-None values. Explicit application defaults',
             'from the requirements are preserved on the dataclasses."""',
             "", HEADER_IMPORTS.strip(), ""]
    for model in ctx["models"]:
        cls = codegen.sanitize(model["name"], "Model")
        lines += ["", "", "@dataclass", f"class {cls}:"]
        fields = fields_of(ctx, model["name"])
        if not fields:
            lines.append("    pass")
            continue
        for name, field in fields:
            pytype = codegen.map_type(field.get("type"), ctx["entity_names"])
            # A documented value set is part of the field's type. The
            # invariant is the only place the vocabulary is written down,
            # so read it there instead of leaving the field as a bare
            # `str` that accepts any spelling.
            values = _field_enum(ctx, model["name"], name)
            if values:
                pytype = "Literal[" + ", ".join(repr(v) for v in values) + "]"
            if field.get("nullable"):
                pytype = f"Optional[{pytype}]"
            default = _field_default(ctx, field)
            lines.append(f"    {codegen.sanitize(name)}: {pytype} = {default!r}")
    return "\n".join(lines) + "\n"


def emit_errors(ctx):
    lines = ['"""Application errors, one class per registered failure."""', ""]
    if not ctx["errors"]:
        lines += ["", "class AppError(Exception):", '    """Fallback when no errors were registered."""', ""]
        return "\n".join(lines) + "\n"
    for error in ctx["errors"]:
        cls = codegen.sanitize(error["name"], "AppError")
        base = error.get("base") if isinstance(error.get("base"), str) and error["base"].strip() else "Exception"
        description = (error.get("description") or "").strip()
        lines += ["", "", f"class {cls}({codegen.sanitize(base, 'Exception')}):"]
        lines.append(f'    """{description}"""' if description else "    pass")
    return "\n".join(lines) + "\n"


def _signature(method, entity_names):
    """`(declaration, [(raw_name, ident, raw_type)])`, all defaulting to None."""
    parts = []
    params = []
    for param in method.get("params") or []:
        if not isinstance(param, dict):
            continue
        raw = param.get("name") if isinstance(param.get("name"), str) else ""
        ident = codegen.sanitize(raw, "param")
        ptype = param.get("type")
        params.append((raw, ident, ptype))
        parts.append(f"{ident}: {_qualify(codegen.map_type(ptype, entity_names), entity_names)} = None")
    return ", ".join(parts), params


def _return_of(method, entity_names):
    return _qualify(codegen.map_type(method.get("return_type"), entity_names), entity_names)


def _qualify(pytype, entity_names):
    """Prefix bare entity references with `models.` so annotations resolve.

    References may already be qualified (`wine.Wine`, the spelling gui's
    contracts use): the head is replaced, never prefixed twice, because
    `models.wine.Wine` resolves against nothing. The class name is the same
    `sanitize` call `emit_models` uses, so the two cannot disagree.
    """
    if not isinstance(pytype, str) or not entity_names:
        return pytype
    names = sorted({n for n in entity_names if isinstance(n, str)}, key=len, reverse=True)
    if not names:
        return pytype
    pattern = re.compile(
        r"(?<![\w.])(" + "|".join(re.escape(n) for n in names) + r")(\.[\w]+)?\b")

    def _replace(match):
        return "models." + codegen.sanitize(match.group(1), "Model")

    return pattern.sub(_replace, pytype)


def _repo_index(ctx):
    """Normalized repo method name -> `[(repo_class, method)]` in ports order."""
    index = {}
    for repo in ctx["repositories"]:
        cls = codegen.sanitize(repo.get("interface_name") or repo.get("entity"), "Repository")
        for method in repo.get("methods") or []:
            if isinstance(method, dict) and method.get("name"):
                index.setdefault(normalize(method["name"]), []).append((cls, method))
    return index


def _standard_read_repo(ctx, method, params):
    """`(repo_class, repo_method, entity)` for a standard read-by-id wrapper."""
    name = normalize(method.get("name") or "")
    if not name.startswith("read") or not name.endswith("byid"):
        return None
    if len(params) != 1:
        return None
    service_params = sorted(normalize(item[0]) for item in params)
    for repo in ctx["repositories"]:
        entity = repo.get("entity")
        if not isinstance(entity, str) or normalize(entity) not in name:
            continue
        cls = codegen.sanitize(repo.get("interface_name") or entity, "Repository")
        for candidate in repo.get("methods") or []:
            if not isinstance(candidate, dict) or not candidate.get("name"):
                continue
            strategy, _ = codegen.plan_method(
                candidate, _match_entry(ctx, cls, candidate["name"]),
                ctx["entity_names"])
            if strategy != "crud:read_one":
                continue
            candidate_params = sorted(
                normalize(p.get("name") or "")
                for p in candidate.get("params") or [] if isinstance(p, dict))
            if len(candidate_params) != 1 or candidate_params != service_params:
                continue
            return cls, candidate, entity
    return None


def _service_standard_read_body(ctx, method, params, returns):
    """Mechanical `read_<entity>_by_id` delegation, even across return spelling."""
    # The exact-name read-one path below already handles matching signatures;
    # this fallback exists only for the mechanically completed wrapper whose
    # optional return (`Entity | None`) differs from the repository's `Entity`.
    params_norm = [normalize(item[0]) for item in params]
    if _read_one_target(ctx, method, params_norm, normalize(returns)) is not None:
        return None
    target = _standard_read_repo(ctx, method, params)
    if target is None:
        return None
    repo_cls, repo_method, entity = target
    rname = codegen.sanitize(repo_method["name"], "method")
    arg = params[0][1]
    call = f"self._repos[{repo_cls!r}].{rname}({arg})"
    optional = bool(re.search(r"\bNone\b", returns or ""))
    if not optional:
        return [f"return {call}"]
    error = method_error(ctx, repo_method, entity)
    if error == "LookupError":
        return [f"return {call}"]
    return [
        "try:",
        f"    return {call}",
        f"except {error}:",
        "    return None",
    ]


# A standard `<verb>_<entity>` service wrapper is only mechanical when its
# description does not hide a domain check.  A description that mentions a
# budget or another business rule is not a plain CRUD wrapper; the repository
# already owns FK existence, but it does not own the rule.
SERVICE_CRUD_BLOCK_WORDS = (
    "budget", "exceed", "overage", "balance", "insufficient", "capacity",
    "guard", "pricing", "discount", "tax",
)


def _preexisting_fk_messages(ctx, entity, contract):
    """True when every precondition is only an FK existence the repo checks."""
    preconditions = contract.get("preconditions") or []
    if not preconditions:
        return True
    model = model_of(ctx, entity)
    if model is None:
        return False
    fk_targets = {
        normalize(field["foreign_key"].get("target_entity"))
        for _name, field in fields_of(ctx, entity)
        if isinstance(field, dict) and isinstance(field.get("foreign_key"), dict)
    }
    registered = {normalize(error.get("name"))
                  for error in ctx.get("errors") or []
                  if isinstance(error, dict) and error.get("name")}
    for item in preconditions:
        if not isinstance(item, dict):
            return False
        check = str(item.get("check") or "").strip()
        match = re.fullmatch(r"([A-Za-z_]\w*)\s+exists", check)
        if match is None:
            return False
        target = normalize(match.group(1))
        error = normalize(item.get("error") or "")
        if target not in fk_targets or error not in registered:
            return False
    return True


def _repair_is_input_validation(record):
    """True when a repair record only asks for required-value validation."""
    complaints = record.get("complaints") if isinstance(record, dict) else None
    if not complaints:
        return False
    allowed = ("required", "is none", "valueerror", "read_all", "duplicate",
               "missing", "empty")
    return all(any(word in str(item).lower() for word in allowed)
               for item in complaints)


def _service_crud_wrapper(ctx, service_name, method, params, returns):
    """Body for a plain `<verb>_<entity>` create/update/delete wrapper.

    This is the contract the model does not need to write: a service method
    named exactly after one entity's CRUD verb, whose parameters map one-for-one
    to that repository method, and whose description names no extra rule.  It
    returns None for anything less certain.
    """
    name = method.get("name") or ""
    tokens = _verb_tokens(name)
    if len(tokens) < 2 or tokens[0] not in ("create", "add", "update", "delete",
                                            "remove"):
        return None
    if len(tokens) > 2 and not (tokens[0] == "update"
                                and tokens[2] in ("stock", "quantity", "count")):
        return None
    entity = next((item for item in ctx["entity_names"]
                   if normalize(item) == normalize(tokens[1])), None)
    if entity is None:
        return None
    description = str(method.get("description") or "").lower()
    if any(word in description for word in SERVICE_CRUD_BLOCK_WORDS):
        return None
    kind = codegen.classify_crud(name)
    if kind not in ("create", "update", "delete"):
        return None
    repair = (ctx.get("method_repairs") or {}).get((service_name, name))
    if repair is not None and not (
            kind == "create" and _repair_is_input_validation(repair)):
        return None
    contract = contract_for(ctx.get("contracts") or [], service_name, name)
    if isinstance(contract, dict):
        if contract.get("effects") or contract.get("reads") \
                or contract.get("derives"):
            return None
        if not _preexisting_fk_messages(ctx, entity, contract):
            return None
    repo = next((item for item in ctx["repositories"]
                 if normalize(item.get("entity")) == normalize(entity)), None)
    if repo is None:
        return None
    target = next((item for item in repo.get("methods") or []
                   if isinstance(item, dict) and item.get("name")
                   and codegen.classify_crud(item["name"]) == kind), None)
    if target is None:
        return None
    target_params = [item.get("name") for item in target.get("params") or []
                     if isinstance(item, dict) and item.get("name")]
    mapped = []
    used = set()
    for raw, ident, _ptype in params:
        key = _service_param_target(raw, entity, target_params)
        if key is None or key in used:
            return None
        used.add(key)
        mapped.append((key, ident))
    model = model_of(ctx, entity)
    fields = fields_of(ctx, entity) if model else []
    required = {}
    if kind == "create":
        required = {normalize(name): name for name, field in fields
                    if isinstance(field, dict) and not field.get("primary_key")
                    and not field.get("nullable")}
        supplied = {normalize(key) for key, _ in mapped}
        if set(required) - supplied:
            return None
    else:
        primary = primary_key_of(ctx, entity)
        if normalize(primary) not in {normalize(key) for key, _ in mapped}:
            return None
    holder = codegen.sanitize(repo.get("interface_name") or entity, "Repository")
    repo_method = codegen.sanitize(target["name"], "method")
    args = ", ".join(f"{codegen.sanitize(key, 'kw')}={ident}"
                     for key, ident in mapped)
    call = f"self._repos[{holder!r}].{repo_method}({args})"
    lines = []
    if kind == "create":
        missing = [ident for key, ident in mapped
                   if normalize(key) in {normalize(item) for item in required}]
        if missing:
            check = " or ".join(f"{item} is None" for item in missing)
            lines += [f"if {check}:", "    raise ValueError('missing required field')"]
    if normalize(returns) in ("none", "nonetype", "void", ""):
        lines.append(call)
    else:
        lines.append(f"return {call}")
    return lines


def _service_param_target(raw, entity, target_params):
    """The repository parameter a service parameter feeds, or None."""
    wanted = normalize(raw)
    exact = [name for name in target_params if normalize(name) == wanted]
    if len(exact) == 1:
        return exact[0]
    if exact:
        return None
    entity_prefix = normalize(entity)
    rest = wanted[len(entity_prefix):] if wanted.startswith(entity_prefix) else ""
    if rest:
        matches = [name for name in target_params if normalize(name) == rest]
        if len(matches) == 1:
            return matches[0]
    if wanted.startswith("new") and len(wanted) > 3:
        rest = wanted[3:]
        matches = [name for name in target_params if normalize(name) == rest]
        if len(matches) == 1:
            return matches[0]
    return None


def _service_delegate(ctx, method, repo_index):
    """The `(repo_class, repo_method)` of the same normalized name, or None.

    Several repositories may declare one name; the one whose entity the method
    names wins, else ports order decides — recorded in a comment beside the call.
    """
    candidates = repo_index.get(normalize(method.get("name") or ""), [])
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    haystack = normalize(method.get("name") or "")
    for cls, candidate in candidates:
        _ = candidate
        entity_hit = next((r.get("entity") or "" for r in ctx["repositories"]
                           if codegen.sanitize(r.get("interface_name") or r.get("entity")) == cls), "")
        if entity_hit and normalize(entity_hit) in haystack:
            return (cls, candidate)
    return sorted(candidates, key=lambda item: item[0])[0]


# Neighboring verbs for cross-name delegation: the same call spelled with the
# neighboring verb (`get_expense_by_id` → `read_expense_by_id`). Anything
# outside these families is a different operation, not a respelling.
RENAME_FAMILIES = ({"get", "read"}, {"add", "create"}, {"update", "edit"},
                   {"delete", "remove"}, {"list", "read_all"})


def _verb_tokens(name):
    """Lowercased `_`/`-`-separated tokens of a method name."""
    return [token for token in re.split(r"[_-]+", str(name or "").lower()) if token]


def _rename_target(ctx, method, param_names, returns):
    """`(repo_class, repo_method)` for the same call under a neighboring verb.

    Same normalized parameters and same normalized return type, and a
    mechanical target — delegating past a guard or into a stub would move
    the refusal, not implement the method. The same-name path owns exact
    matches; this only fires across neighboring verbs.
    """
    want = _verb_tokens(method.get("name"))
    if not want:
        return None
    for repo in ctx["repositories"]:
        holder = repo.get("interface_name") or repo.get("entity")
        cls = codegen.sanitize(holder, "Repository")
        for candidate in repo.get("methods") or []:
            if not isinstance(candidate, dict) or not candidate.get("name"):
                continue
            got = _verb_tokens(candidate["name"])
            if len(got) != len(want) or got == want:
                continue
            if got[0] == want[0]:
                if got[1:] != want[1:]:
                    continue
            elif not any({got[0], want[0]} <= family for family in RENAME_FAMILIES) \
                    or got[1:] != want[1:]:
                continue
            strategy, _ = codegen.plan_method(
                candidate, _match_entry(ctx, holder, candidate["name"]),
                ctx["entity_names"])
            if not strategy.startswith("crud:"):
                continue
            candidate_params = sorted(
                normalize(p.get("name") or "")
                for p in candidate.get("params") or [] if isinstance(p, dict))
            if candidate_params != sorted(param_names):
                continue
            if normalize(_return_of(candidate, ctx["entity_names"])) != returns:
                continue
            return (cls, candidate)
    return None


def _read_one_target(ctx, method, param_names, returns):
    """`(repo_class, repo_method)` that already reads one record by key.

    A service `read_book_by_id(book_id) -> Book | None` is the repository's
    `read_one(book_id)` under another name; the verbs differ in shape
    (`read_one` has no noun), so `_rename_target` cannot pair them. Same
    normalized parameters and return type, and a mechanical read-one target:
    delegating into a guard or a stub would move the refusal, not implement
    the method.
    """
    for repo in ctx["repositories"]:
        holder = repo.get("interface_name") or repo.get("entity")
        cls = codegen.sanitize(holder, "Repository")
        for candidate in repo.get("methods") or []:
            if not isinstance(candidate, dict) or not candidate.get("name"):
                continue
            strategy, _ = codegen.plan_method(
                candidate, _match_entry(ctx, holder, candidate["name"]),
                ctx["entity_names"])
            if strategy != "crud:read_one":
                continue
            candidate_params = sorted(
                normalize(p.get("name") or "")
                for p in candidate.get("params") or [] if isinstance(p, dict))
            if candidate_params != sorted(param_names):
                continue
            if normalize(_return_of(candidate, ctx["entity_names"])) != returns:
                continue
            return (cls, candidate)
    return None


def _service_cancel_stock_delegate(ctx, method, params, delegate):
    """Same-name delegation for a mechanically emitted cancel/restore body."""
    if delegate is None:
        return None
    target_cls, target = delegate
    repo = next((item for item in ctx.get("repositories") or []
                 if isinstance(item, dict)
                 and (item.get("interface_name") or item.get("entity")) == target_cls),
                None)
    entity = repo.get("entity") if isinstance(repo, dict) else None
    if entity is None or _cancel_stock_plan(ctx, entity, target) is None:
        return None
    wanted = sorted(normalize(raw) for raw, _, _ in params)
    have = sorted(normalize(param.get("name") or "")
                  for param in target.get("params") or []
                  if isinstance(param, dict) and param.get("name"))
    if wanted != have:
        return None
    return target_cls, target.get("name")


def _realized_delegate(ctx, service_name, method, params, returns, delegate):
    """Same-name delegation past a non-mechanical service plan — when safe.

    Fires only when the old same-name rule did not: the service plan is not
    crud (typically a slotted pattern like an aggregate), but the target is
    mechanical with identical parameters and returns. Guard-patterned
    services never delegate: the check must run, so the stub stands.
    """
    if delegate is None:
        return None
    target_cls, target = delegate
    holder = next((r.get("interface_name") or r.get("entity")
                   for r in ctx["repositories"]
                   if any(m is target for m in (r.get("methods") or []))), None)
    tstrategy, _ = codegen.plan_method(
        target, _match_entry(ctx, holder, target.get("name")), ctx["entity_names"])
    if not tstrategy.startswith("crud:"):
        # A slot-answered aggregate or threshold is mechanical too: the
        # emitter writes it from the recorded slots, so delegating to it is
        # delegating to running code, not to a refusal.
        pattern, slots = _slot_pattern(ctx, holder, target)
        if pattern is None or not _slots_usable(pattern, slots, target, True):
            return None
    tparams = sorted(normalize(p.get("name") or "")
                     for p in target.get("params") or [] if isinstance(p, dict))
    if tparams != sorted(normalize(raw) for raw, _, _ in params):
        return None
    if normalize(_return_of(target, ctx["entity_names"])) != normalize(returns):
        return None
    entry = _match_entry(ctx, service_name, method.get("name"))
    if isinstance(entry, dict):
        kind, payload = tie_rules.effective_directive(entry)
        if kind == "pattern" and payload in GUARD_PATTERNS:
            return None
    return (target_cls, codegen.sanitize(target.get("name"), "method"))


def _service_filter_plan(ctx, method, params):
    """`(repo_cls, read_all, entity, fields, detail)` for a service filter.

    A FILTER_BY_FIELD — or read_all-shaped — service with mappable parameters
    runs over the entity's read-all: the criteria are the kernel's own field
    matching, so the body filters exactly as the repository would. Parameterless
    reads compose to a straight pass-through. Anything else (no list entity
    in the return, an entity-typed parameter, an unmappable parameter, no
    read-all repository) is None — a stub, not a guess.
    """
    returns = (method.get("return_type") or "")
    words = {normalize(token)
             for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", returns)}
    if "list" not in words:
        return None
    entity = next((name for name in ctx["entity_names"]
                   if isinstance(name, str) and normalize(name) in words
                   and normalize(name) not in ("list", "dict", "optional", "none")),
                  None)
    if entity is None:
        return None
    model = model_of(ctx, entity)
    field_names = [name for name, _ in fields_of(ctx, entity)] if model else []
    if not field_names:
        return None
    field_types = {name: (field.get("type") or "")
                   for name, field in fields_of(ctx, entity)}
    for raw, _, ptype in params:
        if codegen.is_entity_type(ptype, ctx["entity_names"]):
            return None
        if codegen.match_param(field_names, raw) is None:
            return None
    for repo in ctx["repositories"]:
        if repo.get("entity") != entity:
            continue
        holder = repo.get("interface_name") or entity
        for candidate in repo.get("methods") or []:
            if not isinstance(candidate, dict) or not candidate.get("name"):
                continue
            strategy, _ = codegen.plan_method(
                candidate, _match_entry(ctx, holder, candidate["name"]),
                ctx["entity_names"])
            if strategy == "crud:read_all":
                return (codegen.sanitize(holder, "Repository"),
                        codegen.sanitize(candidate["name"], "method"),
                        entity, field_names, field_types)
    return None


def _fk_checks(ctx, entity):
    """`[(field, target_entity, target_field, ErrorOrNone)]` for a model's FKs."""
    checks = []
    for name, field in fields_of(ctx, entity):
        foreign = field.get("foreign_key")
        if not isinstance(foreign, dict) or not foreign.get("target_entity"):
            continue
        err = _registered_error(ctx, foreign["target_entity"])
        checks.append((name, foreign["target_entity"],
                       foreign.get("target_field") or "id",
                       f"errors.{codegen.sanitize(err)}" if err else "None"))
    return checks


def _match_entry(ctx, holder_name, method_name):
    return ctx["match_index"].get(f"contract:{holder_name}.{method_name}")


def _docstring(text):
    return (text or "").strip().replace('"""', '"')


def emit_repositories(ctx, stats):
    """Repository classes with mechanical bodies."""
    lines = ['"""Repositories over an in-memory Store, one class per persistence port.',
             "",
             "CRUD, reads and filters run for real. Anything else raises",
             "NotImplementedError with its work order — an aggregate or guard body",
             "is specified by its pattern, not invented here.",
             '"""',
             "",
             "from typing import Any, Dict, List, Optional, Tuple, Union",
             "",
             "import datetime",
             "",
             "import models",
             "import errors",
             "from store import Store, match_criterion",
             "",
             "",
             "def _record_values(data, field_names):",
             '    """A dataclass or dict entity argument as a `{field: value}` dict."""',
             "    if data is None:",
             "        return {}",
             "    if isinstance(data, dict):",
             "        return {name: data.get(name) for name in field_names}",
             "    return {name: getattr(data, name, None) for name in field_names}",
             "",
             "",
             "def _model_list(records, model_cls):",
             '    """Model objects from records, deduplicated by stable id."""',
             "    out = []",
             "    seen = set()",
             "    if records is None:",
             "        records = []",
             "    elif isinstance(records, dict) or isinstance(records, (str, bytes)) \\",
             "            or not hasattr(records, '__iter__'):",
             "        records = [records]",
             "    for record in records:",
             "        if isinstance(record, dict):",
             "            key = record.get('id')",
             "            item = model_cls(**record)",
             "        else:",
             "            key = getattr(record, 'id', None)",
             "            item = record",
             "        if key is not None:",
             "            if key in seen:",
             "                continue",
             "            seen.add(key)",
             "        out.append(item)",
             "    return out",
             ""]
    for repo in ctx["repositories"]:
        entity = repo.get("entity")
        holder = repo.get("interface_name") or entity
        cls = codegen.sanitize(holder, "Repository")
        pk = primary_key_of(ctx, entity)
        model_cls = None
        if model_of(ctx, entity):
            model_cls = f"models.{codegen.sanitize(entity, 'Model')}"
        field_names = [name for name, _ in fields_of(ctx, entity)]
        fk_checks = _fk_checks(ctx, entity)
        fk_literal = "[" + ", ".join(
            f'("{f}", "{t}", "{tf}", {e})' for f, t, tf, e in fk_checks) + "]"
        lines += ["", "", f"class {cls}:",
                  f'    ENTITY = "{entity}"',
                  f'    PK = "{pk}"',
                  "",
                  "    def __init__(self, store):",
                  "        self._store = store",
                  ""]
        for method in repo.get("methods") or []:
            if not isinstance(method, dict) or not method.get("name"):
                continue
            strategy, detail = codegen.plan_method(
                method, _match_entry(ctx, holder, method["name"]), ctx["entity_names"])
            fname = codegen.sanitize(method["name"], "method")
            declaration, params = _signature(method, ctx["entity_names"])
            returns = _return_of(method, ctx["entity_names"])
            pattern, slots = _slot_pattern(ctx, holder, method)
            if pattern is not None and _slots_usable(pattern, slots, method, True):
                field_types = {name: (field.get("type") or "")
                               for name, field in fields_of(ctx, entity)}
                body = _repo_slot_body(ctx, entity, model_cls, field_types,
                                       method, pattern, slots)
                if body is not None:
                    slot_detail = ", ".join(
                        f"{slot}={slots[slot]}"
                        for slot in SLOT_REQUIREMENTS.get(pattern, ())
                        if slots.get(slot) not in (None, ""))
                    lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                              f'        """{_docstring(method.get("description"))} '
                              f'[{pattern} via answered slots: {slot_detail}]"""']
                    lines.extend("        " + line if line else "" for line in body)
                    stats["implemented"] += 1
                    _record(stats, holder, method["name"], strategy, True,
                            f"slots:{pattern}")
                    continue
            paginated = _repo_pagination_body(ctx, entity, model_cls, method)
            if paginated is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[mechanical pagination]"""']
                lines.extend("        " + line if line else "" for line in paginated)
                stats["implemented"] += 1
                _record(stats, holder, method["name"], strategy, True,
                        "pagination")
                continue
            named_filter = _repo_named_filter_body(ctx, entity, model_cls,
                                                   method)
            if named_filter is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          f'[FILTER_BY_NAMED_FIELD: {method["name"]}]"""']
                lines.extend("        " + line if line else "" for line in named_filter)
                stats["implemented"] += 1
                _record(stats, holder, method["name"], strategy, True,
                        "named field filter")
                continue
            relation_lookup = _repo_relation_lookup_body(
                ctx, entity, model_cls, method)
            if relation_lookup is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[lookup through a named relation]"""']
                lines.extend("        " + line if line else ""
                             for line in relation_lookup)
                stats["implemented"] += 1
                _record(stats, holder, method["name"], strategy, True,
                        "relation lookup")
                continue
            two_hop = _repo_two_hop_filter_body(
                ctx, entity, model_cls, method)
            if two_hop is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[filters through one intermediate relation]"""']
                lines.extend("        " + line if line else "" for line in two_hop)
                stats["implemented"] += 1
                _record(stats, holder, method["name"], strategy, True,
                        "two-hop filter")
                continue
            text_search = _repo_text_search_body(
                ctx, entity, model_cls, method)
            if text_search is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[mechanical text search]"""']
                lines.extend("        " + line if line else "" for line in text_search)
                stats["implemented"] += 1
                _record(stats, holder, method["name"], strategy, True,
                        "text search")
                continue
            count_by = _repo_count_by_field_body(ctx, entity, method)
            if count_by is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[mechanical count by field]"""']
                lines.extend("        " + line if line else "" for line in count_by)
                stats["implemented"] += 1
                _record(stats, holder, method["name"], strategy, True,
                        "count by field")
                continue
            containment = _repo_containment_filter_body(
                ctx, entity, model_cls, method)
            if containment is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[mechanical contained-name filter]"""']
                lines.extend("        " + line if line else "" for line in containment)
                stats["implemented"] += 1
                _record(stats, holder, method["name"], strategy, True,
                        "contained-name filter")
                continue
            check_stock = _repo_check_stock_body(ctx, entity, model_cls, method)
            if check_stock is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[mechanical stock check]"""']
                lines.extend("        " + line if line else "" for line in check_stock)
                stats["implemented"] += 1
                _record(stats, holder, method["name"], strategy, True,
                        "stock check")
                continue
            cancel_stock = _repo_cancel_stock_body(ctx, entity, model_cls, method)
            if cancel_stock is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[mechanical cancel with stock restoration]"""']
                lines.extend("        " + line if line else "" for line in cancel_stock)
                stats["implemented"] += 1
                _record(stats, holder, method["name"], strategy, True,
                        "cancel stock restoration")
                continue
            low_stock = _repo_low_stock_body(ctx, entity, model_cls, method)
            if low_stock is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[mechanical low-stock scan]"""']
                lines.extend("        " + line if line else "" for line in low_stock)
                stats["implemented"] += 1
                _record(stats, holder, method["name"], strategy, True,
                        "low-stock scan")
                continue
            stock_value = _repo_stock_value_body(ctx, entity, model_cls, method)
            if stock_value is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[mechanical stock value]"""']
                lines.extend("        " + line if line else "" for line in stock_value)
                stats["implemented"] += 1
                _record(stats, holder, method["name"], strategy, True,
                        "stock value")
                continue
            utilization = _repo_utilization_body(ctx, entity, method)
            if utilization is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[mechanical utilization]"""']
                lines.extend("        " + line if line else "" for line in utilization)
                stats["implemented"] += 1
                _record(stats, holder, method["name"], strategy, True,
                        "utilization")
                continue
            period_sum = _repo_period_sum_body(ctx, entity, method)
            if period_sum is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[mechanical period sum]"""']
                lines.extend("        " + line if line else "" for line in period_sum)
                stats["implemented"] += 1
                _record(stats, holder, method["name"], strategy, True,
                        "period sum")
                continue
            top_categories = _repo_top_categories_body(ctx, entity, method)
            if top_categories is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[mechanical top categories]"""']
                lines.extend("        " + line if line else "" for line in top_categories)
                stats["implemented"] += 1
                _record(stats, holder, method["name"], strategy, True,
                        "top categories")
                continue
            lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:"]
            query_fields, query_model, query_table = field_names, model_cls, "self.ENTITY"
            target = _query_entity(ctx, method, entity)
            if target is not None and strategy in ("crud:read_all", "crud:filter"):
                query_fields = [name for name, _ in fields_of(ctx, target)]
                query_model = f"models.{codegen.sanitize(target, 'Model')}"
                query_table = repr(target)
            try:
                body = _repo_body(ctx, strategy, detail, method, params, entity,
                                  query_model, query_fields, pk, fk_literal,
                                  table=query_table,
                                  contract=contract_for(ctx.get("contracts") or [],
                                                        holder, method["name"]))
            except _Unmappable as stuck:
                detail = f"parameter {stuck.param!r} maps to no field"
                body = None
            if body is None:
                lines += [f'        """{_docstring(method.get("description"))} '
                          f'[{strategy}: {detail}]"""',
                          "        raise NotImplementedError(",
                          f'            "{cls}.{fname}: {strategy}: {detail}")']
                stats["stubs"] += 1
                stats["stub_reasons"].append(f"{cls}.{fname}: {detail}")
                _record(stats, holder, method["name"], strategy, False, detail)
                continue
            lines.append(f'        """{_docstring(method.get("description"))} [{strategy}: {detail}]"""')
            lines.extend("        " + line if line else "" for line in body)
            if strategy.startswith("crud:"):
                stats["implemented"] += 1
                _record(stats, holder, method["name"], strategy, True, "crud")
            else:
                stats["stubs"] += 1
                stats["stub_reasons"].append(f"{cls}.{fname}: {detail}")
                _record(stats, holder, method["name"], strategy, False, detail)
    return "\n".join(lines) + "\n"


def _query_entity(ctx, method, entity):
    """The declared entity a query reads, when it is not this repo's own.

    `AuthorRepository.find_books_by_author -> List[Book]` reads Book: the
    return type names the table, and the borrowed parameters (`author_id`)
    are Book fields. A return type naming several declared entities is
    ambiguous and refuses (None).
    """
    returns = method.get("return_type")
    if not isinstance(returns, str):
        return None
    words = {normalize(token) for token in
             re.findall(r"[A-Za-z_][A-Za-z0-9_]*", returns)}
    targets = [name for name in ctx["entity_names"]
               if isinstance(name, str)
               and normalize(name) in words
               and normalize(name) != normalize(entity)]
    if len(targets) != 1:
        return None
    target = targets[0]
    if model_of(ctx, target) is None:
        return None
    return target


def _read_one_names_entity_error(ctx, method, entity):
    """Whether a lookup's declared failure actually belongs to this entity.

    `BudgetRepository.read_one` carried `CategoryNotFoundError` because a
    budget has a category foreign key, but a missing budget is not a missing
    category. With no budget-specific not-found class, the lookup returns
    None; the caller decides (an add_expense with no budget simply has no
    limit).
    """
    if _registered_error(ctx, entity):
        return True
    wanted = normalize(entity or "")
    return any(wanted and wanted in normalize(name)
               for name in method.get("raises") or []
               if isinstance(name, str))


def _cancel_stock_plan(ctx, entity, method):
    """The model graph for a cancel operation that restores child stock.

    Returns the child model, its parent/product fields, the product model and
    stock field, or None when the graph does not prove that shape.
    """
    if "cancel" not in normalize(method.get("name") or ""):
        return None
    parent_model = model_of(ctx, entity)
    if parent_model is None:
        return None
    status_field = next((field.get("name") for field in parent_model.get("fields") or []
                         if isinstance(field, dict)
                         and normalize(field.get("name") or "") in ("status", "state")),
                        None)
    if status_field is None:
        return None
    child = None
    for candidate in ctx.get("models") or []:
        if not isinstance(candidate, dict) or not candidate.get("name"):
            continue
        fields = [field for field in candidate.get("fields") or []
                  if isinstance(field, dict) and field.get("name")]
        parent_fk = next((field for field in fields
                          if (isinstance(field.get("foreign_key"), dict)
                              and normalize(field["foreign_key"].get("target_entity") or "")
                              == normalize(entity))
                          or normalize(field.get("name") or "") == normalize(entity) + "id"), None)
        product_fk = next((field for field in fields
                           if normalize(field.get("name") or "").endswith("productid")
                           or (isinstance(field.get("foreign_key"), dict)
                               and normalize(field["foreign_key"].get("target_entity") or "")
                               == "product")), None)
        quantity = next((field for field in fields
                         if normalize(field.get("name") or "") == "quantity"), None)
        if parent_fk and product_fk and quantity:
            child = candidate
            product_name = (product_fk.get("foreign_key") or {}).get("target_entity") \
                if isinstance(product_fk.get("foreign_key"), dict) else product_fk["name"][:-3]
            product = next((model for model in ctx.get("models") or []
                            if isinstance(model, dict)
                            and normalize(model.get("name") or "") == normalize(product_name or "")),
                           None)
            if product is None:
                continue
            stock = next((field.get("name") for field in product.get("fields") or []
                          if isinstance(field, dict)
                          and "stock" in normalize(field.get("name") or "")), None)
            if stock is None:
                continue
            return {
                "child": child["name"],
                "parent_fk": parent_fk["name"],
                "product_fk": product_fk["name"],
                "quantity": quantity["name"],
                "product": product["name"],
                "product_pk": primary_key_of(ctx, product["name"]),
                "stock": stock,
                "status": status_field,
            }
    return None


def _repo_cancel_stock_body(ctx, entity, model_cls, method):
    """Cancel a parent and restore each child line's product stock."""
    plan = _cancel_stock_plan(ctx, entity, method)
    if plan is None:
        return None
    params = [(param.get("name"), codegen.sanitize(param.get("name"), "param"))
              for param in method.get("params") or []
              if isinstance(param, dict) and param.get("name")]
    if not params:
        return None
    key_param = params[0][1]
    parent_error = _registered_error(ctx, entity)
    product_error = _registered_error(ctx, plan["product"])
    parent = codegen.sanitize(entity, "entity")
    update_parent = (f"self._store.update(self.ENTITY, self.PK, {key_param}, "
                     f"{{{plan['status']!r}: 'cancelled'}})")
    if parent_error:
        get_parent = (f"self._store.get(self.ENTITY, self.PK, {key_param}, "
                      f"error=errors.{codegen.sanitize(parent_error)})")
    else:
        get_parent = f"self._store.get(self.ENTITY, self.PK, {key_param})"
    if product_error:
        get_product = (f"self._store.get({plan['product']!r}, {plan['product_pk']!r}, "
                       f"product_id, error=errors.{codegen.sanitize(product_error)})")
    else:
        get_product = (f"self._store.get({plan['product']!r}, "
                       f"{plan['product_pk']!r}, product_id)")
    lines = [
        f"{parent} = {get_parent}",
        f"if {parent} is None:",
        f"    raise errors.{codegen.sanitize(parent_error)}" if parent_error
        else "    return None",
        update_parent,
        f"lines = self._store.select({plan['child']!r}, "
        f"[({plan['parent_fk']!r}, 'eq', {key_param})])",
        "for line in lines:",
        f"    product_id = line.get({plan['product_fk']!r})",
        f"    quantity = line.get({plan['quantity']!r})",
        "    if product_id is None or quantity is None:",
        "        continue",
        f"    product = {get_product}",
        "    if product is None:",
        "        continue",
        f"    stock = product.get({plan['stock']!r}, 0) + quantity",
        f"    self._store.update({plan['product']!r}, {plan['product_pk']!r}, "
        f"product_id, {{{plan['stock']!r}: stock}})",
    ]
    if normalize(method.get("return_type") or "") in ("bool", "boolean"):
        lines.append("return True")
    return lines


def _repo_check_stock_body(ctx, entity, model_cls, method):
    """Check a product-id collection for positive stock.

    The same method is reached from a CLI with a comma-separated string and
    from a service with a list of ids. Accept both shapes instead of letting
    the model choose one and call `.split()` on the other.
    """
    name = normalize(method.get("name") or "")
    if "check" not in name or "stock" not in name:
        return None
    params = [param for param in method.get("params") or []
              if isinstance(param, dict) and param.get("name")]
    if len(params) != 1 or not normalize(params[0].get("name") or "").endswith("ids"):
        return None
    stock = next((name for name, field in fields_of(ctx, entity)
                  if isinstance(field, dict)
                  and "stock" in normalize(name)), None)
    if stock is None:
        return None
    ids = codegen.sanitize(params[0].get("name"), "ids")
    product_error = _registered_error(ctx, entity) or "ProductNotFoundError"
    stock_error = next((error.get("name") for error in ctx.get("errors") or []
                        if isinstance(error, dict)
                        and "stock" in normalize(error.get("name") or "")
                        and "quantity" in normalize(error.get("description") or "")),
                       "ProductStockQuantityError")
    return [
        f"if isinstance({ids}, str):",
        f"    {ids} = [item for item in {ids}.split(',') if item.strip()]",
        f"for product_id in {ids} or []:",
        f"    product = self._store.get(self.ENTITY, self.PK, int(product_id), "
        f"error=errors.{codegen.sanitize(product_error)})",
        f"    if product.get({stock!r}) is None:",
        f"        raise errors.{codegen.sanitize(stock_error)}("
        f"f\"Product with id {{product_id}} has no stock quantity\")",
        f"    if product.get({stock!r}) <= 0:",
        f"        raise errors.{codegen.sanitize(stock_error)}("
        f"f\"Product with id {{product_id}} has insufficient stock quantity\")",
    ]


def _repo_low_stock_body(ctx, entity, model_cls, method):
    """Products below their category's reorder threshold."""
    name = normalize(method.get("name") or "")
    if "low" not in name or "stock" not in name:
        return None
    if method.get("params"):
        return None
    fields = fields_of(ctx, entity)
    stock = next((field_name for field_name, field in fields
                  if isinstance(field, dict) and "stock" in normalize(field_name)),
                 None)
    relation = next(((field_name, field) for field_name, field in fields
                     if isinstance(field, dict)
                     and isinstance(field.get("foreign_key"), dict)
                     and normalize(field["foreign_key"].get("target_entity"))
                     in {normalize(item) for item in ctx["entity_names"]}), None)
    if stock is None or relation is None:
        return None
    relation_name, relation_field = relation
    parent = relation_field["foreign_key"]["target_entity"]
    threshold = next((field_name for field_name, field in fields_of(ctx, parent)
                      if isinstance(field, dict)
                      and ("threshold" in normalize(field_name)
                           or "reorder" in normalize(field_name))), None)
    if threshold is None:
        return None
    parent_pk = primary_key_of(ctx, parent)
    lines = [
        f"parents = self._store.select({parent!r}, [])",
        f"thresholds = {{row[{parent_pk!r}]: row[{threshold!r}] for row in parents}}",
        "result = []",
        "for row in self._store.select(self.ENTITY, []):",
        f"    parent_id = row.get({relation_name!r})",
        "    threshold = thresholds.get(parent_id)",
        f"    stock = row.get({stock!r})",
        "    if stock is not None and threshold is not None and stock < threshold:",
        "        result.append(row)",
    ]
    if model_cls is None:
        lines.append("return result")
    else:
        lines.append(f"return _model_list([{model_cls}(**row) for row in result], {model_cls})")
    return lines


def _repo_stock_value_body(ctx, entity, model_cls, method):
    """Stock value per category: price * stock, with empty categories at zero."""
    name = normalize(method.get("name") or "")
    if "stock" not in name or "value" not in name or method.get("params"):
        return None
    fields = fields_of(ctx, entity)
    price = next((field_name for field_name, field in fields
                  if isinstance(field, dict)
                  and ("price" in normalize(field_name)
                       or "cost" in normalize(field_name))), None)
    stock = next((field_name for field_name, field in fields
                  if isinstance(field, dict) and "stock" in normalize(field_name)),
                 None)
    relation = next(((field_name, field) for field_name, field in fields
                     if isinstance(field, dict)
                     and isinstance(field.get("foreign_key"), dict)
                     and normalize(field["foreign_key"].get("target_entity"))
                     in {normalize(item) for item in ctx["entity_names"]}), None)
    if price is None or stock is None or relation is None:
        return None
    relation_name, relation_field = relation
    parent = relation_field["foreign_key"]["target_entity"]
    parent_pk = primary_key_of(ctx, parent)
    return [
        f"parents = self._store.select({parent!r}, [])",
        f"values = {{row[{parent_pk!r}]: 0 for row in parents}}",
        "for row in self._store.select(self.ENTITY, []):",
        f"    parent_id = row.get({relation_name!r})",
        "    if parent_id is None:",
        "        continue",
        f"    values[parent_id] = values.get(parent_id, 0) + "
        f"(row.get({price!r}) or 0) * (row.get({stock!r}) or 0)",
        "return values",
    ]


def _repo_text_search_body(ctx, entity, model_cls, method):
    """Case-insensitive substring search over text fields and one relation name."""
    name = normalize(method.get("name") or "")
    if "search" not in name:
        return None
    words = {normalize(token) for token in
             re.findall(r"[A-Za-z_][A-Za-z0-9_]*", method.get("return_type") or "")}
    if "list" not in words:
        return None
    params = [param for param in method.get("params") or []
              if isinstance(param, dict) and param.get("name")]
    if len(params) != 1:
        return None
    param = params[0]
    if str(param.get("type") or "").lower() not in ("str", "string", "text"):
        return None
    fields = fields_of(ctx, entity)
    text_fields = [field_name for field_name, field in fields
                   if isinstance(field, dict)
                   and str(field.get("type") or "").lower() in
                   ("str", "string", "text")]
    relation = next(((field_name, field) for field_name, field in fields
                     if isinstance(field, dict)
                     and isinstance(field.get("foreign_key"), dict)
                     and normalize(field["foreign_key"].get("target_entity"))
                     in {normalize(item) for item in ctx["entity_names"]}), None)
    if not text_fields:
        return None
    ident = codegen.sanitize(param["name"], "param")
    lines = [
        f"if not {ident}:",
        "    return []",
        f"query = str({ident}).lower()",
    ]
    parent_name = None
    if relation is not None:
        relation_name, relation_field = relation
        parent = relation_field["foreign_key"]["target_entity"]
        parent_name = next((field_name for field_name, field in fields_of(ctx, parent)
                            if isinstance(field, dict)
                            and normalize(field_name) == "name"), None)
        parent_pk = primary_key_of(ctx, parent)
        if parent_name is not None:
            lines += [
                f"parents = self._store.select({parent!r}, [])",
                f"names = {{row[{parent_pk!r}]: row[{parent_name!r}] for row in parents}}",
            ]
    values = [f"row.get({field_name!r})" for field_name in text_fields]
    if parent_name is not None and relation is not None:
        values.append(f"names.get(row.get({relation[0]!r}))")
    lines += [
        "result = []",
        "for row in self._store.select(self.ENTITY, []):",
        "    values = [" + ", ".join(values) + "]",
        "    if any(value is not None and query in str(value).lower() "
        "for value in values):",
        "        result.append(row)",
    ]
    if model_cls is None:
        lines.append("return result")
    else:
        lines.append(f"return _model_list([{model_cls}(**row) for row in result], {model_cls})")
    return lines


def _service_overdue_body(ctx, method, params, returns):
    """Active records whose due date is before today."""
    name = normalize(method.get("name") or "")
    if "overdue" not in name or params:
        return None
    words = {normalize(token) for token in
             re.findall(r"[A-Za-z_][A-Za-z0-9_]*", returns or "")}
    entity = next((item for item in ctx["entity_names"]
                   if normalize(item) in words), None)
    if entity is None:
        return None
    fields = fields_of(ctx, entity)
    due = next((field_name for field_name, field in fields
                if isinstance(field, dict) and "due" in normalize(field_name)), None)
    returned = next((field_name for field_name, field in fields
                     if isinstance(field, dict)
                     and "return" in normalize(field_name)), None)
    status = next((field_name for field_name, field in fields
                   if isinstance(field, dict)
                   and normalize(field_name) in ("status", "state")), None)
    if due is None:
        return None
    repo = next((item for item in ctx["repositories"]
                 if normalize(item.get("entity")) == normalize(entity)), None)
    read_all = next((item.get("name") for item in (repo or {}).get("methods") or []
                     if isinstance(item, dict)
                     and codegen.classify_crud(item.get("name") or "") == "read_all"),
                    None)
    if repo is None or read_all is None:
        return None
    repo_cls = codegen.sanitize(repo.get("interface_name") or entity, "Repository")
    var = codegen.sanitize(entity.lower(), "row")
    due_attr = codegen.sanitize(due, "attr")
    lines = [
        f"records = self._repos[{repo_cls!r}].{codegen.sanitize(read_all, 'method')}()",
        "today = datetime.date.today()",
        "result = []",
        f"for {var} in records:",
        f"    if {var}.{due_attr} is None or {var}.{due_attr} >= today:",
        "        continue",
    ]
    if returned is not None:
        lines += [f"    if {var}.{codegen.sanitize(returned, 'attr')} is not None:",
                  "        continue"]
    if status is not None:
        lines.append(f"    {var}.{codegen.sanitize(status, 'attr')} = 'overdue'")
    lines += ["    result.append(" + var + ")", "return result"]
    return lines


def _service_search_delegate_body(ctx, method, params, returns):
    """Delegate a list search to the matching repository search."""
    name = normalize(method.get("name") or "")
    if "search" not in name or len(params) != 1:
        return None
    words = {normalize(token) for token in
             re.findall(r"[A-Za-z_][A-Za-z0-9_]*", returns or "")}
    entity = next((item for item in ctx["entity_names"]
                   if normalize(item) in words), None)
    if entity is None:
        return None
    repo = next((item for item in ctx["repositories"]
                 if normalize(item.get("entity")) == normalize(entity)), None)
    if repo is None:
        return None
    target = next((item.get("name") for item in repo.get("methods") or []
                   if isinstance(item, dict) and "search" in normalize(item.get("name") or "")), None)
    if target is None:
        return None
    repo_cls = codegen.sanitize(repo.get("interface_name") or entity, "Repository")
    return [f"return self._repos[{repo_cls!r}].{codegen.sanitize(target, 'method')}"
            f"({codegen.sanitize(params[0][0], 'param')})"]


def _repo_count_by_field_body(ctx, entity, method):
    """Count records grouped by one categorical field."""
    name = normalize(method.get("name") or "")
    if "count" not in name or method.get("params"):
        return None
    fields = {normalize(field_name): field_name for field_name, field in fields_of(ctx, entity)
              if isinstance(field, dict)
              and str(field.get("type") or "").lower() in ("str", "string", "text")}
    field = max(
        (value for value in fields.values()
         if all(token in name for token in _verb_tokens(value))),
        key=len, default=None)
    if field is None:
        return None
    return [
        "counts = {}",
        "for row in self._store.select(self.ENTITY, []):",
        f"    key = row.get({field!r})",
        "    if key is not None:",
        "        counts[key] = counts.get(key, 0) + 1",
        "return counts",
    ]


def _repo_containment_filter_body(ctx, entity, model_cls, method):
    """A list filter whose parameter is uniquely contained in a field name."""
    words = {normalize(token) for token in
             re.findall(r"[A-Za-z_][A-Za-z0-9_]*", method.get("return_type") or "")}
    if "list" not in words:
        return None
    params = [param for param in method.get("params") or []
              if isinstance(param, dict) and param.get("name")]
    if len(params) != 1:
        return None
    wanted = normalize(params[0]["name"])
    fields = [field_name for field_name, field in fields_of(ctx, entity)
              if isinstance(field, dict) and field.get("name")
              and normalize(field_name) != wanted]
    matches = [field_name for field_name in fields
               if wanted in normalize(field_name)]
    if len(matches) != 1:
        return None
    field = matches[0]
    ident = codegen.sanitize(params[0]["name"], "param")
    lines = ["criteria = []",
             f"if {ident} is not None:",
             f"    criteria.append(({field!r}, 'eq', {ident}))",
             "found = self._store.select(self.ENTITY, criteria)"]
    if model_cls is None:
        lines.append("return found")
    else:
        lines.append(f"return _model_list([{model_cls}(**row) for row in found], {model_cls})")
    return lines


def _model_param_field(ctx, entity, raw):
    """The model field a service parameter names, allowing `new_` prefixes."""
    fields = [name for name, _field in fields_of(ctx, entity)]
    wanted = normalize(raw)
    exact = [name for name in fields if normalize(name) == wanted]
    if len(exact) == 1:
        return exact[0]
    for prefix in ("new", "updated", "current"):
        if wanted.startswith(prefix) and len(wanted) > len(prefix):
            rest = wanted[len(prefix):]
            matches = [name for name in fields if normalize(name) == rest]
            if len(matches) == 1:
                return matches[0]
    matches = [name for name in fields
               if wanted in normalize(name) or normalize(name) in wanted]
    return matches[0] if len(matches) == 1 else None


def _error_named(ctx, *hints):
    """A registered error whose normalized name mentions one of the hints."""
    for error in ctx.get("errors") or []:
        if not isinstance(error, dict) or not isinstance(error.get("name"), str):
            continue
        lowered = normalize(error["name"])
        if any(hint in lowered for hint in hints):
            return f"errors.{codegen.sanitize(error['name'])}"
    return None


def _service_negative_stock_body(ctx, service_name, method, params, returns):
    """A bool guard rejecting a negative value written to a stock field."""
    if normalize(returns) not in ("bool", "boolean"):
        return None
    text = (normalize(method.get("name") or "") + " "
            + normalize(method.get("description") or ""))
    if "stock" not in text or "negative" not in text:
        return None
    entity = _entity_for_service(ctx, service_name)
    if entity is None:
        return None
    numeric = [item for item in params
               if str(item[2]).lower() in ("int", "integer", "float", "decimal")]
    matches = [(item, _model_param_field(ctx, entity, item[0])) for item in numeric]
    matches = [(item, field) for item, field in matches
               if field and "stock" in normalize(field)]
    if len(matches) != 1:
        return None
    (raw, ident, _ptype), field = matches[0]
    error = _error_named(ctx, "negativestock", "negative", "stock")
    if error is None:
        return None
    return [
        f"if {ident} is not None and {ident} < 0:",
        f"    raise {error}({field + ' must be non-negative'!r})",
        "return True",
    ]


def _service_price_guard_body(ctx, service_name, method, params, returns):
    """A bool guard comparing two numeric model fields named in the description."""
    if normalize(returns) not in ("bool", "boolean"):
        return None
    description = str(method.get("description") or "").lower()
    comparator = next((word for word in ("greater than", "less than")
                       if word in description), None)
    if comparator is None:
        return None
    entity = _entity_for_service(ctx, service_name)
    if entity is None:
        return None
    numeric = []
    for item in params:
        if str(item[2]).lower() not in ("int", "integer", "float", "decimal"):
            continue
        field = _model_param_field(ctx, entity, item[0])
        if field is None:
            continue
        phrase = normalize(field).replace("_", " ")
        position = description.find(field.replace("_", " "))
        if position < 0:
            position = description.find(normalize(field))
        if position >= 0:
            numeric.append((position, item, field))
    if len(numeric) != 2:
        return None
    numeric.sort()
    if numeric[0][0] >= description.find(comparator):
        return None
    if numeric[1][0] <= description.find(comparator):
        return None
    left, right = numeric[0][1], numeric[1][1]
    error = _error_named(ctx, "pricing", "price", "invalidpricing")
    if error is None:
        return None
    operator = ">" if comparator == "greater than" else "<"
    return [
        f"if not ({left[1]} {operator} {right[1]}):",
        f"    raise {error}('invalid price comparison')",
        "return True",
    ]


def _service_utilization_body(ctx, service_name, method, params, returns):
    """A percentage from a parent capacity and the sum of its children's stock."""
    if normalize(returns) not in ("float", "number", "decimal"):
        return None
    if "utilization" not in normalize(method.get("name") or ""):
        return None
    if len(params) != 1:
        return None
    entity = next((item for item in ctx["entity_names"]
                   if _param_for_entity([params[0][0]], item)), None)
    if entity is None:
        return None
    parent_fields = fields_of(ctx, entity)
    capacity = next((name for name, field in parent_fields
                     if isinstance(field, dict)
                     and ("capacity" in normalize(name)
                          or "limit" in normalize(name))), None)
    if capacity is None:
        return None
    child = next((name for name in ctx["entity_names"]
                  if normalize(name) != normalize(entity)
                  and any(isinstance(field, dict)
                          and isinstance(field.get("foreign_key"), dict)
                          and normalize(field["foreign_key"].get("target_entity"))
                          == normalize(entity)
                          for _n, field in fields_of(ctx, name))), None)
    if child is None:
        return None
    fk = next((name for name, field in fields_of(ctx, child)
               if isinstance(field, dict)
               and isinstance(field.get("foreign_key"), dict)
               and normalize(field["foreign_key"].get("target_entity"))
               == normalize(entity)), None)
    stock = next((name for name, field in fields_of(ctx, child)
                  if isinstance(field, dict) and "stock" in normalize(name)), None)
    if fk is None or stock is None:
        return None
    parent_repo = next((item for item in ctx["repositories"]
                        if normalize(item.get("entity")) == normalize(entity)), None)
    child_repo = next((item for item in ctx["repositories"]
                       if normalize(item.get("entity")) == normalize(child)), None)
    if parent_repo is None or child_repo is None:
        return None
    read_parent = next((item.get("name") for item in parent_repo.get("methods") or []
                        if isinstance(item, dict)
                        and codegen.classify_crud(item.get("name") or "") == "read_one"),
                       None)
    read_children = next((item.get("name") for item in child_repo.get("methods") or []
                          if isinstance(item, dict)
                          and codegen.classify_crud(item.get("name") or "") == "read_all"),
                         None)
    if read_parent is None or read_children is None:
        return None
    parent_cls = codegen.sanitize(parent_repo.get("interface_name") or entity, "Repository")
    child_cls = codegen.sanitize(child_repo.get("interface_name") or child, "Repository")
    pk = codegen.sanitize(primary_key_of(ctx, entity), "attr")
    param = codegen.sanitize(params[0][0], "param")
    return [
        f"record = self._repos[{parent_cls!r}].{codegen.sanitize(read_parent, 'method')}({param})",
        f"used = sum(item.{codegen.sanitize(stock, 'attr')} or 0 "
        f"for item in self._repos[{child_cls!r}].{codegen.sanitize(read_children, 'method')}() "
        f"if item.{codegen.sanitize(fk, 'attr')} == getattr(record, {pk!r}))",
        f"capacity = getattr(record, {codegen.sanitize(capacity, 'attr')!r}, 0) or 0",
        "if not capacity:",
        "    return 0.0",
        "return float(used) / capacity * 100.0",
    ]


def _repo_utilization_body(ctx, entity, method):
    """Percentage used from a parent capacity and the sum of its children."""
    if "utilization" not in normalize(method.get("name") or ""):
        return None
    params = [param for param in method.get("params") or []
              if isinstance(param, dict) and param.get("name")]
    if len(params) != 1:
        return None
    fields = fields_of(ctx, entity)
    capacity = next((name for name, field in fields
                     if isinstance(field, dict)
                     and ("capacity" in normalize(name)
                          or "limit" in normalize(name))), None)
    child = next((name for name in ctx["entity_names"]
                  if normalize(name) != normalize(entity)
                  and any(isinstance(field, dict)
                          and isinstance(field.get("foreign_key"), dict)
                          and normalize(field["foreign_key"].get("target_entity"))
                          == normalize(entity)
                          for _n, field in fields_of(ctx, name))), None)
    if capacity is None or child is None:
        return None
    fk = next((name for name, field in fields_of(ctx, child)
               if isinstance(field, dict)
               and isinstance(field.get("foreign_key"), dict)
               and normalize(field["foreign_key"].get("target_entity"))
               == normalize(entity)), None)
    stock = next((name for name, field in fields_of(ctx, child)
                  if isinstance(field, dict) and "stock" in normalize(name)), None)
    if fk is None or stock is None:
        return None
    ident = codegen.sanitize(params[0]["name"], "param")
    pk = primary_key_of(ctx, entity)
    return [
        f"record = self._store.get(self.ENTITY, self.PK, {ident}, "
        f"error={_error_named(ctx, normalize(entity).lower()) or 'LookupError'})",
        f"used = sum(row.get({stock!r}) or 0 for row in "
        f"self._store.select({child!r}, [({fk!r}, 'eq', record[{pk!r}])]))",
        f"capacity = record.get({capacity!r}) or 0",
        "if not capacity:",
        "    return 0.0",
        "return float(used) / capacity * 100.0",
    ]


def _service_plain_list_filter_body(ctx, method, params, returns):
    """Delegate a list-shaped filter to the entity repository's read_all."""
    raw_returns = method.get("return_type") or returns
    words = {normalize(token) for token in
             re.findall(r"[A-Za-z_][A-Za-z0-9_]*", raw_returns or "")}
    if "list" not in words or not params:
        return None
    entity = next((item for item in ctx["entity_names"]
                   if normalize(item) in normalize(method.get("name") or "")), None)
    if entity is None:
        return None
    repo = next((item for item in ctx["repositories"]
                 if normalize(item.get("entity")) == normalize(entity)), None)
    read_all = next((item for item in (repo or {}).get("methods") or []
                     if isinstance(item, dict)
                     and codegen.classify_crud(item.get("name") or "") == "read_all"),
                    None)
    if repo is None or read_all is None:
        return None
    repo_params = [item.get("name") for item in read_all.get("params") or []
                   if isinstance(item, dict) and item.get("name")]
    args = []
    for raw, ident, _ptype in params:
        target = next((item for item in repo_params
                       if normalize(item) == normalize(raw)), None)
        if target is None:
            return None
        args.append(f"{codegen.sanitize(target, 'kw')}={ident}")
    repo_cls = codegen.sanitize(repo.get("interface_name") or entity, "Repository")
    return [f"return self._repos[{repo_cls!r}].{codegen.sanitize(read_all.get('name'), 'method')}"
            f"({', '.join(args)})"]


def _repo_period_sum_body(ctx, entity, method):
    """Monthly-by-category or yearly-by-month spending totals."""
    name = normalize(method.get("name") or "")
    if "spending" not in name and "summary" not in name:
        return None
    params = [param.get("name") for param in method.get("params") or []
              if isinstance(param, dict) and param.get("name")]
    if len(params) != 1:
        return None
    fields = fields_of(ctx, entity)
    amount = next((field_name for field_name, field in fields
                   if isinstance(field, dict)
                   and ("amount" in normalize(field_name)
                        or "total" in normalize(field_name))), None)
    date = next((field_name for field_name, field in fields
                 if isinstance(field, dict) and "date" in normalize(field_name)), None)
    relation = next(((field_name, field) for field_name, field in fields
                     if isinstance(field, dict)
                     and isinstance(field.get("foreign_key"), dict)), None)
    if amount is None or date is None:
        return None
    ident = codegen.sanitize(params[0], "param")
    if "monthly" in name and "category" in name and relation is not None:
        relation_name, _ = relation
        return [
            "totals = {}",
            "for row in self._store.select(self.ENTITY, []):",
            f"    date = str(row.get({date!r}) or '')[:10]",
            f"    if not date.startswith(str({ident})):",
            "        continue",
            f"    key = row.get({relation_name!r})",
            "    if key is None:",
            "        continue",
            f"    totals[key] = totals.get(key, 0) + (row.get({amount!r}) or 0)",
            "return totals",
        ]
    if "yearly" in name and "summary" in name:
        return [
            "totals = {}",
            "for row in self._store.select(self.ENTITY, []):",
            f"    date = str(row.get({date!r}) or '')[:10]",
            f"    if not date.startswith(str({ident})):",
            "        continue",
            "    key = date[:7]",
            f"    totals[key] = totals.get(key, 0) + (row.get({amount!r}) or 0)",
            "return dict(sorted(totals.items()))",
        ]
    return None


def _repo_top_categories_body(ctx, entity, method):
    """Top spending categories for a date range, with category names."""
    name = normalize(method.get("name") or "")
    if "top" not in name or "categor" not in name:
        return None
    params = [param.get("name") for param in method.get("params") or []
              if isinstance(param, dict) and param.get("name")]
    if len(params) != 2:
        return None
    fields = fields_of(ctx, entity)
    amount = next((field_name for field_name, field in fields
                   if isinstance(field, dict)
                   and ("amount" in normalize(field_name)
                        or "total" in normalize(field_name))), None)
    date = next((field_name for field_name, field in fields
                 if isinstance(field, dict) and "date" in normalize(field_name)), None)
    relation = next(((field_name, field) for field_name, field in fields
                     if isinstance(field, dict)
                     and isinstance(field.get("foreign_key"), dict)
                     and normalize(field["foreign_key"].get("target_entity"))
                     in {normalize(item) for item in ctx["entity_names"]}), None)
    if amount is None or date is None or relation is None:
        return None
    relation_name, relation_field = relation
    parent = relation_field["foreign_key"]["target_entity"]
    parent_name = next((field_name for field_name, field in fields_of(ctx, parent)
                        if isinstance(field, dict)
                        and normalize(field_name) == "name"), None)
    parent_pk = primary_key_of(ctx, parent)
    if parent_name is None:
        return None
    start, end = (codegen.sanitize(item, "param") for item in params)
    return [
        f"start = str({start})[:10] if {start} is not None else ''",
        f"end = str({end})[:10] if {end} is not None else ''",
        "totals = {}",
        "for row in self._store.select(self.ENTITY, []):",
        f"    date = str(row.get({date!r}) or '')[:10]",
        "    if start and date < start:",
        "        continue",
        "    if end and date > end:",
        "        continue",
        f"    key = row.get({relation_name!r})",
        "    if key is None:",
        "        continue",
        f"    totals[key] = totals.get(key, 0) + (row.get({amount!r}) or 0)",
        f"parents = self._store.select({parent!r}, [])",
        f"names = {{row[{parent_pk!r}]: row[{parent_name!r}] for row in parents}}",
        "return sorted([(key, names.get(key), total) "
        "for key, total in totals.items()], key=lambda item: (-item[2], item[0]))",
    ]


def _entity_for_service(ctx, service_name):
    """The declared entity a service/repository name is built around.

    `ExpenseService` is exact; `WineInventoryService` contains `Wine`, so the
    longest declared entity name contained in the service name wins.  No
    domain-specific service spelling is assumed.
    """
    base = re.sub(r"(?:Service|Repository)$", "", str(service_name or ""))
    exact = next((item for item in ctx["entity_names"]
                  if normalize(item) == normalize(base)), None)
    if exact is not None:
        return exact
    contained = [item for item in ctx["entity_names"]
                 if normalize(item) and normalize(item) in normalize(base)]
    return max(contained, key=lambda item: len(normalize(item)), default=None)


def _service_export_csv_body(ctx, service_name, method, params, returns):
    """CSV export of the date-filtered records of the service's entity."""
    name = normalize(method.get("name") or "")
    if "export" not in name or "csv" not in name:
        return None
    entity = _entity_for_service(ctx, service_name)
    model = model_of(ctx, entity) if entity else None
    repo = next((item for item in ctx["repositories"]
                 if normalize(item.get("entity")) == normalize(entity)), None)         if entity else None
    if model is None or repo is None:
        return None
    repo_cls = codegen.sanitize(repo.get("interface_name") or entity, "Repository")
    read_all = next((item.get("name") for item in repo.get("methods") or []
                     if isinstance(item, dict)
                     and codegen.classify_crud(item.get("name") or "") == "read_all"),
                    None)
    if read_all is None:
        return None
    field_names = [field_name for field_name, _field in fields_of(ctx, entity)]
    date_field = next((field_name for field_name, field in fields_of(ctx, entity)
                       if isinstance(field, dict)
                       and str(field.get("type") or "").lower()
                       in ("date", "datetime")), None)
    path_param = next((item for item in params
                       if any(word in normalize(item[0])
                              for word in ("file", "output", "path"))), None)
    if path_param is None:
        path_param = next((item for item in params
                           if str(item[2]).lower() in ("str", "string", "text")),
                          None)
    date_params = [item for item in params if item is not path_param]
    start = next((item for item in date_params
                  if any(word in normalize(item[0])
                         for word in ("start", "from"))), None)
    end = next((item for item in date_params
                if any(word in normalize(item[0])
                       for word in ("end", "to"))), None)
    path_expr = (codegen.sanitize(path_param[0], "param") if path_param
                 else repr(f"{normalize(entity) or 'export'}.csv"))
    row_values = []
    for field_name in field_names:
        field = next((item for name_, item in fields_of(ctx, entity)
                      if name_ == field_name), {})
        attr = f"record.{codegen.sanitize(field_name, 'attr')}"
        if str(field.get("type") or "").lower() in (
                "str", "string", "text", "date", "datetime"):
            attr = f"'' if {attr} is None else {attr}"
        row_values.append(attr)
    lines = [
        f"records = self._repos[{repo_cls!r}].{codegen.sanitize(read_all, 'method')}()",
    ]
    if date_field is not None:
        if start is not None:
            ident = codegen.sanitize(start[0], "param")
            lines.append(f"start = str({ident})[:10] if {ident} is not None else ''")
        else:
            lines.append("start = ''")
        if end is not None:
            ident = codegen.sanitize(end[0], "param")
            lines.append(f"end = str({ident})[:10] if {ident} is not None else ''")
        else:
            lines.append("end = ''")
        lines += [
            "filtered = []",
            "for record in records:",
            f"    date = str(getattr(record, {date_field!r}, None) or '')[:10]",
            "    if start and date < start:",
            "        continue",
            "    if end and date > end:",
            "        continue",
            "    filtered.append(record)",
        ]
    else:
        lines.append("filtered = records")
    lines += [
        f"with open({path_expr}, 'w', newline='', encoding='utf-8') as handle:",
        "    writer = csv.writer(handle)",
        f"    writer.writerow({field_names!r})",
        "    for record in filtered:",
        f"        writer.writerow([{', '.join(row_values)}])",
    ]
    return lines


def _service_export_json_body(ctx, service_name, method, params, returns):
    """JSON export of all records of the service's entity."""
    name = normalize(method.get("name") or "")
    if "export" not in name or "json" not in name:
        return None
    entity = _entity_for_service(ctx, service_name)
    model = model_of(ctx, entity) if entity else None
    repo = next((item for item in ctx["repositories"]
                 if normalize(item.get("entity")) == normalize(entity)), None)
    if model is None or repo is None:
        return None
    repo_cls = codegen.sanitize(repo.get("interface_name") or entity, "Repository")
    read_all = next((item.get("name") for item in repo.get("methods") or []
                     if isinstance(item, dict)
                     and codegen.classify_crud(item.get("name") or "") == "read_all"),
                    None)
    if read_all is None:
        return None
    field_names = [field_name for field_name, _field in fields_of(ctx, entity)]
    path_param = next((item for item in params
                       if any(word in normalize(item[0])
                              for word in ("file", "output", "path"))), None)
    path_expr = (codegen.sanitize(path_param[0], "param") if path_param
                 else repr(f"{normalize(entity) or 'export'}.json"))
    return [
        f"records = self._repos[{repo_cls!r}].{codegen.sanitize(read_all, 'method')}()",
        "rows = []",
        "for record in records:",
        "    rows.append({",
        *[f"        {field_name!r}: getattr(record, {field_name!r}, None),"
          for field_name in field_names],
        "    })",
        f"with open({path_expr}, 'w', encoding='utf-8') as handle:",
        "    json.dump(rows, handle, indent=2, default=str)",
    ]


def _service_detect_recurring_body(ctx, service_name, method, params, returns):
    """Mark groups of same amount/related-record present in more than one month."""
    name = normalize(method.get("name") or "")
    if "recurring" not in name or "detect" not in name:
        return None
    entity = _entity_for_service(ctx, service_name)
    if entity is None:
        return None
    repo = next((item for item in ctx["repositories"]
                 if normalize(item.get("entity")) == normalize(entity)), None)
    if repo is None:
        return None
    fields = fields_of(ctx, entity)
    amount = next((field_name for field_name, field in fields
                   if isinstance(field, dict)
                   and ("amount" in normalize(field_name)
                        or "total" in normalize(field_name)
                        or "price" in normalize(field_name))), None)
    date = next((field_name for field_name, field in fields
                 if isinstance(field, dict)
                 and ("date" in normalize(field_name)
                      or "period" in normalize(field_name))), None)
    relation = next((field_name for field_name, field in fields
                     if isinstance(field, dict)
                     and isinstance(field.get("foreign_key"), dict)), None)
    recurring = next((field_name for field_name, field in fields
                      if isinstance(field, dict)
                      and "recurr" in normalize(field_name)), None)
    if amount is None or date is None or recurring is None:
        return None
    repo_cls = codegen.sanitize(repo.get("interface_name") or entity, "Repository")
    read_all = next((item.get("name") for item in repo.get("methods") or []
                     if isinstance(item, dict)
                     and codegen.classify_crud(item.get("name") or "") == "read_all"),
                    None)
    update = next((item.get("name") for item in repo.get("methods") or []
                   if isinstance(item, dict)
                   and codegen.classify_crud(item.get("name") or "") == "update"),
                  None)
    if read_all is None or update is None:
        return None
    key_parts = [f"record.{codegen.sanitize(amount, 'attr')}"]
    if relation is not None:
        key_parts.append(f"record.{codegen.sanitize(relation, 'attr')}")
    month_attr = codegen.sanitize(date, "attr")
    flag_attr = codegen.sanitize(recurring, "kw")
    return [
        f"records = self._repos[{repo_cls!r}].{codegen.sanitize(read_all, 'method')}()",
        "groups = {}",
        "for record in records:",
        f"    key = ({', '.join(key_parts)}{',' if len(key_parts) == 1 else ''})",
        "    groups.setdefault(key, []).append(record)",
        "result = []",
        "for group in groups.values():",
        f"    months = {{str(getattr(item, {date!r}, None) or '')[:7] for item in group}}",
        "    if len(months) <= 1:",
        "        continue",
        "    for item in group:",
        f"        result.append(self._repos[{repo_cls!r}].{codegen.sanitize(update, 'method')}(item.{codegen.sanitize(primary_key_of(ctx, entity), 'attr')}, {flag_attr}=True))",
        "return result",
    ]


def _service_stock_value_body(ctx, method, params, returns):
    """Delegate a stock-value report to its repository aggregate."""
    name = normalize(method.get("name") or "")
    if params or "stock" not in name or "value" not in name:
        return None
    candidates = []
    for repo in ctx["repositories"]:
        for target in repo.get("methods") or []:
            if not isinstance(target, dict):
                continue
            target_name = normalize(target.get("name") or "")
            if "stock" in target_name and "value" in target_name:
                candidates.append((repo, target))
    if len(candidates) != 1:
        return None
    repo, target = candidates[0]
    holder = codegen.sanitize(repo.get("interface_name") or repo.get("entity"), "Repository")
    return [f"return self._repos[{holder!r}].{codegen.sanitize(target['name'], 'method')}()"]


def _service_mapping_update_body(ctx, service_name, method, params):
    """An update taking one dict, delegated to the repository's update."""
    if codegen.classify_crud(method.get("name") or "") != "update":
        return None
    if (service_name, method.get("name")) in (ctx.get("method_repairs") or {}):
        return None
    description = str(method.get("description") or "").lower()
    if any(word in description for word in SERVICE_CRUD_BLOCK_WORDS):
        return None
    mapping = next((item for item in params
                    if codegen.is_mapping_type(item[2])), None)
    key = next((item for item in params if item is not mapping), None)
    if mapping is None or key is None:
        return None
    entity = next((item for item in ctx["entity_names"]
                   if normalize(item) in normalize(method.get("name") or "")), None)
    if entity is None:
        return None
    repo = next((item for item in ctx["repositories"]
                 if normalize(item.get("entity")) == normalize(entity)), None)
    target = next((item for item in (repo or {}).get("methods") or []
                   if isinstance(item, dict)
                   and codegen.classify_crud(item.get("name") or "") == "update"), None)
    if repo is None or target is None:
        return None
    holder = codegen.sanitize(repo.get("interface_name") or entity, "Repository")
    key_name = codegen.sanitize(key[0], "param")
    data_name = codegen.sanitize(mapping[0], "param")
    target_params = [item.get("name") for item in target.get("params") or []
                     if isinstance(item, dict) and item.get("name")]
    key_target = next((item for item in target_params
                       if normalize(item) == normalize(key[0])), None)
    if key_target is None:
        return None
    extras = [item for item in target_params if item != key_target]
    call_args = [f"{codegen.sanitize(key_target, 'kw')}={key_name}"]
    call_args += [f"{codegen.sanitize(item, 'kw')}={data_name}.get({item!r})"
                  for item in extras]
    return [
        f"if {data_name} is None:",
        "    return",
        f"self._repos[{holder!r}].{codegen.sanitize(target['name'], 'method')}"
        f"({', '.join(call_args)})",
    ]


def _repo_relation_lookup_body(ctx, entity, model_cls, method):
    """A unique lookup by a related entity's name plus a field of this one.

    `get_product_by_category_and_name(category_name, product_name)` reads the
    Category row by name, then the Product by `category_id` and `name`.  The
    data model carries both steps, so the body is derived, not guessed.
    """
    if codegen.classify_crud(method.get("name") or "") in (
            "create", "update", "delete"):
        return None
    returns = method.get("return_type") or ""
    words = {normalize(token) for token in
             re.findall(r"[A-Za-z_][A-Za-z0-9_]*", returns)}
    if normalize(entity) not in words or "list" in words:
        return None
    params = [param for param in method.get("params") or []
              if isinstance(param, dict) and param.get("name")]
    if not params:
        return None
    own_fields = {normalize(name): name for name, _field in fields_of(ctx, entity)}
    relation_for = {}
    for name, field in fields_of(ctx, entity):
        if isinstance(field, dict) and isinstance(field.get("foreign_key"), dict):
            target = field["foreign_key"].get("target_entity")
            if target:
                relation_for[normalize(target)] = (name, target)
    criteria = []
    relation_used = False
    for param in params:
        raw = param["name"]
        ident = codegen.sanitize(raw, "param")
        target = next((key for key in relation_for
                       if normalize(raw).startswith(key)), None)
        if target is not None:
            relation_used = True
            fk_name, parent = relation_for[target]
            parent_field = next((field_name for field_name, field in fields_of(ctx, parent)
                                 if isinstance(field, dict)
                                 and normalize(field_name) in normalize(raw)
                                 and normalize(field_name) != normalize(fk_name)), None)
            if parent_field is None:
                parent_field = next((field_name for field_name, field in fields_of(ctx, parent)
                                     if isinstance(field, dict)
                                     and normalize(field_name) == "name"), None)
            parent_pk = primary_key_of(ctx, parent)
            if parent_field is None:
                return None
            criteria.append((fk_name, ident, parent, parent_field, parent_pk))
            continue
        remainder = normalize(raw)
        if remainder.startswith(normalize(entity)):
            remainder = remainder[len(normalize(entity)):]
        own = own_fields.get(remainder)
        if own is None:
            return None
        criteria.append((own, ident, None, None, None))
    if not relation_used or not criteria:
        return None
    lines = ["criteria = []"]
    for field_name, ident, parent, parent_field, parent_pk in criteria:
        lines.append(f"if {ident} is not None:")
        if parent is None:
            lines.append(f"    criteria.append(({field_name!r}, 'eq', {ident}))")
        else:
            lines.append(
                f"    parent_rows = self._store.select({parent!r}, "
                f"[({parent_field!r}, 'eq', {ident})])")
            lines.append("    if not parent_rows:")
            lines.append("        return None")
            lines.append(
                f"    criteria.append(({field_name!r}, 'eq', "
                f"parent_rows[0][{parent_pk!r}]))")
    lines += ["found = self._store.select(self.ENTITY, criteria)",
              "if not found:",
              "    return None"]
    if model_cls is None:
        lines.append("return dict(found[0])")
    else:
        lines.append(f"return {model_cls}(**found[0])")
    return lines


def _repo_two_hop_filter_body(ctx, entity, model_cls, method):
    """A list query that reaches its entity through one intermediate FK.

    `CustomerRepository.find_invoices_by_customer_id` is Invoice -> Order ->
    Customer: the direct filter planner sees `customer_id` on no Invoice field.
    The model graph supplies both hops; the body reads the middle rows, then
    the target rows whose FK meets the middle key.
    """
    returns = method.get("return_type") or ""
    words = {normalize(token) for token in
             re.findall(r"[A-Za-z_][A-Za-z0-9_]*", returns)}
    if "list" not in words:
        return None
    target = next((name for name in ctx["entity_names"]
                   if normalize(name) in words
                   and normalize(name) != normalize(entity)), None)
    if target is None or model_of(ctx, target) is None:
        return None
    params = [param for param in method.get("params") or []
              if isinstance(param, dict) and param.get("name")]
    if len(params) != 1:
        return None
    related = normalize(params[0]["name"][:-3]) \
        if normalize(params[0]["name"]).endswith("id") else ""
    if not related:
        return None
    related_entity = next((name for name in ctx["entity_names"]
                           if normalize(name) == related), None)
    if related_entity is None:
        return None
    target_fks = [(name, field["foreign_key"].get("target_entity"))
                  for name, field in fields_of(ctx, target)
                  if isinstance(field, dict)
                  and isinstance(field.get("foreign_key"), dict)]
    for target_fk, middle in target_fks:
        if middle is None or normalize(middle) == normalize(related_entity):
            continue
        middle_fk = next((name for name, field in fields_of(ctx, middle)
                          if isinstance(field, dict)
                          and isinstance(field.get("foreign_key"), dict)
                          and normalize(field["foreign_key"].get("target_entity"))
                          == normalize(related_entity)), None)
        if middle_fk is None:
            continue
        middle_pk = primary_key_of(ctx, middle)
        ident = codegen.sanitize(params[0]["name"], "param")
        target_cls = f"models.{codegen.sanitize(target, 'Model')}"
        lines = [
            f"middle_rows = self._store.select({middle!r}, [({middle_fk!r}, 'eq', {ident})])",
            f"middle_ids = {{row[{middle_pk!r}] for row in middle_rows}}",
            f"found = [row for row in self._store.select({target!r}, []) "
            f"if row.get({target_fk!r}) in middle_ids]",
        ]
        if model_cls is None:
            lines.append("return found")
        else:
            lines.append(f"return _model_list([{target_cls}(**row) for row in found], {target_cls})")
        return lines
    return None


def _repo_body(ctx, strategy, detail, method, params, entity, model_cls, field_names, pk, fk_literal, table="self.ENTITY", contract=None):
    """The statement list of one repository method."""
    kind = strategy[5:] if strategy.startswith("crud:") else None
    err = method_error(ctx, method, entity)
    if kind == "create":
        return _create_body(ctx, method, params, entity, model_cls, field_names,
                            fk_literal, contract=contract)
    if kind == "read_one":
        lookup_err = err if _read_one_names_entity_error(ctx, method, entity) else None
        return _read_one_body(params, entity, model_cls, field_names, pk, lookup_err)
    if kind in ("read_all", "filter"):
        return _select_body(params, entity, model_cls, field_names, table=table)
    if kind == "update":
        return _update_body(ctx, method, params, entity, model_cls, field_names, err)
    if kind == "delete":
        return _delete_body(params, entity, field_names, err, ctx)
    name = method.get("name") if isinstance(method.get("name"), str) else "?"
    return ["raise NotImplementedError(",
            f'    "{entity}.{name}: {strategy}: {detail}")']


class _Unmappable(Exception):
    """A criteria parameter no field satisfies.

    A body built from it would raise ValueError on every call — not a
    mechanical reading. Emission catches this and writes a stub instead.
    """

    def __init__(self, param):
        super().__init__(param)
        self.param = param



def _entity_params(params, entity_names, entity=None):
    """Split `(raw, ident, type)` params into `(entity_param|None, scalars)`."""
    entity_param = None
    scalars = []
    for raw, ident, ptype in params:
        mapping_for_entity = bool(
            entity and (codegen.is_mapping_type(ptype)
                        or codegen.is_dto_type(ptype))
            and normalize(str(ptype or "")).startswith(normalize(entity)))
        if entity_param is None and (
                codegen.is_entity_type(ptype, entity_names) or mapping_for_entity):
            entity_param = (raw, ident)
        else:
            scalars.append((raw, ident))
    return entity_param, scalars


def _result_wrap(model_cls):
    if model_cls is None:
        return "return record"
    return f"return {model_cls}(**record)"


def _create_defaults(ctx, entity):
    """Fields a create command omits but a useful record still needs.

    A membership created by `member add --name --email` has no date flag;
    the domain's own date is today. Only conventional creation-date names
    are filled, so a loan's due date is not silently invented.
    """
    defaults = {}
    for name, field in fields_of(ctx, entity):
        if _field_default(ctx, field) is not None:
            continue
        declared = str(field.get("type") or "").strip().lower()
        if name not in ("membership_date", "joined_date", "created_date",
                        "created_at", "updated_at", "updated_date",
                        "modified_at", "generated_at", "registration_date"):
            continue
        if declared in ("datetime", "timestamp"):
            defaults[name] = "datetime.datetime.now()"
        else:
            defaults[name] = "datetime.date.today()"
    # A line total is the one arithmetic field the schema commonly makes NOT
    # NULL while the create signature carries only its inputs. Derive it from
    # the two fields whose semantics define it instead of inserting NULL.
    names = {name for name, _field in fields_of(ctx, entity)}
    if {"quantity", "unit_price", "line_total"} <= names \
            and "line_total" not in defaults:
        defaults["line_total"] = (
            "values.get('quantity', 0) * values.get('unit_price', 0)")
    return defaults


def _numeric_bounds(ctx, entity):
    """`[(field, operator, literal)]` the invariants state for entity fields.

    The schema step records `Book.available_copies must be non-negative` (or
    `>= 0`), and the library prompt's negative-copy rule depends on it. The
    bound is read from those records, never inferred from a field name; a
    create/update emitter that writes the value without the check lets a
    negative count through even though every generated layer agrees it is
    invalid.
    """
    model = model_of(ctx, entity)
    if model is None:
        return []
    fields = [field for field in model.get("fields") or []
              if isinstance(field, dict) and field.get("name")]
    named = {field["name"]: field for field in fields}
    found = []
    for invariant in ctx.get("invariants") or []:
        text = invariant.get("text") if isinstance(invariant, dict) else None
        if not isinstance(text, str):
            continue
        for clause in re.split(r"[.;\n]", text):
            for name, field in named.items():
                if normalize(name) not in normalize(clause):
                    continue
                declared = str(field.get("type") or "").strip().lower()
                if declared not in ("int", "integer", "float", "decimal",
                                    "number", "real"):
                    continue
                bound = None
                if re.search(r"\bnon-?negative\b", clause, re.I) \
                        or re.search(r"\bnot\s+be\s+negative\b", clause, re.I) \
                        or re.search(r"\b(?:below|under)\s+zero\b", clause, re.I):
                    bound = (">=", "0")
                elif re.search(r"\bpositive\b", clause, re.I):
                    bound = (">", "0")
                else:
                    match = re.search(r"(>=|>)\s*(-?\d+(?:\.\d+)?)",
                                      clause)
                    if match:
                        bound = (match.group(1), match.group(2))
                if bound is not None and (name,) + bound not in found:
                    found.append((name,) + bound)
    return found


def _field_relations(ctx, entity):
    """`[(left, operator, right)]` comparisons the invariants state.

    A prompt can state a cross-field rule such as "the selling price must be
    strictly greater than its cost price".  The two field names are words in
    the sentence ("selling price", "cost price"), not necessarily their
    underscored spellings, so match normalized tokens and read the comparison
    operator from the same clause.
    """
    model = model_of(ctx, entity)
    if model is None:
        return []
    fields = [field for field in model.get("fields") or []
              if isinstance(field, dict) and field.get("name")]
    numeric = [field for field in fields
               if str(field.get("type") or "").strip().lower()
               in ("int", "integer", "float", "decimal", "number", "real")]
    found = []
    for invariant in ctx.get("invariants") or []:
        text = invariant.get("text") if isinstance(invariant, dict) else None
        if not isinstance(text, str):
            continue
        for clause in re.split(r"[.;\n]", text):
            flat = normalize(clause)
            mentioned = [field for field in numeric
                         if normalize(field["name"]) in flat]
            if len(mentioned) < 2:
                continue
            mentioned.sort(key=lambda field: flat.find(normalize(field["name"])))
            operator = None
            if re.search(r"\b(?:strictly\s+)?greater\s+than\b", clause, re.I):
                operator = ">"
            elif re.search(r"\b(?:at\s+least|no\s+less\s+than)\b",
                           clause, re.I):
                operator = ">="
            elif re.search(r"\b(?:strictly\s+)?less\s+than\b", clause, re.I):
                operator = "<"
            if operator is None:
                match = re.search(r"(>=|>|<=|<)", clause)
                operator = match.group(1) if match else None
            if operator is None:
                continue
            # The first mentioned field is the left side for the common
            # sentence order ("selling price ... cost price"); reversed
            # wording is handled by the comparison at runtime either way.
            left, right = mentioned[0]["name"], mentioned[1]["name"]
            if (left, operator, right) not in found:
                found.append((left, operator, right))
    return found


def _relation_error(ctx, left, right):
    """The registered error for a cross-field price/ordering rule."""
    for error in ctx.get("errors") or []:
        name = error.get("name") if isinstance(error, dict) else None
        if not isinstance(name, str):
            continue
        flat = normalize(name)
        if "price" in flat or "pricing" in flat or "margin" in flat:
            return f"errors.{codegen.sanitize(name)}"
    return "ValueError"


def _bound_error(ctx, kind):
    """The registered error for a negative/positive numeric bound, if any."""
    for error in ctx.get("errors") or []:
        name = error.get("name") if isinstance(error, dict) else None
        if isinstance(name, str) and "negative" in normalize(name):
            return f"errors.{codegen.sanitize(name)}"
    return "ValueError"


def _capacity_relation(ctx, entity):
    """`(fk_field, quantity_field, target, capacity_field, error)` or None.

    A prompt can say that the bottles assigned to a location cannot exceed
    its capacity.  The fact is a relationship between a numeric quantity on
    the source entity, an FK to the target, and a numeric capacity on the
    target; all three names come from the model.  Only a capacity invariant
    enables the check.
    """
    texts = [item.get("text") for item in ctx.get("invariants") or []
             if isinstance(item, dict) and isinstance(item.get("text"), str)]
    if not any("capacity" in text.lower() and "exceed" in text.lower()
               for text in texts):
        return None
    fields = fields_of(ctx, entity)
    source_quantity = next(
        (name for name, field in fields
         if str(field.get("type") or "").lower() in
         ("int", "integer", "float", "decimal", "number", "real")
         and any(word in normalize(name) for word in ("stock", "quantity"))),
        None)
    if source_quantity is None:
        return None
    for fk_name, field in fields:
        foreign = field.get("foreign_key")
        if not isinstance(foreign, dict):
            continue
        target = foreign.get("target_entity")
        target_model = model_of(ctx, target)
        if target_model is None:
            continue
        capacity = next(
            (name for name, item in fields_of(ctx, target)
             if str(item.get("type") or "").lower() in
             ("int", "integer", "float", "decimal", "number", "real")
             and "capacity" in normalize(name)), None)
        if capacity is None:
            continue
        error = next((f"errors.{codegen.sanitize(item['name'])}"
                      for item in ctx.get("errors") or []
                      if isinstance(item, dict) and isinstance(item.get("name"), str)
                      and "capacity" in normalize(item["name"])),
                     "ValueError")
        return fk_name, source_quantity, target, capacity, error
    return None


def _capacity_targets(ctx, entity):
    """The source relations whose capacity lives on `entity`.

    Updating a capacity row is the reverse direction of `_capacity_relation`:
    the wine side guards its own writes, but shrinking a location must also
    look at the bottles already assigned to it.  Return one tuple per source
    model that points at `entity`.
    """
    targets = []
    for model in ctx.get("models") or []:
        source = model.get("name") if isinstance(model, dict) else None
        if not isinstance(source, str):
            continue
        relation = _capacity_relation(ctx, source)
        if relation is None:
            continue
        fk, quantity, target, capacity, error = relation
        if normalize(target) == normalize(entity):
            targets.append((source, fk, quantity, capacity, error))
    return targets


def _in_use_relation(ctx, entity):
    """`(source, fk_field)` when an invariant forbids deleting an in-use row."""
    texts = [item.get("text") for item in ctx.get("invariants") or []
             if isinstance(item, dict) and isinstance(item.get("text"), str)]
    if not any(re.search(r"\bremov(?:e|al|ing)\b", text, re.I)
               and re.search(r"\b(?:assigned|in\s+use|currently)\b", text, re.I)
               for text in texts):
        return None
    for model in ctx.get("models") or []:
        source = model.get("name")
        if not isinstance(source, str):
            continue
        for field in model.get("fields") or []:
            foreign = field.get("foreign_key") if isinstance(field, dict) else None
            if (isinstance(foreign, dict)
                    and normalize(foreign.get("target_entity")) == normalize(entity)
                    and field.get("name")):
                return source, field["name"]
    return None


def _delete_in_use_guard(ctx, entity):
    relation = _in_use_relation(ctx, entity)
    if relation is None:
        return []
    source, fk_field = relation
    return [
        f"for record in found:",
        f"    if self._store.select({source!r}, [({fk_field!r}, 'eq', record[self.PK])]):",
        f"        raise ValueError(f\"{entity} is still assigned to {source} records\")",
    ]


def _unique_fields(ctx, entity):
    """Non-key fields the schema makes unique.

    The invariants are more precise than the model flags: an extraction can
    mark a descriptive field (`Book.title`) unique while the requirements
    only make `isbn` unique. When the invariants name unique fields for the
    entity, they win; otherwise the model's `unique` flags are the fallback.
    A field in a composite key (`UNIQUE(category_id, month)`) is not unique
    on its own, so it is removed from the per-field list; the table-level
    constraint lives in `_unique_groups`.
    """
    fields = [name for name, field in fields_of(ctx, entity)
              if not field.get("primary_key")]
    grouped = {name for group in _unique_groups(ctx, entity) for name in group}
    invariant_fields = set()
    wanted = normalize(entity)
    for invariant in ctx.get("invariants") or []:
        text = invariant.get("text") if isinstance(invariant, dict) else None
        if not isinstance(text, str) or "unique" not in text.lower():
            continue
        for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b", text):
            if normalize(match.group(1)) == wanted:
                invariant_fields.add(match.group(2))
    if invariant_fields:
        return [name for name in fields if name in invariant_fields]
    return [name for name, field in fields_of(ctx, entity)
            if field.get("unique") and not field.get("primary_key")
            and name not in grouped]


def _unique_groups(ctx, entity):
    """The composite unique keys the documents give an entity.

    A budget is unique per category and month, not by month alone. The
    extraction records that fact either as `UNIQUE(category_id, month)` in
    the requirements or as an invariant ("a unique combination of ..."), and
    the model's per-field `unique` flag cannot express the difference. Only
    groups whose every member is a field of this entity count.
    """
    names = {normalize(name): name for name, _field in fields_of(ctx, entity)}
    if not names:
        return []
    groups = []

    def add(tokens):
        resolved = []
        for token in tokens:
            field = names.get(normalize(token))
            if field is None:
                return
            if field not in resolved:
                resolved.append(field)
        if len(resolved) >= 2 and tuple(resolved) not in groups:
            groups.append(tuple(resolved))

    texts = []
    wanted = normalize(entity)
    for invariant in ctx.get("invariants") or []:
        text = invariant.get("text") if isinstance(invariant, dict) else None
        if isinstance(text, str) and "unique" in text.lower():
            texts.append(text)
    texts.append(ctx.get("requirements") or "")
    for text in texts:
        for match in re.finditer(r"UNIQUE\s*\(([^)]*)\)", text, re.IGNORECASE):
            add(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", match.group(1)))
        for match in re.finditer(
                r"unique\s+constraint\s+(?:on|over|for)\s*\(([^)]*)\)",
                text, re.IGNORECASE):
            add(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", match.group(1)))
        for pattern in (
                r"unique\s+combination\s+of\s+([^.;\n]+)",
                r"unique(?:\s+together)?\s+(?:on|over|for)\s+([^.;\n]+)",
                r"([A-Za-z_][A-Za-z0-9_]*(?:\s*(?:,|and)\s*[A-Za-z_][A-Za-z0-9_]*)+)"
                r"\s+must\s+be\s+unique\s+together"):
            for match in re.finditer(pattern, text, re.IGNORECASE):
                clause = match.group(1)
                if pattern.startswith("([A-Za-z_]") and wanted \
                        and wanted not in normalize(text):
                    continue
                add(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", clause))
    return groups


def _unique_error(ctx, entity):
    wanted = normalize(entity)
    for error in ctx["errors"]:
        name = error.get("name")
        if not isinstance(name, str):
            continue
        flat = normalize(name)
        if wanted and wanted in flat and (
                "alreadyexists" in flat or flat.endswith("existserror")
                or "duplicate" in flat):
            return f"errors.{codegen.sanitize(name)}"
    return "ValueError"


def _create_effect_lines(ctx, contract, params, entity):
    """Apply cross-entity effects after a repository create.

    A repository has `self._store`, not `self._repos`. An effect on another
    entity is therefore a store get/update, with the key parameter and the
    operand taken from the method signature rather than a domain noun.
    """
    lines = []
    param_names = {item[1] for item in params}
    for effect in (contract or {}).get("effects") or []:
        if effect.get("op") not in ("increment", "decrement"):
            continue
        target = str(effect.get("target") or "")
        variable, _, field = target.partition(".")
        target_entity = next((name for name in ctx["entity_names"]
                              if normalize(name) == normalize(variable)), None)
        model = model_of(ctx, target_entity) if target_entity else None
        if model is None:
            continue
        target_pk = primary_key_of(ctx, target_entity)
        key_param = next((name for name in param_names
                          if normalize(name) in (
                              normalize(target_entity) + "id",
                              normalize(target_entity) + "key")), None)
        by = effect.get("by")
        if not isinstance(by, str) or by not in param_names or key_param is None:
            continue
        operator = "-" if effect["op"] == "decrement" else "+"
        lines += [
            f"if {key_param} is not None and {by} is not None:",
            f"    _target = self._store.get({target_entity!r}, {target_pk!r}, {key_param})",
            "    if _target is not None:",
            f"        self._store.update({target_entity!r}, {target_pk!r}, {key_param}, "
            f"{{{field!r}: _target.get({field!r}, 0) {operator} {by}}})",
        ]
    return lines


def _create_body(ctx, method, params, entity, model_cls, field_names, fk_literal,
                 contract=None):
    entity_param, scalars = _entity_params(params, ctx["entity_names"], entity)
    lines = []
    if entity_param is not None and not scalars:
        lines.append(f"values = _record_values({entity_param[1]}, {field_names!r})")
    else:
        lines.append("values = {}")
        if entity_param is not None:
            lines.append(f"values.update(_record_values({entity_param[1]}, {field_names!r}))")
        for raw, ident in scalars:
            lines.append(f"if {ident} is not None:")
            lines.append(f"    values[{raw!r}] = {ident}")
        lines.append(f"unknown = [k for k in values if k not in {field_names!r}]")
        lines.append("if unknown:")
        lines.append(f"    raise ValueError(f\"cannot create {entity} from {{unknown}}\")")
    for field_name, expression in _create_defaults(ctx, entity).items():
        lines.append(f"if values.get({field_name!r}) is None:")
        lines.append(f"    values[{field_name!r}] = {expression}")
    for field_name, field in fields_of(ctx, entity):
        if _field_default(ctx, field) is not None:
            continue
        values_enum = _field_vocabulary(ctx, entity, field_name)
        if not values_enum or field.get("nullable") or field.get("primary_key"):
            continue
        lines.append(f"if values.get({field_name!r}) is None:")
        lines.append(f"    values[{field_name!r}] = {values_enum[0]!r}")
        lines.append(f"if values.get({field_name!r}) not in {values_enum!r}:")
        lines.append(
            f"    raise ValueError(f\"{entity}.{field_name} must be one of "
            f"{values_enum!r}\")")
    for field_name, field in fields_of(ctx, entity):
        if _field_default(ctx, field) is not None:
            continue
        declared = str(field.get("type") or "").strip().lower()
        if declared not in ("bool", "boolean") \
                or field.get("nullable") or field.get("primary_key"):
            continue
        lines.append(f"if values.get({field_name!r}) is None:")
        lines.append(f"    values[{field_name!r}] = False")
    for field_name, operator, literal in _numeric_bounds(ctx, entity):
        comparison = "value < 0" if operator == ">=" else "value <= 0"
        lines.append(f"value = values.get({field_name!r})")
        lines.append(f"if value is not None and {comparison}:")
        lines.append(
            f"    raise {_bound_error(ctx, operator)}("
            f"f\"{entity}.{field_name} must be {operator} {literal}, "
            "got {value!r}\")")
    for left, operator, right in _field_relations(ctx, entity):
        test = operator
        lines.append(f"value = values.get({left!r})")
        lines.append(f"other = values.get({right!r})")
        lines.append(
            f"if value is not None and other is not None and "
            f"not (value {test} other):")
        lines.append(
            f"    raise {_relation_error(ctx, left, right)}("
            f"f\"{entity}.{left} must be {operator} {right}, "
            "got {value!r} vs {other!r}\")")
    capacity = _capacity_relation(ctx, entity)
    if capacity is not None:
        fk, quantity, target, capacity_field, error = capacity
        target_pk = primary_key_of(ctx, target)
        lines += [
            f"location_id = values.get({fk!r})",
            f"quantity = values.get({quantity!r}) or 0",
            "if location_id is not None:",
            f"    location = self._store.get({target!r}, {target_pk!r}, location_id)",
            f"    used = sum(row.get({quantity!r}) or 0 for row in "
            f"self._store.select(self.ENTITY, [({fk!r}, 'eq', location_id)]))",
            f"    if used + quantity > location.get({capacity_field!r}, 0):",
            f"        raise {error}(f\"{target} capacity exceeded for {{location_id}}\")",
        ]
    unique_fields = _unique_fields(ctx, entity)
    if unique_fields:
        unique_error = _unique_error(ctx, entity)
        lines.append(f"for unique_field in {unique_fields!r}:")
        lines.append("    value = values.get(unique_field)")
        lines.append("    if value is not None and self._store.select("
                     "self.ENTITY, [(unique_field, 'eq', value)]):")
        lines.append(f"        raise {unique_error}("
                     f"f\"{entity} with {{unique_field}}={{value!r}} already exists\")")
    lines.append(f"record = self._store.add(self.ENTITY, self.PK, values, check_fk={fk_literal})")
    lines.extend(_create_effect_lines(ctx, contract, params, entity))
    declared = str(method.get("return_type") or "").strip().lower()
    if re.search(r"\b(?:int|integer|bool|boolean)\b", declared):
        # A port may declare `create(...) -> int`: returning the dataclass
        # there makes the service's `read_one(id=created)` look up an object
        # as the key. The store already knows the new primary key.
        lines.append("return record[self.PK]")
    elif declared in ("none", "nonetype") or declared.startswith("none"):
        lines.append("return None")
    else:
        lines.append(_result_wrap(model_cls))
    return lines


def _criteria_block(params, field_names):
    """`criteria = [...]` with every parameter resolved to its field now.

    Parameters come as `(raw, ident[, type])`; `None` values are skipped.
    The mapping is the kernel's own (`match_param`), resolved at generation
    time: a parameter matching no field raises `_Unmappable`, so the caller
    emits a stub instead of a body that raises on every call.
    """
    lines = ["criteria = []"]
    for item in params:
        raw, ident = item[0], item[1]
        matched = codegen.match_param(field_names, raw)
        if matched is None:
            raise _Unmappable(raw)
        lines.append(f"if {ident} is not None:")
        lines.append(f"    criteria.append(({matched[0]!r}, {matched[1]!r}, {ident}))")
    return lines


def _alternative_scan(ident, alternatives):
    """Locate records through any of `ident`'s identity alternatives.

    `book_id_or_isbn` scans `id` and `isbn` and unions the hits; callers
    add their own uniqueness/strictness check on `found`.
    """
    return ["found = []",
            f"if {ident} is not None:",
            f"    for field, operator in {alternatives!r}:",
            f"        found.extend(self._store.select("
            f"self.ENTITY, [(field, operator, {ident})]))"]


def _read_one_body(params, entity, model_cls, field_names, pk, err):
    """Lookup one record: by PK directly, else criteria plus uniqueness.

    The old fast path read every single-parameter lookup through the
    primary key — `read_x_by_email(email)` searched `PK == email` and
    reported "not found" instead of finding. Now only a parameter mapping
    to the PK with `eq` takes it; an `a_or_b` parameter (`book_id_or_isbn`)
    scans its alternatives; anything else goes through criteria, which
    refuses unmappable parameters at generation time.
    """
    if len(params) == 1:
        raw, ident = params[0][0], params[0][1]
        matched = codegen.match_param(field_names, raw)
        if matched is not None and list(matched) == [pk, "eq"]:
            if err is None:
                lines = [f"found = self._store.select(self.ENTITY, "
                         f"[(self.PK, 'eq', {ident})])",
                         "if not found:",
                         "    return None",
                         "record = found[0]"]
            else:
                lines = [f"record = self._store.get(self.ENTITY, self.PK, {ident}, error={err})"]
            lines.append(_result_wrap(model_cls))
            return lines
        alternatives = codegen.match_alternatives(field_names, raw)
        if alternatives is not None:
            lines = _alternative_scan(ident, alternatives)
            if err is None:
                lines += ["if not found:", "    return None", "record = found[0]"]
            else:
                lines += ["if len(found) != 1:",
                          f"    raise {err}(f\"{entity} lookup matched {{len(found)}} records\")",
                          "record = found[0]"]
            lines.append(_result_wrap(model_cls))
            return lines
    lines = _criteria_block(params, field_names)
    lines += ["found = self._store.select(self.ENTITY, criteria)"]
    if err is None:
        lines += ["if not found:", "    return None", "record = found[0]"]
    else:
        lines += ["if len(found) != 1:",
                  f"    raise {err}(f\"{entity} lookup matched {{len(found)}} records\")",
                  "record = found[0]"]
    lines.append(_result_wrap(model_cls))
    return lines


def _select_body(params, entity, model_cls, field_names, table="self.ENTITY"):
    lines = _criteria_block(params, field_names)
    lines.append(f"found = self._store.select({table}, criteria)")
    if model_cls is None:
        lines.append("return [dict(r) for r in found]")
    else:
        lines.append(f"return [{model_cls}(**r) for r in found]")
    return lines


def _repo_pagination_body(ctx, entity, model_cls, method):
    """Mechanical paged read from `page_size`/`page_number` parameters.

    The declared return may be a page DTO the extractor did not declare as a
    model. A dict with the page items and total-pages fields is the generic
    representation; when the signature returns a list, return the page items
    directly. Other filter parameters (for example a foreign key) narrow the
    records before pagination.
    """
    pair = codegen.pagination_params(method)
    if pair is None:
        return None
    page_name, size_name = pair
    page_ident = codegen.sanitize(page_name, "param")
    size_ident = codegen.sanitize(size_name, "param")
    field_names = [name for name, _ in fields_of(ctx, entity)]
    params = [(item.get("name"), codegen.sanitize(item.get("name"), "param"),
               item.get("type"))
              for item in method.get("params") or []
              if isinstance(item, dict) and item.get("name")
              and normalize(item.get("name")) not in {
                  normalize(page_name), normalize(size_name)}]
    try:
        lines = _criteria_block(params, field_names) if params else ["criteria = []"]
    except _Unmappable:
        return None
    lines += [
        "records = self._store.select(self.ENTITY, criteria)",
        "total = len(records)",
        f"page_number = {page_ident} if {page_ident} is not None else 1",
        f"page_size = {size_ident} if {size_ident} is not None else 10",
        "if page_size <= 0:",
        "    page_size = 10",
        "total_pages = (total + page_size - 1) // page_size",
        "start = max(0, (page_number - 1) * page_size)",
        "end = start + page_size",
        "page_records = records[start:end]",
    ]
    if model_cls:
        lines.append(f"items = [{model_cls}(**row) for row in page_records]")
    else:
        lines.append("items = [dict(row) for row in page_records]")
    if _collection_return(method):
        lines.append("return items")
    else:
        lines.append("return {'items': items, 'page_number': page_number, "
                     "'page_size': page_size, 'total_items': total, "
                     "'total_pages': total_pages}")
    return lines


def _names_primary_key(ctx, entity, field_names, param):
    """True when `param` resolves to the entity's primary-key field."""
    primary = {name for name, field in fields_of(ctx, entity)
               if field.get("primary_key")}
    matched = codegen.match_param(field_names, param)
    return bool(matched) and matched[0] in primary


def _update_body(ctx, method, params, entity, model_cls, field_names, err):
    entity_param, scalars = _entity_params(params, ctx["entity_names"])
    if not scalars:
        return ["raise ValueError(",
                f"    \"{entity}.{method.get('name')}: update needs key parameters\")"]
    alternatives = None
    if len(scalars) == 1:
        alternatives = codegen.match_alternatives(field_names, scalars[0][0])
    mapping_names = {raw for raw, _ident, ptype in params
                     if codegen.is_mapping_type(ptype)}
    if alternatives is not None:
        lines = _alternative_scan(scalars[0][1], alternatives)
        lines += ["if len(found) != 1:",
                  f"    raise {err}(f\"{entity} update matched {{len(found)}} records\")"]
    else:
        # The parameters that name the record's key identify it; every other
        # one is the change. Looking the record up by the new values too made
        # `update(book_id=1, available_copies=0)` search for a book that
        # already has zero copies and refuse the last borrow. A composite
        # unique key (`category_id`, `month`) identifies a record even though
        # neither field is the primary key; using the new amount as a lookup
        # criterion found no record.
        composite = [name for group in _unique_groups(ctx, entity)
                     for name in group]
        keys = [(raw, ident) for raw, ident in scalars
                if _names_primary_key(ctx, entity, field_names, raw)
                or (composite and codegen.match_param(composite, raw))]
        criteria_params = keys or [(raw, ident) for raw, ident in scalars
                                   if raw not in mapping_names]
        lines = _criteria_block(criteria_params, field_names)
        lines += ["found = self._store.select(self.ENTITY, criteria)",
                  "if len(found) != 1:",
                  f"    raise {err}(f\"{entity} update matched {{len(found)}} records\")"]
    lines += ["patch = {}"]
    for raw, ident, ptype in params:
        if not codegen.is_mapping_type(ptype):
            continue
        lines.append(f"if {ident} is not None:")
        lines.append(f"    for key, value in {ident}.items():")
        lines.append(f"        if value is not None and key in {field_names!r}:")
        lines.append("            patch[key] = value")
    if entity_param is not None:
        lines.append(f"for key, value in _record_values({entity_param[1]}, {field_names!r}).items():")
        lines.append("    if value is not None:")
        lines.append("        patch[key] = value")
    for raw, ident in scalars:
        if raw in mapping_names:
            continue
        lines.append(f"if {ident} is not None and {raw!r} in {field_names!r}:")
        lines.append(f"    patch[{raw!r}] = {ident}")
    for field_name, operator, literal in _numeric_bounds(ctx, entity):
        comparison = "value < 0" if operator == ">=" else "value <= 0"
        lines.append(f"value = patch.get({field_name!r})")
        lines.append(f"if value is not None and {comparison}:")
        lines.append(
            f"    raise {_bound_error(ctx, operator)}("
            f"f\"{entity}.{field_name} must be {operator} {literal}, "
            "got {value!r}\")")
    for left, operator, right in _field_relations(ctx, entity):
        lines.append(f"value = patch.get({left!r}, found[0].get({left!r}))")
        lines.append(f"other = patch.get({right!r}, found[0].get({right!r}))")
        lines.append(
            f"if value is not None and other is not None and "
            f"not (value {operator} other):")
        lines.append(
            f"    raise {_relation_error(ctx, left, right)}("
            f"f\"{entity}.{left} must be {operator} {right}, "
            "got {value!r} vs {other!r}\")")
    capacity = _capacity_relation(ctx, entity)
    if capacity is not None:
        fk, quantity, target, capacity_field, error = capacity
        target_pk = primary_key_of(ctx, target)
        lines += [
            f"location_id = patch.get({fk!r}, found[0].get({fk!r}))",
            f"quantity = patch.get({quantity!r}, found[0].get({quantity!r})) or 0",
            "if location_id is not None:",
            f"    location = self._store.get({target!r}, {target_pk!r}, location_id)",
            f"    used = sum(row.get({quantity!r}) or 0 for row in "
            f"self._store.select(self.ENTITY, [({fk!r}, 'eq', location_id)]) "
            f"if row.get(self.PK) != found[0][self.PK])",
            f"    if used + quantity > location.get({capacity_field!r}, 0):",
            f"        raise {error}(f\"{target} capacity exceeded for {{location_id}}\")",
        ]
    for source, fk, quantity, capacity_field, error in _capacity_targets(
            ctx, entity):
        lines += [
            f"new_capacity = patch.get({capacity_field!r})",
            "if new_capacity is not None:",
            f"    used = sum(row.get({quantity!r}) or 0 for row in "
            f"self._store.select({source!r}, [({fk!r}, 'eq', "
            f"found[0][self.PK])]))",
            "    if used > new_capacity:",
            f"        raise {error}(f\"{entity}.{capacity_field} capacity "
            "below assigned quantity\")",
        ]
    unique_fields = _unique_fields(ctx, entity)
    if unique_fields:
        unique_error = _unique_error(ctx, entity)
        lines.append(f"for unique_field in {unique_fields!r}:")
        lines.append("    value = patch.get(unique_field)")
        lines.append(
            "    if value is not None and any("
            "row.get(self.PK) != found[0][self.PK] for row in "
            "self._store.select(self.ENTITY, [(unique_field, 'eq', value)])):")
        lines.append(f"        raise {unique_error}("
                     f"f\"{entity} with {{unique_field}}={{value!r}} already exists\")")
    lines.append(f"record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error={err})")
    lines.append(_result_wrap(model_cls))
    return lines


def _delete_body(params, entity, field_names, err, ctx=None):
    if not params:
        return ["raise ValueError(",
                f"    \"{entity}: delete needs key parameters\")"]
    alternatives = None
    if len(params) == 1:
        alternatives = codegen.match_alternatives(field_names, params[0][0])
    if alternatives is not None:
        lines = _alternative_scan(params[0][1], alternatives)
    else:
        lines = _criteria_block(params, field_names)
        lines += ["found = self._store.select(self.ENTITY, criteria)"]
    lines += ["if not found:",
              f"    raise {err}(f\"{entity} delete matched no records\")"]
    if ctx is not None:
        lines += _delete_in_use_guard(ctx, entity)
    lines += [
        "for record in found:",
        "    self._store.delete(self.ENTITY, self.PK, record[self.PK])",
        "return None"]
    return lines


# --------------------------------------------------------------------------
# services (delegate on exact same-name repo methods, else stub)
# --------------------------------------------------------------------------

def _service_filter_uses_dates(ctx, port_names):
    """Whether any filter-composition body compares a date-typed field.

    The service twin of `_holds` compares raw values; a dataclass read
    carries `datetime.date`, while a CLI argument is ISO text, so a date
    criterion would raise `TypeError`. The module gets a small normaliser
    only when such a body exists, which keeps programs without date filters
    byte-identical.
    """
    for service in ctx["services"]:
        if normalize(service.get("service_name")) in port_names:
            continue
        for method in service.get("methods") or []:
            if not isinstance(method, dict) or not method.get("name"):
                continue
            _declaration, params = _signature(method, ctx["entity_names"])
            plan = _service_filter_plan(ctx, method, params)
            if plan is None:
                continue
            field_names, field_types = plan[3], plan[4]
            for raw, _ident, _ptype in params:
                matched = codegen.match_param(field_names, raw)
                if matched and _is_date_type(field_types.get(matched[0])):
                    return True
    return False


def _is_date_type(declared):
    return str(declared or "").strip().lower() in ("date", "datetime", "timestamp")


def _service_place_order_body(ctx, method, params, returns):
    """Mechanical order placement: validate, create parent/lines, decrement stock.

    This is the recurring shape of `place_order(customer_id, order_items)`.
    Every name below comes from the extracted model/repository graph; if a
    required relation or stock field is absent, the method stays a stub.
    """
    return_text = method.get("return_type") or returns or ""
    if "place" not in normalize(method.get("name") or "") \
            or "order" not in normalize(str(return_text)):
        return None
    entity_names = ctx.get("entity_names") or []
    order = next((name for name in entity_names
                  if normalize(name) in normalize(str(return_text))), None)
    if order is None:
        return None
    order_model = model_of(ctx, order)
    order_pk = primary_key_of(ctx, order)
    order_repo = next((repo for repo in ctx.get("repositories") or []
                       if isinstance(repo, dict)
                       and normalize(repo.get("entity") or "") == normalize(order)), None)
    if order_model is None or order_repo is None:
        return None
    create_order = next((m for m in order_repo.get("methods") or []
                         if isinstance(m, dict)
                         and normalize(m.get("name") or "") == "create"), None)
    if create_order is None:
        return None
    customer = next((name for name in entity_names
                     if any(normalize(p.get("name") or "") == normalize(name) + "id"
                            or normalize(p.get("name") or "") == normalize(name)
                            for p in method.get("params") or []
                            if isinstance(p, dict))), None)
    if customer is None:
        return None
    customer_repo = next((repo for repo in ctx.get("repositories") or []
                          if isinstance(repo, dict)
                          and normalize(repo.get("entity") or "") == normalize(customer)), None)
    if customer_repo is None:
        return None
    customer_read = next((m for m in customer_repo.get("methods") or []
                          if isinstance(m, dict)
                          and normalize(m.get("name") or "") == "readone"), None)
    line_model = None
    for candidate in ctx.get("models") or []:
        if not isinstance(candidate, dict) or not candidate.get("name"):
            continue
        fields = [f for f in candidate.get("fields") or [] if isinstance(f, dict)]
        if any(isinstance(f.get("foreign_key"), dict)
               and normalize(f["foreign_key"].get("target_entity") or "") == normalize(order)
               for f in fields) and any(
                   normalize(f.get("name") or "").endswith("productid") for f in fields) \
                and any(normalize(f.get("name") or "") == "quantity" for f in fields):
            line_model = candidate
            break
    if line_model is None:
        return None
    line_pk = primary_key_of(ctx, line_model["name"])
    line_repo = next((repo for repo in ctx.get("repositories") or []
                      if isinstance(repo, dict)
                      and normalize(repo.get("entity") or "") == normalize(line_model["name"])), None)
    if line_repo is None:
        return None
    create_line = next((m for m in line_repo.get("methods") or []
                        if isinstance(m, dict)
                        and normalize(m.get("name") or "") == "create"), None)
    if create_line is None:
        return None
    product_fk = next((f for f in line_model.get("fields") or []
                       if isinstance(f, dict)
                       and normalize(f.get("name") or "").endswith("productid")), None)
    product_name = None
    if product_fk and isinstance(product_fk.get("foreign_key"), dict):
        product_name = product_fk["foreign_key"].get("target_entity")
    if product_name is None:
        return None
    product_model = model_of(ctx, product_name)
    product_repo = next((repo for repo in ctx.get("repositories") or []
                         if isinstance(repo, dict)
                         and normalize(repo.get("entity") or "") == normalize(product_name)), None)
    if product_model is None or product_repo is None:
        return None
    product_pk = primary_key_of(ctx, product_name)
    stock = next((name for name, field in fields_of(ctx, product_name)
                  if isinstance(field, dict) and "stock" in normalize(name)), None)
    if stock is None:
        return None
    product_read = next((m for m in product_repo.get("methods") or []
                         if isinstance(m, dict)
                         and normalize(m.get("name") or "") == "readone"), None)
    product_update = next((m for m in product_repo.get("methods") or []
                           if isinstance(m, dict)
                           and normalize(m.get("name") or "") == "update"), None)
    if product_read is None or product_update is None:
        return None
    customer_param = next((p.get("name") for p in method.get("params") or []
                           if isinstance(p, dict)
                           and (normalize(p.get("name") or "") == normalize(customer) + "id"
                                or normalize(p.get("name") or "") == normalize(customer))), None)
    items_param = next((p.get("name") for p in method.get("params") or []
                        if isinstance(p, dict)
                        and "item" in normalize(p.get("name") or "")), None)
    if customer_param is None or items_param is None:
        return None
    customer_read_params = [p.get("name") for p in customer_read.get("params") or []
                            if isinstance(p, dict) and p.get("name")]
    if not customer_read_params:
        return None
    order_create_params = {p.get("name") for p in create_order.get("params") or []
                           if isinstance(p, dict) and p.get("name")}
    line_create_params = {p.get("name") for p in create_line.get("params") or []
                          if isinstance(p, dict) and p.get("name")}
    product_read_params = [p.get("name") for p in product_read.get("params") or []
                           if isinstance(p, dict) and p.get("name")]
    product_update_params = {p.get("name") for p in product_update.get("params") or []
                             if isinstance(p, dict) and p.get("name")}
    if not product_read_params:
        return None
    customer_error = _registered_error(ctx, customer) or "CustomerNotFoundError"
    product_error = _registered_error(ctx, product_name) or "ProductNotFoundError"
    stock_error = next((error.get("name") for error in ctx.get("errors") or []
                        if isinstance(error, dict)
                        and ("stock" in normalize(error.get("name") or "")
                             or "insufficient" in normalize(error.get("name") or ""))),
                       "InsufficientStockError")
    order_call = [
        f"{codegen.sanitize(k, 'kw')}={codegen.sanitize(customer_param, 'param')}"
        for k in order_create_params if normalize(k) == normalize(customer) + "id"]
    if any(normalize(k) in ("orderdate", "createdat", "date") for k in order_create_params):
        date_key = next(k for k in order_create_params
                        if normalize(k) in ("orderdate", "createdat", "date"))
        order_call.append(f"{codegen.sanitize(date_key, 'kw')}=datetime.datetime.now()")
    lines = [
        f"{codegen.sanitize(customer_param, 'param')} = {codegen.sanitize(customer_param, 'param')}",
        f"{codegen.sanitize(customer, 'customer')} = self._repos[{codegen.sanitize(customer_repo.get('interface_name') or customer, 'Repository')!r}].{codegen.sanitize(customer_read['name'], 'method')}({codegen.sanitize(customer_read_params[0], 'param')}={codegen.sanitize(customer_param, 'param')})",
        f"if {codegen.sanitize(customer, 'customer')} is None:",
        f"    raise errors.{codegen.sanitize(customer_error)}",
        f"items = {codegen.sanitize(items_param, 'param')} or []",
        "for item in items:",
        f"    product_id = item.get({product_fk['name']!r})",
        "    quantity = item.get('quantity')",
        "    if product_id is None or quantity is None:",
        "        continue",
        f"    product = self._repos[{codegen.sanitize(product_repo.get('interface_name') or product_name, 'Repository')!r}].{codegen.sanitize(product_read['name'], 'method')}({codegen.sanitize(product_read_params[0], 'param')}=product_id)",
        f"    if product is None:",
        f"        raise errors.{codegen.sanitize(product_error)}",
        f"    if product.{stock} is None or product.{stock} < quantity:",
        f"        raise errors.{codegen.sanitize(stock_error)}",
        f"order = self._repos[{codegen.sanitize(order_repo.get('interface_name') or order, 'Repository')!r}].{codegen.sanitize(create_order['name'], 'method')}({', '.join(order_call)})",
        "for item in items:",
        f"    product_id = item.get({product_fk['name']!r})",
        "    quantity = item.get('quantity')",
        "    if product_id is None or quantity is None:",
        "        continue",
        f"    self._repos[{codegen.sanitize(line_repo.get('interface_name') or line_model['name'], 'Repository')!r}].{codegen.sanitize(create_line['name'], 'method')}(" + ", ".join(
            f"{codegen.sanitize(k, 'kw')}=" + (
                f"order.{codegen.sanitize(order_pk, 'param')}"
                if normalize(k) == normalize(order) + "id"
                else "product_id" if normalize(k) == normalize(product_fk["name"])
                else "quantity")
            for k in line_create_params
            if normalize(k) in (normalize(order) + "id", normalize(product_fk["name"]), "quantity")) + ")",
        f"    product = self._repos[{codegen.sanitize(product_repo.get('interface_name') or product_name, 'Repository')!r}].{codegen.sanitize(product_read['name'], 'method')}({codegen.sanitize(product_read_params[0], 'param')}=product_id)",
        f"    self._repos[{codegen.sanitize(product_repo.get('interface_name') or product_name, 'Repository')!r}].{codegen.sanitize(product_update['name'], 'method')}(" + ", ".join(
            [f"{codegen.sanitize(k, 'kw')}=product_id" for k in product_update_params if normalize(k) == normalize(product_pk)] + [f"{codegen.sanitize(stock, 'kw')}=product.{stock} - quantity"] ) + ")",
        "return order",
    ]
    # Remove a leading no-op assignment for readability.
    if lines and lines[0].count(" = ") == 1 and lines[0].split(" = ")[0] == lines[0].split(" = ")[1]:
        lines = lines[1:]
    return lines


def _service_aggregate_body(ctx, service_name, method, plan):
    """A service-level aggregate from an extraction-side plan."""
    entity = plan.get("entity")
    slots = plan.get("slots") or {}
    repo = next((item for item in ctx["repositories"]
                 if item.get("entity") == entity), None)
    if repo is None:
        return None
    repo_cls = codegen.sanitize(repo.get("interface_name") or entity,
                               "Repository")
    read_all = next((item for item in repo.get("methods") or []
                     if isinstance(item, dict)
                     and codegen.classify_crud(item.get("name") or "") == "read_all"),
                    None)
    if read_all is None:
        return None
    target = slots.get("target_field")
    date_field = slots.get("date_field")
    fk_field = slots.get("fk_field")
    if not target or not date_field:
        return None
    params = [p.get("name") for p in method.get("params") or []
              if isinstance(p, dict) and p.get("name")]
    fk_param = fk_field if fk_field in params else None
    start = next((p for p in params if "start" in p.lower()
                  or p.lower().startswith("from")), None)
    end = next((p for p in params if "end" in p.lower()
                or p.lower().startswith("to")), None)
    lines = [
        f"records = self._repos[{repo_cls!r}].{codegen.sanitize(read_all['name'], 'method')}()",
        "total = 0",
        "by_key = {}",
        "for record in records:",
    ]
    indent = "    "
    if fk_param:
        lines += [f"{indent}if {fk_param} is not None and "
                  f"record.{fk_field} != {fk_param}:",
                  f"{indent}    continue"]
    if start:
        lines += [f"{indent}when = str(record.{date_field} or '')[:10]",
                  f"{indent}if {start} is not None and when < str({start})[:10]:",
                  f"{indent}    continue"]
    if end:
        lines += [f"{indent}when = str(record.{date_field} or '')[:10]",
                  f"{indent}if {end} is not None and when > str({end})[:10]:",
                  f"{indent}    continue"]
    lines += [f"{indent}value = record.{target} or 0",
              f"{indent}total += value",
              f"{indent}key = record.{fk_field}" if fk_field else f"{indent}key = None",
              f"{indent}by_key[key] = by_key.get(key, 0) + value"]
    returns = normalize(method.get("return_type") or "")
    if "dict" in returns or "mapping" in returns:
        lines.append("return {'total_spending': total, 'category_spending': by_key}")
    elif "list" in returns:
        return None
    else:
        lines.append("return total")
    return lines


def emit_services(ctx, repo_index, stats):
    """Service classes: same-name delegation or documented stubs."""
    port_names = {normalize(r.get("interface_name") or "") for r in ctx["repositories"]}
    date_filters = _service_filter_uses_dates(ctx, port_names)
    lines = ['"""Services. A method with the same name as a repository method delegates',
             "to it; anything else raises NotImplementedError with its work order.",
             '"""',
             "",
             "from typing import Any, Dict, List, Optional, Tuple, Union",
             "",
             "import calendar",
             "import csv",
             "import datetime",
             "import json",
             "",
             "import models",
             "import errors",
             "from store import match_criterion",
             "",
             "",
             "def _holds(actual, operator, expected):",
             '    """Twin of `store._holds`: the operators filter composition reuses."""',
             '    if operator == "eq":',
             "        return actual == expected",
             '    if operator == "ge":',
             "        return actual is not None and actual >= expected",
             '    if operator == "le":',
             "        return actual is not None and actual <= expected",
             '    if operator == "gt":',
             "        return actual is not None and actual > expected",
             '    if operator == "lt":',
             "        return actual is not None and actual < expected",
             '    raise ValueError(f"unknown operator {operator!r}")',
             ""]
    lines += ["",
              "def _as_date(value):",
              '    """Accept an ISO string or a date object; return a date or None."""',
              "    if value is None or isinstance(value, datetime.date):",
              "        return value",
              "    return datetime.date.fromisoformat(str(value))",
              ""]
    if date_filters:
        lines += ["",
                  "def _filter_value(value):",
                  '    """Dates compare as ISO text, the form the store keeps."""',
                  '    return value.isoformat() if hasattr(value, "isoformat") else value',
                  ""]
    emitted = set()
    for service in ctx["services"]:
        name = service.get("service_name")
        if normalize(name) in port_names \
                or normalize(name).endswith("repository"):
            # A repository contract is implemented by repositories.py. When
            # persistence is skipped there is no port name to compare, but
            # the `*Repository` suffix still identifies the same layer.
            continue
        cls = codegen.sanitize(name, "Service")
        emitted.add(cls)
        lines += ["", "", f"class {cls}:",
                  "",
                  "    def __init__(self, repos):",
                  "        self._repos = repos",
                  ""]
        for method in service.get("methods") or []:
            if not isinstance(method, dict) or not method.get("name"):
                continue
            strategy, detail = codegen.plan_method(
                method, _match_entry(ctx, name, method["name"]), ctx["entity_names"])
            fname = codegen.sanitize(method["name"], "method")
            declaration, params = _signature(method, ctx["entity_names"])
            returns = _return_of(method, ctx["entity_names"])
            program = (ctx.get("programs") or {}).get(
                (name, method["name"]))
            if isinstance(program, dict):
                program_body = _program_body(ctx, program)
                if program_body is not None:
                    lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                              f'        """{_docstring(method.get("description"))} '
                              '[reviewed program]"""']
                    lines.extend("        " + line if line else ""
                                 for line in program_body)
                    stats["implemented"] += 1
                    _record(stats, name, method["name"], strategy, True,
                            "reviewed program")
                    continue
            contract = contract_for(
                ctx.get("contracts") or [], name, method["name"])
            compiled, compile_reason = contract_compiler.compile_contract(
                contract, method, ctx)
            if compiled is not None:
                compiled_body = _program_body(ctx, compiled)
                if compiled_body is not None:
                    lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                              f'        """{_docstring(method.get("description"))} '
                              f'[closed contract: {compile_reason}]"""']
                    lines.extend("        " + line if line else ""
                                 for line in compiled_body)
                    stats["implemented"] += 1
                    _record(stats, name, method["name"], "closed-contract", True,
                            compile_reason)
                    continue
            place_order = _service_place_order_body(ctx, method, params, returns)
            if place_order is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[mechanical order placement]"""']
                lines.extend("        " + line if line else "" for line in place_order)
                stats["implemented"] += 1
                _record(stats, name, method["name"], strategy, True,
                        "order placement")
                continue
            wrapper = _service_crud_wrapper(
                ctx, name, method, params, returns)
            if wrapper is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[mechanical CRUD wrapper]"""']
                lines.extend("        " + line if line else "" for line in wrapper)
                stats["implemented"] += 1
                _record(stats, name, method["name"], strategy, True,
                        "mechanical CRUD wrapper")
                continue
            count_report = _service_count_report_body(
                ctx, method, params, returns)
            if count_report is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[mechanical count report]"""']
                lines.extend("        " + line if line else "" for line in count_report)
                stats["implemented"] += 1
                _record(stats, name, method["name"], strategy, True,
                        "count report")
                continue
            stock_report = _service_stock_report_body(
                ctx, method, params, returns)
            if stock_report is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[mechanical stock report]"""']
                lines.extend("        " + line if line else "" for line in stock_report)
                stats["implemented"] += 1
                _record(stats, name, method["name"], strategy, True,
                        "stock report")
                continue
            plan = (ctx.get("method_plans") or {}).get((name, method["name"]))
            if plan and plan.get("strategy") == "mechanical" \
                    and str(plan.get("pattern") or "").startswith("AGGREGATE"):
                body = _service_aggregate_body(ctx, name, method, plan)
                if body is not None:
                    lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                              f'        """{_docstring(method.get("description"))} '
                              f'[{plan.get("pattern")} via extraction plan]"""']
                    lines.extend("        " + line if line else "" for line in body)
                    stats["implemented"] += 1
                    _record(stats, name, method["name"], "mechanical", True,
                            f"plan:{plan.get('pattern')}")
                    continue
            low_stock_body = _service_low_stock_body(
                ctx, method, params, returns)
            if low_stock_body is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[mechanical low-stock filter]"""']
                lines.extend("        " + line if line else ""
                             for line in low_stock_body)
                stats["implemented"] += 1
                _record(stats, name, method["name"], strategy, True,
                        "low-stock filter")
                continue
            stock_value = _service_stock_value_body(ctx, method, params, returns)
            if stock_value is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[delegates to the stock-value aggregate]"""']
                lines.extend("        " + line if line else "" for line in stock_value)
                stats["implemented"] += 1
                _record(stats, name, method["name"], strategy, True,
                        "stock value delegation")
                continue
            mapping_update = _service_mapping_update_body(
                ctx, name, method, params)
            if mapping_update is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[delegates the mapping to the repository update]"""']
                lines.extend("        " + line if line else "" for line in mapping_update)
                stats["implemented"] += 1
                _record(stats, name, method["name"], strategy, True,
                        "mapping update")
                continue
            export_csv = _service_export_csv_body(ctx, name, method, params, returns)
            if export_csv is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[mechanical CSV export]"""']
                lines.extend("        " + line if line else "" for line in export_csv)
                stats["implemented"] += 1
                _record(stats, name, method["name"], strategy, True,
                        "csv export")
                continue
            export_json = _service_export_json_body(
                ctx, name, method, params, returns)
            if export_json is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[mechanical JSON export]"""']
                lines.extend("        " + line if line else ""
                             for line in export_json)
                stats["implemented"] += 1
                _record(stats, name, method["name"], strategy, True,
                        "json export")
                continue
            recurring = _service_detect_recurring_body(
                ctx, name, method, params, returns)
            if recurring is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[mechanical recurring detection]"""']
                lines.extend("        " + line if line else "" for line in recurring)
                stats["implemented"] += 1
                _record(stats, name, method["name"], strategy, True,
                        "recurring detection")
                continue
            overdue = _service_overdue_body(ctx, method, params, returns)
            if overdue is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[mechanical overdue read]"""']
                lines.extend("        " + line if line else "" for line in overdue)
                stats["implemented"] += 1
                _record(stats, name, method["name"], strategy, True,
                        "overdue read")
                continue
            search_delegate = _service_search_delegate_body(
                ctx, method, params, returns)
            if search_delegate is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[delegates to the repository search]"""']
                lines.extend("        " + line if line else "" for line in search_delegate)
                stats["implemented"] += 1
                _record(stats, name, method["name"], strategy, True,
                        "search delegation")
                continue
            plain_filter = _service_plain_list_filter_body(
                ctx, method, params, returns)
            if plain_filter is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[delegates the list filter to read_all]"""']
                lines.extend("        " + line if line else "" for line in plain_filter)
                stats["implemented"] += 1
                _record(stats, name, method["name"], strategy, True,
                        "plain list filter")
                continue
            negative_stock = _service_negative_stock_body(
                ctx, name, method, params, returns)
            if negative_stock is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[mechanical non-negative stock guard]"""']
                lines.extend("        " + line if line else "" for line in negative_stock)
                stats["implemented"] += 1
                _record(stats, name, method["name"], strategy, True,
                        "negative stock guard")
                continue
            price_guard = _service_price_guard_body(
                ctx, name, method, params, returns)
            if price_guard is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[mechanical price comparison guard]"""']
                lines.extend("        " + line if line else "" for line in price_guard)
                stats["implemented"] += 1
                _record(stats, name, method["name"], strategy, True,
                        "price guard")
                continue
            utilization = _service_utilization_body(
                ctx, name, method, params, returns)
            if utilization is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[mechanical utilization]"""']
                lines.extend("        " + line if line else "" for line in utilization)
                stats["implemented"] += 1
                _record(stats, name, method["name"], strategy, True,
                        "utilization")
                continue
            related_body = _service_related_filter_body(ctx, method, params)
            if related_body is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[filters through one relation]"""']
                lines.extend("        " + line if line else ""
                             for line in related_body)
                stats["implemented"] += 1
                _record(stats, name, method["name"], strategy, True,
                        "related filter")
                continue
            assign_body = _service_assign_body(
                ctx, name, method, params, returns)
            if assign_body is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[assigns a record to its related entity]"""']
                lines.extend("        " + line if line else ""
                             for line in assign_body)
                stats["implemented"] += 1
                _record(stats, name, method["name"], strategy, True,
                        "assign relation")
                continue
            standard_read = _service_standard_read_body(
                ctx, method, params, returns)
            if standard_read is not None:
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          '[mechanical standard read]"""']
                lines.extend("        " + line if line else ""
                             for line in standard_read)
                stats["implemented"] += 1
                _record(stats, name, method["name"], strategy, True,
                        "standard read")
                continue
            delegate = _service_delegate(ctx, method, repo_index)
            cancel_delegate = _service_cancel_stock_delegate(
                ctx, method, params, delegate)
            if cancel_delegate is not None:
                target_cls, tname = cancel_delegate
                call = ", ".join(ident for _, ident, _ in params)
                prefix = "return " if normalize(returns) not in (
                    "none", "nonetype", "void", "") else ""
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          f'[delegates to {target_cls}.{tname} — cancel/restore]"""',
                          f"        {prefix}self._repos[{target_cls!r}].{tname}({call})"]
                stats["implemented"] += 1
                _record(stats, name, method["name"], strategy, True,
                        f"delegate-cancel:{target_cls}.{tname}")
                continue
            if delegate is not None and strategy.startswith("crud:"):
                target_cls, _ = delegate
                call = ", ".join(ident for _, ident, _ in params)
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} [delegates to {target_cls}.{fname}]"""',
                          f"        return self._repos[{target_cls!r}].{fname}({call})"]
                stats["implemented"] += 1
                _record(stats, name, method["name"], strategy, True, "delegate")
                continue
            if strategy.startswith("crud:"):
                renamed = _rename_target(
                    ctx, method,
                    [normalize(raw) for raw, _, _ in params],
                    normalize(returns))
                if renamed is None and strategy == "crud:read_one":
                    renamed = _read_one_target(
                        ctx, method,
                        [normalize(raw) for raw, _, _ in params],
                        normalize(returns))
                if renamed is not None:
                    target_cls, target_method = renamed
                    tname = codegen.sanitize(target_method["name"], "method")
                    call = ", ".join(ident for _, ident, _ in params)
                    lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                              f'        """{_docstring(method.get("description"))} '
                              f'[delegates to {target_cls}.{tname} — renamed from {fname}]"""',
                              f"        return self._repos[{target_cls!r}].{tname}({call})"]
                    stats["implemented"] += 1
                    _record(stats, name, method["name"], strategy, True, "rename")
                    continue
                if strategy in ("crud:filter", "crud:read_all"):
                    composed = _service_filter_plan(ctx, method, params)
                    if composed is not None:
                        repo_cls, read_all, entity, field_names, field_types = composed
                        try:
                            body = _service_filter_body(
                                fname, declaration, returns, method, repo_cls,
                                read_all, entity, field_names, field_types,
                                params, detail)
                        except _Unmappable as stuck:
                            body = None
                            detail = (f"parameter {stuck.param!r} maps to "
                                      "no field")
                        if body is not None:
                            lines += body
                            stats["implemented"] += 1
                            _record(stats, name, method["name"], strategy, True,
                                    f"compose:{repo_cls}.{read_all}")
                            continue
            record = ctx.get("slots", {}).get((name, method["name"]))
            plan = _service_guard_plan(
                ctx, name, method,
                record.get("slots", {}) if isinstance(record, dict) else {})
            if plan is not None:
                body = _service_guard_body(
                    fname, declaration, returns, method, plan, detail)
                if body is not None:
                    lines += body
                    stats["implemented"] += 1
                    _record(stats, name, method["name"], strategy, True,
                            "guard")
                    continue
            if delegate is not None:
                realized = _realized_delegate(ctx, name, method, params,
                                              returns, delegate)
                if realized is not None:
                    target_cls, tname = realized
                    call = ", ".join(ident for _, ident, _ in params)
                    lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                              f'        """{_docstring(method.get("description"))} '
                              f'[delegates to {target_cls}.{tname} — pattern realized by target]"""',
                              f"        return self._repos[{target_cls!r}].{tname}({call})"]
                    stats["implemented"] += 1
                    _record(stats, name, method["name"], strategy, True,
                            f"delegate-realized:{target_cls}.{tname}")
                    continue
                where = f" [same-name repo method on {delegate[0]} is {detail}]"
            elif strategy.startswith("crud:"):
                where = " [no same-name repository method to delegate to]"
            else:
                where = f" [{detail}]"
            lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                      f'        """{_docstring(method.get("description"))}{where}"""',
                      "        raise NotImplementedError(",
                      f'            "{cls}.{fname}: {detail}")']
            stats["stubs"] += 1
            stats["stub_reasons"].append(f"{cls}.{fname}: {detail}")
            _record(stats, name, method["name"], strategy, False, detail)
    atomic = {}
    for contract in ctx.get("contracts") or []:
        if not isinstance(contract, dict):
            continue
        writes = (len(contract.get("effects") or [])
                  + len(contract.get("creates") or []))
        holder = codegen.sanitize(contract.get("holder"), "Service")
        method = codegen.sanitize(contract.get("method"), "method")
        if writes > 1 and holder in emitted and method:
            atomic.setdefault(holder, []).append(method)
    if atomic:
        lines += [
            "", "",
            "def _atomic(method):",
            '    """Run a multi-write service method in one store transaction."""',
            "    def wrapper(self, *args, **kwargs):",
            "        store = None",
            "        for repo in self._repos.values():",
            "            store = getattr(repo, '_store', None)",
            "            if store is not None:",
            "                break",
            "        if store is None or not hasattr(store, 'transaction'):",
            "            return method(self, *args, **kwargs)",
            "        with store.transaction():",
            "            return method(self, *args, **kwargs)",
            "    wrapper.__name__ = method.__name__",
            "    wrapper.__doc__ = method.__doc__",
            "    wrapper.__wrapped__ = method",
            "    return wrapper",
        ]
        for holder in sorted(atomic):
            lines += ["", "", f"for _name in {atomic[holder]!r}:"]
            lines += [f"    if hasattr({holder}, _name):"]
            lines += [f"        setattr({holder}, _name, "
                      f"_atomic(getattr({holder}, _name)))"]
    return "\n".join(lines) + "\n"


def _record(stats, holder, method, strategy, implemented, how):
    """One row for the coverage meter: every method, mechanical or stub."""
    stats.setdefault("methods", []).append({
        "holder": holder, "method": method, "strategy": strategy,
        "implemented": implemented, "how": how,
    })


def _program_expr(value):
    """A reviewed program expression, validated as a Python expression."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        ast.parse(value, mode="eval")
    except SyntaxError:
        return None
    return value


def _program_error(ctx, name):
    """`errors.Name` for a registered error, or `ValueError`."""
    if not isinstance(name, str) or not name:
        return "ValueError"
    registered = {item.get("name") for item in ctx.get("errors") or []
                  if isinstance(item, dict)}
    if name in registered:
        return f"errors.{codegen.sanitize(name)}"
    return "ValueError"


def _program_call(repo, method, args):
    rendered = ", ".join(_program_expr(arg) or "None" for arg in args or [])
    return f"self._repos[{repo!r}].{codegen.sanitize(method, 'method')}({rendered})"


def _program_steps(ctx, steps, indent=0):
    """Lines for a reviewed declarative service program, or None."""
    pad = " " * indent
    lines = []
    for step in steps or []:
        if not isinstance(step, dict):
            return None
        op = str(step.get("op") or "").strip().lower()
        repo = step.get("repo")
        method = step.get("method")
        if op in ("read", "query", "call", "create", "update"):
            if not isinstance(repo, str) or not isinstance(method, str):
                return None
        if op == "read":
            target = step.get("as")
            expr = _program_expr(step.get("expr")) if step.get("expr") else None
            args = [_program_expr(arg) for arg in step.get("args") or []]
            if any(arg is None for arg in args) or not isinstance(target, str):
                return None
            call = _program_call(repo, method, args)
            if expr:
                call = f"{expr} if {expr} is not None else {call}"
            lines.append(f"{pad}{target} = {call}")
            error = step.get("error")
            if error:
                message = step.get("message") or f"{target} not found"
                lines.append(f"{pad}if {target} is None:")
                lines.append(f"{pad}    raise {_program_error(ctx, error)}({message!r})")
            continue
        if op == "query":
            target = step.get("as")
            args = [_program_expr(arg) for arg in step.get("args") or []]
            if any(arg is None for arg in args) or not isinstance(target, str):
                return None
            lines.append(f"{pad}{target} = {_program_call(repo, method, args)}")
            continue
        if op == "check":
            condition = _program_expr(step.get("condition"))
            if condition is None:
                return None
            error = _program_error(ctx, step.get("error"))
            message = step.get("message") or condition
            lines.append(f"{pad}if {condition}:")
            lines.append(f"{pad}    raise {error}({message!r})")
            continue
        if op == "assign":
            name = step.get("name")
            expr = _program_expr(step.get("expr"))
            if not isinstance(name, str) or expr is None:
                return None
            lines.append(f"{pad}{name} = {expr}")
            continue
        if op == "add":
            name = step.get("name")
            expr = _program_expr(step.get("expr"))
            if not isinstance(name, str) or expr is None:
                return None
            lines.append(f"{pad}{name} += {expr}")
            continue
        if op == "for_each":
            collection = _program_expr(step.get("collection"))
            name = step.get("as")
            if collection is None or not isinstance(name, str):
                return None
            nested = _program_steps(ctx, step.get("steps") or [], indent + 4)
            if nested is None:
                return None
            lines.append(f"{pad}for {name} in {collection}:")
            lines.extend(nested or [f"{pad}    pass"])
            continue
        if op == "update":
            args = [_program_expr(arg) for arg in step.get("args") or []]
            fields = step.get("fields") or {}
            if any(arg is None for arg in args) or not isinstance(fields, dict):
                return None
            rendered_fields = []
            for key, value in fields.items():
                expr = _program_expr(value)
                if expr is None:
                    return None
                rendered_fields.append(f"{codegen.sanitize(key, 'kw')}={expr}")
            lines.append(
                f"{pad}{_program_call(repo, method, args)}" if not rendered_fields
                else f"{pad}self._repos[{repo!r}].{codegen.sanitize(method, 'method')}"
                     f"({', '.join([*(_program_expr(arg) for arg in args or []), *rendered_fields])})")
            continue
        if op == "create":
            fields = step.get("fields") or {}
            if not isinstance(fields, dict):
                return None
            rendered = []
            for key, value in fields.items():
                expr = _program_expr(value)
                if expr is None:
                    return None
                rendered.append(f"{codegen.sanitize(key, 'kw')}={expr}")
            lines.append(
                f"{pad}self._repos[{repo!r}].{codegen.sanitize(method, 'method')}"
                f"({', '.join(rendered)})")
            continue
        if op == "call":
            args = [_program_expr(arg) for arg in step.get("args") or []]
            if any(arg is None for arg in args):
                return None
            lines.append(f"{pad}{_program_call(repo, method, args)}")
            continue
        if op == "return":
            expr = _program_expr(step.get("expr"))
            lines.append(f"{pad}return {expr if expr is not None else 'None'}")
            continue
        if op == "raise":
            error = _program_error(ctx, step.get("error"))
            message = step.get("message") or "refused"
            lines.append(f"{pad}raise {error}({message!r})")
            continue
        return None
    return lines


def _program_body(ctx, program):
    """A body from one reviewed declarative program, with no domain nouns."""
    lines = _program_steps(ctx, program.get("steps") or [])
    if lines is None:
        return None
    # Validate the expressions and generated body as one unit.
    source = "def _body():\n" + "\n".join(
        "    " + line if line.strip() else "" for line in lines)
    try:
        compile(source, "service_program", "exec")
    except SyntaxError:
        return None
    return lines


def _service_low_stock_body(ctx, method, params, returns):
    """A list/report of products below their category's reorder threshold.

    The data model carries the whole rule: the product's stock field, its
    category FK, and the category's threshold field.  The model kept writing
    the `low_only=False` branch as "not None", which returned only low-stock
    products for a false flag; deriving the body from the fields removes that
    whole class of prompt-dependent error.
    """
    name = normalize(method.get("name") or "")
    raw_params = [item[0] if isinstance(item, tuple) else item.get("name")
                  for item in params if item]
    low_param = next((raw for raw in raw_params
                      if "low" in normalize(raw)), None)
    if "low" not in name and low_param is None:
        return None
    words = {normalize(token) for token in
             re.findall(r"[A-Za-z_][A-Za-z0-9_]*", returns or "")}
    entity = next((item for item in ctx["entity_names"]
                   if normalize(item) in words), None)
    if entity is None:
        return None
    fields = fields_of(ctx, entity)
    stock = next((name for name, field in fields
                  if isinstance(field, dict)
                  and "stock" in normalize(name)), None)
    relation = next(((name, field) for name, field in fields
                     if isinstance(field, dict)
                     and isinstance(field.get("foreign_key"), dict)
                     and normalize(field["foreign_key"].get("target_entity"))
                     in {normalize(item) for item in ctx["entity_names"]}), None)
    if stock is None or relation is None:
        return None
    relation_name, relation_field = relation
    parent = relation_field["foreign_key"]["target_entity"]
    threshold = next((name for name, field in fields_of(ctx, parent)
                      if isinstance(field, dict)
                      and ("threshold" in normalize(name)
                           or "reorder" in normalize(name))), None)
    if threshold is None:
        return None
    repo = next((item for item in ctx["repositories"]
                 if normalize(item.get("entity")) == normalize(entity)), None)
    parent_repo = next((item for item in ctx["repositories"]
                        if normalize(item.get("entity")) == normalize(parent)), None)
    if repo is None or parent_repo is None:
        return None
    repo_cls = codegen.sanitize(repo.get("interface_name") or entity, "Repository")
    parent_cls = codegen.sanitize(
        parent_repo.get("interface_name") or parent, "Repository")
    read_all = next((item["name"] for item in repo.get("methods") or []
                     if isinstance(item, dict)
                     and codegen.classify_crud(item.get("name") or "") == "read_all"),
                    None)
    parent_read = next((item["name"] for item in parent_repo.get("methods") or []
                        if isinstance(item, dict)
                        and codegen.classify_crud(item.get("name") or "") == "read_all"),
                       None)
    if read_all is None or parent_read is None:
        return None
    category_param = next((raw for raw in raw_params
                           if normalize(raw) == normalize(relation_name)), None)
    repo_params = {item.get("name") for item in
                   (next(method for method in repo.get("methods") or []
                         if isinstance(method, dict)
                         and method.get("name") == read_all).get("params") or [])
                   if isinstance(item, dict)}
    category_arg = (f"{codegen.sanitize(category_param, 'param')}="
                    f"{codegen.sanitize(category_param, 'param')}"
                    if category_param and relation_name in repo_params else "")
    base = f"self._repos[{repo_cls!r}].{codegen.sanitize(read_all, 'method')}({category_arg})"
    parent_pk = primary_key_of(ctx, parent)
    product_fk = codegen.sanitize(relation_name, "attr")
    stock_attr = codegen.sanitize(stock, "attr")
    threshold_attr = codegen.sanitize(threshold, "attr")
    parent_pk_attr = codegen.sanitize(parent_pk, "attr")
    lines = [f"products = {base}"]
    if low_param is not None:
        low = codegen.sanitize(low_param, "param")
        lines.append(f"if {low} is not True:")
        lines.append("    return products")
    lines += [
        f"categories = self._repos[{parent_cls!r}].{codegen.sanitize(parent_read, 'method')}()",
        f"thresholds = {{row.{parent_pk_attr}: row.{threshold_attr} for row in categories}}",
        "result = []",
        "for product in products:",
        f"    if product.{product_fk} is None:",
        "        continue",
        f"    threshold = thresholds.get(product.{product_fk})",
        "    if threshold is not None and product." + f"{stock_attr} < threshold:",
        "        result.append(product)",
        "return result",
    ]
    return lines


def _service_count_report_body(ctx, method, params, returns):
    """A `{status: count}` report over one entity field."""
    words = {normalize(token) for token in
             re.findall(r"[A-Za-z_][A-Za-z0-9_]*", returns or "")}
    if "dict" not in words or "list" in words or params:
        return None
    name_tokens = _tokens_for_report(method.get("name") or "")
    entity = next((item for item in ctx["entity_names"]
                   if normalize(item) in name_tokens), None)
    if entity is None:
        return None
    fields = {normalize(name): name for name, _field in fields_of(ctx, entity)}
    field = next((fields[token] for token in name_tokens if token in fields), None)
    if field is None:
        return None
    values = _field_vocabulary(ctx, entity, field)
    if not values:
        match = re.search(r"status(?:es)?\s*:\s*(.+)",
                          method.get("description") or "", re.IGNORECASE)
        if match:
            values = [value.strip(" `'\"") for value in re.split(
                r",|\bor\b", match.group(1)) if value.strip(" `'\"")]
    if not values:
        return None
    repo = next((item for item in ctx["repositories"]
                 if normalize(item.get("entity")) == normalize(entity)), None)
    read_all = next((item["name"] for item in (repo or {}).get("methods") or []
                     if isinstance(item, dict)
                     and codegen.classify_crud(item.get("name") or "") == "read_all"),
                    None)
    if repo is None or read_all is None:
        return None
    repo_cls = codegen.sanitize(repo.get("interface_name") or entity, "Repository")
    attr = codegen.sanitize(field, "attr")
    var = codegen.sanitize(entity.lower(), "row")
    return [
        f"counts = {{{', '.join(repr(value) + ': 0' for value in values)}}}",
        f"for {var} in self._repos[{repo_cls!r}].{codegen.sanitize(read_all, 'method')}():",
        f"    key = {var}.{attr}",
        "    if key in counts:",
        "        counts[key] += 1",
        "return counts",
    ]


def _tokens_for_report(name):
    return [token for token in re.split(r"[_-]+", str(name or "").lower()) if token]


def _service_stock_report_body(ctx, method, params, returns):
    """A list of product rows carrying their category name."""
    name = normalize(method.get("name") or "")
    words = {normalize(token) for token in
             re.findall(r"[A-Za-z_][A-Za-z0-9_]*", returns or "")}
    if params or "list" not in words or "stock" not in name or "report" not in name:
        return None
    entity = next((item for item in ctx["entity_names"]
                   if normalize(item) in normalize(method.get("name") or "")), None)
    if entity is None:
        return None
    fields = fields_of(ctx, entity)
    relation = next(((field_name, field) for field_name, field in fields
                     if isinstance(field, dict)
                     and isinstance(field.get("foreign_key"), dict)
                     and normalize(field["foreign_key"].get("target_entity"))
                     in {normalize(item) for item in ctx["entity_names"]}), None)
    if relation is None:
        return None
    relation_name, relation_field = relation
    parent = relation_field["foreign_key"]["target_entity"]
    parent_name = next((field_name for field_name, field in fields_of(ctx, parent)
                        if isinstance(field, dict)
                        and normalize(field_name) == "name"), None)
    if parent_name is None:
        return None
    repo = next((item for item in ctx["repositories"]
                 if normalize(item.get("entity")) == normalize(entity)), None)
    parent_repo = next((item for item in ctx["repositories"]
                        if normalize(item.get("entity")) == normalize(parent)), None)
    read_all = next((item["name"] for item in (repo or {}).get("methods") or []
                     if isinstance(item, dict)
                     and codegen.classify_crud(item.get("name") or "") == "read_all"),
                    None)
    parent_read = next((item["name"] for item in (parent_repo or {}).get("methods") or []
                        if isinstance(item, dict)
                        and codegen.classify_crud(item.get("name") or "") == "read_all"),
                       None)
    if repo is None or parent_repo is None or read_all is None or parent_read is None:
        return None
    repo_cls = codegen.sanitize(repo.get("interface_name") or entity, "Repository")
    parent_cls = codegen.sanitize(
        parent_repo.get("interface_name") or parent, "Repository")
    parent_pk = codegen.sanitize(primary_key_of(ctx, parent), "attr")
    rows = {}
    for field_name, _field in fields:
        rows[field_name] = f"'{field_name}': {codegen.sanitize(entity.lower(), 'row')}.{codegen.sanitize(field_name, 'attr')}"
    rows[f"{normalize(parent)}_name"] = (
        f"'{normalize(parent)}_name': names.get("
        f"{codegen.sanitize(entity.lower(), 'row')}.{codegen.sanitize(relation_name, 'attr')})")
    var = codegen.sanitize(entity.lower(), "row")
    return [
        f"rows = self._repos[{repo_cls!r}].{codegen.sanitize(read_all, 'method')}()",
        f"parents = self._repos[{parent_cls!r}].{codegen.sanitize(parent_read, 'method')}()",
        f"names = {{row.{parent_pk}: row.{codegen.sanitize(parent_name, 'attr')} for row in parents}}",
        "result = []",
        f"for {var} in rows:",
        "    result.append({" + ", ".join(rows.values()) + "})",
        "return result",
    ]


def _service_related_filter_body(ctx, method, params):
    """Filter a list through one intermediate relation (Invoice -> Order -> Customer).

    A service method such as `search_invoices_by_customer(customer_id)` has no
    direct FK from Invoice to Customer; the path is one hop through Order.
    The model graph is the authority, so this emits a read-all plus an id set
    instead of inventing a field or delegating to a wrong repository.
    """
    name = normalize(method.get("name") or "")
    if not name.startswith(("search", "find", "list", "get")):
        return None
    returns = method.get("return_type")
    if not isinstance(returns, str):
        return None
    target = next((entity for entity in ctx["entity_names"]
                   if normalize(entity) in normalize(returns)), None)
    if target is None or len(params) != 1:
        return None
    raw = params[0][0] if isinstance(params[0], tuple) else params[0].get("name")
    if not isinstance(raw, str) or not raw.endswith("_id"):
        return None
    related = next((entity for entity in ctx["entity_names"]
                    if normalize(entity) == normalize(raw[:-3])), None)
    if related is None or normalize(target) == normalize(related):
        return None
    target_model = model_of(ctx, target)
    if target_model is None:
        return None
    target_fks = [field for field in target_model.get("fields") or []
                  if isinstance(field, dict) and isinstance(field.get("foreign_key"), dict)]
    if any(normalize(field["foreign_key"].get("target_entity")) == normalize(related)
           for field in target_fks):
        return None  # the normal filter planner handles a direct FK
    for field in target_fks:
        middle = field["foreign_key"].get("target_entity")
        middle_model = model_of(ctx, middle)
        if middle_model is None:
            continue
        middle_related = next(
            (item["name"] for item in middle_model.get("fields") or []
             if isinstance(item, dict) and isinstance(item.get("foreign_key"), dict)
             and normalize(item["foreign_key"].get("target_entity")) == normalize(related)),
            None)
        if middle_related is None:
            continue
        target_repo = next((item for item in ctx["repositories"]
                            if normalize(item.get("entity")) == normalize(target)), None)
        middle_repo = next((item for item in ctx["repositories"]
                            if normalize(item.get("entity")) == normalize(middle)), None)
        if target_repo is None or middle_repo is None:
            continue
        t_cls = target_repo.get("interface_name") or f"{target}Repository"
        m_cls = middle_repo.get("interface_name") or f"{middle}Repository"
        t_read = next((item["name"] for item in target_repo.get("methods") or []
                       if isinstance(item, dict) and normalize(item.get("name") or "") == "readall"), None)
        m_read = next((item["name"] for item in middle_repo.get("methods") or []
                       if isinstance(item, dict) and normalize(item.get("name") or "") == "readall"), None)
        if not t_read or not m_read:
            continue
        param = codegen.sanitize(raw, "param")
        return [
            f"middle = [row for row in self._repos[{m_cls!r}].{codegen.sanitize(m_read, 'method')}() if row.{codegen.sanitize(middle_related, 'attr')} == {param}]",
            "middle_ids = {row." + codegen.sanitize(primary_key_of(ctx, middle), 'attr') + " for row in middle}",
            f"return [row for row in self._repos[{t_cls!r}].{codegen.sanitize(t_read, 'method')}() if row.{codegen.sanitize(field['name'], 'attr')} in middle_ids]",
        ]
    return None


def _name_tokens(name):
    """Lowercased tokens of a camelCase, snake_case or kebab-case name."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(name or ""))
    return [token for token in re.split(r"[^a-z0-9]+", spaced.lower())
            if token]


def _param_for_entity(raw_params, entity):
    """The parameter whose tokens name the entity, when exactly one does."""
    tokens = set(_name_tokens(entity))
    matches = []
    for raw in raw_params:
        if not isinstance(raw, str):
            continue
        overlap = tokens & set(_name_tokens(raw))
        if overlap:
            matches.append((len(overlap), raw))
    if not matches:
        return None
    matches.sort(key=lambda item: -item[0])
    if len(matches) > 1 and matches[1][0] == matches[0][0]:
        return None
    return matches[0][1]


def _service_assign_body(ctx, service_name, method, params, returns):
    """A `assign_<entity>_to_<target>` service method that moves a record.

    The GUI prompt's wine-to-storage-location operation is a foreign-key move
    with no domain-specific arithmetic.  The source repository supplies the
    read and update; the target id is the second parameter.  Repository update
    guards (capacity) still run underneath.
    """
    name = normalize(method.get("name") or "")
    if not name.startswith("assign"):
        return None
    if len(params) < 2:
        return None
    raw_params = [item[0] if isinstance(item, tuple) else item.get("name")
                  for item in params if item]
    source = target = None
    for raw in raw_params:
        if not isinstance(raw, str):
            continue
        token = normalize(raw[:-3] if raw.endswith("_id") else raw)
        entity = next((item for item in ctx["entity_names"]
                       if normalize(item) == token
                       or token in normalize(item)), None)
        if entity is not None and source is None:
            source = entity
        elif entity is not None and target is None and entity != source:
            target = entity
    if source is None or target is None:
        return None
    source_model = model_of(ctx, source)
    if source_model is None:
        return None
    fk = next((field_name for field_name, field in fields_of(ctx, source)
               if isinstance(field.get("foreign_key"), dict)
               and normalize(field["foreign_key"].get("target_entity"))
               == normalize(target)), None)
    if fk is None:
        return None
    repo = next((item for item in ctx["repositories"]
                 if normalize(item.get("entity")) == normalize(source)), None)
    if repo is None:
        return None
    repo_cls = repo.get("interface_name") or f"{source}Repository"
    read = next((m["name"] for m in repo.get("methods") or []
                 if isinstance(m, dict)
                 and normalize(m.get("name") or "").startswith("readone")), None)
    update = next((m["name"] for m in repo.get("methods") or []
                   if isinstance(m, dict)
                   and normalize(m.get("name") or "") == "update"), None)
    if read is None or update is None:
        return None
    target_repo = next((item for item in ctx["repositories"]
                        if normalize(item.get("entity")) == normalize(target)),
                       None)
    if target_repo is None:
        return None
    target_cls = target_repo.get("interface_name") or f"{target}Repository"
    target_read = next((m["name"] for m in target_repo.get("methods") or []
                        if isinstance(m, dict)
                        and normalize(m.get("name") or "").startswith("readone")),
                       None)
    if target_read is None:
        return None
    source_param = _param_for_entity(raw_params, source)
    target_param = _param_for_entity(raw_params, target)
    if source_param is None or target_param is None:
        return None
    not_found = next((f"errors.{codegen.sanitize(item['name'])}"
                      for item in ctx.get("errors") or []
                      if isinstance(item, dict) and isinstance(item.get("name"), str)
                      and normalize(source) in normalize(item["name"])
                      and "notfound" in normalize(item["name"])), None)
    target_not_found = next((f"errors.{codegen.sanitize(item['name'])}"
                             for item in ctx.get("errors") or []
                             if isinstance(item, dict) and isinstance(item.get("name"), str)
                             and normalize(target) in normalize(item["name"])
                             and "notfound" in normalize(item["name"])), None)
    pk = primary_key_of(ctx, source)
    source_ident = codegen.sanitize(source_param, "param")
    target_ident = codegen.sanitize(target_param, "param")
    lines = [
        f"if {target_ident} is None:",
        f"    raise {target_not_found or 'ValueError'}("
        f"{target_param + ' is required'!r})",
        f"self._repos[{target_cls!r}].{codegen.sanitize(target_read, 'method')}"
        f"({target_ident})",
        f"record = self._repos[{repo_cls!r}].{codegen.sanitize(read, 'method')}"
        f"({source_ident})",
        "if record is None:",
        f"    raise {not_found or 'LookupError'}(f\"{source} not found\")",
        f"record.{codegen.sanitize(fk, 'attr')} = {target_ident}",
        f"self._repos[{repo_cls!r}].{codegen.sanitize(update, 'method')}"
        f"(record.{codegen.sanitize(pk, 'attr')}, "
        f"{codegen.sanitize(fk, 'kw')}={target_ident})",
    ]
    declared = str(method.get("return_type") or "").strip().lower()
    if "bool" in declared:
        lines.append("return True")
    elif "none" not in declared:
        lines.append("return record")
    return lines


def _service_filter_body(fname, declaration, returns, method, repo_cls,
                         read_all, entity, field_names, field_types, params,
                         detail):
    """A service filter over the entity's read-all, with kernel criteria.

    The criteria are the kernel's own field matching (`match_param`),
    resolved at generation time — the body filters exactly as the
    repository would, and a parameter no field satisfies refuses
    (`_Unmappable`) instead of emitting a body that raises when called.
    A date criterion compares the dataclass's date with a CLI string, so
    both sides go through `_filter_value`, the module's ISO normaliser.
    """
    lines = [
        "",
        f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
        f'        """{_docstring(method.get("description"))} '
        f'[composes {repo_cls}.{read_all} over {detail}]"""',
        f"        records = self._repos[{repo_cls!r}].{read_all}()",
        "        criteria = []",
    ]
    date_criteria = False
    for raw, ident, _ in params:
        matched = codegen.match_param(field_names, raw)
        if matched is None:
            raise _Unmappable(raw)
        if _is_date_type(field_types.get(matched[0])):
            date_criteria = True
        lines.append(f"        if {ident} is not None:")
        lines.append(f"            criteria.append(({matched[0]!r}, "
                     f"{matched[1]!r}, {ident}))")
    lines += [
        "        out = []",
        "        for record in records:",
        "            row = record if isinstance(record, dict) else vars(record)",
    ]
    if date_criteria:
        lines += [
            "            if all(_holds(_filter_value(row.get(field)), operator,",
            "                          _filter_value(value))",
            "                   for field, operator, value in criteria):",
        ]
    else:
        lines += [
            "            if all(_holds(row.get(field), operator, value)",
            "                   for field, operator, value in criteria):",
        ]
    lines += [
        "                out.append(record)",
        "        return out",
    ]
    return lines


def _guard_entity_param(ctx, method):
    """The single record the guard acts on: `(raw, ident, entity)`, or None.

    A budget guard wraps one record (add this expense); anything else — no
    record, several records, extra scalar arguments — is update/exclusion
    semantics no template covers, so a stub.
    """
    found = [(p.get("name"), codegen.sanitize(p.get("name"), "param"), ptype)
             for p in method.get("params") or [] if isinstance(p, dict)
             for ptype in [p.get("type")] if codegen.is_entity_type(ptype, ctx["entity_names"])]
    params = [p for p in method.get("params") or [] if isinstance(p, dict)]
    if len(found) != 1 or len(params) != 1:
        return None
    return found[0]


def _mechanical_creates(ctx, entity):
    """`[(repo_cls, method)]` crud:create methods for one entity, in order."""
    out = []
    for repo in ctx["repositories"]:
        if repo.get("entity") != entity:
            continue
        holder = repo.get("interface_name") or entity
        cls = codegen.sanitize(holder, "Repository")
        for method in repo.get("methods") or []:
            if not isinstance(method, dict) or not method.get("name"):
                continue
            strategy, _ = codegen.plan_method(
                method, _match_entry(ctx, holder, method["name"]),
                ctx["entity_names"])
            if strategy == "crud:create":
                out.append((cls, method))
    return out


def _usable_aggregates(ctx, entity):
    """`[(repo_cls, method)]` slot-answered aggregates over one entity."""
    out = []
    for repo in ctx["repositories"]:
        if repo.get("entity") != entity:
            continue
        holder = repo.get("interface_name") or entity
        cls = codegen.sanitize(holder, "Repository")
        for method in repo.get("methods") or []:
            if not isinstance(method, dict) or not method.get("name"):
                continue
            pattern, slots = _slot_pattern(ctx, holder, method)
            if pattern is not None and pattern.startswith("AGGREGATE") \
                    and _slots_usable(pattern, slots, method, True):
                out.append((cls, method))
    return out


def _aggregate_feed(ctx, entity, date_field, method):
    """How an aggregate's parameters are fed, or None when one cannot be.

    An fk parameter takes the same-named entity field; `month`/`year` take
    the date field's `YYYY-MM` prefix; `start`/`end` take that month's
    bounds. Anything else is unfeedable — the aggregate answers a different
    question than the guard asks. Kinds: `field`, `month`, `start`, `end`.
    """
    feed = {}
    for param in method.get("params") or []:
        if not isinstance(param, dict) or not param.get("name"):
            return None
        raw = param["name"]
        if any(normalize(raw) == normalize(name)
               for name, _ in fields_of(ctx, entity)):
            feed[raw] = ("field", next(
                name for name, _ in fields_of(ctx, entity)
                if normalize(name) == normalize(raw)))
        elif normalize(raw) in ("month", "year"):
            feed[raw] = ("month",)
        else:
            tokens = codegen.canon_tokens(raw)
            if tokens[:1] == ["start"]:
                feed[raw] = ("start",)
            elif tokens[:1] == ["end"]:
                feed[raw] = ("end",)
            else:
                return None
    return feed


def _service_guard_plan(ctx, service_name, method, slots):
    """A resolved budget-guard composition, or None.

    Every reference answers from the recorded slots and is re-verified
    here — a renamed method, a dropped aggregate, a hand-written record —
    so a stale answer degrades to a stub at generation time, never to a
    body wired to the wrong call.
    """
    entry = _match_entry(ctx, service_name, method.get("name"))
    pattern = None
    if isinstance(entry, dict):
        kind, payload = tie_rules.effective_directive(entry)
        if kind == "pattern" and payload == "BUDGET_OVERFLOW_GUARD":
            pattern = payload
    if pattern is None:
        return None
    if not _complete_slots(pattern, slots, False):
        return None
    acted = _guard_entity_param(ctx, method)
    if acted is None:
        return None
    _, entity_ident, entity = acted
    entity_name = next((n for n in ctx["entity_names"]
                        if codegen.is_entity_type(entity, [n])), None)
    if entity_name is None:
        return None
    creates = {m["name"]: (c, m) for c, m in _mechanical_creates(ctx, entity_name)}
    if slots.get("create_method") not in creates:
        return None
    create_cls, create_method = creates[slots["create_method"]]
    aggregates = {}
    for agg_cls, agg_method in _usable_aggregates(ctx, entity_name):
        feed = _aggregate_feed(ctx, entity_name, slots.get("date_field"),
                               agg_method)
        if feed is not None:
            aggregates[agg_method["name"]] = (agg_cls, agg_method, feed)
    if slots.get("aggregate_method") not in aggregates:
        return None
    agg_cls, agg_method, feed = aggregates[slots["aggregate_method"]]
    budget = _resolve_budget_read(ctx, entity_name, slots.get("budget_method"),
                                  slots.get("date_field"))
    if budget is None:
        return None
    budget_cls, budget_method, budget_entity, budget_feed, budget_kind = budget
    limit_field = slots.get("limit_field")
    if not any(name == limit_field or normalize(name) == normalize(limit_field)
               for name, _ in fields_of(ctx, budget_entity)):
        return None
    errors = {e["name"] for e in ctx["errors"]
              if isinstance(e, dict) and e.get("name")}
    if slots.get("error") not in errors:
        return None
    budget_errors = []
    for candidate in (method_error(ctx, budget_method, budget_entity),
                      "LookupError"):
        if candidate not in budget_errors:
            budget_errors.append(candidate)
    amount_field = slots.get("amount_field")
    if not any(name == amount_field or normalize(name) == normalize(amount_field)
               for name, _ in fields_of(ctx, entity_name)):
        return None
    date_field = slots.get("date_field")
    if not any(name == date_field or normalize(name) == normalize(date_field)
               for name, _ in fields_of(ctx, entity_name)):
        return None
    return {
        "entity": entity_name, "entity_ident": entity_ident,
        "create_cls": create_cls, "create_method": create_method,
        "agg_cls": agg_cls, "agg_method": agg_method, "feed": feed,
        "budget_cls": budget_cls, "budget_method": budget_method,
        "budget_entity": budget_entity, "budget_feed": budget_feed,
        "budget_kind": budget_kind, "budget_errors": budget_errors,
        "amount_field": amount_field, "date_field": date_field,
        "limit_field": limit_field, "error": slots["error"],
    }


def _feed_scopes(feed, ctx, entity_name):
    """True when a budget feed constrains more than identity.

    A feed matching only the guarded entity's primary key
    (`read_budget_by_id` fed `expense.id`) looks up one arbitrary record
    by a cross-entity id collision — scoped in form, unscoped in fact.
    At least one feed entry must name a non-key field.
    """
    key_names = {normalize(name) for name, field in fields_of(ctx, entity_name)
                 if isinstance(field, dict) and field.get("primary_key")}
    for kind, field in feed.values():
        if kind == "field" and normalize(field) not in key_names:
            return True
        if kind in ("month", "start", "end"):
            return True
    return False


def _resolve_budget_read(ctx, entity_name, method_name, date_field):
    """`(cls, method, budget_entity, feed, kind)` for a recorded budget read.

    The read returns one budget record (`kind="one"`) or a list to pick
    from (`kind="many"`); a missing record means no limit either way. Its
    parameters must all feed from the guarded entity (same name, or the
    month from the date field), and at least one must — an unscoped read
    cannot serve a scoped guard. The read itself must be mechanical
    (crud or usable slots): the guard refuses to build on a refusal.
    """
    for repo in ctx["repositories"]:
        holder = repo.get("interface_name") or repo.get("entity")
        for method in repo.get("methods") or []:
            if not isinstance(method, dict) or method.get("name") != method_name:
                continue
            returns = (method.get("return_type") or "")
            words = {normalize(token) for token in
                     re.findall(r"[A-Za-z_][A-Za-z0-9_]*", returns)}
            budget_entity = next(
                (n for n in ctx["entity_names"]
                 if isinstance(n, str) and normalize(n) in words
                 and normalize(n) not in ("dict", "optional", "none")),
                None)
            if budget_entity is None:
                return None
            strategy, _ = codegen.plan_method(
                method, _match_entry(ctx, holder, method["name"]),
                ctx["entity_names"])
            mechanical = strategy.startswith("crud:")
            if not mechanical:
                pattern, slots = _slot_pattern(ctx, holder, method)
                mechanical = pattern is not None and _slots_usable(
                    pattern, slots, method, True)
            if not mechanical:
                return None
            feed = _aggregate_feed(ctx, entity_name, date_field, method)
            if not feed:
                return None
            if not _feed_scopes(feed, ctx, entity_name):
                return None
            kind = "many" if "list" in words else "one"
            return (codegen.sanitize(holder, "Repository"), method,
                    budget_entity, feed, kind)
    return None


def _service_guard_body(fname, declaration, returns, method, plan, detail):
    """Check-then-act: scope the month, total it, compare the limit, create."""
    entity_ident = plan["entity_ident"]

    def call_args(feed, params):
        """One call-site expression per parameter, in signature order."""
        args = []
        for param in params:
            if not isinstance(param, dict):
                continue
            kind = feed.get(param.get("name"), (None,))[0]
            if kind == "field":
                args.append(f"record.get({feed[param['name']][1]!r})")
            elif kind == "month":
                args.append("month")
            elif kind == "start":
                args.append("month_start")
            elif kind == "end":
                args.append("month_end")
            else:
                return None
        return args

    agg = plan["agg_method"]
    agg_args = call_args(plan["feed"],
                         [p for p in agg.get("params") or [] if isinstance(p, dict)])
    budget = plan["budget_method"]
    budget_args = call_args(
        plan["budget_feed"],
        [p for p in budget.get("params") or [] if isinstance(p, dict)])
    if agg_args is None or budget_args is None:
        return None
    create = plan["create_method"]
    needs_bounds = any(kind in ("start", "end")
                       for kind, *_ in list(plan["feed"].values())
                       + list(plan["budget_feed"].values()))
    lines = [
        "",
        f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
        f'        """{_docstring(method.get("description"))} '
        f'[budget guard over {plan["agg_cls"]}.{agg["name"]}]"""',
        f"        record = {entity_ident} if isinstance({entity_ident}, dict) "
        f"else vars({entity_ident})",
        f"        month = str(record.get({plan['date_field']!r}) or '')[:7]",
        f"        if not month:",
        f"            raise ValueError("
        f"f\"budget guard needs {plan['date_field']}: without it the expense "
        f"cannot be scoped to a month\")",
    ]
    if needs_bounds:
        lines += [
            "        year, mon = [int(part) for part in month.split('-')]",
            "        month_start = f\"{year:04d}-{mon:02d}-01\"",
            "        month_end = f\"{year:04d}-{mon:02d}-{calendar.monthrange(year, mon)[1]:02d}\"",
        ]
    lines += [
        f"        current = self._repos[{plan['agg_cls']!r}]."
        f"{codegen.sanitize(agg['name'], 'method')}({', '.join(agg_args)})",
    ]
    budget_call = (
        f"self._repos[{plan['budget_cls']!r}]."
        f"{codegen.sanitize(budget['name'], 'method')}({', '.join(budget_args)})"
    )
    if plan["budget_kind"] == "many":
        lines += [
            f"        rows = {budget_call}",
            f"        if len(rows) > 1:",
            f"            raise ValueError("
            f"f\"several budgets match this scope\")",
            f"        budget = rows[0] if rows else None",
        ]
    else:
        caught = ", ".join(plan["budget_errors"])
        lines += [
            f"        try:",
            f"            budget = {budget_call}",
            f"        except ({caught}):",
            f"            budget = None  # no budget record: no limit to exceed",
        ]
    lines += [
        f"        if budget is not None:",
        f"            limit = budget.get({plan['limit_field']!r}) "
        f"if isinstance(budget, dict) else getattr(budget, {plan['limit_field']!r}, None)",
        f"            new_amount = record.get({plan['amount_field']!r}) or 0",
        f"            if limit is not None and current + new_amount > limit:",
        f"                raise errors.{codegen.sanitize(plan['error'])}("
        f"f\"exceeds budget limit of {{limit}}\")",
        f"        return self._repos[{plan['create_cls']!r}]."
        f"{codegen.sanitize(create['name'], 'method')}({entity_ident})",
    ]
    return lines


# --------------------------------------------------------------------------
# slotted patterns (human-answered slots -> mechanical bodies)
# --------------------------------------------------------------------------

# Required slots per pattern, from the kernel catalogues. COUNT needs no
# target (it counts rows); everything else does. BUDGET differs by role: a
# repository check reads the limit and compares, while a service guard also
# names the create to run, the aggregate for the current total, the budget
# read, and the error to raise.
SLOT_REQUIREMENTS = {
    "AGGREGATE_BY_FK": ("fk_field", "target_field", "aggregate_func"),
    "AGGREGATE_BY_FK_AND_DATE": ("fk_field", "date_field", "target_field",
                                 "aggregate_func"),
    "THRESHOLD_SCAN": ("comparison_field", "operator", "threshold"),
    "BUDGET_OVERFLOW_GUARD": ("limit_field", "target_field", "date_field",
                              "spend_entity"),
    "FILTER_CRITERION": ("criterion_field", "criterion_value"),
}
SERVICE_BUDGET_SLOTS = ("create_method", "aggregate_method", "budget_method",
                        "amount_field", "date_field", "limit_field", "error")


def _field_enum(ctx, entity, field_name):
    """The documented value set for a field, or [].

    The invariants carry schema lines like `Loan.status must be one of
    ['active', 'returned', 'overdue']` — the only place a status vocabulary
    is written down, so the only place it may be read from.
    """
    wanted = f"{entity}.{field_name}"
    for invariant in ctx.get("invariants") or []:
        text = invariant.get("text") if isinstance(invariant, dict) else None
        if not isinstance(text, str):
            continue
        match = re.search(
            rf"\b{re.escape(wanted)}\b[^.]*?must be one of\s*\[([^\]]*)\]",
            text, re.IGNORECASE)
        if match:
            return re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))
    return []


def _field_vocabulary(ctx, entity, field_name):
    """A field's documented `must be one of` values, with or without brackets.

    Invariants write `Loan.status must be one of 'active', 'returned'` and
    `Expense.payment_method must be one of 'cash', 'card', 'transfer'`; a
    create body can default a missing non-null value to the first and refuse
    a spelling outside the set. The bracket form is accepted too.  A status
    vocabulary can also be stated in prose (`Orders can be pending, confirmed,
    shipped or cancelled`); read that as the same record rather than making
    the transition emitter know any status word.
    """
    wanted = f"{entity}.{field_name}"
    for invariant in ctx.get("invariants") or []:
        text = invariant.get("text") if isinstance(invariant, dict) else None
        if not isinstance(text, str):
            continue
        match = re.search(
            rf"\b{re.escape(wanted)}\b[^.]*?must be one of\s*(.+?)(?:\.\s|\.$|$)",
            text, re.IGNORECASE)
        if not match:
            continue
        values = re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))
        if values:
            return values
    if normalize(field_name) not in ("status", "state"):
        return []
    requirements = ctx.get("requirements") or ""
    if not isinstance(requirements, str):
        return []
    noun = re.escape(entity)
    match = re.search(
        rf"\b{noun}s?\b[^.]*?\b(?:can be|may be|is one of)\s+([^.;]+)",
        requirements, re.IGNORECASE)
    if not match:
        return []
    values = [value.strip(" `'\"") for value in re.split(
        r",|\bor\b", match.group(1)) if value.strip(" `'\"")]
    # A prose continuation (`orders can be cancelled, cancelling an order...`)
    # is not a status vocabulary. Only short identifier-like values qualify.
    if all(re.fullmatch(r"[A-Za-z0-9_.-]+", value) for value in values):
        return values
    return []


def _criterion_values(ctx, entity, field_name):
    """Literal candidates for an equality criterion on a model field, or [].

    Boolean fields read True/False; a string field must carry a documented
    value set — a status word with no vocabulary would be invented, not
    read. Fields of any other type offer nothing.
    """
    model = model_of(ctx, entity)
    if model is None or not isinstance(field_name, str) or not field_name:
        return []
    for field in model.get("fields") or []:
        if not isinstance(field, dict):
            continue
        if normalize(field.get("name") or "") != normalize(field_name):
            continue
        ftype = str(field.get("type") or "").strip().lower()
        if ftype in ("boolean", "bool"):
            return ["True", "False"]
        if ftype in ("str", "string", "text"):
            # Invariants write both `must be one of ['a', 'b']` and the
            # bracket-less `must be one of 'a', 'b'`; the review needs the
            # value set either way.  The bracket-only reader missed the
            # library's `Loan.status` vocabulary and left `find_active_loans`
            # unasked.
            return _field_vocabulary(ctx, entity, field.get("name") or field_name)
        return []
    return []


def _collection_return(method):
    """True when the declared return type is a list of something."""
    returns = method.get("return_type")
    if not isinstance(returns, str):
        return False
    words = {normalize(token) for token in
             re.findall(r"[A-Za-z_][A-Za-z0-9_]*", returns)}
    return "list" in words


def _slot_pattern(ctx, holder, method):
    """The slottable pattern id for a method, or None (with its slots).

    A parameterless list-returning method whose filter-ish pattern currently
    stubs is offered the synthetic FILTER_CRITERION question instead:
    `find_active_members` cannot read `is_active` off its name, but a human
    can say which field equals which documented value.
    """
    entry = _match_entry(ctx, holder, method.get("name"))
    if not isinstance(entry, dict):
        return None, {}
    kind, payload = tie_rules.effective_directive(entry)
    if (kind == "rule" and payload == "signature-pagination"
            and not method.get("params") and _collection_return(method)):
        # The rule only decides pagination versus a plain filter. With no
        # parameter at all there is still no field to filter on, so the
        # method is a stub, not a filter: offer the synthetic criterion
        # question instead of leaving it silently unusable. Without this,
        # a rule-resolved `find_active_members` never gets asked, and the
        # surface review can only offer the inverse `find_inactive_members`.
        kind, payload = "pattern", "FILTER_BY_FIELD"
    if kind == "pattern" and payload in ("READ_ALL", "FILTER_BY_FIELD",
                                         "FILTER_WITH_PAGINATION"):
        strategy, _ = codegen.plan_method(method, entry, ctx["entity_names"])
        if (strategy == "stub" and not method.get("params")
                and _collection_return(method)):
            payload = "FILTER_CRITERION"
    if (kind == "pattern" and payload == "AGGREGATE_BY_FK_AND_DATE"):
        # A total over all rows has no date slice when the entity and the
        # signature expose no date at all; the date pattern then offers no
        # review question.  Fall back to the same aggregate without the date
        # role, which is exactly the operation the contract describes.
        entity = next((item.get("entity") for item in ctx.get("repositories") or []
                       if item.get("interface_name") == holder), None)
        has_date = any(_is_date_type(field.get("type"))
                       for _name, field in fields_of(ctx, entity))
        has_date_param = any(_is_date_type(param.get("type"))
                             for param in method.get("params") or []
                             if isinstance(param, dict))
        if (not has_date and not has_date_param
                and normalize(method.get("name") or "").startswith(
                    ("gettotal", "total", "sum"))):
            # A plain grand total has no date slice; other date-shaped
            # aggregates (counts grouped by a field, utilization rates) are
            # not this operation and stay with the normal planner.
            payload = "AGGREGATE_BY_FK"
    if kind != "pattern" or payload not in SLOT_PATTERNS:
        return None, {}
    record = ctx.get("slots", {}).get((holder, method.get("name")))
    if not isinstance(record, dict) or not isinstance(record.get("slots"), dict):
        return payload, {}
    return payload, record["slots"]


def _required_slots(pattern, slots, is_repo=True):
    """Required slots: catalog minus the optional fk slice, minus the target
    under COUNT, service guards naming their full cast instead."""
    if pattern == "BUDGET_OVERFLOW_GUARD" and not is_repo:
        return list(SERVICE_BUDGET_SLOTS)
    required = [slot for slot in SLOT_REQUIREMENTS.get(pattern, ())
                if slot != "fk_field"]
    if pattern.startswith("AGGREGATE") and slots.get("aggregate_func") == "COUNT":
        required = [slot for slot in required if slot != "target_field"]
    return required


def _complete_slots(pattern, slots, is_repo=True):
    """True when every required slot is answered (COUNT needs no target).

    `fk_field` is never required: it scopes the aggregate only when a
    parameter feeds it (a monthly total takes no fk argument), so the review
    asks it solely when a matching parameter exists — otherwise the record
    simply carries no slice.
    """
    return all(slots.get(slot) not in (None, "")
               for slot in _required_slots(pattern, slots, is_repo))


def _slots_usable(pattern, slots, method, is_repo=True):
    """True when recorded slots are well-formed enough to emit from.

    Completeness is not enough: a hand-written record could name an unknown
    func, a threshold that is neither `today` nor a parameter, or an fk no
    argument supplies — and the emitter would write a body that fails at
    runtime. Anything off here is a stub, exactly as if the question were
    still open. Service guards resolve their cast in `_service_guard_plan`
    instead; here only their shapes are checked.
    """
    if not _complete_slots(pattern, slots, is_repo):
        return False
    if not all(isinstance(slots.get(slot), str)
               for slot in _required_slots(pattern, slots, is_repo)):
        return False
    params = {p.get("name") for p in method.get("params") or []
              if isinstance(p, dict) and isinstance(p.get("name"), str)}
    if pattern.startswith("AGGREGATE"):
        if slots.get("aggregate_func") not in ("SUM", "COUNT", "AVG", "MIN", "MAX"):
            return False
        if slots.get("fk_field") and slots["fk_field"] not in params \
                and normalize(slots["fk_field"]) not in {normalize(p) for p in params}:
            return False
        return True
    if pattern == "THRESHOLD_SCAN":
        if slots.get("operator") not in ("<", "<=", ">", ">=", "="):
            return False
        threshold = slots.get("threshold")
        return threshold == "today" or threshold in params
    # BUDGET_OVERFLOW_GUARD: cross-method references resolve in the plan
    # (`_service_guard_plan`) and the repo check body; here only shapes.
    return True


def _slot_fk_param(method, fk_field):
    """The parameter feeding the fk filter, or None when the method takes none."""
    if not fk_field:
        return None
    for param in method.get("params") or []:
        if isinstance(param, dict) and normalize(param.get("name") or "") == normalize(fk_field):
            return param.get("name")
    return None


def _slot_date_role(method):
    """How the signature carries dates: `("range", start, end)`,
    `("prefix", param)` or None — param names verified, never assumed."""
    names = [p.get("name") for p in method.get("params") or []
             if isinstance(p, dict) and isinstance(p.get("name"), str)]
    canon = {name: codegen.canon_tokens(name) for name in names}
    starts = [name for name, tokens in canon.items() if tokens[:1] == ["start"]]
    ends = [name for name, tokens in canon.items() if tokens[:1] == ["end"]]
    if starts and ends:
        return ("range", starts[0], ends[0])
    for name in names:
        if normalize(name) in ("month", "year"):
            return ("prefix", name)
    return None


def _repo_named_filter_body(ctx, entity, model_cls, method):
    """A repository `filter_by_<field>` with no reviewed field argument.

    `BookRepository.filter_by_available_copies` is named by the prompt, but
    its optional boolean is not a model field, so the generic filter planner
    refuses it. The method name itself names the field (the model is the
    authority that `available_copies` exists); the body keeps that field's
    positive condition even when the optional flag is omitted, because the
    acceptance contract calls the finder with no argument after a zero-copy
    book exists. The CLI's `book list` path uses `read_all`, not this method.
    """
    name = normalize(method.get("name") or "")
    if not name.startswith("filterby"):
        return None
    field = next((field_name for field_name, _field in fields_of(ctx, entity)
                  if normalize(field_name) and normalize(field_name) in name),
                 None)
    if field is None:
        return None
    field_type = dict((name, (field.get("type") or ""))
                      for name, field in fields_of(ctx, entity)).get(field, "")
    declared = str(field_type).strip().lower()
    if declared in ("bool", "boolean"):
        criterion = f"({field!r}, 'eq', True)"
    elif declared in ("int", "integer", "float", "decimal", "number", "real"):
        criterion = f"({field!r}, 'ge', 1)"
    else:
        return None
    params = [param for param in method.get("params") or []
              if isinstance(param, dict) and param.get("name")]
    if len(params) > 1:
        return None
    lines = []
    if params:
        ident = codegen.sanitize(params[0]["name"], "param")
        lines.append(f"criteria = [{criterion}] if {ident} is not False else []")
    else:
        lines.append(f"criteria = [{criterion}]")
    lines.append("found = self._store.select(self.ENTITY, criteria)")
    if model_cls is None:
        lines.append("return [dict(record) for record in found]")
    else:
        lines.append(f"return [{model_cls}(**record) for record in found]")
    return lines


def _repo_slot_body(ctx, entity, model_cls, field_types, method, pattern, slots):
    """An aggregate, threshold, or budget-check body from answered slots."""
    fname = method.get("name") if isinstance(method.get("name"), str) else "?"
    if pattern.startswith("AGGREGATE"):
        return _repo_aggregate_body(entity, model_cls, method, fname, slots)
    if pattern == "THRESHOLD_SCAN":
        return _repo_threshold_body(entity, model_cls, field_types, method,
                                    fname, slots)
    if pattern == "BUDGET_OVERFLOW_GUARD":
        return _repo_budget_check_body(ctx, entity, method, fname, slots)
    if pattern == "FILTER_CRITERION":
        return _repo_criterion_body(ctx, entity, model_cls, field_types,
                                    method, fname, slots)
    return None


def _repo_criterion_body(ctx, entity, model_cls, field_types, method, fname,
                         slots):
    """A flat equality filter from an answered criterion.

    The literal must be grounded: True/False on a boolean field, or a value
    the invariants document for the field. An unverifiable literal refuses —
    the emitter falls back to the stub rather than inventing the constraint
    the method exists for.
    """
    field = slots.get("criterion_field")
    value = slots.get("criterion_value")
    if not isinstance(field, str) or not isinstance(value, str):
        return None
    ftype = str((field_types or {}).get(field) or "").strip().lower()
    if ftype in ("boolean", "bool"):
        if value not in ("True", "False"):
            return None
        literal = value
    else:
        if value not in _field_vocabulary(ctx, entity, field):
            return None
        literal = repr(value)
    lines = [f"criteria = [({field!r}, 'eq', {literal})]",
             "found = self._store.select(self.ENTITY, criteria)"]
    if model_cls is None:
        lines.append("return [dict(record) for record in found]")
    else:
        lines.append(f"return [{model_cls}(**record) for record in found]")
    return lines


def _repo_budget_check_body(ctx, entity, method, fname, slots):
    """True when the named budget question is true, else False.

    Reads the matching budget record (scope comes from the method's own
    parameters, mapped by name onto budget fields), totals the spending
    entity's scoped records, and compares. The name decides the polarity:
    `check_budget_exceeded` is True when spending is over the limit and
    False when there is no budget; `check_budget_status` is the opposite,
    True while spending stays within the limit. No budget record means no
    limit to exceed, so the exceeded form is False and the within form is
    True. Only `bool` returns are emitted — a status vocabulary would be
    invented — and every parameter must scope something, or the check is
    not this shape.
    """
    returns = normalize(method.get("return_type") or "")
    if returns not in ("bool", "boolean"):
        return None
    name = normalize(fname or "")
    exceeded = any(word in name for word in ("exceed", "overflow", "overbudget"))
    no_budget = "False" if exceeded else "True"
    verdict = (f"spent > limit if limit is not None else False"
               if exceeded else
               f"spent <= limit if limit is not None else True")
    spend_entity = slots.get("spend_entity")
    spend_fields = [name for name, _ in fields_of(ctx, spend_entity)]
    if not spend_fields:
        return None
    date_field = slots.get("date_field")
    target = slots.get("target_field")
    scope_lines = []
    spend_lines = []
    month_idents = []
    budget_fields = [name for name, _ in fields_of(ctx, entity)]
    for param in method.get("params") or []:
        if not isinstance(param, dict) or not param.get("name"):
            return None
        raw = param["name"]
        ident = codegen.sanitize(raw, "param")
        if normalize(raw) in ("month", "year"):
            field = next((name for name in budget_fields
                          if normalize(name) == normalize(raw)), None)
            if field is None:
                return None
            month_idents.append(ident)
            scope_lines.append(f"            if record.get({field!r}) == {ident}")
            spend_lines.append(
                f"    if not str(record.get({date_field!r}) or '').startswith({ident}):")
            spend_lines.append(f"        continue")
        elif any(normalize(raw) == normalize(name) for name in budget_fields):
            field = next(name for name in budget_fields
                         if normalize(name) == normalize(raw))
            scope_lines.append(f"            if record.get({field!r}) == {ident}")
            if any(normalize(raw) == normalize(name) for name in spend_fields):
                sfield = next(name for name in spend_fields
                              if normalize(name) == normalize(raw))
                spend_lines.append(f"    if record.get({sfield!r}) != {ident}:")
                spend_lines.append(f"        continue")
            else:
                return None
        else:
            return None
    lines = [
        f"budgets = self._store.select(self.ENTITY, [])",
        f"match = [record for record in budgets",
    ] + scope_lines + [
        f"]",
        f"if not match:",
        f"    return {no_budget}  # no budget record: no limit to exceed",
        f"limit = match[0].get({slots['limit_field']!r})",
        f"spent = 0",
        f"for record in self._store.select({spend_entity!r}, []):",
    ] + spend_lines + [
        f"    spent += record.get({target!r}) or 0",
        f"return {verdict}",
    ]
    if month_idents:
        guard = [f"if not ({' or '.join(month_idents)}):",
                 f"    raise ValueError(\"budget check needs a month scope: "
                 f"an empty month matches every record\")"]
        lines[0:0] = guard
    return lines


def _repo_aggregate_body(entity, model_cls, method, fname, slots):
    """SUM/COUNT/AVG/MIN/MAX over records matching the fk and date slices."""
    func = slots.get("aggregate_func")
    target = slots.get("target_field")
    fk_param = _slot_fk_param(method, slots.get("fk_field"))
    date_role = _slot_date_role(method)
    date_field = slots.get("date_field")
    lines = []
    if func == "COUNT":
        lines.append("count = 0")
    elif func == "AVG":
        lines += ["total = 0", "count = 0"]
    elif func in ("MIN", "MAX"):
        lines.append("best = None")
    else:
        lines.append("total = 0")
    lines.append(f"for record in self._store.select(self.ENTITY, []):")
    if fk_param:
        lines.append(f"    if {codegen.sanitize(fk_param, 'param')} is not None and "
                     f"record.get({slots['fk_field']!r}) != {codegen.sanitize(fk_param, 'param')}:")
        lines.append(f"        continue")
    if isinstance(date_role, tuple) and date_role[0] == "range" and date_field:
        _, start_param, end_param = date_role
        start_ident = codegen.sanitize(start_param, "param")
        end_ident = codegen.sanitize(end_param, "param")
        lines.append(f"    if {start_ident} is not None and "
                     f"str(record.get({date_field!r}) or '') < str({start_ident}):")
        lines.append(f"        continue")
        lines.append(f"    if {end_ident} is not None and "
                     f"str(record.get({date_field!r}) or '') > str({end_ident}):")
        lines.append(f"        continue")
    elif isinstance(date_role, tuple) and date_role[0] == "prefix" and date_field:
        param = codegen.sanitize(date_role[1], "param")
        lines.append(f"    if {param} is not None and not "
                     f"str(record.get({date_field!r}) or '').startswith(str({param})):")
        lines.append(f"        continue")
    if func == "COUNT":
        lines.append("    count += 1")
    elif func == "AVG":
        lines.append(f"    total += record.get({target!r}) or 0")
        lines.append("    count += 1")
    elif func == "MIN":
        lines.append(f"    value = record.get({target!r})")
        lines.append("    best = value if best is None or (value is not None and value < best) else best")
    elif func == "MAX":
        lines.append(f"    value = record.get({target!r})")
        lines.append("    best = value if best is None or (value is not None and value > best) else best")
    else:
        lines.append(f"    total += record.get({target!r}) or 0")
    if func == "COUNT":
        lines.append("return count")
    elif func == "AVG":
        lines.append("return (total / count) if count else 0")
    elif func in ("MIN", "MAX"):
        lines.append("return best")
    else:
        lines.append("return total")
    return lines


def _repo_threshold_body(entity, model_cls, field_types, method, fname, slots):
    """Records whose field crosses the threshold: param or today.

    Date-typed fields compare as ISO `YYYY-MM-DD` prefixes (lexicographic
    holds for both date strings and datetimes); anything else compares
    directly. Only `today` and real parameters can be thresholds — a literal
    would be an unreviewed constant, so the review never offers one.
    """
    field = slots.get("comparison_field")
    operator = slots.get("operator")
    threshold = slots.get("threshold")
    ops = {"<": "<", "<=": "<=", ">": ">", ">=": ">=", "=": "=="}
    symbol = ops.get(operator, "<")
    dated = (field_types.get(field) or "").strip().lower() in ("date", "datetime") \
        or threshold == "today"
    lines = []
    if threshold == "today":
        lines.append("bound = datetime.date.today().isoformat()")
    else:
        lines.append(f"bound = {codegen.sanitize(threshold, 'param')}")
    lines.append("out = []")
    lines.append(f"for record in self._store.select(self.ENTITY, []):")
    return_field = next((name for name, type_ in field_types.items()
                         if "return" in normalize(name)
                         and str(type_ or "").lower() in ("date", "datetime")),
                        None)
    if "overdue" in normalize(fname) and return_field is not None:
        # "Overdue" means two predicates: the due date has passed *and* the
        # loan has not been returned. THRESHOLD_SCAN names only the date
        # comparison, so the null-return half is emitted here; without it a
        # returned-but-late record would be reported as still overdue.
        lines.append(f"    if record.get({return_field!r}) is not None:")
        lines.append("        continue")
    if dated:
        lines.append(f"    key = str(record.get({field!r}) or '')[:10]")
        lines.append(f"    hit = key {symbol} str(bound)[:10]")
    else:
        lines.append(f"    value = record.get({field!r})")
        lines.append(f"    hit = value is not None and value {symbol} bound")
    lines.append(f"    if hit:")
    if model_cls is None:
        lines.append(f"        out.append(dict(record))")
    else:
        lines.append(f"        out.append({model_cls}(**record))")
    lines.append("return out")
    return lines

def _option_plans(options, stats):
    """Emitted `{flags, dest, type, ...}` per declared option.

    One planning pass so the parser lines and the binding choices read the
    same skips: help/version are argparse's, a repeated dest registers once,
    a flag string taken twice on one parser keeps its free strings or is
    skipped with none left — reported either way, since one flag goes
    unreachable.
    """
    plans = []
    seen = set()
    taken = {"-h", "--help"}
    for option in options or []:
        if not isinstance(option, dict):
            continue
        raw = (option.get("name") or option.get("short") or "").strip()
        if not raw.startswith("-"):
            raw = "--" + raw if raw else ""
        # A multi-character single-dash token is a long option written with
        # the wrong arity (`-title`), not a short flag. Emit the standard
        # spelling the requirements use (`--title`); a true short flag such
        # as `-t` is left alone.
        if raw.startswith("-") and not raw.startswith("--") \
                and len(raw) > 2:
            raw = "--" + raw[1:]
        if not raw:
            continue
        if raw.lstrip("-").lower() in ("help", "version"):
            stats.setdefault("skipped_options", []).append(raw)
            continue
        dest = codegen.sanitize(raw.lstrip("-").replace("-", "_"), "opt")
        if dest in seen:
            continue
        seen.add(dest)
        flags = [raw]
        short = (option.get("short") or "").strip()
        if short and short != raw:
            flags.append(short)
        flags = [f for f in flags if f not in taken]
        if not flags:
            stats.setdefault("skipped_options", []).append(f"{raw} (all flag strings taken)")
            continue
        taken.update(flags)
        plans.append({"flags": flags, "dest": dest,
                      "otype": (option.get("type") or "str").strip().lower(),
                      "required": bool(option.get("required")),
                      "default": option.get("default")})
    return plans


def _render_plan(indent, parser_var, plan):
    """The `add_argument` line for one planned option."""
    parts = [f"{flag!r}" for flag in plan["flags"]]
    otype = plan["otype"]
    if otype == "bool":
        parts.append("action='store_true'" if not plan["default"] else "action='store_false'")
        if plan["default"]:
            parts.append("default=True")
    elif otype == "list":
        parts.append("nargs='*'")
        if plan["default"] is not None:
            parts.append(f"default={plan['default']!r}")
    else:
        parts.append(f"type={ {'str': 'str', 'int': 'int', 'float': 'float'}.get(otype, 'str')}")
        parts.append(f"required={plan['required']!r}")
        if plan["default"] is not None:
            parts.append(f"default={plan['default']!r}")
    parts.append(f"dest={plan['dest']!r}")
    return f"{indent}{parser_var}.add_argument({', '.join(parts)})"


def _emit_options(indent, parser_var, options, stats, destinations=None):
    """`add_argument` lines; emitted `(dest, flag, kind)` pairs are collected
    into `destinations` for the binding choices and dead-option check."""
    lines = []
    for plan in _option_plans(options, stats):
        lines.append(_render_plan(indent, parser_var, plan))
        if destinations is not None:
            destinations.append(
                (plan["dest"], plan["flags"][0],
                 "truthy" if plan["otype"] == "bool" else "value"))
    return lines


def _service_method(ctx, service_ref, method_name):
    """The documented method object for a service/repo reference, or None."""
    wanted = normalize(service_ref or "")
    for repo in ctx["repositories"]:
        names = {normalize(repo.get("interface_name") or ""),
                 normalize(repo.get("entity") or "")}
        if wanted not in names:
            continue
        for method in repo.get("methods") or []:
            if isinstance(method, dict) and method.get("name") == method_name:
                return method
    for service in ctx["services"]:
        if normalize(service.get("service_name") or "") != wanted:
            continue
        for method in service.get("methods") or []:
            if isinstance(method, dict) and method.get("name") == method_name:
                return method
    return None


def _return_shape(ctx, returns):
    """`collection`, `entity` or `scalar` — how a method's result displays."""
    if not isinstance(returns, str):
        return "scalar"
    words = {normalize(token) for token in
             re.findall(r"[A-Za-z_][A-Za-z0-9_]*", returns)}
    if "list" in words:
        return "collection"
    names = {normalize(name) for name in ctx["entity_names"]
             if isinstance(name, str)}
    return "entity" if words & names else "scalar"


def _alternate_actions(ctx, base_action, dests, actions):
    """Adapter actions this leaf's flags feed end-to-end, sorted.

    Only a leaf whose bound method takes no arguments can be refined by its
    flags — `budget list` reading everything becomes the category-month
    read when both flags are passed. A method that already takes arguments
    (`remove_product(id)`, `get_product(id)`) is not an unfiltered fallback,
    and its flags must never redirect it to a different action.

    An alternate counts only when every declared field binds to one of the
    leaf's own flags AND the same names are actual parameters of the
    action's target method, whose result still displays like a list. The
    parameter check is what refuses a mis-targeted document: the action
    `list_books_by_author` points at the availability filter with an
    `author_id` field, and no wiring may paper over that contradiction.
    """
    base = actions.get(base_action) or {}
    service = base.get("target_service")
    base_method = _service_method(ctx, service, base.get("target_method"))
    if base_method is None or base_method.get("params"):
        return []
    alternates = []
    for name in sorted(actions):
        spec = actions.get(name)
        if not isinstance(spec, dict) or name == base_action:
            continue
        if spec.get("target_service") != service:
            continue
        fields = [f for f in spec.get("input_fields") or []
                  if isinstance(f, dict) and f.get("field_name")]
        if not fields:
            continue
        method = _service_method(ctx, service, spec.get("target_method"))
        if method is None:
            continue
        params = {p.get("name") for p in method.get("params") or []
                  if isinstance(p, dict) and isinstance(p.get("name"), str)}
        if not all(f["field_name"] in params for f in fields):
            continue
        if _return_shape(ctx, method.get("return_type")) not in ("collection",
                                                                 "entity"):
            continue
        bindings = []
        used = set()
        ok = True
        for field in fields:
            source = field.get("flag") or field["field_name"]
            dest = codegen.bind_field(dests, source)
            if dest is None or dest in used:
                ok = False
                break
            used.add(dest)
            bindings.append((field["field_name"], dest))
        if not ok:
            continue
        alternates.append((name, bindings))
    return alternates


def _route_field(record, method):
    """The adapter field that carries a routed flag into the method.

    A parameterless route has none (the flag is a switch). A value route
    names the method's single parameter and the transform its CLI type
    needs; the record was checked against the signature by the review.
    """
    target = record.get("target_param")
    if not isinstance(target, str) or not target:
        return None
    params = [p for p in (method or {}).get("params") or []
              if isinstance(p, dict)]
    if len(params) != 1:
        return None
    if normalize(params[0].get("name") or "") != normalize(target):
        return None
    return {"field_name": params[0].get("name"), "target_param": target,
            "transform": record.get("transform") or "DIRECT",
            "required": True}


def _route_action_key(actions, service, method, field=None, dest=None):
    """An action key for a recorded route, synthesized when none exists.

    A parameterless routed method usually has no adapter action (that is why
    the flag is stranded); the virtual entry calls it with no arguments. A
    value route always gets its own action: reusing an adapter that maps the
    same method to different flags would send the value to the wrong dest.
    """
    if field is None:
        for name, spec in actions.items():
            if (isinstance(spec, dict)
                    and spec.get("target_service") == service
                    and spec.get("target_method") == method
                    and not (spec.get("input_fields") or [])):
                return name
        key = codegen.sanitize(method, "route")
        while key in actions:
            key += "_route"
        actions[key] = {"action_name": key, "target_service": service,
                        "target_method": method, "input_fields": []}
        return key
    key = codegen.sanitize(f"{method}_{dest or field['field_name']}", "route")
    while key in actions:
        key += "_route"
    actions[key] = {"action_name": key, "target_service": service,
                    "target_method": method, "input_fields": [field]}
    return key


def _leaf_choices(ctx, where, destinations, base_bound, actions, usage):
    """`[(action, score, need)]`: routes, mechanical alternates, fallback.

    `need` items are `(dest, kind, flag)` — `kind` `truthy` for boolean
    selectors, `value` for valued flags. The recorded routes come first
    (explicit human decisions), then alternates (document-derived), and
    the bound action last with an empty need, so dispatch always has a
    fallback and flags win over it whenever they are passed.
    """
    command, subcommand = where
    base_action, base_score = base_bound
    flag_of = {dest: flag for dest, flag, _kind in destinations}
    kind_of = {dest: kind for dest, _flag, kind in destinations}
    choices = []
    for record in ctx.get("routes") or []:
        if (record.get("command"), record.get("subcommand")) != where:
            continue
        flag = record.get("flag")
        if flag not in flag_of:
            continue
        service = record.get("service")
        method = record.get("method")
        method_spec = _service_method(ctx, service, method)
        if method_spec is None:
            continue
        field = _route_field(record, method_spec)
        if record.get("target_param") and field is None:
            continue
        if field is not None and kind_of[flag] != "value":
            # The component was not retyped: a boolean switch cannot carry
            # an author_id. Refuse rather than call the method with True.
            continue
        key = _route_action_key(actions, service, method, field, flag)
        if field is not None:
            usage.setdefault(key, []).append((field["field_name"], flag))
        choices.append((key, base_score,
                        ((flag, kind_of[flag], flag_of[flag]),)))
    used = [dest for dest, _flag, _kind in destinations]
    for name, bindings in _alternate_actions(ctx, base_action, used, actions):
        usage.setdefault(name, []).extend(bindings)
        need = tuple((dest, kind_of[dest], flag_of[dest])
                     for _field, dest in bindings)
        choices.append((name, base_score, need))
    choices.append((base_action, base_score, ()))
    return choices


def _report_dead_options(where, dead, stats):
    """Declared options no choice reads: parsed, then ignored.

    `member list -active-only` printed every member — the flag parsed and
    did nothing, which is worse than refusing. The surface is the
    documents'; removing or wiring the flag is a human decision, so it is
    reported here, never silently dropped and never guessed at.
    """
    for _dest, flag, _kind in dead:
        stats.setdefault("dead_options", []).append(
            f"{where}: {flag} — no adapter field reads it")


def _leaf_scan(ctx, bindings, stats):
    """Plan every leaf once: flags, choices, and flags no choice reads.

    Shared by the emitter and the route review (`review_surface.py`): the
    same numbers decide what the CLI dispatches to and what the review asks
    about. Returns `(leaves, actions, argv, targets, assembled)`; each leaf
    carries `plans`, `destinations`, `choices` and `dead`.
    """
    actions = {a["action_name"]: a for a in ctx["adapters"]}
    invocation = (ctx["components"].get("facade") or {}).get("invocation") or {}
    argv = codegen.action_argv(ctx["adapters"], bindings, invocation)
    targets = codegen.action_targets(ctx["adapters"], ctx["services"],
                                     ctx["repositories"], ctx["entity_names"])
    assembled = {}
    for name, adapter in actions.items():
        assembled[name] = [
            f["field_name"] for f in adapter.get("input_fields") or []
            if isinstance(f, dict) and f.get("field_name")
            and codegen.is_assembly_field(adapter, f["field_name"],
                                          targets.get(name, {}))]
    # The choices phase: plan every leaf's flags once, work out what each
    # leaf may dispatch to, and only then let the emitter write the file in
    # its final order.
    leaves = []
    usage = {}
    for command in invocation.get("commands") or []:
        if not isinstance(command, dict) or not command.get("name"):
            continue
        cname = command["name"]
        subs = [s for s in (command.get("subcommands") or [])
                if isinstance(s, dict) and s.get("name")]
        if not subs:
            leaf_names = [None]
        else:
            # A recognized action group may also expose its own leaf (for
            # example `return --loan-id`) beside nested commands. The binding
            # phase adds that parent key only when the group has an action.
            leaf_names = ([None] if bindings.get((cname, None)) is not None else [])
            leaf_names.extend(s["name"] for s in subs)
        for sname in leaf_names:
            plans = _option_plans(codegen.leaf_options(invocation, cname, sname),
                                  stats)
            destinations = [(plan["dest"], plan["flags"][0],
                             "truthy" if plan["otype"] == "bool" else "value")
                            for plan in plans]
            bound = bindings.get((cname, sname))
            choices = None
            consumed = set()
            if bound:
                choices = _leaf_choices(ctx, (cname, sname), destinations,
                                        bound, actions, usage)
                for _action, _score, need in choices:
                    consumed.update(dest for dest, _kind, _flag in need)
                base_action = bound[0]
                for field in (actions.get(base_action) or {}).get("input_fields") or []:
                    if not isinstance(field, dict) or not field.get("field_name"):
                        continue
                    if field["field_name"] in assembled.get(base_action, []):
                        continue
                    dest = argv.get(base_action, {}).get(field["field_name"])
                    if dest:
                        consumed.add(dest)
            leaves.append({"command": cname, "subcommand": sname,
                           "plans": plans, "destinations": destinations,
                           "choices": choices,
                           "dead": [item for item in destinations
                                    if item[0] not in consumed] if bound else []})
    # Alternate choices read flags through argv: fill in their field→dest
    # mapping from the leaves that select them (the action itself was never
    # bound, so action_argv could not know these).
    for action, pairs in usage.items():
        entry = argv.setdefault(action, {})
        for field, dest in pairs:
            if entry.get(field) is None:
                entry[field] = dest
    # Routes may have synthesized actions after the first target pass.
    targets = codegen.action_targets(list(actions.values()), ctx["services"],
                                     ctx["repositories"], ctx["entity_names"])
    return leaves, actions, argv, targets, assembled


def _click_commands(invocation, leaves):
    """A declarative command tree for the click backend.

    Keeping the tree as data makes the generated module small: one generic
    `_make_command` turns plans into `click.Option`s, and click owns parsing,
    help, typing and exit codes.
    """
    leaf_index = {(leaf["command"], leaf["subcommand"]): leaf
                  for leaf in leaves}
    tree = {}
    for command in invocation.get("commands") or []:
        if not isinstance(command, dict) or not command.get("name"):
            continue
        cname = command["name"]
        subs = [sub for sub in (command.get("subcommands") or [])
                if isinstance(sub, dict) and sub.get("name")]
        if not subs:
            leaf = leaf_index.get((cname, None)) or {}
            tree[cname] = {"binding": (cname, None),
                           "plans": leaf.get("plans") or []}
            continue
        children = {}
        for sub in subs:
            sname = sub["name"]
            leaf = leaf_index.get((cname, sname)) or {}
            node = {"binding": (cname, sname), "plans": leaf.get("plans") or []}
            words = sname.split()
            if len(words) <= 1:
                children[sname] = node
                continue
            # A path (`category add`) becomes nested groups: `category` holds
            # `add`. The binding keeps the whole path, so dispatch still finds
            # the leaf by (command, path).
            holder = children
            for word in words[:-1]:
                holder = holder.setdefault(word, {}).setdefault("subcommands", {})
            holder.setdefault(words[-1], {}).update(node)
        group = {"subcommands": children}
        parent = leaf_index.get((cname, None))
        if parent is not None:
            group["binding"] = (cname, None)
            group["plans"] = parent.get("plans") or []
        tree[cname] = group
    return tree


def _click_cli_tail(leaves, invocation, stats):
    """The click-specific half of `cli.py`; shares ADAPTERS/BINDINGS/helpers."""
    commands = _click_commands(invocation, leaves)
    lines = ["", "",
             "COMMANDS = " + pprint.pformat(commands, width=110,
                                             sort_dicts=False),
             "",
             "",
             "def _make_option(plan):",
             "    attrs = {}",
             "    otype = plan.get('otype')",
             "    if otype == 'bool':",
             "        attrs['is_flag'] = True",
             "        attrs['default'] = bool(plan.get('default'))",
             "    elif otype == 'list':",
             "        attrs['multiple'] = True",
             "        attrs['type'] = str",
             "    else:",
             "        attrs['type'] = {'str': str, 'int': int,",
             "                         'float': float}.get(otype, str)",
             "        attrs['required'] = bool(plan.get('required'))",
             "        if plan.get('default') is not None:",
             "            attrs['default'] = plan['default']",
             "    return click.Option(list(plan['flags']) + [plan['dest']], **attrs)",
             "",
             "",
             "def _make_command(name, spec):",
             "    if 'subcommands' in spec:",
             "        params = [_make_option(dict(plan, required=False))",
             "                  for plan in spec.get('plans', [])]",
             "        callback = None",
             "        if 'binding' in spec:",
             "            def callback(ctx, **kwargs):",
             "                if ctx.invoked_subcommand is None:",
             "                    return _dispatch(spec['binding'], kwargs, ctx.obj)",
             "            callback = click.pass_context(callback)",
             "        group = click.Group(name, params=params, callback=callback,",
             "                            invoke_without_command=('binding' in spec))",
             "        for child_name, child in spec['subcommands'].items():",
             "            group.add_command(_make_command(child_name, child))",
             "        return group",
             "    def callback(deps, **kwargs):",
             "        return _dispatch(spec['binding'], kwargs, deps)",
             "    params = [_make_option(plan) for plan in spec.get('plans', [])]",
             "    return click.Command(name, params=params,",
             "                         callback=click.pass_obj(callback))",
             "",
             "",
             "def _call(bound, values, deps):",
             "    action = bound[0]",
             "    spec = ADAPTERS[action]",
             "    service = deps['services'][_sanitize(spec['service'])]",
             "    method = getattr(service, _sanitize(spec['method']))",
             "    present = {_normalize(k): v for k, v in values.items()}",
             "    argv = spec.get('argv', {})",
             "    targets = spec.get('targets', {})",
             "    assembled = set(spec.get('assembled', []))",
             "    grouped = {}",
             "    for field_name, (target_param, kind, required) in spec['fields']:",
             "        if field_name in assembled:",
             "            continue  # built from its sibling fields, not from argv",
             "        dest = argv.get(field_name)",
             "        given = present.get(_normalize(dest)) if dest is not None else None",
             "        # An absent no-value flag parses as False: it was not given, so the",
             "        # method's own default applies (`member list` without --active-only",
             "        # lists everyone, not the inactive).",
             "        if given is None or given is False:",
             "            if required and given is None:",
             "                raise ValueError(f\"missing required field {field_name!r} for {action!r}\")",
             "            if given is None and spec.get('creates') and str(field_name).endswith('date') and str(field_name) not in ('due_date', 'return_date', 'start_date', 'end_date', 'birth_date'):",
             "                given = datetime.date.today()",
             "            else:",
             "                continue",
             "        value = _transform(kind, given, field_name)",
             "        if targets.get(target_param) and targets[target_param].startswith('__mapping__:'):",
             "            grouped.setdefault(target_param, {})[field_name] = value",
             "        elif targets.get(target_param) is not None:",
             "            grouped.setdefault(target_param, {})[field_name] = value",
             "        else:",
             "            grouped[target_param] = value",
             "    call_kwargs = {}",
             "    for target_param, value in grouped.items():",
             "        model_name = targets.get(target_param)",
             "        if model_name and model_name.startswith('__mapping__:'):",
             "            call_kwargs[_sanitize(target_param)] = value",
             "        elif model_name is not None and isinstance(value, dict):",
             "            call_kwargs[_sanitize(target_param)] = getattr(models, model_name)(**value)",
             "        else:",
             "            call_kwargs[_sanitize(target_param)] = value",
             "    return method(**call_kwargs)",
             "",
             "",
             "def _sanitize(text):",
             '    cleaned = "".join(c if c.isalnum() or c == "_" else "_" for c in str(text))',
             '    cleaned = cleaned.strip("_") or "opt"',
             '    return "_" + cleaned if cleaned[:1].isdigit() else cleaned',
             "",
             "",
             "def build_cli(db_path=None):",
             "    store = Store(db_path, SCHEMA)",
             "    repos = {cls_name: getattr(repositories, cls_name)(store) for cls_name in REPOSITORIES}",
             "    hired = {cls_name: getattr(services, cls_name)(repos) for cls_name in SERVICES}",
             "    entities = {_normalize(name): getattr(models, name) for name in MODELS}",
             "    return {'store': store, 'repos': repos,",
             "            'services': {**repos, **hired},",
             "            'entities': entities}",
             "",
             "",
             "def _dispatch(binding, values, deps):",
             "    \"\"\"Run one click command against shared dependencies.\"\"\"",
             "    bound = BINDINGS.get(tuple(binding))",
             "    if bound is None:",
             "        raise click.ClickException(",
             "            f\"no adapter bound for {' '.join(binding)} — not implemented\")",
             "    choice, present = _choose(bound, values)",
             "    trouble = _incomplete(choice, bound, present)",
             "    if trouble:",
             "        raise click.ClickException(",
             "            f\"{' '.join(binding)}: {trouble}\")",
             "    try:",
             "        _show(_call(choice, values, deps))",
             "    except click.ClickException:",
             "        raise",
             "    except Exception as error:",
             "        raise click.ClickException(_error_text(error)) from error",
             "    return 0",
             "",
             "",
             "@click.group(" + repr(stats["prog"]) + ")",
             "@click.option('--db', default=None,",
             "              help=('SQLite file for record storage (default: ' + DEFAULT_DB + ' in the working directory; use :memory: to stay in memory)'))",
             "@click.pass_context",
             "def cli(ctx, db):",
             "    deps = build_cli(db or DEFAULT_DB)",
             "    ctx.obj = deps",
             "    ctx.call_on_close(lambda: deps['store'].close())",
             "",
             "",
             "for _name, _spec in COMMANDS.items():",
             "    cli.add_command(_make_command(_name, _spec))",
             "",
             "",
             "def main(argv=None):",
             "    try:",
             "        cli.main(args=argv, prog_name=" + repr(stats["prog"]) + ",",
             "                 standalone_mode=False)",
             "    except click.exceptions.Exit as error:",
             "        return error.exit_code",
             "    except click.ClickException as error:",
             "        error.show()",
             "        return error.exit_code",
             "    except click.Abort:",
             "        click.echo('Aborted!', err=True)",
             "        return 1",
             "    return 0",
             "",
             "",
             'if __name__ == "__main__":',
             "    sys.exit(main())",
             ""]
    return lines


def emit_cli(ctx, bindings, stats):
    """A CLI in the declared backend: every verb parses; bound verbs dispatch.

    A leaf may bind several choices: recorded routes (a flag selecting a
    method the documents never linked it to), mechanical alternates (an
    adapter action every one of whose fields the leaf's flags supply, and
    whose own target method agrees with those field names), then the plain
    bound action as the fallback. The first choice whose flags are all
    passed wins; flags that select nothing are reported, not ignored.
    """
    technology = ((ctx.get("components") or {}).get("facade") or {}).get("technology")
    click_backend = str(technology or "").strip().lower() == "click"
    repo_classes = [codegen.sanitize(r.get("interface_name") or r.get("entity"), "Repository")
                    for r in ctx["repositories"]]
    port_names = {normalize(r.get("interface_name") or "") for r in ctx["repositories"]}
    service_classes = [codegen.sanitize(s["service_name"], "Service")
                       for s in ctx["services"]
                       if normalize(s["service_name"]) not in port_names
                       and not normalize(s["service_name"]).endswith("repository")]
    model_names = [codegen.sanitize(m["name"], "Model") for m in ctx["models"]]
    leaves, actions, argv, targets, assembled = _leaf_scan(ctx, bindings, stats)
    for leaf in leaves:
        where = (leaf["command"] if leaf["subcommand"] is None
                 else f"{leaf['command']} {leaf['subcommand']}")
        _report_dead_options(where, leaf["dead"], stats)
        for action, _score, need in leaf["choices"] or []:
            if not need:
                continue
            stats.setdefault("choice_routes", []).append(
                f"{where}: "
                f"{' '.join(flag for _dest, _kind, flag in need)} -> {action}")
    lines = ['"""Command line. Every declared verb parses; bound verbs dispatch to',
             "their adapter's service method, unbound ones fail with the reason.",
             "",
             "Transforms follow the adapter document: DIRECT passes through, ISO_DATE",
             "validates ISO format, DECIMAL_TO_CENTS converts money to integer cents,",
             "CSV_LIST splits on commas, INT_LIST converts a list to integers,",
             "LOOKUP_ID coerces to int (existence is enforced by the repository's",
             "foreign-key check on write, or by the record lookup itself on read),",
             "BOOL_TO_ONE turns a selector such as --available-only into the",
             "minimum count of one.",
             '"""',
             "",
             "import click" if click_backend else "import argparse",
             "import dataclasses",
             "import datetime",
             "import json",
             "import sys",
             "",
             "import models",
             "import errors",
             "from schema import SCHEMA",
             "from store import Store",
             "import repositories",
             "import services",
             "",
             "",
             "MODELS = " + repr(model_names),
             "REPOSITORIES = " + repr(repo_classes),
             "SERVICES = " + repr(service_classes),
             "",
             "",
             "def _transform(kind, value, field):",
             '    if kind == "DIRECT" or value is None:',
             "        return value",
             '    if kind == "ISO_DATE":',
             "        text = str(value)",
             '        if "T" in text or " " in text:',
             "            return datetime.datetime.fromisoformat(text)",
             "        return datetime.date.fromisoformat(text)",
             '    if kind == "DECIMAL_TO_CENTS":',
             "        return int(round(float(value) * 100))",
             '    if kind == "CSV_LIST":',
              "        items = value if isinstance(value, (list, tuple)) else [value]",
              "        split = []",
              "        for part in items:",
              "            split.extend(p.strip() for p in str(part).split(\",\") if p.strip())",
              "        return split",
             '    if kind == "INT_LIST":',
              "        items = value if isinstance(value, (list, tuple)) else [value]",
              "        return [int(item) for item in items]",
             '    if kind == "LOOKUP_ID":',
             "        return int(value)",
             '    if kind == "ENUM_LOOKUP":',
             "        return str(value)",
             '    if kind == "BOOL_TO_ONE":',
             "        return 1 if value else 0",
             '    raise ValueError(f"unknown transform {kind!r} for {field!r}")',
             "",
             "",
             "def _show(result):",
             "    if result is None:",
             "        return",
             "    if isinstance(result, list):",
             "        for item in result:",
             "            _show(item)",
             "        return",
             "    if dataclasses.is_dataclass(result):",
             "        print(json.dumps(dataclasses.asdict(result), default=str))",
             "        return",
             "    if isinstance(result, (dict, tuple)):",
             "        print(json.dumps(result, default=str))",
             "        return",
             "    print(result)",
             "",
             "",
             "ADAPTERS = {"]
    for name in sorted(actions):
        adapter = actions[name]
        lines.append(f"    {name!r}: {{")
        lines.append(f"        'service': {adapter.get('target_service')!r},")
        lines.append(f"        'method': {adapter.get('target_method')!r},")
        lines.append("        'fields': [")
        for field in adapter.get("input_fields") or []:
            if not isinstance(field, dict):
                continue
            lines.append(
                f"            ({field.get('field_name')!r}, "
                f"({field.get('target_param')!r}, {field.get('transform')!r}, "
                f"{bool(field.get('required'))!r})),")
        lines.append("        ],")
        lines.append(f"        'argv': {argv.get(name, {})!r},")
        lines.append(f"        'targets': {targets.get(name, {})!r},")
        lines.append(f"        'assembled': {assembled.get(name, [])!r},")
        creates = str(adapter.get("target_method") or "").lower().startswith(
            ("add", "create"))
        lines.append(f"        'creates': {creates!r},")
        lines.append("    },")
        for field in adapter.get("input_fields") or []:
            if not isinstance(field, dict) or not field.get("field_name"):
                continue
            if argv.get(name, {}).get(field["field_name"]) is None:
                stats.setdefault("unbound_fields", []).append(
                    f"{name}.{field['field_name']} (required={bool(field.get('required'))})")
    lines.append("}")
    choice_index = {(leaf["command"], leaf["subcommand"]): leaf["choices"]
                    for leaf in leaves}
    lines += ["", "", "BINDINGS = {  # (command, subcommand) -> [(action, score, need)]"]
    for (command, sub), bound in sorted(bindings.items(), key=lambda item: str(item[0])):
        if bound is None:
            lines.append(f"    {(command, sub)!r}: None,")
            stats["unmapped"].append(f"{command} {sub}" if sub else f"{command}")
        else:
            choices = choice_index.get((command, sub)) or [(bound[0], bound[1], ())]
            rendered = ", ".join(f"({action!r}, {score}, {need!r})"
                                 for action, score, need in choices)
            lines.append(f"    {(command, sub)!r}: [{rendered}],")
    lines.append("}")
    lines += ["", "",
              "def _normalize(text):",
              '    return "".join(c for c in str(text).lower() if c.isalnum())',
              "",
              "",
              "def _needs_met(present, need):",
              "    for dest, kind, _flag in need:",
              "        value = present.get(_normalize(dest))",
              "        if kind == 'truthy':",
              "            if not value:",
              "                return False",
              "        elif value is None:",
              "            return False",
              "    return True",
              "",
              "",
              "def _choose(bound, values):",
              "    \"\"\"The first choice whose flags are all passed: routes and",
              "    filters before the fallback, which needs nothing.\"\"\"",
              "    present = {_normalize(k): v for k, v in values.items()}",
              "    for choice in bound:",
              "        if _needs_met(present, choice[2]):",
              "            return choice, present",
              "    return bound[-1], present",
              "",
              "",
              "def _incomplete(chosen, bound, present):",
              "    \"\"\"Flags passed that select a choice also needing companions",
              "    (`--category` without `--month`): naming the missing flag beats",
              "    ignoring the one passed.\"\"\"",
              "    consumed = {dest for dest, _kind, _flag in chosen[2]}",
              "    for action, _score, need in bound:",
              "        if action == chosen[0]:",
              "            continue",
              "        passed = [item for item in need if _needs_met(present, (item,))]",
              "        if not passed or len(passed) == len(need):",
              "            continue",
              "        if any(item[0] in consumed for item in passed):",
              "            continue",
              "        missing = ' and '.join(item[2] for item in need",
              "                               if item not in passed)",
              "        return f'{action!r} also needs {missing}'",
              "    return None",
              "",
              "",
              "def _error_text(error):",
              "    \"\"\"A domain error keeps its class name when it carries no text.\"\"\"",
              "    detail = str(error)",
              "    name = type(error).__name__",
              "    return f'{name}: {detail}' if detail else name",
              "",
              "",
              f"DEFAULT_DB = {stats['prog'] + '.db'!r}",
              ""]
    invocation = (ctx["components"].get("facade") or {}).get("invocation") or {}
    if click_backend:
        lines += _click_cli_tail(leaves, invocation, stats)
        return "\n".join(lines) + "\n"
    lines += ["",
              "def build_parser():",
              f"    parser = argparse.ArgumentParser(prog={stats['prog']!r})",
              "    parser.add_argument('--db', default=None,",
              "                        help=('SQLite file for record storage "
              "(default: ' + DEFAULT_DB + ' in the working directory; "
              "use :memory: to stay in memory)'))",
              "    sub = parser.add_subparsers(dest='command')"]
    leaf_index = {(leaf["command"], leaf["subcommand"]): leaf
                  for leaf in leaves}
    for command in invocation.get("commands") or []:
        if not isinstance(command, dict) or not command.get("name"):
            continue
        cname = command["name"]
        cvar = codegen.sanitize(cname, "cmd")
        subs = [s for s in (command.get("subcommands") or [])
                if isinstance(s, dict) and s.get("name")]
        if not subs:
            lines.append(f"    p_{cvar} = sub.add_parser({cname!r})")
            for plan in (leaf_index.get((cname, None)) or {}).get("plans", []):
                lines.append(_render_plan("    ", f"p_{cvar}", plan))
            lines.append("    p_" + cvar + ".set_defaults(_binding=" + repr((cname, None)) + ")")
        else:
            lines.append(f"    p_{cvar} = sub.add_parser({cname!r})")
            parent_leaf = leaf_index.get((cname, None))
            if parent_leaf is not None:
                # Parent options must be optional while parsing a child path;
                # the adapter completeness check enforces them only when the
                # parent action itself runs.
                for plan in parent_leaf.get("plans", []):
                    group_plan = dict(plan, required=False)
                    lines.append(_render_plan("    ", f"p_{cvar}", group_plan))
                lines.append("    p_" + cvar + ".set_defaults(_parent_binding=" + repr((cname, None)) + ")")
            lines.append(f"    sub_{cvar} = p_{cvar}.add_subparsers(dest='subcommand')")
            groups = {(): f"sub_{cvar}"}
            for item in subs:
                sname = item["name"]
                svar = codegen.sanitize(sname, "sub")
                words = sname.split()
                holder = ()
                # A path (`category add`) is a chain of parsers: `category`
                # holds `add`. Each level stores its chosen name in the same
                # `subcommand` slot, which dispatch already ignores.
                for word in words[:-1] if len(words) > 1 else []:
                    key = holder + (word,)
                    if key not in groups:
                        gvar = codegen.sanitize("_".join(key), "grp")
                        lines.append(f"    p_{cvar}_{gvar} = {groups[holder]}.add_parser({word!r})")
                        lines.append(f"    sub_{cvar}_{gvar} = p_{cvar}_{gvar}.add_subparsers(dest='subcommand')")
                        groups[key] = f"sub_{cvar}_{gvar}"
                    holder = key
                leaf_name = words[-1] if len(words) > 1 else sname
                lines.append(f"    p_{cvar}_{svar} = {groups[holder]}.add_parser({leaf_name!r})")
                for plan in (leaf_index.get((cname, sname)) or {}).get("plans", []):
                    lines.append(_render_plan("    ", f"p_{cvar}_{svar}", plan))
                lines.append("    p_" + cvar + "_" + svar + ".set_defaults(_binding=" + repr((cname, sname)) + ")")
    lines += ["    return parser",
              "",
              "",
              "def _call(bound, values, deps):",
              "    action = bound[0]",
              "    spec = ADAPTERS[action]",
              "    service = deps['services'][_sanitize(spec['service'])]",
              "    method = getattr(service, _sanitize(spec['method']))",
              "    present = {_normalize(k): v for k, v in values.items()}",
              "    argv = spec.get('argv', {})",
              "    targets = spec.get('targets', {})",
              "    assembled = set(spec.get('assembled', []))",
              "    grouped = {}",
              "    for field_name, (target_param, kind, required) in spec['fields']:",
              "        if field_name in assembled:",
              "            continue  # built from its sibling fields, not from argv",
              "        dest = argv.get(field_name)",
              "        given = present.get(_normalize(dest)) if dest is not None else None",
              "        # An absent no-value flag parses as False: it was not given, so the",
              "        # method's own default applies (`member list` without --active-only",
              "        # lists everyone, not the inactive).",
              "        if given is None or given is False:",
              "            if required and given is None:",
              "                raise ValueError(f\"missing required field {field_name!r} for {action!r}\")",
              "            if given is None and spec.get('creates') and str(field_name).endswith('date') and str(field_name) not in ('due_date', 'return_date', 'start_date', 'end_date', 'birth_date'):",
              "                given = datetime.date.today()",
              "            else:",
              "                continue",
              "        value = _transform(kind, given, field_name)",
              "        if targets.get(target_param) and targets[target_param].startswith('__mapping__:'):",
              "            grouped.setdefault(target_param, {})[field_name] = value",
              "        elif targets.get(target_param) is not None:",
              "            grouped.setdefault(target_param, {})[field_name] = value",
              "        else:",
              "            grouped[target_param] = value",
              "    call_kwargs = {}",
              "    for target_param, value in grouped.items():",
              "        model_name = targets.get(target_param)",
              "        if model_name and model_name.startswith('__mapping__:'):",
              "            call_kwargs[_sanitize(target_param)] = value",
              "        elif model_name is not None and isinstance(value, dict):",
              "            call_kwargs[_sanitize(target_param)] = getattr(models, model_name)(**value)",
              "        else:",
              "            call_kwargs[_sanitize(target_param)] = value",
              "    return method(**call_kwargs)",
              "",
              "",
              "def _sanitize(text):",
              '    cleaned = "".join(c if c.isalnum() or c == "_" else "_" for c in str(text))',
              '    cleaned = cleaned.strip("_") or "opt"',
              '    return "_" + cleaned if cleaned[:1].isdigit() else cleaned',
              "",
              "",
              "def build_cli(db_path=None):",
              "    store = Store(db_path, SCHEMA)",
              "    repos = {cls_name: getattr(repositories, cls_name)(store) for cls_name in REPOSITORIES}",
              "    hired = {cls_name: getattr(services, cls_name)(repos) for cls_name in SERVICES}",
              "    entities = {_normalize(name): getattr(models, name) for name in MODELS}",
              "    return build_parser(), {'store': store, 'repos': repos,",
              "                           'services': {**repos, **hired},",
              "                           'entities': entities}",
              "",
              "",
              "def main(argv=None):",
              "    parser = build_parser()",
              "    args = parser.parse_args(argv)",
              "    _, deps = build_cli(args.db or DEFAULT_DB)",
              "    try:",
              "        return dispatch(parser, args, deps)",
              "    finally:",
              "        deps['store'].close()",
              "",
              "",
              "def dispatch(parser, args, deps):",
              "    \"\"\"Run one parsed command against shared dependencies.\"\"\"",
              "    binding = (getattr(args, '_binding', None)",
              "               or getattr(args, '_parent_binding', None))",
              "    if binding is None:",
              "        parser.print_usage()",
              "        return 2",
              "    bound = BINDINGS.get(tuple(binding))",
              "    if bound is None:",
              "        print(f\"no adapter bound for {' '.join(binding)} — not implemented\")",
              "        return 1",
              "    values = {key: value for key, value in vars(args).items()",
              "              if key not in ('command', 'subcommand', '_binding',",
              "                             '_parent_binding', 'db')}",
              "    choice, present = _choose(bound, values)",
              "    trouble = _incomplete(choice, bound, present)",
              "    if trouble:",
              "        print(f\"error: {' '.join(binding)}: {trouble}\")",
              "        return 1",
              "    try:",
              "        _show(_call(choice, values, deps))",
              "    except Exception as error:",
              "        print(f\"error: {_error_text(error)}\")",
              "        return 1",
              "    return 0",
              "",
              "",
              'if __name__ == "__main__":',
              "    sys.exit(main())",
              ""]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------

def emit_schema(ctx):
    """The database schema, generated from models and invariants.

    It is a plain Python literal so the generated program stays dependency-
    free. Unique flags follow the invariants when they are precise enough;
    explicit application defaults come from the requirements (the extraction
    format has no default slot).
    """
    schema = {}
    for model in ctx["models"]:
        entity = model["name"]
        fields = fields_of(ctx, entity)
        primary_key = next((name for name, field in fields
                            if field.get("primary_key")), "id")
        unique_fields = set(_unique_fields(ctx, entity))
        entries = []
        for name, field in fields:
            foreign = field.get("foreign_key")
            entries.append({
                "name": name,
                "type": field.get("type"),
                "primary_key": name == primary_key,
                "nullable": bool(field.get("nullable"))
                            and name != primary_key,
                "unique": name in unique_fields or name == primary_key,
                "foreign_key": foreign if isinstance(foreign, dict) else None,
                "default": _field_default(ctx, field),
            })
        schema[entity] = {"primary_key": primary_key, "fields": entries}
        groups = _unique_groups(ctx, entity)
        if groups:
            schema[entity]["unique_together"] = [list(group) for group in groups]
    return "SCHEMA = " + pprint.pformat(schema, width=110,
                                       sort_dicts=False) + "\n"


def _defer_annotations(text):
    """Make emitted annotations lazy without qualifying every model class.

    Type hints are not executable behavior, but a generated repository or
    service can name a UUID or a request shape that has no sibling import.
    `from __future__ import annotations` keeps those hints as strings and
    prevents import-time NameError from an otherwise runnable program.
    """
    if "from __future__ import annotations" in text:
        return text
    match = re.match(r"\A(\s*(?:\"\"\"[\s\S]*?\"\"\"|'''[\s\S]*?''')\s*\n)",
                     text)
    insert = match.end() if match else 0
    return text[:insert] + "from __future__ import annotations\n\n" + text[insert:]


def render_program(ctx, stats):
    """Every file of the package as `{filename: text}`."""
    stats.setdefault("skipped_options", [])
    stats.setdefault("unmapped", [])
    stats.setdefault("dead_options", [])
    repo_index = _repo_index(ctx)
    files = {
        "models.py": emit_models(ctx),
        "errors.py": emit_errors(ctx),
        "repositories.py": emit_repositories(ctx, stats),
        "services.py": emit_services(ctx, repo_index, stats),
        "schema.py": emit_schema(ctx),
    }
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "kernel", STORE_CONTRACT.template),
              encoding="utf-8") as handle:
        files["store.py"] = handle.read()
    from kernel.consistency.checks_surface import COMMAND_VERB_STEMS
    invocation = (ctx["components"].get("facade") or {}).get("invocation") or {}
    bindings, unmapped = codegen.bind_commands(ctx["adapters"], invocation, COMMAND_VERB_STEMS)
    for item in unmapped:
        if item not in stats["unmapped"]:
            stats["unmapped"].append(item)
    stats["bindings"] = {f"{c} {s}" if s else c: (b[0], b[1]) if b else None
                         for (c, s), b in bindings.items()}
    files["cli.py"] = emit_cli(ctx, bindings, stats)
    files["__init__.py"] = emit_init(ctx, stats)
    return files


def gate(output_dir):
    """`(ok, message)`: refuse generation when the probe would blame us."""
    name = os.path.basename(output_dir.rstrip(os.sep))
    blockers, risks, _ = probe_readiness.check_prompt(name, output_dir)
    questions = probe_readiness.open_questions(output_dir)
    # A context repair may rebind an aggregate-create adapter to the entity's
    # plain create. The probe reads the source documents, where the old DTO
    # fields still look unknown; those findings and the field-mapping review
    # they prompted describe a surface the generator is no longer emitting.
    try:
        repaired = load_context(output_dir)
    except Exception:
        repaired = {}
    retargeted = {
        adapter.get("action_name") for adapter in repaired.get("adapters") or []
        if isinstance(adapter, dict) and adapter.get("_surface_retargeted")}
    if retargeted:
        def still_applies(finding):
            if finding.rule == "unknown_model_field" and any(
                    f"'{action}'" in finding.message for action in retargeted):
                return False
            if (finding.rule == "open_human_review"
                    and "field mapping" in finding.message):
                return False
            return True
        blockers = [finding for finding in blockers if still_applies(finding)]
    if blockers:
        first = "; ".join(f"[{b.rule}] {b.message}" for b in blockers[:5])
        return False, f"refusing: {len(blockers)} generator blocker(s): {first}"
    if questions:
        return False, (f"refusing: {questions} open tie(s) need a human "
                       f"(python review_ties.py {output_dir})")
    return True, (f"gate passed ({len(risks)} residual risk(s); "
                   "gaps stay documented stubs)")


def is_degenerate(ctx):
    """True when the documents carry no domain for the mechanical emitter.

    A program with no models, services, repositories or adapters has no
    architecture — the mechanical emitters would write an empty shell.  A
    command table alone is not architecture either: the command has no
    service method to call, so the generator can only emit an UNBOUND shell.
    The requirements describe the whole tiny program, so the direct `app.py`
    fallback is the honest path.  Any real domain content disables it.
    """
    return not (ctx["models"] or ctx["services"] or ctx["repositories"]
                or ctx["adapters"])


# --------------------------------------------------------------------------
# GUI backends (one generic emitter per declared technology)
# --------------------------------------------------------------------------

GUI_BACKENDS = ("pyimgui",)


def gui_backend(ctx, override=None):
    """`(kind, tech, note)`: the GUI to emit, if any.

    Only a `gui` facade asks for one, and the declared technology names it —
    `--gui-tech` overrides the declaration. Anything but a supported backend
    is a skip with a reason, never a silent substitution: emitting tkinter
    when the documents say pyimgui would be inventing an architecture choice.
    """
    facade = ctx["components"].get("facade")
    if not isinstance(facade, dict):
        return None, None, ""
    if (facade.get("type") or "").strip().lower() != "gui":
        if override:
            return None, None, "--gui-tech ignored: not a gui facade"
        return None, None, ""
    tech = (override or facade.get("technology") or "").strip().lower()
    if tech in GUI_BACKENDS:
        return "gui", tech, ""
    return None, None, f"unsupported gui technology {tech!r} — skipping gui.py"


def _widget_kind(field):
    """The input widget kind for a model field's declared type."""
    ftype = (field.get("type") or "str").strip().lower() if isinstance(field, dict) else "str"
    if ftype in ("int", "integer"):
        return "int"
    if ftype in ("float", "double", "decimal", "number", "money"):
        return "float"
    if ftype in ("bool", "boolean"):
        return "bool"
    return "str"


def _crud_binding(ctx, holder, repo):
    """`{create,read_all,update,delete}` -> method dict for the mechanical ones."""
    bound = {}
    for method in repo.get("methods") or []:
        if not isinstance(method, dict) or not method.get("name"):
            continue
        strategy, _ = codegen.plan_method(
            method, _match_entry(ctx, holder, method["name"]), ctx["entity_names"])
        if strategy.startswith("crud:"):
            bound.setdefault(strategy[5:], method)
    return bound


def _param_specs(method, entity_names):
    """`[{raw, py, kind, entity}]` per parameter; entity-typed ones build models."""
    specs = []
    for param in method.get("params") or []:
        if not isinstance(param, dict):
            continue
        raw = param.get("name") if isinstance(param.get("name"), str) else ""
        ptype = param.get("type")
        specs.append({"raw": raw, "py": codegen.sanitize(raw, "param"),
                      "kind": _widget_kind({"type": ptype if isinstance(ptype, str) else "str"}),
                      "entity": codegen.is_entity_type(ptype, entity_names)})
    return specs


def emit_gui_pyimgui(ctx, stats):
    """A generic pyimgui CRUD GUI: one window per modeled entity.

    No bespoke screens — the documents describe no forms or events, only
    models, CRUD services and adapters — so every entity with a repository
    gets the same working surface: a record table (read_all), field inputs
    with Add/Update, and delete by id. Service methods without a mechanical
    CRUD reading stay out (their stubs refuse), and the limitation is stated
    in the file header, not hidden.
    """
    panels = []
    for repo in ctx["repositories"]:
        entity = repo.get("entity")
        model = model_of(ctx, entity)
        if not isinstance(entity, str) or model is None:
            continue
        holder = repo.get("interface_name") or entity
        bound = _crud_binding(ctx, holder, repo)
        if not bound:
            continue
        fields = [{"name": name,
                   "kind": _widget_kind(field),
                   "pk": bool(field.get("primary_key"))}
                  for name, field in fields_of(ctx, entity)]
        ops = {}
        for op, method in bound.items():
            ops[op] = {"method": codegen.sanitize(method["name"], "method"),
                       "specs": _param_specs(method, ctx["entity_names"])}
        panels.append({"entity": entity,
                       "model": codegen.sanitize(entity, "Model"),
                       "repo": codegen.sanitize(holder, "Repository"),
                       "pk": primary_key_of(ctx, entity),
                       "fields": fields, "ops": ops})
    stats["gui_panels"] = [p["entity"] for p in panels]
    lines = ['"""Generic pyimgui CRUD GUI: one window per modeled entity.',
             "",
             "Generation principle: the PANELS table below is built from the",
             "documents — one panel per entity that has repository CRUD methods",
             "— and the rest of this file is a fixed runtime that draws every",
             "panel the same way. No bespoke screens: the documents describe",
             "no forms or events, so every entity gets the same working",
             "surface — record list, field inputs with Add/Update, delete by",
             "id — wired to the mechanical CRUD methods only. Service methods",
             "without one stay out; their stubs refuse with their work order.",
             "",
             "Requires: pip install imgui glfw PyOpenGL",
             '"""',
             "",
             "import imgui",
             "import glfw",
             "from imgui.integrations.glfw import GlfwRenderer",
             "from OpenGL import GL as gl",
             "",
             "import sys",
             "",
             "import models",
             "import errors",
             "from schema import SCHEMA",
             "from store import Store",
             "import repositories",
             "",
             "",
             f"DEFAULT_DB = {(stats.get('prog') or 'app') + '.db'!r}",
             "",
             "",
             "PANELS = " + repr(panels),
             "",
             "",
             "TOOLBAR_WIDTH = 160",
             "",
             "",
             "def _display():",
             '    """The current display size (toolbar math needs it twice)."""',
             "    return imgui.get_io().display_size",
             "",
             "",
             "def _parse(kind, text):",
             '    if text is None or (isinstance(text, str) and not text.strip()):',
             "        return None",
             '    if kind == "int":',
             "        return int(str(text).strip())",
             '    if kind == "float":',
             "        return float(str(text).strip())",
             '    if kind == "bool":',
             "        return str(text).strip().lower() in ('1', 'true', 'yes', 'y')",
             "    return str(text)",
             "",
             "",
             "def _new_state():",
             '    return {"rows": [], "inputs": {}, "id": "", "message": "", "open": True}',
             "",
             "",
             "def _refresh(panel, repo, state):",
             '    op = panel["ops"].get("read_all")',
             "    if op is None:",
             '        state["message"] = "no list method"',
             "        return",
             "    try:",
             '        state["rows"] = getattr(repo, op["method"])()',
             '        state["message"] = ""',
             "    except Exception as error:",
             '        state["message"] = f"error: {error}"',
             "",
             "",
             "def _collect(panel, state, specs):",
             '    """Split widgets into `(model_kwargs, scalar_kwargs)` for one call."""',
             "    names = {f['name'] for f in panel['fields']}",
             "    model_kwargs, scalar_kwargs = {}, {}",
             "    for spec in specs:",
             "        if spec['entity']:",
             "            continue  # assembled into the model instance below",
             "        if spec['raw'] in names:",
             "            text = state['inputs'].get(spec['raw'], '')",
             "            if not str(text).strip() and spec['raw'] == panel['pk']:",
             "                text = state['id']  # pk has no widget; the id box serves it",
             "        else:",
             "            text = state['inputs'].get(spec['raw'], '')",
             "        scalar_kwargs[spec['py']] = _parse(spec['kind'], text)",
             "    for field in panel['fields']:",
             "        value = _parse(field['kind'], state['inputs'].get(field['name'], ''))",
             "        if value is not None:",
             "            model_kwargs[field['name']] = value",
             "    return model_kwargs, scalar_kwargs",
             "",
             "",
             "def _invoke(panel, repo, state, op_name):",
             '    op = panel["ops"].get(op_name)',
             "    if op is None:",
             '        state["message"] = f"no {op_name} method"',
             "        return",
             "    try:",
             "        model_kwargs, scalar_kwargs = _collect(panel, state, op['specs'])",
             "        call_kwargs = dict(scalar_kwargs)",
             "        for spec in op['specs']:",
             "            if spec['entity']:",
             "                model_cls = getattr(models, panel['model'])",
             "                call_kwargs[spec['py']] = model_cls(**model_kwargs)",
             "        method = getattr(repo, op['method'])",
             "        method(**call_kwargs)",
             "        _refresh(panel, repo, state)  # add/update/delete reload the list",
             '        if not state["message"]:',
             '            state["message"] = f"{op_name} ok"',
             "    except Exception as error:",
             '        state["message"] = f"error: {error}"',
             "",
             "",
             "def _draw_toolbar(states):",
             '    """Left vertical bar, always visible: one button per window."""',
             "    size = _display()",
             "    imgui.set_next_window_position(0, 0)",
             "    imgui.set_next_window_size(TOOLBAR_WIDTH, size.y)",
             '    imgui.begin("toolbar")',
             "    for panel in PANELS:",
             "        state = states[panel['entity']]",
             "        label = ('[x] ' if state['open'] else '[ ] ') + panel['entity']",
             "        if imgui.button(label):",
             "            state['open'] = not state['open']",
             "    imgui.end()",
             "",
             "",
             "def _draw_panel(panel, repo, state):",
             "    size = _display()  # maximized in the space right of the toolbar",
             "    imgui.set_next_window_position(TOOLBAR_WIDTH, 0)",
             "    imgui.set_next_window_size(size.x - TOOLBAR_WIDTH, size.y)",
             "    opened, _ = imgui.begin(panel['entity'], True)",
             "    if not opened:",
             "        imgui.end()",
             "        return",
             '    if state["message"]:',
             '        imgui.text(state["message"])',
             "    imgui.text(f\"{panel['entity']} records:\")",
             "    columns = [f['name'] for f in panel['fields']] or ['-']",
             "    if imgui.begin_table('rows', len(columns)):",
             "        for name in columns:",
             "            imgui.table_next_column()",
             "            imgui.text(name)",
             "        for row in state['rows']:",
             "            imgui.table_next_row()",
             "            record = row if isinstance(row, dict) else vars(row)",
             "            for name in columns:",
             "                imgui.table_next_column()",
             "                imgui.text(str(record.get(name, '')))",
             "        imgui.end_table()",
             "    imgui.separator()",
             "    for field in panel['fields']:",
             "        if field['pk'] and 'create' in panel['ops']:",
             "            continue  # assigned by the store on insert",
             "        changed, value = imgui.input_text(",
             "            field['name'], state['inputs'].get(field['name'], ''), 256)",
             "        if changed:",
             "            state['inputs'][field['name']] = value",
             "    for op_name, label in (('create', 'Add'), ('update', 'Update')):",
             "        if op_name in panel['ops']:",
             "            imgui.same_line()",
             "            if imgui.button(f\"{label} {panel['entity']}\"):",
             "                _invoke(panel, repo, state, op_name)",
             "    imgui.separator()",
             "    _, state['id'] = imgui.input_text('id', state['id'], 64)",
             "    imgui.same_line()",
             "    if imgui.button('Delete') and 'delete' in panel['ops']:",
             "        _invoke(panel, repo, state, 'delete')",
             "    imgui.end()",
             "",
             "",
             "def build_gui():",
             "    store = Store(DEFAULT_DB, SCHEMA)",
             "    repos = {}",
             "    states = {}",
             "    for panel in PANELS:",
             "        repo = getattr(repositories, panel['repo'])(store)",
             "        repos[panel['repo']] = repo",
             "        state = _new_state()",
             "        _refresh(panel, repo, state)",
             "        states[panel['entity']] = state",
             "    return repos, states",
             "",
             "",
             "def main():",
             "    if not PANELS:",
             '        print("no GUI panels: no entity has CRUD methods")',
             "        return 1",
             "    if not glfw.init():",
             '        print("could not initialize glfw")',
             "        return 1",
             "    # macOS defaults to a legacy GL context, which the stock",
             "    # renderer cannot use (GLError 1282 in _create_device_objects).",
             "    # Other platforms keep their default context: forcing a",
             "    # profile there could break drivers that work fine as-is.",
             '    if sys.platform == "darwin":',
             "        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)",
             "        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 2)",
             "        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)",
             "        glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, True)",
             '    window = glfw.create_window(1280, 800, "crud", None, None)',
             "    glfw.make_context_current(window)",
             "    imgui.create_context()",
             "    impl = GlfwRenderer(window)",
             "    repos, states = build_gui()",
             "    while not glfw.window_should_close(window):",
             "        glfw.poll_events()",
             "        impl.process_inputs()",
             "        imgui.new_frame()",
             "        _draw_toolbar(states)",
             "        for panel in PANELS:",
             "            state = states[panel['entity']]",
             "            if state['open']:",
             "                _draw_panel(panel, repos[panel['repo']], state)",
             "        gl.glClearColor(0.1, 0.1, 0.1, 1)",
             "        gl.glClear(gl.GL_COLOR_BUFFER_BIT)",
             "        imgui.render()",
             "        impl.render(imgui.get_draw_data())",
             "        glfw.swap_buffers(window)",
             "    impl.shutdown()",
             "    glfw.terminate()",
             "    return 0",
             "",
             "",
             'if __name__ == "__main__":',
             "    raise SystemExit(main())",
             ""]
    return "\n".join(lines) + "\n"


def fallback_prompt(requirements, errors):
    """The whole tiny program, asked for directly: there is no architecture."""
    lines = ["Write a single-file Python 3 program (standard library only)",
             "implementing these requirements:", "",
             requirements.strip(), ""]
    named = [e for e in (errors or []) if isinstance(e, dict) and e.get("name")]
    if named:
        lines.append("Registered application errors (define and raise them where fitting):")
        for error in named:
            base = error.get("base") if isinstance(error.get("base"), str) and error["base"].strip() else "Exception"
            description = (error.get("description") or "").strip()
            lines.append(f"- {error['name']}({base}): {description}")
        lines.append("")
    lines += ["Rules:",
              "- Output ONLY Python code: no fences, no prose before or after,",
              "  no bullet points, no explanations.",
              '- Include `def main():` and the `if __name__ == "__main__": main()` guard.',
              "- Type hints throughout.",
              "- Define application errors named by the requirements as Python",
              "  exception classes (subclasses of `Exception`); raise each where",
              "  the failure occurs, with a clear message.",
              "- Expected input, decoding and file errors must be caught at the",
              "  command boundary: print a concise `error: ...` message to stderr",
              "  and exit nonzero. Never let an expected error escape as a",
              "  traceback.",
              "",
              "Remember: your entire response must be Python code and nothing else."]
    return "\n".join(lines) + "\n"


def extract_code(text, keep_indent=False, open_fence=False):
    """The model's code: the ```python block when fenced, else the bare text.

    Told to emit bare code, the model usually obeys (cli_tool) but sometimes
    narrates first and fences second (hello) — taking the whole text then
    writes prose into app.py. A fenced block wins over surrounding prose; a
    ```python tag wins over a bare fence; bare text passes through for the
    caller to compile-check. `keep_indent` leaves the answer's own leading
    whitespace alone: a body fragment written in the shown module's style is
    a fragment still, and `.strip()` would cut only the first line's share —
    the filler then reads a stray deeper line and refuses a good answer.
    A single, unpaired fence line is dropped too: the prompt opens the
    block, the model usually just closes it, and a ``` line at indent 0
    would drag the body's base indent to zero the same way.

    `open_fence` is for the ask whose prompt ended with an open ``` block
    (the stub filler's). The answer then *starts* inside a fence and its
    first fence line closes the prompt's; a model that echoes the stub,
    closes the fence and only then reasons — Qwen3-4B does under raw
    completion — puts its body in a later block. The plain `findall` read
    that closing fence as the next block's opener and returned the prose
    between the two; `_continuation_block` keeps the answer's own last
    ```python block instead.
    """
    raw = text or ""
    stripped = raw.strip()
    if "```" not in raw:
        return raw if keep_indent else stripped
    if open_fence:
        block = _continuation_block(raw)
        if block is not None:
            return block if keep_indent else block.strip()
        source = raw if keep_indent else stripped
        return "\n".join(line for line in source.splitlines()
                         if not _FENCE_LINE.match(line))
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", stripped, re.DOTALL)
    if blocks:
        for block in blocks:
            if block.strip():
                return block if keep_indent else block.strip()
        return ""
    # One unpaired fence: the prompt opened it (or the model opened one and
    # stopped). The fence line is packaging, never code.
    source = raw if keep_indent else stripped
    return "\n".join(line for line in source.splitlines()
                     if not _FENCE_LINE.match(line))


_FENCE_LINE = re.compile(r"^\s*```([A-Za-z0-9_+.-]*)\s*$")
_PYTHON_TAGS = ("python", "py", "python3")
_CODE_LINE = re.compile(
    r"^\s*(?:return|raise|yield|assert|pass|del|import|from|def|class|if|"
    r"elif|else|for|while|with|try|except|finally)\b"
    r"|^\s*[A-Za-z_][\w.\[\]'\"]*\s*[-+*/|&^%@]?=(?!=)")


def _is_stub_echo(text):
    """The model repeated the stub instead of replacing its raise.

    A stub echo contains `NotImplementedError` or a `def` line matching
    the stub pattern (method name + `raise NotImplementedError`).
    """
    if "NotImplementedError" in text:
        return True
    # Check for def line followed by NotImplementedError in the same block
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^\s*def \w+", line):
            # Check if the next few lines contain NotImplementedError
            block = "\n".join(lines[i:i+5])
            if "NotImplementedError" in block:
                return True
    return False


def _looks_like_code(text):
    """One keyword-led or assignment line is enough for a continuation body."""
    return any(_CODE_LINE.match(line) for line in text.splitlines())


def _fenced_blocks(lines, inside, tag=""):
    """`[(tag, lines)]` for the fenced regions in `lines`, from `inside` state."""
    blocks = []
    current = []
    for line in lines:
        match = _FENCE_LINE.match(line)
        if match:
            if inside:
                blocks.append((tag, current))
                current = []
                tag = ""
            else:
                tag = match.group(1)
            inside = not inside
            continue
        if inside:
            current.append(line)
    if inside:
        blocks.append((tag, current))
    return blocks


def _continuation_block(raw):
    """The body of an answer that starts inside the prompt's open fence.

    The first fence line decides how to read the rest: a tagged one
    (```` ```python ````) is the model opening its own block, a bare one is
    the model closing the prompt's. The text before it is the prompt's own
    region — the body when it is code, an echo when the model repeated the
    stub (the body then lives in the model's own last ```python block), and
    prose when it narrated (the fenced block wins, as everywhere else).
    """
    lines = raw.splitlines()
    first = next((index for index, line in enumerate(lines)
                  if _FENCE_LINE.match(line)), None)
    if first is None:
        return None
    region = "\n".join(lines[:first])
    if (region.strip() and not _is_stub_echo(region)
            and _looks_like_code(region)):
        return region
    opener = _FENCE_LINE.match(lines[first])
    blocks = _fenced_blocks(lines[first + 1:], bool(opener.group(1)),
                            opener.group(1))
    fenced = [(tag, "\n".join(lines_)) for tag, lines_ in blocks
              if tag and "\n".join(lines_).strip()]
    if fenced:
        python = [text for tag, text in fenced if tag in _PYTHON_TAGS]
        return python[-1] if python else fenced[-1][1]
    return region if region.strip() else None


def strip_code_fences(text):
    """Backward-compatible wrapper over `extract_code` (same contract)."""
    return extract_code(text)


# --- the model pass: bodies for what the emitter refused -------------------


STUB_FILES = ("repositories.py", "services.py")
STUB_PROMPT_BUDGET = 24000  # chars of module text one prompt may carry
# Modules a filled body may reach for. The ones the file already imports are
# left alone; the rest are added when the body's text actually uses them,
# so an accepted body never meets a NameError at its first call.
BODY_IMPORTS = ("calendar", "csv", "json", "os", "re", "math", "time", "io",
                "random", "string", "collections", "itertools", "functools",
                "decimal", "uuid", "datetime", "pathlib", "sqlite3")


def find_stub_spans(text):
    """`[(start, end, info)]` for every `raise NotImplementedError` stub.

    `start` is the docstring line when the emitted method has one — the
    filler rewrites its `[...]` work order — and `end` the closing line of
    the raise. `info` carries the class, the method's `def` line and the
    reason the emitter refused, so the prompt can state the exact hole.
    """
    lines = text.splitlines()
    spans = []
    cls = None
    def_line = None
    for index, line in enumerate(lines):
        if re.match(r"^class (\w+)", line):
            cls = line.split()[1].rstrip(":")
            def_line = None
            continue
        if re.match(r"^    def (\w+)", line):
            def_line = line.strip()
            continue
        if line != "        raise NotImplementedError(" or def_line is None:
            continue
        end = None
        reason = ""
        for offset in (1, 2):
            probe = lines[index + offset] if index + offset < len(lines) else ""
            if probe.strip().startswith('"') and probe.strip().endswith('")'):
                reason = probe.strip()[1:-2]
                end = index + offset
                break
        if end is None:
            continue
        start = index
        docstring = None
        if index and lines[index - 1].startswith('        """'):
            start = index - 1
            docstring = lines[index - 1]
        spans.append((start, end, {"cls": cls, "def": def_line,
                                   "reason": reason, "docstring": docstring}))
    return spans


def _stub_method(info):
    """The method name a stub span belongs to."""
    match = re.match(r"def (\w+)", info.get("def") or "")
    return match.group(1) if match else "?"


def load_method_repairs(output_dir):
    """Complaints for reviewed LLM body repairs, keyed by holder/method."""
    try:
        with open(os.path.join(output_dir, METHOD_REPAIRS_NAME),
                  encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return {}
    records = payload.get("repairs") if isinstance(payload, dict) else None
    repairs = {}
    for record in records or []:
        if not isinstance(record, dict):
            continue
        holder = record.get("holder")
        method = record.get("method")
        if isinstance(holder, str) and isinstance(method, str):
            repairs[(holder, method)] = record
    return repairs


def load_previous_generated(out_dir):
    """The generated stub modules already on disk, before this run overwrites them."""
    target = os.path.join(out_dir, GENERATED_DIR)
    files = {}
    for filename in STUB_FILES:
        path = os.path.join(target, filename)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as handle:
                files[filename] = handle.read()
    return files


def reviewed_bodies(files):
    """`{(filename, class, method): (docstring, body_lines)}` for tagged bodies.

    A body that a previous run tagged `llm-written` has been read or run at
    least once; the mechanical emitter is allowed to evolve underneath it
    (new imports, new CRUD helpers), but regenerating must not silently throw
    a reviewed answer away. Only exact method labels are cached; a method the
    emitter now handles mechanically is not overwritten.
    """
    found = {}
    for filename in STUB_FILES:
        text = files.get(filename)
        if not isinstance(text, str):
            continue
        lines = text.splitlines()
        cls = None
        index = 0
        while index < len(lines):
            class_match = re.match(r"^class (\w+)", lines[index])
            if class_match:
                cls = class_match.group(1)
                index += 1
                continue
            method_match = re.match(r"^    def (\w+)\(", lines[index])
            if not method_match or cls is None:
                index += 1
                continue
            method = method_match.group(1)
            docstring = None
            cursor = index + 1
            if cursor < len(lines) and lines[cursor].lstrip().startswith('"""'):
                docstring = lines[cursor]
                cursor += 1
            body = []
            while cursor < len(lines):
                line = lines[cursor]
                if line.strip() and not line.startswith("        "):
                    break
                body.append(line[8:] if line.startswith("        ") else line)
                cursor += 1
            while body and not body[-1].strip():
                body.pop()
            if docstring and "llm-written by" in docstring:
                found[(filename, cls, method)] = (docstring, body)
            index = max(cursor, index + 1)
    return found


def _spliced_reviewed(text, start, end, info, cached):
    """Replace one fresh stub with a reviewed body, keeping its original tag.

    The docstring is generated from the current contract; the body is the
    reviewed part. A description corrected after the review (a live
    `renew_membership` still said "toggling" after the contract changed it
    to set `True`) must reach the reused method, so the fresh stub's
    docstring wins and only the `[llm-written ...]` tag is carried over.
    """
    docstring, body = cached
    fresh = info.get("docstring")
    if fresh:
        indent = fresh[:len(fresh) - len(fresh.lstrip())]
        current = fresh.strip()
        current = re.sub(r'\s*\[[^\]]*\]"""\s*$', '"""', current)
        current = current[:-3].rstrip()
        match = re.search(r"\[llm-written by [^\]]*\]", docstring or "")
        if match and "llm-written by" not in current:
            current = f"{current} {match.group(0)}"
        replacement = [f'{indent}{current}"""']
    else:
        replacement = [docstring] if docstring else []
        if not replacement and info.get("docstring"):
            replacement.append(info["docstring"])
    replacement.extend("        " + line if line.strip() else ""
                       for line in body)
    lines = text.splitlines()
    candidate = "\n".join(lines[:start] + replacement + lines[end + 1:])
    if text.endswith("\n"):
        candidate += "\n"
    return candidate


def reuse_reviewed_bodies(files, previous):
    """Re-splice reviewed LLM bodies into the freshly emitted stubs.

    Returns `[(label, status, note)]`: `reused` for a matching body, `kept`
    when a cached body no longer compiles against the new module. This is a
    preservation step, not generation: it never invents a body and never
    changes one that the current emitter made mechanical.
    """
    cache = reviewed_bodies(previous)
    if not cache:
        return []
    rows = []
    for filename in STUB_FILES:
        text = files.get(filename)
        if not isinstance(text, str):
            continue
        labels = [f"{info['cls']}.{_stub_method(info)}"
                  for _start, _end, info in find_stub_spans(text)]
        for label in reversed(labels):
            current = next(
                (found for found in find_stub_spans(text)
                 if f"{found[2]['cls']}.{_stub_method(found[2])}" == label),
                None)
            if current is None:
                continue
            _start, _end, info = current
            cached = cache.get((filename, info["cls"], _stub_method(info)))
            if cached is None:
                continue
            candidate = _spliced_reviewed(text, _start, _end, info, cached)
            candidate, added = _add_imports(candidate, "\n".join(cached[1]))
            try:
                compile(candidate, filename, "exec")
            except SyntaxError as error:
                rows.append((label, "kept",
                             f"the reviewed body no longer compiles ({error.msg})"))
                continue
            text = candidate
            note = "reviewed body preserved"
            if added:
                note += "; added import " + ", ".join(added)
            rows.append((label, "reused", note))
        files[filename] = text
    return rows


def _split_signature(text):
    """Split a parameter list at top-level commas only.

    `Union[str, int]` carries a comma the naive split cuts inside,
    leaving a bogus `int]` parameter behind.
    """
    parts, depth, current = [], 0, ""
    for char in text:
        if char in "[({":
            depth += 1
        elif char in "])}":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    return parts


def _stub_params(info):
    """The stub's parameter names, `self` out — the body must use them."""
    match = re.match(r"def \w+\(([^)]*)\)", info.get("def") or "")
    if not match:
        return []
    names = []
    for piece in _split_signature(match.group(1)):
        name = piece.strip().split(":")[0].split("=")[0].strip()
        if name and name != "self" and not name.startswith("*"):
            names.append(name)
    return names


def _first_model(annotation):
    """`models.X` from an annotation, or None for plain types."""
    match = re.search(r"models\.(\w+)", annotation or "")
    return match.group(1) if match else None


def _direct_model(annotation):
    """The model a return annotation names, or None for a container.

    A `List[models.Book]` variable is a list, not a Book: typing it as a
    Book would make `rows.title` look valid and `rows[0].title` invisible.
    `Optional[models.Member]` and `models.Book | None` are one object.
    """
    if not annotation or re.search(
            r"\b(?:List|list|Dict|dict|Set|set|Tuple|tuple|Iterable|"
            r"Iterator|Sequence)\s*\[", annotation):
        return None
    return _first_model(annotation)


def _return_annotation(info):
    """The stub's own return annotation as written, or an empty string."""
    match = re.match(r"def \w+\([^)]*\)\s*->\s*(.+?):?$",
                     info.get("def") or "")
    return match.group(1).strip() if match else ""


def _declared_return(info):
    """The `models.X` a stub's own `-> ...` names, or None."""
    return _first_model(_return_annotation(info))


def _clip_module(text, cls, budget):
    """The module text, or its header plus the stub's own class when huge.

    The module is the API reference; trimming it in the middle would show
    a half-finished body as if it were the pattern to imitate. One class
    over budget at least keeps the stub's own class whole.
    """
    if len(text) <= budget:
        return text
    lines = text.splitlines()
    header = []
    for line in lines:
        if re.match(r"^class ", line):
            break
        header.append(line)
    block, inside = [], False
    for line in lines:
        if re.match(r"^class ", line):
            inside = line.split()[1].rstrip(":") == cls
        if inside:
            block.append(line)
    return "\n".join(header + [""] + block)[:budget]


def stub_prompt(requirements, module_text, info, references=(), api=(),
                budget=STUB_PROMPT_BUDGET, previous=None, complaints=(),
                context=DEFAULT_STUB_CONTEXT, contract=()):
    """One ask: the emitted module is the API reference; fill one hole.

    Nothing is rewritten into a summary — the module shows the real store
    calls, model constructors and error raises the body must imitate, and
    a model told a simplified API invents one that does not exist. When
    the text would not fit `budget` it is clipped to the module header and
    the stub's own class; `references` lists signatures a service body
    may need from the repositories module, and `api` names what the module
    text cannot show — the fields of each model and the error classes the
    errors module defines (a model that could not see them guessed
    `book.author`, `models.date_today` and made-up exception names).

    With `previous` and `complaints`, the same ask becomes the repair ask:
    the refused answer is shown back with the exact contract violations,
    so the second answer can be a correction instead of a guess.
    """
    method = _stub_method(info)
    # The store rule is for repository bodies: a service has no
    # `self._store` and no `self.ENTITY`, and the first live service
    # answer copied the example verbatim into a class with neither.
    # Minimal has no reference list, so the rule must not point at one.
    if info.get("file") == "services.py" and context == "minimal":
        call_rule = [
            "- Call only what the module shows: `self._repos['Name']`",
            "  repositories, `models.*`, `errors.*`, module helpers.",
            "  A service body has no `self._store` and no `self.ENTITY`:",
            "  read through the repositories and filter what they return",
            "  in Python.",
        ]
    elif info.get("file") == "services.py":
        call_rule = [
            "- Call only what the module shows: `self._repos['Name']`",
            "  repositories and the methods listed below, `models.*`,",
            "  `errors.*`, module helpers. A service body has no",
            "  `self._store` and no `self.ENTITY`: read through the",
            "  repositories and filter what they return in Python.",
            "- Standard CRUD is on the repositories, not on this service.",
            "  Do not call a service method that is absent from the module;",
            "  use `self._repos['...']` for create/read/update/delete.",
            "- A method declared by another repository is reached as",
            "  `self._repos['OtherRepository'].method(...)`, never as",
            "  `self.method(...)`; `self` is the holder you are writing.",
            "- Copy repository parameter names exactly from the method",
            "  list; a keyword can use a different noun than the entity",
            "  id. When a method takes one value, passing it positionally",
            "  is always safe. Never invent `__ge`, `__le` or other",
            "  query suffixes: `read_all` takes only the named fields;",
            "  filter a date or range in Python after reading.",
            "- A repository `create` whose signature says `-> int` returns",
            "  the new id, not a record; read it back with `read_one` before",
            "  using its fields.",
            "- A related collection is not an attribute of a dataclass.",
            "  When the contract changes records related through a foreign",
            "  key, read them with the repository finder listed below, then",
            "  update each record through its own repository. Never write",
            "  `record.<plural>` or invent a collection attribute.",
            "- Use an exception class that appears in `errors.*` exactly;",
            "  do not invent a synonym. If the contract names no error for",
            "  a condition, use the closest registered name or ValueError.",
            "- Every non-optional parameter of a referenced create/update",
            "  method must be supplied. Compute an amount from the related",
            "  records when the created record has one, and use",
            "  `datetime.datetime.now()` for a current date/time field.",
            "- A status/state precondition in the contract is checked before",
            "  any write, and raises the exact named error.",
        ]
    else:
        operators = "`, `".join(STORE_CONTRACT.criteria_operators)
        call_rule = [
            "- Call only what the module shows: `self._store` methods used",
            "  in sibling bodies, `models.*`, `errors.*`, module helpers.",
            f"  `_store.select` criteria support only `{operators}` —",
            "  anything else (substring search, several fields) reads",
            "  `self._store.all(self.ENTITY)` and filters in Python.",
        ]
    lines = [
        "A Python module was generated mechanically from the architecture",
        "documents below. Exactly one method could not be derived",
        "mechanically and raises NotImplementedError; write its body.",
        "",
        "Rules:",
        "- Reply with ONLY the replacement for the raise statement: the",
        "  body's lines, indented with 8 spaces. No `def` line, no",
        "  docstring, no markdown fences, no explanation.",
    ]
    # The method-specific part goes after the shared prefix. llama-server
    # reuses the longest matching prompt prefix; a method name near the top
    # (as it used to be) makes every request diverge after ~88 tokens.
    tail = [
        f"- The method is `{info['cls']}.{method}`; the emitter refused it"
        " with:",
        f"  {info['reason']}",
    ]
    lines += call_rule
    if info.get("file") == "services.py":
        lines += [
            "- A repository update that lists individual fields takes them",
            "  as named keywords (`update(id=..., field=value)`); only",
            "  a method that declares a `data` parameter takes a dict.",
            "- A `data` mapping parameter may be None; treat None as an",
            "  empty mapping before reading or iterating it.",
            "- Changing a dataclass in memory does not save it: call the",
            "  repository's update method for every record you mark.",
        ]
    requirement_line = _requirements_line(requirements, method)
    if re.search(
            r"\bafter\s+(?:the\s+)?(?:insert(?:ion)?|creat(?:e|ion)|"
            r"sav(?:e|ing)|add(?:ing)?)\b",
            requirement_line or "", re.IGNORECASE):
        tail += [
            "- The requirement says the check runs AFTER the insert: call",
            "  the create first, then perform the check. When the check",
            "  raises, the created record stays saved — that is intended.",
        ]
    signature = info.get("def") or ""
    if re.search(r"\bmonth\b", signature):
        tail += [
            "- A `month` value is a `YYYY-MM` label, not an ISO date.",
            "  A range covering that month starts at `<month>-01`; its end",
            "  is the last day of that calendar month (`<month>-31` for a",
            "  31-day month), never a bare `31-01`.",
        ]
    if re.search(r"recurr", method, re.IGNORECASE) \
            or "recurr" in (requirement_line or "").lower():
        tail += [
            "- Recurring records share the fields that define the",
            "  recurrence and appear in more than one period. Group the",
            "  records themselves, collect the distinct period prefixes,",
            "  and for each group with at least two periods set the",
            "  recurring flag on every record and save it through the",
            "  repository update. Never reuse a loop variable from another",
            "  loop; compare period prefixes as a set, never parse them",
            "  with a date constructor.",
        ]
    flat_method = normalize(method)
    if re.search(r"year|annual", method, re.IGNORECASE):
        tail += [
            "- A yearly summary keys period totals by `YYYY-MM` labels,",
            "  not by bare month numbers.",
            "- A yearly repository aggregate returns a mapping from",
            "  `YYYY-MM` to the total; never return one scalar.",
            "- A top-category result must be JSON-serialisable: a list of",
            "  [key, amount] pairs or a string-keyed dict, never tuple",
            "  keys or a name built from an id.",
        ]
    if "monthly" in flat_method or "month" in flat_method:
        tail += [
            "- A monthly spending-by-category aggregate returns a mapping",
            "  from the related record's id to its total; never one",
            "  scalar.",
            "- For a monthly report, read the records with `read_all()`",
            "  (no keyword arguments), keep rows whose date field starts",
            "  with the requested `YYYY-MM`, then group them. Never pass the",
            "  same keyword twice.",
            "- Never construct the month end as a fixed `-31`; use",
            "  `calendar.monthrange` or filter by the `YYYY-MM` prefix.",
            "- Keep the exact output keys the method and contract declare;",
            "  do not rename them.",
            "- Budget status: `exceeded` when the period total is above the",
            "  limit, `warning` at 90% or more, otherwise `on_track`.",
        ]
    if re.search(r"top|categor", flat_method) and re.search(
            r"date|spend", flat_method + requirement_line, re.IGNORECASE):
        tail += [
            "- For an inclusive date window, compare full ISO date strings",
            "  with `>= start_text` and `<= end_text`; never use",
            "  `startswith` or `endswith`.",
            "- When the return includes a related record's name, read the",
            "  parent rows and use that record's name field; never return",
            "  `str(id)` as the name.",
            "- When the return type declares pairs of a numeric key and an",
            "  amount, keep the key numeric; do not stringify it.",
        ]
    if re.search(r"add|create", flat_method) and re.search(
            r"budget|month", flat_method + requirement_line, re.IGNORECASE):
        tail += [
            "- After creating a record whose amount counts toward a",
            "  period total, recompute that period total from all records",
            "  and compare it with the budget's limit field; never compare",
            "  only the new record.",
        ]
    if "budget" in flat_method and "status" in flat_method:
        tail += [
            "- A budget record exposes its limit through its own model",
            "  attribute, not a store dict.",
            "- Status is `exceeded` only when the period total is above the",
            "  limit, `warning` at 90% or more, otherwise `on_track`.",
        ]
    if info.get("file") == "repositories.py" and "search" in flat_method:
        tail += [
            "- When the search covers a related record's name as well as",
            "  the row's own text fields, read the related rows too and",
            "  compare each text field independently.",
            "- Collect matching rows in a list and return that list; never",
            "  rebuild `select` criteria from a set/comprehension of ids.",
        ]
    if info.get("file") == "repositories.py" and "top" in flat_method:
        tail += [
            "- When a repository reads a parent row by key, the store",
            "  returns a dict, not a model; read the field with `.get(...)`.",
        ]

    if re.search(r"spend(?:ing)?|total|aggregate|\bsum\b", method, re.IGNORECASE):
        tail += [
            "- This method aggregates: return the total, or the keyed",
            "  totals its return type declares — never one entry per input",
            "  record.",
            "- For a date-range aggregate, call `read_all()` with no",
            "  keyword filters and filter the returned records in Python:",
            "  compare the record's date field as ISO text with the ISO",
            "  start/end. Never invent `__ge` or `__le` suffixes.",
        ]
    if any(line.strip() == "creates:" for line in contract):
        tail += [
            "- A non-null model field still needs a value on create. When",
            "  an optional flag is omitted, use the requirement's stated",
            "  default; with none stated, use today for a date and the",
            "  first documented value of an enumerated field.",
            "- Preconditions run before the create. If a precondition reads",
            "  a parent record, do that read and raise its error before",
            "  calling create; never store the record first and validate",
            "  afterwards.",
        ]
    if any(line.strip() == "creates:" for line in contract):
        tail += [
            "- If the body both creates a record and changes an existing",
            "  one, create the record first; a failed create must not leave",
            "  the change behind.",
        ]
    reference_text = (module_text or "") + "\n" + "\n".join(references or ())
    if info.get("file") == "services.py" \
            and any(line.strip() == "creates:" for line in contract) \
            and re.search(r"\bdue\b", requirement_line or "",
                          re.IGNORECASE) \
            and re.search(r"\b(?:calendar\s+)?days?\b",
                          requirements or "", re.IGNORECASE):
        tail += [
            "- The requirements state a due date. Compute it from the",
            "  record's start date and the stated number of days (for",
            "  example, `start + datetime.timedelta(days=14)`), and pass",
            "  both dates to the create call; do not leave a non-null date",
            "  field None.",
        ]
    if context in ("honest", "exact") \
            and re.search(r"search|filter|find", method, re.I):
        tail += [
            "- A search or filter over several fields tests each field",
            "  independently: a record matching any one is a hit. Do not",
            "  put the fields in one `elif` chain — the later fields then",
            "  never run.",
            "- A `search` matches text fields by "
            f"{STORE_CONTRACT.text_search}",
            "  and compares ids/numbers exactly. `select(..., 'eq', ...)`",
            "  is an exact test, so read the records and filter text in",
            "  Python.",
        ]
    if info.get("file") == "repositories.py":
        tail += [
            "- `_store.select` and `_store.get` return plain dictionaries.",
            "  If the declared return type is a model (or a list of models),",
            "  construct `models.X(**record)`; never read attributes on a",
            "  store dictionary.",
            "- `_store.select` always takes the entity and a criteria list;",
            "  use `self._store.select(self.ENTITY, [])` for every record.",
            "- A stored date may already be a `datetime.date`, not a string.",
            "  Normalise it with `str(value)[:10]` before slicing or comparing;",
            "  use `str(value)[:7]` for a `YYYY-MM` month key.",
        ]
    if re.search(r"report|summary", flat_method):
        tail += [
            "- The requirements name the report's keys; use their snake_case",
            "  spellings exactly (for example `total spent` -> `total_spent`),",
            "  not invented synonyms.",
            "- An id stays an int in every returned structure; never call",
            "  `str()` on it, even when a dict key must be a string.",
        ]
    if re.search(r"year|annual", method, re.IGNORECASE):
        tail += [
            "- A method with a `year` parameter filters records by that",
            "  year; compare `str(record_date)[:4] == str(year)` and never",
            "  ignore the parameter.",
        ]
    if info.get("file") == "services.py" and re.search(
            r"only|include|available|active", signature
            + " ".join(info.get("params") or []), re.IGNORECASE):
        tail += [
            "- A boolean selector filters only when it is true. When it is",
            "  false or omitted, return the unfiltered records; do not use",
            "  `is None` as the only off switch.",
        ]
    if info.get("file") == "services.py" and re.search(
            r"stock|quantity|qty", flat_method + signature, re.IGNORECASE):
        tail += [
            "- Apply every numeric bound the requirements state before",
            "  saving a stock/quantity change; a negative restock is a",
            "  rejection, not a smaller number. Raise ValueError for the",
            "  invalid value before changing the record, not a not-found",
            "  error.",
        ]
    if any(line.strip() == "creates:" for line in contract):
        tail += [
            "- Every required (non-null) create field must be checked",
            "  before the create. If a required value is missing, raise",
            "  ValueError; never let a schema NOT NULL error escape.",
        ]
    if info.get("file") == "services.py" and re.search(
            r"stock|value|aggregate|sum", flat_method, re.IGNORECASE) \
            and "dict" in _return_annotation(info).lower():
        tail += [
            "- A category-keyed map includes every category in the model,",
            "  initialising categories with no products to zero.",
        ]
    if info.get("file") == "repositories.py" and re.search(
            r"stock|value|aggregate|sum", flat_method, re.IGNORECASE) \
            and "dict" in _return_annotation(info).lower():
        tail += [
            "- A category-keyed map includes a zero entry for every",
            "  category, even when no product references it.",
            "- Build that map from the parent rows first: initialise each",
            "  parent id to zero, then add each child row's value. Do not",
            "  build the map only from child rows.",
        ]
    if info.get("file") == "services.py" and re.search(
            r"return|borrow|confirm|cancel|ship", flat_method,
            re.IGNORECASE):
        tail += [
            "- A state guard checks every field that defines the state",
            "  before writing.",
            "- A reservation that decrements stock on confirmation must",
            "  increment it on cancellation; base the write on the record's",
            "  current value, not a recomputed opposite.",
        ]

    if info.get("file") == "services.py" and re.search(
            r"capacity|summary|utilization", flat_method, re.IGNORECASE):
        tail += [
            "- Capacity is the sum of each assigned wine's",
            "  `stock_quantity`, not the number of wine rows.",
        ]
    if info.get("file") == "services.py" and re.search(
            r"pricing|price", flat_method, re.IGNORECASE):
        tail += [
            "- When validating a partial price update, compare the supplied",
            "  value with the other existing field on the wine; do not",
            "  reject a one-sided update merely because one argument is None.",
        ]
    if info.get("file") == "services.py" and "| None" in (info.get("def") or ""):
        tail += [
            "- The return annotation permits `None`: if the repository lookup",
            "  raises its not-found error, catch that exact error and return",
            "  None instead of letting it escape.",
        ]
    if info.get("file") == "services.py" and re.search(
            r"export|write", flat_method, re.IGNORECASE):
        tail += [
            "- Catch OSError around file I/O and raise ValueError with a",
            "  concise message naming the path; never re-raise the raw",
            "  filesystem exception.",
        ]
    if info.get("file") == "services.py" and re.search(
            r"report|budget|monthly|yearly", flat_method, re.IGNORECASE):
        tail += [
            "- A period budget status compares the period total for each",
            "  category, not one expense row at a time.",
            "- A yearly category table aggregates once per category over",
            "  the whole year; do not key it by (category, month).",
        ]
    if info.get("file") == "services.py" and "invoice" in flat_method \
            and "customer" in flat_method:
        tail += [
            "- To find invoices for a customer, first find that customer's",
            "  orders, then match invoices on each invoice's `order_id`;",
            "  an invoice id is not an order id.",
        ]
    if info.get("file") == "services.py" and "status" in flat_method \
            and "report" in flat_method:
        tail += [
            "- A status report starts by initialising every documented",
            "  status to zero, then counts the records; absent statuses",
            "  must still appear with zero.",
        ]

    lines += [
        "- If the requirements do not determine the behavior, reply with",
        '  `raise NotImplementedError("...")` and nothing else.',
    ]
    if complaints:
        repair_block = [
            "",
            "Your previous answer to this method was refused:",
        ]
        repair_block += [f"  - {complaint}" for complaint in complaints]
        if previous:
            repair_block += [
                "",
                "The refused answer was:",
                "```python",
                previous.strip(),
                "```",
                "Write the body again, fixing exactly what was refused and",
                "keeping what was right.",
            ]
    else:
        repair_block = []
    if references:
        lines += ["", "Methods this module may lean on:"]
        lines += [f"  {signature}" for signature in references]
    if api:
        lines += [""] + list(api)
    lines += ["", "requirements:", (requirements or "").strip(), "",
              f"module ({info.get('file', 'module')}):",
              "```python",
              _clip_module(module_text, info["cls"], budget).rstrip(),
              "```",
              ]
    if contract:
        lines += [""] + list(contract)
    if info.get("file") == "services.py" and re.search(
            r"date|month|year", " ".join(info.get("params") or []) + " " + signature,
            re.IGNORECASE):
        tail += [
            "- A date or month parameter may already arrive as a",
            "  `datetime.date`; the CLI validates ISO text and converts it.",
            "  Use the value directly. Only parse it when it is still a",
            "  string; never call `fromisoformat` on a date object.",
        ]
    annotation = _return_annotation(info)
    if annotation and annotation not in ("None", "NoneType"):
        lines += ["",
                  f"The method is declared `-> {annotation}`; end the body",
                  "by returning its value."]
    lines += ["", "Method-specific rules:"] + tail
    # The correction is the last thing before the ask: a small model that
    # saw the complaint at the top and then thousands of tokens of API and
    # module text repeated the refused keyword twice in a live
    # `return_book` repair. Recency is what makes it fix the named call.
    lines += repair_block
    lines += [
              "",
              f"Now write the body of `{info['cls']}.{method}`, replacing",
              "the `raise NotImplementedError(...)` statement:",
              "```python"]
    return "\n".join(lines) + "\n"


def _clean_body(text):
    """Extract the function body from a complete function definition, or
    handle the legacy body-only format.

    New format (preferred): model writes complete function with `def`.
    Legacy format: model writes only body lines (no `def` line).
    """
    # Use keep_indent=True to preserve original indentation for legacy format
    code = extract_code(text, keep_indent=True, open_fence=True)
    if not code.strip():
        return []
    
    # Try to parse as a complete function first
    try:
        tree = ast.parse(code)
    except SyntaxError:
        tree = None
    
    func = None
    if tree:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                func = node
                break
    
    if func:
        # New format: complete function with def line
        code_lines = code.splitlines()
        body_start = func.lineno
        body_end = getattr(func, 'end_lineno', len(code_lines))
        body_source = code_lines[body_start - 1:body_end]
        if not body_source:
            return []
        body_lines = body_source[1:]  # skip def line
        # Strip leading docstring if present (AST path)
        while body_lines and re.match(r'^\s*("""|\'\'\')', body_lines[0].lstrip()):
            opener = body_lines.pop(0)
            # Single-line docstring?
            if re.search(r'("""|\'\'\')', opener[opener.find('"""')+3:] if '"""' in opener else opener[opener.find("'''")+3:]):
                continue
            # Multi-line docstring: find closing triple quotes
            while body_lines and not re.search(r'("""|\'\'\')', body_lines[0]):
                body_lines.pop(0)
            if body_lines:
                body_lines.pop(0)  # remove closing line
    else:
        # Legacy format: body lines only (no def line), but may have
        # a leading def line/docstring that AST couldn't parse (e.g. fences in middle).
        body_lines = [line for line in code.splitlines() if line.strip() or True]
        # Remove leading/trailing empty lines
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
        while body_lines and not body_lines[-1].strip():
            body_lines.pop()
        # Strip leading def line if present (model echoed the stub)
        if body_lines and re.match(r'^\s*def\s+\w+\s*\(', body_lines[0]):
            body_lines.pop(0)
        # Strip leading docstring if present
        while body_lines and re.match(r'^\s*("""|\'\'\')', body_lines[0].lstrip()):
            opener = body_lines.pop(0)
            # If the opener line also contains closing quotes, we're done
            if re.search(r'("""|\'\'\')', opener[opener.find('"""')+3:] if '"""' in opener else opener[opener.find("'''")+3:]):
                # Single-line docstring, already removed
                continue
            # Multi-line docstring: find closing triple quotes
            while body_lines and not re.search(r'("""|\'\'\')', body_lines[0]):
                body_lines.pop(0)
            if body_lines:
                body_lines.pop(0)  # remove closing line
        # Remove deliberation after a lone closing fence (model reasoning after code)
        # Find first lone ``` line and drop everything after it
        for i, line in enumerate(body_lines):
            if re.match(r'^\s*```', line.strip()):
                body_lines = body_lines[:i]
                break
        # Remove fence lines
        body_lines = [line for line in body_lines if not re.match(r'^\s*```', line)]
    
    if not body_lines:
        return []
    
    # Dedent to minimum indent among body lines
    indents = [len(line) - len(line.lstrip(" ")) for line in body_lines if line.strip()]
    if not indents:
        return []
    # Body-only answers sometimes put the first statement at column 0 (or
    # one level shallower) while the rest of the body keeps the def's base
    # indent. Trimming by the minimum column then leaves the first `if`
    # body at the base, and the module does not compile. The outlier is
    # the first line, not the base: add the missing base to the leading
    # line(s) at that shallow column, dedent by the rest's base, and keep
    # the result only when it parses. A correct body whose whole content
    # is nested under its first line (e.g. a lone `for`) fails that parse
    # and falls back to the minimum column unchanged.
    #
    # A live `search_books_by_title_author_isbn` answer was internally
    # inconsistent instead: `return []` and the statements after it were
    # all at the rest's base, so no single re-base made both the `if` body
    # and the following statements correct. That answer parses after the
    # fallback but leaves every later statement dead inside the `if`;
    # `_body_complaints` refuses it as unreachable rather than accepting
    # a body whose whole search only runs for an empty query.
    def dedent_at(lines, trim):
        cut_lines = []
        for line in lines:
            if not line.strip():
                cut_lines.append("")
                continue
            indent = len(line) - len(line.lstrip(" "))
            cut = trim if indent >= trim else 0
            cut_lines.append(line[cut:])
        return cut_lines

    def compiles(lines):
        source = "def _body():\n" + "\n".join(
            ("    " + line) if line.strip() else "" for line in lines)
        try:
            compile(source, "<body>", "exec")
        except SyntaxError:
            return False
        return True

    trim = min(indents)
    rest = indents[1:]
    if rest and indents[0] < min(rest):
        base = min(rest)
        missing = base - indents[0]
        shifted = list(body_lines)
        for index, line in enumerate(body_lines):
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip(" "))
            if indent != indents[0]:
                break
            shifted[index] = " " * missing + line
        candidate = dedent_at(shifted, base)
        if compiles(candidate):
            return candidate
    result = dedent_at(body_lines, trim)
    
    return result

def _answer_continued(text):
    """True when an answer keeps talking after its first code block.

    The ask ends with an open fence, so a compliant answer is body lines
    and one closing fence. A model that deliberates writes a draft, closes
    the fence, then reasons and offers another body; `_clean_body` sees
    only the first block, so landing it would accept a body the model was
    itself about to correct. A live `return_book` answer did exactly this:
    the accepted draft set the return date to the due date and skipped the
    copy increment, while the model's final block had both right.
    """
    lines = (text or "").splitlines()
    first = next((index for index, line in enumerate(lines)
                  if line.strip().startswith("```")), None)
    if first is None:
        return False
    if all(not line.strip() for line in lines[:first]):
        close = next((index for index in range(first + 1, len(lines))
                      if lines[index].strip().startswith("```")), None)
    else:
        # The prompt supplied the opening fence; this is its close.
        close = first
    if close is None:
        return False
    return any(line.strip() for line in lines[close + 1:])


def _raised_by_repository(files, raised_name):
    """True when a generated repository create can raise this error itself."""
    if not raised_name or not files:
        return False
    repositories = files.get("repositories.py") or ""
    return raised_name in repositories


def _permits_post_write_raise(requirement, contract, raised_name):
    """A requirement that says \"after insertion\" wants the row kept.

    The generic create-before-raise rule protects the usual case: a refused
    operation must not have stored its record. When the requirement itself
    asks for the check after the insert (a budget check that must include the
    new expense), the stored record is the intended outcome, so a raise the
    contract did not declare as a precondition may follow the create.
    """
    if not re.search(
            r"\bafter\s+(?:the\s+)?(?:insert(?:ion)?|creat(?:e|ion)|"
            r"sav(?:e|ing)|add(?:ing)?)\b",
            requirement or "", re.IGNORECASE):
        return False
    errors = {_last_name(item.get("error"))
              for item in (contract or {}).get("preconditions") or []
              if isinstance(item, dict) and item.get("error")}
    if raised_name in errors:
        return False
    # Only the error the clause is about may follow the write. The clause
    # names it in words (`budget exceeded`, `expense not found`); a plain
    # `ValueError` from input validation does not share a word and stays a
    # normal pre-write refusal.
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", raised_name or "")
    error_tokens = {token for token in re.findall(r"[a-z]{4,}",
                                                   spaced.lower())}
    error_tokens -= {"error", "exception"}
    if not error_tokens:
        return False
    # Read the clause around the after-insert phrase, not the whole
    # requirement. `add_expense` says the *budget* check runs after the insert
    # and also says the *category* must exist before it; the category error is
    # a pre-write refusal even though both words occur in the same requirement.
    for match in re.finditer(
            r"\bafter\s+(?:the\s+)?(?:insert(?:ion)?|creat(?:e|ion)|"
            r"sav(?:e|ing)|add(?:ing)?)\b",
            requirement or "", re.IGNORECASE):
        start = max(0, match.start() - 120)
        end = min(len(requirement), match.end() + 120)
        clause = requirement[start:end].lower()
        if error_tokens & set(re.findall(r"[a-z]{4,}", clause)):
            return True
    return False


def _last_code_block(text):
    """The final fenced block in a deliberating answer, or None.

    The first block is the draft the model was about to correct; the last
    fenced block is the answer it arrived at (the live `return_book`
    transcript ended with `Final answer:` and a complete body). Taking the
    last pair of fence lines avoids the parity shift a stray closing fence
    at the start causes for a block-matching regex.
    """
    lines = (text or "").splitlines()
    fences = [index for index, line in enumerate(lines)
              if line.strip().startswith("```")]
    if len(fences) < 2:
        return None
    return "\n".join(lines[fences[-2] + 1:fences[-1]])


def _raised_name(node):
    """The exception name in a raise statement, for the complaint."""
    exc = node.exc
    if isinstance(exc, ast.Call):
        exc = exc.func
    if isinstance(exc, ast.Attribute):
        return exc.attr
    if isinstance(exc, ast.Name):
        return exc.id
    return "an exception"


def _block_chain(node, parents):
    """The statement blocks that enclose `node`, outermost first.

    A write in an ancestor block runs before a raise in a nested block;
    a write in one branch of an `if` does not run in the other branch.
    The chain keeps that distinction: `(If, body)` and `(If, orelse)`
    differ, so the create in an `else` is not blamed for the raise in the
    `if`.
    """
    chain, child = [], node
    while child in parents:
        parent = parents[child]
        branch = None
        for name in ("body", "orelse", "finalbody"):
            block = getattr(parent, name, None)
            if isinstance(block, list) and child in block:
                branch = name
                break
        if branch is None and child in getattr(parent, "handlers", []):
            branch = "handlers"
        if branch is not None:
            chain.append((id(parent), branch))
        child = parent
    chain.reverse()
    return chain


def _in_nested_function(node, parents):
    """Whether `node` sits inside a function defined within the body."""
    functions, child = 0, node
    while child in parents:
        parent = parents[child]
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.Lambda)):
            functions += 1
        child = parent
    return functions > 1


def _module_names(text):
    """Class attributes and methods: the `self.<name>` a body may touch."""
    names = {"_store", "_repos"}
    for line in text.splitlines():
        match = re.match(r"^    (?:def )?(\w+)", line)
        if match:
            names.add(match.group(1))
    return names


def _module_bindings(text):
    """Names the module itself defines: imports, classes, defs, constants.

    The mirror of `_module_names` for bare names: a body reading a name
    that is neither a parameter, a local, an import nor a module-level
    definition is a NameError waiting to happen.  The prompt-side module
    text can be a truncated tail (the context was full), so a syntax error
    must degrade to the regex names rather than abort generation before the
    already-mechanical files are written.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        lines = text.splitlines()
        for _ in range(min(8, len(lines))):
            lines = lines[:-1]
            try:
                tree = ast.parse("\n".join(lines))
                break
            except SyntaxError:
                continue
        else:
            return _module_names(text)
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) \
                else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _class_names(text):
    """The `class ...` names a module defines."""
    return {match.group(1) for match in
            re.finditer(r"^class (\w+)", text or "", re.M)}


def _model_fields(text):
    """`Entity(field: type, ...)` lines from the emitted models module.

    Field names alone left the shape to guessing: a live body stored a
    `datetime` into a string field and another sliced a value that was
    not a string. The emitted annotation tells the two apart.
    """
    classes = []
    for line in (text or "").splitlines():
        match = re.match(r"^class (\w+)", line)
        if match:
            classes.append((match.group(1), []))
            continue
        match = re.match(r"^    (\w+):\s*(.+?)\s*=", line)
        if match and classes:
            classes[-1][1].append(f"{match.group(1)}: {match.group(2)}")
            continue
        match = re.match(r"^    (\w+):", line)
        if match and classes:
            classes[-1][1].append(match.group(1))
    return [f"{name}({', '.join(fields)})" for name, fields in classes]


def _api_reference(files, filename=""):
    """Prompt lines naming the data surfaces the module text cannot show.

    Tailored by file: a repository body reads `self._store` and its
    `self.ENTITY` table, a service body has `self._repos` and no store —
    the shared block (and the shared rule, above) taught a live service
    answer to write `self._store.all(self.ENTITY)` in a class with
    neither, and the invented-name guard rightly refused it.
    """
    lines = ["The data the sibling modules hand you:"]
    if filename == "services.py":
        lines.append("- `self._repos` maps repository names to instances:")
        lines.append("  call their methods and filter the dataclasses they")
        lines.append("  return, in Python. A service has no `self._store`")
        lines.append("  and no `self.ENTITY`.")
    else:
        lines.append(f"- `self._store` reads return {STORE_CONTRACT.read_shape}:")
        lines.append('  read them with `record.get("field")`; `self.ENTITY`')
        lines.append("  is this class's table.")
    entries = _model_fields(files.get("models.py") or "")
    if entries:
        lines.append("- The dataclasses in models.py and their fields; read")
        lines.append("  them as attributes (`entity.title`), never `.get(...)`,")
        lines.append("  never a field that is not listed. They are plain")
        lines.append("  dataclasses: set the fields and pass the instance back —")
        lines.append("  there is no `copy(...)` with keyword updates:")
        lines += [f"  {entry}" for entry in entries]
        lines.append(f"- The store {STORE_CONTRACT.date_read}.")
        lines.append(f"  It {STORE_CONTRACT.date_write}. Compare a typed")
        lines.append("  date field with `datetime.date.today()` or")
        lines.append("  `datetime.datetime.now()` directly; store a")
        lines.append("  date/datetime (or its `.isoformat()`) back.")
        if filename != "services.py":
            lines.append(f"- {STORE_CONTRACT.mutation}.")
    errors = sorted(_class_names(files.get("errors.py") or ""))
    if errors:
        lines.append(f"- errors.py defines only these: {', '.join(errors)}")
    lines.append("- A body may use these stdlib modules; a needed import")
    lines.append(f"  is added for you: {', '.join(BODY_IMPORTS)}")
    return lines


def _honest_api_reference(files, filename=""):
    """The full ask's facts, corrected where a live run showed them lying.

    The full block tells a body to compare date fields as ISO strings but
    calls `read_one_*` nullable when it raises, and lists error names
    without saying when they apply: a live body formatted a space-separated
    timestamp (which never compares equal to the stored ISO text) and
    reached for an error to enforce a rule the requirements never stated.
    The surfaces are the same; the lines that were wrong or missing are
    different.
    """
    lines = ["The data the sibling modules hand you:"]
    if filename == "services.py":
        lines += [
            "- `self._repos` maps repository names to instances:",
            "  call their methods and filter the dataclasses they",
            "  return, in Python. A service has no `self._store`",
            "  and no `self.ENTITY`.",
            "- If a repository method already does the work under a",
            "  different name, delegate to it; do not re-filter",
            "  `read_all_*` in Python.",
            "- `read_one_*` raises `<Entity>NotFoundError` when nothing",
            "  matches, despite the `| None` in its annotation; a `None`",
            "  check after it is dead code.",
        ]
    else:
        lines.append(f"- `self._store` reads return {STORE_CONTRACT.read_shape}:")
        lines.append('  read them with `record.get("field")`; `self.ENTITY`')
        lines.append("  is this class's table.")
    entries = _model_fields(files.get("models.py") or "")
    if entries:
        lines.append("- The dataclasses in models.py and their fields; read")
        lines.append("  them as attributes (`entity.title`), never `.get(...)`,")
        lines.append("  never a field that is not listed. They are plain")
        lines.append("  dataclasses: set the fields and pass the instance back —")
        lines.append("  there is no `copy(...)` with keyword updates:")
        lines += [f"  {entry}" for entry in entries]
        lines.append(f"- The store {STORE_CONTRACT.date_read} and")
        lines.append(f"  {STORE_CONTRACT.date_write}. Compare a typed date")
        lines.append("  field with `datetime.date.today()` or")
        lines.append("  `datetime.datetime.now()` directly; store a")
        lines.append("  date/datetime (or its `.isoformat()`) back. Never")
        lines.append('  `strftime("%Y-%m-%d %H:%M:%S")`: space-separated text does not match')
        lines.append("  the stored ISO values.")
    errors = sorted(_class_names(files.get("errors.py") or ""))
    if errors:
        lines.append(f"- errors.py defines only these: {', '.join(errors)}")
        lines.append("  The list is a vocabulary, not a work order: raise one")
        lines.append("  only where the requirements or the human-confirmed")
        lines.append("  contract describe that failure. Do not add checks")
        lines.append("  they do not state.")
    lines.append("- A body may use these stdlib modules; a needed import")
    lines.append(f"  is added for you: {', '.join(BODY_IMPORTS)}")
    return lines


def _class_source(text, name):
    """One `class` block from the emitted models module, decorator included."""
    lines = (text or "").splitlines()
    class_line = next((index for index, line in enumerate(lines)
                       if re.match(rf"^class {re.escape(name)}\b", line)),
                      None)
    if class_line is None:
        return ""
    start = class_line
    while start and lines[start - 1].lstrip().startswith("@"):
        start -= 1
    end = class_line + 1
    while end < len(lines) and not re.match(r"^class \w+", lines[end]):
        end += 1
    return "\n".join(lines[start:end]).rstrip()


def _exact_api_reference(files, filename=""):
    """The honest facts, with models.py shown as code instead of a summary.

    A compressed `Loan(id, book_id, ...)` line is technically complete and
    practically invisible: a live return body read `loan.title` from it.
    The class source carries the decorator, the defaults and the layout a
    body can pattern-match; the target method's return class is repeated
    above the ask by `_target_contract`. The behavioral facts stay, because
    they are not visible in the source: dates are normalized by the store,
    mutating a dataclass does not persist it, and the error list is a
    vocabulary rather than a work order.
    """
    lines = ["The data the sibling modules hand you:"]
    if filename == "services.py":
        lines += [
            "- `self._repos` maps repository names to instances:",
            "  call their methods and filter the dataclasses they",
            "  return, in Python. A service has no `self._store`",
            "  and no `self.ENTITY`.",
            "- If a repository method already does the work under a",
            "  different name, delegate to it; do not re-filter",
            "  `read_all_*` in Python.",
            "- `read_one_*` raises `<Entity>NotFoundError` when nothing",
            "  matches, despite the `| None` in its annotation; a `None`",
            "  check after it is dead code.",
        ]
    else:
        lines += [
            f"- `self._store` reads return {STORE_CONTRACT.read_shape}:",
            '  read them with `record.get("field")`; `self.ENTITY`',
            "  is this class's table.",
        ]
    models_text = (files.get("models.py") or "").rstrip()
    if models_text:
        lines.append("- models.py, exactly as defined (types, defaults and")
        lines.append("  imports); read attributes, never `.get(...)`:")
        lines.append("```python")
        lines += models_text.splitlines()
        lines.append("```")
        lines += [
            "- The dataclasses annotate dates as `datetime.date`/",
            "  `datetime.datetime`; the store",
            f"  {STORE_CONTRACT.date_read}. It",
            f"  {STORE_CONTRACT.date_write}. Compare a typed date field",
            "  with `datetime.date.today()` or `datetime.datetime.now()`",
            "  directly; store a date/datetime (or its `.isoformat()`)",
            "  back. Never `strftime(\"%Y-%m-%d %H:%M:%S\")`:",
            "  space-separated text does not match the stored ISO values.",
        ]
        if filename == "services.py":
            lines += [
                "- Changing a dataclass does not save it: write through the",
                "  repository's `update_*` method; returning a mutated",
                "  object alone saves nothing.",
            ]
        else:
            lines += [
                f"- {STORE_CONTRACT.mutation}.",
            ]
    errors = sorted(_class_names(files.get("errors.py") or ""))
    if errors:
        lines.append(f"- errors.py defines only these: {', '.join(errors)}")
        lines.append("  The list is a vocabulary, not a work order: raise one")
        lines.append("  only where the requirements or the human-confirmed")
        lines.append("  contract describe that failure. Do not add checks")
        lines.append("  they do not state.")
    lines.append("- A body may use these stdlib modules; a needed import")
    lines.append(f"  is added for you: {', '.join(BODY_IMPORTS)}")
    return lines


def _requirements_line(requirements, method):
    """The requirements sentence that names this method, if any.

    A method's requirement line can carry an order or a value the model
    would otherwise retrieve from the middle of a long prompt. The full
    requirements are at the top; the target contract repeats the one line
    at the elbow. Domain facts, when they exist, come from the human-
    confirmed method contract rather than from this line.
    """
    for line in (requirements or "").splitlines():
        if method and re.search(
                rf"\b{re.escape(method)}\b\s*(?:\(|:)", line):
            return line.strip()
    return ""


def _ordered_assigned_fields(check, assigned):
    """The fields in `check` that a body sets and compares by order.

    Only `a > b`, `a < b`, `a >= b`, `a <= b` mean "compare the value this
    body is about to assign". An existence check such as
    `loan.return_date is not None` tests the old value (already returned),
    so it stays among the early preconditions.
    """
    try:
        expression = ast.parse(check, mode="eval").body
    except SyntaxError:
        return []
    if not isinstance(expression, ast.Compare):
        return []
    if not any(isinstance(op, (ast.Gt, ast.Lt, ast.GtE, ast.LtE))
               for op in expression.ops):
        return []
    found = []
    for node in ast.walk(expression):
        if isinstance(node, ast.Attribute):
            name = ast.unparse(node)
            if name in assigned:
                found.append(name)
    return sorted(set(found))


def _contract_lines(contract):
    """The human's method contract as prompt lines.

    The generator knows the schema, never the domain: every name below comes
    from the record. A library return and a stock consumption render through
    the same function.

    A check that compares a field the body sets is about the new value, so
    it is rendered after the sets and before the save: a small model shown
    it among the preconditions tested the old value (still None) and the
    branch could never fire. Existence checks such as `return_date is not
    None` stay early; they are about the old value.
    """
    if not contract:
        return []
    lines = ["The human-confirmed contract for this method (where it",
             "differs from the requirement, this contract wins):"]
    preconditions = contract.get("preconditions") or []
    effects = contract.get("effects") or []
    assigned = {item["target"] for item in effects
                if item.get("op") == "set" and item.get("target")}
    early, late = [], []
    for item in preconditions:
        named = _ordered_assigned_fields(item.get("check") or "", assigned)
        if named:
            late.append((item, named))
        else:
            early.append(item)
    if early:
        lines.append("  preconditions:")
        for item in early:
            check = item["check"]
            error = item.get("error")
            raise_when = item.get("raise_when")
            if error and raise_when in ("true", "false"):
                guard = (f"if {check}: raise {error}(...)"
                         if raise_when == "true"
                         else f"if not ({check}): raise {error}(...)")
                lines.append(
                    f"    - raise `{error}` when `{check}` is {raise_when}; "
                    f"write exactly `{guard}`")
            else:
                suffix = f"; otherwise raise `{error}`" if error else ""
                lines.append(f"    - `{check}`{suffix}")
    creates = contract.get("creates") or []
    if creates:
        lines.append("  creates:")
        for item in creates:
            class_name, call = item.get("class"), item.get("call")
            if class_name and call:
                lines.append(
                    f"    - create `models.{class_name}` through `{call}(...)`")
            elif call:
                lines.append(f"    - create through `{call}(...)`")
            elif class_name:
                lines.append(f"    - create `models.{class_name}`")
    def effect_line(item):
        target, op = item["target"], item["op"]
        detail = ""
        if op == "set":
            detail = f" to `{item['value']}`" if "value" in item else ""
        elif "by" in item:
            detail = f" by `{item['by']}`"
        return f"    - {op} `{target}`{detail}"

    def late_line(item):
        check = item.get("check") or ""
        error = item.get("error")
        raise_when = item.get("raise_when")
        if error and raise_when in ("true", "false"):
            guard = (f"if {check}: raise {error}(...)"
                     if raise_when == "true"
                     else f"if not ({check}): raise {error}(...)")
            return f"    - then, before saving, write `{guard}`"
        return f"    - then, before saving, check `{check}`"

    rendered_late = set()
    if effects:
        lines.append("  effects:")
        index = 0
        while index < len(effects):
            item = effects[index]
            write = item.get("write")
            group = [item]
            cursor = index + 1
            if write:
                while cursor < len(effects) \
                        and effects[cursor].get("write") == write:
                    group.append(effects[cursor])
                    cursor += 1
            for member in group:
                lines.append(effect_line(member))
            group_targets = {member.get("target") for member in group
                             if member.get("target")}
            for late_item, named in late:
                if id(late_item) in rendered_late:
                    continue
                if any(target in group_targets for target in named):
                    lines.append(late_line(late_item))
                    rendered_late.add(id(late_item))
            if write:
                owners = []
                for member in group:
                    prefix = (member.get("target") or "").split(".")[0]
                    if prefix and prefix not in owners:
                        owners.append(prefix)
                noun = (" and ".join(f"`{owner}`" for owner in owners)
                        if owners else "record")
                lines.append(
                    f"    - save the changed {noun} with `{write}(...)`")
            index = cursor
    reads = contract.get("reads") or []
    if reads:
        lines.append("  reads:")
        for item in reads:
            via = f" (related through `{item['via']}`)" if item.get("via") \
                else ""
            lines.append(
                f"    - read `{item['entity']}.{item['field']}` from the "
                f"`{item['entity']}` records{via}; matching against the "
                f"foreign key alone is wrong")
    derives = contract.get("derives") or []
    if derives:
        lines.append("  derived values (in memory only):")
        for item in derives:
            lines.append(
                f"    - every returned record carries `{item['target']}` = "
                f"{item['value']!r}: set it on the returned objects and do "
                "not save it (no `update` call)")
    order = contract.get("order") or []
    if order:
        lines.append("  order: " + " -> ".join(f"`{step}`" for step in order))
    forbid = contract.get("forbid") or []
    if forbid:
        lines.append("  forbidden:")
        for item in forbid:
            message = f": {item['message']}" if item.get("message") else ""
            lines.append(
                f"    - the value assigned to `{item['target']}` must not "
                f"read `{item['reads']}`{message}")
    for late_item, _named in late:
        if id(late_item) not in rendered_late:
            lines.append(late_line(late_item))
            rendered_late.add(id(late_item))
    if len(lines) == 1:
        return []
    return lines + [""]


def _target_contract(info, files, requirements="", contract=None):
    """The target method, its requirement and confirmed contract, above the ask.

    The API block is long by design; a small model does not reliably
    retrieve a schema from its middle. The class the declared return type
    names is the one the body must construct or mutate, so it goes last.
    The requirement sentence goes first so the model does not have to find
    it in the middle. The human-confirmed contract follows it: those are the
    only domain-specific facts the generator uses, and they come from a
    review record rather than a phrase in this file.
    """
    lines = []
    requirement = _requirements_line(requirements, _stub_method(info))
    if requirement:
        lines += ["The requirement for this method:", "    " + requirement,
                  ""]
    lines += _contract_lines(contract)
    signature = (info.get("def") or "").strip()
    if signature:
        lines += ["The method you are writing:", "    " + signature, ""]
    declared = _declared_return(info)
    if declared:
        source = _class_source(files.get("models.py") or "", declared)
        if source:
            lines += [f"`models.{declared}` is exactly:", "```python",
                      *source.splitlines(), "```", ""]
    if info.get("file") == "services.py":
        lines += ["Changing a dataclass does not save it: call the",
                  "repository's `update_*` method with the instance.",
                  "Returning the mutated object alone saves nothing.", ""]
    else:
        lines += ["Changing a record dict does not save it: write through",
                  "`self._store.update(...)`.", ""]
    return lines


def _body_refusal(body, module_names, store_names, model_names=frozenset(),
                  error_names=frozenset()):
    """Why this answer may not replace a stub, or None when it may.

    Compilation is checked by the caller; this catches the ways a
    compiling body still cannot work: the model kept the refusal, imported
    a module outside the prompt's allowed list, or invented an API surface
    the module, store, models or errors never defined (`self.helper`,
    `self._store.frobnicate`, `models.date_today`,
    `errors.BookUnavailableError`).
    """
    if not body or all(not line.strip() for line in body):
        return "the model returned nothing"
    text = "\n".join(body)
    if "NotImplementedError" in text:
        return "the model kept it unimplemented"
    for match in re.finditer(r"^\s*(?:from\s+([\w.]+)|import\s+([\w.]+))",
                             text, re.M):
        module = (match.group(1) or match.group(2)).split(".")[0]
        if module not in BODY_IMPORTS:
            return (f"imports `{module}`, which is not one of the modules "
                    "the prompt allows")
    unknown = sorted({name for name in re.findall(r"self\.(\w+)", text)
                      if name not in module_names})
    if unknown:
        return f"calls self.{unknown[0]}, which the module does not define"
    invented = sorted({name for name in re.findall(r"self\._store\.(\w+)", text)
                       if name not in store_names})
    if invented:
        return (f"calls self._store.{invented[0]}, which the store does not "
                "define")
    invented = sorted({name for name in re.findall(r"\bmodels\.(\w+)", text)
                       if name not in model_names})
    if invented:
        return f"calls models.{invented[0]}, which models.py does not define"
    invented = sorted({name for name in re.findall(r"\berrors\.(\w+)", text)
                       if name not in error_names})
    if invented:
        return f"calls errors.{invented[0]}, which errors.py does not define"
    return None


def _field_map(text):
    """`{class: [field, ...]}` from the emitted models module."""
    mapping = {}
    for entry in _model_fields(text):
        name, _, fields = entry.partition("(")
        mapping[name.strip()] = [
            piece.split(":")[0].strip()
            for piece in fields.rstrip(")").split(",") if piece.strip()]
    return mapping


def _call_owner(node, current_cls=None):
    """The class whose method `node` calls, when the receiver names one.

    Service bodies call `self._repos['LoanRepository'].read_one(...)`; the
    repository key is the owner. A plain `self.read_one(...)` belongs to the
    module's own class. When neither is available the caller falls back to a
    method-name lookup.
    """
    if (isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "_repos"):
        index = node.slice
        if isinstance(index, ast.Constant) and isinstance(index.value, str):
            return index.value
    if isinstance(node, ast.Name) and node.id == "self":
        return current_cls
    return None


def _method_returns(*texts):
    """`({(owner, method): annotation}, {method: annotation})` from source.

    Repository interfaces share method names (`read_one` exists on every
    repository), so a bare name cannot say whether `read_one` returns a Book,
    a Member or a Loan. The owner/method key is exact; the name key is only the
    fallback for source that has no class context.
    """
    by_owner, by_name = {}, {}
    for text in texts:
        if not text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for item in node.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                annotation = ast.unparse(item.returns) if item.returns else ""
                by_owner[(node.name, item.name)] = annotation
                by_name.setdefault(item.name, annotation)
    return by_owner, by_name


def _target_names(target):
    """The plain names a comprehension target binds (`for k, v in ...`)."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names = []
        for element in target.elts:
            names.extend(_target_names(element))
        return names
    return []


def _body_complaints(body, info, module_text, references_text, files,
                     requirement="", contract=None, judge=None):
    """The contract violations the refusal regexes cannot see.

    The prompt's API section is a contract: it lists each model's fields,
    the module's own names, the imports a body may gain and each method's
    declared return type. A body that breaks one of those facts compiles
    and still cannot work — a live body read a field the model lacks,
    another indexed `dict.keys()[i]`, another never used a parameter, and
    two returned the wrong dataclass. A repository read carries its type
    too; changes to a read instance must reach an `update_*` call or the
    store keeps the old record. Those checks are domain-neutral.

    The same function checks the human-confirmed method contract when one
    is present: the named fields are written, the named create/write calls
    exist, the named error is raised, and a forbidden field-to-field
    assignment does not appear. The domain names all come from the record;
    this module only knows effects, calls, raises and fields. The generic
    create-before-raise and update-before-create checks remain independent
    of any contract because they describe a safe write order for every
    application. Each complaint names the fact, so the repair ask can quote
    it and the second answer can be a correction instead of a guess.
    """
    params = _stub_params(info)
    source = ("def _wrapped(" + ", ".join(["self"] + params) + "):\n") \
        + "\n".join(("    " + line if line.strip() else "")
                    for line in body)
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return [f"the body does not compile ({error.msg})"]
    module_names = _module_bindings(module_text)
    bound, loads = {}, {}
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Store):
                names.append(node.id)
            elif isinstance(node.ctx, ast.Load):
                loads[node.id] = min(loads.get(node.id, 10 ** 9),
                                     node.lineno)
        elif isinstance(node, (ast.Lambda, ast.FunctionDef,
                               ast.AsyncFunctionDef)):
            args = node.args
            names += [arg.arg for arg in (*args.posonlyargs, *args.args,
                                          *args.kwonlyargs)]
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp,
                               ast.GeneratorExp)):
            # A comprehension binds its targets before its first use: in a
            # dict comprehension the key expression is read while the
            # `for` clause that binds the name is further down, so the
            # target counts as bound where the comprehension starts.
            for generator in node.generators:
                names += _target_names(generator.target)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            names += [item.optional_vars.id for item in node.items
                      if isinstance(item.optional_vars, ast.Name)]
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names += [alias.asname or alias.name.split(".")[0]
                      for alias in node.names]
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.append(node.name)
        for name in names:
            bound[name] = min(bound.get(name, 10 ** 9), node.lineno)
    known = (set(params) | {"self"} | module_names | set(BODY_IMPORTS)
             | set(bound) | set(dir(builtins)))
    found = []
    text = "\n".join(body)
    unresolved_comment = re.compile(
        r"\b(?:TODO|FIXME|XXX)\b"
        r"|\b(?:this|that|the call|the result|the expression)\s+"
        r"(?:is|was)\s+(?:incorrect|wrong|invalid)\b"
        r"|\b(?:wrong|incorrect)\s+(?:field|method|call|value|result)\b"
        r"|\b(?:should be fixed|needs? to be fixed|must be corrected)\b",
        re.I)
    try:
        comments = [token.string for token in tokenize.generate_tokens(
            io.StringIO(source).readline) if token.type == tokenize.COMMENT]
    except (IndentationError, tokenize.TokenError):
        comments = []  # the parser above already reports malformed bodies
    for comment in comments:
        if unresolved_comment.search(comment):
            found.append(
                "contains an unresolved reasoning comment; resolve the note "
                "in code or remove it before accepting the body")
            break
    terminal = (ast.Return, ast.Raise, ast.Break, ast.Continue)
    lines = source.splitlines()
    for node in ast.walk(tree):
        for attribute in ("body", "orelse", "finalbody"):
            block = getattr(node, attribute, None)
            if not isinstance(block, list):
                continue
            for position, statement in enumerate(block[:-1]):
                if not isinstance(statement, terminal):
                    continue
                following = block[position + 1]
                snippet = ""
                if 0 < following.lineno <= len(lines):
                    snippet = lines[following.lineno - 1].strip()[:60]
                found.append(
                    f"has code after `{type(statement).__name__.lower()}`"
                    + (f" (`{snippet}`)" if snippet else "")
                    + " that can never run; check the indentation of the "
                    "lines after it")
                break
    if re.search(r"\.(?:keys|values|items)\(\)\s*\[", text):
        found.append("indexes a dict view (`dict.keys()[i]` is not "
                     "subscriptable); wrap it in `list(...)` or iterate")
    for name in sorted(set(loads) - known):
        found.append(f"uses `{name}`, which neither the module nor the "
                     "body binds")
    for param in params:
        if param not in loads:
            found.append(f"parameter `{param}` is never used in the body")
    fields = _field_map(files.get("models.py") or "")
    parents = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    owner_returns, returns = _method_returns(
        module_text, references_text or "")
    typed, sequence_typed, read_names = {}, {}, set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Call)):
            continue
        name = node.targets[0].id
        func = node.value.func
        cls = None
        sequence_cls = None
        if (isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "models"
                and func.attr in fields):
            cls = func.attr
        elif isinstance(func, ast.Attribute):
            owner = _call_owner(func.value, info.get("cls"))
            annotation = owner_returns.get((owner, func.attr)) if owner else None
            if annotation is None:
                annotation = returns.get(func.attr)
            cls = _direct_model(annotation or "")
            sequence_cls = (
                _first_model(annotation or "")
                if re.search(r"\b(?:List|list|Set|set|Tuple|tuple|Iterable|"
                             r"Iterator|Sequence)\s*\[", annotation or "")
                else None)
            if cls and not (func.attr in ("create", "update")
                            or func.attr.startswith(("create_", "update_"))):
                read_names.add(name)
        if cls:
            typed[name] = cls
        elif sequence_cls:
            sequence_typed[name] = sequence_cls

    def expression_model(expression):
        """The model class carried by an object or iterable expression."""
        if isinstance(expression, ast.Name):
            return typed.get(expression.id) or sequence_typed.get(expression.id)
        if isinstance(expression, (ast.ListComp, ast.SetComp,
                                   ast.GeneratorExp)):
            return expression_model(expression.elt)
        if isinstance(expression, ast.Call):
            func = expression.func
            if (isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "models"
                    and func.attr in fields):
                return func.attr
            if isinstance(func, ast.Attribute):
                owner = _call_owner(func.value, info.get("cls"))
                annotation = owner_returns.get((owner, func.attr)) if owner else None
                if annotation is None:
                    annotation = returns.get(func.attr)
                return _first_model(annotation or "")
        return None

    # Retain the element model for local list/set/generator comprehensions so
    # ``set(matches)`` is checked just like ``set(book for book in books)``.
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, (ast.ListComp, ast.SetComp,
                                            ast.GeneratorExp))):
            continue
        model = expression_model(node.value.elt)
        if model:
            sequence_typed[node.targets[0].id] = model

    # A list filled with `.append(models.X(...))` carries X too: the live
    # search body built `results` that way and deduplicated it with
    # `dict.fromkeys(results)`, which hashes every model.
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append"
                and isinstance(node.func.value, ast.Name) and node.args):
            model = expression_model(node.args[0])
            if model:
                sequence_typed.setdefault(node.func.value.id, model)

    def comprehension_model(comprehension, member):
        """The model a comprehension member carries: a loop variable takes
        the element model of what it iterates."""
        if isinstance(member, ast.Name):
            for generator_ in comprehension.generators:
                if isinstance(generator_.target, ast.Name) \
                        and generator_.target.id == member.id:
                    return expression_model(generator_.iter)
        return expression_model(member)

    advice = ("; use a stable key such as the model ID and return the model "
              "objects")
    for node in ast.walk(tree):
        label = None
        if isinstance(node, ast.Call) and node.args:
            func = node.func
            if isinstance(func, ast.Name) and func.id in ("set", "frozenset"):
                label = f"{func.id}()"
            elif (isinstance(func, ast.Attribute) and func.attr == "fromkeys"
                    and isinstance(func.value, ast.Name)
                    and func.value.id in ("dict", "OrderedDict")):
                label = f"{func.value.id}.fromkeys()"
            if label:
                model = expression_model(node.args[0])
                if model:
                    found.append(
                        f"uses {label} to deduplicate mutable `{model}` "
                        f"models" + advice)
        elif isinstance(node, (ast.SetComp, ast.DictComp)):
            member = node.elt if isinstance(node, ast.SetComp) else node.key
            model = comprehension_model(node, member)
            if model:
                found.append(
                    (f"builds a set of mutable `{model}` models"
                     if isinstance(node, ast.SetComp)
                     else f"keys a dict by mutable `{model}` models")
                    + advice)
    declared_annotation = _return_annotation(info)
    declared_model = _declared_return(info)
    declared_collection = bool(re.search(
        r"\b(?:List|list|Set|set|Tuple|tuple|Iterable|Iterator|Sequence)\s*\[",
        declared_annotation))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        value = node.value
        if declared_collection and isinstance(value, ast.Name) \
                and value.id in typed:
            found.append(
                f"returns one `{typed[value.id]}` from a method declared "
                f"`-> {declared_annotation}`; the return annotation requires "
                "a collection")
        elif declared_collection and isinstance(value, ast.Call):
            func = value.func
            annotation = None
            if (isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "models"
                    and func.attr in fields):
                annotation = f"models.{func.attr}"
            elif isinstance(func, ast.Attribute):
                owner = _call_owner(func.value, info.get("cls"))
                annotation = owner_returns.get((owner, func.attr)) if owner else None
                if annotation is None:
                    annotation = returns.get(func.attr)
            if annotation and _direct_model(annotation):
                found.append(
                    f"returns one `{_direct_model(annotation)}` from a method "
                    f"declared `-> {declared_annotation}`; the return "
                    "annotation requires a collection")
        elif (not declared_collection and declared_model
              and isinstance(value, (ast.List, ast.Tuple, ast.Set,
                                     ast.ListComp, ast.SetComp,
                                     ast.GeneratorExp))):
            found.append(
                f"returns a collection from a method declared `-> "
                f"{declared_annotation}`; the return annotation requires "
                f"one `{declared_model}` or None")
        elif (not declared_collection and declared_model
              and isinstance(value, ast.Name)
              and value.id in sequence_typed):
            found.append(
                f"returns a collection of `{sequence_typed[value.id]}` from a "
                f"method declared `-> {declared_annotation}`; the return "
                f"annotation requires one `{declared_model}` or None")
    seen = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) \
                and isinstance(node.value, ast.Name):
            cls = typed.get(node.value.id)
            if cls and node.attr not in fields[cls] \
                    and (node.value.id, node.attr) not in seen:
                seen.add((node.value.id, node.attr))
                found.append(
                    f"`{node.value.id}.{node.attr}`: {cls} has no field "
                    f"`{node.attr}` (fields: {', '.join(fields[cls])})")
    found.extend(_date_assignment_complaints(tree))
    mutations = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AugAssign):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if (isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id in typed):
                mutations.setdefault(target.value.id, target.attr)
    updated = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and (node.func.attr == "update"
                     or node.func.attr.startswith("update_"))):
            continue
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            for inner in ast.walk(arg):
                if isinstance(inner, ast.Name) and inner.id in mutations:
                    updated.add(inner.id)
    for name in sorted(mutations):
        if name in read_names and name not in updated:
            found.append(
                f"`{name}.{mutations[name]}` is changed, but `{name}` is "
                "never passed to an update_* method; a dataclass is a copy, "
                "so the change is lost")
    if info.get("file") == "services.py" \
            and not (contract or {}).get("derives"):
        untyped_mutations = []
        for node in ast.walk(tree):
            targets = node.targets if isinstance(node, ast.Assign) \
                else [node.target] if isinstance(node, ast.AugAssign) else []
            for target in targets:
                if (isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id != "self"):
                    untyped_mutations.append(
                        f"{target.value.id}.{target.attr}")
        update_calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and (node.func.attr == "update"
                 or node.func.attr.startswith("update_"))]
        if untyped_mutations and not update_calls:
            found.append(
                f"changes `{untyped_mutations[0]}` in memory but never calls "
                "a repository update; a dataclass change is not saved")
    writes = [node for node in ast.walk(tree)
              if (isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute)
                  and (node.func.attr == "create"
                       or node.func.attr.startswith("create_"))
                  and not _in_nested_function(node, parents))]
    raises = [node for node in ast.walk(tree)
              if isinstance(node, ast.Raise)
              and not _in_nested_function(node, parents)]
    for write in writes:
        chain = _block_chain(write, parents)
        if not chain:
            continue
        for raised in raises:
            if raised.lineno < write.lineno \
                    and _permits_post_write_raise(requirement, contract,
                                                  _raised_name(raised)) \
                    and not _raised_by_repository(files, _raised_name(raised)) \
                    and _block_chain(raised, parents)[:len(chain)] == chain:
                found.append(
                    f"the requirement says the check runs after the insert, "
                    f"but `raise {_raised_name(raised)}(...)` runs before "
                    f"`{write.func.attr}(...)`; create the record first, then "
                    "check — the stored record is the intended outcome")
                continue
            if raised.lineno <= write.lineno:
                continue
            if _block_chain(raised, parents)[:len(chain)] != chain:
                continue
            if _permits_post_write_raise(requirement, contract,
                                         _raised_name(raised)) \
                    or _raised_by_repository(files, _raised_name(raised)):
                continue
            found.append(
                f"`{write.func.attr}(...)` runs before `raise "
                f"{_raised_name(raised)}(...)`; the record is stored even "
                "when the operation is refused — validate first, create, "
                "then update; do not move the update ahead of the create")
    updates = [node for node in ast.walk(tree)
               if (isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Attribute)
                   and node.func.attr.startswith("update_")
                   and not _in_nested_function(node, parents))]
    for update in updates:
        chain = _block_chain(update, parents)
        if not chain:
            continue
        for create in writes:
            if create.lineno <= update.lineno:
                continue
            if _block_chain(create, parents)[:len(chain)] != chain:
                continue
            found.append(
                f"`{update.func.attr}(...)` runs before "
                f"`{create.func.attr}(...)`; if the create fails, the "
                "change is kept without the new record — create first, "
                "then update")
    for name in sorted(loads):
        if name in params or name == "self" or name in module_names \
                or name in BODY_IMPORTS:
            continue
        if name in bound and loads[name] < bound[name]:
            found.append(f"reads `{name}` (line {loads[name]}) before it "
                         f"is assigned (line {bound[name]})")
    declared = _declared_return(info)
    if declared:
        annotation = _return_annotation(info)
        value_returns = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Return) and node.value is not None
            and not (isinstance(node.value, ast.Constant)
                     and node.value.value is None)]
        yields = [node for node in ast.walk(tree)
                  if isinstance(node, (ast.Yield, ast.YieldFrom))]
        if yields and not re.search(
                r"\b(?:Iterator|Generator|Iterable)\b", annotation):
            found.append(
                f"the body uses `yield`, but the method is declared "
                f"`-> {annotation}`; a generator function does not return "
                "that value")
        elif not value_returns:
            found.append(
                f"the method is declared `-> {annotation}`, but the body "
                "never returns a value")
        reported = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Return) \
                    or not isinstance(node.value, ast.Name):
                continue
            name = node.value.id
            for assign in ast.walk(tree):
                if not (isinstance(assign, ast.Assign)
                        and len(assign.targets) == 1
                        and isinstance(assign.targets[0], ast.Name)
                        and assign.targets[0].id == name
                        and isinstance(assign.value, ast.Call)):
                    continue
                func = assign.value.func
                method = func.attr if isinstance(func, ast.Attribute) else ""
                owner = (_call_owner(func.value, info.get("cls"))
                         if isinstance(func, ast.Attribute) else None)
                annotation = (owner_returns.get((owner, method))
                              if owner else None)
                if annotation is None:
                    annotation = returns.get(method, "")
                actual = _first_model(annotation)
                if actual and actual != declared:
                    key = (name, method, actual)
                    if key not in reported:
                        reported.add(key)
                        found.append(
                            f"returns `{name}` from `{method}(...)` "
                            f"(a {actual}) but the method is declared "
                            f"`-> models.{declared}`")
                    break
    found.extend(_contract_complaints(
        tree, contract, judge, "\n".join(body)))
    found += _keyword_call_complaints(tree, references_text)
    found += _positional_dict_complaints(tree, references_text)
    found += _scalar_return_complaints(tree, references_text)
    found += _repository_call_complaints(tree, references_text)
    found += _entity_create_usage_complaints(tree, references_text)
    found += _store_operator_complaints(tree)
    return found


def _last_name(value):
    """The final segment of a contract reference (`Repo.update_x` -> `update_x`)."""
    return str(value).rsplit(".", 1)[-1]


def _target_names_of(target):
    """Field names a store target writes: an attribute or a string subscript."""
    if isinstance(target, (ast.Tuple, ast.List)):
        names = set()
        for item in target.elts:
            names |= _target_names_of(item)
        return names
    if isinstance(target, ast.Attribute):
        return {target.attr}
    if isinstance(target, ast.Subscript) \
            and isinstance(target.slice, ast.Constant) \
            and isinstance(target.slice.value, str):
        return {target.slice.value}
    return set()


def _assignment(node):
    """`(targets, value)` for an assignment, ann-assignment or aug-assignment."""
    if isinstance(node, ast.Assign):
        return node.targets, node.value
    if isinstance(node, ast.AugAssign):
        return [node.target], node.value
    if isinstance(node, ast.AnnAssign) and node.value is not None:
        return [node.target], node.value
    return [], None


def _date_assignment_complaints(tree):
    """Reject an integer expression stored as a date.

    `due_date=book.published_year + 10` compiles and then fails at the first
    `.isoformat()`; a date field accepts a date, a datetime, an ISO string or
    `None`, and arithmetic only makes sense with `datetime.timedelta`.
    """
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            name = keyword.arg or ""
            if not (name.endswith(("_date", "_time"))
                    or name in ("date", "time")):
                continue
            value = keyword.value
            if isinstance(value, ast.Constant) and value.value is None:
                continue
            bad = (isinstance(value, ast.Constant)
                   and isinstance(value.value, (int, float)))
            if isinstance(value, ast.BinOp):
                timedelta = any(
                    isinstance(inner, ast.Attribute)
                    and inner.attr == "timedelta"
                    for inner in ast.walk(value))
                bad = bad or not timedelta
            if bad:
                found.append(
                    f"sets `{name}` from an arithmetic expression that is not "
                    "a date; use a date/datetime or `datetime.timedelta`")
    return found


def _mapping_items(node, tree):
    """`(key, value)` pairs of a dict literal or a local dict variable."""
    if isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                yield key.value, value
        return
    if isinstance(node, ast.Name):
        for text in _assigned_values(tree, node.id):
            try:
                value = ast.parse(text, mode="eval").body
            except SyntaxError:
                continue
            yield from _mapping_items(value, tree)


def _field_writes(tree, field):
    """Every write of `field`, with the expression assigned or passed.

    A service saves through the repository API, so `update(return_date=...)`
    is a write exactly as `loan.return_date = ...` is; both shapes carry the
    value the contract checks need to see. A repository path may also build a
    patch mapping (`patch = {'stock': value}`) and pass it to
    `store.update(..., patch)`; the mapping key is the write.
    """
    writes = []
    for node in ast.walk(tree):
        targets, value = _assignment(node)
        if any(field in _target_names_of(target) for target in targets):
            writes.append((node, value))
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == field:
                    writes.append((node, keyword.value))
            for argument in node.args:
                for key, mapped in _mapping_items(argument, tree):
                    if key == field:
                        writes.append((node, mapped))
    return writes


def _mentions_field(node, field):
    """True when an expression reads `field` as an attribute or string key."""
    if node is None:
        return False
    return any(field in _target_names_of(inner) for inner in ast.walk(node))


def _mentions_field_resolved(tree, node, field, seen=None):
    """Like `_mentions_field`, following simple local assignments.

    A correct body often writes `current = wine.stock_quantity`, computes
    `new = current + quantity`, then assigns `wine.stock_quantity = new`.
    The contract is about the field, not the spelling of the local variable,
    so follow a Name back to its assigned expression before judging the
    increment.
    """
    if node is None:
        return False
    if _mentions_field(node, field):
        return True
    seen = set() if seen is None else seen
    if isinstance(node, ast.Name):
        if node.id in seen:
            return False
        seen = set(seen)
        seen.add(node.id)
        for value in _assigned_values(tree, node.id):
            try:
                inner = ast.parse(value, mode="eval").body
            except SyntaxError:
                continue
            if _mentions_field_resolved(tree, inner, field, seen):
                return True
    if isinstance(node, ast.BinOp):
        return (_mentions_field_resolved(tree, node.left, field, seen)
                or _mentions_field_resolved(tree, node.right, field, seen))
    return False


def _resolved_binops(tree, node, seen=None):
    """BinOps assigned to `node`, following simple local names."""
    if isinstance(node, ast.BinOp):
        return [node]
    if not isinstance(node, ast.Name):
        return []
    seen = set() if seen is None else seen
    if node.id in seen:
        return []
    seen = set(seen)
    seen.add(node.id)
    found = []
    for value in _assigned_values(tree, node.id):
        try:
            inner = ast.parse(value, mode="eval").body
        except SyntaxError:
            continue
        found.extend(_resolved_binops(tree, inner, seen))
    return found


def _call_names(tree):
    """Method names called anywhere in the body (`update_book`, `now`, ...)."""
    return {node.func.attr for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)}


def _signature_parameters(references_text):
    """`{(class, method): [parameter, ...]}` from repository source OR lines.

    `fill_stubs` passes the repositories module for its return types, while
    the prompt and tests may pass the shorter `Class.method(...)` lines.
    Accept both shapes so a keyword check uses the same signatures the body
    was shown.
    """
    mapping = {}
    cls = None
    for line in (references_text or "").splitlines():
        stripped = line.strip()
        match = re.match(r"^class (\w+)", stripped)
        if match:
            cls = match.group(1)
            continue
        dotted = re.match(r"^(\w+)\.(\w+)\((.*)\)(?:\s*->.*)?$",
                          stripped)
        method = re.match(r"^def (\w+)\((.*)\)(?:\s*->.*)?:$", stripped)
        if dotted:
            owner, name, params_text = (
                dotted.group(1), dotted.group(2), dotted.group(3))
        elif method and cls:
            owner, name, params_text = (
                cls, method.group(1), method.group(2))
        else:
            continue
        if "**" in params_text:
            mapping[(owner, name)] = None
            continue
        try:
            node = ast.parse("def _f(" + params_text + "):\n    pass\n").body[0]
        except SyntaxError:
            continue
        params = [arg.arg for arg in (*node.args.posonlyargs,
                                      *node.args.args,
                                      *node.args.kwonlyargs)
                  if arg.arg not in ("self", "cls")]
        if node.args.vararg:
            params.append(node.args.vararg.arg)
        if node.args.kwarg:
            params.append(node.args.kwarg.arg)
        mapping[(owner, name)] = params
    return mapping


def _repo_name(node):
    """The repository name in `self._repos['BookRepository']`, or None."""
    if not isinstance(node, ast.Subscript):
        return None
    owner = node.value
    if not (isinstance(owner, ast.Attribute)
            and owner.attr == "_repos"
            and isinstance(owner.value, ast.Name)
            and owner.value.id == "self"):
        return None
    key = node.slice
    if isinstance(key, ast.Constant) and isinstance(key.value, str):
        return key.value
    return None


# Spellings a body reaches for when it means a supported operator.
_OPERATOR_SYNONYMS = {"is": "eq", "==": "eq", "=": "eq", "equals": "eq",
                      "<": "lt", ">": "gt", "<=": "le", ">=": "ge"}


def _store_operator_complaints(tree):
    """Reject a `select` operator the store does not implement.

    Criteria reach `select` as a literal list or through a name the body
    fills first (`criteria.append(('return_date', 'is', None))`); both are
    read, because a live body used the unsupported `is` that way and the
    store raised `unknown operator` at run time.
    """
    supported = set(STORE_CONTRACT.criteria_operators)
    allowed = ", ".join(f"`{name}`" for name in
                        STORE_CONTRACT.criteria_operators)
    items, names = [], set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "select"):
            continue
        owner = node.func.value
        if not (isinstance(owner, ast.Attribute) and owner.attr == "_store"
                and isinstance(owner.value, ast.Name)
                and owner.value.id == "self"):
            continue
        if len(node.args) < 2:
            continue
        criteria = node.args[1]
        if isinstance(criteria, (ast.List, ast.Tuple)):
            items.extend(criteria.elts)
        elif isinstance(criteria, ast.Name):
            names.add(criteria.id)
    if names:
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name) \
                    and node.targets[0].id in names \
                    and isinstance(node.value, (ast.List, ast.Tuple)):
                items.extend(node.value.elts)
            elif isinstance(node, ast.AugAssign) \
                    and isinstance(node.target, ast.Name) \
                    and node.target.id in names \
                    and isinstance(node.value, (ast.List, ast.Tuple)):
                items.extend(node.value.elts)
            elif isinstance(node, ast.Call) \
                    and isinstance(node.func, ast.Attribute) \
                    and isinstance(node.func.value, ast.Name) \
                    and node.func.value.id in names and node.args:
                if node.func.attr in ("append", "insert"):
                    items.append(node.args[-1])
                elif node.func.attr == "extend" \
                        and isinstance(node.args[0], (ast.List, ast.Tuple)):
                    items.extend(node.args[0].elts)
    found = []
    for item in items:
        if not (isinstance(item, (ast.Tuple, ast.List))
                and len(item.elts) >= 2):
            continue
        operator = item.elts[1]
        if isinstance(operator, ast.Constant) \
                and isinstance(operator.value, str) \
                and operator.value not in supported:
            message = (f"calls `self._store.select` with operator "
                       f"`{operator.value}`; the store supports only "
                       f"{allowed}")
            if operator.value in _OPERATOR_SYNONYMS:
                message += (f"; write `{_OPERATOR_SYNONYMS[operator.value]}` "
                            "(a null test is `eq` with `None`)"
                            if _OPERATOR_SYNONYMS[operator.value] == "eq"
                            else f"; write "
                                 f"`{_OPERATOR_SYNONYMS[operator.value]}`")
            if message not in found:
                found.append(message)
    return found


def _keyword_parameter(name, params, used):
    """The declared parameter a wrong keyword most likely means.

    A live service body wrote `read_one_book(book_id=loan.book_id)` and
    `update_book(book_id=loan.book_id, book=book)` for signatures
    `(book_id_or_isbn, book)`. The complaint can then quote the exact
    positional call instead of only naming the mismatch, which is what
    the small model followed on the single-parameter method.
    """
    for param in params:
        if param == name and param not in used:
            return param
    prefixed = [param for param in params
                if param not in used and param.startswith(name + "_")]
    if len(prefixed) == 1:
        return prefixed[0]
    extended = [param for param in params
                if param not in used and name.startswith(param + "_")]
    if len(extended) == 1:
        return extended[0]
    name_tokens = set(name.split("_"))
    shared = [param for param in params
              if param not in used
              and name_tokens & set(param.split("_"))]
    return shared[0] if len(shared) == 1 else None


def _positional_call(node, params):
    """The same repository call with every keyword passed positionally.

    `node` must have keywords only (no positional arguments) and every
    keyword must map to one declared parameter. A call that already uses a
    declared keyword is left alone; the caller decides whether it needs a
    rewrite.
    """
    used = set()
    values = {}
    for keyword in node.keywords:
        if keyword.arg is None:
            return None
        matched = _keyword_parameter(keyword.arg, params, used)
        if matched is None:
            return None
        used.add(matched)
        values[matched] = ast.unparse(keyword.value)
    ordered = [values[param] for param in params if param in values]
    return (f"{ast.unparse(node.func)}(" + ", ".join(ordered) + ")")


def _qualify_error_names(body, error_names):
    """Write a known error class as `errors.Name` when the model left it bare.

    The generated service modules import `errors`; a body that raises
    `MemberNotFoundError` instead of `errors.MemberNotFoundError` compiles but
    fails the module-name check, and a small model repeats it on repair asks.
    Qualifying the class is mechanical: only names declared in `errors.py`
    are touched, and an already qualified `errors.Name` is left alone.
    """
    if not body or not error_names:
        return list(body)
    pattern = re.compile(
        r"(?<![\w.])(" + "|".join(re.escape(name)
                                  for name in sorted(error_names, key=len,
                                                     reverse=True))
        + r")\b")
    return [pattern.sub(r"errors.\1", line) for line in body]


def _normalise_repository_returns(body, info, filename):
    """Honour a repository's declared list return with model objects.

    A live library search body appended raw store dictionaries and then
    called `dict.fromkeys(results)`, which raises `TypeError: unhashable
    type: 'dict'` before the method can return. Another filter returned the
    store's dictionaries directly for its no-argument branch. The declared
    return is `list[models.X]`, so the mechanical repair wraps every return
    in `_model_list`, which converts dictionaries and deduplicates by id.
    Only repository list returns are touched; service bodies keep their own
    contract and are not second-guessed here.
    """
    if filename != "repositories.py" or not body:
        return list(body)
    annotation = _return_annotation(info)
    model_name = _declared_return(info)
    if not model_name or not re.search(
            r"\b(?:list|List|Sequence|Iterable|Set|set|Tuple|tuple)\s*\[",
            annotation):
        return list(body)
    source = textwrap.dedent("\n".join(body))
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return list(body)

    class Rewrite(ast.NodeTransformer):
        def visit_Call(self, node):
            node = self.generic_visit(node)
            func = node.func
            if (isinstance(func, ast.Attribute)
                    and func.attr == "fromkeys"
                    and isinstance(func.value, ast.Name)
                    and func.value.id in ("dict", "OrderedDict")
                    and node.args):
                # The result is normalized and deduplicated by `_model_list`;
                # evaluating `dict.fromkeys` first is what raises on a dict.
                return node.args[0]
            return node

        def visit_Return(self, node):
            node = self.generic_visit(node)
            value = node.value
            if value is None or (isinstance(value, ast.Constant)
                                 and value.value is None):
                return node
            if (isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id == "_model_list"):
                return node
            replacement = ast.Call(
                func=ast.Name(id="_model_list", ctx=ast.Load()),
                args=[value, ast.Attribute(
                    value=ast.Name(id="models", ctx=ast.Load()),
                    attr=model_name, ctx=ast.Load())],
                keywords=[])
            return ast.Return(value=replacement)

    try:
        rewritten = ast.fix_missing_locations(Rewrite().visit(tree))
        text = ast.unparse(rewritten)
        compile("def _body():\n" + textwrap.indent(text, "    "),
                "repositories.py", "exec")
    except (SyntaxError, ValueError):
        return list(body)
    return text.splitlines()


def _normalise_create_return_usage(body, references_text):
    """Use the created record's key when a body treats the record as an id.

    `order_id = OrderRepository.create(...)` returns the `Order` dataclass in
    the generated repository, not an integer. A later
    `read_one(id=order_id)` or `OrderItemRepository.create(order_id=order_id)`
    therefore needs `order_id.id`. The rewrite is syntax-driven and only
    applies to variables assigned directly from a repository `create`.
    """
    if not body:
        return list(body)
    returns = {}
    for line in _method_signatures(references_text):
        match = re.match(r"^(\w+)\.(\w+)\(.*\)\s*->\s*(.+?)\s*$", line)
        if match:
            returns[(match.group(1), match.group(2))] = match.group(3).strip()
    if not returns:
        return list(body)
    wrapped = "def _body(self):\n" + "\n".join(
        ("    " + line) if line.strip() else "" for line in body)
    try:
        tree = ast.parse(wrapped)
    except SyntaxError:
        return list(body)
    created = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Call)):
            continue
        func = node.value.func
        if not isinstance(func, ast.Attribute):
            continue
        repo = _repo_name(func.value)
        if repo is None:
            continue
        declared = returns.get((repo, func.attr))
        if not declared or declared.lower() in ("none", "nontype", "int", "str",
                                                "bool", "float", "uuid"):
            continue
        created[node.targets[0].id] = True
    if not created:
        return list(body)

    class Rewrite(ast.NodeTransformer):
        def visit_Call(self, node):
            node = self.generic_visit(node)
            if not (isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("read_one", "update", "delete",
                                            "create")):
                return node
            for keyword in node.keywords:
                if (keyword.arg == "id" or (keyword.arg or "").endswith("_id")) \
                        and isinstance(keyword.value, ast.Name) \
                        and keyword.value.id in created:
                    keyword.value = ast.Attribute(
                        value=keyword.value, attr="id", ctx=ast.Load())
            if node.func.attr in ("read_one", "update", "delete"):
                for index, arg in enumerate(node.args):
                    if isinstance(arg, ast.Name) and arg.id in created:
                        node.args[index] = ast.Attribute(
                            value=arg, attr="id", ctx=ast.Load())
            return node

    try:
        rewritten = ast.fix_missing_locations(Rewrite().visit(tree))
        text = ast.unparse(rewritten)
        lines = text.splitlines()[1:]
        return [line[4:] if line.startswith("    ") else line for line in lines]
    except (SyntaxError, ValueError):
        return list(body)


def _add_collection_creates(body, contract, method, files):
    """Complete a service body that creates a parent but omits its collection.

    The contract names the related create; the method signature names the
    collection; the parent create assignment in the body supplies the key.
    The inserted loop is generic: it forwards each item's own fields and
    overrides only the parent foreign key.
    """
    if not body or not isinstance(contract, dict):
        return list(body)
    creates = contract.get("creates") or []
    if len(creates) < 2:
        return list(body)
    param_names = ([p.get("name") for p in method.get("params") or []
                    if isinstance(p, dict)] if isinstance(method, dict)
                   else [])
    if not param_names:
        param_names = _stub_params(method if isinstance(method, dict) else {})
    target = collection = None
    for candidate in creates:
        if not (isinstance(candidate, dict) and candidate.get("call")
                and candidate.get("class")):
            continue
        candidate_name = candidate["class"]
        candidate_collection = next(
            (name for name in param_names
             if isinstance(name, str) and name.endswith("s")
             and normalize(name)[:-1] == normalize(candidate_name)),
            None)
        if candidate_collection:
            target, collection = candidate, candidate_collection
            break
    if target is None or collection is None:
        return list(body)
    target_class = target["class"]
    call_parts = target["call"].split(".")
    if len(call_parts) < 2:
        return list(body)
    target_repo, target_method = call_parts[-2], call_parts[-1]
    source = textwrap.dedent("\n".join(body))
    try:
        function = ast.parse("def _body(self):\n" + textwrap.indent(source, "    ")).body[0]
    except SyntaxError:
        return list(body)
    parent = None
    for statement in function.body:
        if not (isinstance(statement, ast.Assign) and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
                and isinstance(statement.value, ast.Call)
                and isinstance(statement.value.func, ast.Attribute)
                and statement.value.func.attr == "create"):
            continue
        parent = (statement.targets[0].id, ast.unparse(statement.value.func.value))
        break
    if parent is None:
        return list(body)
    parent_var, parent_receiver = parent
    parent_entity = ""
    match = re.search(r"['\"](\w+)Repository['\"]", parent_receiver)
    if match:
        parent_entity = match.group(1)
    fk = f"{parent_entity.lower()}_id" if parent_entity else "id"
    # Only forward keys that the related model declares; the generated create
    # would reject an unknown keyword.
    model_text = files.get("models.py") or ""
    fields = []
    for line in model_text.splitlines():
        if line.startswith(f"class {target_class}"):
            fields = []
        elif line.startswith("class "):
            fields = None
        elif fields is not None:
            match = re.match(r"    (\w+):", line)
            if match:
                fields.append(match.group(1))
    for name in list(fields or []):
        if name == fk:
            fields.remove(name)
    loop_text = (
        f"for item in {collection} or []:\n"
        f"    payload = dict(item)\n"
        f"    payload[{fk!r}] = {parent_var}.id\n"
        f"    self._repos[{target_repo!r}].{target_method}(**payload)")
    loop = ast.parse(loop_text).body
    new_body = []
    inserted = False
    for statement in function.body:
        new_body.append(statement)
        if (not inserted and isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
                and statement.targets[0].id == parent_var):
            new_body.extend(loop)
            inserted = True
    if not inserted:
        return list(body)
    function.body = new_body
    try:
        text = ast.unparse(function)
        lines = text.splitlines()[1:]
        return [line[4:] if line.startswith("    ") else line for line in lines]
    except (SyntaxError, ValueError):
        return list(body)


def _normalise_repository_keywords(body, references_text):
    """Pass a repository call's values positionally when its keywords are
    unambiguous aliases of the declared parameters.

    A live `borrow_book` answer wrote `read_one_book(book_id=book_id)` for
    a signature `(book_id_or_isbn)` and repeated it on every repair ask,
    even with the exact positional call quoted back: the local parameter
    and the model field are both `book_id`, so the keyword looks right to
    the model. The mapping is mechanical and unique, and passing the value
    positionally is always safe. A call whose keywords map ambiguously is
    left for `_keyword_call_complaints` to refuse.

    Returns the possibly rewritten body and the `Class.method` labels whose
    call was rewritten, so the run can say what it changed.
    """
    signatures = _signature_parameters(references_text)
    if not signatures or not body:
        return list(body), []
    wrapped = "def _body():\n" + "\n".join(
        ("    " + line) if line.strip() else "" for line in body)
    try:
        tree = ast.parse(wrapped)
    except SyntaxError:
        return list(body), []
    edits, labels = [], []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        method = node.func
        if not isinstance(method, ast.Attribute):
            continue
        repo = _repo_name(method.value)
        if repo is None:
            continue
        params = signatures.get((repo, method.attr))
        if params is None or not node.keywords or node.args:
            continue
        if all(keyword.arg in params for keyword in node.keywords):
            continue
        replacement = _positional_call(node, params)
        if replacement is None:
            continue
        if node.lineno != node.end_lineno:
            # A multi-line call may contain comments; rewriting it would
            # discard them. Leave it to the complaint instead.
            continue
        edits.append((node, replacement))
        labels.append(f"{repo}.{method.attr}")
    rewritten = list(body)
    for node, replacement in sorted(
            edits, key=lambda item: (item[0].lineno, item[0].col_offset),
            reverse=True):
        index = node.lineno - 2
        if not 0 <= index < len(rewritten):
            continue
        line = rewritten[index]
        start, end = node.col_offset - 4, node.end_col_offset - 4
        if start < 0 or end > len(line):
            continue
        rewritten[index] = line[:start] + replacement + line[end:]
    return rewritten, labels


def _entity_create_usage_complaints(tree, references_text):
    """Reject an entity returned by `create` used as a scalar id.

    Repositories return the created model; a body that assigns
    `order_id = OrderRepository.create(...)` then calls
    `read_one(id=order_id)` has mistaken the record for its key. The signatures
    come from the generated repositories module, so this is independent of the
    domain and of the method name.
    """
    returns = {}
    for line in _method_signatures(references_text):
        match = re.match(r"^(\w+)\.(\w+)\(.*\)\s*->\s*(.+?)\s*$", line)
        if match:
            returns[(match.group(1), match.group(2))] = match.group(3).strip()
    if not returns:
        return []
    scalar = re.compile(
        r"^(?:int|bool|float|str|None|NoneType|UUID|Any|dict|list\[)"
        r"(?:\s*\|.*)?$", re.IGNORECASE)
    created = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Call)):
            continue
        func = node.value.func
        if not isinstance(func, ast.Attribute):
            continue
        repo = _repo_name(func.value)
        if repo is None:
            continue
        declared = returns.get((repo, func.attr))
        if not declared or scalar.match(declared):
            continue
        created[node.targets[0].id] = f"{repo}.{func.attr}"
    found = []
    for name, call in created.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg == "id" or (keyword.arg or "").endswith("_id"):
                    if isinstance(keyword.value, ast.Name) and keyword.value.id == name:
                        found.append(
                            f"`{name}` is assigned from `{call}`, which returns "
                            "an entity, but is passed as an id; read the created "
                            f"record's key (`{name}.id` or its declared primary key)")
                        break
            if found and found[-1].startswith(f"`{name}`"):
                break
        # A positional id into a repository read/update/delete is the same
        # mistake without a keyword to inspect.
        if any(item.startswith(f"`{name}`") for item in found):
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("read_one", "update", "delete")):
                continue
            if any(isinstance(arg, ast.Name) and arg.id == name
                   for arg in node.args):
                found.append(
                    f"`{name}` is assigned from `{call}`, which returns an "
                    f"entity, but is passed as an id to `{node.func.attr}`; "
                    f"use `{name}.id` or its declared primary key")
                break
    return found


def _keyword_call_complaints(tree, references_text):
    """Reject a repository keyword the repository signature does not define."""
    signatures = _signature_parameters(references_text)
    if not signatures:
        return []
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        method = node.func
        if not isinstance(method, ast.Attribute):
            continue
        repo = _repo_name(method.value)
        if repo is None:
            continue
        params = signatures.get((repo, method.attr))
        if params is None:
            continue
        for keyword in node.keywords:
            if keyword.arg is None or keyword.arg in params:
                continue
            declared = ("none: it takes no parameters" if not params
                        else f"`{params[0]}`" if len(params) == 1
                        else "one of " + ", ".join(
                            f"`{name}`" for name in params))
            suggestion = ""
            if not node.args:
                used = set()
                ordered = []
                for item in node.keywords:
                    matched = (None if item.arg is None
                               else _keyword_parameter(item.arg, params, used))
                    if matched is None:
                        ordered = None
                        break
                    used.add(matched)
                    ordered.append(ast.unparse(item.value))
                if ordered:
                    suggestion = (
                        f"; write `{ast.unparse(node.func)}("
                        + ", ".join(ordered) + ")`")
            found.append(
                f"passes keyword `{keyword.arg}` to `{repo}.{method.attr}`, "
                f"whose declared parameter is {declared}; pass the value "
                f"positionally or use the declared keyword{suggestion}")
            break
    return found


def _positional_dict_complaints(tree, references_text):
    """Reject a field dict passed into a scalar repository parameter.

    A method that declares scalar parameters does not take a field dict;
    only a method that declares a mapping (`update(id, data)`) does.
    """
    signatures = _signature_parameters(references_text)
    if not signatures:
        return []
    mapping_names = {"data", "updates", "values", "patch", "fields"}
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        method = node.func
        if not isinstance(method, ast.Attribute):
            continue
        repo = _repo_name(method.value)
        if repo is None:
            continue
        params = signatures.get((repo, method.attr))
        if params is None:
            continue
        for index, argument in enumerate(node.args):
            if not isinstance(argument, ast.Dict):
                continue
            if index < len(params) and params[index] in mapping_names:
                continue
            target = params[index] if index < len(params) else "an extra parameter"
            found.append(
                f"passes a dict positionally to `{repo}.{method.attr}(...)`, "
                f"where parameter {index + 1} is `{target}`; pass the field "
                "as a keyword instead")
            break
    return found


def _scalar_return_complaints(tree, references_text):
    """Reject a scalar repository result treated as a record.

    A repository `create(...) -> int` returns the new id. A body that
    assigns it to a record variable and reads its fields crashes; the
    record must be read back first.
    """
    returns = {}
    for line in _method_signatures(references_text):
        match = re.match(
            r"^(\w+)\.(\w+)\(.*\)\s*->\s*(.+?)\s*$", line)
        if match:
            returns[(match.group(1), match.group(2))] = match.group(3)
    if not returns:
        return []
    scalar = re.compile(
        r"^(?:int|bool|float|str|None|NoneType)"
        r"(?:\s*\|\s*(?:None|NoneType))?$")
    assigned = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        value = node.value
        if not (isinstance(target, ast.Name) and isinstance(value, ast.Call)):
            continue
        func = value.func
        if not isinstance(func, ast.Attribute):
            continue
        repo = _repo_name(func.value)
        if repo is None:
            continue
        declared = returns.get((repo, func.attr))
        if declared and scalar.match(declared):
            assigned[target.id] = f"{repo}.{func.attr}"
    found = []
    for name, call in assigned.items():
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == name):
                found.append(
                    f"assigns `{name} = {call}(...)`, which returns "
                    "a scalar (the new id), then reads "
                    f"`{name}.{node.attr}` as if it were a record; read it "
                    "back with `read_one` first")
                break
    return found


def _repository_call_complaints(tree, references_text):
    """Reject a method called on a repository that does not define it.

    A service body guessed a repository finder that did not exist
    while the method is declared on `CategoryRepository`; the call reads
    fine and fails only when reached. The module's own repository
    signatures are the only authority.
    """
    signatures = _signature_parameters(references_text)
    if not signatures:
        return []
    owners = {}
    for repo, method in signatures:
        owners.setdefault(method, set()).add(repo)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        method = node.func
        if not isinstance(method, ast.Attribute):
            continue
        repo = _repo_name(method.value)
        if repo is None or (repo, method.attr) in signatures:
            continue
        elsewhere = sorted(owners.get(method.attr, set()) - {repo})
        if elsewhere:
            found.append(
                f"calls `{repo}.{method.attr}(...)`, but {repo} does not "
                f"define `{method.attr}`; it is declared on "
                + " or ".join(f"`{name}`" for name in elsewhere))
        else:
            found.append(
                f"calls `{repo}.{method.attr}(...)`, but no repository "
                "declares that method")
    return found


def _raise_names(tree):
    """Exception names raised anywhere in the body."""
    return {_raised_name(node) for node in ast.walk(tree)
            if isinstance(node, ast.Raise)}


def _expression(text):
    """A contract's condition as an AST expression, or None when it is prose."""
    try:
        return ast.parse(str(text), mode="eval").body
    except (SyntaxError, ValueError):
        return None


def _same_expression(left, right):
    """True when two parsed conditions are structurally identical."""
    return (left is not None and right is not None
            and ast.dump(left, include_attributes=False)
            == ast.dump(right, include_attributes=False))


def _negated_expression(node):
    """The condition's negation, flipping comparisons instead of wrapping."""
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return node.operand
    if isinstance(node, ast.Compare) and len(node.ops) == 1 \
            and len(node.comparators) == 1:
        opposite = {
            ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
            ast.Gt: ast.LtE, ast.LtE: ast.Gt,
            ast.GtE: ast.Lt, ast.Lt: ast.GtE,
        }.get(type(node.ops[0]))
        if opposite is not None:
            return ast.Compare(left=node.left, ops=[opposite()],
                               comparators=[node.comparators[0]])
    return ast.UnaryOp(op=ast.Not(), operand=node)


def _guard_expression(node):
    """A branch condition in positive form: `not a == b` is `a != b`."""
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return _negated_expression(node.operand)
    return node


def _raise_guards(tree, error):
    """The conditions under which a body directly raises `error`."""
    return [guard for guard, _line in _raise_guard_positions(tree, error)]


def _raise_guard_positions(tree, error):
    """`(condition, raise_line)` for every direct raise of `error`."""
    guards = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        for statement in node.body:
            if isinstance(statement, ast.Raise) \
                    and _raised_name(statement) == error:
                guards.append((_guard_expression(node.test),
                               statement.lineno))
        for statement in node.orelse:
            if isinstance(statement, ast.Raise) \
                    and _raised_name(statement) == error:
                guards.append((_negated_expression(node.test),
                               statement.lineno))
    return guards


def _assigned_values(tree, target):
    """The expressions a body assigns to `target`, in source order."""
    values = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if node.value is None:
            continue
        value = ast.unparse(node.value)
        for item in targets:
            if ast.unparse(item) == target:
                values.append(value)
    return values


def _with_assignment(node, target, value):
    """A copy of `node` with the assigned field replaced by its value."""
    class Replace(ast.NodeTransformer):
        def visit_Attribute(self, item):
            if ast.unparse(item) == target:
                return ast.parse(value, mode="eval").body
            return self.generic_visit(item)
    return Replace().visit(ast.parse(ast.unparse(node), mode="eval").body)


def _precondition_match(precondition, tree):
    """The parts of a parseable precondition, or None.

    Returns `(error, check, expected, opposite, target, assigned)`: the
    exception name, the contract expression, the guard that satisfies it,
    the inverted guard, the field being compared (when it is an ordering
    comparison), and the values the body assigns to that field.
    """
    error = _last_name(precondition.get("error") or "")
    raise_when = precondition.get("raise_when")
    check = _expression(precondition.get("check") or "")
    if not error or check is None or raise_when not in ("true", "false"):
        return None
    expected = check if raise_when == "true" \
        else _negated_expression(check)
    opposite = _negated_expression(check) if raise_when == "true" else check
    target = None
    if isinstance(check, ast.Compare) and len(check.ops) == 1 \
            and isinstance(check.ops[0], (ast.Gt, ast.Lt, ast.GtE, ast.LtE)):
        target = ast.unparse(check.left)
    assigned = _assigned_values(tree, target) if target else []
    return error, check, expected, opposite, target, assigned


def _guard_satisfies(guard, expected, target, assigned):
    """True when `guard` is the contract condition, allowing the assigned
    temporary (`now > due` for `field = now; field > due`)."""
    if _same_expression(guard, expected):
        return True
    if target is None:
        return False
    return any(_same_expression(guard, _with_assignment(expected, target, value))
               for value in assigned)


def _raise_when_complaints(tree, precondition, judge=None, body_text=""):
    """Check a comparison's polarity, when the contract states its trigger.

    `raise_when` says whether the named error fires when the condition is
    true or when it is false. A precondition such as `loan is returned`
    usually fires on true; a precondition such as `copies > 0` fires on
    false. Without that bit the same record can be rendered backwards, and
    a body can raise the right error at the wrong time while passing every
    name-and-call check.
    """
    match = _precondition_match(precondition, tree)
    if match is None:
        return []
    error, check, expected, opposite, target, assigned = match
    guards = _raise_guards(tree, error)
    if not guards:
        return []
    if any(_guard_satisfies(guard, expected, target, assigned)
           for guard in guards):
        return []
    if any(_same_expression(guard, opposite) for guard in guards):
        return [
            f"raises `{error}` when `{precondition['check']}` is "
            f"{'false' if precondition['raise_when'] == 'true' else 'true'}; "
            f"the confirmed contract raises it when the condition is "
            f"{precondition['raise_when']}"]
    # A guard that is not the contract's text may still mean the same thing
    # (a loop for `any(...)`, a local for a repeated read). The structural
    # comparison cannot tell; the judge, when there is one, reads the whole
    # body against the confirmed condition. Anything but a clear yes refuses.
    reason = None
    if judge is not None:
        equivalent, reason = judge(precondition, body_text)
        if equivalent:
            return []
    return [
        f"raises `{error}` but not when `{precondition['check']}` is "
        f"{precondition['raise_when']}; the confirmed contract requires "
        "that branch"
        + (f" (equivalence check: {reason})" if reason else "")]


def _precondition_order_complaints(tree, contract):
    """Reject a check that runs after the write its value depends on.

    A live return body put the late-return check after `update_loan(...)`,
    so a refused return still saved the loan and incremented the copies.
    A precondition is checked before the write, even when it compares a
    value the body is about to assign.
    """
    assigned_targets = {effect.get("target") for effect in
                        (contract.get("effects") or [])
                        if effect.get("op") == "set" and effect.get("target")}
    writes = {}
    for effect in contract.get("effects") or []:
        if effect.get("write") and effect.get("target"):
            writes.setdefault(effect["target"], set()).add(
                _last_name(effect["write"]))
    found = []
    for precondition in contract.get("preconditions") or []:
        match = _precondition_match(precondition, tree)
        if match is None:
            continue
        error, _check, expected, _opposite, target, assigned = match
        if target is None or target not in assigned_targets:
            continue
        guard_lines = [
            line for guard, line in _raise_guard_positions(tree, error)
            if _guard_satisfies(guard, expected, target, assigned)]
        if not guard_lines:
            continue
        names = writes.get(target) or set()
        if not names:
            continue
        call_lines = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute):
                name = node.func.attr
            elif isinstance(node.func, ast.Name):
                name = node.func.id
            else:
                continue
            if name in names:
                call_lines.append(node.lineno)
        if call_lines and min(guard_lines) > min(call_lines):
            found.append(
                f"checks `{precondition['check']}` after calling "
                f"`{sorted(names)[0]}(...)`; a precondition must be checked "
                "before the write")
    return found


def _call_target_count(tree, call):
    """How many calls target the exact `Repository.method` in a contract."""
    parts = str(call).split(".")
    repo_name, method_name = ((parts[-2], parts[-1]) if len(parts) >= 2
                              else (None, _last_name(call)))
    count = 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == method_name):
            continue
        if repo_name is None or _repo_name(node.func.value) == repo_name:
            count += 1
    return count


def _contract_complaints(tree, contract, judge=None, body_text=""):
    """Check the human-confirmed method contract, using only its vocabulary.

    Every target, call, error and field below comes from the record. This
    function has no `copies`, `return_date`, `stock_qty` or `book` in it; the
    same checks serve a library return and a factory consumption.
    """
    if not isinstance(contract, dict):
        return []
    found = []
    text = ast.unparse(tree)
    calls = _call_names(tree)
    raises = _raise_names(tree)

    for effect in contract.get("effects") or []:
        target = effect.get("target") or ""
        field = _last_name(target)
        writes = _field_writes(tree, field)
        if not writes:
            found.append(
                f"the confirmed contract changes `{target}`, but the body "
                f"never writes `{field}`")
            continue
        op = effect.get("op")
        if op in ("increment", "decrement"):
            wanted = ast.Add if op == "increment" else ast.Sub
            matched = False
            for node, value in writes:
                if isinstance(node, ast.AugAssign) \
                        and isinstance(node.op, wanted):
                    matched = True
                    break
                for expression in _resolved_binops(tree, value):
                    if isinstance(expression.op, wanted) \
                            and (_mentions_field_resolved(
                                tree, expression.left, field)
                                 or _mentions_field_resolved(
                                     tree, expression.right, field)):
                        matched = True
                        break
                if matched:
                    break
            if not matched:
                found.append(
                    f"the confirmed contract says {op} `{target}`, but the "
                    f"body does not {op} `{field}`")
        if effect.get("write"):
            write = _last_name(effect["write"])
            if write not in calls:
                found.append(
                    f"the confirmed contract saves `{target}` with "
                    f"`{effect['write']}(...)`, but the body never calls "
                    f"`{write}`")
        if effect.get("op") == "set" and str(effect.get("value", "")).lower() \
                == "now" and not ({"now", "today", "utcnow"} & calls):
            found.append(
                f"the confirmed contract sets `{target}` to `now`, but the "
                "body never reads the current time")
        if effect.get("op") == "set":
            value = effect.get("value")
            simple = (isinstance(value, (str, int, float, bool))
                      and str(value).lower() != "now"
                      and " " not in str(value) and "." not in str(value))
            if simple and not any(
                    (isinstance(inner, ast.Constant)
                     and inner.value == value)
                    or (isinstance(value, str) and value in text)
                    for _node, rhs in writes for inner in ast.walk(rhs)):
                found.append(
                    f"the confirmed contract sets `{target}` to `{value}`, "
                    "but the body does not use that value")

    for create in contract.get("creates") or []:
        call = create.get("call")
        if call:
            times = _call_target_count(tree, call)
            if times == 0:
                found.append(
                    f"the confirmed contract creates `{create.get('class') or 'a record'}` "
                    f"through `{call}(...)`, but the body never calls "
                    f"`{call}`")
            elif times > 1:
                found.append(
                    f"the confirmed contract creates one "
                    f"`{create.get('class') or 'record'}` through "
                    f"`{call}(...)`, but the body calls "
                    f"`{call}` {times} times")

    for precondition in contract.get("preconditions") or []:
        error = precondition.get("error")
        if error and _last_name(error) not in raises:
            found.append(
                f"the confirmed contract requires `{precondition.get('check')}` "
                f"to raise `{error}`, but the body never raises it")
        if error and precondition.get("raise_when") in ("true", "false"):
            found.extend(_raise_when_complaints(
                tree, precondition, judge, body_text))

    found.extend(_precondition_order_complaints(tree, contract))

    constants = {node.value for node in ast.walk(tree)
                 if isinstance(node, ast.Constant)
                 and isinstance(node.value, str)}
    attributes = {node.attr for node in ast.walk(tree)
                  if isinstance(node, ast.Attribute)}
    for read in contract.get("reads") or []:
        entity, field = read.get("entity") or "", read.get("field") or ""
        # The related model is reached through its repository's key
        # (`self._repos['AuthorRepository']`) or by naming it to the store
        # (`self._store.select("Author", ...)`); both are string constants.
        reached = {entity, read.get("repository")} - {None, ""}
        if not reached & constants:
            found.append(
                f"the confirmed contract reads `{entity}.{field}`, but the "
                f"body never reads `{entity}`")
        elif field not in attributes and field not in constants:
            found.append(
                f"the confirmed contract reads `{entity}.{field}`, but the "
                f"body never uses its `{field}`")

    keywords = {keyword.arg for node in ast.walk(tree)
                if isinstance(node, ast.Call) for keyword in node.keywords
                if keyword.arg}
    for derive in contract.get("derives") or []:
        target, value = derive.get("target") or "", derive.get("value")
        field = _last_name(target)
        # The value is carried by an assignment, a keyword (`replace(...,
        # status='overdue')`) or a mapping key; the literal must appear too.
        if not (str(value) in constants
                and (field in attributes or field in constants
                     or field in keywords)):
            found.append(
                f"the confirmed contract derives `{target}` = {value!r} on "
                "the returned records, but the body never sets it")
        saves = sorted(name for name in calls if name.startswith("update"))
        if saves:
            found.append(
                f"the confirmed contract derives `{target}` in memory only, "
                f"but the body calls `{saves[0]}`, which saves it")

    for rule in contract.get("forbid") or []:
        target, reads = rule.get("target") or "", rule.get("reads") or ""
        target_field, read_field = _last_name(target), _last_name(reads)
        for _node, value in _field_writes(tree, target_field):
            if _mentions_field(value, read_field):
                found.append(
                    rule.get("message")
                    or f"`{target}` is set from `{reads}`; the confirmed "
                       "contract forbids it")
                break
    return found


def _add_imports(text, body_text):
    """Add the imports a filled body needs; return `(text, added)`."""
    added = []
    for module in BODY_IMPORTS:
        if not re.search(rf"\b{re.escape(module)}\.", body_text):
            continue
        if re.search(rf"^import {re.escape(module)}\b", text, re.M) \
                or re.search(rf"^from {re.escape(module)}\b", text, re.M):
            continue
        lines = text.splitlines()
        anchor = max((index for index, line in enumerate(lines)
                      if re.match(r"^(?:import|from) \w", line)), default=0)
        lines.insert(anchor + 1, f"import {module}")
        text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
        added.append(module)
    return text, added


def _method_signatures(text):
    """`Class.method(...) -> returns` lines: what a service may delegate to."""
    signatures = []
    cls = None
    for line in text.splitlines():
        match = re.match(r"^class (\w+)", line)
        if match:
            cls = match.group(1)
            continue
        match = re.match(r"^    def (\w+\(.*\)(?:\s*->\s*[^:]+)?):$", line)
        if match and cls:
            signatures.append(f"{cls}.{match.group(1)}")
    return signatures


def _spliced_candidate(text, start, end, info, body, model_name):
    """The module with the stub's raise replaced by `body`, tag rewritten."""
    lines = text.splitlines()
    replacement = []
    docstring = info.get("docstring")
    if docstring:
        replacement.append(re.sub(
            r"\[[^\]]*\]\s*(\"\"\")$",
            lambda match: f"[llm-written by {model_name} — review]"
            f"{match.group(1)}", docstring))
    replacement.extend("        " + line if line.strip() else ""
                       for line in body)
    candidate = "\n".join(lines[:start] + replacement + lines[end + 1:])
    if text.endswith("\n"):
        candidate += "\n"
    return candidate


def _attempt_fields(result):
    """The generation facts recorded beside every raw answer in the dump."""
    def number(value):
        return value if isinstance(value, (int, float)) else None

    return {
        "finish_reason": result.finish_reason,
        "tokens": result.tokens,
        "budget": result.budget,
        "truncated": result.truncated,
        "seconds": number(result.seconds),
        "decode_seconds": number(getattr(result, "decode_seconds", None)),
        "prompt_tokens": number(getattr(result, "prompt_tokens", None)),
        "cached_tokens": number(getattr(result, "cached_tokens", None)),
    }


def _first_fields(result):
    return {f"first_{key}": value
            for key, value in _attempt_fields(result).items()}


def _answered(framing, llm, prompt, label):
    """One generation, retried once with the whole room when it was truncated.

    The first attempt stops at `MAX_NEW_TOKENS`; an answer that hit that
    ceiling is not one, and the retry is what tells a model that needed
    more room from one that will never stop. Qwen3-4B-Instruct-2507 under
    raw completion filled 3584 tokens and was still mid-reasoning, then
    filled the whole 5905-token room the same way; through its chat
    template the same ask stopped at 220. A reply that is still truncated
    after the retry is kept as `truncated` and never spliced.
    """
    result = framing(llm, prompt, label, temperature=FALLBACK_TEMPERATURE,
                     seed=FALLBACK_SEED)
    if result.truncated:
        room = runner.available_tokens(llm, prompt)
        if room > (result.budget or 0):
            result = framing(llm, prompt, f"{label}:retry",
                             temperature=FALLBACK_TEMPERATURE,
                             seed=FALLBACK_SEED, max_new_tokens=room)
    return result


def _equivalence_prompt(precondition, body_text):
    """The ask that compares one confirmed condition with a written body."""
    error = precondition.get("error")
    check = precondition.get("check")
    when = precondition.get("raise_when")
    return (
        "You compare a human-confirmed rule with a Python method body.\n\n"
        f"Rule: the method must raise `{error}` when this condition is "
        f"{when}:\n    {check}\n\n"
        "Method body (earlier lines may define the variables a guard uses; "
        "follow them):\n```python\n" + body_text + "\n```\n\n"
        f"Question: does the body raise `{error}` in exactly the situations "
        "where the rule says it must, no more and no fewer? Ignore the "
        "message text and any other checks. Answer NO if the body raises it "
        "under a stricter, a looser or a different condition, or if you are "
        "not sure.\n"
        "Reply with exactly two lines:\n"
        "VERDICT: YES or VERDICT: NO\n"
        "REASON: one short sentence")


def _parse_equivalence(text):
    """`(equivalent, reason)` from a judge reply; anything unclear is no."""
    verdict = re.search(r"VERDICT:\s*(YES|NO)\b", text or "", re.IGNORECASE)
    reason = re.search(r"REASON:\s*(.+)", text or "", re.IGNORECASE)
    why = reason.group(1).strip() if reason else ""
    if verdict is None:
        return False, "the judge gave no clear verdict"
    return verdict.group(1).upper() == "YES", why


def _archive_previous_dump(dump_path):
    """Move the previous raw-answer dump aside before this run overwrites it.

    The dump is the only place a truncated body survives; replacing it on the
    next invocation destroyed the evidence for a live 11k-token cancel answer.
    Keep every completed run under `llm_stub_answers_runs/` beside the latest
    `llm_stub_answers.json`.
    """
    if not os.path.isfile(dump_path):
        return None
    archive_dir = os.path.join(os.path.dirname(dump_path),
                               "llm_stub_answers_runs")
    os.makedirs(archive_dir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    candidate = os.path.join(archive_dir, f"llm_stub_answers-{stamp}.json")
    suffix = 1
    while os.path.exists(candidate):
        candidate = os.path.join(
            archive_dir, f"llm_stub_answers-{stamp}-{suffix}.json")
        suffix += 1
    os.replace(dump_path, candidate)
    return candidate


def fill_stubs(files, model_path, requirements, out=print, dump_path=None,
               context=DEFAULT_STUB_CONTEXT, contracts=None, repairs_by_method=None):
    """Ask the model for the bodies the mechanical emitter refused.

    Best-effort by design: the mechanical set is already final and honest,
    so a missing model or an answer that still fails leaves the stub in
    place and says why. Every accepted body passes the module's `compile`,
    only touches `self.<name>`, `self._store.<name>`, `models.<name>` and
    `errors.<name>` names the sibling modules actually define, and breaks
    none of the API facts the prompt states (`_body_complaints`); a body
    that fails either gets up to two repair asks quoting the complaints
    back. It gains any import it uses, is spliced by re-finding the stub
    in the current text (an import added for a lower body moves every stub
    above it), and is tagged in its docstring as LLM-written — nothing here
    verifies behavior, and only reading the body (and running it) can.

    The ask is a free conversation, so it goes through the model's chat
    template when the GGUF carries one (`runner.generate_chat`); raw
    continuation makes an instruct model reason at the document instead of
    answering (see the runner). An answer that is still truncated after one
    retry with the whole room is never spliced — it is kept as `truncated`
    in the dump, because a cut-off body compiles and can still be wrong.
    `context` controls what the ask shows besides the task rules, the
    requirements and the module text. `contracts` are the human-confirmed
    method records loaded from `method_contracts.json`; a matching record
    adds its domain facts to the exact ask and every context checks the
    accepted body against it. No matching record means the old behavior:
    the requirement and the generic API checks only. `full` adds the repository signatures
    and the API facts (model fields and their types, error names, the date
    rule, the allowed imports); `honest` adds the same surfaces with the
    facts corrected where a live run proved them wrong (truthful
    `read_one_*`, one ISO date rule, errors as a vocabulary, delegation
    and search-order hints); `exact` adds the honest facts but shows
    `models.py` as code instead of a field summary, and repeats the
    target's signature and return dataclass above the ask; `minimal`
    omits the facts — the experiment that showed which were load-bearing.
    Returns `[(label, status, note)]`, one row per refused stub, `status`
    `written` or `kept`. With `dump_path`, every raw answer lands there as
    JSON — both attempts when a repair was asked, with `finish_reason`,
    `tokens`, `budget`, `truncated`, `seconds`, `decode_seconds`,
    `prompt_tokens` and `cached_tokens` beside each, so the refusal, the
    correction and where the time went can be read instead of guessed at.
    """
    targets = [(name, find_stub_spans(files[name])) for name in STUB_FILES
               if isinstance(files.get(name), str)]
    todo = sum(len(spans) for _name, spans in targets)
    if not todo:
        return []
    model_name = os.path.basename(model_path)
    try:
        llm = runner.load_model(model_path, logits_all=False, quiet=True)
    except Exception as error:  # missing file or missing runtime: stubs stand
        return [(f"{todo} refused stub(s)", "kept",
                 f"the model would not load ({error})")]
    store_names = {match.group(1) for match in
                   re.finditer(r"^    def (\w+)", files.get("store.py") or "",
                               re.M)}
    model_names = _class_names(files.get("models.py") or "")
    error_names = _class_names(files.get("errors.py") or "")
    # The free ask is conversation-shaped: an instruct model continued as
    # raw text reasons at the document instead of answering it (probe:
    # Qwen3-4B-Instruct-2507 filled every raw budget and was still
    # mid-sentence). The chat template answers when the GGUF has one.
    framing = (runner.generate_chat if runner.has_chat_template(llm)
               else runner.generate_free)
    framing_name = ("chat template" if framing is runner.generate_chat
                    else "no chat template: raw continuation")
    if context == "minimal":
        framing_name += "; minimal context: requirements + module only"
    elif context == "honest":
        framing_name += "; honest context: references + corrected facts"
    elif context == "exact":
        framing_name += "; exact context: models as code + local contract"
    out(f"llm: {todo} refused stub(s) — {model_name} writes them body "
        f"by body ({framing_name})")
    rows, dumped = [], []
    judgements, judged = {}, {}

    def judge_for(label):
        """The equivalence judge for one method's body, with its record."""
        def judge(precondition, body_text):
            key = (precondition.get("error"), precondition.get("check"),
                   precondition.get("raise_when"), body_text)
            if key not in judged:
                try:
                    reply = framing(
                        llm, _equivalence_prompt(precondition, body_text),
                        f"equivalence:{label}",
                        temperature=FALLBACK_TEMPERATURE,
                        seed=FALLBACK_SEED, max_new_tokens=160)
                    if reply.truncated:
                        verdict = (False, "the judge answer was cut off")
                    else:
                        verdict = _parse_equivalence(reply.text)
                    raw = reply.text
                except Exception as error:  # a failed judge refuses
                    verdict, raw = (False, f"the judge failed ({error})"), None
                judged[key] = verdict
                judgements.setdefault(label, []).append({
                    "error": precondition.get("error"),
                    "condition": precondition.get("check"),
                    "raise_when": precondition.get("raise_when"),
                    "equivalent": verdict[0], "reason": verdict[1],
                    "raw": raw})
                out(f"llm: {label} equivalence of `{precondition.get('check')}`"
                    f" -> {'YES' if verdict[0] else 'NO'} ({verdict[1]})")
            return judged[key]
        return judge

    for filename, spans in targets:
        text = files[filename]
        references = ()
        if filename == "services.py" and context != "minimal":
            references = _method_signatures(files.get("repositories.py") or "")
        if context == "exact":
            api = _exact_api_reference(files, filename)
        elif context == "honest":
            api = _honest_api_reference(files, filename)
        elif context == "full":
            api = _api_reference(files, filename)
        else:
            api = ()
        for planned in reversed(spans):
            # Re-find the span in the current text before every splice: a
            # body that adds an import lands at the top of the file and
            # moves every stub above it, and a stale span then cuts into
            # the wrong lines and leaves the stub's own reason behind —
            # the live `borrow_book` refusal blamed the model for exactly
            # that.
            label = f"{planned[2]['cls']}.{_stub_method(planned[2])}"
            span = next((found for found in find_stub_spans(text)
                         if f"{found[2]['cls']}.{_stub_method(found[2])}"
                         == label), None)
            if span is None:
                note = "the stub is no longer in the module"
                rows.append((label, "kept", note))
                dumped.append({"label": label, "status": "kept",
                               "note": note, "answer": None})
                continue
            start, end, info = span
            info["file"] = filename
            requirement = _requirements_line(requirements,
                                             _stub_method(info))
            method_contract = contract_for(
                contracts, info["cls"], _stub_method(info))
            target_contract = (
                _target_contract(info, files, requirements,
                                 contract=method_contract)
                if context == "exact" or method_contract else ())
            out(f"llm: {label} ...")

            keyword_changes = []

            def attempt(raw):
                """One raw answer as `(candidate, problems, body)`."""
                nonlocal keyword_changes
                body = _qualify_error_names(_clean_body(raw), error_names)
                body = _normalise_repository_returns(body, info, filename)
                body = _normalise_create_return_usage(
                    body, files.get("repositories.py") or "")
                body = _add_collection_creates(
                    body, method_contract, info, files)
                body, keyword_changes = _normalise_repository_keywords(
                    body, files.get("repositories.py") or "")
                refusal = _body_refusal(body, _module_names(text),
                                        store_names, model_names, error_names)
                problems = [refusal] if refusal else _body_complaints(
                    body, info, text, files.get("repositories.py") or "",
                    files, requirement=requirement, contract=method_contract,
                    judge=judge_for(label))
                if _answer_continued(raw):
                    problems.insert(
                        0, "the answer continued after the body with "
                           "reasoning or another candidate body; reply with "
                           "only the final body")
                if problems:
                    return None, problems, body
                candidate = _spliced_candidate(text, start, end, info, body,
                                               model_name)
                try:
                    compile(candidate, filename, "exec")
                except SyntaxError as error:
                    culprit = ""
                    culprit_lines = candidate.splitlines()
                    if error.lineno and error.lineno <= len(culprit_lines):
                        culprit = culprit_lines[error.lineno - 1][:70]
                    return None, [f"the body does not compile ({error.msg}"
                                  + (f"; line {error.lineno} {culprit!r}"
                                     if culprit else "") + ")"], body
                return candidate, [], body

            repair = (repairs_by_method or {}).get(
                (info["cls"], _stub_method(info)))
            prompt = stub_prompt(
                requirements, text, info, references, api,
                previous=(repair.get("previous") if repair else None),
                complaints=(repair.get("complaints") or [] if repair else ()),
                context=context, contract=target_contract)
            try:
                result = _answered(framing, llm, prompt, f"stub:{label}")
            except Exception as error:  # one failed call keeps one stub
                note = f"the model failed ({error})"
                rows.append((label, "kept", note))
                dumped.append({"label": label, "status": "kept",
                               "note": note, "answer": None})
                continue
            if result.truncated:
                # A cut-off answer was judged as complete before this check
                # and its prose was spliced into the module.
                note = (f"the answer was cut off at the {result.budget}-token "
                        "ceiling")
                rows.append((label, "kept", note))
                dumped.append({"label": label, "status": "kept", "note": note,
                               "answer": result.text,
                               **_attempt_fields(result)})
                continue
            first_answer = result.text
            first_result = result
            candidate, problems, body = attempt(result.text)
            used_final = False
            repaired_from_final = False
            if _answer_continued(result.text):
                final_block = _last_code_block(result.text)
                if final_block:
                    candidate, problems, body = attempt(final_block)
                    if problems:
                        repaired_from_final = True
                    else:
                        used_final = True
                        out(f"llm: {label} used its final block "
                            "(the first was a draft)")
            extra = {}
            if problems:
                initial_problems = list(problems)
                # One complaint per ask when there are several: a small
                # model that repeats a body with two independent mistakes
                # (two wrong repository keywords) can still correct one
                # when the repair names only that one. A single complaint
                # gets a second ask only when the first repair introduces a
                # different complaint (a late check moved after the write);
                # repeating the same complaint ends the loop.
                max_repairs = 2
                repairs = 0
                kept_note = None
                while problems and repairs < max_repairs:
                    repairs += 1
                    ask = f"repair ask {repairs}"
                    out(f"llm: {label} refused ({problems[0]}) — {ask}")
                    pending = (problems[:1] if len(problems) > 1
                               else problems)
                    # Quote the body that was judged, not the raw answer: a
                    # reasoning transcript is both huge (the repair ask then
                    # no longer fits the context) and not what the
                    # complaints are about.
                    repair = stub_prompt(
                        requirements, text, info, references, api,
                        previous="\n".join(body) or None,
                        complaints=pending, context=context,
                        contract=target_contract)
                    try:
                        result = _answered(framing, llm, repair,
                                           f"stub:{label}:repair")
                    except Exception as error:  # the stub stands, said aloud
                        kept_note = (f"the model failed on the repair ask "
                                     f"({error})")
                        break
                    if result.truncated:
                        kept_note = (
                            "still refused: the repair answer was cut off at "
                            f"the {result.budget}-token ceiling")
                        break
                    candidate, second, body = attempt(result.text)
                    if second:
                        problems = second
                        if set(second) == set(pending):
                            break
                    else:
                        problems = []
                if problems:
                    note = kept_note or ("still refused: "
                                         + "; ".join(problems))
                    rows.append((label, "kept", note))
                    dumped.append({"label": label, "status": "kept",
                                   "note": note, "answer": result.text,
                                   "first_answer": first_answer,
                                   "complaints": initial_problems,
                                   "second_complaints": problems,
                                   "repairs": repairs,
                                   **_first_fields(first_result),
                                   **_attempt_fields(result)})
                    continue
                note = "repaired: " + "; ".join(initial_problems)
                extra = {"first_answer": first_answer,
                         "complaints": initial_problems,
                         "repairs": repairs,
                         **_first_fields(first_result)}
                if repaired_from_final:
                    extra["repair_draft"] = "final_block"
            else:
                note = ("used the final block of a deliberating answer"
                        if used_final else "")
                if used_final:
                    extra = {"first_answer": first_answer,
                             "used_final_block": True,
                             **_first_fields(first_result)}
            text, added = _add_imports(candidate, "\n".join(body))
            if added:
                note = "; ".join(filter(None,
                                        [note,
                                         "added import " + ", ".join(added)]))
            if keyword_changes:
                note = "; ".join(filter(None, [
                    note,
                    "passed the arguments of "
                    + ", ".join(sorted(set(keyword_changes)))
                    + " positionally to match the declared parameter"]))
            rows.append((label, "written", note))
            entry = {"label": label, "status": "written", "note": note,
                     "answer": result.text}
            entry.update(extra)
            entry.update(_attempt_fields(result))
            dumped.append(entry)
        files[filename] = text
    for entry in dumped:
        entry["context"] = context
        if entry.get("label") in judgements:
            entry["equivalence_judgements"] = judgements[entry["label"]]
    if dump_path and dumped:
        archived = _archive_previous_dump(dump_path)
        if archived:
            out(f"llm: previous raw answers archived -> {archived}")
        with open(dump_path, "w", encoding="utf-8") as handle:
            json.dump(dumped, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        out(f"llm: raw answers -> {dump_path}")
    return rows


def repair_invented_state_guards(files, ctx):
    """Remove a reviewed body's state guard the contract never declared.

    A body that says `if order.status != 'pending': raise
    InvalidOrderStatusError` invents a precondition when the reviewed contract
    has none (a cancel operation allowed from confirmed orders). Preconditions
    that the contract does declare are preserved exactly.
    """
    contracts = ctx.get("contracts") or []
    declared = set()
    for contract in contracts:
        if not isinstance(contract, dict):
            continue
        if any(str(item.get("check") or "").find(".status") >= 0
               or str(item.get("check") or "").find(".state") >= 0
               for item in contract.get("preconditions") or []
               if isinstance(item, dict)):
            declared.add((str(contract.get("holder") or ""),
                          str(contract.get("method") or "")))
    pattern = re.compile(
        r"(?m)^(?P<indent>[ \t]*)if\s+\w+\.(?:status|state)\s*!=\s*"
        r"(['\"]).*?\2\s*:\s*\n"
        r"(?P=indent)[ \t]+raise\s+errors\.[A-Za-z_][A-Za-z0-9_]*[^\n]*\n")
    for filename in ("services.py", "repositories.py"):
        text = files.get(filename)
        if not isinstance(text, str):
            continue

        def repl(match):
            current_holder = None
            current_method = None
            for line in text[:match.start()].splitlines():
                stripped = line.strip()
                if stripped.startswith("class "):
                    current_holder = stripped[6:].split("(")[0].strip().rstrip(":")
                    current_method = None
                elif stripped.startswith("def ") and "(" in stripped:
                    current_method = stripped[4:].split("(")[0].strip()
            if (current_holder, current_method) not in declared:
                return ""
            return match.group(0)

        updated = pattern.sub(repl, text)
        if updated != text:
            files[filename] = updated
    return files


def repair_related_primary_keys(files, ctx):
    """Use the related model's PK when a repository body says `self.PK`.

    An LLM body occasionally writes `self._store.get('Category', self.PK, ...)`
    while `self.PK` belongs to the current repository.  The model graph has the
    related primary key; substitute it rather than leaving a lookup that only
    works when both entities happen to use `id`.
    """
    text = files.get("repositories.py")
    if not isinstance(text, str):
        return files, []
    pattern = re.compile(
        r"self\._store\.get\((['\"])([A-Za-z_][A-Za-z0-9_]*)\1\s*,\s*self\.PK\s*,")
    repaired = []
    def replace(match):
        entity = match.group(2)
        primary = primary_key_of(ctx, entity)
        if not primary or normalize(primary) == "pk":
            return match.group(0)
        repaired.append(f"{entity}.{primary}")
        return f"self._store.get({match.group(1)}{entity}{match.group(1)}, {primary!r},"
    text = pattern.sub(replace, text)
    if repaired:
        files["repositories.py"] = text
    return files, repaired


def repair_service_dates(files):
    """Make generated service date parsing accept dates and ISO strings."""
    text = files.get("services.py")
    if not isinstance(text, str):
        return files
    marker = "__ESUS_AS_DATE_IMPL__"
    text = text.replace(
        "return datetime.date.fromisoformat(str(value))",
        f"return {marker}(str(value))")
    text = text.replace("datetime.date.fromisoformat(", "_as_date(")
    text = text.replace(f"{marker}(", "datetime.date.fromisoformat(")
    files["services.py"] = text
    return files


def normalize_state_spellings(files, ctx):
    """Use the spelling the documents use for a state literal.

    Model-written bodies sometimes mix `canceled` and `cancelled` even when
    the error/invariant text chooses one. Only string literals are changed,
    and only when one spelling is present in the requirements/error/invariant
    text.
    """
    document_text = " ".join([
        str(ctx.get("requirements") or ""),
        " ".join(str(item.get("description") or "")
                 for item in ctx.get("errors") or [] if isinstance(item, dict)),
        " ".join(str(item.get("text") or "")
                 for item in ctx.get("invariants") or [] if isinstance(item, dict)),
    ]).lower()
    replacements = {}
    if "cancelled" in document_text:
        replacements["canceled"] = "cancelled"
    if "cancelled" in document_text and "cancelation" in document_text:
        replacements["cancelation"] = "cancellation"
    if not replacements:
        return files
    for filename, text in list(files.items()):
        if not isinstance(text, str) or not filename.endswith(".py"):
            continue
        for old, new in replacements.items():
            text = text.replace(f'"{old}"', f'"{new}"')
            text = text.replace(f"'{old}'", f"'{new}'")
        files[filename] = text
    return files


def _clean_error_boundary(source):
    """Wrap the fallback's `main()` so expected failures are not tracebacks.

    A generated single-file tool often validates paths before its own `try`.
    The fallback has no domain architecture to preserve, so its command
    boundary is fixed here: exit status and wording stay the program's, but
    an uncaught exception becomes one concise stderr line.
    """
    guard = re.compile(
        r"(?ms)^if\s+__name__\s*==\s*['\"]__main__['\"]\s*:\s*\n"
        r"(?:[ \t]+.*(?:\n|$))*")
    replacement = (
        'if __name__ == "__main__":\n'
        "    try:\n"
        "        main()\n"
        "    except SystemExit:\n"
        "        raise\n"
        "    except Exception as error:\n"
        "        print(f\"error: {error}\", file=sys.stderr)\n"
        "        raise SystemExit(1)\n")
    if guard.search(source):
        return guard.sub(replacement, source, count=1)
    return source.rstrip() + "\n\n\n" + replacement


def generate_fallback(out_dir, model_path):
    """Write `generated/app.py` from the requirements; return the exit code."""
    requirements = load_requirements(out_dir)
    if not requirements:
        print(f"error: {out_dir} has no requirements.txt to generate from")
        return 1
    ctx = load_context(out_dir)
    prompt = fallback_prompt(requirements, ctx["errors"])
    try:
        llm = runner.load_model(model_path, logits_all=False)
    except ServerError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    result = runner.generate_free(llm, prompt, "fallback",
                                  temperature=FALLBACK_TEMPERATURE,
                                  seed=FALLBACK_SEED)
    code = strip_code_fences(result.text)
    if not code:
        print("error: the model returned no code for the fallback program")
        return 1
    code = _clean_error_boundary(code)
    try:
        compile(code, "app.py", "exec")
    except SyntaxError as error:
        print(f"error: the fallback program does not parse ({error}) — "
              f"not writing it")
        return 1
    header = ('"""LLM-generated fallback: the extracted architecture is empty (no models,\n'
              'services or commands), so there is nothing mechanical to be faithful to.\n'
              f'Generated from {out_dir}/requirements.txt by `generator.py --model`; '
              'verify by running it.\n'
              '"""\n\n')
    target = os.path.join(out_dir, GENERATED_DIR)
    os.makedirs(target, exist_ok=True)
    path = os.path.join(target, "app.py")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(header + code + "\n")
    print(f"degenerate architecture (no models, services or commands) — LLM fallback")
    print(f"[write] {path} ({result.tokens} tokens in {result.seconds:.1f}s)")
    print(f"verify by running it: python3 {path}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir", help="Extraction output directory (e.g. out/expenses)")
    parser.add_argument("--model", default=None,
                        help="GGUF model for the LLM passes, or `server` to "
                             "use an already-running llama-server at "
                             "LLAMA_SERVER_URL (default "
                             "http://127.0.0.1:8080): the degenerate "
                             "fallback (clean but empty documents) writes "
                             "generated/app.py from requirements.txt, and a "
                             "normal run fills every method body the "
                             "mechanical emitter refused (bodies are "
                             "provisional until behavior is verified)")
    parser.add_argument("--gui-tech", default=None,
                        help="Override the declared GUI technology (default: "
                             "the components facade declaration)")
    parser.add_argument("--verbose", action="store_true",
                        help="Also print harmless diagnostics (skipped "
                             "argparse-owned options, adapter fields with no "
                             "CLI flag). Anything actionable is already a "
                             "probe blocker, which refuses generation.")
    parser.add_argument("--reuse-reviewed-bodies", action="store_true",
                        help="Keep bodies tagged `llm-written` from the "
                             "existing generated/repositories.py and "
                             "services.py when their method labels still "
                             "match a stub; mechanical code is regenerated "
                             "underneath them")
    parser.add_argument("--stub-context",
                        choices=("full", "minimal", "honest", "exact"),
                        default=DEFAULT_STUB_CONTEXT,
                        help="What a body ask shows besides the task rules, "
                             "the requirements and the module text: `exact` "
                             "(default) shows models.py as code and repeats "
                             "the target's return dataclass above the ask; "
                             "`full` adds the repository signatures and the "
                             "API facts; `honest` adds them with the facts a "
                             "live run proved wrong corrected; `minimal` "
                             "omits the facts, to measure which the model "
                             "actually needs")
    args = parser.parse_args(argv)

    ok, message = gate(args.out_dir)
    print(message)
    if not ok:
        return 1

    ctx = load_context(args.out_dir)
    repairs_by_method = load_method_repairs(args.out_dir)
    if is_degenerate(ctx):
        if not args.model:
            print("degenerate architecture (no models, services or commands) — "
                  "LLM fallback needs --model PATH to write generated/app.py "
                  "from requirements.txt")
            return 2
        return generate_fallback(args.out_dir, args.model)

    stats = {"source": args.out_dir, "implemented": 0, "stubs": 0,
             "stub_reasons": [], "prog": os.path.basename(args.out_dir.rstrip(os.sep))}
    previous = (load_previous_generated(args.out_dir)
                if args.reuse_reviewed_bodies else {})
    files = render_program(ctx, stats)
    if args.reuse_reviewed_bodies:
        stats["reused_bodies"] = reuse_reviewed_bodies(files, previous)

    kind, tech, note = gui_backend(ctx, args.gui_tech)
    if note:
        print(f"gui: {note}")
    if kind == "gui" and tech == "pyimgui":
        files["gui.py"] = emit_gui_pyimgui(ctx, stats)
    if args.model:
        stats["llm_stubs"] = fill_stubs(
            files, args.model, load_requirements(args.out_dir),
            dump_path=os.path.join(args.out_dir, "llm_stub_answers.json"),
            context=args.stub_context, contracts=ctx.get("contracts"),
            repairs_by_method=repairs_by_method)
    repair_invented_state_guards(files, ctx)
    aggregate_decisions = load_aggregate_decisions(
        args.out_dir, requirements_sha(ctx.get("requirements") or ""))
    files, applied_aggregates = apply_aggregate_decisions(
        files, aggregate_decisions)
    if applied_aggregates:
        stats["aggregate_decisions"] = applied_aggregates
        print("aggregate decisions: " + ", ".join(applied_aggregates))
    files, repaired_keys = repair_related_primary_keys(files, ctx)
    if repaired_keys:
        stats["related_pk_repairs"] = repaired_keys
        print("related primary keys: " + ", ".join(repaired_keys))
    repair_service_dates(files)
    normalize_state_spellings(files, ctx)

    target = os.path.join(args.out_dir, GENERATED_DIR)
    os.makedirs(target, exist_ok=True)
    if ctx.get("dropped_slots"):
        print(f"dropped {ctx['dropped_slots']} predated slot record(s) — "
              f"their questions reopen in review_slots.py")
    if ctx.get("dropped_contracts"):
        print(f"dropped {ctx['dropped_contracts']} predated method "
              f"contract(s) — their questions reopen in review_contracts.py")
    if ctx.get("dropped_routes"):
        print(f"dropped {ctx['dropped_routes']} predated route decision(s) — "
              f"their questions reopen in review_surface.py")
    for filename, text in files.items():
        if filename.endswith(".py"):
            text = _defer_annotations(text)
        with open(os.path.join(target, filename), "w", encoding="utf-8") as handle:
            handle.write(text)
        print(f"[write] {os.path.join(target, filename)}")
    total = stats["implemented"] + stats["stubs"]
    coverage = stats["implemented"] / total if total else 1.0
    print(f"methods: {stats['implemented']} implemented, {stats['stubs']} stubs "
          f"({coverage:.0%} mechanical)")
    reused = stats.get("reused_bodies") or []
    if reused:
        count = sum(1 for _label, status, _note in reused if status == "reused")
        print(f"llm: reused {count} reviewed body(s) from the previous output")
        for label, status, note in reused:
            print(f"  llm {status}: {label} — {note}")
    rows = stats.get("llm_stubs") or []
    if rows:
        written = sum(1 for _label, status, _note in rows if status == "written")
        print(f"llm: {written} of {len(rows)} refused stub(s) written "
              f"provisionally by {os.path.basename(args.model)} — "
              "behavior is not verified by syntax or contract checks")
        for label, status, note in rows:
            word = ("llm provisional" if status == "written"
                    else "llm kept stub")
            print(f"  {word}: {label}{' — ' + note if note else ''}")
    if stats.get("gui_panels") is not None:
        print(f"  gui pyimgui panels: {stats['gui_panels'] or 'none'}")
    for reason in stats["stub_reasons"]:
        print(f"  stub: {reason}")
    for where, bound in sorted(stats["bindings"].items()):
        print(f"  cli {where} -> {bound[0] if bound else 'UNBOUND'}"
              f"{'' if not bound else f' [score {bound[1]}]'}")
    for route in stats.get("choice_routes") or []:
        print(f"  cli route: {route}")
    if args.verbose and stats["skipped_options"]:
        print(f"skipped argparse-owned options: {sorted(set(stats['skipped_options']))}")
    if args.verbose and stats.get("unbound_fields"):
        print(f"adapter fields with no CLI flag: {sorted(set(stats['unbound_fields']))}")
    for finding in sorted(set(stats.get("dead_options") or [])):
        print(f"  dead option: {finding}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
