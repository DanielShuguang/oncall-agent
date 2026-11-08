# ADR-0011 · RAG 默认不引入 torch/PyMuPDF 2.x

- 状态：已采纳（W2 D6–D10）
- 日期：2026-11-09
- 相关：[05-rag-design](../05-rag-design.md)、[10-roadmap](../10-roadmap-6weeks.md)

## 背景

W2 要在「私有化、8C16G、无 GPU」的演示环境里跑通 RAG 全链路，并且评测必须可复现。
初始依赖里写了 `sentence-transformers`（bge-m3 / bge-reranker）和 `pymupdf>=2`：

- `sentence-transformers` 会拖进 torch（Windows wheel 约 2GB+），`uv sync --all-extras`
  在普通开发机上要下载很久，CI 缓存也很大
- PyMuPDF 2.x 的 wheel 带布局模型（`pymupdf-layout` / `pymupdf4llm` / onnxruntime），
  单 wheel 63MB；本机实测下载 60s 只拿到 1.8MB，`uv sync` 会卡在解析阶段
- 这两者都不是 W2 验收项的必要条件：W2 要证明的是「切分、混合召回、引用、评测」
  这条工程链路，而不是「本地模型效果」

## 决策

1. **向量化默认用确定性哈希**（`HashingEmbedder`）：token 特征哈希到 1024 维并归一化。
   没有模型下载、无需 GPU、同文本在任何机器上得到同一向量，评测可复现。
2. **保留 OpenAI 兼容 HTTP embedding**：`ONCALL_EMBEDDING_PROVIDER=http` 可接
   bge-m3 / Ollama / vLLM / 云厂商；维度强校验 1024，不能静默截断。
3. **重排用确定性规则**：词面覆盖 + 标题命中 + RRF + 向量相似 + 短语奖励；
   重排是 `rag/retrieve.py::_rerank` 这一个纯函数，W4 有模型服务后替换它即可接 bge-reranker。
4. **PDF 默认用 pypdf**：纯 Python、几百 KB，只取文本层 + 页码；
   环境里装了 PyMuPDF 时 `parse.py` 自动优先使用（不写进默认依赖）。
5. `rag` extra 只保留 `pypdf` + `python-docx`；`pgvector` 放进核心依赖（纯 Python，小）。

## 被否决的方案

| 方案 | 否决原因 |
|---|---|
| 默认装 sentence-transformers | 2GB+ torch，私有化交付体积与冷启动都不可接受 |
| 默认装 PyMuPDF 2.x | 63MB wheel + onnxruntime，本机网络下 `uv sync` 不可用 |
| 用云端 embedding 作为默认 | 演示/离线环境无 key，评测不可复现，且与「私有化」定位冲突 |
| 只做词面检索 | 无法验证向量通道与 RRF，W2 的混合检索验收缺失 |

## 后果

- **好处**：`uv sync --extra dev --extra rag` 几十 MB 内完成；评测零成本、可复现；
  私有化交付不需要 GPU
- **代价**：默认哈希向量语义能力弱，同义改写召回差；负样本阈值 0.38 是调出来的，
  换 bge-m3 后必须重跑基线
- **切换方式**：配置 `ONCALL_EMBEDDING_PROVIDER=http` + `ONCALL_EMBEDDING_*`，
  然后 `POST /api/admin/kb/reindex`；评测用固定知识库快照对比（docs/08 §6）
- W3 的意图识别仍走规则 + 小模型兜底，不受本 ADR 影响；W4 的模型网关再统一接本地模型
