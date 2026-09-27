"""模組建構器的輸出預覽元件（form-preview.js mode:'output'，BUILDER-UX §3.4；A）。

- 內容來自只讀預覽端點（正式匯出同一個 renderer），放進不跑腳本的 sandbox iframe（只有 allow-same-origin）。
- update() 不重建 iframe、不搶焦點；同一時間只有一個請求，途中的草稿只留最後一份。
- 未完成欄位：輸出裡是佔位、提示列出清單；畫不出來（422）⇒ 保留上一次的畫面並說明原因。
"""
import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402
from tests.test_builder_output_preview_2026_09_27 import KEY, _definition  # noqa: E402


def _harness(browser, base, user):
    page = browser.new_page()
    inject_login(page, base, user[0], user[1])
    page.goto(base + "/static/form-preview.js")          # 同源、不會轉址的頁（已登入時 login.html 會自己跳到 index）
    page.set_content('<!doctype html><html><head><meta charset="utf-8"></head><body>'
                     '<input id="focusme"><div id="host"></div></body></html>')
    page.add_script_tag(url=base + "/static/form-preview.js")
    page.wait_for_function("() => !!window.MotrixFormPreview")
    posts = []
    page.on("request", lambda r: posts.append(r.url) if (r.method == "POST" and "/output/preview" in r.url) else None)
    return page, posts


def _frame_text(page):
    return page.evaluate("() => { const d = window.__h.iframe.contentDocument; return d && d.body ? d.body.innerText : '' }")


def _wait_text(page, text, timeout=15000):
    try:
        page.wait_for_function("t => { const d = window.__h.iframe.contentDocument; return !!(d && d.body && d.body.innerText.indexOf(t) >= 0) }",
                               arg=text, timeout=timeout)
    except Exception:
        diag = page.evaluate("""() => { const f = window.__h && window.__h.iframe, n = document.querySelector('.fp-output__note')
          let doc = 'n/a'; try { doc = f.contentDocument ? (f.contentDocument.body ? f.contentDocument.body.innerText.slice(0, 200) : 'nobody') : 'null' } catch (e) { doc = 'ERR ' + e }
          return { srcdocLen: f ? (f.srcdoc || '').length : -1, doc, note: n ? n.textContent : null, session: !!localStorage.getItem('motrix_session') } }""")
        raise AssertionError("輸出預覽沒有出現「%s」：%s" % (text, diag))


def _render(page, d):
    page.evaluate("([d, k]) => { window.__h = MotrixFormPreview.render(document.getElementById('host'), d, {mode: 'output', key: k}) }", [d, KEY])


@pytest.mark.e2e
def test_output_preview_draws_the_server_html_in_a_scriptless_sandbox(live_server, make_user, e2e_browser):
    user = make_user(username="bo_e2e1", role="superadmin")
    page, posts = _harness(e2e_browser, live_server, user)
    _render(page, _definition())
    _wait_text(page, "範例文字")
    assert "輸出預覽測試" in _frame_text(page)
    assert page.evaluate("() => window.__h.iframe.getAttribute('sandbox')") == "allow-same-origin"
    # 正式輸出內建「超過 A4 就縮放」的小腳本；sandbox 沒給 allow-scripts ⇒ 在預覽裡不執行（超過一頁時不縮放，其餘相同）
    assert page.locator(".fp-output__note").is_hidden()
    assert len(posts) == 1


@pytest.mark.e2e
def test_output_update_keeps_focus_and_frame_and_only_sends_the_latest(live_server, make_user, e2e_browser):
    user = make_user(username="bo_e2e2", role="superadmin")
    page, posts = _harness(e2e_browser, live_server, user)
    _render(page, _definition())
    _wait_text(page, "範例文字")
    page.evaluate("() => { window.__first = window.__h.iframe }")
    page.locator("#focusme").focus()
    page.keyboard.type("ab")
    page.evaluate("""d => { for (let i = 1; i <= 5; i++) { const x = JSON.parse(JSON.stringify(d)); x.name = '第' + i + '版'; window.__h.update(x) } }""",
                  _definition())
    _wait_text(page, "第5版")
    page.keyboard.type("c")
    assert page.evaluate("() => [document.activeElement.id, document.getElementById('focusme').value]") == ["focusme", "abc"]
    assert page.evaluate("() => window.__first === window.__h.iframe && document.querySelectorAll('#host iframe').length === 1")
    assert len(posts) <= 3, posts                    # 第一次＋途中那次＋（最多）最後一份；五次 update 不會變成五個請求
    assert "第1版" not in _frame_text(page)


@pytest.mark.e2e
def test_output_and_list_instances_coexist_and_update_independently(live_server, make_user, e2e_browser):
    """建構器同一頁：上方輸出、下方列表兩個實例同時存在，各自 update 只動自己那一個。"""
    user = make_user(username="bo_e2e4", role="superadmin")
    page, posts = _harness(e2e_browser, live_server, user)
    page.evaluate("""([d, k]) => { const host = document.getElementById('host')
      const a = document.createElement('div'), b = document.createElement('div'); host.appendChild(a); host.appendChild(b)
      window.__h = MotrixFormPreview.render(a, d, {mode: 'output', key: k})
      window.__l = MotrixFormPreview.render(b, d, {mode: 'list'}) }""", [_definition(), KEY])
    _wait_text(page, "範例文字")
    fr = None
    page.wait_for_function("() => [...document.querySelectorAll('#host iframe')].length === 2")
    for _ in range(150):
        fr = next((f for f in page.frames if "preview=1" in f.url), None)
        if fr is not None:
            break
        page.wait_for_timeout(100)
    fr.wait_for_function("() => document.querySelectorAll('#cr-list thead th').length >= 1", timeout=15000)
    heads = fr.evaluate("() => [...document.querySelectorAll('#cr-list thead th')].map(t => t.textContent)")
    n_posts = len(posts)
    d2 = _definition()
    d2["ui"] = {"list": {"columns": ["$recordNo", "item"]}}
    page.evaluate("d => window.__l.update(d)", d2)
    fr.wait_for_function("() => document.querySelectorAll('#cr-list thead th').length === 2", timeout=15000)
    page.wait_for_timeout(300)
    assert len(posts) == n_posts, "列表的 update 不該讓輸出重打"
    d3 = _definition()
    d3["name"] = "只改輸出"
    page.evaluate("d => window.__h.update(d)", d3)
    _wait_text(page, "只改輸出")
    assert fr.evaluate("() => document.querySelectorAll('#cr-list thead th').length") == 2, "輸出的 update 不該動到列表"
    assert heads and heads != ["編號", "設備"]


@pytest.mark.e2e
def test_output_half_done_shows_placeholder_and_422_keeps_the_last_picture(live_server, make_user, e2e_browser):
    user = make_user(username="bo_e2e3", role="superadmin")
    page, _posts = _harness(e2e_browser, live_server, user)
    d = _definition()
    d["fields"].append({"key": "memo", "label": "折扣", "type": "formula", "formula": ""})
    _render(page, d)
    _wait_text(page, "〈折扣〉尚未完成")
    page.wait_for_function("() => { const n = document.querySelector('.fp-output__note'); return n && !n.hidden }")
    assert page.locator('.fp-output__note li[data-field="memo"]').count() == 1
    page.evaluate("() => window.__h.update({name: 'x', fields: []})")
    page.wait_for_function("() => document.querySelector('.fp-output__note').textContent.indexOf('還沒有可以預覽的欄位') >= 0")
    assert "〈折扣〉尚未完成" in _frame_text(page), "畫不出來時保留上一次的畫面"
    page.evaluate("() => window.__h.destroy()")
    assert page.evaluate("() => document.querySelectorAll('#host *').length") == 0
