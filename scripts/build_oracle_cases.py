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
from kernel.oracle import cases as case_rules  # noqa: E402

SCHEMA = """{
  "cases": [
    {
      "id": "short_unique_id",
      "source": "exact sentence from the requirements",
      "given": {
        "alias": {"field": "value"}
      },
      "when": {
        "action": "public action or method named by the requirement",
        "args": ["alias.field or literal"]
      },
      "then": {
        "state": {"alias.field": "expected value"},
        "error": "ErrorName or omit",
        "rows": {"Entity": 1}
      },
      "status": "confirmed | assumed | ambiguous | contradictory",
      "assumptions": ["only when status is assumed"],
      "ambiguities": ["only when status is ambiguous or contradictory"]
    }
  ]
}"""


def build_prompt(requirements):
    return f"""You are a requirements analyst. Read only the requirements below.
Do not use or infer an extracted architecture, database schema, method contract
or generated code. Produce externally observable behavioral cases.

Return one JSON object matching this schema:
{SCHEMA}

Rules:
- `source` must be copied exactly from a sentence or command example in the requirements.
- Use only behavior the requirements state. If a value or transition is not stated,
  use status `assumed` or `ambiguous` and explain the gap. Never silently fill it.
- If two requirements contradict, mark the affected cases `contradictory`.
- Prefer public actions a user can perform; do not invent implementation details.
- A case with no concrete expected outcome is not a test; leave it out or mark it ambiguous.
- `given` values are state before the action. `then.state` is state after the action.
- Do not write test code. Output JSON only.

REQUIREMENTS:
{requirements}
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


def build_one(project, model_path, context=8192, max_new_tokens=4096,
              out=print):
    project = Path(project)
    try:
        requirements = (project / "requirements.txt").read_text(encoding="utf-8")
    except OSError:
        raise SystemExit(f"no requirements.txt in {project}")
    llm = runner.load_model(model_path, context_size=context, quiet=True)
    framing = runner.generate_chat if runner.has_chat_template(llm) else runner.generate_free
    prompt = build_prompt(requirements)
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
    path = case_rules.save_cases(project / case_rules.CASES_NAME, valid,
                                 prompt_sha=sha)
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
    parser.add_argument("--max-new-tokens", type=int, default=4096)
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
    total = 0
    for project in projects:
        valid, _errors = build_one(project, args.model, args.context,
                                   args.max_new_tokens)
        total += len(valid)
    print(f"total: {total} oracle case(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
