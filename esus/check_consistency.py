#!/usr/bin/env python3
"""Cross-check the internal consistency of extract_arch.py output.

Each directory passed to --dirs is given as "name:path" and must hold the
per-step JSON documents written by extract_arch.py. The exit code is 0 when no
error was found and 1 otherwise.

Usage:
    python check_consistency.py --dirs hello:out/hello library:out/library
"""

import argparse
import sys

from kernel.consistency import check_directory, render_grand_total, render_report

USAGE_FORMAT = "NAME:PATH"


def parse_directory_argument(entry):
    """Split a 'name:path' argument into its two parts."""
    name, separator, path = entry.partition(":")
    if not separator or not name.strip() or not path.strip():
        raise argparse.ArgumentTypeError(f"expected '{USAGE_FORMAT}', got '{entry}'")
    return name.strip(), path.strip()


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dirs",
        nargs="+",
        required=True,
        type=parse_directory_argument,
        metavar=USAGE_FORMAT,
        help="One or more output directories to check (format: name:path).",
    )
    parser.add_argument(
        "--all-findings",
        action="store_true",
        dest="show_all",
        help="List every finding instead of truncating long sections.",
    )
    return parser


def main():
    args = build_parser().parse_args()

    reports = [check_directory(path, name) for name, path in args.dirs]

    for report in reports:
        print(render_report(report, show_all=args.show_all))
    print(render_grand_total(reports))

    total_errors = sum(report.counts[0] for report in reports)
    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())
