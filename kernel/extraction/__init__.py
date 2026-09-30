"""Chained extraction: vocabularies, grammars and prompts for extract_archi.py.

The extractor runs eight steps over the same requirements. Historically each
step read the raw prompt only, so every step invented its own names for the
same concepts and the documents never agreed. This package carries the values
of one step into the next:

  * `vocabulary` turns an extracted document into the authoritative name sets;
  * `grammar_open` holds the unconstrained grammars used as a fallback;
  * `grammar_builders` and `grammar_persistence` close those grammars to the
    values an earlier step actually produced;
  * `grammar_check` validates a generated grammar before it reaches the model;
  * `prompts` renders the step prompts, including the vocabulary block.

Only `runner` imports llama_cpp; the rest are plain strings and pure Python, so
the consistency checker can import them freely.
"""

from kernel.extraction import (
    grammar,
    grammar_balance,
    grammar_builders,
    grammar_check,
    grammar_open,
    grammar_persistence,
    prompts,
    vocabulary,
)

__all__ = [
    "grammar",
    "grammar_balance",
    "grammar_builders",
    "grammar_check",
    "grammar_open",
    "grammar_persistence",
    "prompts",
    "vocabulary",
]
