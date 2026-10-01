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
    runner,
    vocabulary,
)

# A second attempt at a higher temperature, used only when a step returns
# something JSON rejects.
RETRY_TEMPERATURE = 0.35

# Document keys, which are also the top-level JSON keys the checker reads.
INTENTIONS = "intentions"
DATA_MODELS = "data_models"
INVARIANTS = "invariants"
COMPONENTS = "components"
SERVICE_CONTRACTS = "service_contracts"
PATTERN_MATCHES = "pattern_matches"
INTERACTION_ADAPTERS = "interaction_adapters"
PERSISTENCE_PORTS = "persistence_ports"


class Pipeline:
    """Runs steps A–H over one set of requirements."""

    def __init__(self, llm, classifier, log):
        self.llm = llm
        self.classifier = classifier
        self.log = log
        self.documents = {}
        self.results = []

    def run(self, requirements):
        self._step_intentions(requirements)
        self._step_data_models(requirements)
        self._step_invariants(requirements)
        self._step_components(requirements)
        self._step_contracts(requirements)
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
        for attempt, attempt_temperature in enumerate((temperature, RETRY_TEMPERATURE)):
            result = runner.generate(
                self.llm, prompt, grammar_text, key, temperature=attempt_temperature
            )
            self.results.append(result)
            self.log.write(result.describe())
            if result.truncated:
                self.log.write(
                    f"[!] step {key} hit the token ceiling — its document may be incomplete"
                )

            body = _parse_document(result.text, key)
            if body is not None:
                break
            if attempt == 0:
                self.log.write(f"[!] step {key} produced unusable JSON — retrying once")

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
        self._generate(
            DATA_MODELS,
            prompts.data_models(requirements),
            grammar_open.data_models(),
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
            grammar_open.phrase_list(INVARIANTS),
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
        )
        # E owns the repositories it declares, so it must be told which
        # operations each entity needs — otherwise it writes "standard CRUD"
        # from an adjective rather than from the list, and every delete is lost.
        self._generate(
            SERVICE_CONTRACTS,
            prompts.service_contracts(requirements, prompts.requirements_block(vocab)),
            grammar_open.service_contracts(),
        )

    def _step_patterns(self):
        """Step F: classify invariants and contract methods into kernel patterns."""
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
        self.documents[PERSISTENCE_PORTS] = interfaces.unify_repository_interfaces(
            body, self.documents.get(SERVICE_CONTRACTS), self.log
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
    """Parse a generated document, returning None when it is unusable."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        print(f"[!] {key}: JSON error: {error}", file=sys.stderr)
        return None
    if not isinstance(payload, dict) or key not in payload:
        print(f"[!] {key}: generated JSON has no '{key}' key", file=sys.stderr)
        return None
    return payload[key]
