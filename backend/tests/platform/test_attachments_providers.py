"""`attachments.for_document`（主持裁示 M06-b，2026-09-26；docs/platform/plans/ATTACHMENTS-PLAN.md）。

傳票帶入附件的九類來源由各擁有模組提供（M01 案件 6 類、M04 外包工班 2 類、M05 應收應付 1 類），
M06 `helpers/voucher_attachments.py` 不再直讀別組的表。
- 取用方只讀 M06 自己的表（dep_scan 的 SQL 解析，與 dep_graph 同一份）；合成正對照／反向控制
- 在場的提供者：類型聯集 ⊆ 白名單、兩兩不重疊；模組全在 ⇒ 聯集＝白名單（取代原本 import 時的 assert）
- 提供者不在：候選不列那幾類、說出是哪個模組不在；帶入 400 並說明（不回空清單）
本檔在任何模組不在時也要綠（期望值依 module_installed 決定）。
"""
import ast
import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

from core import registry, source_tree
from tests.platform.test_case_stage_connectors import _without

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import dep_scan  # noqa: E402

CAP = "attachments.for_document"


def _groups():
    return json.loads((REPO / "docs" / "platform" / "modules.json").read_text(encoding="utf-8"))["modules"]


def foreign_tables(src, own, known):
    """原始碼裡讀寫到、而不屬於 `own` 的已知表。"""
    r, w, _ddl, _dyn = dep_scan.sql_tables(dep_scan.string_chunks(ast.parse(src)), known)
    return sorted((r | w) - set(own))


def test_positive_and_reverse_control_of_the_table_scan():
    known = {"vouchers_all", "voucher_attachments", "contractor_dispatches", "quotations"}
    own = {"vouchers_all", "voucher_attachments"}
    ok = 'x = "SELECT 1 FROM voucher_attachments va JOIN vouchers_all v ON v.id = va.voucher_id"\n'
    assert foreign_tables(ok, own, known) == []
    bad = ok + 'y = "SELECT files_json FROM contractor_dispatches WHERE id = ?"\n'
    assert foreign_tables(bad, own, known) == ["contractor_dispatches"]


def test_voucher_attachments_reads_no_foreign_tables():
    groups = _groups()
    own = set(groups["M06"]["tables"])
    known = {t for g in groups.values() for t in g.get("tables", [])}
    assert {"quotations", "contractor_dispatches", "invoice_vouchers"} <= known, "modules.json 讀不到表 ⇒ 會假綠"
    src = (source_tree.BACKEND / "helpers" / "voucher_attachments.py").read_text(encoding="utf-8")
    assert foreign_tables(src, own, known) == []


def _present():
    return [p for p in registry.providers(CAP).values()]


def test_providers_cover_the_whitelist_without_overlap(client):
    """client 夾具＝載入器已掛好在場的模組。"""
    from helpers import voucher_attachments as va
    assert set(va._SOURCE_OWNERS) == set(va.SOURCE_TYPES), "缺席說明的對照表要涵蓋整份白名單"
    seen = {}
    for name, prov in registry.providers(CAP).items():
        for st in prov.SOURCE_TYPES:
            assert st in va.SOURCE_TYPES, "%s 提供了白名單外的類型 %s" % (name, st)
            assert st not in seen, "%s 同時由 %s 與 %s 提供" % (st, seen[st], name)
            seen[st] = name
    owner_path = {"case": "routers/quotations.py", "arap": "routers/invoice_vouchers.py",
                  "subcontract": "modules/subcontract/api/vendor_contractors.py"}
    want = {st for st, (key, _l, _w) in va._SOURCE_OWNERS.items() if source_tree.module_installed(owner_path[key])}
    assert set(seen) == want, "在場的提供者沒有涵蓋該在的類型：少 %s" % sorted(want - set(seen))


def _dispatch_types():
    from helpers import voucher_attachments as va
    return [st for st, (key, _l, _w) in va._SOURCE_OWNERS.items() if key == "subcontract"]


def test_absent_provider_is_named_not_silent(client, monkeypatch):
    """合成：拿掉外包工班的提供者 ⇒ 候選不列那兩類、`unavailable_sources` 說出是誰、帶入與列檔 400 並說明。"""
    from helpers import voucher_attachments as va
    _without(monkeypatch, CAP, "subcontract")
    assert not set(_dispatch_types()) & set(va._providers())
    reasons = [u["reason"] for u in va.unavailable_sources()]
    assert any("外包工班模組未安裝" in r and "派工單" in r and "承攬商發票" in r for r in reasons), reasons
    for st in _dispatch_types():
        with pytest.raises(HTTPException) as ei:
            va.source_files(None, st, "1")
        assert ei.value.status_code == 400 and "外包工班模組未安裝" in ei.value.detail
        with pytest.raises(HTTPException) as ei:
            va.resolve_picks(None, [{"type": st, "docNo": "1", "fileId": "x"}])
        assert "外包工班模組未安裝" in ei.value.detail


def test_everything_present_means_nothing_unavailable(client):
    from helpers import voucher_attachments as va
    if not source_tree.module_installed("modules/subcontract/api/vendor_contractors.py"):
        pytest.skip("外包工班不在這個安裝包 ⇒ 本來就會有一筆缺席說明")
    assert va.unavailable_sources() == []


@pytest.mark.parametrize("name", ["case", "arap"])
def test_l1_side_providers_refuse_to_swallow_broken_json(client, name):
    """M01、M05 的提供者（M04 的在模組測試裡）：壞 JSON ⇒ AttachmentSourceError；單據不存在 ⇒ []。"""
    import db
    from helpers.uploads import AttachmentSourceError
    prov = registry.providers(CAP).get(name)
    assert prov is not None, "%s 的提供者沒有登記" % name
    conn = db.get_db()
    try:
        if name == "case":
            conn.execute("INSERT INTO quotations (quote_no, status, data_json, signed_files_json, created_at, updated_at)"
                         " VALUES ('ATT-BAD','草稿','{壞','{壞','2026-01-01','2026-01-01')")
            with pytest.raises(AttachmentSourceError):
                prov.files(conn, "quotation_signed", "ATT-BAD")
            with pytest.raises(AttachmentSourceError):
                prov.files(conn, "payment_item", "ATT-BAD_0")
            with pytest.raises(AttachmentSourceError):
                prov.files(conn, "material", "ATT-BAD")          # 沒有索引
            assert prov.files(conn, "quotation_signed", "NO-SUCH") == []
        else:
            conn.execute("INSERT INTO invoice_vouchers (voucher_no, quote_no, issued_files_json, created_at, updated_at)"
                         " VALUES ('IV-ATT-BAD','ATT-BAD','{壞','2026-01-01','2026-01-01')")
            with pytest.raises(AttachmentSourceError):
                prov.files(conn, "invoice_voucher", "IV-ATT-BAD")
            assert prov.files(conn, "invoice_voucher", "NO-SUCH") == []
            assert prov.doc_nos_for_case(conn, "invoice_voucher", "ATT-BAD") == ["IV-ATT-BAD"]
    finally:
        conn.close()
