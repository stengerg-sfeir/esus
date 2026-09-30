import argparse
import sys
import json
import time
from llama_cpp import Llama, LlamaGrammar

# --- GRAMMAIRES GBNF ROBUSTES (Espaces internes libres, arrêt immédiat à la fin) ---

GRAMMAR_INTENTIONS = r"""
root ::= "{" ws "\"intentions\"" ws ":" ws string-list ws "}"
string-list ::= "[" ws (string (ws "," ws string)*)? ws "]"
string ::= "\"" ([^"\\] | "\\" ["\\/bfnrt] | "\\u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F])* "\""
ws ::= [ \t\n\r]*
"""

GRAMMAR_INVARIANTS = r"""
root ::= "{" ws "\"invariants\"" ws ":" ws string-list ws "}"
string-list ::= "[" ws (string (ws "," ws string)*)? ws "]"
string ::= "\"" ([^"\\] | "\\" ["\\/bfnrt] | "\\u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F])* "\""
ws ::= [ \t\n\r]*
"""

GRAMMAR_MODELES = r"""
root ::= "{" ws "\"data_models\"" ws ":" ws entity-list ws "}"
entity-list ::= "[" ws (entity (ws "," ws entity)*)? ws "]"
entity ::= "{" ws "\"name\"" ws ":" ws string ws "," ws "\"fields\"" ws ":" ws field-list ws "}"
field-list ::= "[" ws (field (ws "," ws field)*)? ws "]"
field ::= "{" ws "\"name\"" ws ":" ws string ws "," ws "\"type\"" ws ":" ws string ws "," ws "\"status\"" ws ":" ws ("\"explicit\"" | "\"deduced\"") ws "}"
string ::= "\"" ([^"\\] | "\\" ["\\/bfnrt] | "\\u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F])* "\""
ws ::= [ \t\n\r]*
"""

def run_extraction(llm, full_prompt, grammar_str, label):
    """Exécute une extraction en streaming et compte précisément les tokens."""
    print(f"\n🚀 [Query] Extracting {label}...", file=sys.stderr)
    print(f"--- START OF {label.upper()} STREAM ---")
    
    grammar = LlamaGrammar.from_string(grammar_str)
    
    start_time = time.time()
    response_stream = llm(
        prompt=full_prompt,
        max_tokens=1524,
        temperature=0.1,
        grammar=grammar,
        stream=True
    )

    raw_json = ""
    token_count = 0
    
    for chunk in response_stream:
        if "choices" in chunk and len(chunk["choices"]) > 0:
            token = chunk["choices"][0]["text"]  # Index 0 explicite pour la stabilité
            raw_json += token
            token_count += 1
            
            # Affichage immédiat du token
            sys.stdout.write(token)
            sys.stdout.flush()
        
    end_time = time.time()
    duration = end_time - start_time
    speed = token_count / duration if duration > 0 else 0
    
    print(f"\n--- END OF {label.upper()} STREAM ---")
    print(f"📊 Stats {label} : {token_count} tokens generated in {duration:.2f}s ({speed:.1f} tok/s)", file=sys.stderr)
    
    return raw_json, token_count

def main():
    parser = argparse.ArgumentParser(description="Modular software architecture extractor.")
    parser.add_argument("--model", type=str, required=True, help="Path to GGUF model")
    parser.add_argument("--output", type=str, help="Prefix for output files")
    args = parser.parse_args()

    user_prompt = sys.stdin.read().strip()
    if not user_prompt:
        print("Error: Input prompt is empty.", file=sys.stderr)
        sys.exit(1)

    # 1. Configuration à 8 threads (recommandée pour de meilleures performances CPU)
    print("[1/2] Initializing model on CPU (8k context, 8 threads)...", file=sys.stderr)
    llm = Llama(
        model_path=args.model,
        n_ctx=8192,
        n_threads=8,
        n_threads_batch=8,
        flash_attn=False,
        verbose=False
    )

    # 2. Comptage des tokens du prompt initial
    system_base = "<|im_start|>system\nYou are an expert software engineer.<|im_end|>\n<|im_start|>user\n"
    prompt_tokens_count = len(llm.tokenize(bytes(system_base + user_prompt, 'utf-8')))
    print(f"📊 Input prompt size: ~{prompt_tokens_count} tokens.\n", file=sys.stderr)

    total_generated_tokens = 0
    results = {}

    # --- STEP A: INTENTIONS (SERVICES & USE CASES) ---
    prompt_intentions = (
        "<|im_start|>system\n"
        "You are an expert software architect. Analyze the provided user specifications. "
        "Extract ONLY the core business intentions, meaning the services, actions, features, and use cases that need to be implemented (e.g., 'Printing a Hello World message to the console', 'Exporting data to CSV'). "
        "Do NOT describe or list database tables, fields or models here. "
        "Your output must be strictly in English. "
        "Output your findings exclusively as a strict JSON object following exactly this structure: {\"intentions\": [\"service 1\", \"service 2\"]}."
        "<|im_end|>\n"
        f"<|im_start|>user\n{user_prompt}<|im_end|>\n<|im_start|>assistant\n"
    )
    json_intentions, tok_a = run_extraction(llm, prompt_intentions, GRAMMAR_INTENTIONS, "intentions")
    total_generated_tokens += tok_a
    results["intentions"] = json_intentions

    # --- STEP B: DATA MODEL ---
    prompt_modeles = (
        "<|im_start|>system\n"
        "You are an expert software architect. Analyze the provided user specifications. "
        "Extract the complete data model, identifying the entities, their fields, types, and whether they are explicitly requested or logically deduced. "
        "If the requirements do not specify or require any data persistence, objects, or tables (like a simple hello world script), return an empty list. "
        "Your output must be strictly in English. "
        "You MUST output your findings exclusively as a strict JSON object mapping exactly to this structure: "
        "{\"data_models\": [{\"name\": \"EntityName\", \"fields\": [{\"name\": \"fieldName\", \"type\": \"dataType\", \"status\": \"explicit|deduced\"}]}]}."
        "<|im_end|>\n"
        f"<|im_start|>user\n{user_prompt}<|im_end|>\n<|im_start|>assistant\n"
    )
    json_modeles, tok_b = run_extraction(llm, prompt_modeles, GRAMMAR_MODELES, "data_models")
    total_generated_tokens += tok_b
    results["data_models"] = json_modeles

    # --- STEP C: INVARIANTS ---
    prompt_invariants = (
        "<|im_start|>system\n"
        "You are an expert software architect. Analyze the provided user specifications. "
        "Identify and extract all systemic invariants, static constraints, and immutable business rules that the application logic must always satisfy (e.g., 'Main function must use type hints'). "
        "If there are no specific business constraints or database restrictions, return an empty list. "
        "Your output must be strictly in English. "
        "Output your findings exclusively as a strict JSON object following exactly this structure: {\"invariants\": [\"invariant 1\", \"invariant 2\"]}."
        "<|im_end|>\n"
        f"<|im_start|>user\n{user_prompt}<|im_end|>\n<|im_start|>assistant\n"
    )
    json_invariants, tok_c = run_extraction(llm, prompt_invariants, GRAMMAR_INVARIANTS, "invariants")
    total_generated_tokens += tok_c
    results["invariants"] = json_invariants

    # 3. Sauvegarde optionnelle
    if args.output:
        for key, raw_content in results.items():
            file_name = f"{args.output}_{key}.json"
            try:
                clean_json = json.loads(raw_content)
                with open(file_name, "w", encoding="utf-8") as f:
                    json.dump(clean_json, f, indent=2, ensure_ascii=False)
                print(f"💾 File saved: {file_name}", file=sys.stderr)
            except json.JSONDecodeError:
                with open(file_name, "w", encoding="utf-8") as f:
                    f.write(raw_content)
                print(f"⚠️ File saved raw (JSON Error): {file_name}", file=sys.stderr)

    # Global Summary
    print("\n==========================================", file=sys.stderr)
    print(f"🏆 TOTAL TOKENS SUMMARY:", file=sys.stderr)
    print(f" -> Prompt Tokens: {prompt_tokens_count}", file=sys.stderr)
    print(f" -> Generated Tokens (Total): {total_generated_tokens}", file=sys.stderr)
    print("==========================================", file=sys.stderr)

if __name__ == "__main__":
    main()

