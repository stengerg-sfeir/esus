# Reviewed generation inputs (2026-11-10 defect-fix pass)

These are copies of the review sidecars that were beside the generated outputs
under `out/` during the behavioral defect-fix pass.  `out/` is intentionally
untracked (see `.gitignore`), so this directory preserves the inputs needed to
regenerate the same reviewed bodies.

Each program record says `decided_by: "assistant"`; these are assistant-filled
review decisions made during the test phase, not claimed human authorship.
`method_programs.json` also records the requirements SHA it was reviewed
against.  The SHA values are:

- `60_program_clean`: `009bd41c9b1bbcbf35e2a0ad999fde416e3655fdaf079841b11cac78d84edd9f`
- `inventory_same_conditions_final`: `b9c933fce0957b1671df5df7e30a5ef2b1c33e670df85753fae631f6cbb75716`
- `gui_same_conditions_final`: `797396aa6da996f220987f5713e3e5fb3a1a89d1ab6e7a626d17c853eca87cba`
- `expenses_ngram_mod`: `0165d441bca97899220fe4b75355a25deb0db465b0ef4ce2bc92730833904f50`
- `library_same_conditions_final`: `a52edca22d3a421c331dfb6c7d6fd00cb903dc10d12391c073fbe94b9e854b9f`

To reproduce one output after a fresh extraction, copy its files back beside
the documents before generation, for example:

```sh
cp backup/review-inputs-2026-11-10/60_program_clean/*.json out/60_program_clean/
python3.12 generator.py out/60_program_clean --model server \
  --stub-context exact --reuse-reviewed-bodies
```

The library directory also preserves the recorded CLI route that sends
`library book search --query` through `LibraryService.search_books` instead of
the repository search.
