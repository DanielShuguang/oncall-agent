"""知识库管理接口：上传/切片预览/权限/重建索引。"""

from __future__ import annotations

import io

import pytest
from httpx import AsyncClient

from tests.support import auth_headers

ADMIN = auth_headers(user_id="admin_1", roles=("admin",))


async def test_upload_markdown_returns_chunks_with_heading_path(client: AsyncClient) -> None:
    content = """# 访客网络说明

## 登记流程

访客由接待人提前一天在访客系统登记。

## 连接方式

访客使用手机号验证码登录 OnCall-Guest。
""".encode()
    response = await client.post(
        "/api/admin/kb/documents",
        headers=ADMIN,
        files={"file": ("guest-network.md", content, "text/markdown")},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["document"]["title"] == "访客网络说明"
    assert payload["document"]["chunk_count"] == len(payload["chunks"])
    assert any(chunk["heading"] == "访客网络说明 > 登记流程" for chunk in payload["chunks"])

    document_id = payload["document"]["id"]
    detail = await client.get(f"/api/admin/kb/documents/{document_id}", headers=ADMIN)
    assert detail.status_code == 200
    assert detail.json()["document"]["id"] == document_id


async def test_upload_docx_keeps_heading_and_table(client: AsyncClient) -> None:
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_heading("打印服务说明", level=1)
    document.add_heading("队列清理", level=2)
    document.add_paragraph("清空 Print Spooler 队列后重启服务。")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "型号"
    table.cell(0, 1).text = "驱动"
    table.cell(1, 0).text = "HP-1020"
    table.cell(1, 1).text = "内网软件库"
    buffer = io.BytesIO()
    document.save(buffer)

    response = await client.post(
        "/api/admin/kb/documents",
        headers=ADMIN,
        files={
            "file": (
                "print.docx",
                buffer.getvalue(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert response.status_code == 201
    chunks = response.json()["chunks"]
    assert any(
        chunk["heading"] and "打印服务说明 > 队列清理" in chunk["heading"] for chunk in chunks
    )
    assert any(chunk["is_table"] and "HP-1020" in chunk["content"] for chunk in chunks)


async def test_upload_requires_admin_role(client: AsyncClient) -> None:
    response = await client.post(
        "/api/admin/kb/documents",
        files={"file": ("x.md", b"# hi\n\nbody", "text/markdown")},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


async def test_upload_scanned_pdf_returns_422(client: AsyncClient) -> None:
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)

    response = await client.post(
        "/api/admin/kb/documents",
        headers=ADMIN,
        files={"file": ("scan.pdf", buffer.getvalue(), "application/pdf")},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "PARSE_FAILED"


async def test_upload_unsupported_type_returns_422(client: AsyncClient) -> None:
    response = await client.post(
        "/api/admin/kb/documents",
        headers=ADMIN,
        files={"file": ("setup.exe", b"binary", "application/octet-stream")},
    )
    assert response.status_code == 422


async def test_list_documents_includes_seed_corpus(client: AsyncClient) -> None:
    response = await client.get("/api/admin/kb/documents", headers=ADMIN)
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 50
    assert payload["chunk_count"] > 50


async def test_seed_corpus_loads_even_after_upload(client: AsyncClient) -> None:
    """内存模式的 seed 不能因为「先上传了一篇」就整体不加载。"""
    upload = await client.post(
        "/api/admin/kb/documents",
        headers=ADMIN,
        files={"file": ("first.md", "# 先上传的文档\n\n正文在这里。".encode(), "text/markdown")},
    )
    assert upload.status_code == 201

    listing = await client.get("/api/admin/kb/documents", headers=ADMIN)
    assert listing.json()["total"] == 51


async def test_reindex_recomputes_vectors(client: AsyncClient) -> None:
    upload = await client.post(
        "/api/admin/kb/documents",
        headers=ADMIN,
        files={"file": ("reindex.md", "# Reindex\n\nVPN 连不上".encode(), "text/markdown")},
    )
    assert upload.status_code == 201

    response = await client.post("/api/admin/kb/reindex", headers=ADMIN)
    assert response.status_code == 200
    assert response.json()["chunks"] >= 1


HR = auth_headers(user_id="u_301", roles=("employee", "hr"))
EMPLOYEE = auth_headers(user_id="u_204", roles=("employee",))

COMPENSATION = """# 薪酬、年终奖与工资条查询

## 年终奖

年终奖在次年 1 月随工资发放，金额按绩效系数计算。
""".encode()


async def _upload_compensation(client: AsyncClient, data: dict[str, str] | None = None) -> str:
    response = await client.post(
        "/api/admin/kb/documents",
        headers=ADMIN,
        files={"file": ("compensation.md", COMPENSATION, "text/markdown")},
        data=data or {},
    )
    assert response.status_code == 201
    return str(response.json()["document"]["id"])


async def test_upload_restricted_document_records_access(client: AsyncClient) -> None:
    document_id = await _upload_compensation(
        client, {"visibility": "roles", "allowed_roles": " hr , finance "}
    )

    listing = await client.get("/api/admin/kb/documents", headers=ADMIN)
    row = next(doc for doc in listing.json()["documents"] if doc["id"] == document_id)
    assert row["visibility"] == "roles"
    assert row["allowed_roles"] == ["hr", "finance"]

    detail = await client.get(f"/api/admin/kb/documents/{document_id}", headers=ADMIN)
    assert detail.json()["document"]["allowed_roles"] == ["hr", "finance"]


async def test_upload_defaults_to_public(client: AsyncClient) -> None:
    response = await client.post(
        "/api/admin/kb/documents",
        headers=ADMIN,
        files={"file": ("public.md", b"# Public\n\n## Body\n\nhello", "text/markdown")},
    )
    assert response.status_code == 201
    document = response.json()["document"]
    assert document["visibility"] == "public"
    assert document["allowed_roles"] == []


async def test_upload_rejects_ambiguous_access(client: AsyncClient) -> None:
    for data in (
        {"visibility": "public", "allowed_roles": "hr"},  # 公开文档不能带角色
        {"visibility": "roles", "allowed_roles": ""},  # 指定角色至少一个
        {"visibility": "roles", "allowed_roles": "人事"},  # 非法角色名
        {"visibility": "team"},  # 未知可见性
    ):
        response = await client.post(
            "/api/admin/kb/documents",
            headers=ADMIN,
            files={"file": ("ambiguous.md", COMPENSATION, "text/markdown")},
            data=data,
        )
        assert response.status_code == 422, data
        assert response.json()["code"] == "INVALID_ARGS", data


async def test_patch_access_switch_without_reindexing(client: AsyncClient) -> None:
    document_id = await _upload_compensation(client)
    before = await client.get(f"/api/admin/kb/documents/{document_id}", headers=ADMIN)
    chunks_before = [chunk["ord"] for chunk in before.json()["chunks"]]
    preview_before = await client.get(f"/api/kb/documents/{document_id}/preview", headers=EMPLOYEE)
    chunk_ids_before = [chunk["chunk_id"] for chunk in preview_before.json()["chunks"]]

    response = await client.patch(
        f"/api/admin/kb/documents/{document_id}/access",
        headers=ADMIN,
        json={"visibility": "roles", "allowed_roles": ["hr"]},
    )
    assert response.status_code == 200
    assert response.json()["visibility"] == "roles"
    assert response.json()["allowed_roles"] == ["hr"]

    after = await client.get(f"/api/admin/kb/documents/{document_id}", headers=ADMIN)
    assert [chunk["ord"] for chunk in after.json()["chunks"]] == chunks_before

    # 员工立刻读不到，hr 立刻读得到：权限变化不需要等重建索引
    employee = await client.get(f"/api/kb/documents/{document_id}/preview", headers=EMPLOYEE)
    hr = await client.get(f"/api/kb/documents/{document_id}/preview", headers=HR)
    assert employee.status_code == 404
    assert hr.status_code == 200
    # 关键承诺：chunk_id 不变，收紧后旧引用仍然能定位
    assert [chunk["chunk_id"] for chunk in hr.json()["chunks"]] == chunk_ids_before

    reopened = await client.patch(
        f"/api/admin/kb/documents/{document_id}/access",
        headers=ADMIN,
        json={"visibility": "public", "allowed_roles": []},
    )
    assert reopened.status_code == 200
    assert reopened.json()["visibility"] == "public"
    assert reopened.json()["allowed_roles"] == []


async def test_patch_access_rejects_bad_input_and_unknown_document(client: AsyncClient) -> None:
    document_id = await _upload_compensation(client)

    bad = await client.patch(
        f"/api/admin/kb/documents/{document_id}/access",
        headers=ADMIN,
        json={"visibility": "roles", "allowed_roles": []},
    )
    assert bad.status_code == 422
    assert bad.json()["code"] == "INVALID_ARGS"

    # PATCH 是整体替换：只给一半字段不能被解释成默认值（尤其不能静默改成公开）
    partial = await client.patch(
        f"/api/admin/kb/documents/{document_id}/access",
        headers=ADMIN,
        json={"visibility": "public"},
    )
    assert partial.status_code == 422

    missing = await client.patch(
        "/api/admin/kb/documents/not-a-uuid/access",
        headers=ADMIN,
        json={"visibility": "public", "allowed_roles": []},
    )
    assert missing.status_code == 404


async def test_employee_cannot_change_document_access(client: AsyncClient) -> None:
    document_id = await _upload_compensation(client)

    response = await client.patch(
        f"/api/admin/kb/documents/{document_id}/access",
        headers=EMPLOYEE,
        json={"visibility": "roles", "allowed_roles": ["employee"]},
    )
    assert response.status_code == 403
