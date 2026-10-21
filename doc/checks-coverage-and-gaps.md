# What ESUS checks, what it covers, and what is missing

This guide complements [How the ESUS agent works](how-the-agent-works.md). It explains what a clean check tells us—and what it does not tell us—about the agent's reading of a request.

## The short answer

It is not accurate to say that ESUS checks only whether its files are well formed. Some checks compare parts of the extracted design with the original requirements, and others check whether related design documents agree.

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

ESUS saves the requirements with the extracted design. The checks compare some explicit command examples with the extracted command-line definition. They can look for missing commands or subcommands, and for flags in backticked command examples. Another check tries to match commands to service methods by their names.

This is a real comparison with the request, but the checks recognize particular command and flag formats. If a requirement is written in another form or only described in prose, it can be skipped. The checker does not read every sentence and check that its full meaning appears in the design.

### 4. Whether the design is usable by this code generator

The readiness probe checks practical needs such as whether an action has a method to call, whether required fields can be supplied, and whether adapter fields exist on their models. It also reports some risks, including close pattern choices, low-confidence classifications, or a pattern the generator does not know.

These findings help decide whether the generator can proceed without inventing missing pieces. They are not a score of how well the prompt was understood.

### 5. Selected human reviews

With `--chat`, ESUS can ask a person about flagged choices such as close pattern matches, duplicate interface entries, field mappings, and method details for supported patterns. This resolves those specific uncertainties; it is not a complete human review of every requirement against every generated design document.

## How much of the request is covered?

| Area | What the current checks can establish |
| --- | --- |
| File shape and named references | They can catch many missing, duplicate, malformed, or unsupported values. |
| Agreement between design documents | They can catch selected contradictions and disconnected parts. |
| Explicit CLI examples | They can catch some missing commands and flags when the examples use the formats they recognize. |
| Free-form business requirements | They are not checked comprehensively against the extracted design. |
| Generated behavior | The readiness probe does not run the generated program against acceptance scenarios. |

## Example: a uniqueness rule

Suppose the request says: “Each product has a unique SKU. The user can add a product with `product add --sku --name`.”

ESUS can check that the extracted command includes `--sku` and `--name`, and that a simple “SKU must be unique” invariant agrees with the model's `unique` field. These are useful signs that important details made it into the design.

But those checks do not prove that the generated program rejects a second product with the same SKU. To establish that, a test must run the generated program twice with the same SKU and check that the second attempt is rejected as required.

## What is still missing

- **A full link from every sentence to the design.** The current command-line checks cover a narrow, recognizable part of the request; there is no general check that every requirement has a matching design item.
- **Broad checks of meaning.** Intentions and most free-text rules can be checked for basic content and duplicates, but the checker cannot judge their complete meaning. It may miss implied behavior, edge cases, or a rule described in different words.
- **A guarantee from internal agreement.** The model can leave a requirement out of several documents in a consistent way. Those documents may agree with each other while still missing the user's intent.
- **Behavior tests for each request.** Readiness checks inspect the extracted design. Separate acceptance tests are needed to run the generated program and check the requested behavior, including errors and edge cases.

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
- `probe_readiness.py` groups findings into generator blockers and separate risks.
- `extract_arch.py` runs selected interactive reviews when `--chat` is used.
