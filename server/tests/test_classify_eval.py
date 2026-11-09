"""D11 意图分类评测的回归测试（不依赖数据库/模型）。"""

from __future__ import annotations

from datetime import UTC, datetime

from app.eval.classify import CASES_PATH, evaluate, load_cases, render_report


def test_cases_cover_all_intents_and_fifty_samples() -> None:
    cases = load_cases()
    assert len(cases) == 50
    assert {case.intent for case in cases} == {"knowledge", "asset_check", "ticket_create"}
    assert all(
        case.incident in {"hardware", "network", "account", "software", "other"} for case in cases
    )


def test_rule_path_meets_acceptance_line() -> None:
    report = evaluate(load_cases())
    # D11 验收线 85%；规则路径是确定性运行，低于线直接失败
    assert report.joint_accuracy >= 0.85, report.misses
    assert report.intent_accuracy >= 0.85
    assert report.incident_accuracy >= 0.85


def test_report_documents_methodology_and_failures() -> None:
    report = evaluate(load_cases())
    text = render_report(
        report,
        cases_path=CASES_PATH,
        generated_at=datetime(2026, 11, 9, tzinfo=UTC),
    )
    assert "50 条人工标注" in text
    assert "样本内" in text
    assert "模型兜底" in text
    assert "验收线（≥ 85%）" in text
