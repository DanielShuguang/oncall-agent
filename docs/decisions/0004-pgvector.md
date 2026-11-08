# ADR-0004 · 向量存储选 pgvector 而非 Milvus

- 状态：已采纳
- 日期：2026-11-08

## 背景

知识库规模预估：50 篇文档 → 约 5000-50000 个 chunk。私有化交付要求组件尽量少。

## 方案对比

| 维度 | pgvector | Milvus |
|---|---|---|
| 私有化组件数 | 0（复用 PG） | +1 套独立集群（etcd/minio/milvus） |
| 5 万 chunk 延迟 | HNSW 下 <50ms | 更低，但过剩 |
| 与业务表一致性 | 同库，天然事务一致 | 跨库，需自己保证最终一致 |
| 运维成本 | 已有 PG 备份即够 | 需独立备份/扩容方案 |
| JD 关键词 | 一般 | 常被点名 |

## 决策

选 **PostgreSQL 16 + pgvector**，同时用 `tsvector` 做 BM25 稀疏检索，**一个库解决混合检索**。

## 后果

- 正面：部署组件最少；引用溯源可直接 JOIN `kb_chunks` 拿原文；备份/恢复复用 PG 方案
- 负面：千万级向量性能不如专用库；HNSW 索引构建占内存
- 缓解：文档里写明"规模阈值"——超过 500 万 chunk 建议迁移，并给出迁移路径（换 Qdrant/Milvus，检索层抽象为 `Retriever` 接口）

## 设计约束

- `rag/retrieve.py` 定义 `Retriever` 协议（`search(query, top_k) -> list[Hit]`），实现可替换
- 不在业务代码里直接写向量 SQL

## 面试话术

> 我的规模是 5 万 chunk，pgvector 的 HNSW 在这个量级延迟 50ms 以内，而 Milvus 会引入一套独立集群，私有化交付时运维成本翻倍。如果上到千万级我会换 Milvus——这是规模决定的，不是技术优劣。
