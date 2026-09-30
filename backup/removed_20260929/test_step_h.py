import argparse
import json
import sys
from pathlib import Path

from llama_cpp import Llama

from extract_archi import GRAMMAR_PERSISTENCE_PORTS, run_extraction


def build_prompt(user_prompt):
    return (
        "<|im_start|>system\nYou are a software architect. Your task is to output a non-empty JSON object listing persistence ports. "
        "Read the requirements below and produce one repository entry per persisted entity model. "
        "Rules: "
        "(1) 'repositories' and 'entity_mappings' must never be empty — every model with a database table needs an entry. "
        "(2) The 'entity' field is the bare domain model name (e.g. 'Expense', 'Category') — never a class name like 'ExpenseRepository'. "
        "(3) If the requirements name a 'FooRepository', use entity='Foo', interface_name='FooRepository'. "
        "(4) Include standard CRUD methods plus any custom query/aggregate methods mentioned. "
        "(5) For each entity provide table name, primary key field, and relevant indexes. "
        "Output strictly in English as JSON: {\"persistence_ports\": {\"repositories\": [{\"entity\": \"...\", \"interface_name\": \"...\", \"methods\": [{\"name\": \"...\", \"description\": \"...\", \"params\": [{\"name\": \"...\", \"type\": \"...\"}], \"return_type\": \"...\"}]}], \"entity_mappings\": [{\"entity\": \"...\", \"table\": \"...\", \"primary_key\": \"...\", \"indexes\": [\"...\"]}]}}.<|im_end|>\n"
        f"<|im_start|>user\n{user_prompt}<|im_end|>\n<|im_start|>assistant\n"
        "{\"persistence_ports\": {\"repositories\": ["
    )


def validate_persistence_ports(payload):
    persistence_ports = payload.get("persistence_ports", {})
    repositories = persistence_ports.get("repositories", [])
    entity_mappings = persistence_ports.get("entity_mappings", [])

    if not repositories:
        raise ValueError("persistence_ports.repositories is empty — the model produced no repository entries.")
    if not entity_mappings:
        raise ValueError("persistence_ports.entity_mappings is empty — the model produced no entity mapping entries.")

    mapped_entities = {
        mapping.get("entity")
        for mapping in entity_mappings
        if mapping.get("entity")
    }
    invalid_entities = [
        repository.get("entity")
        for repository in repositories
        if repository.get("entity") not in mapped_entities
    ]

    if invalid_entities:
        raise ValueError(
            "Repository entities missing from entity mappings: "
            + ", ".join(str(e) for e in invalid_entities)
        )


def main():
    parser = argparse.ArgumentParser(description="Run only architecture extraction Step H.")
    parser.add_argument(
        "--model",
        default="../models/Ministral-3-3B-Instruct-2512-Q4_K_M.gguf",
        help="Path to the GGUF model",
    )
    parser.add_argument(
        "--prompt",
        default="prompts/prompt_expenses.txt",
        help="Path to the requirements prompt",
    )
    parser.add_argument(
        "--output",
        default="out/step_h_expenses_persistence_ports.json",
        help="Path for the generated persistence ports JSON",
    )
    args = parser.parse_args()

    user_prompt = Path(args.prompt).read_text(encoding="utf-8").strip()
    if not user_prompt:
        raise ValueError("Input prompt is empty.")

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

    MAX_RETRIES = 3
    payload = None
    for attempt in range(1, MAX_RETRIES + 1):
        if attempt > 1:
            print(f"⚠️  Retrying step H (attempt {attempt}/{MAX_RETRIES})...", file=sys.stderr)
        raw_json, _ = run_extraction(
            llm, build_prompt(user_prompt), GRAMMAR_PERSISTENCE_PORTS, "persistence_ports"
        )
        payload = json.loads(raw_json)
        try:
            validate_persistence_ports(payload)
            break
        except ValueError as e:
            print(f"❌ Validation failed (attempt {attempt}): {e}", file=sys.stderr)
            if attempt == MAX_RETRIES:
                raise

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Persistence ports validated and saved: {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
