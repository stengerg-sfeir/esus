"""MLX backend wiring and GBNF translation.

The model itself is not loaded in these tests; generation is covered by the
real speed run. The point here is the backend contract: a grammar reaches MLX
as GBNF text rather than a `LlamaGrammar`, and the same grammars ESUS builds
survive the GBNF -> Lark translation llguidance uses.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.extraction import grammar_open  # noqa: E402
from kernel.extraction import runner  # noqa: E402


class _FakeMLX:
    is_mlx = True

    def __init__(self):
        self.calls = []

    def reset(self):
        pass

    def n_ctx(self):
        return 8192

    def tokenize(self, text, add_bos=True, special=False):
        return [1, 2]

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "choices": [{"text": '{"ok": true}', "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 3},
        }


class MLXBackendTests(unittest.TestCase):
    def test_runner_passes_gbnf_text_to_mlx(self):
        llm = _FakeMLX()
        result = runner.generate(llm, "prompt", 'root ::= "Z"', "doc")
        self.assertEqual(result.text, '{"ok": true}')
        self.assertEqual(llm.calls[0]["grammar"], 'root ::= "Z"')

    def test_open_grammars_translate_to_valid_llguidance_grammars(self):
        try:
            from llguidance._lib import LLMatcher
            from llguidance.gbnf_to_lark import gbnf_to_lark
        except ImportError:
            self.skipTest("llguidance is not installed in this interpreter")

        grammars = [
            grammar_open.phrase_list("intentions"),
            grammar_open.invariant_list("invariants"),
            grammar_open.data_models(),
            grammar_open.errors(),
            grammar_open.components(),
            grammar_open.service_contracts(),
            grammar_open.adapters(),
            grammar_open.persistence_ports(),
        ]
        for text in grammars:
            lark = gbnf_to_lark(text)
            spec = LLMatcher.grammar_from_lark(lark)
            self.assertEqual(LLMatcher.validate_grammar(spec), "")


if __name__ == "__main__":
    unittest.main()
