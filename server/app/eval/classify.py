"""意图分类评测（W3 D11）：50 条人工标注，规则路径准确率 + 混淆矩阵。

与 `app/eval/runner.py` 的区别：
- 这里只测 classify 节点，不跑检索/工具/生成，因此是**确定性的**，不需要知识库
- 只覆盖规则路径：mock 模式下没有真实模型，模型兜底路径无法在这里量化
  （docs/08 §6 已说明真实模型效果需配置 provider 后另跑）
- 失败用例原样展示，不静默剔除（R11）

用法：
    uv run python -m app.eval.classify
    uv run python -m app.eval.classify --cases path/to/cases.yaml
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from app.agent.nodes.classify import (
    INCIDENT_TYPES,
    INTENTS,
    classify_incident,
    classify_intent,
    needs_model,
)

CASES_PATH = Path(__file__).resolve().parent / "classify_cases.yaml"
REPORTS_DIR = Path(__file__).resolve().parents[2] / "eval-reports"
INTENT_LABELS = {
    "knowledge": "知识问答",
    "asset_check": "资产查询",
    "ticket_create": "开单（写操作）",
}


@dataclass(slots=True)
class ClassifyCase:
    id: str
    query: str
    intent: str
    incident: str
    note: str = ""


@dataclass(slots=True)
class Miss:
    case: ClassifyCase
    predicted_intent: str
    predicted_incident: str


@dataclass(slots=True)
class ClassifyReport:
    total: int
    intent_ok: int
    incident_ok: int
    joint_ok: int
    misses: list[Miss] = field(default_factory=list)
    confusion: Counter[tuple[str, str]] = field(default_factory=Counter)
    fallback: list[str] = field(default_factory=list)

    @property
    def joint_accuracy(self) -> float:
        return self.joint_ok / self.total if self.total else 0.0

    @property
    def intent_accuracy(self) -> float:
        return self.intent_ok / self.total if self.total else 0.0

    @property
    def incident_accuracy(self) -> float:
        return self.incident_ok / self.total if self.total else 0.0


def load_cases(path: Path = CASES_PATH) -> list[ClassifyCase]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    cases: list[ClassifyCase] = []
    seen: set[str] = set()
    for item in payload:
        case_id = str(item["id"])
        if case_id in seen:
            raise SystemExit(f"分类用例 id 重复: {case_id}")
        seen.add(case_id)
        intent = str(item["intent"])
        incident = str(item["incident"])
        if intent not in INTENTS:
            raise SystemExit(f"{case_id}: 未知 intent {intent}")
        if incident not in INCIDENT_TYPES:
            raise SystemExit(f"{case_id}: 未知 incident {incident}")
        cases.append(
            ClassifyCase(
                id=case_id,
                query=str(item["query"]),
                intent=intent,
                incident=incident,
                note=str(item.get("note") or ""),
            )
        )
    if not cases:
        raise SystemExit(f"没有读到分类用例: {path}")
    return cases


def evaluate(cases: list[ClassifyCase]) -> ClassifyReport:
    report = ClassifyReport(total=len(cases), intent_ok=0, incident_ok=0, joint_ok=0)
    for case in cases:
        predicted_incident = classify_incident(case.query)
        predicted_intent = classify_intent(case.query, predicted_incident)
        intent_ok = predicted_intent == case.intent
        incident_ok = predicted_incident == case.incident
        report.intent_ok += int(intent_ok)
        report.incident_ok += int(incident_ok)
        report.joint_ok += int(intent_ok and incident_ok)
        report.confusion[(case.intent, predicted_intent)] += 1
        if not (intent_ok and incident_ok):
            report.misses.append(Miss(case, predicted_intent, predicted_incident))
        if needs_model(case.query):
            report.fallback.append(case.id)
    return report


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def render_report(
    report: ClassifyReport,
    *,
    cases_path: Path,
    generated_at: datetime | None = None,
) -> str:
    generated_at = generated_at or datetime.now(UTC)
    generated_local = generated_at.astimezone()
    status = "达标" if report.joint_accuracy >= 0.85 else "未达标（< 85%）"
    lines = [
        "# 意图分类评测（D11）",
        "",
        f"- 生成时间：{generated_local:%Y-%m-%d %H:%M:%S %Z}",
        f"- 样本：{report.total} 条人工标注（`{cases_path.name}`）",
        "- 模式：规则路径（mock，无 LLM 调用）",
        "- 判定：intent 与 incident 同时命中才算通过",
        "- 口径：确定性规则，单次运行即结果；样本参与过规则设计，属**样本内**结果",
        "",
        "## 总览",
        "",
        "| 指标 | 结果 |",
        "|---|---|",
        f"| 联合准确率 | **{_pct(report.joint_accuracy)}**（{report.joint_ok}/{report.total}） |",
        f"| intent 准确率 | {_pct(report.intent_accuracy)}（{report.intent_ok}/{report.total}） |",
        f"| incident 准确率 | {_pct(report.incident_accuracy)}"
        f"（{report.incident_ok}/{report.total}） |",
        f"| 验收线（≥ 85%） | {status} |",
        "",
        "## intent 混淆矩阵",
        "",
        "| 期望 \\ 预测 | knowledge | asset_check | ticket_create |",
        "|---|---|---|---|",
    ]
    for expected in ("knowledge", "asset_check", "ticket_create"):
        row = [
            str(report.confusion.get((expected, predicted), 0))
            for predicted in (
                "knowledge",
                "asset_check",
                "ticket_create",
            )
        ]
        lines.append(f"| {expected} | " + " | ".join(row) + " |")

    lines += ["", "## 失败用例", ""]
    if not report.misses:
        lines.append("无。")
    else:
        lines += [
            "| id | query | 期望 | 预测 | 说明 |",
            "|---|---|---|---|---|",
        ]
        for miss in report.misses:
            expected = f"{miss.case.intent} / {miss.case.incident}"
            predicted = f"{miss.predicted_intent} / {miss.predicted_incident}"
            lines.append(
                f"| {miss.case.id} | {miss.case.query} | {expected} | {predicted} "
                f"| {miss.case.note or '—'} |"
            )

    lines += [
        "",
        "## 模型兜底",
        "",
        f"满足 `needs_model` 触发条件、生产环境会调模型兜底/复核的用例："
        f"**{len(report.fallback)}** 条"
        f"（{', '.join(report.fallback) if report.fallback else '无'}）。",
        "这些用例的规则结果仍会计入上面的准确率；模型可能覆盖规则结果，",
        "mock 模式没有真实模型，本报告不度量模型兜底路径的准确率。",
        "",
        "## 局限",
        "",
        "- 50 条用例参与了规则设计，结果不代表盲测泛化",
        "- 只覆盖规则路径；真实模型分类质量需配置 provider 后另跑",
        "- incident 是一句话里的主领域，跨领域描述按先出现的领域人工标注",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="意图分类评测（D11）")
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--report-dir", type=Path, default=REPORTS_DIR)
    args = parser.parse_args(argv)

    cases = load_cases(args.cases)
    report = evaluate(cases)
    generated_at = datetime.now(UTC)
    stamp = generated_at.astimezone().strftime("%Y%m%d-%H%M%S")
    args.report_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = args.report_dir / f"classify-{stamp}.md"
    json_path = args.report_dir / f"classify-{stamp}.json"
    markdown_path.write_text(
        render_report(report, cases_path=args.cases, generated_at=generated_at),
        encoding="utf-8",
    )
    payload: dict[str, Any] = {
        "total": report.total,
        "joint_ok": report.joint_ok,
        "intent_ok": report.intent_ok,
        "incident_ok": report.incident_ok,
        "joint_accuracy": round(report.joint_accuracy, 4),
        "intent_accuracy": round(report.intent_accuracy, 4),
        "incident_accuracy": round(report.incident_accuracy, 4),
        "fallback": report.fallback,
        "misses": [
            {
                "id": miss.case.id,
                "query": miss.case.query,
                "expected": {"intent": miss.case.intent, "incident": miss.case.incident},
                "predicted": {
                    "intent": miss.predicted_intent,
                    "incident": miss.predicted_incident,
                },
            }
            for miss in report.misses
        ],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"分类评测：{report.joint_ok}/{report.total} "
        f"joint={_pct(report.joint_accuracy)} "
        f"intent={_pct(report.intent_accuracy)} "
        f"incident={_pct(report.incident_accuracy)}"
    )
    if report.misses:
        print("失败用例：")
        for miss in report.misses:
            print(
                f"  - {miss.case.id}: {miss.case.query} "
                f"期望 {miss.case.intent}/{miss.case.incident} "
                f"得到 {miss.predicted_intent}/{miss.predicted_incident}"
            )
    print(f"报告：{markdown_path}")
    return 0 if report.joint_accuracy >= 0.85 else 1


if __name__ == "__main__":
    raise SystemExit(main())
