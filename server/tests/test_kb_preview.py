"""引用跳全文接口：可见性、焦点定位、404 与鉴权。

可见性：预览与检索共用同一条规则（ADR-0018 / ADR-0019）。
`public` 文档任何登录员工可读；`roles` 文档要求角色交集，不可见与不存在
都返回 404（403 会泄露「文档存在」）；知识库管理接口仍只属于管理员。
"""

from __future__ import annotations

from httpx import AsyncClient

from tests.support import auth_headers

ADMIN = auth_headers(user_id="admin_1", roles=("admin",))
EMPLOYEE = auth_headers(user_id="u_204", roles=("employee",))
HR = auth_headers(user_id="u_301", roles=("employee", "hr"))

DOC = """# 访客网络说明

## 登记流程

访客由接待人提前一天在访客系统登记，未登记无法入网。

## 连接方式

访客使用手机号验证码登录 OnCall-Guest，连接时限为 8 小时。

## 常见问题

验证码收不到时，先在访客系统确认手机号，再由接待人重新发起。
""".encode()


async def _upload(client: AsyncClient) -> str:
    response = await client.post(
        "/api/admin/kb/documents",
        headers=ADMIN,
        files={"file": ("guest-network.md", DOC, "text/markdown")},
    )
    assert response.status_code == 201
    return str(response.json()["document"]["id"])


async def test_employee_can_preview_document_seen_in_citations(client: AsyncClient) -> None:
    document_id = await _upload(client)

    response = await client.get(f"/api/kb/documents/{document_id}/preview", headers=EMPLOYEE)

    assert response.status_code == 200
    payload = response.json()
    assert payload["document"]["id"] == document_id
    assert payload["document"]["title"] == "访客网络说明"
    assert payload["total_chunks"] == len(payload["chunks"])
    assert payload["truncated"] is False
    assert all(chunk["chunk_id"] > 0 for chunk in payload["chunks"])
    assert any("访客系统登记" in chunk["content"] for chunk in payload["chunks"])


async def test_preview_focuses_cited_chunk_then_falls_back_to_ord(
    client: AsyncClient,
) -> None:
    document_id = await _upload(client)
    base = await client.get(f"/api/kb/documents/{document_id}/preview", headers=EMPLOYEE)
    chunks = base.json()["chunks"]
    assert len(chunks) >= 2
    target = chunks[1]

    by_chunk = await client.get(
        f"/api/kb/documents/{document_id}/preview",
        params={"chunk_id": target["chunk_id"]},
        headers=EMPLOYEE,
    )
    assert by_chunk.status_code == 200
    assert by_chunk.json()["focused_chunk_id"] == target["chunk_id"]

    # chunk_id 对不上（引用来自旧版本）时退回 ord
    by_ord = await client.get(
        f"/api/kb/documents/{document_id}/preview",
        params={"chunk_id": 999_999_999, "ord": target["ord"]},
        headers=EMPLOYEE,
    )
    assert by_ord.json()["focused_chunk_id"] == target["chunk_id"]

    stale = await client.get(
        f"/api/kb/documents/{document_id}/preview",
        params={"chunk_id": 99_999_999},
        headers=EMPLOYEE,
    )
    assert stale.status_code == 200
    assert stale.json()["focused_chunk_id"] is None


async def test_preview_rejects_unknown_or_malformed_document_id(
    client: AsyncClient,
) -> None:
    for document_id in ("not-a-uuid", "00000000-0000-0000-0000-000000000000"):
        response = await client.get(f"/api/kb/documents/{document_id}/preview", headers=EMPLOYEE)
        assert response.status_code == 404
        assert response.json()["code"] == "NOT_FOUND"


async def test_preview_requires_login(client: AsyncClient) -> None:
    document_id = await _upload(client)

    response = await client.get(
        f"/api/kb/documents/{document_id}/preview",
        headers={"Authorization": "Bearer "},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


async def test_preview_caps_long_document_and_keeps_far_focus(client: AsyncClient) -> None:
    """超过 200 段时只回窗口，但引用段在第 250 段也要能看到（窗口前移）。"""
    sections = "\n\n".join(
        f"## 第 {index} 节\n\n这是第 {index} 节的正文，用来验证超长文档的预览窗口与焦点。"
        for index in range(1, 251)
    )
    upload = await client.post(
        "/api/admin/kb/documents",
        headers=ADMIN,
        files={
            "file": (
                "long.md",
                f"# 超长文档\n\n{sections}\n".encode(),
                "text/markdown",
            )
        },
    )
    assert upload.status_code == 201
    document_id = upload.json()["document"]["id"]

    head = await client.get(f"/api/kb/documents/{document_id}/preview", headers=EMPLOYEE)
    payload = head.json()
    total = payload["total_chunks"]
    assert total >= 240
    assert len(payload["chunks"]) == 200
    assert payload["truncated"] is True
    assert payload["chunks"][0]["ord"] == 1

    tail = await client.get(
        f"/api/kb/documents/{document_id}/preview",
        params={"ord": total},
        headers=EMPLOYEE,
    )
    tail_payload = tail.json()
    assert tail_payload["focused_chunk_id"] is not None
    assert tail_payload["chunks"][0]["ord"] == total - 199
    assert tail_payload["chunks"][-1]["ord"] == total


async def test_admin_kb_list_still_requires_admin(client: AsyncClient) -> None:
    """预览开放给登录用户，不能顺带把管理面的列表也放开。"""
    response = await client.get("/api/admin/kb/documents", headers=EMPLOYEE)
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


HR_DOC = """# 薪酬、年终奖与工资条查询（HR 专用）

## 年终奖

年终奖在次年 1 月随工资发放，金额按绩效系数计算。
""".encode()


async def _upload_restricted(client: AsyncClient) -> str:
    response = await client.post(
        "/api/admin/kb/documents",
        headers=ADMIN,
        files={"file": ("hr-compensation.md", HR_DOC, "text/markdown")},
        data={"visibility": "roles", "allowed_roles": "hr"},
    )
    assert response.status_code == 201
    payload = response.json()["document"]
    assert payload["visibility"] == "roles"
    assert payload["allowed_roles"] == ["hr"]
    return str(payload["id"])


async def test_restricted_document_is_404_for_employees(client: AsyncClient) -> None:
    document_id = await _upload_restricted(client)

    response = await client.get(f"/api/kb/documents/{document_id}/preview", headers=EMPLOYEE)

    # 不用 403：403 等于承认「这篇文档存在，只是你看不到」
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
    assert "年终奖" not in response.text


async def test_restricted_document_is_readable_with_matching_role(client: AsyncClient) -> None:
    document_id = await _upload_restricted(client)

    employee = await client.get(f"/api/kb/documents/{document_id}/preview", headers=HR)

    assert employee.status_code == 200
    assert any("年终奖" in chunk["content"] for chunk in employee.json()["chunks"])


async def test_admin_reads_restricted_document_as_knowledge_owner(client: AsyncClient) -> None:
    document_id = await _upload_restricted(client)

    response = await client.get(f"/api/kb/documents/{document_id}/preview", headers=ADMIN)

    assert response.status_code == 200
    assert response.json()["document"]["visibility"] == "roles"
