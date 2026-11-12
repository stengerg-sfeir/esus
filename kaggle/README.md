# Kaggle validation run

This directory contains the notebook and kernel metadata for the 60-prompt
validation run. The notebook runs one worker per visible GPU (up to two),
merges the shards into one run directory, and writes a self-contained zip
under `/kaggle/working/`.

## Prerequisites

```sh
export KAGGLE_USERNAME=...
export KAGGLE_KEY=...
# or place the token at ~/.kaggle/access_token
```

Replace `gillesstenger` below if you use another Kaggle account.

## Datasets

Create two private datasets.

### Code

The notebook expects a single zip file named `esus-code.bundle` at the root
of `/kaggle/input/esus-code-bundle/`. That file contains the repository at
its root (`extract_arch.py`, `kernel/`, `prompts/validation/`,
`scripts/run_validation.py`, ...):

```sh
mkdir -p /tmp/esus-code-bundle
cd /path/to/esus
zip -qr /tmp/esus-code-bundle/esus-code.bundle . \
  -x 'out/*' '.git/*' '__pycache__/*' '*.pyc' \
     'esus/*' 'llama.cpp/*' 'session.json'
cat > /tmp/esus-code-bundle/dataset-metadata.json <<'JSON'
{
  "title": "ESUS code bundle",
  "id": "gillesstenger/esus-code-bundle",
  "licenses": [{"name": "CC0-1.0"}]
}
JSON
kaggle datasets create -p /tmp/esus-code-bundle
```

`esus-code.bundle` is a normal zip archive despite the name. The notebook
extracts it into `/kaggle/working/esus`.

### Model

The Qwen GGUF is about 2.3 GB:

```sh
mkdir -p /tmp/qwen3-4b-dataset
cp ~/Documents/models/Qwen3-4B-Instruct-2507-Q4_K_M.gguf /tmp/qwen3-4b-dataset/
cat > /tmp/qwen3-4b-dataset/dataset-metadata.json <<'JSON'
{
  "title": "Qwen3 4B Instruct 2507 Q4_K_M",
  "id": "gillesstenger/qwen3-4b-instruct",
  "licenses": [{"name": "Apache-2.0"}]
}
JSON
kaggle datasets create -p /tmp/qwen3-4b-dataset
```

## Push the kernel

From the repository root:

```sh
kaggle kernels push -p kaggle
kaggle kernels status gillesstenger/esus-validation-60-prompts
kaggle kernels logs gillesstenger/esus-validation-60-prompts
```

The notebook downloads a CUDA `llama-server` prebuilt if the image does not
provide one, starts one server with two parallel decode slots, and runs
`scripts/run_validation.py --concurrency 2`. The two slots share the loaded
model; each prompt is still executed exactly once. The run directory is
archived as `/kaggle/working/validation-<run-id>.zip`.

If the full 60-prompt run exceeds the session limit, rerun in batches:

```sh
python3 scripts/run_validation.py --only prompt_01,prompt_02,prompt_03
```

The runner skips directories that already contain `metrics.json`; preserve
the same `--run-id` across sessions.
