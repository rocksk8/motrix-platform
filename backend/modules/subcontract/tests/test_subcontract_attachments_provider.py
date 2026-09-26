"""M04 的附件來源提供者（`attachments.for_document`，主持裁示 M06-b）：派工單與承攬商發票。

需要 M04 ⇒ 隨模組（PLAYBOOK §B-11）。兩類共用同一個派工單 id，內容來自不同欄位。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import pytest

from core import registry
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')

ROOT = {"id": 0, "username": "att_root", "role": "superadmin", "modules": []}


def _dispatch(conn, quote_no, files, invoice_files):
    cur = conn.execute("INSERT INTO contractor_dispatches (quote_no, files_json, invoice_files_json) VALUES (?,?,?)",
                       (quote_no, files, invoice_files))
    conn.commit()
    return str(cur.lastrowid)


def test_subcontract_attachments_provider(client):
    import db
    from helpers.uploads import AttachmentSourceError
    prov = registry.providers("attachments.for_document").get("subcontract")
    assert prov is not None and set(prov.SOURCE_TYPES) == {"contractor_dispatch", "contractor_invoice"}
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, data_json, created_at, updated_at)"
                     " VALUES ('ATT-SC','草稿','{}','2026-01-01','2026-01-01')")
        ok = _dispatch(conn, "ATT-SC", '[{"id": "f1", "path": "a"}]', '[{"id": "i1", "path": "b"}]')
        bad = _dispatch(conn, "ATT-SC", "{壞", "[]")
        assert prov.doc_nos_for_case(conn, "contractor_dispatch", "ATT-SC", ROOT) == [ok, bad]
        assert [f["id"] for f in prov.files(conn, "contractor_dispatch", ok, ROOT)] == ["f1"]
        assert [f["id"] for f in prov.files(conn, "contractor_invoice", ok, ROOT)] == ["i1"]   # 同一個 id、不同欄位
        with pytest.raises(AttachmentSourceError):
            prov.files(conn, "contractor_dispatch", bad, ROOT)
        assert prov.files(conn, "contractor_dispatch", "999999", ROOT) == []
        with pytest.raises(AttachmentSourceError):
            prov.files(conn, "invoice_voucher", ok, ROOT)
    finally:
        conn.close()


def test_subcontract_provider_refuses_a_reader_who_cannot_see_the_case(client):
    """AT-M1：看不到派工單所屬案件的人 ⇒ AttachmentNotVisible（列清單與讀檔都擋）。"""
    import db
    from helpers.uploads import AttachmentNotVisible
    prov = registry.providers("attachments.for_document")["subcontract"]
    nobody = {"id": 999999, "username": "att_nobody", "role": "engineer", "modules": []}
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, data_json, created_at, updated_at)"
                     " VALUES ('ATT-SC2','草稿','{}','2026-01-01','2026-01-01')")
        did = _dispatch(conn, "ATT-SC2", '[{"id": "f1", "path": "a"}]', "[]")
        for st in prov.SOURCE_TYPES:
            with pytest.raises(AttachmentNotVisible):
                prov.files(conn, st, did, nobody)
            with pytest.raises(AttachmentNotVisible):
                prov.doc_nos_for_case(conn, st, "ATT-SC2", nobody)
    finally:
        conn.close()
