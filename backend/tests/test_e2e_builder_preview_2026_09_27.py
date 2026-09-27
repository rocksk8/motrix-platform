"""模組建構器的即時預覽（docs/platform/BUILDER-UX.md §3.2／§3.3／§6-3；A：form-preview.js＋custom-records.html 預覽掛鉤）。

① 同一份模組定義：預覽的表單與正式執行頁的表單 DOM 一致（欄位順序、型別、標籤、必填、分組標題）——
   預覽就是執行頁本身（iframe 載入 custom-records.html?preview=1），所以改執行期模板，預覽跟著變。
② 預覽模式不打任何 API：攔截預覽 iframe 的所有請求，呼叫次數 0；存檔無效；直接開 ?preview=1 也一樣。
③ postMessage 只收同源、約定格式；iframe 帶 sandbox（allow-scripts allow-same-origin，沒有 forms／top-navigation）。
④ update() 不重新載入、不搶焦點；highlight 框起選中的欄位；未知型別畫佔位。
⑤ 流程／簽核／通知／輸出縮圖是純函式 SVG。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402

KEY = "bp_preview_mod"


def _definition():
    return {
        "name": "預覽一致性測試", "icon": "box", "permission": "custom.%s" % KEY,
        "numbering": {"prefix": "BP", "date": "", "digits": 3},
        "fields": [
            {"key": "item", "label": "設備", "type": "text", "required": True, "dataClass": "T1"},
            {"key": "qty", "label": "數量", "type": "number", "required": True, "dataClass": "T1"},
            {"key": "price", "label": "單價", "type": "number", "default": 0, "dataClass": "T1"},
            {"key": "total", "label": "總值", "type": "formula", "formula": "qty * price", "dataClass": "T1"},
            {"key": "kind", "label": "類別", "type": "select", "options": ["甲", "乙"], "dataClass": "T1"},
            {"key": "urgent", "label": "急件", "type": "checkbox", "dataClass": "T1"},
            {"key": "who", "label": "對象", "type": "ref", "target": "users", "dataClass": "T1"},
            {"key": "day", "label": "日期", "type": "date", "required": True, "dataClass": "T1"},
        ],
        "workflow": {"initial": "draft", "states": [
            {"key": "draft", "label": "草稿"},
            {"key": "pending", "label": "簽核中", "approval": {
                "tiers": [{"approvers": [{"username": "bp_mgr"}]},
                          {"approvers": [{"username": "bp_boss"}, {"username": "bp_mgr"}], "when": "total > 100"}],
                "on_approved": "done", "on_rejected": "draft"}},
            {"key": "done", "label": "完成", "final": True, "notify": {"requester": True, "users": ["bp_mgr"]}}],
            "transitions": [{"key": "submit", "label": "送審", "from": "draft", "to": "pending"},
                            {"key": "reopen", "label": "退回", "from": ["pending"], "to": "draft"}]},
        "ui": {"form": {"groups": [{"title": "基本", "fields": ["item", "qty", "price", "total"]},
                                   {"title": "其他", "fields": ["day", "kind", "urgent", "who"]}]},
               "list": {"columns": ["$recordNo", "$status", "item", "qty"]}},
    }


def _publish(client, h, key, body):
    assert client.put("/api/definitions/custom_module/%s/draft" % key, json={"body": body}, headers=h).status_code == 200
    r = client.post("/api/definitions/custom_module/%s/publish" % key, json={}, headers=h)
    assert r.status_code == 200, r.text


def _h(client, user):
    r = client.post("/api/auth/login", json={"username": user[0], "password": user[1]})
    return {"Authorization": "Bearer " + r.json()["token"]}


#: 從一個文件取出表單的結構（執行頁與預覽用同一支，比的是同一組觀測點）
_SHAPE_JS = """() => [...document.querySelectorAll('#cr-form .cr-sec')].map(sec => ({
  title: (sec.querySelector('.cr-sec__t') || {}).textContent || '',
  fields: [...sec.querySelectorAll('.cr-f')].map(f => {
    const k = f.getAttribute('data-field')
    const req = f.querySelector('label .req')
    const ctl = f.querySelector('#cr-in-' + CSS.escape(k))
    return { key: k, label: f.querySelector('label span').textContent,
             required: !!(req && getComputedStyle(req).display !== 'none'), reqMark: req ? req.textContent : '',
             control: ctl ? (ctl.tagName.toLowerCase() + (ctl.type ? ':' + ctl.type : '') + (ctl.hasAttribute('data-formula') ? ':formula' : '')) : '' }
  })
}))"""


def _harness(browser, base):
    """同源的空白宿主頁＋form-preview.js（建構器頁屬 B，這裡不依賴它）。"""
    page = browser.new_page()
    page.goto(base + "/pages/login.html")
    page.set_content('<!doctype html><html><head><meta charset="utf-8"></head><body>'
                     '<input id="focusme"><div id="host"></div><div id="thumbs"></div></body></html>')
    page.add_script_tag(url=base + "/static/form-preview.js")
    page.wait_for_function("() => !!window.MotrixFormPreview")
    page.evaluate("""() => { window.__readyCount = 0; window.__fpMsgs = []
      window.addEventListener('message', e => { if (e.data && e.data.type === 'motrix-preview') {
        window.__fpMsgs.push(e.data.kind); if (e.data.kind === 'ready') window.__readyCount++ } }) }""")
    return page


def _preview_frame(page):
    page.wait_for_function("() => window.__readyCount >= 1", timeout=15000)
    fr = next(f for f in page.frames if "preview=1" in f.url)
    return fr


def _render(page, definition, mode="form", highlight=None):
    page.evaluate("([d, m, hl]) => { window.__h = MotrixFormPreview.render(document.getElementById('host'), d, {mode: m, highlight: hl}) }",
                  [definition, mode, highlight])
    fr = _preview_frame(page)
    n = len(definition.get("fields") or [])
    want = "#cr-list thead th" if mode == "list" else "#cr-form .cr-f"
    try:
        fr.wait_for_function("([sel, n]) => document.querySelectorAll(sel).length >= (sel.indexOf('thead') >= 0 ? 1 : n)",
                             arg=[want, n], timeout=15000)
    except Exception:
        diag = {"parent_msgs": page.evaluate("() => window.__fpMsgs"),
                "frame": fr.evaluate("() => ({mode: Alpine.$data(document.body).mode, preview: Alpine.$data(document.body).preview,"
                                     " fields: document.querySelectorAll('.cr-f').length, blocked: window.__motrixPreviewBlocked})")}
        raise AssertionError("預覽沒有畫出草稿：%s" % json.dumps(diag, ensure_ascii=False))
    return fr


@pytest.mark.e2e
def test_preview_form_matches_the_runtime_form(live_server, make_user, e2e_browser, client):
    """①：同一份定義，執行頁「新增」表單與預覽表單的結構逐欄相同；預覽的具體樣子來自執行期模板（必填記號 *、日期欄 input:date）。"""
    user = make_user(username="bp_sa", role="superadmin")
    _publish(client, _h(client, user), KEY, _definition())
    rt = e2e_browser.new_page()
    inject_login(rt, live_server, user[0], user[1])
    rt.goto(live_server + "/pages/custom-records.html?key=" + KEY)
    rt.locator("#cr-new").click()
    rt.wait_for_function("() => document.querySelectorAll('#cr-form .cr-f').length === 8", timeout=15000)
    runtime = rt.evaluate(_SHAPE_JS)

    page = _harness(e2e_browser, live_server)
    fr = _render(page, _definition())
    fr.wait_for_function("() => document.querySelectorAll('#cr-form .cr-f').length === 8", timeout=15000)
    preview = fr.evaluate(_SHAPE_JS)
    assert preview == runtime, json.dumps({"runtime": runtime, "preview": preview}, ensure_ascii=False)[:2000]
    flat = {f["key"]: f for s in preview for f in s["fields"]}
    assert [s["title"] for s in preview] == ["基本", "其他"]
    assert [f["key"] for s in preview for f in s["fields"]] == ["item", "qty", "price", "total", "day", "kind", "urgent", "who"]
    assert flat["item"]["required"] and flat["item"]["reqMark"] == "*" and not flat["price"]["required"]
    assert flat["day"]["control"] == "input:date" and flat["total"]["control"].endswith(":formula")


#: 預覽「不打 API」的唯一豁免（主持 2026-09-28 裁示）：品牌包的 favicon——瀏覽器自己抓的公開唯讀圖示，不是資料 API
FAVICON_EXEMPT = ("GET", "/api/system/branding/favicon")


def counts_as_api(method, url):
    """這個請求算不算「打 API」：路徑含 /api/，扣掉 FAVICON_EXEMPT（方法＋路徑都要完全相同；查詢字串不看）。"""
    from urllib.parse import urlsplit
    path = urlsplit(url).path
    if "/api/" not in path:
        return False
    return (method.upper(), path) != FAVICON_EXEMPT


@pytest.mark.e2e
def test_preview_mode_makes_no_api_calls(live_server, make_user, e2e_browser):
    """②：預覽 iframe 發出的請求裡 /api/ 次數 0；後備攔截器也沒有被觸發（沒有任何程式碼試著打）；按存檔無效。
    同一個旗標：本頁的 api() 直接拒絕（不走到 fetch）；有人硬呼叫 fetch 也被攔下、記次、不出網路。"""
    page = _harness(e2e_browser, live_server)
    api_reqs = []
    page.on("request", lambda r: api_reqs.append(r.url) if (counts_as_api(r.method, r.url) and r.frame.url and "preview=1" in r.frame.url) else None)
    fr = _render(page, _definition())
    fr.wait_for_function("() => document.querySelectorAll('#cr-form .cr-f').length === 8", timeout=15000)
    fr.locator("#cr-save").click()
    page.wait_for_timeout(300)
    assert api_reqs == [], api_reqs
    assert fr.evaluate("() => window.__motrixPreviewBlocked") == 0, "預覽模式不該有任何程式碼試著打 API"
    got = fr.evaluate("""async () => {
      const c = Alpine.$data(document.body); let viaApi = 'resolved'
      try { await c.api('GET', '/api/auth/me') } catch (e) { viaApi = 'refused' }
      const before = window.__motrixPreviewBlocked
      let raw = 'resolved'
      try { await fetch('/api/auth/me') } catch (e) { raw = 'refused' }
      return { viaApi, raw, before, after: window.__motrixPreviewBlocked }
    }""")
    assert got == {"viaApi": "refused", "raw": "refused", "before": 0, "after": 1}, got
    page.wait_for_timeout(200)
    assert api_reqs == [], api_reqs


@pytest.mark.e2e
def test_opening_preview_directly_leaks_nothing(live_server, e2e_browser):
    """②：直接開 custom-records.html?preview=1（沒有登入、不在 iframe 裡）⇒ 不轉登入頁、不打 API。"""
    page = e2e_browser.new_page()
    api_reqs = []
    page.on("request", lambda r: api_reqs.append(r.url) if counts_as_api(r.method, r.url) else None)
    page.goto(live_server + "/pages/custom-records.html?preview=1")
    page.wait_for_function("() => window.Alpine && Alpine.$data(document.body) && Alpine.$data(document.body).preview === true")
    page.wait_for_timeout(300)
    assert "custom-records.html" in page.url and api_reqs == [], (page.url, api_reqs)


@pytest.mark.e2e
def test_only_the_branding_favicon_is_exempt_from_the_no_api_rule(live_server, e2e_browser):
    """正對照＋反向控制（主持 2026-09-28 裁示：favicon 語意衝突，TRAIN14-PREP §1-6）：
    品牌包把頁面 favicon 改成 `GET /api/system/branding/favicon`——瀏覽器自己抓、不經 window.fetch，預覽的防線擋不到，
    而它是公開唯讀的圖示，不是資料 API ⇒ 只豁免這一個。在同一頁用**非 fetch** 的方式載入：
    ① favicon 端點 ⇒ 不算（豁免有效，沒有品牌包的樹上也驗得到）；② `/api/system/branding`（JSON）⇒ 算（豁免沒有放寬到別的 /api/）。"""
    page = e2e_browser.new_page()
    try:
        api_reqs, seen = [], []
        page.on("request", lambda r: (seen.append(r.url), api_reqs.append(r.url) if counts_as_api(r.method, r.url) else None))
        page.goto(live_server + "/pages/custom-records.html?preview=1")
        page.wait_for_function("() => window.Alpine && Alpine.$data(document.body) && Alpine.$data(document.body).preview === true")
        page.evaluate("""() => { for (const u of ['/api/system/branding/favicon', '/api/system/branding']) {
            const i = new Image(); i.src = u; document.body.appendChild(i) } }""")
        page.wait_for_function("() => performance.getEntriesByType('resource').filter(e => e.name.includes('/api/system/branding')).length >= 2")
        assert any(u.endswith("/api/system/branding/favicon") for u in seen), seen      # 請求真的有發出（觀測點量得到）
        assert [u for u in api_reqs if u.endswith("/api/system/branding/favicon")] == [], api_reqs
        assert any(u.endswith("/api/system/branding") for u in api_reqs), ("其他 /api/ 必須照算", api_reqs)
    finally:
        page.close()


def test_counts_as_api_exempts_exactly_one_request():
    """豁免只有「GET＋路徑恰好等於 /api/system/branding/favicon」（查詢字串不影響）；其餘 /api/ 一律算。"""
    base = "http://127.0.0.1:1"
    assert not counts_as_api("GET", base + "/api/system/branding/favicon")
    assert not counts_as_api("GET", base + "/api/system/branding/favicon?v=3")
    for method, path in (("GET", "/api/system/branding"), ("POST", "/api/system/branding/favicon"),
                         ("GET", "/api/system/branding/favicon2"), ("GET", "/api/system/branding/favicon/x"),
                         ("GET", "/api/auth/me"), ("GET", "/x/api/system/branding/favicon")):
        assert counts_as_api(method, base + path), (method, path)
    assert not counts_as_api("GET", base + "/pages/custom-records.html")


@pytest.mark.e2e
def test_messages_from_elsewhere_are_ignored_and_the_frame_is_sandboxed(live_server, e2e_browser):
    """③：非同源、格式不對、不是父頁送的訊息一律忽略；iframe 只有 allow-scripts allow-same-origin。"""
    page = _harness(e2e_browser, live_server)
    fr = _render(page, _definition())
    fr.wait_for_function("() => document.querySelectorAll('#cr-form .cr-f').length === 8", timeout=15000)
    other = {"name": "x", "fields": [{"key": "evil", "label": "惡意", "type": "text"}]}
    page.evaluate("d => { const w = window.__h.iframe.contentWindow; w.postMessage({type: 'motrix-preview', v: 2, kind: 'draft', draft: d}, location.origin);"
                  " w.postMessage({type: 'other', v: 1, kind: 'draft', draft: d}, location.origin) }", other)
    fr.evaluate("""d => { window.dispatchEvent(new MessageEvent('message', {data: {type: 'motrix-preview', v: 1, kind: 'draft', draft: d},
      origin: 'https://evil.example', source: window.parent}))
      window.dispatchEvent(new MessageEvent('message', {data: {type: 'motrix-preview', v: 1, kind: 'draft', draft: d},
      origin: location.origin, source: window})) }""", other)
    page.wait_for_timeout(300)
    assert fr.evaluate("() => document.querySelectorAll('[data-field=\"evil\"]').length") == 0
    assert fr.evaluate("() => document.querySelectorAll('#cr-form .cr-f').length") == 8
    sb = page.evaluate("() => window.__h.iframe.getAttribute('sandbox')")
    assert sorted(sb.split()) == ["allow-same-origin", "allow-scripts"], sb


@pytest.mark.e2e
def test_update_keeps_focus_and_frame_and_highlight_frames_the_field(live_server, e2e_browser):
    """④：update() 不重新載入（ready 只有一次、同一個 iframe）、不搶焦點；setHighlight 只框一個欄位；未知型別畫佔位。"""
    page = _harness(e2e_browser, live_server)
    fr = _render(page, _definition(), highlight="qty")
    fr.wait_for_function("() => document.querySelectorAll('.cr-f.is-preview-hl').length === 1", timeout=15000)
    assert fr.evaluate("() => document.querySelector('.cr-f.is-preview-hl').getAttribute('data-field')") == "qty"
    page.locator("#focusme").focus()
    page.keyboard.type("ab")
    d2 = _definition()
    d2["fields"].append({"key": "sig", "label": "簽名", "type": "signature", "dataClass": "T1"})
    page.evaluate("d => window.__h.update(d)", d2)
    fr.wait_for_function("() => !!document.querySelector('[data-field=\"sig\"] [data-preview-placeholder]')", timeout=15000)
    page.keyboard.type("c")
    assert page.evaluate("() => [document.activeElement.id, document.getElementById('focusme').value]") == ["focusme", "abc"]
    assert page.evaluate("() => window.__readyCount") == 1, "update 不可以重新載入 iframe"
    assert fr.evaluate("() => document.querySelector('.cr-f.is-preview-hl').getAttribute('data-field')") == "qty", "重畫後保留選中的欄位"
    page.evaluate("() => window.__h.setHighlight('day')")
    fr.wait_for_function("() => document.querySelector('.cr-f.is-preview-hl') && document.querySelector('.cr-f.is-preview-hl').getAttribute('data-field') === 'day'")
    assert fr.evaluate("() => document.querySelectorAll('.cr-f.is-preview-hl').length") == 1


@pytest.mark.e2e
def test_list_mode_uses_the_runtime_columns(live_server, e2e_browser):
    """列表模式：欄位標題照 ui.list.columns（執行期 custom-layout.js 的同一套規則）。"""
    page = _harness(e2e_browser, live_server)
    fr = _render(page, _definition(), mode="list")
    fr.wait_for_function("() => document.querySelectorAll('#cr-list thead th').length === 4", timeout=15000)
    assert fr.evaluate("() => [...document.querySelectorAll('#cr-list thead th')].map(t => t.textContent)") == ["編號", "狀態", "設備", "數量"]


@pytest.mark.e2e
def test_step_thumbnails_are_pure_svg(live_server, e2e_browser):
    """⑤：流程／簽核／通知／輸出縮圖＝純函式 SVG：內容來自草稿、文字有跳脫、空的步驟說明為什麼空、不寫色碼。"""
    page = _harness(e2e_browser, live_server)
    d = _definition()
    d["workflow"]["states"][0]["label"] = "<b>草稿</b>"
    d["output"] = {"template": {"key": "k", "version": 1, "theme": "plain", "title": {"path": "item", "suffix": ""},
                                "blocks": [{"type": "heading"}, {"type": "fields"}, {"type": "signatures"}]}}
    got = page.evaluate("""d => { const S = MotrixFormPreview.svg; const q = (s, sel) => { const x = document.createElement('div'); x.innerHTML = s; return x.querySelectorAll(sel).length }
      const w = S.workflow(d), a = S.approval(d), n = S.notify(d), o = S.output(d)
      return { states: q(w, '[data-state]'), arcs: q(w, '[data-transition]'), escaped: w.indexOf('&lt;b&gt;') >= 0 && w.indexOf('<b>') < 0,
               tiers: q(a, '[data-tier]'), notify: q(n, '[data-notify]'), blocks: q(o, '[data-block]'),
               emptyWf: S.workflow({}).indexOf('尚未設定狀態') >= 0, emptyOut: S.output({}).indexOf('沒有輸出版型') >= 0,
               colors: /#[0-9a-fA-F]{3,6}\\b|rgb\\(/.test(w + a + n + o) }
    }""", d)
    assert got == {"states": 3, "arcs": 2, "escaped": True, "tiers": 2, "notify": 1, "blocks": 3,
                   "emptyWf": True, "emptyOut": True, "colors": False}, got
    page.evaluate("d => { window.__t = MotrixFormPreview.thumb(document.getElementById('thumbs'), d, {step: 'workflow'}) }", d)
    assert page.locator('#thumbs svg[data-thumb="workflow"]').count() == 1
