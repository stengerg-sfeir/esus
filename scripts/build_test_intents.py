#!/usr/bin/env python3
"""Build prompt-derived test intents for uncovered requirement clauses.

The verifier never sees the extracted documents here. It returns only a test
intent: operation, target entity/action, setup graph, lookup fields, semantic
changes and observable expectations. A later mechanical kernel will turn the
intent into fixtures and executable checks.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kernel.extraction import runner  # noqa: E402
from kernel.extraction.decisions import requirements_sha  # noqa: E402
from kernel.oracle import intents as intent_rules  # noqa: E402


def _clean(value):
    return " ".join(str(value or "").split()).strip().casefold().rstrip(" .;:")


def _same_clause(source, clause):
    left, right = _clean(source), _clean(clause)
    return bool(left and right) and (left == right or left in right or right in left)


def _anchor_source(payload, clause):
    """Use the target clause when the model returned a larger source span."""
    if not isinstance(payload, dict):
        return payload
    intents = payload.get("intents")
    if not isinstance(intents, list):
        return payload
    wanted = _clean(clause)
    for intent in intents:
        if not isinstance(intent, dict):
            continue
        source = _clean(intent.get("source"))
        if source and wanted and (source in wanted or wanted in source):
            intent["source"] = clause
    return payload


def build_intent_prompt(requirements, clause):
    return f"""You are a requirements analyst. Read only the requirements below.
Do not use or infer an extracted architecture, database schema, method
contract, generated code or test code.

TARGET CLAUSE:
{clause}

Produce test intents for that clause. Return JSON matching:
{intent_rules.INTENT_SCHEMA}

Rules:
- `source` must be copied exactly from the target clause.
- Use only behavior stated in the target clause. Do not import behavior from
  another requirement or another sentence.
- Produce one intent for each distinct observable behavior in the clause, at
  most three. Return `{{"intents": []}}` when the clause has no observable
  behavior.
- `kind` is the observable test shape: create, update, delete, list,
  aggregate, error, cli or app.
- Use `kind: cli` only when the requirements show the exact command syntax;
  otherwise test the domain action. Put `cli` only on cli intents and `app`
  only on app intents.
- Use an action verb or operation named by the clause. Do not replace a
  domain operation with a generic balance update or CRUD name.
- The target entity is the subject of the operation. When the clause describes
  an effect (`when an order is created ...`), test the operation that creates
  the order, not an invented helper such as `decrease_stock`.
- For a state-transition clause (`cancelling a confirmed order`, `returning a
  loan`), target the object being transitioned, seed its pre-action status from
  the clause, and assert the related stock/copy effect separately. Do not make
  the affected stock row the target.
- Use the exact action named or directly implied by the full requirements. If
  the requirements say `place orders`, use `place_order`; do not invent a
  different operation.
- For a domain intent, `setup_entities` names the target row and every related
  row the action reads. Use lower-case aliases and entity nouns named by the
  requirements. Do not invent entities or relationships.
- `setup_values` contains only setup values stated by the requirements and
  needed by the expected result. Do not materialize a full row; the kernel will
  fill unasserted required fields.
- `lookup` names the fields that identify a setup row, such as
  `"product.sku"`. `where` is for a filter clause only.
- `args` and `changes` contain only values named or directly implied by the
  clause. Never use placeholders.
- `expect.state` maps `alias.field` to the expected value. `expect.rows` names
  expected row counts. `expect.error` is an exception class identifier only
  when the clause names or clearly identifies one; otherwise use `null` and
  mark the intent `assumed`. Do not put an error sentence there.
- Do not invent fields, filters or statuses the clause does not name, such as
  an `active` flag or a `sort` option.
- For a list/search clause, seed enough rows through `setup_entities` and
  `setup_values` to make the expected count meaningful, including parent rows.
- A standalone one-file program uses `"kind": "app"`, no entities, and
  `"app": {{"args": [...], "stdin": "", "files": {{}}}}`; assert
  `stdout_contains` and/or `exit_code`.
- If the clause has no concrete observable behavior, return
  `{{"intents": []}}`.
- `status` is `confirmed` only when the clause states the behavior; otherwise
  `assumed` or `ambiguous`.
- Do not write implementation details and do not invent sort options, payload
  shapes, statuses or file abstractions.

REQUIREMENTS:
{requirements}
"""


def build_repair_prompt(requirements, clause, payload, errors):
    return f"""You are correcting a prompt-derived test intent. Return the
complete corrected JSON object matching the intent schema. Preserve a valid
intent; fix every listed error. Do not use extracted architecture or generated
code.

SCHEMA:
{intent_rules.INTENT_SCHEMA}

VALIDATION ERRORS:
{chr(10).join(f"- {error}" for error in errors)}

CURRENT INTENT:
{json.dumps(payload, indent=2, ensure_ascii=False)}

TARGET CLAUSE:
{clause}

REQUIREMENTS:
{requirements}
"""


def _select(valid, clause):
    return [intent for intent in valid
            if _same_clause(intent.get("source"), clause)]


def build_one(project, model_path, context=8192, max_new_tokens=4096,
              coverage=None, repair_attempts=1, append=False, out=print):
    project = Path(project)
    try:
        requirements = (project / "requirements.txt").read_text(encoding="utf-8")
    except OSError:
        raise SystemExit(f"no requirements.txt in {project}")
    if not coverage:
        return [], project / intent_rules.INTENTS_NAME
    llm = runner.load_model(model_path, context_size=context, quiet=True)
    framing = runner.generate_chat if runner.has_chat_template(llm) else runner.generate_free
    selected, rejected = [], []
    for clause in coverage:
        prompt = build_intent_prompt(requirements, clause)
        result = framing(llm, prompt, f"intent:{project.name}",
                         temperature=0.0, max_new_tokens=max_new_tokens)
        if result.truncated:
            rejected.append({"clause": clause, "errors": ["intent was truncated"],
                             "text": result.text})
            continue
        payload = intent_rules.parse_payload(result.text)
        if payload is None:
            rejected.append({"clause": clause, "errors": ["intent was not JSON"],
                             "text": result.text})
            continue
        payload = _anchor_source(payload, clause)
        valid, errors = intent_rules.validate_intents(payload, requirements)
        attempts = 0
        while errors and attempts < repair_attempts:
            attempts += 1
            repaired = framing(
                llm, build_repair_prompt(requirements, clause, payload, errors),
                f"intent-repair:{project.name}:{attempts}",
                temperature=0.0, max_new_tokens=max_new_tokens)
            if repaired.truncated:
                break
            repaired_payload = intent_rules.parse_payload(repaired.text)
            if repaired_payload is None:
                break
            repaired_payload = _anchor_source(repaired_payload, clause)
            candidate, candidate_errors = intent_rules.validate_intents(
                repaired_payload, requirements)
            if len(candidate) > len(valid):
                valid, errors, payload = candidate, candidate_errors, repaired_payload
            else:
                errors = candidate_errors or errors
        matched = _select(valid, clause)
        if matched:
            selected.extend(intent_rules.ground_intents(matched, requirements))
        else:
            rejected.append({"clause": clause,
                             "errors": errors or ["no intent matched the clause"],
                             "text": result.text})
    if append:
        existing = intent_rules.load_intents(project / intent_rules.INTENTS_NAME)
        replaced = {clause for clause in coverage
                    if any(_same_clause(item.get("source"), clause)
                           for item in selected)}
        selected = [item for item in existing
                    if not any(_same_clause(item.get("source"), clause)
                               for clause in replaced)] + selected
    seen = set()
    for item in selected:
        base = str(item.get("id") or "intent")
        candidate = base
        number = 2
        while candidate in seen:
            candidate = f"{base}_{number}"
            number += 1
        item["id"] = candidate
        seen.add(candidate)
    path = intent_rules.save_intents(
        project / intent_rules.INTENTS_NAME, selected)
    (project / "test_intents_meta.json").write_text(
        json.dumps({
            "requirements_sha": requirements_sha(requirements),
            "rejected": rejected,
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    out(f"{project.name}: {len(selected)} intent(s) -> {path}")
    if rejected:
        out(f"{project.name}: {len(rejected)} rejected clause(s)")
    return selected, path


def _coverage(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    found = {}
    for item in payload.get("projects") or []:
        found[item.get("project")] = [
            row.get("text") for row in item.get("rows") or []
            if row.get("status") == "mapped_untested"
            and isinstance(row.get("text"), str)
        ]
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", help="validation root containing prompt_* directories")
    parser.add_argument("--coverage", required=True,
                        help="coverage.json with mapped_untested clauses")
    parser.add_argument("--model", default="server",
                        help="GGUF path or `server` (default: server)")
    parser.add_argument("--server-url", default=None,
                        help="llama-server URL (sets LLAMA_SERVER_URL)")
    parser.add_argument("--only", default=None,
                        help="comma-separated prompt names")
    parser.add_argument("--context", type=int, default=8192)
    parser.add_argument("--max-new-tokens", type=int, default=4096)
    parser.add_argument("--repair-attempts", type=int, default=1)
    parser.add_argument("--append", action="store_true",
                        help="keep intents for clauses not selected in this run")
    args = parser.parse_args(argv)
    if args.server_url:
        os.environ["LLAMA_SERVER_URL"] = args.server_url
    root = Path(args.root)
    wanted = {item.strip() for item in args.only.split(",") if item.strip()} \
        if args.only else None
    coverage = _coverage(args.coverage)
    projects = [path for path in sorted(root.glob("prompt_*"))
                if path.is_dir() and coverage.get(path.name)
                and (wanted is None or path.name in wanted)]
    if not projects:
        raise SystemExit(f"no covered prompt directories under {root}")
    total = 0
    failed = []
    for project in projects:
        try:
            selected, _path = build_one(
                project, args.model, context=args.context,
                max_new_tokens=args.max_new_tokens,
                coverage=coverage.get(project.name),
                repair_attempts=args.repair_attempts,
                append=args.append)
        except (SystemExit, RuntimeError, OSError) as error:
            failed.append(project.name)
            print(f"{project.name}: intent build failed ({error})")
            continue
        total += len(selected)
    print(f"total: {total} test intent(s)")
    if failed:
        print("failed prompts: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
