"""多轮评测（ADR-0024 / ADR-0025）：追问轮到底有没有用上之前的上下文。

docs/08 §3.2 一直写着「多轮不在评测集里」。缺的不是用例，是**口径**：追问
（「那怎么办」）单独拿去检索本来就没有可匹配的词，只要它命中了文档，就分不清
是"用上了上下文"还是"碰巧命中"。所以这里把判定拆成两步：

1. **指代解对**：追问轮的引用命中用例标注的文档（文档级，不看段落）；
2. **隔离对照**：同一句追问在**空会话**里单独提问时，不得命中同一篇文档——
   否则这条用例根本没测到指代，是假通过。

只有两步都成立才算解对。这个对照让"多轮有效"变成可证伪的结论，而不是
"正例都过了"。

另一个相反的方向是**上下文过度应用**（ADR-0025）：「那报销怎么走」是新话题，
单独提问就能命中《差旅报销流程》，却曾被上一轮的保修话题稀释。这类用例
（`kind: shift`）的判定是「引用命中新话题 + 不得引用上一轮话题」，隔离对照
的方向也反过来——单独提问**必须**命中所列文档，否则说明它其实是追问，
用例的档位就写错了。两条指标分开记：`coref_acc` 与 `shift_acc`。

与 `runner.py` 的分工：
- 50 条主评测仍是**单轮**，基线（`docs/eval/baseline-v1.md`）的召回/引用/延迟口径不变
- 这里只测多轮，指标是 `coref_acc` / `shift_acc`，另有诊断项（「那 + 新话题」但
  没有点名任何文档），诊断项**不计入门槛**，避免把已知边界伪装成回归
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
from typing import Any, Literal

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
#: 话题切换同样单独设门槛：把 `shift_acc` 混进 `coref_acc` 会让两边都说不清
SHIFT_ACC_FLOOR = 0.85
MODEL_LABEL = "rule-engine（mock 模式，无 LLM 调用）"

#: coref：追问指代上一轮；shift：新话题不被上一轮劫持（ADR-0025）
CaseKind = Literal["coref", "shift"]


@dataclass(slots=True)
class TurnSpec:
    query: str
    expected: dict[str, Any]


@dataclass(slots=True)
class MultiTurnCase:
    id: str
    turns: list[TurnSpec]
    note: str = ""
    kind: CaseKind = "coref"
    #: 诊断项：只观测、不参与 coref_acc/shift_acc 与门槛（见 `load_cases` 的约束）
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
    #: 隔离对照不成立的原因；单独存一份，统计时不靠匹配 failures 里的文案
    isolation_failures: list[str] = field(default_factory=list)

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
    def isolation_holds(self) -> bool | None:
        """没有对照（诊断项/无 must_cite_docs）时返回 None，不计入分母。"""
        if not self.case.judged.expected.get("must_cite_docs"):
            return None
        return not self.judged.isolation_failures


def load_cases(path: Path = CASES_PATH) -> list[MultiTurnCase]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    cases: list[MultiTurnCase] = []
    seen: set[str] = set()
    for item in payload:
        case_id = str(item["id"])
        if case_id in seen:
            raise SystemExit(f"多轮用例 id 重复: {case_id}")
        seen.add(case_id)
        kind_raw = str(item.get("kind") or "coref")
        if kind_raw not in ("coref", "shift"):
            raise SystemExit(f"{case_id}: kind 只能是 coref 或 shift，收到「{kind_raw}」")
        kind: CaseKind = "shift" if kind_raw == "shift" else "coref"
        diagnostic = bool(item.get("diagnostic"))
        if kind == "shift" and diagnostic:
            # 诊断项观测「该拒答的别答」，shift 是正例指标；混在一起两边都说不清
            raise SystemExit(f"{case_id}: shift 用例不能标 diagnostic")
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
            if index < len(raw_turns) - 1 and not expected.get("must_cite_docs"):
                # setup 轮次不判引用的话，它跑挂了只会让追问轮"莫名其妙"答不出来
                raise SystemExit(f"{case_id}: 第 {index + 1} 轮（setup）必须标 must_cite_docs")
            if index == len(raw_turns) - 1:
                cites = bool(expected.get("must_cite_docs"))
                refuses = bool(expected.get("must_refuse"))
                forbidden = bool(expected.get("must_not_cite_docs"))
                if cites and refuses:
                    raise SystemExit(f"{case_id}: 最后一轮不能同时要求命中文档和拒答")
                if not cites and not refuses:
                    raise SystemExit(f"{case_id}: 最后一轮必须是 must_cite_docs 或 must_refuse")
                if refuses and (forbidden or kind == "shift"):
                    raise SystemExit(
                        f"{case_id}: 拒答类用例既不是 shift，也不能带 must_not_cite_docs"
                    )
                if refuses and not diagnostic:
                    raise SystemExit(
                        f"{case_id}: 拒答用例必须标 diagnostic: true"
                        "（正例指标只统计引用命中的用例）"
                    )
                if kind == "shift":
                    if not forbidden:
                        # 少了这一条，"顺手"带上一篇旧话题的文档也会算过
                        raise SystemExit(
                            f"{case_id}: shift 用例必须写 must_not_cite_docs（上一轮话题）"
                        )
                elif forbidden:
                    raise SystemExit(f"{case_id}: must_not_cite_docs 只用于 shift 用例")
            turns.append(TurnSpec(query=query, expected=expected))
        if diagnostic and not turns[-1].expected.get("must_refuse"):
            # 诊断项只观测「不该答的别答」；否则等于给失败用例开一个绕开门槛的口子
            raise SystemExit(f"{case_id}: 诊断项只能判定 must_refuse")
        cases.append(
            MultiTurnCase(
                id=case_id,
                turns=turns,
                note=str(item.get("note") or ""),
                kind=kind,
                diagnostic=diagnostic,
            )
        )
    if not cases:
        raise SystemExit(f"没有读到多轮用例: {path}")
    if not any(case.kind == "coref" and not case.diagnostic for case in cases):
        raise SystemExit(f"没有 coref 正例: {path}（coref_acc 会变成空指标）")
    if not any(case.kind == "shift" for case in cases):
        raise SystemExit(f"没有 shift 用例: {path}（shift_acc 会变成空指标）")
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
    """单轮的期望判定：引用命中 / 不该引用的 / 答案关键词 / 该拒答。"""
    expected = turn.expected
    failures: list[str] = []

    required = [str(doc) for doc in expected.get("must_cite_docs") or []]
    missing = [doc for doc in required if not _citation_covers(citations, doc)]
    if missing:
        failures.append(f"引用未命中: {missing}")

    # 话题切换用例专用：把上一轮话题的文档带进引用，等于没切换过去
    forbidden = [str(doc) for doc in expected.get("must_not_cite_docs") or []]
    leaked = [doc for doc in forbidden if _citation_covers(citations, doc)]
    if leaked:
        failures.append(f"引用了上一轮话题: {leaked}")

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
    """隔离对照（coref）：单独提问也命中文档，就说明这条用例没测到指代。"""
    documents = [str(doc) for doc in turn.expected.get("must_cite_docs") or []]
    hit = [doc for doc in documents if _citation_covers(isolation_citations, doc)]
    if hit:
        return [f"隔离对照不成立：单独提问也命中 {hit}（用例没测到指代）"]
    return []


def judge_shift_isolation(turn: TurnSpec, isolation_citations: list[dict[str, Any]]) -> list[str]:
    """隔离对照（shift）方向相反：单独提问必须自己就命中所列文档。

    这条检查守的是**用例的前提**：如果「那报销怎么走」单独提问都命不中《差旅报销
    流程》，那它其实是个普通追问，写成 shift 就等于把一条指代用例标成了新话题，
    指标会虚高。
    """
    documents = [str(doc) for doc in turn.expected.get("must_cite_docs") or []]
    missing = [doc for doc in documents if not _citation_covers(isolation_citations, doc)]
    if missing:
        return [f"前提不成立：单独提问没有命中 {missing}（这句其实不自足，应写成 coref 用例）"]
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
        if index == last_index and turn.expected.get("must_cite_docs"):
            # 隔离对照：同样的追问句，不带历史再跑一遍。
            # 拒答类（诊断项）没有"必须命中的文档"，对照无从谈起，不白跑一次
            isolation_answer, isolation_citations = await _run_turn(
                turn.query,
                history=[],
                deps=deps,
                session_id=None,
            )
            outcome.isolation_citations = isolation_citations
            if not isolation_answer:
                # 空回答说明这次 run 没跑完：对照不成立不能被当成"对照通过"
                outcome.isolation_failures = ["隔离对照未完成：空会话的 run 没有产出回答"]
            elif case.kind == "shift":
                # 方向相反：新话题的句子单独提问必须自己就能命中文档
                outcome.isolation_failures = judge_shift_isolation(turn, isolation_citations)
            else:
                outcome.isolation_failures = judge_isolation(turn, isolation_citations)
            outcome.failures += outcome.isolation_failures
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
        return [
            outcome
            for outcome in self.outcomes
            if outcome.case.kind == "coref" and not outcome.case.diagnostic
        ]

    @property
    def shift_cases(self) -> list[CaseOutcome]:
        return [outcome for outcome in self.outcomes if outcome.case.kind == "shift"]

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
    def shift_hit(self) -> int:
        return sum(1 for outcome in self.shift_cases if outcome.passed)

    @property
    def shift_acc(self) -> float:
        return _ratio(self.shift_hit, len(self.shift_cases))

    @property
    def isolation_total(self) -> int:
        return sum(1 for outcome in self.coref_cases if outcome.isolation_holds is not None)

    @property
    def isolation_ok(self) -> int:
        return sum(1 for outcome in self.coref_cases if outcome.isolation_holds)

    @property
    def shift_premise_total(self) -> int:
        return sum(1 for outcome in self.shift_cases if outcome.isolation_holds is not None)

    @property
    def shift_premise_ok(self) -> int:
        """shift 的前提：单独提问自己就要能命中所列文档（与 coref 相反）。"""
        return sum(1 for outcome in self.shift_cases if outcome.isolation_holds)

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


def _kind_text(case: MultiTurnCase) -> str:
    if case.diagnostic:
        return "诊断"
    return "切换" if case.kind == "shift" else "指代"


def _isolation_text(outcome: CaseOutcome) -> str:
    if outcome.case.judged.expected.get("must_refuse"):
        return "不适用（诊断项）"
    if outcome.case.kind == "shift":
        # 方向相反：成立的意思是"单独提问也命中"，见 judge_shift_isolation
        return "成立（单独提问也命中）" if outcome.isolation_holds else "前提不成立"
    return "成立" if outcome.isolation_holds else "不成立"


def render_report(report: Report, *, cases_path: Path, generated_at: datetime | None = None) -> str:
    generated_at = generated_at or datetime.now(UTC)
    generated_local = generated_at.astimezone()
    coref_status = (
        "达标" if report.coref_acc >= CORE_ACC_FLOOR else f"未达标（< {CORE_ACC_FLOOR:.0%}）"
    )
    shift_status = (
        "达标" if report.shift_acc >= SHIFT_ACC_FLOOR else f"未达标（< {SHIFT_ACC_FLOOR:.0%}）"
    )
    lines = [
        "# 多轮评测（ADR-0024 / ADR-0025）",
        "",
        f"- 生成时间：{generated_local:%Y-%m-%d %H:%M:%S %Z}",
        f"- 样本：{len(report.coref_cases)} 条指代用例 + {len(report.shift_cases)} 条话题切换用例"
        f" + {len(report.diagnostic_cases)} 条诊断项（`{cases_path.name}`）",
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
        f"| 隔离对照成立（单独提问命不中） | {report.isolation_ok}/{report.isolation_total} |",
        f"| 话题切换正确率 `shift_acc` | **{_pct(report.shift_acc)}**"
        f"（{report.shift_hit}/{len(report.shift_cases)}） |",
        f"| 切换前提成立（单独提问就命中新话题） | {report.shift_premise_ok}/"
        f"{report.shift_premise_total} |",
        f"| 诊断：没点名文档的新话题仍被稀释 | {report.diagnostic_ok}/"
        f"{len(report.diagnostic_cases)}（不计入门槛） |",
        f"| 回归门槛（`coref_acc` ≥ {CORE_ACC_FLOOR:.0%}、`shift_acc` ≥ {SHIFT_ACC_FLOOR:.0%}）"
        f" | coref {coref_status}；shift {shift_status} |",
        "",
        "## 用例明细",
        "",
        "| 用例 | 类别 | setup 问题 | 追问 | 追问轮引用 | 隔离对照 | 结果 |",
        "|---|---|---|---|---|---|---|",
    ]
    for outcome in report.outcomes:
        setup_query = " → ".join(turn.query for turn in outcome.case.setup)
        judged = outcome.judged
        lines.append(
            f"| {outcome.case.id} | {_kind_text(outcome.case)} "
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
        "- 隔离对照用同一句追问在空会话里再跑一次：coref 要求它单独命不中（否则没测到"
        "指代），shift 要求它单独就命中（否则这句话本来就是追问，档位写错了）。",
        "- `shift_acc` 只判引用：命中新话题、且不含上一轮话题的文档；不判答案语句"
        "（选句质量归主集的 `answer_acc`）。",
        "- 诊断项观测的是 ADR-0025 仍未覆盖的边界（**没点名任何文档**的新话题），"
        "只报告、不计入两条指标与门槛；失败不代表本次回归。",
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
        "shift_cases": len(report.shift_cases),
        "shift_hit": report.shift_hit,
        "shift_acc": report.shift_acc,
        "shift_premise_ok": report.shift_premise_ok,
        "shift_premise_total": report.shift_premise_total,
        "diagnostic_total": len(report.diagnostic_cases),
        "diagnostic_ok": report.diagnostic_ok,
        "coref_floor": CORE_ACC_FLOOR,
        "shift_floor": SHIFT_ACC_FLOOR,
        "cases": [
            {
                "id": outcome.case.id,
                "kind": outcome.case.kind,
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
    parser = argparse.ArgumentParser(description="多轮评测（ADR-0024 / ADR-0025）")
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
        f"({_pct(report.coref_acc)}) 隔离对照 {report.isolation_ok}/{report.isolation_total}；"
        f"shift {report.shift_hit}/{len(report.shift_cases)} ({_pct(report.shift_acc)}) "
        f"前提 {report.shift_premise_ok}/{report.shift_premise_total}；"
        f"诊断 {report.diagnostic_ok}/{len(report.diagnostic_cases)}"
    )
    for outcome in report.failures:
        reasons = list(outcome.setup_failures)
        if outcome.judged.failures:
            reasons.append("；".join(outcome.judged.failures))
        print(f"  - {outcome.case.id}: {'；'.join(reasons)}")
    print(f"报告：{markdown_path}")
    passed = report.coref_acc >= CORE_ACC_FLOOR and report.shift_acc >= SHIFT_ACC_FLOOR
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
