# Audit ESUS — registre consolidé des findings

**Base examinée :** archive `esus_review.zip` fournie dans la conversation  
**Nature :** audit statique du code et reproductions ciblées de fonctions de l’archive  
**Périmètre prioritaire :** faux positifs, réparations susceptibles de masquer une mauvaise compréhension, et erreurs métier possibles malgré les contrôles  
**État :** findings consolidés des passes déjà réalisées. L’examen approfondi de `review_contracts.py`, `review_slots.py`, `probe_readiness.py`, `kernel/tie_rules.py` et de l’ensemble des contrôles de cohérence reste à faire ; aucune conclusion n’est attribuée à ces modules dans ce document sans vérification.

## Comment lire ce registre

- **Reproduit** : un appel direct au code de l’archive a donné le comportement décrit.
- **Risque statique** : le chemin de code paraît permettre le comportement, mais le cas n’a pas été reproduit de bout en bout.
- **Gravité** : estimation de l’impact potentiel sur la justesse du logiciel généré, pas une mesure de fréquence.
- Les numéros de lignes se rapportent aux fichiers de l’archive tels qu’examinés. Ils peuvent varier si le dépôt a changé depuis la création du ZIP.

---

## Synthèse exécutive

Les risques les plus sérieux ne viennent pas seulement du LLM qui écrit du code. Ils viennent aussi de mécanismes déterministes qui peuvent **interpréter trop largement un nom ou une phrase**, puis produire une implémentation cohérente avec cette interprétation erronée. Les contrôles peuvent alors confirmer la cohérence interne d’une mauvaise compréhension.

Priorités proposées :

1. **P0/P1 — Faux positifs des contrôles de contrats** : une valeur ou un champ simplement présent dans le corps peut être pris pour une preuve d’effet ou de lecture.
2. **P1 — Classifications mécaniques par sous-chaînes** : un nom contenant `all` ou `list` peut déclencher une lecture globale sans que ce soit l’intention.
3. **P1 — Invariants mal interprétés** : la négation d’une règle numérique ou d’une comparaison peut être perdue, inversant la règle métier.
4. **P1 — Réparation qui supprime une garde métier** : l’absence de contrat déclaré peut conduire à retirer une vérification au lieu de signaler l’incertitude.
5. **P1 — Modèle de domaine inféré automatiquement** : une réparation peut transformer une extraction vide en entité persistée et CRUD standard, sans confirmation explicite.
6. **P1/P2 — Paramètres rapprochés par inclusion** : un paramètre peut être associé au mauvais champ.
7. **P1/P2 — Formules métier déduites des noms** : une formule plausible peut être générée sans preuve qu’elle représente la règle réelle.
8. **P2 — Juge LLM non indépendant** : le même modèle peut écrire le code puis évaluer sa conformité.

---

# Findings détaillés

## F-01 — Le contrôle d’une valeur contractuelle cherche la valeur dans tout le corps

**Gravité : P1 — faux positif de validation**  
**Statut : reproduit**

**Emplacement :** `generator.py`, `_contract_complaints()`, autour des lignes 10339–10351.

Pour un effet de type `op == "set"`, le contrôle vérifie que la valeur attendue apparaît dans le texte du corps (`value in text`) ou parmi certaines constantes AST. Il ne prouve donc pas que cette valeur soit celle effectivement affectée à la cible contractuelle.

Exemple minimal du problème :

```python
order.status = "pending"
self.log("confirmed")
```

Pour un contrat exigeant `order.status = "confirmed"`, le mot `confirmed` présent dans le journal peut satisfaire le test textuel, alors que l’état enregistré reste `pending`.

**Reproduction effectuée :** appel direct à `_contract_complaints()` avec un corps de cette forme ; aucune plainte n’a été retournée.

**Pourquoi c’est important :** le contrôle donne l’apparence d’une vérification AST, mais une partie de la preuve repose sur une recherche de sous-chaîne dans le corps complet. Un faux positif peut donc laisser passer une mauvaise valeur métier.

**Correction de conception recommandée :** relier la preuve à l’affectation de la cible contractuelle : identifier le nœud AST d’affectation, sa cible, son RHS et comparer la valeur ou l’expression sur ce RHS uniquement. En cas d’expression dynamique non démontrable, conserver un statut `unknown`/à revue plutôt que valider.

---

## F-02 — Le contrôle de lecture peut confondre mention d’un champ et lecture effective

**Gravité : P1 — faux positif de validation**  
**Statut : reproduit**

**Emplacement :** `generator.py`, `_contract_complaints()`, autour des lignes 10386 et suivantes (contrôle des lectures contractuelles).

Le contrôle peut s’appuyer sur la présence de noms d’entités/champs dans le corps, au lieu de démontrer que le champ est effectivement lu depuis l’objet ou le résultat de repository attendu.

Exemple :

```python
author = self._repos["AuthorRepository"].read_one(1)
print("name")
```

La chaîne `"name"` apparaît, mais `Author.name` n’est pas lu.

**Reproduction effectuée :** appel direct au contrôle avec ce corps ; la lecture contractuelle a pu être considérée comme satisfaite.

**Pourquoi c’est important :** une simple mention dans un message, un log, un commentaire ou une constante peut être prise pour une lecture métier. Le contrôle ne garantit alors pas que le résultat utilise les données exigées.

**Correction recommandée :** vérifier une chaîne de données AST : résultat de lecture → variable/objet → accès à l’attribut demandé → usage pertinent. Pour les cas que l’analyse statique ne peut pas établir, ne pas convertir l’absence de preuve en succès.

---

## F-03 — Les vérifications de `raise` ne démontrent pas toujours la bonne condition de déclenchement

**Gravité : P1 — risque de comportement métier inversé**  
**Statut : risque statique**

**Emplacement :** `generator.py`, `_raise_when_complaints()` (à partir de la ligne 10171), et les helpers associés de vérification des gardes.

Le code cherche à vérifier la polarité de `raise_when` (lever lorsque la condition est vraie ou fausse). La détection des `raise` paraît dépendre de formes de contrôle particulières et de leur position dans les branches `if`/`else`. Un `raise` inconditionnel ou placé dans une structure non reconnue peut ne pas être relié correctement à la précondition attendue.

Cas à tester explicitement :

```python
def borrow_book(self, book_id):
    raise errors.BookUnavailableError()
```

Une méthode qui lève toujours l’erreur ne respecte pas une règle où l’erreur ne doit être levée que si le livre est indisponible. Le risque est que la présence du bon nom d’erreur soit prise pour une preuve suffisante.

**Reproduction de bout en bout :** non établie dans cette passe.

**Correction recommandée :** analyser le flot de contrôle et la condition dominante de chaque `raise`. Si l’analyse ne peut pas prouver que le `raise` est conditionné par le prédicat contractuel, signaler `unknown` ou échec de preuve.

---

## F-04 — `repair_invented_state_guards` peut supprimer une garde lorsque le contrat est absent

**Gravité : P1 — réparation destructive de logique métier**  
**Statut : reproduit**

**Emplacement :** `generator.py`, `repair_invented_state_guards()`, lignes 10922–10967, particulièrement 10930–10940 et 10950–10962.

La fonction retire une garde de statut/état si la méthode n’est pas présente dans l’ensemble des contrats déclarant une précondition de statut ou d’état. Le cas où aucun contrat n’est disponible aboutit donc à un ensemble `declared` vide et à la suppression de la garde correspondante.

Exemple :

```python
if order.status != "pending":
    raise errors.InvalidOrderStatusError()
```

Avec `ctx={"contracts": []}`, la garde peut être supprimée.

**Reproduction effectuée :** reproduction directe avec une garde de ce type et un contexte sans contrat.

**Pourquoi c’est important :** « le contrat ne déclare pas cette garde » ne signifie pas « cette garde est fausse ». Cela peut signifier que l’extraction du contrat est incomplète. La réparation transforme une incertitude documentaire en suppression de protection métier.

**Correction recommandée :** distinguer explicitement :
- contrat présent et préconditions examinées ;
- contrat présent mais préconditions inconnues/incomplètes ;
- contrat absent.

Ne supprimer une garde que si une revue humaine confirme qu’elle est indue. En l’absence de contrat, conserver la garde ou bloquer la validation en demandant une clarification.

---

## F-05 — `repair_empty_domain` peut créer un modèle persistant à partir de prose

**Gravité : P1 — risque d’invention d’architecture**  
**Statut : comportement confirmé par lecture du code ; impact dépendant des entrées**

**Emplacement :** `kernel/extraction/repairs.py`, `repair_empty_domain()`, lignes 1199–1239 ; propagation vers les composants autour de 1242 et suivantes.

Lorsque l’extraction ne retourne aucun modèle, la réparation cherche un nom de domaine dans le texte et crée une entité minimale comprenant notamment :
- un identifiant entier ;
- un champ `status` ;
- éventuellement `created_at` si certains termes apparaissent.

Le modèle est marqué `status: "inferred from prose"`, ce qui conserve une trace d’inférence. Toutefois, la présence de cette marque ne garantit pas que l’utilisateur ait confirmé le choix d’une entité persistée, son identifiant ou son état.

**Risque :** une extraction manquée peut être convertie en modèle, puis en architecture CRUD/persistance standard. Le pipeline peut ainsi avancer avec une hypothèse structurelle non validée.

**Correction recommandée :** traiter cette sortie comme un candidat bloquant ou explicitement provisoire. Exiger confirmation des éléments qui changent l’architecture (entité persistée, champs, cycle de vie) avant de générer les couches aval.

---

## F-06 — `repair_capability_adapters` peut compléter service et interface à partir d’un adaptateur reconnu

**Gravité : P2 — risque de surinterprétation d’une capacité**  
**Statut : risque statique**

**Emplacement :** `kernel/extraction/repairs.py`, `repair_capability_adapters()`, lignes 2295–2428.

La fonction reconnaît des verbes de capacité dans les noms d’actions d’adaptateur et ajoute une méthode au service cible. Pour une demande d’import détectée dans la prose, elle peut également ajouter un sous-ordre CLI, un adaptateur et une méthode de service (notamment autour des lignes 2361–2422).

Le code s’appuie sur les informations déjà présentes dans l’adaptateur, le nom de service, les modèles et des marqueurs textuels (`import`, `json`, `csv`). Cela peut être utile pour réparer une extraction partielle, mais ne prouve pas à lui seul que tous les détails de la capacité ont été compris : format, sémantique de fusion, doublons, validation, erreurs partielles, transactionnalité, etc.

**Correction recommandée :** la réparation peut proposer une capacité candidate, mais les choix métier non déductibles (comportement en cas de doublon, stratégie d’upsert, atomicité, format exact) doivent rester explicitement non résolus jusqu’à confirmation.

---

## F-07 — Une erreur de champ initiale peut être propagée de façon cohérente dans plusieurs couches

**Gravité : P1 — propagation systémique d’une hypothèse erronée**  
**Statut : risque de conception**

**Emplacements :** réparations de champs de création dans `kernel/extraction/repairs.py`, notamment les familles `repair_required_create_fields()` et `repair_create_adapter_fields()` (rechercher ces noms dans le fichier).

Ces réparations peuvent propager un champ considéré requis depuis le modèle vers les contrats, services, repositories, adaptateurs ou surfaces CLI.

La cohérence obtenue entre les couches n’est pas une preuve indépendante que le champ initial était correct. Si le modèle a été mal extrait, la réparation peut rendre l’erreur plus systématique et plus difficile à détecter.

**Correction recommandée :** conserver l’origine et le statut de confiance de chaque champ. Une propagation automatique ne devrait pas promouvoir un champ inféré en champ confirmé. Les contrôles de cohérence doivent distinguer « toutes les couches s’accordent » de « la règle est appuyée par une source utilisateur ».

---

## F-08 — Le même LLM peut écrire le corps puis juger sa conformité

**Gravité : P2 — risque de validation corrélée**  
**Statut : confirmé par lecture du code**

**Emplacement :** `generator.py`, `fill_stubs()` à partir de 10584 ; fonction locale `judge_for()` autour des lignes 10662–10691.

Le flux de remplissage de stubs utilise l’objet `llm` pour solliciter la génération, puis le même objet pour l’évaluation d’équivalence via `framing(llm, _equivalence_prompt(...))`.

La consigne de répondre non en cas de doute est une précaution utile, mais le juge n’est pas indépendant du générateur : les mêmes biais de compréhension et les mêmes hypothèses peuvent se retrouver dans les deux étapes.

**Risque :** le modèle peut produire une interprétation erronée du contrat puis la reconnaître comme équivalente à sa propre interprétation.

**Correction recommandée :**
- séparer génération et jugement (modèles, prompts et contexte distincts) ;
- fournir au juge le texte source utilisateur et le contrat confirmé, pas seulement un contrat déjà transformé ;
- ajouter des tests comportementaux ciblés et des assertions indépendantes ;
- conserver les verdicts LLM comme indices, non comme preuve suffisante.

---

## F-09 — `classify_crud` utilise des sous-chaînes pour reconnaître une lecture globale

**Gravité : P1 — faux positif pouvant générer une requête trop large**  
**Statut : reproduit**

**Emplacement :** `kernel/codegen.py`, constantes `READ_ALL_MARKERS` ligne 47 ; `classify_crud()` lignes 202–219 ; `plan_method()` lignes 285–294. Le corps repository est ensuite émis dans `generator.py` (branche `read_all`/`filter`, autour des lignes 2601–2619).

La classification utilise :

```python
READ_ALL_MARKERS = ("readall", "all", "list")
...
if any(marker in name for marker in READ_ALL_MARKERS):
    return "read_all"
```

Après normalisation, une sous-chaîne suffit à classer la méthode comme lecture de tous les enregistrements.

**Reproductions effectuées :**

```python
classify_crud("get_small_businesses") == "read_all"
classify_crud("blacklist_user") == "read_all"
```

`plan_method()` a également classé `get_small_businesses` en `crud:read_all` lorsque l’étape de pattern matching n’avait pas reconnu la méthode.

**Impact possible :** une méthode métier qui porte un mot contenant `all` peut être implémentée comme une lecture globale, plutôt que comme une recherche ciblée ou un stub prudent.

**Correction recommandée :** classifier sur des tokens et des structures de nom exactes (par exemple `read_all`, `list_<entity>` dans un contexte reconnu), pas sur une inclusion arbitraire. En cas d’ambiguïté, préférer le stub.

---

## F-10 — `match_param` peut associer un paramètre au mauvais champ

**Gravité : P1 — filtre métier incorrect**  
**Statut : reproduit**

**Emplacement :** `kernel/codegen.py`, `match_param()`, lignes 93–127, en particulier 112–121.

Pour les préfixes `min_`, `max_`, `start_`, etc., la fonction cherche un champ dont le nom normalisé contient le reste du paramètre, ou l’inverse. Une inclusion partielle peut donc être ambiguë sémantiquement sans être ambiguë lexicalement.

**Reproduction effectuée :**

```python
match_param(["stage"], "min_age") == ("stage", "ge")
```

Le paramètre `min_age` est ainsi associé au champ `stage` et peut devenir un filtre `stage >= ...`, ce qui n’a pas de rapport avec l’âge.

**Correction recommandée :** utiliser des correspondances exactes après retrait du préfixe, des alias explicitement déclarés et une tokenisation stricte. Si aucun champ ne correspond clairement, ne pas inventer de filtre : laisser la méthode en stub ou demander clarification.

---

## F-11 — Les regex d’invariants numériques peuvent perdre la négation

**Gravité : P1 — inversion directe d’une règle métier**  
**Statut : reproduit**

**Emplacement :** `generator.py`, `_numeric_bounds()`, lignes 2689–2732.

La détection de termes comme `positive` ne semble pas traiter correctement les négations qui les précèdent.

**Reproduction effectuée :**

Entrée :

```text
Product price must not be positive.
```

Résultat :

```python
[("price", ">", "0")]
```

La phrase négative a été interprétée comme `price > 0`, alors que « ne doit pas être positif » implique une contrainte différente.

**Correction recommandée :** ne pas convertir une phrase en opérateur numérique par simple présence d’un mot-clé. Extraire la négation et la portée de la proposition, ou demander une formulation structurée/confirmée. Ajouter des tests de paires minimales positives/négatives.

---

## F-12 — Les relations entre champs peuvent également perdre la négation

**Gravité : P1 — inversion directe d’une règle métier**  
**Statut : reproduit**

**Emplacement :** `generator.py`, `_field_relations()`, lignes 2735–2783.

La reconnaissance de « greater than » peut produire `>` même lorsque la phrase contient « not be greater than ».

**Reproduction effectuée :**

Entrée :

```text
selling price must not be greater than cost price
```

Résultat :

```python
[("selling_price", ">", "cost_price")]
```

La contrainte attendue devrait être de type `selling_price <= cost_price`, pas `>`.

**Correction recommandée :** représenter explicitement la négation et les comparateurs dans une structure normalisée, puis tester les variantes « greater than », « not greater than », « at least », « no more than », etc. Une phrase non comprise ne doit pas être convertie en règle.

---

## F-13 — `line_total` peut être calculé par convention de nommage sans contrat de formule

**Gravité : P1 — formule financière potentiellement fausse**  
**Statut : risque statique**

**Emplacement :** `generator.py`, `_create_defaults()`, lignes 2658–2686.

Lorsque les champs `quantity`, `unit_price` et `line_total` existent ensemble, la fonction peut remplir `line_total` par :

```python
quantity * unit_price
```

Cette formule est plausible, mais elle n’est pas nécessairement la règle métier. Elle peut omettre taxes, remises, frais, commissions, arrondis, devise ou règles de quantité.

**Risque :** le code généré semble complet et fonctionne techniquement, mais produit un montant incorrect.

**Correction recommandée :** générer la formule uniquement si elle est explicitement spécifiée ou confirmée. Sinon, laisser la valeur non résolue et demander la règle de calcul, y compris les règles d’arrondi et de devise si pertinentes.

---

## F-14 — La réparation de création de collections peut supposer une forme de données trop précise

**Gravité : P2 — risque de code généré incompatible ou sémantiquement incomplet**  
**Statut : risque statique**

**Emplacement :** `generator.py`, `_add_collection_creates()`, à partir de la ligne 9628.

La fonction complète un corps de service en créant une collection liée au parent, en s’appuyant sur le contrat, la signature de méthode et l’affectation de création du parent. La passe précédente a identifié un risque autour de l’utilisation de `dict(item)` et de la déduction de collection par nom pluriel.

**Risque :** les éléments peuvent être des dataclasses, objets typés ou structures qui ne sont pas convertibles par `dict(item)`. Plus important, la présence d’un nom de collection ne prouve pas la relation ni la règle exacte de création.

**Correction recommandée :** vérifier le type/shape déclaré de l’élément et la relation dans le modèle. Ne pas déduire une relation métier du seul pluriel ou du nom d’un paramètre.

---

## F-15 — Les corps LLM acceptés ne sont pas exécutés pour démontrer leur comportement

**Gravité : P1 — limite fondamentale de la preuve de conformité**  
**Statut : confirmé par lecture du code et par la conception documentée**

**Emplacement :** `generator.py`, `fill_stubs()`, à partir de la ligne 10584.

Les corps acceptés passent notamment par compilation et contrôles structurels/API. Cela vérifie la syntaxe et certaines contraintes de forme, mais ne prouve pas que le comportement métier est correct à l’exécution.

La documentation/commentaire du flux indique que cette étape ne vérifie pas le comportement. Une méthode marquée comme écrite/acceptée ne doit donc pas être assimilée à une méthode validée fonctionnellement.

**Correction recommandée :** distinguer clairement les statuts `generated`, `compiled`, `contract-checked`, `behavior-tested` et `accepted`. Ajouter des tests d’exécution dérivés de scénarios indépendants, en particulier sur les préconditions, effets persistés, erreurs et cas limites.

---

## F-16 — Une extraction JSON exploitable n’est pas nécessairement exhaustive

**Gravité : P1/P2 — exigences manquantes silencieuses**  
**Statut : risque de conception identifié lors de la passe précédente**

**Emplacement :** `kernel/extraction/pipeline.py`, `_generate()` ; `review_grounding.collect_questions()` (à vérifier plus précisément lors de la prochaine passe).

Le fait que le JSON généré soit valide et exploitable ne démontre pas que toutes les exigences du texte source ont été extraites. La passe précédente a relevé que les `missing_capabilities` ne sont pas nécessairement toutes transformées en questions de revue.

**Risque :** une capacité absente de l’extraction peut ne jamais être soumise à l’utilisateur. Les étapes aval travaillent alors proprement sur un cahier des charges incomplet.

**Correction recommandée :** construire une matrice de couverture traçable entre phrases/exigences sources, exigences extraites, contrats, capacités, tests et questions ouvertes. Les exigences non couvertes doivent être visibles, pas assimilées à une absence d’exigence.

---

# Annexe — constats préliminaires sur le runner d’acceptance

Ces constats ont été relevés lors d’une première passe, mais **ne constituent pas le cœur de l’audit demandé**. L’utilisateur a précisé que la priorité est la justesse sémantique de l’agent, les faux positifs et les réparations.

Les points suivants avaient été identifiés dans `scripts/run_bench_acceptance.py` et `tests/runtime/worker.py` :

- `not_applicable` pouvait être traité comme réussite dans le statut global.
- Une exception de `load_context()` était ignorée (`except Exception: pass`) dans le worker.
- Des scénarios absents ou des JSON invalides pouvaient être masqués.
- Certains tests CLI validaient essentiellement le code retour.
- L’oracle était basé sur des documents extraits plutôt que sur une source indépendante du cahier des charges original.
- La passe précédente avait compté environ 268 scénarios sur 60 prompts (262 CLI, 6 sémantiques) dans l’archive ; ce décompte est à revalider avant toute utilisation comme métrique.

Ces constats doivent être revérifiés sur la version courante du dépôt avant d’être traités comme des défauts confirmés.

---

# Ce que cet audit ne démontre pas encore

Les modules suivants n’ont pas encore fait l’objet de la passe approfondie promise. Il serait incorrect de conclure ici que leur revue est biaisée ou insuffisante sans les examiner précisément :

- `review_contracts.py`
- `review_slots.py`
- `probe_readiness.py`
- `kernel/tie_rules.py`
- `kernel/consistency/` (contrôles de cohérence et statuts `unknown`, `unresolved`, `skipped`, etc.)

Les questions ouvertes pour cette prochaine passe sont :

1. Les questions présentées à l’utilisateur exposent-elles réellement les alternatives, ou poussent-elles vers le candidat proposé par le LLM ?
2. Les valeurs de slots préremplies sont-elles traitées comme hypothèses ou comme décisions confirmées ?
3. Les ambiguïtés critiques imposent-elles une revue, ou celle-ci est-elle optionnelle ?
4. Les contrats humains conservent-ils les citations/phrases sources et leur provenance ?
5. Les tie-breakers choisissent-ils parfois une option par défaut sans preuve suffisante ?
6. Les contrôles de cohérence vérifient-ils la sémantique, ou surtout l’existence et l’alignement des noms ?
7. Les états `unknown`, `unresolved` ou `skipped` peuvent-ils être agrégés comme succès ?
8. Les réparations conservent-elles les données d’origine, les valeurs candidates et la justification de chaque transformation ?

---

# Recommandations transversales

## 1. Ne pas confondre cohérence interne et vérité métier

Un modèle, un contrat, un adaptateur, un service et un CLI peuvent être parfaitement alignés tout en partageant la même mauvaise hypothèse. Les contrôles doivent mesurer séparément :
- la cohérence entre artefacts ;
- la preuve dans le texte utilisateur ;
- la confirmation humaine ;
- le comportement à l’exécution.

## 2. Conserver la provenance de bout en bout

Pour chaque champ, invariant, méthode, capacité et précondition, conserver au minimum :
- le passage source exact ;
- l’identifiant de l’exigence source ;
- le statut (`quoted`, `extracted`, `inferred`, `human-confirmed`, `unknown`) ;
- la transformation appliquée ;
- la justification et la version de la réparation.

Une réparation ne doit pas transformer silencieusement `inferred` en `confirmed`.

## 3. Préférer l’abstention à une classification hasardeuse

Les règles mécaniques sont utiles lorsqu’elles sont exactes. Quand le nom, la phrase ou la structure est ambiguë, le comportement sûr est le stub, le statut non résolu ou une question de clarification — pas une implémentation plausible.

## 4. Séparer les niveaux de validation

Ne pas présenter comme « validé » un corps seulement compilé ou jugé équivalent par un LLM. Utiliser des statuts distincts et une preuve explicite pour chaque niveau.

## 5. Construire des tests adversariaux ciblés

Ajouter des tests de non-régression pour :
- mots-clés présents dans des logs/commentaires/chaînes sans effet réel ;
- noms contenant fortuitement `all`, `list`, `readone`, etc. ;
- paramètres proches lexicalement mais sémantiquement différents ;
- phrases métier avec négation ;
- absence de contrat ;
- extraction vide ;
- contrats incomplets ;
- formules de calcul avec taxes/remises/arrondis ;
- valeurs inconnues et revue non effectuée.

---

# Conclusion

Les éléments reproduits montrent que certains contrôles peuvent accepter un corps qui ne réalise pas réellement l’effet contractuel, que des heuristiques de nommage peuvent déclencher une stratégie CRUD incorrecte et que les parseurs d’invariants peuvent inverser une règle contenant une négation. D’autres réparations présentent un risque de transformer une extraction incomplète en architecture plausible, ou de supprimer une garde parce qu’elle n’apparaît pas dans un contrat absent.

Le risque transversal est celui d’une **erreur sémantique rendue cohérente par les couches successives** : le système peut produire un résultat propre, compilable et aligné en apparence, mais fondé sur une interprétation initiale erronée.

La prochaine passe utile est l’examen détaillé de la revue humaine, des slots, des tie-breakers et des contrôles de cohérence, afin de déterminer si ces mécanismes empêchent réellement ces erreurs ou s’ils peuvent les entériner.
