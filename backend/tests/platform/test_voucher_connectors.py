"""IP-2 voucher.draft／voucher.account_check、IP-3 accounting.settings（INTEGRATION-POINTS.md）。

M07 獎金不再 import M06 的私有函式；M06 不在時：
  獎金核准／標記已發放**照常成立**，不產生傳票，而且**明說**「未產生傳票：會計模組未安裝」
  （回傳 notice、明細的 voucherNotice、設定頁 problems）——不可以默默略過。

① 契約：三個提供者存在；voucher.draft 真的寫出草稿＋分錄；account_check／settings 形狀
② 反向控制：同一條流程，有 M06 時產生傳票（正對照），拿掉三個提供者後獎金照走、沒有傳票、有明確提示
③ 邊界：M07 不再 import M06 的函式
"""
import pytest

from core import registry
from tests.test_bonus_case_api_2026_09_24 import (  # noqa: F401
    people, _seed_case, _create, _members_spec, _auth)

CAPS = ("voucher.draft", "voucher.account_check", "accounting.settings")
MISSING = "未產生傳票：會計模組未安裝"


def _db():
    import db
    return db.get_db()


def _award(no):
    conn = _db()
    try:
        return dict(conn.execute("SELECT * FROM bonus_case_awards WHERE quote_no=?", (no,)).fetchone())
    finally:
        conn.close()


def _voucher_count():
    conn = _db()
    try:
        return conn.execute("SELECT COUNT(*) FROM vouchers_all").fetchone()[0]
    finally:
        conn.close()


def _to_payout(client, people, no):
    _seed_case(no, net=100000)
    assert _create(client, people["bc_sa"], no, members=_members_spec()).status_code == 200
    assert client.post("/api/bonus/cases/%s/submit" % no, headers=_auth(people["bc_sa"])).status_code == 200
    return client.post("/api/bonus/cases/%s/approve" % no, headers=_auth(people["bc_sa2"]))


def _drop_accounting(monkeypatch):
    monkeypatch.setattr(registry, "_LEGACY_PROVIDERS",
                        {k: v for k, v in registry._LEGACY_PROVIDERS.items() if k[0] not in CAPS})
    assert all(registry.single_provider(c) is None for c in CAPS)


# ── ① 契約 ──────────────────────────────────────────────────────────────────

def test_contract_providers_exist_and_draft_really_writes(client):
    for c in CAPS:
        assert registry.single_provider(c) is not None, c
    ok, err = registry.single_provider("voucher.account_check")(_db(), "6111")
    assert ok and err == ""
    bad_ok, bad_err = registry.single_provider("voucher.account_check")(_db(), "99999999")
    assert not bad_ok and bad_err
    s = registry.single_provider("accounting.settings")()
    assert set(s) == {"bankAccounts", "defaultBankAccountCode"}          # 只公開這一小塊
    conn = _db()
    try:
        v = registry.single_provider("voucher.draft")(
            conn, voucher_date="2026-09-25", summary="IP-2 契約", created_by="t", now="2026-09-25T00:00:00",
            lines=[{"account_code": "6111", "summary": "x", "debit": 100, "credit": 0},
                   {"account_code": "2191", "summary": "x", "debit": 0, "credit": 100}])
        assert set(v) == {"id", "voucher_no"}
        row = conn.execute("SELECT status, category FROM vouchers_all WHERE id=?", (v["id"],)).fetchone()
        assert (row["status"], row["category"]) == ("草稿", "轉")
        assert conn.execute("SELECT COUNT(*) FROM voucher_lines WHERE voucher_id=?", (v["id"],)).fetchone()[0] == 2
        conn.rollback()                                   # 契約：不 commit，由呼叫端決定
    finally:
        conn.close()


# ── ② 反向控制 ───────────────────────────────────────────────────────────────

def test_with_accounting_the_flow_makes_vouchers(client, people):
    """正對照：同一條流程在 M06 在時確實產生兩張草稿——否則「沒產生」的斷言沒有意義。"""
    before = _voucher_count()
    r = _to_payout(client, people, "MQ-IP2-001")
    assert r.status_code == 200 and r.json()["voucher"], r.text
    d = client.get("/api/bonus/cases/MQ-IP2-001", headers=_auth(people["bc_cash"])).json()
    assert "voucherNotice" not in d
    r = client.post("/api/bonus/cases/MQ-IP2-001/mark-paid", headers=_auth(people["bc_cash"]))
    assert r.status_code == 200 and r.json()["voucher"], r.text
    assert _voucher_count() == before + 2


def test_without_accounting_bonus_still_works_and_says_so(client, people, monkeypatch):
    _drop_accounting(monkeypatch)
    before = _voucher_count()

    r = _to_payout(client, people, "MQ-IP2-002")                      # 核准 ⇒ 待發放
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "待發放" and body["voucher"] is None
    assert MISSING in body["notice"], body                            # 明說，不默默略過
    assert not _award("MQ-IP2-002")["accrual_voucher_id"]

    d = client.get("/api/bonus/cases/MQ-IP2-002", headers=_auth(people["bc_cash"])).json()
    assert d["bankAccounts"] == [] and MISSING in d["voucherNotice"]   # 畫面上看得到

    r = client.post("/api/bonus/cases/MQ-IP2-002/mark-paid", headers=_auth(people["bc_cash"]),
                    json={"bank_account_code": "1113"})               # 帶了銀行也不擋發放
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "已發放" and r.json()["voucher"] is None and MISSING in r.json()["notice"]
    assert _voucher_count() == before                                 # 一張都沒寫

    g = client.get("/api/bonus/cases/voucher-accounts", headers=_auth(people["bc_sa"])).json()
    assert g["problems"] and all("會計模組未安裝" in v for v in g["problems"].values())
    p = client.put("/api/bonus/cases/voucher-accounts", headers=_auth(people["bc_sa"]), json={"expense": "6111"})
    assert p.status_code == 400 and "會計模組未安裝" in p.text        # 驗證不了就不寫，並說明


# ── ③ 邊界 ──────────────────────────────────────────────────────────────────

def test_m07_no_longer_imports_m06_functions():
    from pathlib import Path
    backend = Path(__file__).resolve().parents[2]
    for rel in ("helpers/bonus_vouchers.py", "routers/bonus.py"):
        src = (backend / rel).read_text(encoding="utf-8")
        for bad in ("from routers.vouchers import", "from routers.accounting_export import",
                    "from helpers.voucher import"):
            assert bad not in src, (rel, bad)


def test_the_page_shows_the_voucher_notice():
    """「畫面要明確告知」：API 帶了 voucherNotice，頁面必須真的綁上去，不然使用者看不到。"""
    from pathlib import Path
    html = (Path(__file__).resolve().parents[3] / "frontend" / "pages" / "bonus.html").read_text(encoding="utf-8")
    assert 'x-text="detail.voucherNotice"' in html
