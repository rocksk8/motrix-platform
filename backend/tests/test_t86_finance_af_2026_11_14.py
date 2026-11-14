# -*- coding: utf-8 -*-
"""T86 財務細項（使用者裁示 2026-11-14）：只開 A，並做 F。

A  精算頁「已出貨數量」`GET /api/quotations/{no}/item-shipped`：模組檢查早就放行 financial_view，逐案卻用擁有者規則 ⇒ 財務 404。
   改用與案件頁本體相同的讀取規則（scope="read"）。B、C、D、E 沒開：派工／出貨單／完工單／動態對只靠 cashier 的人照舊被擋（正對照見下）。
F① 沒有 daily_task／case_manage 模組的人不送 /api/daily-tasks（後端一定 403）；最高管理者與有模組的人照送。
F② 案件整包裡被擋的四塊（派工／出貨單／完工單／動態）顯示白話說明（需要哪個模組），不洩漏案件是否存在、不亂說（有模組卻被擋、模組未安裝都不說）。
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from core.source_tree import page_file
from tests._requires import requires_module

needs_m01 = requires_module("case", "本題打 M01（案件）的端點")

FRONT = Path(__file__).resolve().parents[2] / "frontend"
CORE = FRONT / "js" / "case-management-core.js"
FEED = FRONT / "js" / "case-management-feed.js"
NOTIF = FRONT / "static" / "notif.js"
CSS = FRONT / "css" / "case-management.css"
NODE = shutil.which("node")
NO = "MQ-T86AF-001"


# ───────────── A：後端 ─────────────
def _login(client, u):
    r = client.post("/api/auth/login", json={"username": u[0], "password": u[1]})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _seed_case(make_user):
    import db
    owner = make_user(username="af_owner", role="sales")
    conn = db.get_db()
    try:
        oid = conn.execute("SELECT id FROM users WHERE username=?", (owner[0],)).fetchone()[0]
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, sales_person_id, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "客", "案", 100, 95, json.dumps({"dealTag": "已成案"}, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", oid, "擁有者", "[]"))
        conn.commit()
    finally:
        conn.close()


@needs_m01
def test_a_finance_with_financial_view_reads_item_shipped_of_someone_elses_case(client, make_user):
    u = make_user(username="af_fin", role="finance", modules=["cashier", "financial_view"])
    _seed_case(make_user)
    r = client.get(f"/api/quotations/{NO}/item-shipped", headers=_login(client, u))
    assert r.status_code == 200, r.text
    assert set(r.json()) >= {"quoteNo", "items", "totals"}


@needs_m01
def test_a_teeth_a_non_reader_with_the_module_is_still_denied(client, make_user):
    """正對照：有 case_manage 模組、但不是擁有者也沒有 cashier 讀取資格的人，照舊 404——放寬的是財務的『讀取』範圍，不是所有人。"""
    u = make_user(username="af_eng", role="engineer", modules=["case_manage"])
    _seed_case(make_user)
    assert client.get(f"/api/quotations/{NO}/item-shipped", headers=_login(client, u)).status_code == 404


@needs_m01
def test_a_cashier_only_finance_account_reads_it_too(client, make_user):
    """沙箱實測的真實情境：只靠 cashier 進案件的財務（有效模組含 financial_view）——以前模組放行、逐案 404，現在 200。"""
    u = make_user(username="af_cash", role="finance", modules=["cashier"])
    _seed_case(make_user)
    assert client.get(f"/api/quotations/{NO}/item-shipped", headers=_login(client, u)).status_code == 200


@needs_m01
def test_a_module_check_is_unchanged_an_account_without_any_of_the_three_modules_is_refused(client, make_user):
    u = make_user(username="af_nomod", role="engineer", modules=["customer"])
    _seed_case(make_user)
    assert client.get(f"/api/quotations/{NO}/item-shipped", headers=_login(client, u)).status_code == 403


@needs_m01
def test_b_to_e_stay_closed_for_a_cashier_only_finance_account(client, make_user):
    u = make_user(username="af_cash2", role="finance", modules=["cashier"])
    _seed_case(make_user)
    parts = client.get(f"/api/quotations/{NO}/case-bundle", headers=_login(client, u)).json()["parts"]
    for k in ("dispatches", "shippingNotes", "completionNotes", "updates"):
        assert parts[k]["ok"] is False and parts[k]["status"] in (403, 404), (k, parts[k])


# ───────────── F①：前端不送注定 403 的請求 ─────────────
NOTIF_HARNESS = r"""
const fs = require('fs'); const src = fs.readFileSync(process.argv[1], 'utf8'); const inp = JSON.parse(process.argv[2])
const a = src.indexOf('    async _fetchDailyTaskCount() {')
const body = src.slice(a, src.indexOf('\n    },\n', a) + 7)
const calls = []
global.fetch = async (url) => { calls.push(url); return { ok: true, json: async () => ({ items: [] }) } }
const o = new Function('return {' + body.replace(/,\s*$/, '') + '}')()
Object.assign(o, { _sess: { username: 'u', token: 't', role: inp.role, modules: inp.modules }, _updateDTBadge() {} })
;(async () => { await o._fetchDailyTaskCount(); console.log(JSON.stringify(calls)) })()
"""


def _notif_calls(role, modules):
    out = subprocess.run([NODE, "-e", NOTIF_HARNESS, str(NOTIF), json.dumps({"role": role, "modules": modules})],
                         capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not NODE, reason="需要 node")
@pytest.mark.parametrize("role,mods,n", [
    ("finance", ["cashier", "financial_view"], 0),          # 沒有 daily_task／case_manage ⇒ 後端一定 403 ⇒ 不送
    ("admin", [], 0),                                       # admin 也不直通（require_any_module：只有 superadmin 直通）
    ("sales", ["quotation"], 0),
    ("finance", ["cashier", "case_manage"], 1),
    ("sales", ["daily_task"], 1),
    ("superadmin", [], 1),
])
def test_f1_bell_only_asks_for_daily_tasks_when_the_account_may_read_them(role, mods, n):
    assert len(_notif_calls(role, mods)) == n


def test_f1_the_case_page_task_list_follows_the_same_rule():
    s = FEED.read_text(encoding="utf-8")
    a = s.index("async _loadCaseTasks(quoteNo)")
    blk = s[a:s.index("fetch(`/api/daily-tasks", a)]
    assert "this.session.role !== 'superadmin' && !this.hasModule('daily_task') && !this.hasModule('case_manage')" in blk


# ───────────── F②：被擋的分頁說白話 ─────────────
BLOCK_HARNESS = r"""
const fs = require('fs'); const src = fs.readFileSync(process.argv[1], 'utf8'); const inp = JSON.parse(process.argv[2])
const a = src.indexOf('    hasModule(key) {')
const body = src.slice(a, src.indexOf('    canMarkPayment() {', a))
const o = new Function('return {' + body.replace(/,\s*$/, '') + '}')()
Object.assign(o, { session: { role: inp.role, modules: inp.modules } })
o._notePartAccess(inp.parts)
console.log(JSON.stringify(['dispatch', 'shipping', 'completion', 'feed'].map(t => o.blockedNote(t))))
"""
DENIED = {"ok": False, "status": 404, "detail": "報價單 MQ-1 不存在"}
OK = {"ok": True, "data": []}


def _notes(role, modules, parts):
    out = subprocess.run([NODE, "-e", BLOCK_HARNESS, str(CORE), json.dumps({"role": role, "modules": modules, "parts": parts})],
                         capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_f2_a_blocked_tab_says_which_module_is_needed():
    parts = {"dispatches": {"ok": False, "status": 403, "detail": "沒有權限"}, "shippingNotes": DENIED, "completionNotes": DENIED, "updates": DENIED}
    notes = _notes("finance", ["cashier", "financial_view"], parts)
    assert all("「案件管理」" in n and "模組權限" in n for n in notes), notes
    # 不洩漏：訊息裡沒有案號、沒有「不存在」
    assert not any(re.search(r"MQ-|不存在|查無", n) for n in notes)


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_f2_nothing_is_said_when_the_account_has_the_module_is_superadmin_or_the_part_loaded():
    parts = {"dispatches": DENIED, "shippingNotes": DENIED, "completionNotes": DENIED, "updates": DENIED}
    assert _notes("finance", ["case_manage"], parts) == ["", "", "", ""]          # 有模組卻被擋＝逐案規則，不亂說是模組問題
    assert _notes("superadmin", [], parts) == ["", "", "", ""]
    ok = {"dispatches": OK, "shippingNotes": OK, "completionNotes": OK, "updates": OK}
    assert _notes("finance", ["cashier"], ok) == ["", "", "", ""]


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_f2_module_not_installed_keeps_its_own_notice():
    gone = {"ok": False, "status": 404, "detail": "採購・庫存・出貨模組未安裝：沒有出貨單資料"}
    notes = _notes("finance", ["cashier"], {"dispatches": OK, "shippingNotes": gone, "completionNotes": OK, "updates": OK})
    assert notes == ["", "", "", ""]


def test_f2_each_of_the_four_panes_carries_the_notice_and_the_css_hides_the_rest():
    html = page_file("case-management.html").read_text(encoding="utf-8")
    for tab in ("dispatch", "shipping", "completion", "feed"):
        assert f"data-testid=\"cm-blocked-{tab}\"" in html and f"blockedNote('{tab}')" in html, tab
        assert f":class=\"{{'cm-pane-blocked': blockedNote('{tab}')}}\"" in html, tab
    css = CSS.read_text(encoding="utf-8")
    assert ".cm-pane-blocked > :not(.cm-blocked) { display:none !important; }" in css
    core = CORE.read_text(encoding="utf-8")
    assert core.index("this._notePartAccess(parts)") < core.index("this.loadDispatches(quoteNo, parts.dispatches)")


# ───────────── e2e ─────────────
from tests._e2e_login import inject_login  # noqa: E402


def _open_home(live_server, e2e_browser, u):
    page = e2e_browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
    seen = []
    page.on("request", lambda r: seen.append(r.url) if "/api/daily-tasks" in r.url else None)
    inject_login(page, live_server, u[0], u[1])
    page.goto(f"{live_server}/index.html")
    page.wait_for_function("() => { try { const d = Alpine.$data(document.body); return d.statsLoaded === true && !d.loading } catch (e) { return false } }", timeout=20000)
    page.wait_for_timeout(1000)
    return page, seen


@pytest.mark.e2e
@pytest.mark.parametrize("mods,n", [(["cashier"], 0), (["cashier", "case_manage"], 1)])
def test_e2e_f1_home_sends_daily_tasks_request_only_when_the_account_has_the_module(live_server, make_user, e2e_browser, mods, n):
    u = make_user(username=f"af_e2e_fin{n}", role="finance", modules=mods)
    _page, seen = _open_home(live_server, e2e_browser, u)
    assert len(seen) == n, seen


@pytest.mark.e2e
def test_e2e_f2_a_blocked_pane_shows_only_the_plain_notice(live_server, make_user, e2e_browser):
    """案件頁本身要 case_manage 才進得去，所以這題用「有 case_manage 才能開頁」的帳號開案件，
    再把這個帳號的模組表改成沒有 case_manage、並餵入被擋的整包段落，驗畫面：白話說明出現、空清單被藏起來。"""
    u = make_user(username="af_e2e_blk", role="finance", modules=["cashier", "case_manage"])
    _seed_case(make_user)
    page = e2e_browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
    inject_login(page, live_server, u[0], u[1])
    page.goto(f"{live_server}/pages/case-management.html")
    page.wait_for_function("() => { try { const d = Alpine.$data(document.body); return d.session && d.session.token && !d.loading && d.caseCounts } catch (e) { return false } }", timeout=20000)
    page.evaluate("(no) => Alpine.$data(document.body).selectCase(no)", NO)
    page.wait_for_selector("[data-testid=cm-blocked-feed]", state="attached", timeout=20000)
    # 有 case_manage（真實情況）：四塊都沒被擋、說明不出現
    for tab in ("dispatch", "shipping", "completion", "feed"):
        assert page.locator(f"[data-testid=cm-blocked-{tab}]").is_visible() is False, tab
    denied = {"ok": False, "status": 404, "detail": "報價單 X 不存在"}
    page.evaluate("""(d) => { const a = Alpine.$data(document.body)
        a.session = { ...a.session, modules: ['cashier'] }
        a._notePartAccess({ dispatches: { ok: false, status: 403, detail: '沒有權限' }, shippingNotes: d, completionNotes: d, updates: d }) }""", denied)
    for tab in ("dispatch", "shipping", "completion", "feed"):
        page.evaluate("(t) => { Alpine.$data(document.body).activeTab = t }", tab)
        page.wait_for_timeout(200)
        box = page.locator(f"[data-testid=cm-blocked-{tab}]")
        assert box.is_visible(), tab
        assert "「案件管理」模組權限" in box.inner_text() and "不存在" not in box.inner_text()
        # 同一個分頁裡其他子元素都被藏起來（沒有空清單的「尚無…」跟說明並排）
        visible_siblings = page.evaluate(
            "(t) => [...document.querySelector('[data-testid=cm-blocked-' + t + ']').parentElement.children].filter(e => !e.classList.contains('cm-blocked') && getComputedStyle(e).display !== 'none').length", tab)
        assert visible_siblings == 0, (tab, visible_siblings)
