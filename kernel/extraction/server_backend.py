"""HTTP backend for an already-running `llama-server`.

`--model server` selects this backend. The server owns the GGUF, its context,
the Metal/CPU placement, and the grammar implementation; this module only sends
prompts and turns the responses back into the small surface `runner` expects.

The server is deliberately not started here. Keeping process ownership out of
the extractor means a long extraction can use a warm server, a remote server,
or a server started with flags this code should not guess (model, context,
parallel slots, API key). Point the run at it with `LLAMA_SERVER_URL`:

    llama-server -m MODEL.gguf -c 8192 -ngl 99 -fa on --port 8080
    LLAMA_SERVER_URL=http://127.0.0.1:8080 \
        python3.12 extract_arch.py --model server --output out/library ...

The endpoint is llama-server's native `/completion`, not the OpenAI adapter:
the native endpoint accepts a GBNF `grammar` directly, returns
`completion_probabilities`, and reports prompt and decode timings separately.
The OpenAI `/v1/chat/completions` endpoint is used for the free-form body asks,
which are chat-shaped rather than grammar-constrained.
"""

import json
import os
import urllib.error
import urllib.request

DEFAULT_SERVER_URL = "http://127.0.0.1:8080"
SERVER_MODEL = "server"
DEFAULT_TIMEOUT = 600.0


class ServerError(RuntimeError):
    """A llama-server request failed, or the server is not reachable."""


class ServerUnavailable(ServerError):
    """No llama-server answered at the configured URL."""


def _grammar_text(grammar) -> str:
    """Return the GBNF text from a `LlamaGrammar` or a plain string."""
    if isinstance(grammar, str):
        return grammar
    text = getattr(grammar, "_grammar", None)
    if isinstance(text, str):
        return text
    raise ServerError("the server backend needs a GBNF grammar string")


class ServerModel:
    """The subset of `llama_cpp.Llama` used by the extraction runner.

    `runner` only needs tokenization, the context size, reset/caching, a
    completion call, a chat call, and a next-token distribution. Implementing
    that surface here keeps `pipeline.py` and the step prompts independent of
    where generation happens.
    """

    is_server = True

    def __init__(self, url=None, context_size=8192, timeout=None):
        self.url = (url or os.environ.get("LLAMA_SERVER_URL")
                    or DEFAULT_SERVER_URL).strip().rstrip("/")
        self.api_key = os.environ.get("LLAMA_SERVER_API_KEY")
        self.timeout = float(timeout or os.environ.get("LLAMA_SERVER_TIMEOUT")
                             or DEFAULT_TIMEOUT)
        self.last_timings = {}
        self._props = self._get("/props")
        settings = self._props.get("default_generation_settings") or {}
        n_ctx = settings.get("n_ctx")
        self._n_ctx = int(n_ctx) if isinstance(n_ctx, (int, float)) and n_ctx > 0 \
            else int(context_size)
        self.model_name = (self._props.get("model_alias")
                           or self._props.get("model_path")
                           or "server")
        self.chat_format = "llama-server"

    # -- transport -----------------------------------------------------

    def _request(self, method, path, payload=None):
        url = f"{self.url}{path}"
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(url, data=data, headers=headers,
                                         method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:1000]
            raise ServerError(
                f"{method} {path} returned {error.code}: {detail}"
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            reason = getattr(error, "reason", error)
            raise ServerUnavailable(
                f"llama-server is not reachable at {self.url} ({reason}); "
                f"start llama-server there or set LLAMA_SERVER_URL"
            ) from error
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ServerError(
                f"{method} {path} returned non-JSON: {raw[:500]!r}"
            ) from error

    def _get(self, path):
        return self._request("GET", path)

    def _post(self, path, payload):
        return self._request("POST", path, payload)

    # -- llama_cpp.Llama surface ---------------------------------------

    def reset(self):
        """No-op: llama-server applies `cache_prompt` per request itself."""

    def n_ctx(self):
        return self._n_ctx

    def tokenize(self, text, add_bos=True, special=False):
        """Tokenize through `/tokenize` (the server's own vocabulary)."""
        if isinstance(text, bytes):
            text = text.decode("utf-8")
        response = self._post(
            "/tokenize",
            {"content": text, "add_special": bool(add_bos or special)},
        )
        tokens = response.get("tokens")
        if not isinstance(tokens, list):
            raise ServerError(f"/tokenize returned no token list: {response!r}")
        return tokens

    @property
    def metadata(self):
        # The server exposes a chat endpoint; `has_chat_template` only needs a
        # truthy template to choose `create_chat_completion` over raw text.
        return {"tokenizer.chat_template": "llama-server"}

    def __call__(self, prompt, max_tokens, temperature=0.0, grammar=None,
                 seed=None, **kwargs):
        """Run one grammar-constrained (or free) completion."""
        payload = {
            "prompt": prompt,
            "n_predict": int(max_tokens),
            "temperature": temperature,
            "cache_prompt": True,
            "id_slot": 0,
        }
        if grammar is not None:
            payload["grammar"] = _grammar_text(grammar)
        if seed is not None:
            payload["seed"] = int(seed)
        response = self._post("/completion", payload)
        self.last_timings = response.get("timings") or {}

        text = response.get("content") or ""
        predicted = response.get("tokens_predicted")
        if not isinstance(predicted, int):
            predicted = 0
        # `tokens_cached` is the slot's cache size, not necessarily the number
        # of prompt tokens reused; the timings split is the accurate count.
        prompt_tokens = self.last_timings.get("prompt_n")
        cached = self.last_timings.get("cache_n")
        if isinstance(prompt_tokens, int) and isinstance(cached, int):
            prompt_tokens += cached
        if not isinstance(prompt_tokens, int):
            prompt_tokens = response.get("tokens_evaluated") or 0
        finish_reason = (
            "length"
            if response.get("truncated") or response.get("stop_type") == "limit"
            else "stop"
        )
        return {
            "choices": [{"text": text, "finish_reason": finish_reason}],
            "usage": {
                "prompt_tokens": prompt_tokens or 0,
                "completion_tokens": predicted,
                "total_tokens": (prompt_tokens or 0) + predicted,
            },
            "timings": self.last_timings,
        }

    def create_chat_completion(self, messages, max_tokens, temperature=0.0,
                               seed=None, **kwargs):
        """Run one chat-template completion for the body-writing pass."""
        payload = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": int(max_tokens),
            "temperature": temperature,
            "stream": False,
            "cache_prompt": True,
            "id_slot": 0,
        }
        if seed is not None:
            payload["seed"] = int(seed)
        response = self._post("/v1/chat/completions", payload)
        self.last_timings = response.get("timings") or {}
        choice = (response.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        return {
            "choices": [{
                "message": {"content": message.get("content") or ""},
                "finish_reason": choice.get("finish_reason") or "stop",
            }],
            "usage": response.get("usage") or {},
            "timings": self.last_timings,
        }

    def next_token_logprobs(self, prompt, top_n=15):
        """Top logprobs after `prompt`, using llama-server's native endpoint.

        `/completion` with `n_predict=1` and `n_probs` returns the sampled
        token plus `completion_probabilities[0].top_logprobs`; the classifier
        consumes the latter exactly like the local last-logits helper.
        """
        response = self._post(
            "/completion",
            {
                "prompt": prompt,
                "n_predict": 1,
                "temperature": 0.0,
                "n_probs": int(top_n),
                "cache_prompt": True,
                "id_slot": 0,
            },
        )
        probabilities = response.get("completion_probabilities") or []
        top = (probabilities[0].get("top_logprobs")
               if probabilities and isinstance(probabilities[0], dict) else None)
        if not isinstance(top, list):
            raise ServerError(
                "llama-server did not return completion_probabilities; "
                "the server may be too old for --model server"
            )
        result = {}
        for item in top:
            if not isinstance(item, dict):
                continue
            token = item.get("token")
            logprob = item.get("logprob")
            if isinstance(token, str) and isinstance(logprob, (int, float)):
                result[token] = float(logprob)
        if not result:
            raise ServerError("llama-server returned an empty next-token distribution")
        return result
