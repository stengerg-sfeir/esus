"""Model loading and one-step generation.

This is the only module in the package that imports llama_cpp.

Two things it does that the previous extractor did not: it computes the token
budget from the space actually left in the context instead of hardcoding 4096,
and it reads `finish_reason` so a truncated step is reported rather than saved
as if it were complete.
"""

import sys
import time

from llama_cpp import Llama, LlamaGrammar

try:  # llama-cpp-python < 0.2.x has no GPU offload probe
    from llama_cpp import llama_supports_gpu_offload
except ImportError:
    llama_supports_gpu_offload = None

GPU_LAYERS_ALL = -1
GPU_LAYERS_NONE = 0

# Thread counts are a CPU-backend tuning knob: llama.cpp picks the physical core
# count itself when they are omitted, which beats a fixed number on both a small
# laptop and a large workstation. They are therefore set only off macOS, where
# the CPU backend does the work and an explicit count keeps it predictable —
# on macOS Metal does the work and the setting is mostly moot.
CPU_THREADS = 8

# Novel-token ceiling for the *first* attempt at a step. The context is 8192 and
# the prompts are a few hundred tokens, so this is rarely the binding
# constraint; the room left in the context is. It exists to stop an
# unconstrained generation from filling the whole context, and it is deliberately
# not the last word: a step that hits it is retried with the full room left in
# the context instead, because a ceiling that truncated an attempt cannot also be
# the ceiling the retry runs under — see `generation_budget` and the retry in
# `pipeline._generate`.
MAX_NEW_TOKENS = 3584
# The floor a budget is never allowed to fall below, so even a long prompt
# leaves room for the shortest possible document.
MIN_BUDGET = 16
CONTEXT_RESERVE = 64

# Flash attention, measured rather than assumed. This stack (Metal, Ministral-3
# 3B Q4_K_M) renders decode 22.1 -> 25.3 tok/s and a whole document 24.8 -> 28.0
# tok/s (+13-15%) with it on, and the effect on the output was measured too,
# because the setting is commonly believed to cost quality:
#
#   - 118 real classification items across five prompts: **118/118 identical
#     verdicts**, confidence drifting by a median of 0.0004 (max 0.0034);
#   - one whole document generated at temperature 0: **byte-identical**, 7694
#     characters either way;
#   - the runner-up ordering differed on 2 of 118 items, which can move a
#     `narrow_margin` note but never a verdict.
#
# `n_batch`/`n_ubatch` were measured in the same pass and are deliberately left
# at their defaults: they changed nothing (prompts are ~1 100 tokens, so the
# default 512 already chunks them and prefill is fixed-cost dominated, 4.2 s
# flat across 512-4096). Raise `n_batch` only if a prompt ever exceeds 512
# tokens by enough for the chunking to matter.
FLASH_ATTENTION = True

TRUNCATED = "length"


def resolve_gpu_layers():
    """Offload every layer on Metal, otherwise stay on CPU."""
    if sys.platform != "darwin":
        return GPU_LAYERS_NONE
    if llama_supports_gpu_offload is None or not llama_supports_gpu_offload():
        return GPU_LAYERS_NONE
    return GPU_LAYERS_ALL


def threading_parameters():
    """Explicit thread counts, or no keys at all to let llama.cpp choose.

    Returning an empty dict — rather than keys set to None — matters, because
    llama-cpp-python forwards these straight through to llama.cpp, which is
    not expecting a None thread count.
    """
    if sys.platform == "darwin":
        return {}
    return {"n_threads": CPU_THREADS, "n_threads_batch": CPU_THREADS}


def load_model(model_path, context_size=8192, logits_all=False):
    """Load the GGUF model with the settings every step shares."""
    device = "CPU" if resolve_gpu_layers() == GPU_LAYERS_NONE else "Metal"
    threading = threading_parameters()
    threads = threading.get("n_threads", "auto")
    print(
        f"[model] {model_path} on {device}, n_ctx={context_size}, "
        f"n_threads={threads}, logits_all={logits_all}, "
        f"flash_attn={FLASH_ATTENTION}",
        file=sys.stderr,
    )
    started = time.time()
    llm = Llama(
        model_path=model_path,
        n_ctx=context_size,
        **threading,
        n_gpu_layers=resolve_gpu_layers(),
        flash_attn=FLASH_ATTENTION,
        logits_all=logits_all,
        verbose=False,
    )
    print(f"[model] loaded in {time.time() - started:.1f}s", file=sys.stderr)
    return llm


class StepResult:
    """The outcome of one constrained generation."""

    def __init__(self, label, text, tokens, seconds, finish_reason, budget=None):
        self.label = label
        self.text = text
        self.tokens = tokens
        self.seconds = seconds
        self.finish_reason = finish_reason
        self.budget = budget

    @property
    def truncated(self):
        """True when the model ran out of budget rather than finishing."""
        return self.finish_reason == TRUNCATED

    def describe(self):
        speed = self.tokens / self.seconds if self.seconds else 0.0
        # The ceiling is named on a truncation, because the ceiling is the
        # diagnosis: it is what the retry has to raise.
        note = f" TRUNCATED at the {self.budget}-token ceiling" if self.truncated else ""
        return (
            f"[{self.label}] {self.tokens} tokens in {self.seconds:.1f}s "
            f"({speed:.1f} tok/s){note}"
        )


def token_count(llm, text):
    """Tokens consumed by `text` as a prompt."""
    return len(llm.tokenize(text.encode("utf-8")))


def available_tokens(llm, prompt):
    """How many tokens the context can still hold as a response to `prompt`.

    This is the real ceiling: the room the prompt left behind. `MAX_NEW_TOKENS`
    is only a guard against filling the whole context on the first attempt.
    """
    if llm is None or not prompt or llm.n_ctx() <= 0:
        return MAX_NEW_TOKENS
    return max(MIN_BUDGET, llm.n_ctx() - token_count(llm, prompt) - CONTEXT_RESERVE)


def generation_budget(llm, prompt, max_new_tokens=None):
    """The response ceiling: the one asked for, clamped to the room available.

    The retry after a truncation passes `max_new_tokens=available_tokens(...)`,
    which is how a step that hit `MAX_NEW_TOKENS` gets the rest of the context
    on the second attempt instead of the same ceiling that cut it off.
    """
    ceiling = MAX_NEW_TOKENS if max_new_tokens is None else max_new_tokens
    return max(MIN_BUDGET, min(ceiling, available_tokens(llm, prompt)))


def generate(llm, prompt, grammar_text, label, temperature=0.1, max_new_tokens=None):
    """Generate one document under `grammar_text`, honouring the context budget.

    The call is **not** streamed. Streaming yields one chunk per token and
    rebuilds a response dict for each, which is pure Python overhead on top of
    the sampler that already runs per token — it buys nothing here, because the
    document is only ever parsed once the whole step has finished. A single
    non-streaming call returns the same text in one dict, and its `usage` gives
    the exact completion-token count instead of the one-per-chunk estimate the
    stream forced.

    The caller is responsible for having validated `grammar_text` first: this
    function assumes it is well formed and would otherwise fail on the first
    token rather than up front.

    `max_new_tokens` overrides the first-attempt ceiling of `MAX_NEW_TOKENS`,
    still clamped to the room the prompt left in the context. The retry after a
    truncation uses it to ask for that whole room.

    The grammar is required, not optional. An experiment with no GBNF mask at
    all (§9.31) settled it: the raw model fences its JSON, appends prose and
    code, renames the document's own keys and loses whole steps, so the mask is
    what makes the output machine-readable at all — not a vocabulary guard on
    top of otherwise-good JSON. There is deliberately no switch to turn it off.
    """
    grammar = LlamaGrammar.from_string(grammar_text)
    llm.reset()

    budget = generation_budget(llm, prompt, max_new_tokens)

    started = time.time()
    response = llm(
        prompt=prompt,
        max_tokens=budget,
        temperature=temperature,
        grammar=grammar,
    )

    choice = (response.get("choices") or [{}])[0]
    text = choice.get("text") or ""
    finish_reason = choice.get("finish_reason")
    usage = response.get("usage") or {}
    tokens = usage.get("completion_tokens")
    if not isinstance(tokens, int):
        # A backend without a usage block: measure the text directly rather than
        # reporting zero, so the speed line and the truncation diagnosis stay
        # meaningful.
        tokens = token_count(llm, text)

    return StepResult(
        label, text, tokens, time.time() - started, finish_reason, budget
    )
