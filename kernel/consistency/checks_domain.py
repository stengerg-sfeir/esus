"""Consistency checks for the domain layer.

Runs the per-document checks over intentions, invariants, data models,
components and service contracts, and returns the facts the architecture
checks need in order to resolve names.
"""

from dataclasses import dataclass, field

from kernel.consistency.checks_components import check_components
from kernel.consistency.checks_contracts import check_service_contracts
from kernel.consistency.checks_errors import (
    check_duplicate_error_subject,
    check_errors,
    check_raises,
    check_unreachable_not_found,
)
from kernel.consistency.checks_invariants import check_invariant_claims
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
    # An invariant can name a field and claim an attribute of it; the data model
    # declares that attribute, so the two can be compared.
    check_invariant_claims(documents.get("invariants"), entities, report)
    crud_entities = check_components(documents.get("components"), entities, report)
    # The registry first: a contract method's `raises` is resolved against it, so
    # the names have to be known before the references can be judged.
    error_names = check_errors(documents.get("errors"), report)
    check_service_contracts(documents.get("service_contracts"), report)
    check_raises(documents.get("service_contracts"), error_names, report)
    # Two sharper error checks, both stated in names rather than guessed: an
    # error for a missing record that the method reading it never raises, and two
    # names for the same missing record.
    check_unreachable_not_found(
        documents.get("errors"), documents.get("service_contracts"), error_names, report
    )
    check_duplicate_error_subject(documents.get("errors"), error_names, report)
    return DomainFacts(entities=entities, crud_entities=crud_entities)
