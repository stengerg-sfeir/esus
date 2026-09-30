import json
import math
import sys
from pathlib import Path
from llama_cpp import Llama

KERNEL_DIR = Path(__file__).parent.parent

# Step 1 Categories (High-level Domain Groups)
DOMAINS = [
    {
        "id": "REPO_QUERY",
        "name": "Repository Query or Aggregate",
        "description": "Database query, filtered list, SQL aggregation, sum, count, pagination, or uniqueness check."
    },
    {
        "id": "SERVICE_GUARD",
        "name": "Service Invariant or Business Rule Guard",
        "description": "Validation check, budget overflow, stock sufficiency, capacity quota, or pricing rule."
    },
    {
        "id": "CUSTOM_OR_NONE",
        "name": "Standard CRUD or Custom Domain Logic",
        "description": "Basic CRUD (create/read/update/delete by id) or non-standard custom business logic."
    }
]

def load_catalog():
    repo_file = KERNEL_DIR / "repo_patterns" / "patterns.json"
    service_file = KERNEL_DIR / "service_patterns" / "patterns.json"
    
    with open(repo_file, "r", encoding="utf-8") as f:
        repo_patterns = json.load(f)
    with open(service_file, "r", encoding="utf-8") as f:
        service_patterns = json.load(f)
        
    return {
        "REPO_QUERY": repo_patterns,
        "SERVICE_GUARD": service_patterns,
        "CUSTOM_OR_NONE": []
    }

def softmax_classify(llm, target_text: str, candidates: list, id_key: str = "id", desc_key: str = "description") -> tuple[str, float, dict]:
    """
    Executes a single forward pass with max_tokens=1 and computes softmax over candidate letters.
    """
    options_text = ""
    letter_to_id = {}
    
    for i, item in enumerate(candidates):
        letter = chr(ord('A') + i)
        letter_to_id[letter] = item[id_key]
        name = item.get("name") or item[id_key]
        desc = item.get(desc_key, "")
        options_text += f"[{letter}] {name}: {desc}\n"
        
    prompt = f"""<|im_start|>system
You are a software architecture classifier. Select the single best matching option letter for the given requirement.
Reply strictly with only the single uppercase letter, e.g. A.<|im_end|>
<|im_start|>user
Requirement: "{target_text}"

Options:
{options_text}
<|im_end|>
<|im_start|>assistant
"""

    llm.reset()
    response = llm(
        prompt=prompt,
        max_tokens=1,
        temperature=0.0,
        logprobs=15
    )
    
    choice = response["choices"][0]
    top_logprobs = choice.get("logprobs", {}).get("top_logprobs", [{}])[0]
    
    # Calculate softmax across candidate letters (supporting 'A', ' A', '[A', etc.)
    scores = {}
    for letter, item_id in letter_to_id.items():
        # Look for the letter token or space-prefixed letter token
        logprob = -100.0
        for token_str, lp in top_logprobs.items():
            clean_token = token_str.strip().strip("[]").upper()
            if clean_token == letter:
                if lp > logprob:
                    logprob = lp
        scores[letter] = math.exp(logprob) if logprob > -90.0 else 1e-6
        
    total_exp = sum(scores.values()) or 1.0
    probabilities = {letter_to_id[letter]: prob / total_exp for letter, prob in scores.items()}
    
    best_id = max(probabilities, key=probabilities.get)
    confidence = probabilities[best_id]
    
    return best_id, confidence, probabilities

def classify_requirement_2step(llm, target_text: str, catalog: dict) -> dict:
    """
    Hierarchical 2-Step Logprobs Classifier:
    Step 1: Classify Domain (REPO_QUERY vs SERVICE_GUARD vs CUSTOM_OR_NONE) -> 1 token
    Step 2: Classify exact Pattern ID within the selected domain -> 1 token
    """
    # Step 1: Domain Classification
    domain_id, domain_conf, domain_probs = softmax_classify(
        llm, target_text, DOMAINS, id_key="id", desc_key="description"
    )
    
    if domain_id == "CUSTOM_OR_NONE" or not catalog.get(domain_id):
        return {
            "target_text": target_text,
            "domain": domain_id,
            "pattern_id": "CUSTOM_OR_STANDARD_CRUD",
            "confidence": domain_conf,
            "step1_probabilities": domain_probs,
            "step2_probabilities": {}
        }
        
    # Step 2: Specific Pattern Classification
    patterns_in_domain = catalog[domain_id] + [{
        "pattern_id": "CUSTOM_DOMAIN_LOGIC",
        "name": "Custom / Other Logic",
        "description": "Does not match any of the standard patterns in this group."
    }]
    
    pattern_id, pattern_conf, pattern_probs = softmax_classify(
        llm, target_text, patterns_in_domain, id_key="pattern_id", desc_key="description"
    )
    
    total_confidence = domain_conf * pattern_conf
    
    return {
        "target_text": target_text,
        "domain": domain_id,
        "pattern_id": pattern_id,
        "confidence": total_confidence,
        "step1_probabilities": domain_probs,
        "step2_probabilities": pattern_probs
    }
