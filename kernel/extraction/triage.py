"""One short question before extraction: does the program need a domain model?

The extraction pipeline is built for programs with entities, services and
persistence.  A one-file utility (hello world, a calculator, a CSV converter)
has no domain to extract: the generator already knows the honest answer is a
single `app.py` written from the requirements.  Running five or six extraction
steps first only adds model calls.

This module asks the model one question, constrained to a single letter:

    Y  the program defines named domain entities/records with fields
    N  it is a stateless one-file utility
    U  unsure (the caller must run the full extraction)

The prompt is deliberately about a **domain model**, not CRUD: a report or
simulator with records counts even when it never stores them.  Measured on the
66 initial+validation prompts (2026-11-12): 62 Y, 4 N, 0 U, 0 false N; the
four N prompts were hello, cli_tool and two equivalent validation prompts.
The triage call took 0.10-0.86 s each, 0.23 s on average.
"""

from dataclasses import dataclass

from kernel.extraction import grammar, grammar_check, runner

SYSTEM = (
    "You classify software requirements. The question is whether the program "
    "needs a domain data model: named entities, records or objects with fields, "
    "even if they are only used in memory. A parser, report or simulator counts "
    "when it defines such records. A one-shot calculator, formatter or converter "
    "without domain records does not. Answer Y for a domain model, N for none, "
    "U if unsure. Reply with exactly one letter: Y, N or U."
)

# One token, no JSON, no prose.  The grammar leaves no room for an explanation
# that would have to be parsed away.
GRAMMAR = grammar.grammar(['root ::= "Y" | "N" | "U"'])
grammar_check.assert_valid(GRAMMAR, "triage")


@dataclass
class TriageResult:
    answer: str
    seconds: float
    tokens: int
    prompt_tokens: int


def prompt_for(requirements):
    return (f"<|im_start|>system\n{SYSTEM}<|im_end|>\n"
            f"<|im_start|>user\n{requirements}<|im_end|>\n"
            "<|im_start|>assistant\n")


def classify(llm, requirements, seed=None):
    """`Y`, `N` or `U`, with the wall and prompt-token cost of the call."""
    result = runner.generate(
        llm,
        prompt_for(requirements),
        GRAMMAR,
        "domain_triage",
        temperature=0.0,
        max_new_tokens=1,
        seed=seed,
    )
    answer = result.text.strip().upper()[:1]
    if answer not in ("Y", "N", "U"):
        answer = "U"
    return TriageResult(
        answer=answer,
        seconds=result.seconds,
        tokens=result.tokens,
        prompt_tokens=result.prompt_tokens or 0,
    )
