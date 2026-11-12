"""Merge validation shards produced by concurrent GPU workers."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import run_validation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", nargs="+", required=True,
                        help="run directories, one per GPU worker")
    parser.add_argument("--out", required=True)
    parser.add_argument("--require", type=int, default=None,
                        help="fail unless this many unique prompts are present")
    args = parser.parse_args(argv)
    records = []
    manifests = []
    seen = {}
    shard_records = []
    for raw in args.runs:
        run_dir = Path(raw)
        payload = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        manifests.append(payload.get("manifest") or {})
        for record in payload.get("results") or []:
            prompt = record.get("prompt")
            if prompt in seen:
                raise SystemExit(f"duplicate prompt {prompt} in {run_dir}")
            seen[prompt] = record
            records.append(record)
            shard_records.append((run_dir, record))
    records.sort(key=lambda item: item.get("prompt", ""))
    if args.require is not None and len(records) != args.require:
        raise SystemExit(
            f"expected {args.require} unique prompts, found {len(records)}")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    # A merged run must be self-contained: the notebook archives this directory,
    # so copying only summary.json/csv would lose every extraction output.
    for run_dir, record in shard_records:
        prompt = record.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            continue
        source = Path(record.get("output_dir") or (run_dir / prompt))
        if not source.is_dir():
            raise SystemExit(f"missing output for {prompt}: {source}")
        target = out / prompt
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
        record["output_dir"] = str(target)
    manifest = {
        "run_id": out.name,
        "merged": True,
        "shards": [str(Path(path).resolve()) for path in args.runs],
        "source_manifests": manifests,
        "prompts": [record["prompt"] for record in records],
        "counts": {},
    }
    for record in records:
        kind = record.get("classification", "unknown")
        manifest["counts"][kind] = manifest["counts"].get(kind, 0) + 1
    run_validation.write_summary(out, records, manifest)
    print(f"merged {len(records)} prompts -> {out / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
