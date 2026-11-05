# Changelog

All notable changes to Cadence Studio are documented here.

## [0.2.0] — 2026-11-05

### Added

- Editable daily target on the overview runway and in Settings → Workspace.
- Genre hierarchy: every result keeps multiple independent genres with
  level-1/2/3 lineage (`Pop › K-Pop`), while `primary`/`secondary` are only
  convenience projections.
- Collapsible taxonomy browser: level-1 styles first, arrows expand
  level-2/3 children; expand-all/collapse controls.
- Human-facing sequence numbers start at 01 in every category. Stable internal
  IDs (e.g. `genre-2`) are retained and shown only as technical IDs.
- The vendored taxonomy reference now has a 1-based `序号` column before the
  stable ID; IDs remain unchanged for traceability.
- Supplemental `Extra` tags are automatically included in the Genre
  normalizer catalog; the audio model is not separately prompted for them.
- Native audio-model prompts: no 641-tag catalog, tag IDs, or standard
  structure vocabulary is sent to the audio model.
- Hardware presets for T4, L4, A10G, L40S, A100, H100, H200, RTX PRO 6000,
  multi-GPU, and custom hardware, with recommended concurrency, audio cap,
  output tokens, timeout, and reference hourly price.
- Per-route `max_new_tokens` and `max_audio_seconds` controls.
- DeepSeek defaults updated to `deepseek-flash`; automatic migration from
  retired `deepseek-chat` / `deepseek-reasoner` defaults.
- DeepSeek thinking mode toggle; normalization uses `thinking=disabled` by
  default for lower latency.
- Result schema `1.1.0` for genre `items` / hierarchy fields.

### Fixed

- Taxonomy category tabs now update their active state immediately; the
  previously selected category no longer stays highlighted.
- The first tag is selected when opening a category, so the selected row is
  visible before the first click.
- The `全部` view now renders Genre as a collapsible hierarchy (01/01.01)
  before the other flat categories.
- Removed the technical “stable ID / display sequence” line from the taxonomy
  detail panel; internal IDs remain in API/exports for traceability.
- Settings save bar no longer remains visible after a successful save.
- Success toasts auto-dismiss after 3 seconds and duplicate success toasts are
  removed.
- Existing configs are migrated with hardware profile and output-token
  defaults.
- Export columns include first-level, second-level, supplemental, and complete
  genre paths.

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
