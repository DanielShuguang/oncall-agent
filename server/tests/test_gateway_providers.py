"""Provider 适配器的 HTTP 契约（W4 D16）：不依赖真实模型或 API key。

用 `httpx.MockTransport` 校验 URL 拼接、鉴权头、JSON 模式、usage 解析与错误映射；
真实模型的质量/成本仍需配置 provider 后另测（docs/08 §6）。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.gateway.providers import OllamaProvider, OpenAICompatibleProvider
from app.gateway.types import ChatMessage, ProviderError, RawCompletion, Route

Handler = Callable[[httpx.Request], httpx.Response]


def _factory(handler: Handler) -> Callable[..., httpx.AsyncClient]:
    transport = httpx.MockTransport(handler)

    def factory(*, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=transport, timeout=timeout)

    return factory


def _route(**overrides: Any) -> Route:
    values: dict[str, Any] = {
        "provider": "cloud",
        "model": "gpt-test",
        "base_url": "http://cloud/v1/",
        "api_key": "secret",
        "price_in_cents_per_1m": 15,
        "price_out_cents_per_1m": 60,
        "timeout_s": 3.0,
    }
    values.update(overrides)
    return Route(**values)


async def test_openai_compatible_contract() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"intent":"knowledge"}'}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3},
            },
        )

    provider = OpenAICompatibleProvider(_route(), client_factory=_factory(handler))
    raw = await provider.chat(
        [ChatMessage(role="system", content="规则"), ChatMessage(role="user", content="hi")],
        max_tokens=64,
        temperature=0.0,
        json_mode=True,
    )

    request = captured[0]
    assert str(request.url) == "http://cloud/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer secret"
    assert json.loads(request.content) == {
        "model": "gpt-test",
        "messages": [
            {"role": "system", "content": "规则"},
            {"role": "user", "content": "hi"},
        ],
        "temperature": 0.0,
        "max_tokens": 64,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    assert raw == RawCompletion(text='{"intent":"knowledge"}', token_in=7, token_out=3)


async def test_ollama_contract_strips_v1_and_uses_native_format() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "message": {"content": "ok"},
                "prompt_eval_count": 9,
                "eval_count": 4,
            },
        )

    route = _route(
        provider="local",
        model="qwen-test",
        base_url="http://local:11434/v1/",
        api_key="",
    )
    provider = OllamaProvider(route, client_factory=_factory(handler))
    raw = await provider.chat(
        [ChatMessage(role="user", content="hi")],
        max_tokens=32,
        temperature=0.2,
        json_mode=True,
    )

    request = captured[0]
    assert str(request.url) == "http://local:11434/api/chat"
    assert "authorization" not in request.headers
    assert json.loads(request.content) == {
        "model": "qwen-test",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 32},
        "format": "json",
    }
    assert raw == RawCompletion(text="ok", token_in=9, token_out=4)


@pytest.mark.parametrize(
    ("status", "retryable"),
    [(400, False), (429, True), (500, True)],
)
async def test_provider_maps_http_status(status: int, retryable: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="provider error")

    provider = OpenAICompatibleProvider(_route(), client_factory=_factory(handler))
    with pytest.raises(ProviderError) as excinfo:
        await provider.chat(
            [ChatMessage(role="user", content="hi")],
            max_tokens=8,
            temperature=0.0,
            json_mode=False,
        )
    assert excinfo.value.retryable is retryable
    assert excinfo.value.status == status


async def test_provider_maps_timeout_and_non_json() -> None:
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    timeout_provider = OpenAICompatibleProvider(_route(), client_factory=_factory(timeout_handler))
    with pytest.raises(ProviderError, match="超时"):
        await timeout_provider.chat(
            [ChatMessage(role="user", content="hi")],
            max_tokens=8,
            temperature=0.0,
            json_mode=False,
        )

    def plain_text_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    text_provider = OpenAICompatibleProvider(_route(), client_factory=_factory(plain_text_handler))
    with pytest.raises(ProviderError, match="非 JSON"):
        await text_provider.chat(
            [ChatMessage(role="user", content="hi")],
            max_tokens=8,
            temperature=0.0,
            json_mode=False,
        )


async def test_provider_tolerates_missing_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    provider = OpenAICompatibleProvider(_route(), client_factory=_factory(handler))
    raw = await provider.chat(
        [ChatMessage(role="user", content="hi")],
        max_tokens=8,
        temperature=0.0,
        json_mode=False,
    )
    assert raw.text == "ok"
    assert raw.token_in is None
    assert raw.token_out is None
