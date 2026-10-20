#!/usr/bin/env python3
"""Generate a runnable Python program from extraction output.

The probe proves the documents agree; this writes the program they describe:

    python generator.py out/expenses

writes `out/expenses/generated/` — `models.py`, `errors.py`, `store.py`,
`repositories.py`, `services.py`, `cli.py` — and refuses (exit 1) when the
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

The CLI backend is `argparse` (stdlib) regardless of the declared technology —
porting a CLI facade to click is later work — and
each `(command, subcommand)` is bound to the adapter that serves its verb, the
binding baked into `cli.py` with its score beside it.

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
refused answer gets one repair ask carrying the exact complaint; a body
that still fails keeps the stub. Accepted docstrings are tagged
`[llm-written by ... — review]` and the method still counts as a stub in
the mechanical coverage, because nothing here verifies behavior — read the
body, and the run leaves every raw answer in `<out>/llm_stub_answers.json`.
"""

import argparse
import ast
import builtins
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import probe_readiness  # noqa: E402
from kernel import codegen  # noqa: E402
from kernel import tie_rules  # noqa: E402
from kernel.consistency.checks_surface import COMMAND_VERB_STEMS  # noqa: E402
from kernel.consistency.loader import load_documents, load_requirements  # noqa: E402
from kernel.consistency.naming import normalize  # noqa: E402
from kernel.consistency.report import Report  # noqa: E402
from kernel.extraction import runner  # noqa: E402
from kernel.extraction.contracts import (  # noqa: E402
    contract_for,
    load_method_contracts,
)
from kernel.extraction.decisions import requirements_sha  # noqa: E402

GENERATED_DIR = "generated"

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

# `method_slots.json` beside the documents: `{holder, method, pattern,
# slots, decided_by, requirements_sha}` from the slot review.
METHOD_SLOTS_NAME = "method_slots.json"
METHOD_SLOTS_KEY = "slots"

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

def load_context(output_dir):
    """The generation context: every body plus the indexes the emitters need."""
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
    mappings = {}
    if isinstance(ports, dict) and isinstance(ports.get("entity_mappings"), list):
        for mapping in ports["entity_mappings"]:
            if isinstance(mapping, dict) and mapping.get("entity"):
                mappings[normalize(mapping["entity"])] = mapping
    matches = documents.get("pattern_matches")
    if not isinstance(matches, list):
        matches = []
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
        "routes": routes,
        "dropped_routes": dropped_routes,
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
from typing import Any, Dict, List, Optional
"""


def emit_init(ctx, stats):
    lines = ['"""Generated program. Do not edit by hand: regenerate with `generator.py`."""',
             "",
             f"Source documents: {stats['source']}",
             f"Methods: {stats['implemented']} implemented, {stats['stubs']} stubs "
             "(each stub names its work order in its docstring).",
             "CLI backend is argparse (stdlib); the declared facade technology is",
             "recorded in the documents and porting the CLI to it is later work.",
             ""]
    return "\n".join(lines) + "\n"


def emit_models(ctx):
    lines = ['"""Data models. Every field defaults to None: the store assigns integer',
             'primary keys on insert, and updates merge only non-None values."""',
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
            if field.get("nullable"):
                pytype = f"Optional[{pytype}]"
            lines.append(f"    {codegen.sanitize(name)}: {pytype} = None")
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
                        entity, field_names)
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
             "from typing import Any, Dict, List, Optional, Union",
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
                                  table=query_table)
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


def _repo_body(ctx, strategy, detail, method, params, entity, model_cls, field_names, pk, fk_literal, table="self.ENTITY"):
    """The statement list of one repository method."""
    kind = strategy[5:] if strategy.startswith("crud:") else None
    err = method_error(ctx, method, entity)
    if kind == "create":
        return _create_body(ctx, method, params, entity, model_cls, field_names, fk_literal)
    if kind == "read_one":
        return _read_one_body(params, entity, model_cls, field_names, pk, err)
    if kind in ("read_all", "filter"):
        return _select_body(params, entity, model_cls, field_names, table=table)
    if kind == "update":
        return _update_body(ctx, method, params, entity, model_cls, field_names, err)
    if kind == "delete":
        return _delete_body(params, entity, field_names, err)
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



def _entity_params(params, entity_names):
    """Split `(raw, ident, type)` params into `(entity_param|None, scalars)`."""
    entity_param = None
    scalars = []
    for raw, ident, ptype in params:
        if entity_param is None and codegen.is_entity_type(ptype, entity_names):
            entity_param = (raw, ident)
        else:
            scalars.append((raw, ident))
    return entity_param, scalars


def _result_wrap(model_cls):
    if model_cls is None:
        return "return record"
    return f"return {model_cls}(**record)"


def _create_body(ctx, method, params, entity, model_cls, field_names, fk_literal):
    entity_param, scalars = _entity_params(params, ctx["entity_names"])
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
    lines.append(f"record = self._store.add(self.ENTITY, self.PK, values, check_fk={fk_literal})")
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
            lines = [f"record = self._store.get(self.ENTITY, self.PK, {ident}, error={err})"]
            lines.append(_result_wrap(model_cls))
            return lines
        alternatives = codegen.match_alternatives(field_names, raw)
        if alternatives is not None:
            lines = _alternative_scan(ident, alternatives)
            lines += ["if len(found) != 1:",
                      f"    raise {err}(f\"{entity} lookup matched {{len(found)}} records\")",
                      "record = found[0]"]
            lines.append(_result_wrap(model_cls))
            return lines
    lines = _criteria_block(params, field_names)
    lines += ["found = self._store.select(self.ENTITY, criteria)",
              "if len(found) != 1:",
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


def _update_body(ctx, method, params, entity, model_cls, field_names, err):
    entity_param, scalars = _entity_params(params, ctx["entity_names"])
    if not scalars:
        return ["raise ValueError(",
                f"    \"{entity}.{method.get('name')}: update needs key parameters\")"]
    alternatives = None
    if len(scalars) == 1:
        alternatives = codegen.match_alternatives(field_names, scalars[0][0])
    if alternatives is not None:
        lines = _alternative_scan(scalars[0][1], alternatives)
        lines += ["if len(found) != 1:",
                  f"    raise {err}(f\"{entity} update matched {{len(found)}} records\")"]
    else:
        lines = _criteria_block(scalars, field_names)
        lines += ["found = self._store.select(self.ENTITY, criteria)",
                  "if len(found) != 1:",
                  f"    raise {err}(f\"{entity} update matched {{len(found)}} records\")"]
    lines += ["patch = {}"]
    if entity_param is not None:
        lines.append(f"for key, value in _record_values({entity_param[1]}, {field_names!r}).items():")
        lines.append("    if value is not None:")
        lines.append("        patch[key] = value")
    for raw, ident in scalars:
        lines.append(f"if {ident} is not None and {raw!r} in {field_names!r}:")
        lines.append(f"    patch[{raw!r}] = {ident}")
    lines.append(f"record = self._store.update(self.ENTITY, self.PK, found[0][self.PK], patch, error={err})")
    lines.append(_result_wrap(model_cls))
    return lines


def _delete_body(params, entity, field_names, err):
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
              f"    raise {err}(f\"{entity} delete matched no records\")",
              "for record in found:",
              "    self._store.delete(self.ENTITY, self.PK, record[self.PK])",
              "return None"]
    return lines


# --------------------------------------------------------------------------
# services (delegate on exact same-name repo methods, else stub)
# --------------------------------------------------------------------------

def emit_services(ctx, repo_index, stats):
    """Service classes: same-name delegation or documented stubs."""
    lines = ['"""Services. A method with the same name as a repository method delegates',
             "to it; anything else raises NotImplementedError with its work order.",
             '"""',
             "",
             "from typing import Any, Dict, List, Optional, Union",
             "",
             "import calendar",
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
             '    raise ValueError(f"unknown operator {operator!r}")',
             ""]
    port_names = {normalize(r.get("interface_name") or "") for r in ctx["repositories"]}
    for service in ctx["services"]:
        name = service.get("service_name")
        if normalize(name) in port_names:
            continue
        cls = codegen.sanitize(name, "Service")
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
            delegate = _service_delegate(ctx, method, repo_index)
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
                        repo_cls, read_all, entity, field_names = composed
                        try:
                            body = _service_filter_body(
                                fname, declaration, returns, method, repo_cls,
                                read_all, entity, field_names, params, detail)
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
    return "\n".join(lines) + "\n"


def _record(stats, holder, method, strategy, implemented, how):
    """One row for the coverage meter: every method, mechanical or stub."""
    stats.setdefault("methods", []).append({
        "holder": holder, "method": method, "strategy": strategy,
        "implemented": implemented, "how": how,
    })


def _service_filter_body(fname, declaration, returns, method, repo_cls,
                         read_all, entity, field_names, params, detail):
    """A service filter over the entity's read-all, with kernel criteria.

    The criteria are the kernel's own field matching (`match_param`),
    resolved at generation time — the body filters exactly as the
    repository would, and a parameter no field satisfies refuses
    (`_Unmappable`) instead of emitting a body that raises when called.
    """
    lines = [
        "",
        f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
        f'        """{_docstring(method.get("description"))} '
        f'[composes {repo_cls}.{read_all} over {detail}]"""',
        f"        records = self._repos[{repo_cls!r}].{read_all}()",
        "        criteria = []",
    ]
    for raw, ident, _ in params:
        matched = codegen.match_param(field_names, raw)
        if matched is None:
            raise _Unmappable(raw)
        lines.append(f"        if {ident} is not None:")
        lines.append(f"            criteria.append(({matched[0]!r}, "
                     f"{matched[1]!r}, {ident}))")
    lines += [
        "        out = []",
        "        for record in records:",
        "            row = record if isinstance(record, dict) else vars(record)",
        "            if all(_holds(row.get(field), operator, value)",
        "                   for field, operator, value in criteria):",
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
            return _field_enum(ctx, entity, field.get("name") or field_name)
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
    if kind == "pattern" and payload in ("READ_ALL", "FILTER_BY_FIELD",
                                         "FILTER_WITH_PAGINATION"):
        strategy, _ = codegen.plan_method(method, entry, ctx["entity_names"])
        if (strategy == "stub" and not method.get("params")
                and _collection_return(method)):
            payload = "FILTER_CRITERION"
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
        if value not in _field_enum(ctx, entity, field):
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
    """True while spending stays within the budget limit, else False.

    Reads the matching budget record (scope comes from the method's own
    parameters, mapped by name onto budget fields), totals the spending
    entity's scoped records, and compares. No budget record means no limit:
    True, stated in the code. Only `bool` returns are emitted — a status
    vocabulary would be invented — and every parameter must scope something,
    or the check is not this shape.
    """
    returns = normalize(method.get("return_type") or "")
    if returns not in ("bool", "boolean"):
        return None
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
        f"    return True  # no budget record: no limit to exceed",
        f"limit = match[0].get({slots['limit_field']!r})",
        f"spent = 0",
        f"for record in self._store.select({spend_entity!r}, []):",
    ] + spend_lines + [
        f"    spent += record.get({target!r}) or 0",
        f"return spent <= limit if limit is not None else True",
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
            dest = codegen.bind_field(dests, field["field_name"])
            if dest is None or dest in used:
                ok = False
                break
            used.add(dest)
            bindings.append((field["field_name"], dest))
        if not ok:
            continue
        alternates.append((name, bindings))
    return alternates


def _route_action_key(actions, service, method):
    """An action key for a recorded route, synthesized when none exists.

    A routed method usually has no adapter action (that is why the flag is
    stranded); the virtual entry calls it with no arguments, which is what
    makes it a route candidate in the first place.
    """
    for name, spec in actions.items():
        if (isinstance(spec, dict)
                and spec.get("target_service") == service
                and spec.get("target_method") == method):
            return name
    key = codegen.sanitize(method, "route")
    while key in actions:
        key += "_route"
    actions[key] = {"action_name": key, "target_service": service,
                    "target_method": method, "input_fields": []}
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
        if _service_method(ctx, service, method) is None:
            continue
        key = _route_action_key(actions, service, method)
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
        for sname in ([None] if not subs else [s["name"] for s in subs]):
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
    return leaves, actions, argv, targets, assembled


def emit_cli(ctx, bindings, stats):
    """An argparse CLI: every declared verb parses; bound verbs dispatch.

    A leaf may bind several choices: recorded routes (a flag selecting a
    method the documents never linked it to), mechanical alternates (an
    adapter action every one of whose fields the leaf's flags supply, and
    whose own target method agrees with those field names), then the plain
    bound action as the fallback. The first choice whose flags are all
    passed wins; flags that select nothing are reported, not ignored.
    """
    repo_classes = [codegen.sanitize(r.get("interface_name") or r.get("entity"), "Repository")
                    for r in ctx["repositories"]]
    port_names = {normalize(r.get("interface_name") or "") for r in ctx["repositories"]}
    service_classes = [codegen.sanitize(s["service_name"], "Service") for s in ctx["services"]
                       if normalize(s["service_name"]) not in port_names]
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
             "CSV_LIST splits on commas, LOOKUP_ID coerces to int (existence is",
             "enforced by the repository's foreign-key check on write, or by the",
             "record lookup itself on read).",
             '"""',
             "",
             "import argparse",
             "import dataclasses",
             "import datetime",
             "import json",
             "import sys",
             "",
             "import models",
             "import errors",
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
             "        datetime.date.fromisoformat(str(value))",
             "        return value",
             '    if kind == "DECIMAL_TO_CENTS":',
             "        return int(round(float(value) * 100))",
             '    if kind == "CSV_LIST":',
              "        items = value if isinstance(value, list) else [value]",
              "        split = []",
              "        for part in items:",
              "            split.extend(p.strip() for p in str(part).split(\",\") if p.strip())",
              "        return split",
             '    if kind == "LOOKUP_ID":',
             "        return int(value)",
             '    if kind == "ENUM_LOOKUP":',
             "        return str(value)",
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
              "    (`-category` without `-month`): naming the missing flag beats",
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
              f"DEFAULT_DB = {stats['prog'] + '.db'!r}",
              "",
              "",
              "def build_parser():",
              f"    parser = argparse.ArgumentParser(prog={stats['prog']!r})",
              "    parser.add_argument('--db', default=None,",
              "                        help=('SQLite file for record storage "
              "(default: ' + DEFAULT_DB + ' in the working directory; "
              "use :memory: to stay in memory)'))",
              "    sub = parser.add_subparsers(dest='command')"]
    invocation = (ctx["components"].get("facade") or {}).get("invocation") or {}
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
            lines.append(f"    sub_{cvar} = p_{cvar}.add_subparsers(dest='subcommand')")
            for item in subs:
                sname = item["name"]
                svar = codegen.sanitize(sname, "sub")
                lines.append(f"    p_{cvar}_{svar} = sub_{cvar}.add_parser({sname!r})")
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
              "        if dest is None or present.get(_normalize(dest)) is None:",
              "            if required:",
              "                raise ValueError(f\"missing required field {field_name!r} for {action!r}\")",
              "            continue",
              "        value = _transform(kind, present[_normalize(dest)], field_name)",
              "        if targets.get(target_param) is not None:",
              "            grouped.setdefault(target_param, {})[field_name] = value",
              "        else:",
              "            grouped[target_param] = value",
              "    call_kwargs = {}",
              "    for target_param, value in grouped.items():",
              "        model_name = targets.get(target_param)",
              "        if model_name is not None and isinstance(value, dict):",
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
              "    store = Store(db_path)",
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
              "    binding = getattr(args, '_binding', None)",
              "    if binding is None:",
              "        parser.print_usage()",
              "        return 2",
              "    bound = BINDINGS.get(tuple(binding))",
              "    if bound is None:",
              "        print(f\"no adapter bound for {' '.join(binding)} — not implemented\")",
              "        return 1",
              "    values = {key: value for key, value in vars(args).items()",
              "              if key not in ('command', 'subcommand', '_binding', 'db')}",
              "    choice, present = _choose(bound, values)",
              "    trouble = _incomplete(choice, bound, present)",
              "    if trouble:",
              "        print(f\"error: {' '.join(binding)}: {trouble}\")",
              "        return 1",
              "    try:",
              "        _show(_call(choice, values, deps))",
              "    except Exception as error:",
              "        print(f\"error: {error}\")",
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
    }
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "kernel", "codegen_store_template.py"),
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
    if blockers:
        first = "; ".join(f"[{b.rule}] {b.message}" for b in blockers[:5])
        return False, f"refusing: {len(blockers)} generator blocker(s): {first}"
    if questions:
        return False, (f"refusing: {questions} open tie(s) need a human "
                       f"(python review_ties.py {output_dir})")
    return True, (f"gate passed ({len(risks)} residual risk(s); "
                   "gaps stay documented stubs)")


def is_degenerate(ctx):
    """True when the documents are clean but empty: nothing to be faithful to.

    A program with no models, services, repositories, adapters or commands
    (hello, cli_tool) has no architecture — the mechanical emitters would
    write an empty shell. The requirements alone describe the whole tiny
    program, so the generator may write it from them directly (LLM fallback)
    instead. Any single model, service or command disables the fallback.
    """
    commands = ((ctx["components"].get("facade") or {}).get("invocation") or {}).get("commands") or []
    return not (ctx["models"] or ctx["services"] or ctx["repositories"]
                or ctx["adapters"] or commands)


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
             "from store import Store",
             "import repositories",
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
             "    store = Store()",
             "    repos = {}",
             "    states = {}",
             "    for panel in PANELS:",
             "        repo = getattr(repositories, panel['repo'])(store)",
             "        repos[panel['entity']] = repo",
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
             "                _draw_panel(panel, repos[panel['entity']], state)",
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
    """The model repeated the stub instead of replacing its raise."""
    return bool(re.match(r"^\s*def \w+", text)) or "NotImplementedError" in text


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


def _declared_return(info):
    """The `models.X` a stub's own `-> ...` names, or None."""
    match = re.match(r"def \w+\([^)]*\)\s*->\s*(.+?):?$",
                     info.get("def") or "")
    return _first_model(match.group(1)) if match else None


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
                context="full", contract=()):
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
        ]
    else:
        call_rule = [
            "- Call only what the module shows: `self._store` methods used",
            "  in sibling bodies, `models.*`, `errors.*`, module helpers.",
            "  `_store.select` criteria support only `eq`, `ge` and `le` —",
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
        f"- The method is `{info['cls']}.{method}`; the emitter refused it"
        " with:",
        f"  {info['reason']}",
    ]
    lines += call_rule
    if context in ("honest", "exact") \
            and re.search(r"search|filter|find", method, re.I):
        lines += [
            "- A search or filter over several fields tests each field",
            "  independently: a record matching any one is a hit. Do not",
            "  put the fields in one `elif` chain — the later fields then",
            "  never run.",
        ]
    lines += [
        "- If the requirements do not determine the behavior, reply with",
        '  `raise NotImplementedError("...")` and nothing else.',
    ]
    if complaints:
        lines += [
            "",
            "Your previous answer to this method was refused:",
        ]
        lines += [f"  - {complaint}" for complaint in complaints]
        if previous:
            lines += [
                "",
                "The refused answer was:",
                "```python",
                previous.strip(),
                "```",
                "Write the body again, fixing exactly what was refused and",
                "keeping what was right.",
            ]
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
    lines += [
              "",
              f"Now write the body of `{info['cls']}.{method}`, replacing",
              "the `raise NotImplementedError(...)` statement:",
              "```python"]
    return "\n".join(lines) + "\n"


def _clean_body(text):
    """The model's answer as unindented body lines: fences and `def` gone.

    The answer keeps its own base indent (`keep_indent`) so a body written
    in the shown module's style — the usual case — dedents to zero here
    instead of leaving its first line shallower than the rest. The `def`
    line and an echoed docstring are dropped; the filler writes both itself.
    The stub ask ends with an open fence, so the answer is parsed as a
    continuation (`open_fence`).
    """
    lines = [line.rstrip() for line in
             extract_code(text, keep_indent=True, open_fence=True).splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and re.match(r"^\s*def \w+", lines[0]):
        lines.pop(0)  # the whole method came back; only its body goes in
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines:
        opener = re.match(r'^\s*[rubf]{0,2}("""|\'\'\')', lines[0])
        if opener:  # the model echoed the docstring; the filler rewrites it
            closing = opener.group(1)
            tail = lines.pop(0)[opener.end():]
            while closing not in tail and lines:
                tail = lines.pop(0)
    indents = [len(line) - len(line.lstrip(" ")) for line in lines
               if line.strip()]
    if not indents:
        return []
    trim = min(indents)
    return [line[trim:] if line.strip() else "" for line in lines]


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
    definition is a NameError waiting to happen.
    """
    names = set()
    for node in ast.parse(text).body:
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
        lines.append("- `self._store` reads return plain records (dicts):")
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
        lines.append('- Date fields hold ISO strings (`"2026-10-05"`):')
        lines.append("  compare and slice them as strings; convert with")
        lines.append("  `datetime.date.fromisoformat` /")
        lines.append("  `datetime.datetime.fromisoformat` only for date")
        lines.append("  arithmetic.")
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
        lines.append("- `self._store` reads return plain records (dicts):")
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
        lines.append("- The store normalizes `datetime.date`/`datetime.datetime`")
        lines.append("  values to ISO strings on write, so values read back are")
        lines.append('  ISO text (`"2026-10-05"`, `"2026-10-05T14:30:00"`).')
        lines.append("  Compare them as strings; use `fromisoformat` for")
        lines.append("  arithmetic and store a datetime (or its `.isoformat()`)")
        lines.append('  back. Never `strftime("%Y-%m-%d %H:%M:%S")`:')
        lines.append("  space-separated text does not match the stored ISO")
        lines.append("  strings.")
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
            "- `self._store` reads return plain records (dicts):",
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
            "  `datetime.datetime`, but the store normalizes them to ISO",
            "  strings on write and hands them back as strings. Values you",
            '  read are ISO text (`"2026-10-05"`, `"2026-10-05T14:30:00"`);',
            "  compare them as strings, use `fromisoformat` for arithmetic,",
            "  and store a datetime (or its `.isoformat()`) back. Never",
            '  `strftime("%Y-%m-%d %H:%M:%S")`: space-separated text does',
            "  not match the stored ISO strings.",
        ]
        if filename == "services.py":
            lines += [
                "- Changing a dataclass does not save it: write through the",
                "  repository's `update_*` method; returning a mutated",
                "  object alone saves nothing.",
            ]
        else:
            lines += [
                "- Changing a record dict does not save it: write through",
                "  `self._store.update(...)`.",
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
        if method and re.search(rf"\b{re.escape(method)}\s*\(", line):
            return line.strip()
    return ""


def _contract_lines(contract):
    """The human's method contract as prompt lines.

    The generator knows the schema, never the domain: every name below comes
    from the record. A library return and a stock consumption render through
    the same function.
    """
    if not contract:
        return []
    lines = ["The human-confirmed contract for this method:"]
    preconditions = contract.get("preconditions") or []
    if preconditions:
        lines.append("  preconditions:")
        for item in preconditions:
            error = item.get("error")
            suffix = f"; otherwise raise `{error}`" if error else ""
            lines.append(f"    - `{item['check']}`{suffix}")
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
    effects = contract.get("effects") or []
    if effects:
        lines.append("  effects:")
        for item in effects:
            target, op = item["target"], item["op"]
            detail = ""
            if op == "set":
                detail = (f" to `{item['value']}`" if "value" in item else "")
            elif "by" in item:
                detail = f" by `{item['by']}`"
            write = item.get("write")
            suffix = f"; save it with `{write}(...)`" if write else ""
            lines.append(f"    - {op} `{target}`{detail}{suffix}")
    order = contract.get("order") or []
    if order:
        lines.append("  order: " + " -> ".join(f"`{step}`" for step in order))
    forbid = contract.get("forbid") or []
    if forbid:
        lines.append("  forbidden:")
        for item in forbid:
            message = f": {item['message']}" if item.get("message") else ""
            lines.append(
                f"    - `{item['target']}` must not read `{item['reads']}`"
                f"{message}")
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
                     requirement="", contract=None):
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
    returns = {}
    for source_text in (module_text, references_text or ""):
        for match in re.finditer(r"def (\w+)\([^)]*\)\s*->\s*([^:]+):",
                                 source_text):
            returns.setdefault(match.group(1), match.group(2))
    typed, read_names = {}, set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Call)):
            continue
        name = node.targets[0].id
        func = node.value.func
        cls = None
        if (isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "models"
                and func.attr in fields):
            cls = func.attr
        elif isinstance(func, ast.Attribute) and func.attr in returns:
            cls = _direct_model(returns[func.attr])
            if cls and not func.attr.startswith(("create_", "update_")):
                read_names.add(name)
        if cls:
            typed[name] = cls
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
                and node.func.attr.startswith("update_")):
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
    writes = [node for node in ast.walk(tree)
              if (isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute)
                  and node.func.attr.startswith("create_")
                  and not _in_nested_function(node, parents))]
    raises = [node for node in ast.walk(tree)
              if isinstance(node, ast.Raise)
              and not _in_nested_function(node, parents)]
    for write in writes:
        chain = _block_chain(write, parents)
        if not chain:
            continue
        for raised in raises:
            if raised.lineno <= write.lineno:
                continue
            if _block_chain(raised, parents)[:len(chain)] != chain:
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
                actual = _first_model(returns.get(method, ""))
                if actual and actual != declared:
                    key = (name, method, actual)
                    if key not in reported:
                        reported.add(key)
                        found.append(
                            f"returns `{name}` from `{method}(...)` "
                            f"(a {actual}) but the method is declared "
                            f"`-> models.{declared}`")
                    break
    found.extend(_contract_complaints(tree, contract))
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


def _field_writes(tree, field):
    """Every assignment whose target writes `field`, with its right-hand side."""
    writes = []
    for node in ast.walk(tree):
        targets, value = _assignment(node)
        if any(field in _target_names_of(target) for target in targets):
            writes.append((node, value))
    return writes


def _mentions_field(node, field):
    """True when an expression reads `field` as an attribute or string key."""
    if node is None:
        return False
    return any(field in _target_names_of(inner) for inner in ast.walk(node))


def _call_names(tree):
    """Method names called anywhere in the body (`update_book`, `now`, ...)."""
    return {node.func.attr for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)}


def _raise_names(tree):
    """Exception names raised anywhere in the body."""
    return {_raised_name(node) for node in ast.walk(tree)
            if isinstance(node, ast.Raise)}


def _contract_complaints(tree, contract):
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
                if isinstance(node, ast.Assign) \
                        and isinstance(value, ast.BinOp) \
                        and isinstance(value.op, wanted) \
                        and (_mentions_field(value.left, field)
                             or _mentions_field(value.right, field)):
                    matched = True
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
                == "now" and "now" not in calls:
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
        if call and _last_name(call) not in calls:
            found.append(
                f"the confirmed contract creates `{create.get('class') or 'a record'}` "
                f"through `{call}(...)`, but the body never calls "
                f"`{_last_name(call)}`")

    for precondition in contract.get("preconditions") or []:
        error = precondition.get("error")
        if error and _last_name(error) not in raises:
            found.append(
                f"the confirmed contract requires `{precondition.get('check')}` "
                f"to raise `{error}`, but the body never raises it")

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
    return {"finish_reason": result.finish_reason, "tokens": result.tokens,
            "budget": result.budget, "truncated": result.truncated}


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


def fill_stubs(files, model_path, requirements, out=print, dump_path=None,
               context="full", contracts=None):
    """Ask the model for the bodies the mechanical emitter refused.

    Best-effort by design: the mechanical set is already final and honest,
    so a missing model or an answer that still fails leaves the stub in
    place and says why. Every accepted body passes the module's `compile`,
    only touches `self.<name>`, `self._store.<name>`, `models.<name>` and
    `errors.<name>` names the sibling modules actually define, and breaks
    none of the API facts the prompt states (`_body_complaints`); a body
    that fails either gets one repair ask quoting the complaints back. It
    gains any import it uses, is spliced by re-finding the stub in the
    current text (an import added for a lower body moves every stub above
    it), and is tagged in its docstring as LLM-written — nothing here
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
    `tokens`, `budget` and `truncated` beside each, so the refusal and the
    correction can be read instead of guessed at.
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

            def attempt(raw):
                """One raw answer as `(candidate, problems, body)`."""
                body = _clean_body(raw)
                refusal = _body_refusal(body, _module_names(text),
                                        store_names, model_names, error_names)
                problems = [refusal] if refusal else _body_complaints(
                    body, info, text, files.get("repositories.py") or "",
                    files, requirement=requirement, contract=method_contract)
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

            prompt = stub_prompt(requirements, text, info, references, api,
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
                out(f"llm: {label} refused ({problems[0]}) — one repair ask")
                # Quote the body that was judged, not the raw answer: a
                # reasoning transcript is both huge (the repair ask then no
                # longer fits the context) and not what the complaints are
                # about.
                repair = stub_prompt(requirements, text, info, references,
                                     api, previous="\n".join(body) or None,
                                     complaints=problems, context=context,
                                     contract=target_contract)
                try:
                    result = _answered(framing, llm, repair,
                                       f"stub:{label}:repair")
                except Exception as error:  # the stub stands, said aloud
                    note = f"the model failed on the repair ask ({error})"
                    rows.append((label, "kept", note))
                    dumped.append({"label": label, "status": "kept",
                                   "note": note, "answer": first_answer,
                                   "complaints": problems,
                                   **_attempt_fields(result)})
                    continue
                if result.truncated:
                    note = ("still refused: the repair answer was cut off at "
                            f"the {result.budget}-token ceiling")
                    rows.append((label, "kept", note))
                    dumped.append({"label": label, "status": "kept",
                                   "note": note, "answer": result.text,
                                   "first_answer": first_answer,
                                   "complaints": problems,
                                   "second_complaints": [],
                                   **_first_fields(first_result),
                                   **_attempt_fields(result)})
                    continue
                candidate, second, body = attempt(result.text)
                if second:
                    note = "still refused: " + "; ".join(second)
                    rows.append((label, "kept", note))
                    dumped.append({"label": label, "status": "kept",
                                   "note": note, "answer": result.text,
                                   "first_answer": first_answer,
                                   "complaints": problems,
                                   "second_complaints": second,
                                   **_first_fields(first_result),
                                   **_attempt_fields(result)})
                    continue
                note = "repaired: " + "; ".join(problems)
                extra = {"first_answer": first_answer,
                         "complaints": problems,
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
            rows.append((label, "written", note))
            entry = {"label": label, "status": "written", "note": note,
                     "answer": result.text}
            entry.update(extra)
            entry.update(_attempt_fields(result))
            dumped.append(entry)
        files[filename] = text
    for entry in dumped:
        entry["context"] = context
    if dump_path and dumped:
        with open(dump_path, "w", encoding="utf-8") as handle:
            json.dump(dumped, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        out(f"llm: raw answers -> {dump_path}")
    return rows


def generate_fallback(out_dir, model_path):
    """Write `generated/app.py` from the requirements; return the exit code."""
    requirements = load_requirements(out_dir)
    if not requirements:
        print(f"error: {out_dir} has no requirements.txt to generate from")
        return 1
    ctx = load_context(out_dir)
    prompt = fallback_prompt(requirements, ctx["errors"])
    llm = runner.load_model(model_path, logits_all=False)
    result = runner.generate_free(llm, prompt, "fallback",
                                  temperature=FALLBACK_TEMPERATURE,
                                  seed=FALLBACK_SEED)
    code = strip_code_fences(result.text)
    if not code:
        print("error: the model returned no code for the fallback program")
        return 1
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
                        help="GGUF model for the LLM passes: the degenerate "
                             "fallback (clean but empty documents) writes "
                             "generated/app.py from requirements.txt, and a "
                             "normal run fills every method body the "
                             "mechanical emitter refused (bodies are tagged "
                             "`llm-written`; read them before trusting them)")
    parser.add_argument("--gui-tech", default=None,
                        help="Override the declared GUI technology (default: "
                             "the components facade declaration)")
    parser.add_argument("--verbose", action="store_true",
                        help="Also print harmless diagnostics (skipped "
                             "argparse-owned options, adapter fields with no "
                             "CLI flag). Anything actionable is already a "
                             "probe blocker, which refuses generation.")
    parser.add_argument("--stub-context",
                        choices=("full", "minimal", "honest", "exact"),
                        default="full",
                        help="What a body ask shows besides the task rules, "
                             "the requirements and the module text: `full` "
                             "(default) adds the repository signatures and "
                             "the API facts; `honest` adds them with the "
                             "facts a live run proved wrong corrected; "
                             "`exact` shows models.py as code and repeats "
                             "the target's return dataclass above the ask; "
                             "`minimal` omits the facts, to measure which "
                             "the model actually needs")
    args = parser.parse_args(argv)

    ok, message = gate(args.out_dir)
    print(message)
    if not ok:
        return 1

    ctx = load_context(args.out_dir)
    if is_degenerate(ctx):
        if not args.model:
            print("degenerate architecture (no models, services or commands) — "
                  "LLM fallback needs --model PATH to write generated/app.py "
                  "from requirements.txt")
            return 2
        return generate_fallback(args.out_dir, args.model)

    stats = {"source": args.out_dir, "implemented": 0, "stubs": 0,
             "stub_reasons": [], "prog": os.path.basename(args.out_dir.rstrip(os.sep))}
    files = render_program(ctx, stats)

    kind, tech, note = gui_backend(ctx, args.gui_tech)
    if note:
        print(f"gui: {note}")
    if kind == "gui" and tech == "pyimgui":
        files["gui.py"] = emit_gui_pyimgui(ctx, stats)
    if args.model:
        stats["llm_stubs"] = fill_stubs(
            files, args.model, load_requirements(args.out_dir),
            dump_path=os.path.join(args.out_dir, "llm_stub_answers.json"),
            context=args.stub_context, contracts=ctx.get("contracts"))

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
        with open(os.path.join(target, filename), "w", encoding="utf-8") as handle:
            handle.write(text)
        print(f"[write] {os.path.join(target, filename)}")
    total = stats["implemented"] + stats["stubs"]
    coverage = stats["implemented"] / total if total else 1.0
    print(f"methods: {stats['implemented']} implemented, {stats['stubs']} stubs "
          f"({coverage:.0%} mechanical)")
    rows = stats.get("llm_stubs") or []
    if rows:
        written = sum(1 for _label, status, _note in rows if status == "written")
        print(f"llm: {written} of {len(rows)} refused stub(s) written by "
              f"{os.path.basename(args.model)} — read the tagged bodies "
              f"before trusting them")
        for label, status, note in rows:
            word = "llm written" if status == "written" else "llm kept stub"
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
