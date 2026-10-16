# -*- coding: utf-8 -*-
"""補登歷史報價單 L0（T69）——契約題。設計 D:/Claude-pm/reports/design-backfill-quote-t69.md（§9 裁示 1–4）。

證明：
1. 序號月份：用戶端帶舊月份單號建立時，`quote_seq` 記在**單號自己的月份**，不墊高「本月」（正對照：修正前此題為紅）。
2. 一般新單（不帶單號）行為不變：單號為本月、序號 +1。
3. 送審失敗回收只動單號所屬月份，不動本月。
4. 旗標群組 `quote_backfill.enabled`：預設 0＝關；立即生效（不經確認期間）。
5. 能力鍵 `case.quote_backfill.create`：存在、不可委派、沒有任何角色種子（只有最高管理者）。
"""
import re
from datetime import datetime

OLD_MONTH = "202007"          # 一定早於本月，且不與其他測試的月份混用


def _boss(client, make_user, name="qbf_boss"):
    u, p = make_user(name, "Lay-Pass-123", role="superadmin")[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _seq(month):
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT seq FROM quote_seq WHERE month=?", (month,)).fetchone()
    finally:
        conn.close()
    return row[0] if row else 0


def _create(client, h, no=None, status="草稿"):
    data = {"customerName": "補登測試", "projectName": "序號月份", "items": []}
    body = {"status": status, "data": data}
    if no:
        body["quote_no"] = no
    return client.post("/api/quotations", headers=h, json=body)


def _qn(r):
    assert r.status_code in (200, 201), r.text
    return r.json().get("quote_no") or r.json().get("quoteNo")


# ── 1. 正對照：舊月份單號不可墊高本月序號 ───────────────────────────────────
def test_old_month_client_number_reserves_its_own_month_not_current(client, make_user):
    h = _boss(client, make_user)
    cur = datetime.now().strftime("%Y%m")
    before_cur = _seq(cur)
    no = "MQ-%s-005" % OLD_MONTH
    assert _qn(_create(client, h, no)) == no
    assert _seq(OLD_MONTH) == 5                      # 記在單號自己的月份
    assert _seq(cur) == before_cur                   # 本月序號沒被墊高（修正前會變成 5）
    nxt = _qn(_create(client, h))
    assert nxt.startswith("MQ-%s-" % cur)
    assert int(nxt.rsplit("-", 1)[1]) == before_cur + 1


# ── 2. 一般新單不變 ─────────────────────────────────────────────────────────
def test_normal_new_quote_number_unchanged(client, make_user):
    h = _boss(client, make_user, "qbf_boss2")
    cur = datetime.now().strftime("%Y%m")
    before = _seq(cur)
    no = _qn(_create(client, h))
    assert re.fullmatch(r"MQ-%s-\d{3}" % cur, no)
    assert int(no.rsplit("-", 1)[1]) == before + 1
    assert _seq(cur) == before + 1


# ── 3. 舊月單號：後續同月續號 ───────────────────────────────────────────────
def test_old_month_sequence_continues_from_existing_max(client, make_user):
    h = _boss(client, make_user, "qbf_boss3")
    month = "202008"
    assert _qn(_create(client, h, "MQ-%s-003" % month)) == "MQ-%s-003" % month
    import db
    from modules.case.api import quotations as Q
    conn = db.get_db()
    try:
        assert Q._peek_next_no(conn, month) == "MQ-%s-004" % month
    finally:
        conn.close()


# ── 4. 旗標群組 ─────────────────────────────────────────────────────────────
def test_backfill_flag_default_off_and_group_registered():
    from helpers import settings_registry as SR
    assert int(SR.get("quote_backfill", "enabled")) == 0
    assert int(SR.get("quote_backfill", "earliest_month")) == 202001


def test_backfill_flag_takes_effect_immediately(client):
    import db
    from helpers import settings_registry as SR
    conn = db.get_db()
    try:
        SR.publish("quote_backfill", {"enabled": 1}, reason="測試：立即生效", user="qbf_test", conn=conn)
        conn.commit()
        SR.invalidate("quote_backfill")
        assert int(SR.get("quote_backfill", "enabled", conn=conn)) == 1
        SR.publish("quote_backfill", {"enabled": 0}, reason="測試：還原", user="qbf_test", conn=conn)
        conn.commit()
        SR.invalidate("quote_backfill")
        assert int(SR.get("quote_backfill", "enabled", conn=conn)) == 0
    finally:
        conn.close()


# ── 5. 能力鍵 ───────────────────────────────────────────────────────────────
def test_backfill_capability_is_superadmin_only_and_not_delegable():
    from core import capabilities as CAP
    CAP.reset_cache()
    c = CAP.get("case.quote_backfill.create")
    assert c is not None, CAP.problems()
    assert c.delegable is False
    assert not c.roles and not c.modules             # 沒有任何角色種子
    assert c.legacy == ("superadmin",)
    assert not CAP.problems()


# ── 6. 送審失敗的回收路徑也要用單號自己的月份（稽核 r1 建議；修正前為紅）──────────
def test_failed_submit_rollback_recomputes_the_numbers_own_month(client, make_user, monkeypatch):
    from modules.case.api import quotations as Q
    h = _boss(client, make_user, "qbf_boss4")
    month = "202009"
    cur = datetime.now().strftime("%Y%m")
    assert _qn(_create(client, h, "MQ-%s-002" % month)) == "MQ-%s-002" % month
    import db
    conn = db.get_db()
    try:                                               # 把該月序號墊到 9：只有「回收時依該月份實際剩下的單據重算」才會回到 2
        conn.execute("UPDATE quote_seq SET seq=9 WHERE month=?", (month,))
        conn.commit()
    finally:
        conn.close()
    before_cur = _seq(cur)

    def boom(*a, **k):
        raise RuntimeError("模擬建不出簽核流程")
    monkeypatch.setattr(Q, "_build_approval_tiers_and_notify", boom)
    try:
        client.post("/api/quotations", headers=h, json={
            "status": "待審核", "quote_no": "MQ-%s-005" % month,
            "data": {"customerName": "補登測試", "projectName": "回收", "items": []}})
    except Exception:                                  # noqa: BLE001 — TestClient 會把伺服器例外重新拋出
        pass
    conn = db.get_db()
    try:
        assert conn.execute("SELECT 1 FROM quotations WHERE quote_no=?", ("MQ-%s-005" % month,)).fetchone() is None   # 失敗的那張已收回
        assert conn.execute("SELECT 1 FROM quotations WHERE quote_no=?", ("MQ-%s-002" % month,)).fetchone() is not None
    finally:
        conn.close()
    assert _seq(month) == 2                            # 依該月份實際剩下的單據重算（修正前：回收只重算本月，該月份維持 9）
    assert _seq(cur) == before_cur                     # 本月不受影響


# ── 7. earliest_month 的月份必須是合法年月 ────────────────────────────────────
def test_earliest_month_rejects_invalid_month_and_year():
    from helpers import settings_registry as SR
    for bad in (202000, 202013, 202099, 199912, 210001, 20201):
        probs = SR.validate_values("quote_backfill", {"enabled": 0, "earliest_month": bad})
        assert probs, "應拒絕 %r" % bad
    for good in (202001, 202012, 209912, 202607):
        assert not SR.validate_values("quote_backfill", {"enabled": 0, "earliest_month": good}), good
