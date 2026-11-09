"""Provider 适配：OpenAI 兼容协议 + Ollama 原生协议。

两者都支持 JSON 模式：云端用 `response_format={"type":"json_object"}`，
Ollama 用 `format="json"`。网关不依赖某个 SDK，换 vLLM / 其他兼容服务只改
`base_url` / `model` 配置（docs/decisions/0013-model-gateway.md）。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

from app.gateway.types import ChatMessage, Provider, ProviderError, RawCompletion, Route


class OpenAICompatibleProvider:
    """`/chat/completions` 协议；云端与 vLLM 都走这里。"""

    def __init__(self, route: Route, *, client_factory: Any = httpx.AsyncClient) -> None:
        self.route = route
        self._client_factory = client_factory

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int,
        temperature: float,
        json_mode: bool,
    ) -> RawCompletion:
        payload: dict[str, Any] = {
            "model": self.route.model,
            "messages": [message.as_payload() for message in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        data = await _post_json(
            self._client_factory,
            f"{self.route.base_url.rstrip('/')}/chat/completions",
            payload,
            self.route,
        )
        choices = data.get("choices")
        choice = choices[0] if isinstance(choices, list) and choices else {}
        message = choice.get("message") if isinstance(choice, dict) else {}
        text = message.get("content") if isinstance(message, dict) else ""
        raw_usage = data.get("usage")
        usage = raw_usage if isinstance(raw_usage, dict) else {}
        return RawCompletion(
            text=str(text or ""),
            token_in=_optional_int(usage.get("prompt_tokens")),
            token_out=_optional_int(usage.get("completion_tokens")),
        )


class OllamaProvider:
    """Ollama 原生 `/api/chat`；base_url 配成 `.../v1` 也能用（自动去掉）。"""

    def __init__(self, route: Route, *, client_factory: Any = httpx.AsyncClient) -> None:
        self.route = route
        self._client_factory = client_factory

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int,
        temperature: float,
        json_mode: bool,
    ) -> RawCompletion:
        payload: dict[str, Any] = {
            "model": self.route.model,
            "messages": [message.as_payload() for message in messages],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if json_mode:
            payload["format"] = "json"

        root = self.route.base_url.rstrip("/")
        if root.endswith("/v1"):
            root = root[: -len("/v1")]
        data = await _post_json(
            self._client_factory,
            f"{root}/api/chat",
            payload,
            self.route,
        )
        message = data.get("message")
        text = message.get("content") if isinstance(message, dict) else ""
        return RawCompletion(
            text=str(text or ""),
            token_in=_optional_int(data.get("prompt_eval_count")),
            token_out=_optional_int(data.get("eval_count")),
        )


def build_provider(route: Route) -> Provider:
    if route.provider == "local":
        return OllamaProvider(route)
    return OpenAICompatibleProvider(route)


async def _post_json(
    client_factory: Any,
    url: str,
    payload: dict[str, Any],
    route: Route,
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if route.api_key:
        headers["Authorization"] = f"Bearer {route.api_key}"
    try:
        async with client_factory(timeout=route.timeout_s) as client:
            response = await client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        raise ProviderError(f"{route.provider} 超时", retryable=True) from exc
    except httpx.HTTPError as exc:
        raise ProviderError(f"{route.provider} 网络错误: {exc}", retryable=True) from exc

    if response.status_code >= 400:
        # 429/5xx 值得换下一个 provider；4xx 多半是 key/模型名配错，换一个也可能好
        retryable = response.status_code == 429 or response.status_code >= 500
        raise ProviderError(
            f"{route.provider} HTTP {response.status_code}: {response.text[:200]}",
            retryable=retryable,
            status=response.status_code,
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise ProviderError(f"{route.provider} 返回非 JSON", retryable=True) from exc
    if not isinstance(data, dict):
        raise ProviderError(f"{route.provider} 返回格式错误", retryable=True)
    return data


def _optional_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None
