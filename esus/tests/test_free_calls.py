"""The maskless calls: raw continuation for documents, chat for free asks.

Why this has a test at all: the stub filler used to ask by raw continuation,
and an instruct model completed the *document* instead of answering — Qwen3-
4B-Instruct-2507 echoed the stub inside the prompt's open fence, closed it,
and reasoned for the whole context (`finish_reason='length'` at 3584/3584
tokens, and again at 5905/5905). Through the GGUF's own chat template the
same ask stopped at 220 tokens with a body on the first line. The template
is the framing lever; these tests pin which call each case takes, what
budget it asks for, and what a mock without one reads as.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.extraction import runner  # noqa: E402


class ChatModel:
    """Just enough of a Llama to answer `create_chat_completion`."""

    metadata = {"tokenizer.chat_template": "{{ prompt }}"}

    def __init__(self, content="return 0", finish_reason="stop",
                 completion_tokens=7, context=8192, prompt_tokens=100):
        self.content = content
        self.finish_reason = finish_reason
        self.completion_tokens = completion_tokens
        self._context = context
        self._prompt_tokens = prompt_tokens
        self.calls = []

    def reset(self):
        self.calls.append(("reset",))

    def n_ctx(self):
        return self._context

    def tokenize(self, data):
        return list(range(self._prompt_tokens))

    def create_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "choices": [{"message": {"content": self.content},
                         "finish_reason": self.finish_reason}],
            "usage": {"completion_tokens": self.completion_tokens},
        }


class GenerateChatTests(unittest.TestCase):
    def test_the_prompt_goes_through_the_chat_template(self):
        model = ChatModel(content="return 0")
        result = runner.generate_chat(model, "write the body", "stub:x",
                                      temperature=0.0, seed=20261012)
        call = model.calls[-1]
        self.assertEqual(call["messages"],
                         [{"role": "user", "content": "write the body"}])
        self.assertEqual(call["temperature"], 0.0)
        self.assertEqual(call["seed"], 20261012)
        self.assertEqual(call["max_tokens"], 3584)
        self.assertEqual(result.text, "return 0")
        self.assertEqual(result.finish_reason, "stop")
        self.assertEqual(result.tokens, 7)
        self.assertEqual(result.budget, 3584)
        self.assertFalse(result.truncated)

    def test_a_length_finish_is_truncated_and_says_so(self):
        model = ChatModel(finish_reason="length")
        result = runner.generate_chat(model, "write the body", "stub:x")
        self.assertTrue(result.truncated)
        self.assertEqual(result.budget, 3584)
        self.assertIn("TRUNCATED at the 3584-token ceiling", result.describe())

    def test_the_budget_respects_the_room_the_prompt_left(self):
        model = ChatModel(context=8192, prompt_tokens=8000)
        result = runner.generate_chat(model, "write the body", "stub:x")
        # 8192 context - 8000 prompt tokens - 64 reserve
        self.assertEqual(model.calls[-1]["max_tokens"], 128)
        self.assertEqual(result.budget, 128)

    def test_an_overridden_ceiling_is_still_clamped_to_the_room(self):
        model = ChatModel(context=8192, prompt_tokens=8000)
        runner.generate_chat(model, "write the body", "stub:x",
                             max_new_tokens=4096)
        self.assertEqual(model.calls[-1]["max_tokens"], 128)


class NoUsageBlockTests(unittest.TestCase):
    """A binding without `usage` counts the text itself, as raw does."""

    def test_the_text_is_measured_when_the_response_has_no_usage(self):
        model = ChatModel(content="return 0")

        def no_usage(**kwargs):
            model.calls.append(kwargs)
            return {"choices": [{"message": {"content": "return 0"},
                                 "finish_reason": "stop"}]}

        model.create_chat_completion = no_usage
        result = runner.generate_chat(model, "write the body", "stub:x")
        self.assertEqual(result.tokens, 100, "tokenize(0..99) is the stand-in")


class ChatTemplateProbeTests(unittest.TestCase):
    def test_a_template_in_the_metadata_means_chat(self):
        model = mock.Mock(metadata={"tokenizer.chat_template": "{{ ... }}"})
        self.assertTrue(runner.has_chat_template(model))

    def test_the_resolved_chat_format_also_counts(self):
        model = mock.Mock(metadata={}, chat_format="chatml")
        self.assertTrue(runner.has_chat_template(model))

    def test_a_model_without_either_stays_on_raw_continuation(self):
        self.assertFalse(runner.has_chat_template(object()))
        self.assertFalse(runner.has_chat_template(
            mock.Mock(metadata={}, chat_format=None)))
        # A bare Mock answers truthy for every attribute: it must not read
        # as a template.
        self.assertFalse(runner.has_chat_template(mock.Mock()))


class RawModel(ChatModel):
    """ChatModel with the raw entry point `generate_free` calls."""

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return {"choices": [{"text": "prose", "finish_reason": "stop"}],
                "usage": {"completion_tokens": 3}}


class RawGenerationStaysAvailableTests(unittest.TestCase):
    """`generate_free` is the document-style raw call; it must not move."""

    def test_generate_free_still_sends_a_raw_prompt(self):
        model = RawModel()
        result = runner.generate_free(model, "a document", "step")
        self.assertEqual(model.calls[-1]["prompt"], "a document")
        self.assertNotIn("messages", model.calls[-1])
        self.assertEqual(result.text, "prose")
        self.assertEqual(result.finish_reason, "stop")


if __name__ == "__main__":
    unittest.main()
