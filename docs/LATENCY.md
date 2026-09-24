# Latency: what it depends on and how to tune it

🇦🇷 [Versión en español](es/LATENCIA.md)

## Where each second comes from

With the `gemini-live` engine, a translated caption travels this path:

```
speaker talks ──► [1] audio reaches the server ──► [2] the model transcribes (interim) ──► [3] the model decides the sentence ended
              ──► [4] transcriba commits the sentence ──► [5] translation (flash-lite) ──► [6] the viewer shows it
```

| Stage | Typical time | What determines it |
|---|---|---|
| [1] Capture and upload | 0.1-0.3 s | 100 ms chunks; local network. With RTMP/HLS from the stream, add the 2-10 s of the stream itself. |
| [2] Interim results | 0.3-0.8 s | The model. Shown in the viewer in italics: this is what the audience sees while the speaker talks. |
| [3] End of sentence | 0.3-1.0 s after the pause | The model's VAD (`end_sensitivity`, `silence_duration_ms`). A speaker who never pauses produces long sentences. |
| [4] Commit | 0-4 s | Finals arrive in pieces. If the piece ends with a period, transcriba waits `final_chunk_timeout_s` (1.5 s) for more; if it stopped mid-sentence, up to `final_chunk_max_wait_s` (4 s). When the server flags `finished`, it is immediate. |
| [5] Translation | 0.5-1.5 s | Text model with thinking disabled. More context (`context_size`) = slightly slower and better. |
| [6] Render | < 0.1 s | WebSocket → browser. |

In practice: **the original language appears in under a second** (interim results) and **the translation arrives 1 to 3 seconds after the speaker finishes the sentence**. Translating well before the sentence ends is not possible: Spanish word order depends on how the English sentence ends.

With the segment-based engines (`gemini-chunked`, `local`) there are no interim results: latency is the segment length (up to `max_segment_s`, 8 s) plus inference (1-3 s). That is why they feel "jumpy".

## Profiles

One setting moves every related parameter that is not written by hand in the YAML:

```yaml
latency_profile: fast | balanced | quality
```

| Profile | Behaviour | When |
|---|---|---|
| `fast` | Short sentences: the model closes after 300 ms of silence, transcriba waits less for incomplete pieces, 5 s segments, 3 sentences of context. | Q&A panels, fast speakers, screens where immediacy matters more than prose. |
| `balanced` | Default values. | Technical talks in general. |
| `quality` | Waits for complete sentences: 800 ms of silence, up to 5 s for the rest of a sentence, 10 s segments, 8 sentences of context. | Keynotes with unhurried speakers, when the text will be published afterwards. |

To try quickly from the terminal: `transcriba run pulse:default -e gemini-live -l es -t en --latency fast`.

## Fine tuning

All under `engines.gemini-live` (full reference in [CONFIGURATION.md](CONFIGURATION.md)):

- `end_sensitivity: high` closes sentences earlier; `low` tolerates breathing pauses without cutting.
- `silence_duration_ms`: silence the model takes as end of sentence (300 fast, 800 unhurried).
- `final_chunk_timeout_s` / `final_chunk_max_wait_s`: how long transcriba waits for a piece to complete. Lowering the second speeds things up but can split sentences and worsen translation.
- `emit_partials: false` if the room screen flickers too much; the audience loses the immediacy of the original.

Translation (`translator`):

- `context_size`: 3 is faster, 8 translates pronouns and references better.
- `model`: `gemini-3.5-flash-lite` is the fastest of the family; a bigger model does not speed anything up.
- `max_concurrency`: with many rooms and 429 errors, lowering it spreads the quota better (translations wait their turn).

Segment-based engines (`vad`):

- `min_silence_ms` (600): pause that closes a segment. 400 cuts more often.
- `max_segment_s` (8): duration ceiling; 5 is nimbler but translates fragments.

## How to measure it

- In the viewer, `?lang=both`: compare when the interim text appears and when the translation does.
- `transcriba run … --log-level debug` prints every Live API event with its text and the `finished` flag: you see exactly where the wait is.
- In the panel, "último hace Ns" (last caption N s ago) per room.
