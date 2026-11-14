"""報價單 PDF 重新下載（沿用同版檔）要留稽核、但不累加匯出次數（T86 U2，2026-11-14）。

POST /api/quotations/{no}/export：一般＝產生一次（export_count＋1、export_log 加一筆、稽核一筆）；
reused=true＝同版重新下載（只寫稽核一筆，detail 帶 reused=true；export_count／export_log 不變）。
觀測點：資料庫 export_count／export_log 與 audit_log 列。正對照：不帶 reused 的呼叫仍累加。
"""
import json

from tests.test_quote_put_fail_reason_codes_2026_11_14 import _login, _seed


def _count_and_log(no):
    import db
    conn = db.get_db()
    try:
        r = conn.execute("SELECT export_count, export_log FROM quotations WHERE quote_no=?", (no,)).fetchone()
        return (r["export_count"] or 0), json.loads(r["export_log"] or "[]")
    finally:
        conn.close()


def _export_audit(no):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM audit_log WHERE action='quotation.export_pdf' AND target_id=? ORDER BY id", (no,)).fetchall()]
    finally:
        conn.close()


def test_reused_download_audits_each_time_but_does_not_bump_export_count(client, make_user):
    u, p = make_user(username="ex_sa1", role="superadmin", modules=[])
    h = _login(client, u, p)
    _seed("MQ-2611-921", "已送出")
    r1 = client.post("/api/quotations/MQ-2611-921/export?mode=external", headers=h)
    assert r1.status_code == 200 and r1.json()["export_count"] == 1
    for _ in range(2):
        r = client.post("/api/quotations/MQ-2611-921/export?mode=external&reused=true", headers=h)
        assert r.status_code == 200 and r.json()["export_count"] == 1 and r.json()["reused"] is True
    n, log = _count_and_log("MQ-2611-921")
    assert n == 1 and len(log) == 1, "重新下載不累加產生次數、不加匯出紀錄"
    rows = _export_audit("MQ-2611-921")
    assert len(rows) == 3, "一次事件一筆稽核（1 次產生＋2 次重新下載）"
    flags = [bool(json.loads(x["detail"] or "{}").get("reused")) for x in rows]
    assert flags == [False, True, True], f"只有重新下載的兩筆 detail 帶 reused=true：{flags}"


def test_plain_export_still_increments(client, make_user):
    u, p = make_user(username="ex_sa2", role="superadmin", modules=[])
    h = _login(client, u, p)
    _seed("MQ-2611-922", "已送出")
    for i in (1, 2):
        assert client.post("/api/quotations/MQ-2611-922/export", headers=h).json()["export_count"] == i
    assert _count_and_log("MQ-2611-922")[0] == 2
