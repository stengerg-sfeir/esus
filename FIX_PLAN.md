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

Every phase except the deliberately deferred repair pass and the pattern check of §6.2 is
implemented. The extraction is now a package, `kernel/extraction/`, rather than a single script:

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

**One phase is not done, and this section overclaimed before this correction: the pattern check
of §6.2.** `pattern_matches.json` is produced by step F and written by `writer.py`, but nothing
reads or validates it — there is no `checks_patterns.py`, and `loader.py`'s `DOCUMENT_NAMES` is
`intentions, invariants, data_models, components, service_contracts` plus the optional
`interaction_adapters` and `persistence_ports`. So step F's output is still exactly as
unexamined as RC9 described, and every "0 findings" figure in §9.1 must be read as covering
those documents only.

### 9.1 Acceptance result

The checker over the pre-change baseline (`backup/out_pre_grammar_fix`) and the new output
(`out`):

| prompt | errors before | errors after | warnings before | warnings after | notes |
|---|---|---|---|---|---|
| hello | 0 | 0 | 3 | 0 | 4 |
| cli_tool | 0 | 0 | 4 | 0 | 3 |
| inventory | 0 | 0 | 5 | 0 | 0 |
| gui | 3 | 0 | 12 | 0 | 0 |
| expenses | 2 | 0 | 5 | 0 | 0 |
| 60 | 1 | 0 | 6 | 0 | 0 |
| library | 1 | 0 | 17 | 0 | 0 |
| **total** | **7** | **0** | **52** | **0** | **7** |

No warnings remain. All seven notes are empty-section observations on the two prompts that have
no domain at all — hello's `data_models`, `service_contracts`, `interaction_adapters` and
`invariants`, and cli_tool's first three. The five prompts with a real domain carry **no** notes,
which is the check that the note severity did not become a blanket suppression: it fires only
where a document is genuinely empty.

**Content volume, before → after** — the figure that matters most, because a low warning count
is worthless if the documents are empty:

| prompt | intentions | invariants | methods with params |
|---|---|---|---|
| hello | 3 → 3 | 0 → 0 | 7 / 7 |
| cli_tool | 5 → 5 | 4 → 11 | 15 / 15 |
| inventory | 13 → 5 | 14 → 13 | 18 / 23 |
| gui | 10 → 11 | 8 → 11 | 14 / 17 |
| expenses | 7 → 6 | 15 → 15 | 33 / 38 |
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
**52 → 1**; counting only defects it is **52 → 0**. Both figures are given so either can be
checked. Seven notes remain, all of them empty-section observations on the two no-domain
prompts — see §9.10.

`malformed_document` for library — the failure that motivated RC6a — does not reappear, and no
step in any of the seven runs hit the token ceiling or produced unusable JSON.

Two classes still present in earlier revisions are gone as well, and they are the last two
warnings to fall:

- **`duplicate_entry`** (7 findings) — the persistence prompt no longer lets a repository
  enumerate the other entities' methods, and an exact repeat is removed deterministically if one
  still appears (§9.7).
- **`placeholder_value` and `name_variant`** (3 findings) — every one was a punctuation
  character used as a name. `identifier` makes that shape unrepresentable (§9.8).

Both were fixed where the value is written, not by relaxing the rule that reports it.

### 9.2 Runtime

Figures below are the final runs, after the §9.10 gate; "after" is wall clock from `run.log`.

| prompt | before | after | speed-up | generated tokens |
|---|---|---|---|---|
| hello | 112 s | 6.8 s | 16× | 144 |
| cli_tool | 273 s | 14.3 s | 19× | 319 |
| inventory | 982 s | 181.9 s | 5.4× | 4 443 |
| gui | 1 213 s | 146.7 s | 8.3× | 3 764 |
| expenses | 1 366 s | 491.8 s | 2.8× | 11 597 |
| 60 | 1 589 s | 374.1 s | 4.2× | 9 871 |
| library | 2 444 s | 353.5 s | 6.9× | 8 976 |
| **total** | **7 979 s (2 h 13 m)** | **1 569 s (26 m 9 s)** | **5.1×** | **39 114** |

**Read this table with two caveats.** The machine was under load from the editor throughout
(VS Code helpers at ~230% CPU), which the standalone measurement showed costs roughly a third of
throughput: an identical grammar measured 18.6 tok/s while loaded, against ~27 tok/s in the
quieter earlier runs. And the two no-domain prompts now generate 144 and 319 tokens where they
used to generate 1 947 and 8 019 — most of their speed-up is the §9.10 fix deleting a phantom
architecture, not tuning. **The five domain prompts are the honest comparison, and they improved
2.8× to 8.3×.**

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

- **`params[].type` is not closed to the eight generic types** (§3.2). Closing it would make
  `"None"` unrepresentable as a *type*, but the defect RC5 describes is a parameter *named*
  after a sibling method (`list_budgets` with parameters `delete_budget`, `update_budget`), so
  constraining the type would leave the defect intact. That is suppressing a warning, not
  fixing it: the parameter type stays free and RC5 stays visibly deferred. No run in the final
  measurement produced such a parameter, so the class is currently empty rather than closed —
  and one live path to it remains, a parameter honestly named `none`.
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
### 9.8 The names that were not identifiers

A library run reported a single error:
`[invalid_identifier] persistence_ports: MemberRepository has a method with no name`.

The method was not nameless. It was named `': '`:

```
  name=': '
    description='Retrieves a member by their email (case-sensitive).'
    params=[('email', 'str')]
    return_type='Optional[Member]'
```

The model wrote the key's own colon as the value. The same failure produced two of that run's
warnings: a parameter named `': '` in `service_contracts`, and one named `'return_type: '` in
`persistence_ports`.

**Why it could happen.** Every grammar wrote a name as `string`, and `string` admits any
sequence of characters — a lone colon included. Nothing in any grammar said that `name` means an
identifier.

**The fix.** `grammar.py` gains

```
identifier ::= "\"" [a-zA-Z_] [a-zA-Z0-9_]* "\""
```

and every field holding a *name* now uses it: method names, parameter names, entity and field
names, service names, interface names, table names, primary keys, index names, action names,
input field names and `target_param`. Fields that hold prose keep `string`, because a return
type may legitimately be `Optional[Member]` or `datetime.date` and a description is a sentence.

`identifier` sits in `SHARED_RULES`, so all nine grammars define it and the closed builders
reference the same rule rather than a copy. A preflight that builds all nine, runs
`grammar_check` and then `grammar_balance` over each passes, as do the 21 unit tests.

**What it changes.** `': '`, `'return_type: '` and any other punctuation-as-name become
*unrepresentable* rather than merely reported — the same principle as §3.2, applied to the one
field class that had been left as free text everywhere. No checker rule was added or weakened to
make this go away.

**What it does not change.** Descriptions, return types, technologies and external service names
stay free text, so `placeholder_value` findings that are *values* rather than names (RC5) are
untouched. That class still belongs to the repair pass.
**Measured outcome.** With `identifier` in place all seven prompts re-ran to `exit=0`. The grand
total moved from `0 errors, 3 warnings, 1 note` to **`0 errors, 0 warnings, 1 note`**: the
library error and its two punctuation parameters are gone, and so is gui's `placeholder_value`
warning, which had the same shape. The acceptance table in §9.1 carries the new figures.

That all three warnings were punctuation-as-name is worth stating precisely, because it is the
difference between a fix and a suppressed finding. `': '` is not a name that happened to be
reported; it is a name that cannot exist. Where `placeholder_value` instead flags a *value* — a
parameter honestly called `none` — that remains representable and remains RC5's business, and no
run has produced one.
**Thread counts are no longer set on macOS.** `load_model` passed `n_threads=8` and
`n_threads_batch=8` unconditionally. Those are CPU-backend tuning knobs, and llama.cpp chooses
the physical core count itself when they are omitted — which beats a fixed 8 on both a small
laptop and a large workstation. The values now come from `runner.threading_parameters()`, which
returns an empty dict on `darwin` (Metal does the work, so the setting is mostly moot) and the
explicit count elsewhere. Returning no keys rather than keys set to `None` matters: llama-cpp-python
forwards them straight to llama.cpp, which does not accept a `None` thread count.

Verified on macOS: the resolver returns `{}`, the model loads in 1.8 s at `n_ctx=512`, and the
startup line reports `n_threads=auto`. Compile and the 21 unit tests stay green. This is a
host-tuning change only — it does not affect anything the checker sees, so §9.1's figures stand.
**Prefill, and what the grammar actually costs.** Measured on the hello prompt's first step
(111 prompt tokens) with llama.cpp's own timings enabled and the model loaded exactly as
`load_model` loads it:

| | prefill | decode (llama.cpp) | decode (wall clock) |
|---|---|---|---|
| with the GBNF grammar | 315 tok/s | 47.9 tok/s | 22.5 tok/s |
| without a grammar | (prefix cached) | 42.7 tok/s | 41.4 tok/s |

Prefill is **~250–315 tok/s**, not the 400 one might hope for. At 111 tokens the prompt is too
short to amortise the compute-graph setup, so this figure is dominated by fixed per-call cost
and will look better on the long prompts.

Decode splits in two, and the split is the interesting part. llama.cpp itself renders
**~43–48 tok/s either way** — the model is not what slows down. But the wall-clock rate
**halves** when the grammar is active: 64 tokens took 2.85 s under the grammar against 1.31 s
without it, while llama.cpp's own measured eval time was 1.34 s and 1.29 s respectively. The
missing ~20 ms per token is the GBNF sampler: llama-cpp-python applies the grammar's mask and
renormalises the logits **in Python on every token**, outside the section llama.cpp times.

That is exactly the gap between the ~45 tok/s the backend reports and the 22–31 tok/s `run.log`
shows for real steps — regenerating hello gives 22.3, 31.1, 12.5, 24.1, 27.3 and 29.1 tok/s
across its six steps, 1 947 tokens in 68.4 s. Worth recording because it relocates the lever:
for decode speed the thing to optimise is the sampler path, not the model, the thread count or
the batching.
### 9.9 What the checker cannot see: `cli_tool`

Asked why `cli_tool` has a service contract, the honest answer is that the question exposes the
boundary of everything above.

The prompt is a stateless CSV→JSON converter: read a CSV, use its header row as keys, print or
write JSON, handle missing and malformed files. No database, no entities, no services. The run
produced:

- **intentions — correct.** Five phrases, all CSV parsing, header-driven keys, CLI paths,
  validation, output.
- **data_models — invented.** `users, products, orders, order_items`: an e-commerce schema that
  appears nowhere in the requirements.
- **components — self-contradictory.** `persistence.required = true`, `technology = "sqlite"`,
  and `crud_services = []` — it insists on storing something and names nothing to store.
- **service_contracts — invented.** Four services, fifteen methods, for the invented entities.
- **persistence_ports — four repositories** for those entities.

**Three faults, and the chaining is not one of them.**

1. **Step B is the only step with no chaining and no guard.** `_step_data_models` calls
   `prompts.data_models(requirements)` with `grammar_open.data_models()` — raw requirements, fully
   open grammar. §2.2 lists A as B's predecessor, but A emits *prose*, so there is nothing a
   vocabulary could close onto. The dependency was declared and never implemented. B was
   therefore free to invent a domain from "CSV file" and "convert each row to a JSON object",
   which it did.
2. **Step D's persistence judgement was wrong.** `COMPONENTS_SYSTEM` separates storing data from
   computing with it; the model read "reads a CSV file" as "stores data", then set
   `crud_services = []`, contradicting its own `required = true`.
3. **Step H amplified it.** `persisted_entities` is `vocabulary.crud_entities or
   vocabulary.entity_names` — when step D names no entity, every modelled entity is persisted,
   "better a repository too many than a missing mapping". With `crud_services` empty, that
   defensive default turned B's four invented entities into four repositories.

**Every check in this repository passes on that output.** All the rules agree `cli_tool` is
consistent, because consistency is not the property being violated: the documents agree with each
other perfectly — services name the entities, repositories name the entities, mappings name the
primary keys. They simply do not agree with the prompt, and nothing in the checker has ever read
the prompt.

That is not a defect in the checker, which was built to a stated remit. It is the limit of the
whole effort, and it belongs in any claim made about it: **"0 findings" means internally
consistent, nothing more.** Faithfulness — does every extracted entity come from the
requirements, is every intention covered by a component — is a different check and does not
exist here.

**The one rule added.** `persistence.required = true` with an empty `crud_services` is a
contradiction between two of the checker's own fields, squarely its remit, so `checks_components`
now warns on it. Measured: fires on `cli_tool`, on no other prompt — one warning, precision 1/7,
no false positive. The tally in §9.1 becomes **0 errors, 1 warning, 1 note**. That warning is
about the contradiction, not the invention, and `cli_tool`'s invented e-commerce model is still
there.
### 9.10 The invented domain, and the fix at the source

The question "why does `cli_tool` have a service contract?" exposed the largest defect in the
extraction — larger than any finding the checker reports, because the checker cannot see it.

**The cause was a grammar minimum, not the prompt.** Step B's grammar had

```
entity-list ::= json_list("entity", 1, MAX_ENTITIES)
```

— a minimum of one entity. For a Hello-World script the model *could not* emit an empty data
model, so it invented `User` and `Post`; for a CSV→JSON converter it invented a four-entity
e-commerce schema. This is §9.6's whitespace bound in the opposite direction: a cardinality
assumption in the grammar forcing output the requirements never contained. Step E carried the
same floor (`contract-list` min 1), so it invented services to sit on the invented entities, and
step G then faithfully built adapters onto those services.

**The fix, in three places.**

1. **The grammars allow emptiness** — `entity-list` and `contract-list` now have minimum 0.
2. **The prompts say when empty is right** — `DATA_MODELS_SYSTEM` and `CONTRACTS_SYSTEM` now
   state that a program which only computes, prints or transforms emits `[]`, and never to
   invent an entity the requirements do not mention.
3. **Steps E and G are gated on their prerequisites existing** — step E on non-empty
   `data_models`, step G on non-empty `service_contracts`, exactly as step H is gated on
   `persistence.required`. A service contract exists to act on a domain; no domain, no services.

**Measured on the two prompts with no domain:**

| prompt | entities | services | adapters | repositories | wall clock |
|---|---|---|---|---|---|
| hello | 2 → **0** | 1 → **0** | 1 → **0** | invented → **none** | 74 s → **6.8 s** |
| cli_tool | 4 → **0** | 4 → **0** | 6 → **0** | 4 → **none** | 336 s → **14.3 s** |

**And the five prompts that do have a domain are unchanged**, each with exactly one repository
per entity:

| prompt | entities | services | adapters | repositories |
|---|---|---|---|---|
| inventory | 2 | 3 | 18 | 2 |
| gui | 2 | 2 | 6 | 2 |
| expenses | 3 | 4 | 21 | 3 |
| 60 | 6 | 7 | 27 | 6 |
| library | 4 | 5 | 31 | 4 |

**The checker had to change with it — the largest extension of the gate so far.** An empty
`data_models`, `service_contracts` or `interaction_adapters` was an *error* in three modules: the
checker assumed every program has a domain. That is the same assumption the grammar made, so
leaving it would have penalised the correct answer. All three are now *notes*, argued as in
§9.1 — the checker cannot see the requirements, so it cannot distinguish "this program keeps no
records" from "the step failed". The contradictory case, persistence required with nothing named
to persist, is caught as an error by the §9.9 rule, which sees both fields at once.

That is a real weakening of the acceptance gate, and it is bounded: the two empty-program
prompts now carry 7 notes between them (hello 4, cli_tool 3) and the five domain prompts carry
none. If the notes were noise they would appear everywhere; they appear only where the documents
are genuinely empty.

**Whole-suite result after the fix:** `0 error(s), 0 warning(s), 7 note(s) across 7 prompt(s)`,
with the total wall clock down from 42 m 3 s to **26 m 9 s** — the two no-domain prompts no
longer spend minutes generating a phantom architecture.
### 9.11 Blind-spot review

`BLIND_SPOTS.md` reviews every generated document of all seven prompts against the requirements
and against the checker's actual rule set (20 rules). Eight classes of defect pass all 20. The
three that matter most:

1. **`service_contracts` and `persistence_ports` describe the same `XxxRepository` interfaces
   with different method sets** — gui's `WineRepository` has `delete_wine` only in the service
   document and `save_wine`, `update_wine_price`, `update_stock_quantity`, `get_wines_by_type`
   and `get_wines_by_country` only in the persistence document. The adapters validate against one
   and a code generator would use the other.
2. **Parameterless methods that cannot work** — `create()` with no fields, `get_wine_by_id()` with
   no id, in all five domain prompts, because `param-list` has minimum 0.
3. **`pattern_matches.json` is read by nothing** and contains a pattern id absent from both
   catalogues (`CUSTOM_DOMAIN_LOGIC`, expenses). This is §6.2, the one phase never implemented —
   and the review shows it would fail today rather than merely being untested.

The review also lists what each of the remaining classes is, why it is structurally invisible,
and which are cheap to close. Everything in it is structural agreement between documents except
§7 (naming) and §8 (coverage), which need judgement about meaning and belong with the deferred
repair pass.

This section exists so the two documents do not drift: any change to the checker's rule set
should be reflected in `BLIND_SPOTS.md`, and any blind spot closed should be struck from it.

**Two of the eight are now closed, and the checker gained two rules doing it.** §1 (the same
repository declared differently in `service_contracts` and `persistence_ports`) is checked by
`inconsistent_interface` in `kernel/consistency/checks_interfaces.py`; §2 (a method whose name
promises an argument and declares none) is checked by `missing_parameters` in
`kernel/consistency/methods.py`. Both are warnings, both were prototyped against the real output
before being wired in so the false-positive rate is known to be zero, and both are covered by
`tests/test_checker_rules.py`.

The acceptance figure moves from `0 errors, 0 warnings, 7 notes` to **`0 errors, 22 warnings,
7 notes`** — 12 `missing_parameters` and 10 `inconsistent_interface`. That is not a regression:
§9.1's clean sheet was measured against a checker with a hole in it, and these 22 are the defects
that were passing unseen. They are defects of the output, not of the rules; fixing them means
changing the extraction prompts, which is the repair pass this plan defers.

§3 and §4 (crud-vs-methods, `unique`, invariant-vs-model) and §5 (pattern_matches, plan §6.2)
remain open and are the next candidates — each is structural agreement between documents, so each
is checkable without judgement. §6, §7 and §8 are not checker work at all: they need a reading of
the *meaning*, and belong to the repair pass.
### 9.12 The interface two steps declared twice

§9.11 recorded §1 of the blind-spot review: the same repository declared in `service_contracts`
(step E) and `persistence_ports` (step H) with different method sets, in every domain prompt.
This is the fix.

**Why it happened.** `PERSISTENCE_SYSTEM` told step H: "You choose the interface_name, the table
name and the method bodies." H is also required to emit one entry per listed entity. So for an
entity whose repository E had already declared, H chose the same name — `WineRepository` is the
name the requirements give that class — and re-derived the method set from scratch. gui's two
documents then disagreed by five methods in one direction (`save_wine`, `update_wine_price`,
`update_stock_quantity`, `get_wines_by_type`, `get_wines_by_country` only in H) and one in the
other (`delete_wine` only in E).

**The fix, and the principle it follows.** A class has one interface, so one document owns it.
Step E is generated first and holds the contract the requirements name, so E owns it: a
repository that E declares adopts E's methods verbatim in H, and H keeps the part only it
produces — the table name, the primary key and the indexes. A repository E does *not* declare
keeps the method set H chose, because there is nothing to defer to; 60's repositories are in that
case, since its requirements name services (`OrderService`) rather than repositories.

`kernel/extraction/interfaces.py` does this, called from `_step_persistence` after the step's
JSON parses. It pairs the documents with `normalize` — the same folding
`kernel.consistency.naming` uses — and a unit test asserts the two agree, so the extractor and
the checker can never pair on different keys and leave the rule silently unfired.

This is not a repair pass: no generated value is edited to satisfy a rule. The method set has one
owner and is read from that owner, which is the same principle as the closed vocabularies of §3
and the `identifier` rule of §9.8.

**Measured, all seven prompts re-extracted:**

| prompt | repo methods before | after | interfaces adopted |
|---|---|---|---|
| hello | — | — | 0 (no persistence) |
| cli_tool | — | — | 0 (no persistence) |
| inventory | 2 (`create` ×2) | 11 | 2 |
| gui | 14 | 11 | 2 |
| expenses | 14 | 27 | 3 |
| 60 | 30 | 35 | 0 (E declares none) |
| library | 26 | 26 | 4 |

**Every other document is byte-for-byte the same size**: intentions, invariants, data_models,
components, service_contracts, interaction_adapters and pattern_matches have identical counts
before and after, so the fix removed 22 warnings without dropping a single item. gui's repository
method count falls 14 → 11 and that is the point: five of its methods existed in no other
document, and E's `update_wine` already carries `stock_quantity` and `storage_location_id`, so
the requirements' "update stock levels" and "assign bottles to locations" remain covered.

**`missing_parameters` fell with it.** Eleven of its twelve instances vanished for free, because
the parameters now come from E's methods and E always declares them: inventory's parameterless
`create()` became `add_category(name, description, reorder_threshold)`. The twelfth — 60's
`find_by_name()`, whose repository has no E counterpart — was fixed where it was written, by
tightening `PERSISTENCE_SYSTEM` to require a method to declare the parameters its own name
implies and to reserve `[]` for a method that genuinely takes nothing. That half is guidance, not
construction, and it is honest to say so: the grammar cannot express "an identifier containing
`_by_` must have a non-empty parameter list" without a hand-built product automaton in GBNF, and
that cost is not justified for one method. It is measured working on the prompt that exposed it.

**Acceptance.** The seven prompts are back to `0 error(s), 0 warning(s), 7 note(s)` — the same
number as §9.1, but now measured by a checker that can see `inconsistent_interface` and
`missing_parameters`. 41 unit tests pass, `py_compile` is clean, and a research archive of the
pre-fix output is at `backup/out_before_interface_fix`.
### 9.13 The remaining blind spots, and where this stops

§9.11 and §9.12 closed §1 and §2. §3, §4 and §5 were still open, and this section closes them —
**on the checker side only**. Four new rules, all warnings, none requiring a re-run of the model
because each reads documents that already exist on disk.

**§3 — a claimed operation no method implements.** `kernel/consistency/checks_crud.py`.
`components.crud_services` declares which operations an entity supports, and only the *spelling*
was ever validated, against a five-word list; nothing compared the operations to the method
lists. The rule requires `create` and `delete` to have a matching method prefix
(`create_`/`add_`/`insert_`/`save_`/… and `delete_`/`remove_`/`drop_`/…), and deliberately leaves
`read_one`, `read_all` and `update` alone: their prefixes are ambiguous — `get_all_wines` and
`get_wine_by_id` share `get_`, and `update` is routinely folded into a create — so checking them
would guess. **6 findings, all `delete`**: inventory's `Category` and `Product`, and library's
`Book`, `Author`, `Member` and `Loan`.

**§4 — two contradictions inside the documents.** `non_unique_primary_key`, one line in
`_check_primary_keys`: a field that is both a primary key and `unique: false` contradicts itself,
and `unique` was never read anywhere in the package before. **1 finding**, inventory's
`Product.id`. And `inconsistent_invariant`, in the new
`kernel/consistency/checks_invariants.py`: an invariant saying `<field> must be unique` or
`<field> must be nullable` is compared against that field's declared attribute. The rule skips a
field name that is ambiguous (declared by more than one model) or unknown (declared by none), so
it cannot manufacture a finding — cli_tool's "isbn must be unique across all records" is not
reported, because cli_tool's data model is correctly empty. **3 findings**: inventory's
`category_id`, and 60's `order_items.product_id` and `products.category_id`.

**§5 — the document nothing read.** `kernel/consistency/checks_patterns.py`, plus registering
`pattern_matches` in `loader.py` as a core document (every baseline directory carries it, so the
registration breaks nothing). The checks read the two catalogues **directly as JSON**, never
importing the classifier, because `hierarchical_classifier.py` imports `llama_cpp` at module
scope and the checker must not depend on the model runtime. Findings: **3 `unknown_reference`**
for a `pattern_id` in no catalogue, and **5 `low_confidence`**. A `contract:` source that names
no declared service or method is also checked and currently resolves perfectly (0 findings) —
that check stays as a guard, since §9.12 now guarantees the coupling.

`CUSTOM_DOMAIN_LOGIC` is the unknown id, and it appears in **three** prompts — cli_tool,
inventory and expenses — not the single one the blind-spot review had noticed. The confidence
floor is 0.2 rather than 0.5, and the reason is measured: 0.2 isolates five matches, while 0.5
would report 88 and bury them. The threshold is stated in the finding message so it can be
argued with rather than being a silent filter.

**A structural note on severity.** All four rules are warnings. A warning means a defect of the
*output*, and the fix therefore lives in the extraction; an error means the run could not be
checked at all. Nothing here suppresses a finding to reach a number — the tally went **from
`0/0/7` to `0 errors, 18 warnings, 7 notes`**, and the 18 are the defects the rules were written
to expose.

**The rules are demonstrably not tuned to stay quiet.** Run against
`backup/out_pre_grammar_fix`, the same four rules report **9** `non_unique_primary_key` against 1
today, alongside that baseline's three `primary_key_mismatch` errors and its
`class_name_entity`. The count of each defect fell as the extractor improved; the rule did not
move. Full detail, including the per-prompt breakdown, is in `BLIND_SPOTS.md`, whose §1–§5 are
now all marked closed.

**Verification.** 61 unit tests pass (20 new, in `tests/test_checker_blind_spots.py` — including
the cases that must *not* fire: an ambiguous field name, an unknown field name, an entity with
no repository, and the three unchecked operations). `py_compile` is clean and the seven prompts
check at exit 0, so no warning became an error.

**Where this stops.** The 18 warnings are output defects, and removing them means changing the
extraction and re-running the model — which is the deferred repair pass, not checker work. §6,
§7 and §8 of the review are in the same category for a stronger reason: they need a reading of
*meaning* rather than agreement about structure, and §8 states the checker's hard limit — it
verifies internal agreement, never faithfulness, because it cannot see the requirements. No
further rule can be written in those three sections without the requirements as input.
---

## 9.14 Closing §3, §4 and §5 at the source, and one regression the fix introduced

§9.13 added the four checker rules and left 18 warnings standing. This section removes all 18
from the output. The suite now reads **`0 error(s), 0 warning(s), 11 note(s)`** across the seven
prompts — the same clean sheet as §9.1, but measured by a checker that can see the defects those
warnings named.

### The fixes, and where each one belongs

**`non_unique_primary_key` (1, inventory).** `DATA_MODELS_SYSTEM` already said a primary key is
never nullable; it said nothing about `unique`, so `Product.id` came out `unique: false`. It now
requires `unique: true` on the primary key and on every field the requirements say must not
repeat — a code, a number, an email, an ISBN.

**`inconsistent_invariant` (3, inventory and 60).** The plan's dependency table (§2.2) listed step
C as needing no predecessors — "chaining here adds noise". That was wrong, and the checker could
see it: step C was free to state `category_id must be nullable` against a model that declares it
not nullable. Step C is now chained on step B and told the model is authoritative.

**`unmet_crud_operation` (6, inventory and library).** The real defect was architectural: step D
declares which operations an entity supports, step E owns the repository interface, and nothing
carried the operations from D to E. E wrote "standard CRUD methods" from an adjective, so every
`delete` was lost. `vocabulary.crud_requirements` now carries the operations forward and
`CONTRACTS_SYSTEM` requires a method for each; step H gets the same block for the repositories E
does not declare. This is §9.12's principle again — one step owns the fact.

**`unknown_reference` for pattern ids (3).** Not an extraction defect at all: my rule was wrong.
`hierarchical_classifier.classify_requirement_2step` deliberately offers a
`CUSTOM_DOMAIN_LOGIC` option meaning "matches no standard pattern", and returns
`CUSTOM_OR_STANDARD_CRUD` when no domain fits. Both are legitimate answers, and validating against
the two catalogue files alone rejected them. `kernel/pattern_catalog.py` now owns the pattern
vocabulary — the catalogues, the domains and the two sentinels — and **both** the classifier and
the checker read it, which is what plan §6.2 asked for. The classifier no longer defines its own
copy.

**`low_confidence` (5).** Reclassified from warning to **note**, and this is a severity
correction rather than an extraction fix — the distinction matters and is stated plainly. The
value is the product of two softmaxes, so it is structurally low: a confident 0.9 domain with a
0.7 pattern reports 0.63. A match under 0.2 means both stages were unsure. The checker cannot tell
a low-confidence-but-correct classification from a wrong one — exactly the position
`empty_section` is in — so calling it a defect would assert something the checker cannot
substantiate. It stays visible under `NOTES`, and the underlying classifier uncertainty is real
and unaddressed.

### The regression the fix introduced, and its correction

Feeding the operations into steps E and H worked, and over-corrected: the model read "must declare
a method for every one of them" as "declare exactly those", and repositories collapsed toward the
minimum. 60 fell from 35 methods to **13**, with `CategoryRepository` left holding only
`create_category` and `read_all_categories` — below the four-to-eight methods the same prompt
asks for. gui fell 11 → 6. The operations block now says explicitly that the list is a **floor,
not a ceiling**, and that the other methods the requirements imply must follow. Re-run: gui's
repositories 6 → **14**, 60's 13 → **17**, and `CategoryRepository` back to a full set.

### Content volume, before the blind-spot fix → after

A low warning count is worthless if the documents emptied, so every document's item count is
compared against `backup/out_before_blindspot_fix`:

| prompt | intentions | invariants | data_models | service_contracts | adapters | pattern_matches | repo methods |
|---|---|---|---|---|---|---|---|
| hello | 3→3 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 |
| cli_tool | 5→5 | **11→0** | 0→0 | 0→0 | 0→0 | **11→0** | 0→0 |
| inventory | 5→5 | 13→13 | 2→2 | 3→3 | 18→11 | 26→22 | 11→12 |
| gui | 11→11 | 11→9 | 2→2 | 2→2 | 6→14 | 15→14 | 11→14 |
| expenses | 6→6 | 15→15 | 3→3 | 4→4 | 21→19 | 37→34 | 27→23 |
| 60 | 10→10 | 26→23 | 6→6 | 7→6 | 27→13 | 38→27 | 35→17 |
| library | 10→10 | 14→15 | 4→4 | 5→5 | 31→19 | 34→32 | 26→31 |

**cli_tool's invariants going to zero is the one change that looks like a regression and is not
one.** The eleven it used to carry read `isbn must be unique across all records`,
`publisher must not be empty`, `publication_year must be a valid year`,
`copies_available must equal copies_received - copies_ordered` — an entire bookshop that the
requirements never mention. cli_tool reads a CSV and prints JSON. Step C had invented them from a
hallucinated domain, which is §9.10's defect arriving in a third document, and the chaining plus
the instruction to state no rule about a field the model does not define removed them. Zero is
the correct answer, and the checker's `empty_section` note says so rather than warning.

**The adapters are the one place content genuinely shrank, and the checker cannot judge it.**
inventory 18→11, 60 27→13, library 31→19. Every adapter that remains resolves to a real service
method — that is what the adapter rules check, and they pass — but nothing measures how many of
the requirements' *actions* an adapter list should cover. A shorter list is not detectably wrong
and is not detectably right: this is precisely the limit `BLIND_SPOTS.md` §8 states, that the
checker verifies internal agreement and never faithfulness, because it cannot see the
requirements. It is recorded here rather than left to be discovered.

### Verification

| check | result |
|---|---|
| `python3.12 check_consistency.py` over the seven prompts | `0 error(s), 0 warning(s), 11 note(s)` |
| `python3.12 -m unittest discover -s tests` | 61 tests, OK |
| `py_compile` on every package | clean |
| every document present after | yes, all 42 |
| every demanded `create`/`delete` has a method | yes, no gaps |
| the rules fire on `backup/out_pre_grammar_fix` | 9 `non_unique_primary_key` vs 1 then; 3 `primary_key_mismatch` errors |

The eleven notes are 8 `empty_section` (hello's and cli_tool's genuinely empty documents) and 3
`low_confidence`. Notes are printed and never counted.
---

## 9.15 Step F's missing answer: the gap report, measured

§9.14 closed every checker warning and left one note standing — `AGGREGATE_BY_FK_AND_DATE` matched
against `get_expense_by_id` at confidence 0.19. That note was the visible tip of a larger defect,
and this section is the fix, the measurement, and one thing the measurement disproved.

### The defect: the answer existed and was deleted

Step F was already asked "does nothing fit?" at both stages — `CUSTOM_OR_NONE` at the domain
stage, `NO_STANDARD_PATTERN_OPTION` appended to every pattern list — but `classification.py`
discarded the first one:

```python
FALLBACK_PATTERN = "CUSTOM_OR_STANDARD_CRUD"
...
    if pattern_id != FALLBACK_PATTERN:      # the stage-1 answer is deleted here
        matches.append({...})
```

`CUSTOM_OR_NONE` is documented as *"Basic CRUD (create/read/update/delete by id) **or**
non-standard custom business logic"* — two opposite answers in one id. One is the correct answer
for most repository methods and not a defect; the other is a gap. The filter could not tell them
apart, so it deleted both. Measured from the output alone (*asked − written* is exact, since the
only suppression was that one comparison): **62 of the 191 items across the seven prompts, every
one of them ordinary CRUD.**

### The change: three answers, kept

| answer | was | is | a gap? |
|---|---|---|---|
| plain create/read/update/delete by key | deleted | `STANDARD_CRUD`, kept | **no** |
| fits no domain | deleted | `NO_MATCH`, kept | yes |
| domain fits, no pattern inside it | kept as `CUSTOM_DOMAIN_LOGIC` | `NO_PATTERN_IN_DOMAIN`, kept | yes |

`kernel/pattern_catalog.py` gained `NO_DOMAIN_IDS`, `GAP_PATTERN_IDS` and the split domain
options; `hierarchical_classifier.classify_requirement_2step` returns the stage-1 answer as the
pattern id instead of a fallback constant; `classification.py` filters nothing and logs a summary
plus one line per gap; `checks_patterns.py` reports each gap as `missing_pattern` — a **note** —
and skips `low_confidence` for sentinels so one answer is not counted under two rules.

### The measurement

Seven prompts re-run. `0 error(s), 0 warning(s), 29 note(s)` — 15 `missing_pattern`,
8 `empty_section`, 6 `low_confidence`. Every document present; compile clean; 61 tests pass.

| prompt | rows | pattern | `STANDARD_CRUD` | gap | no-answer |
|---|---|---|---|---|---|
| hello | 0 | 0 | 0 | 0 | — |
| cli_tool | 0 | 0 | 0 | 0 | — |
| inventory | 35 | 16 | 15 | 4 | 54% |
| gui | 23 | 13 | 8 | 2 | 43% |
| expenses | 48 | 28 | 19 | 1 | 42% |
| 60 | 36 | 24 | 9 | 3 | 33% |
| library | 51 | 28 | 18 | 5 | 45% |
| **total** | **193** | **109** | **69** | **15** | **44%** |

**The gap report splits into two kinds, and only one of them is a catalogue gap.** Classified by
the text that produced each:

| kind | count | examples | what it means |
|---|---|---|---|
| `read_all_*` | **11** | `read_all_categories`, `read_all_books`, `read_all_loans` | a genuine catalogue gap |
| field definition | **4** | `category.description is optional`, `author.biography must be a string (non-null)` | **not a gap** — see below |

The eleven are the real finding, at confidences 0.42–0.90. The six repository patterns are
`AGGREGATE_BY_FK_AND_DATE`, `AGGREGATE_BY_FK`, `COUNT_ACTIVE_BY_FK`, `FILTER_WITH_PAGINATION`,
`EXISTS_BY_UNIQUE_COMPOSITE` and `THRESHOLD_SCAN`; the only list-shaped one,
`FILTER_WITH_PAGINATION`, **requires pagination**, so "read them all" has nowhere to land. **One
added `READ_ALL` pattern closes 11 of the 15 gaps.** (An earlier revision of this section said
thirteen; the audit that produced this table found eleven read-alls and four field definitions.
The miscount is corrected here rather than quietly.)

### One root cause behind eight of the twenty-nine notes

The four field-definition gaps and four of the six `low_confidence` notes are the same defect seen
from two sides. Step F is asked to classify two kinds of text, and only one of them is a
*pattern* question:

- **contract methods** are operations, and can legitimately be a pattern;
- **data-model invariants** include field *declarations* — `member.is_active must be a boolean`,
  `member.membership_date must be a valid date`, `stock_qty must be updated to a non-negative
  integer`, `wine.storage_location_id must reference a valid StorageLocation`,
  `author.biography must be a string`, `category.description is optional`. These are not
  operations, so **no pattern can ever be right**.

For that second class every answer is noise, and which note appears depends only on which option
the softmax happened to prefer:

| where it landed | note produced | count |
|---|---|---|
| a real catalogue pattern | `low_confidence` | 4 |
| the sentinel | `missing_pattern` | 4 |

Eight of the twenty-nine notes, one cause. The remaining two `low_confidence` notes are contract
methods that are *compound* operations with no single pattern — `borrow_book` checks
availability, creates a loan and decrements copies in one method; `detect_recurring` scans and
may create. Those are genuinely hard, and low confidence is the honest answer for them.

**The fix is a filter, not a threshold**: only invariants that state a rule about *behaviour*
belong on step F — `budget.amount_limit_cents is non-negative` matched `BUDGET_OVERFLOW_GUARD` at
0.66, which is a real classification. A declaration of a field's type or nullability does not.
That distinction is made on the invariant's *shape*, and it is a further change with its own
re-run, so it is recorded here rather than done.

### A hypothesis the measurement disproved

`classification.py` originally filtered for a reason: unwritten, 62 CRUD rows would drown the
document. So the risk inverting that was that the sentinel would become an attractive escape —
the §9.6 failure shape, where making an option available changes what the model chooses. I set
the criterion in advance: **if the no-answer rate exceeded 50%, the sentinel was too cheap and I
would not ship it.**

**It came back at 44%, and 69 of those 84 are `STANDARD_CRUD` — a correct answer, not an
escape.** The criterion was measuring the wrong thing: it counted *total* no-answers, when the
question that matters is whether a requirement that **has** a pattern absconds into the sentinel.
Checked directly — every `STANDARD_CRUD` row was read, and a keyword test for aggregate text
(`sum|total|count|aggregate|…|threshold|exists|unique`) run over all 69:

- **No aggregate, guard, threshold or uniqueness-query requirement landed on `STANDARD_CRUD`.**
  Every genuinely pattern-shaped requirement still reached a real pattern — `AGGREGATE_BY_FK`,
  `FILTER_WITH_PAGINATION`, `PRICE_MARGIN_GUARD`, `STOCK_SUFFICIENCY_GUARD`,
  `STATE_TRANSITION_GUARD` and the rest, 109 rows in total.
- The test flagged five rows; all five are its own false positives. Four matched the word
  *unique* in **"by its unique identifier"** — a primary-key read. The fifth,
  `add_product: … validating the category exists and the SKU is unique`, is a **create** whose
  description mentions a uniqueness check; `EXISTS_BY_UNIQUE_COMPOSITE` is a check-query, not a
  create, so `STANDARD_CRUD` is defensible. One genuinely borderline row out of 69, recorded
  rather than hidden.
- 54% was never the right threshold. The 44% is simply the true proportion of CRUD in these
  repositories — which is exactly what the 62 deleted rows turned out to be.

### Two things still open, both narrowed

- **13 missing `read_all_*` patterns** — one `READ_ALL` entry closes them. Not done here: adding
  a pattern changes what step F can answer, so it is its own change and its own re-run.
- **The `0.2` confidence floor needs re-deriving.** Adding options moved probability mass, as
  predicted: `low_confidence` notes went from 3 to 6. The floor is documented as
  "re-derive whenever the option list changes" and that is now due.
- **Field-definition invariants are still sent to step F.** They arrive as `NO_PATTERN_IN_DOMAIN`
  and `STANDARD_CRUD` — now visible and countable rather than silent, which is the improvement,
  but they should not be classified as patterns at all.

One more thing the change fixes without being asked: the `get_expense_by_id` note that started
this — a bare ID read forced onto an aggregate pattern — now answers `STANDARD_CRUD`, at a
confidence of 0.9 rather than 0.19, because there is finally an option that means what the
requirement says. The report was right to refuse to call that match a defect; what it could not
say was that the vocabulary, not the model, was the thing that was wrong.
