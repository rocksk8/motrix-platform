# -*- coding: utf-8 -*-
"""啟動資料的前端端（static/auth-guard.js 的 window.MotrixBoot／motrixBoot／motrixBootFetch；notif.js／sidebar.js 的呼叫點）。

用 node 直接執行 auth-guard.js（不開瀏覽器；沒有 node 就略過）。守的事：
  - 第一次要某區段時由 bootstrap 供應（Response 形狀與原端點一致）、之後一律是真的 fetch（重抓拿到真資料）；
  - 過期（20 秒）、token 不同、區段缺（errors）、非 GET、帶 query ⇒ 一律真的 fetch；
  - 使用者動作事件（簽核處理完、標已讀…）⇒ 整份啟動資料作廢；
  - 供應時補上 bootstrap 那次回應的橫幅標頭（授權／本公司資料設定）；
  - JS 端的「路徑 → 區段」表與後端 routers/bootstrap.ORIGINAL_PATH 完全一致。
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from routers import bootstrap as B

FRONT = Path(__file__).resolve().parents[2] / "frontend" / "static"
GUARD = FRONT / "auth-guard.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="需要 node")

HARNESS = r"""
const fs = require('fs'); const src = fs.readFileSync(process.argv[2], 'utf8'); const inp = JSON.parse(process.argv[3])
let now = 1000000; Date.now = () => now
let guardMeSeen = false
const handlers = {}; const real = []; const banners = []
const win = { addEventListener: (ev, fn) => { (handlers[ev] = handlers[ev] || []).push(fn) }, motrixApplyBanners: h => banners.push(h) }
const ls = { getItem: () => JSON.stringify({ token: 'T' }), removeItem() {} }
const ss = { setItem() {}, getItem: k => (k === 'motrix_prefs_synced' ? '1' : null), removeItem() {} }   // 偏好同步（t82 syncPrefs）已做過 ⇒ 不發 /api/auth/preferences，不干擾請求清單
const loc = { pathname: '/pages/x.html', search: '', hash: '', replace() {} }
const doc = { createElement: () => ({}), head: { appendChild() {} }, getElementById: () => null }
const bootBody = Object.assign({ v: 1, me: { username: 'u' }, menu: { groups: [1] }, approvalCount: { count: 3 }, notifications: { items: [], unread: 0 }, errors: {} }, inp.extra || {})
const fetchFn = (url, opts) => {
  if (url === '/api/bootstrap') return Promise.resolve({ ok: true, status: 200, headers: { get: k => ({ 'X-Motrix-License': 'dev_key', 'X-Motrix-Company-Setup': null })[k] }, json: () => Promise.resolve(bootBody) })
  if (url === '/api/auth/me' && !guardMeSeen) { guardMeSeen = true; return Promise.resolve({ ok: true, status: 200 }) }   // auth-guard 自己的放行請求（不算頁面載入點）
  real.push(url)
  return Promise.resolve(new Response(JSON.stringify({ real: url }), { status: 200 }))
}
const f = new Function('window', 'location', 'localStorage', 'sessionStorage', 'document', 'fetch', 'setTimeout', 'clearTimeout', src)
f(win, loc, ls, ss, doc, fetchFn, (fn) => 0, () => {})
const H = t => ({ headers: { Authorization: 'Bearer ' + (t || 'T') } })
const J = async p => { const r = await p; return await r.json() }
;(async () => {
  await win.MotrixBoot
  const out = {}
  const steps = inp.steps
  out.results = []
  for (const st of steps) {
    if (st.advance) { now += st.advance; continue }
    if (st.fire) { (handlers[st.fire] || []).forEach(fn => fn({})); out.results.push(['fire', st.fire]); continue }
    if (st.boot) { out.results.push(['boot', st.boot, await win.motrixBoot(st.boot)]); continue }
    const o = st.opts === undefined ? H(st.token) : st.opts
    out.results.push([st.url, await J(win.motrixBootFetch(st.url, o))])
  }
  out.real = real; out.banners = banners
  console.log(JSON.stringify(out))
})()
"""


GUARD_HARNESS = r"""
const fs = require('fs'); const src = fs.readFileSync(process.argv[2], 'utf8'); const inp = JSON.parse(process.argv[3])
const log = []; let revealed = false; let removedSession = false; let replaced = null
const style = { remove() { revealed = true } }
const win = { addEventListener() {}, motrixApplyBanners() {} }
const ls = { getItem: () => JSON.stringify({ token: 'T' }), removeItem() { removedSession = true } }
const ss = { setItem() {}, getItem: k => (k === 'motrix_prefs_synced' ? '1' : null), removeItem() {} }   // 偏好同步（t82 syncPrefs）已做過 ⇒ 不發 /api/auth/preferences，不干擾請求清單
const loc = { pathname: '/pages/x.html', search: '', hash: '', replace(u) { replaced = u } }
const doc = { createElement: () => style, head: { appendChild() {} }, getElementById: () => style }
const pending = new Promise(() => {})
const resp = (st, body) => ({ ok: st >= 200 && st < 300, status: st, headers: { get: () => null }, json: () => Promise.resolve(body) })
const fetchFn = (url) => {
  log.push(url)
  if (url === '/api/bootstrap') return inp.boot === 'pending' ? pending : inp.boot === 'reject' ? Promise.reject(new Error('net')) : Promise.resolve(resp(inp.boot, { v: 1, me: { username: 'u' }, errors: {} }))
  if (url === '/api/auth/me') return Promise.resolve(resp(inp.me, {}))
  return Promise.reject(new Error('unexpected ' + url))
}
const f = new Function('window', 'location', 'localStorage', 'sessionStorage', 'document', 'fetch', 'setTimeout', 'clearTimeout', src)
f(win, loc, ls, ss, doc, fetchFn, () => 0, () => {})
const tick = () => new Promise(r => setImmediate(r))
;(async () => { for (let i = 0; i < 5; i++) await tick(); console.log(JSON.stringify({ log, revealed, removedSession, replaced })) })()
"""


HUNG_HARNESS = r"""
// 真的計時器：bootstrap 永遠不回，頁面要資料的 motrixBootFetch 必須在逾時後退回真的 fetch（B1 追加：等待上限 1.5 s，不是 6 s）
const fs = require('fs'); const src = fs.readFileSync(process.argv[2], 'utf8')
const win = { addEventListener() {}, motrixApplyBanners() {} }
const ls = { getItem: () => JSON.stringify({ token: 'T' }), removeItem() {} }
const ss = { setItem() {}, getItem: k => (k === 'motrix_prefs_synced' ? '1' : null), removeItem() {} }   // 偏好同步（t82 syncPrefs）已做過 ⇒ 不發 /api/auth/preferences，不干擾請求清單
const loc = { pathname: '/pages/x.html', search: '', hash: '', replace() {} }
const el = { remove() {} }
const doc = { createElement: () => el, head: { appendChild() {} }, getElementById: () => el }
const t0 = Date.now(); const log = []
const lateBody = { v: 1, me: { username: 'u' }, menu: { late: true }, errors: {} }
let releaseBoot
const fetchFn = (url) => {
  if (url === '/api/bootstrap') return new Promise(res => { releaseBoot = () => res({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve(lateBody) }) })
  if (url === '/api/auth/me') return Promise.resolve({ ok: true, status: 200 })
  log.push(url); return Promise.resolve(new Response(JSON.stringify({ real: url }), { status: 200 }))
}
const f = new Function('window', 'location', 'localStorage', 'sessionStorage', 'document', 'fetch', 'setTimeout', 'clearTimeout', src)
f(win, loc, ls, ss, doc, fetchFn, setTimeout, clearTimeout)
;(async () => {
  const r = await win.motrixBootFetch('/api/platform/menu', { headers: { Authorization: 'Bearer T' } })
  const body = await r.json(); const ms = Date.now() - t0
  releaseBoot()                                                   // 逾時之後才到的 bootstrap：要被丟掉
  await new Promise(res => setTimeout(res, 50))
  const r2 = await win.motrixBootFetch('/api/platform/menu', { headers: { Authorization: 'Bearer T' } })
  console.log(JSON.stringify({ ms, body, log, later: await r2.json() }))
})()
"""


def test_hung_bootstrap_delays_page_data_by_at_most_two_seconds():
    """PM：bootstrap 卡住時，等它的頁面資料不能卡 6 秒（比沒有 bootstrap 還糟）。上限 ~1.5 s 後退回原端點；晚到的 bootstrap 不得再被拿來供應。"""
    r = subprocess.run([NODE, "-e", HUNG_HARNESS, "x", str(GUARD)], capture_output=True, text=True, encoding="utf-8", timeout=30, check=True)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["body"] == {"real": "/api/platform/menu"}
    assert 1200 <= out["ms"] < 2000, out["ms"]                       # 下限＝確實等了逾時（不是根本沒等）；上限＝PM 要求的 2 秒內
    assert out["later"] == {"real": "/api/platform/menu"}, out       # 逾時後才回的 bootstrap（menu.late）不得被供應
    assert out["log"] == ["/api/platform/menu", "/api/platform/menu"]   # 兩次都是真的請求


def test_boot_wait_constant_is_one_and_a_half_seconds():
    assert "var BOOT_WAIT_MS = 1500," in GUARD.read_text(encoding="utf-8")


def _guard(me, boot):
    r = subprocess.run([NODE, "-e", GUARD_HARNESS, "x", str(GUARD), json.dumps({"me": me, "boot": boot})],
                       capture_output=True, text=True, encoding="utf-8", timeout=30, check=True)
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_page_is_revealed_by_the_fast_me_call_without_waiting_for_bootstrap():
    """B1：放行只看 auth/me；bootstrap 還沒回來（甚至永遠不回）頁面照樣顯示——啟動資料慢不能拖慢首繪。"""
    out = _guard(me=200, boot="pending")
    assert out["revealed"] is True and out["replaced"] is None
    assert sorted(out["log"]) == ["/api/auth/me", "/api/bootstrap"]          # 兩支同時發出（並行，不是先後）
    assert out["log"][0] == "/api/bootstrap"                                 # bootstrap 不排在 me 後面等


@pytest.mark.parametrize("boot", [401, 403, 428, 404, 500, "reject"])
def test_bootstrap_failure_never_blocks_or_changes_the_guard_outcome(boot):
    out = _guard(me=200, boot=boot)
    assert out["revealed"] is True and out["replaced"] is None and out["removedSession"] is False


def test_guard_outcome_follows_auth_me_only():
    assert _guard(me=401, boot=200)["replaced"] == "login.html"              # bootstrap 說好也不能讓一個過期的登入放行
    assert _guard(me=402, boot=200)["replaced"] == "license-required.html"
    assert _guard(me=401, boot=200)["removedSession"] is True


def _run(steps, extra=None):
    r = subprocess.run([NODE, "-e", HARNESS, "x", str(GUARD), json.dumps({"steps": steps, "extra": extra})],
                       capture_output=True, text=True, encoding="utf-8", timeout=30, check=True)
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_first_request_is_served_from_bootstrap_then_real():
    out = _run([{"url": "/api/platform/menu"}, {"url": "/api/platform/menu"}])
    assert out["results"][0] == ["/api/platform/menu", {"groups": [1]}]
    assert out["results"][1][1] == {"real": "/api/platform/menu"}
    assert out["real"] == ["/api/platform/menu"]


def test_sections_used_by_two_loaders_are_served_twice():
    out = _run([{"url": "/api/approval-queue/count"}] * 3)
    assert [r[1] for r in out["results"]] == [{"count": 3}, {"count": 3}, {"real": "/api/approval-queue/count"}]


def test_everything_that_cannot_be_trusted_goes_to_the_real_endpoint():
    out = _run([
        {"url": "/api/platform/menu", "token": "OTHER"},                                   # 換了人
        {"url": "/api/platform/menu", "opts": {"method": "POST", "headers": {"Authorization": "Bearer T"}}},
        {"url": "/api/platform/menu?x=1"},                                                   # 帶 query 不是這個端點
        {"url": "/api/platform/menu", "opts": {}},                                           # 沒帶 Authorization
        {"url": "/api/system/bonus-module-status"},                                          # bootstrap 沒給這一段
        {"url": "/api/customers"},                                                           # 不在對照表
    ])
    assert all("real" in r[1] for r in out["results"]), out
    assert len(out["real"]) == 6


def test_expired_after_20_seconds():
    out = _run([{"advance": 20001}, {"url": "/api/platform/menu"}])
    assert out["results"][0][1] == {"real": "/api/platform/menu"}
    out = _run([{"advance": 19000}, {"url": "/api/platform/menu"}])
    assert out["results"][0][1] == {"groups": [1]}


@pytest.mark.parametrize("ev", ["motrix:approval-changed", "motrix:reads-changed", "motrix:item-read", "motrix:item-read-failed"])
def test_user_driven_refresh_events_invalidate_the_snapshot(ev):
    out = _run([{"fire": ev}, {"url": "/api/platform/menu"}, {"url": "/api/approval-queue/count"}])
    assert out["real"] == ["/api/platform/menu", "/api/approval-queue/count"]


@pytest.mark.parametrize("status", (403, 404))
def test_a_section_bootstrap_was_refused_is_answered_with_the_same_status_without_a_request(status):
    """T86 U5：bootstrap 剛問過原端點、回 403／404 ⇒ 20 秒內再問只會得到同一個答案 ⇒ 不再送請求（只供應一次，之後照舊真的送）。"""
    out = _run([{"url": "/api/build-info"}, {"url": "/api/build-info"}], extra={"buildInfo": None, "errors": {"buildInfo": status}})
    assert out["results"][0][1] == {"detail": "沒有權限" if status == 403 else "不存在"}
    assert out["results"][1][1] == {"real": "/api/build-info"} and out["real"] == ["/api/build-info"]


@pytest.mark.parametrize("status", (428, 500, 502))
def test_other_failures_are_still_retried_for_real(status):
    out = _run([{"url": "/api/build-info"}], extra={"buildInfo": None, "errors": {"buildInfo": status}})
    assert out["results"][0][1] == {"real": "/api/build-info"}


def test_a_refused_section_is_not_replayed_after_20_seconds_or_for_someone_else():
    out = _run([{"advance": 20001}, {"url": "/api/build-info"}], extra={"buildInfo": None, "errors": {"buildInfo": 403}})
    assert out["results"][0][1] == {"real": "/api/build-info"}
    out = _run([{"url": "/api/build-info", "token": "OTHER"}], extra={"buildInfo": None, "errors": {"buildInfo": 403}})
    assert out["results"][0][1] == {"real": "/api/build-info"}


def test_failed_sections_are_not_served_even_if_present_as_null():
    out = _run([{"url": "/api/build-info"}], extra={"buildInfo": None, "errors": {"buildInfo": 500}})
    assert out["results"][0][1] == {"real": "/api/build-info"}


def test_motrix_boot_helper_hands_out_each_section_once():
    out = _run([{"boot": "menu"}, {"boot": "menu"}, {"boot": "approvalCount"}, {"boot": "approvalCount"}, {"boot": "approvalCount"}])
    assert [r[2] for r in out["results"]] == [{"groups": [1]}, None, {"count": 3}, {"count": 3}, None]


def test_banner_headers_of_the_bootstrap_response_are_applied_on_first_serve():
    out = _run([{"url": "/api/platform/menu"}])
    assert out["banners"] == [{"license": "dev_key", "setup": None}]


def test_js_section_table_matches_the_backend():
    src = GUARD.read_text(encoding="utf-8")
    block = src[src.index("var BOOT_SECTIONS = {"):src.index("};", src.index("var BOOT_SECTIONS = {"))]
    pairs = dict(re.findall(r"'(/api/[^']+)': \['(\w+)', \d\]", block))
    assert pairs == {path: name for name, path in B.ORIGINAL_PATH.items()}


def test_every_boot_fetch_call_site_is_a_first_load_call_with_the_same_url():
    """sidebar.js／notif.js 裡改用 motrixBootFetch 的呼叫點：URL 都在對照表裡、都帶 Authorization（否則永遠退回真的 fetch）。"""
    src = (FRONT / "sidebar.js").read_text(encoding="utf-8") + (FRONT / "notif.js").read_text(encoding="utf-8")
    urls = re.findall(r"\(window\.motrixBootFetch \|\| fetch\)\('(/api/[^']+)'", src)
    assert sorted(urls) == sorted([
        "/api/build-info", "/api/platform/menu", "/api/auth/me", "/api/system/bonus-module-status",
        "/api/system/modules/availability", "/api/online-users", "/api/auth/totp/status", "/api/notifications/mine",
        "/api/reads/module-counts", "/api/approval-queue/count"]), urls
    assert set(urls) <= set(B.ORIGINAL_PATH.values())
