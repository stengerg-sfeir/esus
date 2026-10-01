import math

from llama_cpp import Llama

# The pattern vocabulary lives in one dependency-free module so the classifier
# that emits these ids and the checker that validates them cannot disagree.
from kernel.pattern_catalog import (
    DOMAINS,
    NO_DOMAIN_IDS,
    NO_PATTERN_IN_DOMAIN_OPTION,
    load_catalog,
)

def softmax_classify(llm, target_text: str, candidates: list, id_key: str = "id", desc_key: str = "description") -> tuple[str, float, dict]:
    """
    Executes a single forward pass with max_tokens=1 and computes softmax over candidate letters.

    The option list is placed before the requirement and `reset()` is deliberately
    not called. llama.cpp reuses the longest common KV prefix of consecutive
    prompts; with the options first, the only differing part of the prompt is the
    requirement at the end, so a run costs one full prefill instead of one per
    item (measured: 1.57s -> 0.53s per call). Calling reset() sets n_tokens to 0
    and destroys exactly that cache.
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
Reply strictly with only the single uppercase letter, e.g. A.

Options:
{options_text}<|im_end|>
<|im_start|>user
Requirement: "{target_text}"<|im_end|>
<|im_start|>assistant
"""

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
    Step 1: Classify Domain (REPO_QUERY, SERVICE_GUARD, STANDARD_CRUD, NO_MATCH) -> 1 token
    Step 2: Classify exact Pattern ID within the selected domain -> 1 token

    STANDARD_CRUD and NO_MATCH are answers rather than domains, so they end the
    classification and become the pattern id itself. STANDARD_CRUD is the correct
    answer for ordinary create/read/update/delete and is not a gap; NO_MATCH says
    no domain fits and is one. Both are returned so the caller can count them,
    which is what turns the gap into a report instead of a discarded answer.
    """
    # Step 1: Domain Classification
    domain_id, domain_conf, domain_probs = softmax_classify(
        llm, target_text, DOMAINS, id_key="id", desc_key="description"
    )
    
    if domain_id in NO_DOMAIN_IDS or not catalog.get(domain_id):
        return {
            "target_text": target_text,
            "domain": domain_id,
            "pattern_id": domain_id,
            "confidence": domain_conf,
            "step1_probabilities": domain_probs,
            "step2_probabilities": {}
        }
        
    # Step 2: Specific Pattern Classification
    patterns_in_domain = catalog[domain_id] + [NO_PATTERN_IN_DOMAIN_OPTION]
    
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
