"""Consistency checks for the domain layer.

Runs the per-document checks over intentions, invariants, data models,
components and service contracts, and returns the facts the architecture
checks need in order to resolve names.
"""

from dataclasses import dataclass, field

from kernel.consistency.checks_components import check_components
from kernel.consistency.checks_contracts import check_service_contracts
from kernel.consistency.checks_models import check_data_models
from kernel.consistency.checks_phrases import check_phrase_list
from kernel.consistency.naming import EntityIndex


@dataclass
class DomainFacts:
    """What the domain checks learned, for the architecture checks to reuse."""

    entities: EntityIndex = field(default_factory=EntityIndex)
    crud_entities: tuple = ()


def check_domain_layer(documents, report):
    """Run every domain check and return a DomainFacts."""
    entities = check_data_models(documents.get("data_models"), report)
    check_phrase_list(documents.get("intentions"), "intentions", report)
    check_phrase_list(documents.get("invariants"), "invariants", report)
    crud_entities = check_components(documents.get("components"), entities, report)
    check_service_contracts(documents.get("service_contracts"), report)
    return DomainFacts(entities=entities, crud_entities=crud_entities)
