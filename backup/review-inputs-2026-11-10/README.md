# Reviewed generation inputs (2026-11-10 pass)

These are copies of the review sidecars beside the generated outputs during the
LLM-first restoration pass.  `out/` is intentionally untracked (see
`.gitignore`), so this directory preserves the inputs needed to regenerate the
same outputs.

## LLM-first policy

The mechanical emitter is intentionally incomplete.  Repository/service bodies
that it cannot derive are completed by the LLM and tagged
`[llm-written by server — review]`.  The per-method `method_programs.json`
substitutions introduced in the previous pass were removed, except for the
three pre-existing `60_program_clean` programs (`confirm_order`,
`cancel_order`, `ship_order`), which predate this pass.

`method_slots.json` records the attended slot decisions.  In the expenses
output the two aggregate slots are deliberately recorded with empty `slots`
(`get_monthly_spending_by_category`, `get_yearly_spending_summary`): that is an
explicit decision to leave those bodies to the LLM instead of emitting the
incomplete mechanical aggregate.  The library route keeps
`library book search --query` on `LibraryService.search_books`.

All review decisions copied here are assistant-filled
(`decided_by: "assistant"`); they are not claimed human authorship.

## Requirements SHAs

- `60_program_clean`: `009bd41c9b1bbcbf35e2a0ad999fde416e3655fdaf079841b11cac78d84edd9f`
- `inventory_same_conditions_final`: `b9c933fce0957b1671df5df7e30a5ef2b1c33e670df85753fae631f6cbb75716`
- `gui_same_conditions_final`: `797396aa6da996f220987f5713e3e5fb3a1a89d1ab6e7a626d17c853eca87cba`
- `expenses_ngram_mod`: `0165d441bca97899220fe4b75355a25deb0db465b0ef4ce2bc92730833904f50`
- `library_same_conditions_final`: `a52edca22d3a421c331dfb6c7d6fd00cb903dc10d12391c073fbe94b9e854b9f`

## Reproduction

Copy the files back beside the documents before generation, for example:

```sh
cp backup/review-inputs-2026-11-10/60_program_clean/*.json out/60_program_clean/
python3.12 generator.py out/60_program_clean --model server \
  --stub-context exact --reuse-reviewed-bodies
```

For the LLM-filled outputs, omit `--reuse-reviewed-bodies` when starting from a
clean generated directory so every refused body is asked for again.
