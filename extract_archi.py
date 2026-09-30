import argparse
import difflib
import re
import sys
import json
import time
from llama_cpp import Llama, LlamaGrammar
from kernel.classifier.hierarchical_classifier import load_catalog, classify_requirement_2step

# --- GRAMMAIRES GBNF SPÉCIALISÉES (Structure Anglaise & Clés Stricte) ---

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

field ::= "{" ws "\"name\"" ws ":" ws string ws "," ws "\"type\"" ws ":" ws generic-type ws "," ws "\"primary_key\"" ws ":" ws boolean ws "," ws "\"nullable\"" ws ":" ws boolean ws "," ws "\"unique\"" ws ":" ws boolean ws "," ws "\"foreign_key\"" ws ":" ws ( "null" | foreign-key-obj ) ws "," ws "\"status\"" ws ":" ws ("\"explicit\"" | "\"deduced\"") ws "}"

foreign-key-obj ::= "{" ws "\"target_entity\"" ws ":" ws string ws "," ws "\"target_field\"" ws ":" ws string ws "," ws "\"relationship\"" ws ":" ws ("\"many_to_one\"" | "\"one_to_one\"" | "\"one_to_many\"") ws "}"

boolean ::= "true" | "false"
generic-type ::= "\"int\"" | "\"string\"" | "\"boolean\"" | "\"decimal\"" | "\"datetime\"" | "\"date\"" | "\"text\"" | "\"float\""

string ::= "\"" ([^"\\] | "\\" ["\\/bfnrt] | "\\u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F])* "\""
ws ::= [ \t\n\r]*
"""

GRAMMAR_COMPOSANTS = r"""
root ::= "{" ws "\"components\"" ws ":" ws "{" ws "\"facade\"" ws ":" ws facade-obj ws "," ws "\"persistence\"" ws ":" ws persistence-obj ws "," ws "\"external_access\"" ws ":" ws string-list ws "," ws "\"crud_services\"" ws ":" ws crud-list ws "}" ws "}"
facade-obj ::= "{" ws "\"type\"" ws ":" ws ("\"cli\"" | "\"api\"" | "\"gui\"") ws "," ws "\"technology\"" ws ":" ws string ws "}"
persistence-obj ::= "{" ws "\"required\"" ws ":" ws ("true" | "false") ws "," ws "\"technology\"" ws ":" ws string ws "}"
crud-list ::= "[" ws (crud-item (ws "," ws crud-item)*)? ws "]"
crud-item ::= "{" ws "\"entity\"" ws ":" ws string ws "," ws "\"operations\"" ws ":" ws operation-list ws "}"
operation-list ::= "[" ws (operation (ws "," ws operation)*)? ws "]"
operation ::= "\"create\"" | "\"read_one\"" | "\"read_all\"" | "\"update\"" | "\"delete\""
string-list ::= "[" ws (string (ws "," ws string)*)? ws "]"
string ::= "\"" ([^"\\] | "\\" ["\\/bfnrt] | "\\u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F])* "\""
ws ::= [ \t\n\r]*
"""

GRAMMAR_CONTRACTS = r"""
root ::= "{" ws "\"service_contracts\"" ws ":" ws contract-list ws "}"
contract-list ::= "[" ws (contract (ws "," ws contract)*)? ws "]"
contract ::= "{" ws "\"service_name\"" ws ":" ws string ws "," ws "\"methods\"" ws ":" ws method-list ws "}"
method-list ::= "[" ws (method (ws "," ws method)*)? ws "]"
method ::= "{" ws "\"name\"" ws ":" ws string ws "," ws "\"description\"" ws ":" ws string ws "," ws "\"params\"" ws ":" ws param-list ws "," ws "\"return_type\"" ws ":" ws string ws "}"
param-list ::= "[" ws (param (ws "," ws param)*)? ws "]"
param ::= "{" ws "\"name\"" ws ":" ws string ws "," ws "\"type\"" ws ":" ws string ws "}"
string ::= "\"" ([^"\\] | "\\" ["\\/bfnrt] | "\\u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F])* "\""
ws ::= [ \t\n\r]*
"""

GRAMMAR_ADAPTERS = r"""
root ::= "{" ws "\"interaction_adapters\"" ws ":" ws adapter-list ws "}"
adapter-list ::= "[" ws (adapter (ws "," ws adapter)*)? ws "]"
adapter ::= "{" ws "\"action_name\"" ws ":" ws string ws "," ws "\"target_service\"" ws ":" ws string ws "," ws "\"target_method\"" ws ":" ws string ws "," ws "\"input_fields\"" ws ":" ws input-field-list ws "}"
input-field-list ::= "[" ws (input-field (ws "," ws input-field)*)? ws "]"
input-field ::= "{" ws "\"field_name\"" ws ":" ws string ws "," ws "\"target_param\"" ws ":" ws string ws "," ws "\"transform\"" ws ":" ws transform-type ws "," ws "\"lookup_entity\"" ws ":" ws ( "null" | string ) ws "," ws "\"required\"" ws ":" ws boolean ws "}"
transform-type ::= "\"DIRECT\"" | "\"LOOKUP_ID\"" | "\"DECIMAL_TO_CENTS\"" | "\"ISO_DATE\"" | "\"CSV_LIST\"" | "\"ENUM_LOOKUP\""
boolean ::= "true" | "false"
string ::= "\"" ([^"\\] | "\\" ["\\/bfnrt] | "\\u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F])* "\""
ws ::= [ \t\n\r]*
"""

GRAMMAR_PERSISTENCE_PORTS = r"""
root ::= "{" ws "\"persistence_ports\"" ws ":" ws "{" ws "\"repositories\"" ws ":" ws repository-list ws "," ws "\"entity_mappings\"" ws ":" ws mapping-list ws "}" ws "}"
repository-list ::= "[" ws (repository (ws "," ws repository)*)? ws "]"
repository ::= "{" ws "\"entity\"" ws ":" ws string ws "," ws "\"interface_name\"" ws ":" ws string ws "," ws "\"methods\"" ws ":" ws method-list ws "}"
method-list ::= "[" ws (method (ws "," ws method)*)? ws "]"
method ::= "{" ws "\"name\"" ws ":" ws string ws "," ws "\"description\"" ws ":" ws string ws "," ws "\"params\"" ws ":" ws param-list ws "," ws "\"return_type\"" ws ":" ws string ws "}"
param-list ::= "[" ws (param (ws "," ws param)*)? ws "]"
param ::= "{" ws "\"name\"" ws ":" ws string ws "," ws "\"type\"" ws ":" ws string ws "}"
mapping-list ::= "[" ws (mapping (ws "," ws mapping)*)? ws "]"
mapping ::= "{" ws "\"entity\"" ws ":" ws string ws "," ws "\"table\"" ws ":" ws string ws "," ws "\"primary_key\"" ws ":" ws string ws "," ws "\"indexes\"" ws ":" ws string-list ws "}"
string-list ::= "[" ws (string (ws "," ws string)*)? ws "]"
string ::= "\"" ([^"\\] | "\\" ["\\/bfnrt] | "\\u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F])* "\""
ws ::= [ \t\n\r]?
"""

def verify_extractions(results):
    """Effectue des vérifications déterministes sur les schémas extraits."""
    errors = []
    warnings = []
    
    # Check JSON validity
    parsed = {}
    for key, raw in results.items():
        try:
            parsed[key] = json.loads(raw)
        except json.JSONDecodeError as e:
            errors.append(f"Invalid JSON in {key}: {e}")
            
    if errors:
        return errors, warnings
        
    models = parsed.get("data_models", {}).get("data_models", [])
    model_names = {m.get("name") for m in models}
    model_fields = {m.get("name"): {f.get("name") for f in m.get("fields", [])} for m in models}
    
    # Check Foreign Keys reference valid entities
    for m in models:
        for f in m.get("fields", []):
            fk = f.get("foreign_key")
            if fk and isinstance(fk, dict):
                target_entity = fk.get("target_entity")
                if target_entity and target_entity not in model_names:
                    # Check case-insensitive
                    matches = [name for name in model_names if name.lower() == target_entity.lower()]
                    if not matches:
                        warnings.append(f"Foreign key in {m.get('name')}.{f.get('name')} references unknown entity '{target_entity}'")
                        
    # Check Service Contracts
    contracts = parsed.get("service_contracts", {}).get("service_contracts", [])
    for c in contracts:
        s_name = c.get("service_name")
        for method in c.get("methods", []):
            m_name = method.get("name")
            if not m_name:
                errors.append(f"Service {s_name} has a method without a name")

    # Check Persistence Ports reference extracted entities
    persistence = parsed.get("persistence_ports", {}).get("persistence_ports", {})
    for repository in persistence.get("repositories", []):
        entity = repository.get("entity")
        if entity and entity not in model_names:
            matches = [name for name in model_names if name.lower() == entity.lower()]
            if not matches:
                warnings.append(f"Repository {repository.get('interface_name')} references unknown entity '{entity}'")

        for method in repository.get("methods", []):
            if not method.get("name"):
                errors.append(f"Repository {repository.get('interface_name')} has a method without a name")

    for mapping in persistence.get("entity_mappings", []):
        entity = mapping.get("entity")
        if entity and entity not in model_names:
            matches = [name for name in model_names if name.lower() == entity.lower()]
            if not matches:
                warnings.append(f"Persistence mapping for unknown entity '{entity}'")
                
    return errors, warnings


def _build_service_summary(json_contracts_str):
    """Return a plain-text block listing every service_name and its methods.

    This is injected into Step G's prompt so that the model is constrained to
    use the *exact* service names that Step E already declared, eliminating the
    naming drift that causes nearly all unresolved_adapter_target warnings.

    Returns an empty string if Step E produced no parseable services (safe
    fallback: Step G then behaves exactly as before the fix).
    """
    try:
        contracts = json.loads(json_contracts_str).get("service_contracts", [])
    except (json.JSONDecodeError, AttributeError):
        contracts = []

    if not contracts:
        return ""

    lines = [
        "The following service contracts were declared in this session.",
        "For every adapter's target_service field use one of these EXACT service_name values "
        "(copy the string verbatim, including capitalisation and spaces):",
    ]
    for c in contracts:
        sname = c.get("service_name", "")
        if not sname:
            continue
        methods = [m.get("name", "") for m in c.get("methods", []) if m.get("name")]
        method_str = ", ".join(methods) if methods else "(no methods)"
        lines.append(f'  "{sname}": methods = {method_str}')
    lines.append("")   # blank line before the rest of the system message
    return "\n".join(lines) + "\n"


_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _norm_str(s):
    """Lowercase, strip non-alphanumeric — same normalisation as naming.py."""
    return _NON_ALNUM.sub("", s.lower())


def _best_service_match(raw, norm_to_canonical):
    """Return the best-matching canonical service name for *raw*, or None.

    Cascade:
      1. Exact match (fast path, already checked by caller).
      2. Normalised match (strips punctuation / casing differences).
      3. difflib close match at a generous 0.45 cutoff (handles partial
         token swaps typical of small quantised models).
      4. Longest common prefix >= 5 normalised chars (catches cases like
         'Inventory_correctly' → 'InventoryManagementSystem' where both
         share the 'inventory' prefix but difflib scores are borderline).
    """
    nr = _norm_str(raw)
    norm_names = list(norm_to_canonical)

    # 2. Normalised exact
    if nr in norm_to_canonical:
        return norm_to_canonical[nr], "normalized"

    # 3. difflib
    close = difflib.get_close_matches(nr, norm_names, n=1, cutoff=0.45)
    if close:
        return norm_to_canonical[close[0]], "difflib"

    # 4. Longest common prefix (>= 5 chars)
    best_len, best_name = 4, None   # 4 = minimum - 1, so >= 5 triggers
    for nn in norm_names:
        plen = 0
        for a, b in zip(nr, nn):
            if a == b:
                plen += 1
            else:
                break
        if plen > best_len:
            best_len, best_name = plen, norm_to_canonical[nn]
    if best_name:
        return best_name, f"prefix({best_len})"

    return None, None


def _normalise_adapter_targets(json_adapters_str, service_names):
    """Fix-1b: correct any target_service that does not match a known service.

    Applied immediately after Step G returns, before saving.  Pure Python,
    no LLM call.  Returns the (possibly corrected) JSON string.
    """
    if not service_names:
        return json_adapters_str

    try:
        doc = json.loads(json_adapters_str)
    except json.JSONDecodeError:
        return json_adapters_str   # malformed; leave it, checker will report

    norm_to_canonical = {_norm_str(n): n for n in service_names}
    adapters = doc.get("interaction_adapters", [])
    corrections = 0

    for adapter in adapters:
        raw = adapter.get("target_service", "")
        if not raw or raw in service_names:
            continue   # already correct
        corrected, method = _best_service_match(raw, norm_to_canonical)
        if corrected:
            print(
                f"   🔧 [Fix-1b] target_service '{raw}' → '{corrected}' ({method})",
                file=sys.stderr,
            )
            adapter["target_service"] = corrected
            corrections += 1
        else:
            print(
                f"   ⚠️  [Fix-1b] target_service '{raw}' unresolved — no close match found",
                file=sys.stderr,
            )

    if corrections:
        print(f"   📎 [Fix-1b] {corrections} adapter target(s) auto-corrected.", file=sys.stderr)

    return json.dumps(doc)


def run_extraction(llm, full_prompt, grammar_str, label):
    """Exécute une extraction en streaming avec nettoyage du cache KV et index corrigé."""
    print(f"\n🚀 [Query] Extracting {label}...", file=sys.stderr)
    print(f"--- START OF {label.upper()} STREAM ---")
    
    grammar = LlamaGrammar.from_string(grammar_str)
    llm.reset()
    
    start_time = time.time()
    response_stream = llm(
        prompt=full_prompt,
        max_tokens=4096,
        temperature=0.1,
        grammar=grammar,
        stream=True
    )

    raw_json = ""
    token_count = 0
    
    for chunk in response_stream:
        if "choices" in chunk and len(chunk["choices"]) > 0:
            token = chunk["choices"][0]["text"]  # ✅ Corrigé : accès explicite à l'index 0
            raw_json += token
            token_count += 1
            sys.stdout.write(token)
            sys.stdout.flush()
        
    end_time = time.time()
    duration = end_time - start_time
    speed = token_count / duration if duration > 0 else 0
    
    print(f"\n--- END OF {label.upper()} STREAM ---")
    print(f"📊 Stats {label} : {token_count} tokens generated in {duration:.2f}s ({speed:.1f} tok/s)", file=sys.stderr)
    
    return raw_json, token_count

def main():
    parser = argparse.ArgumentParser(description="Universal Software Architecture Extractor.")
    parser.add_argument("--model", type=str, required=True, help="Path to GGUF model")
    parser.add_argument("--output", type=str, help="Prefix for output files")
    args = parser.parse_args()

    user_prompt = sys.stdin.read().strip()
    if not user_prompt:
        print("Error: Input prompt is empty.", file=sys.stderr)
        sys.exit(1)

    print("[1/2] Initializing model on CPU (8k context, 8 threads)...", file=sys.stderr)
    llm = Llama(
        model_path=args.model,
        n_ctx=8192,
        n_threads=8,
        n_threads_batch=8,
        flash_attn=False,
        logits_all=True,
        verbose=False
    )

    system_base = "<|im_start|>system\nYou are an expert software engineer.<|im_end|>\n<|im_start|>user\n"
    prompt_tokens_count = len(llm.tokenize(bytes(system_base + user_prompt, 'utf-8')))
    print(f"📊 Input prompt size: ~{prompt_tokens_count} tokens.\n", file=sys.stderr)

    total_generated_tokens = 0
    results = {}

    # --- STEP A: INTENTIONS ---
    prompt_intentions = (
        "<|im_start|>system\nExtract core intentions (use cases/services). "
        "Do not list details. Output in English as JSON: {\"intentions\": []}.<|im_end|>\n"
        f"<|im_start|>user\n{user_prompt}<|im_end|>\n<|im_start|>assistant\n"
    )
    json_intentions, tok_a = run_extraction(llm, prompt_intentions, GRAMMAR_INTENTIONS, "intentions")
    total_generated_tokens += tok_a
    results["intentions"] = json_intentions

    # --- STEP B: DATA MODEL ---
    prompt_modeles = (
        "<|im_start|>system\nExtract data model. Use ONLY generic types: "
        "'int', 'string', 'boolean', 'decimal', 'datetime', 'date', 'text', 'float'. "
        "For each field, specify boolean 'primary_key', 'nullable', 'unique', and 'status' ('explicit'|'deduced'). "
        "For 'foreign_key', use null if not a foreign key, or an object: {\"target_entity\": \"...\", \"target_field\": \"...\", \"relationship\": \"many_to_one\"|\"one_to_one\"|\"one_to_many\"}. "
        "Output strictly in English as JSON.<|im_end|>\n"
        f"<|im_start|>user\n{user_prompt}<|im_end|>\n<|im_start|>assistant\n"
    )
    json_modeles, tok_b = run_extraction(llm, prompt_modeles, GRAMMAR_MODELES, "data_models")
    total_generated_tokens += tok_b
    results["data_models"] = json_modeles

    # --- STEP C: INVARIANTS ---
    prompt_invariants = (
        "<|im_start|>system\nIdentify the business and data invariants explicitly stated or directly implied by the requirements. "
        "Each invariant must be a single, unique, concrete rule (e.g. 'isbn must be unique', 'available_copies must be >= 0'). "
        "Do not repeat, paraphrase, or generalize the same rule. Do not invent rules not grounded in the requirements. "
        "Stop as soon as all distinct rules are listed. "
        "Output strictly in English as JSON: {\"invariants\": [\"...\", \"...\"]}.<|im_end|>\n"
        f"<|im_start|>user\n{user_prompt}<|im_end|>\n<|im_start|>assistant\n"
    )
    json_invariants, tok_c = run_extraction(llm, prompt_invariants, GRAMMAR_INVARIANTS, "invariants")
    total_generated_tokens += tok_c
    results["invariants"] = json_invariants

    # --- STEP D: COMPOSANTS ET ARCHITECTURE ---
    prompt_composants = (
        "<|im_start|>system\nClassify tech components. Fallbacks: 1. Facade type: cli, api, gui. "
        "If empty: facade=cli + tech=argparse. 2. If api requested but no tech named: tech=flask. "
        "3. If gui requested but no tech named: tech=pyimgui. 4. If persistence requested but no DB named: tech=sqlite. "
        "If none: required=false + tech=none. 5. external_access: list cloud services. "
        "6. crud_services: list the bare domain model entities (e.g. 'Book', 'Expense', never 'BookRepository' or service class names) "
        "with their CRUD operations (subset of [\"create\", \"read_one\", \"read_all\", \"update\", \"delete\"]). "
        "Output strictly in English as JSON.<|im_end|>\n"
        f"<|im_start|>user\n{user_prompt}<|im_end|>\n<|im_start|>assistant\n"
    )
    json_composants, tok_d = run_extraction(llm, prompt_composants, GRAMMAR_COMPOSANTS, "components")
    total_generated_tokens += tok_d
    results["components"] = json_composants

    # --- STEP E: SERVICE CONTRACTS ---
    prompt_contracts = (
        "<|im_start|>system\nExtract high-level business service method signatures with parameters and return types. "
        "Include domain services and repository custom aggregates (e.g. get_total_by_category_and_month). "
        "Output strictly in English as JSON: {\"service_contracts\": [{\"service_name\": \"...\", \"methods\": [{\"name\": \"...\", \"description\": \"...\", \"params\": [{\"name\": \"...\", \"type\": \"...\"}], \"return_type\": \"...\"}]}]}.<|im_end|>\n"
        f"<|im_start|>user\n{user_prompt}<|im_end|>\n<|im_start|>assistant\n"
    )
    json_contracts, tok_e = run_extraction(llm, prompt_contracts, GRAMMAR_CONTRACTS, "service_contracts")
    total_generated_tokens += tok_e
    results["service_contracts"] = json_contracts

    # Build a service-name anchor for Step G so both steps agree on naming.
    service_summary = _build_service_summary(json_contracts)
    if service_summary:
        print("\n📎 [Fix-1] Service summary injected into Step G prompt:", file=sys.stderr)
        for line in service_summary.splitlines():
            print(f"   {line}", file=sys.stderr)

    # --- STEP F: PATTERN CLASSIFICATION (Single-Token Logprobs) ---
    print("\n🚀 [Step F] Classifying operations into Canonical Kernel Patterns (Hierarchical Logprobs)...", file=sys.stderr)
    catalog = load_catalog()
    pattern_classifications = []
    
    # Classify Invariants
    try:
        parsed_invariants = json.loads(results.get("invariants", "{}")).get("invariants", [])
        for inv in parsed_invariants:
            cls_res = classify_requirement_2step(llm, inv, catalog)
            if cls_res["pattern_id"] != "CUSTOM_OR_STANDARD_CRUD":
                pattern_classifications.append({
                    "source": "invariant",
                    "text": inv,
                    "domain": cls_res["domain"],
                    "pattern_id": cls_res["pattern_id"],
                    "confidence": round(cls_res["confidence"], 4)
                })
                total_generated_tokens += 2
    except Exception as e:
        print(f"⚠️ Error classifying invariants: {e}", file=sys.stderr)
        
    # Classify Service Contract Methods
    try:
        parsed_contracts = json.loads(results.get("service_contracts", "{}")).get("service_contracts", [])
        for contract in parsed_contracts:
            s_name = contract.get("service_name", "")
            for method in contract.get("methods", []):
                m_desc = f"{method.get('name', '')}: {method.get('description', '')}"
                cls_res = classify_requirement_2step(llm, m_desc, catalog)
                if cls_res["pattern_id"] != "CUSTOM_OR_STANDARD_CRUD":
                    pattern_classifications.append({
                        "source": f"contract:{s_name}.{method.get('name')}",
                        "text": m_desc,
                        "domain": cls_res["domain"],
                        "pattern_id": cls_res["pattern_id"],
                        "confidence": round(cls_res["confidence"], 4)
                    })
                    total_generated_tokens += 2
    except Exception as e:
        print(f"⚠️ Error classifying service contracts: {e}", file=sys.stderr)

    results["pattern_matches"] = json.dumps({"pattern_matches": pattern_classifications}, indent=2)

    # --- STEP G: INTERACTION ADAPTERS (Abstract Input -> Domain Param Translation) ---
    prompt_adapters = (
        f"<|im_start|>system\n{service_summary}"
        "Extract abstract interaction adapters mapping external input actions to domain service method parameters. "
        "Transforms allowed: 'DIRECT', 'LOOKUP_ID', 'DECIMAL_TO_CENTS', 'ISO_DATE', 'CSV_LIST', 'ENUM_LOOKUP'. "
        "Set 'lookup_entity' to the entity name if transform is 'LOOKUP_ID', else null. "
        "Output strictly in English as JSON: {\"interaction_adapters\": [{\"action_name\": \"...\", \"target_service\": \"...\", \"target_method\": \"...\", \"input_fields\": [{\"field_name\": \"...\", \"target_param\": \"...\", \"transform\": \"...\", \"lookup_entity\": null|\"...\", \"required\": true|false}]}]}.<|im_end|>\n"
        f"<|im_start|>user\n{user_prompt}<|im_end|>\n<|im_start|>assistant\n"
    )
    json_adapters, tok_g = run_extraction(llm, prompt_adapters, GRAMMAR_ADAPTERS, "interaction_adapters")
    total_generated_tokens += tok_g

    # Fix-1b: deterministic post-generation normalisation of target_service values.
    try:
        known_services = [
            c.get("service_name") for c in
            json.loads(results.get("service_contracts", "{}")).get("service_contracts", [])
            if c.get("service_name")
        ]
    except (json.JSONDecodeError, AttributeError):
        known_services = []
    json_adapters = _normalise_adapter_targets(json_adapters, known_services)

    results["interaction_adapters"] = json_adapters

    # --- STEP H: PERSISTENCE PORTS (Domain Repository Contracts -> Database Adapters) ---
    prompt_persistence_ports = (
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
    json_persistence_ports, tok_h = run_extraction(
        llm, prompt_persistence_ports, GRAMMAR_PERSISTENCE_PORTS, "persistence_ports"
    )
    total_generated_tokens += tok_h
    results["persistence_ports"] = json_persistence_ports

    # Verification
    errors, warnings = verify_extractions(results)
    if warnings:
        print("\n⚠️ VERIFICATION WARNINGS:", file=sys.stderr)
        for w in warnings:
            print(f"  - {w}", file=sys.stderr)
    if errors:
        print("\n❌ VERIFICATION ERRORS:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
    else:
        print("\n✅ All extraction contracts verified successfully!", file=sys.stderr)

    # 3. Sauvegarde automatique
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

    # Bilan Global
    print("\n==========================================", file=sys.stderr)
    print(f"🏆 TOTAL TOKENS SUMMARY:", file=sys.stderr)
    print(f" -> Prompt Tokens: {prompt_tokens_count}", file=sys.stderr)
    print(f" -> Generated Tokens (Total): {total_generated_tokens}", file=sys.stderr)
    print("==========================================", file=sys.stderr)

if __name__ == "__main__":
    main()

