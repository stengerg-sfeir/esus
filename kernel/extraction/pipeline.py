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
        self._generate(
            INVARIANTS,
            prompts.invariants(requirements),
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
        """Step E: service names are new, so the grammar stays open."""
        vocab = vocabulary.Vocabulary(entities=self._entities())
        self._generate(
            SERVICE_CONTRACTS,
            prompts.service_contracts(requirements, _entity_block(vocab)),
            grammar_open.service_contracts(),
        )

    def _step_patterns(self):
        """Step F: classify invariants and contract methods into kernel patterns."""
        matches = classification.classify_documents(self.classifier, self.documents, self.log)
        self.documents[PATTERN_MATCHES] = matches

    def _step_adapters(self, requirements):
        """Step G: targets are closed to step E's services and step B's entities."""
        vocab = vocabulary.Vocabulary(entities=self._entities(), services=self._services())
        if not vocab.services:
            self.log.write("[!] step adapters: no services from step E — targets unconstrained")
        block = prompts.combined_block(vocab) if (vocab.services or vocab.entities) else None
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
        )
        if not vocab.entity_names and not vocab.crud_entities:
            self.log.write("[!] step persistence: no entities to persist — step skipped")
            return
        self._generate(
            PERSISTENCE_PORTS,
            prompts.persistence_ports(requirements, _entity_block(vocab)),
            grammar_persistence.persistence_ports(vocab),
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
