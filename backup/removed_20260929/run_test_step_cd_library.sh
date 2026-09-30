#!/usr/bin/env bash

cd "$(dirname "$0")"

LOG="out/step_cd_library.log"
mkdir -p out

{
    echo "Started at: $(date)"
    echo "---"
    python test_step_cd.py \
        --model "../models/Ministral-3-3B-Instruct-2512-Q4_K_M.gguf" \
        --prompt "prompts/prompt_library_system.txt" \
        --output "out/step_cd_library"
    echo "---"
    echo "Finished at: $(date)"
    echo "Exit code: $?"
} > "$LOG" 2>&1
