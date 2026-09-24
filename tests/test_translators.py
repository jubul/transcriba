import json

import httpx
import pytest

from transcriba.config import TranslatorConfig
from transcriba.translators.base import TranslationRequest, build_user_prompt, clean_translations, parse_json_object
from transcriba.translators.mock import MockTranslator
from transcriba.translators.ollama import OllamaTranslator


def test_parse_json_tolerates_fences_and_aliases():
    obj = parse_json_object('```json\n{"Spanish": "hola", "en": "hi"}\n```')
    assert clean_translations(obj, ["es", "en"]) == {"es": "hola", "en": "hi"}


def test_prompt_includes_context_and_glossary():
    req = TranslationRequest("Deploy the pods", "en", ["es"], context=[("Hi all", {"es": "Hola a todos"})], glossary=["Kubernetes"])
    p = build_user_prompt(req)
    assert "Hi all" in p and "Hola a todos" in p and "Deploy the pods" in p


async def test_mock_translator():
    tr = MockTranslator()
    out = await tr.translate(TranslationRequest("hello", "en", ["es", "pt"]))
    assert out == {"es": "[es] hello", "pt": "[pt] hello"}


async def test_ollama_translator_against_fake_server():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        assert request.url.path == "/api/chat"
        return httpx.Response(200, json={"message": {"role": "assistant", "content": json.dumps({"es": "Hola mundo"})}})

    tr = OllamaTranslator(TranslatorConfig(provider="ollama", model="gemma4:e4b"), transport=httpx.MockTransport(handler))
    out = await tr.translate(TranslationRequest("Hello world", "en", ["es"], glossary=["Nerdearla"]))
    assert out == {"es": "Hola mundo"}
    assert seen["body"]["model"] == "gemma4:e4b"
    assert seen["body"]["format"]["required"] == ["es"]
    assert "Nerdearla" in seen["body"]["messages"][0]["content"]
    await tr.aclose()


async def test_ollama_gives_up_gracefully():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    tr = OllamaTranslator(TranslatorConfig(provider="ollama", model="gemma4:e4b", timeout_s=1), transport=httpx.MockTransport(handler))
    tr._client.timeout = httpx.Timeout(1)
    out = await tr.translate(TranslationRequest("x", "en", ["es"]))
    assert out == {}
    await tr.aclose()
