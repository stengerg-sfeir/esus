import argparse
import sys
import json
from llama_cpp import Llama, LlamaGrammar

# 1. Définition de la grammaire GBNF stricte pour forcer la structure JSON
GBNF_GRAMMAR = r"""
root ::= "{" ws "\"intentions\"" ws ":" ws string-list ws "," ws "\"modeles_de_donnees\"" ws ":" ws entite-list ws "," ws "\"invariants\"" ws ":" ws string-list ws "}" ws

# Listes et tableaux
string-list ::= "[" ws (string (ws "," ws string)*)? ws "]"
entite-list ::= "[" ws (entite (ws "," ws entite)*)? ws "]"

# Définition d'une entité du modèle de données
entite ::= "{" ws "\"nom\"" ws ":" ws string ws "," ws "\"champs\"" ws ":" ws champ-list ws "}"
champ-list ::= "[" ws (champ (ws "," ws champ)*)? ws "]"
champ ::= "{" ws "\"nom\"" ws ":" ws string ws "," ws "\"type\"" ws ":" ws string ws "," ws "\"statut\"" ws ":" ws ("\"explicite\"" | "\"deduit\"") ws "}"

# Éléments de base (Primitifs JSON)
string ::= "\"" ([^"\\] | "\\" ["\\/bfnrt] | "\\u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F])* "\""
ws ::= [ \t\n\r]*
"""

def main():
    parser = argparse.ArgumentParser(description="Extracteur d'architecture logicielle via GBNF en streaming.")
    parser.add_argument("--model", type=str, required=True, help="Chemin vers le fichier GGUF")
    args = parser.parse_args()

    # Lecture du prompt depuis l'entrée standard (fichiers redirigés)
    print("👉 Analyse du fichier d'entrée...", file=sys.stderr)
    user_prompt = sys.stdin.read().strip()
    
    if not user_prompt:
        print("Erreur : Le prompt d'entrée est vide.", file=sys.stderr)
        sys.exit(1)

    print("\n[1/3] Chargement du modèle GGUF sur le CPU...", file=sys.stderr)
    # Configuration CPU optimisée avec contexte à 8k et 16 threads
    llm = Llama(
        model_path=args.model,
        n_ctx=8192,            # Contexte fixé à 8192
        n_threads=16,          # Utilisation des 16 cœurs pour la génération
        n_threads_batch=16,    # Utilisation des 16 cœurs pour le prompt initial
        verbose=False
    )

    print("[2/3] Compilation de la grammaire GBNF...", file=sys.stderr)
    grammar = LlamaGrammar.from_string(GBNF_GRAMMAR)

    # Format de prompt ChatML standard pour Ministral / Qwen
    full_prompt = (
        "<|im_start|>system\n"
        "Tu es un ingénieur logiciel expert. Analyse le prompt utilisateur pour extraire de façon brute : \n"
        "1. Les intentions principales.\n"
        "2. Le modèle de données complet (avec champs, types, et s'ils sont 'explicites' ou 'deduits').\n"
        "3. Les invariants (règles métiers strictes).\n"
        "Tu dois obligatoirement respecter la grammaire JSON fournie.<|im_end|>\n"
        f"<|im_start|>user\n{user_prompt}<|im_end|>\n"
        "<|im_start|>assistant\n"
    )

    print("[3/3] Extraction en cours (Génération en streaming) :", file=sys.stderr)
    print("\n=== DÉBUT DU FLUX JSON ===\n")

    # Activation du streaming de jetons (tokens)
    response_stream = llm(
        prompt=full_prompt,
        max_tokens=2048,
        temperature=0.1,
        grammar=grammar,
        stream=True
    )

    raw_json = ""
    # Lecture du flux en temps réel
    for chunk in response_stream:
        token = chunk["choices"][0]["text"]
        raw_json += token
        
        # Écriture immédiate du token dans le terminal
        sys.stdout.write(token)
        sys.stdout.flush()

    print("\n\n=== FIN DU FLUX JSON ===")

    # Validation finale de la syntaxe par sécurité
    try:
        json.loads(raw_json)
        print("\n✅ Extraction terminée avec succès. Structure JSON 100% valide.", file=sys.stderr)
    except json.JSONDecodeError:
        print("\n⚠️ Attention : Le JSON généré semble incomplet ou comporte une erreur de syntaxe.", file=sys.stderr)

if __name__ == "__main__":
    main()

