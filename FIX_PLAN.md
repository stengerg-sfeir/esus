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
step in any of the seven runs produced unusable JSON.

**One claim this section made is false, corrected in §9.21.** It read "no step hit the token
ceiling". Expenses' `interaction_adapters` hit it on *every* run — all eleven backups and the
current output, always at exactly 3 584 tokens — and the retries that rescued the document were
luck, not design. The ceiling was set below half the room the context had, and until §9.21 the
retry ran under the same ceiling that caused the truncation.

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
---

## 9.16 Keeping field declarations out of the pattern matcher

§9.15 ended with three things left open, the third being that field-definition
invariants were still being classified. This section closes it.

### The defect, measured

Step F was handed every invariant and every contract method. But **most invariants
are not pattern questions at all** — they restate a field's own declaration: its
type, nullability, uniqueness, key or foreign key. Across the seven prompts that was
75 invariants, of which the great majority were declarations, and the classifier
answered every one. Worse than noise, most of that noise scored **above** the 0.2
floor and so was never reported:

| invariant | pattern | confidence |
|---|---|---|
| `budget.month is 'YYYY-MM' string (e.g., '2024-01')` | `BUDGET_OVERFLOW_GUARD` | 0.58 |
| `budget.amount_limit_cents is non-negative integer` | `BUDGET_OVERFLOW_GUARD` | 0.51 |
| `created_at and updated_at in orders must be valid timestamps` | `STATE_TRANSITION_GUARD` | 0.73 |
| `StorageLocation.zone_name must not be null` | `BUDGET_OVERFLOW_GUARD` | 0.38 |
| `product.name is required` | `AGGREGATE_BY_FK_AND_DATE` | 0.28 |

The few that were genuine — `wine.selling_price must be strictly greater than
wine.cost_price` (0.62), `The total number of bottles assigned to a StorageLocation
must not exceed its max_bottle_capacity` (0.71), `loan.return_date must be null if
loan.status is 'active'` (0.84) — were indistinguishable from them.

### The change: tag the invariant when it is written

Two fixes were possible. A filter in `classification_items` would have parsed the
prose with a regular expression — and the extractor's document pipeline contains
**no** content regex anywhere (the only regex in `kernel/extraction/` is structural,
in the GBNF preflight linters; `kernel/classifier/` has none at all), so that would
have introduced a new and fragile precedent. Instead step C now tags each invariant
at the moment it writes it, with the value closed by the grammar:

```
INVARIANT_KINDS = _enum("rule", "schema")     # grammar_open.invariant_list
{"invariants": [{"text": "...", "kind": "rule"}]}
```

`rule` constrains behaviour — it relates two fields, holds only in a state, or bounds
an aggregate — and is worth classifying. `schema` restates a field's declaration and
is not. Step F classifies the `rule`s only (`classification_items`); the declarations
stay in `invariants.json`, because `checks_invariants.inconsistent_invariant` (§4 of
`BLIND_SPOTS.md`) compares them against the data model and would have nothing to check
without them.

Touched: `grammar_open.py` (the builder), `prompts.py` (`INVARIANTS_SYSTEM`),
`pipeline.py` (step C), `classification.py` (the filter), `checks_phrases.py`
(`phrase_text`, one reader for both shapes), `checks_invariants.py`, and two tests —
plus `tests/test_invariant_kinds.py` for the tag itself. The readers accept the old
bare-string shape too, so a directory written before this change still reads.

### The measurement

Seven prompts re-run: **`0 error(s), 0 warning(s), 21 note(s)`** — from 29. The
declaration noise was **8 of those notes**: `low_confidence` 6 → 2, `missing_pattern`
15 → 11. 61 tests became 71; compile clean.

| prompt | invariants | `rule` | `schema` | classified before | after |
|---|---|---|---|---|---|
| inventory | 11 | 1 | 10 | 13 | 1 |
| gui | 16 | 3 | 13 | 9 | 3 |
| expenses | 20 | 4 | 16 | 15 | 4 |
| 60 | 36 | 9 | 27 | 23 | 9 |
| library | 11 | 5 | 6 | 15 | 5 |
| **total** | **94** | **22** | **72** | **75** | **22** |

**75 invariants classified became 22 — a 71% reduction — and no prompt lost all its
rules**, which is the failure in the other direction and was checked for explicitly.
The 22 that remain are genuinely behavioural: `An order can only be confirmed if its
status is 'pending'`, `Expense.is_recurring must be false if expense_date is in the
future`, `Loan.return_date must be null if Loan.status is 'active'`,
`A wine's stock_quantity must not exceed the capacity of its assigned
storage_location`. Those were the classifications worth keeping and they survived.

### The residual, stated rather than rounded away

**Three of the 22 `rule`s still read declarative, and only one is a real mis-tag.**
`product.category_id must reference an existing category` is referential — a
declaration — and the prompt lists that shape as `schema` explicitly, so the model
overrode an instruction. The other two,
`wine.selling_price must be a non-negative integer and strictly greater than
wine.cost_price` and `Loan.due_date must be a valid date (greater than Loan.loan_date)`,
are **mixed** — a bound *and* a cross-field comparison — so `rule` is correct for them
and the marker that flagged them was too crude. Precision is therefore 21 of 22.

One mis-tag in 22 is left in place deliberately: it is one requirement landing on one
plausible pattern, the prompt already forbids it, and another full re-run costs hours
on a machine that was, for most of this work, at a load average between 18 and 54.
Recorded rather than chased.

### A second effect, measured and not hidden

The prompt change also made step C **leaner**: inventory's invariants went 19 → 11 and
library's 22 → 11, as the four redundant `must not be null` restatements and one
malformed hedged entry (`product.sku must match the format of a valid SKU (if format
rules were specified`) disappeared. Earlier in this work a first attempt at the tag
had pushed the count the other way, to 108 — the model filling the new field by
enumerating more declarations. The tightened instruction reversed it.
---

## 9.17 Two things the run logs showed

Asked to review the execution logs, two findings fell out, one of which was a
genuine defect of the class this work exists to remove.

### A truncated document could be accepted silently

`runner.generate` sets `finish_reason` and `StepResult.truncated` reads it, and step G
on **expenses** hit it:

```
[interaction_adapters] 3584 tokens in 159.7s (22.4 tok/s) TRUNCATED
[!] step interaction_adapters hit the token ceiling — its document may be incomplete
[!] step interaction_adapters produced unusable JSON — retrying once
[interaction_adapters] 2869 tokens in 122.4s (23.4 tok/s)
[write] out/expenses/interaction_adapters.json
```

The recovery worked — the truncated text failed to parse, the retry produced a
complete 19-adapter document — **but the parse failure is what saved it, not the
truncation check.** `_generate` ended its retry loop on "the JSON parsed", so a
truncation that landed exactly on a valid list boundary would have been stored with
no retry and no note. A short document is indistinguishable from a complete one
downstream, which is the silent-incompleteness shape §9.6 and §9.16 are both about.

**Fixed**: a truncated document is now retried *even when it parsed*, and only an
untruncated, parseable document ends the loop. If the retry is truncated too it is
kept — better an incomplete document than a missing one — and the log says so:
`[!] step X is still truncated after the retry — the document written is
incomplete`. Six tests in `tests/test_truncation_retry.py` pin the contract with a
stubbed generator, because the case the old code got wrong (a truncated document
that parses) cannot be produced on demand from a real model.

The message `hit the token ceiling — its document may be incomplete` also fired on
an attempt that the retry then fixed, which reads as alarming when the outcome was
fine; it is now folded into the retry line and only the *final* truncation is
declared.

### `read_all` is not only a gap — it is sometimes absorbed, silently

Reviewing why `read_all_*` is a gap in four prompts but not in expenses:

| prompt | what the `read_all_*` methods became |
|---|---|
| library (4) | `NO_PATTERN_IN_DOMAIN` 0.71–0.83 — gap |
| inventory (2) | `NO_PATTERN_IN_DOMAIN` 0.78, 0.90 — gap |
| gui (2) | `NO_PATTERN_IN_DOMAIN` 0.59, 0.62 — gap |
| 60 (4) | three gaps, `read_all_orders` → **`FILTER_WITH_PAGINATION` 0.53** |
| expenses (3) | **all three → `FILTER_WITH_PAGINATION` 0.35–0.57** |

A plain `read_all_expenses` has no filter and no pagination, yet it was recorded as
`FILTER_WITH_PAGINATION` — **above** the 0.2 floor, so silently, with no note. So the
asymmetry is not run-to-run noise: `read_all` has no pattern of its own, and the
model splits between the sentinel and the nearest list-shaped pattern. Expenses'
wording pushed all three to pagination; library's pushed all four to the sentinel.

**This makes the `missing_pattern` count an under-count, and the §9.15 note about
it too optimistic.** "One `READ_ALL` pattern closes 11 gaps" is the reported figure;
there are also **six list-shaped requirements silently mapped to a real pattern**,
which a `READ_ALL` pattern would also claim:

| match | pattern | confidence |
|---|---|---|
| `CategoryRepository.read_all_categories` (expenses) | `FILTER_WITH_PAGINATION` | 0.35 |
| `ExpenseRepository.read_all_expenses` (expenses) | `FILTER_WITH_PAGINATION` | 0.43 |
| `orders.read_all_orders` (60) | `FILTER_WITH_PAGINATION` | 0.53 |
| `ExpenseService.list_expenses` (expenses) | `FILTER_WITH_PAGINATION` | 0.57 |
| `BudgetRepository.read_all_budgets` (expenses) | `FILTER_WITH_PAGINATION` | 0.57 |
| `InventoryService.list_products` (inventory) | `FILTER_WITH_PAGINATION` | 0.64 |

The real target is therefore **seventeen** list-shaped requirements — eleven reported
as gaps and six absorbed — not fifteen. (An earlier revision of this paragraph said
four absorbed, having counted only the matches named `read_all_*` and missed the two
named `list_*`. Corrected here rather than quietly.) It is still one pattern, and
still the highest-value single addition available.

**And this is not a floor problem, which the numbers settle.** The floor is
`LOW_CONFIDENCE = 0.2` in `checks_patterns.py`, and the six absorbed matches are at
0.35–0.64 — every one **above** it. Lowering the floor cannot report them at all;
raising it high enough to catch the cheapest costs far more than it finds:

| floor | matches flagged | of which list-shaped | what else it flags |
|---|---|---|---|
| 0.20 (current) | 2 | 0 | — |
| 0.40 | 10 | 1 | 9 correct: `AGGREGATE_BY_FK`, `AGGREGATE_BY_FK_AND_DATE`, `STATE_TRANSITION_GUARD`, `EXISTS_BY_UNIQUE_COMPOSITE` |
| 0.50 | 25 | 3 | includes `STANDARD_CRUD`, which is a *correct* answer |
| 0.60 | 42 | 8 | 5 `STANDARD_CRUD`, 12 `FILTER_WITH_PAGINATION` |

So no threshold catches these. The model is not unsure — it is **confident and
wrong**, because the option it needed did not exist. That is why the fix is a
pattern, never a number: the floor can separate a hesitant match from a confident
one, and cannot separate a confident right match from a confident wrong one.

Worth stating plainly because it is the same lesson as §9.15 read the other way: a
gap the checker reports is a gap the checker can see, and a wrong match above the
floor is invisible whether the vocabulary is missing a pattern or the model simply
preferred the nearest one.
### Verified on a real run

The retry change was verified against the model, not only against stubs, and the
truncation it defends against **reproduced on the same step it had before** — expenses,
step G:

```
[interaction_adapters] 3584 tokens in 166.0s (21.6 tok/s) TRUNCATED
[!] step interaction_adapters hit the token ceiling — its document may be incomplete — retrying once
```

No `still truncated` line follows, and the document written holds 19 adapters, ending at
`detect_recurring_expenses` — the retry recovered it, as before. What changed is the
*reason* the retry fired and what would happen if the truncated text had parsed. The old
code logged the ceiling unconditionally and then a separate `produced unusable JSON`
line; the reason is now named once, and a truncated-but-parseable document would be
retried rather than stored.

All seven prompts were regenerated through the CLI with the change in place:

| | before | after |
|---|---|---|
| grand total | `0 error, 0 warning, 29 note` → `0/0/21` | **`0 error(s), 0 warning(s), 21 note(s)`** |

and every document is the **same size** on both sides of the run — intentions,
invariants, data models, services and adapters, for all seven prompts, unchanged, with
**no document emptied**. The change alters which attempt is stored, never what is
written, and the identical counts are what shows it.

The `read_all` absorption also reproduced independently on this run, which is what
promotes it from an observation to a property: 60's four list-shaped methods gave three
`NO_PATTERN_IN_DOMAIN` gaps and `orders.read_all_orders → FILTER_WITH_PAGINATION` (0.53),
and expenses gave `read_all_budgets → FILTER_WITH_PAGINATION` (0.57). Two prompts, one
run, same split.
---

## 9.18 Where a pattern kept changing its mind

Asked to review why the same kind of method — `read_all_*` — came back as a
`missing_pattern` gap in one prompt and a `FILTER_WITH_PAGINATION` match in another,
the honest answer turned out to be two defects stacked, and the second one was in
the code, not the vocabulary.

### The vocabulary was missing the read shapes

The repository catalogue held six patterns, and none of them was "read the whole
table" — `FILTER_WITH_PAGINATION` was the only list-shaped one and it *requires a
filter and a page*. So a plain `read_all_categories()` had nowhere to land, and the
softmax split between the sentinel (`NO_PATTERN_IN_DOMAIN`) and the nearest
list-shaped pattern. Which won depended on the wording, so the same requirement
reported differently across prompts.

Two patterns were added, and the existing ones were given exclusion clauses so each
read shape has exactly one home:

| shape | pattern | returns |
|---|---|---|
| `read_all_categories()` | `READ_ALL` | the whole table, **no selection argument** |
| `get_products_by_category(id)` | `FILTER_BY_FIELD` | the records matching a foreign key or status |
| `list_expenses(filters, limit, offset)` | `FILTER_WITH_PAGINATION` | a filtered, paginated page |
| `get_category_by_id(id)` | `STANDARD_CRUD` | one record by key |
| `count_active_loans(member_id)` | `COUNT_ACTIVE_BY_FK` | an **int** count, not records |
| `find_overdue_loans()` | `THRESHOLD_SCAN` | records past a threshold |

The exclusion clauses are the load-bearing part: `READ_ALL` now says outright that a
method taking a `category_id`, `author_id`, `status` or date argument is
`FILTER_BY_FIELD`, and `COUNT_ACTIVE_BY_FK` says outright that returning the *list*
of active records is `FILTER_BY_FIELD`. Measured after the change:

**`read_all` is now consistent — 14 of 14 list reads across the seven prompts land
on `READ_ALL`,** where before they split between a gap and `FILTER_WITH_PAGINATION`.
`single by key` is 11 of 12 on `STANDARD_CRUD`.

First attempt at this was wrong and is worth recording: adding `READ_ALL` **alone**
fixed 15 classifications and broke 10, because with no `FILTER_BY_FIELD` the new
pattern became a catch-all — `find_active_members` (`COUNT_ACTIVE_BY_FK` 0.74),
`find_active_loans` (0.81) and `find_overdue_loans` (`THRESHOLD_SCAN` 0.60) all moved
onto `READ_ALL`. It was the same complaint one level up. The second pattern, not the
first, is what made the vocabulary coherent.

### The runner-up was thrown away, so instability was invisible

The deeper defect was in `classification.py`. The classifier returns the full
softmax over the options, and this step wrote down the winner's probability and
**discarded the rest**:

```python
"pattern_id": pattern_id,
"confidence": round(confidence, 4),     # the winner alone
```

So a `0.70` that beat a `0.69` and a `0.70` that beat a `0.05` produced identical
records, and the checker could not tell a decision from a coin-flip. That is exactly
why the same requirement could report two ways: the two were near-tied, and only one
side of the tie was ever written down. No confidence floor can see this — 0.70 is
0.70.

Fixed by recording the runner-up and the margin, and reporting the margin below a
threshold:

```python
"runner_up_pattern_id": runner_up_id,
"runner_up_confidence": round(runner_up_confidence, 4),
"margin": round(margin, 4),
```

with a `narrow_margin` note in `checks_patterns.py` when `margin < NARROW_MARGIN`
(0.15). Across the seven prompts it reports **12 matches that were too close to
call** and stays silent on the rest — and the split it produces is the proof it
works:

| match | margin | reported |
|---|---|---|
| `filter_expenses` → `AGGREGATE_BY_FK` over `FILTER_WITH_PAGINATION` | **0.00** | yes — a literal tie |
| `list_expenses` → `AGGREGATE_BY_FK` | 0.09 | yes |
| `get_location_by_zone_and_shelf` → `FILTER_BY_FIELD` | 0.06 | yes |
| every `read_all_*` → `READ_ALL` | **0.40–0.72** | no — decided |

**One bug in that change is worth recording**, because the measurement caught it and
a code review would not have: `confidence` is the product of the two softmaxes
(domain × pattern) but the runner-up was taken from the pattern stage alone, so the
margin compared two different quantities and came out **negative** on inventory's
first invariant (−0.034), which no real top-two gap can be. The runner-up is now
scaled by the same domain probability, and the margin is non-negative by
construction.

### What this does not fix, stated plainly

`filtered list` is still not one pattern — 27 such methods land on six different
answers. But my grouping is coarse: `get_overdue_loans` → `THRESHOLD_SCAN` (0.85)
and `get_category_spending` → `AGGREGATE_BY_FK_AND_DATE` (0.88) are *correct* and
belong in that bucket only because a keyword put them there. The genuine stragglers
are the filtered reads where the model is confidently wrong rather than unsure —
`find_active_members` and `find_active_loans` land on `READ_ALL` at margins of 0.49
and 0.53, i.e. it *meant* it. Those are not instability; they are the classifier
preferring a broad pattern over a narrow one, and the fix is a description the model
reads differently, not a threshold.

Two things are deliberately left in place: the 0.15 margin threshold, calibrated
from one corpus and re-derivable as the floor is, and the `STANDARD_CRUD` win for
`get_wine_by_name` (a by-name lookup is not the primary-key read `STANDARD_CRUD`
describes, but it was flagged at a margin of 0.05, so it is at least visible).
### 9.19 The catch-all is `UNKNOWN`, and the attribution is checked against the signature

Asked for two things: the catch-all should be `unknown` so a missing kernel feature is
*detected* rather than papered over by the nearest pattern, and the attribution should be
provably correct because it drives code generation. Both are now in, and the first attempt at the
second was wrong in a way worth recording.

**The sentinel cannot be the catch-all, measured.** The obvious design is to compare the winner
against the "none of these" option and answer `UNKNOWN` when it does not clearly win. That design
was built, then killed by a probe before it was committed: across the 34 expenses methods the
sentinel's probability was **0.000 on 30 of them and never above 0.036**. The model does not use
the option, so a rule that waits for it to win would refuse nothing — offering a
"none of these" answer does not make the model select it. `UNKNOWN` had to be decided **outside
the model**, on evidence the model cannot misread, and that evidence is the item's own return
type.

**Half the evidence was not reaching step F.** `classification_items` built the classification
text as `name: description` — no parameters, no return type. So
`get_monthly_expenses(month) -> List[Expense]` ("Returns expenses for a specific month") and
`get_category_spending(...) -> int` ("Returns total spending …") reached the classifier as
near-identical text, and both were classified `AGGREGATE_BY_FK_AND_DATE`. The signature is now
classified, and this alone corrected cases: `filter_expenses` moved from `AGGREGATE_BY_FK` 0.33
to `FILTER_WITH_PAGINATION` 0.56, because "Filters expenses by category, date range, and payment
method" plus a returning-`List` signature is a filter.

**Each pattern now declares the shape it returns.** `"returns": ["collection"]` beside the
pattern in the catalogue, so a pattern's meaning and its return type cannot drift apart, and
`kernel/pattern_shapes.py` reads it rather than keeping a second vocabulary:

| shape | patterns |
|---|---|
| `collection` | `READ_ALL`, `FILTER_BY_FIELD`, `FILTER_WITH_PAGINATION`, `THRESHOLD_SCAN` |
| `scalar`, `mapping` | `AGGREGATE_BY_FK`, `AGGREGATE_BY_FK_AND_DATE`; `scalar` also `COUNT_ACTIVE_BY_FK` |
| `boolean` | `EXISTS_BY_UNIQUE_COMPOSITE`; `boolean`/`none` for the five guards |

A claim whose shape cannot be the method's return type is **impossible**, not merely unlikely,
and it is replaced by the next candidate whose shape can be right. `find_expenses_by_category
(category_id) -> List[Expense]` claimed `AGGREGATE_BY_FK` (0.58) with `FILTER_BY_FIELD` second
(0.39), so the correction is the filter. Only when **no** candidate can be right does the item
become a gap — and then it is a missing kernel feature, named by the claim and the reason.

**My own rule had the same defect it was written to catch, and the corpus caught it.** The
correction was first written to accept any shape-compatible candidate, and `export_to_csv(...) ->
bool` came out "corrected" to `EXISTS_BY_UNIQUE_COMPOSITE` — a *different* pattern that is also
boolean, therefore shape-valid, and plainly absurd: an export is not an existence check. Shape
compatibility is not family compatibility, so the correction is now confined to
**record-returning** candidates (`pattern_shapes.returns_records`). That is the defect that was
actually demonstrated — a read returning records, named as an aggregate — and correcting into
another return family is a guess, which is what the gap exists to avoid. With the narrowing, the
two `export_to_csv` methods became gaps instead of confident nonsense.

**Measured over the seven prompts** (140 classified items):

| prompt | items | named | gaps | corrected |
|---|---|---|---|---|
| inventory | 23 | 22 | 1 | 0 |
| gui | 17 | 15 | 2 | 0 |
| expenses | 37 | 33 | 4 | 5 |
| 60 | 22 | 22 | 0 | 0 |
| library | 41 | 40 | 1 | 0 |
| **total** | **140** | **132** | **8** | **5** |

The five corrections are all reads misnamed as aggregates, and all five are right:
`get_monthly_expenses` and `get_yearly_expenses` → `FILTER_BY_FIELD`; `find_expenses_by_category`
→ `FILTER_BY_FIELD`; `get_budget_by_month` → `FILTER_BY_FIELD`; `list_expenses` →
`FILTER_WITH_PAGINATION`.

**The eight gaps are four missing kernel features**, which is the detection the section was
asked for:

| missing feature | items | evidence |
|---|---|---|
| **read one record by a unique field** (name, or a composite key) | 3 | gui `get_wine_by_name(wine_name) -> Wine \| None`; gui `get_location_by_zone_and_shelf(zone, row, shelf) -> StorageLocation \| None`; expenses `read_budget_by_category_month(category_id, month) -> Budget` |
| **compound service operation returning an entity** | 2 | library `borrow_book(member_id, book_id) -> Loan \| None` (check, create, decrement); expenses `add_expense(...) -> Expense` (validate, check budget, create) |
| **export / side-effect operation** | 2 | expenses `export_to_csv(...) -> bool` in both the repository and the service |
| **composite service operation returning a summary** | 1 | inventory `add_product(...) -> dict[str, object]` |

Every one is a shape the repository catalogue genuinely does not describe: the six repository
patterns and five guards between them return records, a number, a boolean, or a verdict, and none
returns *one record found by something other than its primary key*, or performs a write and
returns what it wrote. That is not a threshold being too strict — it is the coverage report §5
set out to produce, and it names the next patterns to add.

**The checker gained two notes and no error was ever relaxed.** `corrected_claim` (5) records a
match whose recorded pattern is not the one the classifier chose, so an overruled claim is
visible rather than silent; `missing_pattern` (7, from 8 gap entries — two identical
`export_to_csv` texts dedupe to one message) now names the refused claim and the evidence, e.g.

```
[missing_pattern] 'borrow_book(member_id: int, book_id: int) -> Loan | None: Borrow a book
  for a member. Checks availability, creates loan, and decrements copies.' fits a domain but
  no pattern inside it — the classifier claimed 'READ_ALL' and it was refused: READ_ALL returns
  collection, but this method returns entity (Loan | None) — the catalogue has no pattern for a
  method of this shape
```

Final tally: **0 errors, 0 warnings, 28 notes** — 8 `empty_section`, 8 `narrow_margin`,
7 `missing_pattern`, 5 `corrected_claim`. 116 unit tests pass.

**What is still not checked, stated rather than hidden.**

- **Invariants have no signature**, so the guard chosen for one is judged by the model alone.
  `Wine.selling_price must be strictly greater than cost_price` is a pricing rule the shape rule
  cannot confirm or deny; only contract methods can be checked this way.
- **`READ_ALL` against a parameterless status read.** library's `find_active_members() ->
  List[Member]` and `find_active_loans() -> List[Loan]` were classified `READ_ALL` (0.86, 0.78) and
  the shape rule accepts them, because a collection is exactly what they return. Semantically
  they are `FILTER_BY_FIELD` with the status in the name rather than an argument, and no return
  type can tell the two apart — it needs the *name*, which is the kind of rule that has already
  been wrong twice in this work. It is left as a known residual and a named next step, not
  quietly accepted.
- **The sentinel is still never chosen.** The three answer ids remain, `NO_MATCH` still reports
  "fits no domain", and the model still assigns it ~0 mass. The catch-all works because it does
  not depend on the model choosing the sentinel.
### 9.20 Throughput: what flash attention bought, and why the GPU reads below 70%

Asked to test `n_batch`/`n_ubatch` and `flash_attn` for speed without degrading the output, and
then why GPU utilisation sits under 70%. Both are answered by measurement, and one presumption in
the question turned out to be false.

**`flash_attn=True` is a clear win and is now the default** (`runner.FLASH_ATTENTION`). It is +15%
on decode and +24% on a whole document step, and the output does not change:

| measurement | result |
|---|---|
| 118 real classification items, five prompts | **118/118 identical verdicts**; confidence drifts by a median of 0.0004, max 0.0034; the runner-up *ordering* differs on 2 of 118 |
| one whole document, temperature 0 | **byte-identical** — sha256 `d53bd8d05973316f`, 16 081 bytes either way |
| the expenses adapters step, temperature 0 | **byte-identical**, 22 adapters, and it *completes* under both (3 212 tokens, `finish=stop`, valid JSON) at 23.7 → 29.4 tok/s |

The first probe here reported "0/8 identical" under `flash_attn`, which looked like the
degradation the setting is remembered for. It was my metric: it compared the confidence to six
decimals, so a drift in the sixth decimal read as a different answer. Comparing the **verdict**
gives 118/118. The lesson is §9.19's — compare the thing that matters, not the thing that is easy
to compare.

**`n_batch`/`n_ubatch` do nothing here, and that is consistent with the prompt sizes.** Measured
across 512–4096 for both: prefill 4.02–4.47 s and decode 22.1–25.6 tok/s, no trend. The prompts
are small — library's largest step prompt is **1 122 tokens** — so the default `n_batch=512` costs
three chunks and the chunking is free. Both are left at their defaults, with a note to raise
`n_batch` only if a prompt ever grows past 512 by enough to matter.

**The GPU reads below 70% because it is idle during the grammar sampler, and that is the whole
story.** `llama_perf_context_print` (reachable only with `verbose=True` — the counters go through
llama.cpp's logging callback, which `verbose=False` suppresses) splits decode into the model eval
and everything else:

| decode | prompt eval | eval (the model) | total | non-model per token |
|---|---|---|---|---|
| no grammar | 532.9 tok/s | **50.34 tok/s** (19.87 ms) | 5 804 ms | **0.3 ms** |
| grammar, 881 chars | 541.2 tok/s | **49.26 tok/s** (20.30 ms) | 8 220 ms | **12.7 ms** |
| grammar, 11 212 chars | 532.6 tok/s | **49.06 tok/s** (20.38 ms) | 7 666 ms | **9.5 ms** |

The model takes the *same* ~20 ms per token in all three; the grammar adds ~13 ms of work that is
neither prompt eval nor eval. That is the GBNF sampler applying its mask over the 131k-token
vocabulary, on the CPU, while the GPU does nothing. The GPU-active fraction during decode is
therefore `20.3 / (20.3 + 0.3) = 98%` without a grammar and `20.3 / (20.3 + 12.7) = 61%` with one
— which is the sub-70% figure, explained rather than guessed at.

**The cost is per token, not per grammar.** A grammar 12.7× larger is *cheaper* (9.5 vs 12.7 ms),
so trimming grammars is not a lever and no grammar-complexity budget needs managing. What the
corpus pays for enforcement is ~13 ms/token, and it buys the consistency §9.1–§9.19 were about;
trading it for a 29% decode gain would undo that work.

**Model eval runs at about half the memory-bandwidth ceiling.** The library is 2.15 GB and the
batch-1 ceiling is ~93 tok/s at the M1 Pro's ~200 GB/s, against a measured 49–50 tok/s — normal
for Q4_K on a Metal path where llama.cpp logs `tensor API disabled for pre-M5 and pre-A19 devices`
and falls back to the simdgroup kernels.

**Hypotheses tested and rejected, so they are not retried:**

- **`logits_all=True` is not the cost.** It is *required* — llama-cpp-python refuses `logprobs`
  without it (`ValueError: logprobs is not supported for models created with logits_all=False`) —
  and it costs **+21% on prefill only** (484 tokens: 0.95 s → 1.16 s), not the multiple assumed.
- **Grammar trimming** is not a lever, measured above.
- **`n_batch`/`n_ubatch`** are not a lever, measured above.

**Speculative decoding was tested and rejected.** The obvious remaining lever is speculative
decoding, and this binding exposes it without needing a second model:
`llama_cpp.llama_speculative.LlamaPromptLookupDecoding` drafts the continuation by finding the
last n-gram *already in the input* and copying what followed it — which should suit this project,
because every JSON document repeats names straight out of the prompt's authoritative-names block.
Measured on the same step, same prompt, temperature 0:

| drafter | wall clock | rate | text vs baseline |
|---|---|---|---|
| none | 8.41 s | **22.8 tok/s** | — |
| prompt-lookup, n-gram 2 | 13.12 s | 14.6 tok/s (**0.64×**) | identical |
| prompt-lookup, n-gram 3 | 12.62 s | 15.2 tok/s (**0.67×**) | identical |

It is 1.5× **slower** at both n-gram sizes, and the output is byte-identical — so the mechanism is
sound and the arithmetic is not. Two costs explain it: `draft_model` forces `logits_all=True`
(line 351 of the binding, the same +21%-on-prefill flag measured above), and every rejected draft
token is wasted forward-pass work. With decode bandwidth-bound, verifying a drafted batch is not
cheaper than emitting the tokens one at a time, so the drafter only adds overhead on top.

**That closes the throughput question rather than deferring it.** `n_batch`/`n_ubatch` measured
neutral, grammar trimming measured neutral, `logits_all` is required and cheap, and speculative
decoding is now measured to cost. The remaining decode cost is the ~20 ms of unavoidable model
eval plus the ~13 ms the consistency enforcement requires, and no configuration available here
removes either.
### 9.21 The retry could not recover a truncation, because it reused the ceiling that caused it

Asked whether the token budget had been raised for the steps that fail and retry. It had not, and
the question exposed a defect the retry had carried since §4.2: on a truncation the retry changed
only the temperature, while `runner.generate` clamped the budget to `MAX_NEW_TOKENS = 3584` on
every attempt. **A step that hits a ceiling cannot be recovered by a retry that runs under the
same ceiling** — it can only truncate again.

**It was not hypothetical.** Expenses' `interaction_adapters` truncated at exactly 3 584 tokens in
**every run on record** — the current output and all eleven backups:

```
out/expenses/run.log                         3584 tokens  TRUNCATED
out/expenses/run.log                         3584 tokens  TRUNCATED   <- the retry
backup/out_before_blindspot_fix/expenses     3584 tokens  TRUNCATED
backup/out_before_dontknow_split/expenses    3584 tokens  TRUNCATED
backup/out_before_filter_by_field/expenses   3584 tokens  TRUNCATED
backup/out_before_flash_attn/expenses        3584 tokens  TRUNCATED
backup/out_before_interface_fix/expenses     3584 tokens  TRUNCATED
backup/out_before_invariant_tag/expenses     3584 tokens  TRUNCATED
backup/out_before_margin_field/expenses      3584 tokens  TRUNCATED
backup/out_before_read_all/expenses          3584 tokens  TRUNCATED
backup/out_before_shape_rule/expenses        3584 tokens  TRUNCATED
backup/out_before_truncation_fix/expenses    3584 tokens  TRUNCATED
```

Until the last of those the retry happened to come in under the cap and the document was saved;
in the final one both attempts truncated and the document was lost entirely. So the corpus was
running a step permanently at its ceiling and relying on luck for the result.

**The ceiling was set below half the room the context had.** Tokenising the real step prompts:

| prompt | step | prompt tokens | old ceiling | room available | withheld |
|---|---|---|---|---|---|
| library | contracts / adapters / persistence | 1 039 / 1 122 / 1 130 | 3 584 | 7 089 / 7 006 / 6 998 | **3 505 / 3 422 / 3 414** |
| expenses | contracts / adapters / persistence | 1 330 / 1 461 / 1 421 | 3 584 | 6 798 / 6 667 / 6 707 | **3 214 / 3 083 / 3 123** |
| 60 | all three | 603–796 | 3 584 | 7 332–7 525 | **3 748–3 941** |
| gui | all three | 875–966 | 3 584 | 7 162–7 253 | **3 578–3 669** |
| inventory | all three | 1 047–1 138 | 3 584 | 6 990–7 081 | **3 406–3 497** |

The cap bound on **every** step and withheld 3 083–3 941 tokens. For expenses' adapters — 1 461
prompt tokens, so 6 667 tokens of room — the cap gave 3 584. The step produces roughly 3 200–3 600
tokens, so it was sitting exactly on the boundary: at temperature 0 it fits (3 212), at
temperature 0.1 it tips over. That is the whole failure, and it was a budget set too close to a
real document size rather than anything the model did wrong.

**The fix.** `MAX_NEW_TOKENS` is now explicitly the *first-attempt* guard, and two functions make
the real ceiling explicit:

- `runner.available_tokens(llm, prompt)` — the room the prompt left (`n_ctx - prompt - 64`),
  floored at `MIN_BUDGET = 16`.
- `runner.generation_budget(llm, prompt, max_new_tokens=None)` — the requested ceiling clamped to
  that room. `generate` takes `max_new_tokens` and passes it through.

`pipeline._generate` then does the thing it should always have done: **when an attempt truncates,
the retry asks for the whole remaining context** rather than the ceiling that cut it off. A parse
failure is not a ceiling problem and keeps the default ceiling, so the two failure modes stay
distinct. `StepResult` now carries the budget it ran under and names it in the log, because on a
truncation the ceiling is the diagnosis:

```
[interaction_adapters] 3584 tokens in 125.9s (28.5 tok/s) TRUNCATED at the 3584-token ceiling
[!] step interaction_adapters hit the 3584-token ceiling — its document may be incomplete,
    retrying with a 6667-token ceiling — retrying once
```

And when the context genuinely has no room left, the log says so instead of pretending to raise
it — `the context has no room left to raise the 3584-token ceiling — retrying at the same
ceiling`. That case is real for a prompt long enough to eat the context, and it is reported
rather than passed over.

**Tests: 9 new, 125 total, all green.** The arithmetic is pinned without a model
(`available_tokens`, `generation_budget`, the floor, the no-model fallback), and the retry
contract is pinned with a stubbed generator: the first attempt uses the default ceiling, the
retry after a truncation asks for `context - prompt - reserve`, a *parse* failure does not raise
anything, a context with no room says so, and an untruncated step never raises anything at all.
**Measured end to end, on the prompt and step that failed.** Expenses re-run with the fix, same
model, same prompt, same code path:

```
[interaction_adapters] 3584 tokens in 125.0s (28.7 tok/s) TRUNCATED at the 3584-token ceiling
[!] step interaction_adapters hit the 3584-token ceiling — its document may be incomplete,
    retrying with a 6668-token ceiling — retrying once
[interaction_adapters] 4707 tokens in 170.6s (27.6 tok/s)
[write] out/expenses/interaction_adapters.json
```

**The retry needed 4 707 tokens — 1 123 more than the old ceiling.** Under the code as it was,
that attempt would have been capped at 3 584 and truncated a third time; that is precisely what
happened in the run that lost the document. With the raised ceiling it completes, and the
document is written: **30 adapters, 20 333 bytes**, where the previous run's file was absent
entirely. The checker over the new expenses output reports **`0 errors, 0 warnings`**.

The first attempt still truncates, which is worth stating plainly: the fix does not stop the
model from running long on this step, it stops the *system* from losing the result when it does.
Whether the first-attempt ceiling should rise to meet it is a separate question, and the measured
answer is no — a first attempt that fills 3 584 tokens and a retry that needs 4 707 means the
retry-with-room is doing its job, and raising the default would spend context on every step to
serve one.
### 9.22 Preparing the JSON as a generator input: three defects

The question "are the documents consistent enough to build a code generator on" has a measured
answer: **consistent, yes — `0 errors, 0 warnings` across all seven — but not yet sufficient.**
Consistency is achieved by construction (the closed grammars make an unresolvable name
unwritable), so every reference in the documents resolves. What remains are three things the
generator needs and the documents do not yet provide correctly. This section plans and fixes them
in the order below, because two of the three change *generation* and one does not.

#### D1 — `narrow_margin` compares a pattern with itself (a bug, not a signal)

`classification._runner_up` excludes `result["pattern_id"]` — the model's **raw claim** — when
choosing the runner-up. But `_attribute` may have **corrected** the claim to a different pattern,
and a corrected answer is not excluded, so it can be selected as its own runner-up. Three of the
twelve `narrow_margin` notes are exactly that:

```
'FILTER_BY_FIELD'      ... by a margin of 0.14 over 'FILTER_BY_FIELD'
'FILTER_BY_FIELD'      ... by a margin of 0.06 over 'FILTER_BY_FIELD'
'FILTER_WITH_PAGINATION' ... by a margin of 0.01 over 'FILTER_WITH_PAGINATION'
```

`read_budgets_by_category` was claimed `AGGREGATE_BY_FK` (0.44), corrected to `FILTER_BY_FIELD`
(0.30); the margin 0.44 − 0.30 = 0.14 is real, but the name recorded is the corrected pattern, so
the note compares the winner with itself and can never mean anything.

**Fix:** exclude the **recorded** `pattern_id`, not the claim. A margin may never be computed
against the winner. **Guard:** the checker reports an entry whose `runner_up_pattern_id` equals
its `pattern_id` as a defect, so the bug cannot return silently.

#### D2 — expose the two categories explicitly: `undefined` and `undecided`

Both already exist in the machinery but are implicit, and only the pattern stage is covered:

- **`undefined`** is `GAP_PATTERN_IDS` — `NO_MATCH` ("fits no domain") and
  `NO_PATTERN_IN_DOMAIN` ("domain fits, no pattern inside it"). Already recorded, already reported.
- **`undecided`** is `margin < NARROW_MARGIN`. Recorded, but **only for the pattern stage**.

The hole is that **step 1 is the more consequential decision and its ambiguity is invisible.**
The domain chooses which pattern list step 2 even sees, and a near-tie between `REPO_QUERY` and
`STANDARD_CRUD` decides between a pattern and "no pattern needed" — yet `_runner_up` reads only
`step2_probabilities` and returns nothing at all when step 1 short-circuits. The domain
runner-up is free to derive: `classify_requirement_2step` already returns `step1_probabilities`.

**Fix:** one explicit field, plus the domain-stage margin:

```
"decision":        "decided" | "undecided" | "undefined"
"undecided_stage": "domain" | "pattern" | null      # which stage was near-tied
"domain_runner_up": ..., "domain_margin": ...       # new, from step1_probabilities
# existing and now correct: pattern_id, confidence,
#                          runner_up_pattern_id, runner_up_confidence, margin
```

So the generator switches on one value, and an `undecided` carries the alternatives and the margin
for the stage that was undecided. **`undefined` and `undecided` route differently** — "the kernel
has no pattern" needs the text and the refused claim; "the kernel has two, pick one" needs both
candidates and the margin — and both payloads are already in the record. The threshold stays on
the **margin**, never the confidence: the confidence is the product of two softmaxes, so 0.34 is
not "34% sure" of anything.

#### D3 — step B is the only step that can invent a domain

`data_models` (step B) is the only step whose grammar is **not** generated from an earlier step's
names — every other step's grammar is, so it cannot invent a name. A emits prose, which cannot
become a vocabulary. B therefore runs on the raw requirements with an open grammar, and for
`cli_tool` it filled the required shape from priors: `users, products, orders, order_items` for a
program that converts a CSV to JSON and models nothing.

Measured contrast, same run, same code path: **hello produced zero entities; cli_tool invented
four.** The difference is the nouns — cli_tool says "CSV", "rows", "records", "keys".

Fix in two parts, **landed and measured one at a time**:

1. **A criterion, not a permission.** B must separate *data the program models and persists as a
   domain* from *data it merely reads, converts or passes through*. expenses models and stores
   `Budget`/`Expense`/`Category` — yes; cli_tool reads a CSV and writes JSON, modelling nothing —
   no. The wording must **not** offer emptiness as an answer: the empty list is already legal
   (hello proves it), so a permission would add nothing except an escape for expenses to take.
   This is the §9.6 lesson — a rule that loosens can empty documents.
2. **Implement the A→B chain §2.2 declared and never built.** A's phrases are grounded in the
   requirements. Feeding them to B *adds* grounded vocabulary and fills the vacuum that priors
   fill, and offers no escape. Show, don't constrain.

**No synthesis check.** A rule that every entity be traceable to a noun phrase in the requirements
was considered and rejected: the checker has no ground truth, so it compares strings, and a French
prompt producing English entity names — or any synonym, pluralisation or legitimate domain term —
would be flagged. The failure mode of the criterion is measurable; the failure mode of invention
is invisible; a string matcher would produce false positives on both.

#### Verification, per defect

| defect | how it is verified | the check that must fail if it is wrong |
|---|---|---|
| D1 | unit test on `_runner_up` with a corrected entry | the runner-up must never equal the recorded pattern |
| D2 | unit tests on both stages, plus a run | `undecided` must name a *different* answer, and must fire when step 1 is near-tied |
| D3 | all seven prompts, entity counts before/after, and read hello/cli_tool | the five domain prompts must not shrink |

The acceptance line for the whole section: **`0 errors, 0 warnings`** still holds, and the
generator-facing contract is explicit — `decision` is one of three values on every match,
`undefined` and `undecided` both name what they are, and no margin compares an answer with itself.
### 9.23 The margin was measured against the claim, so every corrected entry reported a fake tie

Four changes to step F, all found by *reading the numbers the previous section produced*
rather than by any test. Three of them are the same defect wearing different masks: a
figure computed against the wrong thing.

**The defect.** §9.22 gave every match a `decision` and a `margin`. Reading the first run
that used them:

```
prompt     recorded                   claimed             runner-up             margin decision
expenses   FILTER_BY_FIELD            AGGREGATE_BY_FK     AGGREGATE_BY_FK        0.0   undecided
expenses   FILTER_BY_FIELD            AGGREGATE_BY_FK     AGGREGATE_BY_FK        0.0   undecided
expenses   FILTER_WITH_PAGINATION     AGGREGATE_BY_FK     AGGREGATE_BY_FK        0.0   undecided
```

Ten corrected entries, ten margins of exactly `0.0`, and in every one the "runner-up" is
the entry's own *claim*. Two things were wrong at once:

- `confidence` was the classifier's total, which describes the pattern it **claimed** —
  not the corrected one recorded beside it;
- `_runner_up` excluded the claim, so for a corrected entry the top remaining candidate
  **was** the claim at exactly the confidence already reported. `confidence - runner_up`
  therefore cancelled: `0.0`, ten times out of ten.

A margin of `0.0` is below any threshold, so all ten were labelled `undecided` — on top of
the `corrected_claim` note they already carried. One entry, two rules, one story: the same
double-reporting §9.2's sentinel work had already had to remove once.

**Fix 1 — the confidence describes the answer, not the claim.** `_recorded_confidence`
recomputes it as `domain_probability * step2_probabilities[recorded]`, and the classifier's
own figure for the claim is kept beside it as `claimed_confidence` (present only when a
correction happened, so the two figures a reader might compare are both on record). Where
there is no second stage to recompute from — a sentinel the model never scored, or a
domain short-circuit like `STANDARD_CRUD` — the classifier's figure stands, because it is
the only one that exists.

**Fix 2 — the margin is asked among answers that were possible.** `_viable_patterns`
returns the candidate ids whose shape can be this method's return type, and `_runner_up`
restricts the choice to them. An impossible claim is not a competitor: it lost to the shape
rule, not to a margin, so measuring a margin against it says nothing about how close the
real decision was. The corrected entries now read honestly:

```
expenses  FILTER_BY_FIELD         0.3574  <- AGGREGATE_BY_FK 0.4221  runner-up FILTER_WITH_PAGINATION  margin 0.3495  decided
expenses  FILTER_BY_FIELD         0.2962  <- AGGREGATE_BY_FK 0.4403  runner-up FILTER_WITH_PAGINATION  margin 0.2818  decided
expenses  FILTER_WITH_PAGINATION  0.3290  <- AGGREGATE_BY_FK 0.3386  runner-up FILTER_BY_FIELD         margin 0.1613  decided
expenses  FILTER_BY_FIELD         0.0699  <- AGGREGATE_BY_FK 0.2619  runner-up FILTER_WITH_PAGINATION  margin 0.0486  undecided
```

Three of the four are *decided* — the correction was not a close call — and the fourth is
a genuine near-tie among viable answers, which is exactly what `undecided` is for. The
`claimed_confidence` column shows the correction was not free: the third entry's claim was
0.3386 against its corrected 0.3290.

**An empty viable set is not `None`, and the difference is the gap.** `_viable_patterns`
returns `None` for an unknown return type (an invariant carries no signature, so nothing
can be excluded) and an **empty set** when no candidate can be right — which is what makes
the item a gap. Collapsing the empty set into `None` made `_runner_up` fall back to the
unfiltered list and compare the entry against its own claim again.

**Fix 3 — a gap carries no margin at all.** Before this, six of the seven gaps had a large
*negative* margin:

```
library    NO_PATTERN_IN_DOMAIN    margin -0.3563   runner-up READ_ALL
expenses   NO_PATTERN_IN_DOMAIN    margin -0.4787   runner-up READ_ALL
```

A gap is not a choice between two answers; the negative figure was the entry's own sentinel
probability minus the claim's, which is not a margin. `margin` and `runner_up_pattern_id`
are now `None` for a gap, and the checker reports a gap that carries one as an **error**
rather than a signal — `invalid_value: 'NO_PATTERN_IN_DOMAIN' has no pattern but carries a
margin of -0.4787 — a gap is not a choice between two answers` — so the shape cannot come
back quietly.

**Fix 4 — the crash the test suite could not see.** The first real run of Fix 3 raised:

```
TypeError: '<' not supported between instances of 'NoneType' and 'float'
```

`_decide` compared `margin < NARROW_MARGIN` with a margin that can now be `None`. Every one
of the 162 tests passed, because every case in `DecideTests` had passed a *number*. A
`None` margin means there was nothing to compare against, so it is `decided` — not
undecided — and `_is_narrow_pattern_margin` says so. **This is the second time in this
document that running the thing found what the suite did not** (§9.22's `LOW_CONFIDENCE`
floor against a real document was the first), and it is why §9.22's acceptance line
includes a real run and not only a green suite.

**The domain threshold is now chosen from data, not borrowed.** §9.22 set
`DOMAIN_NARROW_MARGIN = 0.15` as "a starting point from the pattern stage, **not** a
measured value". Sorted, the domain margins on the corpus are:

```
0.0446  0.0834  0.0912  0.1338  0.1377  0.1395  0.1428  |  0.1897  0.2663  0.2876 ...
```

There is a real gap between `0.1428` and `0.1897`, and 0.15 sits inside it — so the
constant flags five items and separates them from a distinct higher population. Measured
rather than asserted, and the same figure for the pattern stage (`NARROW_MARGIN`) selects
18 items where 0.02 would select 11 and 0.30 would select 30.

**Measured on the seven-prompt corpus, after the fix:**

| | before | after |
|---|---|---|
| margins compared against the winner | 10 | **0** |
| corrected entries with a margin of exactly 0.0 | 10 | **0** |
| gaps carrying a margin | 6 (negative) | **0** |
| `narrow_margin` notes | 23 | 18 (5 domain, 13 pattern) |
| `low_confidence` notes | 1 | 2 |

Decisions: **129 decided, 18 undecided (5 domain / 13 pattern), 7 undefined** out of 154
matches. `0 errors, 0 warnings, 39 notes`, and the checker's new gap guard reports nothing
on the corrected output while an injected negative margin is reported as an error.

`low_confidence` rising from 1 to 2 is Fix 1 telling the truth: a corrected entry now
reports its own 0.0699 instead of its claim's 0.2619, so it crosses the 0.2 floor it had
been hiding behind. One entry, two true facts — `narrow_margin` and `low_confidence` — is
not the double-reporting Fix 1 removed, which was two rules for one story.

**A process note, because it cost a restore.** `writer.write_documents` calls
`clear_documents` first, which is right for a full run and destructive for a partial one:
re-writing step F alone against an existing output directory deleted the other seven
documents, and the checker immediately said so (`35 missing_document, 126
unknown_reference` — the second from `service_contracts` being gone). Re-running one step
in place requires saving the step's file, restoring the directory, and putting the file
back. `backup/out_before_margin_fix/` holds the pre-fix output this section is measured
against.

The acceptance line for the whole of §9.22–9.23: **`0 errors, 0 warnings`** still holds,
every match carries a `decision` from the three known values, a margin is recorded only
where two answers existed, and no figure in `pattern_matches` is computed against something
other than what it claims to describe.
### 9.24 Two facts the requirements stated and no document could hold

#### The gap

Two things the requirements say plainly had no place in the schema, so both were
lost, and in both cases the loss was invisible: nothing was missing from a
document, because no document had a field for it.

1. **What the program accepts on its command line.** `components.facade` held a
   `type` and a `technology` and nothing else. `technology` is a *claim about a
   library* — `argparse`, `click`, `pyimgui` — and a claim is only meaningful
   against what it is for. The hello-world prompt asks for "a CLI entry point
   that prints Hello, World!", which takes no arguments at all, and the prompt's
   own instruction produced the defect directly:

       "if the requirements name none, use cli with technology argparse"

   Four words, and the run obeyed them: `technology: argparse` for a script with
   nothing to parse. No rule could catch it, because the document never said what
   the parser was for. A parser with no arguments is not a formatting mistake; it
   is an unfalsifiable claim, and it generated an unnecessary `argparse` import
   and an `ArgumentParser` in a Hello-World program.

2. **The exception types the requirements name.** inventory's requirements name
   `CategoryNotFoundError` and `ProductNotFoundError` outright. cli_tool's
   describe two failures without naming them — "error handling for missing files
   and malformed CSV". Neither could be recorded: the schema had no document for
   exception types, so every named type was dropped silently and every described
   failure had to be re-invented by whatever step needed it, or not at all.
   `service_contracts` could not even say that a method raises anything.

Both are the same shape of defect as §9.22's: a requirement the pipeline cannot
represent is a requirement the pipeline discards, and discarding it looks exactly
like a clean run.

#### What was built

**The CLI surface** (`facade.invocation`). A third field on the facade records
what the program *accepts*: `positional` (name, type, required), `options`
(name, an optional short form, type, required, default) and `commands` (name,
options, `subcommands` — nesting one level, which is what the prompts describe).
`null` is the answer for a program that takes no arguments, and it is a bare JSON
null rather than an object holding three empty lists, so "there is no CLI" cannot
be confused with "there is a CLI with nothing in it".

The grammar gained `option-name ::= "\"" "-" [a-zA-Z0-9] [a-zA-Z0-9-]* "\""`,
because `identifier` cannot express `--output` — and a single leading dash that
must be followed by an alphanumeric keeps `"-"`, `"--"` and `"- "`
unrepresentable, so an option always has a name of its own.

**The error registry** (`errors.json`, step E′). A new document, run between step
B and step C:

    {"errors": [{"name": "CategoryNotFoundError",
                 "base": "LookupError",
                 "description": "Raised when a category ... does not exist."}]}

`name` is free (an identifier) because the requirements name some types and only
describe others; `base` is **closed** by the grammar to eight Python builtins
(`LookupError`, `ValueError`, `KeyError`, `RuntimeError`, `PermissionError`,
`OSError`, `TypeError`, `Exception`), so the generated class derives from a real
base and not from prose. The list is capped at 20 and may be empty: a program
whose requirements describe no failure has no errors.

`method_rules(extra=())` was parameterised so that a **contract** method carries
`raises` while a repository method does not — the service declares the behaviour,
so the service is where the failure it may produce is named. `raises` is capped at
6 names per method, and the registry's names travel into step E's prompt through
`vocabulary.errors`, `Vocabulary.error_names` and `Vocabulary.errors_block`, so
the contracts are handed the authoritative list rather than left to invent one.

#### The rules, and what they found on real output

Five rules exist because these two fields make five statements falsifiable:

| rule | severity | what it says | found on |
|---|---|---|---|
| `inconsistent_facade` | warning | a parser technology with `invocation: null`, or arguments with technology `none` | — (the defect it replaced, `argparse` on hello-world, was in the *old* output) |
| `unsupported_value` | warning | an error `base` outside the eight builtins | — |
| `unused_error` | note | a declared error type no method raises | 10 across the corpus |
| `unknown_reference` | warning | a method's `raises` names an unregistered error | 60, once |
| `contradictory_raise` | warning | a method that creates a record claims it can fail to find one | 4 (inventory ×2, expenses ×2) |

`unknown_reference` and `unsupported_value` already existed; the registry gave
them something to resolve against. `unused_error` is gated on the program having
services at all, because cli_tool's errors belong to its CLI layer and a
services-less program would otherwise have every one of its errors called unused —
true, and useless.

`contradictory_raise` reads the names, like `methods._missing_arguments_reason`
beside it: the method's name states what it brings into existence and the error's
name states what was not found, and they have to **agree** for the pair to
contradict itself. The first draft fired on any `create`/`add` prefix, which was
wrong — `add_stock(product_id, ...)` must find the product it adds stock to, so its
`ProductNotFoundError` is correct. Comparing the nouns (`add_stock` → *stock*
against *product*) leaves that alone and still catches `add_product`.

Two defects were found **by running the new checks over real output**, and both
were defects in the change itself:

- **A missing registry was reported twice.** `check_errors(None)` said "errors
  should be a list" on top of the loader's `missing_document`, telling the reader
  the registry held the wrong kind of value when in fact there was no registry.
  Caught on the first checker run after `errors.json` became a core document:
  7 `missing_document` errors, and 7 spurious `invalid_value` errors beside them.
- **`none` had become a placeholder.** Making `"none"` the correct technology for
  a program with no arguments turned hello-world's document into a warning,
  because `is_placeholder` had always counted the string as unfilled. `none` is a
  *value* for a facade's technology now, and the placeholder test excludes it —
  the contradiction it might hide is `inconsistent_facade`'s job, so nothing is
  lost.

#### What the corpus said

*(These bullets are the **first** batch after the change, before the prompt fixes were in
place. What the re-run measured — including one fix that took and one that did not — is at the
end of this section.)*

- **hello**: `technology: "none"`, `invocation: null`, `errors: []`. The
  `argparse`-on-Hello-World defect is gone at the source, and the empty registry
  is the correct answer.
- **cli_tool**: `FileNotFoundError (OSError)` and `MalformedCSVError
  (ValueError)` — exactly its two described failures, named and based; its
  `invocation` names an `input_file` positional and an optional `-output`/`-o`.
  `argparse` is now justified by a surface instead of asserted.
- **inventory**: nine errors, including the two the requirements name outright.
  `read_one_category` raises `CategoryNotFoundError`, `restock` raises
  `ProductNotFoundError` + `InvalidStockQuantityError`. The §8 gap — named
  exception types vanishing — is closed.
- **60**: sixteen errors, and one genuine cross-document inconsistency:
  `InvoiceService.read_invoice_by_id` raised `InvoiceNotFoundError`, which the
  registry did not declare. The registry was at fault, not the contract: it held
  a not-found error for orders, customers and products but none for invoices.
- **gui**: five errors mapped to its own invariants (negative stock, pricing,
  duplicate wine name, capacity, assignment), and `facade: gui/pyimgui` with
  `invocation: null` — correctly *not* flagged, since `pyimgui` is not a parser.

#### The fixes, and where they belong

Three of the defects the checks found are generation mistakes with a source, so
the source was fixed rather than only the output:

- `COMPONENTS_SYSTEM` was rewritten from a **verb list** ("computes, prints,
  parses or transforms") to a **criterion** over the surface, and technology now
  follows the surface rather than the reverse: no arguments → `none`, positionals
  only → `sys.argv`, any option → `argparse`, nested commands → `click`.
- `CONTRACTS_SYSTEM` now states that a create cannot fail to find the record it is
  creating, and that a long option carries two dashes.
- `ERRORS_SYSTEM` now asks for a not-found error **per entity that is looked up**,
  which is the gap 60 exposed.

#### Acceptance

`errors.json` is a core document, so a run without it is a `missing_document`
error rather than a silent omission. All seven prompts run to `exit=0` and write
it. The suite is at **206 tests**, of which `tests/test_facade_and_errors.py`
pins the CLI surface, the registry, the `raises` reference, and — deliberately —
the cases each rule stays quiet on (`add_stock`, a read raising not-found, an
absent registry).
#### What the re-run then measured, and the one fix that did not take

All seven prompts were re-run with the three prompt corrections in place, and the whole batch
finished `exit=0`. The final verdict is **`0 error(s), 0 warning(s), 44 note(s)`** (from
`0 error(s), 5 warning(s), 41 note(s)` before the corrections).

**The registry grew, which is the point of it.** Comparing the two batches document by
document — the check §9.6 established, that a clean tally means nothing if a document emptied:

| prompt | intentions | invariants | data_models | **errors** | methods | adapters | patterns |
|---|---|---|---|---|---|---|---|
| hello | 3 → 3 | 0 → 0 | 0 → 0 | 0 → 0 | 0 → 0 | 0 → 0 | 0 → 0 |
| cli_tool | 6 → 6 | 0 → 0 | 0 → 0 | 2 → 2 | 0 → 0 | 0 → 0 | 0 → 0 |
| inventory | 5 → 5 | 12 → 12 | 2 → 2 | **9 → 10** | 22 → 21 | 13 → 13 | 24 → 23 |
| gui | 11 → 11 | 17 → 17 | 2 → 2 | **5 → 8** | 16 → 16 | 16 → 16 | 20 → 20 |
| expenses | 6 → 6 | 16 → 16 | 3 → 3 | **3 → 10** | 42 → 37 | 20 → 18 | 44 → 39 |
| 60 | 10 → 10 | 28 → 28 | 6 → 6 | 16 → 16 | 21 → 24 | 19 → 23 | 34 → 37 |
| library | 10 → 10 | 14 → 14 | 4 → 4 | **11 → 12** | 36 → 36 | 18 → 16 | 42 → 42 |

The documents the change did not touch — intentions, invariants, data_models — are *identical*
on all seven prompts, so the variation in the other columns is generation spread at
`temperature=0.1`, not drift. The registry grew on **five of seven** prompts, most sharply on
expenses (3 → 10), because it is the only column the new instruction can affect.

**Two of the three corrections worked, and they were measured, not assumed.**

1. **A create cannot raise a not-found error** — worked. The four `contradictory_raise` warnings
   (inventory ×2, expenses ×2) are gone, and the surviving `raises` are the right ones:
   expenses' `create_expense` raises `['CategoryNotFoundError']` — its foreign key must exist,
   which is a real reason a create can fail — while `create_category` and `create_budget` raise
   `[]`, and `add_expense` raises `['CategoryNotFoundError', 'BudgetExceededException']`.
2. **A not-found error per entity that is looked up** — worked, and it closed the
   `unknown_reference`. Prompt 60's registry now declares `InvoiceNotFoundError (LookupError)`,
   so `InvoiceService.read_invoice_by_id` resolves. This was the one finding that needed the
   *registry* fixed rather than the contract: the contract was right to raise it.
3. **A long option carries two dashes** — did **not** take. cli_tool still writes
   `{"name": "-output", "short": "-o"}`, exactly as before the sentence was added.

**Why the third one is left alone rather than enforced.** `-output` is valid `argparse` (a
single-dash multi-character option), and cli_tool's requirements never spell the flag — they say
"an optional output file path". Making `--` mandatory in the grammar would fix the style and
would also make a requirement that genuinely names a single-dash option *unrepresentable*, which
is a worse trade. It is recorded as an unenforced convention, alongside the mixed error-name
suffixes (expenses' registry has nine `*Error` and one `*Exception`): both are naming style that
the checker constrains for shape but deliberately does not judge for taste.

**The limit this exposed, stated plainly.** The create/not-found rule is checkable because two
names carry the evidence, but it is **not enforceable in the grammar**: GBNF cannot condition
`raises`'s alternatives on the textual prefix of the method's own `name`, since that is a
property of a string rather than of the parse state. So this defect class is detectable and not
preventable — the same expressiveness limit §9.7 hit for repeated method names, in a different
guise. The check is the guardrail, and it is why the prompt correction was worth attempting but
not worth relying on: the warning would have caught the mistake whether or not the model
complied.

**`unused_error` is now the largest note, at 17.** That is the honest shape of the new
information: a registry declares the error types a program needs — including the ones its CLI or
persistence layer raises, which no *contract* method raises — and the note says so without
counting it as a defect. It fires only when a program has services at all, so cli_tool's two
errors are not reported merely for having no service layer to raise them.
### 9.25 The CLI surface: verbs recorded as flags, a loop with no stopping rule, and the four rules that name it

`components.facade.invocation` is the one place the schema asks for a *shape* rather than a
name: which positionals, options and commands a program accepts. Nothing checked it until this
section, and the first run of the field produced four distinct defects across three prompts.

**The shape was inverted, and inside out.** inventory's requirements name the calls —
`product add --sku`, `category update --id` — so the noun is the command and the verb is the
subcommand. The document recorded it the other way round:

```
product  options: -add (dict), -list (dict), -update (dict), -delete (dict), -restock (dict), -report (dict)
         subcommands: low, value
category options: -add (dict), -list (dict), -update (dict), -delete (dict)
```

Two faults in one object. The **verbs are options**, each of type `dict` — a mapping is not a
command-line value at all, so `-add` is a subcommand written as a flag. And the only
subcommands are `low` and `value`, which are not commands: they are the two halves of the
method name `low_stock_value`, split on the underscore.

**`cli-option.type` was free text, and that is what produced a generation that could not stop.**
With the noun/verb sentence added to the prompt, inventory grew the correct subcommands
(`add, list, update, delete, restock, report`) — and kept every verb as an option beside them,
while its options list ran away:

```
-add (none), -list (none), -update (none), -delete (none), -restock (none), -report (none),
-low-stock (none), -value (none), -add (dict), -add (positional), -add (dict), -add (dict),
-add (dict), -add (dict), -add (dict), -add (str), -add (str), -add (int), -add (int)
```

Twenty-one entries, eleven of them `-add`, the type changing on each pass. The run took
**22 minutes** against 341 s for the same prompt once the type was closed. The loop had no
stopping rule: every value was admissible, so the model could always write one more, and only
`MAX_CLI_OPTIONS` eventually cut it.

**The fix is a closed set, in the grammar.** `cli-option.type` and `cli-arg.type` were `string`;
they are now `option-type`:

```
option-type ::= "\"str\"" | "\"int\"" | "\"float\"" | "\"bool\"" | "\"list\""
```

An option carries one value, and the value has one of a few shapes, so the field is closed the
way `generic-type` closes a field's type (§9.8's `identifier` is the same principle applied to
names). `dict`, `none` and `positional` are no longer writable **as types**, and with nothing
left to vary the loop loses its fuel: the same prompt now finishes in 341 s with a bounded,
typed surface.

**The repeat itself is removed deterministically.** `kernel/extraction/dedupe.py` already
dropped repeated method and parameter names; it now covers the surface too, at all three levels
— a command, a subcommand and an option list each keep the first occurrence of a name and drop
later ones. library's surface had listed `member` twice, once with `[add, list]` and once with
`[history]`, which collide in any CLI framework:

```
before:  book, member[add,list], borrow, return, overdue, member[history]
after:   book, author[add,list], member[add,list], borrow[book], return[book], overdue
```

**What the checker gained — four rules, each naming a contradiction rather than a style.**

| rule | fires on | severity |
|---|---|---|
| `_check_options_are_not_subcommands` | a word that is both an option of a command and one of its subcommands | `invalid_value` |
| `_check_cli_args` | positional arguments are now checked exactly like options: name, type, repeats | `invalid_value`, `unsupported_value`, `duplicate_entry` |
| `_is_option_type` | a type outside `option-type` — the document did not come from this grammar | `unsupported_value` |
| existing repeated-name check | a command, subcommand or option listed twice | `duplicate_entry` |

The first is the rule that finds the shape error that survives the prompt fix. `tool product
add --sku` and `tool product -add` cannot both be how a product is added, so the document
contradicts itself and no requirements are needed to see it: the two lists are compared.

**Measured, on the seven prompts re-run under the frozen code.**

| | before this work | after |
|---|---|---|
| option types outside the set | 10 (`dict`) | **0** — unrepresentable |
| option-vs-subcommand collisions | 0 found | **6** (inventory 1, 60 5) |
| repeated command/subcommand names | 1 (library `member`) | **0** — removed |
| inventory wall clock | 22 min (loop) | **341 s** |
| grand total | 0 errors, 3 warnings, 44 notes | **0 errors, 6 warnings, 43 notes** |

The warning count rises and every one is a real defect that was previously invisible: six
surfaces use one word as both a flag and a command. That is the honest direction for a count to
move when a rule is added, and it is stated here rather than hidden behind the number.

**The boundary — what these rules still cannot see.** expenses records `category` with **no
subcommands**, and `-add`, `-list`, `-update`, `-delete` among its options, beside `-id`, `-name`
and `-budget`. That is the original defect, unchanged, and it is *not* reported, because nothing
in the document contradicts itself: `-add` and `-id` are the same kind of thing to a checker
that has no list of verbs. Deciding `-add` is a verb and `-id` is a field needs a lexical
judgement no field of this schema supplies, and inventing one would report every program whose
options include a word that is also a verb. 60 has the same shape in five places but is caught
only where a subcommand happens to share the word. **The rule catches the contradiction, not the
modelling mistake**, and expenses shows where the line falls.

cli_tool carries a smaller, deliberate silence: its long option is written `-output` with a
single dash (`argparse` accepts exactly that, and the prompt asks for it), and the grammar
permits one or two dashes because a short option is spelled the same way. So nothing enforces
the convention, and this section does not add a rule for it — `-output` is what the requirements
describe.
### 9.26 Four checks only prose can make, and two claims I had to withdraw

§9.24 and §9.25 read a document against another document. This one is about the
defects those cannot reach, and it began with a question — *is this ready to
generate code from?* — that the checker's own answer (`0 errors, 6 warnings`)
could not answer, because zero errors means the documents agree with **each
other**, and says nothing about whether they agree with the requirements.

Ten candidate defects were listed before anything was changed. Two of them turned
out not to exist, and both were mine:

- **"60 names its entities as table names"** — false. `out/60/data_models.json`
  holds `Customer, Category, Product, Order, OrderItem, Invoice`: singular
  PascalCase, and no entity name equals its own table name in any of the five
  domain prompts. The claim came from an earlier run and I repeated it from
  `BLIND_SPOTS.md` §7 without re-reading the document it described. Corrected in
  §7 below, and the rule I was about to write for it is not written.
- **"`add_category` returns `None` while `add_product` returns `Product`"** —
  false. The final documents return the entity from every create
  (`create_category → Category`, `create_product → Product`), a list from every
  `read_all_*`, one entity from every `read_by_id`, and an aggregate from `get_*`.
  My example was from an older run too. The lesson is recorded rather than
  smoothed over: a defect list written from memory of a previous batch is not
  evidence, and both of these cost nothing because they were checked before a
  rule was built on them.

That leaves eight real ones, and the shape of the work was the same for each:
**a rule first, because a rule is what makes the defect countable and testable**,
then the fix — and only where the fix belongs.

#### The five rules

| rule | severity | what only it can see | measured |
|---|---|---|---|
| `misplaced_field` | warning | an adapter field sent to a parameter that is not its own | **2** (expenses) |
| `mismatched_transform` | warning | a transform applied to a field whose name contradicts it | **15** |
| `missing_command` | warning | a command the requirements name and the surface lacks | **8** (expenses 7, library 1) |
| `unreachable_error` | warning | a not-found error nothing raises while its own reader exists | **2** |
| `duplicate_error_subject` | warning | two error types naming one missing record | **3** |

`misplaced_field` needs no judgement: when the target method declares a parameter
with the input field's own name, the value belongs there, and mapping it elsewhere
silently drops it. expenses' `add_expense` sends `category_id` into the `expense`
object while the method declares a `category_id` of its own, and `update_budget`
sends `month` into `budget` while a `month` parameter exists. The rule is exact
and fires twice across the corpus.

`mismatched_transform` is the one name-based rule here, and it is deliberately
narrow — the same shape as `missing_parameters`, which the project already
accepts. A transform says how a value's *representation* changes, and no document
records a field's representation, so the only evidence is the name. It therefore
judges only the three transforms that name a kind of value (`DECIMAL_TO_CENTS`,
`CSV_LIST`, `ISO_DATE`) and stays silent on `DIRECT`, `LOOKUP_ID` and
`ENUM_LOOKUP`. What it found is not marginal: `add_category` read `name` as a
comma-separated list and converted `description` to cents, `add_book` converted
`copies` to cents, gui read `stock_quantity` as a list.

`missing_command` is the first rule in the checker that reads the **requirements
prose**, and the plumbing is what makes it possible. `extract_archi.py` now writes
the requirements it was given beside its documents as `requirements.txt`, and
`loader.load_requirements` reads them back. A run from before this change has no
such file, and its absence produces no finding — the check simply does not run,
rather than reporting every older directory for a file it could not have written.
The comparison reads the one notation every prompt uses (`<noun> <verb> --flag`)
and reports only when the noun is a command the surface already declares; when the
noun is not a command the pair is skipped, because `library borrow book` puts the
*program* name before the verb and a rule that could not tell a tool name from a
command would fire on correct output. That decision is what makes its eight
findings trustworthy: seven are expenses (`category` and `budget` recorded **no
subcommands at all** while the requirements name three each, and `expense` had no
`add`), and one is library's `member history`.

`unreachable_error` and `duplicate_error_subject` sharpen `unused_error`, which
is only a note because the checker cannot tell a failure raised outside the
service layer from one the service forgot. For these two it can tell. If a method
that reads the record by its key is declared and nothing raises that record's
not-found error, the lookup cannot report what the registry says it can
(inventory's `MissingProductError`, expenses' `MissingCategoryError`). And if two
declared errors say the same thing is missing, the registry holds two exception
classes for one condition — `CategoryNotFoundError` beside `MissingCategoryError`
in inventory and expenses, `ProductNotFoundError` beside `MissingProductError` in
inventory. The second rule is exact because it compares what each name *says is
absent* rather than how it is spelled.

#### The two prompt fixes

Both defects above are extraction defects as much as checking gaps, so both
prompts changed, and both changes name the mistake in the words the model got
wrong:

- `COMPONENTS_SYSTEM` already said "write a verb as a subcommand and never as an
  option", and two prompts still emitted the verbs as options beside correct
  subcommands. The sentence was too abstract. It now states the rule the model
  actually needs: when the requirements write `<thing> <verb>`, the thing becomes
  a command and the verb one of its subcommands; **a command with subcommands
  carries no options of its own except the global ones**, because the flags a
  verb needs belong to that verb's subcommand; and the same word must never
  appear both in a command's `options` and in its `subcommands`.
- `ADAPTERS_SYSTEM` now says what `misplaced_field` checks and what
  `mismatched_transform` checks: a field whose name is also a parameter's name
  goes to *that* parameter, and the transform must match the field's own kind
  (`DECIMAL_TO_CENTS` for a money amount, never a count or a boolean; `CSV_LIST`
  for several comma-separated values, never a single name or a flag).

The pattern is the same one §9.24 found: a rule is not enough on its own, and a
prompt sentence is not enough on its own. The rule makes the defect countable;
the sentence is what stops the extractor producing it; and neither is trusted
until the other confirms it.

#### What is still not checked

Stated because the whole point of this section is to keep the boundary visible:

- **Adapter coverage.** Every surviving adapter resolves to a real service
  method, but nothing measures how many of the requirements' *actions* an adapter
  list ought to cover. inventory 18 → 11, 60 27 → 13, library 31 → 19, and the
  checker cannot say whether that is a loss.
- **A verb recorded only as an option when no subcommand shares the word.**
  expenses' `category` had `-add, -list, -update, -delete` and no subcommands at
  all, so `missing_command` catches it — but only because the requirements name
  those verbs. Without the requirements, nothing distinguishes `-add` from `-id`,
  and a verb vocabulary the checker does not own is the only thing that would.
- **A returned value's meaning.** `get_monthly_report → dict` and
  `get_yearly_summary → dict` are consistent with each other and with nothing
  else; no rule says what a report is, and the repair pass is where that belongs.
- **`product.category_id must reference an existing category`** remains tagged
  `rule` when the prompt calls it `schema`, recorded in §9.16 and left alone
  rather than chased with another full re-run.
### 9.27 The command shape that cannot hold a verb twice — and the sentence that did not take

§9.25 recorded the defect and gave two fixes for it: five rules that *name* it, and a prompt
sentence that asks the model not to produce it. The sentence did not take. Three clean runs
after it, inventory still wrote a command whose `options` repeated its own `subcommands`:

```
cmd product   opts ['-add','-list','-update','-delete','-restock','-report']
              subs ['add','list','update','delete','restock','report']
```

and 60 repeated `-search` and `-update` the same way on `category`, `customer`, `invoice` and
`order`. On the worst run the model did not just repeat each verb once: it emitted twenty-one
options all named `-add`, the type changing on every one. That is the same class of non-stopping
generation §9.25 described, and it is why a prompt sentence is not a guarantee — it is a
tendency, and a tendency is not something a checker can rest on.

**The closure.** The facade grammar no longer has a shape in which one word can be both. A
command is now an alternation of two rules that disagree in *both* the fields that could hold a
verb:

```
cli-command   ::= ( cli-command-nested | cli-command-flat )
cli-command-nested ::= { name, options: cli-global-option-list, subcommands: cli-subcommand-list-nonempty }
cli-command-flat   ::= { name, options: cli-option-list,        subcommands: "[" ws "]" }
global-option-name ::= "-help" | "--help" | "-version" | "--version"
```

A command that declares subcommands carries only the four global flags, because the flags a
*verb* needs belong to that verb's own subcommand; a command with no subcommands carries the
options it needs. There is no branch that admits both an arbitrary option and a subcommand, so
`-add` beside subcommand `add` is not discouraged — it is unrepresentable. This is the same
principle as the `option-type` enum of §9.25 and the `identifier` rule of §9.8: where a prompt
sentence has been tried and missed twice, close the shape instead of asking again.

`GLOBAL_OPTION_NAME_RULE` lives in `grammar.py` beside `OPTION_TYPE_RULE`; `facade_rules()`
returns it and both the open grammar and the closed builder use the same function, so the two
paths cannot drift. Four unit tests pin the property structurally — the nested branch references
`cli-global-option-list` and *not* `cli-option-list`, the flat branch does the reverse and forces
an empty `subcommands`, `cli-command` has exactly those two alternatives, and `global-option-name`
admits only the four flags. They cannot run a model; they pin the decision, which is what a
structural test can do. The suite is 244 tests.

**Measured outcome.** One clean batch on frozen code, all seven prompts `exit=0`:

| metric | this run | the run §9.25 measured |
|---|---|---|
| errors | 0 | 0 |
| warnings | 10 | 6 |
| notes | 57 | 43 |
| `invalid_value` (option repeats a subcommand) | **0** | 6 |
| `duplicate_entry` | **0** | 0 |

inventory's surface is now correct: `product` and `category` carry only `--help`/`--version`, and
`add, list, update, delete, restock, report` are subcommands only. The collision class is empty.

**What the ten warnings are, stated plainly so the drop in one class is not read as a clean run
in all of them.** They are not `invalid_value`; they are five other content defects this
generation produced:

- `contradictory_raise` (3) — inventory's `create_category`, `create_product` and `add_product`
  raise a not-found error although they create the record. The §9.24 prompt sentence did not
  take on this run either; it is a tendency, and generation is stochastic.
- `duplicate_error_subject` (3) + `unreachable_error` (2) — inventory declared **two** names for
  one missing record (`CategoryNotFoundError` beside `MissingCategoryError`, `ProductNotFoundError`
  beside `MissingProductError`) and raised only one of each pair, leaving the other unreachable.
  expenses had the same shape on its category error.
- `mismatched_transform` (1) — library's `add_book.copies` converted with `DECIMAL_TO_CENTS`.
- `missing_command` (1) — library's requirements name `book search`, which the surface lacks.

All five are the checker doing its job on per-run content; none is a `service_contracts` or
`components` output caused by this change (the facade grammar cannot reach the errors or adapter
steps). They are recorded rather than chased, because each is the class §9.25 and §9.24 already
document: the rules that see them exist, and closing them in the grammar is not possible —
`contradictory_raise` needs to know which verbs create, `duplicate_error_subject` needs to know
two names mean one thing, and neither is a regular property of the text.

**The batch got slower, and the reason is honest.** inventory 341 → 513 s, expenses 434 → 673 s,
60 442 → 1143 s. The two-branch command alternation gives the model one more decision per
command, and a slower decode is the price of a shape that cannot be wrong. It is recorded because
the change trades a few minutes of wall clock for a class of defect that can no longer be
produced.

**Residuals confirmed unchanged, not introduced here.** The final documents still carry three
bare `dict` returns on expenses' report methods (`get_monthly_report`, `get_yearly_summary`,
`get_category_spending`) and `None` on library's four `delete_*` methods in both contracts and
ports. The bare `dict` count is byte-identical to the pre-change backup, and `return_types.py`
deliberately targets only the `dict[str, object]` spelling: a report aggregate names no single
entity, so repairing it to an entity would be a wrong answer, and `None` on a delete is correct
Python. They are pre-existing and out of scope for this change; they are named here so the next
reader does not rediscover them as a regression.
## 9.28 Repair the three contradictions instead of accepting them (`kernel/extraction/repairs.py`)

§9.27 left five findings standing on the field batch and argued each was a class the grammar
cannot close: knowing which verbs create, or that two spellings name one thing, is not a regular
property of the text. That argument is right about the *grammar* and wrong about the *pipeline*.
A GBNF rule constrains what the model may emit; it is not the only point at which the document
can be made consistent. The three findings that were pure contradictions inside one document —
two names for one missing record, a create that fails to find what it creates, a name that lies
about its transform — are decidable by a total function of the documents already generated, so
they belong in a deterministic pass over the finished documents, not in the grammar and not in
the prompt.

**This is not the repair pass §"consistency by construction" defers.** That deferral is about
rewriting a *signature* into correctness, which needs the body the document does not carry. Each
repair here only **removes or redirects a value the same document already contradicts**:

1. **Duplicate error subject** — two declared error names differing only in one of the
   not-found spellings (`Missing`/`NotFoundError`) name one missing record. The pair is collapsed
   to one name: the one a method actually `raise`s (so no reference is orphaned), else the first
   declared. A `raise` of the dropped name is redirected to the kept one. Fired on inventory
   (`MissingCategoryError`->`CategoryNotFoundError`, `MissingProductError`->`ProductNotFoundError`)
   and expenses (`MissingCategoryError`->`CategoryNotFoundError`).
2. **Contradictory raise** — a method that **creates** an entity as its object (`create_product`,
   `add_product`) cannot fail to *find* that same entity, so the not-found `raise` is dropped. The
   created-noun comparison is what keeps `add_stock`'s `ProductNotFoundError`: `add_stock` finds
   the product it must add stock *to*, whereas `add_product` creates it. Fired three times on
   inventory (`CategoryRepository.create_category`, `ProductRepository.create_product`,
   `InventoryService.add_product`).
3. **Mismatched transform** — an adapter field whose name describes no such value
   (`add_book.copies` with `DECIMAL_TO_CENTS`) is set to `DIRECT`. Fired once, library.

**The predicates are shared with the checker.** `checks_errors.is_contradictory_raise`,
`_created_subject`, `_absent_subject` and `checks_adapters`' transform rule are imported by
`repairs.py`, so the pass that removes a finding and the rule that would report it can never
disagree. A repair that used its own copy of the predicate could silently diverge from the rule
and either leave a finding or delete a value no rule objected to; sharing one implementation
makes that impossible. `is_contradictory_raise` was factored out of the checker loop for exactly
this reason (`checks_errors.check_raises` now calls it).

**Measured outcome, one clean batch on frozen code.** All seven prompts `exit=0`; the full
checker run is **0 error(s), 1 warning(s), 55 note(s)**, down from the pre-repair field tally of
6 warnings / 43 notes. The repair log shows the three classes firing eight times. Notes are
`unused_error` 19, `narrow_margin` 13, `missing_pattern` 10, `corrected_claim` 3,
`low_confidence` 2, and the rest `empty_section`; the one remaining warning is library's
`missing_command` — the requirements name `book search`, which the surface lacks. No repair can
close it without the requirements text and a verb vocabulary the checker does not own, so it
stands, recorded.

**Nothing else moved.** `/tmp/content_volume.py backup/out_before_error_repair out` shows the
`errors` item count the only field that changed on any prompt (inventory 10->8, expenses 10->9);
`intentions`, `invariants`, `data_models`, `service_contracts` methods, `interaction_adapters` and
`pattern_matches` are byte-for-byte identical on all seven. A repair that had spilled into any
other document would show there.

**The residual generics are the repair's deliberate boundary, re-confirmed.** expenses still
returns bare `dict` on its three report methods and library still returns `None` on its four
`delete_*` methods in both contracts and ports — the same counts §9.27 recorded, unchanged by
this pass. `return_types.GENERIC_RETURNS` targets only the `dict[str, object]` spelling; a report
aggregate names no single entity, so rewriting it would be a wrong answer, and `None` on a delete
is correct Python. They are left and named, not repaired.

**Tests.** `tests/test_repairs.py` (new, 12 tests) pins each repair and, for each, the silence
that keeps it from over-reaching: one name per subject is untouched; `add_stock` keeps its raise;
a reader keeps its not-found; a money field keeps `DECIMAL_TO_CENTS`; a date field keeps
`ISO_DATE`; `DIRECT` is never touched. Suite 245 -> 256, `py_compile` clean.
## 9.29 Streaming removed from the generation call

The one LLM call per step (`runner.generate`) was streamed: it looped over the
per-token generator, appended each chunk's text and counted one token per chunk.
Nothing consumed the stream incrementally — a document is parsed only once the
step has finished — so the loop bought no behaviour and cost a response dict, a
`choices` lookup and a generator resume **per token**, on top of the GBNF sampler
that already runs per token. On a hot decode path that is measurable Python-side
overhead for zero benefit, which is why it was removed.

The call is now a single non-streaming `llm(...)` returning one dict. Two things
improve as a result:

- the completion-token count comes from `usage.completion_tokens` (exact) rather
  than the one-per-chunk tally the stream forced; a backend without a usage block
  falls back to re-tokenising the text, so the speed line stays meaningful;
- `finish_reason` is read from the single response as before, so truncation
  detection and the retry are unchanged.

**Cost of the change: one function and two test signatures.** `stream` was a
keyword parameter of `generate` that no caller passed — `pipeline._generate`
calls it with only `temperature` and `max_new_tokens`, and nothing else in the
tree imports it. The only other references were the two `fake_generate` doubles
in `tests/test_truncation_retry.py`, whose signatures carried `stream=True` to
mirror the real one; both were updated. No pipeline, grammar, prompt or checker
code was touched.

**Verified on both ends of the range.** The 256-test suite is green and
`py_compile` clean.

- **`hello`** (no domain, 5 steps) — non-streaming, Metal, wrote all eight
  documents, read `finish_reason` and `usage` correctly: `5 steps, 157 generated
  tokens in 10.1s`, checker `0 error(s), 0 warning(s), 4 note(s)`, with exact
  per-step counts (`[intentions] 58 tokens in 2.5s (23.6 tok/s)`).
- **`library`** (5 services, 44 classified items, the deepest grammar) —
  `8 steps, 9782 generated tokens in 344.7s`. Every document is populated —
  intentions 10, data_models 4 entities, errors 12, invariants 14, crud_services
  4, service_contracts 5 services / 38 methods, pattern_matches 44,
  interaction_adapters 17, persistence_ports 4 repos / 33 methods — and the
  checker reports `0 error(s), 1 warning(s), 7 note(s)`. The single warning is
  the pre-existing `missing_command` (`book search`), unchanged by this work, and
  the `add_book.copies` transform repair fired as expected. Deep-grammar steps
  decoded at ~27–30 tok/s (persistence 1911 tokens in 69.7s), no slower than the
  streamed runs of the same prompt.

No behavioural regression, a small per-token Python saving, and exact token
accounting as a bonus.
## 9.30 Two model loads: the classifier is now deferred

Asked why the run loads the model twice, and whether flash attention is really on.

**Flash attention is on, and forced.** `llama-cpp-python 0.3.36` takes `flash_attn` as
a plain `bool` (default `False`), so `FLASH_ATTENTION = True` is a hard on, not an
auto. Confirmed against llama.cpp's own log, not inferred from the code:

```
llama_context: flash_attn            = enabled
llama_graph_n_input_tensors: ... (FLASH_ATTN_EXT)   # 216 attention nodes, Qwen3
```

Both models load with it (`Ministral`: 216-node graph; `Qwen3-4B`: `enabled`). The
startup line now prints it — `flash_attn={FLASH_ATTENTION}` — because the previous
line named the device, context and thread count but not this, so the setting could
not be seen without turning on llama.cpp verbosity.

**The two loads.** `extract_archi.py` used to build two `Llama` instances on the same
GGUF at startup: `extractor` (`logits_all=False`) for every generation step, and
`classifier` (`logits_all=True`) for step F alone. Step F's `softmax_classify` reads
per-token `logprobs`, which needs the context to keep the logits at every position —
that is what `logits_all=True` buys, and it is the reason the two instances exist
rather than one (§5.1).

**The waste was that the count was unconditional.** For `hello` and `cli_tool`, step F
logs `nothing to classify` and returns before using the classifier at all — but the
second full model had already been loaded to discover that. A no-domain program paid
two model loads to do one model's work.

**The fix: load the classifier on first use.** `Pipeline` now takes a
`classifier_factory` and builds the model inside `_step_patterns`, only after
`classification_items` shows there is at least one item to classify
(`extract_archi.py` passes the factory; `tests/test_lazy_classifier.py` pins that no
items never invokes it, items invoke it exactly once, and a pre-built instance is
reused). Measured:

| prompt | model loads | classifier load |
|---|---|---|
| hello | **1** (was 2) | never |
| library | 2 | at step F, immediately before `44 item(s)` |

**No effect on output, measured.** `library` on the lazy path: `0 error(s), 1
warning(s), 7 note(s)`, **9782 generated tokens**, every document count identical to
the eager run (intentions 10, data_models 4, errors 12, invariants 14, crud_services
4, service_contracts 5 services / 38 methods, pattern_matches 44, adapters 17,
persistence_ports 4 repos / 33 methods). The lazy reload is invisible to the result.

**A timing anomaly to read correctly.** That same `library` run reported `803.3s`
against `344.7s` for the identical output, and the whole gap is one step:
`service_contracts` at **4.7 tok/s** (2634 tokens in 556.3s) where the earlier run did
the **same 2634 tokens in 96.0s** (27.4 tok/s). It is not this change, and the evidence
is threefold: the slow step runs *before* the classifier loads (`service_contracts` is
log line 60, the classifier load line 61), its sibling steps in the same run decoded at
28–30 tok/s, and it produced byte-count-identical output. It is host contention — the
editor's helpers were at ~100% on three processes plus 52% WindowServer during the
window. The earlier `FIX_PLAN` note that editor load costs about a third of throughput
understates what a fully busy machine does to a single step; a clean timing needs an
idle host.
## 9.31 Grammar is mandatory — measured, not asserted

Asked whether the GBNF mask could be switched off, to see how far the raw model
could be trusted. A `--no-grammar` flag was added for one batch and then **removed
again** once the answer was in: the mask is not a vocabulary guard on top of
good JSON, it is what makes the output machine-readable at all. It is required,
and there is deliberately no switch to turn it off.

**What the raw model does.** Captured directly, one step at a time, with no mask:

- **It fences its JSON.** Every response came back as ```` ```json … ``` ````, so
  `json.loads` on the whole text fails before anything else is even considered.
- **It appends prose and code after the object.** Step B's reply was the JSON
  document followed by "Here is a simple Python script…" and a complete
  `def main()` — a second artefact the pipeline has no schema for.
- **It renames the document's own keys.** Step A's entries came back as
  `{"name": …, "description": …}`; the contract, and therefore the checker, wants
  `text`. The schema itself is carried by the grammar — with it off, the model
  answers the *idea* of the step rather than the step's interface.
- **It loses whole steps.** hello's `components.json` failed to parse on both
  attempts and was never written; every downstream step that needed it degraded.

**Measured, same prompts, same model, same checker.** Only the two no-domain
prompts and inventory were run before the switch was pulled:

| prompt | errors (grammar) | errors (no grammar) | what the mask was preventing |
|---|---|---|---|
| hello | 0 | 2 | `invalid_value` (renamed keys) + a missing `components.json` |
| cli_tool | 0 | 2 | same two classes |
| inventory | 0 (6 warnings) | 3 | schema drift and lost steps again |

Every step in the unconstrained runs needed a fence-and-prose recovery to parse
at all — i.e. every step failed the strict parse the grammar path treats as the
baseline. That is the point: with the mask on, "the output is JSON with these
keys" holds by construction; with it off, it does not hold even for the simplest
prompt. The raw model's *content* was often reasonable — hello's intentions were
sensible prose — but reasonableness is not parseability, and the pipeline runs on
the latter.

**Consequences for the code.** The experiment's machinery was reverted: no
`--no-grammar` flag, no `use_grammar` plumbing through `Pipeline` or
`runner.generate`, and no lenient parse path in `_parse_document`. A lenient path
was tried during the experiment (to forgive the fence and judge content rather
than formatting) and is exactly the wrong direction to keep: it would paper over,
in the loader, a failure the grammar prevents in the model. `_parse_document`
stays strict, and `runner.generate`'s docstring records why.

The conclusion also retires the reading that the grammar is "one of" several
correctness mechanisms. It is the load-bearing one: the closed vocabularies, the
bounded whitespace, the identifier rule and the schema itself are all only ever
enforced through the mask, and without it the documents do not survive the first
`json.loads`.
## 9.32 What is left, assessed against the generator's needs

The goal is not a clean tally for its own sake: these documents feed a code
generator, so a finding matters only if it makes the JSON describe the program
inaccurately. Assessed on the frozen baseline (`out/`, the seven prompts):
**0 errors, 1 warning, 55 notes.** Read through that lens, the 55 notes are four
groups, of which two are already excluded by decision and two are real.

**Excluded by decision — the classifier's own coverage, not extraction bugs.**

- **10 `missing_pattern`** — the classifier reporting that no catalogue pattern
  fits (a read-by-unique-field, an export, a compound service op). The generator
  will cover these by LLM generation rather than by a catalogue entry, so the
  gap is expected and no pattern is added (user decision, this session).
- **13 `narrow_margin` + 2 `low_confidence`** — the same classifier being
  undecided between two patterns. This is a reliability signal about a document
  whose downstream use is being replaced anyway; it is not a defect in the
  extraction.

**Real, and generator-visible.**

### A. The CLI surface under-enumerates the commands the requirements name

The one **warning** is library's `missing_command` (`book search`), but it is the
tip: the checked-in `out/library/components.json` declares **one** command form
(`book` → `add`) where the requirements list **eight** —
`book add|list|search`, `member add|list`, `member history`, `borrow`, `return`.

Two causes, both measured this session:

1. **Step D is nondeterministic at the tail.** Regenerating library's components
   with the identical prompt and grammar produced `book` **and** `member` with
   `book` → `add, member, list, borrow, return, overdue, history` (2472 tokens,
   `finish=stop`) — better than the committed run, but still wrong: `member`,
   `borrow` and `return` are nested under `book` instead of being top-level. The
   committed run drew a shorter, worse answer. So this is not one grammar byte
   to fix; it is a step that must be *checked* and *retried*, and a prompt that
   states the shape more forcefully.
2. **The dedupe hides the failure.** The committed run logged
   `[ok] step components: removed 19 exactly repeated name(s)` and the fresh run
   `removed = 21`. A large removal is the model looping on option blocks; the
   dedupe cleans it and writes a document that then *passes* the checker. The
   removal makes a looping generation look like a deliberate short surface. It
   should be visible, and it should be a reason to retry the step.

The checker catches only `book search` because its rule compares the
requirements against a small **verb list** (`checks_surface._commands_by_name`);
`list`, `update`, `delete`, `borrow`, `return` are not in it, so seven missing
command forms go unreported. This is §8's faithfulness limit in one concrete
place: the one rule that reads the requirements reads them shallowly.

### B. Declared error types that no method raises (19)

Measured per prompt (`declared / raised / unused`):

| prompt | declared | raised | unused |
|---|---|---|---|
| 60 | 16 | 10 | OrderItemNotFoundError, InvoiceNotFoundError, InsufficientStockError, InvalidPriceError, MalformedCSVError, PermissionDeniedError |
| cli_tool | 2 | 0 | FileNotFoundError, MalformedCSVError |
| expenses | 9 | 4 | InvalidBudgetMonthError, InvalidDateFormatError, InvalidPaymentMethodError, InvalidRecurringFlagError, InvalidBudgetAmountError |
| gui | 8 | 7 | InvalidWineTypeError |
| inventory | 8 | 4 | InvalidSkuError, InvalidPriceError, InvalidThresholdError, MalformedCSVError |
| library | 12 | 9 | MalformedCSVError, InvalidInputError, OverdueLoanFoundError |

They split into two causes that need different treatment:

- **Fabricated validation errors (10).** `InvalidBudgetAmountError`,
  `InvalidSkuError`, `InvalidWineTypeError` and the rest are validation rules
  turned into exception classes. `ERRORS_SYSTEM` already forbids exactly this
  ("do not turn a validation rule into an error class"), and `CONTRACTS_SYSTEM`
  already requires a method to name the failures it can produce in `raises`. So
  the model declares a class the program never uses: a generator emits a dead
  exception. This is a prompt-compliance gap, not a missing rule.
- **Grounded but unwired (9).** `MalformedCSVError` (×4), `FileNotFoundError`
  (cli_tool), the not-founds (`InvoiceNotFoundError`, `OrderItemNotFoundError`,
  `OverdueLoanFoundError`). The requirements do describe these failures and the
  registry records them, but no method's `raises` names them — so the generated
  program has an error the spec asks for and no code that raises it. Here the
  gap is in `service_contracts`, not in the registry.

`cli_tool` is the extreme: two errors declared, **zero** raised — nothing in its
contract raises the file/malformed-CSV failures the requirements name.

### C. Free-text content the checker never judges (§6, unchanged)

Not new, but still the largest "describes the prompt inaccurately" surface and
still unchecked:

- **`transform` vs the field it is applied to** — `DECIMAL_TO_CENTS` on
  `stock_qty`, a boolean or a count; `CSV_LIST` on a boolean.
- **`field_name` → `target_param` collapse** — expenses maps seven distinct
  fields onto the single parameter `expense`; only "is it *a* parameter" is
  checked.
- **`return_type` inconsistency** — comparable operations returning `None`,
  `bool`, the entity and a bare `dict` within and across documents, with no rule.

Each is a rule the checker could carry (a coherence rule is internal, like the
ones already added), and each is a place a generator would emit wrong code.
### 9.33 The CLI surface that under-enumerated its own commands (§9.32-A)

The remaining warning on the frozen baseline was library's `missing_command`, and §9.32-A
showed it was the tip of an eight-command collapse: the requirements name nine command lines
(`book add|list|search`, `member add|list|history`, `borrow`, `return`, `overdue`) and the
committed `out/library/components.json` declared **one** (`book` → `add`). Two things were
wrong, and both are fixed at the source:

1. **The prompt did not demand the whole surface.** `COMPONENTS_SYSTEM` described a command
   and its subcommands but never said every command line must appear, and it had no rule for a
   line that is a **single** word before the flags (`borrow`, `return`). It now says: every
   command line must appear, each distinct thing is a command of its own, and a line of the
   form `<program> <verb> --flag` makes that word a top-level command carrying its own options.
2. **The checker could not see most of the gap.** `checks_surface.COMMAND_PAIR` matched only
   `<noun> <verb> --flag`, so a bracketed optional flag (`book list [--author]`) hid the verb
   entirely, and it only ever compared a noun the surface already had, so a whole omitted
   command group was invisible. It now (a) accepts `[--flag`, and (b) reports a noun used
   before **two or more** distinct verbs as a missing command — with the **program name** and
   any **subcommand** excluded, so `library` (the program) and `report` (a subcommand of
   `expense`) are not false positives.

Measured on library, same prompt and grammar as before:

| | committed run | fresh run with the new prompt |
|---|---|---|
| `book` subcommands | `[add]` | `[add, list, search]` |
| `missing_command` warnings | 1 (`book search`) | 1 (`member`) |

The surface improved from one command form to three, and the strengthened checker reports the
one that remains honestly — `member` — where before it would have reported one of eight. On the
other six prompts the widened rule adds **no** false positive.

### 9.34 The declared errors nothing raises (§9.32-B)

Measured per prompt, 19 declared errors were raised by no method (`unused_error`). They split
into two causes: a **fabricated validation class** (`InvalidBudgetAmountError`,
`InvalidSkuError`, `InvalidWineTypeError` — `ERRORS_SYSTEM` forbids exactly this), and a
**grounded but unwired** failure (`MalformedCSVError`, `FileNotFoundError`, the not-founds).
An unraised class is dead code the generator would emit and never use, but a grounded one is a
gap in the *contracts*, not the registry, and the registry must stay faithful.

`repairs.repair_unraised_errors` decides by the requirements, the only authority on the
program's failures. An error is **kept** when a method raises it, when the requirements spell
its name out, or when a distinctive word of its name is grounded there; a validation-shaped
name is kept only when the requirements actually use its validation word. It is otherwise
dropped. It runs after step E, on the registry the contracts were written against, and every
drop is logged.

Measured across the corpus (13 of 19 dropped; grounded ones kept):

| prompt | dropped |
|---|---|
| expenses | InvalidBudgetMonthError, InvalidDateFormatError, InvalidPaymentMethodError, InvalidRecurringFlagError, InvalidBudgetAmountError |
| inventory | InvalidSkuError, InvalidPriceError, InvalidThresholdError, MalformedCSVError |
| 60 | InvalidPriceError, MalformedCSVError, PermissionDeniedError |
| library | MalformedCSVError, InvalidInputError |
| cli_tool, gui, hello | none |

The kept ones are the point: cli_tool's `MalformedCSVError` survives because its requirements
say "handle missing files and malformed CSV"; gui's `InvalidWineTypeError` survives because its
requirements say "invalid"; the not-founds of `60` and library survive because "invoice",
"order", "stock" and "overdue" are in their requirements. Eight tests pin the rule, including
the cli_tool keep and the no-requirements pass-through.
## §9.35 — capability described in prose has no method (60's search)

**The defect the generator-readiness probe found.** 60's requirements say
*"Customers should be able to search their orders and invoices"*. The surface
declared `customer search`, `order search`, `invoice search`; **no service method
provided search**, so a generator would emit three commands calling nothing. The
consistency checker could not see it: `missing_command` compares the surface with
the *requirements*, and nothing compared it with the *methods*.

**Fix, and the regression it caused.** A sentence was added to `CONTRACTS_SYSTEM`
requiring a method for a capability the requirements describe in prose. On the
first re-run 60 went from **0 to 15 warnings** — the model, told to write more
methods, emitted one service entry per *group* of methods (`CategoryRepository`
twice, `OrderService` three times), and the checker reported the duplicate names,
the adapter targets that no longer resolved, and the operations with no method.
The search methods appeared (`search_orders_by_customer_id`,
`search_invoices_by_customer_id`), so the prompt did what it was asked; the
damage was the duplication, which the dedupe pass should have merged and did not.

## §9.36 — dedupe merges services that share a name

`dedupe._deduplicate_services` removed duplicate *method* names inside a service
but never merged two service entries that share a `service_name`, though a second
registration of a name is exactly what a program cannot have.
`_deduplicate_services` now merges by normalised `service_name` — first spelling
and order kept, methods concatenated, then deduplicated by name — and nothing is
renamed or invented. Re-measured on 60: 12 service entries collapsed to 12 **with
no duplicate name**, wall clock back to 486 s, and the run returned to
**`0 error(s), 0 warning(s)`** with the search methods intact. Four tests pin the
merge (`tests/test_dedupe.py`).

## §9.37 — `unbacked_command`: the surface checked against the methods

The class §9.35 belongs to had no rule. `checks_surface.check_command_backing`
now walks every command verb in the surface and reports a **note** when no
service method name matches — the verb matched through a stem family, because
`book add` is `create_book` and `book list` is `read_all_books`, so the rule stays
silent on a synonym and fires only on a verb nothing plausibly implements. It is
the second rule (after `missing_command`) that reads something other than another
document, and the one a generator needs: a command the surface declares and no
method serves cannot be written. Measured across the corpus: **one** note, 60's
`order confirm`, reported beside the `cancel_order` the same run declares. Six
tests pin it, including the synonym silence and the "no services, no check" case
(`tests/test_generator_readiness_rules.py`).
