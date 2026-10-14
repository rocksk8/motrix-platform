# -*- coding: utf-8 -*-
"""案件管理頁（case-management.html）的版面 ON 狀態：真瀏覽器＋真的設定／定義 API（BP-1 C1／C2／C3；已寫、未跑）。

場景：
  C-1 區塊：隱藏專案期間、改名自訂欄位以外的可改名區塊、把人員角色排到合約資訊之前（健康總覽固定最上、客戶回簽單固定最下）
  C-2 分頁列：隱藏「承攬商」、把「動態」改名、把「財務」排到前面；目前停在被隱藏的分頁會被拉回
  C-3 執行管理子分頁：隱藏保固備註、待辦事項改名、設備登錄排到材料申請之前；停在被隱藏的子分頁 ⇒ 退回執行進度
  C-4 被隱藏區塊的資料照樣自動存檔：隱藏專案期間後改人員角色（可見）與專案期間的日期（不可見）⇒ PATCH case-record ⇒ 資料庫有
  C-5 核心項目不能被隱藏／改名（發布被擋 422），畫面不變
"""
import pytest

from tests._requires import requires_module
from tests.e2e_on_state._common import (DATA_JS, SUB_TABS, TOP_TABS, api, open_case, pid, publish_layout, seed_case, set_flag,
                                        stored_data, token_of, visible_tab_texts, wait_layout_on, y_of)

pytestmark = [pytest.mark.e2e, requires_module("case", "案件管理頁")]
PAGE = "case-management.html"
BLOCKS = pid(PAGE, "list", "bizBlocks")
TABS = pid(PAGE, "list", "tabs")
EXEC = pid(PAGE, "list", "execTabs")


def _col(lst, f):
    return pid(PAGE, "list", lst, f)


def _boot(live_server, make_user, new_context, no, ops, tab="biz"):
    u = make_user(username="on_case_" + no[-3:].lower(), role="superadmin")
    ctx = new_context()
    tk = token_of(ctx, live_server, u)
    seed_case(no)
    set_flag(ctx, live_server, tk, "builder_layout", "case_management", 1)
    if ops:
        publish_layout(ctx, live_server, tk, ops)
    page = ctx.new_page()
    open_case(page, live_server, u, no, tab)
    wait_layout_on(page)
    return u, ctx, tk, page


def test_c1_biz_blocks_hide_and_reorder(live_server, make_user, new_context):
    ops = [{"op": "hide", "target": _col("bizBlocks", "timeline")},
           {"op": "reorder", "target": BLOCKS,
            "order": [_col("bizBlocks", f) for f in ("health", "roles", "contract", "timeline", "customFields", "privacy", "signedBack")]}]
    u, ctx, tk, page = _boot(live_server, make_user, new_context, "MQ-ONC-001", ops)
    page.locator(".cm-section-title", has_text="人員角色").first.wait_for(state="visible", timeout=10000)
    assert page.locator(".cm-section-title", has_text="專案期間").count() == 0 or not page.locator(".cm-section-title", has_text="專案期間").first.is_visible()
    assert not page.locator("#cm-tl-start").is_visible()                                      # 專案期間的輸入框一併隱藏
    assert y_of(page, "人員角色") < y_of(page, "合約資訊"), "人員角色應排在合約資訊之前"


def test_c1b_block_title_relabel(live_server, make_user, new_context):
    ops = [{"op": "relabel", "target": _col("bizBlocks", "timeline"), "label": "施工期間"}]
    u, ctx, tk, page = _boot(live_server, make_user, new_context, "MQ-ONC-002", ops)
    page.locator(".cm-section-title", has_text="施工期間").first.wait_for(state="visible", timeout=10000)
    assert page.locator(".cm-section-title", has_text="專案期間").count() == 0                  # 預設字被改名取代


def test_c2_top_tab_bar_hide_relabel_reorder(live_server, make_user, new_context):
    ops = [{"op": "hide", "target": _col("tabs", "dispatch")},
           {"op": "relabel", "target": _col("tabs", "feed"), "label": "進度動態"},
           {"op": "reorder", "target": TABS, "order": [_col("tabs", f) for f in ("biz", "fin", "exec", "shipping", "completion", "feed", "allfiles", "xexp")]}]
    u, ctx, tk, page = _boot(live_server, make_user, new_context, "MQ-ONC-003", ops)
    texts = visible_tab_texts(page, TOP_TABS)
    assert "承攬商" not in texts and "動態" not in texts and "進度動態" in texts
    assert texts.index("財務") < texts.index("執行管理"), texts
    assert texts[0] == "案件資訊", texts                                                     # 核心分頁維持第一個
    # 目前停在被隱藏的分頁 ⇒ 拉回（tabFix）
    page.evaluate("() => { %s.activeTab = 'dispatch' }" % DATA_JS)
    page.wait_for_function("() => %s.activeTab !== 'dispatch'" % DATA_JS, timeout=5000)


def test_c3_exec_sub_tabs(live_server, make_user, new_context):
    ops = [{"op": "hide", "target": _col("execTabs", "warranty")},
           {"op": "relabel", "target": _col("execTabs", "todos"), "label": "我的待辦"},
           {"op": "reorder", "target": EXEC, "order": [_col("execTabs", f) for f in ("progress", "devices", "materials", "todos", "info")]}]
    u, ctx, tk, page = _boot(live_server, make_user, new_context, "MQ-ONC-004", ops, tab="exec")
    page.locator(".cm-subtabs").first.wait_for(state="visible", timeout=10000)
    texts = visible_tab_texts(page, SUB_TABS)
    assert "保固備註" not in texts and "待辦事項" not in texts and "我的待辦" in texts
    assert texts.index("設備登錄") < texts.index("材料申請"), texts
    assert texts[0] == "執行進度", texts                                                     # 核心子分頁
    page.evaluate("() => { %s.execSubTab = 'warranty' }" % DATA_JS)                         # 停在被隱藏的子分頁 ⇒ 退回執行進度
    page.wait_for_function("() => %s.execSubTab === 'progress'" % DATA_JS, timeout=5000)


def test_c4_hidden_block_data_still_autosaves(live_server, make_user, new_context):
    ops = [{"op": "hide", "target": _col("bizBlocks", "timeline")}]
    u, ctx, tk, page = _boot(live_server, make_user, new_context, "MQ-ONC-005", ops)
    sel = page.locator("#cm-role-executor")
    sel.wait_for(state="visible", timeout=10000)
    with page.expect_response(lambda r: "/case-record" in r.url and r.request.method == "PATCH", timeout=15000) as resp:
        sel.select_option(value=u[0])                                                       # 可見區塊（人員角色）的改動 ⇒ 自動存檔
    assert resp.value.ok
    with page.expect_response(lambda r: "/case-record" in r.url and r.request.method == "PATCH", timeout=15000) as resp2:
        page.evaluate("""() => { const c = %s; c.cr.caseRecord.projectTimeline.startDate = '2026-11-01'; c.setDirty() }""" % DATA_JS)   # 被隱藏區塊的資料
    assert resp2.value.ok
    cr = stored_data("MQ-ONC-005")["caseRecord"]
    assert cr["roles"]["executor"] == u[0], cr["roles"]
    assert cr["projectTimeline"]["startDate"] == "2026-11-01", cr["projectTimeline"]


def test_c5_core_items_cannot_be_hidden_or_renamed(live_server, make_user, new_context):
    u, ctx, tk, page = _boot(live_server, make_user, new_context, "MQ-ONC-006", [])
    for lst, core in (("bizBlocks", "contract"), ("bizBlocks", "roles"), ("tabs", "biz"), ("execTabs", "progress")):
        for op in ({"op": "hide", "target": _col(lst, core)}, {"op": "relabel", "target": _col(lst, core), "label": "x"}):
            s, _ = api(ctx, live_server, "PUT", "/api/definitions/layout/module:case/draft", tk, {"body": {"ops": [op]}}, {"scope": "company"})
            if s == 200:                                                                    # 草稿能存，發布一定被擋
                s2, _ = api(ctx, live_server, "POST", "/api/definitions/layout/module:case/publish", tk, {"note": "x"}, {"scope": "company"})
                assert s2 == 422, (lst, core, op["op"], s2)
            else:
                assert s == 422, (lst, core, op["op"], s)
    page.reload()
    wait_layout_on(page)
    assert page.locator(".cm-section-title", has_text="合約資訊").first.is_visible()
