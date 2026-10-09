"""舊「獎金項目＋分潤單」流程停用（SPEC-BONUS §十一／§11.7，2026-09-24）。

使用者：「上一次開發的內容我無法接受」「重做成新流程」；舊單「舊的都是開發機測試用，直接作廢」。
⇒ 舊的**寫入**端點停用（第 49 班起整個移除，原本回 410）；**不寫入任何東西**；讀取端點與群組維護照舊。
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
def test_legacy_write_endpoint_is_removed_and_writes_nothing(client, make_user, path):
    """第 49 班（使用者裁示）：8 條 410 墓碑端點整個移除 ⇒ 這些 POST 不再有路由（404／405），仍然不寫任何東西。"""
    u, p = make_user(username="lg_sa", role="superadmin")
    tok = _login(client, u, p)
    before = _counts()
    r = client.post(path, headers={"Authorization": f"Bearer {tok}"},
                    json={"name": "x", "quote_no": "MQ-X", "reason": "x"})
    assert r.status_code in (404, 405), (path, r.status_code, r.text)
    assert r.status_code != 410, "墓碑端點應已移除，不是回 410"
    assert _counts() == before, "移除後不可以寫入任何東西"


def test_no_post_route_is_registered_for_the_retired_paths(client):
    """路由表層級的反向控制：8 條退役路徑沒有任何 POST 路由（放寬到「路徑模板」比對，/awards/1/submit ⇒ /awards/{award_id}/submit）。
    正對照：GET /api/bonus/awards 與 /items 仍在（讀取端點保留）。"""
    import re
    ops = {}
    for path, methods in client.app.openapi()["paths"].items():
        ops[path] = {m.upper() for m in methods}
    retired = {re.sub(r"/awards/1/", "/awards/{award_id}/", p) for p in RETIRED}
    for path in retired:
        assert "POST" not in ops.get(path, set()), (path, ops.get(path))
    assert "GET" in ops["/api/bonus/awards"] and "GET" in ops["/api/bonus/items"]


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
