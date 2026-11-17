"""Merging GPU shards must produce one self-contained validation run."""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import merge_validation_runs as merge  # noqa: E402


def write_shard(root, run_id, prompt, classification):
    run_dir = root / run_id
    output = run_dir / prompt
    output.mkdir(parents=True)
    (output / "metrics.json").write_text("{}\n", encoding="utf-8")
    record = {
        "prompt": prompt,
        "classification": classification,
        "output_dir": str(output),
        "exit_code": 0,
        "timed_out": False,
        "seconds": 1.0,
        "tokens": {"calls": 1, "tokens_out": 2, "tokens_prompt": 3,
                   "decode_seconds": 0.5},
        "summary": {"generatable": True, "blockers": 0, "open_ties": 0,
                    "rules": []},
    }
    (run_dir / "summary.json").write_text(
        json.dumps({"manifest": {"run_id": run_id}, "results": [record]}),
        encoding="utf-8",
    )
    return run_dir, record


class MergeTests(unittest.TestCase):
    def test_prompt_directories_are_copied_and_paths_rewritten(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            shard_a, _ = write_shard(root, "gpu0", "prompt_01", "direct")
            shard_b, _ = write_shard(root, "gpu1", "prompt_02", "review")
            out = root / "merged"

            code = merge.main([
                "--runs", str(shard_a), str(shard_b),
                "--out", str(out), "--require", "2",
            ])

            self.assertEqual(code, 0)
            summary = json.loads((out / "summary.json").read_text(
                encoding="utf-8"))
            self.assertEqual([item["prompt"] for item in summary["results"]],
                             ["prompt_01", "prompt_02"])
            self.assertEqual(summary["manifest"]["run_id"], "merged")
            self.assertEqual(summary["manifest"]["counts"],
                             {"direct": 1, "review": 1})
            for prompt in ("prompt_01", "prompt_02"):
                self.assertTrue((out / prompt / "metrics.json").is_file())
                record = next(item for item in summary["results"]
                              if item["prompt"] == prompt)
                self.assertEqual(record["output_dir"], str(out / prompt))
            self.assertTrue((out / "summary.csv").is_file())

    def test_a_missing_prompt_fails_before_any_copy(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            shard, _ = write_shard(root, "gpu0", "prompt_01", "direct")
            out = root / "merged"
            with self.assertRaises(SystemExit):
                merge.main([
                    "--runs", str(shard), "--out", str(out), "--require", "2",
                ])
            self.assertFalse((out / "prompt_01").exists())

    def test_a_missing_output_directory_is_an_error(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            shard, record = write_shard(root, "gpu0", "prompt_01", "direct")
            shutil.rmtree(record["output_dir"])
            with self.assertRaises(SystemExit):
                merge.main([
                    "--runs", str(shard), "--out", str(root / "merged"),
                    "--require", "1",
                ])


if __name__ == "__main__":
    unittest.main()
