"""舊「獎金項目＋分潤單」流程停用（SPEC-BONUS §十一／§11.7，2026-09-24）。

使用者：「上一次開發的內容我無法接受」「重做成新流程」；舊單「舊的都是開發機測試用，直接作廢」。
⇒ 舊的**寫入**端點一律 410，說明改用新頁面；**不寫入任何東西**；讀取端點與群組維護照舊。
（不以 migration 作廢任何資料——migration 會在正式機執行。）
"""
import pytest


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _counts():
    import db
    conn = db.get_db()
    try:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("bonus_items", "bonus_awards", "bonus_award_lines", "bonus_award_edit_log")}
    finally:
        conn.close()


RETIRED = [
    "/api/bonus/items", "/api/bonus/awards",
    "/api/bonus/awards/1/submit", "/api/bonus/awards/1/approve", "/api/bonus/awards/1/reject",
    "/api/bonus/awards/1/mark-paid", "/api/bonus/awards/1/void", "/api/bonus/awards/1/recall",
]


@pytest.mark.parametrize("path", RETIRED)
def test_legacy_write_endpoint_is_gone_and_writes_nothing(client, make_user, path):
    u, p = make_user(username="lg_sa", role="superadmin")
    tok = _login(client, u, p)
    before = _counts()
    r = client.post(path, headers={"Authorization": f"Bearer {tok}"},
                    json={"name": "x", "quote_no": "MQ-X", "reason": "x"})
    assert r.status_code == 410, (path, r.status_code, r.text)
    assert "獎金分潤" in r.json()["detail"] and "停用" in r.json()["detail"]
    assert _counts() == before, "410 之前不可以寫入任何東西"


def test_legacy_read_and_group_endpoints_still_work(client, make_user):
    u, p = make_user(username="lg_sa2", role="superadmin")
    h = {"Authorization": f"Bearer {_login(client, u, p)}"}
    assert client.get("/api/bonus/awards", headers=h).status_code == 200
    assert client.get("/api/bonus/items", headers=h).status_code == 200
    r = client.post("/api/bonus/groups", headers=h, json={"name": "後勤組"})
    assert r.status_code in (200, 201), r.text
    assert client.get("/api/bonus/groups", headers=h).status_code == 200


def test_new_page_does_not_call_legacy_write_endpoints():
    """新頁面只打 /api/bonus/cases（與群組、使用者清單），不再打舊的寫入端點。"""
    from pathlib import Path
    js = (Path(__file__).resolve().parents[4] / "frontend" / "js" / "bonus.js").read_text(encoding="utf-8")
    for old in ("/api/bonus/awards", "/api/bonus/items"):
        assert old not in js, f"新頁面還在打舊端點 {old}"
    assert "/api/bonus/cases" in js
