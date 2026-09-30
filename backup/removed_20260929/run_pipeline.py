#!/usr/bin/env python3
"""
Full extraction pipeline for a single prompt: runs steps A-H and saves all outputs.
Each step that can fail is retried up to MAX_RETRIES times.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from llama_cpp import Llama

from extract_archi import (
    GRAMMAR_INTENTIONS,
    GRAMMAR_INVARIANTS,
    GRAMMAR_MODELES,
    GRAMMAR_COMPOSANTS,
    GRAMMAR_CONTRACTS,
    GRAMMAR_ADAPTERS,
    GRAMMAR_PERSISTENCE_PORTS,
    run_extraction,
)

MAX_RETRIES = 3


def build_prompt_intentions(user_prompt):
    return (
        "<|im_start|>system\nExtract core intentions (use cases/services). "
        "Do not list details. Output in English as JSON: {\"intentions\": []}.<|im_end|>\n"
        f"<|im_start|>user\n{user_prompt}<|im_end|>\n<|im_start|>assistant\n"
    )


def build_prompt_data_models(user_prompt):
    return (
        "<|im_start|>system\nExtract data model. Use ONLY generic types: "
        "'int', 'string', 'boolean', 'decimal', 'datetime', 'date', 'text', 'float'. "
        "For each field, specify boolean 'primary_key', 'nullable', 'unique', and 'status' ('explicit'|'deduced'). "
        "For 'foreign_key', use null if not a foreign key, or an object: "
        "{\"target_entity\": \"...\", \"target_field\": \"...\", \"relationship\": \"many_to_one\"|\"one_to_one\"|\"one_to_many\"}. "
        "Output strictly in English as JSON.<|im_end|>\n"
        f"<|im_start|>user\n{user_prompt}<|im_end|>\n<|im_start|>assistant\n"
    )


def build_prompt_invariants(user_prompt):
    return (
        "<|im_start|>system\nIdentify the business and data invariants explicitly stated or directly implied by the requirements. "
        "Each invariant must be a single, unique, concrete rule (e.g. 'isbn must be unique', 'available_copies must be >= 0'). "
        "Do not repeat, paraphrase, or generalize the same rule. Do not invent rules not grounded in the requirements. "
        "Stop as soon as all distinct rules are listed. "
        "Output strictly in English as JSON: {\"invariants\": [\"...\", \"...\"]}.<|im_end|>\n"
        f"<|im_start|>user\n{user_prompt}<|im_end|>\n<|im_start|>assistant\n"
    )


def build_prompt_components(user_prompt):
    return (
        "<|im_start|>system\nClassify tech components. Fallbacks: 1. Facade type: cli, api, gui. "
        "If empty: facade=cli + tech=argparse. 2. If api requested but no tech named: tech=flask. "
        "3. If gui requested but no tech named: tech=pyimgui. 4. If persistence requested but no DB named: tech=sqlite. "
        "If none: required=false + tech=none. 5. external_access: list cloud services. "
        "6. crud_services: list the bare domain model entities (e.g. 'Book', 'Expense', never 'BookRepository' or service class names) "
        "with their CRUD operations (subset of [\"create\", \"read_one\", \"read_all\", \"update\", \"delete\"]). "
        "Output strictly in English as JSON.<|im_end|>\n"
        f"<|im_start|>user\n{user_prompt}<|im_end|>\n<|im_start|>assistant\n"
    )


def build_prompt_contracts(user_prompt):
    return (
        "<|im_start|>system\nExtract high-level business service method signatures with parameters and return types. "
        "Include domain services and repository custom aggregates (e.g. get_total_by_category_and_month). "
        "Output strictly in English as JSON: {\"service_contracts\": [{\"service_name\": \"...\", \"methods\": "
        "[{\"name\": \"...\", \"description\": \"...\", \"params\": [{\"name\": \"...\", \"type\": \"...\"}], \"return_type\": \"...\"}]}]}.<|im_end|>\n"
        f"<|im_start|>user\n{user_prompt}<|im_end|>\n<|im_start|>assistant\n"
    )


def build_prompt_adapters(user_prompt):
    return (
        "<|im_start|>system\nExtract abstract interaction adapters mapping external input actions to domain service method parameters. "
        "Transforms allowed: 'DIRECT', 'LOOKUP_ID', 'DECIMAL_TO_CENTS', 'ISO_DATE', 'CSV_LIST', 'ENUM_LOOKUP'. "
        "Set 'lookup_entity' to the entity name if transform is 'LOOKUP_ID', else null. "
        "Output strictly in English as JSON: {\"interaction_adapters\": [{\"action_name\": \"...\", \"target_service\": \"...\", "
        "\"target_method\": \"...\", \"input_fields\": [{\"field_name\": \"...\", \"target_param\": \"...\", "
        "\"transform\": \"...\", \"lookup_entity\": null|\"...\", \"required\": true|false}]}]}.<|im_end|>\n"
        f"<|im_start|>user\n{user_prompt}<|im_end|>\n<|im_start|>assistant\n"
    )


def build_prompt_persistence_ports(user_prompt):
    return (
        "<|im_start|>system\nYou are a software architect. Your task is to output a non-empty JSON object listing persistence ports. "
        "Read the requirements below and produce one repository entry per persisted entity model. "
        "Rules: "
        "(1) 'repositories' and 'entity_mappings' must never be empty — every model with a database table needs an entry. "
        "(2) The 'entity' field is the bare domain model name (e.g. 'Expense', 'Category') — never a class name like 'ExpenseRepository'. "
        "(3) If the requirements name a 'FooRepository', use entity='Foo', interface_name='FooRepository'. "
        "(4) Include standard CRUD methods plus any custom query/aggregate methods mentioned. "
        "(5) For each entity provide table name, primary key field, and relevant indexes. "
        "Output strictly in English as JSON: {\"persistence_ports\": {\"repositories\": [{\"entity\": \"...\", "
        "\"interface_name\": \"...\", \"methods\": [{\"name\": \"...\", \"description\": \"...\", "
        "\"params\": [{\"name\": \"...\", \"type\": \"...\"}], \"return_type\": \"...\"}]}], "
        "\"entity_mappings\": [{\"entity\": \"...\", \"table\": \"...\", \"primary_key\": \"...\", \"indexes\": [\"...\"]}]}}.<|im_end|>\n"
        f"<|im_start|>user\n{user_prompt}<|im_end|>\n<|im_start|>assistant\n"
        "{\"persistence_ports\": {\"repositories\": ["
    )


def extract_with_retry(llm, prompt, grammar, label, validate_fn=None):
    """Run extraction, retrying up to MAX_RETRIES times if validate_fn raises."""
    for attempt in range(1, MAX_RETRIES + 1):
        if attempt > 1:
            print(f"⚠️  Retrying {label} (attempt {attempt}/{MAX_RETRIES})...", file=sys.stderr)
        raw, tok = run_extraction(llm, prompt, grammar, label)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"❌ JSON parse error on {label} attempt {attempt}: {e}", file=sys.stderr)
            if attempt == MAX_RETRIES:
                raise
            continue
        if validate_fn:
            try:
                validate_fn(payload)
            except ValueError as e:
                print(f"❌ Validation failed ({label} attempt {attempt}): {e}", file=sys.stderr)
                if attempt == MAX_RETRIES:
                    raise
                continue
        return payload, tok
    raise RuntimeError(f"All {MAX_RETRIES} attempts failed for {label}")


def validate_persistence_ports(payload):
    pp = payload.get("persistence_ports", {})
    repos = pp.get("repositories", [])
    mappings = pp.get("entity_mappings", [])
    if not repos:
        raise ValueError("repositories is empty")
    if not mappings:
        raise ValueError("entity_mappings is empty")
    mapped = {m.get("entity") for m in mappings if m.get("entity")}
    bad_entity = [r.get("entity") for r in repos if r.get("entity") not in mapped]
    if bad_entity:
        raise ValueError(f"Repository entities missing from entity_mappings: {bad_entity}")
    bad_names = [r.get("entity") for r in repos
                 if r.get("entity", "").endswith("Repository") or r.get("entity", "").endswith("Service")]
    if bad_names:
        raise ValueError(f"entity field contains class names instead of domain names: {bad_names}")


def validate_components(payload):
    crud = payload.get("components", {}).get("crud_services", [])
    bad = [i.get("entity") for i in crud
           if i.get("entity", "").endswith("Repository") or i.get("entity", "").endswith("Service")]
    if bad:
        raise ValueError(f"crud_services contains non-entity names: {bad}")


def main():
    parser = argparse.ArgumentParser(description="Run full extraction pipeline A-H for one prompt.")
    parser.add_argument("--model", default="../models/Ministral-3-3B-Instruct-2512-Q4_K_M.gguf")
    parser.add_argument("--prompt", required=True, help="Path to requirements prompt file")
    parser.add_argument("--output", required=True, help="Output directory for JSON files")
    parser.add_argument("--no-persistence", action="store_true",
                        help="Skip steps G and H (no database in this prompt)")
    args = parser.parse_args()

    user_prompt = Path(args.prompt).read_text(encoding="utf-8").strip()
    if not user_prompt:
        raise ValueError("Input prompt is empty.")

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Loading model from {args.model}...", file=sys.stderr)
    llm = Llama(
        model_path=args.model,
        n_ctx=8192,
        n_threads=8,
        n_threads_batch=8,
        flash_attn=False,
        logits_all=True,
        verbose=False,
    )

    def save(name, payload):
        p = out_dir / f"{name}.json"
        p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"  💾 Saved: {p}", file=sys.stderr)

    # A: Intentions
    p, _ = extract_with_retry(llm, build_prompt_intentions(user_prompt), GRAMMAR_INTENTIONS, "intentions")
    save("intentions", p)

    # B: Data models
    p, _ = extract_with_retry(llm, build_prompt_data_models(user_prompt), GRAMMAR_MODELES, "data_models")
    save("data_models", p)

    # C: Invariants
    p, _ = extract_with_retry(llm, build_prompt_invariants(user_prompt), GRAMMAR_INVARIANTS, "invariants")
    save("invariants", p)

    # D: Components
    p, _ = extract_with_retry(llm, build_prompt_components(user_prompt), GRAMMAR_COMPOSANTS, "components",
                               validate_fn=validate_components)
    save("components", p)

    # E: Service contracts
    p, _ = extract_with_retry(llm, build_prompt_contracts(user_prompt), GRAMMAR_CONTRACTS, "service_contracts")
    save("service_contracts", p)

    # G: Interaction adapters (skip for no-persistence prompts)
    if not args.no_persistence:
        p, _ = extract_with_retry(llm, build_prompt_adapters(user_prompt), GRAMMAR_ADAPTERS, "interaction_adapters")
        save("interaction_adapters", p)

        # H: Persistence ports
        p, _ = extract_with_retry(llm, build_prompt_persistence_ports(user_prompt),
                                   GRAMMAR_PERSISTENCE_PORTS, "persistence_ports",
                                   validate_fn=validate_persistence_ports)
        save("persistence_ports", p)

    print(f"\n✅ Pipeline complete for {args.prompt}", file=sys.stderr)


if __name__ == "__main__":
    main()
