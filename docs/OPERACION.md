# Guía de operación para conferencias

Pensada para que cualquier evento (5, 10 o 30 salas) despliegue transcriba en una tarde y lo opere con voluntarios. Complementa al [README](../README.md); la referencia de cada opción está en [CONFIGURACION.md](CONFIGURACION.md).

## 1. Una semana antes

### 1.1 Servidor
- Una VM chica alcanza (2 vCPU / 4 GB) para 30 salas con motores en la nube. Con motor `local`, una GPU por cada 3-5 salas.
- Dominio con TLS. Es necesario para que el navegador permita el micrófono en la ingesta desde otras máquinas (en `localhost` no hace falta) y para QR limpios. Con Caddy son dos líneas y el certificado se gestiona solo:

```
subs.miconferencia.org {
    reverse_proxy localhost:8000
}
```
Con nginx: `proxy_http_version 1.1; proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade"; proxy_read_timeout 3600;`.

### 1.2 Credenciales y cuotas
1. API key en https://aistudio.google.com/apikey (ahí aplican los créditos de Google Developers).
2. Con varias salas en paralelo, el free tier no alcanza (pocas solicitudes por minuto): activar facturación en el proyecto de AI Studio.
3. Presupuesto y alerta de gasto. Números en [COSTOS.md](COSTOS.md).

### 1.3 Instalación

```bash
git clone https://…/transcriba && cd transcriba
python3 -m venv .venv && source .venv/bin/activate
pip install -e .                    # ".[local]" para Whisper, ".[cuda]" para GPU NVIDIA

transcriba init                     # asistente: evento, API key, idiomas, salas → transcriba.yaml + .env
transcriba check --live             # dependencias, key, modelos y una conexión Live real
transcriba serve                    # imprime las URLs de audiencia, panel e ingesta
```

El `.env` (API key, token de admin, URL pública) se carga solo. Para cambiar algo después, editar `transcriba.yaml` (todas las claves en [CONFIGURACION.md](CONFIGURACION.md)) y reiniciar; las salas también se pueden agregar en caliente desde el panel.

Con Docker (`docker-compose.yml`):

- `docker compose up -d` levanta transcriba con la configuración de `./config/transcriba.yaml` y los datos en `./data`. Las variables salen del `.env` (`GEMINI_API_KEY`, `TRANSCRIBA_ADMIN_TOKEN`, `TRANSCRIBA_PUBLIC_URL`).
- `docker compose --profile rtmp up -d` agrega un servidor RTMP (`tiangolo/nginx-rtmp`, puerto 1935) al que OBS hace push; en transcriba la fuente es `rtmp://rtmp/live/<sala>`.
- `docker compose --profile local up -d` agrega Ollama (puerto 11434) para el motor `local`; después `docker compose exec ollama ollama pull gemma4:e4b`. Para usar una GPU NVIDIA dentro de Docker, agregar al servicio `ollama`: `deploy: { resources: { reservations: { devices: [{ driver: nvidia, count: all, capabilities: [gpu] }] } } }`.
- Whisper dentro del contenedor (CPU): `docker compose build --build-arg EXTRAS="[local]"` (la imagen crece ~1 GB).

Como servicio systemd:

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
(El `.env` junto al YAML se carga solo; no hace falta `EnvironmentFile`.)

### 1.4 Configuración por sala
Una entrada en `sessions:` por escenario. Decidir por sala **cómo llega el audio** (sección 2), idioma de origen (`en`, `es`, o `auto` si hay charlas mixtas), idiomas destino y glosario (nombre del evento, sponsors, speakers, tecnologías). El glosario se pasa como vocabulario al reconocedor y como términos intocables al traductor: vale la pena cargarlo.

`latency_profile` regula la sensación de velocidad: `fast` para paneles y Q&A, `quality` para keynotes pausadas ([LATENCIA.md](LATENCIA.md)).

### 1.5 Ensayo
- `transcriba serve -c config/demo.yaml` para practicar la operación sin audio ni credenciales.
- `transcriba serve -c config/mic.yaml` y hablarle al micrófono desde `/ingest/mic?token=mic`.
- Probar cada tipo de fuente real con una charla grabada del año anterior (`source: charla.mp4`).
- Medir la latencia percibida en el visor con `?lang=both`: original < 1 s, traducción 1-3 s después de cada pausa.

## 2. Cómo capturar el audio de cada sala

| Opción | Cuándo | Cómo |
|---|---|---|
| **Laptop + navegador** (`source: browser`) | Salas sin streaming, poca infra | Una laptop con la salida de la consola (o un micrófono ambiental decente) abre `https://subs…/ingest/<sala>?token=…`, elige el dispositivo y "Empezar a enviar". Reconecta sola si cae la red; la página dice exactamente qué falla (token, permisos, sesión detenida). |
| **RTMP/SRT desde el streaming** (`source: rtmp://…`) | Ya transmiten con OBS/vMix | Levantar el perfil `rtmp` del compose (o cualquier nginx-rtmp) y agregar en OBS una salida a `rtmp://<server>/live/<sala>`. transcriba lee `rtmp://rtmp/live/<sala>`. El HLS público (`https://…/playlist.m3u8`) también sirve, con 5-10 s más de latencia. |
| **Dispositivo en el servidor** (`source: pulse:…`, `alsa:hw:X`) | Servidor físico en la sala | `transcriba devices` lista las entradas. Una interfaz USB multicanal permite varias salas en una máquina. En WSL2, `pulse:default` es el micrófono de Windows. |
| **Audio del sistema** | Charlas remotas (Zoom/Meet/YouTube) | En la ingesta, marcar "capturar audio del sistema/pestaña" (Chrome). |

Recomendación: tomar el audio **post-mezcla de la consola** (el mismo que va al streaming), nunca el micrófono de la laptop.

## 3. Durante el evento

### Panel `/admin`
Cada sala muestra: estado, medidor de nivel, tiempo de audio, subtítulos emitidos, hace cuánto llegó el último, personas viendo, último original y traducción. Botones: iniciar/detener/eliminar, visor, overlay OBS, ingesta (con el token ya puesto), QR, exportar. Las salas creadas ahí quedan guardadas y vuelven si el servidor se reinicia.

Qué mirar cada tanto:
- **Nivel**: barra en cero = no llega audio (cable, dispositivo, OBS). Siempre al máximo = saturación.
- **"último hace Ns"**: si el orador habla y pasan más de 30 s sin subtítulos, abrir "detalles del motor" (`last_error`, `reconnects`).
- **`rotations`** sube cada ~9 min con `gemini-live`: es normal. **`idle_closes`** sube cuando la sala queda sin audio (recesos): también normal.

### Para la audiencia
- Página raíz `/`: cada persona elige sala e idioma. Publicar el QR de cada sala (`/api/sessions/<sala>/qr.svg?lang=es`) en pantalla y carteles.
- Pantalla o streaming: en OBS, fuente "Navegador" con `…/view/<sala>?lang=es&overlay=1&lines=2&size=1.4`, 1920×1080, fondo transparente.
- Accesibilidad: `?history=1` muestra la transcripción completa con marcas de tiempo; `?theme=light` para ambientes muy iluminados.

### Problemas típicos
| Síntoma | Causa probable | Acción |
|---|---|---|
| Sala en `error` al iniciar | key inválida, modelo no disponible, ffmpeg no encuentra la fuente | Mensaje en el panel; `transcriba check`; probar la fuente con `ffplay <source>` |
| Ingesta "desconectado: token…" | token distinto al del servidor | Copiarlo del `.env` o abrir la ingesta desde el botón del panel |
| Ingesta "sin micrófono" | permiso denegado o página sin HTTPS | Candado del navegador → permitir micrófono; usar HTTPS o `localhost` |
| Original llega, traducción no | cuota del traductor o key sin facturación | `translation_errors` en detalles del motor; bajar `translator.max_concurrency`; activar facturación |
| `last_error: 1008 … aborted` repetido con audio fluyendo | el Live API cortó la sesión | Se reconecta solo; si es constante, revisar red saliente/proxy |
| Subtítulos "a saltos" de 8 s | motor por segmentos (`chunked`/`local`) | Esperado; `latency_profile: fast` o pasar a `gemini-live` |
| Frases cortadas a la mitad | orador sin pausas + perfil `fast` | `latency_profile: balanced` o `quality` |
| Traduce a "vosotros" | falta `language_notes.es` | Viene por defecto; revisar que no se haya borrado |
| Nombres propios mal | glosario incompleto | Agregar términos y reiniciar la sala (no el servidor) |
| Ingesta se desconecta seguido | wifi de la sala | La página reconecta sola; usar cable si se puede |

Reiniciar una sala no afecta a las otras. Las transcripciones persistidas nunca se borran al reiniciar (se agregan al mismo JSONL).

## 4. Después del evento

```bash
transcriba export sala-a -f srt -l es -o sala-a.es.srt      # subtítulos para el video
transcriba export sala-a -f txt -l orig -o sala-a.en.txt    # transcripción para publicar
transcriba export sala-a -f vtt -l both -o sala-a.vtt
```
o desde el panel (botones SRT/TXT) o `GET /api/sessions/<sala>/transcript.{srt|vtt|txt|jsonl}?lang=…`.

Los tiempos son relativos al inicio de la sesión: si la sesión arrancó antes que la grabación, desplazar con cualquier editor de subtítulos (`ffmpeg -itsoffset` también sirve).

## 5. Checklist del día

- [ ] `transcriba check --live` OK con la key del evento
- [ ] Token de admin en el `.env`, no en pantallas ni chats públicos
- [ ] Una sala por escenario, con glosario y `latency_profile` elegido
- [ ] Audio verificado en cada sala (barra de nivel moviéndose, subtítulos apareciendo)
- [ ] QR/URL de `/` publicados en pantallas y programa
- [ ] Overlay probado en OBS
- [ ] Una persona de guardia mirando `/admin` (alcanza para todas las salas)
- [ ] Presupuesto/alerta de gasto activo
