import sys
import time
from llama_cpp import Llama
from kernel.classifier.hierarchical_classifier import load_catalog, classify_requirement_2step

def main():
    if len(sys.argv) < 2:
        model_path = "../models/Ministral-3-3B-Instruct-2512-Q4_K_M.gguf"
    else:
        model_path = sys.argv[1]

    print(f"Loading model from {model_path}...", file=sys.stderr)
    llm = Llama(
        model_path=model_path,
        n_ctx=4096,
        n_threads=8,
        logits_all=True,
        verbose=False
    )
    
    catalog = load_catalog()
    
    test_cases = [
        # English
        "Calculate the total spent in a specific category for the current month.",
        "Refuse to add an expense if it causes the category budget to be exceeded.",
        "Ensure selling price is strictly greater than cost price.",
        "Check available copies before loaning a book and decrement count.",
        "Retrieve a list of overdue loans where due date is before today.",
        # French (Multilingual test)
        "Calculer le total des dépenses par catégorie pour le mois en cours.",
        "Vérifier que le prix de vente d'un vin est strictement supérieur à son prix d'achat.",
        "Empêcher l'ajout d'une dépense si le plafond du budget mensuel est dépassé.",
        "Lister les produits dont le stock est inférieur au seuil de réapprovisionnement."
    ]
    
    print("\n================ RUNNING HIERARCHICAL LOGPROBS CLASSIFICATION ================\n")
    for tc in test_cases:
        t0 = time.time()
        result = classify_requirement_2step(llm, tc, catalog)
        dt = time.time() - t0
        
        print(f"📝 Text: \"{tc}\"")
        print(f"   -> Domain:   {result['domain']} (p={result['step1_probabilities'].get(result['domain'], 0.0):.2f})")
        print(f"   -> Pattern:  🎯 {result['pattern_id']} (Confidence: {result['confidence']*100:.1f}%)")
        print(f"   ⏱️ Latency:   {dt*1000:.1f}ms (2 tokens total)")
        print("-" * 75)

if __name__ == "__main__":
    main()
