"""三条演示剧本（W6 D28）：无模型 key 的 mock 模式也能完整跑通。

用法：
    # 本地已启动 api（make api）
    uv run python -m app.eval.demo

    # 容器化环境
    uv run python -m app.eval.demo --base-url http://127.0.0.1:8000

    # 远端：显式带 token（请求人 + 审批人，审批人不能是请求人）
    uv run python -m app.eval.demo --token "$USER_TOKEN" --approver-token "$APPROVER_TOKEN"

覆盖：
1. 知识问答（无工具）
2. 查资产 + 保修政策（query_cmdb）
3. 申请装软件 → 审批中心批准 → 工单落库

脚本会真实调用 API、真实写库；不要在演示库之外跑第三条。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.security import create_token

SCENARIOS = (
    ("知识问答", "VPN 连不上怎么办"),
    ("查资产 + 保修政策", "我的笔记本蓝屏了，还在保修期吗"),
    ("申请装软件（写操作，需审批）", "帮我申请安装设计软件"),
)


def _token(user: str, roles: list[str]) -> str:
    return create_token(
        user_id=user,
        roles=roles,
        secret=get_settings().session_secret,
        ttl_minutes=60,
    )


async def _stream(
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    message: str,
) -> tuple[str, list[tuple[str, dict[str, Any]]]]:
    payload = {
        "session_id": f"demo-{uuid.uuid4().hex[:8]}",
        "client_msg_id": f"demo_{uuid.uuid4().hex}",
        "message": message,
    }
    run_id = ""
    events: list[tuple[str, dict[str, Any]]] = []
    async with client.stream(
        "POST",
        f"{base_url}/api/chat/stream",
        json=payload,
        headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
    ) as response:
        if response.status_code != 200:
            body = (await response.aread()).decode("utf-8", "replace")
            raise SystemExit(f"请求失败 HTTP {response.status_code}: {body[:300]}")
        event_type = ""
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                event_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                try:
                    raw = json.loads(line.split(":", 1)[1].strip())
                except json.JSONDecodeError:
                    continue
                if isinstance(raw, dict) and raw.get("run_id"):
                    run_id = str(raw["run_id"])
                events.append((event_type, raw if isinstance(raw, dict) else {}))
                if event_type in {"run.completed", "run.failed", "approval.required"}:
                    return run_id, events
    return run_id, events


def _print_events(events: list[tuple[str, dict[str, Any]]]) -> None:
    for event_type, event in events:
        payload = event.get("payload") or {}
        if event_type == "step.started":
            print(f"  · {payload.get('title', payload.get('node', ''))}")
        elif event_type == "tool.call":
            print(f"  → 调用工具 {payload.get('tool')} args={payload.get('args')}")
        elif event_type == "tool.result":
            status = payload.get("status")
            print(f"  ← 工具结果 {payload.get('tool')} status={status}")
        elif event_type == "message.completed":
            text = str(payload.get("text") or "").strip()
            print(f"\n  回答：{text[:500]}")
            citations = payload.get("citations") or []
            for index, citation in enumerate(citations, start=1):
                title = citation.get("title", "")
                heading = citation.get("heading") or ""
                print(f"    [{index}] {title} · {heading}")
        elif event_type == "run.failed":
            print(f"  ✗ run.failed: {payload.get('message') or payload.get('error')}")


async def _wait_run(
    client: httpx.AsyncClient, base_url: str, token: str, run_id: str
) -> dict[str, Any]:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        response = await client.get(
            f"{base_url}/api/runs/{run_id}", headers={"Authorization": f"Bearer {token}"}
        )
        if response.status_code == 200:
            data = response.json()
            if data.get("status") in {"completed", "failed", "interrupted"}:
                return data
        await asyncio.sleep(0.3)
    return {}


async def run_demo(
    *,
    base_url: str,
    user_token: str,
    approver_token: str | None,
) -> int:
    base_url = base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
        health = await client.get(f"{base_url}/api/health")
        if health.status_code != 200:
            print(f"API 不可用：HTTP {health.status_code}，先执行 `make api` 或 `make stack`")
            return 1
        info = health.json()
        print(f"API {base_url} | status={info.get('status')} | mock_mode={info.get('mock_mode')}")
        if not info.get("mock_mode"):
            print("提示：当前不是 mock 模式，演示会真实调用模型并产生费用。")

        for index, (name, question) in enumerate(SCENARIOS, start=1):
            print(f"\n=== 剧本 {index}：{name} ===")
            print(f"用户：{question}")
            run_id, events = await _stream(client, base_url, user_token, question)
            _print_events(events)

            approval = next(
                (
                    event.get("payload") or {}
                    for event_type, event in events
                    if event_type == "approval.required"
                ),
                None,
            )
            if approval is None:
                continue

            approval_id = approval.get("approval_id")
            print(
                f"\n  写操作已挂起：{approval.get('tool')} "
                f"approval_id={approval_id} risk={approval.get('risk_level')}"
            )
            if not approver_token:
                print("  未提供 --approver-token，跳过审批；可在后台审批中心手动处理。")
                continue

            resolved = await client.post(
                f"{base_url}/api/approvals/{approval_id}/resolve",
                json={"decision": "approved", "reason": "演示：审批通过", "scope": "once"},
                headers={"Authorization": f"Bearer {approver_token}"},
            )
            if resolved.status_code != 200:
                print(f"  审批失败 HTTP {resolved.status_code}: {resolved.text[:200]}")
                return 1
            print("  审批人已批准，等待 run 收尾…")
            record = await _wait_run(client, base_url, user_token, run_id)
            print(f"  run 状态：{record.get('status')} | 输出：{record.get('output')}")
        print("\n演示完成。")
        return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OnCall 三条演示剧本")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default=None, help="请求人 token；不传则本地签发 u_102")
    parser.add_argument("--approver-token", default=None, help="审批人 token；不传则跳过审批")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    user_token = args.token or _token("u_102", ["employee"])
    approver_token = args.approver_token
    if approver_token is None and args.token is None:
        # 本地演示默认自动生成审批人；远端环境不要假设密钥一致
        approver_token = _token("u_900", ["approver"])
    return asyncio.run(
        run_demo(
            base_url=args.base_url,
            user_token=user_token,
            approver_token=approver_token,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
