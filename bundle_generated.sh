#!/bin/sh
# Put every generated Python file into one review bundle.
#
# usage: ./bundle_generated.sh [GENERATED_DIR] [OUTPUT_FILE]
#
# Defaults to the Qwen library run and writes generated_bundle.txt in the
# current directory. Attach or copy that one file; nothing needs pasting.
set -eu
src=${1:-/tmp/library_contract_qwen/generated}
out=${2:-generated_bundle.txt}
if [ ! -d "$src" ]; then
    echo "no generated directory: $src" >&2
    exit 2
fi
: > "$out"
for file in "$src"/*.py; do
    [ -f "$file" ] || continue
    printf '\n===== %s =====\n\n' "$(basename "$file")" >> "$out"
    cat "$file" >> "$out"
done
printf 'wrote %s (%s bytes)\n' "$out" "$(wc -c < "$out")"
