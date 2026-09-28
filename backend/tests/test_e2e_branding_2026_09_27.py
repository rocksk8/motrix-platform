# -*- coding: utf-8 -*-
"""e2e：換品牌圖檔後，各頁 DOM 的 src／href 真的換了（2026-09-27 H10）。

觀測點是瀏覽器真的載入的圖（`naturalWidth`／`naturalHeight`，每一種上傳一張尺寸獨特的圖），
不是 Alpine 模型；恢復預設的終點是伺服器狀態（存放目錄沒有檔、端點回預設檔）加 DOM。
"""
import io
import os

import pytest
from PIL import Image

pytest.importorskip("playwright.sync_api")

ROOT = "Alpine.$data(document.querySelector('[x-data]'))"


def _png(w, h, color):
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def _hdr(client, u):
    r = client.post("/api/auth/login", json={"username": u[0], "password": u[1]})
    return {"Authorization": "Bearer " + r.json()["token"]}


def _put(client, hdr, kind, data):
    r = client.put("/api/settings/branding/" + kind, headers=hdr, files={"file": ("x.png", data, "image/png")})
    assert r.status_code == 200, r.text
    return r.json()["v"]


def _natural(page, selector):
    page.wait_for_function(
        "s => { const i = document.querySelector(s); return i && i.complete && i.naturalWidth > 0 }",
        arg=selector, timeout=20000)
    return page.evaluate("s => { const i = document.querySelector(s); return [i.naturalWidth, i.naturalHeight] }",
                         selector)


def _fetch_size(page, url):
    """在頁面裡用 <img> 載入某個網址 ⇒ 實際尺寸（驗 favicon 的 href 指到的是新圖）。"""
    return page.evaluate("""u => new Promise((ok, bad) => { const i = new Image();
        i.onload = () => ok([i.naturalWidth, i.naturalHeight]); i.onerror = () => bad('load failed'); i.src = u })""", url)


@pytest.mark.e2e
def test_login_topbar_and_favicon_show_the_uploaded_images(live_server, make_user, new_page, login_as, client):
    u = make_user(username="bre_sa", role="superadmin")
    hdr = _hdr(client, u)
    client.put("/api/settings/company-profile", headers=hdr, json={"name": "範例科技股份有限公司",
                                                                  "company_name_en": "Example Tech"})
    v_logo = _put(client, hdr, "logo", _png(321, 97, (200, 0, 0, 255)))
    _put(client, hdr, "logo-dark", _png(233, 61, (255, 255, 255, 255)))
    _put(client, hdr, "favicon", _png(40, 40, (0, 0, 200, 255)))

    # 登入頁（沒有 session）：LOGO 換成帶新版本的網址、載入的是上傳的那一張；副標是客戶的英文名
    page = new_page()
    page.goto(live_server + "/pages/login.html")
    page.wait_for_function("v => (document.querySelector('img[data-brand-logo=\"logo\"]').getAttribute('src') || '')"
                           ".endsWith('v=' + v)", arg=v_logo, timeout=20000)
    assert _natural(page, 'img[data-brand-logo="logo"]') == [321, 97]
    assert page.locator("[data-brand-name-en]").inner_text().strip() == "EXAMPLE TECH"
    assert "SYNERGY" not in page.content().upper()

    # 登入後首頁：上方列是深色底 LOGO、分頁圖示指到品牌端點且內容是新的（256×256）
    page2 = new_page()
    login_as(page2, u)
    page2.goto(live_server + "/index.html")
    assert _natural(page2, 'img[data-brand-logo="logo-dark"]') == [233, 61]
    href = page2.evaluate("() => document.querySelector('link[rel=\"icon\"]').href")
    assert href.endswith("/api/system/branding/favicon"), href
    assert _fetch_size(page2, href) == [256, 256]

    # 任取一個一般頁面：分頁圖示同樣指到品牌端點（不再是寫死的靜態檔）
    page2.goto(live_server + "/pages/customers.html")
    assert page2.evaluate("() => document.querySelector('link[rel=\"icon\"]').getAttribute('href')") == \
        "/api/system/branding/favicon"
    assert _natural(page2, 'img[data-brand-logo="logo-dark"]') == [233, 61]


@pytest.mark.e2e
def test_settings_page_upload_and_reset(live_server, make_user, new_page, login_as, client, tmp_path):
    import helpers.branding as b
    u = make_user(username="bre_set", role="superadmin")
    page = new_page()
    page.on("dialog", lambda d: d.accept())
    login_as(page, u)
    page.goto(live_server + "/pages/company-profile-settings.html")
    page.locator('[data-brand-slot="logo"]').wait_for(state="visible", timeout=20000)

    f = tmp_path / "new-logo.png"
    f.write_bytes(_png(177, 55, (0, 150, 0, 255)))
    page.set_input_files('input[data-brand-input="logo"]', str(f))
    # 終點：busy 解除，且預覽的 src 換成新版本、載入的是上傳的那一張
    page.wait_for_function(f"() => {ROOT}.brandBusy === ''", timeout=20000)
    page.wait_for_function("() => !(document.querySelector('img[data-brand-preview=\"logo\"]').getAttribute('src') || '')"
                           ".endsWith('v=default')", timeout=20000)
    assert _natural(page, 'img[data-brand-preview="logo"]') == [177, 55]
    stored = os.path.join(b.UPLOADS_ROOT, "branding", "logo.png")
    assert os.path.isfile(stored)
    assert Image.open(stored).size == (177, 55)

    # 恢復預設：伺服器端沒有檔、端點回預設；DOM 的預覽改回 v=default
    page.locator('button[data-brand-reset="logo"]').click()
    page.wait_for_function("() => (document.querySelector('img[data-brand-preview=\"logo\"]').getAttribute('src') || '')"
                           ".endsWith('v=default')", timeout=20000)
    assert not os.path.isfile(stored)
    assert client.get("/api/system/branding").json()["assets"]["logo"].endswith("v=default")

    # 拒收：SVG ⇒ 畫面顯示錯誤，伺服器端沒有檔
    svg = tmp_path / "evil.png"
    svg.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
    page.set_input_files('input[data-brand-input="logo"]', str(svg))
    page.wait_for_function(f"() => {ROOT}.brandBusy === ''", timeout=20000)
    # 上一步「已恢復預設」的訊息可能還在 ⇒ 等畫面上的訊息變成拒收的那一句（DOM，不看模型）
    page.wait_for_function("() => (document.querySelector('[data-brand-msg]').textContent || '').includes('SVG')",
                           timeout=20000)
    assert not os.path.isfile(stored)



#: 初次 GET /api/settings/branding 照常送出（取回的是上傳前的預設狀態），但扣住不交給頁面，直到題目呼叫
#: window.__releaseFirst()——不靠時間差（同 tests/platform/test_e2e_menu_layout 的 _HOLD_FIRST）。
#: 產品呼叫 json() 時設 window.__staleRead（＝產品已經在處理這一趟），題目再等兩個 macrotask 讓 then 鏈跑完。
_HOLD_FIRST_BRANDING = """
  (function () {
    var real = window.fetch, n = 0
    window.fetch = function (url, opt) {
      if (String(url) === '/api/settings/branding' && !(opt && opt.method) && ++n === 1) {
        var got = real.apply(this, arguments).then(function (r) {
          return r.json().then(function (body) { return { ok: r.ok, status: r.status, body: body } })
        })
        return new Promise(function (res) {
          window.__releaseFirst = function () {
            got.then(function (g) {
              res({ ok: g.ok, status: g.status, json: function () { window.__staleRead = true; return Promise.resolve(g.body) } })
            })
          }
        })
      }
      return real.apply(this, arguments)
    }
  })()
"""


def test_initial_load_arriving_after_upload_does_not_revert_the_preview(live_server, make_user, new_page, login_as, tmp_path):
    """產品競態（2026-09-28 A，test_settings_page_upload_and_reset 約 1/4 偶發紅）：卡片在初次 GET /api/settings/branding
    回來之前就畫好、可以上傳；上傳的回應先到、初次載入的舊回應後到 ⇒ 舊版會把預覽蓋回預設、「恢復預設」鈕消失。
    這裡把初次載入扣到上傳完成之後才交給頁面 ⇒ 決定性重現那個順序。"""
    u = make_user(username="bre_race", role="superadmin")
    page = new_page()
    page.add_init_script(_HOLD_FIRST_BRANDING)
    login_as(page, u)
    page.goto(live_server + "/pages/company-profile-settings.html")
    page.locator('[data-brand-slot="logo"]').wait_for(state="visible", timeout=20000)
    page.wait_for_function("() => typeof window.__releaseFirst === 'function'", timeout=20000)
    f = tmp_path / "race-logo.png"
    f.write_bytes(_png(133, 47, (0, 0, 200, 255)))
    page.set_input_files('input[data-brand-input="logo"]', str(f))
    page.wait_for_function("() => { const b = %s; return b.brandBusy === '' && !!(b.brand.logo && b.brand.logo.custom) }" % ROOT,
                           timeout=20000)
    page.evaluate("window.__releaseFirst()")
    page.wait_for_function("window.__staleRead === true", timeout=10000)
    page.evaluate("() => new Promise(r => setTimeout(() => setTimeout(r, 0), 0))")
    src = page.locator('img[data-brand-preview="logo"]').get_attribute("src") or ""
    assert not src.endswith("v=default"), "晚到的初次載入把預覽蓋回預設：%s" % src
    assert _natural(page, 'img[data-brand-preview="logo"]') == [133, 47]
    assert page.locator('button[data-brand-reset="logo"]').is_visible(), "晚到的初次載入讓「恢復預設」鈕消失"
