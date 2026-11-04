# Contributing

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

Run the app with `.\启动 Cadence.cmd` or:

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -m cadence_studio --no-browser
```

## Change rules

1. Read `docs/product/annotation-schema.md` before changing output fields.
2. Taxonomy IDs are stable. Never silently rename an ID; add an alias or a new
   tag in a new taxonomy version.
3. Every result must retain the audio-model raw output, the normalizer output,
   requested modules, model route IDs, and timings.
4. The normalizer must never invent a taxonomy ID. Unknown values go to
   `unmapped` and are visible to reviewers.
5. Preserve the “only requested keys” contract. A caption-only request must not
   return genre, BPM, or other modules.
6. Do not put audio, API keys, databases, or model weights in the repository.
7. Update docs and tests in the same change.

## Verification

```powershell
$env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests tools
node --check src\cadence_studio\web\app.js
```

For UI changes, verify at 1440×1100 and 390×844; test dark and light themes;
test the new-batch modal, batch table, item drawer, settings save, and export.

## Commit style

Use imperative, scoped subjects:

```text
feat(pipeline): preserve raw output on normalization failure
fix(hf): treat 400 already-running as idempotent resume
docs(operations): document A10G first-track validation
```
