# -*- coding: utf-8 -*-
"""T61 S6：自訂按鈕的前端（執行時 store、點擊行為、按鈕編輯器）——靜態＋node 真的執行。

證明：旗標關閉（讀到 enabled=false／HTTP 錯誤／斷線）什麼都不畫、不掛編輯器；開頁只接受單純的頁面檔名；
匯出只接受 /api/ 開頭的路徑、用點擊者自己的 token、檔名取自 Content-Disposition、錯誤如實顯示；預覽中的按鈕不執行任何動作；
編輯器的定義 body 只含認得的鍵、取消確認就不送發布、待核准如實顯示、沒有原生對話框。
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
JS = ROOT / "frontend" / "static" / "user-buttons.js"
NODE = shutil.which("node")
NATIVE = re.compile(r"(?:(?<![\w.$])|(?<=window\.))(alert|confirm|prompt)\s*\(")


def _strip(s):
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", r"\1", line) for line in s.split("\n"))


def _native(text):
    return [m.group(1) for line in _strip(text).split("\n") for m in NATIVE.finditer(line)]


def test_scanner_positive_control_and_no_native_dialogs():
    assert _native("alert('a'); if (!confirm('b')) return; window.prompt('c'); await this._ask('d')") == ["alert", "confirm", "prompt"]
    assert _native(JS.read_text(encoding="utf-8")) == []


def test_labels_are_never_inserted_as_html():
    src = _strip(JS.read_text(encoding="utf-8"))
    assert "innerHTML" in src                                    # 只有編輯器自己的樣板（常數）用 innerHTML
    assert "x-html" not in src
    i = src.index("function mountEditor")
    assert "wrap.innerHTML = tpl()" in src[i:i + 600] and src.count("innerHTML") == 1


_RT = r"""
const fs = require('fs')
global.window = global
const calls = { fetch: [], appended: 0, clicks: [], hrefs: [] }
let ROLE = %(role)s
global.localStorage = { getItem() { return JSON.stringify({ token: 'tok-1', role: ROLE }) } }
window.location = { set href(v) { calls.hrefs.push(v) }, get href() { return '' } }
global.URL = { createObjectURL() { return 'blob:x' }, revokeObjectURL() {} }
global.document = { addEventListener() {}, getElementById() { return null }, head: { appendChild() {} },
  createElement(t) { const el = { tag: t, innerHTML: '', firstChild: {}, textContent: '', id: '', click() { calls.clicks.push({ download: el.download, href: el.href }) } }; return el },
  body: { appendChild() { calls.appended++ }, removeChild() {}, classList: { add() {}, remove() {} } } }
let RESP = %(resp)s
global.fetch = async (url, opt) => { calls.fetch.push({ url: String(url), auth: opt && opt.headers && opt.headers.Authorization })
  if (RESP === 'fail') throw new Error('x')
  if (String(url).indexOf('/api/user-buttons/') === 0) return { ok: RESP !== 'http', json: async () => RESP }
  return EXPORT(url) }
let EXPORT = () => ({ ok: true, headers: { get: () => "attachment; filename*=UTF-8''%%E5%%A4%%96%%E5%%8C%%85%%E5%%90%%8D%%E5%%86%%8A.xlsx" }, blob: async () => ({}), json: async () => ({}) })
eval(fs.readFileSync(process.argv[1], 'utf8'))
;(async () => {
%(body)s
})().catch(e => { console.error(String(e)); process.exit(1) })
"""


def _node(body, resp, role="'superadmin'"):
    js = _RT % dict(body=body, resp=resp, role=role)
    out = subprocess.run([NODE, "-e", js, str(JS)], capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[:1500]
    return json.loads(out.stdout.decode("utf-8"))


_INIT = "await window.MotrixUserButtons.init({ module: 'supply', page: 'suppliers.html', slot: 'toolbar' })\nconst S = window.MotrixUserButtons._state()\n"
BTNS = ("{ enabled: true, buttons: [{ key: 'b1', slot: 'toolbar', label: '出貨匯出紀錄', type: 'navigate', page: 'shipping-export-history.html' },"
        " { key: 'b2', slot: 'toolbar', label: '外包名冊', type: 'export', endpoint: '/api/contractors/export', format: 'xlsx' }] }")


@pytest.mark.skipif(NODE is None, reason="沒有 node")
@pytest.mark.parametrize("resp", ["{ enabled: false, buttons: [] }", "'http'", "'fail'"])
def test_flag_off_or_unreadable_draws_nothing_and_mounts_no_editor(resp):
    r = _node(_INIT + "console.log(JSON.stringify({ calls, enabled: S.enabled, list: S.list('toolbar') }))", resp)
    assert r["enabled"] is False and r["list"] == [] and r["calls"]["appended"] == 0
    assert [c["url"] for c in r["calls"]["fetch"]] == ["/api/user-buttons/supply/suppliers.html"]


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_flag_on_lists_by_slot_and_mounts_the_editor_only_for_superadmin():
    r = _node(_INIT + "console.log(JSON.stringify({ calls, enabled: S.enabled, keys: S.list('toolbar').map(b => b.key), other: S.list('nope').length }))", BTNS)
    assert r["enabled"] is True and r["keys"] == ["b1", "b2"] and r["other"] == 0 and r["calls"]["appended"] == 1
    r = _node(_INIT + "console.log(JSON.stringify({ calls, keys: S.list('toolbar').map(b => b.key) }))", BTNS, role="'sales'")
    assert r["keys"] == ["b1", "b2"] and r["calls"]["appended"] == 0


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_navigate_only_accepts_plain_page_names():
    body = _INIT + """
  const good = { type: 'navigate', page: 'shipping-export-history.html' }
  await window.MotrixUserButtons.run(good)
  for (const p of ['https://evil.example/x.html', 'javascript:alert(1)', '../x.html', 'a.html?x=1', '/etc/passwd', 'x.html#y', '', undefined, 'A B.html'])
    await window.MotrixUserButtons.run({ type: 'navigate', page: p })
  console.log(JSON.stringify({ hrefs: calls.hrefs, fetches: calls.fetch.length }))"""
    r = _node(body, "{ enabled: true, buttons: [] }")
    assert r["hrefs"] == ["shipping-export-history.html"] and r["fetches"] == 1                 # 只有啟動時讀按鈕的那一個請求


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_export_uses_the_clickers_own_token_downloads_with_server_filename_and_shows_errors():
    body = _INIT + """
  const b = S.buttons[1]
  await window.MotrixUserButtons.run(b)
  const ok = { fetches: calls.fetch.slice(1), clicks: calls.clicks.slice(), msg: S.msg }
  EXPORT = () => ({ ok: false, status: 403, headers: { get: () => '' }, blob: async () => ({}), json: async () => ({ detail: '沒有權限' }) })
  calls.clicks.length = 0
  await window.MotrixUserButtons.run(b)
  console.log(JSON.stringify({ ok, err: { msg: S.msg, clicks: calls.clicks.length, busy: S.busy } }))"""
    r = _node(body, BTNS)
    assert r["ok"]["fetches"] == [{"url": "/api/contractors/export", "auth": "Bearer tok-1"}]
    assert r["ok"]["clicks"] == [{"download": "外包名冊.xlsx", "href": "blob:x"}] and r["ok"]["msg"] == ""
    assert r["err"] == {"msg": "匯出失敗：沒有權限", "clicks": 0, "busy": False}


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_export_refuses_paths_that_are_not_plain_api_paths_and_preview_runs_nothing():
    body = _INIT + """
  const n0 = calls.fetch.length
  for (const e of ['https://evil.example/api/x', '//evil.example/api/x', '/api/../etc/passwd', 'api/contractors/export', '/api/x?y=1', '/static/x.js', '', undefined])
    await window.MotrixUserButtons.run({ type: 'export', endpoint: e, label: 'x' })
  const refused = calls.fetch.length - n0
  window.MotrixUserButtons.show([{ key: 'b9', slot: 'toolbar', label: '預覽', type: 'export' }], 'edit', '預覽')
  await window.MotrixUserButtons.run({ type: 'export', endpoint: '/api/contractors/export', label: 'x' })
  await window.MotrixUserButtons.run({ type: 'navigate', page: 'x.html' })
  const inPreview = { fetches: calls.fetch.length - n0, hrefs: calls.hrefs.length, keys: S.list('toolbar').map(b => b.key), mode: S.mode }
  window.MotrixUserButtons.show(null)
  console.log(JSON.stringify({ refused, inPreview, back: S.list('toolbar').map(b => b.key), mode: S.mode }))"""
    r = _node(body, BTNS)
    assert r["refused"] == 0 and r["inPreview"] == {"fetches": 0, "hrefs": 0, "keys": ["b9"], "mode": "edit"}
    assert r["back"] == ["b1", "b2"] and r["mode"] == "live"


# ── 編輯器 ────────────────────────────────────────────────────────────────
_ED = r"""
const fs = require('fs')
global.window = global
global.localStorage = { getItem() { return JSON.stringify({ token: 't', role: 'superadmin' }) } }
global.document = { addEventListener() {}, getElementById() { return null }, body: { classList: { add() {}, remove() {} } } }
let reloads = 0, shown = []
eval(fs.readFileSync(process.argv[1], 'utf8'))
window.MotrixUserButtons.reload = async () => { reloads++ }
window.MotrixUserButtons.show = (v, m, l) => { shown.push(v) }
window.MotrixUserButtons.init({ module: 'supply', page: 'suppliers.html', slot: 'toolbar' }).catch(() => {})
const c = window.MotrixUserButtons.component()
c.open = true
;(async () => {
%(body)s
})().catch(e => { console.error(String(e)); process.exit(1) })
"""


def _ed(body):
    out = subprocess.run([NODE, "-e", _ED % dict(body=body), str(JS)], capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[:1500]
    return json.loads(out.stdout.decode("utf-8"))


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_editor_body_has_only_known_keys_and_draft_preview_hides_the_target():
    r = _ed("""
  c.work = [{ key: 'b1', slot: 'suppliers.html/toolbar', label: ' 出貨紀錄 ', type: 'navigate', target: 'shipping-export-history.html' },
            { key: 'b2', slot: 'suppliers.html/toolbar', label: '外包名冊', type: 'export', target: 'subcontract:roster' }]
  c.add()
  console.log(JSON.stringify({ body: c._body(), view: c._view(), next: c._nextKey(), n: c.work.length }))""")
    b = r["body"]["buttons"]
    assert b[0] == {"key": "b1", "slot": "suppliers.html/toolbar", "label": "出貨紀錄", "action": {"type": "navigate", "page": "shipping-export-history.html"}}
    assert b[1]["action"] == {"type": "export", "export": "subcontract:roster"}
    assert r["n"] == 3 and r["next"] == "b4" and b[2]["key"] == "b3"
    assert all(set(v) == {"key", "slot", "label", "type"} for v in r["view"])               # 預覽畫面不帶目標（也就沒有可執行的端點）
    assert r["view"][0]["slot"] == "toolbar"


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_editor_ask_publish_cancel_and_pending_text():
    body = """
  const calls = []
  c.defs = { latest: null, draft: null, versions: [] }
  c.work = [{ key: 'b1', slot: 'suppliers.html/toolbar', label: '名冊', type: 'export', target: 'subcontract:roster' }]
  c.load = async () => { c.loadError = '' }
  let RESP = null
  c._j = async (url, opt) => { calls.push((opt && opt.method || 'GET') + ' ' + url.replace(/\\?.*/, ''))
    if (url.indexOf('/draft') >= 0) return { ok: true, status: 200, d: { problems: [] } }
    if (url.indexOf('/validate') >= 0) return { ok: true, status: 200, d: { problems: [] } }
    if (url.indexOf('/publish') >= 0) return { ok: true, status: 200, d: RESP }
    return { ok: true, status: 200, d: { draft: null, latest: null, versions: [] } } }
  window.MotrixDefGovernance = undefined
  let pub = c.publish(); await new Promise(r => setTimeout(r, 20)); c.answer(false); await pub
  const cancelled = calls.filter(x => x.indexOf('/publish') >= 0).length
  RESP = { pending: true, version: 3, effectiveAt: '2026-10-21T09:30:00', reasons: ['新增匯出按鈕'] }
  calls.length = 0; pub = c.publish(); await new Promise(r => setTimeout(r, 20)); c.answer(true); await pub
  const pend = { state: c.state, msg: c.msg, reloads }
  RESP = { version: 4 }
  pub = c.publish(); await new Promise(r => setTimeout(r, 20)); c.answer(true); await pub
  console.log(JSON.stringify({ cancelled, pend, ok: { state: c.state, msg: c.msg, reloads } }))"""
    r = _ed(body)
    assert r["cancelled"] == 0
    assert r["pend"]["state"] == "pending" and r["pend"]["reloads"] == 0
    assert r["pend"]["msg"].startswith("已送出發布，待第二位最高管理者核准") and "已發布" not in r["pend"]["msg"] and "新增匯出按鈕" in r["pend"]["msg"]
    assert r["ok"] == {"state": "published", "msg": "已發布第 4 版", "reloads": 1}


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_editor_preview_as_user_lists_visible_and_hidden_and_never_runs_anything():
    r = _ed("""
  const calls = []
  c.work = [{ key: 'b1', slot: 'suppliers.html/toolbar', label: '名冊', type: 'export', target: 'subcontract:roster' }]
  c.previewUser = ' ub_low '
  c._j = async (url, opt) => { calls.push({ url, method: opt && opt.method, body: opt && opt.body })
    return { ok: true, status: 200, d: { user: 'ub_low', role: 'sales', visible: [], hidden: [{ key: 'b1', reason: '這位使用者沒有匯出「外包名冊」的權限' }] } } }
  await c.previewAs()
  console.log(JSON.stringify({ calls, res: c.previewResult, msg: c.msg }))""")
    assert len(r["calls"]) == 1 and r["calls"][0]["method"] == "POST" and r["calls"][0]["url"].endswith("/suppliers.html/preview")
    assert json.loads(r["calls"][0]["body"])["user"] == "ub_low"                                       # 帳號去頭尾空白
    assert r["res"]["hidden"][0]["label"] == "名冊" and "沒有匯出" in r["res"]["hidden"][0]["reason"]
    assert "沒有執行任何動作" in r["msg"]
