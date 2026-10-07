"""A truncated step is retried, and a still-truncated one is declared.

Why this has a test at all: the retry used to fire only when the output failed to
parse. A truncation that lands exactly on a valid list boundary parses, so it was
accepted with no retry and no note — a short document that is indistinguishable
from a complete one downstream. Measured on the corpus (expenses, step G): the
truncated attempt produced 3584 tokens, failed to parse, and the retry recovered
it at 2869. The parse failure is what saved it, and that was luck rather than
design.

The generator is stubbed, so the contract is pinned without a model: what ends
the retry loop, what is stored, and what is logged.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.extraction import grammar_check, pipeline  # noqa: E402
from kernel.extraction.runner import StepResult  # noqa: E402


def result(text, truncated=False, tokens=10, seconds=1.0, budget=3584):
    return StepResult("step", text, tokens, seconds, "length" if truncated else "stop", budget)


class FakeModel:
    """Just enough of a Llama to answer `n_ctx` and `tokenize`.

    `runner.available_tokens` is the subject of the budget assertions, and it
    only needs those two methods — so the ceiling arithmetic is tested without
    loading a model.
    """

    def __init__(self, context, prompt_tokens):
        self._context = context
        self._prompt_tokens = prompt_tokens

    def n_ctx(self):
        return self._context

    def tokenize(self, data):
        return list(range(self._prompt_tokens))


class CollectingLog:
    """A log that keeps its lines, so the messages can be asserted."""

    def __init__(self):
        self.lines = []

    def write(self, message):
        self.lines.append(message)

    def flush(self):
        pass

    def joined(self):
        return "\n".join(self.lines)


class TruncatedStepIsRetried(unittest.TestCase):
    def setUp(self):
        self.log = CollectingLog()
        self.pipeline = pipeline.Pipeline(llm=None, classifier=None, log=self.log)
        # The grammar is not the subject here; the caller is responsible for
        # having validated it and this stub keeps the test model-free.
        self._real_assert_valid = grammar_check.assert_valid
        grammar_check.assert_valid = lambda text, label="grammar": None

    def tearDown(self):
        grammar_check.assert_valid = self._real_assert_valid

    def stub(self, *results):
        """Make the next generate() calls return `results` in order.

        Returns the recorded (temperature, max_new_tokens) of each call, because
        the budget the retry asks for is part of the contract.
        """
        calls = []

        def fake_generate(llm, prompt, grammar_text, label, temperature=0.1,
                          stream=True, max_new_tokens=None):
            calls.append((temperature, max_new_tokens))
            return results[len(calls) - 1]

        self._real_generate = pipeline.runner.generate
        pipeline.runner.generate = fake_generate
        self.addCleanup(lambda: setattr(pipeline.runner, "generate", self._real_generate))
        return calls

    def test_a_truncated_document_that_parsed_is_still_retried(self):
        """The case the old code accepted silently."""
        calls = self.stub(
            result('{"widgets": [1]}', truncated=True),
            result('{"widgets": [1, 2, 3]}'),
        )
        body = self.pipeline._generate("widgets", "prompt", "grammar")
        self.assertEqual(len(calls), 2, "a truncated document must be retried")
        self.assertEqual(body, [1, 2, 3], "the retry's document is the one kept")
        self.assertIn("retrying once", self.log.joined())

    def test_an_untruncated_document_is_not_retried(self):
        calls = self.stub(result('{"widgets": [1, 2]}'))
        body = self.pipeline._generate("widgets", "prompt", "grammar")
        self.assertEqual(len(calls), 1)
        self.assertEqual(body, [1, 2])

    def test_unparseable_output_is_retried_as_before(self):
        calls = self.stub(result("not json"), result('{"widgets": [7]}'))
        body = self.pipeline._generate("widgets", "prompt", "grammar")
        self.assertEqual(len(calls), 2)
        self.assertEqual(body, [7])
        self.assertIn("unusable JSON", self.log.joined())

    def test_a_still_truncated_retry_is_kept_and_declared(self):
        """Better an incomplete document than a missing one — but stated, not silent."""
        calls = self.stub(
            result('{"widgets": [1]}', truncated=True),
            result('{"widgets": [1, 2]}', truncated=True),
        )
        body = self.pipeline._generate("widgets", "prompt", "grammar")
        self.assertEqual(len(calls), 2)
        self.assertEqual(body, [1, 2])
        self.assertIn("still truncated after the retry", self.log.joined())

    def test_a_recovered_retry_is_not_declared_truncated(self):
        """The final message must reflect the last attempt, not the first."""
        self.stub(
            result('{"widgets": [1]}', truncated=True),
            result('{"widgets": [1, 2]}'),
        )
        self.pipeline._generate("widgets", "prompt", "grammar")
        self.assertNotIn("still truncated", self.log.joined())

    def test_both_attempts_unusable_stores_nothing(self):
        self.stub(result("not json"), result("also not json"))
        body = self.pipeline._generate("widgets", "prompt", "grammar")
        self.assertIsNone(body)
        self.assertIn("dependent steps degrade", self.log.joined())


class TheRetryRaisesTheCeiling(unittest.TestCase):
    """A truncation is retried with the room the prompt left, not the ceiling that cut it.

    This is the defect the first version of the retry had: it changed only the
    temperature, so a step that hit `MAX_NEW_TOKENS` was retried under the very
    ceiling that truncated it and truncated again. Expenses' adapters did exactly
    that — twice at 3 584 tokens while the context still held room for thousands
    more — and the document was lost.
    """

    def setUp(self):
        self.log = CollectingLog()
        self._real_assert_valid = grammar_check.assert_valid
        grammar_check.assert_valid = lambda text, label="grammar": None

    def tearDown(self):
        grammar_check.assert_valid = self._real_assert_valid

    def pipeline_with(self, context=8192, prompt_tokens=1600):
        return pipeline.Pipeline(
            llm=FakeModel(context, prompt_tokens), classifier=None, log=self.log
        )

    def stub(self, *results):
        calls = []

        def fake_generate(llm, prompt, grammar_text, label, temperature=0.1,
                          stream=True, max_new_tokens=None):
            calls.append(max_new_tokens)
            return results[len(calls) - 1]

        self._real_generate = pipeline.runner.generate
        pipeline.runner.generate = fake_generate
        self.addCleanup(lambda: setattr(pipeline.runner, "generate", self._real_generate))
        return calls

    def test_the_retry_asks_for_the_room_the_prompt_left(self):
        pipeline_ = self.pipeline_with(context=8192, prompt_tokens=1600)
        calls = self.stub(
            result('{"widgets": [1]}', truncated=True),
            result('{"widgets": [1, 2, 3]}'),
        )
        pipeline_._generate("widgets", "prompt", "grammar")
        self.assertIsNone(calls[0], "the first attempt uses the default ceiling")
        # 8192 context - 1600 prompt tokens - 64 reserve
        self.assertEqual(calls[1], 6528, "the retry must be given the whole remaining context")

    def test_the_log_names_both_ceilings(self):
        pipeline_ = self.pipeline_with()
        self.stub(
            result('{"widgets": [1]}', truncated=True, budget=3584),
            result('{"widgets": [1, 2]}'),
        )
        pipeline_._generate("widgets", "prompt", "grammar")
        logged = self.log.joined()
        self.assertIn("3584-token ceiling", logged, "the attempt's ceiling is the diagnosis")
        self.assertIn("6528-token ceiling", logged, "the retry's ceiling is stated")

    def test_an_unparseable_attempt_does_not_raise_the_ceiling(self):
        """Only a truncation is a ceiling problem; a JSON failure is not."""
        pipeline_ = self.pipeline_with()
        calls = self.stub(result("not json"), result('{"widgets": [7]}'))
        pipeline_._generate("widgets", "prompt", "grammar")
        self.assertEqual(calls, [None, None], "a parse failure keeps the default ceiling")

    def test_a_context_with_no_room_left_says_so(self):
        """The honest case: the ceiling cannot be raised, so the log says that."""
        pipeline_ = self.pipeline_with(context=8192, prompt_tokens=8000)
        calls = self.stub(
            result('{"widgets": [1]}', truncated=True, budget=3584),
            result('{"widgets": [1, 2]}'),
        )
        pipeline_._generate("widgets", "prompt", "grammar")
        # 8192 - 8000 - 64 = 128, which is less than the ceiling that truncated.
        self.assertEqual(calls[1], 128)
        self.assertIn("no room left to raise", self.log.joined())

    def test_an_untruncated_step_never_raises_anything(self):
        pipeline_ = self.pipeline_with()
        calls = self.stub(result('{"widgets": [1, 2]}'))
        pipeline_._generate("widgets", "prompt", "grammar")
        self.assertEqual(calls, [None], "no retry, no raised ceiling")


class TheBudgetArithmetic(unittest.TestCase):
    """`available_tokens` / `generation_budget`, without a model."""

    def test_available_tokens_is_the_context_less_the_prompt_and_the_reserve(self):
        from kernel.extraction import runner

        llm = FakeModel(context=8192, prompt_tokens=1122)
        self.assertEqual(runner.available_tokens(llm, "a prompt"), 8192 - 1122 - 64)

    def test_generation_budget_clamps_a_request_to_the_room_available(self):
        from kernel.extraction import runner

        llm = FakeModel(context=8192, prompt_tokens=1600)
        # Asking for more than the context can hold still returns the room there is.
        self.assertEqual(runner.generation_budget(llm, "p", 99999), 6528)
        # Asking for less is honoured.
        self.assertEqual(runner.generation_budget(llm, "p", 256), 256)
        # Asking for nothing uses the first-attempt ceiling.
        self.assertEqual(runner.generation_budget(llm, "p"), runner.MAX_NEW_TOKENS)

    def test_a_long_prompt_still_leaves_the_minimum_budget(self):
        from kernel.extraction import runner

        llm = FakeModel(context=8192, prompt_tokens=8192)
        self.assertEqual(runner.available_tokens(llm, "a prompt"), runner.MIN_BUDGET)

    def test_no_model_falls_back_to_the_default_ceiling(self):
        from kernel.extraction import runner

        self.assertEqual(runner.available_tokens(None, "a prompt"), runner.MAX_NEW_TOKENS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
