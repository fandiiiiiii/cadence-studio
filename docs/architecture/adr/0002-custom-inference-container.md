# ADR 0002 — Custom container instead of managed HF engines

- Status: accepted
- Date: 2026-11-05

## Context

MOSS-Music requires a fork of SGLang; Music Flamingo is not servable by current
vLLM. Hugging Face dedicated Endpoints expose managed vLLM/SGLang images, but
neither can load these models reliably in November 2026.

## Decision

Ship a small FastAPI inference server as a custom container. It exposes
`/health` and `/v1/annotate`, loads one model family per image, serializes
generation, and returns raw text plus usage/timings.

## Consequences

- The workbench has a stable model-agnostic contract.
- The user must build/push an image and create a custom Endpoint manually.
- The container can be tested with `DRY_RUN=1` without a GPU.
- The user owns model compatibility, GPU sizing, and license verification.
