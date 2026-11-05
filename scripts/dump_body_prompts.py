#!/usr/bin/env python3
"""Reconstruct the body prompts and answers for one generated run.

The generator asks one body at a time and overwrites the stub with the
accepted answer, so the original prompt is not in the dump by default. This
script replays that sequence without calling a model: it starts from the
mechanical render, rebuilds each prompt, reads the matching raw answer from
``llm_stub_answers.json``, and splices the answer exactly as ``fill_stubs``
did so the next prompt sees the same module text.

Usage:
    python3 scripts/dump_body_prompts.py out/expenses_correct

Writes:
    <out>/llm_stub_prompts.md
    <out>/llm_stub_prompts.json
"""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import generator  # noqa: E402


def _answers(output_dir):
    path = output_dir / "llm_stub_answers.json"
    if not path.is_file():
        raise SystemExit(f"missing {path}; run generator.py first")
    return {entry["label"]: entry for entry in json.loads(path.read_text())}


def _timing(entry):
    return {
        "status": entry.get("status"),
        "wall_seconds": entry.get("seconds"),
        "first_wall_seconds": entry.get("first_seconds"),
        "decode_seconds": entry.get("decode_seconds"),
        "first_decode_seconds": entry.get("first_decode_seconds"),
        "prompt_tokens": entry.get("prompt_tokens"),
        "first_prompt_tokens": entry.get("first_prompt_tokens"),
        "cached_tokens": entry.get("cached_tokens"),
        "first_cached_tokens": entry.get("first_cached_tokens"),
        "tokens": entry.get("tokens"),
        "first_tokens": entry.get("first_tokens"),
        "budget": entry.get("budget"),
        "finish_reason": entry.get("finish_reason"),
        "truncated": entry.get("truncated"),
        "repairs": entry.get("repairs"),
    }


def collect(output_dir):
    output_dir = Path(output_dir)
    ctx = generator.load_context(str(output_dir))
    requirements = generator.load_requirements(str(output_dir))
    stats = {
        "source": str(output_dir),
        "prog": output_dir.name,
        "implemented": 0,
        "stubs": 0,
        "stub_reasons": [],
    }
    files = generator.render_program(ctx, stats)
    answers = _answers(output_dir)
    contracts = ctx.get("contracts") or []

    records = []
    for filename in generator.STUB_FILES:
        text = files.get(filename)
        if not isinstance(text, str):
            continue
        references = ()
        if filename == "services.py":
            references = generator._method_signatures(
                files.get("repositories.py") or "")
        spans = generator.find_stub_spans(text)
        for planned in reversed(spans):
            label = f"{planned[2]['cls']}.{generator._stub_method(planned[2])}"
            entry = answers.get(label)
            if entry is None:
                continue
            span = next((found for found in generator.find_stub_spans(text)
                         if f"{found[2]['cls']}."
                         f"{generator._stub_method(found[2])}" == label), None)
            if span is None:
                continue
            start, end, info = span
            info = dict(info)
            info["file"] = filename
            method = generator._stub_method(info)
            contract = generator.contract_for(contracts, info["cls"], method)
            target_contract = (
                generator._target_contract(
                    info, files, requirements, contract=contract)
                if entry.get("context", "exact") == "exact" or contract
                else ())
            prompt = generator.stub_prompt(
                requirements, text, info, references,
                generator._exact_api_reference(files, filename),
                context=entry.get("context", "exact"),
                contract=target_contract)
            first_answer = entry.get("first_answer")
            complaints = entry.get("complaints") or []
            repair_prompt = None
            if first_answer and complaints:
                repair_prompt = generator.stub_prompt(
                    requirements, text, info, references,
                    generator._exact_api_reference(files, filename),
                    previous=first_answer, complaints=complaints,
                    context=entry.get("context", "exact"),
                    contract=target_contract)
            records.append({
                "label": label,
                "file": filename,
                "prompt": prompt,
                "first_answer": first_answer,
                "complaints": complaints,
                "repair_prompt": repair_prompt,
                "answer": entry.get("answer"),
                **_timing(entry),
            })

            # Replay the splice so the next prompt sees the same text.
            if entry.get("status") != "written" or not entry.get("answer"):
                continue
            body, _keyword_changes = generator._normalise_repository_keywords(
                generator._clean_body(entry["answer"]),
                files.get("repositories.py") or "")
            candidate = generator._spliced_candidate(
                text, start, end, info, body, "server")
            candidate, _added = generator._add_imports(
                candidate, "\n".join(body))
            text = candidate

        files[filename] = text

    matches = {}
    generated = output_dir / "generated"
    for filename in generator.STUB_FILES:
        target = generated / filename
        matches[filename] = (
            target.is_file()
            and target.read_text(encoding="utf-8") == files.get(filename))
    return records, matches


def render_markdown(records, matches, output_dir):
    lines = [
        f"# Body prompts and answers: {output_dir}",
        "",
        "Prompts are reconstructed by replaying `fill_stubs` without a model. "
        "The answer text is the raw model answer stored in "
        "`llm_stub_answers.json`.",
        "",
        "Replay matches the generated files: "
        + ", ".join(f"`{name}`={'yes' if ok else 'NO'}"
                    for name, ok in matches.items()),
        "",
    ]
    for record in records:
        lines += [
            f"## {record['label']}",
            "",
            f"- status: `{record.get('status')}`",
            f"- file: `{record['file']}`",
            f"- wall: `{record.get('wall_seconds')}` s"
            f" (first: `{record.get('first_wall_seconds')}`)",
            f"- decode: `{record.get('decode_seconds')}` s",
            f"- prompt tokens: `{record.get('prompt_tokens')}`"
            f" (cached: `{record.get('cached_tokens')}`)",
            f"- completion tokens: `{record.get('tokens')}`",
            f"- repairs: `{record.get('repairs')}`",
            "",
            "### Prompt (first attempt)",
            "",
            "````text",
            record["prompt"].rstrip(),
            "````",
            "",
        ]
        if record.get("first_answer") is not None:
            lines += [
                "### First answer",
                "",
                "````text",
                (record["first_answer"] or "").rstrip(),
                "````",
                "",
            ]
        if record.get("complaints"):
            lines += ["### Complaints", ""]
            lines += [f"- {item}" for item in record["complaints"]]
            lines += [""]
        if record.get("repair_prompt"):
            lines += [
                "### Repair prompt",
                "",
                "````text",
                record["repair_prompt"].rstrip(),
                "````",
                "",
            ]
        lines += [
            "### Final answer",
            "",
            "````text",
            (record.get("answer") or "").rstrip(),
            "````",
            "",
        ]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir", help="generated output directory")
    args = parser.parse_args(argv)
    output_dir = Path(args.out_dir).resolve()
    records, matches = collect(output_dir)
    (output_dir / "llm_stub_prompts.json").write_text(
        json.dumps({"replay_matches": matches, "records": records}, indent=2)
        + "\n", encoding="utf-8")
    (output_dir / "llm_stub_prompts.md").write_text(
        render_markdown(records, matches, output_dir), encoding="utf-8")
    print(f"wrote {output_dir / 'llm_stub_prompts.json'}")
    print(f"wrote {output_dir / 'llm_stub_prompts.md'}")
    for name, ok in matches.items():
        print(f"replay {name}: {'match' if ok else 'MISMATCH'}")


if __name__ == "__main__":
    main()
