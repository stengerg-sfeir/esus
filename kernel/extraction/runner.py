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

# Novel-token ceiling for one step. The context is 8192 and the prompts are a
# few hundred tokens, so this is rarely the binding constraint; the context
# budget below is.
MAX_NEW_TOKENS = 3584
CONTEXT_RESERVE = 64

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
        f"n_threads={threads}, logits_all={logits_all}",
        file=sys.stderr,
    )
    started = time.time()
    llm = Llama(
        model_path=model_path,
        n_ctx=context_size,
        **threading,
        n_gpu_layers=resolve_gpu_layers(),
        flash_attn=False,
        logits_all=logits_all,
        verbose=False,
    )
    print(f"[model] loaded in {time.time() - started:.1f}s", file=sys.stderr)
    return llm


class StepResult:
    """The outcome of one constrained generation."""

    def __init__(self, label, text, tokens, seconds, finish_reason):
        self.label = label
        self.text = text
        self.tokens = tokens
        self.seconds = seconds
        self.finish_reason = finish_reason

    @property
    def truncated(self):
        """True when the model ran out of budget rather than finishing."""
        return self.finish_reason == TRUNCATED

    def describe(self):
        speed = self.tokens / self.seconds if self.seconds else 0.0
        note = " TRUNCATED" if self.truncated else ""
        return (
            f"[{self.label}] {self.tokens} tokens in {self.seconds:.1f}s "
            f"({speed:.1f} tok/s){note}"
        )


def token_count(llm, text):
    """Tokens consumed by `text` as a prompt."""
    return len(llm.tokenize(text.encode("utf-8")))


def generate(llm, prompt, grammar_text, label, temperature=0.1, stream=True):
    """Generate one document under `grammar_text`, honouring the context budget.

    The caller is responsible for having validated `grammar_text` first: this
    function assumes it is well formed and would otherwise fail on the first
    token rather than up front.
    """
    grammar = LlamaGrammar.from_string(grammar_text)
    llm.reset()

    budget = MAX_NEW_TOKENS
    if prompt and llm.n_ctx() > 0:
        budget = max(16, min(MAX_NEW_TOKENS, llm.n_ctx() - token_count(llm, prompt) - CONTEXT_RESERVE))

    started = time.time()
    chunks = []
    tokens = 0
    finish_reason = None

    for chunk in llm(
        prompt=prompt,
        max_tokens=budget,
        temperature=temperature,
        grammar=grammar,
        stream=stream,
    ):
        choice = chunk["choices"][0]
        piece = choice.get("text") or ""
        if piece:
            chunks.append(piece)
            tokens += 1
        finish_reason = choice.get("finish_reason") or finish_reason

    return StepResult(label, "".join(chunks), tokens, time.time() - started, finish_reason)
