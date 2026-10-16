# -*- coding: utf-8 -*-
"""補登歷史報價單 L1（T69）——後端端點契約題。設計 D:/Claude-pm/reports/design-backfill-quote-t69.md §9、§10。

端點：POST /api/quotations/historical（最高管理者、旗標開、過去月份、必填原因、已送出＋已成案、不偽造簽核）。
每題的「紅」是對未實作端點／未開例外的現況（404／403）成立；負向題另以「列數、序號都沒變」鎖住副作用。
"""
import threading
from datetime import datetime

import pytest

MONTH = "202607"
CUR = datetime.now().strftime("%Y%m")


def _login(client, make_user, name, role="superadmin"):
    u, p = make_user(name, "Lay-Pass-123", role=role)[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


@pytest.fixture
def boss(client, make_user):
    return _login(client, make_user, "bf1_boss")


@pytest.fixture
def flag_on():
    import db
    from helpers import settings_registry as SR

    def _set(v=1, **extra):
        conn = db.get_db()
        try:
            SR.publish("quote_backfill", dict({"enabled": v}, **extra), reason="測試", user="bf1_test", conn=conn)
            conn.commit()
            SR.invalidate("quote_backfill")
        finally:
            conn.close()
    _set(1)
    yield _set
    _set(0)


def _body(date="2026-07-15", no=None, reason="補登 7 月舊案件，紙本單據遺失重建", **kw):
    data = {"customerName": "補登客戶", "projectName": "歷史案件", "quoteDate": date, "items": []}
    data.update(kw.pop("data", {}))
    b = {"data": data, "reason": reason}
    if no:
        b["quote_no"] = no
    b.update(kw)
    return b


def _post(client, h, **kw):
    return client.post("/api/quotations/historical", headers=h, json=_body(**kw))


def _seq(month):
    import db
    conn = db.get_db()
    try:
        r = conn.execute("SELECT seq FROM quote_seq WHERE month=?", (month,)).fetchone()
        return r[0] if r else 0
    finally:
        conn.close()


def _count(where="1=1", args=()):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT COUNT(*) FROM quotations WHERE " + where, args).fetchone()[0]
    finally:
        conn.close()


def _row(no):
    import db, json
    conn = db.get_db()
    try:
        r = conn.execute("SELECT * FROM quotations WHERE quote_no=?", (no,)).fetchone()
        return (dict(r), json.loads(r["data_json"])) if r else (None, None)
    finally:
        conn.close()


def _audits(action):
    import db, json
    conn = db.get_db()
    try:
        return [dict(r, detail=json.loads(r["detail"] or "{}")) for r in
                conn.execute("SELECT * FROM audit_log WHERE action=? ORDER BY id", (action,)).fetchall()]
    finally:
        conn.close()


# ── 1. 正常補登 ─────────────────────────────────────────────────────────────
def test_backfill_creates_closed_deal_numbered_by_its_own_month(client, boss, flag_on):
    cur_before = _seq(CUR)
    r = _post(client, boss)
    assert r.status_code == 201, r.text
    no = r.json()["quote_no"]
    assert no == "MQ-%s-001" % MONTH                       # 該月沒有單 ⇒ 001
    row, d = _row(no)
    assert row["status"] == "已送出" and row["deal_tag"] == "已成案" and d["dealTag"] == "已成案"
    ap = d["approval"]
    assert ap["historical"] is True and ap["tiers"] == []
    assert ap["recordedBy"] == "bf1_boss" and len(ap["reason"]) >= 5
    # 不偽造簽核：沒有任何簽核人／簽核時間欄位
    assert not [k for k in ap if k in ("approvedBy", "approvedAt", "approvedByDisplay", "signedAt")]
    assert row["quote_date"] == "2026-07-15"
    assert row["created_at"][:7] == datetime.now().strftime("%Y-%m")   # created_at 是真實時間，不偽造
    assert _seq(CUR) == cur_before                         # 本月序號不動
    assert _seq(MONTH) == 1


def test_backfill_continues_from_existing_max_of_that_month(client, boss, flag_on):
    assert _post(client, boss, no="MQ-%s-004" % MONTH).status_code == 201
    r = _post(client, boss)
    assert r.json()["quote_no"] == "MQ-%s-005" % MONTH


def test_client_supplied_original_number_is_honoured_and_reserves_its_month(client, boss, flag_on):
    cur_before = _seq(CUR)
    r = _post(client, boss, date="2026-08-03", no="MQ-202608-007")
    assert r.status_code == 201 and r.json()["quote_no"] == "MQ-202608-007"
    assert _seq("202608") == 7 and _seq(CUR) == cur_before


def test_profit_basis_is_stamped_as_current_basis(client, boss, flag_on):
    no = _post(client, boss).json()["quote_no"]
    _, d = _row(no)
    h = d["historical"]
    assert h["quoteDate"] == "2026-07-15" and h["basisNote"] == "補登案件，以現行口徑計算"
    assert d["statusLog"][-1]["to"] == "已成案" and "補登" in d["statusLog"][-1]["note"]


# ── 2. 守門：旗標、身分 ─────────────────────────────────────────────────────
def test_flag_off_refuses_and_changes_nothing(client, boss):
    n = _count()
    r = _post(client, boss)
    assert r.status_code == 403 and "補登" in r.text
    assert _count() == n and _seq(MONTH) == 0


@pytest.mark.parametrize("role", ["admin", "user"])
def test_non_superadmin_is_refused_even_with_flag_on(client, make_user, flag_on, role):
    h = _login(client, make_user, "bf1_" + role, role=role)
    n = _count()
    r = _post(client, h)
    assert r.status_code == 403
    assert _count() == n and _seq(MONTH) == 0


# ── 3. 日期 ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("date", [
    datetime.now().strftime("%Y-%m-01"),                   # 本月
    datetime.now().strftime("%Y-%m-%d"),                   # 今天
    "2099-01-15",                                          # 未來
    "2019-12-31",                                          # 早於 2020-01
    "2026-13-01", "2026-02-30", "", "abc",                 # 不是日期
])
def test_dates_outside_past_months_window_are_refused(client, boss, flag_on, date):
    n = _count()
    r = _post(client, boss, date=date)
    assert r.status_code == 400, (date, r.text)
    assert _count() == n


def test_earliest_month_setting_is_enforced(client, boss, flag_on):
    flag_on(1, earliest_month=202606)
    assert _post(client, boss, date="2026-05-31").status_code == 400
    assert _post(client, boss, date="2026-06-01").status_code == 201


# ── 4. 原因 ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("reason", ["", "   ", "短", "1234"])
def test_reason_is_mandatory(client, boss, flag_on, reason):
    n = _count()
    assert _post(client, boss, reason=reason).status_code == 400
    assert _count() == n and _seq(MONTH) == 0


# ── 5. 嚴格單號驗證（稽核 hichan-49 追加）───────────────────────────────────
@pytest.mark.parametrize("no", [
    "MQ-209913-001",       # 月份 13
    "MQ-202013-001",
    "MQ-202000-001",       # 月份 00
    "MQ-199912-001",       # 年份不在 2000–2099 / 早於最早月
    "MQ-202007-000",       # 序號 0
    "MQ-202007-1000",
    "MQ-202007-01",
    "mq-202007-001",
    "MQ-202007-???",
    " ../MQ-202007-001",
])
def test_malformed_or_impossible_numbers_are_rejected_not_silently_reassigned(client, boss, flag_on, no):
    n, cur_before = _count(), _seq(CUR)
    r = _post(client, boss, no=no)
    assert r.status_code == 400, (no, r.text)
    assert _count() == n and _seq(MONTH) == 0 and _seq(CUR) == cur_before


def test_number_month_must_match_quote_date_month(client, boss, flag_on):
    n = _count()
    assert _post(client, boss, date="2026-07-15", no="MQ-202608-001").status_code == 400
    assert _count() == n and _seq("202608") == 0


def test_number_in_current_or_future_month_is_rejected(client, boss, flag_on):
    n = _count()
    assert _post(client, boss, no="MQ-%s-001" % CUR).status_code == 400
    assert _post(client, boss, no="MQ-209912-001").status_code == 400
    assert _count() == n


def test_duplicate_old_month_number_is_409_and_never_falls_back_to_current_month(client, boss, flag_on):
    assert _post(client, boss, no="MQ-%s-003" % MONTH).status_code == 201
    n, cur_before, cur_rows = _count(), _seq(CUR), _count("quote_no LIKE ?", ("MQ-%s-%%" % CUR,))
    r = _post(client, boss, no="MQ-%s-003" % MONTH)
    assert r.status_code == 409, r.text
    assert _count() == n                                    # 沒有新增任何一筆
    assert _count("quote_no LIKE ?", ("MQ-%s-%%" % CUR,)) == cur_rows   # 絕不改派成本月單號
    assert _seq(CUR) == cur_before


# ── 6. 稽核 ─────────────────────────────────────────────────────────────────
def test_audit_records_who_why_business_date_and_real_created_at(client, boss, flag_on):
    no = _post(client, boss, reason="年度結算前補登 7 月舊案").json()["quote_no"]
    a = [x for x in _audits("quotation.historical_backfill") if x["target_id"] == no]
    assert len(a) == 1
    d = a[0]["detail"]
    assert a[0]["username"] == "bf1_boss"
    assert d["reason"] == "年度結算前補登 7 月舊案"
    assert d["quoteDate"] == "2026-07-15" and d["month"] == MONTH and d["historical"] is True
    assert d["createdAt"][:10] == datetime.now().strftime("%Y-%m-%d") and d["createdAt"] != d["quoteDate"]
    assert d["seqBefore"] == 0


def test_refusals_are_audited(client, boss, make_user):
    _post(client, boss)                                     # 旗標關
    assert [x for x in _audits("quotation.historical_denied") if x["username"] == "bf1_boss"]


# ── 7. 不發通知 ─────────────────────────────────────────────────────────────
def test_no_activity_notification_is_sent(client, boss, flag_on, monkeypatch):
    from modules.case.api import quotations as Q
    sent = []
    monkeypatch.setattr(Q, "notify_module_activity", lambda *a, **k: sent.append(a))
    monkeypatch.setattr(Q, "_notify", lambda *a, **k: sent.append(a))
    assert _post(client, boss).status_code == 201
    assert sent == []


# ── 8. 回收（rollback）覆蓋 ─────────────────────────────────────────────────
def test_failure_after_insert_leaves_no_row_and_no_sequence_change(client, boss, flag_on, monkeypatch):
    from modules.case.api import quotations as Q
    assert _post(client, boss, no="MQ-%s-002" % MONTH).status_code == 201
    seq_m, seq_c, n = _seq(MONTH), _seq(CUR), _count()

    def boom(*a, **k):
        raise RuntimeError("模擬建立後續步驟失敗")
    with monkeypatch.context() as m:
        m.setattr(Q, "_sync_json_stages_to_table", boom)
        try:
            r = _post(client, boss, data={"caseRecord": {"stages": [{"id": "s1", "name": "x"}]}})
            assert r.status_code >= 400
        except RuntimeError:                                # TestClient 會把未處理例外直接拋出
            pass
    assert _count() == n                                    # 單據沒留下
    assert _seq(MONTH) == seq_m and _seq(CUR) == seq_c      # 該月與本月序號都不變
    assert _post(client, boss).json()["quote_no"] == "MQ-%s-003" % MONTH   # 之後續號正常


# ── 9. 併發 ─────────────────────────────────────────────────────────────────
def test_concurrent_backfills_of_the_same_month_get_distinct_numbers(client, boss, flag_on):
    out = []

    def go():
        out.append(_post(client, boss))
    ts = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    ok = [r.json()["quote_no"] for r in out if r.status_code == 201]
    assert len(ok) == len(set(ok)) and len(ok) >= 1
    assert all(r.status_code in (201, 409) for r in out), [r.text for r in out]
    assert _seq(MONTH) == len(ok)


# ── 10. 作廢／刪除：僅最高管理者、進暫存區、單號不回收 ───────────────────────
def _bin_id(no):
    import db
    conn = db.get_db()
    try:
        r = conn.execute("SELECT id FROM recycle_bin WHERE entity_type='quotation' AND entity_id=? ORDER BY id DESC", (no,)).fetchone()
        return r[0] if r else None
    finally:
        conn.close()


def test_superadmin_can_delete_backfilled_quote_to_bin_and_number_is_not_reused(client, boss, flag_on):
    no = _post(client, boss).json()["quote_no"]
    r = client.delete("/api/quotations/" + no, headers=boss)
    assert r.status_code == 200, r.text
    assert _row(no)[0] is None and _bin_id(no)
    assert [x for x in _audits("quotation.delete") if x["target_id"] == no]
    assert _post(client, boss).json()["quote_no"] == "MQ-%s-002" % MONTH      # 001 不重用
    rr = client.post("/api/recycle-bin/%s/restore" % _bin_id(no), headers=boss)
    assert rr.status_code == 200, rr.text
    assert _row(no)[0]["status"] == "已送出"                                     # 復原回到原單號


def test_non_superadmin_cannot_delete_backfilled_quote(client, boss, make_user, flag_on):
    no = _post(client, boss).json()["quote_no"]
    adm = _login(client, make_user, "bf1_adm", role="admin")
    assert client.delete("/api/quotations/" + no, headers=adm).status_code == 403
    assert _row(no)[0] is not None


def test_ordinary_non_draft_quote_still_cannot_be_deleted(client, boss):
    r = client.post("/api/quotations", headers=boss, json={"status": "待審核", "data": {"customerName": "一般", "items": []}})
    if r.status_code not in (200, 201):                     # 送審環境不齊時改用已送出直建
        r = client.post("/api/quotations", headers=boss, json={"status": "已送出", "data": {"customerName": "一般", "items": []}})
    assert r.status_code in (200, 201), r.text
    no = r.json()["quote_no"]
    assert client.delete("/api/quotations/" + no, headers=boss).status_code == 403
    assert _row(no)[0] is not None


# ── 11. 補登標記只由專用端點寫入（PM 裁示 2026-10-17）──────────────────────────
FORGED = {"approval": {"historical": True, "tiers": [], "recordedBy": "x", "reason": "偽造"},
          "historical": {"basisNote": "偽造"}}


@pytest.mark.parametrize("role", ["admin", "superadmin"])
def test_normal_create_drops_client_sent_backfill_marker(client, make_user, role):
    h = _login(client, make_user, "bf1_forge_" + role, role=role)
    r = client.post("/api/quotations", headers=h, json={"status": "草稿", "data": dict({"customerName": "偽造", "items": []}, **FORGED)})
    assert r.status_code in (200, 201), r.text
    _, d = _row(r.json()["quote_no"])
    assert "historical" not in (d.get("approval") or {}) and "historical" not in d


def test_forged_marker_does_not_unlock_superadmin_void(client, make_user):
    h = _login(client, make_user, "bf1_forge_void")
    r = client.post("/api/quotations", headers=h, json={"status": "已送出", "data": dict({"customerName": "偽造", "items": []}, **FORGED)})
    assert r.status_code in (200, 201), r.text
    no = r.json()["quote_no"]
    assert client.delete("/api/quotations/" + no, headers=h).status_code == 403
    assert _row(no)[0] is not None


def test_update_drops_client_marker_on_ordinary_draft(client, make_user):
    h = _login(client, make_user, "bf1_forge_upd")
    no = client.post("/api/quotations", headers=h, json={"status": "草稿", "data": {"customerName": "一般", "items": []}}).json()["quote_no"]
    r = client.put("/api/quotations/" + no, headers=h, json={"status": "草稿", "data": dict({"customerName": "一般2", "items": []}, **FORGED)})
    assert r.status_code == 200, r.text
    _, d = _row(no)
    assert "historical" not in (d.get("approval") or {}) and "historical" not in d


def test_pin_marker_keeps_real_marker_and_drops_forged_one():
    from modules.case.api.quotations import _pin_backfill_marker
    old = {"approval": {"historical": True, "recordedBy": "boss", "reason": "原因原因"}, "historical": {"basisNote": "n"}}
    q = {"approval": {"isEditApproval": True}}
    _pin_backfill_marker(q, old)                           # 現值是補登單 ⇒ 編輯後仍是
    assert q["approval"]["historical"] is True and q["approval"]["recordedBy"] == "boss" and q["historical"] == {"basisNote": "n"}
    q2 = dict(FORGED, approval=dict(FORGED["approval"]))
    _pin_backfill_marker(q2, {"approval": {"status": "pending"}})   # 現值不是 ⇒ 丟掉
    assert "historical" not in q2["approval"] and "historical" not in q2
