"""知识库管理接口：上传/切片预览/权限/重建索引。"""

from __future__ import annotations

import io

from docx import Document
from httpx import AsyncClient
from pypdf import PdfWriter

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
    document = Document()
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
    writer = PdfWriter()
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
