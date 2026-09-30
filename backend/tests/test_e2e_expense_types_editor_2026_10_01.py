# -*- coding: utf-8 -*-
"""請款類型定義編輯頁（`expense-types.html`）v1：新增類型 → 驗證紅字 → 修正 → 存草稿 → 發布 → 改動 → 差異 → 還原；
非超級管理員進不了定義 API。終點狀態＝畫面＋資料庫（ui_definitions.body_json）。

`expense_type` 種類由 W1 的 A2-2 登記；本題在沒有登記時自己登記一個最小驗證器（契約形狀：name／numbering.prefix／payable／
docType／含 `lines` 表格欄位），登記好之後（A2-2 合進來）`register_kind` 會丟 ValueError ⇒ 用正式的。
截圖（預設暫存目錄；設 MOTRIX_SHOTS_DIR 才寫共用資料夾）。"""
import json
import os
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402

SHOTS = Path(os.environ.get("MOTRIX_SHOTS_DIR") or os.path.join(tempfile.gettempdir(), "aet27-shots")) / "wip-w3-etype-editor"


def _shot(page, name):
    try:
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / (name + ".png")), full_page=True)
    except Exception:                                            # noqa: BLE001 — 截圖失敗（含 BK19 護欄）不影響判定
        pass


def _ensure_kind():
    from core import definitions as D
    if "expense_type" in D.kinds():
        return

    def _validator(body, key):
        out = []
        if not isinstance(body, dict):
            return [{"path": "", "message": "定義必須是物件"}]
        if not str(body.get("name") or "").strip():
            out.append({"path": "name", "message": "必須有名稱"})
        if not str((body.get("numbering") or {}).get("prefix") or "").strip():
            out.append({"path": "numbering.prefix", "message": "必須有單號前綴"})
        if not isinstance(body.get("payable"), bool):
            out.append({"path": "payable", "message": "payable 必須是 true／false"})
        if not str(body.get("docType") or "").strip():
            out.append({"path": "docType", "message": "必須選簽核單據類型"})
        if not any(isinstance(f, dict) and f.get("key") == "lines" and f.get("type") == "table" for f in body.get("fields") or []):
            out.append({"path": "fields", "message": "必須有 lines 明細表"})
        return out
    D.register_kind("expense_type", "請款類型", validator=_validator)


def _db(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args)]
    finally:
        c.close()


def _open(e2e_browser, base, user, width=1280):
    ctx = e2e_browser.new_context(viewport={"width": width, "height": 900})
    page = ctx.new_page()
    inject_login(page, base, user[0], user[1])
    page.goto(base + "/pages/expense-types.html")
    page.wait_for_selector("[data-testid=et-new]", timeout=20000)
    page.wait_for_function("() => !document.body.innerText.includes('載入中…')", timeout=20000)
    return page


@pytest.mark.e2e
def test_superadmin_creates_validates_publishes_and_restores_a_type(live_server, make_user, e2e_browser):
    _ensure_kind()
    u = make_user(username="et_admin", role="superadmin", modules=[])
    page = _open(e2e_browser, live_server, u)
    assert page.locator("[data-testid=et-empty]").is_visible()
    _shot(page, "1_list_empty")
    page.click("[data-testid=et-new]")
    page.wait_for_selector("[data-testid=et-edit]")
    # 新類型：預設有 applicant／req_date／lines；先填代碼與名稱，故意不選簽核類型、不填前綴 ⇒ 驗證紅字
    page.fill("[data-testid=et-key]", "purchase_req")
    page.fill("[data-testid=et-name]", "請購單")
    page.click("[data-testid=et-validate]")
    try:
        page.wait_for_selector("[data-testid=et-problems] li", timeout=8000)
    except Exception:
        print("DBG", page.inner_text("[data-testid=et-error]"), "|", page.inner_text("[data-testid=et-msg]"), "|", page.evaluate("() => Alpine.$data(document.body).problems"))
        raise
    txt = page.inner_text("[data-testid=et-problems]")
    assert "單號前綴" in txt and "簽核單據類型" in txt, txt
    _shot(page, "2_problems")
    # 修正：前綴（小寫輸入自動轉大寫）、簽核單據類型、不進出納；加保留欄位 dept、明細欄 invoiceNo；全部放一組
    page.fill("[data-testid=et-prefix]", "pr")
    assert page.input_value("[data-testid=et-prefix]") == "PR"
    opts = page.eval_on_selector_all("[data-testid=et-doctype] option", "els => els.map(e => e.value).filter(Boolean)")
    assert opts, "簽核單據類型清單不該是空的"
    page.select_option("[data-testid=et-doctype]", opts[0])
    page.uncheck("[data-testid=et-payable]")
    page.select_option("[data-testid=et-add-reserved]", "dept")
    assert page.locator("[data-testid=et-field-row][data-key=dept]").count() == 1
    page.select_option("[data-testid=et-add-col]", "invoiceNo")
    assert page.locator("[data-testid=et-col-row][data-key=invoiceNo]").count() == 1
    page.click("[data-testid=et-auto-group]")
    page.click("[data-testid=et-validate]")
    page.wait_for_selector("[data-testid=et-msg]", state="visible")
    assert "驗證通過" in page.inner_text("[data-testid=et-msg]")
    assert not page.locator("[data-testid=et-problems]").is_visible()
    # 申請人預填鎖定（預設範本）：UI 上勾著
    assert page.locator("[data-testid=et-field-row][data-key=applicant] [data-testid=et-f-locked]").is_checked()
    _shot(page, "3_edit_valid")
    # 存草稿 ⇒ DB 有草稿列、內容是契約形狀
    page.click("[data-testid=et-save]")
    page.wait_for_function("() => document.querySelector('[data-testid=et-msg]').innerText.includes('草稿已儲存')", timeout=10000)
    row = _db("SELECT status, version, body_json FROM ui_definitions WHERE kind='expense_type' AND key='purchase_req'")
    assert len(row) == 1 and row[0]["status"] == "draft"
    body = json.loads(row[0]["body_json"])
    assert body["name"] == "請購單" and body["numbering"]["prefix"] == "PR" and body["payable"] is False and body["docType"] == opts[0]
    lines = next(f for f in body["fields"] if f["key"] == "lines")
    assert lines["type"] == "table" and [c["key"] for c in lines["columns"]] == ["category", "summary", "amount", "invoiceNo"]
    assert next(f for f in body["fields"] if f["key"] == "applicant")["default"] == {"$": "requester"}
    assert body["ui"]["form"]["groups"][0]["fields"] == [f["key"] for f in body["fields"] if f["key"] != "lines"]
    # 發布 ⇒ v1
    page.fill("[data-testid=et-note]", "首版")
    page.click("[data-testid=et-publish]")
    page.wait_for_function("() => document.querySelector('[data-testid=et-msg]').innerText.includes('已發布第 1 版')", timeout=10000)
    pub = _db("SELECT version, status, note FROM ui_definitions WHERE kind='expense_type' AND key='purchase_req' AND status='published'")
    assert pub == [{"version": 1, "status": "published", "note": "首版"}]
    # 改名（存草稿）⇒ 與已發布版的差異 1 處以上；再發布 v2；還原 v1 ⇒ v3 內容＝v1
    page.fill("[data-testid=et-name]", "請購單（改）")
    page.click("[data-testid=et-save]")
    page.wait_for_function("() => document.querySelector('[data-testid=et-msg]').innerText.includes('草稿已儲存')", timeout=10000)
    page.click("[data-testid=et-changes]")
    page.wait_for_selector("[data-testid=et-changes-list] li")
    assert "name" in page.inner_text("[data-testid=et-changes-list]")
    page.click("[data-testid=et-publish]")
    page.wait_for_function("() => document.querySelector('[data-testid=et-msg]').innerText.includes('已發布第 2 版')", timeout=10000)
    page.wait_for_selector("[data-testid=et-restore-1]")
    _shot(page, "4_versions")
    page.click("[data-testid=et-restore-1]")
    page.wait_for_function("() => document.querySelector('[data-testid=et-msg]').innerText.includes('還原為第 3 版')", timeout=10000)
    v3 = _db("SELECT body_json FROM ui_definitions WHERE kind='expense_type' AND key='purchase_req' AND version=3")
    assert json.loads(v3[0]["body_json"])["name"] == "請購單"
    # 清單：回清單看得到名稱／前綴／版本
    page.click("[data-testid=et-back]")
    page.wait_for_selector("[data-testid=et-row-purchase_req]")
    t = page.inner_text("[data-testid=et-row-purchase_req]")
    assert "請購單" in t and "PR" in t and "v3" in t and "否" in t, t
    _shot(page, "5_list")


@pytest.mark.e2e
def test_new_type_key_must_be_valid_and_unique_and_narrow_fits(live_server, make_user, e2e_browser):
    _ensure_kind()
    u = make_user(username="et_admin2", role="superadmin", modules=[])
    page = _open(e2e_browser, live_server, u, width=390)
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"), "窄螢幕頁面本身不可橫向捲動（表格在自己的捲動區內）"
    page.click("[data-testid=et-new]")
    page.wait_for_selector("[data-testid=et-edit]")
    page.fill("[data-testid=et-key]", "Bad Key")
    page.click("[data-testid=et-save]")
    page.wait_for_selector("[data-testid=et-error]", state="visible")
    assert "小寫英文" in page.inner_text("[data-testid=et-error]")
    assert _db("SELECT 1 FROM ui_definitions WHERE kind='expense_type'") == []
    _shot(page, "6_narrow_bad_key")


@pytest.mark.e2e
def test_non_superadmin_cannot_use_the_definition_api_or_see_data(live_server, make_user, e2e_browser):
    _ensure_kind()
    u = make_user(username="et_user", role="viewer", modules=[])
    page = _open_noguard(e2e_browser, live_server, u)
    status = page.evaluate("""async () => {
        const s = JSON.parse(localStorage.getItem('motrix_session') || '{}');
        const r = await fetch('/api/definitions/expense_type', {headers: {Authorization: 'Bearer ' + (s.token || '')}});
        return r.status;
    }""")
    assert status in (401, 403)


def _open_noguard(e2e_browser, base, user):
    ctx = e2e_browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    inject_login(page, base, user[0], user[1])
    page.goto(base + "/pages/expense-types.html")
    page.wait_for_load_state("domcontentloaded")
    return page
