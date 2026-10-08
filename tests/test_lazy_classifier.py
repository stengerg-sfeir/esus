"""Step F must not load the classifier model when there is nothing to classify.

The classifier is a second full model load (`logits_all=True`, for the per-token
`logprobs` the pattern classifier reads). It used to be loaded at startup, so a
program with no domain — hello, cli_tool — paid for a model step F would never
call. These tests pin the deferral: no items means the factory is never invoked,
and items means it is invoked exactly once.
"""

import unittest
from unittest import mock

from kernel.extraction import pipeline


class _RecordingLog:
    def __init__(self):
        self.lines = []

    def write(self, message):
        self.lines.append(message)


class LazyClassifierTests(unittest.TestCase):
    def test_no_items_never_loads_the_classifier(self):
        loaded = []

        def factory():
            loaded.append(True)
            raise AssertionError("the classifier must not load when nothing is classified")

        run = pipeline.Pipeline(llm=None, log=_RecordingLog(), classifier_factory=factory)
        run.documents = {"invariants": [], "service_contracts": []}

        run._step_patterns()

        self.assertEqual(run.documents["pattern_matches"], [])
        self.assertEqual(loaded, [])

    def test_items_load_the_classifier_once_and_use_it(self):
        sentinel = object()
        loaded = []

        def factory():
            loaded.append(sentinel)
            return sentinel

        run = pipeline.Pipeline(llm=None, log=_RecordingLog(), classifier_factory=factory)
        run.documents = {
            "invariants": [{"kind": "rule", "text": "a borrow must not exceed copies"}],
            "service_contracts": [],
        }

        seen = {}

        def fake_classify(classifier, documents, log):
            seen["classifier"] = classifier
            return []

        with mock.patch.object(pipeline.classification, "classify_documents", fake_classify):
            run._step_patterns()

        self.assertEqual(loaded, [sentinel])
        self.assertIs(seen["classifier"], sentinel)
        self.assertEqual(run.documents["pattern_matches"], [])

    def test_an_already_built_classifier_is_reused(self):
        existing = object()
        loaded = []

        def factory():
            loaded.append(True)
            return object()

        run = pipeline.Pipeline(
            llm=None, classifier=existing, log=_RecordingLog(), classifier_factory=factory
        )
        run.documents = {
            "invariants": [{"kind": "rule", "text": "a borrow must not exceed copies"}],
            "service_contracts": [],
        }

        seen = {}

        def fake_classify(classifier, documents, log):
            seen["classifier"] = classifier
            return []

        with mock.patch.object(pipeline.classification, "classify_documents", fake_classify):
            run._step_patterns()

        self.assertEqual(loaded, [])
        self.assertIs(seen["classifier"], existing)


if __name__ == "__main__":
    unittest.main()
