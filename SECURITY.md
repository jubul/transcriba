# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.x (main branch) | Yes |

## Reporting a vulnerability

Do not open a public issue. Use GitHub's private reporting: **Security → Report a vulnerability** at https://github.com/jubul/transcriba/security. We answer within 7 days and coordinate the publication of the fix with the reporter.

We care especially about anything that affects a live conference: access to the panel or the ingest without a token, injecting audio or captions into someone else's room, leaking the API key or the transcripts, and any way of taking down the rooms of an event.

## Operating recommendations

- Always set `server.admin_token` before exposing the server to a network.
- Serve over HTTPS behind a reverse proxy; never expose the raw port to the Internet.
- The Gemini API key belongs in `.env` (ignored by git), not in the YAML or in screenshots.
- `data/` holds the transcripts: back it up and treat it as event content.
