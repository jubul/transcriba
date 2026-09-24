from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from transcriba import __version__
from transcriba.audio.pcm import SAMPLE_RATE, resample_pcm
from transcriba.config import ENGINE_NAMES, AppConfig, SessionConfig
from transcriba.export import FORMATS, render
from transcriba.hub import ALL, Hub
from transcriba.pipeline import SessionManager
from transcriba.store import CaptionStore

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent / "web"


class CreateSession(SessionConfig):
    start: bool = True


def create_app(cfg: AppConfig, manager: SessionManager | None = None, hub: Hub | None = None, store: CaptionStore | None = None) -> FastAPI:
    hub = hub or Hub(history_size=cfg.server.history_size)
    store = store or CaptionStore(cfg.server.data_dir)
    manager = manager or SessionManager(cfg, hub, store)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        if not cfg.server.admin_token:
            log.warning("server.admin_token is empty: admin API and ingest are OPEN. Set it before exposing to a network.")
        await manager.start_all()
        try:
            yield
        finally:
            await manager.stop_all()

    app = FastAPI(title="transcriba", version=__version__, lifespan=lifespan)
    app.state.cfg, app.state.manager, app.state.hub, app.state.store = cfg, manager, hub, store
    app.add_middleware(CORSMiddleware, allow_origins=cfg.server.cors_origins, allow_methods=["*"], allow_headers=["*"])
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")

    def token_ok(token: str | None) -> bool:
        return not cfg.server.admin_token or token == cfg.server.admin_token

    def require_admin(request: Request) -> None:
        auth = request.headers.get("authorization", "")
        token = (
            request.headers.get("x-admin-token")
            or request.query_params.get("token")
            or (auth[7:] if auth.lower().startswith("bearer ") else None)
        )
        if not token_ok(token):
            raise HTTPException(401, "admin token required")

    def public_base(request: Request) -> str:
        if cfg.server.public_url:
            return cfg.server.public_url.rstrip("/")
        return str(request.base_url).rstrip("/")

    def runner_or_404(session_id: str):
        r = manager.get(session_id)
        if r is None:
            raise HTTPException(404, f"session {session_id} not found")
        return r

    @app.get("/", include_in_schema=False)
    async def audience_page() -> FileResponse:
        return FileResponse(WEB_DIR / "audience.html")

    @app.get("/admin", include_in_schema=False)
    async def admin_page() -> FileResponse:
        return FileResponse(WEB_DIR / "admin.html")

    @app.get("/view/{session_id}", include_in_schema=False)
    async def viewer_page(session_id: str) -> FileResponse:
        return FileResponse(WEB_DIR / "viewer.html")

    @app.get("/ingest/{session_id}", include_in_schema=False)
    async def ingest_page(session_id: str) -> FileResponse:
        return FileResponse(WEB_DIR / "ingest.html")

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"ok": True, "version": __version__, "sessions": len(manager.runners)}

    @app.get("/api/config")
    async def api_config(request: Request) -> dict[str, Any]:
        return {
            "version": __version__,
            "title": cfg.server.title,
            "public_url": public_base(request),
            "engines": list(ENGINE_NAMES),
            "defaults": cfg.defaults.model_dump(exclude={"translator"}),
            "auth_required": bool(cfg.server.admin_token),
        }

    @app.get("/api/sessions")
    async def list_sessions() -> list[dict[str, Any]]:
        return manager.statuses()

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str) -> dict[str, Any]:
        return runner_or_404(session_id).status().model_dump(mode="json")

    @app.get("/api/sessions/{session_id}/captions")
    async def get_captions(session_id: str, limit: int = Query(200, ge=1, le=2000)) -> list[dict[str, Any]]:
        runner_or_404(session_id)
        return [c.model_dump(mode="json") for c in hub.history(session_id)[-limit:]]

    @app.get("/api/sessions/{session_id}/transcript.{fmt}")
    async def transcript(session_id: str, fmt: str, lang: str = "both", download: bool = False) -> Response:
        if fmt not in FORMATS:
            raise HTTPException(400, f"format must be one of {', '.join(FORMATS)}")
        caps = store.load(session_id)
        if not caps and manager.get(session_id) is None:
            raise HTTPException(404, "no transcript for that session")
        if not caps:
            caps = [c for c in hub.history(session_id)]
        body, mime = render(caps, fmt, lang)
        headers = {"Content-Disposition": f'attachment; filename="{session_id}.{lang}.{fmt}"'} if download else {}
        return Response(content=body, media_type=f"{mime}; charset=utf-8", headers=headers)

    @app.get("/api/sessions/{session_id}/qr.svg")
    async def qr(request: Request, session_id: str, lang: str = "es") -> Response:
        import qrcode
        import qrcode.image.svg

        url = f"{public_base(request)}/view/{session_id}?lang={lang}"
        img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=2)
        buf = io.BytesIO()
        img.save(buf)
        return Response(content=buf.getvalue(), media_type="image/svg+xml")

    @app.post("/api/sessions", status_code=201, dependencies=[Depends(require_admin)])
    async def create_session(body: CreateSession) -> dict[str, Any]:
        if manager.get(body.id) is not None:
            raise HTTPException(409, f"session {body.id} already exists")
        session_cfg = SessionConfig.model_validate(body.model_dump(exclude={"start"}))
        runner = manager.add(session_cfg, persist=True)
        if body.start:
            try:
                await runner.start()
            except Exception as e:
                raise HTTPException(502, f"session created but failed to start: {e}")
        return runner.status().model_dump(mode="json")

    @app.post("/api/sessions/{session_id}/start", dependencies=[Depends(require_admin)])
    async def start_session(session_id: str) -> dict[str, Any]:
        r = runner_or_404(session_id)
        try:
            await r.start()
        except Exception as e:
            raise HTTPException(502, str(e))
        return r.status().model_dump(mode="json")

    @app.post("/api/sessions/{session_id}/stop", dependencies=[Depends(require_admin)])
    async def stop_session(session_id: str) -> dict[str, Any]:
        r = runner_or_404(session_id)
        await r.stop()
        return r.status().model_dump(mode="json")

    @app.delete("/api/sessions/{session_id}", dependencies=[Depends(require_admin)])
    async def delete_session(session_id: str) -> dict[str, str]:
        runner_or_404(session_id)
        await manager.remove(session_id)
        return {"deleted": session_id}

    async def relay(ws: WebSocket, q: asyncio.Queue, binary: bool = False) -> None:
        async def sender() -> None:
            while True:
                item = await q.get()
                if binary:
                    await ws.send_bytes(item)
                else:
                    await ws.send_text(item)

        async def receiver() -> None:
            while True:
                await ws.receive()

        tasks = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks:
                t.cancel()
            for t in tasks:
                with contextlib.suppress(BaseException):
                    await t

    @app.websocket("/ws/captions/{session_id}")
    async def ws_captions(ws: WebSocket, session_id: str) -> None:
        await ws.accept()
        q = hub.subscribe(session_id)
        try:
            await ws.send_text(hub.snapshot_message(session_id))
            await relay(ws, q)
        except WebSocketDisconnect:
            pass
        finally:
            hub.unsubscribe(session_id, q)

    @app.websocket("/ws/audio/{session_id}")
    async def ws_audio(ws: WebSocket, session_id: str) -> None:
        await ws.accept()
        q = hub.subscribe_audio(session_id)
        try:
            await relay(ws, q, binary=True)
        except WebSocketDisconnect:
            pass
        finally:
            hub.unsubscribe_audio(session_id, q)

    @app.websocket("/ws/status")
    async def ws_status(ws: WebSocket) -> None:
        await ws.accept()
        q = hub.subscribe(ALL)
        try:
            await ws.send_text(json.dumps({"type": "sessions", "data": manager.statuses()}, ensure_ascii=False))
            await relay(ws, q)
        except WebSocketDisconnect:
            pass
        finally:
            hub.unsubscribe(ALL, q)

    @app.websocket("/ws/ingest/{session_id}")
    async def ws_ingest(ws: WebSocket, session_id: str, token: str | None = None) -> None:
        await ws.accept()

        async def reject(code: int, message: str) -> None:
            await ws.send_text(json.dumps({"type": "error", "code": code, "message": message}, ensure_ascii=False))
            await ws.close(code=code, reason=message[:120])

        if not token_ok(token):
            return await reject(4401, "token de admin inválido o faltante (campo 'Admin token' o ?token= en la URL)")
        runner = manager.get(session_id)
        if runner is None:
            return await reject(4404, f"la sesión '{session_id}' no existe; crearla en /admin")
        if runner.state.value != "running":
            return await reject(
                4409,
                f"la sesión está en estado '{runner.state.value}'"
                + (f": {runner.error}" if runner.error else "")
                + "; iniciarla desde /admin",
            )
        if not runner.accepts_push:
            return await reject(
                4400, f"la fuente de la sesión es '{runner.cfg.source}', no 'browser'; detenerla y recrearla con source: browser"
            )
        runner.set_ingest_connected(True)
        await runner.publish_status()
        sample_rate = SAMPLE_RATE
        received = 0
        try:
            while True:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                if msg.get("bytes"):
                    pcm = msg["bytes"]
                    if sample_rate != SAMPLE_RATE:
                        pcm = resample_pcm(pcm, sample_rate, SAMPLE_RATE)
                    runner.push_audio(pcm)
                    received += len(pcm)
                elif msg.get("text"):
                    try:
                        ctl = json.loads(msg["text"])
                    except json.JSONDecodeError:
                        continue
                    if ctl.get("type") == "hello":
                        sample_rate = int(ctl.get("sampleRate") or SAMPLE_RATE)
                        await ws.send_text(json.dumps({"type": "ready", "sampleRate": SAMPLE_RATE, "session": session_id}))
                    elif ctl.get("type") == "ping":
                        await ws.send_text(json.dumps({"type": "pong", "received": received, "stream_time": runner.clock()}))
        except WebSocketDisconnect:
            pass
        finally:
            runner.set_ingest_connected(False)
            with contextlib.suppress(Exception):
                await runner.publish_status()

    @app.exception_handler(KeyError)
    async def key_error(_: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    return app
