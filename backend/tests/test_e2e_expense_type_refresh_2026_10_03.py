# -*- coding: utf-8 -*-
"""D14／D15 e2e（請款類型頁）：公司發布過的 travel（與出貨範本有差異）——
D15：提示「出貨範本與目前內容有 N 項差異」→ 逐項比較；「採用出貨的」只改畫面、按「儲存草稿」才寫入（稽核記採用的路徑）、不發布；
     「保留我的」只是不再列出、資料庫不變。
D14：「複製出貨範本到草稿」＝確認後草稿等於出貨範本、不自動發布（已發布列數不變）。
等待一律等終點（訊息出現、列消失），不用 sleep。headless。"""
import json
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._ui_dialogs import answer_confirm  # noqa: E402

KEY = "travel"
ROWS = "[data-testid^=et-rf-row-]"


def _shipped():
    import db
    return json.loads((Path(db.__file__).parent / "helpers" / "expense_type_defs" / "travel.json").read_text(encoding="utf-8"))


def _seed_published():
    """公司發布的 v1：改名、申請人說明舊文字、拿掉部門欄。"""
    import db
    body = _shipped()
    body["name"] = "我的差旅"
    for f in body["fields"]:
        if f["key"] == "applicant":
            f["help"] = "舊說明"
    body["fields"] = [f for f in body["fields"] if f["key"] != "dept"]
    c = db.get_db()
    try:
        c.execute("INSERT INTO ui_definitions (kind, key, scope, version, status, body_json, created_by, created_at, published_by, published_at) "
                  "VALUES ('expense_type',?,'company',1,'published',?,'seed','2026-10-01T00:00:00','seed','2026-10-01T00:00:00')",
                  (KEY, json.dumps(body, ensure_ascii=False)))
        c.commit()
    finally:
        c.close()


def _q(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _draft():
    r = _q("SELECT body_json FROM ui_definitions WHERE kind='expense_type' AND key=? AND version=0", (KEY,))
    return json.loads(r[0]["body_json"]) if r else None


def _published_count():
    return _q("SELECT COUNT(*) n FROM ui_definitions WHERE kind='expense_type' AND key=? AND status='published'", (KEY,))[0]["n"]


def _msg_has(page, text):
    page.wait_for_function("(t) => (document.querySelector('[data-testid=et-msg]') || {}).innerText && document.querySelector('[data-testid=et-msg]').innerText.includes(t)", arg=text, timeout=15000)


@pytest.fixture()
def page(live_server, make_user, new_context):
    _seed_published()
    u = make_user(username="d15_sa", role="superadmin")
    errors = []
    p = new_context().new_page()
    p.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(p, live_server, u[0], u[1])
    p.goto(live_server + "/pages/expense-types.html?key=" + KEY)
    p.wait_for_selector("[data-testid=et-refresh]", state="visible", timeout=20000)
    yield p
    assert not errors, errors


def test_hint_counts_differences_and_table_lists_them(page):
    n = int(page.locator("[data-testid=et-refresh-count]").inner_text())
    assert n >= 3                                                              # 名稱、申請人說明、部門欄
    page.click("[data-testid=et-refresh-toggle]")
    page.wait_for_selector(ROWS, timeout=5000)
    assert page.locator(ROWS).count() == n
    txt = page.locator("[data-testid=et-refresh] table").inner_text()
    assert "申請人" in txt and "部門" in txt and "名稱" in txt and "出貨範本新增" in txt


def test_adopt_changes_only_the_screen_until_save_then_audits_and_never_publishes(page):
    page.click("[data-testid=et-refresh-toggle]")
    row = page.locator(ROWS).filter(has_text="申請人")
    row.locator("button", has_text="採用出貨的").click()
    _msg_has(page, "尚未儲存")
    assert _draft() is None and _published_count() == 1                         # 還沒存＝資料庫沒動
    page.click("[data-testid=et-save]")
    _msg_has(page, "草稿已儲存")
    d = _draft()
    assert [f for f in d["fields"] if f["key"] == "applicant"][0]["help"] == [f for f in _shipped()["fields"] if f["key"] == "applicant"][0]["help"]
    assert d["name"] == "我的差旅"                                              # 其他項沒被帶動
    ad = [json.loads(r["detail"]) for r in _q("SELECT detail FROM audit_log WHERE action='definitions.save_draft' ORDER BY id")]
    assert ad and ad[-1]["adopted_from_default"] == ["fields[applicant].help"]
    assert _published_count() == 1                                              # 沒有自動發布


def test_adopting_an_added_field_puts_it_back_and_the_row_disappears(page):
    page.click("[data-testid=et-refresh-toggle]")
    before = page.locator(ROWS).count()
    page.locator(ROWS).filter(has_text="出貨範本新增").filter(has_text="部門").locator("button", has_text="採用出貨的").click()
    page.wait_for_function("(n) => document.querySelectorAll('[data-testid^=et-rf-row-]').length === n", arg=before - 1, timeout=10000)
    page.click("[data-testid=et-save]")
    _msg_has(page, "草稿已儲存")
    assert "dept" in [f["key"] for f in _draft()["fields"]]


def test_keep_mine_hides_the_row_and_writes_nothing(page):
    page.click("[data-testid=et-refresh-toggle]")
    before = page.locator(ROWS).count()
    page.locator(ROWS).filter(has_text="名稱").first.locator("button", has_text="保留我的").click()
    page.wait_for_function("(n) => document.querySelectorAll('[data-testid^=et-rf-row-]').length === n", arg=before - 1, timeout=10000)
    assert _draft() is None and _published_count() == 1


def test_copy_default_to_draft_replaces_content_and_does_not_publish(page):
    page.click("[data-testid=et-copy-default]")
    answer_confirm(page, ok=True, expect="出貨範本")
    _msg_has(page, "已複製出貨範本到草稿")
    assert _draft() == _shipped()
    assert _published_count() == 1
    page.wait_for_selector("[data-testid=et-refresh]", state="hidden", timeout=10000)      # 內容等於出貨範本 ⇒ 沒有差異可列
    ad = [json.loads(r["detail"]) for r in _q("SELECT detail FROM audit_log WHERE action='definitions.save_draft' ORDER BY id")]
    assert ad[-1]["adopted_from_default"] == ["（整份出貨範本）"]


def test_copy_default_cancelled_changes_nothing(page):
    page.click("[data-testid=et-copy-default]")
    answer_confirm(page, ok=False, expect="出貨範本")
    assert _draft() is None
    assert page.locator("[data-testid=et-refresh]").is_visible()
