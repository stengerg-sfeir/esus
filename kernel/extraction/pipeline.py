"""The extraction steps, run in order and chained.

Each step receives the names its predecessors actually produced, both in the
prompt (as an authoritative list) and in its grammar (as the only writable
strings). Steps whose predecessor produced nothing usable fall back to the
unconstrained grammar and say so in the log, so a degraded run is visible
rather than silent.
"""

import json
import re
import sys

from kernel.consistency.checks_crud import check_crud_coverage
from kernel.consistency.checks_surface import check_flag_coverage, check_surface_coverage
from kernel.consistency.report import Report
from kernel.extraction import (
    classification,
    command_lines,
    dedupe,
    grammar_builders,
    grammar_check,
    grammar_open,
    grammar_persistence,
    interfaces,
    prompts,
    repairs,
    return_types,
    runner,
    vocabulary,
)

# Greedy decoding plus a fixed seed: the same prompt yields the same document
# (modulo GPU arithmetic), so a healed rerun proves the fix rather than luck.
# Reproducibility is diagnostic, not corrective — but the first attempt is the
# baseline everything is judged against, so it stays cold and reproducible.
TEMPERATURE = 0.0
SEED = 20261012

# A second attempt at a higher temperature, used when a step returns something
# JSON rejects — and, deliberately, for coverage retries too. Measured
# 2026-10-13: three temp-0 library runs came back token-identical, and a cold
# coverage retry re-asked and re-omitted the same two commands. A retry that
# cannot differ cannot heal; the first attempt stays reproducible, the retry
# explores once, and the probe judges the result either way.
RETRY_TEMPERATURE = 0.35

# Document keys, which are also the top-level JSON keys the checker reads.
INTENTIONS = "intentions"
DATA_MODELS = "data_models"
ERRORS = "errors"
INVARIANTS = "invariants"
COMPONENTS = "components"
SERVICE_CONTRACTS = "service_contracts"
PATTERN_MATCHES = "pattern_matches"
INTERACTION_ADAPTERS = "interaction_adapters"
PERSISTENCE_PORTS = "persistence_ports"


def describe_step(name, documents):
    """One line saying what a step produced (`components: 9 command(s)`).

    Counts what the document holds, never the model's token counts: the user
    asked "how many intentions/entities came out", not "how long it took".
    A missing or unusable document says so instead of reporting zero.
    """
    body = documents.get(name)
    if name == "errors_repair":
        errors = documents.get(ERRORS)
        services = documents.get(SERVICE_CONTRACTS)
        if not isinstance(errors, list) or not isinstance(services, list):
            return "no usable documents"
        return f"{len(errors)} error(s), {len(services)} service(s) after repair"
    if body is None:
        return "no usable document"
    if name == INTENTIONS:
        return f"{len(body)} phrase(s)" if isinstance(body, list) else "no usable document"
    if name == DATA_MODELS:
        if not isinstance(body, list):
            return "no usable document"
        fields = sum(len(e.get("fields") or []) for e in body
                     if isinstance(e, dict))
        return f"{len(body)} entities, {fields} field(s)"
    if name == ERRORS:
        return f"{len(body)} error(s)" if isinstance(body, list) else "no usable document"
    if name == INVARIANTS:
        return f"{len(body)} invariant(s)" if isinstance(body, list) else "no usable document"
    if name == COMPONENTS:
        if not isinstance(body, dict):
            return "no usable document"
        facade = body.get("facade") if isinstance(body.get("facade"), dict) else {}
        invocation = facade.get("invocation")
        commands = (invocation.get("commands") if isinstance(invocation, dict)
                    else None)
        if isinstance(commands, list):
            return f"{len(commands)} command(s)"
        # A non-CLI facade (gui) legitimately has no invocation: the surface
        # is the crud list, not a command table. Reporting "no usable
        # document" here once hid a fine gui/pyimgui facade as a failure.
        crud = body.get("crud_services")
        kinds = f"{len(crud)} crud service(s), " if isinstance(crud, list) else ""
        return f"{kinds}{facade.get('type', '?')} facade (no CLI surface)"
    if name == SERVICE_CONTRACTS:
        if not isinstance(body, list):
            return "no usable document"
        methods = sum(len(s.get("methods") or []) for s in body
                      if isinstance(s, dict))
        return f"{len(body)} service(s), {methods} method(s)"
    if name == PATTERN_MATCHES:
        return f"{len(body)} item(s)" if isinstance(body, list) else "no usable document"
    if name == INTERACTION_ADAPTERS:
        return f"{len(body)} adapter(s)" if isinstance(body, list) else "no usable document"
    if name == PERSISTENCE_PORTS:
        if not isinstance(body, dict):
            return "no usable document"
        repos = body.get("repositories")
        return f"{len(repos)} repositor(y/ies)" if isinstance(repos, list) else "no usable document"
    return "done"


class Pipeline:
    """Runs steps A–H over one set of requirements."""

    def __init__(self, llm, classifier=None, log=None, classifier_factory=None,
                 progress_fn=None):
        self.llm = llm
        # `progress_fn(name, summary)` runs after each step with one line
        # describing what the step produced (`components: 9 command(s)`).
        # The run log already narrates repairs and retries; this is the
        # concise per-step result the terminal shows, quiet or not.
        self.progress_fn = progress_fn
        # Step F reads the next-token distribution from the model already
        # loaded for A–E, so `classifier` defaults to `llm` when no separate
        # instance is supplied. `classifier_factory` remains for callers and
        # tests that want a deferred or different classifier; it is no longer
        # used by `extract_arch.py`, which would otherwise load the GGUF twice.
        self.classifier = classifier
        self.classifier_factory = classifier_factory
        self.log = log
        self.documents = {}
        self.results = []

    def run(self, requirements, start=None):
        # Kept so the post-contract error repair can consult the requirements — the
        # only authority on whether a declared-but-unraised error belongs.
        self.requirements = requirements
        steps = [
            (INTENTIONS, lambda: self._step_intentions(requirements)),
            (DATA_MODELS, lambda: self._step_data_models(requirements)),
            (ERRORS, lambda: self._step_errors(requirements)),
            (INVARIANTS, lambda: self._step_invariants(requirements)),
            (COMPONENTS, lambda: self._step_components(requirements)),
            (SERVICE_CONTRACTS, lambda: self._step_contracts(requirements)),
            ("errors_repair", self._repair_errors),
            (PATTERN_MATCHES, self._step_patterns),
            (INTERACTION_ADAPTERS, lambda: self._step_adapters(requirements)),
            (PERSISTENCE_PORTS, lambda: self._step_persistence(requirements)),
        ]
        index = 0
        if start is not None:
            # Resuming (`extract_arch.py --from-step`) reruns one failed step
            # against the earlier steps' archived documents instead of the
            # whole pipeline: a D-fix validates in minutes, not half an hour.
            # Documents already in `self.documents` are the context the
            # remaining steps chain from.
            index = [name for name, _ in steps].index(start)
        for name, step in steps[index:]:
            step()
            if self.progress_fn is not None:
                self.progress_fn(name, describe_step(name, self.documents))
        return self.documents

    def _generate(self, key, prompt, grammar_text, temperature=TEMPERATURE,
                  retry_temperature=RETRY_TEMPERATURE):
        """Validate the grammar, generate, and store the document under `key`.

        One unusable document used to cost the whole run: library's missing
        components.json and every downstream warning came from a single
        malformed step. A grammar-constrained step fails only when the model
        writes something the grammar permits but JSON rejects, so one retry at a
        higher temperature recovers it cheaply. Coverage retries (a miss the
        checker names) keep the cold temperature instead — see TEMPERATURE.
        """
        grammar_check.assert_valid(grammar_text, label=f"step {key}")

        body = None
        # The ceiling the retry runs under. It starts as None, meaning the
        # first-attempt ceiling of `MAX_NEW_TOKENS`.
        retry_budget = None
        for attempt, attempt_temperature in enumerate((temperature, retry_temperature)):
            result = runner.generate(
                self.llm, prompt, grammar_text, key,
                temperature=attempt_temperature,
                max_new_tokens=retry_budget,
                seed=SEED,
            )
            self.results.append(result)
            self.log.write(result.describe())

            body = _parse_document(result.text, key, self.log)
            # A truncated document is retried even when it parsed. It can parse and
            # still be incomplete — the ceiling can fall exactly on a valid list
            # boundary — and accepting that silently is the one outcome this must
            # not produce, because a short document is indistinguishable from a
            # complete one downstream. Only an untruncated, parseable document ends
            # the loop.
            if body is not None and not result.truncated:
                break
            if attempt == 0:
                if result.truncated:
                    # Retrying a truncation under the ceiling that caused it can
                    # only truncate again — that is what happened to expenses'
                    # adapters, which hit `MAX_NEW_TOKENS` twice while the context
                    # still held room for thousands more tokens. So the retry gets
                    # the whole room the prompt left behind.
                    retry_budget = runner.available_tokens(self.llm, prompt)
                    if retry_budget <= (result.budget or 0):
                        self.log.write(
                            f"[!] step {key}: the context has no room left to raise the "
                            f"{result.budget}-token ceiling — retrying at the same ceiling"
                        )
                    reason = (
                        f"hit the {result.budget}-token ceiling — its document may be "
                        f"incomplete, retrying with a {retry_budget}-token ceiling"
                    )
                else:
                    reason = "produced unusable JSON"
                self.log.write(f"[!] step {key} {reason} — retrying once")

        if body is not None and result.truncated:
            self.log.write(
                f"[!] step {key} is still truncated after the retry — "
                f"the document written is incomplete"
            )

        if body is None:
            self.log.write(f"[!] step {key} produced unusable JSON — dependent steps degrade")
            return None

        # A repeated name cannot be prevented by the grammar (distinctness over
        # free text is not a regular property) and must not be prevented by a
        # length cap either, which would truncate a legitimate long list. So the
        # exact repeat is removed here, keeping the first occurrence untouched.
        body, removed = dedupe.deduplicate(key, body)
        if removed:
            self.log.write(f"[ok] step {key}: removed {removed} exactly repeated name(s)")

        self.documents[key] = body
        return body

    def _entities(self):
        return vocabulary.entities_from(self.documents.get(DATA_MODELS))

    def _services(self):
        return vocabulary.services_from(self.documents.get(SERVICE_CONTRACTS))

    def _step_intentions(self, requirements):
        self._generate(
            INTENTIONS,
            prompts.intentions(requirements),
            grammar_open.phrase_list(INTENTIONS),
        )

    def _step_data_models(self, requirements):
        """Step B: the one step nothing constrains, so it is shown A's phrases.

        Every other step's grammar is generated from the names an earlier step
        produced, so it *cannot* invent one. A emits prose, which cannot become a
        vocabulary — so B ran on the raw requirements with an open grammar, and
        for a program that models nothing it filled the required shape from
        priors (cli_tool got `users, products, orders, order_items`).

        Showing it A's phrases is grounding rather than constraint: it supplies
        the program's own words and leaves no vacuum for priors to fill. It is
        deliberately the **only** thing added here — the empty answer is already
        permitted by both the prompt and the grammar, and cli_tool took neither,
        so more permission cannot be the fix. See `prompts.intentions_block`.
        """
        grounding = prompts.intentions_block(self.documents.get(INTENTIONS))
        if grounding is None:
            self.log.write(
                "[!] step data_models: step A produced no usable phrases — running ungrounded"
            )
        body = self._generate(
            DATA_MODELS,
            prompts.data_models(requirements, grounding),
            grammar_open.data_models(),
        )
        # A primary key declaring `unique=false` contradicts itself; the flag
        # was never read anywhere, so it is noise, not modeling — fixed here
        # so the check below judges the repaired models.
        if isinstance(body, list):
            repairs.repair_primary_key_uniqueness(body, self.log)
            repairs.repair_primary_key_foreign_keys(body, self.log)
            self.documents[DATA_MODELS] = body
        return body

    def _step_errors(self, requirements):
        """Step E': the application error types, before the services that raise them.

        Placed after step B so a type named for an entity is spelled with that
        entity's own name, and before step E because a contract method names the
        errors it may raise — the registry has to exist first for the reference to
        mean anything. This is the one thing the requirements name that had
        nowhere to go: inventory asks for `CategoryNotFoundError` and
        `ProductNotFoundError`, and every earlier run dropped them silently,
        because no document had a place to record an exception type.

        Ungated: a program with no domain can still fail, and cli_tool's "error
        handling for missing files and malformed CSV" is exactly that case.
        """
        vocab = vocabulary.Vocabulary(entities=self._entities())
        block = prompts.entity_block(vocab) if vocab.entity_names else None
        self._generate(
            ERRORS,
            prompts.errors(requirements, block),
            grammar_open.errors(),
        )

    def _step_invariants(self, requirements):
        """Step C: chained on step B, because an invariant can contradict it.

        The plan's dependency table marked this pair as needing no chaining
        ("chaining here adds noise"), and that was wrong in a way the checker
        could see: an invariant claiming `category_id must be nullable` against a
        model that declares it not nullable, and 60 claiming `product_id must be
        unique` for a foreign key that cannot be. Giving step C the model it has
        to agree with is the same move as every other chained step.
        """
        vocab = vocabulary.Vocabulary(entities=self._entities())
        block = prompts.entity_block(vocab) if vocab.entity_names else None
        self._generate(
            INVARIANTS,
            prompts.invariants(requirements, block),
            grammar_open.invariant_list(INVARIANTS),
        )

    def _step_components(self, requirements):
        """Step D: crud_services is closed to the entities of step B."""
        vocab = vocabulary.Vocabulary(entities=self._entities())
        if not vocab.entity_names:
            self.log.write("[!] step components: no entities from step B — crud_services unconstrained")
        block = prompts.components_block(vocab)
        grammar = grammar_builders.components(vocab)
        # The command lines the requirements state, enumerated: discovery is
        # what fails, so the step is handed each line to cover rather than
        # asked to find them. An empty list (prose-only prompts) falls back
        # to discovery, and says so in the log.
        spans = command_lines.extract_command_lines(requirements)
        lines_block = prompts.command_lines_block(spans)
        if lines_block is None:
            self.log.write("[!] step components: no command lines extracted — "
                           "deriving the surface from prose")
        else:
            self.log.write(f"[ok] step components: {len(spans)} command line(s) enumerated")
        body = self._generate(
            COMPONENTS,
            prompts.components(requirements, block, lines_block),
            grammar,
        )
        # A bare command line (`` `library overdue` ``) comes back with a
        # subcommand named `none` stating there is none. The grammar leaves
        # subcommand names free text, so the placeholder is removed here —
        # before the coverage check, so the check judges the real surface.
        if isinstance(body, dict):
            repairs.repair_placeholder_subcommands(body, self.log)
        # A required flag the requirements pass and the leaf does not declare
        # is added here when the data model types it — the name comes from the
        # requirements' own command line, the type from the model field, so the
        # coverage check below judges the repaired surface.
        if isinstance(body, dict):
            repairs.repair_missing_surface(
                body, requirements, self.documents.get(DATA_MODELS), self.log
            )
        # A flat `a_b` duplicating a declared `a b` pair goes last: the pair
        # itself may have been added by the surface repair just above (the
        # retry body lacked `member history` while keeping a flat
        # `member_history`), so running this any earlier finds no pair and
        # keeps the flat form it should drop.
        if isinstance(body, dict):
            repairs.repair_flat_command_duplicates(body, self.log)
            repairs.repair_misread_flat_commands(body, self.log)
            repairs.repair_long_option_names(body, self.log)
        # The prompt orders every requirements command line onto the surface,
        # but the grammar cannot enforce presence — omission is always
        # representable. A surface missing a named command (or a named flag
        # behind a declared verb, like inventory's flagless `product add`)
        # leaves a path the CLI parses but can never run, so a miss is
        # retried once with the miss itself appended to the requirements,
        # exactly as named.
        missing = _missing_commands(body, requirements) + _missing_flags(body, requirements)
        if missing:
            self.log.write(
                f"[!] step components omits {len(missing)} surface item(s) the requirements "
                f"name — retrying once"
            )
            first = body
            retry = self._generate(
                COMPONENTS,
                prompts.components(
                    _with_miss_note(
                        requirements, missing,
                        command_lines=_command_lines(requirements),
                    ),
                    block,
                ),
                grammar,
            )
            if isinstance(retry, dict):
                repairs.repair_placeholder_subcommands(retry, self.log)
                repairs.repair_missing_surface(
                    retry, requirements, self.documents.get(DATA_MODELS), self.log
                )
                repairs.repair_flat_command_duplicates(retry, self.log)
                repairs.repair_misread_flat_commands(retry, self.log)
                repairs.repair_long_option_names(retry, self.log)
                retry_misses = (_missing_commands(retry, requirements)
                                + _missing_flags(retry, requirements))
            else:
                retry_misses = list(missing)
            body, _ = _settle_retry(
                COMPONENTS, first, missing, retry, retry_misses,
                self.log, unit="surface item(s)",
            )
            # _generate stores every attempt: point the document back at the
            # kept one, or a degrading retry silently replaces good content.
            self.documents[COMPONENTS] = body
        return body

    def _step_contracts(self, requirements):
        """Step E: service names are new, so the grammar stays open.

        Gated on there being entities, as step H is gated on persistence: a
        service contract exists to act on a domain, so no domain means no
        services. Ungated, this step invented a `HelloWorldService` for a
        program whose data model was, correctly, empty — and step G then
        faithfully built an adapter onto it.
        """
        entities = self._entities()
        if not entities:
            self.log.write("[ok] step contracts: step B produced no entities — no services")
            self.documents[SERVICE_CONTRACTS] = []
            return
        vocab = vocabulary.Vocabulary(
            entities=entities,
            crud_operations=vocabulary.crud_requirements(self.documents.get(COMPONENTS)),
            errors=self.documents.get(ERRORS) or (),
        )
        # E owns the repositories it declares, so it must be told which
        # operations each entity needs — otherwise it writes "standard CRUD"
        # from an adjective rather than from the list, and every delete is lost.
        block = prompts.requirements_block(vocab)
        grammar = grammar_open.service_contracts()
        body = self._generate(
            SERVICE_CONTRACTS,
            prompts.service_contracts(requirements, block),
            grammar,
        )
        # A signature is a specification the generated body must honour, so a
        # method that returns `dict[str, object]` where the entity is known is a
        # defect no generation can repair without overriding the contract.
        if isinstance(body, list):
            # A sibling class that landed inside this service's method list is
            # not a callable; remove it before return types or patterns see it.
            body = repairs.repair_nested_declarations(
                body, self.log, document=SERVICE_CONTRACTS)
            self.documents[SERVICE_CONTRACTS] = return_types.repair_contract_returns(
                body, self._entities(), self.log
            )
        # The operations block is a minimum the interface must provide, but the
        # grammar cannot enforce that a create/delete method exists — absence is
        # always representable. A miss is retried once with the miss itself
        # appended, exactly as named.
        missing = _unmet_operations(
            self.documents.get(COMPONENTS),
            {
                SERVICE_CONTRACTS: self.documents.get(SERVICE_CONTRACTS),
                PERSISTENCE_PORTS: self.documents.get(PERSISTENCE_PORTS),
            },
        )
        if missing:
            self.log.write(
                f"[!] step contracts omits {len(missing)} required operation(s) — "
                f"retrying once"
            )
            first = self.documents.get(SERVICE_CONTRACTS)
            retry = self._generate(
                SERVICE_CONTRACTS,
                prompts.service_contracts(_with_miss_note(requirements, missing), block),
                grammar,
            )
            if isinstance(retry, list):
                retry = return_types.repair_contract_returns(
                    retry, self._entities(), self.log
                )
                self.documents[SERVICE_CONTRACTS] = retry
                retry_misses = _unmet_operations(
                    self.documents.get(COMPONENTS),
                    {
                        SERVICE_CONTRACTS: retry,
                        PERSISTENCE_PORTS: self.documents.get(PERSISTENCE_PORTS),
                    },
                )
            else:
                retry_misses = list(missing)
            body, _ = _settle_retry(
                SERVICE_CONTRACTS, first, missing, retry, retry_misses,
                self.log, unit="required operation(s)",
            )
            self.documents[SERVICE_CONTRACTS] = body

    def _repair_errors(self):
        """Remove the two error contradictions the grammar cannot express (§9.28).

        Run after step E because both documents have to exist first: the registry
        is what `raises` resolves against, and the keep/drop decision for a
        duplicate subject follows which name a method actually raises. The
        constraints are global — two names meaning one thing, a create raising
        its own not-found — so no GBNF expresses them, and the check for each is
        shared with the checker to keep one definition.
        """
        services = self.documents.get(SERVICE_CONTRACTS)
        errors, services = repairs.repair_errors(
            self.documents.get(ERRORS), services, self.log
        )
        # A declared error that no method raises is dead code. The registry keeps
        # one when a method raises it, when the requirements name it, or when a
        # distinctive word of its name is grounded in the requirements; otherwise
        # it is dropped (§9.34).
        errors = repairs.repair_unraised_errors(
            errors, services, getattr(self, "requirements", ""), self.log
        )
        self.documents[ERRORS] = errors
        if isinstance(services, list):
            self.documents[SERVICE_CONTRACTS] = services

    def _step_patterns(self):
        """Step F: classify invariants and contract methods into kernel patterns.

        The classifier reads the last-token logits from the ordinary
        `logits_all=False` extractor context, so a no-domain run still loads
        nothing extra. `classifier_factory` is a deferred-loader escape hatch
        for callers that genuinely need a separate model; when it is absent,
        the extractor itself is the classifier.
        """
        items = classification.classification_items(self.documents)
        if not items:
            self.log.write("[ok] step patterns: nothing to classify")
            self.documents[PATTERN_MATCHES] = []
            return
        if self.classifier is None and self.classifier_factory is not None:
            self.classifier = self.classifier_factory()
        classifier = self.classifier or self.llm
        matches = classification.classify_documents(classifier, self.documents, self.log)
        self.documents[PATTERN_MATCHES] = matches

    def _step_adapters(self, requirements):
        """Step G: targets are closed to step E's services and step B's entities.

        Gated on there being services: an adapter maps an external action onto a
        service method, so with no services there is nothing to map onto and an
        empty list is the correct answer rather than an invention.
        """
        vocab = vocabulary.Vocabulary(entities=self._entities(), services=self._services())
        if not vocab.services:
            self.log.write("[ok] step adapters: step E produced no services — no adapters")
            self.documents[INTERACTION_ADAPTERS] = []
            return
        block = prompts.combined_block(vocab)
        grammar = grammar_builders.adapters(vocab)
        self._generate(
            INTERACTION_ADAPTERS,
            prompts.adapters(requirements, block),
            grammar,
        )
        self._repair_adapters()
        # An adapter assembling an undeclared model field (`author_id` into a
        # `Book` with no such field) fails at construction no matter what the
        # CLI supplies, and a required field no bound leaf flag supplies
        # (`file_path` where the leaf offers `--output`) strands the action.
        # Field names are free text the grammar cannot constrain, so either
        # miss is retried once with the miss itself appended, exactly as named.
        # (A miss the surface owns instead — a flag the requirements name and
        # no leaf declares, like inventory's flagless `product add` — is step
        # D's retry to heal; it is listed here only when the adapter side can
        # also move, e.g. renaming the field to the flag.)
        unknown = _unknown_model_fields(self.documents) + _uncovered_cli_fields(self.documents)
        if unknown:
            self.log.write(
                f"[!] step adapters has {len(unknown)} unreachable field(s) — "
                f"retrying once"
            )
            first = self.documents.get(INTERACTION_ADAPTERS)
            retry = self._generate(
                INTERACTION_ADAPTERS,
                prompts.adapters(_with_miss_note(requirements, unknown), block),
                grammar,
            )
            if isinstance(retry, list):
                self._repair_adapters()
                retry_misses = (_unknown_model_fields(self.documents)
                                + _uncovered_cli_fields(self.documents))
            else:
                retry, retry_misses = None, list(unknown)
            kept, _ = _settle_retry(
                INTERACTION_ADAPTERS, first, unknown, retry, retry_misses,
                self.log, unit="unreachable field(s)",
            )
            # _generate stores every attempt: point the document back at the
            # kept one, or a degrading retry silently replaces good content.
            self.documents[INTERACTION_ADAPTERS] = kept
        # The surface and adapter steps are separate: an adapter can require
        # a value the surface never declares. Expose it after both exist so
        # the readiness probe judges a runnable leaf, not a stranded call.
        repairs.repair_missing_adapter_flags(
            self.documents.get(COMPONENTS),
            self.documents.get(INTERACTION_ADAPTERS),
            self.documents.get(SERVICE_CONTRACTS),
            self.documents.get(DATA_MODELS),
            self.log,
        )
        # A boolean selector can name a filter the adapter document never
        # wired (`--available-only` beside `filter_books_by_available_copies`).
        # The flag otherwise parses and is ignored; the one-parameter method
        # supplies the missing action.
        repairs.repair_missing_filter_actions(
            self.documents.get(COMPONENTS),
            self.documents.get(INTERACTION_ADAPTERS),
            self.documents.get(SERVICE_CONTRACTS),
            self.documents.get(DATA_MODELS),
            self.log,
        )

    def _repair_adapters(self):
        """Deterministic adapter repairs, sharing the checker's predicates."""
        adapters = self.documents.get(INTERACTION_ADAPTERS)
        if not isinstance(adapters, list):
            return
        # A transform that contradicts the field's name — a count converted
        # to cents, a single name read as a list — is not expressible in the
        # grammar (transform is an enum, the name is free text), so it is
        # removed here, reusing the checker's own predicate (§9.28).
        repairs.repair_adapter_transforms(
            adapters, self.log, self.documents.get(SERVICE_CONTRACTS))
        # A field mapped past a parameter of its own name — `category_id`
        # into `data` while the method declares `category_id` — is the same
        # class of defect: the field's name and the method's parameter list
        # are never related by the prompt block or the grammar, so the
        # redirect happens here, reusing the checker's predicate.
        repairs.repair_adapter_targets(
            adapters, self.documents.get(SERVICE_CONTRACTS), self.log
        )
        # A field targeting an entity parameter must spell a declared model
        # field — the generator builds `Model(**fields)` — so a flag spelling
        # with proven units is renamed to its unique model field (`amount` to
        # `amount_cents` under DECIMAL_TO_CENTS). DIRECT carries no unit
        # evidence and is never renamed.
        repairs.repair_adapter_field_names(
            adapters, self.documents.get(SERVICE_CONTRACTS),
            self.documents.get(DATA_MODELS), self.log
        )

    def _step_persistence(self, requirements):
        """Step H: repositories and mappings are fixed by steps B and D."""
        components = self.documents.get(COMPONENTS)
        if not persistence_required(components):
            self.log.write("[ok] step persistence: components declare no persistence — step skipped")
            return
        vocab = vocabulary.Vocabulary(
            entities=self._entities(),
            crud_entities=vocabulary.crud_entity_names(components),
            crud_operations=vocabulary.crud_requirements(components),
        )
        if not vocab.entity_names and not vocab.crud_entities:
            self.log.write("[!] step persistence: no entities to persist — step skipped")
            return
        body = self._generate(
            PERSISTENCE_PORTS,
            prompts.persistence_ports(requirements, prompts.requirements_block(vocab)),
            grammar_persistence.persistence_ports(vocab),
        )
        if body is None:
            return
        # A repository step E already declared is the same class, so its method
        # set is E's; H keeps the mapping it alone produces. Without this the two
        # documents described one interface two ways in all five domain prompts.
        unified = interfaces.unify_repository_interfaces(
            body, self.documents.get(SERVICE_CONTRACTS), self.log
        )
        # H can repeat the same nesting defect, and a repository H declares
        # alone is not overwritten by E; clean it before pattern matching.
        if isinstance(unified, dict):
            repairs.repair_nested_declarations(
                unified.get("repositories"), self.log,
                document=PERSISTENCE_PORTS)
        # Repaired after unification so the figure logged is what the document
        # actually ends up with, and so a repository only step H declares is
        # covered too.
        self.documents[PERSISTENCE_PORTS] = return_types.repair_port_returns(
            unified, self._entities(), self.log
        )
        # A create that describes a required field its parameters omit can
        # never succeed at the store; the description is the evidence.
        repairs.repair_create_missing_fields(
            self.documents[PERSISTENCE_PORTS], self.documents.get(DATA_MODELS),
            self.log)
        # Step H owns the same minimum as step E: a repository per listed entity
        # with a method for every required operation. A miss is logged, not
        # retried — the document is already unified with E's method sets, so a
        # retry would re-ask for methods E owns, and the probe reports the rest.
        still = _unmet_operations(
            self.documents.get(COMPONENTS), self.documents
        )
        if still:
            self.log.write(
                f"[!] step persistence still omits {len(still)} required operation(s) — "
                f"kept, the probe will report it"
            )


def persistence_required(components):
    """True when step D asked for persistence."""
    if not isinstance(components, dict):
        return False
    persistence = components.get("persistence")
    return isinstance(persistence, dict) and persistence.get("required") is True


def _settle_retry(step, first_body, first_misses, second_body, second_misses, log, unit="item(s)"):
    """Keep the retry iff it strictly reduces the misses; ties keep the first.

    A coverage retry that returns a fragment (expenses' adapters came back as
    one action) must not replace a fuller document with the same miss count.
    An unusable retry always loses. The outcome is logged either way, naming
    both counts, so a degraded retry is visible rather than silent.
    """
    if second_body is None:
        log.write(f"[!] step {step} retry is unusable — kept first attempt")
        return first_body, first_misses
    if len(second_misses) < len(first_misses):
        log.write(f"[ok] step {step} retry healed "
                  f"{len(first_misses)}->{len(second_misses)} {unit}")
        return second_body, second_misses
    log.write(f"[!] step {step} still omits {len(first_misses)} {unit} "
              f"(retry: {len(second_misses)}) — kept first attempt; "
              f"the probe will report it")
    return first_body, first_misses


def _missing_commands(components, requirements):
    """The `missing_command` messages for a components body, or [].

    The checker's own rule, run against the requirements the step was given —
    so the retry asks for exactly what the probe would report.
    """
    if not isinstance(components, dict) or not requirements:
        return []
    report = Report("components")
    check_surface_coverage(components, requirements, report)
    return [
        finding.message for finding in report.warnings if finding.rule == "missing_command"
    ]


def _missing_flags(components, requirements):
    """The `missing_flag` warnings for a components body, or [].

    The checker's own rule: a verb the surface declares with none of the
    flags the requirements pass behind it. Optional (bracketed) flags report
    as notes and are not retried — the generator can omit an optional.
    """
    if not isinstance(components, dict) or not requirements:
        return []
    report = Report("components")
    check_flag_coverage(components, requirements, report)
    return [
        finding.message for finding in report.warnings if finding.rule == "missing_flag"
    ]


def _unmet_operations(components, documents):
    """The `unmet_crud_operation` messages for a components body, or [].

    The checker's own rule, scoped to the entity's own interface — so the retry
    asks for exactly what the probe would report.
    """
    if not isinstance(components, dict):
        return []
    report = Report("crud")
    check_crud_coverage(components, documents, report)
    return [
        finding.message
        for finding in report.warnings
        if finding.rule == "unmet_crud_operation"
    ]


def _unknown_model_fields(documents):
    """`adapter builds Entity with undeclared field` messages, or [].

    The generator's own predicate (`codegen.unknown_model_fields` — one
    definition): a field targeting an entity-typed parameter must name a
    declared field of that entity, or construction fails at runtime.
    """
    from kernel.codegen import unknown_model_fields

    if not isinstance(documents, dict):
        return []
    adapters = documents.get(INTERACTION_ADAPTERS)
    services = documents.get(SERVICE_CONTRACTS)
    models = documents.get(DATA_MODELS)
    found = unknown_model_fields(adapters or [], services or [], [], models or [])
    return [f"adapter '{action}' builds {entity} with undeclared '{field}'"
            for action, field, entity in found]


def _uncovered_cli_fields(documents):
    """`adapter requires a field no bound leaf flag supplies` messages, or [].

    The generator's own predicate, over CLI facades only: a GUI takes no
    flags by design. Step D owns surface-side misses (a flag the requirements
    name and no leaf declares); this fires the retry when the adapter side
    can move too — renaming the field to the flag, or decomposing a lone
    aggregate like a solitary `data`.
    """
    from kernel.codegen import action_targets, uncovered_required_fields

    if not isinstance(documents, dict):
        return []
    components = documents.get(COMPONENTS)
    facade = (components or {}).get("facade") if isinstance(components, dict) else {}
    if not isinstance(facade, dict) or facade.get("type") != "cli":
        return []
    invocation = facade.get("invocation")
    if not isinstance(invocation, dict):
        return []
    adapters = documents.get(INTERACTION_ADAPTERS) or []
    services = documents.get(SERVICE_CONTRACTS) or []
    models = documents.get(DATA_MODELS) or []
    entity_names = [m.get("name") for m in models
                    if isinstance(m, dict) and m.get("name")]
    targets = action_targets(adapters, services, [], entity_names)
    found = uncovered_required_fields(adapters, invocation, targets)
    return [f"adapter '{action}' requires '{field}' but no bound leaf flag supplies it"
            for action, field in found]


def _with_miss_note(requirements, messages, command_lines=()):
    """The requirements plus the previous attempt's misses, exactly as named.

    `command_lines` carries the requirements' own backtick-quoted command lines
    (CLI steps only): a summary like "the command 'member'" tells the model what
    is missing, but only the exact lines tell it the flags each verb takes —
    which is what the library retry needed and the summary alone did not give.
    """
    listed = "\n".join(f"- {message}" for message in messages)
    note = (
        f"{requirements}\n\nThe previous attempt was incomplete. "
        f"The following must be covered, exactly as named:\n{listed}\n"
    )
    lines = [line for line in command_lines if line]
    if lines:
        quoted = "\n".join(f"- `{line}`" for line in lines)
        note += f"\nThe exact command lines in the requirements are:\n{quoted}\n"
    return note


def _command_lines(requirements):
    """Every backtick-quoted span in the requirements, in order."""
    if not isinstance(requirements, str):
        return []
    return [span.strip() for span in re.findall(r"`([^`]*)`", requirements) if span.strip()]


def _entity_block(vocab):
    return prompts.entity_block(vocab) if vocab.entity_names else None


def _parse_document(text, key, log=None):
    """Parse a generated document, returning None when it is unusable.

    The parse is strict: the grammar guarantees bare JSON, so anything else is a
    real defect to report rather than to recover from. An experiment with the
    mask off (§9.31) is why no lenient path exists here — accepting a fence or
    trailing prose would be papering over a failure the grammar prevents.

    Diagnostics go through the run log (file always, terminal unless quiet),
    never straight to stderr: a raw print would bypass `--quiet` and appear
    beside the concise progress with no context.
    """
    def report(message):
        if log is not None:
            log.write(message)
        else:  # pragma: no cover - every live caller passes the run log
            print(message, file=sys.stderr)

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        report(f"[!] {key}: JSON error: {error}")
        return None
    if not isinstance(payload, dict) or key not in payload:
        report(f"[!] {key}: generated JSON has no '{key}' key")
        return None
    return payload[key]
