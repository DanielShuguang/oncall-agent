"""引用跳全文接口：可见性、焦点定位、404 与鉴权。

可见性由 ADR-0018 定：预览与检索共用同一边界，普通员工可读引用文档全文，
但知识库的列表/上传/重建索引仍只属于管理员。
"""

from __future__ import annotations

from httpx import AsyncClient

from tests.support import auth_headers

ADMIN = auth_headers(user_id="admin_1", roles=("admin",))
EMPLOYEE = auth_headers(user_id="u_204", roles=("employee",))

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
