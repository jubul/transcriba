# Latencia: de qué depende y cómo ajustarla

## De dónde sale cada segundo

Con el motor `gemini-live`, un subtítulo traducido recorre este camino:

```
orador habla ──► [1] audio llega al servidor ──► [2] el modelo transcribe (parciales) ──► [3] el modelo decide que la frase terminó
             ──► [4] transcriba confirma la frase ──► [5] traducción (flash-lite) ──► [6] el visor la muestra
```

| Etapa | Tiempo típico | Qué lo determina |
|---|---|---|
| [1] Captura y envío | 0.1-0.3 s | Chunks de 100 ms; red local. Con RTMP/HLS desde el streaming se suman 2-10 s del propio streaming. |
| [2] Parciales | 0.3-0.8 s | El modelo. Se muestran en el visor en itálica: es lo que ve la audiencia mientras el orador habla. |
| [3] Fin de frase | 0.3-1.0 s después de la pausa | El VAD del modelo (`end_sensitivity`, `silence_duration_ms`). Un orador que no hace pausas produce frases largas. |
| [4] Confirmación | 0-4 s | Los finales llegan en trozos. Si el trozo termina en punto, transcriba espera `final_chunk_timeout_s` (1.5 s) por más; si quedó a mitad de oración, hasta `final_chunk_max_wait_s` (4 s). Si el servidor marca `finished`, es inmediato. |
| [5] Traducción | 0.5-1.5 s | Modelo de texto con razonamiento desactivado. Más contexto (`context_size`) = algo más lento y mejor. |
| [6] Render | < 0.1 s | WebSocket → navegador. |

En la práctica: **el idioma original aparece en menos de un segundo** (parciales) y **la traducción llega entre 1 y 3 segundos después de que el orador termina la frase**. No es posible traducir bien antes de que la frase termine: el orden de las palabras en español depende del final de la oración en inglés.

Con los motores por segmentos (`gemini-chunked`, `local`) no hay parciales: la latencia es la duración del segmento (hasta `max_segment_s`, 8 s) más la inferencia (1-3 s). Por eso se sienten "a saltos".

## Perfiles

Un solo ajuste mueve todos los parámetros relacionados que no estén escritos a mano en el YAML:

```yaml
latency_profile: fast | balanced | quality
```

| Perfil | Comportamiento | Cuándo |
|---|---|---|
| `fast` | Frases cortas: el modelo cierra al detectar 300 ms de silencio, transcriba espera menos por trozos incompletos, segmentos de 5 s, 3 frases de contexto. | Paneles de preguntas y respuestas, oradores rápidos, pantallas donde importa más la inmediatez que la prosa. |
| `balanced` | Valores por defecto. | Charlas técnicas en general. |
| `quality` | Espera frases completas: 800 ms de silencio, hasta 5 s por el resto de una oración, segmentos de 10 s, 8 frases de contexto. | Keynotes con oradores pausados, cuando el texto se va a publicar después. |

Para probar rápido desde la terminal: `transcriba run pulse:default -e gemini-live -l es -t en --latency fast`.

## Ajuste fino

Todos en `engines.gemini-live` (referencia completa en [CONFIGURACION.md](CONFIGURACION.md)):

- `end_sensitivity: high` cierra frases antes; `low` tolera pausas para respirar sin cortar.
- `silence_duration_ms`: silencio que el modelo toma como fin de frase (300 rápido, 800 pausado).
- `final_chunk_timeout_s` / `final_chunk_max_wait_s`: cuánto espera transcriba a que un trozo se complete. Bajar el segundo acelera pero puede partir oraciones y empeorar la traducción.
- `emit_partials: false` si el visor de la sala parpadea demasiado; la audiencia pierde la inmediatez del original.

Traducción (`translator`):

- `context_size`: 3 es más rápido, 8 traduce mejor pronombres y referencias.
- `model`: `gemini-3.5-flash-lite` es el más rápido de la familia; un modelo más grande no acelera nada.
- `max_concurrency`: si hay muchas salas y aparecen errores 429, bajarlo reparte mejor la cuota (las traducciones esperan su turno).

Motores por segmentos (`vad`):

- `min_silence_ms` (600): pausa que cierra un segmento. 400 corta más seguido.
- `max_segment_s` (8): techo de duración; 5 es más ágil pero traduce fragmentos.

## Cómo medirla

- En el visor, `?lang=both`: compará cuándo aparece el parcial y cuándo la traducción.
- `transcriba run … --log-level debug` imprime cada evento del Live API con su texto y el flag `finished`: se ve exactamente dónde se está esperando.
- En el panel, "último hace Ns" por sala.
