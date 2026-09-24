"""篩選／搜尋／檢視切換欄改值後不可以觸發「尚未儲存」離頁警告（W-8，2026-09-24 開發機實走發現）。

sidebar.js 的 _maybeSetDirty 只略過 type=search／range 或 class 含 search／filter 的欄位；
這些頁的篩選欄沒有 ⇒ 一改就 motrixIsDirty=true，接著點任何連結都跳「確定要離開嗎？」。
觀測點：window.motrixIsDirty。反向控制：同頁一個會存檔的欄位改值後仍要設 dirty
（避免整頁都標成 filter 而變綠）。
"""
import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

from tests.test_e2e_case_mark_all_read_2026_09_24 import live_server  # noqa: F401  (live_server 是 fixture)

# 頁面 → (篩選欄 x-model 名稱, 反向控制：會存檔的欄位 x-model 名稱)
PAGES = {
    "access-guide":      (["globalSearch", "productSearch[c.code]", "compareShowUniform"], "modal.name"),
    "automation-guide":  (["globalSearch", "productSearch[c.code]", "compareShowUniform"], "modal.name"),
    "gateway-guide":     (["globalSearch", "productSearch[c.code]", "compareShowUniform"], "modal.name"),
    "monitor-guide":     (["globalSearch", "productSearch[c.code]", "compareShowUniform"], "modal.name"),
    "switch-guide":      (["globalSearch", "productSearch[c.code]", "compareShowUniform"], "modal.name"),
    "netarch-guide":     (["globalSearch"], "modal.name"),
    "dev-crm":           (["filterPerson", "sortPref.sortMode", "filterYear", "filterMonth"], "caseForm.case_name"),
    "tender-radar":      (["watchFilter"], "scanHoursText"),
    "case-stage-board":  (["departmentId", "salesFilter", "searchQ"], None),
    "customer-log?id={cid}": (["sortDir"], None),
    "supplier-log?id={sid}": (["sortDir"], None),
    "work-log":          (["viewDate"], None),
    "network-plans":     (["caseSearch"], "createForm.siteName"),
    "inventory":         (["intake.brandFilter"], "intake.invoiceNo"),
    "devices":           (["filterCustomer"], None),
    "online-stats":      (["start", "end", "trailUser", "showPaths"], None),
    "network-plan-form?id={pid}": (["stockSearch"], "plan.siteName"),
}

# 在 x-for 裡、要有資料才渲染的欄位：不在畫面上時略過（靜態守門另外看原始碼）
OPTIONAL = {"productSearch[c.code]"}

FIRE = """([name, mark]) => {
  const els = [...document.querySelectorAll('input,select,textarea')].filter(e =>
    [...e.attributes].some(a => a.name.startsWith('x-model') && a.value === name))
  if (!els.length) return 'missing'
  const e = els[0]
  window.motrixIsDirty = false
  if (e.type === 'checkbox') e.checked = !e.checked
  else if (e.tagName === 'SELECT') { if (e.options.length > 1) e.selectedIndex = (e.selectedIndex + 1) % e.options.length }
  else if (e.type === 'date') e.value = '2026-01-02'
  else e.value = (e.value || '') + 'x'
  e.dispatchEvent(new Event('input', { bubbles: true }))
  e.dispatchEvent(new Event('change', { bubbles: true }))
  return !!window.motrixIsDirty
}"""


def _seed_parties():
    import db
    conn = db.get_db()
    try:
        cid = conn.execute("INSERT INTO customers (name, data_json, created_at) VALUES (?,?,?)",
                           ("W8 客戶", "{}", "2026-01-01T00:00:00")).lastrowid
        sid = conn.execute("INSERT INTO suppliers (name, data_json, created_at) VALUES (?,?,?)",
                           ("W8 供應商", "{}", "2026-01-01T00:00:00")).lastrowid
        conn.commit()
    finally:
        conn.close()
    return {"cid": cid, "sid": sid}


@pytest.mark.e2e
@pytest.mark.parametrize("page_name", sorted(PAGES))
def test_filter_fields_do_not_mark_the_page_dirty(live_server, make_user, monkeypatch, page_name):
    from helpers import geo
    monkeypatch.setattr(geo, "tiles_blocked", lambda *a, **k: None)   # 標案雷達的地圖會觸發後端探測圖磚（連外）
    u = make_user(username="w8_" + page_name.split("?")[0].replace("-", "_")[:20], role="superadmin")
    filters, saved = PAGES[page_name]
    ids = _seed_parties()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            ctx = browser.new_context()
            ctx.route("**/tile.openstreetmap.org/**", lambda r: r.abort())   # 地圖圖磚不連外
            page = ctx.new_page()
            page.goto(f"{live_server}/pages/login.html")
            page.fill('input[x-model="username"]', u[0])
            page.fill('input[x-model="password"]', u[1])
            page.click('button:has-text("登入")')
            page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=15000)
            if "{pid}" in page_name:
                ids["pid"] = page.evaluate("""async () => {
                  const t = JSON.parse(localStorage.getItem('motrix_session')).token
                  const r = await fetch('/api/network-plans', { method: 'POST',
                    headers: { Authorization: 'Bearer ' + t, 'Content-Type': 'application/json' },
                    body: JSON.stringify({ siteName: 'W8 規劃' }) })
                  return (await r.json()).id }""")
            page.goto(f"{live_server}/pages/" + page_name.replace("?", ".html?", 1).format(**ids) + ("" if "?" in page_name else ".html"))
            page.wait_for_function("() => window.Alpine && document.querySelector('[x-data]')", timeout=15000)
            page.wait_for_timeout(1500)
            dirty = {name: page.evaluate(FIRE, [name, None]) for name in filters}
            missing = [k for k, v in dirty.items() if v == "missing" and k not in OPTIONAL]
            assert not missing, ("篩選欄不在畫面上（前提不成立）", dirty)
            dirty = {k: v for k, v in dirty.items() if v != "missing"}
            assert dirty, "沒有任何篩選欄被實測到"
            assert not any(dirty.values()), ("改篩選欄就被當成未存修改（會跳離頁警告）", dirty)
            if saved:
                assert page.evaluate(FIRE, [saved, None]) is True, "反向控制：會存檔的欄位改值後應該設 dirty"
        finally:
            browser.close()
