import json
import re
from pathlib import Path

KERNEL_DIR = Path(__file__).parent

def load_patterns():
    repo_file = KERNEL_DIR / "repo_patterns" / "patterns.json"
    service_file = KERNEL_DIR / "service_patterns" / "patterns.json"
    
    with open(repo_file, "r", encoding="utf-8") as f:
        repo_patterns = json.load(f)
    with open(service_file, "r", encoding="utf-8") as f:
        service_patterns = json.load(f)
        
    return repo_patterns, service_patterns

def match_text_to_patterns(text: str, patterns: list) -> list:
    """Matches freeform intentions or invariant text against catalog patterns via keyword overlap."""
    matched = []
    text_lower = text.lower()
    
    for pat in patterns:
        score = 0
        matched_kws = []
        for kw in pat.get("match_keywords", []):
            if re.search(r'\b' + re.escape(kw.lower()) + r'\b', text_lower):
                score += 1
                matched_kws.append(kw)
        if score > 0:
            matched.append({
                "pattern_id": pat["pattern_id"],
                "score": score,
                "matched_keywords": matched_kws,
                "pattern": pat
            })
            
    # Sort by relevance
    matched.sort(key=lambda x: x["score"], reverse=True)
    return matched

def match_architecture(prefix: str):
    """Matches all extracted architecture files for a given prefix against kernel patterns."""
    repo_patterns, service_patterns = load_patterns()
    
    intentions_file = Path(f"{prefix}_intentions.json")
    invariants_file = Path(f"{prefix}_invariants.json")
    contracts_file = Path(f"{prefix}_service_contracts.json")
    
    intentions = []
    invariants = []
    contracts = []
    
    if intentions_file.exists():
        with open(intentions_file, "r", encoding="utf-8") as f:
            intentions = json.load(f).get("intentions", [])
    if invariants_file.exists():
        with open(invariants_file, "r", encoding="utf-8") as f:
            invariants = json.load(f).get("invariants", [])
    if contracts_file.exists():
        with open(contracts_file, "r", encoding="utf-8") as f:
            contracts = json.load(f).get("service_contracts", [])
        
    results = {
        "matched_repo_operations": [],
        "matched_service_guards": []
    }
    
    # Match Intentions -> Repository Patterns
    for intent in intentions:
        repo_matches = match_text_to_patterns(intent, repo_patterns)
        if repo_matches:
            results["matched_repo_operations"].append({
                "source": "intention",
                "text": intent,
                "matches": [m["pattern_id"] for m in repo_matches]
            })
            
    # Match Invariants -> Service Patterns
    for inv in invariants:
        svc_matches = match_text_to_patterns(inv, service_patterns)
        if svc_matches:
            results["matched_service_guards"].append({
                "source": "invariant",
                "text": inv,
                "matches": [m["pattern_id"] for m in svc_matches]
            })

    # Match Service Contracts (Methods & Descriptions)
    for contract in contracts:
        s_name = contract.get("service_name", "")
        for method in contract.get("methods", []):
            m_text = f"{method.get('name', '')} {method.get('description', '')}"
            
            repo_matches = match_text_to_patterns(m_text, repo_patterns)
            if repo_matches:
                results["matched_repo_operations"].append({
                    "source": f"contract:{s_name}.{method.get('name')}",
                    "text": m_text,
                    "matches": [m["pattern_id"] for m in repo_matches]
                })
                
            svc_matches = match_text_to_patterns(m_text, service_patterns)
            if svc_matches:
                results["matched_service_guards"].append({
                    "source": f"contract:{s_name}.{method.get('name')}",
                    "text": m_text,
                    "matches": [m["pattern_id"] for m in svc_matches]
                })
            
    return results

if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 2:
        prefix = sys.argv[1]
        res = match_architecture(prefix)
        print(json.dumps(res, indent=2))
    else:
        print("Usage: python3 matcher.py <prefix_e.g._out_expenses>")
