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
"""

import argparse
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
from kernel.extraction.decisions import requirements_sha  # noqa: E402

GENERATED_DIR = "generated"

# Patterns whose slots a human can answer (see review_slots.py): with every
# required slot recorded, the emitters below write the body mechanically.
# Guard patterns are deliberately absent — a guard must run its check, never
# delegate past it or reduce to a scan; those stay stubs until we design them.
SLOT_PATTERNS = frozenset({"AGGREGATE_BY_FK", "AGGREGATE_BY_FK_AND_DATE",
                            "THRESHOLD_SCAN", "BUDGET_OVERFLOW_GUARD"})
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


# --------------------------------------------------------------------------
# document access
# --------------------------------------------------------------------------

def load_context(output_dir):
    """The generation context: every body plus the indexes the emitters need."""
    report = Report(os.path.basename(output_dir.rstrip(os.sep)))
    documents = load_documents(output_dir, report)
    models = [m for m in (documents.get("data_models") or []) if isinstance(m, dict) and m.get("name")]
    errors = [e for e in (documents.get("errors") or []) if isinstance(e, dict) and e.get("name")]
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
    current = requirements_sha(load_requirements(output_dir))
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
    return {
        "models": models,
        "errors": errors,
        "services": services,
        "repositories": repositories,
        "mappings": mappings,
        "match_index": match_index,
        "adapters": adapters,
        "components": components,
        "entity_names": [m["name"] for m in models],
        "slots": slots,
        "dropped_slots": dropped,
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
                slot_detail = ", ".join(
                    f"{slot}={slots[slot]}"
                    for slot in SLOT_REQUIREMENTS.get(pattern, ())
                    if slots.get(slot) not in (None, ""))
                lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                          f'        """{_docstring(method.get("description"))} '
                          f'[{pattern} via answered slots: {slot_detail}]"""']
                field_types = {name: (field.get("type") or "")
                               for name, field in fields_of(ctx, entity)}
                body = _repo_slot_body(ctx, entity, model_cls, field_types,
                                       method, pattern, slots)
                lines.extend("        " + line if line else "" for line in body)
                stats["implemented"] += 1
                _record(stats, holder, method["name"], strategy, True,
                        f"slots:{pattern}")
                continue
            lines += ["", f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
                      f'        """{_docstring(method.get("description"))} [{strategy}: {detail}]"""']
            body = _repo_body(ctx, strategy, detail, method, params, entity,
                              model_cls, field_names, pk, fk_literal)
            lines.extend("        " + line if line else "" for line in body)
            if strategy.startswith("crud:"):
                stats["implemented"] += 1
                _record(stats, holder, method["name"], strategy, True, "crud")
            else:
                stats["stubs"] += 1
                stats["stub_reasons"].append(f"{cls}.{fname}: {detail}")
                _record(stats, holder, method["name"], strategy, False, detail)
    return "\n".join(lines) + "\n"


def _repo_body(ctx, strategy, detail, method, params, entity, model_cls, field_names, pk, fk_literal):
    """The statement list of one repository method."""
    kind = strategy[5:] if strategy.startswith("crud:") else None
    err = method_error(ctx, method, entity)
    if kind == "create":
        return _create_body(ctx, method, params, entity, model_cls, field_names, fk_literal)
    if kind == "read_one":
        return _read_one_body(params, entity, model_cls, field_names, pk, err)
    if kind in ("read_all", "filter"):
        return _select_body(params, entity, model_cls, field_names)
    if kind == "update":
        return _update_body(ctx, method, params, entity, model_cls, field_names, err)
    if kind == "delete":
        return _delete_body(params, entity, field_names, err)
    name = method.get("name") if isinstance(method.get("name"), str) else "?"
    return ["raise NotImplementedError(",
            f'    "{entity}.{name}: {strategy}: {detail}")']


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


def _criteria_block(params, entity, field_names):
    """`criteria = [...]`; each param is `(raw, ident[, type])`, `None` skipped."""
    lines = ["criteria = []"]
    for item in params:
        raw, ident = item[0], item[1]
        lines.append(f"if {ident} is not None:")
        lines.append(f"    matched = match_criterion({field_names!r}, {raw!r})")
        lines.append("    if matched is None:")
        lines.append(f"        raise ValueError(f\"cannot filter {entity} by {raw!r}\")")
        lines.append("    field, operator = matched")
        lines.append(f"    criteria.append((field, operator, {ident}))")
    return lines


def _read_one_body(params, entity, model_cls, field_names, pk, err):
    """Lookup one record: by PK directly, else criteria plus uniqueness.

    The old fast path read every single-parameter lookup through the
    primary key — `read_x_by_email(email)` searched `PK == email` and
    reported "not found" instead of finding. Now only a parameter mapping
    to the PK with `eq` takes it; anything else goes through criteria
    (unmappable parameters fail loudly there, as everywhere).
    """
    if len(params) == 1:
        matched = codegen.match_param(field_names, params[0][0])
        if matched is not None and list(matched) == [pk, "eq"]:
            lines = [f"record = self._store.get(self.ENTITY, self.PK, {params[0][1]}, error={err})"]
            lines.append(_result_wrap(model_cls))
            return lines
    lines = _criteria_block(params, entity, field_names)
    lines += ["found = self._store.select(self.ENTITY, criteria)",
              "if len(found) != 1:",
              f"    raise {err}(f\"{entity} lookup matched {{len(found)}} records\")",
              "record = found[0]"]
    lines.append(_result_wrap(model_cls))
    return lines


def _select_body(params, entity, model_cls, field_names):
    lines = _criteria_block(params, entity, field_names)
    lines.append("found = self._store.select(self.ENTITY, criteria)")
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
    lines = _criteria_block(scalars, entity, field_names)
    lines += ["found = self._store.select(self.ENTITY, criteria)",
              "if len(found) != 1:",
              f"    raise {err}(f\"{entity} update matched {{len(found)}} records\")",
              "patch = {}"]
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
    lines = _criteria_block(params, entity, field_names)
    lines += ["found = self._store.select(self.ENTITY, criteria)",
              "if not found:",
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
                        lines += _service_filter_body(
                            fname, declaration, returns, method, repo_cls,
                            read_all, entity, field_names, params, detail)
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

    The criteria are the kernel's own field matching (`match_criterion`),
    so the body filters exactly as the repository would — same fields, same
    operators, same fail-loud on unmappable parameters.
    """
    values = ", ".join(f"{raw!r}: {ident}" for raw, ident, _ in params)
    return [
        "",
        f"    def {fname}(self{', ' + declaration if declaration else ''}) -> {returns}:",
        f'        """{_docstring(method.get("description"))} '
        f'[composes {repo_cls}.{read_all} over {detail}]"""',
        f"        records = self._repos[{repo_cls!r}].{read_all}()",
        f"        fields = {field_names!r}",
        "        criteria = []",
        f"        values = {{{values}}}",
        "        for param, value in values.items():",
        "            if value is None:",
        "                continue",
        "            matched = match_criterion(fields, param)",
        "            if matched is None:",
        '                raise ValueError(f"cannot filter '
        f'{entity} by {{param!r}}")',
        "            field, operator = matched",
        "            criteria.append((field, operator, value))",
        "        out = []",
        "        for record in records:",
        "            row = record if isinstance(record, dict) else vars(record)",
        "            if all(_holds(row.get(field), operator, value)",
        "                   for field, operator, value in criteria):",
        "                out.append(record)",
        "        return out",
    ]


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
}
SERVICE_BUDGET_SLOTS = ("create_method", "aggregate_method", "budget_method",
                        "amount_field", "date_field", "limit_field", "error")


def _slot_pattern(ctx, holder, method):
    """The slottable pattern id for a method, or None (with its slots)."""
    entry = _match_entry(ctx, holder, method.get("name"))
    if not isinstance(entry, dict):
        return None, {}
    kind, payload = tie_rules.effective_directive(entry)
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
    return None


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

def _emit_options(indent, parser_var, options, stats):
    """`add_argument` lines; argparse already owns `help`/`version`.

    A flag string taken twice on one parser (the documents give `-a` to two
    options of `book list`) cannot register twice: the option keeps its free
    strings, or is skipped with none left — reported, since one flag goes
    unreachable either way.
    """
    lines = []
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
        otype = (option.get("type") or "str").strip().lower()
        required = bool(option.get("required"))
        default = option.get("default")
        parts = [f"{flag!r}" for flag in flags]
        if otype == "bool":
            parts.append("action='store_true'" if not default else "action='store_false'")
            if default:
                parts.append("default=True")
        elif otype == "list":
            parts.append("nargs='*'")
            if default is not None:
                parts.append(f"default={default!r}")
        else:
            parts.append(f"type={ {'str': 'str', 'int': 'int', 'float': 'float'}.get(otype, 'str')}")
            parts.append(f"required={required!r}")
            if default is not None:
                parts.append(f"default={default!r}")
        parts.append(f"dest={dest!r}")
        lines.append(f"{indent}{parser_var}.add_argument({', '.join(parts)})")
    return lines


def emit_cli(ctx, bindings, stats):
    """An argparse CLI: every declared verb parses; bound verbs dispatch."""
    repo_classes = [codegen.sanitize(r.get("interface_name") or r.get("entity"), "Repository")
                    for r in ctx["repositories"]]
    port_names = {normalize(r.get("interface_name") or "") for r in ctx["repositories"]}
    service_classes = [codegen.sanitize(s["service_name"], "Service") for s in ctx["services"]
                       if normalize(s["service_name"]) not in port_names]
    model_names = [codegen.sanitize(m["name"], "Model") for m in ctx["models"]]
    actions = {a["action_name"]: a for a in ctx["adapters"]}
    invocation = (ctx["components"].get("facade") or {}).get("invocation") or {}
    argv = codegen.action_argv(ctx["adapters"], bindings, invocation)
    targets = codegen.action_targets(ctx["adapters"], ctx["services"], ctx["repositories"], ctx["entity_names"])
    assembled = {}
    for name, adapter in actions.items():
        assembled[name] = [
            f["field_name"] for f in adapter.get("input_fields") or []
            if isinstance(f, dict) and f.get("field_name")
            and codegen.is_assembly_field(adapter, f["field_name"], targets.get(name, {}))]
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
    lines += ["", "", "BINDINGS = {  # (command, subcommand) -> (action, score)"]
    for (command, sub), bound in sorted(bindings.items(), key=lambda item: str(item[0])):
        if bound is None:
            lines.append(f"    {(command, sub)!r}: None,")
            stats["unmapped"].append(f"{command} {sub}" if sub else f"{command}")
        else:
            action, score = bound
            lines.append(f"    {(command, sub)!r}: ({action!r}, {score}),")
    lines.append("}")
    lines += ["", "",
              "def _normalize(text):",
              '    return "".join(c for c in str(text).lower() if c.isalnum())',
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
    for command in invocation.get("commands") or []:
        if not isinstance(command, dict) or not command.get("name"):
            continue
        cname = command["name"]
        cvar = codegen.sanitize(cname, "cmd")
        subs = [s for s in (command.get("subcommands") or [])
                if isinstance(s, dict) and s.get("name")]
        if not subs:
            options = codegen.leaf_options(invocation, cname, None)
            lines.append(f"    p_{cvar} = sub.add_parser({cname!r})")
            lines.extend(_emit_options("    ", f"p_{cvar}", options, stats))
            lines.append("    p_" + cvar + ".set_defaults(_binding=" + repr((cname, None)) + ")")
        else:
            lines.append(f"    p_{cvar} = sub.add_parser({cname!r})")
            lines.append(f"    sub_{cvar} = p_{cvar}.add_subparsers(dest='subcommand')")
            for item in subs:
                sname = item["name"]
                svar = codegen.sanitize(sname, "sub")
                options = codegen.leaf_options(invocation, cname, sname)
                lines.append(f"    p_{cvar}_{svar} = sub_{cvar}.add_parser({sname!r})")
                lines.extend(_emit_options("    ", f"p_{cvar}_{svar}", options, stats))
                lines.append("    p_" + cvar + "_" + svar + ".set_defaults(_binding=" + repr((cname, sname)) + ")")
    lines += ["    return parser",
              "",
              "",
              "def _call(bound, values, deps):",
              "    action, _score = bound",
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
              "    try:",
              "        _show(_call(bound, values, deps))",
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


def extract_code(text):
    """The model's code: the ```python block when fenced, else the bare text.

    Told to emit bare code, the model usually obeys (cli_tool) but sometimes
    narrates first and fences second (hello) — taking the whole text then
    writes prose into app.py. A fenced block wins over surrounding prose; a
    ```python tag wins over a bare fence; bare text passes through for the
    caller to compile-check.
    """
    stripped = (text or "").strip()
    if "```" not in stripped:
        return stripped
    import re
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", stripped, re.DOTALL)
    if not blocks:
        return stripped
    for block in blocks:
        if block.strip():
            return block.strip()
    return ""


def strip_code_fences(text):
    """Backward-compatible wrapper over `extract_code` (same contract)."""
    return extract_code(text)


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
                        help="GGUF model for the degenerate fallback: when the "
                             "documents are clean but empty (no models, services "
                             "or commands), the whole tiny program is written "
                             "from requirements.txt instead of an empty shell")
    parser.add_argument("--gui-tech", default=None,
                        help="Override the declared GUI technology (default: "
                             "the components facade declaration)")
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

    target = os.path.join(args.out_dir, GENERATED_DIR)
    os.makedirs(target, exist_ok=True)
    if ctx.get("dropped_slots"):
        print(f"dropped {ctx['dropped_slots']} predated slot record(s) — "
              f"their questions reopen in review_slots.py")
    for filename, text in files.items():
        with open(os.path.join(target, filename), "w", encoding="utf-8") as handle:
            handle.write(text)
        print(f"[write] {os.path.join(target, filename)}")
    total = stats["implemented"] + stats["stubs"]
    coverage = stats["implemented"] / total if total else 1.0
    print(f"methods: {stats['implemented']} implemented, {stats['stubs']} stubs "
          f"({coverage:.0%} mechanical)")
    if stats.get("gui_panels") is not None:
        print(f"  gui pyimgui panels: {stats['gui_panels'] or 'none'}")
    for reason in stats["stub_reasons"]:
        print(f"  stub: {reason}")
    for where, bound in sorted(stats["bindings"].items()):
        print(f"  cli {where} -> {bound[0] if bound else 'UNBOUND'}"
              f"{'' if not bound else f' [score {bound[1]}]'}")
    if stats["skipped_options"]:
        print(f"skipped argparse-owned options: {sorted(set(stats['skipped_options']))}")
    if stats.get("unbound_fields"):
        print(f"adapter fields with no CLI flag: {sorted(set(stats['unbound_fields']))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
