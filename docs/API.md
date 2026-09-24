# API

🇦🇷 [Versión en español](es/API.md)

Base: the server URL (`http://host:8000`). Everything returns UTF-8 JSON. Admin operations require the token (`server.admin_token`) via the `X-Admin-Token: …` header, `Authorization: Bearer …` or `?token=…`.

## Data model

### Caption

```json
{
  "id": "room-a-000042",
  "session_id": "room-a",
  "seq": 42,
  "status": "translated",
  "original": "So we adopted OpenTelemetry for traces, metrics and logs.",
  "language": "en",
  "translations": { "es": "Así que adoptamos OpenTelemetry para trazas, métricas y logs." },
  "t_start": 1834.2,
  "t_end": 1838.9,
  "ts": 1790273116.42,
  "engine": "gemini-live",
  "meta": {}
}
```

| Field | Meaning |
|---|---|
| `id` | Stable for the whole life of the caption. Clients **upsert by `id`**. |
| `seq` | Order within the room (monotonically increasing). Sort by `seq`, not by arrival. |
| `status` | `partial` (hypothesis, will change) → `final` (definitive original text, translation pending) → `translated` (translations ready or `meta.translation_error`). |
| `original`, `language` | Text in the spoken language and its ISO 639-1 code (detected or configured). |
| `translations` | Map language → text. If a target matches `language`, it contains the original. |
| `t_start`, `t_end` | Seconds since the session started (stream time, used for SRT). |
| `ts` | Epoch (seconds) of the last update. |
| `meta.translation_error` | Present if any translation is missing. |

### SessionStatus

`id`, `name`, `state` (`stopped|starting|running|error`), `engine`, `source`, `source_language`, `target_languages`, `stream_time`, `level_dbfs`, `captions`, `last_caption_ts`, `last_original`, `last_translation`, `error`, `ingest_connected`, `viewers`, `audio_minutes`, `engine_info` (engine counters: `sessions`, `rotations`, `reconnects`, `idle_closes`, `last_error`, tokens…).

## REST

| Method and path | Auth | Description |
|---|---|---|
| `GET /healthz` | no | `{ok, version, sessions}` |
| `GET /api/config` | no | Title, public URL, available engines, defaults, whether auth is on. |
| `GET /api/sessions` | no | List of `SessionStatus`. |
| `GET /api/sessions/{id}` | no | Status of one room. |
| `GET /api/sessions/{id}/captions?limit=200` | no | Latest captions in memory (includes the current partial). |
| `GET /api/sessions/{id}/transcript.{srt\|vtt\|txt\|jsonl}?lang=es&download=1` | no | Persisted transcript. `lang`: `orig`, `both` or a language code. |
| `GET /api/sessions/{id}/qr.svg?lang=es` | no | QR code to the room viewer. |
| `POST /api/sessions` | yes | Create a room. Body: [SessionConfig](CONFIGURATION.md#sessionconfig) + `start` (bool, default true). 201, 409 if it exists, 502 if it failed to start. |
| `POST /api/sessions/{id}/start` | yes | Start. |
| `POST /api/sessions/{id}/stop` | yes | Stop (drains the last captions). |
| `DELETE /api/sessions/{id}` | yes | Stop and remove. |

Examples:

```bash
TOKEN=$(grep TRANSCRIBA_ADMIN_TOKEN .env | cut -d= -f2)
curl -s -X POST localhost:8000/api/sessions -H "X-Admin-Token: $TOKEN" -H 'content-type: application/json' \
  -d '{"id":"room-d","name":"Room D","source":"browser","source_language":"auto","target_languages":["es","en"]}'
curl -s localhost:8000/api/sessions | jq '.[] | {id, state, captions, last_translation}'
curl -s "localhost:8000/api/sessions/room-d/transcript.srt?lang=es" -o room-d.es.srt
```

Rooms created through the API are persisted to `data/sessions.json` and restored on restart.

## WebSockets

### `/ws/captions/{id}` — captions of one room

On connect, the server sends the history and the status:

```json
{ "type": "history", "data": [Caption, …], "status": SessionStatus }
```

Then events:

```json
{ "type": "caption", "data": Caption }
{ "type": "status",  "data": SessionStatus }
```

Minimal viewer:

```html
<div id="sub"></div>
<script>
const caps = new Map();
const ws = new WebSocket(`ws://${location.host}/ws/captions/room-a`);
ws.onmessage = (e) => {
  const m = JSON.parse(e.data);
  if (m.type === "history") m.data.forEach((c) => caps.set(c.id, c));
  if (m.type === "caption") caps.set(m.data.id, m.data);
  const last = [...caps.values()].filter((c) => c.status === "translated").sort((a, b) => a.seq - b.seq).slice(-2);
  document.getElementById("sub").textContent = last.map((c) => c.translations.es).join("\n");
};
</script>
```

### `/ws/status` — all rooms (panel)

First message `{ "type": "sessions", "data": [SessionStatus, …] }`; then `status` per room and `{ "type": "removed", "data": { "id" } }`.

### `/ws/audio/{id}` — translated audio (`gemini-live-translate` engine)

Binary frames: 16-bit little-endian PCM, mono, 24 000 Hz, no header.

### `/ws/ingest/{id}?token=…` — send audio (auth)

- Binary frames: 16-bit little-endian PCM, mono. 16 000 Hz by default; another sample rate is declared in the `hello` and the server resamples.
- Text frames (JSON): `{"type":"hello","sampleRate":16000}` → answers `{"type":"ready"}`; `{"type":"ping"}` → `{"type":"pong","received":<bytes>,"stream_time":<s>}`.
- Rejections: the server accepts the connection, sends `{"type":"error","code":44xx,"message":"…"}` and closes with that code: `4401` token, `4404` room does not exist, `4409` room is not running, `4400` the room's source is not `browser`.

Minimal Python client (send a 16 kHz mono WAV):

```python
import asyncio, json, wave, websockets

async def main():
    async with websockets.connect("ws://localhost:8000/ws/ingest/room-a?token=TOKEN") as ws:
        await ws.send(json.dumps({"type": "hello", "sampleRate": 16000}))
        with wave.open("talk.wav", "rb") as w:
            while chunk := w.readframes(1600):        # 100 ms
                await ws.send(chunk)
                await asyncio.sleep(0.1)              # real-time pace: the ASR is live
asyncio.run(main())
```

## On-disk persistence

`data/<room>/captions.jsonl` (one line per `translated` caption; when an `id` appears several times the last one wins), `data/<room>/meta.json` (session configuration and start time) and `data/sessions.json` (rooms created on the fly). All plain text: easy to back up, version and publish.
