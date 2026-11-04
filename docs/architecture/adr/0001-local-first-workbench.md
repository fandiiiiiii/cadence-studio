# ADR 0001 — Local-first control plane

- Status: accepted
- Date: 2026-11-05

## Context

The workbench handles copyrighted audio, provider API keys, and annotation
results. A cloud-hosted control plane would add identity, tenancy, storage, and
compliance work before the first track can be annotated.

## Decision

Run the UI, queue, SQLite, audio files, exports and secrets on the user's
machine. Send audio only to the user-configured inference endpoint and text
only to the user-configured normalizer. Bind to loopback.

## Consequences

- Double-click launch is possible; no server hosting required.
- API keys can be protected with OS-level DPAPI.
- No multi-user/RBAC; not suitable for LAN/public deployment.
- Data portability is a folder copy, except DPAPI secrets.
