"""多轮评测（ADR-0024）：追问轮到底有没有用上之前的上下文。

docs/08 §3.2 一直写着「多轮不在评测集里」。缺的不是用例，是**口径**：追问
（「那怎么办」）单独拿去检索本来就没有可匹配的词，只要它命中了文档，就分不清
是"用上了上下文"还是"碰巧命中"。所以这里把判定拆成两步：

1. **指代解对**：追问轮的引用命中用例标注的文档（文档级，不看段落）；
2. **隔离对照**：同一句追问在**空会话**里单独提问时，不得命中同一篇文档——
   否则这条用例根本没测到指代，是假通过。

只有两步都成立才算解对。这个对照让"多轮有效"变成可证伪的结论，而不是
"跑了 9 条都过了"。

与 `runner.py` 的分工：
- 50 条主评测仍是**单轮**，基线（`docs/eval/baseline-v1.md`）的召回/引用/延迟口径不变
- 这里只测多轮，指标是 `coref_acc`，另有诊断项（「那 + 新话题」会不会被上一轮
  话题带偏），诊断项**不计入门槛**，避免把已知边界伪装成回归
- 判定全部是规则，mock 模式即可确定性复跑；真实模型的指代解析收益不在这里量化
- 三轮用例同时是 `contextual_query` 连续追问累积的回归：只拼紧邻一句时，第三步的
  检索词里已经没有最初的话题（ADR-0024）

用法：
    uv run python -m app.eval.multiturn
    uv run python -m app.eval.multiturn --cases path/to/cases.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from app.agent.deps import AgentDeps
from app.agent.history import HistoryTurn, needs_context
from app.agent.nodes.finalize import REFUSAL
from app.agent.runtime import stream
from app.rag.embed import HashingEmbedder
from app.rag.memory import MemoryKnowledgeStore
from app.rag.retrieve import KnowledgeBase
from app.schemas.event import EventType
from app.tools.builtin import build_registry
from app.tools.registry import Identity, ToolGuard

CASES_PATH = Path(__file__).resolve().parent / "multiturn_cases.yaml"
REPORTS_DIR = Path(__file__).resolve().parents[2] / "eval-reports"
#: 与 `runner.EVAL_USER` 同一个人：多轮只是多轮，权限边界不能跟着放宽
EVAL_USER = Identity(user_id="u_102", roles=frozenset({"employee"}))
#: 回归门槛：低于它就返回非 0，供 CI/本地发现"多轮变差了"
CORE_ACC_FLOOR = 0.85
MODEL_LABEL = "rule-engine（mock 模式，无 LLM 调用）"


@dataclass(slots=True)
class TurnSpec:
    query: str
    expected: dict[str, Any]


@dataclass(slots=True)
class MultiTurnCase:
    id: str
    turns: list[TurnSpec]
    note: str = ""
    #: 诊断项：只观测、不参与 coref_acc 与门槛（见 `load_cases` 的约束）
    diagnostic: bool = False

    @property
    def judged(self) -> TurnSpec:
        """只判定最后一轮；前面的轮次负责把上下文铺出来。"""
        return self.turns[-1]

    @property
    def setup(self) -> list[TurnSpec]:
        return self.turns[:-1]


@dataclass(slots=True)
class TurnOutcome:
    index: int
    query: str
    answer: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    #: 同一句单独提问（空会话）时的引用；只有被判定轮才有对照
    isolation_citations: list[dict[str, Any]] | None = None

    @property
    def passed(self) -> bool:
        return not self.failures


@dataclass(slots=True)
class CaseOutcome:
    case: MultiTurnCase
    turns: list[TurnOutcome]
    #: 铺上下文的那几轮没答对：追问轮的上下文不成立，用例直接失败
    setup_failures: list[str] = field(default_factory=list)

    @property
    def judged(self) -> TurnOutcome:
        return self.turns[-1]

    @property
    def passed(self) -> bool:
        return not self.setup_failures and self.judged.passed

    @property
    def isolation_ok(self) -> bool | None:
        """没有对照（诊断项/无 must_cite_docs）时返回 None，不计入分母。"""
        if not self.case.judged.expected.get("must_cite_docs"):
            return None
        return not any("隔离对照不成立" in failure for failure in self.judged.failures)


def load_cases(path: Path = CASES_PATH) -> list[MultiTurnCase]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    cases: list[MultiTurnCase] = []
    seen: set[str] = set()
    for item in payload:
        case_id = str(item["id"])
        if case_id in seen:
            raise SystemExit(f"多轮用例 id 重复: {case_id}")
        seen.add(case_id)
        raw_turns = item.get("turns") or []
        if len(raw_turns) < 2:
            raise SystemExit(f"{case_id}: 多轮用例至少要有两轮（首轮 + 追问）")
        turns: list[TurnSpec] = []
        for index, raw in enumerate(raw_turns):
            query = str(raw.get("query") or "").strip()
            if not query:
                raise SystemExit(f"{case_id}: 第 {index + 1} 轮缺少 query")
            expected = dict(raw.get("expected") or {})
            if index > 0 and not needs_context(query):
                # 启发式不认它是追问，就不会把上一轮拼进检索词——测到的不是指代
                raise SystemExit(
                    f"{case_id}: 第 {index + 1} 轮「{query}」不会被判定为追问"
                    "（需要 ≤30 字且带指代词/承接词，见 ADR-0020）"
                )
            if index == len(raw_turns) - 1 and not (
                expected.get("must_cite_docs") or expected.get("must_refuse")
            ):
                raise SystemExit(f"{case_id}: 最后一轮必须是 must_cite_docs 或 must_refuse")
            turns.append(TurnSpec(query=query, expected=expected))
        diagnostic = bool(item.get("diagnostic"))
        if diagnostic and not turns[-1].expected.get("must_refuse"):
            # 诊断项只观测「不该答的别答」；否则等于给失败用例开一个绕开门槛的口子
            raise SystemExit(f"{case_id}: 诊断项只能判定 must_refuse")
        cases.append(
            MultiTurnCase(
                id=case_id,
                turns=turns,
                note=str(item.get("note") or ""),
                diagnostic=diagnostic,
            )
        )
    if not cases:
        raise SystemExit(f"没有读到多轮用例: {path}")
    return cases


def _citation_covers(citations: list[dict[str, Any]], document: str) -> bool:
    for citation in citations:
        title = str(citation.get("title") or "")
        heading = str(citation.get("heading") or "")
        if document in title or document in heading:
            return True
    return False


def _refused(answer: str) -> bool:
    return answer.startswith(REFUSAL) or "没有检索到" in answer


def judge_turn(turn: TurnSpec, answer: str, citations: list[dict[str, Any]]) -> list[str]:
    """单轮的期望判定：引用命中 / 答案关键词 / 该拒答。"""
    expected = turn.expected
    failures: list[str] = []

    required = [str(doc) for doc in expected.get("must_cite_docs") or []]
    missing = [doc for doc in required if not _citation_covers(citations, doc)]
    if missing:
        failures.append(f"引用未命中: {missing}")

    for phrase in [str(text) for text in expected.get("answer_must_contain") or []]:
        if phrase not in answer:
            failures.append(f"答案缺少: {phrase}")

    if expected.get("must_refuse"):
        if not _refused(answer):
            failures.append("没有拒答：被上一轮话题带偏了")
        if citations:
            failures.append(f"不应带引用: {[str(item.get('title') or '') for item in citations]}")

    return failures


def judge_isolation(turn: TurnSpec, isolation_citations: list[dict[str, Any]]) -> list[str]:
    """隔离对照：单独提问也命中文档，就说明这条用例没测到指代。"""
    documents = [str(doc) for doc in turn.expected.get("must_cite_docs") or []]
    hit = [doc for doc in documents if _citation_covers(isolation_citations, doc)]
    if hit:
        return [f"隔离对照不成立：单独提问也命中 {hit}（用例没测到指代）"]
    return []


async def _run_turn(
    query: str,
    *,
    history: list[HistoryTurn],
    deps: AgentDeps,
    session_id: str | None,
) -> tuple[str, list[dict[str, Any]]]:
    events = [
        event
        async for event in stream(
            run_id=str(uuid.uuid4()),
            identity=EVAL_USER,
            query=query,
            model="rule-engine",
            deps=deps,
            session_id=session_id,
            history=history,
        )
    ]
    answer = ""
    citations: list[dict[str, Any]] = []
    for event_type, payload in events:
        if event_type is EventType.MESSAGE_COMPLETED:
            answer = str(payload.get("text") or "")
            citations = list(payload.get("citations") or [])
    return answer, citations


async def run_case(case: MultiTurnCase, deps: AgentDeps) -> CaseOutcome:
    history: list[HistoryTurn] = []
    outcomes: list[TurnOutcome] = []
    last_index = len(case.turns) - 1
    for index, turn in enumerate(case.turns):
        answer, citations = await _run_turn(
            turn.query,
            history=list(history),
            deps=deps,
            session_id=f"mt-{case.id}",
        )
        outcome = TurnOutcome(
            index=index,
            query=turn.query,
            answer=answer,
            citations=citations,
            failures=judge_turn(turn, answer, citations),
        )
        if index == last_index:
            # 隔离对照：同样的追问句，不带历史再跑一遍
            _, isolation_citations = await _run_turn(
                turn.query,
                history=[],
                deps=deps,
                session_id=None,
            )
            outcome.isolation_citations = isolation_citations
            outcome.failures += judge_isolation(turn, isolation_citations)
        if answer:
            history.append(HistoryTurn(query=turn.query, answer=answer))
        outcomes.append(outcome)

    setup_failures = [
        f"第 {outcome.index + 1} 轮「{outcome.query}」未通过：{'；'.join(outcome.failures)}"
        for outcome in outcomes[:-1]
        if outcome.failures
    ]
    return CaseOutcome(case=case, turns=outcomes, setup_failures=setup_failures)


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


@dataclass(slots=True)
class Report:
    outcomes: list[CaseOutcome]

    @property
    def coref_cases(self) -> list[CaseOutcome]:
        return [outcome for outcome in self.outcomes if not outcome.case.diagnostic]

    @property
    def diagnostic_cases(self) -> list[CaseOutcome]:
        return [outcome for outcome in self.outcomes if outcome.case.diagnostic]

    @property
    def coref_hit(self) -> int:
        return sum(1 for outcome in self.coref_cases if outcome.passed)

    @property
    def coref_acc(self) -> float:
        return _ratio(self.coref_hit, len(self.coref_cases))

    @property
    def isolation_total(self) -> int:
        return sum(1 for outcome in self.coref_cases if outcome.isolation_ok is not None)

    @property
    def isolation_ok(self) -> int:
        return sum(1 for outcome in self.coref_cases if outcome.isolation_ok)

    @property
    def diagnostic_ok(self) -> int:
        return sum(1 for outcome in self.diagnostic_cases if outcome.passed)

    @property
    def failures(self) -> list[CaseOutcome]:
        return [outcome for outcome in self.outcomes if not outcome.passed]


def evaluate(outcomes: list[CaseOutcome]) -> Report:
    return Report(outcomes=outcomes)


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _docs_text(citations: list[dict[str, Any]]) -> str:
    titles = {str(citation.get("title") or "") for citation in citations}
    return "、".join(sorted(title for title in titles if title)) or "无"


def _isolation_text(outcome: CaseOutcome) -> str:
    if outcome.case.judged.expected.get("must_refuse"):
        return "不适用（诊断项）"
    if outcome.isolation_ok:
        return "成立"
    return "不成立"


def render_report(report: Report, *, cases_path: Path, generated_at: datetime | None = None) -> str:
    generated_at = generated_at or datetime.now(UTC)
    generated_local = generated_at.astimezone()
    status = "达标" if report.coref_acc >= CORE_ACC_FLOOR else f"未达标（< {CORE_ACC_FLOOR:.0%}）"
    lines = [
        "# 多轮评测（ADR-0024）",
        "",
        f"- 生成时间：{generated_local:%Y-%m-%d %H:%M:%S %Z}",
        f"- 样本：{len(report.coref_cases)} 条多轮用例 + "
        f"{len(report.diagnostic_cases)} 条诊断项（`{cases_path.name}`）",
        f"- 模型：{MODEL_LABEL}",
        "- 判定：只判最后一轮追问；前面的轮次是 setup，它失败用例即失败",
        "- 口径：确定性规则，单次运行即结果；用例参与过追问启发式设计，属**样本内**结果",
        "",
        "## 总览",
        "",
        "| 指标 | 结果 |",
        "|---|---|",
        f"| 追问轮指代解对率 `coref_acc` | **{_pct(report.coref_acc)}**"
        f"（{report.coref_hit}/{len(report.coref_cases)}） |",
        f"| 隔离对照成立 | {report.isolation_ok}/{report.isolation_total} |",
        f"| 诊断：新话题不被上一轮带偏 | {report.diagnostic_ok}/{len(report.diagnostic_cases)}"
        "（不计入门槛） |",
        f"| 回归门槛（`coref_acc` ≥ {CORE_ACC_FLOOR:.0%}） | {status} |",
        "",
        "## 用例明细",
        "",
        "| 用例 | setup 问题 | 追问 | 追问轮引用 | 隔离对照 | 结果 |",
        "|---|---|---|---|---|---|",
    ]
    for outcome in report.outcomes:
        setup_query = " → ".join(turn.query for turn in outcome.case.setup)
        judged = outcome.judged
        lines.append(
            f"| {outcome.case.id}{'（诊断）' if outcome.case.diagnostic else ''} "
            f"| {setup_query} | {judged.query} | {_docs_text(judged.citations)} "
            f"| {_isolation_text(outcome)} | {'PASS' if outcome.passed else 'FAIL'} |"
        )

    lines += ["", "## 失败明细", ""]
    if not report.failures:
        lines.append("无。")
    else:
        lines += ["| 用例 | 原因 |", "|---|---|"]
        for outcome in report.failures:
            reasons = list(outcome.setup_failures)
            if outcome.judged.failures:
                reasons.append(f"追问轮：{'；'.join(outcome.judged.failures)}")
            lines.append(f"| {outcome.case.id} | {'；'.join(reasons)} |")

    lines += [
        "",
        "## 口径与局限",
        "",
        "- 只覆盖**被追问启发式判定为追问**的句子（≤ 30 字 + 指代词/承接词，ADR-0020）；"
        "启发式漏判的追问不在这里，它们的表现仍是单轮行为。",
        "- 隔离对照用同一句追问在空会话里再跑一次：只有它单独命不中文档，才算测到了指代。",
        "- 诊断项（「那 + 新话题」）观测的是 ADR-0020 已记录的稀释边界，"
        "只报告、不计入 `coref_acc` 与门槛；失败不代表本次回归。",
        "- mock 模式没有 LLM：历史只影响检索词与选句，"
        "真实模型的指代解析收益需配置 provider 后另跑。",
        "- 每条用例只判最后一轮，前序轮次失败会让用例失败；用例参与过启发式设计，属样本内结果。",
        "",
    ]
    return "\n".join(lines) + "\n"


def _payload(report: Report) -> dict[str, Any]:
    return {
        "coref_cases": len(report.coref_cases),
        "coref_hit": report.coref_hit,
        "coref_acc": report.coref_acc,
        "isolation_ok": report.isolation_ok,
        "isolation_total": report.isolation_total,
        "diagnostic_total": len(report.diagnostic_cases),
        "diagnostic_ok": report.diagnostic_ok,
        "floor": CORE_ACC_FLOOR,
        "cases": [
            {
                "id": outcome.case.id,
                "diagnostic": outcome.case.diagnostic,
                "passed": outcome.passed,
                "setup": [turn.query for turn in outcome.case.setup],
                "query": outcome.judged.query,
                "citations": [str(item.get("title") or "") for item in outcome.judged.citations],
                "isolation_citations": [
                    str(item.get("title") or "")
                    for item in (outcome.judged.isolation_citations or [])
                ],
                "setup_failures": outcome.setup_failures,
                "failures": outcome.judged.failures,
            }
            for outcome in report.outcomes
        ],
    }


async def run_eval(cases: list[MultiTurnCase] | None = None) -> Report:
    cases = cases or load_cases()
    kb = KnowledgeBase(MemoryKnowledgeStore(), HashingEmbedder(), auto_seed=True)
    deps = AgentDeps(guard=ToolGuard(build_registry()), retriever=kb)
    return evaluate([await run_case(case, deps) for case in cases])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="多轮评测（ADR-0024）")
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--report-dir", type=Path, default=REPORTS_DIR)
    args = parser.parse_args(argv)

    cases = load_cases(args.cases)
    report = asyncio.run(run_eval(cases))
    generated_at = datetime.now(UTC)
    stamp = generated_at.astimezone().strftime("%Y%m%d-%H%M%S")
    args.report_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = args.report_dir / f"multiturn-{stamp}.md"
    json_path = args.report_dir / f"multiturn-{stamp}.json"
    markdown_path.write_text(
        render_report(report, cases_path=args.cases, generated_at=generated_at),
        encoding="utf-8",
    )
    json_path.write_text(
        json.dumps(_payload(report), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(
        f"多轮评测：coref {report.coref_hit}/{len(report.coref_cases)} "
        f"({_pct(report.coref_acc)}) "
        f"隔离对照 {report.isolation_ok}/{report.isolation_total} "
        f"诊断 {report.diagnostic_ok}/{len(report.diagnostic_cases)}"
    )
    for outcome in report.failures:
        reasons = list(outcome.setup_failures)
        if outcome.judged.failures:
            reasons.append("；".join(outcome.judged.failures))
        print(f"  - {outcome.case.id}: {'；'.join(reasons)}")
    print(f"报告：{markdown_path}")
    return 0 if report.coref_acc >= CORE_ACC_FLOOR else 1


if __name__ == "__main__":
    raise SystemExit(main())
