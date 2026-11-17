# Kaggle validation run

This directory contains the notebook and kernel metadata for the 60-prompt
validation run. The Kaggle API key is not configured yet; these steps are
ready for the account key.

## Prerequisites

```sh
export KAGGLE_USERNAME=...
export KAGGLE_KEY=...
# or place the key at ~/.kaggle/kaggle.json
```

Replace `YOUR_KAGGLE_USERNAME` in `kernel-metadata.json`.

## Datasets

Create two private datasets.

### Code

The code dataset must contain the repository at its root (`extract_arch.py`,
`kernel/`, `prompts/validation/`, `scripts/run_validation.py`, ...):

```sh
mkdir -p /tmp/esus-code-dataset
rsync -a --exclude out --exclude .git ./ /tmp/esus-code-dataset/
cat > /tmp/esus-code-dataset/dataset-metadata.json <<'JSON'
{
  "title": "ESUS code",
  "id": "YOUR_KAGGLE_USERNAME/esus-code",
  "licenses": [{"name": "CC0-1.0"}]
}
JSON
kaggle datasets create -p /tmp/esus-code-dataset
```

### Model

The Qwen GGUF is about 2.3 GB:

```sh
mkdir -p /tmp/qwen3-4b-dataset
cp ~/Documents/models/Qwen3-4B-Instruct-2507-Q4_K_M.gguf /tmp/qwen3-4b-dataset/
cat > /tmp/qwen3-4b-dataset/dataset-metadata.json <<'JSON'
{
  "title": "Qwen3 4B Instruct 2507 Q4_K_M",
  "id": "YOUR_KAGGLE_USERNAME/qwen3-4b-instruct",
  "licenses": [{"name": "Apache-2.0"}]
}
JSON
kaggle datasets create -p /tmp/qwen3-4b-dataset
```

## Push the kernel

From the repository root:

```sh
kaggle kernels push -p kaggle
kaggle kernels status YOUR_KAGGLE_USERNAME/esus-validation-60
kaggle kernels logs YOUR_KAGGLE_USERNAME/esus-validation-60
```

The notebook builds `llama.cpp` if `llama-server` is absent, starts the Qwen
server, runs `scripts/run_validation.py`, and writes a zip under
`/kaggle/working/`.

If the full 60-prompt run exceeds the session limit, rerun in batches:

```sh
python3 scripts/run_validation.py --only prompt_01,prompt_02,prompt_03
```

The runner skips directories that already contain `metrics.json`; preserve
the same `--run-id` across sessions.
