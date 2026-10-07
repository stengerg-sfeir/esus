"""Consistency checks for the JSON documents written by extract_archi.py."""

from kernel.consistency.checks_architecture import check_architecture_layer
from kernel.consistency.checks_domain import check_domain_layer
from kernel.consistency.checks_surface import check_surface_coverage
from kernel.consistency.loader import load_documents, load_requirements
from kernel.consistency.report import Report, render_grand_total, render_report

__all__ = [
    "Report",
    "check_directory",
    "render_grand_total",
    "render_report",
]


def check_directory(output_dir, prompt_name):
    """Run every check over one extraction output directory.

    Returns a Report; documents that cannot be loaded are reported as findings
    and skipped, so a broken file never prevents the remaining checks.
    """
    report = Report(prompt_name)
    documents = load_documents(output_dir, report)

    facts = check_domain_layer(documents, report)
    check_architecture_layer(documents, facts, report)

    # Last, because it compares a document with the prose the run was given
    # rather than with another document — the one check that can see a command
    # the requirements name and the surface never recorded. It runs only when
    # the run stored its requirements, so an older output directory is not
    # reported for a file it could not have written.
    requirements = load_requirements(output_dir)
    if requirements:
        check_surface_coverage(documents.get("components"), requirements, report)

    return report
