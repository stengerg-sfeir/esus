#!/usr/bin/env bash

cd "$(dirname "$0")"

LOG="out/step_h_expenses_retry.log"
mkdir -p out

{
    echo "Started at: $(date)"
    echo "---"
    python test_step_h.py \
        --model "../models/Ministral-3-3B-Instruct-2512-Q4_K_M.gguf" \
        --prompt "prompts/prompt_expenses.txt" \
        --output "out/step_cdh_expenses_persistence_ports.json"
    echo "---"
    echo "Finished at: $(date)"
    echo "Exit code: $?"
} > "$LOG" 2>&1
