"""Is the extraction output ready for a code generator? Checks the documents directly.

The consistency checker proves the documents agree with each other. A generator
needs more: every command backed by a method, every adapter resolving, every
crud operation implemented by its own entity's interface, every parameter
well-typed, every raised error registered. This probe measures those, per
prompt, and prints the blockers a generator would have to paper over.

Implementation: this probe reuses kernel.consistency.check_directory as the
single definition of each defect (no duplicated stem tables), then classifies
findings into generator blockers vs consistency risks:

- blockers: every error + every warning + unbacked_command notes promoted to
  blockers (a CLI verb no method serves is a call the generator cannot write).
- risks: narrow_margin / low_confidence / missing_pattern / corrected_claim
  notes. They do not force invention, but they mean the JSON may differ
  between runs or name a vocabulary gap the generator must work around.

Exit code is 0 when no blocker was found and 1 otherwise, so CI can gate on it.
Usage:
    python probe_readiness.py [--dirs NAME:PATH ...]
    python probe_readiness.py   # checks out/<PROMPTS>
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kernel.consistency import check_directory  # noqa: E402
from kernel import tie_rules  # noqa: E402
from kernel import codegen as codegen_rules  # noqa: E402
from kernel.consistency.loader import load_documents  # noqa: E402
from kernel.consistency.naming import normalize  # noqa: E402
from kernel.consistency.report import Finding, Report  # noqa: E402

OUT = "out"
PROMPTS = ("hello", "cli_tool", "inventory", "gui", "expenses", "60", "library_correct")

# Notes that do not force invention but mean the JSON may differ per run or
# name a pattern the catalogue lacks. Reported separately, never counted as
# blockers.
RISK_RULES = frozenset(
    {"narrow_margin", "low_confidence", "missing_pattern", "corrected_claim"}
)

# The one note the checker cannot call a defect (stem match only) but a
# generator cannot survive: a command with no method behind it.
PROMOTED_NOTES = frozenset({"unbacked_command"})
BOOLEAN_FLAG_SUFFIXES = frozenset({
    "only", "active", "enabled", "disabled", "verbose", "quiet",
    "all", "force", "recursive", "dry_run",
})


def open_questions(path):
    """Ties needing a human that have no recorded answer (`review_ties.py`)."""
    import json

    try:
        with open(os.path.join(path, "pattern_matches.json"), encoding="utf-8") as handle:
            matches = json.load(handle).get("pattern_matches")
    except (OSError, ValueError, AttributeError):
        return 0
    if not isinstance(matches, list):
        return 0
    return sum(1 for entry in matches if tie_rules.needs_user(entry))


def check_prompt(name, path):
    """Run the checker over one output directory; return (blockers, risks)."""
    report = check_directory(path, name)
    blockers = list(report.errors) + list(report.warnings)
    risks = []
    for note in report.notes:
        if note.rule in PROMOTED_NOTES:
            blockers.append(note)
        elif note.rule in RISK_RULES:
            risks.append(note)
    # Deterministic order: severity already split, sort by rule then message.
    blockers.sort(key=lambda f: (f.rule, f.message))
    risks.sort(key=lambda f: (f.rule, f.message))
    for action, field in uncovered_fields(path):
        blockers.append(Finding(
            "warning", "uncovered_field",
            f"interaction_adapters: '{action}' requires field '{field}' "
            f"but no CLI flag supplies it — the action parses but can never run"))
    for action, field, entity in unknown_model_fields(path):
        blockers.append(Finding(
            "warning", "unknown_model_field",
            f"interaction_adapters: '{action}' builds {entity} with '{field}', "
            f"which {entity} does not declare — construction always fails"))
    blockers.extend(generation_surface_findings(path))
    blockers.extend(relation_filter_findings(path))
    blockers.extend(create_field_findings(path))
    blockers.extend(contract_record_findings(path))
    blockers.extend(open_review_findings(path))
    blockers.sort(key=lambda f: (f.rule, f.message))
    return blockers, risks, report


def generation_surface_findings(path):
    """Find parsed CLI options the generated dispatcher ignores or mis-types.

    ``render_program`` uses the same command/action and flag routing plan as
    the CLI emitter. Reusing that plan here prevents readiness from blessing
    an option that parses successfully but never reaches an adapter.
    """
    from generator import (load_context, render_program, _leaf_scan,
                           _service_method)

    findings = []
    documents = load_documents(path, Report("probe"))
    components = documents.get("components") or {}
    facade = components.get("facade") or {}
    invocation = facade.get("invocation") or {}
    for command in invocation.get("commands") or []:
        if not isinstance(command, dict):
            continue
        groups = [(command.get("name") or "command", command.get("options") or [])]
        groups += [
            (f"{command.get('name', 'command')} {sub.get('name', 'subcommand')}",
             sub.get("options") or [])
            for sub in command.get("subcommands") or []
            if isinstance(sub, dict)
        ]
        for where, options in groups:
            for option in options:
                if not isinstance(option, dict):
                    continue
                raw = str(option.get("name") or option.get("short") or "")
                dest = codegen_rules.option_dest(option)
                kind = str(option.get("type") or "").strip().lower()
                suffix = (dest or "").rsplit("_", 1)[-1]
                if suffix in BOOLEAN_FLAG_SUFFIXES and kind != "bool":
                    findings.append(Finding(
                        "warning", "invalid_flag_type",
                        f"components.facade.invocation {where}: '{raw}' is a "
                        "presence flag but is declared as a value-taking "
                        f"'{kind or 'untyped'}' option"))

    try:
        ctx = load_context(path)
        stats = {"source": path, "implemented": 0, "stubs": 0, "stub_reasons": [],
                 "prog": os.path.basename(path.rstrip(os.sep))}
        render_program(ctx, stats)
    except Exception as error:
        return findings + [Finding(
            "warning", "surface_plan_failed",
            f"the generator could not resolve the CLI surface ({type(error).__name__}: {error})")]

    for message in sorted(set(stats.get("dead_options") or [])):
        findings.append(Finding(
            "warning", "ignored_cli_option",
            f"interaction_adapters: {message}; the option parses but is not "
            "consumed by an effective action"))

    # Check that one CLI value does not feed multiple parameters of the same
    # action. That ambiguity used to pass because every required field had a
    # fuzzy name match, even when both matches chose the same dest.
    from kernel.consistency.checks_surface import COMMAND_VERB_STEMS
    bindings, _unmapped = codegen_rules.bind_commands(
        ctx["adapters"], invocation, COMMAND_VERB_STEMS)
    leaves, actions, argv, targets, assembled = _leaf_scan(
        ctx, bindings, stats)
    for leaf in leaves:
        where = (leaf["command"] if leaf["subcommand"] is None else
                 f"{leaf['command']} {leaf['subcommand']}")
        option_by_dest = {
            codegen_rules.option_dest(item): item
            for item in codegen_rules.leaf_options(
                invocation, leaf["command"], leaf["subcommand"])
            if codegen_rules.option_dest(item)
        }
        for action_name, _score, _need in leaf.get("choices") or []:
            adapter = actions.get(action_name) or {}
            method = _service_method(
                ctx, adapter.get("target_service"), adapter.get("target_method"))
            params = {normalize(item.get("name")): item.get("type")
                      for item in (method or {}).get("params") or []
                      if isinstance(item, dict) and item.get("name")}
            mapped = {}
            for field in adapter.get("input_fields") or []:
                if not isinstance(field, dict) or not field.get("field_name"):
                    continue
                if codegen_rules.is_assembly_field(
                        adapter, field["field_name"], targets.get(action_name, {})):
                    continue
                dest = (argv.get(action_name) or {}).get(field["field_name"])
                if dest:
                    mapped.setdefault(dest, []).append(field)
            for dest, fields in mapped.items():
                if len(fields) > 1:
                    names = ", ".join(sorted(
                        str(item.get("field_name")) for item in fields))
                    findings.append(Finding(
                        "warning", "ambiguous_option_mapping",
                        f"interaction_adapters: {where} option '--{dest.replace('_', '-')}' "
                        f"maps to multiple fields ({names}) for '{action_name}'"))
                option = option_by_dest.get(dest) or {}
                option_type = str(option.get("type") or "").lower()
                for field in fields:
                    transform = field.get("transform")
                    target_type = str(params.get(normalize(
                        field.get("target_param") or "")) or "").lower()
                    is_bool_target = target_type in ("bool", "boolean")
                    is_int_target = target_type in ("int", "integer")
                    wrong = (
                        (option_type == "bool" and is_bool_target
                         and transform != "DIRECT")
                        or (option_type == "bool" and is_int_target
                            and transform != "BOOL_TO_ONE")
                        or (option_type == "bool" and not is_bool_target
                            and not is_int_target
                            and transform != "BOOL_TO_ONE")
                        or (option_type != "bool"
                            and (is_bool_target or transform == "BOOL_TO_ONE"))
                    )
                    if wrong:
                        findings.append(Finding(
                            "warning", "adapter_option_type_mismatch",
                            f"interaction_adapters: {where} option '{option.get('name', dest)}' "
                            f"({option_type or 'untyped'}) uses {transform!r} for "
                            f"'{field.get('target_param')}' ({target_type or 'unknown'}); "
                            "the option type and transform do not agree"))
    return findings


def relation_filter_findings(path):
    """Catch ID filters that have no relation field on their result entity.

    A query such as ``find_books_by_author(author_id)`` cannot safely fall
    back to the result entity's own primary key. Require the corresponding
    FK field on the repository's entity so the mechanical filter reads the
    declared relationship.
    """
    documents = load_documents(path, Report("probe"))
    models = documents.get("data_models") or []
    ports = documents.get("persistence_ports") or {}
    entities = {normalize(item.get("name")): item.get("name")
                for item in models if isinstance(item, dict) and item.get("name")}
    model_by_name = {normalize(item.get("name")): item for item in models
                     if isinstance(item, dict) and item.get("name")}
    findings = []
    for repo in (ports.get("repositories") or []) if isinstance(ports, dict) else []:
        if not isinstance(repo, dict):
            continue
        entity_name = repo.get("entity")
        model = next((item for item in models if isinstance(item, dict)
                      and item.get("name") == entity_name), None)
        if not model:
            continue
        fields = [item for item in model.get("fields") or []
                  if isinstance(item, dict) and item.get("name")]
        for method in repo.get("methods") or []:
            if not isinstance(method, dict) or not method.get("name"):
                continue
            returns = normalize(method.get("return_type") or "")
            if "list" not in returns or normalize(entity_name) not in returns:
                continue
            for param in method.get("params") or []:
                if not isinstance(param, dict):
                    continue
                param_name = str(param.get("name") or "")
                match = re.fullmatch(r"(.+)_id", param_name, re.I)
                if not match:
                    continue
                related = entities.get(normalize(match.group(1)))
                if not related or normalize(related) == normalize(entity_name):
                    continue
                fk_name = f"{match.group(1)}_id"
                related_model = model_by_name.get(normalize(related)) or {}
                related_pk = next(
                    (field.get("name") for field in related_model.get("fields") or []
                     if isinstance(field, dict) and field.get("primary_key")
                     and field.get("name")), "id")
                fk = next((field for field in fields
                           if normalize(field.get("name")) == normalize(fk_name)
                           and isinstance(field.get("foreign_key"), dict)
                           and normalize(field["foreign_key"].get("target_entity"))
                           == normalize(related)
                           and normalize(field["foreign_key"].get("target_field"))
                           == normalize(related_pk)), None)
                if fk is None:
                    findings.append(Finding(
                        "warning", "missing_relation_filter",
                        f"{repo.get('interface_name', entity_name)}.{method['name']} "
                        f"filters {entity_name} by {related} ID, but {entity_name} "
                        f"does not declare {fk_name} as an FK to {related}. "
                        "Repair the model/repository mapping before treating the "
                        "CLI option as dead."))
                    continue
                mapped = codegen_rules.match_param(
                    [field.get("name") for field in fields], param_name)
                if mapped != (fk_name, "eq"):
                    findings.append(Finding(
                        "warning", "relation_filter_mismatch",
                        f"{method['name']} does not resolve '{param_name}' to "
                        f"{entity_name}.{fk_name}"))
    return findings


def create_field_findings(path):
    """Catch a required field that no repository create can ever set.

    A NOT NULL, non-key field must come from a create parameter, a default
    (the model's, the requirements' own words, or the generator's creation-
    date rule). Otherwise every create fails at the store, whatever the
    service body does. The defaults are the generator's own predicates, so
    readiness and generation cannot disagree about what has one.
    """
    from generator import load_context, fields_of, _field_default, _create_defaults

    ctx = load_context(path)
    findings = []
    for repo in ctx["repositories"]:
        entity = repo.get("entity")
        for method in repo.get("methods") or []:
            if not isinstance(method, dict) or method.get("name") != "create":
                continue
            params = [p for p in method.get("params") or [] if isinstance(p, dict)]
            if any(codegen_rules.is_entity_type(p.get("type"), ctx["entity_names"])
                   for p in params):
                continue
            taken = {normalize(p.get("name")) for p in params}
            defaults = _create_defaults(ctx, entity)
            for name, field in fields_of(ctx, entity):
                if (field.get("primary_key") or field.get("nullable")
                        or normalize(name) in taken or name in defaults
                        or _field_default(ctx, field) is not None):
                    continue
                findings.append(Finding(
                    "warning", "create_field_unreachable",
                    f"{repo.get('interface_name') or entity}.create cannot set "
                    f"required field {entity}.{name}: it is not a parameter and "
                    "has no default, so every create fails the NOT NULL "
                    "constraint"))
    return findings


def contract_record_findings(path):
    """Reject recorded effects that mutate keys or contradict themselves."""
    from generator import load_context

    try:
        ctx = load_context(path)
    except Exception:
        return []  # document loading errors are already reported upstream
    models = {normalize(model.get("name")): model
              for model in ctx.get("models") or []
              if isinstance(model, dict) and model.get("name")}
    findings = []
    for contract in ctx.get("contracts") or []:
        if not isinstance(contract, dict):
            continue
        targets = {}
        for effect in contract.get("effects") or []:
            target = str(effect.get("target") or "")
            if "." not in target:
                continue
            entity, field_name = target.split(".", 1)
            model = models.get(normalize(entity))
            field = next((item for item in (model or {}).get("fields") or []
                          if isinstance(item, dict)
                          and normalize(item.get("name")) == normalize(field_name)),
                         None)
            if (normalize(field_name) == "id"
                    or (field and field.get("primary_key"))):
                findings.append(Finding(
                    "warning", "primary_key_effect",
                    f"method_contracts: {contract.get('holder')}."
                    f"{contract.get('method')} writes primary key "
                    f"'{target}'; IDs identify rows and must not be update effects"))
            signature = (effect.get("op"), repr(effect.get("value")),
                         repr(effect.get("by")))
            if target in targets and targets[target] != signature:
                findings.append(Finding(
                    "warning", "contradictory_contract_effects",
                    f"method_contracts: {contract.get('holder')}."
                    f"{contract.get('method')} records conflicting effects for "
                    f"'{target}'"))
            targets[target] = signature
        seen_preconditions = {}
        for precondition in contract.get("preconditions") or []:
            key = (str(precondition.get("check") or ""),
                   str(precondition.get("error") or ""))
            polarity = precondition.get("raise_when")
            if key in seen_preconditions and polarity != seen_preconditions[key]:
                findings.append(Finding(
                    "warning", "contradictory_contract_preconditions",
                    f"method_contracts: {contract.get('holder')}."
                    f"{contract.get('method')} gives '{key[1]}' conflicting "
                    f"conditions for '{key[0]}'"))
            seen_preconditions[key] = polarity
    return findings


def open_review_findings(path):
    """Block generation while any architecture review question is unanswered."""
    import review_aliases
    import review_contracts
    import review_slots
    import review_surface

    groups = []
    slots, _ = review_slots.collect_slots(path)
    if slots:
        groups.append(("pattern slots", len(slots)))
    duplicates, _ = review_surface.collect_duplicates(path)
    routes, _ = review_surface.collect_routes(path)
    if duplicates or routes:
        groups.append(("surface questions", len(duplicates) + len(routes)))
    aliases, _ = review_aliases.collect_questions(path)
    if aliases:
        groups.append(("field mappings", len(aliases)))
    contracts, _ = review_contracts.collect_contracts(path)
    if contracts:
        groups.append(("method contracts", len(contracts)))
    return [Finding(
        "warning", "open_human_review",
        f"{count} unanswered {label}; run the attended review before generation")
        for label, count in groups]


def uncovered_fields(path):
    """Required adapter fields no bound CLI flag can supply, as `(action, field)`.

    Non-CLI facades (a GUI takes no flags) and missing invocations have no
    flags by design and are skipped — the rule judges CLI surfaces only.
    """
    documents = load_documents(path, Report("probe"))
    facade = (documents.get("components") or {}).get("facade") or {}
    if facade.get("type") != "cli" or not isinstance(facade.get("invocation"), dict):
        return []
    models = documents.get("data_models") or []
    entity_names = [m.get("name") for m in models
                    if isinstance(m, dict) and m.get("name")]
    ports = documents.get("persistence_ports")
    repositories = []
    if isinstance(ports, dict) and isinstance(ports.get("repositories"), list):
        repositories = ports["repositories"]
    targets = codegen_rules.action_targets(
        documents.get("interaction_adapters") or [],
        documents.get("service_contracts") or [],
        repositories, entity_names)
    return codegen_rules.uncovered_required_fields(
        documents.get("interaction_adapters") or [], facade["invocation"], targets)


def unknown_model_fields(path):
    """Adapter fields assembling undeclared model fields, as `(action, field, entity)`."""
    documents = load_documents(path, Report("probe"))
    models = documents.get("data_models")
    ports = documents.get("persistence_ports")
    repositories = []
    if isinstance(ports, dict) and isinstance(ports.get("repositories"), list):
        repositories = ports["repositories"]
    return codegen_rules.unknown_model_fields(
        documents.get("interaction_adapters") or [],
        documents.get("service_contracts") or [],
        repositories, models or [])


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dirs",
        nargs="+",
        metavar="NAME:PATH",
        help="One or more output directories (format: name:path). "
        "Defaults to out/<PROMPTS>.",
    )
    return parser


def parse_dirs(entries):
    pairs = []
    for entry in entries:
        name, sep, path = entry.partition(":")
        if not sep or not name.strip() or not path.strip():
            raise argparse.ArgumentTypeError(
                f"expected 'NAME:PATH', got '{entry}'"
            )
        pairs.append((name.strip(), path.strip()))
    return pairs


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.dirs:
        targets = parse_dirs(args.dirs)
    else:
        targets = [(name, os.path.join(OUT, name)) for name in PROMPTS]

    total_blockers = 0
    total_risks = 0
    total_questions = 0
    for name, path in targets:
        if not os.path.isdir(path):
            print(f"{name:10} MISSING OUTPUT")
            continue
        blockers, risks, _ = check_prompt(name, path)
        questions = open_questions(path)
        total_blockers += len(blockers)
        total_risks += len(risks)
        total_questions += questions
        print(f"{name:10} {len(blockers)} blocker(s), {len(risks)} risk(s), "
              f"{questions} open tie(s)")
        for finding in blockers:
            print(f"           - [{finding.rule}] {finding.message}")
    print(f"\nTOTAL generator blockers: {total_blockers}")
    print(f"TOTAL consistency risks: {total_risks} (narrow/low/missing/corrected)")
    if total_questions:
        print(f"TOTAL open ties needing a human: {total_questions} "
              f"(python review_ties.py OUT_DIR)")
    return 1 if total_blockers else 0


if __name__ == "__main__":
    sys.exit(main())
