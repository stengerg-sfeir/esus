#!/usr/bin/env bash
# Run full extraction pipeline for all prompts in complexity order,
# then run the consistency checker across all of them.

set -euo pipefail
cd "$(dirname "$0")"

MODEL="../models/Ministral-3-3B-Instruct-2512-Q4_K_M.gguf"
LOG="out/full_suite.log"
mkdir -p out

# Prompts in complexity order: name, prompt file, no-persistence flag
declare -a NAMES=(   "hello"     "cli_tool"  "gui"       "inventory" "expenses"  "library"   "60"        )
declare -a PROMPTS=( "prompts/prompt_hello_world.txt"
                     "prompts/prompt_cli_tool.txt"
                     "prompts/prompt_gui.txt"
                     "prompts/prompt_inventory.txt"
                     "prompts/prompt_expenses.txt"
                     "prompts/prompt_library_system.txt"
                     "prompts/prompt_60.txt"                )
declare -a NO_PERS=( "--no-persistence"
                     "--no-persistence"
                     ""
                     ""
                     ""
                     ""
                     ""                                     )

{
    echo "=============================="
    echo "  FULL SUITE STARTED: $(date)"
    echo "=============================="

    for i in "${!NAMES[@]}"; do
        NAME="${NAMES[$i]}"
        PROMPT="${PROMPTS[$i]}"
        NOPFLAG="${NO_PERS[$i]}"
        OUTDIR="out/${NAME}"

        echo ""
        echo "--------------------------------------------------------------"
        echo "  PROMPT: $NAME  ($PROMPT)"
        echo "  OUTPUT: $OUTDIR"
        echo "--------------------------------------------------------------"

        mkdir -p "$OUTDIR"

        python run_pipeline.py \
            --model "$MODEL" \
            --prompt "$PROMPT" \
            --output "$OUTDIR" \
            $NOPFLAG

        echo "  ✅ $NAME done."
    done

    echo ""
    echo "=============================="
    echo "  ALL EXTRACTIONS DONE: $(date)"
    echo "=============================="
    echo ""
    echo "  Running consistency checks..."
    echo ""

    python check_consistency.py --dirs \
        "hello:out/hello" \
        "cli_tool:out/cli_tool" \
        "gui:out/gui" \
        "inventory:out/inventory" \
        "expenses:out/expenses" \
        "library:out/library" \
        "60:out/60"

    echo ""
    echo "  SUITE FINISHED: $(date)"

} > "$LOG" 2>&1

echo "Log: $LOG"
echo "Tail:"
tail -n 5 "$LOG"
