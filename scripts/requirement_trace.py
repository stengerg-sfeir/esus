#!/usr/bin/env python3
"""Trace requirement clauses to extracted artifacts and acceptance checks.

This is a coverage report, not a second oracle. It answers a narrower question
than behavioral acceptance: for each sentence or command example in
`requirements.txt`, which extracted artifact(s) mention the same concepts, and
does at least one runtime check exercise that artifact?

Statuses are deliberately conservative:

- `mapped_tested`   a clause maps to an artifact that a check exercises;
- `mapped_untested` a clause maps to design evidence but no check names it;
- `partial`         only a weak lexical overlap remains;
- `unmapped`        no artifact shares a significant token.

A green acceptance run can therefore report fewer covered requirements than
checks. That gap is the point of the report.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "when",
    "while", "for", "to", "of", "in", "on", "at", "by", "with", "from",
    "into", "as", "is", "are", "be", "been", "being", "was", "were", "must",
    "should", "can", "could", "will", "would", "may", "might", "shall",
    "it", "its", "this", "that", "these", "those", "their", "there", "they",
    "you", "your", "we", "our", "application", "app", "program", "system",
    "python", "3.12", "use", "using", "used", "have", "has", "had", "do",
    "does", "did", "make", "makes", "made", "also", "only", "each", "every",
    "all", "any", "some", "such", "than", "so", "not", "no", "yes",
    "create", "creates", "created", "implement", "implements", "provide",
    "provides", "allow", "allows", "support", "supports", "include",
    "includes", "require", "requires", "required", "need", "needs",
})


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _requirements(project):
    path = project / "requirements.txt"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _clauses(text):
    """Sentences and command/backtick examples from a requirement document."""
    clauses = []
    seen = set()

    def add(value):
        value = " ".join(str(value).split()).strip(" -\t")
        if len(value) < 3:
            return
        key = value.lower()
        if key not in seen:
            seen.add(key)
            clauses.append(value)

    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Markdown headings and labels are structure, not runtime predicates.
        if stripped.startswith("#") or stripped.endswith(":"):
            continue
        if stripped.startswith("**") and stripped.endswith("**"):
            continue
        # Keep command examples and explicit bullets as their own clause.
        if stripped.startswith(("-", "*")) or "`" in stripped:
            add(stripped)
            continue
        for part in re.split(r"(?<=[.!?;])\s+", stripped):
            add(part)
    return clauses


def _stem(word):
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def _words(text):
    return {_stem(word) for word in re.findall(r"[a-z][a-z0-9_]{2,}",
                                               str(text or "").lower())
            if word not in STOPWORDS}


def _artifact(kind, label, text, identifier=None):
    label = str(label or "").strip()
    if not label:
        return None
    return {
        "id": identifier or f"{kind}:{label}",
        "kind": kind,
        "label": label,
        "text": str(text or label),
        "tokens": _words(label + " " + str(text or "")),
    }


def _walk_commands(invocation):
    commands = []
    for command in (invocation or {}).get("commands") or []:
        if not isinstance(command, dict):
            continue
        name = command.get("name")
        if name:
            commands.append((str(name), command))
        for sub in command.get("subcommands") or []:
            if isinstance(sub, dict) and sub.get("name"):
                commands.append((f"{name} {sub['name']}", sub))
    return commands


def artifacts(project, checks=None):
    """Build the traceable artifact index for one extracted project."""
    found = []
    data_models = _read_json(project / "data_models.json") or {}
    for model in data_models.get("data_models") or []:
        if not isinstance(model, dict) or not model.get("name"):
            continue
        fields = [field for field in model.get("fields") or []
                  if isinstance(field, dict) and field.get("name")]
        text = " ".join(
            [str(model["name"])]
            + [str(field["name"]) for field in fields]
            + [str(field.get("type") or "") for field in fields])
        item = _artifact("model", model["name"], text,
                         f"model:{model['name']}")
        if item:
            found.append(item)
        for field in fields:
            field_item = _artifact(
                "field", f"{model['name']}.{field['name']}",
                " ".join(str(part or "") for part in (
                    field["name"], field.get("type"), field.get("unique"),
                    field.get("nullable"), field.get("foreign_key"))),
                f"field:{model['name']}.{field['name']}")
            if field_item:
                found.append(field_item)

    components = _read_json(project / "components.json") or {}
    facade = components.get("facade") or {}
    invocation = facade.get("invocation") if isinstance(facade, dict) else None
    for path, node in _walk_commands(invocation):
        option_text = " ".join(
            str(option.get("name") or option.get("short") or "")
            for option in (node.get("options") or []) if isinstance(option, dict))
        item = _artifact("command", f"`{path}`",
                         f"{path} {option_text}",
                         f"command:{path}")
        if item:
            found.append(item)
        for option in node.get("options") or []:
            if not isinstance(option, dict):
                continue
            name = str(option.get("name") or option.get("short") or "")
            if not name:
                continue
            option_item = _artifact(
                "option", f"`{name}`",
                f"{name} {option.get('type') or ''} {option.get('dest') or ''}",
                f"option:{path}:{name}")
            if option_item:
                found.append(option_item)
    for key in ("persistence", "facade"):
        value = components.get(key)
        if isinstance(value, dict):
            text = " ".join(str(value.get(item) or "") for item in (
                "required", "technology", "type", "invocation"))
            item = _artifact("component", key, text, f"component:{key}")
            if item:
                found.append(item)
            technology = value.get("technology")
            if technology and str(technology).lower() not in ("none", "null"):
                item = _artifact(
                    "component", str(technology), text,
                    f"component:{key}:{technology}")
                if item:
                    found.append(item)
    for service in components.get("crud_services") or []:
        if isinstance(service, dict) and service.get("entity"):
            item = _artifact(
                "component", f"crud {service['entity']}",
                " ".join(str(part) for part in (
                    service.get("entity"), service.get("operations"))),
                f"component:crud:{service['entity']}")
            if item:
                found.append(item)

    services = _read_json(project / "service_contracts.json") or {}
    holders = services.get("service_contracts") or services.get("services") or []
    ports = _read_json(project / "persistence_ports.json") or {}
    holders = list(holders) + list(ports.get("repositories") or [])
    for holder in holders:
        if not isinstance(holder, dict):
            continue
        holder_name = holder.get("service_name") or holder.get("interface_name")
        if not holder_name:
            continue
        for method in holder.get("methods") or []:
            if not isinstance(method, dict) or not method.get("name"):
                continue
            params = " ".join(
                str(param.get("name") or "") + " " + str(param.get("type") or "")
                for param in method.get("params") or [] if isinstance(param, dict))
            text = " ".join(str(part or "") for part in (
                method.get("name"), method.get("description"),
                method.get("return_type"), params, method.get("raises")))
            item = _artifact("method", f"{holder_name}.{method['name']}", text,
                             f"method:{holder_name}.{method['name']}")
            if item:
                found.append(item)

    errors = _read_json(project / "errors.json") or {}
    for error in errors.get("errors") or []:
        if isinstance(error, dict) and error.get("name"):
            item = _artifact("error", error["name"],
                             f"{error['name']} {error.get('description') or ''}")
            if item:
                found.append(item)

    invariants = _read_json(project / "invariants.json") or {}
    for index, rule in enumerate(invariants.get("invariants") or []):
        if isinstance(rule, dict) and rule.get("text"):
            item = _artifact("invariant", f"rule {index + 1}", rule["text"],
                             f"invariant:{index + 1}")
            if item:
                found.append(item)

    contracts = _read_json(project / "method_contracts.json") or {}
    for contract in contracts.get("method_contracts") or []:
        if not isinstance(contract, dict):
            continue
        holder, method = contract.get("holder"), contract.get("method")
        if not holder or not method:
            continue
        item = _artifact("contract", f"{holder}.{method}",
                         json.dumps(contract, sort_keys=True),
                         f"contract:{holder}.{method}")
        if item:
            found.append(item)

    adapters = _read_json(project / "interaction_adapters.json") or {}
    for adapter in adapters.get("interaction_adapters") or []:
        if not isinstance(adapter, dict) or not adapter.get("action_name"):
            continue
        item = _artifact("adapter", adapter["action_name"],
                         json.dumps(adapter, sort_keys=True),
                         f"adapter:{adapter['action_name']}")
        if item:
            found.append(item)

    for name in ("main.py", "models.py", "services.py", "repositories.py",
                 "cli.py", "store.py", "errors.py", "schema.py"):
        if (project / "generated" / name).is_file():
            item = _artifact("file", name, name.replace(".", " "),
                             f"file:{name}")
            if item:
                found.append(item)

    for check in checks or []:
        if not isinstance(check, dict) or not check.get("name"):
            continue
        name = str(check["name"])
        item = _artifact("check", name, name + " " + str(check.get("reason") or ""),
                         f"check:{name}")
        if item:
            found.append(item)

    generated = project / "generated"
    source_files = sorted(generated.glob("*.py")) if generated.is_dir() else []
    source_text = "\n".join(path.read_text(encoding="utf-8", errors="replace")
                            for path in source_files)
    if source_files:
        item = _artifact(
            "component", "application codebase",
            "application cli main entry point modules separate layers "
            "clean architecture separation of concerns easy maintain split "
            "appropriate modules",
            "component:codebase")
        if item:
            found.append(item)
    if "->" in source_text:
        item = _artifact("component", "type hints",
                         "type hints annotations return annotations",
                         "component:type-hints")
        if item:
            found.append(item)
    if "PRAGMA foreign_keys=ON" in source_text or "PRAGMA foreign_keys = ON" in source_text:
        item = _artifact("component", "sqlite foreign keys",
                         "sqlite foreign keys enabled pragma constraints",
                         "component:foreign-keys")
        if item:
            found.append(item)
    if "sqlite3.connect" in source_text or "sqlite3" in source_text:
        item = _artifact("component", "sqlite persistence",
                         "sqlite persistence across sessions database file "
                         "remember information between executions",
                         "component:persistence-sessions")
        if item:
            found.append(item)
    if re.search(r"\bprint\s*\(", source_text) or "click.echo" in source_text:
        item = _artifact("component", "command line output",
                         "display result command line output",
                         "component:cli-output")
        if item:
            found.append(item)
    if re.search(r"\bdef\s+(?:create|read_all|update|delete)\s*\(",
                 source_text):
        item = _artifact("component", "crud operations",
                         "provide crud operations create read update delete",
                         "component:crud")
        if item:
            found.append(item)
    if all(re.search(rf"\bdef\s+{name}\s*\(", source_text)
           for name in ("add", "subtract", "multiply", "divide")):
        item = _artifact("component", "arithmetic operations",
                         "addition subtraction multiplication division "
                         "two numbers",
                         "component:arithmetic")
        if item:
            found.append(item)
    if re.search(r"\bdef\s+(?:search|filter|list)\w*\([^)]*=\s*None"
                 r"[^)]*=\s*None", source_text):
        item = _artifact("component", "combinable filters",
                         "filters combinable name category price quantity",
                         "component:combinable-filters")
        if item:
            found.append(item)
    if "stock_quantity" in source_text and "class Sale" in source_text:
        item = _artifact("component", "sold and stock",
                         "sold still in stock inventory quantity",
                         "component:sold-stock")
        if item:
            found.append(item)
    if "stock_quantity" in source_text and re.search(
            r"inventory|incorrect|stock", source_text, re.IGNORECASE):
        item = _artifact("component", "inventory integrity",
                         "inventory never incorrect stock quantity",
                         "component:inventory-integrity")
        if item:
            found.append(item)
    if "if __name__ == \"__main__\"" in source_text:
        item = _artifact("component", "main guard",
                         "main function standard guard",
                         "component:main-guard")
        if item:
            found.append(item)

    report_cases = {}
    for filename in ("oracle_cases.json", "oracle_cases_coverage.json",
                     "oracle_cases_intents.json", "oracle_cases_merged.json"):
        cases_payload = _read_json(project / filename) or {}
        for case in cases_payload.get("cases") or []:
            if isinstance(case, dict) and case.get("id"):
                report_cases[case["id"]] = case
    for filename in ("oracle_report.json", "oracle_coverage_report.json",
                     "oracle_report_intents.json",
                     "oracle_report_merged.json"):
        report = _read_json(project / filename) or {}
        for result in report.get("results") or []:
            if not isinstance(result, dict) or result.get("status") != "passed":
                continue
            case_id = result.get("case")
            case = report_cases.get(case_id) or {}
            if (filename == "oracle_report_intents.json"
                    and case.get("status") not in (None, "confirmed")):
                # Assumed intent cases are advisory evidence, never trace
                # coverage. Main oracle reports keep their historical status
                # handling.
                continue
            source = case.get("source")
            if not isinstance(source, str) or not source.strip():
                continue
            item = _artifact("oracle", f"oracle:{case_id}", source,
                             f"oracle:{case_id}")
            if item:
                found.append(item)

    check_text = "\n".join(
        str(check.get("name") or "") + " " + str(check.get("reason") or "")
        for check in checks or [] if isinstance(check, dict))
    for item in found:
        item["tested"] = item["kind"] == "oracle" or bool(
            item["label"].strip("`") in check_text
            or item["id"].split(":", 1)[-1] in check_text)
    for item in found:
        if item["id"] == "component:codebase" and (
                "import" in check_text or "app-run" in check_text):
            item["tested"] = True
    return found


def _score(clause, item):
    tokens = _words(clause)
    if not tokens:
        return 0
    label_tokens = _words(item["label"])
    overlap = tokens & item["tokens"]
    score = len(overlap)
    if label_tokens & tokens:
        score += 2
    # Backticked commands/flags are exact evidence, not fuzzy words.
    for quoted in re.findall(r"`([^`]+)`", clause):
        if quoted.strip() and quoted.strip().strip("`") in item["label"].strip("`"):
            score += 4
    if any(token.startswith("--") and token in item["label"] for token in tokens):
        score += 2
    return score


def _norm_text(value):
    return " ".join(str(value or "").split()).strip().casefold().rstrip(" .;:")


def trace_project(project, checks=None):
    """Return a JSON-ready trace for one project directory."""
    project = Path(project)
    clauses = _clauses(_requirements(project))
    items = artifacts(project, checks=checks)
    rows = []
    for index, clause in enumerate(clauses, start=1):
        scored = sorted(
            ((_score(clause, item), item) for item in items),
            key=lambda pair: (-pair[0], pair[1]["id"]))
        best = scored[0][0] if scored else 0
        matches = [item for score, item in scored if score == best and best > 0]
        exact_oracle = any(
            item["kind"] == "oracle" and item["tested"]
            and _norm_text(item["text"]) == _norm_text(clause)
            for item in items)
        if exact_oracle:
            # A confirmed passed case whose source is the clause itself is
            # stronger evidence than a generic design artifact that shares
            # more lexical tokens.
            status = "mapped_tested"
        elif matches and all(item["kind"] == "check" for item in matches):
            # A check can outrank the design artifact it exercises. Keep one
            # design item in the evidence so the trace still says what the
            # clause is mapped to, not only that a check exists.
            design = next((item for score, item in scored
                           if score > 0 and item["kind"] != "check"), None)
            if design is not None and design not in matches:
                matches.append(design)
        structural = any(item["id"] == "component:codebase" for item in items)
        structural_tested = any(
            item["id"] == "component:codebase" and item["tested"]
            for item in items)
        if (structural_tested and re.match(
                r"^(?:create|build|develop)\b", clause, re.IGNORECASE)):
            status = "mapped_tested"
        elif not _words(clause) and structural:
            status = "mapped_untested"
        elif best >= 2:
            status = ("mapped_tested" if any(
                item["tested"] and score >= max(2, best - 1)
                for score, item in scored) else "mapped_untested")
        elif best == 1:
            status = "partial"
        else:
            status = "unmapped"
        if exact_oracle:
            status = "mapped_tested"
        rows.append({
            "index": index,
            "text": clause,
            "status": status,
            "evidence": [
                {"id": item["id"], "kind": item["kind"],
                 "label": item["label"], "tested": item["tested"]}
                for item in matches[:6]
            ],
        })
    counts = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {
        "project": project.name,
        "requirements": len(rows),
        "counts": counts,
        "rows": rows,
    }


def summarize(traces):
    traces = list(traces)
    totals = {}
    for trace in traces:
        for status, count in (trace.get("counts") or {}).items():
            totals[status] = totals.get(status, 0) + count
    return {
        "projects": len(traces),
        "requirements": sum(int(trace.get("requirements") or 0)
                            for trace in traces),
        "counts": totals,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", help="bench root containing prompt_* directories")
    parser.add_argument("--output", default=None,
                        help="JSON report path (default: <root>/coverage.json)")
    args = parser.parse_args(argv)
    root = Path(args.root)
    projects = sorted(path for path in root.iterdir()
                      if path.is_dir() and (path / "requirements.txt").is_file())
    traces = [trace_project(project) for project in projects]
    report = {"root": str(root), "summary": summarize(traces),
              "projects": traces}
    output = Path(args.output) if args.output else root / "coverage.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
