"""评测执行器入口：uv run python -m app.eval.runner

实现后应：
1. 读取 cases/*.yaml（50 条）
2. 逐条跑 agent，采集 recall / cite_acc / steps / cost / latency
3. 输出 markdown 报告到 eval-reports/<batch_id>.md
4. 支持 --baseline 对比上一轮

见 docs/08-eval-metrics.md。
"""

from __future__ import annotations


def main() -> int:
    raise SystemExit(
        "尚未实现（计划 W2 D10 出 v0，W6 D26 补齐 50 条）。\n"
        "见 docs/08-eval-metrics.md 与 docs/10-roadmap-6weeks.md。"
    )


if __name__ == "__main__":
    raise SystemExit(main())
