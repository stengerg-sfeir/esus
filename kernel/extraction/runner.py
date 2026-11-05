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

try:  # the fd-level redirect the wrapper itself uses for backend init
    from llama_cpp._utils import suppress_stdout_stderr
except ImportError:  # pragma: no cover - very old bindings lack the helper
    import contextlib

    def suppress_stdout_stderr(disable=True):
        return contextlib.nullcontext()

try:  # llama-cpp-python < 0.2.x has no GPU offload probe
    from llama_cpp import llama_supports_gpu_offload
except ImportError:
    llama_supports_gpu_offload = None

GPU_LAYERS_ALL = -1
GPU_LAYERS_NONE = 0

# `--model server` is a backend selector, not a path: the GGUF and its
# placement live in an already-running llama-server. Keeping the sentinel in
# this module means extraction and the generator agree on what it means.
SERVER_MODEL = "server"

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


def load_model(model_path, context_size=8192, logits_all=False, quiet=False):
    """Load the GGUF model with the settings every step shares.

    `model_path == "server"` connects to a running llama-server instead of
    loading a GGUF in this process. The server's `n_ctx` wins; the local
    `context_size` is only a fallback for an old server without `/props`.
    """
    if model_path == SERVER_MODEL:
        from kernel.extraction.server_backend import ServerModel

        llm = ServerModel(context_size=context_size)
        if not quiet:
            print(
                f"[server] llama-server {llm.url}: model={llm.model_name}, "
                f"n_ctx={llm.n_ctx()}",
                file=sys.stderr,
            )
        return llm

    started = time.time()
    if quiet:
        # `verbose=False` silences the wrapper's own logs, but two things
        # write to the fds straight from the C layer, bypassing that flag:
        # the offload probe (`resolve_gpu_layers` initialises the Metal
        # backend — device discovery and shader compile banners) and the
        # model load itself. Both are redirected to devnull for the
        # construction only — generation itself is silent, and any failure
        # still raises as an exception.
        with suppress_stdout_stderr(disable=False):
            llm = _construct(model_path, context_size, logits_all)
    else:
        device = "CPU" if resolve_gpu_layers() == GPU_LAYERS_NONE else "Metal"
        threads = threading_parameters().get("n_threads", "auto")
        print(
            f"[model] {model_path} on {device}, n_ctx={context_size}, "
            f"n_threads={threads}, logits_all={logits_all}, "
            f"flash_attn={FLASH_ATTENTION}",
            file=sys.stderr,
        )
        llm = _construct(model_path, context_size, logits_all)
        print(f"[model] loaded in {time.time() - started:.1f}s", file=sys.stderr)
    return llm


def _construct(model_path, context_size, logits_all):
    """Build the `Llama` instance; callers handle noise and announcements."""
    return Llama(
        model_path=model_path,
        n_ctx=context_size,
        **threading_parameters(),
        n_gpu_layers=resolve_gpu_layers(),
        flash_attn=FLASH_ATTENTION,
        logits_all=logits_all,
        verbose=False,
    )


class StepResult:
    """The outcome of one constrained generation."""

    def __init__(self, label, text, tokens, seconds, finish_reason, budget=None,
                 decode_seconds=None, prompt_tokens=None, cached_tokens=None):
        self.label = label
        self.text = text
        self.tokens = tokens
        self.seconds = seconds
        self.finish_reason = finish_reason
        self.budget = budget
        # A server reports prefill and decode separately. The wall time stays
        # in `seconds` (it is what the run total sums); these optional fields
        # let `describe` show the decode rate the server's own timing reports.
        self.decode_seconds = decode_seconds
        self.prompt_tokens = prompt_tokens
        self.cached_tokens = cached_tokens

    @property
    def truncated(self):
        """True when the model ran out of budget rather than finishing."""
        return self.finish_reason == TRUNCATED

    def describe(self):
        speed = self.tokens / self.seconds if self.seconds else 0.0
        timing = f"({speed:.1f} tok/s"
        if self.decode_seconds:
            timing += f", {self.tokens / self.decode_seconds:.1f} decode"
        if self.prompt_tokens:
            timing += f", {self.prompt_tokens} prompt"
        timing += ")"
        # The ceiling is named on a truncation, because the ceiling is the
        # diagnosis: it is what the retry has to raise.
        note = f" TRUNCATED at the {self.budget}-token ceiling" if self.truncated else ""
        return (
            f"[{self.label}] {self.tokens} tokens in {self.seconds:.1f}s "
            f"{timing}{note}"
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


def generate(llm, prompt, grammar_text, label, temperature=0.0, max_new_tokens=None, seed=None):
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
    return _generate_impl(llm, prompt, grammar, label, temperature,
                          max_new_tokens, seed)


def generate_free(llm, prompt, label, temperature=0.0, max_new_tokens=None, seed=None):
    """Generate free text (no grammar mask), returning a `StepResult`.

    The one unmasked call in the project: the generator's degenerate fallback,
    where the documents are clean but empty (no models, services or commands)
    and the requirements describe a whole tiny program. A mask would only be
    able to say "any text", so none is used — and the output is verified by
    running it, the only check that means anything there.

    Raw continuation is the wrong frame for a free *ask*, though — see
    `generate_chat`, which the stub filler prefers whenever the GGUF can
    provide one.
    """
    return _generate_impl(llm, prompt, None, label, temperature,
                          max_new_tokens, seed)


def generate_chat(llm, prompt, label, temperature=0.0, max_new_tokens=None, seed=None):
    """Generate free text through the model's chat template, returning a `StepResult`.

    Raw completion is right for the document steps: a grammar mask makes the
    output machine-readable, and there is nothing to converse about. A free
    ask is different. An instruct model continued as raw text does not answer
    it; it continues the *document*, and the continuation is reasoning.
    Measured on Qwen3-4B-Instruct-2507 (`LibraryService.borrow_book`, the
    same prompt at temperature 0, seed 20261012):

      - raw: `finish_reason='length'` at 3584/3584 tokens, and again at
        5905/5905 with the whole context — still mid-sentence reasoning;
      - the GGUF's chat template: `finish_reason='stop'`, 220 tokens, a body
        that starts at the first line.

    The template is what selects the assistant mode. `has_chat_template`
    lets the caller choose between the two framings per model.
    """
    return _generate_impl(llm, prompt, None, label, temperature,
                          max_new_tokens, seed, chat=True)


def has_chat_template(llm):
    """True when the GGUF carries a chat template `create_chat_completion` uses.

    Every model measured so far does; the check keeps a template-less GGUF
    (and a bare test mock, which answers truthy for every attribute) on
    `generate_free` instead of failing body by body.
    """
    try:
        metadata = llm.metadata or {}
        template = metadata.get("tokenizer.chat_template")
    except Exception:  # a mock or a binding without the property
        template = None
    if isinstance(template, str) and template.strip():
        return True
    return isinstance(getattr(llm, "chat_format", None), str)


def _generate_impl(llm, prompt, grammar, label, temperature, max_new_tokens,
                   seed, chat=False):
    """One non-streaming call (see `generate` for why), timed and counted."""
    llm.reset()

    budget = generation_budget(llm, prompt, max_new_tokens)

    started = time.time()
    if chat:
        if grammar is not None:
            raise ValueError("a chat call cannot carry a GBNF mask")
        call = dict(messages=[{"role": "user", "content": prompt}],
                    max_tokens=budget, temperature=temperature)
        if seed is not None:
            call["seed"] = seed
        response = llm.create_chat_completion(**call)
        choice = (response.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
    else:
        call = dict(prompt=prompt, max_tokens=budget, temperature=temperature)
        if grammar is not None:
            call["grammar"] = grammar
        if seed is not None:
            call["seed"] = seed
        response = llm(**call)
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

    timings = response.get("timings") or {}
    predicted_ms = timings.get("predicted_ms")
    decode_seconds = (predicted_ms / 1000.0
                      if isinstance(predicted_ms, (int, float))
                      and predicted_ms > 0 else None)
    prompt_tokens = usage.get("prompt_tokens")
    if not isinstance(prompt_tokens, int):
        prompt_tokens = None
    cached = timings.get("cache_n")
    cached_tokens = cached if isinstance(cached, int) else None
    return StepResult(
        label, text, tokens, time.time() - started, finish_reason, budget,
        decode_seconds=decode_seconds, prompt_tokens=prompt_tokens,
        cached_tokens=cached_tokens,
    )
