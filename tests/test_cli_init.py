import os

from typer.testing import CliRunner

from transcriba.cli import _load, app, load_env_file, slugify
from transcriba.config import load_config


def test_slugify():
    assert slugify("Sala Á / Keynote") == "sala-a-keynote"
    assert slugify("  ") == "sala"


def test_init_non_interactive_writes_yaml_and_env(tmp_path, monkeypatch):
    for k in ("GEMINI_API_KEY", "TRANSCRIBA_ADMIN_TOKEN", "TRANSCRIBA_PUBLIC_URL"):
        monkeypatch.setenv(k, "sentinel")
        del os.environ[k]
    out = tmp_path / "evento" / "transcriba.yaml"
    r = CliRunner().invoke(
        app,
        [
            "init",
            "-o",
            str(out),
            "--yes",
            "--rooms",
            "2",
            "--title",
            "Nerdearla 2026",
            "--lang",
            "auto",
            "--to",
            "es,en",
            "--api-key",
            "k123",
            "--no-verify",
            "--latency",
            "fast",
        ],
    )
    assert r.exit_code == 0, r.output
    assert "transcriba serve -c" in r.output
    cfg = load_config(out)
    assert cfg.latency_profile == "fast" and cfg.engines.gemini_live.end_sensitivity == "high"
    assert [s.id for s in cfg.sessions] == ["sala-a", "sala-b"] and cfg.sessions[0].source == "browser"
    assert cfg.source_language_for(cfg.sessions[0]) is None and cfg.target_languages_for(cfg.sessions[1]) == ["es", "en"]
    env = (out.parent / ".env").read_text()
    assert "GEMINI_API_KEY=k123" in env and "TRANSCRIBA_ADMIN_TOKEN=" in env
    assert oct((out.parent / ".env").stat().st_mode)[-3:] == "600"

    cfg2 = _load(out)
    assert cfg2.gemini.api_key == "k123" and len(cfg2.server.admin_token) > 10

    r2 = CliRunner().invoke(app, ["init", "-o", str(out), "--yes", "--no-verify"])
    assert r2.exit_code == 1 and "sobrescribir" in r2.output.lower()


def test_load_env_file_does_not_override_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSCRIBA_TEST_A", "already")
    monkeypatch.setenv("TRANSCRIBA_TEST_B", "x")
    del os.environ["TRANSCRIBA_TEST_B"]
    p = tmp_path / ".env"
    p.write_text('# comment\nexport TRANSCRIBA_TEST_A=new\nTRANSCRIBA_TEST_B="quoted value"\n\nBROKEN LINE\n')
    assert load_env_file(p) == 1
    assert os.environ["TRANSCRIBA_TEST_A"] == "already" and os.environ["TRANSCRIBA_TEST_B"] == "quoted value"
