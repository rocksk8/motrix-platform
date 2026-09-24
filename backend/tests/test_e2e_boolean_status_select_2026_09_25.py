"""「狀態」下拉（啟用／停用）必須真的存得進 false，停用的資料打開也要顯示停用。

☠️ 2026-09-25（hichan-8d，季下拉同型掃描時找到）：
`<select x-model="form.active"><option :value="true">往來中</option><option :value="false">停用</option>`
—— Alpine 把 `:value="false"` 當成「移除 value 屬性」⇒ 那個選項的值退回**選項文字**。
- 選「停用」⇒ 模型變成字串 "停用"（truthy）
  - suppliers：原樣存進 data_json，列表用 `s.active !== false` 判斷 ⇒ 存檔成功，仍顯示「往來中」
  - tender-radar：後端 `1 if body.get("enabled", True) else 0` ⇒ 監看條件仍啟用，每日比對照跑
- 已停用（false）的資料打開編輯 ⇒ 下拉顯示第一個選項（往來中／啟用）

兩個方向都驗，而且讀的是**存下去之後**的值（不是模型）。
"""
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_e2e_reports_period_sync_2026_09_10 import _login  # noqa: E402,F401
sys.path.insert(0, str(Path(__file__).resolve().parent))   # 單獨跑這個檔時 tests/ 不在 sys.path
from _mapiso import no_tile_probe  # noqa: E402,F401  （tender-radar 會載地圖 ⇒ 後端探測底圖伺服器）

ROOT = "Alpine.$data(document.querySelector('[x-data]'))"
RADAR = "Alpine.$data(document.querySelector('.tr-wrap'))"   # 標案雷達的 x-data 不在 body 上
_SELECT = "[...document.querySelectorAll('select')].find(e => e.getAttribute('%s') === '%s')"


def _db():
    import db
    return db.get_db()


def _shown(page, attr, expr):
    """下拉目前**顯示**的選項文字。"""
    return page.evaluate("() => { const s = %s; return s.options[s.selectedIndex].text.trim() }" % (_SELECT % (attr, expr)))


def _pick(page, attr, expr, label_prefix):
    page.evaluate("""([sel, pre]) => { const s = eval(sel)
      const i = [...s.options].findIndex(o => o.text.trim().startsWith(pre))
      s.selectedIndex = i; s.dispatchEvent(new Event('change', { bubbles: true })) }""",
                  [_SELECT % (attr, expr), label_prefix])


# ── suppliers ────────────────────────────────────────────────────────────────

def _supplier(name, active):
    conn = _db()
    cur = conn.execute("INSERT INTO suppliers (name, tax_id, phone, data_json, created_at, updated_at) "
                       "VALUES (?, '', '', ?, '2026-09-25T00:00:00', '2026-09-25T00:00:00')",
                       (name, json.dumps({"active": active, "tags": []}, ensure_ascii=False)))
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid


def _supplier_active(sid):
    conn = _db()
    row = conn.execute("SELECT data_json FROM suppliers WHERE id=?", (sid,)).fetchone()
    conn.close()
    return json.loads(row[0]).get("active")


def _open_suppliers(page, base):
    page.goto(f"{base}/pages/suppliers.html")
    page.wait_for_function(f"() => window.Alpine && {ROOT} && ({ROOT}.suppliers || []).length > 0", timeout=20000)


@pytest.mark.e2e
def test_supplier_set_to_inactive_is_saved_as_false(live_server, make_user, e2e_browser):
    u = make_user(username="bs_sup", role="superadmin")
    sid = _supplier("布林供應商甲", True)
    browser = e2e_browser
    page = browser.new_context().new_page()
    _login(page, live_server, *u)
    _open_suppliers(page, live_server)
    page.evaluate(f"() => {{ const d = {ROOT}; d.openEdit(d.suppliers.find(s => s.id === {sid})) }}")
    page.wait_for_timeout(300)
    _pick(page, "x-model.boolean", "form.active", "停用") if page.evaluate(
        "() => !!%s" % (_SELECT % ("x-model.boolean", "form.active"))) else _pick(page, "x-model", "form.active", "停用")
    with page.expect_response(lambda r: f"/api/suppliers/{sid}" in r.url and r.request.method == "PUT") as resp:
        page.evaluate(f"() => {ROOT}.saveSupplier()")
    assert resp.value.status == 200, resp.value.text()
    assert _supplier_active(sid) is False, "選「停用」存檔後，存下去的是 %r" % (_supplier_active(sid),)


@pytest.mark.e2e
def test_inactive_supplier_opens_showing_inactive(live_server, make_user, e2e_browser):
    u = make_user(username="bs_sup2", role="superadmin")
    sid = _supplier("布林供應商乙", False)
    browser = e2e_browser
    page = browser.new_context().new_page()
    _login(page, live_server, *u)
    _open_suppliers(page, live_server)
    page.evaluate(f"() => {{ const d = {ROOT}; d.openEdit(d.suppliers.find(s => s.id === {sid})) }}")
    page.wait_for_timeout(300)
    attr = "x-model.boolean" if page.evaluate("() => !!%s" % (_SELECT % ("x-model.boolean", "form.active"))) else "x-model"
    assert _shown(page, attr, "form.active") == "停用"


# ── tender-radar ─────────────────────────────────────────────────────────────

def _watch(name, enabled):
    conn = _db()
    cur = conn.execute("INSERT INTO tender_watches (name, keywords, excludes, org, budget_min, budget_max, enabled, "
                       "created_at, updated_at) VALUES (?, ?, '[]', '', NULL, NULL, ?, "
                       "'2026-09-25T00:00:00', '2026-09-25T00:00:00')",
                       (name, json.dumps(["監視器"], ensure_ascii=False), 1 if enabled else 0))
    conn.commit()
    wid = cur.lastrowid
    conn.close()
    return wid


def _watch_enabled(wid):
    conn = _db()
    v = conn.execute("SELECT enabled FROM tender_watches WHERE id=?", (wid,)).fetchone()[0]
    conn.close()
    return v


def _open_radar(page, base):
    page.goto(f"{base}/pages/tender-radar.html")
    page.wait_for_function(f"() => window.Alpine && {RADAR} && ({RADAR}.watches || []).length > 0", timeout=20000)


def _attr(page):
    return "x-model.boolean" if page.evaluate("() => !!%s" % (_SELECT % ("x-model.boolean", "form.enabled"))) else "x-model"


@pytest.mark.e2e
def test_tender_watch_set_to_disabled_is_saved_disabled(live_server, make_user, no_tile_probe, e2e_browser):
    u = make_user(username="bs_tr", role="superadmin", modules=["dashboard", "tender_radar"])
    wid = _watch("布林監看甲", True)
    browser = e2e_browser
    page = browser.new_context().new_page()
    _login(page, live_server, *u)
    _open_radar(page, live_server)
    page.evaluate(f"() => {{ const d = {RADAR}; d.edit(d.watches.find(w => w.id === {wid})) }}")
    page.wait_for_timeout(300)
    _pick(page, _attr(page), "form.enabled", "停用")
    with page.expect_response(lambda r: f"/api/tender-radar/watches/{wid}" in r.url
                              and r.request.method == "PUT") as resp:
        page.evaluate(f"() => {RADAR}.save()")
    assert resp.value.status == 200, resp.value.text()   # 存檔被拒時 DB 不變，下面的斷言會誤指向下拉
    assert _watch_enabled(wid) == 0, "選「停用」存檔後，監看條件仍是啟用（enabled=%r）" % (_watch_enabled(wid),)


@pytest.mark.e2e
def test_disabled_tender_watch_opens_showing_disabled(live_server, make_user, no_tile_probe, e2e_browser):
    u = make_user(username="bs_tr2", role="superadmin", modules=["dashboard", "tender_radar"])
    wid = _watch("布林監看乙", False)
    browser = e2e_browser
    page = browser.new_context().new_page()
    _login(page, live_server, *u)
    _open_radar(page, live_server)
    page.evaluate(f"() => {{ const d = {RADAR}; d.edit(d.watches.find(w => w.id === {wid})) }}")
    page.wait_for_timeout(300)
    assert _shown(page, _attr(page), "form.enabled").startswith("停用")

