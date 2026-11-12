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
const handlers = {}; const real = []; const banners = []
const win = { addEventListener: (ev, fn) => { (handlers[ev] = handlers[ev] || []).push(fn) }, motrixApplyBanners: h => banners.push(h) }
const ls = { getItem: () => JSON.stringify({ token: 'T' }), removeItem() {} }
const ss = { setItem() {}, getItem: () => null, removeItem() {} }
const loc = { pathname: '/pages/x.html', search: '', hash: '', replace() {} }
const doc = { createElement: () => ({}), head: { appendChild() {} }, getElementById: () => null }
const bootBody = Object.assign({ v: 1, me: { username: 'u' }, menu: { groups: [1] }, approvalCount: { count: 3 }, notifications: { items: [], unread: 0 }, errors: {} }, inp.extra || {})
const fetchFn = (url, opts) => {
  if (url === '/api/bootstrap') return Promise.resolve({ ok: true, status: 200, headers: { get: k => ({ 'X-Motrix-License': 'dev_key', 'X-Motrix-Company-Setup': null })[k] }, json: () => Promise.resolve(bootBody) })
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
