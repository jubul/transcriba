# Costos estimados

Precios tomados de https://ai.google.dev/gemini-api/docs/pricing el 2026-09-24 (verificarlos antes del evento: cambian).
Todos los modelos usados tienen **free tier** con límites de tasa; para varias salas en paralelo conviene el tier pago.

| Modelo | Uso en transcriba | Precio |
|---|---|---|
| `gemini-3.5-transcribe-live` | ASR streaming (motor `gemini-live`) | audio in US$ 0.005/min · texto out US$ 0.004/min |
| `gemini-3.5-flash-lite` | traducción de texto (todos los motores cloud) | in US$ 0.30/1M tok · out US$ 2.50/1M tok |
| `gemini-3.5-live-translate-preview` | motor `gemini-live-translate` (voz→voz+texto) | audio in US$ 0.0053/min · audio out US$ 0.0315/min |
| `gemini-3.5-flash-lite` con audio | motor `gemini-chunked` | audio = 32 tokens/s → US$ 0.30/1M tok |
| Whisper + Gemma 4 (Ollama) | motor `local` | US$ 0 (hardware propio) |

## Costo por hora de sala (estimado)

Supuestos: orador hablando el 80 % del tiempo, ~600 frases/hora, prompt de traducción ≈ 450 tokens de entrada + 40 de salida por frase.

| Motor | ASR | Traducción | **Total / hora** |
|---|---|---|---|
| `gemini-live` (recomendado) | 0.54 | 0.14 | **≈ US$ 0.70** |
| `gemini-live-translate` | incluido | incluido (audio traducido también) | **≈ US$ 2.20** |
| `gemini-chunked` (económico) | 0.04 + 0.05 prompts | 0.12 (misma llamada) | **≈ US$ 0.20** |
| `local` | 0 | 0 | **US$ 0** + GPU |

## Escenario Nerdearla

30 sesiones en inglés × 45 min ≈ 22.5 horas de sala.

| Motor | Costo del evento |
|---|---|
| `gemini-live` | ≈ US$ 16 |
| `gemini-chunked` | ≈ US$ 5 |
| `gemini-live-translate` | ≈ US$ 50 |

Los US$ 25 de crédito de Google Developers alcanzan para todo el evento con el motor recomendado, con margen para pruebas.
Agregar un segundo idioma destino suma ~US$ 0.10/hora (solo traducción de texto).

## Cómo controlar el gasto

- Las sesiones Live se abren solo mientras llega audio y se cierran tras 30 s sin audio (`idle_close_s`): recesos y salas sin ingesta no gastan.
- `translator.context_size` (frases previas en el prompt): 6 por defecto; bajar a 3 reduce ~30 % los tokens de entrada.
- `engines.gemini-live.emit_partials` no tiene costo extra (los parciales vienen incluidos).
- El panel muestra `audio_minutes` por sesión y, en `engine_info`, tokens consumidos por el motor `gemini-chunked`.
- Poner un presupuesto/alerta en Google Cloud Billing o AI Studio antes del evento.
