"""本地运维命令行（不经过 HTTP）。

v1 不接 SSO（ADR-0010）：给用户签发短期 token 由运维离线完成。

    cd server
    uv run python -m app.cli token --user u_102 --roles employee
    uv run python -m app.cli reap --dry-run
    uv run python -m app.cli prune --dry-run

`reap` 回收进程中断后停在 `running` 的 run（ADR-0017）：只追加
`run.failed(RUN_INTERRUPTED)` 收敛状态，不会自动重放写工具。
`prune` 执行保留策略（ADR-0021 / ADR-0023）：整场删除过期 run 的事件、
清空过期 run 的正文（`input/output`）、按时间删除过期的模型计量行；
先 `--dry-run` 看候选。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.core.config import get_settings
from app.core.db import dispose as dispose_db
from app.core.security import DEFAULT_TTL_MINUTES, create_token
from app.core.store import build_store
from app.gateway.meter import build_model_call_store
from app.runs.recovery import RunRecovery
from app.runs.retention import RetentionSweeper


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oncall", description="OnCall 运维命令")
    sub = parser.add_subparsers(dest="command", required=True)

    token = sub.add_parser("token", help="签发本地 JWT")
    token.add_argument("--user", required=True, help="用户 ID，写入 token 的 sub")
    token.add_argument("--roles", default="employee", help="逗号分隔，如 employee,it_support")
    token.add_argument(
        "--ttl-minutes",
        type=int,
        default=DEFAULT_TTL_MINUTES,
        help=f"有效期（分钟），默认 {DEFAULT_TTL_MINUTES}",
    )

    reap = sub.add_parser("reap", help="回收进程中断的 run（只收敛状态，不重放写操作）")
    reap.add_argument("--dry-run", action="store_true", help="只列候选，不写事件")
    reap.add_argument("--limit", type=int, default=100, help="单次最多处理多少个 run")
    reap.add_argument(
        "--older-than-min",
        type=int,
        default=None,
        help="覆盖 ONCALL_STALE_RUN_MIN（分钟）；必须 >= 1",
    )
    prune = sub.add_parser("prune", help="清理超过保留期的事件、run 正文与模型计量")
    prune.add_argument("--dry-run", action="store_true", help="只列候选，不删除")
    prune.add_argument(
        "--limit",
        type=int,
        default=None,
        help="单批上限，覆盖 ONCALL_RETENTION_BATCH",
    )
    return parser


async def _reap(args: argparse.Namespace) -> int:
    if args.limit < 1:
        print("--limit 必须 >= 1", file=sys.stderr)
        return 2
    if args.older_than_min is not None and args.older_than_min < 1:
        print("--older-than-min 必须 >= 1", file=sys.stderr)
        return 2

    settings = get_settings()
    if args.older_than_min is not None:
        # model_copy 不重新跑校验器；上面已经检查过下限
        settings = settings.model_copy(update={"stale_run_min": int(args.older_than_min)})

    recovery = RunRecovery(build_store(settings), settings=settings)
    try:
        result = await recovery.reap(limit=int(args.limit), dry_run=bool(args.dry_run))
    finally:
        # 一次性命令：显式释放连接池，避免解释器退出时留下未关闭的 asyncpg 连接
        if settings.store_backend == "postgres":
            await dispose_db()
    print(
        json.dumps(
            {
                "store": settings.store_backend,
                "older_than": result.older_than.isoformat(),
                "scanned": result.scanned,
                "reaped": result.reaped,
                "dry_run": result.dry_run,
            },
            ensure_ascii=False,
        )
    )
    return 0


async def _prune(args: argparse.Namespace) -> int:
    if args.limit is not None and args.limit < 1:
        print("--limit 必须 >= 1", file=sys.stderr)
        return 2

    settings = get_settings()
    sweeper = RetentionSweeper(
        build_store(settings),
        build_model_call_store(settings),
        settings=settings,
    )
    try:
        result = await sweeper.sweep(limit=args.limit, dry_run=bool(args.dry_run))
    finally:
        # 一次性命令：显式释放连接池，避免解释器退出时留下未关闭的 asyncpg 连接
        if settings.store_backend == "postgres":
            await dispose_db()
    print(
        json.dumps(
            {
                "store": settings.store_backend,
                "events_before": result.events_before.isoformat(),
                "calls_before": result.calls_before.isoformat(),
                "content_before": result.content_before.isoformat(),
                "runs": len(result.run_ids),
                "events": result.events,
                "calls": result.calls,
                "content_runs": len(result.content_run_ids),
                "batch": result.batch,
                "capped": result.capped,
                "dry_run": result.dry_run,
            },
            ensure_ascii=False,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "token":
        roles = [role.strip() for role in str(args.roles).split(",") if role.strip()]
        print(
            create_token(
                user_id=str(args.user),
                roles=roles,
                secret=get_settings().session_secret,
                ttl_minutes=int(args.ttl_minutes),
            )
        )
        return 0
    if args.command == "reap":
        return asyncio.run(_reap(args))
    if args.command == "prune":
        return asyncio.run(_prune(args))
    return 2  # pragma: no cover - argparse 已保证 command 合法


if __name__ == "__main__":
    raise SystemExit(main())
