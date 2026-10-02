# -*- coding: utf-8 -*-
"""K-2 e2e（請款類型頁 `expense-types.html`，手動存檔）：兩位最高管理者同開一份草稿。
A 改名存草稿後，B 改名按「儲存草稿」⇒ B 看到「別人剛改過這份草稿」、資料庫仍是 A 的；
「重新載入」⇒ 畫面是 A 的、B 的修改消失；「用我的覆蓋」⇒ 資料庫是 B 的、稽核 `_override` 記被覆蓋者；「先不處理」⇒ 提示收起、資料庫不變。
發布也帶 base_etag：B 的草稿戳過期時按「發布」⇒ 同一提示、不發布。等待一律等終點（提示出現、訊息出現），不用 sleep。
"""
import json
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.e2e                                   # 用了瀏覽器夾具：要有 e2e marker（逐題死線；全量跑在 e2e 段）

from tests._e2e_login import inject_login  # noqa: E402
from tests._ui_dialogs import answer_confirm  # noqa: E402

KEY = "k2_type"
CONFLICT = "[data-testid=et-conflict]"
NAME = "[data-testid=et-name]"


def _seed():
    import db
    body = json.loads((Path(db.__file__).parent / "helpers" / "expense_type_defs" / "travel.json").read_text(encoding="utf-8"))
    body["name"] = "原名"
    c = db.get_db()
    try:
        c.execute("INSERT INTO ui_definitions (kind, key, scope, version, status, body_json, created_by, created_at) VALUES ('expense_type',?,'company',0,'draft',?,?,?)",
                  (KEY, json.dumps(body, ensure_ascii=False), "seed", "2026-10-02T00:00:00"))
        c.commit()
    finally:
        c.close()


def _draft():
    import db
    c = db.get_db()
    try:
        r = c.execute("SELECT body_json, created_by FROM ui_definitions WHERE kind='expense_type' AND key=? AND version=0", (KEY,)).fetchone()
        return (json.loads(r["body_json"]), r["created_by"]) if r else (None, None)
    finally:
        c.close()


def _published():
    import db
    c = db.get_db()
    try:
        return c.execute("SELECT COUNT(*) FROM ui_definitions WHERE kind='expense_type' AND key=? AND status='published'", (KEY,)).fetchone()[0]
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
    _seed()
    ua, ub = make_user(username="k2e_a", role="superadmin"), make_user(username="k2e_b", role="superadmin")
    errors = []

    def mk(u):
        p = new_context().new_page()
        p.on("pageerror", lambda e: errors.append("%s: %s" % (u[0], e)))
        inject_login(p, live_server, u[0], u[1])
        p.goto(live_server + "/pages/expense-types.html?key=" + KEY)
        p.wait_for_selector(NAME, timeout=20000)
        p.wait_for_function("() => document.querySelector('[data-testid=et-name]').value === '原名'", timeout=20000)
        return p
    a, b = mk(ua), mk(ub)
    a.fill(NAME, "A改名")
    a.click("[data-testid=et-save]")
    a.wait_for_function("() => (document.querySelector('[data-testid=et-msg]') || {}).innerText && document.querySelector('[data-testid=et-msg]').innerText.includes('草稿已儲存')", timeout=15000)
    assert _draft()[0]["name"] == "A改名"
    b.fill(NAME, "B改名")
    b.click("[data-testid=et-save]")
    b.wait_for_selector(CONFLICT, state="visible", timeout=15000)
    yield a, b, errors
    assert not errors, errors


def test_b_save_is_refused_with_the_banner_and_a_stays_in_the_database(two):
    a, b, _ = two
    assert "k2e_a" in b.locator("[data-testid=et-conflict-who]").inner_text()
    assert b.locator(NAME).input_value() == "B改名"                    # B 的修改還在畫面上
    body, by = _draft()
    assert body["name"] == "A改名" and by == "k2e_a" and _audits("definitions.save_draft_override") == []


def test_reload_shows_a_and_drops_b_then_saving_works(two):
    a, b, _ = two
    b.click("[data-testid=et-conflict-reload]")
    b.wait_for_selector(CONFLICT, state="hidden", timeout=15000)
    b.wait_for_function("() => document.querySelector('[data-testid=et-name]').value === 'A改名'")
    b.fill(NAME, "B接著改")
    b.click("[data-testid=et-save]")
    b.wait_for_function("() => (document.querySelector('[data-testid=et-msg]') || {}).innerText && document.querySelector('[data-testid=et-msg]').innerText.includes('草稿已儲存')", timeout=15000)
    body, by = _draft()
    assert body["name"] == "B接著改" and by == "k2e_b"


def test_override_writes_b_and_audits_the_overwritten_author(two):
    a, b, _ = two
    b.click("[data-testid=et-conflict-force]")
    answer_confirm(b, ok=True, expect="k2e_a")
    b.wait_for_function("() => (document.querySelector('[data-testid=et-msg]') || {}).innerText && document.querySelector('[data-testid=et-msg]').innerText.includes('覆蓋')", timeout=15000)
    body, by = _draft()
    assert body["name"] == "B改名" and by == "k2e_b"
    ov = _audits("definitions.save_draft_override")
    assert len(ov) == 1 and ov[0]["overridden"]["created_by"] == "k2e_a"


def test_hold_hides_the_banner_and_writes_nothing(two):
    a, b, _ = two
    b.click("[data-testid=et-conflict-hold]")
    b.wait_for_selector(CONFLICT, state="hidden")
    assert "還沒存" in b.locator("[data-testid=et-error]").inner_text()
    assert _draft()[0]["name"] == "A改名"


def test_publish_with_a_stale_draft_is_refused_and_publishes_nothing(two):
    a, b, _ = two
    b.click("[data-testid=et-conflict-hold]")
    b.click("[data-testid=et-publish]")
    b.wait_for_selector(CONFLICT, state="visible", timeout=15000)       # 發布前的存草稿就被擋（戳過期）
    assert _published() == 0 and _draft()[0]["name"] == "A改名"
