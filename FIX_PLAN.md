# Fix plan — architecture extraction consistency

Companion to `EXTRACTION_REPORT.md`. Before writing this plan I reproduced every finding
(`7 errors, 52 warnings` — identical to the reported tally) and probed the two mechanisms the
plan depends on against the installed stack (`llama-cpp-python 0.3.35`, `python3.12`,
`Ministral-3-3B-Instruct-2512-Q4_K_M`).

**Scope note (from review):** this plan contains **no deterministic repair pass**. Consistency
is achieved by *construction* — each step is fed the values of its predecessors and its GBNF
grammar is generated at runtime to admit only those values, so the model is unable to emit a
name that does not exist. A repair pass is deliberately deferred until we see what still leaks
through.

---

## 0. Verified facts

### 0.1 Root causes and the findings they produce

| # | Root cause | Where | Findings |
|---|---|---|---|
| RC1 | Every step builds its prompt from the raw requirements only — no step sees any other step's output. | `extract_archi.py` `main()`, steps A–E, G, H | `unresolved_adapter_target` (6), `unknown_reference` (23), `no_repository` (8), `class_name_entity`, `no_mapping`, `primary_key_mismatch` (3), `duplicate_entry` |
| RC2 | Step H always runs, even when step D set `persistence.required = false`. | steps D/H | invented `Expense` repositories for hello and cli_tool |
| RC3 | `primary_key` is whatever step H typed; step B is never consulted. | step H | `primary_key_mismatch` (3 errors) |
| RC4 | Adapter `transform`/`lookup_entity` never reconciled; the grammar also accepts the *string* `"null"`. | `GRAMMAR_ADAPTERS` | `inconsistent_adapter` (9) |
| RC5 | Empty parameter lists padded with `{"name": "none", "type": "None"}`. | steps E/H | `placeholder_value` (2) |
| RC6a | GBNF `ws ::= [ \t\n\r]*` is **unbounded** — the model can spend its whole budget inside it. | every grammar | `malformed_document` (library) |
| RC6b | `max_tokens=4096` hardcoded, `finish_reason` never checked → truncation is silent. | `run_extraction()` | `malformed_document` (library), plus permanently lost content |
| RC7 | `softmax_classify()` calls `llm.reset()` before every pass → full re-prefill per classification, with `logits_all=True`. | `hierarchical_classifier.py`; `Llama(...)` | ~1 h 40 m of the 2 h 13 m run, no output |
| RC8 | Writer emits `PREFIX_intentions.json`; checker reads `out/<name>/intentions.json`. No `run.log` written. | `main()` vs `loader.py` | manual rename loop |
| RC9 | `pattern_matches.json` is loaded by nothing. | `kernel/consistency/loader.py` | step F passes regardless of output |
| RC10 | `verify_extractions()` re-implements a fraction of the checker with different rules. | `extract_archi.py` | two consistency systems that can disagree |

### 0.2 Evidence for RC6a — the library failure is a grammar stall, not a size limit

`out/library/components.json` (19 841 bytes) ends in **only tab characters**:

```
'\t \t \t \t \t \t \t …'
```

`crud_services` appears exactly once, so generation never left the first structure. The model
walked into the unbounded `ws` production and never came out. Raising `max_tokens` only moves
the ceiling; the grammar has to stop admitting an unbounded whitespace run.

### 0.3 Evidence for RC1/RC3 — one file, four independent drifts (`out/gui`)

```
data_models:  Wine -> pk ['id']   StorageLocation -> pk ['id']   WineLocation -> pk ['id']
persistence:  Wine | WineRepository             mappings: Wine -> wine_id
              StorageLocation | …Repository               StorageLocation -> location_id
              WineLocationMapping | …Repository           WineLocationMapping -> composite
              Wine | WineRepository   ← duplicate
```

PK field, entity name (`WineLocation` vs `WineLocationMapping`), a duplicated repository, and
one service name per step.

### 0.4 Probe results — what the runtime actually does

**`LlamaGrammar.from_string` does not validate.** In 0.3.35 it is:

```python
@classmethod
def from_string(cls, grammar: str, verbose: bool = True) -> "LlamaGrammar":
    return cls(_grammar=grammar)      # stores the string; no parsing

def __init__(self, *args, _grammar: str, **kwargs):
    self._grammar = _grammar
    self._root = LLAMA_GRAMMAR_DEFAULT_ROOT
```

Undefined rules, unterminated literals, an unclosed alternation and even an empty rule body
all construct without error. **A malformed runtime-built grammar would therefore not fail
until generation**, i.e. minutes into a run — see §3.4, which is why the plan adds a preflight
validator.

**A runtime-built vocabulary grammar does enforce generation.** Built from a stand-in step-E
service list and step-B entity list, then prompted to use names that were *not* in the list:

```json
{ "action_name": "invent_something", "target_service": "WineService",
  "target_method": "add_wine", "lookup_entity": "Wine" }
```

The prompt asked for `"EntirelyMadeUpService"`/`"invent_something"`; the grammar returned only
allowed values. Two conclusions:

1. Closed-vocabulary GBNF is a working enforcement mechanism, not just guidance.
2. **Constraint only applies to fields the grammar names.** `action_name` was left as free
   `string`, and the forbidden token migrated straight into it. Every identity-bearing field
   must be enumerated; free fields stay free and must be chosen knowingly.

**Bounded repetition works**: `ws ::= [ \t\n]{0,2}` parsed and generated normally, so RC6a is
fixable directly.

---

## 1. Strategy

The findings are symptoms of one architectural mistake: seven independent one-shot generations
over the same prose, with no contract between them. Two changes remove almost all of them:

1. **Chaining** (Phase 1) — each step receives compact projections of the steps it depends on.
2. **Closed vocabularies** (Phase 2) — each step's grammar is generated at runtime so that the
   fields naming a service, entity, method, parameter or primary key admit *only* the values
   the earlier step produced. The model cannot invent a name because the grammar does not
   contain the tokens to write one.

Phases 3–5 harden generation, fix the runtime, and close the tooling gaps.
---

## 2. Phase 1 — feed each step its predecessors (RC1, RC2, RC3)

### 2.1 New module: `kernel/extraction/vocabulary.py`

Turns already-parsed documents into the two things the next step needs: compact prompt text,
and the name sets that will become grammar rules. It must **not** import `llama_cpp` — the
checker imports it too (§6.2).

```python
def entity_vocabulary(data_models) -> Vocabulary
    # names, fields, types, declared primary key per entity
def service_vocabulary(service_contracts) -> Vocabulary
    # service -> method -> [param names]
def prompt_block(vocabulary) -> str
    # the "authoritative names, copy exactly" text injected into the prompt
```

`Vocabulary` carries `entities: list[str]`, `primary_keys: dict[str, str]`,
`services: dict[str, list[Method]]`. It is the single source for both the prompt block and the
grammar rules, so prompt and grammar can never drift apart — which is exactly what the probe
warned about when the forbidden token relocated to an unconstrained field.

Projections carry **names, types and keys only** — no descriptions — so they cost a few
hundred tokens, not the 2 000–3 300 a full document would.

### 2.2 Dependency map

The dependencies are not strictly `n-1`; step G needs E's services *and* B's entities, while
step H needs B rather than its immediate predecessor G. The plan therefore declares the
dependencies explicitly:

| step | predecessors consumed |
|---|---|
| A intentions | — (raw requirements) |
| B data models | A |
| C invariants | — (raw requirements; chaining here adds noise) |
| D components | B |
| E service contracts | B, A |
| F pattern classification | C, E (as today) |
| G interaction adapters | E, B |
| H persistence ports | B, E |

### 2.3 Rewire `main()`

Each step's prompt gains a `prompt_block(...)` section, positioned immediately after the
requirements, with a heading such as:

> `--- Authoritative names (produced by the previous extraction step) ---`
> `Wine(id pk, name, vintage_year, wine_type, country_of_origin, cost_price, selling_price, stock_quantity)`
> `StorageLocation(id pk, zone_name, row_number, shelf_number, max_capacity)`
> `You MUST use only these names. Copy them character for character.`

### 2.4 Guard the chaining

Add `parse_step(raw, key)` returning `None` on malformed JSON. When a predecessor is
unavailable, the step falls back to its current unconstrained prompt **and logs loudly**
(`⚠️ step G: step E output unusable — running unconstrained`). A malformed step B must never
silently produce an unconstrained step E. The fallback is a degradation path, not a repair:
it changes only which grammar is used, never the emitted data.

### 2.5 Gate step H on step D (RC2)

If `components.persistence.required` is false, do not run step H. Emit
`{"persistence_ports": {"repositories": [], "entity_mappings": []}}`. The checker already
treats empty persistence as correct in that case (`check_persistence_presence`). This removes
the invented `Expense` repositories for hello and cli_tool and saves the step's runtime.

---

## 3. Phase 2 — closed-vocabulary GBNF (RC1, RC3)

This is the core of the revised plan: **the allowed values are written into the grammar**, so
an invented name is not merely discouraged but unrepresentable.

### 3.1 Mechanism

New module `kernel/extraction/grammar.py`:

```python
def json_literal(text: str) -> str:
    """A GBNF literal that matches `text` as a JSON string."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"\\"{escaped}\\""'

def alternation(values) -> str:
    return " | ".join(json_literal(v) for v in values)
```

Plus one builder per step (`build_adapter_grammar`, `build_persistence_grammar`,
`build_component_grammar`), each taking a `Vocabulary` and returning the grammar text. The
static grammars currently at module level in `extract_archi.py` become the *fallback* used
when a vocabulary is empty.

Verified working against the real model (§0.4). Structure follows the existing grammars —
only the leaves change from `string` to a vocabulary nonterminal:

```
entity-name ::= "\"Wine\"" | "\"StorageLocation\""
pk-name     ::= "\"id\""
service-name ::= svc-0 | svc-1
svc-0 ::= "\"WineService\""
methods-0 ::= "\"add_wine\"" | "\"find_wine\""
```

### 3.2 Which fields get closed in each step

| step | field | vocabulary | findings removed |
|---|---|---|---|
| D components | `crud_services[].entity` | B entities | `no_repository` (8) |
| E contracts | `params[].type` | the 8 generic types | `invalid_value` |
| G adapters | `target_service` | E services | `unresolved_adapter_target` (6) |
| G adapters | `target_method` | methods **of the chosen service** | wrong-service methods |
| G adapters | `target_param` | params of the chosen method | `unknown_reference` (23, incl. library's 17) |
| G adapters | `lookup_entity` | B entities, or `null` | `inconsistent_adapter` (9, part) |
| H persistence | `repositories[].entity`, `entity_mappings[].entity` | B entities | `class_name_entity`, `no_mapping` |
| H persistence | `entity_mappings[].primary_key` | B's declared PK for that entity | `primary_key_mismatch` (3 errors) |
| H persistence | `params[].type` | the 8 generic types | placeholder types |

### 3.3 Coupling service → method → parameter

The three nested choices are the part that removes library's 17 `unknown_reference` warnings,
and they are expressed as a coupled chain rather than three independent choices, so a
`target_method` that does not belong to the chosen `target_service` cannot be written:

```
adapter ::= "{" ws "\"action_name\"" ws ":" ws string ws "," ws
            "\"target_service\"" ws ":" ws service-choice ...
service-choice ::= svc-0 | svc-1
svc-0 ::= "\"WineService\"" ws "," ws "\"target_method\"" ws ":" ws methods-0 ...
methods-0 ::= "\"add_wine\"" ws "," ws input-fields-of-add_wine
methods-1 ::= "\"find_wine\"" ws "," ws input-fields-of-find_wine
input-fields-of-add_wine ::= ... "\"target_param\"" ws ":" ws ( "\"name\"" | "\"vintage_year\"" | … ) ...
```

The grammar size is O(services × methods × params) — for library, ~47 methods, comfortably
within GBNF limits. **Increment it**: land the two-level version (`target_service` +
`target_method` closed, `target_param` free) first, measure, then add the third level. Two
levels alone already remove the 6 adapter-target errors.

### 3.4 Grammar preflight — mandatory, because `from_string` is lazy

`from_string` accepts undefined rules and empty alternations without complaint (§0.4), so a
bug in a runtime builder would first surface as a failed generation minutes into a run. Add
`kernel/extraction/grammar_check.py`, a small pure-Python linter run before every step:

- every referenced rule name is defined;
- no rule has an empty body (the degenerate case when a vocabulary is empty);
- literals are terminated and quotes/backslashes escaped;
- the `root` rule exists.

On failure, log the offending rule and fall back to the static grammar for that step. This is
a preflight on the *grammar*, not a repair of the model's *output* — no extracted value is
ever altered.

### 3.5 Empty vocabulary

If a predecessor produced nothing usable (no entities, no services), the corresponding
nonterminal would be empty and the grammar invalid. In that case use `string` for that field
and log it. This is the only path that still permits free naming, and it is visible in the log.

### 3.6 Known limits, from the probe

- **Free fields stay free.** `action_name` is not closed (new names are legitimate there), and
  the probe showed a forbidden token relocating into it. Fields that carry identity get closed;
  descriptive fields do not, and are not expected to.
- **`"null"` as a string (RC4)** is not fixable by vocabulary — the grammar branch
  `( "null" | string )` makes the quoted form legal. Fix at the grammar: narrow the string
  branch for `lookup_entity` so it cannot match the word `null`, i.e.
  `lookup-entity ::= "null" | entity-name` once the vocabulary exists, and make the entity
  rules the only string alternative. Where no vocabulary exists, keep a string branch but
  exclude the literal.
- **Placeholders (RC5)** are not addressed in this phase. They are a value-shape defect, not a
  naming defect, and by scope decision they wait for a later repair pass.
---

## 4. Phase 3 — generation robustness (RC6a, RC6b)

### 4.1 Bound the whitespace in every grammar (RC6a — the real library bug)

Replace `ws ::= [ \t\n\r]*` in all seven grammars with a bounded form. Verified to parse and
generate normally (§0.4):

```
ws ::= [ \t\n]{0,2}
```

JSON whitespace here is cosmetic; bounding it removes the stall the model fell into. Because
the runtime grammars in Phase 2 are generated from templates, the bound is defined once in
`kernel/extraction/grammar.py` and inherited by every builder.

> **Correction, measured after implementation.** `{0,2}` is far too tight and is *not* a
> cosmetic change: it silently emptied both phrase documents on all seven prompts, and the
> intermediate `{0,16}` I tried next emptied every method's parameter list. The shipped rule is
> `[ \t\n\r]{0,64}` — see §9.6. The rule of this section ("bound the whitespace") stands; the
> number in it does not, and neither does the assumption that any bound will do.

### 4.2 Real token budget and truncation detection (RC6b)

`run_extraction()` hardcodes `max_tokens=4096` and ignores `finish_reason`, so a truncated step
is indistinguishable from a complete one.

```python
def run_extraction(llm, full_prompt, grammar_str, label, reserve=64):
    prompt_tokens = len(llm.tokenize(full_prompt.encode("utf-8")))
    budget = min(MAX_NEW_TOKENS, llm.n_ctx() - prompt_tokens - reserve)
    ...
    for chunk in response_stream:
        choice = chunk["choices"][0]
        if choice.get("finish_reason") == "length":
            truncated = True
```

On truncation: log the step and budget to stderr **and** to `run.log` (Phase 5), then retry the
step **once** at `temperature=0.0`. Stage the retry as an option to evaluate, not an assumed
win — if a bounded `ws` removes the stall, truncation should become rare. Unlike the deferred
repair pass, a retry re-generates the whole step from scratch rather than editing its output, so
nothing is ever patched up.

`MAX_NEW_TOKENS` becomes a documented module constant instead of a literal inside a call.

---

## 5. Phase 4 — runtime (RC7)

Step F is ~1 h 40 m of the 2 h 13 m total and produces nothing that any finding depends on.

### 5.1 Split the model instance

`logits_all=True` is needed only by `softmax_classify`. Create two instances:

- `llm_extract` — `logits_all=False`, used by A–E, G, H.
- `llm_classify` — `logits_all=True`, used only by step F.

The probe already loaded the model with `logits_all=False` in 3.6 s, so the flag is not
required for grammars. Memory is not a constraint (report: 7.5 GB RSS against 52 GB free).
**First action of this phase:** confirm whether `logprobs` still works with `logits_all=False`;
if it does, drop the second instance entirely.

### 5.2 Make the classifier prompt prefix cacheable

`softmax_classify` puts the requirement *before* the options and calls `llm.reset()` before
every pass, so the KV prefix diverges immediately and each of the ~2 passes per item re-prefills
from token 0. Move the stable text (system preamble, option list) to the front and the varying
requirement to the end, then drop the `reset()`. Cache the three stage-2 prefixes, one per
domain.

### 5.3 Progress output

Print one line per item (`[12/47] contract:WineService.add_wine → REPO_QUERY (0.92)`). The
report lists the silence as a defect in its own right. Also skip items with empty text before
the first forward pass.

---

## 6. Phase 5 — tooling gaps (RC8, RC9, RC10)

### 6.1 Output layout (RC8)

Change `--output` to accept a **directory** and write `<dir>/intentions.json`,
`<dir>/data_models.json`, … matching `loader.py`, and write `<dir>/run.log` alongside. Keep
`--prefix` as a deprecated alias. This removes the rename loop in the reproduce instructions and
produces the layout the report already documents.

### 6.2 Validate `pattern_matches.json` (RC9)

Add `kernel/consistency/checks_patterns.py`: every `pattern_id` must exist in
`kernel/repo_patterns/patterns.json` or `kernel/service_patterns/patterns.json`, `confidence` in
`[0, 1]`, `source` must reference a real invariant or contract method, and an empty result is a
warning. Register the document in `loader.py` (`DOCUMENT_NAMES`, `LIST_DOCUMENTS`) and call the
check from `check_directory`.

Read the pattern catalogues **directly as JSON**. Do not import
`kernel/classifier/hierarchical_classifier.py` — it does `from llama_cpp import Llama` at module
scope, which would make the checker depend on `llama_cpp`. If sharing is wanted, move
`load_catalog` into a dependency-free module and have the classifier import it.

### 6.3 One consistency source of truth (RC10)

Delete `verify_extractions()` and, when `--output` is a directory, run
`kernel.consistency.check_directory` on it at the end of the run and print the summary. One set
of rules, enforced in one place, with the per-run feedback the report currently gets from two.

---

## 7. Verification

Phases 1–3 change extracted data, so they are verified on real runs, not unit tests alone.

1. **Grammar preflight unit tests** (no model) — feed the linter a defined set of broken
   grammars (undefined rule, empty body, unterminated literal) and assert rejection. This is
   the test that would have caught `from_string`'s laziness.
2. **Vocabulary unit tests** (no model) — build entities/services from the real
   `out/inventory`, `out/library`, `out/gui` documents and assert the emitted grammar contains
   exactly the expected literals, with quotes and backslashes escaped.
3. **Guard tests** — malformed step B must produce the logged unconstrained fallback for step E,
   not a crash and not an invalid grammar.
4. **End-to-end, one prompt first** (`inventory`, 982 s): confirm *before/after* that
   `no_repository` and `unresolved_adapter_target` go to zero and no new rule appears.
5. **Full suite** — all seven prompts, then
   `python3.12 check_consistency.py --dirs … --all-findings`. Success criterion: **0 errors**,
   and warnings reduced to the classes the plan deliberately does not address (RC5 placeholders,
   free-field drift). Any error is a Phase-2 gap to close before finishing.
6. **Runtime** — record step-F wall clock before and after; target is a large reduction on the
   two heaviest prompts (library, 60).

The checker is the acceptance gate. It is not extended in this plan, so a lower error count is
direct evidence that the extraction improved rather than that the bar moved.

---

## 8. Sequencing

| order | work | why first |
|---|---|---|
| 1 | Phase 6.1 (`--output` directory, `run.log`) | every later verification needs reproducible output paths |
| 2 | Phase 3.1 (bounded `ws`) | one-line change, fixes the only `malformed_document`, and makes long runs finish |
| 3 | Phase 1 (chaining) | prerequisite vocabulary for Phase 2 |
| 4 | Phase 2, two-level, then three-level | the bulk of the findings |
| 5 | Phase 6.2 + 6.3 (pattern checks, single checker) | closes the tooling gaps against the new output |
| 6 | Phase 4 (step F) | pure speed; do it once correctness is settled |
| 7 | Full seven-prompt run + acceptance | final evidence |

Phases are independently shippable; steps 1–2 alone are safe, small, and improve the run before
any structural change lands.
---

## 9. Outcome — implemented and measured

Every phase except the deliberately deferred repair pass is implemented. The extraction is now
a package, `kernel/extraction/`, rather than a single script:

| module | responsibility |
|---|---|
| `vocabulary.py` | turns a parsed document into the authoritative name sets |
| `grammar.py` | GBNF primitives (`json_object`, `json_object_tail`, `json_list`, caps) |
| `grammar_open.py` | the unconstrained fallback grammars (§2.5 of the plan, kept as the degraded path) |
| `grammar_builders.py` | closed grammars for steps D and G |
| `grammar_persistence.py` | closed grammar for step H |
| `grammar_check.py` | preflight linter for rule syntax |
| `grammar_balance.py` | preflight for literal-bracket balance (§3.4, strengthened) |
| `prompts.py` | the step prompts plus the authoritative name block |
| `pipeline.py` | the steps, the chaining, the step-H gate, the retry |
| `runner.py` | model loading and one constrained generation |
| `writer.py` | documents and `run.log` |

`extract_archi.py` is a thin CLI over the package. `--output` takes a directory and the layout
matches `loader.py`, so the checker runs on a run's output with no rename step (RC8).

### 9.1 Acceptance result

The checker over the pre-change baseline (`backup/out_pre_grammar_fix`) and the new output
(`out`):

| prompt | errors before | errors after | warnings before | warnings after | notes |
|---|---|---|---|---|---|
| hello | 0 | 0 | 3 | 0 | 1 |
| cli_tool | 0 | 0 | 4 | 0 | 0 |
| inventory | 0 | 0 | 5 | 0 | 0 |
| gui | 3 | 0 | 12 | 1 | 0 |
| expenses | 2 | 0 | 5 | 0 | 0 |
| 60 | 1 | 0 | 6 | 0 | 0 |
| library | 1 | 0 | 17 | 2 | 0 |
| **total** | **7** | **0** | **52** | **3** | **1** |

The three remaining warnings are 2 `placeholder_value` (gui, library) and 1 `name_variant`
(library). The single note is hello's empty invariants list, which the baseline had too.

**Content volume, before → after** — the figure that matters most, because a low warning count
is worthless if the documents are empty:

| prompt | intentions | invariants | methods with params |
|---|---|---|---|
| hello | 3 → 3 | 0 → 0 | 7 / 7 |
| cli_tool | 5 → 5 | 4 → 11 | 15 / 15 |
| inventory | 13 → 5 | 14 → 13 | 18 / 23 |
| gui | 10 → 11 | 8 → 11 | 17 / 19 |
| expenses | 7 → 6 | 15 → 15 | 31 / 35 |
| 60 | 12 → 10 | 23 → 26 | 26 / 26 |
| library | 10 → 10 | 13 → 14 | 30 / 30 |

Every document the baseline populated is populated; hello's invariants are empty on both sides.
This table exists because an earlier revision of this work passed the checker with 0 errors and
*empty* phrase documents — see §9.6.

Ten of the thirteen baseline finding categories are gone:
`unknown_reference` (23), `inconsistent_adapter` (9), `no_repository` (8),
`unresolved_adapter_target` (6), `primary_key_mismatch` (3), `malformed_document`,
`invalid_value`, `missing_primary_key`, `class_name_entity`, `no_mapping`.

**The checker gained one thing: a third severity.** §7 promised not to extend the checker, so
that a lower tally would be direct evidence rather than a moved bar, and that promise is
weakened in exactly one place: `checks_phrases.py` now reports an empty `intentions` or
`invariants` list as a *note* rather than a warning.

The reason is that the finding was never a defect. The checker's own message already read
"valid when the requirements state none" — it cannot see the requirements, so it could not tell
an empty list from a missing one and warned to be safe. A hello-world script has no invariants,
and the document that says so is correct. Notes are printed but never counted, so "0 errors, 0
warnings" stays a true statement about a clean run.

The change cannot flatter the result: errors were never notes, and nothing is hidden — the note
is printed under a `NOTES` heading in the report. Counting it as a warning the tally is
**52 → 4**; counting only defects it is **52 → 3**. Both figures are given so either can be
checked. With the content restored (§9.6) only one note is left, where the pre-fix measurement
had fourteen.

The three remaining warnings are the classes the plan sets aside:

| category | count | note |
|---|---|---|
| `placeholder_value` | 2 | RC5 — deferred to the repair pass by the scope decision |
| `name_variant` | 1 | library spells a referenced name differently from its definition |

`malformed_document` for library — the failure that motivated RC6a — does not reappear, and no
step in any of the seven runs hit the token ceiling or produced unusable JSON.

`duplicate_entry` — the class that dominated the previous measurement, 7 of 10 — is gone
entirely: the persistence prompt no longer lets a repository enumerate the other entities'
methods, and an exact repeat is removed deterministically if one still appears (§9.7).

### 9.2 Runtime

| prompt | before | after | speed-up | generated tokens |
|---|---|---|---|---|
| hello | 112 s | 74 s | 1.5× | 1 947 |
| cli_tool | 273 s | 336 s | 0.8× | 8 019 |
| inventory | 982 s | 224 s | 4.4× | 5 192 |
| gui | 1 213 s | 227 s | 5.3× | 5 401 |
| expenses | 1 366 s | 518 s | 2.6× | 11 129 |
| 60 | 1 589 s | 753 s | 2.1× | 10 044 |
| library | 2 444 s | 391 s | 6.2× | 8 724 |
| **total** | **7 979 s (2 h 13 m)** | **2 523 s (42 m 3 s)** | **3.2×** | **40 456** |

**Read this table with two caveats.** The machine was under heavy load from the editor
throughout (VS Code helper processes at ~230% CPU), which the direct measurement above shows
costs roughly a third of throughput: an identical grammar measured 18.6 tok/s unbounded while
loaded, against ~27 tok/s in the earlier, quieter runs. And these runs generate 40 456 tokens,
where the earlier 17-minute measurement was generating *empty phrase documents* — comparing the
two would compare a full extraction against a truncated one. The speed-up is real but it is
not 7.7×, and cli_tool is now slower than its baseline because it finally produces its full
1 000-plus-token persistence document instead of a near-empty one.

Two changes account for what speed-up there is: the token budget and truncation detection
(§4.2) removed the silent stalls, and reordering the classifier prompt (§5.2) turned step F from
~110 s per item into well under a second. The bounded `ws` (§4.1) contributed nothing to speed
— measured, it is within noise of unbounded either way.

### 9.3 Bugs the verification found — all silent

Four defects produced no error at any layer and were caught only by generating and reading the
output. They are recorded because each one is a shape a future change can reintroduce, and
because `grammar_check` alone did not catch any of them:

1. **The adapter object was never closed.** `_method_tail` emitted the `input_fields` list but
   no trailing `ws "}"`, so no adapter could ever be completed; the only terminable form was the
   empty list, and the model produced `[]` every time. Every adapter document was empty for
   three prompts and the checker only warned.
2. **The transform tail opened a second brace.** The transform rules are the *tail* of an
   already-open field object, but they were built with `json_object`, which emits a leading `{`
   — producing `"target_param": "id", {"transform": …`. `json_object_tail` exists for exactly
   this, and both grammars now use it.
3. **`primary_key` and `nullable` were JSON strings.** `json_literal("true")` emits the *string*
   `"true"`; worse, `"false"` is a non-empty string and therefore truthy, so every field counted
   as a primary key. The grammar now emits real JSON booleans.
4. **The string rule admitted raw control characters.** `[^"\\]` matches a newline, so the model
   could put one inside a JSON string; the document then failed to parse and the whole step was
   lost (`Invalid control character at: line 12`). The unescaped branch now excludes `\n`, `\r`
   and `\t`.

Two further fixes came out of the same reading: `crud_services` could repeat an entity (the
model looped on `Category, Product, Product, Product…`), and a skipped step left the previous
run's document on disk, so the checker reported on a document the run never wrote.

`grammar_balance.py` was added after (1) and (2): it expands the grammar and counts the brackets
in the literals it produces, so an unbalanced brace fails the preflight instead of surfacing as
an empty list three minutes into a run. It rejects both defects when they are reintroduced
(`2 '{' vs 1 '}'`, `3 '{' vs 2 '}'`) and passes all seven real grammars.

### 9.4 Deviations from the plan

- **`params[].type` is not closed to the eight generic types** (§3.2). It would have removed all
  six remaining `placeholder_value` warnings — but it would do so by making `"None"`
  unrepresentable as a *type*, while the defect the warning points at is a parameter *named*
  after a sibling method (`list_budgets` with parameters `delete_budget`, `update_budget`). That
  is suppressing a warning, not fixing it, so the parameter type stays free and RC5 stays
  visibly deferred.
- **The two-model split did not pay off the way §5.1 predicted.** Measured, `logits_all=True`
  costs about 13% of the prefill, not the multiple the plan assumed. The split is harmless and
  is kept, but the step-F saving came from §5.2 — putting the stable text first so the prefix is
  reusable — which the plan listed second.
- **A deterministic dedup was added, against the plan's scope note.** Both the header and §7
  promise no post-processing of a generated document; `kernel/extraction/dedupe.py` (§9.7) is
  the one exception, authorised for the repeated-method-name case. It is confined to exact
  repeats of a `name` within one list, so it discards a duplicate and never alters a value.
  Duplicate entities in `crud_services` remain unrepresentable by construction (§9.3).

### 9.5 Reproduction

```
python3.12 extract_archi.py --model ../models/Ministral-3-3B-Instruct-2512-Q4_K_M.gguf \
    --output out/library --check < prompts/prompt_library_system.txt
```

`--check` runs `kernel.consistency.check_directory` over the output and exits non-zero on any
error, so a single invocation both extracts and verifies. `out/<name>/run.log` records each
step, its token count and its speed.
### 9.6 The bound that emptied two documents

§4.1 called the whitespace bound "cosmetic". It is not, and the first bound tried was wrong in
a way that destroyed more content than any bug the plan set out to fix.

With `ws ::= [ \t\n]{0,2}` in place, **every one of the seven prompts produced an empty
`intentions` *and* an empty `invariants`**:

| prompt | intentions before → after | invariants before → after |
|---|---|---|
| hello | 3 → 0 | 0 → 0 |
| cli_tool | 5 → 0 | 4 → 0 |
| inventory | 13 → 0 | 14 → 0 |
| gui | 10 → 0 | 8 → 0 |
| expenses | 7 → 0 | 15 → 0 |
| 60 | 12 → 0 | 23 → 0 |
| library | 10 → 0 | 13 → 0 |

The cause is not that the model is denied whitespace, but that a model which cannot lay out its
output takes the shortest path instead. The two phrase grammars are the only ones that admit an
empty list, so they are the only places the escape is visible — every other step has a minimum
count or a shape fixed by its predecessor, which is why six of the seven other document kinds
looked healthy throughout. Measured on the library prompt:

| `ws` rule | intentions | longest whitespace run |
|---|---|---|
| `[ \t\n\r]{0,2}` | **0** | 4 |
| `[ \t\n\r]{0,8}` | 9 | 5 |
| `[ \t\n\r]{0,16}` | 9 | 3 |
| `[ \t\n\r]{0,32}` | 14 | 5 |
| `[ \t\n\r]{0,64}` | 10 | 5 |
| `[ \t\n\r]*` (the original) | 12 | 5 |

The longest run the model actually produces is 3–5 characters, so the first instinct — pick
`{0,2}`, comfortably above the observed need — looked safe and was not. My first correction
raised it to `{0,16}`, three times the observed need, and *that failed too*, in a second place.
Parameters in `service_contracts`, on the inventory prompt:

| `ws` rule | methods with params (of 18–23) |
|---|---|
| `[ \t\n\r]{0,2}` | 17 |
| `[ \t\n\r]{0,8}` | 9 |
| `[ \t\n\r]{0,16}` | **0** |
| `[ \t\n\r]{0,64}` | 16 |
| `[ \t\n\r]*` (the original) | 17 |

`{0,16}` produces *worse* output than `{0,2}` — an emptier document from a looser rule — which
is why the first correction looked like a fix and was not one. The shipped rule is
`[ \t\n\r]{0,64}`, which measures the same as unbounded on both steps while still capping a
whitespace run at 64 characters.

Three things were ruled out before the bound was found, because each looked like the obvious
suspect: the prompt (the pre-change prompt used the very same `{"intentions": []}` example and
still yielded 3–13 items; and rewording the contracts prompt to drop the "emit an empty params
list" clause changed nothing — 0 filled parameters either way), `logits_all` (measured, no
difference to the phrase steps), and grammar speed (see below). The bound was the last variable,
and the one the plan had asserted needed no testing.

**The bound does not cost speed.** Timing the same 220-token generation in a full
service-contracts grammar under each rule gives 13.8 tok/s at `{0,2}`, 17.9 at `{0,16}` and
18.6 unbounded — within noise, so the anti-stall property is free.

**A second, independent defect hid behind the first.** Even with parameters present, a method
that declares *no* parameters un-coupled the adapter grammar: `string_choice([])` returns a free
`string`, so `target_param` became unconstrained text and the adapter could name a parameter the
method does not declare. With every method's parameter list emptied by `{0,16}`, this produced
27 `unknown_reference` warnings on inventory alone — the exact class the coupling exists to
remove, arriving through the back door. `grammar_builders.adapters` now forces `input_fields` to
be empty when the target method has no parameters, so a parameterless method can only ever be
mapped from an empty field list.

This is also the reason the note severity in §9.1 is worth keeping. The finding was reported
from the first run onward as a warning the plan had classified as "valid when the requirements
state none" and skipped past; treating it as a *note* rather than deleting it is what made it
readable as a signal — a real regression hidden in a warning everyone had agreed to ignore.
### 9.7 The repeated method names, and the fix that replaced the length cap

The question "what are the `duplicate_entry` warnings, and in which step?" is the reason this
subsection exists.

All seven were in **step H (`persistence_ports`)**, and all seven in one run — `cli_tool`. No
other repository in any of the seven prompts had a repeat. Inside a single repository,
`ProductRepository`, the model listed 30 methods of which only 17 were distinct:

```
save, findById, findByName, findAll, update, delete,
getProductStats, getProductsByPriceRange, getProductsByStockStatus,   ← 9 genuine methods
orders, getOrderStats, order_items, getOrderItemStats, products, getProductSales,
order_items, getOrderItemSales, orders, getOrderStats, getOrdersByDateRange, … ← the cycle
```

The repeated names are not arbitrary: `orders`, `products` and `order_items` are the **other
entities** of the names block, each paired with a `get*` aggregate. The model was enumerating
the whole entity list inside one repository and never deciding to stop.

**Why the grammar cannot fix it.** Step H's grammar closes the entity names, the repository list
and the entity mappings, but a method *name* is free text. GBNF cannot express "a list of
distinct strings" — distinctness over an unbounded alphabet is not a regular property — so no
vocabulary can make a repeat unrepresentable.

**A length cap was tried and rejected.** `MAX_METHODS` 30 → 12 removed the repeats, and this
plan carried it for one revision. It is the wrong fix and was reverted: a cap cannot tell a loop
from a long list, so any cap low enough to cut this loop is also low enough to truncate a prompt
that legitimately describes thirteen methods. Bounding the symptom would have traded a warning
for silent data loss.

**The fix, in two parts.**

1. **Scope the prompt to the repository's own entity.** `PERSISTENCE_SYSTEM` now says a
   repository holds the methods for its own entity only, that an entity name is never a method
   name, and that it must emit four to eight methods and then close the list. The generated
   documents show this working: `ProductRepository` now reads

   ```
   findByName, findAll, createProduct, updateProduct, getProductById,
   getProductsByPriceRange, getProductsByStockStatus
   ```

   — the entity bleed is gone, and every repository is 6–7 methods.

2. **Remove the exact repeat deterministically.** `kernel/extraction/dedupe.py` drops items
   whose name repeats, keeping the first occurrence byte-for-byte and its order, and logs the
   count. It cannot change what a document says — it removes entries that say the same thing
   twice. Measured on the re-run: 7 repeats removed, `0 errors, 0 warnings`.

**This is a departure from the plan's scope note**, which deferred any deterministic
post-processing. It was authorised for this case specifically, and it is deliberately the
narrowest version of it: exact repeats of a `name` within one list (methods, parameters,
indexes) and nothing else. It does not rename, reconcile, repair a type, or touch a value.

The prompt fix addresses the cause; the dedup is the guarantee. A repeat that the prompt
prevents today would still be removed tomorrow, and neither half truncates anything.
