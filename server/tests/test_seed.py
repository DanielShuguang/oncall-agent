"""演示数据：数量、确定性、噪声与冲突。"""

from __future__ import annotations

import json
from pathlib import Path

from app.seed.corpus import build_documents
from app.seed.generate import _asset_rows, _ticket_rows, generate


def test_seed_corpus_counts_and_titles() -> None:
    documents = build_documents()
    assert len(documents) == 50
    assert len({document.title for document in documents}) == 50
    assert len({document.filename for document in documents}) == 50
    assert sum(1 for document in documents if "归档" in document.title) == 8
    # 负样本必须真的不在知识库里（例外：neg-bonus 的 HR 文档存在但受限，见下一条用例）
    assert not any("年会抽奖" in document.text for document in documents)


def test_seed_has_one_role_restricted_document() -> None:
    """评测 neg-bonus 的 ACL 金丝雀：语料里真有这篇，但员工身份检索不到（ADR-0019）。"""
    restricted = [doc for doc in build_documents() if doc.visibility != "public"]
    assert [doc.filename for doc in restricted] == ["kb-hr-compensation.md"]
    assert restricted[0].allowed_roles == ("hr",)
    assert "年终奖" in restricted[0].text


def test_assets_and_tickets_are_deterministic() -> None:
    assets = _asset_rows()
    tickets = _ticket_rows(assets)
    assert len(assets) == 200
    assert len(tickets) == 500
    assert assets[0]["id"] == "PC-20481"
    assert assets[0]["owner_id"] == "u_102"
    assert _asset_rows() == assets
    assert _ticket_rows(assets) == tickets
    assert any("再次报修" in str(ticket["title"]) for ticket in tickets)


async def test_generate_writes_files(tmp_path: Path) -> None:
    stats = await generate(out_dir=tmp_path)
    assert stats.documents == 50
    assert stats.assets == 200
    assert stats.tickets == 500
    assert len(list((tmp_path / "kb").glob("*.md"))) == 50
    assets = json.loads((tmp_path / "assets.json").read_text(encoding="utf-8"))
    tickets = json.loads((tmp_path / "tickets.json").read_text(encoding="utf-8"))
    assert len(assets) == 200
    assert len(tickets) == 500
