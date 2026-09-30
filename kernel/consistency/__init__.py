"""Consistency checks for the JSON documents written by extract_archi.py."""

from kernel.consistency.checks_architecture import check_architecture_layer
from kernel.consistency.checks_domain import check_domain_layer
from kernel.consistency.loader import load_documents
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

    return report
