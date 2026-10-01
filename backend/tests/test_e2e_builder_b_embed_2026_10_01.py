# -*- coding: utf-8 -*-
"""建構器方案 B：嵌入頁（custom-records.html?embed=1）的上下文與訊息防護。

① 上下文：`ctx.<鍵>=<值>` ⇒ 列表只列該值的單據（走既有 ?field=&value= 篩選）、新增單據時 contextField 欄位預填。
   （首個掛載點 daily-tasks 沒有 context，所以這裡用 monkeypatch 注入一個有 context 的測試掛載點；伺服器與測試同行程。）
② 訊息防護：外層只接受「同源」且「來源是自己建立的 iframe」的 motrix-embed-height——同源的外層自己發的訊息（source＝外層視窗）、
   沙盒 iframe（origin 'null'）發的訊息，都不可以改到頁籤 iframe 的高度。
"""
import json
from datetime import date

import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_e2e_builder_b_mount_2026_10_01 import (IFRAME, KEY, POINT, TAB, _hdr, _open_and_select, _body)  # noqa: E402,F401

CTX_POINT = "daily_tasks.ctx-demo"


def _inject_ctx_point(monkeypatch):
    from helpers import custom_modules as CM
    real = CM._loaded_manifests

    def patched():
        m = real()
        d = dict(m.get("daily_tasks") or {})
        d["mount_points"] = list(d.get("mount_points") or []) + [{"key": "ctx-demo", "page": "daily-tasks.html", "kind": "tab",
                                                                   "label": "上下文測試", "perm": "any", "context": ["case_no"]}]
        m = dict(m)
        m["daily_tasks"] = d
        return m
    monkeypatch.setattr(CM, "_loaded_manifests", patched)


@pytest.mark.e2e
def test_embed_context_filters_the_list_and_prefills_the_new_record(live_server, client, make_user, new_context, monkeypatch):
    _inject_ctx_point(monkeypatch)
    sa = make_user(username="em_sa", role="superadmin")
    h = _hdr(client, sa)
    body = _body()
    body["fields"] = [{"key": "case_no", "label": "案件編號", "type": "text", "dataClass": "T1"}, {"key": "a", "label": "摘要", "type": "text", "dataClass": "T1"}]
    body["mount"] = {"point": CTX_POINT, "label": "上下文", "contextField": "case_no"}
    r = client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=h, json={"body": body})
    assert r.status_code == 200 and r.json()["problems"] == [], r.text
    assert client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=h, json={}).status_code == 200
    for case, summary in (("MQ-A", "甲案的單"), ("MQ-B", "乙案的單")):
        rr = client.post("/api/custom/%s/records" % KEY, headers=h, json={"values": {"case_no": case, "a": summary}})
        assert rr.status_code == 200, rr.text
    from tests._e2e_login import inject_login
    page = new_context(viewport={"width": 1200, "height": 900}).new_page()
    inject_login(page, live_server, sa[0], sa[1])
    page.goto("%s/pages/custom-records.html?key=%s&embed=1&ctx.case_no=MQ-A" % (live_server, KEY))
    page.wait_for_selector("#cr-new", state="visible", timeout=30000)
    page.wait_for_function("() => document.body.innerText.indexOf('甲案的單') >= 0 || document.querySelectorAll('tbody tr').length > 0", timeout=20000)
    text = page.inner_text("body")
    assert "MQ-A" in text and "MQ-B" not in text, "列表應只含上下文值的單據：" + text[:300]
    page.click("#cr-new")
    page.wait_for_selector("#cr-form", state="visible")
    assert page.locator("#cr-form input").first.input_value() == "MQ-A", "新增時 contextField 應預填上下文值"
    # 沒帶 ctx ⇒ 不篩選（正對照）
    page.goto("%s/pages/custom-records.html?key=%s&embed=1" % (live_server, KEY))
    page.wait_for_selector("#cr-new", state="visible", timeout=30000)
    page.wait_for_function("() => document.body.innerText.indexOf('MQ-B') >= 0", timeout=20000)
    assert "MQ-A" in page.inner_text("body")


@pytest.mark.e2e
def test_foreign_height_messages_are_ignored(live_server, client, make_user, new_context):
    sa = make_user(username="em2_sa", role="superadmin")
    ok = make_user(username="em2_ok", role="user", modules=["daily_task", "custom." + KEY])
    h = _hdr(client, sa)
    assert client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=h, json={"body": _body()}).status_code == 200
    assert client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=h, json={}).status_code == 200
    assert client.post("/api/daily-tasks", headers=h, json={"task_date": date.today().isoformat(), "title": "訊息防護",
                                                            "assigned_to": ["em2_ok"]}).status_code == 201
    from tests._e2e_login import inject_login
    page = new_context(viewport={"width": 1440, "height": 1000}).new_page()
    inject_login(page, live_server, ok[0], ok[1])
    _open_and_select(page, live_server)
    page.click(TAB)
    page.wait_for_selector(IFRAME, state="attached", timeout=15000)
    page.frame_locator(IFRAME).locator("#cr-new").wait_for(state="visible", timeout=30000)
    HEIGHT = "() => Math.round(document.querySelector('iframe[data-mt-key]').getBoundingClientRect().height)"
    # 等內頁自己回報的高度穩定（postMessage 非同步；回報量測是 body 高度，應該收斂而不是來回變）
    page.wait_for_function("() => Math.round(document.querySelector('iframe[data-mt-key]').getBoundingClientRect().height) !== 480", timeout=15000)
    page.wait_for_timeout(2500)
    # 取樣器：記錄之後 iframe 高度出現過的最大值——內頁的回報會把高度拉回來，所以只比「前後相等」看不出外來訊息有沒有生效
    page.evaluate("""(sel) => { window.__maxH = 0; setInterval(() => { const f = document.querySelector(sel); if (f) window.__maxH = Math.max(window.__maxH, f.getBoundingClientRect().height) }, 15) }""", "iframe[data-mt-key]")
    before = page.evaluate(HEIGHT)
    # (a) 外層視窗自己發（同源，但 source 不是任何頁籤 iframe）
    page.evaluate("() => window.postMessage({ type: 'motrix-embed-height', height: 5000 }, location.origin)")
    # (b) 沙盒 iframe（origin 為 'null'）發給外層
    page.evaluate("""() => { const f = document.createElement('iframe'); f.setAttribute('sandbox', 'allow-scripts'); f.style.display = 'none';
        f.srcdoc = "<script>parent.postMessage({ type: 'motrix-embed-height', height: 5000 }, '*')<\/script>"; document.body.appendChild(f) }""")
    page.wait_for_timeout(1500)                                         # 給兩則訊息送達與處理的時間（要證明「沒有發生」只能等）
    peak = page.evaluate("() => window.__maxH")
    assert peak < before + 400, "外來訊息改變了頁籤 iframe 高度（原本 %s，期間最高 %s）" % (before, peak)
