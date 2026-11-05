# MLX backend (Apple Silicon)

ESUS can run the extraction and generation model in process with
[MLX](https://github.com/ml-explore/mlx) instead of a `llama-server` process.
The backend is selected with `--model mlx`.

## Install

MLX has Apple Silicon wheels for Python 3.12; the machine's default Python 3.14
in this checkout cannot install them. Create the local virtualenv once:

```bash
python3.12 -m venv .venv-mlx
.venv-mlx/bin/pip install -r requirements-mlx.txt
```

The model is a 4-bit MLX conversion. It can be downloaded by `mlx-lm` on the
first run, or fetched explicitly:

```bash
.venv-mlx/bin/python - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download(
    "mlx-community/Qwen3-4B-Instruct-2507-4bit",
    local_dir="$HOME/Documents/models/Qwen3-4B-Instruct-2507-4bit-mlx",
)
PY
export MLX_MODEL="$HOME/Documents/models/Qwen3-4B-Instruct-2507-4bit-mlx"
```

`MLX_MODEL` may be a Hugging Face model id or a local MLX directory. If it is
unset, the default is `mlx-community/Qwen3-4B-Instruct-2507-4bit`.

## Run

```bash
.venv-mlx/bin/python main.py prompts/prompt_expenses.txt \
    --model mlx -o out/expenses_mlx

# or the two phases separately
.venv-mlx/bin/python extract_arch.py --model mlx \
    --output out/expenses_mlx --requirements prompts/prompt_expenses.txt --no-chat
.venv-mlx/bin/python generator.py out/expenses_mlx --model mlx
```

The whole pipeline uses `.venv-mlx/bin/python`, so the child extractor and
generator also see MLX. Do not invoke `main.py` with the system Python when using
`--model mlx`.

## Grammar handling

llama.cpp accepts GBNF directly. MLX has no native grammar sampler, so ESUS:

1. parses the same GBNF text with `llguidance.gbnf_to_lark`;
2. compiles the Lark grammar with `llguidance.LLMatcher`;
3. fills a token bitmask before every decode step and applies it to the MLX
   logits with `llguidance.mlx.apply_token_bitmask`.

The grammar text, prompt, temperature and seed are unchanged from the
llama.cpp/server path. The translation is validated by
`tests/test_mlx_backend.py` for every open extraction grammar.

## Notes

- The backend is in `kernel/extraction/mlx_backend.py`; only `runner.load_model`
  imports it, and only when `--model mlx` is selected.
- `mlx-lm` does not reuse a prompt cache across separate ESUS calls, so the
  `cached_tokens` field reported by the runner is zero for this backend.
- `--model server` remains the default; the MLX backend is opt-in.
