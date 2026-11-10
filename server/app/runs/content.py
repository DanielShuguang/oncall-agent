"""回答内容的按当前可见性回收（ADR-0022）。

回答与事件写进库就不再变（R1/R2），但**读**的时候必须按调用者**当前**的角色
重新校验：回答引用了哪些文档记录在 `runs.cited_document_ids` 上，文档一旦被
改成更窄的可见范围（或删除），旧回答正文就是越权内容。这里只做判定，不改存储——
回收按请求生效：把可见范围改回去，旧回答立刻恢复可见，不需要重算或重建。

覆盖的读取路径：

    GET /runs/{id}          详情里的 `output`
    GET /runs/{id}/events   回放事件（message.completed 里带引用切片原文）
    POST /chat/stream       幂等重放（同一 client_msg_id 命中旧 run）
    recent_turns()          多轮上下文（否则旧回答会经模型"再讲一遍"）

`input` 不回收：那是用户自己敲进来的问题，不是知识库正文。管理端审批载荷
（`approvals.state`）不返回给前端（docs/03 §5），也不在本次范围内。

与**按时间**的正文清理（ADR-0023）正交：`runs.content_pruned_at` 非空表示正文已经
被保留策略清空，此时没有任何内容可回收，`content_is_redacted` 直接返回 False，
也不再查知识库（谁都不该看到的内容，谈不上「按你的权限隐藏」）。

**fail-closed**：查不到的文档按不可见处理。管理员删掉一篇文档后，旧回答里由它
生成的正文同样不该继续展示。代价是重新上传会换 `document_id`，旧引用因此被隐藏；
这是有意的取舍，见 ADR-0022。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.core.store import RunRecord, RunTurn
from app.rag.access import Viewer
from app.rag.retrieve import KnowledgeBase


def _unique_ids(document_ids: Iterable[str]) -> list[str]:
    """去空、去重、保序；非法空串不能进 SQL 的 IN 列表。"""
    return list(dict.fromkeys(item for item in document_ids if item))


async def content_is_visible(
    *,
    cited_document_ids: Sequence[str],
    viewer: Viewer,
    kb: KnowledgeBase,
) -> bool:
    """引用的文档当前是否**全部**可见。

    没有引用时恒为 True：工具类回答、拒答与非知识库内容都没有要回收的正文；
    知识库所有者（admin）也直接放行，否则管理页自己就看不到历史。
    """
    ids = _unique_ids(cited_document_ids)
    if not ids or viewer.unrestricted:
        return True
    visible = await kb.visible_document_ids(ids, viewer=viewer)
    return len(visible) == len(ids)


async def content_is_redacted(record: RunRecord, *, viewer: Viewer, kb: KnowledgeBase) -> bool:
    """`content_is_visible` 的反面；API 用它决定是否隐藏 output 与事件。

    正文已被保留策略清空（ADR-0023）时恒为 False：内容已经不存在了，再按权限
    判定只会让详情页把「过期清理」说成「文档不可见」，也会白跑一次知识库查询。
    """
    if record.content_pruned_at is not None:
        return False
    return not await content_is_visible(
        cited_document_ids=record.cited_document_ids,
        viewer=viewer,
        kb=kb,
    )


async def filter_visible_turns(
    turns: Iterable[RunTurn], *, viewer: Viewer, kb: KnowledgeBase
) -> list[RunTurn]:
    """多轮历史里剔除「引用了当前不可见文档」的轮次。

    跨轮次合并成**一次**批量查询：一轮一次查会让每个追问付 3 倍的数据库往返。
    只剔除整轮，不裁剪回答正文——半句旧回答喂给模型比没有历史更糟。
    """
    items = list(turns)
    ids = _unique_ids(document_id for turn in items for document_id in turn.cited_document_ids)
    if not ids or viewer.unrestricted:
        return items
    visible = await kb.visible_document_ids(ids, viewer=viewer)
    return [
        turn
        for turn in items
        if all(document_id in visible for document_id in _unique_ids(turn.cited_document_ids))
    ]
