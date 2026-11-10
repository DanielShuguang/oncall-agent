"""多轮上下文：预算、追问判定与上下文查询（ADR-0020）。

这些是纯函数，不需要知识库或数据库；"历史从哪来"由 store 契约测试覆盖，
"历史有没有真的进检索"由 test_chat_stream 的端到端用例覆盖。
"""

from __future__ import annotations

from app.agent.history import (
    CONTEXT_QUERY_CHARS,
    MAX_ANSWER_CHARS,
    MAX_TURNS,
    HistoryTurn,
    build_messages,
    contextual_query,
    last_user_query,
    needs_context,
    topic_head,
)


def _messages(pairs: list[tuple[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for query, answer in pairs:
        out.append({"role": "user", "content": query})
        out.append({"role": "assistant", "content": answer})
    return out


def test_build_messages_pairs_are_in_chronological_order() -> None:
    turns = [HistoryTurn("第一问", "第一答"), HistoryTurn("第二问", "第二答")]

    messages = build_messages(turns)

    assert messages == _messages([("第一问", "第一答"), ("第二问", "第二答")])


def test_build_messages_keeps_only_latest_turns() -> None:
    turns = [HistoryTurn(f"问题{index}", f"回答{index}") for index in range(MAX_TURNS + 2)]

    messages = build_messages(turns)

    assert len(messages) == MAX_TURNS * 2
    assert messages[0]["content"] == f"问题{2}"
    assert messages[-2]["content"] == f"问题{MAX_TURNS + 1}"


def test_build_messages_truncates_long_answers() -> None:
    messages = build_messages([HistoryTurn("问", "长" * (MAX_ANSWER_CHARS + 50))])

    answer = messages[1]["content"]
    assert len(answer) == MAX_ANSWER_CHARS + 1  # 截断符占 1 个字
    assert answer.endswith("…")


def test_build_messages_drops_oldest_turn_when_over_budget() -> None:
    # 每轮回答都顶到上限：3 轮装不下（1803 > 1200），应该丢最早的
    turns = [HistoryTurn(f"问{index}", "答" * MAX_ANSWER_CHARS) for index in range(3)]

    messages = build_messages(turns)

    contents = {message["content"] for message in messages}
    assert "问0" not in contents
    assert messages[-2]["content"] == "问2"


def test_build_messages_skips_turns_without_answer() -> None:
    messages = build_messages([HistoryTurn("没有回答的问题", ""), HistoryTurn("有回答", "答")])

    assert messages == _messages([("有回答", "答")])


def test_last_user_query_returns_most_recent_question() -> None:
    messages = [
        {"role": "user", "content": "第一问"},
        {"role": "assistant", "content": "第一答"},
        {"role": "user", "content": "第二问"},
        {"role": "assistant", "content": "第二答"},
    ]

    assert last_user_query(messages) == "第二问"


def test_needs_context_recognises_follow_ups() -> None:
    for query in (
        "那怎么办？",
        "那手机端呢",
        "再试一次",
        "它需要审批吗",
        "刚才那个报错",
        "这个怎么申请",
    ):
        assert needs_context(query) is True, query


def test_needs_context_ignores_standalone_questions() -> None:
    for query in ("VPN 连不上怎么办", "打印机离线", "公司电脑保修几年", "怎么申请 VPN 权限"):
        assert needs_context(query) is False, query


def test_needs_context_treats_long_questions_as_standalone() -> None:
    long_query = "我电脑连不上打印机了，刚才重启过还是脱机状态，麻烦帮我看看是不是驱动"

    assert len(long_query) > 30
    assert needs_context(long_query) is False


def test_contextual_query_merges_previous_question_for_follow_up() -> None:
    messages = _messages([("VPN 连不上怎么办", "先检查网络，再换节点。")])

    assert contextual_query("那怎么办？", messages) == "VPN 连不上怎么办 那怎么办？"


def test_contextual_query_keeps_standalone_question_unchanged() -> None:
    messages = _messages([("VPN 连不上怎么办", "先检查网络，再换节点。")])

    assert contextual_query("打印机离线怎么排查", messages) == "打印机离线怎么排查"


def test_contextual_query_without_history_is_passthrough() -> None:
    assert contextual_query("那怎么办？", []) == "那怎么办？"


def test_contextual_query_truncates_previous_question() -> None:
    previous = "问" * (CONTEXT_QUERY_CHARS + 20)
    messages = _messages([(previous, "答")])

    merged = contextual_query("那呢", messages)

    assert merged.startswith("问" * CONTEXT_QUERY_CHARS + "…")
    assert merged.endswith("那呢")


def test_contextual_query_keeps_the_topic_across_consecutive_follow_ups() -> None:
    """连续追问时只拼上一句会失忆：第三句里已经没有 VPN 了（ADR-0024）。"""
    messages = _messages(
        [
            ("VPN 客户端在哪里下载", "从内网软件库下载。"),
            ("那装完还要做什么", "重启电脑并重新导入配置。"),
        ]
    )

    merged = contextual_query("那还要注意什么", messages)

    assert merged == "VPN 客户端在哪里下载 那装完还要做什么 那还要注意什么"


def test_contextual_query_does_not_merge_assistant_answers() -> None:
    messages = _messages([("VPN 客户端在哪里下载", "从内网软件库下载 VPN 客户端")])

    merged = contextual_query("那怎么办", messages)

    assert merged == "VPN 客户端在哪里下载 那怎么办"


def test_contextual_query_budget_keeps_the_most_recent_question() -> None:
    """预算不足时丢更早的轮次，但最近一句必须完整（它决定指代指向）。"""
    messages = _messages(
        [
            ("问" * (CONTEXT_QUERY_CHARS + 20), "答"),
            ("最近一问", "答"),
        ]
    )

    merged = contextual_query("那呢", messages)

    assert merged == "最近一问 那呢"


def test_topic_head_keeps_the_topic_before_the_question_word() -> None:
    assert topic_head("那报销怎么走") == "那报销"
    assert topic_head("那会议室怎么订") == "那会议室"
    assert topic_head("那蓝屏呢") == "那蓝屏"
    assert topic_head("那 VPN 呢") == "那 VPN"


def test_topic_head_is_empty_for_generic_follow_ups() -> None:
    """「处理」「申请」是问法里的谓语，不是话题：不能拿它去点《…处理》《…申请》。"""
    assert topic_head("那怎么处理") == "那"
    assert topic_head("那怎么申请") == "那"
    assert topic_head("那到底要怎么办") == "那到底要"
