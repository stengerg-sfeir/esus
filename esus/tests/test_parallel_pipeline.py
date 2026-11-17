"""Opt-in parallel extraction keeps the dependency order and overlap.

The server backend is the only place where concurrent requests are safe, and a
run is still one step at a time when it resumes from archived documents. These
tests use a barrier, not timing: a sequential scheduler would block at the
barrier and fail instead of silently passing a slow test.
"""

import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.extraction import pipeline  # noqa: E402


class FakeServer:
    is_server = True
    total_slots = 2


class CollectingLog:
    def __init__(self):
        self.lines = []

    def write(self, message):
        self.lines.append(message)


class ParallelPipelineTests(unittest.TestCase):
    def make_pipeline(self):
        class Steps(pipeline.Pipeline):
            def __init__(inner):
                super().__init__(FakeServer(), log=CollectingLog(),
                                 progress_fn=inner.progress)
                inner.events = []
                inner.errors_invariants = threading.Barrier(2, timeout=2)
                inner.patterns_adapters = threading.Barrier(2, timeout=2)

            def progress(inner, name, summary):
                inner.events.append(("progress", name))

            def _step_intentions(inner, requirements):
                inner.events.append(("step", "intentions"))

            def _step_data_models(inner, requirements):
                inner.events.append(("step", "data_models"))

            def _step_errors(inner, requirements):
                if inner.parallel_run:
                    inner.errors_invariants.wait()
                inner.events.append(("step", "errors"))

            def _step_invariants(inner, requirements):
                if inner.parallel_run:
                    inner.errors_invariants.wait()
                inner.events.append(("step", "invariants"))

            def _step_components(inner, requirements):
                inner.events.append(("step", "components"))

            def _step_contracts(inner, requirements):
                inner.events.append(("step", "service_contracts"))

            def _repair_errors(inner):
                inner.events.append(("step", "errors_repair"))

            def _step_persistence(inner, requirements):
                inner.events.append(("step", "persistence_ports"))

            def _step_patterns(inner):
                if inner.parallel_run:
                    inner.patterns_adapters.wait()
                inner.events.append(("step", "pattern_matches"))

            def _step_adapters(inner, requirements):
                if inner.parallel_run:
                    inner.patterns_adapters.wait()
                inner.events.append(("step", "interaction_adapters"))

        return Steps()

    def test_independent_steps_overlap_and_dependencies_stay_ordered(self):
        with mock.patch.object(pipeline, "PARALLEL", True):
            pipe = self.make_pipeline()
            pipe.run("requirements")

        steps = [name for kind, name in pipe.events if kind == "step"]
        self.assertEqual(steps[:2], ["intentions", "data_models"])
        self.assertLess(steps.index("data_models"), steps.index("errors"))
        self.assertLess(steps.index("data_models"), steps.index("invariants"))
        self.assertLess(steps.index("errors"), steps.index("components"))
        self.assertLess(steps.index("invariants"), steps.index("components"))
        self.assertLess(steps.index("components"), steps.index("service_contracts"))
        self.assertLess(steps.index("service_contracts"), steps.index("errors_repair"))
        self.assertLess(steps.index("errors_repair"), steps.index("persistence_ports"))
        self.assertLess(steps.index("persistence_ports"), steps.index("pattern_matches"))
        self.assertLess(steps.index("persistence_ports"), steps.index("interaction_adapters"))

        progress = [name for kind, name in pipe.events if kind == "progress"]
        self.assertEqual(progress, [
            "intentions", "data_models", "errors", "invariants",
            "components", "service_contracts", "errors_repair",
            "persistence_ports", "pattern_matches", "interaction_adapters",
        ])

    def test_resume_stays_sequential_even_when_parallel_is_requested(self):
        with mock.patch.object(pipeline, "PARALLEL", True):
            pipe = self.make_pipeline()
            pipe.documents.update({"intentions": [], "data_models": []})
            pipe.parallel_run = False  # what run(start=...) sets
            pipe.run("requirements", start="errors")

        steps = [name for kind, name in pipe.events if kind == "step"]
        self.assertEqual(steps, [
            "errors", "invariants", "components", "service_contracts",
            "errors_repair", "persistence_ports", "pattern_matches",
            "interaction_adapters",
        ])


if __name__ == "__main__":
    unittest.main()
