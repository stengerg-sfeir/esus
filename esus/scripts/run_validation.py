"""Run ESUS extraction over the validation prompt set and record metrics.

This is the local/Kaggle entry point used by the validation notebook.  It
runs one extraction per prompt, keeps every output directory, and writes a
per-prompt `metrics.json` plus combined `summary.json`/`summary.csv`.

The classification is intentionally conservative:

- `direct`: extraction says GENERATABLE: YES with zero blockers and zero ties;
- `review`: the remaining blockers are `open_human_review` or
  `ignored_cli_option`, or only unresolved ties remain;
- `not_generatable`: any other blocker, a crash, or a timeout.

The exact rule list is kept in each result so the classification can be
audited later.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROMPTS = ROOT / "prompts" / "validation"
DEFAULT_RUN_ROOT = ROOT / "out" / "validation" / "runs"

TIMING_RE = re.compile(
    r"^\[([^\]]+)\] (\d+) tokens in ([\d.]+)s "
    r"\(([\d.]+) tok/s, ([\d.]+) decode, (\d+) prompt\)",
    re.M,
)
SUMMARY_MARK = "==== SUMMARY ===="
VERDICT_RE = re.compile(r"^GENERATABLE: (YES|NO)(?: \((.*?)\))?", re.M)
COUNTS_RE = re.compile(r"^blockers: (\d+), open tie\(s\): (\d+)", re.M)
REASON_RE = re.compile(r"^\s+- \[(\w+)\] (.+)$", re.M)

REVIEWABLE_RULES = frozenset({"open_human_review", "ignored_cli_option"})


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def prompt_files(root: Path) -> list[Path]:
    files = sorted(root.glob("prompt_*.txt"))
    return files


def select_prompts(files: list[Path], only: str | None,
                   limit: int | None) -> list[Path]:
    wanted = None
    if only:
        wanted = {item.strip() for item in only.split(",") if item.strip()}
    selected = [path for path in files if wanted is None or path.stem in wanted]
    if wanted is not None:
        missing = sorted(wanted - {path.stem for path in selected})
        if missing:
            raise SystemExit(f"unknown prompt(s): {', '.join(missing)}")
    if limit is not None:
        selected = selected[:limit]
    return selected


def parse_summary(text: str) -> dict | None:
    start = text.rfind(SUMMARY_MARK)
    if start < 0:
        return None
    block = text[start:]
    verdict = VERDICT_RE.search(block)
    counts = COUNTS_RE.search(block)
    reasons = [{"rule": rule, "message": message.strip()}
               for rule, message in REASON_RE.findall(block)]
    if verdict is None or counts is None:
        return None
    return {
        "generatable": verdict.group(1) == "YES",
        "verdict_note": verdict.group(2) or "",
        "blockers": int(counts.group(1)),
        "open_ties": int(counts.group(2)),
        "rules": reasons,
    }


def parse_tokens(text: str) -> dict:
    rows = TIMING_RE.findall(text)
    output = sum(int(row[1]) for row in rows)
    prompt = sum(int(row[5]) for row in rows)
    # The log's second timing number is decode tokens/second, not seconds.
    # Recover decode time from tokens / rate so the metric stays meaningful.
    decode = sum(int(row[1]) / float(row[4])
                 for row in rows if float(row[4]) > 0)
    return {
        "calls": len(rows),
        "tokens_out": output,
        "tokens_prompt": prompt,
        "decode_seconds": round(decode, 3),
    }


def classify(summary: dict | None, exit_code: int, timed_out: bool) -> str:
    if timed_out or exit_code != 0 and summary is None:
        return "not_generatable"
    if summary is None:
        return "not_generatable"
    rules = {item["rule"] for item in summary["rules"]}
    if summary["generatable"] and summary["blockers"] == 0 \
            and summary["open_ties"] == 0:
        return "direct"
    if summary["generatable"] and not rules:
        return "direct"
    if summary["blockers"] and rules <= REVIEWABLE_RULES:
        return "review"
    if summary["open_ties"] and not summary["blockers"]:
        return "review"
    return "not_generatable"


def run_one(prompt: Path, output_dir: Path, *, run_id: str,
            model: str, server_url: str, timeout: int) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = output_dir / "extract.out"
    stderr_path = output_dir / "extract.err"
    cmd = [
        sys.executable, str(ROOT / "extract_arch.py"),
        "--model", model,
        "--requirements", str(prompt),
        "--output", str(output_dir),
        "--no-chat",
        "--quiet",
    ]
    env = dict(os.environ)
    env.update({
        "ESUS_COMPONENTS_SPLIT": "1",
        "ESUS_MECHANICAL_SCHEMA": "1",
        "ESUS_MECHANICAL_SERVICES": "1",
        "LLAMA_SERVER_URL": server_url,
    })
    started = time.monotonic()
    timed_out = False
    try:
        result = subprocess.run(
            cmd, cwd=str(ROOT), capture_output=True, text=True,
            env=env, timeout=timeout,
        )
        exit_code = result.returncode
        stdout, stderr = result.stdout, result.stderr
    except subprocess.TimeoutExpired as error:
        timed_out = True
        exit_code = 124
        stdout = error.stdout or ""
        stderr = error.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
    elapsed = round(time.monotonic() - started, 3)
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")

    log = output_dir / "run.log"
    log_text = log.read_text(encoding="utf-8") if log.is_file() else ""
    combined = stdout + "\n" + stderr + "\n" + log_text
    summary = parse_summary(combined)
    tokens = parse_tokens(log_text)
    if not tokens["calls"]:
        tokens = parse_tokens(stdout)
    return {
        "prompt": prompt.stem,
        "run_id": run_id,
        "prompt_file": str(prompt),
        "output_dir": str(output_dir),
        "sha256": hashlib.sha256(prompt.read_bytes()).hexdigest(),
        "bytes": prompt.stat().st_size,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "seconds": elapsed,
        "tokens": tokens,
        "summary": summary,
        "classification": classify(summary, exit_code, timed_out),
        "commands": {"extract": cmd},
    }


def write_summary(run_dir: Path, records: list[dict], manifest: dict) -> None:
    (run_dir / "summary.json").write_text(
        json.dumps({"manifest": manifest, "results": records},
                   indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    fields = [
        "prompt", "classification", "exit_code", "timed_out", "seconds",
        "calls", "tokens_out", "tokens_prompt", "blockers", "open_ties",
        "rules", "output_dir",
    ]
    with (run_dir / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            summary = record.get("summary") or {}
            tokens = record.get("tokens") or {}
            writer.writerow({
                "prompt": record["prompt"],
                "classification": record["classification"],
                "exit_code": record["exit_code"],
                "timed_out": record["timed_out"],
                "seconds": record["seconds"],
                "calls": tokens.get("calls", 0),
                "tokens_out": tokens.get("tokens_out", 0),
                "tokens_prompt": tokens.get("tokens_prompt", 0),
                "blockers": summary.get("blockers", ""),
                "open_ties": summary.get("open_ties", ""),
                "rules": ",".join(item["rule"] for item in summary.get("rules", [])),
                "output_dir": record["output_dir"],
            })


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompts", default=str(DEFAULT_PROMPTS))
    parser.add_argument("--out", default=str(DEFAULT_RUN_ROOT))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--model", default="server")
    parser.add_argument("--server-url", default=os.environ.get(
        "LLAMA_SERVER_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--timeout", type=int, default=1800,
                        help="seconds per prompt")
    parser.add_argument("--only", default=None,
                        help="comma-separated prompt stems, e.g. prompt_01,prompt_02")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true",
                        help="rerun prompts that already have metrics.json")
    args = parser.parse_args(argv)

    prompts = select_prompts(prompt_files(Path(args.prompts)), args.only, args.limit)
    if not prompts:
        print("no prompt files selected", file=sys.stderr)
        return 2
    run_id = args.run_id or utc_stamp()
    run_dir = Path(args.out) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": run_id,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "prompts": [path.stem for path in prompts],
        "model": args.model,
        "server_url": args.server_url,
        "timeout_seconds": args.timeout,
        "environment": {
            "ESUS_COMPONENTS_SPLIT": "1",
            "ESUS_MECHANICAL_SCHEMA": "1",
            "ESUS_MECHANICAL_SERVICES": "1",
        },
    }
    records: list[dict] = []
    try:
        for index, prompt in enumerate(prompts, start=1):
            output_dir = run_dir / prompt.stem
            metrics_path = output_dir / "metrics.json"
            if metrics_path.is_file() and not args.force:
                print(f"[{index}/{len(prompts)}] {prompt.stem}: resume", flush=True)
                records.append(json.loads(metrics_path.read_text(encoding="utf-8")))
                continue
            print(f"[{index}/{len(prompts)}] {prompt.stem}: extracting", flush=True)
            record = run_one(prompt, output_dir, run_id=run_id,
                             model=args.model, server_url=args.server_url,
                             timeout=args.timeout)
            metrics_path.write_text(
                json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            records.append(record)
            summary = record.get("summary") or {}
            print(
                f"    {record['classification']} in {record['seconds']}s; "
                f"tokens out={record['tokens']['tokens_out']} "
                f"prompt={record['tokens']['tokens_prompt']}; "
                f"blockers={summary.get('blockers', '?')} "
                f"ties={summary.get('open_ties', '?')}",
                flush=True,
            )
    finally:
        manifest["finished_utc"] = datetime.now(timezone.utc).isoformat()
        manifest["counts"] = {}
        for record in records:
            kind = record["classification"]
            manifest["counts"][kind] = manifest["counts"].get(kind, 0) + 1
        write_summary(run_dir, records, manifest)
    print(f"results: {run_dir / 'summary.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
