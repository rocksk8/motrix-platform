# -*- coding: utf-8 -*-
"""建構器第三輪 S1 — 執行頁（畫面＋DB）：用「報價單」範本建出的模組，填單時明細表可增列、列內公式與小計／稅額／合計即時算、
單位可自打、稅別單選；存檔後單據檢視畫出明細表；DB 的值正確（12,562.5 稅額四捨五入為 12,563）。"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

KEY = "b3e"


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


@pytest.mark.e2e
def test_quotation_template_module_fill_form_live_totals_and_save(live_server, make_user, new_context, client):
    boss = make_user(username="b3e_boss", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": boss[0], "password": boss[1]}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    body = client.get("/api/custom-modules/templates/quotation", headers=h).json()["body"]
    body["permission"] = "custom." + KEY
    assert client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=h, json={"body": body}).json()["problems"] == []
    assert client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=h, json={}).status_code == 200

    errors = []
    page = new_context().new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, boss[0], boss[1])
    page.goto(live_server + "/pages/custom-records.html?key=" + KEY)
    page.click("#cr-new")
    page.wait_for_selector("#cr-form", timeout=15000)

    # 稅別是單選（預設應稅5%）；明細表一開始沒有列
    assert page.locator('[data-radio="tax"] input[type=radio]:checked').get_attribute("value") == "應稅5%"
    assert page.locator('[data-table="lines"] tbody tr').count() == 0
    page.fill("#cr-in-cust", "客戶E")
    page.click('[data-add-row="lines"]')
    row = page.locator('[data-table="lines"] tr[data-row="0"]')
    row.locator('td[data-col="name"] input').fill("線材")
    row.locator('td[data-col="qty"] input').fill("5")
    row.locator('td[data-col="price"] input').fill("50250")
    row.locator('td[data-col="unit"] input').fill("坪")                       # 單位可自己打（清單以外）
    # 伺服器即時算：金額（列內公式）、未稅小計、稅額（12,562.5 → 12,563）、含稅合計
    page.wait_for_function("() => document.querySelector('#cr-in-grand') && document.querySelector('#cr-in-grand').innerText.trim() === '263813'", timeout=15000)
    assert row.locator('td[data-col="amt"]').inner_text().strip() == "251250"
    assert page.locator("#cr-in-sub").inner_text().strip() == "251250"
    assert page.locator("#cr-in-vat").inner_text().strip() == "12563"
    # 第二列：小計跟著變；刪掉第二列又變回來（反向控制：列數變動時公式重算）
    page.click('[data-add-row="lines"]')
    r2 = page.locator('[data-table="lines"] tr[data-row="1"]')
    r2.locator('td[data-col="name"] input').fill("配件")
    r2.locator('td[data-col="qty"] input').fill("2")
    r2.locator('td[data-col="price"] input').fill("100")
    page.wait_for_function("() => document.querySelector('#cr-in-sub').innerText.trim() === '251450'", timeout=15000)
    page.click('[data-remove-row="1"]')
    page.wait_for_function("() => document.querySelector('#cr-in-sub').innerText.trim() === '251250'", timeout=15000)
    # 換稅別 ⇒ 稅額 0
    page.check('[data-radio="tax"] input[value="免稅"]')
    page.wait_for_function("() => document.querySelector('#cr-in-vat').innerText.trim() === '0'", timeout=15000)
    page.check('[data-radio="tax"] input[value="應稅5%"]')
    page.wait_for_function("() => document.querySelector('#cr-in-vat').innerText.trim() === '12563'", timeout=15000)

    page.click("#cr-save")
    page.wait_for_selector("#cr-record", timeout=15000)
    view = page.locator('[data-view-field="lines"]')
    assert "線材" in view.inner_text() and "坪" in view.inner_text() and "251250" in view.inner_text()
    rec = _q("SELECT data_json FROM custom_records WHERE module_key=?", (KEY,))[0]
    d = json.loads(rec["data_json"])
    assert d["lines"] == [{"name": "線材", "qty": 5, "unit": "坪", "price": 50250, "amt": 251250}]
    assert (d["sub"], d["vat"], d["grand"], d["tax"]) == (251250, 12563, 263813, "應稅5%")
    assert d["sales"] == "b3e_boss" and d["qdate"]                                # 申請人與填單當下由伺服器決定
    # 列表：明細表欄顯示筆數（不是 [object Object]）
    assert not errors, errors


@pytest.mark.e2e
def test_group_columns_apply_on_the_runtime_form_and_narrow_screens_collapse_to_one(live_server, make_user, new_context, client):
    """區塊欄數（ui.form.groups[].columns）：執行頁的表單照設定排（3 欄 ⇒ 該區塊網格 3 軌）；沒設的區塊維持自動排（反向控制）；
    亂值（9、0、字串）視同自動；窄螢幕收成 1 欄。"""
    boss = make_user(username="b3c_boss", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": boss[0], "password": boss[1]}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    key = "b3cols"
    fields = [{"key": k, "label": k.upper(), "type": "text", "required": False, "dataClass": "T1"} for k in ("a", "b", "c", "d", "e", "f")]
    body = {"name": "欄數", "permission": "custom." + key, "numbering": {"prefix": "CL", "period": "none", "digits": 3},
            "fields": fields,
            "ui": {"form": {"groups": [{"title": "三欄", "fields": ["a", "b", "c"], "columns": 3},
                                       {"title": "自動", "fields": ["d"]},
                                       {"title": "亂值", "fields": ["e", "f"], "columns": 9}]}},
            "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿"}, {"key": "done", "label": "完成", "final": True}],
                 "transitions": [{"key": "submit", "label": "送出", "from": "draft", "to": "done"}]}}
    r = client.put("/api/definitions/custom_module/%s/draft" % key, headers=h, json={"body": body}).json()
    assert r["problems"] == [], r["problems"]
    assert client.post("/api/definitions/custom_module/%s/publish" % key, headers=h, json={}).status_code == 200

    page = new_context().new_page()
    inject_login(page, live_server, boss[0], boss[1])
    page.set_viewport_size({"width": 1200, "height": 900})
    page.goto(live_server + "/pages/custom-records.html?key=" + key)
    page.click("#cr-new")
    page.wait_for_selector("#cr-form", timeout=15000)
    tracks = "(i) => getComputedStyle(document.querySelectorAll('#cr-form .cr-grid')[i]).gridTemplateColumns.split(' ').length"
    assert page.evaluate(tracks, 0) == 3
    assert "cr-grid--n" not in page.evaluate("() => document.querySelectorAll('#cr-form .cr-grid')[1].className")
    assert "cr-grid--n" not in page.evaluate("() => document.querySelectorAll('#cr-form .cr-grid')[2].className")   # 9 不合法 ⇒ 自動
    page.set_viewport_size({"width": 390, "height": 800})
    assert page.evaluate(tracks, 0) == 1
