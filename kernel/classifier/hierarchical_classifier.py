import math

import numpy as np

# The pattern vocabulary lives in one dependency-free module so the classifier
# that emits these ids and the checker that validates them cannot disagree.
from kernel.pattern_catalog import (
    DOMAINS,
    NO_DOMAIN_IDS,
    NO_PATTERN_IN_DOMAIN_OPTION,
    load_catalog,
)

# The classifier only needs the distribution for the token after the prompt.
# llama-cpp-python's high-level `logprobs` API requires `logits_all=True` at
# context construction, which makes the classifier a second model: every prompt
# token's logits are materialised, and the context's score buffer is sized
# `n_ctx × n_vocab`. Reading the last row directly works with the extractor's
# ordinary `logits_all=False` context, so step F can use the model already
# loaded for steps A–E.
TOP_LOGPROBS = 15


def _longest_token_prefix(cached, tokens) -> int:
    """Length of the longest common prefix of two token sequences."""
    prefix = 0
    for cached_token, token in zip(cached, tokens):
        if cached_token != token:
            break
        prefix += 1
    return prefix


def _next_token_logprobs(llm, prompt: str, top_n: int = TOP_LOGPROBS) -> dict:
    """Top next-token logprobs without requiring a `logits_all=True` context.

    The high-level path (`llm(..., logprobs=N)`) asserts that the context was
    built with `logits_all=True`. It is not the only way to read a next-token
    distribution: after evaluating the prompt, llama.cpp keeps the logits for
    the final token even when `logits_all=False`. `llama_get_logits_ith(-1)`
    returns exactly those logits, which is all a one-token classifier needs.

    KV caching is preserved manually. The options prefix is shared by most
    calls, so the common case is to evaluate only the differing requirement
    suffix; a full reset would throw away that prefix and make the classifier
    much slower.
    """
    tokens = llm.tokenize(prompt.encode("utf-8"), add_bos=True, special=True)

    prefix = _longest_token_prefix(llm.input_ids[: llm.n_tokens], tokens)
    if prefix < llm.n_tokens:
        # Drop the old suffix, but keep the shared prefix in the KV cache.
        llm._ctx.kv_cache_seq_rm(-1, prefix, -1)
        llm.n_tokens = prefix

    if prefix == len(tokens):
        if llm.n_tokens > len(tokens):
            # The context ended in generated tokens. Re-evaluate the final
            # prompt token so the logits belong to the prompt, not to the
            # continuation that happened to follow it.
            llm._ctx.kv_cache_seq_rm(-1, len(tokens) - 1, -1)
            llm.n_tokens = len(tokens) - 1
            llm.eval(tokens[-1:])
    elif tokens:
        llm.eval(tokens[prefix:])

    n_vocab = llm.n_vocab()
    logits = np.ctypeslib.as_array(
        llm._ctx.get_logits_ith(-1), shape=(n_vocab,)
    ).astype(np.float64, copy=True)
    logits -= logits.max()
    logprobs = logits - math.log(float(np.exp(logits).sum()))

    count = min(top_n, logprobs.size)
    ids = np.argpartition(logprobs, -count)[-count:]
    ids = ids[np.argsort(logprobs[ids])[::-1]]

    return {
        llm.detokenize([int(token)]).decode("utf-8", errors="replace"): float(logprobs[token])
        for token in ids
    }


def softmax_classify(llm, target_text: str, candidates: list, id_key: str = "id", desc_key: str = "description") -> tuple[str, float, dict]:
    """
    Executes a single forward pass and computes softmax over candidate letters.

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

    top_logprobs = _next_token_logprobs(llm, prompt)
    
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
