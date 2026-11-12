"""「開始使用」7 步清單（批次「開始使用清單面板」，2026-11-13）：自動偵測、人工旗標、權限、只讀、單步失敗隔離、效能、頁面靜態檢查。"""
import json
import time
from pathlib import Path

import pytest

from helpers import getting_started as GS

_MAKE_USER_DEFAULT_ROLE = "superadmin"
FRONT = Path(__file__).resolve().parent.parent.parent / "frontend"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _sql(sql, args=()):
    from db import get_db
    conn = get_db()
    try:
        cur = conn.execute(sql, args)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _scalar(sql, args=()):
    from db import get_db
    conn = get_db()
    try:
        return conn.execute(sql, args).fetchone()[0]
    finally:
        conn.close()


@pytest.fixture
def su(client, make_user):
    u, p = make_user(username="gs_root", role="superadmin")
    return _login(client, u, p)


def _get(client, su):
    r = client.get("/api/getting-started", headers=su)
    assert r.status_code == 200, r.text
    return r.json()


def _st(res):
    return {s["id"]: s for s in res["steps"]}


def test_seven_steps_in_order_with_the_three_fixed_facts(client, su):
    res = _get(client, su)
    assert [s["id"] for s in res["steps"]] == ["company", "quote_style", "people", "email", "backup", "line", "import"]
    assert [s["n"] for s in res["steps"]] == list(range(1, 8))
    for s in res["steps"]:
        assert s["minutes"] and s["prepare"] and s["confirm"] and s["why"] and s["href"].endswith(".html") and s["link"]
        assert s["status"] in ("done", "todo", "skipped")
    assert res["progress"]["total"] == 7 and set(res["progress"]) == {"done", "skipped", "total"}
    assert res["next"] is None or res["next"]["id"] in GS.STEP_IDS


def test_only_superadmin_may_read_or_write(client, make_user):
    ua, pa = make_user(username="gs_adm", role="admin")
    us, ps = make_user(username="gs_sales", role="sales")
    for u, p in ((ua, pa), (us, ps)):
        h = _login(client, u, p)
        assert client.get("/api/getting-started", headers=h).status_code == 403
        assert client.put("/api/getting-started/steps/email", headers=h, json={"action": "skip"}).status_code == 403
    assert client.get("/api/getting-started").status_code == 401


def test_email_step_follows_the_successful_test_mail_audit(client, su):
    assert _st(_get(client, su))["email"]["status"] == "todo"
    _sql("INSERT INTO audit_log (at, username, action) VALUES (?,?,?)", ("2026-11-13T09:30:00", "gs_root", GS.EMAIL_TEST_ACTION))
    s = _st(_get(client, su))["email"]
    assert s["status"] == "done" and s["auto"] is True and "2026-11-13 09:30" in s["detail"]


def test_backup_step_follows_a_successful_backup(client, su):
    assert _st(_get(client, su))["backup"]["status"] == "todo"
    _sql("INSERT INTO audit_log (at, username, action) VALUES (?,?,?)", ("2026-11-13T03:00:00", "system", "backup.sqlite_snapshot"))
    assert _st(_get(client, su))["backup"]["status"] == "done"


def test_people_step_needs_staff_and_a_clean_org_check(client, make_user, su):
    s = _st(_get(client, su))["people"]
    assert s["status"] == "todo" and "還沒有建立同仁帳號" in s["detail"]           # 全新安裝：沒有缺口也不算完成
    u, _ = make_user(username="gs_staff", role="sales")
    s = _st(_get(client, su))["people"]
    assert s["status"] == "todo" and "還有" in s["detail"] and s["href"] in ("users.html", "org-structure.html")
    div = _sql("INSERT INTO divisions (name, created_at) VALUES ('gs-處','2026-01-01')")
    mgr, _ = make_user(username="gs_mgr", role="admin")
    mid = _scalar("SELECT id FROM users WHERE username=?", (mgr,))
    dep = _sql("INSERT INTO departments (division_id, name, manager_user_id, created_at) VALUES (?,?,?,'2026-01-01')", (div, "gs-部", mid))
    _sql("UPDATE users SET department_id=? WHERE username IN (?,?)", (dep, u, mgr))
    assert _st(_get(client, su))["people"]["status"] == "todo"                    # 還沒人擔任財務
    make_user(username="gs_fin", role="finance")
    _sql("UPDATE users SET department_id=? WHERE username='gs_fin'", (dep,))
    assert _st(_get(client, su))["people"]["status"] == "done"


def test_line_step_needs_enabled_and_at_least_one_bound_user(client, make_user, su, monkeypatch):
    from helpers import line_notify as ln
    u, _ = make_user(username="gs_line_user", role="sales")
    monkeypatch.setattr(ln, "enabled", lambda: False)
    assert _st(_get(client, su))["line"]["status"] == "todo"
    monkeypatch.setattr(ln, "enabled", lambda: True)
    s = _st(_get(client, su))["line"]
    assert s["status"] == "todo" and "沒有同仁綁定" in s["detail"] and s["optional"] is True
    ln.link_user(u, "U" + "a" * 32)
    s = _st(_get(client, su))["line"]
    assert s["status"] == "done" and "1／" in s["detail"]


def test_import_step_sees_existing_customers(client, su):
    assert _st(_get(client, su))["import"]["status"] == "todo"
    _sql("INSERT INTO customers (name, created_at) VALUES ('gs客戶','2026-01-01')")
    s = _st(_get(client, su))["import"]
    assert s["status"] == "done" and "1 位客戶" in s["detail"]


def test_skip_is_saved_on_the_server_and_can_come_back(client, su):
    r = client.put("/api/getting-started/steps/line", headers=su, json={"action": "skip"})
    assert r.status_code == 200 and _st(r.json())["line"]["status"] == "skipped" and r.json()["progress"]["skipped"] == 1
    assert _st(_get(client, su))["line"]["status"] == "skipped"                    # 重新讀（換電腦／換人）仍是略過
    stored = json.loads(_scalar("SELECT value_json FROM system_settings WHERE key=?", (GS.STATE_KEY,)))
    assert set(stored) == {"steps"} and set(stored["steps"]["line"]) == {"skipped", "by", "at"} and stored["steps"]["line"]["by"] == "gs_root"
    r = client.put("/api/getting-started/steps/line", headers=su, json={"action": "unskip"})
    assert _st(r.json())["line"]["status"] == "todo"


def test_auto_done_beats_skip_so_finished_work_is_never_hidden(client, su):
    client.put("/api/getting-started/steps/email", headers=su, json={"action": "skip"})
    _sql("INSERT INTO audit_log (at, username, action) VALUES (?,?,?)", ("2026-11-13T09:30:00", "gs_root", GS.EMAIL_TEST_ACTION))
    assert _st(_get(client, su))["email"]["status"] == "done"


def test_next_step_skips_done_and_skipped(client, su):
    first = _get(client, su)["next"]["id"]
    client.put("/api/getting-started/steps/%s" % first, headers=su, json={"action": "skip"})
    assert _get(client, su)["next"]["id"] != first


def test_manual_done_only_for_steps_the_system_cannot_see(client, su):
    r = client.put("/api/getting-started/steps/quote_style", headers=su, json={"action": "done"})
    assert r.status_code == 200 and _st(r.json())["quote_style"]["status"] == "done" and _st(r.json())["quote_style"]["manualDone"] is True
    r = client.put("/api/getting-started/steps/quote_style", headers=su, json={"action": "undone"})
    assert _st(r.json())["quote_style"]["status"] == "todo"
    for sid in ("email", "backup", "company", "people", "line"):
        assert client.put("/api/getting-started/steps/%s" % sid, headers=su, json={"action": "done"}).status_code == 400, sid
    assert client.put("/api/getting-started/steps/nope", headers=su, json={"action": "skip"}).status_code == 404
    assert client.put("/api/getting-started/steps/email", headers=su, json={"action": "explode"}).status_code == 400
    assert client.put("/api/getting-started/steps/email", headers=su, json={}).status_code == 400


def test_get_is_read_only(client, su):
    before = (_scalar("SELECT COUNT(*) FROM audit_log"), _scalar("SELECT COUNT(*) FROM system_settings"))
    for _ in range(3):
        _get(client, su)
    assert (_scalar("SELECT COUNT(*) FROM audit_log"), _scalar("SELECT COUNT(*) FROM system_settings")) == before
    assert _scalar("SELECT COUNT(*) FROM system_settings WHERE key=?", (GS.STATE_KEY,)) == 0


def test_a_failing_detector_does_not_break_the_other_steps(monkeypatch):
    def boom(conn):
        raise RuntimeError("secret internal detail")
    monkeypatch.setitem(GS._DETECT, "email", boom)
    res = GS.overview()
    assert len(res["steps"]) == 7
    e = _st(res)["email"]
    assert e["status"] == "todo" and "暫時無法自動確認" in e["detail"] and "secret" not in json.dumps(res, ensure_ascii=False)


def test_texts_are_plain_language():
    banned = ("JSON", "SMTP", "token", "Token", "API", "schema", "NULL", "superadmin", "audit", "localhost")
    blob = json.dumps([GS.STEPS], ensure_ascii=False)
    for b in banned:
        assert b not in blob, b
    from core import source_tree
    page = source_tree.page_file("getting-started.html").read_text(encoding="utf-8")
    visible = page.split("<body>", 1)[1].split("<script>", 1)[0]
    for b in banned:
        assert b not in visible, b


def test_overview_with_300_users_is_fast(client, su):
    from db import get_db
    conn = get_db()
    for i in range(300):
        conn.execute("INSERT INTO users (username, display_name, password_hash, role, active, created_at) VALUES (?,?,?,?,1,'2026-01-01')",
                     ("gs_bulk%d" % i, "B%d" % i, "x", "sales"))
    conn.commit()
    conn.close()
    t = time.perf_counter()
    GS.overview()
    assert time.perf_counter() - t < 0.5


def test_page_card_and_registrations():
    from core import source_tree
    page = source_tree.page_file("getting-started.html").read_text(encoding="utf-8")
    assert "innerHTML" not in page and "insertAdjacentHTML" not in page and "document.write" not in page      # 全部 textContent
    assert "/api/getting-started" in page and "sidebar.js" in page and "auth-guard.js" in page
    js = (FRONT / "static" / "getting-started-card.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js and "superadmin" in js
    hub = source_tree.page_file("system-hub.html").read_text(encoding="utf-8")
    assert "data-getting-started-card" in hub and "getting-started-card.js" in hub
    core = Path(__file__).resolve().parent.parent / "core"
    assert "getting-started.html" in json.loads((core / "l1_pages.json").read_text(encoding="utf-8"))
    cards = {c["id"]: c for c in json.loads((core / "system_hub_l1.json").read_text(encoding="utf-8"))["cards"]}
    assert cards["getting-started"]["href"] == "getting-started.html" and cards["getting-started"]["perm"] == "superadmin"
