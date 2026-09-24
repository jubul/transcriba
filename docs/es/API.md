# API

🇬🇧 [English version](../API.md)

Base: la URL del servidor (`http://host:8000`). Todo devuelve JSON UTF-8. Las operaciones de administración requieren el token (`server.admin_token`) por header `X-Admin-Token: …`, `Authorization: Bearer …` o `?token=…`.

## Modelo de datos

### Caption (subtítulo)

```json
{
  "id": "sala-a-000042",
  "session_id": "sala-a",
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

| Campo | Significado |
|---|---|
| `id` | Estable durante toda la vida del subtítulo. Los clientes **hacen upsert por `id`**. |
| `seq` | Orden dentro de la sala (monótono creciente). Ordenar por `seq`, no por llegada. |
| `status` | `partial` (hipótesis, va a cambiar) → `final` (texto original definitivo, traducción pendiente) → `translated` (traducciones listas o `meta.translation_error`). |
| `original`, `language` | Texto en el idioma hablado y su código ISO 639-1 (detectado o configurado). |
| `translations` | Mapa idioma → texto. Si un destino coincide con `language`, contiene el original. |
| `t_start`, `t_end` | Segundos desde el inicio de la sesión (tiempo de stream, sirve para SRT). |
| `ts` | Epoch (segundos) de la última actualización. |
| `meta.translation_error` | Presente si faltó alguna traducción. |

### SessionStatus (estado de sala)

`id`, `name`, `state` (`stopped|starting|running|error`), `engine`, `source`, `source_language`, `target_languages`, `stream_time`, `level_dbfs`, `captions`, `last_caption_ts`, `last_original`, `last_translation`, `error`, `ingest_connected`, `viewers`, `audio_minutes`, `engine_info` (contadores del motor: `sessions`, `rotations`, `reconnects`, `idle_closes`, `last_error`, tokens…).

## REST

| Método y ruta | Auth | Descripción |
|---|---|---|
| `GET /healthz` | no | `{ok, version, sessions}` |
| `GET /api/config` | no | Título, URL pública, motores disponibles, defaults, si hay auth. |
| `GET /api/sessions` | no | Lista de `SessionStatus`. |
| `GET /api/sessions/{id}` | no | Estado de una sala. |
| `GET /api/sessions/{id}/captions?limit=200` | no | Últimos subtítulos en memoria (incluye el parcial en curso). |
| `GET /api/sessions/{id}/transcript.{srt\|vtt\|txt\|jsonl}?lang=es&download=1` | no | Transcripción persistida. `lang`: `orig`, `both` o un código. |
| `GET /api/sessions/{id}/qr.svg?lang=es` | no | QR al visor de la sala. |
| `POST /api/sessions` | sí | Crear sala. Cuerpo: [SessionConfig](CONFIGURACION.md#sessionconfig) + `start` (bool, default true). 201, 409 si existe, 502 si no pudo arrancar. |
| `POST /api/sessions/{id}/start` | sí | Iniciar. |
| `POST /api/sessions/{id}/stop` | sí | Detener (drena los últimos subtítulos). |
| `DELETE /api/sessions/{id}` | sí | Detener y eliminar. |

Ejemplos:

```bash
TOKEN=$(grep TRANSCRIBA_ADMIN_TOKEN .env | cut -d= -f2)
curl -s -X POST localhost:8000/api/sessions -H "X-Admin-Token: $TOKEN" -H 'content-type: application/json' \
  -d '{"id":"sala-d","name":"Sala D","source":"browser","source_language":"auto","target_languages":["es","en"]}'
curl -s localhost:8000/api/sessions | jq '.[] | {id, state, captions, last_translation}'
curl -s "localhost:8000/api/sessions/sala-d/transcript.srt?lang=es" -o sala-d.es.srt
```

Las salas creadas por API se persisten en `data/sessions.json` y se restauran al reiniciar.

## WebSockets

### `/ws/captions/{id}` — subtítulos de una sala

Al conectar, el servidor manda el historial y el estado:

```json
{ "type": "history", "data": [Caption, …], "status": SessionStatus }
```

Luego, eventos:

```json
{ "type": "caption", "data": Caption }
{ "type": "status",  "data": SessionStatus }
```

Visor mínimo:

```html
<div id="sub"></div>
<script>
const caps = new Map();
const ws = new WebSocket(`ws://${location.host}/ws/captions/sala-a`);
ws.onmessage = (e) => {
  const m = JSON.parse(e.data);
  if (m.type === "history") m.data.forEach((c) => caps.set(c.id, c));
  if (m.type === "caption") caps.set(m.data.id, m.data);
  const last = [...caps.values()].filter((c) => c.status === "translated").sort((a, b) => a.seq - b.seq).slice(-2);
  document.getElementById("sub").textContent = last.map((c) => c.translations.es).join("\n");
};
</script>
```

### `/ws/status` — todas las salas (panel)

Primer mensaje `{ "type": "sessions", "data": [SessionStatus, …] }`; luego `status` por sala y `{ "type": "removed", "data": { "id" } }`.

### `/ws/audio/{id}` — audio traducido (motor `gemini-live-translate`)

Frames binarios: PCM 16 bit little-endian, mono, 24 000 Hz, sin cabecera.

### `/ws/ingest/{id}?token=…` — enviar audio (auth)

- Frames binarios: PCM 16 bit little-endian, mono. 16 000 Hz por defecto; otro sample rate se declara en el `hello` y el servidor remuestrea.
- Frames de texto (JSON): `{"type":"hello","sampleRate":16000}` → responde `{"type":"ready"}`; `{"type":"ping"}` → `{"type":"pong","received":<bytes>,"stream_time":<s>}`.
- Rechazos: el servidor acepta la conexión, manda `{"type":"error","code":44xx,"message":"…"}` y cierra con ese código: `4401` token, `4404` sala inexistente, `4409` sala no está corriendo, `4400` la fuente de la sala no es `browser`.

Cliente mínimo en Python (enviar un WAV de 16 kHz mono):

```python
import asyncio, json, wave, websockets

async def main():
    async with websockets.connect("ws://localhost:8000/ws/ingest/sala-a?token=TOKEN") as ws:
        await ws.send(json.dumps({"type": "hello", "sampleRate": 16000}))
        with wave.open("charla.wav", "rb") as w:
            while chunk := w.readframes(1600):        # 100 ms
                await ws.send(chunk)
                await asyncio.sleep(0.1)              # ritmo real: el ASR es en vivo
asyncio.run(main())
```

## Persistencia en disco

`data/<sala>/captions.jsonl` (una línea por subtítulo `translated`; si un `id` aparece varias veces vale la última), `data/<sala>/meta.json` (configuración e inicio de la sesión) y `data/sessions.json` (salas creadas en caliente). Todo es texto plano: fácil de respaldar, versionar y publicar.
