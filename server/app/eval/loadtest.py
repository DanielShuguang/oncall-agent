"""并发压测（W6 D27）：对 `/api/chat/stream` 打完整 SSE run，输出 markdown 报告。

口径：
- 每个请求 = 一次完整对话 run（建 run → 8 节点 → 落库 → SSE 收尾）
- 成功只认 `run.completed`；`run.failed`、HTTP 非 200、流提前结束都算失败
- 首事件延迟从发请求到收到第一帧 SSE，端到端延迟到 `run.completed`
- 默认用多用户 token 规避单用户 30 次/分钟限流；`--token` 单用户只适合小流量

用法：
    cd server
    uv run python -m app.eval.loadtest --requests 100 --concurrency 20 --users 20

    # 远端环境
    uv run python -m app.eval.loadtest --base-url http://10.0.0.8:8000 --token "$TOKEN"

本机开发机数字只能说明「脚本能跑、链路没堵」，不能当成 8C16G 生产容量结论。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.security import create_token
from app.eval.runner import REPORTS_DIR

DEFAULT_QUERIES = (
    "VPN 连不上怎么办",
    "密码多少天需要更换一次",
    "邮件附件最大可以发多大",
)
TERMINAL_EVENTS = {"run.completed", "run.failed"}


@dataclass(slots=True)
class Sample:
    ok: bool
    status: int
    first_event_ms: int | None
    total_ms: int
    events: int
    error: str = ""


@dataclass(slots=True)
class LoadResult:
    samples: list[Sample] = field(default_factory=list)
    wall_s: float = 0.0
    health: dict[str, Any] = field(default_factory=dict)

    @property
    def ok_count(self) -> int:
        return sum(1 for sample in self.samples if sample.ok)


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return int(ordered[index])


def _summary(result: LoadResult) -> dict[str, Any]:
    samples = result.samples
    total = len(samples)
    ok = result.ok_count
    failures: dict[str, int] = {}
    for sample in samples:
        if not sample.ok:
            key = sample.error or f"HTTP {sample.status}"
            failures[key] = failures.get(key, 0) + 1
    totals = [sample.total_ms for sample in samples]
    firsts = [sample.first_event_ms for sample in samples if sample.first_event_ms is not None]
    events = sum(sample.events for sample in samples)
    return {
        "requests": total,
        "ok": ok,
        "failed": total - ok,
        "success_rate": round(ok / total, 4) if total else 0.0,
        "concurrency": 0,
        "wall_s": round(result.wall_s, 2),
        "rps": round(total / result.wall_s, 2) if result.wall_s > 0 else 0.0,
        "p50_ms": _percentile(totals, 0.5),
        "p95_ms": _percentile(totals, 0.95),
        "p99_ms": _percentile(totals, 0.99),
        "first_event_p95_ms": _percentile(firsts, 0.95),
        "avg_events": round(statistics.fmean([sample.events for sample in samples]), 1)
        if samples
        else 0.0,
        "events_per_s": round(events / result.wall_s, 1) if result.wall_s > 0 else 0.0,
        "failures": failures,
        "health": result.health,
    }


async def _one(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    token: str,
    query: str,
    index: int,
) -> Sample:
    started = time.perf_counter()
    headers = {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}
    payload = {
        "session_id": f"load-{index % 20}-{uuid.uuid4().hex[:8]}",
        "client_msg_id": f"load_{uuid.uuid4().hex}",
        "message": query,
    }
    first_event_ms: int | None = None
    events = 0
    terminal: str | None = None
    failure = ""
    status = 0
    try:
        async with client.stream(
            "POST", f"{base_url}/api/chat/stream", json=payload, headers=headers
        ) as response:
            status = response.status_code
            if status != 200:
                body = (await response.aread()).decode("utf-8", "replace")[:200]
                return Sample(
                    False,
                    status,
                    None,
                    int((time.perf_counter() - started) * 1000),
                    0,
                    f"HTTP {status}: {body}",
                )
            event_type = ""
            async for line in response.aiter_lines():
                if line.startswith("id:") and first_event_ms is None:
                    first_event_ms = int((time.perf_counter() - started) * 1000)
                elif line.startswith("event:"):
                    event_type = line.split(":", 1)[1].strip()
                elif line == "":
                    if event_type:
                        events += 1
                        if event_type in TERMINAL_EVENTS:
                            terminal = event_type
                            break
                        if event_type == "approval.required":
                            failure = "写操作挂起等审批（压测用例不应触发）"
                    event_type = ""
    except httpx.HTTPError as exc:
        failure = f"transport: {type(exc).__name__}"
    total_ms = int((time.perf_counter() - started) * 1000)
    if terminal == "run.failed":
        failure = "run.failed"
    elif terminal is None and not failure:
        failure = "stream ended without terminal event"
    return Sample(not failure, status, first_event_ms, total_ms, events, failure)


async def _health(client: httpx.AsyncClient, base_url: str) -> dict[str, Any]:
    try:
        response = await client.get(f"{base_url}/api/health", timeout=5.0)
        if response.status_code == 200:
            payload = response.json()
            return payload if isinstance(payload, dict) else {}
    except httpx.HTTPError:
        pass
    return {}


async def run_load(
    *,
    base_url: str,
    requests: int,
    concurrency: int,
    users: int,
    token: str | None,
    queries: tuple[str, ...],
    warmup: int,
) -> LoadResult:
    settings = get_settings()
    base_url = base_url.rstrip("/")
    tokens = (
        [token]
        if token
        else [
            create_token(
                user_id=f"u_{500 + index:03d}",
                roles=["employee"],
                secret=settings.session_secret,
                ttl_minutes=60,
            )
            for index in range(max(1, users))
        ]
    )
    limits = httpx.Limits(max_connections=concurrency + 5, max_keepalive_connections=concurrency)
    timeout = httpx.Timeout(30.0, connect=5.0)
    semaphore = asyncio.Semaphore(max(1, concurrency))
    counter = {"next": 0}

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        health = await _health(client, base_url)

        async def worker() -> Sample:
            async with semaphore:
                index = counter["next"]
                counter["next"] += 1
                return await _one(
                    client,
                    base_url=base_url,
                    token=tokens[index % len(tokens)],
                    query=queries[index % len(queries)],
                    index=index,
                )

        if warmup > 0:
            await asyncio.gather(*(worker() for _ in range(warmup)))
            counter["next"] = 0

        started = time.perf_counter()
        samples = await asyncio.gather(*(worker() for _ in range(requests)))
        wall_s = time.perf_counter() - started
        return LoadResult(samples=list(samples), wall_s=wall_s, health=health)


def render_report(batch: str, summary: dict[str, Any], result: LoadResult) -> str:
    health = summary.get("health") or {}
    failures: dict[str, int] = summary.get("failures") or {}
    lines = [
        f"# Load Test · {batch}",
        "",
        f"- 并发: {summary.get('concurrency', 0)}",
        f"- 请求数: {summary['requests']}（成功 {summary['ok']} / 失败 {summary['failed']}）",
        f"- 健康检查: status={health.get('status', 'unknown')} | "
        f"mock_mode={health.get('mock_mode', 'unknown')} | "
        f"db={health.get('checks', {}).get('db', '?')} | "
        f"redis={health.get('checks', {}).get('redis', '?')}",
        "",
        "## 结果",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 成功率 | {summary['success_rate']:.2%} |",
        f"| 总耗时 | {summary['wall_s']}s |",
        f"| 吞吐（run/s） | {summary['rps']} |",
        f"| 事件吞吐（条/s） | {summary['events_per_s']} |",
        f"| p50 端到端 | {summary['p50_ms']}ms |",
        f"| p95 端到端 | {summary['p95_ms']}ms |",
        f"| p99 端到端 | {summary['p99_ms']}ms |",
        f"| p95 首事件 | {summary['first_event_p95_ms']}ms |",
        f"| 平均事件数 | {summary['avg_events']} |",
        "",
        "## 失败",
        "",
    ]
    if failures:
        lines += ["| 原因 | 次数 |", "|---|---|"]
        for reason, count in sorted(failures.items(), key=lambda item: -item[1]):
            lines.append(f"| {reason.replace('|', '\\|')} | {count} |")
    else:
        lines.append("无。")
    lines += [
        "",
        "## 口径",
        "",
        "- 每个请求是一次完整 SSE run：建 run、8 节点、事件落库、收尾；成功只认 `run.completed`。",
        "- 首事件延迟从发请求到第一帧 SSE；端到端到 `run.completed`。",
        "- 默认多用户 token 规避单用户限流；`--token` 单用户高并发会被 429，属于预期。",
        "- 本报告是当前机器的结果，不是 8C16G 生产容量承诺；"
        "生产验收需在同规格机器上重跑并记录 Postgres/Redis 资源。",
        "",
    ]
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OnCall SSE 对话压测")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--token", default=None, help="复用单个 token；不传则按 --users 本地签发")
    parser.add_argument("--query", action="append", default=None, help="可重复；默认三条知识问题")
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--out", type=Path, default=REPORTS_DIR)
    return parser


async def _main(args: argparse.Namespace) -> int:
    queries = tuple(args.query) if args.query else DEFAULT_QUERIES
    result = await run_load(
        base_url=args.base_url,
        requests=args.requests,
        concurrency=args.concurrency,
        users=args.users,
        token=args.token,
        queries=queries,
        warmup=args.warmup,
    )
    summary = _summary(result)
    summary["concurrency"] = args.concurrency
    summary["queries"] = list(queries)
    summary["base_url"] = args.base_url
    batch = datetime.now(UTC).strftime("load-%Y%m%d-%H%M%S")
    args.out.mkdir(parents=True, exist_ok=True)
    report = render_report(batch, summary, result)
    (args.out / f"{batch}.md").write_text(report, encoding="utf-8")
    (args.out / f"{batch}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(report)
    print(f"\n报告已写入: {args.out / f'{batch}.md'}")
    return 0 if summary["success_rate"] >= 0.95 else 1


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_main(_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
