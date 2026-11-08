"""向量化。

默认实现是确定性的哈希向量（`HashingEmbedder`）：不下载模型、不需要 GPU，
同一段文本在任何机器上得到同一个向量，评测与测试因此可复现。它当然不如
bge-m3 的语义能力，W2 的目标是**把链路跑通并留下可替换的协议**。

生产/追求效果时把 `ONCALL_EMBEDDING_PROVIDER` 切到 `http`，指向任意
OpenAI 兼容的 `/embeddings`（vLLM、Ollama、云厂商均可）。维度必须与
`kb_chunks.embedding` 的 `vector(1024)` 一致，否则入库直接报错而不是静默截断。
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from typing import Protocol

import httpx

from app.core.config import Settings
from app.rag.text import tokenize


class EmbeddingError(RuntimeError):
    """向量化失败；调用方翻译成 5xx/降级，不能吞掉。"""


class Embedder(Protocol):
    @property
    def dim(self) -> int: ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class HashingEmbedder:
    """确定性特征哈希：token -> 维度桶 + 符号，L2 归一化。

    二元组权重更高（区分"打印机"与"打印"），单字权重更低（只是兜底召回）。
    """

    def __init__(self, dim: int = 1024) -> None:
        if dim <= 0:
            raise ValueError("embedding dim 必须为正")
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self._dim
        for token in tokenize(text):
            weight = 1.0 if len(token) == 1 else 2.0
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self._dim
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign * weight

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]


class HttpEmbedder:
    """OpenAI 兼容 `/embeddings` 客户端（bge-m3 / text-embedding-3 均可）。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        dim: int,
        timeout_s: float = 30.0,
    ) -> None:
        if not base_url:
            raise EmbeddingError("ONCALL_EMBEDDING_BASE_URL 未配置，不能使用 http embedding")
        self._url = base_url.rstrip("/") + "/embeddings"
        self._api_key = api_key
        self._model = model
        self._dim = dim
        self._timeout_s = timeout_s

    @property
    def dim(self) -> int:
        return self._dim

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload = {"model": self._model, "input": list(texts)}
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                response = await client.post(self._url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise EmbeddingError(f"embedding 请求失败: {exc}") from exc

        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list) or len(items) != len(texts):
            raise EmbeddingError("embedding 返回条数与输入不一致")
        vectors: list[list[float]] = []
        for item in items:
            embedding = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(embedding, list) or len(embedding) != self._dim:
                actual = len(embedding) if isinstance(embedding, list) else "?"
                raise EmbeddingError(
                    f"embedding 维度与 kb_chunks.embedding 不一致：期望 {self._dim}，实际 {actual}"
                )
            vectors.append([float(value) for value in embedding])
        return vectors


def build_embedder(settings: Settings) -> Embedder:
    provider = settings.embedding_provider.strip().lower()
    if provider == "hashing":
        return HashingEmbedder(settings.embedding_dim)
    if provider == "http":
        return HttpEmbedder(
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
            model=settings.embedding_model,
            dim=settings.embedding_dim,
        )
    raise ValueError(f"未知 ONCALL_EMBEDDING_PROVIDER: {settings.embedding_provider!r}")


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("向量维度不一致")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
