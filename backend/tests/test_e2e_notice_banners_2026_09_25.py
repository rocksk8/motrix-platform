"""兩個提醒（兩步驟驗證、待簽核）不可以浮在頁面上蓋住操作區。

2026-09-25：原本是浮動卡片（固定右上角 → 改右下角），仍可能蓋住內容。
2026-11-11（UX 提案 D1）：浮動卡片整個拿掉，提醒改放**鈴鐺下拉最上方**（`[data-testid=bell-reminder]`）＋鈴鐺上一顆小點：
  不浮在內容上、不會把頁面往下推、看漏了也還在（同分頁換頁仍在，按 × 才收掉並記在 sessionStorage）。
這裡刻意只注入 session、**不**寫「已經過 index」的分頁旗標（那組旗標＝已處理／已關閉）：要讓提醒在目標頁上真的出現。
觀測點：頁面上沒有任何 #approval-notif-banner／#totp-reminder-banner／.mui-toasts 浮層；鈴鐺裡有提醒；
        頁面所有可見操作元件都沒有被任何浮層蓋住；按 × 之後同分頁不再出現。
"""
from tests._e2e_login import bootstrap_unavailable  # noqa: E402
from tests._requires import requires_module  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
#: 只標真的需要 M01 的題；其餘的題在 M01 不在時照常要過（稽核 D M5-M1，清單＝M01 真刪時實際紅的題）
needs_m01 = requires_module("case", '本題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')
import json
from datetime import datetime

import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_e2e_case_concurrent_edit_2026_09_24 import DATA_JS, NO, _seed  # noqa: E402

#: O5-S1：本檔量版面／字級（getBoundingClientRect 等）⇒ 要真字型，不吃 conftest 的字型替身
pytestmark = pytest.mark.real_fonts

HIT_JS = """(sel) => {
  const b = document.querySelector(sel)
  if (!b) return 'missing'
  const r = b.getBoundingClientRect()
  const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)
  if (hit && (hit === b || b.contains(hit))) return 'button'
  return hit ? hit.tagName + '#' + hit.id : 'none'
}"""
#: 舊的浮動卡片（已移除）：頁面上不可以再出現
OLD_FLOATING = ("#totp-reminder-banner", "#approval-notif-banner")
BELL_BTN = ".topbar__btn:has-text('通知')"
REMINDERS = ("approval", "totp")
# 畫面內所有可見的操作元件：中心點被任何 fixed 浮層（頂欄／導覽列自己除外）蓋住的列出來
COVERED_JS = """() => {
  const out = []
  for (const e of document.querySelectorAll('button, a[href], input, select, textarea, [role=button], .cm-tab')) {
    const r = e.getBoundingClientRect()
    if (r.width < 2 || r.height < 2 || r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)
    if (!hit || hit === e || e.contains(hit) || hit.contains(e)) continue
    const fixed = (n) => { for (; n && n !== document.body; n = n.parentElement) { if (getComputedStyle(n).position === 'fixed') return n } return null }
    const f = fixed(hit)
    if (f && !f.closest('#app-topbar, .topbar, .mnav')) out.push(e.outerHTML.slice(0, 80))
  }
  return out }"""


def _session_only(client, context, user):
    """只注入 session（新分頁直接開某一頁的狀態）；不寫「已經過 index」的分頁旗標。"""
    keys = ("token", "userId", "username", "displayName", "role", "modules", "loginAt")   # 同 login.html
    d = client.post("/api/auth/login", json={"username": user[0], "password": user[1]}).json()
    sess = {k: d.get(k) for k in keys}
    context.add_init_script("try { localStorage.setItem('motrix_session', %s) } catch (e) {}" % json.dumps(json.dumps(sess)))


def _pending_approval(username):
    """一張真的輪到 username 簽的報價單（橫幅數字取自 /api/approval-queue/count；2026-10-01 起不再數未讀通知列）＋通知列。"""
    import db
    conn = db.get_db()
    try:
        appr = {"requestedBy": "nb_requester", "requestedByDisplay": "申請人", "requestedAt": "2026-10-01T01:00:00",
                "currentTier": 0, "tiers": [{"approvers": [{"username": username, "displayName": username, "status": "pending"}]}]}
        conn.execute("INSERT OR REPLACE INTO quotations (quote_no, status, customer_name, project_name, total, data_json, created_at, updated_at)"
                     " VALUES (?,?,?,?,?,?,?,?)",
                     ("MQ-NB-PEND-" + username, "待審核", "客戶", "專案", 1000, json.dumps({"approval": appr}, ensure_ascii=False),
                      "2026-10-01", "2026-10-01"))
        conn.execute("INSERT INTO notifications (username, type, ref_id, ref_label, message, is_read, created_at)"
                     " VALUES (?,?,?,?,?,0,?)",
                     (username, "approval_request", NO, NO, "待簽核", datetime.now().isoformat()))
        conn.commit()
    finally:
        conn.close()


@needs_m01
@pytest.mark.e2e
@pytest.mark.parametrize("width", [1440, 1024])
def test_reminders_live_in_the_bell_and_cover_nothing(live_server, client, make_user, new_context, width):
    u = make_user(username=f"nb_{width}", role="admin")          # admin 未啟用 TOTP ⇒ 兩步驟驗證提醒
    _seed()
    _pending_approval(u[0])                                       # ⇒ 待簽核
    ctx = new_context(viewport={"width": width, "height": 1000})
    _session_only(client, ctx, u)
    page = ctx.new_page()
    page.goto(f"{live_server}/pages/case-management.html?q={NO}")
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'", timeout=20000)
    page.locator(BELL_BTN).wait_for(state="visible", timeout=10000)
    page.wait_for_function("() => document.querySelectorAll('[data-testid=bell-reminder]').length === 2", timeout=15000)   # 兩則都在（下拉收著時也在 DOM）
    page.wait_for_timeout(2500)                                   # 舊橫幅 0.9／1.4 秒才跳：等過它
    for b in OLD_FLOATING:
        assert page.locator(b).count() == 0, ("浮動橫幅應已移除", b)
    assert page.locator(".mui-toasts > *").count() == 0
    for sel in (".cm-header .btn-save", '[data-testid="cm-more"]'):
        assert page.evaluate(HIT_JS, sel) == "button", (width, sel, page.evaluate(HIT_JS, sel))
    assert page.evaluate(COVERED_JS) == [], ("案件頁有操作元件被浮層蓋住", width, page.evaluate(COVERED_JS))
    page.locator(BELL_BTN).click()                                # 打開鈴鐺：兩則提醒釘在最上方
    ids = page.eval_on_selector_all("[data-testid=bell-reminder]", "els => els.map(e => e.dataset.reminderId)")
    assert sorted(ids) == sorted(REMINDERS), ids
    page.locator("[data-reminder-id=approval]").wait_for(state="visible", timeout=5000)
    assert "待您簽核" in page.locator("[data-reminder-id=approval]").inner_text()


@pytest.mark.e2e
@pytest.mark.parametrize("rid", REMINDERS)
def test_reminder_stays_across_pages_until_dismissed_then_stays_closed(live_server, client, make_user, new_context, rid):
    u = make_user(username="nb_once" + rid[0], role="admin")
    _seed()
    _pending_approval(u[0])
    ctx = new_context(viewport={"width": 1440, "height": 900})
    _session_only(client, ctx, u)
    page = ctx.new_page()
    sel = f"[data-reminder-id={rid}]"
    page.goto(f"{live_server}/pages/case-management.html?q={NO}")
    page.wait_for_function(f"() => document.querySelectorAll('{sel}').length === 1", timeout=15000)
    page.goto(f"{live_server}/pages/quotations.html")               # 換頁：還在（提醒不是一次性 7 秒就消失）
    page.wait_for_function(f"() => document.querySelectorAll('{sel}').length === 1", timeout=15000)
    page.locator(BELL_BTN).click()
    page.locator(f"{sel} [data-testid=bell-reminder-close]").click()  # ×
    page.wait_for_function(f"() => document.querySelectorAll('{sel}').length === 0", timeout=5000)
    page.goto(f"{live_server}/pages/case-management.html?q={NO}")   # 再換頁
    page.wait_for_function("() => window.Alpine && document.querySelector('[x-data]')", timeout=15000)
    page.wait_for_timeout(2500)
    assert page.locator(sel).count() == 0, "關掉之後同一分頁不應再出現"


@pytest.mark.e2e
@pytest.mark.parametrize("via_bootstrap", [False, True], ids=["direct", "bootstrap"])
def test_totp_status_is_asked_once_per_tab_not_once_per_page(live_server, client, make_user, new_context, via_bootstrap):
    """提醒改成每頁都在（按 × 才收）之後，「有沒有啟用兩步驟驗證」仍只能每個分頁查一次：
    否則每換一頁多打一支 /api/auth/totp/status（case-page golden 的 API 請求清單就是釘這個）。
    2026-11-13（bootstrap）：第一次由 /api/bootstrap 供應（原端點 0 次）；bootstrap 不可用時退回原端點（1 次）。兩條路都要是「每分頁只問一次」：
    direct＝bootstrap 關掉，原端點恰 1 次；bootstrap＝原端點 0 次（第一頁由 bootstrap 供應，之後兩頁沿用分頁快取、不再補打）。"""
    u = make_user(username="nb_totpq%s" % ("b" if via_bootstrap else "d"), role="admin")
    ctx = new_context(viewport={"width": 1440, "height": 900})
    _session_only(client, ctx, u)
    if not via_bootstrap:
        bootstrap_unavailable(ctx)
    page = ctx.new_page()
    hits = []
    page.on("request", lambda r: hits.append(r.url) if r.url.endswith("/api/auth/totp/status") else None)
    sel = "[data-reminder-id=totp]"
    for path in ("/pages/quotations.html", "/pages/customers.html", "/pages/quotations.html"):
        page.goto(live_server + path)
        page.wait_for_function(f"() => document.querySelectorAll('{sel}').length === 1", timeout=15000)
    want = 0 if via_bootstrap else 1
    assert len(hits) == want, "三頁共查了 %d 次 totp/status（預期 %d；via_bootstrap=%s）：%s" % (len(hits), want, via_bootstrap, hits)
