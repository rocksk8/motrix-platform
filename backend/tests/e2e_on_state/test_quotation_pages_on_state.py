# -*- coding: utf-8 -*-
"""報價單表單（Q1／Q3）與報價單清單（Q2）的版面 ON 狀態：真瀏覽器＋真的設定／定義 API（已寫、未跑）。

場景：
  Q-1 表單區塊（Q1）：隱藏傳真、改名交貨地點、把「售後服務及備註說明」排到「付款條件」之前；核心欄位不能隱藏（發布被擋）
  Q-2 被隱藏欄位的資料照樣存檔：傳真隱藏後存草稿，資料庫裡的傳真值不變
  Q-3 自訂欄位（Q3）：旗標＋定義發布後表單出現「自訂欄位」區塊；填值 → 存草稿 → 重新載入還原；GET 報價單帶回 customFields；旗標關閉後區塊消失但值仍在庫裡
  Q-4 報價單清單欄位（Q2）：隱藏專案欄、金額欄改名；順序固定（登錄檔 fixedOrder）；核心欄（單號、客戶、狀態、案件進度）不能隱藏
"""
import pytest

from tests._requires import requires_module
from tests.e2e_on_state._common import (DATA_JS, api, inject_login, pid, publish_definition, publish_layout, seed_draft_quote, set_flag,
                                        stored_data, token_of, wait_layout_on)

pytestmark = [pytest.mark.e2e, requires_module("case", "報價單頁")]
FORM = "quotation-form.html"
LIST_PAGE = "quotations.html"


def _fld(form, f):
    return pid(FORM, "form", form, f)


def _open_form(page, base, user, qn):
    inject_login(page, base, user[0], user[1])
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    page.goto("%s/pages/quotation-form.html?id=%s" % (base, qn))
    page.wait_for_function("() => %s.q && %s.q.quoteNo === '%s'" % (DATA_JS, DATA_JS, qn), timeout=20000)
    return dialogs


def _save(page):
    page.evaluate("async () => { await %s.saveDraft() }" % DATA_JS)
    page.wait_for_function("() => !%s.isDirty" % DATA_JS, timeout=15000)


def test_q1_form_sections_hide_relabel_reorder(live_server, make_user, new_context):
    u = make_user(username="on_qf1", role="superadmin")
    ctx = new_context()
    tk = token_of(ctx, live_server, u)
    qn = seed_draft_quote()
    set_flag(ctx, live_server, tk, "builder_layout", "quotation_form", 1)
    publish_layout(ctx, live_server, tk, [
        {"op": "hide", "target": _fld("qcustomer", "contactFax")},
        {"op": "relabel", "target": _fld("qproject", "deliveryLocation"), "label": "施工地點"},
        {"op": "reorder", "target": pid(FORM, "form", "qterms"),
         "order": [_fld("qterms", f) for f in ("afterSales", "paymentTerms", "deliveryTerms", "acceptanceTerms", "warrantyTerms")]}])
    page = ctx.new_page()
    _open_form(page, live_server, u, qn)
    wait_layout_on(page)
    assert not page.get_by_text("傳真", exact=True).first.is_visible()
    assert page.get_by_text("施工地點", exact=True).first.is_visible() and page.get_by_text("交貨地點", exact=True).count() == 0
    ya = page.get_by_text("售後服務及備註說明").first.bounding_box()["y"]
    yp = page.get_by_text("付款條件").first.bounding_box()["y"]
    assert ya < yp, "售後服務應排在付款條件之前"
    # 核心欄位發布被擋
    for form, core in (("qcustomer", "customerName"), ("qbasic", "quoteDate"), ("qproject", "projectName")):
        for op in ({"op": "hide", "target": _fld(form, core)}, {"op": "relabel", "target": _fld(form, core), "label": "x"}):
            s, _ = api(ctx, live_server, "PUT", "/api/definitions/layout/module:case/draft", tk, {"body": {"ops": [op]}}, {"scope": "company"})
            if s == 200:
                s, _ = api(ctx, live_server, "POST", "/api/definitions/layout/module:case/publish", tk, {"note": "x"}, {"scope": "company"})
            assert s == 422, (core, op["op"], s)


def test_q2_hidden_field_value_is_still_saved(live_server, make_user, new_context):
    u = make_user(username="on_qf2", role="superadmin")
    ctx = new_context()
    tk = token_of(ctx, live_server, u)
    qn = seed_draft_quote()
    set_flag(ctx, live_server, tk, "builder_layout", "quotation_form", 1)
    publish_layout(ctx, live_server, tk, [{"op": "hide", "target": _fld("qcustomer", "contactFax")}])
    page = ctx.new_page()
    _open_form(page, live_server, u, qn)
    wait_layout_on(page)
    page.evaluate("() => { const c = %s; c.q.projectName = '改過的專案'; c.setDirty() }" % DATA_JS)   # 動別的欄位觸發存檔
    _save(page)
    d = stored_data(qn)
    assert d.get("contactFax") == "04-1234-5678", "隱藏欄位的值不可被存檔洗掉"
    assert d.get("projectName") == "改過的專案"


def test_q3_custom_field_saved_and_restored(live_server, make_user, new_context):
    u = make_user(username="on_qf3", role="superadmin")
    ctx = new_context()
    tk = token_of(ctx, live_server, u)
    qn = seed_draft_quote()
    set_flag(ctx, live_server, tk, "builder_custom_fields", "enabled", 1)
    publish_definition(ctx, live_server, tk, "custom_fields", "quotation",
                       {"fields": [{"key": "project_code", "label": "內部案號", "type": "text"}, {"key": "urgent", "label": "急件", "type": "checkbox"}]})
    page = ctx.new_page()
    _open_form(page, live_server, u, qn)
    sec = page.locator("[data-testid=cf-section]")
    sec.wait_for(state="visible", timeout=15000)
    page.locator("[data-cf-field=project_code] input").fill("PC-2026-001")
    page.locator("[data-cf-field=urgent] input[type=checkbox]").check()
    _save(page)
    assert stored_data(qn).get("customFields") == {"project_code": "PC-2026-001", "urgent": True}
    page.reload()
    page.wait_for_function("() => %s.q && %s.q.quoteNo === '%s'" % (DATA_JS, DATA_JS, qn), timeout=20000)
    page.locator("[data-testid=cf-section]").wait_for(state="visible", timeout=15000)
    assert page.locator("[data-cf-field=project_code] input").input_value() == "PC-2026-001"
    assert page.locator("[data-cf-field=urgent] input[type=checkbox]").is_checked()
    s, got = api(ctx, live_server, "GET", "/api/quotations/" + qn, tk)
    assert s == 200 and got["data"].get("customFields") == {"project_code": "PC-2026-001", "urgent": True}
    # 清掉值 ⇒ 鍵消失（伺服端與前端一致）
    page.locator("[data-cf-field=project_code] input").fill("")
    page.locator("[data-cf-field=urgent] input[type=checkbox]").uncheck()
    _save(page)
    assert "customFields" not in stored_data(qn)
    # 旗標關閉 ⇒ 區塊消失，已存的值（先寫回去再驗）不被動
    page.locator("[data-cf-field=project_code] input").fill("留著")
    _save(page)
    set_flag(ctx, live_server, tk, "builder_custom_fields", "enabled", 0)
    page.reload()
    page.wait_for_function("() => %s.q && %s.q.quoteNo === '%s'" % (DATA_JS, DATA_JS, qn), timeout=20000)
    page.wait_for_timeout(800)
    assert page.locator("[data-testid=cf-section]").count() == 0
    assert stored_data(qn).get("customFields") == {"project_code": "留著"}


def test_q4_quotation_list_columns(live_server, make_user, new_context):
    u = make_user(username="on_ql1", role="superadmin")
    ctx = new_context()
    tk = token_of(ctx, live_server, u)
    seed_draft_quote()
    set_flag(ctx, live_server, tk, "builder_layout", "quotations", 1)
    col = lambda f: pid(LIST_PAGE, "list", "quotes", f)           # noqa: E731
    publish_layout(ctx, live_server, tk, [{"op": "hide", "target": col("project")}, {"op": "relabel", "target": col("amount"), "label": "含稅總額"}])
    page = ctx.new_page()
    inject_login(page, live_server, u[0], u[1])
    page.goto(live_server + "/pages/quotations.html")
    page.wait_for_function("() => %s.layoutOn === true" % DATA_JS, timeout=15000)
    heads = page.evaluate("() => [...document.querySelectorAll('thead th')].filter(t => t.offsetParent !== null).map(t => t.textContent.trim())")
    assert "案件名稱" not in heads and "金額（含稅）" not in heads and "含稅總額" in heads, heads
    # 順序固定：隱藏／改名之外，欄位順序和預設相同
    assert heads.index("報價單號") < heads.index("客戶名稱") < heads.index("含稅總額"), heads
    # 核心欄不能隱藏
    for core in ("quoteNo", "customer", "status", "dealTag"):
        s, _ = api(ctx, live_server, "PUT", "/api/definitions/layout/module:case/draft", tk, {"body": {"ops": [{"op": "hide", "target": col(core)}]}}, {"scope": "company"})
        if s == 200:
            s, _ = api(ctx, live_server, "POST", "/api/definitions/layout/module:case/publish", tk, {"note": "x"}, {"scope": "company"})
        assert s == 422, (core, s)
    # 空列（colspan）跟著可見欄數：隱藏 1 欄 ⇒ 12 - 1
    assert page.evaluate("() => %s.colSpan()" % DATA_JS) == 11
