# Security policy

## Threat model

Cadence Studio is a **single-user, local-first workbench**. It binds to
`127.0.0.1`, rejects non-local Host headers, and rejects cross-site write
requests. It is not designed to be exposed to a LAN or the public internet.

## Secrets

- API tokens are stored in `data/secrets.bin` using Windows DPAPI, scoped to the
  current Windows user and machine.
- Secrets are never returned by the HTTP API; the UI only receives a masked hint
  and a configured/not-configured flag.
- `.env`, `data/`, model weights, audio, exports, and databases are ignored by
  Git. Do not add them manually.
- Moving the data directory to another machine or Windows account makes the
  existing secrets unreadable. Re-enter tokens in Settings.

## Report a vulnerability

Do not open a public issue containing a token, audio sample, or private data.
Send the owner a private report with:

- affected version/commit;
- reproduction steps using synthetic data;
- impact and suggested mitigation.

## Operational guidance

- Use a fine-grained Hugging Face token with only the required Inference
  Endpoints permissions.
- Rotate a token immediately if it appears in a screenshot, terminal output,
  or Git history.
- Back up `data/` only to encrypted storage; exports may contain copyrighted
  metadata or lyrics.
- Review model output before publishing or using it for rights decisions.
