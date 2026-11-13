"""A GUI/API facade has no command-line input to adapt."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.extraction import pipeline  # noqa: E402


class _Log:
    def __init__(self):
        self.lines = []

    def write(self, message):
        self.lines.append(message)

    def flush(self):
        pass


class FacadeAdapterTests(unittest.TestCase):
    def test_a_gui_facade_gets_no_cli_adapters_and_no_model_call(self):
        pipe = pipeline.Pipeline(llm=None, classifier=None, log=_Log())
        pipe.documents[pipeline.COMPONENTS] = {
            "facade": {"type": "gui", "technology": "pyimgui",
                       "invocation": None},
            "persistence": {"required": True},
            "crud_services": [{"entity": "Wine", "operations": ["create"]}],
        }
        pipe.documents[pipeline.DATA_MODELS] = [{
            "name": "Wine",
            "fields": [{"name": "id", "type": "int", "primary_key": True}],
        }]
        pipe.documents[pipeline.SERVICE_CONTRACTS] = [{
            "service_name": "WineRepository",
            "methods": [{"name": "create", "params": [], "return_type": "Wine"}],
        }]
        called = []
        real_generate = pipeline.runner.generate
        pipeline.runner.generate = lambda *args, **kwargs: called.append(args)
        try:
            pipe._step_adapters("A GUI for a wine shop.")
        finally:
            pipeline.runner.generate = real_generate
        self.assertEqual(called, [])
        self.assertEqual(pipe.documents[pipeline.INTERACTION_ADAPTERS], [])
        self.assertTrue(any("non-CLI facade" in line for line in pipe.log.lines))


if __name__ == "__main__":
    unittest.main()
