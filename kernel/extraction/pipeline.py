"""The extraction steps, run in order and chained.

Each step receives the names its predecessors actually produced, both in the
prompt (as an authoritative list) and in its grammar (as the only writable
strings). Steps whose predecessor produced nothing usable fall back to the
unconstrained grammar and say so in the log, so a degraded run is visible
rather than silent.
"""

import json
import sys

from kernel.extraction import (
    classification,
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

# A second attempt at a higher temperature, used only when a step returns
# something JSON rejects.
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


class Pipeline:
    """Runs steps A–H over one set of requirements."""

    def __init__(self, llm, classifier=None, log=None, classifier_factory=None):
        self.llm = llm
        # The classifier is a second `Llama` instance whose context is built with
        # `logits_all=True`, which step F's `logprobs` needs and every other step
        # would only pay for. It is therefore loaded on first use rather than at
        # startup — a program with no domain classifies nothing, and should not
        # load a second model to find that out. `classifier_factory` is that
        # deferred loader (see `extract_archi.py`); `classifier` stays accepted
        # for an already-built instance and in tests.
        self.classifier = classifier
        self.classifier_factory = classifier_factory
        self.log = log
        self.documents = {}
        self.results = []

    def run(self, requirements):
        # Kept so the post-contract error repair can consult the requirements — the
        # only authority on whether a declared-but-unraised error belongs.
        self.requirements = requirements
        self._step_intentions(requirements)
        self._step_data_models(requirements)
        self._step_errors(requirements)
        self._step_invariants(requirements)
        self._step_components(requirements)
        self._step_contracts(requirements)
        self._repair_errors()
        self._step_patterns()
        self._step_adapters(requirements)
        self._step_persistence(requirements)
        return self.documents

    def _generate(self, key, prompt, grammar_text, temperature=0.1):
        """Validate the grammar, generate, and store the document under `key`.

        One unusable document used to cost the whole run: library's missing
        components.json and every downstream warning came from a single
        malformed step. A grammar-constrained step fails only when the model
        writes something the grammar permits but JSON rejects, so one retry at a
        higher temperature recovers it cheaply.
        """
        grammar_check.assert_valid(grammar_text, label=f"step {key}")

        body = None
        # The ceiling the retry runs under. It starts as None, meaning the
        # first-attempt ceiling of `MAX_NEW_TOKENS`.
        retry_budget = None
        for attempt, attempt_temperature in enumerate((temperature, RETRY_TEMPERATURE)):
            result = runner.generate(
                self.llm, prompt, grammar_text, key,
                temperature=attempt_temperature,
                max_new_tokens=retry_budget,
            )
            self.results.append(result)
            self.log.write(result.describe())

            body = _parse_document(result.text, key)
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
        self._generate(
            DATA_MODELS,
            prompts.data_models(requirements, grounding),
            grammar_open.data_models(),
        )

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
        self._generate(
            COMPONENTS,
            prompts.components(requirements, prompts.components_block(vocab)),
            grammar_builders.components(vocab),
        )

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
        body = self._generate(
            SERVICE_CONTRACTS,
            prompts.service_contracts(requirements, prompts.requirements_block(vocab)),
            grammar_open.service_contracts(),
        )
        # A signature is a specification the generated body must honour, so a
        # method that returns `dict[str, object]` where the entity is known is a
        # defect no generation can repair without overriding the contract.
        if isinstance(body, list):
            self.documents[SERVICE_CONTRACTS] = return_types.repair_contract_returns(
                body, self._entities(), self.log
            )

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

        The classifier model is loaded here, on the first run that actually has
        something to classify, rather than at startup. Its context is built with
        `logits_all=True` — the pattern classifier reads per-token `logprobs`,
        which nothing else needs — so it is a second full model load, and a
        program with no domain (hello, cli_tool) must not pay for one it will
        never call. Building it here means a no-domain run loads one model.
        """
        items = classification.classification_items(self.documents)
        if not items:
            self.log.write("[ok] step patterns: nothing to classify")
            self.documents[PATTERN_MATCHES] = []
            return
        if self.classifier is None and self.classifier_factory is not None:
            self.classifier = self.classifier_factory()
        matches = classification.classify_documents(self.classifier, self.documents, self.log)
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
        self._generate(
            INTERACTION_ADAPTERS,
            prompts.adapters(requirements, block),
            grammar_builders.adapters(vocab),
        )
        adapters = self.documents.get(INTERACTION_ADAPTERS)
        if isinstance(adapters, list):
            # A transform that contradicts the field's name — a count converted
            # to cents, a single name read as a list — is not expressible in the
            # grammar (transform is an enum, the name is free text), so it is
            # removed here, reusing the checker's own predicate (§9.28).
            repairs.repair_adapter_transforms(adapters, self.log)

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
        # Repaired after unification so the figure logged is what the document
        # actually ends up with, and so a repository only step H declares is
        # covered too.
        self.documents[PERSISTENCE_PORTS] = return_types.repair_port_returns(
            unified, self._entities(), self.log
        )


def persistence_required(components):
    """True when step D asked for persistence."""
    if not isinstance(components, dict):
        return False
    persistence = components.get("persistence")
    return isinstance(persistence, dict) and persistence.get("required") is True


def _entity_block(vocab):
    return prompts.entity_block(vocab) if vocab.entity_names else None


def _parse_document(text, key):
    """Parse a generated document, returning None when it is unusable.

    The parse is strict: the grammar guarantees bare JSON, so anything else is a
    real defect to report rather than to recover from. An experiment with the
    mask off (§9.31) is why no lenient path exists here — accepting a fence or
    trailing prose would be papering over a failure the grammar prevents.
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        print(f"[!] {key}: JSON error: {error}", file=sys.stderr)
        return None
    if not isinstance(payload, dict) or key not in payload:
        print(f"[!] {key}: generated JSON has no '{key}' key", file=sys.stderr)
        return None
    return payload[key]
