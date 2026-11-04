# Agent and maintainer guidance

This repository is a local-first annotation workbench. Before changing code:

1. Read `README.md`, `docs/product/annotation-schema.md`, and
   `docs/architecture/system.md`.
2. Never claim that a model run, GPU memory fit, license, or 500-track/day
   target has been verified unless there is a recorded real run in
   `docs/quality/benchmark.md` with hardware and model revision.
3. Audio is sent only to the user-configured inference endpoint. Text
   observations are sent only to the user-configured normalizer. Do not add
   silent third-party calls.
4. Do not commit `data/`, `outputs/`, `.env`, secrets, model weights, audio, or
   exported xlsx/json/md files.
5. The taxonomy source is vendored from the user's `workbench-2026-11-03`
   snapshot. Keep the SHA-256 in `taxonomy.json` and update it with the
   generator, not by hand.
6. Keep the API and UI contracts aligned: module IDs, status vocabulary,
   error shapes, and export keys.

## High-risk areas

- `pipeline.py`: queue state transitions, retries, endpoint lifecycle.
- `normalizer.py`: schema and taxonomy enforcement.
- `hf_endpoints.py`: token handling, pause/resume semantics.
- `deploy/inference-endpoint/server.py`: model loading and GPU limits.

Any change to these requires tests and a note in `CHANGELOG.md`.
