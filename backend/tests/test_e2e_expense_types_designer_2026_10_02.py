# -*- coding: utf-8 -*-
"""請款類型編輯頁接上共用表單設計器（`?designer=1`；預設仍是舊的表格畫面，使用者預覽裁示前不換）。

- 開啟四個程式預設類型：設計器載入後定義一個字都不變（不動就不弄髒草稿；含 list.columns 順序、空 groups、output.template）。
- 新增類型：請款常用欄位（型別固定的保留欄位）從左欄加入 ⇒ 驗證通過 ⇒ 存草稿的內容是契約形狀。
- 急迫性的選項固定（設計器不強制，轉接層改回去）；舊表格畫面仍可用（?designer=0 / 切換連結）。"""
import json

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402

BODY = "() => Alpine.$data(document.body)"


def _db(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args)]
    finally:
        c.close()


def _open(e2e_browser, base, user, query="?designer=1"):
    ctx = e2e_browser.new_context(viewport={"width": 1600, "height": 1000})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, base, user[0], user[1])
    page.goto(base + "/pages/expense-types.html" + query)
    page.wait_for_selector("[data-testid=et-new]", timeout=20000)
    page.wait_for_function("() => !document.body.innerText.includes('載入中…')", timeout=20000)
    page.errors = errors
    return page


@pytest.mark.e2e
@pytest.mark.parametrize("code", ["purchase_req", "purchase_order", "travel", "petty_cash"])
def test_designer_loads_each_shipped_type_without_changing_the_definition(live_server, make_user, e2e_browser, code):
    u = make_user(username="etd_a_" + code, role="superadmin", modules=[])
    page = _open(e2e_browser, live_server, u)
    page.click("[data-testid=et-open-%s]" % code)
    page.wait_for_selector(".fd .fd-paper", state="visible", timeout=20000)
    before = page.evaluate("() => JSON.stringify(Alpine.$data(document.body).body)")
    page.wait_for_timeout(1500)                                          # 設計器的延遲提交（commitSoon）若會改定義，這段時間內會發生
    after = page.evaluate("() => JSON.stringify(Alpine.$data(document.body).body)")
    assert before == after, "設計器載入後把定義改掉了"
    page.click("[data-testid=et-validate]")
    page.wait_for_selector("[data-testid=et-msg]", state="visible", timeout=10000)
    assert "驗證通過" in page.inner_text("[data-testid=et-msg]")
    assert not page.errors, page.errors


@pytest.mark.e2e
def test_designer_new_type_with_reserved_preset_validates_and_saves_a_contract_shaped_draft(live_server, make_user, e2e_browser):
    u = make_user(username="etd_new", role="superadmin", modules=[])
    page = _open(e2e_browser, live_server, u)
    page.click("[data-testid=et-new]")
    page.wait_for_selector(".fd .fd-paper", state="visible", timeout=20000)
    page.fill("[data-testid=et-key]", "visit_fee")
    page.fill("[data-testid=et-name]", "訪視單")
    page.fill("[data-testid=et-prefix]", "vf")
    opts = page.eval_on_selector_all("[data-testid=et-doctype] option", "els => els.map(e => e.value).filter(Boolean)")
    page.select_option("[data-testid=et-doctype]", opts[0])
    page.uncheck("[data-testid=et-payable]")
    # 請款常用欄位：部門（參照部門，型別固定）
    page.click('.fd-left [data-add="x0_1"]')
    page.wait_for_function("() => Alpine.$data(document.body).body.fields.some(f => f.key === 'dept')", timeout=10000)
    page.click("[data-testid=et-validate]")
    page.wait_for_selector("[data-testid=et-msg]", state="visible", timeout=10000)
    assert "驗證通過" in page.inner_text("[data-testid=et-msg]"), page.inner_text("[data-testid=et-problems]") if page.locator("[data-testid=et-problems]").is_visible() else ""
    page.click("[data-testid=et-save]")
    page.wait_for_function("() => document.querySelector('[data-testid=et-msg]').innerText.includes('草稿已儲存')", timeout=10000)
    row = _db("SELECT status, body_json FROM ui_definitions WHERE kind='expense_type' AND key='visit_fee'")
    assert len(row) == 1 and row[0]["status"] == "draft"
    body = json.loads(row[0]["body_json"])
    dept = next(f for f in body["fields"] if f["key"] == "dept")
    assert dept["type"] == "ref" and dept["target"] == "departments"
    assert any(f["key"] == "lines" and f["type"] == "table" for f in body["fields"])
    assert body["name"] == "訪視單" and body["numbering"]["prefix"] == "VF" and body["payable"] is False
    assert not page.errors, page.errors


@pytest.mark.e2e
def test_designer_adapter_forces_the_urgency_options_back(live_server, make_user, e2e_browser):
    u = make_user(username="etd_urg", role="superadmin", modules=[])
    page = _open(e2e_browser, live_server, u)
    page.click("[data-testid=et-open-purchase_req]")
    page.wait_for_selector(".fd .fd-paper", state="visible", timeout=20000)
    res = page.evaluate("""() => {
      const d = Alpine.$data(document.body)
      const def = JSON.parse(JSON.stringify(d.body))
      def.fields = def.fields.filter(f => f.key !== 'urgency')
      def.fields.splice(0, 0, { key: 'urgency', label: '急迫性', type: 'select', options: ['隨便', '亂改'] })
      d.fdChanged(def)
      return d.body.fields.find(f => f.key === 'urgency').options
    }""")
    assert res == ["一般", "急件", "特急"], res


@pytest.mark.e2e
def test_designer_switch_back_to_the_old_table_screen_keeps_working(live_server, make_user, e2e_browser):
    u = make_user(username="etd_sw", role="superadmin", modules=[])
    page = _open(e2e_browser, live_server, u)
    page.click("[data-testid=et-open-petty_cash]")
    page.wait_for_selector(".fd .fd-paper", state="visible", timeout=20000)
    assert not page.locator("[data-testid=et-fields]").is_visible()
    page.click("[data-testid=et-old-ui]")
    page.wait_for_selector("[data-testid=et-fields]", state="visible", timeout=10000)
    assert not page.locator(".fd .fd-paper").is_visible()
    assert page.locator("[data-testid=et-field-row]").count() >= 3


@pytest.mark.e2e
def test_designer_reserved_presets_match_the_old_editor_and_column_presets_add_fixed_keys(live_server, make_user, e2e_browser):
    """保留欄位預設值照舊編輯頁（申請人＝鎖定＋預填申請人；填表日期＝預填今天；都沒有 required）；常用欄「數量＋單價」加入固定代碼 qty／unitCost。"""
    u = make_user(username="etd_pre", role="superadmin", modules=[])
    page = _open(e2e_browser, live_server, u)
    page.click("[data-testid=et-new]")
    page.wait_for_selector(".fd .fd-paper", state="visible", timeout=20000)
    page.fill("[data-testid=et-key]", "preset_chk")
    # 新類型本來就帶 applicant／req_date／lines；再加部門
    page.click('.fd-left [data-add="x0_1"]')
    page.wait_for_function("() => Alpine.$data(document.body).body.fields.some(f => f.key === 'dept')", timeout=10000)
    fields = page.evaluate("() => JSON.parse(JSON.stringify(Alpine.$data(document.body).body.fields))")
    by = {f["key"]: f for f in fields}
    assert by["dept"]["type"] == "ref" and by["dept"]["target"] == "departments"
    assert "required" not in by["dept"]
    # 預設範本的申請人／填表日期是舊 newBody 的內容（本來就沒有 required）
    assert by["applicant"].get("locked") is True and by["applicant"]["default"] == {"$": "requester"}
    assert by["req_date"]["default"] == {"$": "today"}
    # 常用欄：選到明細表 ⇒ 加「數量＋單價」
    page.click('.fd-center .fd-fld[data-key="lines"]')
    page.wait_for_selector('.fd-right [data-col-preset]', state="visible", timeout=10000)
    page.click('.fd-right [data-col-preset="0"]')
    page.wait_for_function("() => { const l = Alpine.$data(document.body).body.fields.find(f => f.key === 'lines'); "
                           "return l && l.columns.some(c => c.key === 'qty') && l.columns.some(c => c.key === 'unitCost') }", timeout=10000)
    assert not page.errors, page.errors


@pytest.mark.e2e
def test_designer_clicking_a_problem_selects_that_field(live_server, make_user, e2e_browser):
    u = make_user(username="etd_foc", role="superadmin", modules=[])
    page = _open(e2e_browser, live_server, u)
    page.click("[data-testid=et-open-petty_cash]")
    page.wait_for_selector(".fd .fd-paper", state="visible", timeout=20000)
    page.evaluate("""() => { const d = Alpine.$data(document.body)
      d.problems = [{ path: 'fields[1]', message: '測試問題' }]; d.fdSyncProblems() }""")
    page.wait_for_selector("[data-testid=et-problems] li", state="visible", timeout=5000)
    key = page.evaluate("() => Alpine.$data(document.body).body.fields[1].key")
    page.click("[data-testid=et-problems] li")
    page.wait_for_selector('.fd-center .fd-fld.is-sel[data-key="%s"]' % key, timeout=5000)
