"""M04 的附件來源提供者（`attachments.for_document`，主持裁示 M06-b）：派工單與承攬商發票。

需要 M04 ⇒ 隨模組（PLAYBOOK §B-11）。兩類共用同一個派工單 id，內容來自不同欄位。
"""
import pytest

from core import registry


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
        ok = _dispatch(conn, "ATT-SC", '[{"id": "f1", "path": "a"}]', '[{"id": "i1", "path": "b"}]')
        bad = _dispatch(conn, "ATT-SC", "{壞", "[]")
        assert prov.doc_nos_for_case(conn, "contractor_dispatch", "ATT-SC") == [ok, bad]
        assert [f["id"] for f in prov.files(conn, "contractor_dispatch", ok)] == ["f1"]
        assert [f["id"] for f in prov.files(conn, "contractor_invoice", ok)] == ["i1"]   # 同一個 id、不同欄位
        with pytest.raises(AttachmentSourceError):
            prov.files(conn, "contractor_dispatch", bad)
        assert prov.files(conn, "contractor_dispatch", "999999") == []
        with pytest.raises(AttachmentSourceError):
            prov.files(conn, "invoice_voucher", ok)
    finally:
        conn.close()
