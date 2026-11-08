"""运行态内存存储 —— 临时实现。

W1 D4 会替换为 PostgreSQL（runs + run_events）。之所以先做内存版：
先把"事件先落库再推送 + after_seq 补拉"的语义跑通，再换存储，避免
一开始就被 ORM 细节拖住。

⚠️ 进程重启即丢数据，禁止用于演示之后的环境。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from app.schemas.event import EventType, RunEvent


@dataclass
class RunRecord:
    run_id: str
    user_id: str
    session_id: str
    status: str = "running"
    events: list[RunEvent] = field(default_factory=list)
    _seq: int = 0

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq


class InMemoryRunStore:
    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._client_index: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def create(
        self, *, run_id: str, user_id: str, session_id: str, client_msg_id: str | None = None
    ) -> RunRecord:
        async with self._lock:
            # 幂等：同一个 client_msg_id 返回同一个 run
            if client_msg_id and client_msg_id in self._client_index:
                return self._runs[self._client_index[client_msg_id]]
            rec = RunRecord(run_id=run_id, user_id=user_id, session_id=session_id)
            self._runs[run_id] = rec
            if client_msg_id:
                self._client_index[client_msg_id] = run_id
            return rec

    def get(self, run_id: str) -> RunRecord | None:
        return self._runs.get(run_id)

    async def append(self, run_id: str, event: RunEvent) -> RunEvent:
        """追加事件。先落库、后推送 —— 推送失败不影响数据完整性。"""
        async with self._lock:
            rec = self._runs[run_id]
            rec.events.append(event)
            return event

    def events_after(self, run_id: str, after_seq: int = 0, limit: int = 200) -> list[RunEvent]:
        rec = self._runs.get(run_id)
        if rec is None:
            return []
        return [e for e in rec.events if e.seq > after_seq][:limit]


store = InMemoryRunStore()
