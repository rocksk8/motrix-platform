# -*- coding: utf-8 -*-
"""補登歷史報價單 L2（T70-1）——畫面所需的後端支援、提醒／逾期靜音、列表與 PDF 標示、報表月份、24 小時自動關閉。
設計 D:/Claude-pm/reports/design-backfill-quote-t69.md §10 L2。權限與端點一律真實使用者 HTTP；提醒題以「補登單 vs 一般已成案單」對照，
觀測點是實際落地的紀錄（防重複鍵／通知列／清單內容），不是端點自己 import 的名稱。
"""
import json
from datetime import datetime, timedelta

import pytest

import db

MONTH = "202607"
TODAY = datetime.now().strftime("%Y-%m-%d")
PAST = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d")
SOON = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")


def _login(client, make_user, name, role="superadmin"):
    u, p = make_user(name, "Lay-Pass-123", role=role)[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


@pytest.fixture
def boss(client, make_user):
    return _login(client, make_user, "bf2_boss")


@pytest.fixture
def flag_on():
    from helpers import settings_registry as SR

    def _set(**vals):
        conn = db.get_db()
        try:
            SR.publish("quote_backfill", dict({"enabled": 1}, **vals), reason="測試", user="bf2_test", conn=conn)
            conn.commit()
            SR.invalidate("quote_backfill")
        finally:
            conn.close()
    _set()
    yield _set
    _set(enabled=0, auto_off_hours=24)


def _body(date="2026-07-15", extra=None, reason="補登 7 月舊案件，紙本單據遺失重建"):
    data = {"customerName": "補登客戶", "projectName": "歷史案件", "quoteDate": date, "items": []}
    data.update(extra or {})
    return {"data": data, "reason": reason}


def _case_record():
    return {"stages": [{"label": "施工", "dueDate": SOON, "done": False, "assignedTo": ["bf2_boss"]}],
            "projectTimeline": {"endDate": PAST},
            "payment": {"items": [{"id": "p1", "label": "頭期款", "ratio": 100, "expectedReceiptDate": PAST, "received": False}]}}


def _hist(client, boss, extra=None):
    r = client.post("/api/quotations/historical", headers=boss, json=_body(extra={"caseRecord": _case_record(), **(extra or {})}))
    assert r.status_code == 201, r.text
    return r.json()["quote_no"]


def _normal_won(client, boss):
    """一般已成案單（對照組）：走一般新增（不帶 caseRecord——一般新增帶階段目前會在 _sync_stages_to_json 丟 RuntimeError，既有問題，見 notes），
    再於寫入交易內補上案件資料與階段，並把成案標記直接寫進資料庫（一般新增不可帶 dealTag）。"""
    from core.txn import begin_write
    from modules.case.api import quotations as Q
    r = client.post("/api/quotations", headers=boss, json={"status": "已送出", "data": {"customerName": "一般客戶", "projectName": "一般案", "items": []}})
    assert r.status_code in (200, 201), r.text
    no = r.json()["quote_no"]
    c = db.get_db()
    try:
        begin_write(c)
        d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()[0])
        cr = _case_record()
        stages = cr.pop("stages")
        d["caseRecord"] = cr
        c.execute("UPDATE quotations SET data_json=?, deal_tag='已成案' WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), no))
        Q._sync_json_stages_to_table(c, no, stages)
        c.commit()
    finally:
        c.close()
    return no


def _setting_keys(prefix):
    c = db.get_db()
    try:
        return [r[0] for r in c.execute("SELECT key FROM system_settings WHERE key LIKE ?", (prefix + "%",)).fetchall()]
    finally:
        c.close()


# ── 1. 畫面用的設定與號碼預覽 ───────────────────────────────────────────────
def test_config_is_available_only_to_superadmin_with_flag_on(client, boss, make_user, flag_on):
    r = client.get("/api/quotations/historical/config", headers=boss)
    assert r.status_code == 200 and r.json()["available"] is True
    j = r.json()
    assert j["earliest_month"] == 202001 and j["min_date"] == "2020-01-01"
    assert j["max_date"] == (datetime.now().replace(day=1) - timedelta(days=1)).strftime("%Y-%m-%d")
    adm = _login(client, make_user, "bf2_adm", role="admin")
    assert client.get("/api/quotations/historical/config", headers=adm).json()["available"] is False
    flag_on(enabled=0)
    assert client.get("/api/quotations/historical/config", headers=boss).json()["available"] is False
    assert client.get("/api/quotations/historical/config").status_code in (401, 403)


def test_next_no_preview_matches_the_number_actually_assigned(client, boss, flag_on):
    r = client.get("/api/quotations/historical/next-no", headers=boss, params={"date": "2026-07-15"})
    assert r.status_code == 200 and r.json()["quote_no"] == "MQ-%s-001" % MONTH
    no = client.post("/api/quotations/historical", headers=boss, json=_body()).json()["quote_no"]
    assert no == "MQ-%s-001" % MONTH
    assert client.get("/api/quotations/historical/next-no", headers=boss, params={"date": "2026-07-20"}).json()["quote_no"] == "MQ-%s-002" % MONTH
    # 作廢後預覽也不回頭（單號不回收）
    assert client.delete("/api/quotations/" + no, headers=boss, params={"reason": "測試作廢補登單"}).status_code == 200
    assert client.get("/api/quotations/historical/next-no", headers=boss, params={"date": "2026-07-20"}).json()["quote_no"] == "MQ-%s-002" % MONTH


@pytest.mark.parametrize("date", [TODAY, "2099-01-01", "2019-12-31", "abc", ""])
def test_next_no_preview_applies_the_same_date_rules(client, boss, flag_on, date):
    assert client.get("/api/quotations/historical/next-no", headers=boss, params={"date": date}).status_code == 400


def test_next_no_preview_is_refused_for_non_superadmin_or_flag_off(client, boss, make_user, flag_on):
    adm = _login(client, make_user, "bf2_adm2", role="admin")
    assert client.get("/api/quotations/historical/next-no", headers=adm, params={"date": "2026-07-15"}).status_code == 403
    flag_on(enabled=0)
    assert client.get("/api/quotations/historical/next-no", headers=boss, params={"date": "2026-07-15"}).status_code == 403


# ── 2. 24 小時自動關閉（可選；auto_off_hours，0＝不自動關）───────────────────────
def test_auto_off_closes_the_backfill_after_the_configured_hours(client, boss, flag_on, monkeypatch):
    from helpers import settings_registry as SR
    assert int(SR.get("quote_backfill", "auto_off_hours")) == 24
    from modules.case.api import quotations as Q
    assert client.get("/api/quotations/historical/config", headers=boss).json()["available"] is True
    later = datetime.now() + timedelta(hours=25)
    monkeypatch.setattr(Q, "_backfill_now", lambda: later)
    j = client.get("/api/quotations/historical/config", headers=boss).json()
    assert j["available"] is False and j.get("auto_off") is True
    r = client.post("/api/quotations/historical", headers=boss, json=_body())
    assert r.status_code == 403 and "自動關閉" in r.text


def test_auto_off_zero_means_never_and_bounds_are_enforced(client, boss, flag_on, monkeypatch):
    from modules.case.api import quotations as Q
    flag_on(auto_off_hours=0)
    monkeypatch.setattr(Q, "_backfill_now", lambda: datetime.now() + timedelta(days=400))
    assert client.get("/api/quotations/historical/config", headers=boss).json()["available"] is True
    from helpers import settings_registry as SR
    conn = db.get_db()
    try:
        for bad in (-1, 721):
            with pytest.raises(Exception):
                SR.publish("quote_backfill", {"auto_off_hours": bad}, reason="越界", user="bf2_test", conn=conn)
    finally:
        conn.rollback()
        conn.close()


# ── 3. 提醒／逾期靜音：補登單不吵，一般已成案單照舊（對照組）──────────────────────
def test_stage_deadline_reminders_skip_backfilled_cases_but_not_normal_ones(client, boss, flag_on, monkeypatch):
    from modules.case import case_deadlines as CD
    monkeypatch.setattr(CD, "notify_case_stage_deadline", lambda *a, **k: None)
    h = _hist(client, boss)
    n = _normal_won(client, boss)
    CD._check_case_stage_deadline()
    keys = _setting_keys("casestage_notif.")
    assert any(k.startswith("casestage_notif.%s." % n) for k in keys), "正對照：一般已成案單的階段到期提醒仍會發"
    assert not any(k.startswith("casestage_notif.%s." % h) for k in keys), "補登單不發階段到期提醒"


def test_project_overdue_reminders_skip_backfilled_cases(client, boss, flag_on, monkeypatch):
    from modules.case import case_deadlines as CD
    monkeypatch.setattr(CD, "notify_case_project_overdue", lambda *a, **k: None)
    h = _hist(client, boss)
    n = _normal_won(client, boss)
    CD._check_case_project_timeline_deadline()
    keys = _setting_keys("caseproj_notif.")
    assert any(k.startswith("caseproj_notif.%s." % n) for k in keys), "正對照：一般案件的專案逾期提醒仍會發"
    assert not any(k.startswith("caseproj_notif.%s." % h) for k in keys)


def test_project_end_calendar_skips_backfilled_cases(client, boss, flag_on, monkeypatch):
    from helpers import calendar_sync as CS
    from modules.case import case_deadlines as CD
    seen = {}
    monkeypatch.setattr(CS, "is_active", lambda *_a, **_k: True)
    monkeypatch.setattr(CS, "sync_dated_events", lambda kind, current, *a, **k: seen.update(current))
    h = _hist(client, boss)
    n = _normal_won(client, boss)
    CD._sync_project_end_calendar()
    assert n in seen, "正對照：一般案件會進行事曆"
    assert h not in seen


def test_receivable_queue_mutes_backfilled_cases(client, boss, flag_on):
    h = _hist(client, boss)
    n = _normal_won(client, boss)
    todo = client.get("/api/cashier/receivable-queue", headers=boss, params={"status": "unreceived"}).json()
    assert any(i["quoteNo"] == n and i["overdue"] for i in todo), "正對照：一般案件的逾期應收照舊出現"
    assert not any(i["quoteNo"] == h for i in todo), "補登單不出現在待辦／逾期"
    allq = client.get("/api/cashier/receivable-queue", headers=boss, params={"status": "all"}).json()
    row = [i for i in allq if i["quoteNo"] == h]
    assert row and row[0]["historical"] is True and row[0]["overdue"] is False     # 查詢全部時仍看得到，但標示補登、不算逾期


def test_receipt_calendar_push_skips_backfilled_cases(client, boss, flag_on, monkeypatch):
    import helpers
    from modules.case import receipt_calendar as RC
    calls = []
    monkeypatch.setattr(helpers, "push_event_upsert_for_module", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(helpers, "push_event_delete_for_module", lambda *a, **k: None)
    h = _hist(client, boss)
    n = _normal_won(client, boss)
    items = [{"id": "p9", "label": "尾款", "expectedReceiptDate": SOON, "received": False}]
    RC.push_after_commit(n, [], items)
    assert calls, "正對照：一般案件會推行事曆提醒"
    calls.clear()
    RC.push_after_commit(h, [], items)
    assert calls == []


def test_case_list_overdue_tabs_and_counts_skip_backfilled_cases(client, boss, flag_on):
    h = _hist(client, boss)
    n = _normal_won(client, boss)
    for flt in ("recv_overdue", "stage_overdue"):
        c = db.get_db()
        try:                                                    # 階段逾期需要一個已過期未完成的階段：兩張單都補上
            c.execute("UPDATE case_stages SET due_date=? WHERE quote_no IN (?,?)", (PAST, h, n))
            c.commit()
        finally:
            c.close()
        r = client.get("/api/quotations", headers=boss, params={flt: 1, "counts": 1}).json()
        nos = [i["quote_no"] for i in r["items"]]
        assert n in nos, "正對照：一般案件出現在 %s 分頁" % flt
        assert h not in nos, "補登單不出現在 %s 分頁" % flt
        cn = r["counts"]                                        # 稽核 M1：頁首徽章／分頁件數也要靜音
        key = "recvOverdue" if flt == "recv_overdue" else "stageOverdueCases"
        assert cn[key] == 1, "%s 件數只算一般案件，實得 %r" % (key, cn)
    assert client.get("/api/quotations", headers=boss, params={"counts": 1}).json()["counts"]["overdueStages"] == 1,         "頭部『逾期階段』數只算一般案件的 1 個階段（補登單的階段不算）"


# ── 4. 列表標示、PDF 標示、報表月份 ───────────────────────────────────────────
def test_list_marks_backfilled_quotes(client, boss, flag_on):
    h = _hist(client, boss)
    n = _normal_won(client, boss)
    items = {i["quote_no"]: i for i in client.get("/api/quotations", headers=boss, params={"limit": 200}).json()["items"]}
    assert items[h]["historical"] is True and items[n]["historical"] is False
    assert "hist_dj" not in items[h]


def test_pdf_html_shows_the_backfill_badge_only_for_backfilled_quotes():
    import pdf_gen
    base = {"quoteNo": "MQ-202607-001", "customerName": "客戶", "items": [], "quoteDate": "2026-07-15"}
    hist = dict(base, approval={"historical": True, "tiers": []})
    plain = pdf_gen._build_quote_html(base, {}, unapproved_status=None)
    marked = pdf_gen._build_quote_html(hist, {}, unapproved_status=None)
    assert "歷史補登" in marked and "歷史補登" not in plain


def test_report_month_follows_the_quote_date_not_the_entry_date(client, boss, flag_on):
    from modules.case.quotations import quote_won_month_map
    h = _hist(client, boss)
    c = db.get_db()
    try:
        assert quote_won_month_map(c).get(h) == "2026-07"
    finally:
        c.close()
    r = client.get("/api/quotations", headers=boss, params={"month": MONTH}).json()
    assert [i["quote_no"] for i in r["items"]] == [h]
    cur = datetime.now().strftime("%Y%m")
    assert h not in [i["quote_no"] for i in client.get("/api/quotations", headers=boss, params={"month": cur}).json()["items"]]


def test_hint_prefix_matches_what_the_endpoint_really_stores(client, boss, flag_on):
    """靜音的 SQL 提示依賴 data_json 的序列化形狀；補登與編輯後都要維持 historical 為 approval 的第一個鍵。"""
    from modules.case.quotations import HIST_APPROVAL_PREFIX, is_historical_json
    h = _hist(client, boss)
    c = db.get_db()
    try:
        txt = c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (h,)).fetchone()[0]
    finally:
        c.close()
    assert txt.startswith(HIST_APPROVAL_PREFIX) and is_historical_json(txt), "補登標記必須是 data_json 的開頭"
    from modules.case.api.quotations import _pin_backfill_marker
    q = {"approval": {"note": "x", "tiers": []}}
    _pin_backfill_marker(q, json.loads(txt))
    assert list(q["approval"])[0] == "historical"
    assert not is_historical_json('{"approval": {"historical": false}}') and not is_historical_json("{壞")


def _plant(no, nested):
    """模擬任何寫入路徑把自由欄位寫進 data_json（用戶端可帶任意 key）。"""
    c = db.get_db()
    try:
        d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()[0])
        d["notes_x"] = nested
        c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), no))
        c.execute("UPDATE case_stages SET due_date=? WHERE quote_no=?", (PAST, no))
        c.commit()
    finally:
        c.close()


def test_forged_nested_marker_cannot_hide_a_normal_overdue_quote(client, boss, flag_on):
    """稽核 M2：data 裡任何位置塞同樣結構的子字串，都不能讓一般案件從逾期分頁／件數消失（SQL 靜音只認文件開頭）。"""
    from modules.case.quotations import HIST_APPROVAL_PREFIX
    n = _normal_won(client, boss)
    _plant(n, {"approval": {"historical": True}})
    c = db.get_db()
    try:
        txt = c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (n,)).fetchone()[0]
    finally:
        c.close()
    assert '"approval": {"historical": true' in txt and not txt.startswith(HIST_APPROVAL_PREFIX), "前置：偽造子字串確實在、但不在開頭"
    r = client.get("/api/quotations", headers=boss, params={"stage_overdue": 1, "counts": 1}).json()
    assert n in [i["quote_no"] for i in r["items"]]
    assert r["counts"]["stageOverdueCases"] == 1 and r["counts"]["overdueStages"] == 1
    assert next(i for i in r["items"] if i["quote_no"] == n)["historical"] is False


def test_top_level_forged_marker_on_create_is_dropped_and_real_marker_leads_the_document(client, boss, flag_on):
    r = client.post("/api/quotations", headers=boss, json={"status": "已送出", "data": {
        "customerName": "偽造", "items": [], "approval": {"historical": True, "tiers": []}, "historical": {"x": 1}}})
    assert r.status_code in (200, 201), r.text
    no = r.json()["quote_no"]
    c = db.get_db()
    try:
        txt = c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()[0]
    finally:
        c.close()
    from modules.case.quotations import is_historical_json
    assert not is_historical_json(txt) and '"historical": true' not in txt


def test_pdf_badge_survives_a_non_dict_approval():
    import pdf_gen
    base = {"quoteNo": "MQ-202607-001", "customerName": "客戶", "items": [], "quoteDate": "2026-07-15"}
    for bad in ("x", ["a"], 5):
        assert "歷史補登" not in pdf_gen._build_quote_html(dict(base, approval=bad), {}, unapproved_status=None)


def test_enabled_without_any_ledger_record_is_treated_as_off(client, boss, flag_on, monkeypatch):
    """開關值是 1 但查不到『何時開啟』的紀錄 ⇒ 不信任（fail-closed）。"""
    from helpers import config_ledger as L
    from modules.case.api import quotations as Q
    monkeypatch.setattr(L, "history", lambda *a, **k: [])
    assert Q._backfill_state()["on"] is False
    j = client.get("/api/quotations/historical/config", headers=boss).json()
    assert j["available"] is False
    assert client.post("/api/quotations/historical", headers=boss, json=_body()).status_code == 403


def test_config_does_not_read_the_ledger_for_non_superadmin(client, make_user, flag_on, monkeypatch):
    from modules.case.api import quotations as Q
    adm = _login(client, make_user, "bf2_adm", role="admin")
    monkeypatch.setattr(Q, "_backfill_state", lambda: (_ for _ in ()).throw(AssertionError("不應讀取")))
    j = client.get("/api/quotations/historical/config", headers=adm).json()
    assert j["available"] is False and j["expires_at"] == ""


def test_warranty_reminders_are_not_muted_for_backfilled_cases():
    """保固是真實義務：保固提醒函式不得引用補登靜音（靜態鎖，避免日後誤把保固一併靜音）。"""
    import inspect
    import modules.case.case_deadlines as D
    for fn in (D._check_warranty_expiry, D._sync_warranty_calendar):
        src = inspect.getsource(fn)
        assert "historical" not in src and "_hist" not in src, fn.__name__
