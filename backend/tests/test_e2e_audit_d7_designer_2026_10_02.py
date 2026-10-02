# -*- coding: utf-8 -*-
"""第 31 班表單設計器稽核（d7）：獨立探針（斷言打在草稿 DB／伺服器回應／真 DOM，不讀內部模型當證據）。不隨產品出貨。
B2 四個內建類型不編輯就存草稿＝與出貨定義逐鍵相同；B4 改一欄名稱＝差異恰好 1 處；B3 開關新舊畫面不產生存檔；
C1～C4 預設關閉與開關；E1／E4 注入與協定字串只當文字。"""
import json
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402
from tests._builder_nav import go_step  # noqa: E402

DEFS = Path(__file__).resolve().parents[1] / "helpers" / "expense_type_defs"
KEY = "aud_demo"
XSS = ['<img src=x onerror=window.__x=1>', '"><script>window.__x=2</script>', "javascript:window.__x=3", "<b onmouseover=window.__x=4>m</b>"]


def _db(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args)]
    finally:
        c.close()


def _walk(a, b, path=""):
    """逐鍵差異路徑（含順序：list 逐位、dict 的鍵序用 json.dumps 另比）。"""
    out = []
    if type(a) != type(b):
        return [path or "/"]
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append("%s/%s" % (path, k))
            else:
                out += _walk(a[k], b[k], "%s/%s" % (path, k))
    elif isinstance(a, list):
        if len(a) != len(b):
            return [path + "[len]"]
        for i, (x, y) in enumerate(zip(a, b)):
            out += _walk(x, y, "%s[%d]" % (path, i))
    elif a != b:
        out.append(path)
    return out


def _open_types(e2e_browser, base, user, query="?designer=1"):
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


def _draft_of(code):
    r = _db("SELECT body_json FROM ui_definitions WHERE kind='expense_type' AND key=? AND status='draft' ORDER BY rowid DESC LIMIT 1", (code,))
    return r[0]["body_json"] if r else None


@pytest.mark.e2e
@pytest.mark.parametrize("code", ["purchase_req", "purchase_order", "travel", "petty_cash"])
def test_B2_saving_an_unedited_builtin_type_writes_the_shipped_definition_byte_for_byte(live_server, make_user, e2e_browser, code):
    u = make_user(username="aud_b2_" + code, role="superadmin", modules=[])
    page = _open_types(e2e_browser, live_server, u)
    page.click("[data-testid=et-open-%s]" % code)
    page.wait_for_selector(".fd .fd-paper", state="visible", timeout=20000)
    page.wait_for_timeout(800)
    page.click("[data-testid=et-save]")
    page.wait_for_function("() => (document.querySelector('[data-testid=et-msg]') || {}).innerText && document.querySelector('[data-testid=et-msg]').innerText.includes('草稿已儲存')", timeout=15000)
    raw = _draft_of(code)
    assert raw, "沒有草稿列"
    shipped = json.loads((DEFS / (code + ".json")).read_text(encoding="utf-8"))
    got = json.loads(raw)
    diff = _walk(shipped, got)
    assert diff == [], "存下來的草稿與出貨定義不同：%s" % diff[:10]
    assert json.dumps(shipped, ensure_ascii=False) == json.dumps(got, ensure_ascii=False), "內容相同但鍵順序不同（list.columns／fields 順序被改了）"
    assert not page.errors, page.errors


@pytest.mark.e2e
def test_B4_renaming_one_field_changes_exactly_that_label(live_server, make_user, e2e_browser):
    u = make_user(username="aud_b4", role="superadmin", modules=[])
    page = _open_types(e2e_browser, live_server, u)
    shipped = json.loads((DEFS / "travel.json").read_text(encoding="utf-8"))
    fld = next(f for f in shipped["fields"] if f.get("label") and f["type"] not in ("table", "formula"))
    page.click("[data-testid=et-open-travel]")
    page.wait_for_selector(".fd .fd-paper", state="visible", timeout=20000)
    page.click('.fd-center .fd-fld[data-key="%s"]' % fld["key"])
    box = page.locator('.fd-right [data-fd="label"]')
    box.fill("稽核改名")
    box.dispatch_event("change")
    page.wait_for_timeout(500)
    page.click("[data-testid=et-save]")
    page.wait_for_function("() => document.querySelector('[data-testid=et-msg]').innerText.includes('草稿已儲存')", timeout=15000)
    got = json.loads(_draft_of("travel"))
    idx = shipped["fields"].index(fld)
    assert _walk(shipped, got) == ["/fields[%d]/label" % idx], _walk(shipped, got)
    assert got["fields"][idx]["label"] == "稽核改名"


def _custom_draft(client, tok, body, key=KEY):
    r = client.put("/api/definitions/custom_module/%s/draft" % key, json={"body": body}, headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 200, r.text


def _body(texts=None):
    t = texts or ["地點", "金額", "區塊"]
    return {"name": "稽核", "icon": "", "permission": "custom." + KEY, "numbering": {"prefix": "AD", "date": "YYYYMMDD", "digits": 4},
            "fields": [{"key": "place", "label": t[0], "type": "text", "dataClass": "T1", "required": True, "help": t[0]},
                       {"key": "amount", "label": t[1], "type": "number", "dataClass": "T1", "min": 0},
                       {"key": "kind", "label": "種類", "type": "select", "dataClass": "T1", "options": [{"value": "a", "label": x} for x in XSS[:2]]}],
            "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿", "final": True}], "transitions": []},
            "ui": {"form": {"groups": [{"title": t[2], "fields": ["place", "amount", "kind"]}]}, "list": {"columns": ["place", "amount"]}}}


@pytest.fixture()
def world(live_server, client, make_user):
    user = make_user(username="aud_sa", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": user[0], "password": user[1]}).json()["token"]
    return {"user": user, "tok": tok, "client": client, "base": live_server}


def _builder(world, e2e_browser, query, init_js=None):
    ctx = e2e_browser.new_context(viewport={"width": 1600, "height": 1000})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    if init_js:
        page.add_init_script(init_js)
    inject_login(page, world["base"], world["user"][0], world["user"][1])
    page.goto("%s/pages/module-builder.html?key=%s%s" % (world["base"], KEY, query))
    page.wait_for_selector("#mb-step-1", state="visible")
    go_step(page, 2)
    page.errors = errors
    return page


@pytest.mark.e2e
def test_C1_C2_C4_designer_is_off_by_default_and_the_switch_is_browser_local(world, e2e_browser):
    _custom_draft(world["client"], world["tok"], _body())
    before_rows = _db("SELECT COUNT(*) AS n FROM audit_log WHERE action LIKE 'definitions.%'")[0]["n"]
    page = _builder(world, e2e_browser, "")                                           # C1：無參數、localStorage 空
    page.wait_for_selector("#mb-canvas", state="visible", timeout=20000)
    assert page.locator(".fd").count() == 0 or not page.locator(".fd").first.is_visible()
    assert not page.locator("#mb-fd-host").is_visible()
    assert page.evaluate("() => localStorage.getItem('mb_designer')") in (None, "0", "")
    page.close()
    page = _builder(world, e2e_browser, "&designer=1")                                # C2：?designer=1 ⇒ 設計器
    page.wait_for_selector(".fd .fd-paper", state="visible", timeout=20000)
    assert page.evaluate("() => localStorage.getItem('mb_designer')") in (None, "0", ""), "網址參數本身不寫 localStorage（只有按鈕會）"
    page.click("#mb-fd-toggle")                                                        # 按鈕關 ⇒ '0'；再按開 ⇒ '1'（每使用者每瀏覽器）
    page.wait_for_selector("#mb-canvas", state="visible")
    assert page.evaluate("() => localStorage.getItem('mb_designer')") == "0"
    page.click("#mb-fd-toggle")
    page.wait_for_selector(".fd .fd-paper", state="visible", timeout=20000)
    stored = page.evaluate("() => localStorage.getItem('mb_designer')")
    page.close()
    page = _builder(world, e2e_browser, "&designer=0", "localStorage.setItem('mb_designer','1')")   # C2：?designer=0 即使 localStorage=1 也關
    page.wait_for_selector("#mb-canvas", state="visible", timeout=20000)
    assert page.locator(".fd .fd-paper").count() == 0 or not page.locator(".fd .fd-paper").first.is_visible()
    after_rows = _db("SELECT COUNT(*) AS n FROM audit_log WHERE action LIKE 'definitions.%'")[0]["n"]
    assert after_rows == before_rows, "開關／開關頁面不可以產生任何定義存檔稽核（C4：只存 localStorage）"
    assert stored in ("1", "true"), "C4：?designer=1 後 localStorage 應記住（每瀏覽器）：%r" % stored


@pytest.mark.e2e
def test_B3_opening_and_switching_do_not_create_a_save(world, e2e_browser):
    _custom_draft(world["client"], world["tok"], _body())
    before = _db("SELECT COUNT(*) AS n FROM audit_log WHERE action='definitions.save_draft'")[0]["n"]
    snap = _db("SELECT rowid, body_json FROM ui_definitions WHERE kind='custom_module' AND key=? AND status='draft'", (KEY,))
    page = _builder(world, e2e_browser, "&designer=1")
    page.wait_for_selector(".fd .fd-paper", state="visible", timeout=20000)
    for _ in range(2):
        page.click("#mb-fd-toggle")
        page.wait_for_timeout(500)
        page.click("#mb-fd-toggle")
        page.wait_for_timeout(500)
    page.wait_for_timeout(1500)
    after = _db("SELECT COUNT(*) AS n FROM audit_log WHERE action='definitions.save_draft'")[0]["n"]
    snap2 = _db("SELECT rowid, body_json FROM ui_definitions WHERE kind='custom_module' AND key=? AND status='draft'", (KEY,))
    assert after == before and snap == snap2, (before, after)


@pytest.mark.e2e
def test_E1_E4_hostile_strings_render_as_text_only(world, e2e_browser):
    texts = [XSS[0], XSS[1], XSS[2]]
    _custom_draft(world["client"], world["tok"], _body(texts))
    page = _builder(world, e2e_browser, "&designer=1")
    page.wait_for_selector(".fd .fd-paper", state="visible", timeout=20000)
    for key in ("place", "amount", "kind"):                                           # 每個欄位都點開：右欄、選項清單、用語檢查表都渲染
        page.click('.fd-center .fd-fld[data-key="%s"]' % key)
        page.wait_for_timeout(300)
    page.wait_for_timeout(500)
    assert page.evaluate("() => typeof window.__x") == "undefined", "注入的腳本被執行了"
    assert page.evaluate("() => document.querySelectorAll('.fd img[src=x], .fd script, .fd [onerror], .fd [onmouseover]').length") == 0
    assert page.evaluate("() => document.querySelectorAll('.fd a[href^=\"javascript\"]').length") == 0       # E4：協定字串不成連結
    txt = page.inner_text(".fd")
    assert "window.__x=1" in txt, "惡意字串應以文字顯示（轉義），畫面上找不到它"
    assert not page.errors, page.errors


@pytest.mark.e2e
def test_E2_registry_strings_with_html_render_as_text(world, e2e_browser):
    _custom_draft(world["client"], world["tok"], _body())
    ctx = e2e_browser.new_context(viewport={"width": 1600, "height": 1000})
    page = ctx.new_page()
    evil = [{"token": "evil.<img src=x onerror=window.__x=5>", "label": "<img src=x onerror=window.__x=6>標籤", "why": "<script>window.__x=7</script>為什麼",
             "example": "\"><b onmouseover=window.__x=8>例</b>", "applies_to": [["text"]], "lockable": True, "needs_context": False, "requires_time": False}]
    ctx.route("**/api/platform/prefill-sources", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(evil)))
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, world["base"], world["user"][0], world["user"][1])
    page.goto("%s/pages/module-builder.html?key=%s&designer=1" % (world["base"], KEY))
    page.wait_for_selector("#mb-step-1", state="visible")
    go_step(page, 2)
    page.wait_for_selector(".fd .fd-paper", state="visible", timeout=20000)
    page.click('.fd-center .fd-fld[data-key="place"]')
    page.wait_for_timeout(800)
    assert page.evaluate("() => typeof window.__x") == "undefined"
    assert page.evaluate("() => document.querySelectorAll('.fd img[src=x], .fd script, .fd [onerror], .fd [onmouseover]').length") == 0
    assert "標籤" in page.inner_text(".fd-right"), "註冊表的 label 應出現在下拉（以文字）"
    assert not errors, errors


@pytest.mark.e2e
def test_E3_pasting_ten_thousand_lines_into_options_does_not_hang(world, e2e_browser):
    import time
    _custom_draft(world["client"], world["tok"], _body())
    page = _builder(world, e2e_browser, "&designer=1")
    page.wait_for_selector(".fd .fd-paper", state="visible", timeout=20000)
    page.click('.fd-center .fd-fld[data-key="place"]')
    page.select_option('.fd-right [data-fd="conv"]', "radio")
    page.wait_for_selector('.fd-right [data-item="opt:1"]')
    t0 = time.time()
    page.evaluate("""() => { const i = document.querySelector('.fd-right [data-item="opt:1"]'); i.focus();
        const dt = new DataTransfer(); dt.setData('text', Array.from({length: 10000}, (_, k) => '選項' + k).join(String.fromCharCode(10)));
        i.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true })) }""")
    page.wait_for_function("() => document.querySelectorAll('.fd-right [data-items=\"opt\"] li').length >= 5000", timeout=60000)
    secs = time.time() - t0
    print("E3 一萬行貼上耗時 %.1f 秒；格數 %d" % (secs, page.locator('.fd-right [data-items="opt"] li').count()))
    assert secs < 30, "一萬行貼上超過 30 秒（觀察項：是否需要上限）"
    assert page.evaluate("() => 1 + 1") == 2                                           # 頁面仍可回應


@pytest.mark.e2e
@pytest.mark.parametrize("page_name", ["module-builder.html", "expense-types.html"])
def test_A1_non_superadmin_cannot_load_the_designer(live_server, make_user, e2e_browser, page_name):
    u = make_user(username="aud_a1_" + page_name.split(".")[0].replace("-", "_"), role="admin", modules=[])
    ctx = e2e_browser.new_context(viewport={"width": 1400, "height": 900})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, u[0], u[1])
    page.goto("%s/pages/%s?designer=1" % (live_server, page_name))
    page.wait_for_timeout(3000)
    assert page.locator(".fd .fd-paper").count() == 0, "非最高管理者載入了設計器"
    # 與關閉參數時的結果相同（頁面本來就僅 superadmin）：兩種網址最後停在同一個地方、都沒有設計器
    page.goto("%s/pages/%s" % (live_server, page_name))
    page.wait_for_timeout(2000)
    assert page.locator(".fd .fd-paper").count() == 0
    # 反向控制：superadmin 同一網址 ?designer=1 看得到頁面主體
    sa = make_user(username="aud_a1sa_" + page_name.split(".")[0].replace("-", "_"), role="superadmin", modules=[])
    page2 = e2e_browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
    inject_login(page2, live_server, sa[0], sa[1])
    page2.goto("%s/pages/%s?designer=1" % (live_server, page_name))
    page2.wait_for_selector("#mb-key, [data-testid=et-new]", timeout=20000)
