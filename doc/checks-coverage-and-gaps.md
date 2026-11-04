# What ESUS checks, what it covers, and what is missing

This guide complements [How the ESUS agent works](how-the-agent-works.md). It explains what a clean check tells us—and what it does not tell us—about the agent's reading of a request.

## The short answer

It is not accurate to say that ESUS checks only whether its files are well formed. Some checks compare parts of the extracted design with the original requirements, others check whether related design documents agree, and the generator checks every body the model writes against the confirmed method contract. For one prompt, the library system, an acceptance test also runs the generated program.

Those checks cover specific cases. A clean result means **the checks ESUS knows how to make found no blocking problem**. It does not prove that ESUS captured every requirement or that the generated program behaves as the user intended.

## What ESUS checks

### 1. Whether the architecture files can be used

The checker catches issues such as malformed or missing documents, duplicate names, missing fields, unsupported values, and references to entities or methods that do not exist. These checks make sure the saved design has a usable shape.

### 2. Whether related parts of the design agree

It checks selected links between the JSON documents. For example, it can compare:

- a foreign key with the entity and field it points to;
- repository methods in the service contract and persistence documents;
- interaction adapters with service methods, models, and fields;
- registered errors with errors that service methods say they can raise; and
- certain simple invariant claims, such as “SKU must be unique,” with the matching model field.

Some checks use names as clues. For example, the CRUD check recognizes method-name families such as `create_...` or `delete_...`. That can reveal an obvious gap, but a matching name does not prove the method does the right thing.

### 3. Whether selected command-line details appear in both places

ESUS saves the requirements with the extracted design. The checks compare some explicit command examples with the extracted command-line definition. They can look for missing commands or subcommands, and for flags in backticked command examples. When command lines nest more than two words, the checks match the longest command path and report a missing path line as a missing command. Another check tries to match commands to service methods by their names.

This is a real comparison with the request, but the checks recognize particular command and flag formats. If a requirement is written in another form or only described in prose, it can be skipped. The checker does not read every sentence and check that its full meaning appears in the design.

### 4. Whether the design is usable by this code generator

The readiness probe checks practical needs. It checks whether an action has a method to call, whether required fields can be supplied, and whether adapter fields exist on their models. It also checks that:

- every required command-line option has exactly one effective adapter mapping, and an option that parses but is ignored is a blocker;
- an option's type agrees with the transform and the parameter it feeds (a no-value flag onto a boolean parameter is passed as is);
- every required model field can be set by its repository's `create` (a required field with no parameter and no default would fail on every insert);
- an ID filter such as "books by author" has a real foreign-key field behind it, instead of comparing against the record's own key;
- no recorded method contract writes a primary key or contradicts itself (conflicting effects or conditions); and
- no human question is still open.

It also reports some risks: close pattern choices, low-confidence classifications, a corrected claim, or a method no pattern covers. A risk describes how a method was generated, not a defect. For example, two loan-history methods that sit near a tie between two filter patterns are emitted as the same filter either way, and a method no pattern covers is written by the model and checked by the gates below.

These findings help decide whether the generator can proceed without inventing missing pieces. They are not a score of how well the prompt was understood.

### 5. Selected human reviews

With `--chat`, ESUS can ask a person about flagged choices: close pattern matches, pattern details, duplicate or redundant command-line nodes, flags that select nothing, field mappings, and the behavior of methods that change data (what they set, create and refuse, which related field a search reads, which value is derived and never saved). Each answer is recorded beside the documents and stamped with the requirements hash. This resolves those specific uncertainties; it is not a complete human review of every requirement against every generated design document.

### 6. Whether a model-written body respects the confirmed contract

When the model writes a method body, the generator checks it before accepting it. A refused body gets up to two repair asks that quote the complaint; if it is still refused, the stub stays. The checks cover:

- the body compiles and uses only names the module, the store and the models define, with the keywords the repository signatures declare;
- it returns the declared type, and a read is typed by the repository the call goes through;
- it writes the fields the contract says, calls the named create exactly once, saves through the named call, and raises the declared errors under the confirmed condition (a condition that is written differently is accepted only when a second model call judges it equivalent, and the verdict is recorded);
- it reads the related model a search must read, and sets a derived value without saving it;
- it uses only the store's supported criteria operators, however the criteria list is built, and never puts mutable models in a set or as dictionary keys.

These checks are structural. They do not prove that a body behaves correctly, which is why every accepted body is tagged provisional.

## How much of the request is covered?

| Area | What the current checks can establish |
| --- | --- |
| File shape and named references | They can catch many missing, duplicate, malformed, or unsupported values. |
| Agreement between design documents | They can catch selected contradictions and disconnected parts. |
| Explicit CLI examples | They can catch some missing commands and flags when the examples use the formats they recognize. |
| Free-form business requirements | They are not checked comprehensively against the extracted design. |
| Generated behavior | The readiness probe does not run the generated program. For the library prompt, `tests/e2e_library_acceptance.py` does, and checks the behavior the prompt defines; other prompts have no acceptance test yet. |
| Model-written bodies | Checked against the confirmed contract and the store's API; behavior is only verified on the paths an acceptance test runs. |

## Example: a uniqueness rule

Suppose the request says: “Each product has a unique SKU. The user can add a product with `product add --sku --name`.”

ESUS can check that the extracted command includes `--sku` and `--name`, and that a simple “SKU must be unique” invariant agrees with the model's `unique` field. These are useful signs that important details made it into the design.

But those checks do not prove that the generated program rejects a second product with the same SKU. To establish that, a test must run the generated program twice with the same SKU and check that the second attempt is rejected as required. For the library prompt the acceptance test does exactly this for ISBN and email: it adds a second book or member with the same value, expects a failure with an explanation, and checks that no partial row was stored.

## What is still missing

- **A full link from every sentence to the design.** The current command-line checks cover a narrow, recognizable part of the request; there is no general check that every requirement has a matching design item.
- **Broad checks of meaning.** Intentions and most free-text rules can be checked for basic content and duplicates, but the checker cannot judge their complete meaning. It may miss implied behavior, edge cases, or a rule described in different words.
- **A guarantee from internal agreement.** The model can leave a requirement out of several documents in a consistent way. Those documents may agree with each other while still missing the user's intent.
- **Behavior tests for each request.** Readiness checks inspect the extracted design. A separate acceptance test is needed to run the generated program and check the requested behavior, including errors and edge cases. One exists for the library prompt and one for the expenses prompt (which currently fails most of its checks); a new prompt needs its own, and a passing run covers only the paths it exercises (most, not all, statements in the model-written bodies run).
- **Requirements the checks do not look at.** For the library prompt these are the instruction to use type hints throughout (the fixed store and CLI templates do not provide them) and the quality of the architecture's separation of concerns. Error messages are not asserted unless a prompt names them.

The known open work is listed in [Open points](open-points.md).

## A stronger way to show understanding

For each important requirement, connect three things:

1. The sentence or example from the original request.
2. The design item that represents it.
3. A test showing the generated program does what that requirement asks.

That mapping would make omissions easier to see and provide stronger evidence than a clean consistency or readiness report. It still would not be a mathematical proof of understanding, but it would make the agent's interpretation much more reviewable.

## Code locations

- `kernel/consistency/` contains the checks between extracted documents.
- `kernel/consistency/checks_surface.py` compares selected command and flag examples with the extracted command-line definition.
- `kernel/consistency/checks_invariants.py` compares a small set of invariant claims with model fields.
- `probe_readiness.py` groups findings into generator blockers and separate risks, including the adapter, relation-filter, create-field and contract-record checks.
- `extract_arch.py` runs selected interactive reviews when `--chat` is used; the reviews themselves are the `review_*.py` scripts.
- `generator.py` checks each model-written body (`_body_complaints`, `_contract_complaints`) before accepting it.
- `kernel/pattern_shapes.py` rejects a pattern claim that cannot fit a method's return type.
- `tests/e2e_library_acceptance.py` runs the generated library program against a real database.
