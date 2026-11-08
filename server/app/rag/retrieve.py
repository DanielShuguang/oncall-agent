"""检索编排：切分入库、混合召回、RRF、重排、阈值。

两路召回（稀疏 tsvector / 稠密 pgvector）各自取 `rag_candidates` 条，
用 RRF 融合后按「词面覆盖 + 标题命中 + 融合排名 + 向量相似」重排。
v0 的重排是确定性的，不依赖模型；`bge-reranker` 只是未来的一个实现。

空召回 / 最高分低于 `rag_min_score` 时返回空列表，finalize 必须走兜底话术，
**绝不把空上下文喂给模型**（docs/05 §5.4）。
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Protocol

from app.rag.chunk import Chunk, chunk_parsed
from app.rag.embed import Embedder
from app.rag.parse import ParsedDoc, parse_bytes
from app.rag.text import (
    expand_tokens,
    token_set,
    token_text,
    token_weights,
    tokenize,
    weighted_coverage,
)
from app.rag.types import ChunkRow, DocumentInfo, Hit, KnowledgeStore, Ranked, StoredChunk

RRF_K = 60
MIN_SCORE = 0.38
WEIGHTS = (0.45, 0.10, 0.25, 0.15)  # 覆盖 / 标题路径 / RRF / 向量


class Retriever(Protocol):
    async def search(self, query: str, top_k: int | None = None) -> list[Hit]: ...


@dataclass(slots=True)
class KnowledgeBase:
    store: KnowledgeStore
    embedder: Embedder
    top_k: int = 5
    candidates: int = 20
    min_score: float = MIN_SCORE
    rrf_k: int = RRF_K
    #: 内存模式首次检索时自动灌入 seed 语料；Postgres 模式必须显式 `make seed`
    auto_seed: bool = False
    _seeded: bool = field(default=False, init=False)
    _seed_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def _ensure_seed(self) -> None:
        if not self.auto_seed or self._seeded:
            return
        async with self._seed_lock:
            if self._seeded:
                return
            # 不能只在「库为空」时灌 seed：内存模式下先上传再提问会让 50 篇演示语料
            # 永远缺失。index_text 按 source 覆盖，重复执行是幂等的，失败后下次还能补。
            from app.seed.corpus import build_documents

            for document in build_documents():
                await self.index_text(
                    title=document.title,
                    text=document.text,
                    source=f"seed:{document.filename}",
                )
            self._seeded = True

    async def index_parsed(
        self,
        parsed: ParsedDoc,
        *,
        source: str,
        version: str | None = None,
    ) -> tuple[DocumentInfo, list[Chunk]]:
        chunks = chunk_parsed(parsed)
        if not chunks:
            raise ValueError("文档没有可索引的切片")
        checksum = _checksum(parsed)
        texts = [_embed_text(chunk) for chunk in chunks]
        vectors = await self.embedder.embed(texts)
        stored = [
            StoredChunk(
                ord=chunk.ord,
                text=chunk.text,
                heading=chunk.heading,
                page=chunk.page,
                tokens=token_text(_embed_text(chunk)),
                embedding=vector,
                is_table=chunk.is_table,
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        await self.store.delete_by_source(source)
        info = await self.store.add_document(
            title=parsed.title,
            source=source,
            checksum=checksum,
            chunks=stored,
            version=version,
        )
        return info, chunks

    async def index_bytes(
        self,
        filename: str,
        data: bytes,
        *,
        version: str | None = None,
    ) -> tuple[DocumentInfo, list[Chunk]]:
        # PDF/DOCX 解析是 CPU 密集的同步代码；上传接口在事件循环里，直接跑会卡住
        # 其他请求（包括 SSE）。放线程池，10MB 扫描件也不会把 API 拖死。
        parsed = await asyncio.to_thread(parse_bytes, filename, data)
        return await self.index_parsed(parsed, source=filename, version=version)

    async def index_text(
        self,
        *,
        title: str,
        text: str,
        source: str,
    ) -> tuple[DocumentInfo, list[Chunk]]:
        from app.rag.parse import parse_markdown_text

        parsed = parse_markdown_text(text, title=title)
        return await self.index_parsed(parsed, source=source)

    async def search(self, query: str, top_k: int | None = None) -> list[Hit]:
        query = query.strip()
        if not query:
            return []
        await self._ensure_seed()
        tokens = expand_tokens(tokenize(query))
        if not tokens:
            return []
        limit = top_k or self.top_k
        query_vector = (await self.embedder.embed([query]))[0]

        sparse, dense = await asyncio.gather(
            self.store.sparse_search(tokens, self.candidates),
            self.store.dense_search(query_vector, self.candidates),
        )
        fused, dense_scores = _fuse(sparse, dense, self.rrf_k)
        if not fused:
            return []
        rows = await self.store.fetch_chunks(list(fused))
        if not rows:
            return []

        query_weights = token_weights(query)
        query_compact = _compact(query)
        max_rrf = 2.0 / (self.rrf_k + 1)
        hits: list[Hit] = []
        scored: list[tuple[ChunkRow, float]] = []
        for chunk_id, fused_score in fused.items():
            row = rows.get(chunk_id)
            if row is None:
                continue
            score = _rerank(
                query_weights=query_weights,
                query_compact=query_compact,
                row=row,
                fused_norm=fused_score / max_rrf,
                dense_similarity=dense_scores.get(chunk_id, 0.0),
            )
            scored.append((row, score))

        # 文档级一致性：同一篇文档有一个高分切片，其余切片通常也在回答同一问题。
        # 没有这一步，"VPN 连不上" 的第三条引用会跳到碰巧出现"连不上"的 WiFi 文档。
        best_by_document: dict[str, float] = {}
        for row, score in scored:
            best_by_document[row.document_id] = max(
                best_by_document.get(row.document_id, 0.0), score
            )
        for row, score in scored:
            if best_by_document[row.document_id] >= 0.55:
                score += 0.06
            if score < self.min_score:
                continue
            hits.append(_hit(row, score))
        hits.sort(key=lambda hit: (-hit.score, hit.chunk_id))
        return hits[:limit]

    async def list_documents(self) -> list[DocumentInfo]:
        await self._ensure_seed()
        return await self.store.list_documents()

    async def get_document(self, document_id: str) -> tuple[DocumentInfo, list[ChunkRow]] | None:
        return await self.store.get_document(document_id)

    async def chunk_count(self) -> int:
        await self._ensure_seed()
        return await self.store.chunk_count()

    async def reindex(self) -> int:
        """用当前 embedder 重算所有切片向量与分词；不重新切分源文件。"""
        chunks = await self.store.all_chunks()
        if not chunks:
            return 0
        texts = [_embed_text_row(row) for row in chunks]
        vectors = await self.embedder.embed(texts)
        updates = [
            (row.chunk_id, token_text(text), vector)
            for row, text, vector in zip(chunks, texts, vectors, strict=True)
        ]
        await self.store.replace_vectors(updates)
        return len(updates)


def _embed_text(chunk: Chunk) -> str:
    return f"{chunk.heading}\n{chunk.text}" if chunk.heading else chunk.text


def _embed_text_row(row: ChunkRow) -> str:
    return f"{row.heading}\n{row.content}" if row.heading else row.content


def _checksum(parsed: ParsedDoc) -> str:
    digest = hashlib.sha256()
    digest.update(parsed.title.encode("utf-8"))
    for block in parsed.blocks:
        digest.update(block.text.encode("utf-8"))
    return digest.hexdigest()


def _fuse(
    sparse: list[Ranked], dense: list[Ranked], rrf_k: int
) -> tuple[dict[int, float], dict[int, float]]:
    scores: dict[int, float] = defaultdict(float)
    dense_scores: dict[int, float] = {}
    for index, item in enumerate(sparse):
        scores[item.chunk_id] += 1.0 / (rrf_k + index + 1)
    for index, item in enumerate(dense):
        scores[item.chunk_id] += 1.0 / (rrf_k + index + 1)
        dense_scores[item.chunk_id] = item.score
    ordered = dict(sorted(scores.items(), key=lambda item: -item[1]))
    return ordered, dense_scores


def _rerank(
    *,
    query_weights: dict[str, float],
    query_compact: str,
    row: ChunkRow,
    fused_norm: float,
    dense_similarity: float,
) -> float:
    chunk_set = set(row.tokens.split())
    coverage = weighted_coverage(query_weights, chunk_set)
    heading_coverage = weighted_coverage(query_weights, token_set(row.heading or ""))
    title_set = token_set(row.title)
    title_coverage = weighted_coverage(query_weights, title_set)
    phrase = _phrase_bonus(query_compact, row.content)
    covering, heading, fused, dense = WEIGHTS
    score = (
        covering * coverage
        + heading * heading_coverage
        + fused * fused_norm
        + dense * max(0.0, dense_similarity)
        + phrase
        + _title_bonus(query_weights, title_set, title_coverage)
        - (0.15 if "归档" in row.title else 0.0)
    )
    return min(score, 1.0)


def _title_bonus(
    query_weights: dict[str, float],
    title_tokens: set[str],
    title_coverage: float,
) -> float:
    """标题命中是多跳/同义问法下最稳定的信号。

    "VPN 连不上" 与 VPN 文档里"客户端下载"小节的词面覆盖并不高，
    仅靠正文覆盖会把 WiFi 文档排到前面；标题里出现 `vpn` 应显著加分。
    归档文档在调用处扣分，避免旧流程被这个 bonus 抬上来。
    """
    exact = any(len(token) >= 2 and token in title_tokens for token in query_weights)
    return (0.10 if exact else 0.0) + 0.08 * title_coverage


def _compact(text: str) -> str:
    return "".join(text.lower().split())


def _phrase_bonus(query_compact: str, content: str) -> float:
    """查询短语在正文里原样出现的奖励。

    "VPN 连不上" 与 "VPN 客户端无法连接" 的 token 覆盖度接近，但前者是
    用户真实问法，应稳定排前。最长公共子串 >= 4 才给分，避免"规则"这类
    两字泛化词误伤负样本。
    """
    if len(query_compact) < 4:
        return 0.0
    common = _lcs_length(query_compact, _compact(content))
    if common < 4:
        return 0.0
    return min(0.18, 0.015 * common)


def _lcs_length(left: str, right: str) -> int:
    if not left or not right:
        return 0
    left = left[:300]
    right = right[:1200]
    previous = [0] * (len(right) + 1)
    best = 0
    for char in left:
        current = [0] * (len(right) + 1)
        for index, other in enumerate(right, start=1):
            if char == other:
                current[index] = previous[index - 1] + 1
                best = max(best, current[index])
        previous = current
    return best


def _hit(row: ChunkRow, score: float) -> Hit:
    return Hit(
        chunk_id=row.chunk_id,
        document_id=row.document_id,
        ord=row.ord,
        title=row.title,
        heading=row.heading,
        content=row.content,
        page=row.page,
        score=round(score, 6),
    )
