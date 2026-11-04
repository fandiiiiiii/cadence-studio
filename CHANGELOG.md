# Changelog

All notable changes to Cadence Studio are documented here.

## [0.1.0] — 2026-11-05

### Added

- Local FastAPI workbench with a dark/light single-page UI.
- 641-tag taxonomy, 15 rules, 7 formulas and 20 structure labels.
- 15 configurable annotation modules; only requested modules are emitted.
- Persistent SQLite queue with retries, pause/resume, per-item status and SSE.
- Hugging Face Endpoints lifecycle adapter (status, resume, pause,
  scale-to-zero) with automatic warm-up and idle pause.
- Custom container contract for MOSS-Music and Music Flamingo.
- DeepSeek/OpenAI-compatible normalization with strict ID governance,
  approximate mapping traceability and one repair pass.
- Raw audio-model output, normalizer raw output, validated JSON and mappings.
- XLSX, JSON, Markdown, CSV and ZIP exports; per-item JSON/Markdown.
- Windows DPAPI secret storage; local-only HTTP guard.
- Demo batch with original generated audio; first-run empty state.
- Unit/API tests, CI workflow, enterprise docs and operator setup guides.

### Known limitations

- No real GPU run is included. A10G fit, throughput and model quality must be
  measured with the first licensed track.
- Music Flamingo is noncommercial under its model card; confirm licenses.
- The custom container requires an external image registry and Docker build.
- Direct-URL endpoints cannot be paused/resumed; only HF-managed endpoints can.
