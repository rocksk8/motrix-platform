# -*- coding: utf-8 -*-
"""正式機 11/16 回報：精算存檔成功後約 2.5 秒內再存（或按完結）回 409「已被其他人更新」，只有一人操作。
重現：照精算頁的做法——每次 PUT 都帶「上一次回傳的 updated_at」當 expectedUpdatedAt；存完等背景工作跑完再比對資料庫實際值。"""
import json
import threading
import time

import db
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W, _ln  # noqa: F401
from modules.case.tests.test_settlement_finalize_integrity_2026_10_03 import URL, case, page_payload  # noqa: F401
from modules.case.tests._t40_won import quote_is_won  # noqa: F401


def _db_updated_at():
    cn = db.get_db()
    try:
        return cn.execute("SELECT updated_at FROM quotations WHERE quote_no=?", (NO,)).fetchone()["updated_at"]
    finally:
        cn.close()


def _wait_bg(seconds=3.0):
    """等存檔後的背景執行緒（備份等）跑完，再看版本戳記有沒有被動過。"""
    time.sleep(seconds)
    for t in threading.enumerate():
        if t is not threading.current_thread() and t.daemon and t.name.startswith("Thread-"):
            t.join(timeout=2)


def _put(c, h, st, expected, **kw):
    body = dict({"settlement": st}, **kw)
    if expected:
        body["expectedUpdatedAt"] = expected
    return c.put(URL, json=body, headers=h)


def test_second_save_with_returned_updated_at_is_not_a_conflict(case):
    c, h = case
    g = c.get(URL, headers=h).json()
    r1 = _put(c, h, {"status": "draft", "items": [], "offsets": []}, g["updatedAt"])
    assert r1.status_code == 200, r1.text
    _wait_bg()
    assert _db_updated_at() == r1.json()["updated_at"], "存檔後有別的東西又改了 updated_at（回傳值與資料庫不一致）"
    r2 = _put(c, h, {"status": "draft", "items": [], "offsets": []}, r1.json()["updated_at"])
    assert r2.status_code == 200, "第二次存檔誤報衝突：%s" % r2.text[:200]


def test_each_settlement_409_carries_its_own_fail_reason_code(case):
    """稽核只記狀態碼時三種 409 都是 conflict，查不出正式機那兩筆是哪一種；現在各帶固定詞彙原因碼（本文與狀態碼不變）。"""
    c, h = case
    g = c.get(URL, headers=h).json()
    ok = _put(c, h, {"status": "draft", "items": [], "offsets": []}, g["updatedAt"])
    assert ok.status_code == 200
    stale = _put(c, h, {"status": "draft", "items": [], "offsets": []}, g["updatedAt"])             # 用舊版本戳記
    assert stale.status_code == 409 and stale.headers.get("X-Fail-Reason") == "stale_version"
    forged = page_payload(c, h, netProfit=888888)
    mism = _put(c, h, forged, ok.json()["updated_at"])
    assert mism.status_code == 409 and mism.headers.get("X-Fail-Reason") == "finalize_mismatch", mism.text[:200]
    # 稽核列：reason_code 與 detail.msg（只有欄位名稱，沒有金額）
    cn = db.get_db()
    try:
        ok_det = json.loads(cn.execute("SELECT detail FROM audit_log WHERE action='quotation.settlement' ORDER BY id DESC LIMIT 1").fetchone()["detail"])
    finally:
        cn.close()
    assert ok_det.get("updated_at") == ok.json()["updated_at"], "成功存檔的稽核要記回給頁面的版本戳記：%s" % ok_det
    cn = db.get_db()
    try:
        rows = [(r["reason_code"], json.loads(r["detail"] or "{}")) for r in cn.execute(
            "SELECT reason_code, detail FROM audit_log WHERE action='fail.PUT' ORDER BY id").fetchall()]
    finally:
        cn.close()
    codes = {code for code, _ in rows}
    assert "stale_version" in codes, rows
    assert rows[0][0] == "stale_version" and g["updatedAt"] in rows[0][1].get("msg", "") and ok.json()["updated_at"] in rows[0][1].get("msg", ""), \
        "版本衝突的稽核要記頁面帶的與資料庫現值：%s" % (rows[0],)
    # 同一人同路由同狀態 60 秒內只寫一列，第二次併入 repeat；它的原因在 last_reason／last_msg
    first = rows[0][1]
    assert first.get("repeat") == 1 and first.get("last_reason") == "finalize_mismatch", first
    msg = first.get("last_msg", "")
    assert msg and not any(ch.isdigit() for ch in msg), "訊息只該有欄位名稱、不含金額：" + msg


def test_finalize_right_after_draft_save_is_not_a_conflict(case):
    c, h = case
    g = c.get(URL, headers=h).json()
    r1 = _put(c, h, {"status": "draft", "items": [], "offsets": []}, g["updatedAt"])
    assert r1.status_code == 200, r1.text
    r2 = _put(c, h, page_payload(c, h), r1.json()["updated_at"])
    assert r2.status_code == 200, "草稿存完立刻完結被擋：%s" % r2.text[:300]
