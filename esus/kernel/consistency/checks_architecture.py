"""Consistency checks for the architecture layer.

Runs the persistence and adapter checks, which are the two documents that
reference the domain layer and the service contracts by name.
"""

from kernel.consistency.checks_adapters import check_interaction_adapters
from kernel.consistency.checks_crud import check_crud_coverage
from kernel.consistency.checks_interfaces import check_interface_agreement
from kernel.consistency.checks_patterns import check_pattern_matches
from kernel.consistency.checks_persistence import check_persistence_ports, check_persistence_presence


def check_architecture_layer(documents, facts, report):
    """Run every architecture check against the loaded documents."""
    check_persistence_presence(documents, report)
    check_persistence_ports(documents.get("persistence_ports"), facts, report)
    check_interface_agreement(documents, report)
    check_crud_coverage(documents.get("components"), documents, report)
    check_pattern_matches(documents.get("pattern_matches"), documents, report)
    check_interaction_adapters(
        documents.get("interaction_adapters"),
        documents.get("service_contracts"),
        facts,
        report,
    )
