import argparse
import json
import sys
from pathlib import Path

from llama_cpp import Llama

from extract_archi import (
    GRAMMAR_INVARIANTS,
    GRAMMAR_COMPOSANTS,
    run_extraction,
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


def validate_invariants(payload):
    invariants = payload.get("invariants", [])
    if not invariants:
        raise ValueError("invariants list is empty.")
    duplicates = [x for x in invariants if invariants.count(x) > 1]
    if duplicates:
        raise ValueError(f"Duplicate invariants found: {set(duplicates)}")
    print(f"  ✅ {len(invariants)} invariants, no duplicates.", file=sys.stderr)


def validate_components(payload):
    components = payload.get("components", {})
    crud = components.get("crud_services", [])
    bad = [item["entity"] for item in crud if item.get("entity", "").endswith("Repository") or item.get("entity", "").endswith("Service")]
    if bad:
        raise ValueError(f"crud_services contains non-entity names: {bad}")
    print(f"  ✅ {len(crud)} crud_services entities, all bare domain names.", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Test Step C (invariants) and Step D (components).")
    parser.add_argument(
        "--model",
        default="../models/Ministral-3-3B-Instruct-2512-Q4_K_M.gguf",
        help="Path to the GGUF model",
    )
    parser.add_argument(
        "--prompt",
        default="prompts/prompt_library_system.txt",
        help="Path to the requirements prompt",
    )
    parser.add_argument(
        "--output",
        default="out/step_cd_library",
        help="Output prefix for the generated JSON files",
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

    # --- STEP C: INVARIANTS ---
    raw_c, _ = run_extraction(llm, build_prompt_invariants(user_prompt), GRAMMAR_INVARIANTS, "invariants")
    payload_c = json.loads(raw_c)
    print("\nValidating invariants...", file=sys.stderr)
    validate_invariants(payload_c)

    out_c = Path(f"{args.output}_invariants.json")
    out_c.parent.mkdir(parents=True, exist_ok=True)
    out_c.write_text(json.dumps(payload_c, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved: {out_c}", file=sys.stderr)

    # --- STEP D: COMPONENTS ---
    raw_d, _ = run_extraction(llm, build_prompt_components(user_prompt), GRAMMAR_COMPOSANTS, "components")
    payload_d = json.loads(raw_d)
    print("\nValidating components...", file=sys.stderr)
    validate_components(payload_d)

    out_d = Path(f"{args.output}_components.json")
    out_d.write_text(json.dumps(payload_d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved: {out_d}", file=sys.stderr)


if __name__ == "__main__":
    main()
