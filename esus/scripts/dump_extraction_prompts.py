#!/usr/bin/env python3
"""Reconstruct the extraction prompts and archived answers for one run.

The archived documents are the model's parsed answers. The prompts are rebuilt
from the requirements and those archived documents with the same prompt
builders the pipeline uses. This is a reconstruction from the archive, not a
recording: a later deterministic repair can make an earlier document differ
from what the next step originally saw, and a retry prompt contains the
previous attempt's misses, which are not archived.

Usage:
    python3 scripts/dump_extraction_prompts.py out/expenses_correct

Writes:
    <out>/extraction_prompts.md
    <out>/extraction_prompts.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import generator  # noqa: E402
from kernel.consistency.loader import load_documents  # noqa: E402
from kernel.consistency.report import Report  # noqa: E402
from kernel.extraction import command_lines, prompts, vocabulary  # noqa: E402


def _log_text(output_dir):
    path = Path(output_dir) / "logs" / "extract.log"
    return path.read_text(encoding="utf-8", errors="replace") \
        if path.is_file() else ""


def _retry_steps(log):
    retries = set()
    for line in log.splitlines():
        match = re.search(
            r"\[!\] step (components|contracts|adapters|persistence|"
            r"interaction_adapters|service_contracts) (?:omits|has|is)",
            line)
        if match:
            retries.add(match.group(1))
    return retries


def _record(step, prompt, answer, *, note=None, retry=False,
            review_rerun=False):
    return {
        "step": step,
        "prompt": prompt,
        "answer": answer,
        "retry_detected": retry,
        "review_rerun_detected": review_rerun,
        "note": note,
    }


def collect(output_dir):
    output_dir = Path(output_dir)
    docs = load_documents(str(output_dir), Report(output_dir.name))
    requirements = generator.load_requirements(str(output_dir))
    log = _log_text(output_dir)
    retries = _retry_steps(log)
    review_rerun = "--- resumed ---" in log

    models = docs.get("data_models") or []
    entities = vocabulary.entities_from(models)
    contracts = docs.get("service_contracts") or []
    services = vocabulary.services_from(contracts)
    components = docs.get("components")
    errors = docs.get("errors") or []

    records = []
    records.append(_record(
        "intentions",
        prompts.intentions(requirements),
        docs.get("intentions"),
        note="First extraction document.",
        retry="intentions" in retries,
        review_rerun=review_rerun,
    ))
    records.append(_record(
        "data_models",
        prompts.data_models(
            requirements,
            prompts.intentions_block(docs.get("intentions"))),
        models,
        note="The answer shown is archived after deterministic primary-key/"
             "foreign-key repairs.",
        retry="data_models" in retries,
        review_rerun=review_rerun,
    ))
    entity_names = prompts.entity_block(
        vocabulary.Vocabulary(entities=entities)) if entities else None
    records.append(_record(
        "errors",
        prompts.errors(requirements, entity_names),
        errors,
        note="The archived errors are post-repair; the historical prompt "
             "may have seen the pre-repair registry.",
        retry="errors" in retries,
        review_rerun=review_rerun,
    ))
    records.append(_record(
        "invariants",
        prompts.invariants(requirements, entity_names),
        docs.get("invariants"),
        note="The archived data model may include a later period-field repair.",
        retry="invariants" in retries,
        review_rerun=review_rerun,
    ))
    spans = command_lines.extract_command_lines(requirements)
    components_block = prompts.components_block(
        vocabulary.Vocabulary(entities=entities))
    records.append(_record(
        "components",
        prompts.components(
            requirements, components_block,
            prompts.command_lines_block(spans)),
        components,
        note=("A retry was logged. The archived components may be the retry "
              "answer; its prompt also appended the previous attempt's missing "
              "surface item, which is not archived."
              if "components" in retries else
              "The answer shown is archived after deterministic surface "
              "repairs."),
        retry="components" in retries,
        review_rerun=review_rerun,
    ))
    contract_vocab = vocabulary.Vocabulary(
        entities=entities,
        crud_operations=vocabulary.crud_requirements(components),
        errors=errors,
    )
    records.append(_record(
        "service_contracts",
        prompts.service_contracts(
            requirements, prompts.requirements_block(contract_vocab)),
        contracts,
        note=("The answer shown is archived after return-type and interface "
              "repairs."),
        retry=("contracts" in retries or "service_contracts" in retries),
        review_rerun=review_rerun,
    ))
    records.append(_record(
        "pattern_matches",
        None,
        docs.get("pattern_matches"),
        note="Pattern matching uses next-token logits, not a text prompt; "
             "the archived list is its answer.",
        retry=False,
        review_rerun=review_rerun,
    ))
    adapter_vocab = vocabulary.Vocabulary(entities=entities, services=services)
    records.append(_record(
        "interaction_adapters",
        prompts.adapters(
            requirements, prompts.combined_block(adapter_vocab)),
        docs.get("interaction_adapters"),
        note=("The answer shown is archived after deterministic transform, "
              "target and field-name repairs."),
        retry=("adapters" in retries or "interaction_adapters" in retries),
        review_rerun=review_rerun,
    ))
    persistence_vocab = vocabulary.Vocabulary(
        entities=entities,
        crud_entities=vocabulary.crud_entity_names(components),
        crud_operations=vocabulary.crud_requirements(components),
    )
    records.append(_record(
        "persistence_ports",
        prompts.persistence_ports(
            requirements,
            prompts.requirements_block(persistence_vocab)),
        docs.get("persistence_ports"),
        note="The answer shown is archived after interface unification and "
             "deterministic port repairs.",
        retry=("persistence" in retries or "persistence_ports" in retries),
        review_rerun=review_rerun,
    ))
    return records, {
        "requirements_sha": docs.get("requirements_sha"),
        "retry_steps": sorted(retries),
        "review_rerun": review_rerun,
        "note": "Reconstruction from the archive, not a recording of the "
                "historical requests. Later repairs can change an earlier "
                "document; retry prompts appended misses that are not archived.",
    }


def render_markdown(records, meta, output_dir):
    lines = [
        f"# Extraction prompts and archived answers: {output_dir}",
        "",
        f"Retry steps detected: {', '.join(meta['retry_steps']) or 'none'}",
        f"Review-loop rerun detected: {'yes' if meta['review_rerun'] else 'no'}",
        "",
        meta["note"],
        "",
    ]
    for record in records:
        lines += [
            f"## {record['step']}",
            "",
            f"- retry detected: `{record['retry_detected']}`",
            f"- review rerun detected: `{record['review_rerun_detected']}`",
        ]
        if record.get("note"):
            lines += [f"- note: {record['note']}"]
        lines += [""]
        if record.get("prompt") is None:
            lines += [
                "### Prompt",
                "",
                "_No text prompt; this step classifies with next-token logits._",
                "",
            ]
        else:
            lines += [
                "### Prompt",
                "",
                "````text",
                record["prompt"].rstrip(),
                "````",
                "",
            ]
        lines += [
            "### Archived answer",
            "",
            "````json",
            json.dumps(record.get("answer"), indent=2, ensure_ascii=False),
            "````",
            "",
        ]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir", help="extraction output directory")
    args = parser.parse_args(argv)
    output_dir = Path(args.out_dir).resolve()
    records, meta = collect(output_dir)
    (output_dir / "extraction_prompts.json").write_text(
        json.dumps({"meta": meta, "records": records}, indent=2,
                   ensure_ascii=False) + "\n", encoding="utf-8")
    (output_dir / "extraction_prompts.md").write_text(
        render_markdown(records, meta, output_dir), encoding="utf-8")
    print(f"wrote {output_dir / 'extraction_prompts.json'}")
    print(f"wrote {output_dir / 'extraction_prompts.md'}")
    print(f"retry steps: {', '.join(meta['retry_steps']) or 'none'}")


if __name__ == "__main__":
    main()
