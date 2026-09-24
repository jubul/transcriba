import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

import transcriba.pipeline as pl
from transcriba.audio.source import build_ffmpeg_args, make_source
from transcriba.config import AppConfig, SessionConfig, TranslatorConfig
from transcriba.hub import Hub
from transcriba.pipeline import SessionManager, SessionRunner
from transcriba.server import create_app
from transcriba.store import CaptionStore
from tests.conftest import SAMPLES

JFK = str(SAMPLES / "jfk.wav")


def app_cfg(tmp_path, token=""):
    cfg = AppConfig()
    cfg.server.data_dir = str(tmp_path / "data")
    cfg.server.admin_token = token
    cfg.translator = TranslatorConfig(provider="mock")
    cfg.defaults.engine = "mock"
    return cfg


def test_ffmpeg_arg_builder():
    a = build_ffmpeg_args("rtmp://h/live/x")
    assert a[0] == "ffmpeg" and "-i" in a and a[-1] == "pipe:1" and "-fflags" in a
    a = build_ffmpeg_args("pulse:default")
    assert a[a.index("-f") + 1] == "pulse" and a[a.index("-i") + 1] == "default"
    a = build_ffmpeg_args("some/file.mp3", loop=True)
    assert "-re" in a and "-stream_loop" in a
    a = build_ffmpeg_args("ffmpeg:-f avfoundation -i :0")
    assert a[a.index("-i") + 1] == ":0"


async def test_pipeline_end_to_end_with_file(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "make_source", lambda spec, extra, loop=False: make_source(spec, extra, loop=loop, realtime=False))
    cfg = app_cfg(tmp_path)
    hub, store = Hub(), CaptionStore(cfg.server.data_dir)
    runner = SessionRunner(SessionConfig(id="t1", source=JFK), cfg, hub, store)
    await runner.start()
    assert runner._task is not None
    await asyncio.wait_for(runner._task, timeout=30)
    hist = hub.history("t1")
    finals = [c for c in hist if c.status.value == "translated"]
    assert len(finals) >= 2
    assert runner.status().captions == len(finals)
    assert abs(runner.clock() - 11.0) < 0.3
    persisted = store.load("t1")
    assert [c.id for c in persisted] == [c.id for c in finals]
    await runner.stop()
    assert runner.state.value == "stopped"


def test_server_flow(tmp_path, jfk_pcm):
    cfg = app_cfg(tmp_path, token="secret")
    app = create_app(cfg)
    with TestClient(app) as client:
        assert client.get("/healthz").json()["ok"]
        assert client.get("/").status_code == 200 and "Elegí tu sala" in client.get("/").text
        assert client.get("/admin").status_code == 200 and client.get("/view/x").status_code == 200

        body = {"id": "demo", "name": "Demo", "source": "browser", "engine": "mock", "source_language": "en", "target_languages": ["es"]}
        assert client.post("/api/sessions", json=body).status_code == 401
        r = client.post("/api/sessions", json=body, headers={"X-Admin-Token": "secret"})
        assert r.status_code == 201, r.text
        assert r.json()["state"] == "running"
        assert client.post("/api/sessions", json=body, headers={"X-Admin-Token": "secret"}).status_code == 409

        with client.websocket_connect("/ws/ingest/demo?token=wrong") as bad:
            err = json.loads(bad.receive_text())
            assert err["type"] == "error" and err["code"] == 4401
        with client.websocket_connect("/ws/ingest/nope?token=secret") as bad:
            assert json.loads(bad.receive_text())["code"] == 4404

        with client.websocket_connect("/ws/captions/demo") as caps_ws:
            first = json.loads(caps_ws.receive_text())
            assert first["type"] == "history" and first["data"] == []

            with client.websocket_connect("/ws/ingest/demo?token=secret") as ing:
                ing.send_text(json.dumps({"type": "hello", "sampleRate": 16000}))
                assert json.loads(ing.receive_text())["type"] == "ready"
                audio = jfk_pcm + b"\x00" * 32000 * 2
                for i in range(0, len(audio), 3200):
                    ing.send_bytes(audio[i : i + 3200])
                ing.send_text(json.dumps({"type": "ping"}))
                pong = json.loads(ing.receive_text())
                assert pong["type"] == "pong" and pong["received"] == len(audio)

            translated = {}
            deadline = time.time() + 20
            while time.time() < deadline and len(translated) < 2:
                m = json.loads(caps_ws.receive_text())
                if m["type"] == "caption" and m["data"]["status"] == "translated":
                    translated[m["data"]["id"]] = m["data"]
            assert len(translated) >= 2
            assert all(c["translations"]["es"].startswith("[es] ") for c in translated.values())

        st = client.get("/api/sessions/demo").json()
        assert st["captions"] >= 2 and st["engine"] == "mock"
        assert client.get("/api/sessions/demo/qr.svg").headers["content-type"].startswith("image/svg")
        srt = client.get("/api/sessions/demo/transcript.srt?lang=es").text
        assert "-->" in srt and "[es]" in srt
        assert client.get("/api/sessions/demo/transcript.bad").status_code == 400

        assert client.post("/api/sessions/demo/stop", headers={"X-Admin-Token": "secret"}).json()["state"] == "stopped"
        assert client.delete("/api/sessions/demo", headers={"X-Admin-Token": "secret"}).json() == {"deleted": "demo"}
        assert client.get("/api/sessions/demo").status_code == 404


async def test_runtime_sessions_are_persisted_and_restored(tmp_path):
    cfg = app_cfg(tmp_path)
    store = CaptionStore(cfg.server.data_dir)
    m1 = SessionManager(cfg, Hub(), store)
    m1.add(SessionConfig(id="r1", name="Creada en el panel", source="browser"), persist=True)
    m1.add(SessionConfig(id="yaml-only", source="browser"))
    saved = json.loads((store.root / "sessions.json").read_text())
    assert [s["id"] for s in saved] == ["r1"] and saved[0]["name"] == "Creada en el panel"

    m2 = SessionManager(cfg, Hub(), store)
    await m2.start_all()
    assert set(m2.runners) == {"r1"} and m2.runners["r1"].state.value == "running"
    await m2.remove("r1")
    assert json.loads((store.root / "sessions.json").read_text()) == []
    await m2.stop_all()
