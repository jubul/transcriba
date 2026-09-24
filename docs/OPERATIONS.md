# Operations guide for conferences

🇦🇷 [Versión en español](es/OPERACION.md)

Written so that any event (5, 10 or 30 rooms) can deploy transcriba in an afternoon and run it with volunteers. It complements the [README](../README.md); every option is described in [CONFIGURATION.md](CONFIGURATION.md).

## 1. One week before

### 1.1 Server
- A small VM is enough (2 vCPU / 4 GB) for 30 rooms with cloud engines. With the `local` engine, one GPU per 3-5 rooms.
- A domain with TLS. Browsers only allow the microphone on the ingest page over HTTPS when it is opened from another machine (`localhost` is exempt), and QR codes look cleaner. With Caddy it is two lines and the certificate is handled for you:

```
subs.myconference.org {
    reverse_proxy localhost:8000
}
```
With nginx: `proxy_http_version 1.1; proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade"; proxy_read_timeout 3600;`.

### 1.2 Credentials and quotas
1. API key at https://aistudio.google.com/apikey (Google Developers credits apply there).
2. With several rooms in parallel the free tier is not enough (few requests per minute): enable billing on the AI Studio project.
3. Budget and spend alert. Numbers in [COSTS.md](COSTS.md).

### 1.3 Installation

```bash
git clone https://github.com/jubul/transcriba && cd transcriba
python3 -m venv .venv && source .venv/bin/activate
pip install -e .                    # ".[local]" for Whisper, ".[cuda]" for NVIDIA GPUs

transcriba init                     # wizard: event, API key, languages, rooms → transcriba.yaml + .env
transcriba check --live             # dependencies, key, models and one real Live connection
transcriba serve                    # prints audience, panel and ingest URLs
```

The `.env` (API key, admin token, public URL) is loaded automatically. To change something later, edit `transcriba.yaml` (all keys in [CONFIGURATION.md](CONFIGURATION.md)) and restart; rooms can also be added live from the panel.

With Docker (`docker-compose.yml`):

- `docker compose up -d` starts transcriba with the configuration in `./config/transcriba.yaml` and data in `./data`. Variables come from `.env` (`GEMINI_API_KEY`, `TRANSCRIBA_ADMIN_TOKEN`, `TRANSCRIBA_PUBLIC_URL`).
- `docker compose --profile rtmp up -d` adds an RTMP server (`tiangolo/nginx-rtmp`, port 1935) that OBS pushes to; in transcriba the source is `rtmp://rtmp/live/<room>`.
- `docker compose --profile local up -d` adds Ollama (port 11434) for the `local` engine; then `docker compose exec ollama ollama pull gemma4:e4b`. To use an NVIDIA GPU inside Docker, add to the `ollama` service: `deploy: { resources: { reservations: { devices: [{ driver: nvidia, count: all, capabilities: [gpu] }] } } }`.
- Whisper inside the container (CPU): `docker compose build --build-arg EXTRAS="[local]"` (the image grows by ~1 GB).

As a systemd service:

```ini
[Unit]
Description=transcriba
After=network-online.target
[Service]
User=transcriba
WorkingDirectory=/opt/transcriba
ExecStart=/opt/transcriba/.venv/bin/transcriba serve -c transcriba.yaml
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
```
(The `.env` next to the YAML is loaded automatically; no `EnvironmentFile` needed.)

### 1.4 Per-room configuration
One entry under `sessions:` per stage. Decide per room **how the audio gets in** (section 2), source language (`en`, `es`, or `auto` for mixed talks), target languages and glossary (event name, sponsors, speakers, technologies). The glossary is passed as vocabulary to the recognizer and as untouchable terms to the translator: it is worth filling in.

`latency_profile` sets the feel of speed: `fast` for panels and Q&A, `quality` for unhurried keynotes ([LATENCY.md](LATENCY.md)).

### 1.5 Rehearsal
- `transcriba serve -c config/demo.yaml` to practice operations without audio or credentials.
- `transcriba serve -c config/mic.yaml` and talk to the microphone from `/ingest/mic?token=mic`.
- Try every real source type with a recorded talk from last year (`source: talk.mp4`).
- Measure perceived latency in the viewer with `?lang=both`: original < 1 s, translation 1-3 s after each pause.

## 2. Capturing the audio of each room

| Option | When | How |
|---|---|---|
| **Laptop + browser** (`source: browser`) | Rooms without streaming, little infrastructure | A laptop with the mixer output (or a decent ambient microphone) opens `https://subs…/ingest/<room>?token=…`, picks the device and presses start. It reconnects by itself if the network drops; the page says exactly what fails (token, permissions, stopped room). |
| **RTMP/SRT from the stream** (`source: rtmp://…`) | You already stream with OBS/vMix | Start the `rtmp` profile of the compose file (or any nginx-rtmp) and add an OBS output to `rtmp://<server>/live/<room>`. transcriba reads `rtmp://rtmp/live/<room>`. The public HLS (`https://…/playlist.m3u8`) also works, with 5-10 s more latency. |
| **Device on the server** (`source: pulse:…`, `alsa:hw:X`) | Physical server in the room | `transcriba devices` lists the inputs. A multichannel USB interface allows several rooms on one machine. On WSL2, `pulse:default` is the Windows microphone. |
| **System audio** | Remote talks (Zoom/Meet/YouTube) | On the ingest page, tick "capture system/tab audio" (Chrome). |

Recommendation: take the **post-mix audio from the console** (the same one that goes to the stream), never the laptop's microphone.

## 3. During the event

### Panel `/admin`
Each room shows: state, level meter, audio time, captions emitted, how long since the last one, people watching, latest original and translation. Buttons: start/stop/delete, viewer, OBS overlay, ingest (with the token filled in), QR, export. Rooms created here are saved and come back if the server restarts.

What to watch every so often:
- **Level**: bar at zero = no audio arriving (cable, device, OBS). Always at maximum = clipping.
- **"último hace Ns"** (last caption N s ago): if the speaker is talking and more than 30 s pass without captions, open "detalles del motor" (`last_error`, `reconnects`).
- **`rotations`** grows every ~9 min with `gemini-live`: normal. **`idle_closes`** grows when the room goes silent (breaks): also normal.

### For the audience
- Home page `/`: everyone picks room and language. Publish each room's QR (`/api/sessions/<room>/qr.svg?lang=es`) on screens and signs.
- Screen or stream: in OBS, a "Browser" source with `…/view/<room>?lang=es&overlay=1&lines=2&size=1.4`, 1920×1080, transparent background.
- Accessibility: `?history=1` shows the full transcript with timestamps; `?theme=light` for very bright rooms.

### Typical problems
| Symptom | Likely cause | Action |
|---|---|---|
| Room in `error` at start | invalid key, model unavailable, ffmpeg cannot find the source | Message in the panel; `transcriba check`; test the source with `ffplay <source>` |
| Ingest "desconectado: token…" | token differs from the server's | Copy it from `.env` or open the ingest from the panel button |
| Ingest "sin micrófono" | permission denied or page without HTTPS | Browser padlock → allow microphone; use HTTPS or `localhost` |
| Original arrives, translation does not | translator quota or key without billing | `translation_errors` in engine details; lower `translator.max_concurrency`; enable billing |
| Repeated `last_error: 1008 … aborted` while audio flows | the Live API cut the session | It reconnects by itself; if constant, check outbound network/proxy |
| Captions "jump" every 8 s | segment-based engine (`chunked`/`local`) | Expected; `latency_profile: fast` or switch to `gemini-live` |
| Sentences cut in half | speaker without pauses + `fast` profile | `latency_profile: balanced` or `quality` |
| Translates with "vosotros" | `language_notes.es` missing | Comes by default; check it was not deleted |
| Proper names wrong | incomplete glossary | Add terms and restart the room (not the server) |
| Ingest disconnects often | room wifi | The page reconnects by itself; use a cable if possible |

Restarting a room does not affect the others. Persisted transcripts are never deleted on restart (they are appended to the same JSONL).

## 4. After the event

```bash
transcriba export room-a -f srt -l es -o room-a.es.srt      # subtitles for the video
transcriba export room-a -f txt -l orig -o room-a.en.txt    # transcript to publish
transcriba export room-a -f vtt -l both -o room-a.vtt
```
or from the panel (SRT/TXT buttons) or `GET /api/sessions/<room>/transcript.{srt|vtt|txt|jsonl}?lang=…`.

Timestamps are relative to the session start: if the session started before the recording, shift them with any subtitle editor (`ffmpeg -itsoffset` works too).

## 5. Day-of checklist

- [ ] `transcriba check --live` OK with the event key
- [ ] Admin token in `.env`, not on screens or public chats
- [ ] One room per stage, with glossary and chosen `latency_profile`
- [ ] Audio verified in every room (level bar moving, captions appearing)
- [ ] QR/URL of `/` published on screens and programme
- [ ] Overlay tested in OBS
- [ ] One person on duty watching `/admin` (enough for all rooms)
- [ ] Budget/spend alert active
