from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import re
import secrets
import shutil
import socket
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Optional

import typer

from transcriba import __version__
from transcriba.config import ENGINE_NAMES, AppConfig, SessionConfig, apply_latency_profile, load_config

app = typer.Typer(help="transcriba: subtítulos en vivo (transcripción + traducción) para conferencias.", invoke_without_command=True)


def _setup_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("websockets", "httpx", "httpcore", "google_genai", "asyncio", "faster_whisper", "huggingface_hub", "urllib3", "filelock"):
        logging.getLogger(noisy).setLevel(logging.WARNING if level.lower() != "debug" else logging.INFO)


def load_env_file(path: Path) -> int:
    n = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:]
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
            n += 1
    return n


def _load(config: Optional[Path]) -> AppConfig:
    if config is None:
        for candidate in ("transcriba.yaml", "config/transcriba.yaml"):
            if Path(candidate).exists():
                config = Path(candidate)
                break
    for env_path in [Path(os.environ.get("TRANSCRIBA_ENV_FILE", "")), Path(".env"), (config.parent / ".env") if config else None]:
        if env_path and str(env_path) not in ("", ".") and env_path.is_file():
            load_env_file(env_path)
            break
    return load_config(config)


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text[:64] or "sala"


def lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


@app.callback()
def _main(ctx: typer.Context, version: bool = typer.Option(False, "--version", help="Mostrar versión", is_eager=True)) -> None:
    if version:
        typer.echo(f"transcriba {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


@app.command()
def serve(
    config: Optional[Path] = typer.Option(None, "-c", "--config", help="YAML de configuración (default: transcriba.yaml si existe)"),
    host: Optional[str] = typer.Option(None, help="Override server.host"),
    port: Optional[int] = typer.Option(None, help="Override server.port"),
    ssl_certfile: Optional[Path] = typer.Option(None, help="Certificado TLS (necesario para micrófono desde navegador remoto)"),
    ssl_keyfile: Optional[Path] = typer.Option(None, help="Clave TLS"),
    log_level: str = typer.Option("info"),
) -> None:
    import uvicorn

    from transcriba.server import create_app

    _setup_logging(log_level)
    cfg = _load(config)
    if host:
        cfg.server.host = host
    if port:
        cfg.server.port = port
    scheme = "https" if ssl_certfile else "http"
    shown_host = lan_ip() if cfg.server.host in ("0.0.0.0", "") else cfg.server.host
    base = cfg.server.public_url.rstrip("/") or f"{scheme}://{shown_host}:{cfg.server.port}"
    typer.echo(f"transcriba {__version__} · perfil de latencia: {cfg.latency_profile} · {len(cfg.sessions)} sala(s) en la configuración")
    typer.echo(f"  Audiencia (elegir sala e idioma): {base}/")
    typer.echo(f"  Panel de operación:               {base}/admin")
    for sess in cfg.sessions:
        if sess.source in ("browser", "push", "ws"):
            typer.echo(
                f"  Ingesta de audio · {sess.id:<14} {base}/ingest/{sess.id}   (abrir en la laptop de la sala; pide el token de admin)"
            )
    if not cfg.server.admin_token:
        typer.echo("  ! sin admin_token: cualquiera en la red puede administrar. Configurarlo antes del evento.")
    if shown_host != "127.0.0.1" and not cfg.server.public_url:
        typer.echo(f"  (desde esta misma máquina también: http://localhost:{cfg.server.port}/)")
    uvicorn.run(
        create_app(cfg),
        host=cfg.server.host,
        port=cfg.server.port,
        log_level=log_level,
        ssl_certfile=str(ssl_certfile) if ssl_certfile else None,
        ssl_keyfile=str(ssl_keyfile) if ssl_keyfile else None,
        ws_ping_interval=20,
        ws_ping_timeout=20,
    )


@app.command()
def run(
    source: str = typer.Argument(..., help="Archivo, URL rtmp://…, pulse:default, alsa:hw:0, ffmpeg:<args>"),
    engine: str = typer.Option("gemini-live", "-e", "--engine", help=f"Motor: {', '.join(ENGINE_NAMES)}"),
    lang: Optional[str] = typer.Option("en", "-l", "--lang", help="Idioma de origen ('auto' para detectar)"),
    to: str = typer.Option("es", "-t", "--to", help="Idiomas destino separados por coma"),
    config: Optional[Path] = typer.Option(None, "-c", "--config"),
    glossary: str = typer.Option("", "-g", "--glossary", help="Términos separados por coma"),
    loop: bool = typer.Option(False, help="Repetir archivo en loop"),
    no_realtime: bool = typer.Option(False, help="Procesar archivos más rápido que tiempo real (solo motores por segmentos)"),
    latency: Optional[str] = typer.Option(None, help="Perfil de latencia: fast | balanced | quality (pisa lo del YAML)"),
    log_level: str = typer.Option("info", help="debug muestra los eventos crudos del Live API"),
) -> None:
    from transcriba.hub import Hub
    from transcriba.models import CaptionStatus
    from transcriba.pipeline import SessionRunner
    from transcriba.store import CaptionStore

    _setup_logging(log_level)
    cfg = _load(config)
    if latency:
        cfg.latency_profile = latency
        apply_latency_profile(cfg, force=True)
    targets = [t.strip() for t in to.split(",") if t.strip()]
    scfg = SessionConfig(
        id="cli",
        name="cli",
        source=source,
        engine=engine,
        source_language=None if lang in (None, "auto") else lang,
        target_languages=targets,
        glossary=[g.strip() for g in glossary.split(",") if g.strip()],
        loop=loop,
    )
    hub = Hub()
    store = CaptionStore(cfg.server.data_dir)

    async def main() -> None:
        runner = SessionRunner(scfg, cfg, hub, store)
        if no_realtime:
            from transcriba.audio.source import make_source

            runner_make = make_source

            def fast_source(spec, extra, loop=False, realtime=True):
                return runner_make(spec, extra, loop=loop, realtime=False)

            import transcriba.pipeline as pl

            pl.make_source = fast_source
        q = hub.subscribe("cli")
        await runner.start()
        typer.echo(f"▶ motor={engine} origen={source} {lang or 'auto'} → {','.join(targets)}   (Ctrl+C para salir)")
        last_partial = ""
        try:
            while True:
                try:
                    raw = await asyncio.wait_for(q.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    if runner._task is not None and runner._task.done() and q.empty():
                        break
                    continue
                msg = json.loads(raw)
                if msg["type"] != "caption":
                    if msg["type"] == "status" and msg["data"].get("state") == "error":
                        typer.echo(f"\n✖ {msg['data'].get('error')}")
                    continue
                c = msg["data"]
                if c["status"] == CaptionStatus.partial.value:
                    line = f"… {c['original']}"
                    sys.stdout.write("\r" + line[-150:].ljust(len(last_partial)))
                    sys.stdout.flush()
                    last_partial = line
                elif c["status"] == CaptionStatus.final.value:
                    sys.stdout.write("\r" + " " * len(last_partial) + "\r")
                    last_partial = ""
                    typer.echo(f"[{c['t_start']:7.1f}s] ({c.get('language') or '?'}) {c['original']}")
                else:
                    for k, v in c["translations"].items():
                        if k != c.get("language"):
                            typer.echo(f"            → {k}: {v}")
                    if c.get("meta", {}).get("translation_error"):
                        typer.echo(f"            ! {c['meta']['translation_error']}")
        except (KeyboardInterrupt, asyncio.CancelledError):
            typer.echo("\n⏹ deteniendo (drenando últimos subtítulos)…")
        finally:
            await runner.stop()
            while not q.empty():
                msg = json.loads(q.get_nowait())
                if msg["type"] == "caption" and msg["data"]["status"] != CaptionStatus.partial.value:
                    c = msg["data"]
                    if c["status"] == CaptionStatus.final.value:
                        typer.echo(f"[{c['t_start']:7.1f}s] ({c.get('language') or '?'}) {c['original']}")
                    else:
                        for k, v in c["translations"].items():
                            if k != c.get("language"):
                                typer.echo(f"            → {k}: {v}")
            st = runner.status()
            info = st.engine_info
            typer.echo(
                f"■ fin: {st.captions} subtítulos, {st.audio_minutes} min de audio, estado={st.state.value}"
                + (f", error={st.error}" if st.error else "")
            )
            extras = {
                k: info[k] for k in ("sessions", "rotations", "reconnects", "translation_errors", "asr_errors", "last_error") if info.get(k)
            }
            if extras:
                typer.echo(f"  motor: {extras}")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


YAML_TEMPLATE = """# transcriba — generado por `transcriba init` el {date}
# Referencia completa de opciones: docs/CONFIGURACION.md
# Las variables ${{VAR}} se leen del entorno o del archivo .env que está al lado.

latency_profile: {latency}          # fast | balanced | quality  (ver docs/LATENCIA.md)

server:
  title: "{title}"
  host: 0.0.0.0
  port: {port}
  admin_token: ${{TRANSCRIBA_ADMIN_TOKEN}}   # panel e ingesta; está en .env
  public_url: ${{TRANSCRIBA_PUBLIC_URL:-}}   # ej. https://subs.mievento.org (para los QR); vacío = la URL con la que entran
  data_dir: data

gemini:
  api_key: ${{GEMINI_API_KEY}}

translator:
  provider: {translator_provider}
  model: {translator_model}

defaults:
  engine: {engine}
  source_language: {source_language}   # 'auto' detecta inglés/español por frase
  target_languages: [{targets}]
  glossary: [{glossary}]

sessions:
{sessions}"""

SESSION_TEMPLATE = """  - id: {id}
    name: "{name}"
    source: {source}{extra}
"""


@app.command()
def init(
    out: Path = typer.Option(Path("transcriba.yaml"), "-o", "--out", help="Archivo YAML a generar"),
    title: Optional[str] = typer.Option(None, help="Nombre del evento"),
    rooms: Optional[int] = typer.Option(None, help="Cantidad de salas"),
    lang: Optional[str] = typer.Option(None, help="Idioma de origen por defecto (en, es, auto)"),
    to: Optional[str] = typer.Option(None, help="Idiomas destino separados por coma"),
    engine: str = typer.Option("gemini-live", help=f"Motor: {', '.join(ENGINE_NAMES)}"),
    latency: str = typer.Option("balanced", help="fast | balanced | quality"),
    port: int = typer.Option(8000),
    api_key: Optional[str] = typer.Option(None, help="API key de Gemini (si no, se pregunta o se toma de GEMINI_API_KEY)"),
    yes: bool = typer.Option(False, "-y", "--yes", help="No preguntar: usar flags y valores por defecto"),
    no_verify: bool = typer.Option(False, help="No verificar la API key contra Gemini"),
    force: bool = typer.Option(False, help="Sobrescribir archivos existentes"),
) -> None:
    import datetime

    ask = not yes
    env_path = out.parent / ".env"
    if (out.exists() or env_path.exists()) and not force:
        if not ask or not typer.confirm(f"{out} o {env_path} ya existen. ¿Sobrescribir?", default=False):
            typer.echo("cancelado (usar --force para sobrescribir)")
            raise typer.Exit(1)

    typer.echo("transcriba · asistente de configuración\n")
    title = title or (typer.prompt("Nombre del evento", default="Mi conferencia") if ask else "Mi conferencia")
    engine = engine if (yes or engine != "gemini-live") else typer.prompt("Motor", default=engine)
    if engine not in ENGINE_NAMES:
        typer.echo(f"motor desconocido: {engine}", err=True)
        raise typer.Exit(1)
    needs_gemini = engine.startswith("gemini")
    translator_provider = "gemini" if engine != "local" else "ollama"
    translator_model = "gemini-3.5-flash-lite" if translator_provider == "gemini" else "gemma4:e4b"
    if engine == "mock":
        translator_provider, translator_model = "mock", "mock"
    if engine == "local" and ask:
        translator_model = typer.prompt("Modelo de Ollama para traducir", default=translator_model)

    key = api_key or os.environ.get("GEMINI_API_KEY", "")
    if needs_gemini or translator_provider == "gemini":
        if key and ask and not typer.confirm("Hay una GEMINI_API_KEY en el entorno. ¿Usarla?", default=True):
            key = ""
        if not key and ask:
            key = typer.prompt("API key de Gemini (https://aistudio.google.com/apikey)", hide_input=True, default="", show_default=False)
        if key and not no_verify:
            try:
                from google import genai

                genai.Client(api_key=key).models.get(model=translator_model if translator_provider == "gemini" else "gemini-3.5-flash-lite")
                typer.echo("  ✔ API key verificada")
            except Exception as e:
                typer.echo(f"  ✖ la API key no funciona: {str(e)[:120]}", err=True)
                if ask and not typer.confirm("¿Continuar de todos modos?", default=False):
                    raise typer.Exit(1)
        if not key:
            typer.echo("  ! sin API key: completar GEMINI_API_KEY en .env antes de arrancar")

    lang = lang or (typer.prompt("Idioma de origen por defecto (en, es, auto)", default="en") if ask else "en")
    to = to or (typer.prompt("Idiomas destino (coma)", default="es" if lang != "es" else "en") if ask else ("es" if lang != "es" else "en"))
    targets = [t.strip() for t in to.split(",") if t.strip()]
    glossary = (
        typer.prompt("Glosario: nombres/tecnologías que no se traducen (coma, opcional)", default="", show_default=False) if ask else ""
    )
    glossary_items = [g.strip() for g in glossary.split(",") if g.strip()]

    n = rooms or (typer.prompt("¿Cuántas salas en simultáneo?", default=3, type=int) if ask else 3)
    same_source = True
    if ask:
        same_source = typer.confirm(
            "¿Todas las salas reciben el audio desde el navegador (/ingest)? (No = elegir fuente por sala)", default=True
        )
    sessions = []
    for i in range(n):
        default_name = f"Sala {chr(ord('A') + i)}" if i < 26 else f"Sala {i + 1}"
        name = typer.prompt(f"Nombre de la sala {i + 1}", default=default_name) if ask else default_name
        source = "browser"
        if ask and not same_source:
            source = typer.prompt(f"  fuente de audio para «{name}» (browser | rtmp://… | pulse:default | archivo)", default="browser")
        sessions.append(SESSION_TEMPLATE.format(id=slugify(name), name=name.replace('"', "'"), source=source, extra=""))

    token = secrets.token_urlsafe(16)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        YAML_TEMPLATE.format(
            date=datetime.date.today().isoformat(),
            latency=latency,
            title=title.replace('"', "'"),
            port=port,
            translator_provider=translator_provider,
            translator_model=translator_model,
            engine=engine,
            source_language=lang if lang in ("auto", "") else lang,
            targets=", ".join(targets),
            glossary=", ".join(glossary_items),
            sessions="".join(sessions),
        ),
        encoding="utf-8",
    )
    env_lines = [f"GEMINI_API_KEY={key}", f"TRANSCRIBA_ADMIN_TOKEN={token}", "TRANSCRIBA_PUBLIC_URL="]
    env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    try:
        os.chmod(env_path, 0o600)
    except OSError:
        pass
    load_config(out)
    ip = lan_ip()
    typer.echo(f"\n✔ {out} ({n} salas) y {env_path} (token de admin: {token})")
    typer.echo("Siguiente paso:")
    typer.echo(f"  transcriba serve -c {out}")
    typer.echo(f"  audiencia  http://{ip}:{port}/      panel  http://{ip}:{port}/admin      ingesta  http://{ip}:{port}/ingest/<sala>")
    typer.echo("Para acceso desde fuera de la red local (y micrófono desde otras máquinas) hace falta HTTPS: ver docs/OPERACION.md")


@app.command()
def check(
    config: Optional[Path] = typer.Option(None, "-c", "--config"),
    live: bool = typer.Option(False, help="Probar también una conexión Live API real (~1 segundo de audio)"),
) -> None:
    _setup_logging("warning")
    cfg = _load(config)
    ok = True

    def report(label: str, good: bool, detail: str = "") -> None:
        nonlocal ok
        ok &= good
        typer.echo(f"  {'✔' if good else '✖'} {label}{': ' + detail if detail else ''}")

    typer.echo("Dependencias")
    ff = shutil.which("ffmpeg")
    report("ffmpeg", bool(ff), ff or "no encontrado (apt install ffmpeg)")
    report("python", sys.version_info >= (3, 10), platform.python_version())

    engines_used = {cfg.engine_for(s) for s in cfg.sessions} or {cfg.defaults.engine}
    providers = {cfg.translator_for(s).provider for s in cfg.sessions} or {cfg.translator.provider}
    typer.echo(f"Motores en uso: {', '.join(sorted(engines_used))}; traductores: {', '.join(sorted(providers))}")

    needs_gemini = bool(engines_used & {"gemini-live", "gemini-live-translate", "gemini-chunked"}) or "gemini" in providers
    if needs_gemini:
        typer.echo("Gemini")
        key = cfg.gemini.resolve_api_key()
        report(
            "API key",
            bool(key) or cfg.gemini.vertexai,
            "GEMINI_API_KEY presente" if key else "falta GEMINI_API_KEY (https://aistudio.google.com/apikey)",
        )
        if key or cfg.gemini.vertexai:
            from transcriba.translators.gemini import make_client

            client = make_client(cfg.gemini)
            models = {cfg.translator.model}
            if "gemini-live" in engines_used:
                models.add(cfg.engines.gemini_live.asr_model)
            if "gemini-live-translate" in engines_used:
                models.add(cfg.engines.gemini_live_translate.model)
            if "gemini-chunked" in engines_used:
                models.add(cfg.engines.gemini_chunked.model)
            for m in sorted(models):
                try:
                    info = client.models.get(model=m)
                    report(f"modelo {m}", True, getattr(info, "display_name", "") or "ok")
                except Exception as e:
                    report(f"modelo {m}", False, str(e)[:160])
            try:
                from google.genai import types as gtypes

                r = client.models.generate_content(
                    model=cfg.translator.model,
                    contents="Reply with the single word OK.",
                    config=gtypes.GenerateContentConfig(automatic_function_calling=gtypes.AutomaticFunctionCallingConfig(disable=True)),
                )
                report("generate_content", "ok" in (r.text or "").lower(), (r.text or "").strip()[:40])
            except Exception as e:
                report("generate_content", False, str(e)[:200])
            if live and "gemini-live" in engines_used:
                report("Live API", *asyncio.run(_probe_live(client, cfg.engines.gemini_live.asr_model)))

    if "ollama" in providers:
        typer.echo("Ollama")
        from transcriba.translators.ollama import OllamaTranslator

        tr_cfg = next((cfg.translator_for(s) for s in cfg.sessions if cfg.translator_for(s).provider == "ollama"), cfg.translator)
        good, detail = asyncio.run(OllamaTranslator(tr_cfg).healthy())
        report("ollama", good, detail)

    if "local" in engines_used:
        typer.echo("Local (faster-whisper)")
        try:
            import faster_whisper

            report("faster-whisper", True, f"modelo {cfg.engines.local.whisper_model} (se descarga al iniciar)")
        except ImportError:
            report("faster-whisper", False, "pip install 'transcriba[local]'")

    typer.echo("Sesiones")
    for s in cfg.sessions:
        typer.echo(
            f"  • {s.id}: {cfg.engine_for(s)} | {s.source} | {cfg.source_language_for(s) or 'auto'} → {','.join(cfg.target_languages_for(s))}"
        )
    if not cfg.server.admin_token:
        typer.echo("  ! server.admin_token vacío: panel e ingesta sin autenticación (solo para uso local)")
    raise typer.Exit(code=0 if ok else 1)


async def _probe_live(client, model: str) -> tuple[bool, str]:
    from google.genai import types

    from transcriba.audio.pcm import silence

    try:
        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.TEXT], input_audio_transcription=types.AudioTranscriptionConfig()
        )
        async with client.aio.live.connect(model=model, config=config) as session:
            for _ in range(10):
                await session.send_realtime_input(audio=types.Blob(data=silence(100), mime_type="audio/pcm;rate=16000"))
            await session.send_realtime_input(audio_stream_end=True)
        return True, f"conexión a {model} ok"
    except Exception as e:
        return False, str(e)[:200]


@app.command()
def export(
    session_id: str,
    fmt: str = typer.Option("srt", "-f", "--format", help="srt|vtt|txt|jsonl"),
    lang: str = typer.Option("both", "-l", "--lang", help="orig | both | código (es, en…)"),
    data_dir: Path = typer.Option(Path("data"), help="Directorio de datos"),
    out: Optional[Path] = typer.Option(None, "-o", "--out"),
) -> None:
    from transcriba.export import render
    from transcriba.store import CaptionStore

    caps = CaptionStore(data_dir).load(session_id)
    if not caps:
        typer.echo(f"sin datos para {session_id} en {data_dir}", err=True)
        raise typer.Exit(1)
    body, _ = render(caps, fmt, lang)
    if out:
        out.write_text(body, encoding="utf-8")
        typer.echo(f"{len(caps)} subtítulos → {out}")
    else:
        sys.stdout.write(body)


@app.command()
def devices() -> None:
    system = platform.system()
    typer.echo(f"Sistema: {system}")
    if system == "Linux":
        if shutil.which("pactl"):
            typer.echo("PulseAudio/PipeWire sources (usar como source: pulse:<nombre>):")
            subprocess.run(["pactl", "list", "short", "sources"], check=False)
        if shutil.which("arecord"):
            subprocess.run(["arecord", "-l"], check=False)
        typer.echo("Ejemplos: pulse:default | alsa:hw:1,0 | ffmpeg:-f pulse -i alsa_input.usb-XXXX")
    elif system == "Darwin":
        subprocess.run(["ffmpeg", "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""], check=False)
        typer.echo("Ejemplo: avfoundation::1   (índice de audio después de los dos puntos)")
    elif system == "Windows":
        subprocess.run(["ffmpeg", "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"], check=False)
        typer.echo('Ejemplo: "dshow:audio=Mezcla estéreo (Realtek)"')
    typer.echo("Streams: rtmp://host/app/key | srt://host:port | https://…/playlist.m3u8 | archivo.mp3 (con loop: true para demo)")
    typer.echo("Navegador: source: browser  → abrir /ingest/<id> en la laptop de la sala")


if __name__ == "__main__":
    app()
