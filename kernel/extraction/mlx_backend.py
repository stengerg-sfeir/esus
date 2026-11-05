"""MLX backend for ESUS on Apple Silicon.

This module is imported only for ``--model mlx``.  It keeps the same small
surface as the llama.cpp/server backends used by ``kernel.extraction.runner``:

* raw prompt completion, optionally constrained by a GBNF grammar;
* chat-template completion for the body-writing pass;
* tokenization, context size and next-token log probabilities.

MLX has no GBNF sampler, so the grammar is translated to Lark and enforced by
llguidance's MLX bitmask kernel.  llama.cpp and MLX therefore see the same
grammar text, but arrive at the token mask by different routes.
"""

from __future__ import annotations

import os
import time
from typing import Any

DEFAULT_MLX_MODEL = os.environ.get(
    "MLX_MODEL", "mlx-community/Qwen3-4B-Instruct-2507-4bit"
)


class MLXError(RuntimeError):
    """An MLX request failed, or the MLX runtime is unavailable."""


def _grammar_text(grammar) -> str:
    """Return the GBNF text from a string or a llama.cpp grammar object."""
    if isinstance(grammar, str):
        return grammar
    text = getattr(grammar, "_grammar", None)
    if isinstance(text, str):
        return text
    raise MLXError("the MLX backend needs a GBNF grammar string")


class GrammarLogitsProcessor:
    """Mask MLX logits to the tokens allowed by a GBNF grammar.

    llguidance consumes the previously sampled token on every step after the
    first, which is the same contract as outlines' llguidance processor.  The
    prompt tokens are deliberately not consumed: the matcher starts at the
    grammar root, not at the prompt.
    """

    def __init__(self, grammar_text: str, tokenizer):
        try:
            from llguidance import _lib
            from llguidance import hf
            from llguidance.gbnf_to_lark import gbnf_to_lark
            from llguidance.numpy import allocate_token_bitmask
        except ImportError as error:  # pragma: no cover - environment problem
            raise MLXError(
                "the MLX backend needs llguidance; install it with "
                "`pip install llguidance`"
            ) from error

        inner = getattr(tokenizer, "_tokenizer", tokenizer)
        try:
            from transformers import PreTrainedTokenizerFast
        except ImportError:  # pragma: no cover
            PreTrainedTokenizerFast = ()  # type: ignore[assignment]
        if not isinstance(inner, PreTrainedTokenizerFast):
            inner = tokenizer
        try:
            self._llg_tokenizer = hf.from_tokenizer(inner)
        except Exception as error:  # pragma: no cover - tokenizer variant
            raise MLXError(f"cannot convert the tokenizer for llguidance: {error}") from error

        # llguidance's tokenizer is the source of truth for the vocabulary
        # width.  The model's logits may be padded, so use this number for the
        # bitmask and trim/expand only at application time.
        self.vocab_size = int(self._llg_tokenizer.vocab_size)
        if self.vocab_size <= 0:
            raise MLXError("llguidance returned an empty tokenizer vocabulary")

        try:
            lark = gbnf_to_lark(grammar_text)
            spec = _lib.LLMatcher.grammar_from_lark(lark)
            self._matcher = _lib.LLMatcher(self._llg_tokenizer, spec)
            error = self._matcher.get_error()
            if error:
                raise MLXError(f"llguidance rejected the grammar: {error}")
        except MLXError:
            raise
        except Exception as error:
            raise MLXError(f"cannot compile the GBNF grammar for MLX: {error}") from error

        self._bitmask = allocate_token_bitmask(1, self.vocab_size)
        self._first = True

    def _apply(self, logits):
        import mlx.core as mx

        from llguidance import mlx as llg_mlx
        from llguidance import numpy as llg_numpy

        llg_numpy.fill_next_token_bitmask(self._matcher, self._bitmask, 0)
        try:
            return llg_mlx.apply_token_bitmask(logits, self._bitmask)
        except Exception:
            # The Metal kernel is version-sensitive.  The numpy path is a
            # little slower but always correct and is only used if the kernel
            # cannot be compiled on this MLX build.
            import numpy as np

            bits = np.unpackbits(
                self._bitmask[0].view(np.uint8), bitorder="little"
            )[: self.vocab_size]
            allowed = mx.array(bits.astype(np.bool_))
            width = logits.shape[-1]
            if width < self.vocab_size:
                allowed = allowed[:width]
            elif width > self.vocab_size:
                pad = mx.zeros((width - self.vocab_size,), dtype=mx.bool_)
                allowed = mx.concatenate([allowed, pad])
            return mx.where(allowed, logits, mx.array(-float("inf"), logits.dtype))

    def __call__(self, tokens, logits):
        if self._first:
            self._first = False
        else:
            try:
                last = int(tokens[-1].item())
            except Exception:
                last = int(tokens[-1])
            self._matcher.consume_token(last)
            error = self._matcher.get_error()
            if error:
                raise MLXError(f"grammar rejected token {last}: {error}")
        return self._apply(logits)

    def accepting(self) -> bool:
        return bool(self._matcher.is_accepting())


class MLXModel:
    """The subset of ``llama_cpp.Llama`` used by ESUS, implemented with MLX."""

    is_mlx = True
    chat_format = "mlx"

    def __init__(self, model_path: str | None = None, context_size: int = 8192,
                 timeout: float | None = None):
        try:
            from mlx_lm import load
        except ImportError as error:  # pragma: no cover - environment problem
            raise MLXError(
                "the MLX backend needs mlx-lm; create a Python 3.12 venv and "
                "run `pip install mlx-lm llguidance`"
            ) from error

        self.model_path = model_path or DEFAULT_MLX_MODEL
        self.model_name = self.model_path
        self.timeout = timeout
        try:
            self.model, self.tokenizer = load(self.model_path)
        except Exception as error:
            raise MLXError(f"cannot load MLX model {self.model_path}: {error}") from error
        self._n_ctx = int(context_size)
        self.last_timings: dict[str, Any] = {}
        self._llg_tokenizer = None
        # KV cache reused across calls. ESUS sends the shared body prompt
        # prefix first, so the next body only prefills its method-specific tail.
        self._cache = None
        self._cache_tokens: list[int] = []
        self._cache_len = 0
        self._last_prefix = 0
        self._eos_ids = set(getattr(self.tokenizer, "eos_token_ids", ()) or ())
        eos = getattr(self.tokenizer, "eos_token_id", None)
        if isinstance(eos, int):
            self._eos_ids.add(eos)

    # -- llama_cpp.Llama surface ---------------------------------------

    def reset(self):
        """No-op: each call uses its own KV cache."""

    def n_ctx(self) -> int:
        return self._n_ctx

    def tokenize(self, text, add_bos=True, special=False):
        if isinstance(text, bytes):
            text = text.decode("utf-8")
        return list(self.tokenizer.encode(
            text, add_special_tokens=bool(add_bos or special)
        ))

    def decode(self, tokens):
        return self.tokenizer.decode(list(tokens), skip_special_tokens=True)

    @property
    def metadata(self):
        template = getattr(self.tokenizer, "chat_template", None)
        if not template:
            inner = getattr(self.tokenizer, "_tokenizer", None)
            template = getattr(inner, "chat_template", None)
        return {"tokenizer.chat_template": template or "mlx"}

    def _sample(self, prompt_ids, max_tokens, temperature=0.0, grammar=None,
                seed=None, use_cache=True):
        import mlx.core as mx
        from mlx_lm.generate import generate_step
        from mlx_lm.models.cache import (
            can_trim_prompt_cache,
            make_prompt_cache,
            trim_prompt_cache,
        )
        from mlx_lm.sample_utils import make_sampler

        if seed is not None:
            mx.random.seed(int(seed))
        prompt_ids = list(prompt_ids)
        if not prompt_ids:
            raise MLXError("cannot generate from an empty prompt")
        if not use_cache:
            self._cache = None
            self._cache_tokens = []
            self._cache_len = 0

        # Reuse the longest common prefix with the previous call. The cache
        # already contains the previous prompt and its generated tokens, so
        # trim the generated suffix before evaluating the differing part.
        prefix = 0
        if self._cache is not None:
            if not can_trim_prompt_cache(self._cache):
                self._cache = None
            else:
                for old, new in zip(self._cache_tokens, prompt_ids):
                    if old != new:
                        break
                    prefix += 1
                drop = self._cache_len - prefix
                if drop > 0:
                    try:
                        trimmed = trim_prompt_cache(self._cache, drop)
                        self._cache_len -= trimmed
                        prefix = min(prefix, self._cache_len)
                        if self._cache_len != prefix:
                            raise ValueError("cache prefix cannot be trimmed")
                    except Exception:
                        self._cache = None
                        prefix = 0
        if self._cache is None:
            self._cache = make_prompt_cache(self.model)
            prefix = 0

        # If the whole prompt is already cached, back up one token so the
        # model has an input and produces the next-token distribution.
        if prefix >= len(prompt_ids):
            prefix = len(prompt_ids) - 1
            try:
                trimmed = trim_prompt_cache(
                    self._cache, self._cache_len - prefix)
                self._cache_len -= trimmed
                prefix = min(prefix, self._cache_len)
                if self._cache_len != prefix:
                    raise ValueError("cache prefix cannot be trimmed")
            except Exception:
                self._cache = None
                prefix = 0
        suffix = prompt_ids[prefix:]
        prompt = mx.array(suffix)
        self._last_prefix = prefix
        processor = None
        if grammar is not None:
            processor = GrammarLogitsProcessor(
                _grammar_text(grammar), self.tokenizer
            )
        processors = [processor] if processor is not None else None
        sampler = make_sampler(temp=float(temperature))

        started = time.time()
        first_at = None
        generated = []
        steps = 0
        finish_reason = "stop"
        try:
            for token, _logprobs in generate_step(
                prompt,
                self.model,
                max_tokens=int(max_tokens),
                sampler=sampler,
                logits_processors=processors,
                prompt_cache=self._cache,
            ):
                token_id = int(token.item()) if hasattr(token, "item") else int(token)
                steps += 1
                if first_at is None:
                    first_at = time.time()
                if token_id in self._eos_ids:
                    finish_reason = "stop"
                    break
                generated.append(token_id)
                if len(generated) >= int(max_tokens):
                    finish_reason = "length"
                    break
        except MLXError:
            self._cache = None
            raise
        except Exception as error:
            self._cache = None
            raise MLXError(f"MLX generation failed: {error}") from error

        ended = time.time()
        self._cache_tokens = list(prompt_ids)
        self._cache_len = len(prompt_ids) + steps
        if not use_cache:
            self._cache = None
            self._cache_tokens = []
            self._cache_len = 0
        decode_seconds = (ended - first_at) if first_at is not None else None
        if decode_seconds is not None and decode_seconds <= 0:
            decode_seconds = None
        text = self.decode(generated)
        return text, finish_reason, len(generated), started, ended, decode_seconds

    def __call__(self, prompt, max_tokens, temperature=0.0, grammar=None,
                 seed=None, **kwargs):
        prompt_ids = self.tokenize(prompt, add_bos=True)
        text, finish_reason, predicted, started, ended, decode_seconds = self._sample(
            prompt_ids, max_tokens, temperature, grammar, seed,
            use_cache=os.environ.get("ESUS_SHARED_CONTEXT") == "1",
        )
        prompt_tokens = len(prompt_ids)
        self.last_timings = {
            "prompt_n": prompt_tokens,
            "cache_n": self._last_prefix,
            "predicted_n": predicted,
            "predicted_ms": (decode_seconds or (ended - started)) * 1000.0,
        }
        return {
            "choices": [{"text": text, "finish_reason": finish_reason}],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": predicted,
                "total_tokens": prompt_tokens + predicted,
            },
            "timings": self.last_timings,
        }

    def create_chat_completion(self, messages, max_tokens, temperature=0.0,
                               seed=None, **kwargs):
        template = getattr(self.tokenizer, "apply_chat_template", None)
        if template is None:
            prompt = "\n".join(str(item.get("content", "")) for item in messages)
            prompt_ids = self.tokenize(prompt, add_bos=True)
        else:
            prompt_ids = list(template(
                messages, add_generation_prompt=True, tokenize=True
            ))
        text, finish_reason, predicted, started, ended, decode_seconds = self._sample(
            prompt_ids, max_tokens, temperature, None, seed
        )
        prompt_tokens = len(prompt_ids)
        self.last_timings = {
            "prompt_n": prompt_tokens,
            "cache_n": self._last_prefix,
            "predicted_n": predicted,
            "predicted_ms": (decode_seconds or (ended - started)) * 1000.0,
        }
        return {
            "choices": [{
                "message": {"content": text},
                "finish_reason": finish_reason,
            }],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": predicted,
                "total_tokens": prompt_tokens + predicted,
            },
            "timings": self.last_timings,
        }

    def next_token_logprobs(self, prompt, top_n=15):
        """Top logprobs after ``prompt`` for the extraction classifier."""
        try:
            import mlx.core as mx
            import numpy as np
        except ImportError as error:  # pragma: no cover
            raise MLXError(f"MLX is not available: {error}") from error

        ids = self.tokenize(prompt, add_bos=True)
        if not ids:
            raise MLXError("cannot score an empty prompt")
        logits = self.model(mx.array(ids)[None], cache=None)[0, -1, :]
        logprobs = logits - mx.logsumexp(logits)
        values = np.array(logprobs.astype(mx.float32))
        count = min(int(top_n), values.size)
        indices = np.argpartition(-values, count - 1)[:count]
        result = {}
        for index in indices:
            token = self.decode([int(index)])
            if token:
                result[token] = float(values[int(index)])
        if not result:
            raise MLXError("MLX returned an empty next-token distribution")
        return result
