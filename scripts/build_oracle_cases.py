#!/usr/bin/env python3
"""Build prompt-derived behavioral cases with a separate verifier model.

The verifier sees the requirements and a generic schema. It never sees the
extracted documents, contracts or generated code. Its output is evidence:
`confirmed` cases may run; assumptions, ambiguities and contradictions stay
for human review.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kernel.extraction import runner, triage  # noqa: E402
from kernel.extraction.decisions import requirements_sha  # noqa: E402
from kernel.oracle import cases as case_rules, resolved  # noqa: E402

SCHEMA = """{
  "cases": [
    {
      "id": "short_unique_id",
      "source": "exact sentence or command example from the requirements",
      "given": {
        "order": {"status": "pending", "customer_id": 1},
        "product": {"stock_quantity": 5}
      },
      "when": {
        "action": "cancel_order",
        "args": ["order.id"]
      },
      "then": {
        "state": {"order.status": "cancelled", "product.stock_quantity": 7},
        "error": "ErrorName or omit",
        "rows": {"Order": 1}
      },
      "status": "confirmed | assumed | ambiguous | contradictory",
      "assumptions": ["only when status is assumed"],
      "ambiguities": ["only when status is ambiguous or contradictory"]
    }
  ]
}"""


def build_prompt(requirements, resolved_section="", coverage=None,
                 domain_schema=None):
    coverage_section = ""
    schema_section = _schema_section(domain_schema)
    if coverage:
        listed = "\n".join(f"- {clause}" for clause in coverage)
        coverage_section = (
            "\nUNCOVERED REQUIREMENT CLAUSES TO TARGET:\n"
            f"{listed}\n"
            "Return ONLY cases whose `source` is one of these clauses. Do not "
            "return cases for other requirements, do not duplicate an existing "
            "action/setup, and keep the same prompt-only observable-behavior "
            "rules. If a clause has no concrete observable behavior, return no "
            "case for it.\n"
        )
    return f"""You are a requirements analyst. Read only the requirements below.
Do not use or infer an extracted architecture, database schema, method contract
or generated code. Produce externally observable behavioral cases.

Return one JSON object matching this schema:
{SCHEMA}

Rules:
- `source` must be copied exactly from a sentence or command example in the requirements.
- Use only entities, fields and actions explicitly named in the requirements. Never
  add an entity because it is common in similar applications.
- Produce at most 8 cases, choosing the highest-risk behavior.
- For each action, include every setup row the action needs, including related
  entities named by the prompt (for example an order also needs its customer
  and line items when the prompt says so). If a needed row is not stated, mark
  the case `assumed` or `ambiguous`.
- Setup rows must use distinct ids and must not repeat a unique-looking value
  (email, isbn, sku, code, title) unless the case explicitly tests duplicate
  rejection.
- If a required entity, transition or value is not stated, use status `assumed` or
  `ambiguous` and explain the gap. Never silently fill it.
- If two requirements contradict, mark the affected cases `contradictory`.
- Prefer public actions a user can perform; do not invent implementation details.
- A case with no concrete expected outcome is not a test; leave it out or mark it ambiguous.
- `given` must be a flat mapping of entity alias -> field -> scalar value. Do not
  nest domain objects or lists. For multiple rows, use aliases such as `book_1`,
  `book_2`.
- `then.state` must be flat `alias.field` -> scalar value. Do not nest objects.
- A simple program with no stored entity or CLI file protocol may use an app
  case instead: `"given": {{}}`, `"when": {{"app": true, "args": ["2", "+", "3"],
  "stdin": ""}}`, and `"then": {{"stdout_contains": "5", "exit_code": 0}}`.
  Use `app` only for a standalone generated script, never as a substitute for
  a domain action.
- For list/filter/search cases, seed enough rows to produce the expected result,
  including every parent row the filter reads (for example a product filter by
  category also needs its category row).
- Do not invent an argument that the requirements do not name, such as a sort
  option or a payload shape that no listed action accepts.
- For a delete case, assert the resulting row count; do not read fields from the
  row after it has been deleted.
- On a create case, every expected field value must equal the value supplied in
  `given` unless the requirement explicitly says it is computed or defaulted.
- `when` is either a service action (`action` + `args`) or a CLI path
  (`"cli": ["library", "book", "add", "--title=..."]`).
- Do not use placeholder values such as "today", "None", "auto_incremented_int",
  "unknown", or "authenticated". Use a concrete value, or mark the case assumed/
  ambiguous and explain it.
- `error` must be a single class identifier such as `InsufficientStockError`, or
  omitted. Do not write a sentence, a status, or "ErrorName or omit".
- Do not write test code. Output JSON only.

{schema_section}
REQUIREMENTS:
{requirements}

{resolved_section}
{coverage_section}
"""


PLAN_SCHEMA = """{
  "plans": [
    {
      "id": "short_unique_id",
      "source": "exact sentence or command example from the requirements",
      "when": {"action": "cancel_order", "args": ["order.id"]},
      "setup_entities": [
        {"alias": "order", "entity": "Order", "role": "target"},
        {"alias": "customer", "entity": "Customer", "role": "setup"}
      ],
      "expect": {
        "state": ["order.status"],
        "rows": {"Order": 1},
        "error": "ErrorName or omitted"
      },
      "status": "confirmed | assumed | ambiguous"
    }
  ]
}"""


DOMAIN_SCHEMA_PROMPT = """You are a requirements analyst. Read only the
requirements. Do not use or infer an extracted architecture, method contract or
generated code.

Extract only the neutral domain shape needed to plan test setup: entity names,
field names, scalar types, required/nullable, and foreign-key relationships.
Do not include services, methods, commands, state transitions, expected values,
implementation choices or test cases.

Return JSON:
{{"entities": [
  {{"name": "Product", "fields": [
    {{"name": "name", "type": "string", "required": true}},
    {{"name": "category_id", "type": "integer", "required": true,
      "references": "Category.id"}}
  ]}}
]}}

Rules:
- Use only entity and field nouns named in the requirements.
- Do not invent relationships the requirements do not imply.
- `type` is one of string, integer, number, boolean, date, datetime.
- `references` is optional and names another entity's field.

REQUIREMENTS:
{requirements}
"""


def build_schema_prompt(requirements):
    return DOMAIN_SCHEMA_PROMPT.format(requirements=requirements)


def validate_schema(payload):
    if not isinstance(payload, dict):
        return None, ["schema is not an object"]
    entities = payload.get("entities")
    if not isinstance(entities, list) or not entities:
        return None, ["schema has no entities"]
    normalized = []
    for entity in entities:
        if not isinstance(entity, dict) or not isinstance(entity.get("name"), str):
            continue
        fields = []
        for field in entity.get("fields") or []:
            if not isinstance(field, dict) or not isinstance(field.get("name"), str):
                continue
            item = {"name": field["name"], "type": field.get("type") or "string"}
            if field.get("required") is True:
                item["required"] = True
            if isinstance(field.get("references"), str):
                item["references"] = field["references"]
            fields.append(item)
        if fields:
            normalized.append({"name": entity["name"], "fields": fields})
    if not normalized:
        return None, ["schema has no usable entities"]
    return {"entities": normalized}, []


def extracted_schema(project):
    """1b: neutral schema copied from the extracted data models.

    This is intentionally extraction-coupled and must be documented as such;
    it is a diagnostic fallback, not the prompt-only verifier.
    """
    project = Path(project)
    try:
        payload = json.loads(
            (project / "data_models.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    entities = []
    for model in payload.get("data_models") or []:
        if not isinstance(model, dict) or not model.get("name"):
            continue
        fields = []
        for field in model.get("fields") or []:
            if not isinstance(field, dict) or not field.get("name"):
                continue
            item = {"name": field["name"], "type": field.get("type") or "string"}
            if field.get("nullable") is False:
                item["required"] = True
            foreign = field.get("foreign_key")
            if isinstance(foreign, dict) and foreign.get("target_entity"):
                item["references"] = (f"{foreign['target_entity']}."
                                      f"{foreign.get('target_field') or 'id'}")
            fields.append(item)
        entities.append({"name": model["name"], "fields": fields})
    return {"entities": entities} if entities else None


def _schema_section(domain_schema):
    if not domain_schema:
        return ""
    return ("\nDOMAIN SCHEMA (nouns and setup structure only; no behavior, "
            "methods or expected values):\n"
            + json.dumps(domain_schema, indent=2, ensure_ascii=False) + "\n")


def build_plan_prompt(requirements, resolved_section="", coverage=None,
                      domain_schema=None):
    coverage_section = ""
    if coverage:
        listed = "\n".join(f"- {clause}" for clause in coverage)
        coverage_section = (
            "\nUNCOVERED REQUIREMENT CLAUSES TO TARGET:\n"
            f"{listed}\n"
            "Plan only cases whose `source` is one of these clauses.\n"
        )
    schema_section = _schema_section(domain_schema)
    return f"""You are a requirements analyst. Read only the requirements below.
Do not use or infer an extracted architecture, method contract, database
schema or generated code.

First produce a CASE PLAN, not concrete test values. For every planned case,
name the observable action and the complete graph of entities the action needs.
Do not invent entities or arguments the requirements do not name.

Return JSON matching:
{PLAN_SCHEMA}

Rules:
- `source` must be copied exactly from a sentence or command example in the requirements.
- `setup_entities` must include the action target and every related row the
  action reads. Use prompt entity nouns only. For a simple standalone program
  with no stored entity, use `"when": {{"app": true, "args": [...]}}`,
  `"setup_entities": []`, and `"expect": {{"stdout_contains": "...",
  "exit_code": 0}}` instead.
- `expect.state` lists observable `alias.field` paths, without values.
  `expect.rows` lists expected row counts by entity. `expect.error` names an
  error only when the requirements name or clearly describe it. App plans use
  `expect.stdout_contains` and `expect.exit_code` instead.
- Do not plan a case with no observable outcome.
- Do not invent sort options, file abstractions, statuses or payload shapes.
- `status` is `confirmed` only when the requirement states the behavior;
  otherwise `assumed` or `ambiguous`.

{schema_section}
REQUIREMENTS:
{requirements}

{resolved_section}
{coverage_section}
"""


def build_repair_prompt(requirements, payload, errors, resolved_section=""):
    return f"""You are repairing a prompt-derived verifier case set. The cases
below were rejected by the case validator. Correct every listed error and return
the complete corrected JSON object matching the schema. Preserve valid cases.
Do not add test code. Do not use extracted architecture, contracts or generated
code.

SCHEMA:
{SCHEMA}

VALIDATION ERRORS:
{chr(10).join(f"- {error}" for error in errors)}

CURRENT CASES:
{json.dumps(payload, indent=2, ensure_ascii=False)}

REQUIREMENTS:
{requirements}

{resolved_section}
"""


def validate_plans(payload, requirements):
    """Mechanical checks on the case plan before values are materialized."""
    plans = payload.get("plans") if isinstance(payload, dict) else None
    if not isinstance(plans, list):
        return [], ["plan payload has no 'plans' list"]
    valid, errors = [], []
    for index, plan in enumerate(plans, start=1):
        errors_before = len(errors)
        if not isinstance(plan, dict):
            errors.append(f"plan {index}: not an object")
            continue
        source = plan.get("source")
        if not isinstance(source, str) or not source.strip():
            errors.append(f"plan {index}: missing source")
            continue
        if not _source_in_requirements(source, requirements):
            errors.append(f"plan {index}: source is not a prompt span")
            continue
        when = plan.get("when")
        if not isinstance(when, dict):
            errors.append(f"plan {index}: missing when")
            continue
        setup = plan.get("setup_entities")
        if not isinstance(setup, list):
            errors.append(f"plan {index}: setup_entities must be a list")
            continue
        aliases = set()
        for step in setup:
            if not isinstance(step, dict) or not step.get("alias") or not step.get("entity"):
                errors.append(f"plan {index}: setup entity needs alias and entity")
                continue
            if step["alias"] in aliases:
                errors.append(f"plan {index}: duplicate setup alias {step['alias']!r}")
            aliases.add(step["alias"])
        if when.get("app") is True:
            if setup:
                errors.append(f"plan {index}: app plan must not seed entities")
        else:
            action = when.get("action")
            cli = when.get("cli")
            if not action and not cli:
                errors.append(f"plan {index}: when needs action, cli or app")
                continue
            refs = list(when.get("args") or [])
            expect = plan.get("expect") or {}
            refs += list(expect.get("state") or [])
            for ref in refs:
                if isinstance(ref, str) and "." in ref:
                    head = ref.split(".", 1)[0]
                    if head not in aliases:
                        errors.append(
                            f"plan {index}: reference {ref!r} has no setup alias")
            if action and (expect.get("rows") or expect.get("state")) and not setup:
                errors.append(f"plan {index}: action has no setup entities")
        if len(errors) == errors_before:
            valid.append(plan)
    return valid, errors


def _source_in_requirements(source, requirements):
    def clean(value):
        text = str(value or "").replace("`", "").replace("*", "")
        return " ".join(text.split()).strip().casefold().rstrip(" .;:")
    wanted = clean(source)
    return bool(wanted) and wanted in clean(requirements)


def build_plan_repair_prompt(requirements, payload, errors):
    return f"""Correct this verifier CASE PLAN. Return the complete corrected
JSON object with the same plan schema. Preserve valid plans. Do not invent
entities, arguments, statuses or file abstractions.

VALIDATION ERRORS:
{chr(10).join(f"- {error}" for error in errors)}

CURRENT PLAN:
{json.dumps(payload, indent=2, ensure_ascii=False)}

REQUIREMENTS:
{requirements}
"""


def build_app_prompt(requirements, coverage=None):
    coverage_section = ""
    if coverage:
        listed = "\n".join(f"- {clause}" for clause in coverage)
        coverage_section = (
            "\nTARGET CLAUSES:\n" + listed + "\n"
            "Return only app cases for these clauses.\n")
    return f"""You are a requirements analyst for a stateless one-file program.
The program has no stored entities or domain records. Do not invent entities,
tables, repositories or setup rows. Test it as a process.

Return JSON:
{{"cases": [
  {{
    "id": "short_unique_id",
    "source": "exact sentence from the requirements",
    "given": {{}},
    "when": {{"app": true, "args": ["..."], "stdin": "",
              "files": {{"test.csv": "header1,header2\nvalue1,value2\n"}}}},
    "then": {{"stdout_contains": "...", "exit_code": 0}},
    "status": "confirmed | assumed | ambiguous"
  }}
]}}

Rules:
- `source` must be copied exactly from the requirements.
- Use `args` only for arguments named or clearly implied by the requirements.
  If the exact CLI argument syntax is not stated, mark the case `assumed`.
- When the program reads a file named by an argument, provide a small
  `when.files` fixture for that relative path.
- Assert observable stdout text and/or the process exit code.
- Do not use state, rows, entities, files or placeholders.
- At most 5 cases; choose the highest-risk behaviors.

REQUIREMENTS:
{requirements}
{coverage_section}
"""


def build_materialize_prompt(requirements, plans, resolved_section="",
                             domain_schema=None):
    plan_json = json.dumps({"plans": plans}, indent=2, ensure_ascii=False)
    schema_section = _schema_section(domain_schema)
    return f"""You are a requirements analyst. Read only the requirements and the
approved case plan below. Do not use or infer an extracted architecture,
method contract, database schema or generated code.

Materialize every plan into one concrete behavioral case. Preserve the plan's
source, action, setup entities and expected outcome. Fill concrete values and
all required setup rows. Do not add a case for any other requirement.

Return JSON matching:
{SCHEMA}

Rules:
- `source` must be copied exactly from the requirements.
- For every entity in a plan's `setup_entities`, create a concrete setup row
  with a distinct alias and concrete field values.
- For list/filter/search cases, seed enough rows to produce the expected count,
  including every parent row the filter reads.
- Use only actions, fields, entities and arguments named in the requirements.
  Do not invent sort options, file abstractions or payload shapes.
- `given` is flat alias -> field -> scalar. Use `book_1`, `book_2` for multiple rows.
- `then.state` is flat `alias.field` -> scalar.
- A simple standalone program may use `"given": {{}}`, `"when": {{"app": true,
  "args": [...]}}, and `"then": {{"stdout_contains": "...", "exit_code": 0}}`.
- For a create case, every expected field value must equal the supplied value
  unless the requirements say it is computed or defaulted.
- For a delete case, assert the resulting row count; do not read fields from the
  deleted row.
- Do not use placeholders. Never emit test code.

CASE PLAN:
{plan_json}
{schema_section}
REQUIREMENTS:
{requirements}

{resolved_section}
"""


def _strip_json_comments(raw):
    """Remove // comments outside strings, a common small-model habit."""
    out = []
    in_string = False
    escaped = False
    index = 0
    while index < len(raw):
        char = raw[index]
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < len(raw) and raw[index + 1] == "/":
            while index < len(raw) and raw[index] not in "\r\n":
                index += 1
            continue
        out.append(char)
        index += 1
    return "".join(out)


def parse_payload(text):
    """Extract the first JSON object from a model reply."""
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    candidate = _strip_json_comments(raw[start:end + 1])
    candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
    try:
        return json.loads(candidate)
    except ValueError:
        return None


def _build_per_clause(project, llm, framing, requirements, resolved_section,
                      coverage, domain_schema, max_new_tokens,
                      candidates, candidate_temperature, repair_attempts,
                      cases_name=None, out=print):
    selected = []
    plans_written = []
    for clause in coverage:
        plan_prompt = build_plan_prompt(
            requirements, resolved_section, coverage=[clause],
            domain_schema=domain_schema)
        plan_result = framing(llm, plan_prompt, f"oracle-plan:{project.name}",
                              temperature=0.0, max_new_tokens=max_new_tokens)
        if plan_result.truncated:
            continue
        plan_payload = parse_payload(plan_result.text)
        if plan_payload is None:
            continue
        plans, _plan_errors = validate_plans(plan_payload, requirements)
        plans = [plan for plan in plans
                 if plan.get("source") == clause
                 or _source_in_requirements(clause, plan.get("source") or "")]
        if not plans:
            continue
        plan = plans[0]
        plans_written.append(plan)
        best = None
        for candidate in range(max(1, candidates)):
            prompt = build_materialize_prompt(
                requirements, [plan], resolved_section,
                domain_schema=domain_schema)
            result = framing(
                llm, prompt,
                f"oracle-materialize:{project.name}:{candidate}",
                temperature=candidate_temperature if candidate else 0.0,
                max_new_tokens=max_new_tokens)
            if result.truncated:
                continue
            payload = parse_payload(result.text)
            if payload is None:
                continue
            valid, errors = case_rules.validate_cases(
                payload, requirements, requirements_sha(requirements))
            attempts = 0
            while errors and attempts < repair_attempts:
                attempts += 1
                repaired = framing(
                    llm, build_repair_prompt(requirements, payload, errors,
                                             resolved_section),
                    f"oracle-case-repair:{project.name}:{candidate}:{attempts}",
                    temperature=0.0, max_new_tokens=max_new_tokens)
                if repaired.truncated:
                    break
                repaired_payload = parse_payload(repaired.text)
                if repaired_payload is None:
                    break
                candidate_valid, candidate_errors = case_rules.validate_cases(
                    repaired_payload, requirements,
                    requirements_sha(requirements))
                if len(candidate_valid) > len(valid):
                    valid, errors, payload = (candidate_valid, candidate_errors,
                                              repaired_payload)
                else:
                    errors = candidate_errors or errors
            if valid:
                score = (len(valid[0].get("given") or {})
                         + len((valid[0].get("then") or {}).get("state") or {})
                         + len((valid[0].get("then") or {}).get("rows") or {}))
                if best is None or score > best[0]:
                    best = (score, valid[0])
        if best is not None:
            selected.append(best[1])
    path = case_rules.save_cases(
        project / (cases_name or case_rules.CASES_NAME), selected,
        prompt_sha=requirements_sha(requirements))
    (project / "oracle_case_plans.json").write_text(
        json.dumps({"plans": plans_written}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return selected, path


def build_one(project, model_path, context=8192, max_new_tokens=8192,
              out=print, coverage=None, append=False, cases_name=None,
              two_stage=False, repair_attempts=0, triage_simple=False,
              schema_aware=False, extracted_schema_mode=False,
              per_clause=False, candidates=1, candidate_temperature=0.3):
    project = Path(project)
    try:
        requirements = (project / "requirements.txt").read_text(encoding="utf-8")
    except OSError:
        raise SystemExit(f"no requirements.txt in {project}")
    decisions, sha = resolved.collect(project)
    (project / "oracle_spec.json").write_text(
        json.dumps({"requirements_sha": sha, "decisions": decisions},
                   indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    llm = runner.load_model(model_path, context_size=context, quiet=True)
    framing = runner.generate_chat if runner.has_chat_template(llm) else runner.generate_free
    resolved_section = resolved.prompt_section(project)
    simple_app = False
    if triage_simple:
        simple_app = triage.classify(llm, requirements).answer == "N"
    domain_schema = None
    if extracted_schema_mode and not simple_app:
        domain_schema = extracted_schema(project)
        if domain_schema:
            (project / "oracle_domain_schema.json").write_text(
                json.dumps(domain_schema, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8")
    if schema_aware and not simple_app and not domain_schema:
        schema_result = framing(
            llm, build_schema_prompt(requirements),
            f"oracle-schema:{project.name}",
            temperature=0.0, max_new_tokens=max_new_tokens)
        if schema_result.truncated:
            raise SystemExit(f"{project.name}: oracle schema was truncated")
        schema_payload = parse_payload(schema_result.text)
        if schema_payload is None:
            (project / "oracle_schema.err").write_text(
                schema_result.text, encoding="utf-8")
            raise SystemExit(f"{project.name}: oracle schema was not JSON")
        domain_schema, schema_errors = validate_schema(schema_payload)
        (project / "oracle_domain_schema.json").write_text(
            json.dumps(domain_schema or {}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        if schema_errors:
            out(f"{project.name}: schema rejected: {'; '.join(schema_errors)}")
            domain_schema = None
    if per_clause and coverage:
        selected, path = _build_per_clause(
            project, llm, framing, requirements, resolved_section, coverage,
            domain_schema, max_new_tokens, candidates, candidate_temperature,
            repair_attempts, cases_name=cases_name, out=out)
        out(f"{project.name}: {len(selected)} case(s) -> {path}")
        return selected, []
    if simple_app:
        prompt = build_app_prompt(requirements, coverage=coverage)
        label = f"oracle-app:{project.name}"
    elif two_stage:
        plan_prompt = build_plan_prompt(requirements, resolved_section,
                                        coverage=coverage,
                                        domain_schema=domain_schema)
        plan_result = framing(llm, plan_prompt, f"oracle-plan:{project.name}",
                              temperature=0.0, max_new_tokens=max_new_tokens)
        if plan_result.truncated:
            raise SystemExit(f"{project.name}: oracle plan was truncated")
        plan_payload = parse_payload(plan_result.text)
        if plan_payload is None:
            (project / "oracle_plan.err").write_text(
                plan_result.text, encoding="utf-8")
            raise SystemExit(f"{project.name}: oracle plan was not JSON")
        plans, plan_errors = validate_plans(plan_payload, requirements)
        plan_attempts = 0
        while plan_errors and plan_attempts < repair_attempts:
            plan_attempts += 1
            repaired = framing(llm, build_plan_repair_prompt(
                requirements, plan_payload, plan_errors),
                f"oracle-plan-repair:{project.name}:{plan_attempts}",
                temperature=0.0, max_new_tokens=max_new_tokens)
            if repaired.truncated:
                break
            repaired_payload = parse_payload(repaired.text)
            if repaired_payload is None:
                break
            candidate, candidate_errors = validate_plans(
                repaired_payload, requirements)
            if len(candidate) > len(plans):
                plans, plan_errors, plan_payload = candidate, candidate_errors, repaired_payload
            else:
                plan_errors = candidate_errors or plan_errors
        (project / "oracle_case_plans.json").write_text(
            json.dumps({"plans": plans}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        prompt = build_materialize_prompt(requirements, plans, resolved_section,
                                           domain_schema=domain_schema)
        label = f"oracle-materialize:{project.name}"
    else:
        prompt = build_prompt(requirements, resolved_section,
                              coverage=coverage, domain_schema=domain_schema)
        label = f"oracle:{project.name}"
    result = framing(llm, prompt, label,
                     temperature=0.0, max_new_tokens=max_new_tokens)
    if result.truncated:
        raise SystemExit(f"{project.name}: oracle answer was truncated")
    payload = parse_payload(result.text)
    if payload is None:
        (project / "oracle_build.err").write_text(
            result.text, encoding="utf-8")
        raise SystemExit(f"{project.name}: oracle answer was not JSON")
    sha = requirements_sha(requirements)
    valid, errors = case_rules.validate_cases(payload, requirements, sha)
    attempts = 0
    while errors and attempts < repair_attempts:
        attempts += 1
        repair_prompt = build_repair_prompt(
            requirements, payload, errors, resolved_section)
        repaired = framing(llm, repair_prompt,
                           f"oracle-repair:{project.name}:{attempts}",
                           temperature=0.0, max_new_tokens=max_new_tokens)
        if repaired.truncated:
            break
        repaired_payload = parse_payload(repaired.text)
        if repaired_payload is None:
            break
        candidate, candidate_errors = case_rules.validate_cases(
            repaired_payload, requirements, sha)
        if len(candidate) > len(valid):
            valid, errors, payload = candidate, candidate_errors, repaired_payload
        else:
            errors = candidate_errors or errors
    if append:
        existing = case_rules.load_cases(project / case_rules.CASES_NAME)
        valid = case_rules.validate_cases(
            {"cases": list(existing) + list(valid)}, requirements, sha)[0]
    path = case_rules.save_cases(project / (cases_name or case_rules.CASES_NAME),
                                 valid, prompt_sha=sha)
    out(f"{project.name}: {len(valid)} case(s) -> {path}")
    if errors:
        out(f"{project.name}: {len(errors)} rejected case(s)")
        for error in errors:
            out(f"  - {error}")
    return valid, errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", help="validation root containing prompt_* directories")
    parser.add_argument("--model", default="server",
                        help="GGUF path or `server` (default: server)")
    parser.add_argument("--server-url", default=None,
                        help="llama-server URL (sets LLAMA_SERVER_URL)")
    parser.add_argument("--only", default=None,
                        help="comma-separated prompt names")
    parser.add_argument("--context", type=int, default=8192)
    parser.add_argument("--max-new-tokens", type=int, default=8192)
    parser.add_argument("--coverage", default=None,
                        help="coverage.json: target mapped-but-untested clauses")
    parser.add_argument("--append", action="store_true",
                        help="append new cases instead of replacing the sidecar")
    parser.add_argument("--cases-name", default=None,
                        help="output case sidecar filename (default: oracle_cases.json)")
    parser.add_argument("--two-stage", action="store_true",
                        help="plan case intents first, then materialize values")
    parser.add_argument("--repair-attempts", type=int, default=0,
                        help="same-model repair attempts after case validation")
    parser.add_argument("--triage-simple", action="store_true",
                        help="use the extractor's domain triage for app-only cases")
    parser.add_argument("--schema-aware", action="store_true",
                        help="plan from a prompt-derived neutral domain schema")
    parser.add_argument("--extracted-schema", action="store_true",
                        help="1b diagnostic: use extracted data_models as schema")
    parser.add_argument("--per-clause", action="store_true",
                        help="one plan, multiple candidates and repairs per clause")
    parser.add_argument("--candidates", type=int, default=1,
                        help="materialization candidates per clause")
    parser.add_argument("--candidate-temperature", type=float, default=0.3)
    args = parser.parse_args(argv)
    if args.server_url:
        import os
        os.environ["LLAMA_SERVER_URL"] = args.server_url
    root = Path(args.root)
    wanted = {item.strip() for item in args.only.split(",") if item.strip()} \
        if args.only else None
    projects = [path for path in sorted(root.glob("prompt_*"))
                if path.is_dir() and (wanted is None or path.name in wanted)]
    if not projects:
        raise SystemExit(f"no prompt directories under {root}")
    coverage = {}
    if args.coverage:
        payload = json.loads(Path(args.coverage).read_text(encoding="utf-8"))
        for item in payload.get("projects") or []:
            coverage[item.get("project")] = [
                row.get("text") for row in item.get("rows") or []
                if row.get("status") == "mapped_untested"
                and isinstance(row.get("text"), str)
            ]
    total = 0
    failed = []
    for project in projects:
        try:
            valid, _errors = build_one(
                project, args.model, args.context, args.max_new_tokens,
                coverage=coverage.get(project.name), append=args.append,
                cases_name=args.cases_name, two_stage=args.two_stage,
                repair_attempts=args.repair_attempts,
                triage_simple=args.triage_simple,
                schema_aware=args.schema_aware,
                extracted_schema_mode=args.extracted_schema,
                per_clause=args.per_clause,
                candidates=args.candidates,
                candidate_temperature=args.candidate_temperature)
        except (SystemExit, RuntimeError, OSError) as error:
            failed.append(project.name)
            print(f"{project.name}: oracle build failed ({error})")
            continue
        total += len(valid)
    print(f"total: {total} oracle case(s)")
    if failed:
        print("failed prompts: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
