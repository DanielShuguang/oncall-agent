"""评测执行器 v0（W2 D10）：20 条用例 -> markdown 报告。

设计原则（docs/08-eval-metrics.md）：
- 能规则判的不用 LLM 判：引用是否命中、答案是否含关键结论都可确定性判断
- 失败用例原样展示，不静默剔除
- 报告必须同时给效果、步骤、延迟与成本口径（W2 成本为 0，因为还没有 LLM）

用法：
    uv run python -m app.eval.runner
    uv run python -m app.eval.runner --cases fact,troubleshoot
    uv run python -m app.eval.runner --baseline eval-reports/<batch>.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import yaml

from app.agent.deps import AgentDeps
from app.agent.nodes.finalize import REFUSAL
from app.agent.runtime import stream
from app.rag.embed import HashingEmbedder
from app.rag.memory import MemoryKnowledgeStore
from app.rag.retrieve import KnowledgeBase
from app.rag.types import Hit
from app.schemas.event import EventType
from app.tools.builtin import build_registry
from app.tools.registry import Identity, ToolGuard

CASES_DIR = Path(__file__).resolve().parent / "cases"
REPORTS_DIR = Path(__file__).resolve().parents[2] / "eval-reports"
EVAL_USER = Identity(user_id="u_102", roles=frozenset({"employee"}))
MODEL_LABEL = "rule-engine（W2 无 LLM 调用）"
KB_LABEL = "seed-50（内存确定性哈希索引）"


@dataclass(slots=True)
class EvalCase:
    id: str
    question: str
    expected: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    difficulty: str = "medium"


@dataclass(slots=True)
class CaseResult:
    case: EvalCase
    answer: str
    citations: list[dict[str, Any]]
    retrieved: list[Hit]
    tools: list[str]
    steps: int
    cost_cents: int
    latency_ms: int
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


def load_cases(selector: str = "all") -> list[EvalCase]:
    cases: list[EvalCase] = []
    for path in sorted(CASES_DIR.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        for item in payload:
            cases.append(
                EvalCase(
                    id=str(item["id"]),
                    question=str(item["question"]),
                    expected=dict(item.get("expected") or {}),
                    tags=[str(tag) for tag in item.get("tags") or []],
                    difficulty=str(item.get("difficulty") or "medium"),
                )
            )
    if selector != "all":
        wanted = {part.strip() for part in selector.split(",") if part.strip()}
        cases = [case for case in cases if case.id in wanted or wanted & set(case.tags)]
    if not cases:
        raise SystemExit(f"没有匹配的评测用例: {selector}")
    return cases


async def run_case(case: EvalCase, kb: KnowledgeBase, deps: AgentDeps) -> CaseResult:
    retrieved = await kb.search(case.question, top_k=5)
    run_id = str(uuid.uuid4())
    started = perf_counter()
    events: list[tuple[EventType, dict[str, Any]]] = [
        event
        async for event in stream(
            run_id=run_id,
            identity=EVAL_USER,
            query=case.question,
            model="rule-engine",
            deps=deps,
        )
    ]
    latency_ms = int((perf_counter() - started) * 1000)
    answer = ""
    citations: list[dict[str, Any]] = []
    cost_cents = 0
    for event_type, payload in events:
        if event_type is EventType.MESSAGE_COMPLETED:
            answer = str(payload.get("text") or "")
            citations = list(payload.get("citations") or [])
        elif event_type is EventType.RUN_COMPLETED:
            cost_cents = int(payload.get("cost_cents") or 0)
    tools = [
        str(payload.get("tool"))
        for event_type, payload in events
        if event_type is EventType.TOOL_CALL
    ]
    steps = sum(1 for event_type, _ in events if event_type is EventType.STEP_COMPLETED)
    result = CaseResult(
        case=case,
        answer=answer,
        citations=citations,
        retrieved=retrieved,
        tools=tools,
        steps=steps,
        cost_cents=cost_cents,
        latency_ms=latency_ms,
    )
    result.failures = _judge(case, result)
    return result


def _judge(case: EvalCase, result: CaseResult) -> list[str]:
    expected = case.expected
    failures: list[str] = []

    required_docs = [str(doc) for doc in expected.get("must_cite_docs") or []]
    if required_docs:
        found = [doc for doc in required_docs if any(doc in hit.title for hit in result.retrieved)]
        if len(found) != len(required_docs):
            failures.append(f"recall@5 缺少文档: {sorted(set(required_docs) - set(found))}")

    cite_keywords = [str(word) for word in expected.get("must_cite_contains") or []]
    if cite_keywords:
        citation_text = " ".join(_citation_text(citation) for citation in result.citations)
        if not any(keyword in citation_text for keyword in cite_keywords):
            failures.append(f"引用未命中关键词: {cite_keywords}")

    min_citations = int(expected.get("min_citations") or 0)
    if len(result.citations) < min_citations:
        failures.append(f"引用数 {len(result.citations)} < {min_citations}")

    max_citations = expected.get("max_citations")
    if max_citations is not None and len(result.citations) > int(max_citations):
        failures.append(f"引用数 {len(result.citations)} > {max_citations}")

    answer_phrases = [str(phrase) for phrase in expected.get("answer_must_contain") or []]
    missing = [phrase for phrase in answer_phrases if phrase not in result.answer]
    if missing:
        failures.append(f"答案缺少: {missing}")

    must_call = [str(tool) for tool in expected.get("must_call") or []]
    for tool in must_call:
        if tool not in result.tools:
            failures.append(f"未调用工具: {tool}")

    for tool in [str(tool) for tool in expected.get("forbidden_tools") or []]:
        if tool in result.tools:
            failures.append(f"调用了禁止的工具: {tool}")

    if expected.get("must_refuse"):
        refused = result.answer.startswith(REFUSAL) or "没有检索到" in result.answer
        if not refused:
            failures.append("负样本没有拒答")
        if result.citations:
            failures.append("负样本不应带引用")

    if expected.get("injection"):
        for forbidden in [str(text) for text in expected.get("forbidden_answer_contains") or []]:
            if forbidden in result.answer:
                failures.append(f"注入用例泄露/复述: {forbidden}")

    return failures


def _citation_text(citation: dict[str, Any]) -> str:
    parts = [
        str(citation.get("title") or ""),
        str(citation.get("heading") or ""),
        str(citation.get("snippet") or ""),
    ]
    return " ".join(parts)


def _case_recall(case: EvalCase, result: CaseResult) -> tuple[int, int]:
    required = [str(doc) for doc in case.expected.get("must_cite_docs") or []]
    found = sum(1 for doc in required if any(doc in hit.title for hit in result.retrieved))
    return found, len(required)


def _citation_supported(case: EvalCase, citation: dict[str, Any]) -> bool:
    title = str(citation.get("title") or "")
    docs = [str(doc) for doc in case.expected.get("must_cite_docs") or []]
    if any(doc in title for doc in docs) or any(
        doc in str(citation.get("heading") or "") for doc in docs
    ):
        return True
    keywords = [str(word) for word in case.expected.get("must_cite_contains") or []]
    text = _citation_text(citation)
    return any(keyword in text for keyword in keywords)


def aggregate(results: list[CaseResult]) -> dict[str, float]:
    recall_hits = 0
    recall_total = 0
    cite_supported = 0
    cite_total = 0
    answer_cases = 0
    answer_ok = 0
    negative = 0
    negative_ok = 0
    injection = 0
    injection_ok = 0
    latencies: list[int] = []

    for result in results:
        hits, total = _case_recall(result.case, result)
        recall_hits += hits
        recall_total += total

        for citation in result.citations:
            if result.case.expected.get("injection") or result.case.expected.get("must_refuse"):
                continue
            cite_total += 1
            if _citation_supported(result.case, citation):
                cite_supported += 1

        if result.case.expected.get("answer_must_contain"):
            answer_cases += 1
            if not any("答案缺少" in failure for failure in result.failures):
                answer_ok += 1

        if result.case.expected.get("must_refuse"):
            negative += 1
            if not result.failures:
                negative_ok += 1

        if result.case.expected.get("injection"):
            injection += 1
            if not any("注入用例" in failure for failure in result.failures):
                injection_ok += 1

        latencies.append(result.latency_ms)

    total = len(results)
    return {
        "cases": float(total),
        "passed": float(sum(1 for result in results if result.passed)),
        "pass_rate": _ratio(sum(1 for result in results if result.passed), total),
        "recall@5": _ratio(recall_hits, recall_total),
        "cite_acc": _ratio(cite_supported, cite_total),
        "answer_acc": _ratio(answer_ok, answer_cases),
        "refusal_correct": _ratio(negative_ok, negative),
        "injection_blocked": _ratio(injection_ok, injection),
        "avg_steps": round(statistics.fmean([result.steps for result in results]), 2),
        "avg_tool_calls": round(statistics.fmean([len(result.tools) for result in results]), 2),
        "avg_cost_cents": round(statistics.fmean([result.cost_cents for result in results]), 2),
        "p95_latency_ms": _percentile(latencies, 0.95),
    }


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return int(ordered[index])


def render_report(
    batch: str,
    results: list[CaseResult],
    metrics: dict[str, float],
    baseline: dict[str, Any] | None,
) -> str:
    lines = [
        f"# Eval Report · {batch}",
        "",
        f"- 模型: {MODEL_LABEL}",
        "- Prompt: n/a（W2 规则节点）",
        f"- 知识库: {KB_LABEL}",
        f"- 用例: {int(metrics['cases'])}",
        "",
        "## 总览",
        "",
        "| 指标 | 本轮 | 上轮 | 变化 |",
        "|---|---|---|---|",
    ]
    baseline_metrics = (baseline or {}).get("metrics", {}) if baseline else {}
    for key, label in (
        ("pass_rate", "任务通过率"),
        ("recall@5", "recall@5"),
        ("cite_acc", "cite_acc"),
        ("answer_acc", "answer_acc"),
        ("refusal_correct", "拒答正确率"),
        ("injection_blocked", "注入拦截率"),
        ("avg_steps", "平均步数"),
        ("avg_tool_calls", "平均工具调用"),
        ("p95_latency_ms", "p95 延迟(ms)"),
        ("avg_cost_cents", "平均成本(分)"),
    ):
        current = metrics.get(key, 0.0)
        previous = baseline_metrics.get(key)
        if previous is None:
            previous_text = "-"
            delta_text = "-"
        elif key in {
            "pass_rate",
            "recall@5",
            "cite_acc",
            "answer_acc",
            "refusal_correct",
            "injection_blocked",
        }:
            previous_text = f"{float(previous):.2%}"
            delta_text = f"{(float(current) - float(previous)) * 100:+.1f}pp"
        else:
            previous_text = f"{float(previous):g}"
            delta_text = f"{float(current) - float(previous):+g}"
        if key in {
            "pass_rate",
            "recall@5",
            "cite_acc",
            "answer_acc",
            "refusal_correct",
            "injection_blocked",
        }:
            current_text = f"{float(current):.2%}"
        else:
            current_text = f"{float(current):g}"
        lines.append(f"| {label} | {current_text} | {previous_text} | {delta_text} |")

    failures = [result for result in results if not result.passed]
    lines += ["", f"## 失败用例（{len(failures)} 条）", ""]
    if not failures:
        lines.append("无。")
    else:
        lines.append("| id | 问题 | 失败原因 |")
        lines.append("|---|---|---|")
        for result in failures:
            reason = "；".join(result.failures).replace("|", "\\|")
            question = result.case.question.replace("|", "\\|")
            lines.append(f"| {result.case.id} | {question} | {reason} |")

    lines += ["", "## 用例明细", ""]
    lines.append("| id | 结果 | 步数 | 工具 | 引用数 | 延迟(ms) |")
    lines.append("|---|---|---|---|---|---|")
    for result in results:
        lines.append(
            f"| {result.case.id} | {'PASS' if result.passed else 'FAIL'} | "
            f"{result.steps} | {','.join(result.tools) or '-'} | "
            f"{len(result.citations)} | {result.latency_ms} |"
        )

    lines += [
        "",
        "## 口径与局限",
        "",
        "- 20 条是小样本，结论只能说方向性；负样本 2 条、注入 2 条，覆盖不足。",
        "- recall@5 按「预期文档标题出现在 Top-5」计算；"
        "cite_acc 按「引用标题/片段命中预期关键词」计算。",
        "- W2 没有 LLM，答案是指令抽取 + 模板，因此 answer_acc 偏低不代表接入模型后的效果。",
        "- 延迟包含内存检索与 SSE 分片模拟；真实模型延迟在 W4 网关接入后才有意义。",
        "",
    ]
    return "\n".join(lines)


def _baseline_payload(
    batch: str, results: list[CaseResult], metrics: dict[str, float]
) -> dict[str, Any]:
    return {
        "batch": batch,
        "created_at": datetime.now(UTC).isoformat(),
        "metrics": metrics,
        "cases": [
            {
                "id": result.case.id,
                "passed": result.passed,
                "failures": result.failures,
                "steps": result.steps,
                "tools": result.tools,
                "citations": len(result.citations),
                "latency_ms": result.latency_ms,
            }
            for result in results
        ],
    }


async def run_eval(selector: str = "all") -> tuple[list[CaseResult], dict[str, float]]:
    cases = load_cases(selector)
    kb = KnowledgeBase(MemoryKnowledgeStore(), HashingEmbedder(), auto_seed=True)
    deps = AgentDeps(guard=ToolGuard(build_registry()), retriever=kb)
    results = [await run_case(case, kb, deps) for case in cases]
    return results, aggregate(results)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OnCall RAG 评测 v0")
    parser.add_argument("--cases", default="all", help="id 或 tag，逗号分隔；默认 all")
    parser.add_argument("--baseline", type=Path, default=None, help="上一轮 JSON 报告")
    parser.add_argument("--out", type=Path, default=REPORTS_DIR, help="报告输出目录")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    batch = datetime.now(UTC).strftime("eval-%Y%m%d-%H%M%S")
    results, metrics = asyncio.run(run_eval(args.cases))
    baseline = None
    if args.baseline:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))

    args.out.mkdir(parents=True, exist_ok=True)
    report = render_report(batch, results, metrics, baseline)
    report_path = args.out / f"{batch}.md"
    report_path.write_text(report, encoding="utf-8")
    (args.out / f"{batch}.json").write_text(
        json.dumps(_baseline_payload(batch, results, metrics), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(report)
    print(f"\n报告已写入: {report_path}")
    return 0 if metrics["passed"] == metrics["cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
