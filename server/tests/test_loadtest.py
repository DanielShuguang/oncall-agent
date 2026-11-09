"""压测报告口径：成功只认 run.completed，百分位与失败归因可复现。"""

from __future__ import annotations

from app.eval.loadtest import LoadResult, Sample, _summary, render_report


def test_summary_counts_terminal_states() -> None:
    result = LoadResult(
        samples=[
            Sample(True, 200, 20, 120, 8),
            Sample(True, 200, 25, 150, 8),
            Sample(False, 200, 30, 90, 3, "run.failed"),
            Sample(False, 429, None, 5, 0, "HTTP 429: rate limited"),
        ],
        wall_s=2.0,
        health={"status": "ok", "mock_mode": True},
    )
    summary = _summary(result)
    assert summary["requests"] == 4
    assert summary["ok"] == 2
    assert summary["failed"] == 2
    assert summary["success_rate"] == 0.5
    assert summary["rps"] == 2.0
    assert summary["p95_ms"] == 150
    assert summary["first_event_p95_ms"] == 30
    assert summary["failures"] == {"run.failed": 1, "HTTP 429: rate limited": 1}


def test_report_marks_dev_machine_scope() -> None:
    summary = _summary(
        LoadResult(
            samples=[Sample(True, 200, 10, 50, 7)],
            wall_s=0.5,
            health={"status": "ok", "mock_mode": True, "checks": {"db": "up", "redis": "up"}},
        )
    )
    summary["concurrency"] = 1
    report = render_report("test-load", summary, LoadResult())
    assert "成功率 | 100.00%" in report
    assert "不是 8C16G 生产容量承诺" in report
    assert "无。" in report
