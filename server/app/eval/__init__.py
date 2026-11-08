"""评测框架（W2 D10 起实现）。

设计见 docs/08-eval-metrics.md：
- cases/*.yaml 定义 50 条用例（事实/排查/多跳/负样本/注入）
- runner.py 执行并输出 markdown 报告
- 判定器优先规则，必须用 LLM 判时固定模型与 prompt 版本
"""
