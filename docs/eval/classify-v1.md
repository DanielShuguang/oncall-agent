# 意图分类基线 v1（D11）

- 日期：2026-11-09
- 执行：`make eval-classify`（`cd server && uv run python -m app.eval.classify`）
- 用例：`server/app/eval/classify_cases.yaml`，50 条人工标注
- 模式：规则路径（mock，无 LLM 调用）

## 总览

| 指标 | 结果 |
|---|---|
| 联合准确率（intent + incident） | **100.00%**（50/50） |
| intent 准确率 | 100.00%（50/50） |
| incident 准确率 | 100.00%（50/50） |
| 验收线（≥ 85%） | 达标 |

## 分布

| intent | 条数 |
|---|---|
| knowledge | 18 |
| asset_check | 16 |
| ticket_create | 16 |

| incident | 条数 |
|---|---|
| hardware | 23 |
| network | 8 |
| account | 9 |
| software | 4 |
| other | 6 |

## 混淆矩阵

| 期望 \ 预测 | knowledge | asset_check | ticket_create |
|---|---|---|---|
| knowledge | 18 | 0 | 0 |
| asset_check | 0 | 16 | 0 |
| ticket_create | 0 | 0 | 16 |

## 口径与局限

- 判定：`intent` 与 `incident` 同时命中才算通过；规则是确定性函数，单次运行即结果
- **样本内**：50 条用例参与了规则设计，100% 不代表盲测泛化；RAG 评测同样存在这个局限
- 只度量规则路径。mock 模式没有真实模型，模型兜底路径（4 条满足 `needs_model`
  的 knowledge 问法会触发，规则结果可能被模型覆盖）需要配置 provider 后另跑
- 三处规则修补：`台式机` 漏在 hardware 关键词、`软件` 与 `权限` 的 incident
  优先级由本集失败归因驱动；含设备名的保修/政策问法增加了 `asks_policy` 守卫。
  守卫第一版误伤了 4 条多跳保修用例（RAG 评测通过率 92%），改成「有个人指代或
  故障症状时按资产处理」后恢复 50/50
- 复跑会覆盖 `server/eval-reports/classify-*.md`（该目录不入库），本文件是提交时的基线
