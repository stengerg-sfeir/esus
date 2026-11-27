#!/usr/bin/env python3
"""Run prompt-derived oracle cases for one generated project.

This worker is intentionally black-box: it uses the existing scenario DSL to
seed records and call the public generated service, then compares the case's
expected state/error/rows. Cases that cannot bind are reported as unbound.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "runtime"))

import worker  # noqa: E402
from kernel.oracle import alignment, binder, cases as case_rules, triage  # noqa: E402
from kernel.consistency.naming import normalize  # noqa: E402


def _bare_argument_names(case, docs):
    """Field/parameter names used as literal values make a case incomplete."""
    raw = (case.get("when") or {}).get("args")
    values = list(raw.values()) if isinstance(raw, dict) else (
        raw if isinstance(raw, list) else [raw])
    known = set()
    for model in docs.get("models") or []:
        for field in model.get("fields") or []:
            if isinstance(field, dict) and field.get("name"):
                known.add(normalize(field["name"]))
    for group_key in ("services", "repos"):
        for holder in docs.get(group_key) or []:
            for method in holder.get("methods") or []:
                for param in method.get("params") or []:
                    if isinstance(param, dict) and param.get("name"):
                        known.add(normalize(param["name"]))
    requirement_words = {normalize(word) for word in
                         re.findall(r"[A-Za-z][A-Za-z0-9_]+",
                                    docs.get("requirements") or "")}
    for value in values:
        if not isinstance(value, str) or "." in value or "=" in value:
            continue
        if value.strip().lower() in ("true", "false", "none", "null"):
            continue
        try:
            float(value)
            continue
        except ValueError:
            pass
        token = normalize(value)
        if token in known or token in requirement_words:
            return value
    return None


def _alignment_dict(result):
    if result is None:
        return None
    return {
        "status": result.status,
        "canonical": result.canonical,
        "score": result.score,
        "evidence": result.evidence,
        "alternatives": result.alternatives,
    }


def _case_alignment(case, docs, requirements):
    result = alignment.align_case(case, docs, requirements)
    return {
        "entities": {key: _alignment_dict(value)
                     for key, value in result["entities"].items()},
        "fields": {key: _alignment_dict(value)
                   for key, value in result["fields"].items()},
        "action": _alignment_dict(result["action"]),
    }


def _normalize_state_fields(case):
    """Drop invented asserted fields and use unambiguous alignment aliases.

    The case generator sometimes asserts a field the prompt never names and
    the model does not declare. That is a verifier case defect, not a
    generated-code finding. Coverage-gap fields are deliberately left alone.
    """
    state = (case.get("then") or {}).get("state")
    if not isinstance(state, dict):
        return
    given = case.get("given")
    aliases = set()
    if isinstance(given, dict):
        aliases = {normalize(key) for key in given}
    elif isinstance(given, list):
        aliases = {normalize(item.get("as") or item.get("entity") or "")
                   for item in given if isinstance(item, dict)}
    fields = (case.get("alignment") or {}).get("fields") or {}
    normalized = {}
    for target, expected in state.items():
        alias = str(target).partition(".")[0]
        if aliases and normalize(alias) not in aliases:
            # The assertion names a row the case never seeds.
            continue
        info = fields.get(target) or {}
        status = info.get("status")
        canonical = info.get("canonical")
        if status == "invented":
            continue
        if status == "alias" and isinstance(canonical, str) and canonical:
            head, _, _field = str(target).partition(".")
            target = f"{head}.{canonical}"
        normalized[target] = expected
    case.setdefault("then", {})["state"] = normalized


def run(project, include_assumed=False, cases_name=None):
    project = Path(project)
    docs = worker._documents(project)
    case_path = project / (cases_name or case_rules.CASES_NAME)
    raw_cases = case_rules.load_cases(case_path)
    all_cases, _errors = case_rules.validate_cases(
        raw_cases, docs.get("requirements") or "")
    case_rules.save_cases(
        case_path, all_cases,
        prompt_sha=(all_cases[0].get("prompt_sha") if all_cases else None))
    selected = [case for case in all_cases
                if case.get("status") in (
                    "confirmed", "unbound", "under_specified", "case_defect")
                or (include_assumed and case.get("status") == "assumed")]
    if not selected:
        return {"prompt": project.name, "results": [], "counts": {}}
    cli_path = project / "generated" / "cli.py"
    if cli_path.is_file():
        try:
            cli, deps, db = worker._load_package(project)
        except Exception as error:  # noqa: BLE001
            return {"prompt": project.name, "status": "failed",
                    "results": [{"status": "failed", "name": "import",
                                 "reason": f"{type(error).__name__}: {error}"}],
                    "counts": {"failed": 1}}
        store = deps.get("store")
    else:
        cli, deps, db, store = None, {}, None, None
    results = []
    case_by_id = {case.get("id"): case for case in all_cases}
    for index, case in enumerate(selected, start=1):
        try:
            case["alignment"] = _case_alignment(
                case, docs, docs.get("requirements") or "")
            _normalize_state_fields(case)
            scenario, reason = binder.bind_case(case, docs)
        except Exception as error:  # noqa: BLE001
            scenario = None
            reason = f"verifier harness error: {type(error).__name__}: {error}"
        if scenario is None:
            outcome = {"name": case["id"], "status": "unbound",
                       "reason": reason, "source": case.get("source"),
                       "alignment": case.get("alignment")}
            case["status"] = "unbound"
            kind = triage.classify("unbound", reason, case.get("source"))
            then = case.get("then") or {}
            text = str(reason or "").lower()
            if "app-only project" in text or "under-specified" in text:
                # The project or the assertion is outside what the service
                # verifier can observe. Keep it visible for human review.
                kind = "under_specified"
            if kind == "case_defect: setup" and (
                    "passes parameter name" in text
                    or ("cannot resolve given entity" in text
                        and not any(str(alias).lower() == str(reason).split("'")[-2].lower()
                                    for alias in (case.get("given") or {})))):
                # A field name used as a value, or an invented scalar
                # pseudo-entity, is a prompt/case-shape assumption rather than
                # a generated-code defect.
                kind = "under_specified"
            if "seeded data matches its filter" in str(reason):
                kind = "case_defect: setup"
            bare = _bare_argument_names(case, docs)
            if bare and kind == "coverage_gap: ambiguous action":
                kind = "under_specified"
                reason = f"case passes parameter/field name {bare!r} as a value"
            action_info = (case.get("alignment") or {}).get("action") or {}
            if action_info.get("status") == "under_specified":
                kind = "under_specified"
            if kind == "coverage_gap: missing action":
                if action_info.get("status") == "invented":
                    # The case invented an action that the prompt does not
                    # expose; this is under-specification, not a methods gap.
                    kind = "under_specified"
                elif action_info.get("status") == "ambiguous":
                    kind = "coverage_gap: ambiguous action"
            if (kind.startswith("case_defect")
                    and "cannot resolve given entity" in str(reason)
                    and ("stdout_contains" in then or "exit_code" in then)):
                kind = "under_specified"
            outcome["triage"] = kind
            case["triage"] = kind
            case["needs_review"] = False
            if kind == "under_specified":
                # The prompt does not determine this field. This is neither a
                # malformed case nor evidence about the generated code.
                outcome["status"] = "under_specified"
                case["status"] = "under_specified"
                case["execution"] = {"status": "under_specified",
                                     "reason": reason}
            elif kind.startswith("case_defect"):
                # A malformed case is not an unbound generated-code check.
                # Record it as a verifier defect and do not execute it.
                outcome["status"] = "case_defect"
                case["execution"] = {"status": "case_defect", "reason": reason}
            else:
                case["execution"] = {"status": "unbound", "reason": reason}
            results.append(outcome)
            continue
        try:
            outcome = worker._run_scenario(
                docs, deps, store, scenario, index,
                cli_path=cli_path if cli_path.is_file() else None,
                db=db, cli_module=cli,
                app_path=(project / "generated" / "app.py").resolve())
        except Exception as error:  # noqa: BLE001
            outcome = {"name": scenario["name"], "status": "failed",
                       "reason": f"harness error: {type(error).__name__}: {error}"}
        outcome["case"] = case["id"]
        outcome["source"] = case.get("source")
        outcome["alignment"] = case.get("alignment")
        case["execution"] = {
            "status": outcome.get("status"),
            "reason": outcome.get("reason", ""),
        }
        kind = triage.classify(
            outcome.get("status"), outcome.get("reason"),
            outcome.get("source"))
        expected_error = (case.get("then") or {}).get("error")
        if (kind == "behavior: expected error missing"
                and isinstance(expected_error, str)
                and expected_error
                and not re.fullmatch(r"[A-Z][A-Za-z0-9_]*Error",
                                     expected_error)):
            kind = "under_specified"
        case["triage"] = kind
        outcome["triage"] = kind
        if kind.startswith("case_defect"):
            # A case-generation/binding defect is verifier quality, not a
            # generated-behavior failure. Keep its raw reason for repair.
            outcome["status"] = "case_defect"
            case["status"] = "case_defect"
            case["execution"] = {"status": "case_defect",
                                 "reason": outcome.get("reason", "")}
        case["needs_review"] = kind.startswith("behavior")
        results.append(outcome)
    payload = {"prompt_sha": case_by_id.get(
        selected[0].get("id"), {}).get("prompt_sha"), "cases": all_cases}
    case_rules.save_cases(case_path, all_cases,
                          prompt_sha=payload.get("prompt_sha"))
    counts = {}
    triage_counts = {}
    for result in results:
        status = result.get("status")
        counts[status] = counts.get(status, 0) + 1
        kind = result.get("triage") or "unclassified"
        triage_counts[kind] = triage_counts.get(kind, 0) + 1
    return {"prompt": project.name, "results": results,
            "counts": counts, "triage_counts": triage_counts}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project")
    parser.add_argument("--include-assumed", action="store_true")
    parser.add_argument("--cases", default=None,
                        help="case sidecar filename (default: oracle_cases.json)")
    args = parser.parse_args(argv)
    try:
        payload = run(args.project, args.include_assumed, args.cases)
    except Exception as error:  # noqa: BLE001
        payload = {
            "prompt": Path(args.project).name,
            "status": "failed",
            "results": [{
                "name": "verifier",
                "status": "unbound",
                "reason": f"verifier harness error: {type(error).__name__}: {error}",
                "triage": "case_defect: harness",
            }],
            "counts": {"unbound": 1},
        }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
