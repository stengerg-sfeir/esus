#!/usr/bin/env python3
"""Extract a software architecture from requirements, one step at a time.

Reads the requirements on stdin (or --requirements PATH) and writes one
`<step>.json` per document into the output directory, plus `run.log`. Each
step is handed the names its predecessors produced — in its prompt as an
authoritative list, and in its GBNF grammar as the only strings it can
write — so the documents agree by construction rather than by repair.

With --chat, the run continues after writing: the probe judges the output,
and the tie and alias reviews ask about whatever needs a human, right here —
one entry point for the attended pipeline.

Usage:
    python3.12 extract_arch.py --model MODEL.gguf --output out/library \\
        < prompts/prompt_library_system.txt
    python3.12 extract_arch.py --model MODEL.gguf --output out/library \\
        --requirements prompts/prompt_library_system.txt --chat
"""

import argparse
import os
import sys
from pathlib import Path

from kernel.extraction import pipeline as pipeline_module
from kernel.extraction import runner, writer
from kernel.extraction.aliases import apply_aliases, apply_model_fields, load_aliases
from kernel.extraction.decisions import apply_decisions, load_decisions
from review_surface import apply_surface_decisions, load_surface_decisions


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=False, help="Path to the GGUF model")
    parser.add_argument(
        "--output",
        required=True,
        help="Directory to write the step documents and run.log into",
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Apply the deterministic document repairs to an existing output "
             "(no model run); used to heal archived documents after a repair "
             "rule changes",
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
    parser.add_argument(
        "--requirements",
        default=None,
        metavar="PATH",
        help="Read requirements from PATH instead of stdin (required for "
             "--chat, so stdin stays free for answers)",
    )
    parser.add_argument(
        "--chat",
        action="store_true",
        help="After writing, loop: probe, review what needs a human, resume "
             "the earliest step that can heal the rest — keeping a strictly "
             "better state or rolling back — until clean, stuck, or 3 rounds",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Print only the step plan (name: description), one result line "
             "per step, questions, and the final SUMMARY — full detail stays "
             "in run.log",
    )
    parser.add_argument(
        "--from-step",
        default=None,
        choices=(
            pipeline_module.INTENTIONS,
            pipeline_module.DATA_MODELS,
            pipeline_module.ERRORS,
            pipeline_module.INVARIANTS,
            pipeline_module.COMPONENTS,
            pipeline_module.SERVICE_CONTRACTS,
            pipeline_module.PATTERN_MATCHES,
            pipeline_module.INTERACTION_ADAPTERS,
            pipeline_module.PERSISTENCE_PORTS,
        ),
        help="Resume at one step, chaining from the archived documents instead "
             "of rerunning the whole pipeline (requirements are read from the "
             "output directory's requirements.txt, not stdin)",
    )
    return parser


def resolve_requirements(args):
    """The requirements text from --requirements or stdin, or None when empty."""
    if args.requirements is not None:
        try:
            text = Path(args.requirements).read_text(encoding="utf-8").strip()
        except OSError as error:
            print(f"error: cannot read {args.requirements}: {error}", file=sys.stderr)
            return None
        if not text:
            print(f"error: {args.requirements} is empty", file=sys.stderr)
            return None
        return text
    text = sys.stdin.read().strip()
    if not text:
        print("error: no requirements were provided on stdin", file=sys.stderr)
        return None
    return text


# The pipeline plan a --quiet run prints up front: step name and what it
# produces. Keys match `pipeline_module` document names; `errors_repair` is a
# deterministic fix, not a model call, and prints as such.
STEP_PLAN = (
    ("intentions", "the program's own phrases from the requirements"),
    ("data_models", "entities and their fields"),
    ("errors", "application error types"),
    ("invariants", "rules the program must always hold"),
    ("components", "CLI surface and CRUD services"),
    ("service_contracts", "service methods with params and raises"),
    ("errors_repair", "deterministic error-registry fix (no model call)"),
    ("pattern_matches", "pattern classification of invariants and methods"),
    ("interaction_adapters", "CLI input to service-method mapping"),
    ("persistence_ports", "repository interfaces for the entities"),
)

# A per-step generation result, as `StepResult.describe` writes it:
# `[components] 2310 tokens in 76.3s (30.3 tok/s)`, plus the run totals line
# `[run] 11 steps, 18409 generated tokens in 621.2s` — and only that `[run]`
# line, never the requirements/temperature preamble.
STEP_RESULT = __import__("re").compile(r"^\[.+\] \d+ tokens in .*tok/s")
RUN_TOTALS = __import__("re").compile(r"^\[run\] \d+ steps, \d+ generated tokens in ")


def print_step_plan(out_fn=print, start=None):
    """The steps, one `name: description` line each — the quiet header.

    A resume (`--from-step`) continues a plan already shown by its parent
    run, so it prints nothing: without this every chat-loop round repeats
    the same ten lines.
    """
    if start is not None:
        return
    out_fn("steps:")
    for name, description in STEP_PLAN:
        out_fn(f"  {name}: {description}")


def print_quiet_results(log, out_fn=print):
    """One result line per generation plus the totals; detail stays in run.log."""
    for line in log.lines:
        if STEP_RESULT.match(line) or RUN_TOTALS.match(line):
            out_fn(line)


def chat_flow(output_dir, out_fn=print, tie_runner=None, alias_runner=None,
              surface_runner=None, slot_runner=None, contract_runner=None):
    """Probe, ask, re-probe: the attended tail of an extraction run.

    Runs the probe over `output_dir`; when ties need a human, runs the tie
    review, surface duplicates get the surface review, field pairs the alias
    review, pattern slots the slot review, and method behavior facts the
    contract review. Structural blockers (missing commands, uncovered
    fields, unknown model fields) are reported, never asked — no answer the
    user can type fixes those; a rerun or a code fix does. Returns the
    remaining blockers (a list — the loop judges them without re-probing).
    `*_runner` override the reviews (output_dir -> (asked, answered)) for
    tests.
    """
    import probe_readiness
    import review_aliases
    import review_contracts
    import review_slots
    import review_surface
    import review_ties

    name = os.path.basename(str(output_dir).rstrip(os.sep))
    blockers, _, _ = probe_readiness.check_prompt(name, str(output_dir))
    questions = probe_readiness.open_questions(str(output_dir))
    if questions:
        out_fn(f"{questions} tie(s) need a human — starting the tie review")
        (tie_runner or review_ties.run_review)(str(output_dir))
    duplicates, _ = review_surface.collect_duplicates(str(output_dir))
    # A declared flag that selects nothing is a surface question too
    # (`member list -active-only` parsed and printed every member). It is
    # not a duplicate node, so the old duplicate-only test skipped it and
    # the chat loop never asked. Ask both kinds through the one review.
    routes, _ = review_surface.collect_routes(str(output_dir))
    surface_questions = len(duplicates) + len(routes)
    if surface_questions:
        out_fn(f"{surface_questions} surface node/flag(s) need a human — "
               f"starting the surface review")
        (surface_runner or review_surface.run_review)(str(output_dir))
    pairs, _ = review_aliases.collect_questions(str(output_dir))
    if pairs:
        out_fn(f"{len(pairs)} field mapping(s) need a human — starting the alias review")
        (alias_runner or review_aliases.run_review)(str(output_dir))
    slot_questions, _ = review_slots.collect_slots(str(output_dir))
    if slot_questions:
        out_fn(f"{len(slot_questions)} pattern slot(s) need a human — "
               f"starting the slot review")
        (slot_runner or review_slots.run_review)(str(output_dir))
    contract_questions, _ = review_contracts.collect_contracts(str(output_dir))
    if contract_questions:
        out_fn(f"{len(contract_questions)} method contract(s) need a human — "
               f"starting the contract review")
        (contract_runner or review_contracts.run_review)(str(output_dir))
    final, _, _ = probe_readiness.check_prompt(name, str(output_dir))
    out_fn(f"chat: {len(final)} blocker(s) remain")
    for finding in final:
        out_fn(f"  - [{finding.rule}] {finding.message}")
    return final


def repair_existing(output_dir):
    """Re-run the deterministic repairs over archived documents, no model.

    The repairs are part of extraction, not a hand edit: they add a missing
    optional flag the requirements name, expose a required adapter field on
    the leaf that can supply it, and drop placeholders/duplicate surface
    nodes. This path exists so a repair-rule change can heal an existing
    extraction without regenerating its model-written content.
    """
    from kernel.consistency.loader import load_documents, load_requirements
    from kernel.consistency.report import Report
    from kernel.extraction import repairs

    directory = Path(output_dir)
    report = Report(directory.name)
    documents = load_documents(str(directory), report).bodies
    if report.errors:
        print(f"error: {directory} holds unusable documents:", file=sys.stderr)
        for finding in report.errors:
            print(f"  {finding.render()}", file=sys.stderr)
        return 1
    requirements = load_requirements(str(directory))
    if not requirements:
        print(f"error: {directory} has no requirements.txt", file=sys.stderr)
        return 1

    log = writer.RunLog(None)
    components = documents.get(pipeline_module.COMPONENTS)
    models = documents.get(pipeline_module.DATA_MODELS)
    adapters = documents.get(pipeline_module.INTERACTION_ADAPTERS)
    services = documents.get(pipeline_module.SERVICE_CONTRACTS)
    if isinstance(components, dict):
        repairs.repair_missing_surface(components, requirements, models, log)
        repairs.repair_placeholder_subcommands(components, log)
        repairs.repair_flat_command_duplicates(components, log)
    if isinstance(adapters, list):
        repairs.repair_adapter_transforms(adapters, log)
        repairs.repair_adapter_targets(adapters, services, log)
        repairs.repair_adapter_field_names(adapters, services, models, log)
        repairs.repair_missing_adapter_flags(
            components, adapters, services, models, log)
        repairs.repair_missing_filter_actions(
            components, adapters, services, models, log)
    if isinstance(components, dict):
        decisions = load_surface_decisions(directory)
        if decisions:
            documents[pipeline_module.COMPONENTS] = apply_surface_decisions(
                components, decisions, log, requirements_text=requirements)
    for path in writer.write_documents(directory, documents):
        print(f"[write] {path}")
    return 0


def main():
    args = build_parser().parse_args()
    return run(args)


def run(args):
    """One extraction round (initial or resume); returns the exit code."""

    output_dir = Path(args.output)
    if getattr(args, "repair", False):
        return repair_existing(output_dir)
    if not args.model:
        print("error: --model is required unless --repair is used", file=sys.stderr)
        return 2
    start = args.from_step
    if args.chat and args.requirements is None and start is None:
        # Questions arrive over stdin: a piped requirements text would leave
        # every question at EOF, silently skipping the whole point of --chat.
        print("error: --chat needs --requirements PATH (stdin stays free for answers)",
              file=sys.stderr)
        return 2
    if start is None:
        requirements = resolve_requirements(args)
        if requirements is None:
            return 1
        preloaded = {}
    else:
        # Resuming: the archived requirements are the run's own, so the rerun
        # judges itself against what it was actually given — never against a
        # retyped prompt on stdin.
        from kernel.consistency.loader import load_documents, load_requirements
        from kernel.consistency.report import Report

        requirements = load_requirements(str(output_dir))
        if not requirements:
            print(f"error: {output_dir} has no requirements.txt to resume from",
                  file=sys.stderr)
            return 1
        report = Report(output_dir.name)
        preloaded = load_documents(str(output_dir), report).bodies
        if report.errors:
            print(f"error: {output_dir} holds unusable documents:",
                  file=sys.stderr)
            for finding in report.errors:
                print(f"  {finding.render()}", file=sys.stderr)
            return 1

    log = writer.RunLog(output_dir / writer.RUN_LOG_NAME,
                        quiet=getattr(args, "quiet", False))
    if getattr(args, "quiet", False):
        print_step_plan(start=start)
    log.write(f"[run] requirements: {len(requirements)} characters")
    log.write(f"[run] temperature={pipeline_module.TEMPERATURE} seed={pipeline_module.SEED}")
    if start is not None:
        log.write(f"[run] resuming at step {start} from archived documents")
        # RunLog overwrites on flush: carry the earlier rounds forward, or
        # every resume erases the history that explains the current documents.
        try:
            previous = (output_dir / writer.RUN_LOG_NAME).read_text(encoding="utf-8").splitlines()
        except OSError:
            previous = []
        if previous:
            log.lines[:0] = previous + ["[run] --- resumed ---"]

    extractor = runner.load_model(args.model, context_size=args.context,
                                    logits_all=False,
                                    quiet=getattr(args, "quiet", False))

    # Step F reads last-token logits from the extractor's own context, so the
    # GGUF is loaded once. The high-level `logprobs` API would need a second
    # `logits_all=True` context; `_next_token_logprobs` avoids that.
    pipeline = pipeline_module.Pipeline(
        extractor,
        log=log,
        progress_fn=lambda name, summary: print(f"{name}: {summary}"),
    )
    pipeline.documents.update(preloaded)
    documents = pipeline.run(requirements, start=start)

    # A human decision outranks a coin flip: re-apply the recorded answers to
    # near-tied classifications, so one review settles each tie permanently.
    recorded = load_decisions(output_dir)
    if recorded and isinstance(documents.get(pipeline_module.PATTERN_MATCHES), list):
        documents[pipeline_module.PATTERN_MATCHES] = apply_decisions(
            documents[pipeline_module.PATTERN_MATCHES], recorded, log,
            requirements_text=requirements,
        )

    # Human-asserted field mappings outrank flag spellings the model chose:
    # one recorded alias settles each pair permanently, like decisions do.
    mapped = load_aliases(output_dir)
    if mapped and isinstance(documents.get(pipeline_module.INTERACTION_ADAPTERS), list):
        documents[pipeline_module.INTERACTION_ADAPTERS] = apply_aliases(
            documents[pipeline_module.INTERACTION_ADAPTERS], mapped, log,
            requirements_text=requirements,
        )
    if mapped and isinstance(documents.get(pipeline_module.DATA_MODELS), list):
        documents[pipeline_module.DATA_MODELS] = apply_model_fields(
            documents[pipeline_module.DATA_MODELS], mapped, log,
            requirements_text=requirements,
        )

    # A human surface deletion outranks a regenerated duplicate: reruns
    # rebuild the duplicate from the same ambiguous line, so the recorded
    # keeper is re-applied while the prompt stands.
    dropped = load_surface_decisions(output_dir)
    if dropped and isinstance(documents.get(pipeline_module.COMPONENTS), dict):
        documents[pipeline_module.COMPONENTS] = apply_surface_decisions(
            documents[pipeline_module.COMPONENTS], dropped, log,
            requirements_text=requirements,
        )

    for path in writer.write_documents(output_dir, documents):
        log.write(f"[write] {path}")
    # The requirements accompany the documents so the checker can later compare
    # the recorded surface against what was actually asked for.
    log.write(f"[write] {writer.write_requirements(output_dir, requirements)}")

    tokens = sum(result.tokens for result in pipeline.results)
    seconds = sum(result.seconds for result in pipeline.results)
    log.write(
        f"[run] {len(pipeline.results)} steps, {tokens} generated tokens in {seconds:.1f}s"
    )
    log.flush()
    if getattr(args, "quiet", False):
        print_quiet_results(log)

    if args.check:
        status = check_output(output_dir, quiet=getattr(args, "quiet", False))
    else:
        status = 0
    if args.chat:
        remaining = chat_loop(
            output_dir,
            lambda start: resume_in_subprocess(args, output_dir, start),
            out_fn=print,
        )
        return 1 if remaining or status else 0
    return status


# --------------------------------------------------------------------------
# chat loop: probe, review, resume — keeping better, rolling back worse
# --------------------------------------------------------------------------

ROUND_LIMIT = 3

# Resume attempts per round: both crashes seen so far landed in classifier
# decode (llama_decode -3, transient Metal state) and succeeded on the next
# run, so a crashed resume is retried rather than aborting the session.
# Retries run as fresh child processes (see resume_in_subprocess): reloading
# beside a crashed decode fails with pressure errors, so in-process retry
# would poison its own well.
RESUME_ATTEMPTS = 2

# Findings a rerun can heal, mapped to the earliest step that owns them. A
# rule absent here (malformed documents, placeholders, duplicate names) is
# not a coverage miss but a structural defect: no round of generation fixes
# it, so the loop stops and reports instead of burning model calls.
RULE_STEPS = {
    "missing_command": pipeline_module.COMPONENTS,
    "missing_flag": pipeline_module.COMPONENTS,
    "unbacked_command": pipeline_module.COMPONENTS,
    "non_unique_primary_key": pipeline_module.DATA_MODELS,
    "unmet_crud_operation": pipeline_module.SERVICE_CONTRACTS,
    "uncovered_field": pipeline_module.INTERACTION_ADAPTERS,
    "unknown_model_field": pipeline_module.INTERACTION_ADAPTERS,
}
STEP_ORDER = (
    pipeline_module.DATA_MODELS,
    pipeline_module.COMPONENTS,
    pipeline_module.SERVICE_CONTRACTS,
    pipeline_module.INTERACTION_ADAPTERS,
)


def resume_in_subprocess(args, output_dir, start):
    """One resume round in a child process; raise on failure.

    Model runs are isolated per attempt on purpose: a crashed decode can
    leave Metal state unusable, and reloading beside the wreckage fails
    with pressure errors (`Failed to load model`) that look like missing
    files. The child inherits stdio, so its run.log lines stream live, and
    anything it leaves behind dies with it — the loop's snapshot decides
    what survives, never a half-written directory.
    """
    import subprocess

    script = Path(__file__).resolve().parent / "extract_arch.py"
    cmd = [sys.executable, str(script),
           "--model", args.model, "--output", str(output_dir),
           "--context", str(args.context), "--from-step", start]
    if getattr(args, "quiet", False):
        cmd.append("--quiet")
    completed = subprocess.run(cmd)
    if completed.returncode != 0:
        raise RuntimeError(f"resume exited {completed.returncode}")


def resume_step_for(blockers):
    """The earliest pipeline step that can heal one of these findings, or None."""
    steps = {RULE_STEPS[finding.rule] for finding in blockers if finding.rule in RULE_STEPS}
    if not steps:
        return None
    return min(steps, key=STEP_ORDER.index)


def snapshot_output(output_dir):
    """Copy the output dir aside for rollback; return the snapshot path."""
    output_dir = Path(output_dir)
    snapshot = output_dir.parent / f".chat_snapshot_{output_dir.name}"
    import shutil

    if snapshot.is_dir():
        shutil.rmtree(snapshot)
    shutil.copytree(output_dir, snapshot)
    return snapshot


def restore_snapshot(snapshot, output_dir):
    """Roll back to the snapshot, keeping the snapshot itself as evidence."""
    import shutil

    shutil.rmtree(output_dir)
    shutil.copytree(snapshot, output_dir)


def report_verdict(output_dir, out_fn=print):
    """One explicit tail: GENERATABLE yes/no, with the reasons, or the blocker list.

    The pipeline log narrates repairs and retries; this is the only line that
    answers the question the run was for. Blockers (with rules) come from the
    probe; open ties come from the probe's question list. Both print even when
    empty, so `GENERATABLE: YES` is never the absence of a message.
    Returns the blocker count.
    """
    import probe_readiness

    name = os.path.basename(str(output_dir).rstrip(os.sep))
    blockers, _, _ = probe_readiness.check_prompt(name, str(output_dir))
    questions = probe_readiness.open_questions(str(output_dir))
    out_fn("==== SUMMARY ====")
    out_fn(f"blockers: {len(blockers)}, open tie(s): {questions}")
    if not blockers and not questions:
        out_fn("GENERATABLE: YES — `generator.py` can run on this output")
    else:
        out_fn("GENERATABLE: NO — `generator.py` will refuse this output")
        for finding in blockers:
            out_fn(f"  - [{finding.rule}] {finding.message}")
        if questions:
            out_fn(f"  - {questions} tie(s) still need a human answer "
                   f"(`review_ties.py`)")
    return len(blockers)


def chat_loop(output_dir, rerun, out_fn=print, max_rounds=ROUND_LIMIT,
              tie_runner=None, alias_runner=None, surface_runner=None,
              slot_runner=None):
    """Probe, review, resume — until clean, stuck, or out of rounds.

    `rerun(start)` performs one model round from `start` (raising on crash).
    Each round keeps a strictly better state or rolls back to the snapshot:
    the loop can never leave the documents worse than it found them, and it
    always terminates — 0 blockers, nothing rerunnable, a crash, a
    non-improving round, or `max_rounds`. Returns remaining blockers.
    """
    import probe_readiness

    name = os.path.basename(str(output_dir).rstrip(os.sep))
    current = None
    for _ in range(max(1, max_rounds)):
        blockers = chat_flow(output_dir, out_fn=out_fn,
                             tie_runner=tie_runner, alias_runner=alias_runner,
                             surface_runner=surface_runner,
                             slot_runner=slot_runner)
        if not blockers:
            report_verdict(output_dir, out_fn=out_fn)
            return 0
        step = resume_step_for(blockers)
        if step is None:
            out_fn("chat: remaining blockers need more than a rerun "
                   "(see rules above) — stopping")
            report_verdict(output_dir, out_fn=out_fn)
            return len(blockers)
        snapshot = snapshot_output(output_dir)
        before = len(blockers)
        try:
            attempt_resume(rerun, step, out_fn)
        except Exception as error:
            restore_snapshot(snapshot, output_dir)
            out_fn(f"chat: resume crashed twice ({error}) — rolled back to {before} blocker(s); "
                   f"pre-round state kept at {snapshot}")
            report_verdict(output_dir, out_fn=out_fn)
            return before
        after, _, _ = probe_readiness.check_prompt(name, str(output_dir))
        current = after
        if len(after) < before:
            out_fn(f"chat: round improved {before}->{len(after)} — continuing")
            _drop_snapshot(snapshot)
            continue
        restore_snapshot(snapshot, output_dir)
        out_fn(f"chat: round did not improve ({before}->{len(after)}) — "
               f"rolled back, keeping {before} blocker(s); pre-round state kept at {snapshot}")
        report_verdict(output_dir, out_fn=out_fn)
        return before
    out_fn(f"chat: {max_rounds} rounds done — stopping")
    report_verdict(output_dir, out_fn=out_fn)
    return len(current) if current is not None else 0


def attempt_resume(rerun, step, out_fn=print, attempts=RESUME_ATTEMPTS):
    """Run one resume round, retrying a crashed attempt.

    Raises the last error when every attempt crashes, so the caller rolls
    back to the snapshot instead of continuing on a half-written directory.
    """
    error = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            rerun(step)
            return
        except Exception as exc:
            error = exc
            if attempt < max(1, attempts):
                out_fn(f"chat: resume crashed ({error}) — retrying the resume "
                       f"({attempt + 1}/{max(1, attempts)})")
    raise error


def _drop_snapshot(snapshot):
    import shutil

    shutil.rmtree(snapshot, ignore_errors=True)


def check_output(output_dir, quiet=False):
    """Run the consistency checker over a finished run."""
    from kernel.consistency import check_directory, render_report

    report = check_directory(str(output_dir), output_dir.name)
    if not quiet:
        print(render_report(report, show_all=True))
    errors, warnings = report.counts
    summary = f"consistency: {errors} error(s), {warnings} warning(s)"
    if report.notes:
        summary += f", {len(report.notes)} note(s)"
    print(summary)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
