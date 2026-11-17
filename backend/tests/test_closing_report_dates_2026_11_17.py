# -*- coding: utf-8 -*-
"""結案報表表頭日期（fix/closing-report-amounts，使用者 2026-11-17 裁示 6e）：
①成案日期＝稽核紀錄最後一次轉成「已成案」的日期；查不到（稽核已清）→ 報價單存的 dealWonAt → 客戶回簽日 → 「—」。
②精算日期兩個都印：「精算日期（手填）」＋「完結日期」（finalizedAt 轉台灣時間）；完結人缺就退回編輯歷程；沒完結只印手填的。
③舊完結案只有這幾個日期變，其餘輸出不變。"""
import json
import re

import db
import pdf_gen

_STAMP = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d")
SUMMARY = {"quotedPretax": 100000, "itemActualTotal": 50000, "extraTotal": 0, "dispatchTotal": 0, "totalActualCost": 50000,
           "grossProfit": 50000, "grossMarginPct": 50.0, "adminCost": 10000, "charityDonation": 500, "netProfit": 39500, "netMarginPct": 39.5}


def _make(no, *, settlement=None, signed_at="", extra=None, won_audit=None, status="finalized"):
    st = {"status": status, "items": [], "summary": dict(SUMMARY)}
    st.update(settlement or {})
    data = {"dealTag": "已結案", "settlement": st}
    data.update(extra or {})
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, "
                     "deal_tag, settle_status, signed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (no, "已送出", "測試客戶", "測試專案", 105000, 100000, json.dumps(data, ensure_ascii=False), "2026-01-01T00:00:00",
                      "2026-01-01T00:00:00", "已結案", status, signed_at))
        for at, to in (won_audit or []):
            conn.execute("INSERT INTO audit_log (at, username, action, target_type, target_id, detail) VALUES (?,?,?,?,?,?)",
                         (at, "u", "deal_tag.change", "quotation", no, json.dumps({"from": "", "to": to}, ensure_ascii=False)))
        conn.commit()
    finally:
        conn.close()


def _html(no):
    return _STAMP.sub("<時間>", pdf_gen._build_case_closing_html(pdf_gen._case_closing_report_data(no)))


def _won(html):
    return re.search(r"<span>成案日期：</span>([^<]*)</div>", html).group(1)


# ── ① 成案日期 ────────────────────────────────────────────────────────────────
def test_won_date_prefers_the_last_audit_event_to_won(client):
    _make("MQ-WON-1", won_audit=[("2026-03-01T09:00:00", "已成案"), ("2026-03-05T09:00:00", ""), ("2026-04-02T10:00:00", "已成案"), ("2026-06-01T10:00:00", "已結案")],
          signed_at="2026-02-10T08:00:00", extra={"dealWonAt": "2026-01-15T00:00:00"})
    html = _html("MQ-WON-1")
    assert _won(html) == "2026-04-02"
    assert pdf_gen._case_closing_report_data("MQ-WON-1")["wonAtSource"] == "audit"


def test_won_date_falls_back_to_stored_dealwonat_when_audit_is_gone(client):
    _make("MQ-WON-2", signed_at="2026-02-10T08:00:00", extra={"dealWonAt": "2026-01-15T00:00:00"})
    assert _won(_html("MQ-WON-2")) == "2026-01-15"
    assert pdf_gen._case_closing_report_data("MQ-WON-2")["wonAtSource"] == "dealWonAt"


def test_won_date_falls_back_to_customer_signed_date_then_dash(client):
    _make("MQ-WON-3", signed_at="2026-02-10T08:00:00")
    assert _won(_html("MQ-WON-3")) == "2026-02-10"
    assert pdf_gen._case_closing_report_data("MQ-WON-3")["wonAtSource"] == "signedAt"
    _make("MQ-WON-4")
    assert _won(_html("MQ-WON-4")) == "—"
    assert pdf_gen._case_closing_report_data("MQ-WON-4")["wonAtSource"] == ""


def test_audit_events_that_are_not_won_do_not_count(client):
    _make("MQ-WON-5", won_audit=[("2026-05-01T09:00:00", "未成案")], signed_at="2026-02-10T08:00:00")
    assert _won(_html("MQ-WON-5")) == "2026-02-10"


# ── ② 精算日期／完結日期／完結人 ─────────────────────────────────────────────────────
def test_both_settlement_dates_are_printed_and_finalized_at_is_taiwan_time(client):
    # 2026-08-02T17:30:00Z ＝ 台灣 2026-08-03 01:30：日期要跨日
    _make("MQ-FIN-1", settlement={"settlementDate": "2026-08-02", "finalizedAt": "2026-08-02T17:30:00.000Z", "finalizedBy": "王小明"})
    assert "（精算完結 · 精算日期（手填）：2026-08-02　完結日期：2026-08-03　完結人：王小明）" in _html("MQ-FIN-1")


def test_finalized_by_and_date_fall_back_to_edit_history_when_the_settlement_lacks_them(client):
    _make("MQ-FIN-2", settlement={"settlementDate": "2026-08-02"},
          extra={"editHistory": [{"type": "settlement_draft", "at": "2026-07-30T10:00:00", "by": "x", "byDisplay": "草稿者"},
                                 {"type": "settlement_finalized", "at": "2026-08-04T09:00:00", "frozenAt": "2026-08-04T09:00:01", "by": "wang", "byDisplay": "王小明"}]})
    assert "精算日期（手填）：2026-08-02　完結日期：2026-08-04　完結人：王小明）" in _html("MQ-FIN-2")


def test_nothing_to_fall_back_on_prints_dashes(client):
    _make("MQ-FIN-3", settlement={})
    assert "精算日期（手填）：—　完結日期：—　完結人：—）" in _html("MQ-FIN-3")


def test_not_finalized_prints_only_the_manual_settlement_date_in_the_header(client):
    _make("MQ-FIN-4", status="draft", settlement={"settlementDate": "2026-08-02", "finalizedAt": "", "summary": {}})
    from tests.test_closing_report_amounts_2026_11_17 import _dom
    html = _html("MQ-FIN-4")
    meta = "".join(_dom(html).meta)                                                          # 表頭區塊（class=meta）的文字
    assert "精算日期（手填）：2026-08-02" in meta and "完結日期：2026-08" not in meta
    _make("MQ-FIN-5", status="draft", settlement={"settlementDate": "", "summary": {}})
    assert "精算日期（手填）" not in _html("MQ-FIN-5")


def test_old_finalized_case_only_the_date_texts_change(client):
    """舊完結案（沒有 dealWonAt、沒有 finalized 資訊）：與『把新字串換回舊字串』的輸出逐字相同 ⇒ 只有日期字樣變。"""
    _make("MQ-OLD-1", settlement={"settlementDate": "2026-08-02", "finalizedBy": "舊人員"}, won_audit=[("2026-04-02T10:00:00", "已成案")])
    new = _html("MQ-OLD-1")
    old_like = new.replace("精算日期（手填）：2026-08-02　完結日期：—　完結人：舊人員", "精算日期：2026-08-02　完結人：舊人員")
    assert old_like != new and "完結日期：—" not in old_like
    assert _won(new) == "2026-04-02"


