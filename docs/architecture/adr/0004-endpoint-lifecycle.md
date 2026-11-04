# ADR 0004 — Session-based endpoint lifecycle

- Status: accepted
- Date: 2026-11-05

## Context

Dedicated GPU endpoints bill while running. Pausing after every track would
force a multi-minute cold start for every request. Leaving them running
overnight wastes money.

## Decision

Use a session lease:

1. On batch start, auto-resume if paused;
2. Keep the endpoint alive while any item is active or queued;
3. After the queue is empty for a configurable grace period, auto-pause;
4. Wake again on the next batch.

Pause (not scale-to-zero) is the default because it is explicit and does not
depend on request-time wake behavior. The UI always shows the real HF state.

## Consequences

- Costs are bounded around active sessions, not every request.
- A 0-second grace period is possible but causes cold-start churn.
- Direct-URL endpoints cannot be managed; those users must pause manually.
- A crash can leave the endpoint running; HF's own scale-to-zero is the backstop.
