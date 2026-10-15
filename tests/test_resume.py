"""Resuming reruns one failed step against archived documents, not the pipeline.

A D-fix validates in minutes instead of half an hour: earlier steps are
skipped, their archived documents preserved as the context the remaining
steps chain from. An unknown step name fails loudly rather than running the
whole pipeline by accident.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.extraction import pipeline  # noqa: E402


class CollectingLog:
    def write(self, message):
        pass

    def flush(self):
        pass


class ResumeTests(unittest.TestCase):
    def recorded_run(self, start, preloaded):
        """Run with every step stubbed to record its name; return the order."""
        pipe = pipeline.Pipeline(llm=None, classifier=None, log=CollectingLog())
        pipe.documents.update(preloaded)
        called = []

        def step(name):
            def run(*args):
                called.append(name)
            return run

        pipe._step_intentions = step("intentions")
        pipe._step_data_models = step("data_models")
        pipe._step_errors = step("errors")
        pipe._step_invariants = step("invariants")
        pipe._step_components = step("components")
        pipe._step_contracts = step("service_contracts")
        pipe._repair_errors = step("errors_repair")
        pipe._step_patterns = step("patterns")
        pipe._step_adapters = step("adapters")
        pipe._step_persistence = step("persistence")
        pipe.run("requirements", start=start)
        return called, pipe.documents

    def test_a_full_run_still_runs_every_step_in_order(self):
        called, _ = self.recorded_run(None, {})
        self.assertEqual(called, ["intentions", "data_models", "errors",
                                  "invariants", "components", "service_contracts",
                                  "errors_repair", "patterns", "adapters",
                                  "persistence"])

    def test_resuming_skips_earlier_steps(self):
        called, documents = self.recorded_run(
            "components", {"data_models": [{"name": "X"}]})
        self.assertEqual(called, ["components", "service_contracts", "errors_repair",
                                  "patterns", "adapters", "persistence"])
        self.assertEqual(documents["data_models"], [{"name": "X"}])

    def test_an_unknown_step_fails_loudly(self):
        with self.assertRaises(ValueError):
            self.recorded_run("no_such_step", {})


if __name__ == "__main__":
    unittest.main()
