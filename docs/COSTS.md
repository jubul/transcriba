# Estimated costs

🇦🇷 [Versión en español](es/COSTOS.md)

Prices taken from https://ai.google.dev/gemini-api/docs/pricing on 2026-09-24 (check them before the event: they change). All models used have a **free tier** with rate limits; for several rooms in parallel the paid tier is needed.

| Model | Use in transcriba | Price |
|---|---|---|
| `gemini-3.5-transcribe-live` | streaming ASR (`gemini-live` engine) | audio in US$ 0.005/min · text out US$ 0.004/min |
| `gemini-3.5-flash-lite` | text translation (all cloud engines) | in US$ 0.30/1M tok · out US$ 2.50/1M tok |
| `gemini-3.5-live-translate-preview` | `gemini-live-translate` engine (speech→speech+text) | audio in US$ 0.0053/min · audio out US$ 0.0315/min |
| `gemini-3.5-flash-lite` with audio | `gemini-chunked` engine | audio = 32 tokens/s → US$ 0.30/1M tok |
| Whisper + Gemma 4 (Ollama) | `local` engine | US$ 0 (your own hardware) |

## Cost per room-hour (estimate)

Assumptions: speaker talking 80 % of the time, ~600 sentences/hour, translation prompt ≈ 450 input tokens + 40 output tokens per sentence.

| Engine | ASR | Translation | **Total / hour** |
|---|---|---|---|
| `gemini-live` (recommended) | 0.54 | 0.14 | **≈ US$ 0.70** |
| `gemini-live-translate` | included | included (translated audio too) | **≈ US$ 2.20** |
| `gemini-chunked` (budget) | 0.04 + 0.05 prompts | 0.12 (same call) | **≈ US$ 0.20** |
| `local` | 0 | 0 | **US$ 0** + GPU |

## Nerdearla scenario

30 sessions in English × 45 min ≈ 22.5 room-hours.

| Engine | Event cost |
|---|---|
| `gemini-live` | ≈ US$ 16 |
| `gemini-chunked` | ≈ US$ 5 |
| `gemini-live-translate` | ≈ US$ 50 |

The US$ 25 Google Developers credit covers the whole event with the recommended engine, with room for testing. Adding a second target language adds ~US$ 0.10/hour (text translation only).

## Keeping spend under control

- Live sessions only open while audio flows and close after 30 s without audio (`idle_close_s`): breaks and rooms without ingest cost nothing.
- `translator.context_size` (previous sentences in the prompt): 6 by default; 3 cuts input tokens by ~30 %.
- `engines.gemini-live.emit_partials` has no extra cost (interim results are included).
- The panel shows `audio_minutes` per room and, under `engine_info`, tokens consumed by the `gemini-chunked` engine.
- Set a budget/alert in Google Cloud Billing or AI Studio before the event.
