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

from kernel.extraction import runner  # noqa: E402
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


def build_prompt(requirements, resolved_section="", coverage=None):
    coverage_section = ""
    if coverage:
        listed = "\n".join(f"- {clause}" for clause in coverage)
        coverage_section = (
            "\nUNCOVERED REQUIREMENT CLAUSES TO TARGET:\n"
            f"{listed}\n"
            "Generate additional cases specifically for these clauses. Do not "
            "duplicate an action/setup already covered by the requirements. "
            "Keep the same prompt-only, observable-behavior rules.\n"
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

REQUIREMENTS:
{requirements}

{resolved_section}
{coverage_section}
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


def build_one(project, model_path, context=8192, max_new_tokens=8192,
              out=print, coverage=None, append=False, cases_name=None):
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
    prompt = build_prompt(requirements, resolved.prompt_section(project),
                          coverage=coverage)
    result = framing(llm, prompt, f"oracle:{project.name}",
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
                cases_name=args.cases_name)
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
