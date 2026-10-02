# -*- coding: utf-8 -*-
"""表單設計器的輸出跳脫（XSS）守門：欄位名稱、說明、區塊名、選項，以及後端註冊表給的字串，含 HTML／腳本時都只能當文字顯示。
原為 d7 稽核（audit/train31-designer-d7，E1／E2／E4）的獨立探針，併為正式測試：現有題抓不到 `esc()` 失效（稽核 M4 突變只有這組會紅）。"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._builder_nav import go_step  # noqa: E402

KEY = "fd_xss"
XSS = ['<img src=x onerror=window.__x=1>', '"><script>window.__x=2</script>', "javascript:window.__x=3", "<b onmouseover=window.__x=4>m</b>"]
HOSTILE_DOM = "() => document.querySelectorAll('.fd img[src=x], .fd script, .fd [onerror], .fd [onmouseover]').length"


def _body():
    return {"name": "注入測試", "icon": "", "permission": "custom." + KEY, "numbering": {"prefix": "XS", "date": "YYYYMMDD", "digits": 4},
            "fields": [{"key": "place", "label": XSS[0], "type": "text", "dataClass": "T1", "required": True, "help": XSS[1]},
                       {"key": "amount", "label": XSS[1], "type": "number", "dataClass": "T1", "min": 0},
                       {"key": "kind", "label": XSS[2], "type": "select", "dataClass": "T1", "options": XSS[:4]}],
            "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿", "final": True}], "transitions": []},
            "ui": {"form": {"groups": [{"title": XSS[3], "fields": ["place", "amount", "kind"]}]}, "list": {"columns": ["place", "amount"]}}}


def _open(live_server, client, make_user, new_context, route=None):
    user = make_user(username="xss_sa", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": user[0], "password": user[1]}).json()["token"]
    assert client.put("/api/definitions/custom_module/%s/draft" % KEY, json={"body": _body()}, headers={"Authorization": "Bearer " + tok}).status_code == 200
    ctx = new_context(viewport={"width": 1600, "height": 1000})
    if route:
        ctx.route("**/api/platform/prefill-sources", route)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, user[0], user[1])
    page.goto("%s/pages/module-builder.html?key=%s&designer=1" % (live_server, KEY))
    page.wait_for_selector("#mb-step-1", state="visible")
    go_step(page, 2)
    page.wait_for_selector(".fd .fd-paper", state="visible", timeout=20000)
    page.errors = errors
    return page


@pytest.mark.e2e
def test_hostile_field_text_renders_as_text_everywhere(live_server, client, make_user, new_context):
    page = _open(live_server, client, make_user, new_context)
    for key in ("place", "amount", "kind"):                              # 每個欄位點開：右欄、選項清單都渲染
        page.click('.fd-center .fd-fld[data-key="%s"]' % key)
        page.wait_for_timeout(250)
    page.click('.fd-bar [data-fd-act="check"]')                          # 用語檢查表
    page.wait_for_selector("dialog[data-fd-checklist][open]")
    page.click("dialog[data-fd-checklist] [data-r]")
    assert page.evaluate("() => typeof window.__x") == "undefined", "注入的腳本被執行了"
    assert page.evaluate(HOSTILE_DOM) == 0
    assert page.evaluate("() => document.querySelectorAll('.fd a[href^=\"javascript\"]').length") == 0       # 協定字串不成連結
    assert "window.__x=1" in page.inner_text(".fd"), "惡意字串應以文字顯示（轉義）"
    assert not page.errors, page.errors


@pytest.mark.e2e
def test_hostile_registry_strings_render_as_text(live_server, client, make_user, new_context):
    evil = [{"token": "evil.<img src=x onerror=window.__x=5>", "label": "<img src=x onerror=window.__x=6>標籤", "why": "<script>window.__x=7</script>為什麼",
             "example": "\"><b onmouseover=window.__x=8>例</b>", "applies_to": [["text"]], "lockable": True, "needs_context": False, "requires_time": False}]
    page = _open(live_server, client, make_user, new_context,
                 route=lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(evil)))
    page.click('.fd-center .fd-fld[data-key="place"]')
    page.wait_for_timeout(800)
    assert page.evaluate("() => typeof window.__x") == "undefined"
    assert page.evaluate(HOSTILE_DOM) == 0
    assert "標籤" in page.inner_text(".fd-right"), "註冊表的 label 應出現在下拉（以文字）"
    page.click('.fd-bar [data-fd-act="check"]')
    page.wait_for_selector("dialog[data-fd-checklist][open]")
    assert page.evaluate(HOSTILE_DOM) == 0 and page.evaluate("() => typeof window.__x") == "undefined"
    assert not page.errors, page.errors


@pytest.mark.e2e
def test_reverse_control_the_hostile_dom_check_catches_a_real_injection(live_server, client, make_user, new_context):
    page = _open(live_server, client, make_user, new_context)
    page.evaluate("() => { const d = document.createElement('div'); d.innerHTML = '<img src=x onerror=window.__y=1>'; document.querySelector('.fd').appendChild(d) }")
    assert page.evaluate(HOSTILE_DOM) >= 1, "檢查函式要抓得到真的注入"
