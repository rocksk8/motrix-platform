"""兩個提醒橫幅（兩步驟驗證、待簽核）不可以蓋住頁面的操作區（2026-09-25）。

原本固定在右上角（top:72px、z-index:99999），分頁的第一頁若不是 index（例如新分頁直接開案件頁的連結），
就蓋住標頭的「儲存／更多」。改放右下角、與 MotrixUI toast 同一欄（notif.js::_noticeStack）。
這裡刻意只注入 session、**不**寫「已經過 index」的分頁旗標：要讓橫幅在目標頁上真的跳出來。
觀測點：橫幅出現之後，按鈕中心的 elementFromPoint 必須是按鈕本身；橫幅每個分頁只出現一次、關掉後同分頁不再出現。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
from datetime import datetime

import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_e2e_case_concurrent_edit_2026_09_24 import DATA_JS, NO, _seed  # noqa: E402

#: O5-S1：本檔量版面／字級（getBoundingClientRect 等）⇒ 要真字型，不吃 conftest 的字型替身
pytestmark = pytest.mark.real_fonts
pytestmark = [*(pytestmark if isinstance(pytestmark, list) else [pytestmark]), requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')]

HIT_JS = """(sel) => {
  const b = document.querySelector(sel)
  if (!b) return 'missing'
  const r = b.getBoundingClientRect()
  const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)
  if (hit && (hit === b || b.contains(hit))) return 'button'
  const banner = hit && hit.closest('#totp-reminder-banner, #approval-notif-banner')
  return banner ? 'covered by #' + banner.id : (hit ? hit.tagName + '#' + hit.id : 'none')
}"""
BANNERS = ("#totp-reminder-banner", "#approval-notif-banner")
# 畫面內所有可見的操作元件：中心點被橫幅（.mui-toasts 那一欄）蓋住的列出來
COVERED_JS = """() => {
  const out = []
  for (const e of document.querySelectorAll('button, a[href], input, select, textarea, [role=button], .cm-tab')) {
    if (e.closest('.mui-toasts')) continue
    const r = e.getBoundingClientRect()
    if (r.width < 2 || r.height < 2 || r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)
    if (hit && hit.closest('.mui-toasts')) out.push(e.outerHTML.slice(0, 80))
  }
  return out }"""


def _session_only(client, context, user):
    """只注入 session（新分頁直接開某一頁的狀態）；不寫「已經過 index」的分頁旗標。"""
    keys = ("token", "userId", "username", "displayName", "role", "modules", "loginAt")   # 同 login.html
    d = client.post("/api/auth/login", json={"username": user[0], "password": user[1]}).json()
    sess = {k: d.get(k) for k in keys}
    context.add_init_script("try { localStorage.setItem('motrix_session', %s) } catch (e) {}" % json.dumps(json.dumps(sess)))


def _pending_approval(username):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO notifications (username, type, ref_id, ref_label, message, is_read, created_at)"
                     " VALUES (?,?,?,?,?,0,?)",
                     (username, "approval_request", NO, NO, "待簽核", datetime.now().isoformat()))
        conn.commit()
    finally:
        conn.close()


@pytest.mark.e2e
@pytest.mark.parametrize("width", [1440, 1024])
def test_banners_do_not_cover_the_case_header_buttons(live_server, client, make_user, new_context, width):
    u = make_user(username=f"nb_{width}", role="admin")          # admin 未啟用 TOTP ⇒ 兩步驟驗證提醒
    _seed()
    _pending_approval(u[0])                                       # ⇒ 待簽核通知
    ctx = new_context(viewport={"width": width, "height": 900})
    _session_only(client, ctx, u)
    page = ctx.new_page()
    page.goto(f"{live_server}/pages/case-management.html?q={NO}")
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'", timeout=20000)
    for b in BANNERS:                                            # 前提：兩個橫幅都真的出現在這一頁
        page.locator(b).wait_for(state="visible", timeout=10000)
    for sel in (".cm-header .btn-save", '[data-testid="cm-more"]'):
        assert page.evaluate(HIT_JS, sel) == "button", (width, sel, page.evaluate(HIT_JS, sel))
    assert page.evaluate(COVERED_JS) == [], ("案件頁有操作元件被提醒橫幅蓋住", width, page.evaluate(COVERED_JS))
    # 兩個橫幅彼此不疊
    r1, r2 = (page.locator(b).bounding_box() for b in BANNERS)
    assert r1["y"] + r1["height"] <= r2["y"] or r2["y"] + r2["height"] <= r1["y"], (r1, r2)


@pytest.mark.e2e
@pytest.mark.parametrize("banner", BANNERS)
def test_each_banner_shows_once_and_stays_closed_in_the_same_tab(live_server, client, make_user, new_context, banner):
    u = make_user(username="nb_once" + ("t" if "totp" in banner else "a"), role="admin")
    _seed()
    _pending_approval(u[0])
    ctx = new_context(viewport={"width": 1440, "height": 900})
    _session_only(client, ctx, u)
    page = ctx.new_page()
    page.goto(f"{live_server}/pages/case-management.html?q={NO}")
    page.locator(banner).wait_for(state="visible", timeout=10000)
    assert page.locator(banner).count() == 1
    page.locator(f"{banner} button").click()                       # ×
    page.locator(banner).wait_for(state="detached", timeout=5000)
    page.goto(f"{live_server}/pages/quotations.html")               # 同分頁換頁
    page.wait_for_function("() => window.Alpine && document.querySelector('[x-data]')", timeout=15000)
    page.wait_for_timeout(2500)                                     # 橫幅延遲 0.9／1.4 秒才出現：等過它
    assert page.locator(banner).count() == 0, "關掉之後同一分頁不應再出現"
