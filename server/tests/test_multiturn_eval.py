"""多轮评测（ADR-0024 / ADR-0025）：用例可加载、判定可解释、两个方向的对照都能证伪。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.deps import AgentDeps
from app.agent.history import HistoryTurn
from app.agent.nodes.finalize import REFUSAL
from app.agent.runtime import stream
from app.eval import multiturn as multiturn_module
from app.eval.multiturn import (
    CORE_ACC_FLOOR,
    SHIFT_ACC_FLOOR,
    CaseOutcome,
    MultiTurnCase,
    TurnOutcome,
    TurnSpec,
    evaluate,
    judge_isolation,
    judge_shift_isolation,
    judge_turn,
    load_cases,
    main,
    render_report,
    run_case,
    run_eval,
)
from app.rag.embed import HashingEmbedder
from app.rag.memory import MemoryKnowledgeStore
from app.rag.retrieve import KnowledgeBase
from app.schemas.event import EventType
from app.tools.builtin import build_registry
from app.tools.registry import Identity, ToolGuard

VPN_DOC = "VPN 连接失败排查指南"


def _deps() -> AgentDeps:
    kb = KnowledgeBase(MemoryKnowledgeStore(), HashingEmbedder(), auto_seed=True)
    return AgentDeps(guard=ToolGuard(build_registry()), retriever=kb)


def _case(case_id: str, follow_up: str) -> MultiTurnCase:
    return MultiTurnCase(
        id=case_id,
        turns=[
            TurnSpec("VPN 客户端在哪里下载", {"must_cite_docs": [VPN_DOC]}),
            TurnSpec(follow_up, {"must_cite_docs": [VPN_DOC]}),
        ],
    )


def _outcome(
    case: MultiTurnCase,
    *,
    citations: list[dict[str, object]] | None = None,
    failures: list[str] | None = None,
) -> CaseOutcome:
    return CaseOutcome(
        case=case,
        turns=[
            TurnOutcome(index=0, query=case.turns[0].query, answer="答"),
            TurnOutcome(
                index=1,
                query=case.turns[1].query,
                answer="答",
                citations=list(citations or []),
                failures=list(failures or []),
            ),
        ],
    )


def test_cases_load_and_every_follow_up_is_detected() -> None:
    cases = load_cases()

    assert len(cases) == 17
    assert sum(1 for case in cases if case.diagnostic) == 1
    assert sum(1 for case in cases if case.kind == "shift") == 4
    assert {case.id for case in cases} >= {"mt-vpn-err502", "mt-three-turn-vpn"}
    assert all(len(case.turns) >= 2 for case in cases)
    assert all(case.judged.expected.get("must_cite_docs") for case in cases if not case.diagnostic)
    assert all(case.judged.expected.get("must_refuse") for case in cases if case.diagnostic)
    # shift 必须写死"不得引用上一轮话题"，否则只要顺手带上一篇也会算过
    forbidden = "must_not_cite_docs"
    assert all(case.judged.expected.get(forbidden) for case in cases if case.kind == "shift")
    assert all(not case.judged.expected.get(forbidden) for case in cases if case.kind == "coref")


def test_loader_rejects_follow_up_that_the_heuristic_would_ignore(tmp_path: Path) -> None:
    path = tmp_path / "cases.yaml"
    path.write_text(
        "- id: bad\n"
        "  turns:\n"
        "    - query: 打印机离线怎么排查\n"
        "      expected: {must_cite_docs: [打印机离线排查指南]}\n"
        "    - query: 需要谁审批\n"
        "      expected: {must_cite_docs: [打印机离线排查指南]}\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="不会被判定为追问"):
        load_cases(path)


def test_loader_rejects_diagnostic_that_is_not_a_refusal(tmp_path: Path) -> None:
    """诊断项不计入门槛，必须只能是「该拒答」，否则等于给失败用例开后门。"""
    path = tmp_path / "cases.yaml"
    path.write_text(
        "- id: sneaky\n"
        "  diagnostic: true\n"
        "  turns:\n"
        "    - query: VPN 客户端在哪里下载\n"
        "      expected: {must_cite_docs: [VPN 连接失败排查指南]}\n"
        "    - query: 那接下来要做什么\n"
        "      expected: {must_cite_docs: [VPN 连接失败排查指南]}\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="诊断项只能判定 must_refuse"):
        load_cases(path)


def test_loader_rejects_single_turn_case(tmp_path: Path) -> None:
    path = tmp_path / "cases.yaml"
    path.write_text(
        "- id: lonely\n  turns:\n    - query: 打印机离线怎么办\n"
        "      expected: {must_cite_docs: [打印机离线排查指南]}\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="至少要有两轮"):
        load_cases(path)


def test_loader_rejects_refusal_case_without_diagnostic_flag(tmp_path: Path) -> None:
    """coref_acc 是「引用命中」的正例指标，拒答用例只能作为诊断项观测。"""
    path = tmp_path / "cases.yaml"
    path.write_text(
        "- id: sneak\n"
        "  turns:\n"
        "    - query: VPN 客户端在哪里下载\n"
        "      expected: {must_cite_docs: [VPN 连接失败排查指南]}\n"
        "    - query: 那报销怎么走\n"
        "      expected: {must_refuse: true}\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="拒答用例必须标 diagnostic"):
        load_cases(path)


def test_loader_rejects_mixed_expectations(tmp_path: Path) -> None:
    path = tmp_path / "cases.yaml"
    path.write_text(
        "- id: mixed\n"
        "  turns:\n"
        "    - query: VPN 客户端在哪里下载\n"
        "      expected: {must_cite_docs: [VPN 连接失败排查指南]}\n"
        "    - query: 那接下来要做什么\n"
        "      expected: {must_cite_docs: [VPN 连接失败排查指南], must_refuse: true}\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="不能同时要求命中文档和拒答"):
        load_cases(path)


def test_loader_rejects_case_file_without_positive_cases(tmp_path: Path) -> None:
    """只剩诊断项时 coref_acc 是空指标，不能当成"通过"。"""
    path = tmp_path / "cases.yaml"
    path.write_text(
        "- id: only-diag\n"
        "  diagnostic: true\n"
        "  turns:\n"
        "    - query: 公司笔记本整机保修几年\n"
        "      expected: {must_cite_docs: [电脑保修与换新政策]}\n"
        "    - query: 那报销怎么走\n"
        "      expected: {must_refuse: true}\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="没有 coref 正例"):
        load_cases(path)


def test_loader_rejects_setup_turn_without_citation_assertion(tmp_path: Path) -> None:
    """setup 轮次不判引用，它跑挂了只会让追问轮莫名其妙答不出来。"""
    path = tmp_path / "cases.yaml"
    path.write_text(
        "- id: no-setup\n"
        "  turns:\n"
        "    - query: VPN 客户端在哪里下载\n"
        "      expected: {}\n"
        "    - query: 那接下来要做什么\n"
        "      expected: {must_cite_docs: [VPN 连接失败排查指南]}\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="setup）必须标 must_cite_docs"):
        load_cases(path)


def test_loader_rejects_shift_case_without_forbidden_docs(tmp_path: Path) -> None:
    """shift 不写 must_not_cite_docs，等于只要"顺手"带上一篇旧话题的文档也会算过。"""
    path = tmp_path / "cases.yaml"
    path.write_text(
        "- id: shift\n"
        "  kind: shift\n"
        "  turns:\n"
        "    - query: 公司笔记本整机保修几年\n"
        "      expected: {must_cite_docs: [电脑保修与换新政策]}\n"
        "    - query: 那报销怎么走\n"
        "      expected: {must_cite_docs: [差旅报销流程]}\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="必须写 must_not_cite_docs"):
        load_cases(path)


def test_loader_rejects_forbidden_docs_on_coref_case(tmp_path: Path) -> None:
    path = tmp_path / "cases.yaml"
    path.write_text(
        "- id: coref\n"
        "  turns:\n"
        "    - query: VPN 客户端在哪里下载\n"
        "      expected: {must_cite_docs: [VPN 连接失败排查指南]}\n"
        "    - query: 那接下来要做什么\n"
        "      expected:\n"
        "        must_cite_docs: [VPN 连接失败排查指南]\n"
        "        must_not_cite_docs: [打印机离线排查指南]\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="must_not_cite_docs 只用于 shift 用例"):
        load_cases(path)


def test_loader_rejects_shift_case_marked_as_diagnostic(tmp_path: Path) -> None:
    path = tmp_path / "cases.yaml"
    path.write_text(
        "- id: shift-diag\n"
        "  kind: shift\n"
        "  diagnostic: true\n"
        "  turns:\n"
        "    - query: 公司笔记本整机保修几年\n"
        "      expected: {must_cite_docs: [电脑保修与换新政策]}\n"
        "    - query: 那报销怎么走\n"
        "      expected:\n"
        "        must_cite_docs: [差旅报销流程]\n"
        "        must_not_cite_docs: [电脑保修]\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="shift 用例不能标 diagnostic"):
        load_cases(path)


def test_loader_rejects_unknown_kind(tmp_path: Path) -> None:
    path = tmp_path / "cases.yaml"
    path.write_text(
        "- id: weird\n"
        "  kind: mixed\n"
        "  turns:\n"
        "    - query: VPN 客户端在哪里下载\n"
        "      expected: {must_cite_docs: [VPN 连接失败排查指南]}\n"
        "    - query: 那接下来要做什么\n"
        "      expected: {must_cite_docs: [VPN 连接失败排查指南]}\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="kind 只能是 coref 或 shift"):
        load_cases(path)


def test_loader_rejects_case_file_without_shift_cases(tmp_path: Path) -> None:
    """没有 shift 用例时 shift_acc 是空指标，不能当成"通过"。"""
    path = tmp_path / "cases.yaml"
    path.write_text(
        "- id: coref\n"
        "  turns:\n"
        "    - query: VPN 客户端在哪里下载\n"
        "      expected: {must_cite_docs: [VPN 连接失败排查指南]}\n"
        "    - query: 那接下来要做什么\n"
        "      expected: {must_cite_docs: [VPN 连接失败排查指南]}\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="没有 shift 用例"):
        load_cases(path)


def test_judge_turn_matches_document_by_title_or_heading() -> None:
    turn = TurnSpec("那怎么办", {"must_cite_docs": [VPN_DOC], "answer_must_contain": ["结论"]})

    assert judge_turn(turn, "结论", [{"title": f"{VPN_DOC}（片段）"}]) == []
    assert judge_turn(turn, "结论", [{"heading": f"{VPN_DOC} §1"}]) == []
    assert judge_turn(turn, "结论", []) == [f"引用未命中: ['{VPN_DOC}']"]


def test_judge_turn_flags_refusal_that_answers_with_citations() -> None:
    turn = TurnSpec("那报销怎么走", {"must_refuse": True})

    assert judge_turn(turn, REFUSAL, []) == []
    failures = judge_turn(turn, "按保修规定…", [{"title": "电脑保修与换新政策"}])
    assert len(failures) == 2
    assert "没有拒答" in failures[0]
    assert "不应带引用" in failures[1]


def test_judge_isolation_detects_fake_pass() -> None:
    turn = TurnSpec("那怎么办", {"must_cite_docs": [VPN_DOC]})

    assert judge_isolation(turn, [{"title": "IT 工单流程与优先级说明"}]) == []
    failures = judge_isolation(turn, [{"title": VPN_DOC}])

    assert failures and "隔离对照不成立" in failures[0]


def test_judge_turn_flags_the_previous_topic_document() -> None:
    """话题切换用例：把上一轮话题的文档带进引用，等于没切换过去。"""
    turn = TurnSpec(
        "那报销怎么走",
        {"must_cite_docs": ["差旅报销流程"], "must_not_cite_docs": ["电脑保修"]},
    )

    assert judge_turn(turn, "按报销流程…", [{"title": "差旅报销流程"}]) == []
    failures = judge_turn(
        turn,
        "按报销流程…",
        [{"title": "差旅报销流程"}, {"title": "电脑保修与换新政策"}],
    )

    assert failures == ["引用了上一轮话题: ['电脑保修']"]


def test_judge_shift_isolation_requires_the_new_topic_to_hit_on_its_own() -> None:
    """shift 的前提：单句提问必须自己就能命中，否则它其实是追问。"""
    turn = TurnSpec(
        "那报销怎么走",
        {"must_cite_docs": ["差旅报销流程"], "must_not_cite_docs": ["电脑保修"]},
    )

    assert judge_shift_isolation(turn, [{"title": "差旅报销流程"}]) == []
    failures = judge_shift_isolation(turn, [{"title": "电脑保修与换新政策"}])

    assert failures and "前提不成立" in failures[0]


async def test_run_case_switches_topic_without_leaking_the_old_one() -> None:
    case = MultiTurnCase(
        id="shift",
        kind="shift",
        turns=[
            TurnSpec("公司笔记本整机保修几年", {"must_cite_docs": ["电脑保修与换新政策"]}),
            TurnSpec(
                "那报销怎么走",
                {"must_cite_docs": ["差旅报销流程"], "must_not_cite_docs": ["电脑保修"]},
            ),
        ],
    )

    outcome = await run_case(case, _deps())

    assert outcome.passed, outcome.setup_failures + outcome.judged.failures
    assert outcome.isolation_holds is True
    titles = [str(citation.get("title") or "") for citation in outcome.judged.citations]
    assert titles and all("电脑保修" not in title for title in titles)


async def test_run_case_flags_shift_case_that_is_actually_a_follow_up() -> None:
    """把追问标成"新话题"会让指标虚高，隔离对照的反向检查要拦住它。"""
    case = MultiTurnCase(
        id="mistyped",
        kind="shift",
        turns=[
            TurnSpec("VPN 客户端在哪里下载", {"must_cite_docs": [VPN_DOC]}),
            TurnSpec(
                "那接下来要做什么",
                {"must_cite_docs": [VPN_DOC], "must_not_cite_docs": ["打印机离线排查指南"]},
            ),
        ],
    )

    outcome = await run_case(case, _deps())

    assert not outcome.passed
    assert any("前提不成立" in failure for failure in outcome.judged.isolation_failures)


async def test_run_case_uses_history_and_isolates_the_follow_up() -> None:
    outcome = await run_case(_case("probe", "那接下来要做什么"), _deps())

    assert outcome.passed, outcome.setup_failures + outcome.judged.failures
    assert outcome.judged.isolation_citations is not None
    assert all(
        VPN_DOC not in str(citation.get("title") or "")
        for citation in outcome.judged.isolation_citations
    )


async def test_run_case_fails_when_the_follow_up_answers_on_its_own() -> None:
    """单独提问就能命中时不算指代解对——否则「多轮有效」无法证伪。"""
    outcome = await run_case(_case("fake", "那 VPN 客户端在哪里下载"), _deps())

    assert not outcome.passed
    assert any("隔离对照不成立" in failure for failure in outcome.judged.failures)
    assert outcome.judged.isolation_failures
    assert outcome.isolation_holds is False


async def test_run_case_flags_unfinished_isolation_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空回答说明隔离 run 没跑完：不能因为"没命中"就当成对照成立。"""
    calls = {"count": 0}

    async def fake_run_turn(query: str, **_: object) -> tuple[str, list[dict[str, object]]]:
        calls["count"] += 1
        if calls["count"] == 3:  # 第 3 次是隔离对照
            return "", []
        return "答", [{"title": VPN_DOC}]

    monkeypatch.setattr(multiturn_module, "_run_turn", fake_run_turn)
    outcome = await run_case(_case("probe", "那接下来要做什么"), _deps())

    assert not outcome.passed
    assert any("隔离对照未完成" in failure for failure in outcome.judged.isolation_failures)


async def test_history_is_what_makes_the_follow_up_resolve() -> None:
    """同一句追问：带历史命中 VPN，空会话不命中（隔离对照的底层事实）。"""
    deps = _deps()
    identity = Identity(user_id="u_102", roles=frozenset({"employee"}))
    history = [HistoryTurn("VPN 客户端在哪里下载", "从内网软件库下载。")]

    async def citations(history_turns: list[HistoryTurn]) -> list[dict[str, object]]:
        found: list[dict[str, object]] = []
        async for event_type, payload in stream(
            run_id="00000000-0000-0000-0000-000000000001",
            identity=identity,
            query="那接下来要做什么",
            model="rule-engine",
            deps=deps,
            history=history_turns,
        ):
            if event_type is EventType.MESSAGE_COMPLETED:
                found = list(payload.get("citations") or [])
        return found

    with_history = await citations(history)
    without_history = await citations([])

    assert any(VPN_DOC in str(citation.get("title") or "") for citation in with_history)
    assert not any(VPN_DOC in str(citation.get("title") or "") for citation in without_history)


def test_report_keeps_coref_and_shift_metrics_apart() -> None:
    coref = MultiTurnCase(
        id="coref",
        turns=[
            TurnSpec("首轮", {"must_cite_docs": [VPN_DOC]}),
            TurnSpec("那接下来要做什么", {"must_cite_docs": [VPN_DOC]}),
        ],
    )
    shift = MultiTurnCase(
        id="shift",
        kind="shift",
        turns=[
            TurnSpec("首轮", {"must_cite_docs": [VPN_DOC]}),
            TurnSpec(
                "那报销怎么走",
                {"must_cite_docs": ["差旅报销流程"], "must_not_cite_docs": ["电脑保修"]},
            ),
        ],
    )
    diagnostic = MultiTurnCase(
        id="diag",
        diagnostic=True,
        turns=[
            TurnSpec("首轮", {"must_cite_docs": [VPN_DOC]}),
            TurnSpec("那公司年会抽奖怎么规定", {"must_refuse": True}),
        ],
    )
    report = evaluate(
        [
            _outcome(coref, citations=[{"title": VPN_DOC}]),
            _outcome(shift, citations=[{"title": "差旅报销流程"}]),
            _outcome(
                diagnostic,
                citations=[{"title": "电脑保修与换新政策"}],
                failures=["没有拒答：被上一轮话题带偏了"],
            ),
        ]
    )

    assert report.coref_acc == 1.0
    assert report.shift_acc == 1.0
    assert report.diagnostic_ok == 0
    markdown = render_report(report, cases_path=Path("cases.yaml"))
    assert "**100.00%**（1/1）" in markdown
    assert f"`coref_acc` ≥ {CORE_ACC_FLOOR:.0%}" in markdown
    assert f"`shift_acc` ≥ {SHIFT_ACC_FLOOR:.0%}" in markdown
    assert "| coref | 指代 |" in markdown
    assert "| shift | 切换 |" in markdown
    assert "| diag | 诊断 |" in markdown
    assert "被上一轮话题带偏了" in markdown


async def test_baseline_meets_both_floors_and_both_controls() -> None:
    report = await run_eval()

    assert len(report.coref_cases) == 12
    assert report.coref_acc == 1.0
    assert report.isolation_ok == report.isolation_total == 12
    assert len(report.shift_cases) == 4
    assert report.shift_acc == 1.0
    assert report.shift_premise_ok == report.shift_premise_total == 4
    assert len(report.diagnostic_cases) == 1
    # 拒答类没有"必须命中的文档"，不该白跑一次隔离对照
    assert report.diagnostic_cases[0].judged.isolation_citations is None


def test_main_writes_markdown_and_json(tmp_path: Path) -> None:
    exit_code = main(["--report-dir", str(tmp_path)])

    assert exit_code == 0
    reports = sorted(tmp_path.glob("multiturn-*.md"))
    assert len(reports) == 1
    assert "多轮评测（ADR-0024 / ADR-0025）" in reports[0].read_text(encoding="utf-8")
    assert sorted(tmp_path.glob("multiturn-*.json"))
