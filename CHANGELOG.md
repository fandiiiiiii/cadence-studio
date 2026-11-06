# Changelog

All notable changes to Cadence Studio are documented here.

## [0.2.4] — 2026-11-05

### Fixed

- Flamingo container: add `librosa>=0.10,<1`. The MusicFlamingo processor calls
  `load_audio`, which requires librosa while decoding request audio. Without it
  `/health` succeeds but every `/v1/annotate` request raises
  `ImportError: load_audio requires the librosa library` and returns HTTP 500.

## [0.2.3] — 2026-11-05

### Fixed

- Flamingo container: add an audio-decoding dependency. Initial diagnosis was
  torchcodec; the endpoint logs later showed the actual requirement is librosa
  (0.2.4).

## [0.2.2] — 2026-11-05

### Fixed

- Inference endpoint "Test" returned a 422 `path.action` validation error because
  `/inference/{route_id}/test` was shadowed by the dynamic lifecycle route.
  The health test route now resolves before `{action}`.
- MOSS raw output could fall into a repeated genre-list loop and consume the
  whole output budget. The audio prompt now caps the genre list at 5 unique
  terms and generation uses a repetition penalty plus a 6-gram no-repeat guard.
- Idle endpoint shutdown now uses a dedicated post-completion timer instead of
  relying only on the scheduler tick. A new batch cancels the timer before it
  can run; the timer records `endpoint_auto_scaled_to_zero` or a warning on
  failure.
- Reviewing an item (approve / needs changes) no longer rerenders the drawer
  and replaces its `<audio>` element. Playback continues with the same element;
  the play/pause icon stays in sync and the old and new tracks cannot overlap.
- HF endpoint route locks are now reentrant. `ensure_ready()` holds the route
  lock while calling `resume()`, which takes the same lock; the old non-reentrant
  lock deadlocked when an endpoint was `scaledToZero`, leaving items stuck at
  `checking_endpoint`.

### Added

- **Scale to zero** is now the default idle action, with a 0-second grace by
  default. When the queue is empty, Cadence calls HF
  `/scale-to-zero` immediately instead of pausing the endpoint.
- A `中/EN` switch in the top bar toggles all taxonomy labels between Chinese
  and English. The preference is stored locally.
- `result_summary` now carries `genre_en` and `mood_en` so list views can show
  English labels without loading each item's full JSON.
- Per-module label language settings for genre, mood, scene, instruments,
  vocal, language, and supplemental tags; the same settings drive the UI and
  XLSX/CSV/Markdown exports.
- DeepSeek project rules and reference files at batch creation:
  `.docx`, digital `.pdf`, `.xlsx`, `.txt`, `.md`, `.csv`, and `.json` are
  extracted, summarized into an audio-model prompt by DeepSeek, and injected
  into normalization. Source documents go only to DeepSeek; the audio model
  receives only the generated prompt. Scanned PDFs are rejected with an OCR
  hint rather than silently ignored.
- The SSE cursor now starts at the latest event on page load, so historical
  `item_failed` events no longer replay as fresh error toasts.
- Common video containers are accepted: MP4, M4V, MOV, MKV, WEBM, AVI, MPEG,
  MPG, WMV, FLV, 3GP. ffmpeg extracts the audio track; videos without an audio
  stream are skipped with a clear import warning.
- QT taxonomy supplement: 65 new Genre labels from `对外曲风标签_迭代版0903.xlsx`
  and 35 new Instrument/timbre labels from `QT_音乐caption精标规则文档.md`,
  plus 7 alias additions. The vendored 641-tag snapshot is unchanged; the
  supplement is merged at load time from `taxonomy.additions.json`. Mood and
  Scene are untouched.
- The structure prompt now asks for real boundaries, full-duration coverage, and
  allows decimal seconds. It explicitly forbids fixed 15/30-second grids and
  template sections. The normalizer warns when structure stops far before the
  track end or every boundary sits on a 5-second grid.
- `instruments.additional` preserves non-catalog instrument types and timbres
  from the audio model as free text, including terms the normalizer places in
  `unmapped`; exports include a `补充乐器/音色` column. Result schema is now
  `1.2.0`.

## [0.2.1] — 2026-11-05

### Fixed

- MOSS endpoint startup: the Hub checkpoint ships `audio_config` as a dict,
  while its modeling code expects attribute access. Convert it to an
  attribute config before `from_pretrained`; this fixes the
  `'dict' object has no attribute 'downsample_hidden_size'` failure.

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
