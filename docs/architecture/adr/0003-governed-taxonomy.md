# ADR 0003 — LLM output is governed by a frozen taxonomy

- Status: accepted
- Date: 2026-11-05

## Context

Audio-language models produce free text and labels outside the user's 641-tag
taxonomy. Letting those labels flow into exports makes data inconsistent and
unqueryable.

## Decision

The audio model sees only the task prompt. The normalizer receives a compact
catalog of the selected categories. A deterministic server-side validator then:

- resolves IDs and aliases;
- drops unknown IDs into `unmapped`;
- enforces mood exclusivity;
- clamps numbers and section times;
- keeps only requested module keys;
- writes schema/taxonomy versions and warnings.

## Consequences

- Every result is auditable and queryable.
- The LLM cannot silently invent IDs.
- Ambiguous labels may be dropped rather than forced; reviewers see `unmapped`.
- Taxonomy changes require a new version and a generator run.
