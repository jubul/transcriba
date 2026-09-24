import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from transcriba.config import AppConfig, SessionConfig, load_config

ROOT = Path(__file__).resolve().parent.parent


def test_example_config_loads_with_env_expansion(monkeypatch):
    monkeypatch.setenv("TRANSCRIBA_ADMIN_TOKEN", "tok")
    monkeypatch.setenv("GEMINI_API_KEY", "key")
    monkeypatch.delenv("TRANSCRIBA_PUBLIC_URL", raising=False)
    cfg = load_config(ROOT / "config" / "transcriba.example.yaml")
    assert cfg.server.admin_token == "tok" and cfg.gemini.api_key == "key" and cfg.server.public_url == ""
    assert cfg.engines.gemini_live.asr_model == "gemini-3.5-transcribe-live" and cfg.engines.gemini_live.mode == "SMART"
    assert cfg.engines.gemini_chunked.vad.min_silence_ms == 600
    ids = [s.id for s in cfg.sessions]
    assert ids == ["sala-a", "sala-b", "sala-c", "demo"]
    b = cfg.sessions[1]
    assert cfg.source_language_for(b) is None and cfg.target_languages_for(b) == ["es", "en"]
    c = cfg.sessions[2]
    assert cfg.engine_for(c) == "local" and cfg.translator_for(c).provider == "ollama" and cfg.translator_for(c).model == "gemma4:e4b"
    assert cfg.translator_for(cfg.sessions[0]).provider == "gemini"
    assert "Nerdearla" in cfg.glossary_for(c)


def test_demo_config_loads():
    cfg = load_config(ROOT / "config" / "demo.yaml")
    assert cfg.translator.provider == "mock" and len(cfg.sessions) == 3


def test_unknown_keys_and_bad_ids_are_rejected():
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"server": {"prot": 1}})
    with pytest.raises(ValidationError):
        SessionConfig(id="Sala A")
    with pytest.raises(ValidationError):
        SessionConfig(id="ok", engine="whisperx")


def test_glossary_merge_dedupes():
    cfg = AppConfig.model_validate({"defaults": {"glossary": ["A", "B"]}, "sessions": [{"id": "x", "glossary": ["B", "C", " "]}]})
    assert cfg.glossary_for(cfg.sessions[0]) == ["A", "B", "C"]


def test_latency_profiles_fill_only_unset_values(tmp_path):
    y = tmp_path / "fast.yaml"
    y.write_text("latency_profile: fast\nengines:\n  gemini-live: { final_chunk_max_wait_s: 9 }\n")
    cfg = load_config(y)
    gl = cfg.engines.gemini_live
    assert gl.end_sensitivity == "high" and gl.silence_duration_ms == 300 and gl.final_chunk_timeout_s == 0.8
    assert gl.final_chunk_max_wait_s == 9
    assert cfg.engines.gemini_chunked.vad.max_segment_s == 5.0 and cfg.translator.context_size == 3

    y2 = tmp_path / "quality.yaml"
    y2.write_text("latency_profile: quality\n")
    cfg2 = load_config(y2)
    assert cfg2.engines.gemini_live.end_sensitivity == "low" and cfg2.translator.context_size == 8

    y3 = tmp_path / "default.yaml"
    y3.write_text("server: { port: 9 }\n")
    cfg3 = load_config(y3)
    assert (
        cfg3.latency_profile == "balanced"
        and cfg3.engines.gemini_live.end_sensitivity == "default"
        and cfg3.engines.gemini_live.final_chunk_max_wait_s == 4.0
    )
