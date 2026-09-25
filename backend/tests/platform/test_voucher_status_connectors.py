"""IP-4 voucher.void_draft／voucher.status（INTEGRATION-POINTS.md）：M07 不再直接讀寫 M06 的 vouchers_all。

M06 不在時：退回照常、不作廢、保留連結並明說；明細仍列出連結的傳票並標「無法查詢」——
不可以默默略過，也不可以讓傳票從畫面上消失。M06 回來後，殘留的舊草稿不會被覆蓋成孤兒。

① 契約：void_draft 三種結果（voided／not_draft／gone）、status 形狀、都不 commit
② 反向控制：同一條流程，有 M06 時退回會作廢（正對照）；拿掉後不作廢、有提示、連結保留、明細標無法查詢
③ M06 回來後：殘留草稿 ⇒ 不另開一張、明說；已送審的舊連結照原行為另開新草稿
④ 邊界：M07 原始碼不再出現 vouchers_all
"""
from pathlib import Path

from core import registry
from tests.test_bonus_case_api_2026_09_24 import (  # noqa: F401
    people, _seed_case, _create, _members_spec, _auth)

CAPS = ("voucher.draft", "voucher.account_check", "accounting.settings", "voucher.void_draft", "voucher.status")


def _db():
    import db
    return db.get_db()


def _q(sql, *args):
    conn = _db()
    try:
        return conn.execute(sql, args).fetchone()
    finally:
        conn.close()


def _exec(sql, *args):
    conn = _db()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _accrual_id(no):
    return _q("SELECT accrual_voucher_id FROM bonus_case_awards WHERE quote_no=?", no)[0]


def _to_payout(client, people, no):
    _seed_case(no, net=100000)
    assert _create(client, people["bc_sa"], no, members=_members_spec()).status_code == 200
    assert client.post("/api/bonus/cases/%s/submit" % no, headers=_auth(people["bc_sa"])).status_code == 200
    return client.post("/api/bonus/cases/%s/approve" % no, headers=_auth(people["bc_sa2"]))


def _reapprove(client, people, no):
    assert client.post("/api/bonus/cases/%s/submit" % no, headers=_auth(people["bc_sa"])).status_code == 200
    return client.post("/api/bonus/cases/%s/approve" % no, headers=_auth(people["bc_sa2"]))


def _return(client, people, no):
    return client.post("/api/bonus/cases/%s/return" % no, headers=_auth(people["bc_sa"]), json={"reason": "調整"})


def _drop_accounting(monkeypatch):
    monkeypatch.setattr(registry, "_LEGACY_PROVIDERS",
                        {k: v for k, v in registry._LEGACY_PROVIDERS.items() if k[0] not in CAPS})
    assert all(registry.single_provider(c) is None for c in CAPS)


# ── ① 契約 ──────────────────────────────────────────────────────────────────

def test_contract_void_draft_and_status(client, people):
    _to_payout(client, people, "MQ-IP4-001")
    vid = _accrual_id("MQ-IP4-001")
    void, status = registry.single_provider("voucher.void_draft"), registry.single_provider("voucher.status")
    conn = _db()
    try:
        s = status(conn, vid)
        assert set(s) == {"id", "voucher_no", "status", "voided"} and s["status"] == "草稿" and not s["voided"]
        assert status(conn, 99999999) is None
        assert void(conn, 99999999, voided_by="t", now="n", reason="r")["result"] == "gone"
        conn.execute("UPDATE vouchers_all SET status='待審核' WHERE id=?", (vid,))
        assert void(conn, vid, voided_by="t", now="n", reason="r")["result"] == "not_draft"
        conn.execute("UPDATE vouchers_all SET status='草稿' WHERE id=?", (vid,))
        r = void(conn, vid, voided_by="t", now="n", reason="r")
        assert r["result"] == "voided" and r["voucher_no"] == s["voucher_no"]
        assert void(conn, vid, voided_by="t", now="n", reason="r")["result"] == "gone"   # 已作廢 ⇒ gone
        conn.rollback()                                                                   # 不 commit
    finally:
        conn.close()
    assert _q("SELECT voided_at FROM vouchers_all WHERE id=?", vid)[0] == ""


# ── ② 反向控制 ───────────────────────────────────────────────────────────────

def test_with_accounting_return_voids_the_draft(client, people):
    """正對照：同一條流程在 M06 在時確實作廢——否則「沒作廢」的斷言沒有意義。"""
    _to_payout(client, people, "MQ-IP4-010")
    vid = _accrual_id("MQ-IP4-010")
    r = _return(client, people, "MQ-IP4-010")
    assert r.status_code == 200 and not r.json()["notice"], r.text
    assert _q("SELECT voided_at FROM vouchers_all WHERE id=?", vid)[0] != ""
    assert not _accrual_id("MQ-IP4-010")


def test_without_accounting_return_keeps_the_link_and_says_so(client, people, monkeypatch):
    _to_payout(client, people, "MQ-IP4-011")                          # M06 在時產生草稿
    vid = _accrual_id("MQ-IP4-011")
    assert vid
    _drop_accounting(monkeypatch)

    r = _return(client, people, "MQ-IP4-011")
    assert r.status_code == 200 and r.json()["status"] == "草稿", r.text          # 退回照常
    assert "未作廢" in r.json()["notice"] and "會計模組未安裝" in r.json()["notice"]   # 明說
    assert _accrual_id("MQ-IP4-011") == vid                                        # 連結保留
    assert tuple(_q("SELECT voided_at, status FROM vouchers_all WHERE id=?", vid)) == ("", "草稿")  # 沒碰 M06 的表

    d = client.get("/api/bonus/cases/MQ-IP4-011", headers=_auth(people["bc_sa"])).json()
    v = [x for x in d["vouchers"] if x["kind"] == "accrual"]
    assert v and v[0]["unavailable"] and "會計模組未安裝" in v[0]["status"]       # 沒從畫面消失


# ── ③ M06 回來後 ─────────────────────────────────────────────────────────────

def test_leftover_draft_is_not_orphaned_when_accounting_returns(client, people, monkeypatch):
    _to_payout(client, people, "MQ-IP4-020")
    vid = _accrual_id("MQ-IP4-020")
    with monkeypatch.context() as m:
        _drop_accounting(m)
        _return(client, people, "MQ-IP4-020")                        # M06 不在：沒作廢、連結保留
    assert registry.single_provider("voucher.status") is not None     # M06 回來
    before = _q("SELECT COUNT(*) FROM vouchers_all")[0]
    r = _reapprove(client, people, "MQ-IP4-020")
    assert r.status_code == 200 and r.json()["status"] == "待發放", r.text
    assert r.json()["voucher"] is None and "尚未作廢" in r.json()["notice"]
    assert _q("SELECT COUNT(*) FROM vouchers_all")[0] == before       # 不另開一張
    assert _accrual_id("MQ-IP4-020") == vid                            # 不覆蓋


def test_submitted_old_link_still_gets_a_fresh_draft(client, people):
    """原行為不變：舊連結已送審（不會被作廢）⇒ 再次進入待發放照常另開新草稿。"""
    _to_payout(client, people, "MQ-IP4-021")
    first = _accrual_id("MQ-IP4-021")
    _exec("UPDATE vouchers_all SET status='待審核' WHERE id=?", first)
    _return(client, people, "MQ-IP4-021")
    assert _accrual_id("MQ-IP4-021") == first
    r = _reapprove(client, people, "MQ-IP4-021")
    assert r.json()["voucher"], r.text
    assert _accrual_id("MQ-IP4-021") not in (0, first)


# ── ④ 邊界 ──────────────────────────────────────────────────────────────────

def test_m07_no_longer_touches_vouchers_all():
    backend = Path(__file__).resolve().parents[2]
    for rel in ("helpers/bonus_vouchers.py", "routers/bonus.py"):
        assert "vouchers_all" not in (backend / rel).read_text(encoding="utf-8"), rel


def test_the_page_marks_unavailable_vouchers():
    html = (Path(__file__).resolve().parents[3] / "frontend" / "pages" / "bonus.html").read_text(encoding="utf-8")
    assert 'x-show="v.unavailable"' in html and 'x-show="!v.unavailable"' in html
