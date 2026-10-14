# -*- coding: utf-8 -*-
"""BP-3 R2：匯出範本編輯器（frontend/static/export-editor.js）以 node 假 DOM／假 fetch 驅動。

①旗標關／不是最高管理者 ⇒ 什麼都不畫  ②範本轉換（順序、標題、勾選）與前端驗證  ③發布前一定要先預覽同一份設定
④一般發布 ⇒ 說已發布並重讀  ⑤待核准 ⇒ 如實說待核准、不說已發布、不重讀  ⑥伺服端要求預覽雜湊（409 preview_required）⇒ 白話提示
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

EDITOR = Path(__file__).resolve().parents[3] / "frontend" / "static" / "export-editor.js"
NODE = shutil.which("node")

_HARNESS = r"""
const fs = require('fs')
const appended = []
function mk(tag) { const n = { tag, children: [], attrs: {}, setAttribute(k, v) { this.attrs[k] = v }, appendChild(c) { this.children.push(c); appended.push(c); return c }, removeChild(c) { this.children = this.children.filter(x => x !== c) },
  get firstChild() { return this.children[0] || null }, addEventListener() {}, remove() {}, querySelector() { return null }, textContent: '', style: {} }; return n }
global.document = { createElement: mk, getElementById: () => null, body: mk('body'), currentScript: null }
global.localStorage = { getItem: () => JSON.stringify({ token: 't' }) }
global.window = global
window.MOTRIX_EXPORT_ID = 'x:y'
const calls = []
const scen = JSON.parse(process.argv[1])
global.fetch = async (url, opt) => {
  const m = (opt && opt.method) || 'GET'
  const path = url.split('?')[0]
  calls.push(m + ' ' + path)
  let status = 200, body = {}
  if (/\/status$/.test(path)) body = scen.status
  else if (m === 'GET' && /api\/definitions\/export_template/.test(path)) body = { draft: null, latest: null, versions: [] }
  else if (m === 'PUT') body = { etag: 'e1' }
  else if (/\/preview$/.test(path)) body = { user: 'u', sample: 'sample', columns: ['A'], rows: [['1']], omitted: [], warnings: [] }
  else if (/\/impact$/.test(path)) body = { previewHash: 'e1' }
  else if (/\/publish$/.test(path)) { status = scen.publishStatus || 200; body = scen.publish || {} }
  return { ok: status < 400, status, json: async () => body }
}
eval(fs.readFileSync(process.argv[2], 'utf8'))
;(async () => {
  await new Promise(r => setTimeout(r, 20))
  const E = window.MotrixExportEditor, st = E._state
  const out = { drawn: appended.length }
  if (scen.run) await eval('(async () => {' + scen.run + '})()').then(v => { out.v = v })
  out.calls = calls; out.msg = st.msg; out.state = st.state; out.bad = st.msgBad
  console.log(JSON.stringify(out))
})().catch(e => { console.error(String(e && e.stack || e)); process.exit(1) })
"""

_CAT = {"enabled": True, "canEdit": True, "exportId": "x:y", "label": "測試", "formats": ["csv"],
        "columns": [{"id": "a", "label": "甲", "money": False}, {"id": "b", "label": "乙", "money": False}, {"id": "m", "label": "金額", "money": True}]}


def _run(scen):
    out = subprocess.run([NODE, "-e", _HARNESS, json.dumps(scen), str(EDITOR)], capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[:1500]
    return json.loads(out.stdout.decode("utf-8"))


_SETUP = "const E = window.MotrixExportEditor, st = E._state; E._init(%s); " % json.dumps(_CAT)


@pytest.mark.skipif(NODE is None, reason="沒有 node")
@pytest.mark.parametrize("status", [{"enabled": False, "canEdit": False}, {"enabled": True, "canEdit": False}])
def test_nothing_is_drawn_when_off_or_not_superadmin(status):
    r = _run({"status": status})
    assert r["drawn"] == 0, "旗標關或不是最高管理者 ⇒ 完全不畫"
    assert r["calls"] == ["GET /api/export-templates/x%3Ay/status"], "頁面只多一個 GET"


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_editor_draws_only_when_on_and_superadmin():
    r = _run({"status": _CAT})
    assert r["drawn"] >= 1


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_template_conversion_keeps_order_labels_and_only_checked_columns():
    run = _SETUP + """
      st.cols = [{id:'b',label:' 乙欄 ',on:true},{id:'a',label:'甲',on:false},{id:'m',label:'金額',on:true}]
      return {t: E._toTemplate(), p: E._problems()}"""
    r = _run({"status": {"enabled": False}, "run": run})
    assert r["v"]["t"] == {"version": 1, "format": "csv", "columns": [{"id": "b", "label": "乙欄"}, {"id": "m", "label": "金額"}]}
    assert r["v"]["p"] == []


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_front_end_validation_matches_the_server_rules():
    run = _SETUP + """
      const probs = lbl => { st.cols = [{id:'a',label:lbl,on:true}]; return E._problems().length > 0 }
      const dup = (st.cols = [{id:'a',label:'同',on:true},{id:'b',label:'同',on:true}], E._problems().length > 0)
      st.cols = [{id:'a',label:'ok',on:false}]
      const none = E._problems().length > 0
      return {tpl: probs('{{x}}'), lt: probs('<b>'), eq: probs('=SUM(1)'), plus: probs('+886'), long: probs('x'.repeat(21)), empty: probs('  '), fine: probs('正常'), dup, none}"""
    r = _run({"status": {"enabled": False}, "run": run})["v"]
    assert r == {"tpl": True, "lt": True, "eq": True, "plus": True, "long": True, "empty": True, "fine": False, "dup": True, "none": True}


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_publish_requires_a_preview_of_the_same_settings():
    run = _SETUP + "st.open = true; await E._publish(); return st.msg"
    r = _run({"status": {"enabled": False}, "run": run})
    assert "請先預覽" in r["v"] and r["bad"] is True
    assert not any("publish" in c for c in r["calls"]), "沒預覽 ⇒ 不送發布"
    run2 = _SETUP + "await E._preview(); st.cols[0].label = '改過'; await E._publish(); return st.msg"
    r2 = _run({"status": {"enabled": False}, "run": run2})
    assert "請先預覽" in r2["v"], "預覽之後又改了設定 ⇒ 要重新預覽"
    assert not any(c.endswith("/publish") for c in r2["calls"])


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_preview_saves_draft_then_renders_then_asks_governance_for_the_hash():
    run = _SETUP + "await E._preview(); return {key: st.previewKey === JSON.stringify(E._toTemplate()), hash: st.previewHash}"
    r = _run({"status": {"enabled": False}, "run": run})
    assert r["v"] == {"key": True, "hash": "e1"}
    order = [c for c in r["calls"] if "/status" not in c]
    assert order == ["PUT /api/definitions/export_template/x%3Ay/draft", "POST /api/export-templates/x%3Ay/preview",
                     "GET /api/def-governance/export_template/x%3Ay/impact"], order
    assert r["state"] == "previewed"


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_normal_publish_says_published_and_reloads():
    run = _SETUP + "await E._preview(); await E._publish(); return st.msg"
    r = _run({"status": {"enabled": False}, "publish": {"version": 2}, "run": run})
    assert r["state"] == "published" and "已發布" in r["msg"] and "待" not in r["msg"]
    assert r["calls"].count("GET /api/definitions/export_template/x%3Ay") >= 1, "發布後重讀（旗標關閉時行為不變）"


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_pending_publish_says_waiting_and_does_not_claim_published():
    pend = {"pending": True, "changeId": 7, "version": 3, "effectiveAt": "2026-10-15T09:30:00", "reasons": ["新增匯出欄位 report", {"message": "第二個原因"}]}
    run = _SETUP + "await E._preview(); const before = (window.__n = 0); await E._publish(); return st.msg"
    r = _run({"status": {"enabled": False}, "publish": pend, "run": run})
    assert r["state"] == "pending" and r["bad"] is False
    assert "已送出發布，待第二位最高管理者核准" in r["msg"] and "核准前不會生效" in r["msg"]
    assert "2026-10-15 09:30" in r["msg"] and "新增匯出欄位 report；第二個原因" in r["msg"]
    assert "已發布" not in r["msg"]
    assert r["calls"].count("GET /api/definitions/export_template/x%3Ay") == 0, "待核准：匯出設定沒有變，不重讀"


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_pending_false_or_missing_is_treated_as_published():
    run = _SETUP + "await E._preview(); await E._publish(); return st.msg"
    r = _run({"status": {"enabled": False}, "publish": {"pending": False}, "run": run})
    assert r["state"] == "published"


@pytest.mark.skipif(NODE is None, reason="沒有 node")
@pytest.mark.parametrize("code", ["preview_required", "preview_stale"])
def test_server_side_preview_gate_is_explained_in_plain_words(code):
    run = _SETUP + "await E._preview(); await E._publish(); return st.msg"
    r = _run({"status": {"enabled": False}, "publishStatus": 409, "publish": {"detail": "x", "code": code}, "run": run})
    assert r["state"] == "error" and "必須先看過" in r["msg"] and r["bad"] is True


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_locked_labels_and_print_text_for_an_xlsx_export():
    cat = dict(_CAT, formats=["xlsx"], lockLabels=True, caps={"xlsx": ["footer", "header"]})
    run = ("const E = window.MotrixExportEditor, st = E._state; E._init(%s); " % json.dumps(cat)) + """
      st.cols = [{id:'b',label:'被改的名字',on:true},{id:'a',label:'甲',on:true}]
      st.header = '  外包名冊 '; st.footer = '請勿外流'
      const t1 = E._toTemplate(), p1 = E._problems()
      st.header = 'a&b'; const p2 = E._problems()
      st.header = ''; st.footer = ''
      return {t1, p1, p2, t2: E._toTemplate()}"""
    r = _run({"status": {"enabled": False}, "run": run})["v"]
    assert r["t1"] == {"version": 1, "format": "xlsx", "columns": [{"id": "b", "label": "乙"}, {"id": "a", "label": "甲"}],
                       "header": {"text": "外包名冊"}, "footer": {"text": "請勿外流"}}, "標題鎖定：一律用目錄標題；頁首頁尾去頭尾空白"
    assert r["p1"] == [] and r["p2"] and "header" not in r["t2"] and "footer" not in r["t2"]


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_pdf_decor_only_editor_has_no_columns_and_checks_the_watermark_words():
    cat = dict(_CAT, formats=["pdf"], columns=[], decorOnly=True, caps={"pdf": ["footer", "watermark"]})
    run = ("const E = window.MotrixExportEditor, st = E._state; E._init(%s); " % json.dumps(cat)) + """
      const none = E._problems()
      st.footer = ' 內部資料 '; st.watermark = '內部使用'
      const ok = E._problems(), t = E._toTemplate()
      st.watermark = '已 核准'; const bad = E._problems()
      st.watermark = 'x'.repeat(41); const long = E._problems()
      return {none, ok, t, bad, long}"""
    r = _run({"status": {"enabled": False}, "run": run})["v"]
    assert r["none"] and "至少" in r["none"][0], "至少要設定一項"
    assert r["ok"] == [] and r["t"] == {"version": 1, "format": "pdf", "footer": {"text": "內部資料"}, "watermark": {"text": "內部使用"}}, "沒有 columns 鍵"
    assert r["bad"] and "官方狀態" in r["bad"][0]
    assert r["long"]


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_export_guard_sends_nothing_when_off_and_never_blocks_when_on():
    guard = Path(__file__).resolve().parents[3] / "frontend" / "static" / "export-guard.js"
    h = r"""
    const fs = require('fs'); global.window = global
    global.localStorage = { getItem: () => JSON.stringify({ token: 'tok' }) }
    const sent = []
    const mode = process.argv[1], audit = process.argv[2] === 'on'
    if (audit) window.MOTRIX_EXPORT_AUDIT = true
    global.fetch = (url, o) => {
      sent.push([url, o.method, o.headers.Authorization, o.body])
      if (mode === 'net') return Promise.reject(new Error('down'))
      if (mode === 'throw') throw new Error('sync boom')
      return Promise.resolve({ status: mode === '429' ? 429 : mode === '500' ? 500 : 200, json: async () => ({}) })
    }
    eval(fs.readFileSync(process.argv[3], 'utf8'))
    window.MotrixExport.guard('parts', 7.9).then(v => setTimeout(() => console.log(JSON.stringify({ v, sent })), 20))
    """
    def go(mode, audit):
        out = subprocess.run([NODE, "-e", h, mode, audit, str(guard)], capture_output=True, timeout=30)
        assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[:800]
        return json.loads(out.stdout.decode("utf-8"))
    off = go("200", "off")
    assert off["v"] is True and off["sent"] == [], "旗標關（沒有 exportAudit）⇒ 完全不發請求，行為與今天相同"
    on = go("200", "on")
    assert on["v"] is True and on["sent"][0][0] == "/api/exports/client-log" and on["sent"][0][2] == "Bearer tok"
    assert json.loads(on["sent"][0][3]) == {"name": "parts", "rows": 7}
    for mode in ("429", "500", "net", "throw"):
        assert go(mode, "on")["v"] is True, "任何回應或錯誤都不擋匯出（%s）" % mode
