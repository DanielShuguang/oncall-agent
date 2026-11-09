"""演示数据生成入口：uv run python -m app.seed.generate [--db] [--reset]

产物（默认 `server/seed_data/`）：
- `kb/*.md`：50 篇知识库文档（含过期版本、冲突说法与无关噪声）
- `assets.json`：200 条资产
- `tickets.json`：500 条工单

`--db` 会额外把资产/工单写入 Postgres 并把知识库索引进 pgvector；
需要先执行 `uv run alembic upgrade head`。不加 `--db` 时只落文件，
便于离线检查语料与在 CI 里做纯内存评测。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from app.core.logging import get_logger
from app.seed.corpus import SeedDocument, build_documents

log = get_logger(__name__)

SERVER_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = SERVER_ROOT / "seed_data"
RANDOM_SEED = 20261108

USERS = [f"u_{index:03d}" for index in range(101, 241)]
LAPTOP_MODELS = (
    "ThinkPad T14",
    "ThinkPad X1 Carbon",
    "MacBook Pro 14",
    "Dell Latitude 5440",
    "HP EliteBook 840",
)
DESKTOP_MODELS = ("Dell OptiPlex 7010", "HP ProDesk 400", "Lenovo M720q")
PRINTER_MODELS = ("HP-1020", "HP M404dn", "Canon LBP-2900", "Epson L3253")
LOCATIONS = ("3F-东区", "3F-西区", "4F-研发", "5F-销售", "6F-会议室")
TICKET_TOPICS = (
    ("VPN 连不上", "network"),
    ("打印机显示离线", "hardware"),
    ("密码过期无法登录", "account"),
    ("申请安装设计软件", "software"),
    ("电脑蓝屏", "hardware"),
    ("邮箱收不到邮件", "software"),
    ("会议室投屏无信号", "hardware"),
    ("WiFi 认证失败", "network"),
    ("申请数据导出权限", "account"),
    ("笔记本电池续航异常", "hardware"),
)


@dataclass(frozen=True, slots=True)
class SeedStats:
    documents: int
    assets: int
    tickets: int
    out_dir: str
    loaded_to_db: bool


def _asset_rows() -> list[dict[str, object]]:
    rng = random.Random(RANDOM_SEED)
    rows: list[dict[str, object]] = []
    first: dict[str, object] = {
        "id": "PC-20481",
        "owner_id": "u_102",
        "type": "laptop",
        "model": "ThinkPad T14",
        "location": "4F-研发",
        "ip": "10.30.4.81",
        "warranty_to": "2027-06-30",
        "status": "online",
    }
    rows.append(first)

    for index in range(2, 201):
        kind = rng.choices(
            ("laptop", "desktop", "printer", "server"), weights=(70, 15, 10, 5), k=1
        )[0]
        models = {
            "laptop": LAPTOP_MODELS,
            "desktop": DESKTOP_MODELS,
            "printer": PRINTER_MODELS,
            "server": ("Dell PowerEdge R650",),
        }[kind]
        warranty = date(2026, 1, 1) + timedelta(days=rng.randint(0, 1200))
        rows.append(
            {
                "id": f"PC-{20000 + index}",
                "owner_id": rng.choice(USERS),
                "type": kind,
                "model": rng.choice(models),
                "location": rng.choice(LOCATIONS),
                "ip": f"10.30.{rng.randint(1, 12)}.{rng.randint(2, 250)}",
                "warranty_to": warranty.isoformat(),
                "status": rng.choices(("online", "offline", "repairing"), weights=(82, 12, 6), k=1)[
                    0
                ],
            }
        )
    return rows


def _ticket_rows(assets: list[dict[str, object]]) -> list[dict[str, object]]:
    rng = random.Random(RANDOM_SEED + 1)
    asset_ids = [str(asset["id"]) for asset in assets]
    base = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    for index in range(1, 501):
        title, category = TICKET_TOPICS[index % len(TICKET_TOPICS)]
        created = base + timedelta(hours=index * 7 + rng.randint(0, 5))
        status = rng.choices(
            ("open", "in_progress", "resolved", "closed"), weights=(12, 10, 48, 30), k=1
        )[0]
        resolved = None
        if status in {"resolved", "closed"}:
            resolved = (created + timedelta(hours=rng.randint(1, 72))).isoformat()
        # 每 37 条制造一次重复报修，模拟真实工单里的噪声
        if index % 37 == 0:
            title = f"{title}（再次报修）"
        rows.append(
            {
                "id": f"TK-2026-{index:04d}",
                "title": title,
                "description": f"用户反馈：{title}。已提供资产编号，等待处理。",
                "category": category,
                "priority": rng.choices(("P1", "P2", "P3"), weights=(3, 57, 40), k=1)[0],
                "status": status,
                "requester": rng.choice(USERS),
                "assignee": rng.choice(("u_901", "u_902", "u_903", "u_904")),
                "asset_id": rng.choice(asset_ids) if rng.random() < 0.7 else None,
                "created_at": created.isoformat(),
                "resolved_at": resolved,
            }
        )
    return rows


def write_files(out_dir: Path, documents: list[SeedDocument]) -> tuple[int, int]:
    kb_dir = out_dir / "kb"
    kb_dir.mkdir(parents=True, exist_ok=True)
    for document in documents:
        (kb_dir / document.filename).write_text(document.text, encoding="utf-8")

    assets = _asset_rows()
    tickets = _ticket_rows(assets)
    (out_dir / "assets.json").write_text(
        json.dumps(assets, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "tickets.json").write_text(
        json.dumps(tickets, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return len(assets), len(tickets)


async def load_to_db(out_dir: Path, *, reset: bool) -> None:
    from sqlalchemy import delete

    from app.core.config import get_settings
    from app.core.db import get_sessionmaker
    from app.models.business import Asset, Ticket
    from app.rag.service import build_knowledge_base

    settings = get_settings()
    if settings.store_backend != "postgres" or settings.rag_backend == "memory":
        raise SystemExit(
            "--db 需要 ONCALL_STORE_BACKEND=postgres 且 ONCALL_RAG_BACKEND 不是 memory；"
            "当前配置无法把 seed 写入 pgvector"
        )

    assets = json.loads((out_dir / "assets.json").read_text(encoding="utf-8"))
    tickets = json.loads((out_dir / "tickets.json").read_text(encoding="utf-8"))
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session, session.begin():
        if reset:
            await session.execute(delete(Ticket))
            await session.execute(delete(Asset))
        for row in assets:
            await session.merge(
                Asset(
                    id=row["id"],
                    owner_id=row["owner_id"],
                    type=row["type"],
                    model=row["model"],
                    location=row["location"],
                    ip=row["ip"],
                    warranty_to=date.fromisoformat(row["warranty_to"]),
                    status=row["status"],
                )
            )
        for row in tickets:
            await session.merge(
                Ticket(
                    id=row["id"],
                    title=row["title"],
                    description=row["description"],
                    category=row["category"],
                    priority=row["priority"],
                    status=row["status"],
                    requester=row["requester"],
                    assignee=row["assignee"],
                    asset_id=row["asset_id"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    resolved_at=(
                        datetime.fromisoformat(row["resolved_at"]) if row["resolved_at"] else None
                    ),
                )
            )

    kb = build_knowledge_base(settings)
    for document in build_documents():
        await kb.index_text(
            title=document.title,
            text=document.text,
            source=f"seed:{document.filename}",
            visibility=document.visibility,
            allowed_roles=document.allowed_roles,
        )
    log.info(
        "seed_loaded",
        assets=len(assets),
        tickets=len(tickets),
        documents=len(build_documents()),
        chunks=await kb.chunk_count(),
    )


async def generate(
    *,
    out_dir: Path = DEFAULT_OUT,
    to_db: bool = False,
    reset: bool = False,
) -> SeedStats:
    documents = build_documents()
    # CLI 的同步文件写入；不涉及请求循环，没必要为它引入线程池
    out_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    assets, tickets = write_files(out_dir, documents)
    if to_db:
        await load_to_db(out_dir, reset=reset)
    return SeedStats(
        documents=len(documents),
        assets=assets,
        tickets=tickets,
        out_dir=str(out_dir),
        loaded_to_db=to_db,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成 OnCall 演示数据")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="输出目录")
    parser.add_argument("--db", action="store_true", help="同时写入 Postgres 并索引知识库")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="写库前清空 assets/tickets（知识库按 source 覆盖，无需清空）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    stats = asyncio.run(generate(out_dir=args.out, to_db=args.db, reset=args.reset))
    print(
        f"生成完成：{stats.documents} 篇文档 / {stats.assets} 台资产 / "
        f"{stats.tickets} 张工单 -> {stats.out_dir}"
        + ("（已写入数据库）" if stats.loaded_to_db else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
