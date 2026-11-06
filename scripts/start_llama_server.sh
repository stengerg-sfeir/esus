#!/usr/bin/env bash
# Start llama-server for ESUS. Speculative decoding is opt-in.
#
#   ./scripts/start_llama_server.sh
#
# Environment (all optional):
#   MODEL       target model       default: Qwen3-4B-Instruct-2507-Q4_K_M
#   DRAFT       draft model        default: Qwen3-0.6B-Q4_K_M
#   CTX         context size       default: 16384
#   SLOTS       parallel slots     default: 1
#   PORT        server port        default: 8080
#   SPEC        1 = draft-simple   default: 0; use 1 only to experiment
#   CACHE_RAM   system RAM for KV cache (MiB)  default: 4096 (0 = off)
#   KV_UNIFIED  on/off             default: on
#   LLAMA_SERVER_BIN               default: llama-server from PATH
#
# Speculative decoding needs a draft model with the same tokenizer/vocabulary
# as the target. Qwen3-0.6B is the matching small model for Qwen3-4B. The
# Qwen3-Reranker-0.6B in the models folder is a scoring model, not a draft
# model.
#
# If the draft model is missing, the script stops and prints a download
# command. It never downloads a model on its own.

set -euo pipefail

MODEL="${MODEL:-$HOME/Documents/models/Qwen3-4B-Instruct-2507-Q4_K_M.gguf}"
DRAFT="${DRAFT:-$HOME/Documents/models/Qwen3-0.6B-Q4_K_M.gguf}"
CTX="${CTX:-16384}"
SLOTS="${SLOTS:-1}"
PORT="${PORT:-8080}"
SPEC="${SPEC:-0}"
CACHE_RAM="${CACHE_RAM:-4096}"
KV_UNIFIED="${KV_UNIFIED:-on}"
BIN="${LLAMA_SERVER_BIN:-$(command -v llama-server || true)}"

if [[ -z "$BIN" ]]; then
    echo "llama-server not found. Install it (for example: brew install llama.cpp)" >&2
    exit 1
fi
if [[ ! -f "$MODEL" ]]; then
    echo "Target model not found: $MODEL" >&2
    exit 1
fi

args=(
    -m "$MODEL"
    -c "$CTX"
    -ngl 99
    -t 6
    -fa on
    -ub 1024
    -b 1024
    --port "$PORT"
    -np "$SLOTS"
    --metrics
    --context-shift
)

# KV cache RAM limit (MiB); 0 means unlimited (llama.cpp default)
if [[ -n "$CACHE_RAM" && "$CACHE_RAM" != "0" ]]; then
    args+=(--cache-ram "$CACHE_RAM")
fi

# Unified KV cache across slots (saves VRAM/RAM when SLOTS > 1)
if [[ "$KV_UNIFIED" == "on" ]]; then
    args+=(--kv-unified)
fi

if [[ "$SPEC" == "1" ]]; then
    if [[ ! -f "$DRAFT" ]]; then
        cat >&2 <<EOF
Draft model not found: $DRAFT

Download a Qwen3-0.6B GGUF and point DRAFT at it, for example:

  huggingface-cli download NANI-Nithin/Qwen3-0.6B-GGUF \
      Qwen3-0.6B-Q4_K_M.gguf --local-dir "$HOME/Documents/models"

Then run this script again. To start without speculative decoding:

  SPEC=0 ./scripts/start_llama_server.sh
EOF
        exit 1
    fi
    args+=(
        -md "$DRAFT"
        --spec-type draft-simple
        --spec-draft-ngl 99
    )
fi

echo "llama-server: model=$MODEL" >&2
echo "  context=$CTX, slots=$SLOTS, port=$PORT, speculative=$SPEC, cache_ram=${CACHE_RAM}MiB, kv_unified=$KV_UNIFIED" >&2
[[ "$SPEC" == "1" ]] && echo "  draft=$DRAFT" >&2

exec "$BIN" "${args[@]}"