#!/usr/bin/env python3
"""Extract a software architecture from requirements, one step at a time.

Reads the requirements on stdin and writes one `<step>.json` per document into
the output directory, plus `run.log`. Each step is handed the names its
predecessors produced — in its prompt as an authoritative list, and in its GBNF
grammar as the only strings it can write — so the documents agree by
construction rather than by repair.

Usage:
    python3.12 extract_archi.py --model MODEL.gguf --output out/library \\
        < prompts/prompt_library_system.txt
"""

import argparse
import sys
from pathlib import Path

from kernel.extraction import pipeline as pipeline_module
from kernel.extraction import runner, writer


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True, help="Path to the GGUF model")
    parser.add_argument(
        "--output",
        required=True,
        help="Directory to write the step documents and run.log into",
    )
    parser.add_argument(
        "--context",
        type=int,
        default=8192,
        help="Context size in tokens (default 8192)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run the consistency checker over the output once the run finishes",
    )
    return parser


def main():
    args = build_parser().parse_args()

    requirements = sys.stdin.read().strip()
    if not requirements:
        print("error: no requirements were provided on stdin", file=sys.stderr)
        return 1

    output_dir = Path(args.output)
    log = writer.RunLog(output_dir / writer.RUN_LOG_NAME)
    log.write(f"[run] requirements: {len(requirements)} characters")

    extractor = runner.load_model(args.model, context_size=args.context, logits_all=False)
    classifier = runner.load_model(args.model, context_size=args.context, logits_all=True)

    pipeline = pipeline_module.Pipeline(extractor, classifier, log)
    documents = pipeline.run(requirements)

    for path in writer.write_documents(output_dir, documents):
        log.write(f"[write] {path}")

    tokens = sum(result.tokens for result in pipeline.results)
    seconds = sum(result.seconds for result in pipeline.results)
    log.write(
        f"[run] {len(pipeline.results)} steps, {tokens} generated tokens in {seconds:.1f}s"
    )
    log.flush()

    if args.check:
        return check_output(output_dir)
    return 0


def check_output(output_dir):
    """Run the consistency checker over a finished run."""
    from kernel.consistency import check_directory, render_report

    report = check_directory(str(output_dir), output_dir.name)
    print(render_report(report, show_all=True))
    errors, warnings = report.counts
    summary = f"consistency: {errors} error(s), {warnings} warning(s)"
    if report.notes:
        summary += f", {len(report.notes)} note(s)"
    print(summary)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
