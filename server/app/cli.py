"""本地运维命令行（不经过 HTTP）。

v1 不接 SSO（ADR-0010）：给用户签发短期 token 由运维离线完成。

    cd server
    uv run python -m app.cli token --user u_102 --roles employee
"""

from __future__ import annotations

import argparse

from app.core.config import get_settings
from app.core.security import DEFAULT_TTL_MINUTES, create_token


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
    return parser


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
    return 2  # pragma: no cover - argparse 已保证 command 合法


if __name__ == "__main__":
    raise SystemExit(main())
