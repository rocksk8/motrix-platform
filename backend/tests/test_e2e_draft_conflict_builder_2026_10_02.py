# -*- coding: utf-8 -*-
"""K-2 e2e（模組建構器）：兩位最高管理者（兩個瀏覽器 context）同開一份草稿。
A 改名存檔後，B 改別處等自動存檔 ⇒ B 看到「別人剛改過這份草稿」、自動存檔停止、資料庫仍是 A 的內容；
B 選「重新載入」⇒ 畫面是 A 的改名、B 的修改消失；B 選「用我的覆蓋」⇒ 資料庫是 B 的內容、稽核有 `_override`；
B 選「先不處理」⇒ 提示收成一行、仍不自動存、DB 不變。舊前端相容（不帶 base_etag）見 test_definitions_draft_etag。
等待一律等終點狀態（存檔狀態列、提示出現／消失），不用 sleep。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.e2e                                   # 用了瀏覽器夾具：要有 e2e marker（逐題死線；全量跑在 e2e 段）

from tests._e2e_login import inject_login  # noqa: E402
from tests._builder_nav import start_blank  # noqa: E402
from tests._ui_dialogs import answer_confirm  # noqa: E402

KEY = "k2_demo"
SAVED = """() => { const e = document.getElementById('mb-save-state');
  return !!e && e.dataset.dirty === '0' && e.dataset.saving === '0' && e.dataset.state === 'saved' }"""
CONFLICT = '[data-testid="mb-conflict"]'


def _draft():
    import db
    c = db.get_db()
    try:
        r = c.execute("SELECT body_json, created_by FROM ui_definitions WHERE kind='custom_module' AND key=? AND version=0", (KEY,)).fetchone()
        return (json.loads(r["body_json"]), r["created_by"]) if r else (None, None)
    finally:
        c.close()


def _audits(action):
    import db
    c = db.get_db()
    try:
        return [json.loads(r["detail"] or "{}") for r in c.execute("SELECT detail FROM audit_log WHERE action=? ORDER BY id", (action,)).fetchall()]
    finally:
        c.close()


@pytest.fixture()
def two(live_server, make_user, new_context):
    ua, ub = make_user(username="k2_a", role="superadmin"), make_user(username="k2_b", role="superadmin")
    errors = []

    def mk(u):
        p = new_context().new_page()
        p.on("pageerror", lambda e: errors.append("%s: %s" % (u[0], e)))
        inject_login(p, live_server, u[0], u[1])
        p.goto(live_server + "/pages/module-builder.html")
        return p
    a = mk(ua)
    start_blank(a, KEY)
    a.fill("#mb-name", "原名")
    a.wait_for_function(SAVED, timeout=15000)
    b = mk(ub)
    b.goto(live_server + "/pages/module-builder.html?key=" + KEY)
    b.wait_for_selector("#mb-step-1", state="visible")
    b.wait_for_function("() => document.getElementById('mb-name').value === '原名'")
    a.fill("#mb-name", "A改名")
    a.wait_for_function(SAVED, timeout=15000)
    assert _draft()[0]["name"] == "A改名"
    b.fill("#mb-prefix", "BB")                                  # B 改別處，等自動存檔
    b.wait_for_selector(CONFLICT, state="visible", timeout=15000)
    yield a, b, errors
    assert not errors, errors


def test_b_is_told_autosave_stops_and_the_database_keeps_a(two):
    a, b, _ = two
    assert b.locator("#mb-save-state").inner_text() == "未存：草稿被別人改過"
    assert "k2_a" in b.locator('[data-testid="mb-conflict-who"]').inner_text()
    assert b.locator("#mb-prefix").input_value() == "BB"        # B 的修改還在畫面上
    b.fill("#mb-prefix", "BC")
    b.wait_for_timeout(5000)                                    # 超過自動存檔延遲：仍不該存（用 Playwright 的等待，不阻塞頁面事件）
    body, by = _draft()
    assert body["name"] == "A改名" and (body.get("numbering") or {}).get("prefix") != "BC" and by == "k2_a"
    assert _audits("definitions.save_draft_override") == []


def test_reload_shows_a_and_drops_b(two):
    a, b, _ = two
    b.click('[data-testid="mb-conflict-reload"]')
    b.wait_for_selector(CONFLICT, state="hidden", timeout=15000)
    b.wait_for_function("() => document.getElementById('mb-name').value === 'A改名'")
    assert b.locator("#mb-prefix").input_value() != "BB"
    body, by = _draft()
    assert body["name"] == "A改名" and by == "k2_a"
    b.fill("#mb-name", "B接著改")                                # 重新載入後拿到新戳 ⇒ 之後存檔正常
    b.wait_for_function(SAVED, timeout=15000)
    assert _draft()[0]["name"] == "B接著改" and _draft()[1] == "k2_b"


def test_override_writes_b_and_audits_who_was_overwritten(two):
    a, b, _ = two
    b.click('[data-testid="mb-conflict-force"]')
    msg = answer_confirm(b, ok=True, expect="k2_a")
    b.wait_for_selector(CONFLICT, state="hidden", timeout=15000)
    b.wait_for_function(SAVED, timeout=15000)
    body, by = _draft()
    assert by == "k2_b" and (body.get("numbering") or {}).get("prefix") == "BB" and body["name"] == "原名"      # B 的版本（B 沒改名，所以名稱是 B 載入時的「原名」）
    ov = _audits("definitions.save_draft_override")
    assert len(ov) == 1 and ov[0]["overridden"]["created_by"] == "k2_a"


def test_cancelling_the_override_confirm_changes_nothing(two):
    a, b, _ = two
    b.click('[data-testid="mb-conflict-force"]')
    answer_confirm(b, ok=False)
    assert b.locator(CONFLICT).is_visible()
    body, by = _draft()
    assert body["name"] == "A改名" and by == "k2_a" and _audits("definitions.save_draft_override") == []


def test_hold_collapses_the_banner_and_keeps_autosave_off(two):
    a, b, _ = two
    b.click('[data-testid="mb-conflict-hold"]')
    b.wait_for_selector('[data-testid="mb-conflict-reload"]', state="hidden")
    assert b.locator('[data-testid="mb-conflict-reopen"]').is_visible() and b.locator("#mb-save-state").inner_text() == "未存：草稿被別人改過"
    b.fill("#mb-prefix", "ZZ")
    b.wait_for_timeout(5000)
    assert _draft()[1] == "k2_a"
    b.click('[data-testid="mb-conflict-reopen"]')
    b.wait_for_selector('[data-testid="mb-conflict-reload"]', state="visible")


def test_publish_drawer_does_not_publish_while_the_draft_is_stale(two):
    b = two[1]
    b.click("#mb-publish-open")
    b.wait_for_selector("#mb-step-6", state="visible")
    assert b.locator(CONFLICT).is_visible()
    import db
    c = db.get_db()
    try:
        assert c.execute("SELECT COUNT(*) FROM ui_definitions WHERE kind='custom_module' AND key=? AND status='published'", (KEY,)).fetchone()[0] == 0
    finally:
        c.close()
