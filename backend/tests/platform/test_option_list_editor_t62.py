# -*- coding: utf-8 -*-
"""census #4：選項清單編輯器（frontend/static/option-list-editor.js）以 node 假 DOM／假 fetch 驅動。
①轉換（順序、停用、不能改名的清單用原字、前綴）與前端驗證  ②發布前一定要先預覽同一份  ③待核准如實說  ④伺服端要求預覽雜湊 ⇒ 白話提示
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

EDITOR = Path(__file__).resolve().parents[3] / "frontend" / "static" / "option-list-editor.js"
NODE = shutil.which("node")

_HARNESS = r"""
const fs = require('fs')
const appended = []
function mk(tag) { const n = { tag, children: [], attrs: {}, setAttribute(k, v) { this.attrs[k] = v }, appendChild(c) { this.children.push(c); appended.push(c); return c }, removeChild(c) { this.children = this.children.filter(x => x !== c) },
  get firstChild() { return this.children[0] || null }, addEventListener() {}, remove() {}, textContent: '', style: {} }; return n }
global.document = { createElement: mk, getElementById: () => null, body: mk('body'), querySelector: () => null }
global.localStorage = { getItem: () => JSON.stringify({ token: 't' }) }
global.window = global
window.MOTRIX_OPTION_LIST_IDS = 'customer_type'
const calls = []
const scen = JSON.parse(process.argv[1])
global.fetch = async (url, opt) => {
  const m = (opt && opt.method) || 'GET', path = url.split('?')[0]
  calls.push(m + ' ' + path)
  let status = 200, body = {}
  if (/\/status$/.test(path)) body = scen.meta
  else if (m === 'GET' && /api\/definitions\/option_list/.test(path)) body = { draft: null, latest: null, versions: [] }
  else if (m === 'PUT') body = { etag: 'e1' }
  else if (/\/preview$/.test(path)) body = { values: [], added: [], warnings: [] }
  else if (/\/impact$/.test(path)) body = { previewHash: 'e1' }
  else if (/\/publish$/.test(path)) { status = scen.publishStatus || 200; body = scen.publish || {} }
  return { ok: status < 400, status, json: async () => body }
}
eval(fs.readFileSync(process.argv[2], 'utf8'))
;(async () => {
  await new Promise(r => setTimeout(r, 20))
  const E = window.MotrixOptionListEditor, st = E._state
  const out = { drawn: appended.length }
  if (scen.run) await eval('(async () => {' + scen.run + '})()').then(v => { out.v = v })
  out.calls = calls; out.msg = st.msg; out.state = st.state; out.bad = st.msgBad
  console.log(JSON.stringify(out))
})().catch(e => { console.error(String(e && e.stack || e)); process.exit(1) })
"""
_META = {"enabled": True, "canEdit": True, "label": "客戶類型", "relabel": True, "prefix": False, "usedBy": ["客戶管理頁"], "defaults": [], "current": []}


def _run(scen):
    out = subprocess.run([NODE, "-e", _HARNESS, json.dumps(scen), str(EDITOR)], capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[:1500]
    return json.loads(out.stdout.decode("utf-8"))


def _setup(meta):
    return "const E = window.MotrixOptionListEditor, st = E._state; E._init(%s, [{value:'一般',label:'一般客戶',disabled:false,prefix:''},{value:'VIP',label:'VIP 客戶',disabled:true,prefix:''}], {'一般':true,'VIP':true}); " % json.dumps(meta)


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_body_conversion_and_front_end_validation():
    run = _setup(_META) + """
      const b1 = E._toBody(), p1 = E._problems()
      st.items.push({ value: '新', label: '新', disabled: false, prefix: '' }); const p2 = E._problems()
      st.items.push({ value: '=x', label: 'y', disabled: false, prefix: '' }); const p3 = E._problems()
      return { b1, p1, p2n: p2.length, p3 }"""
    r = _run({"meta": {"enabled": False}, "run": run})["v"]
    assert r["b1"] == {"version": 1, "values": [{"value": "一般", "label": "一般客戶"}, {"value": "VIP", "label": "VIP 客戶", "disabled": True}]}
    assert r["p1"] == [] and r["p2n"] == 0 and r["p3"] and "= + - @" in "".join(r["p3"])


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_lists_that_cannot_be_relabelled_send_the_value_as_label_and_prefix_is_required():
    meta = dict(_META, relabel=False, prefix=True)
    run = _setup(meta) + """
      st.items = [{ value: '網通設備', label: '被改的', disabled: false, prefix: 'NET' }, { value: '新', label: '新', disabled: false, prefix: 'net' }]
      const p = E._problems(); st.items[1].prefix = 'NET'; const dup = E._problems(); st.items[1].prefix = 'SRV'
      return { body: E._toBody(), bad: p, dup, ok: E._problems() }"""
    r = _run({"meta": {"enabled": False}, "run": run})["v"]
    assert r["body"]["values"][0] == {"value": "網通設備", "label": "網通設備", "prefix": "NET"}, "不能改名的清單：label 一律等於 value"
    assert any("前綴" in x for x in r["bad"]) and any("重複" in x for x in r["dup"]) and r["ok"] == []


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_publish_requires_preview_then_says_published_or_pending_honestly():
    base = _setup(_META)
    r = _run({"meta": {"enabled": False}, "run": base + "st.open = true; await E._publish(); return st.msg"})
    assert "請先預覽" in r["v"] and not any(c.endswith("/publish") for c in r["calls"])
    ok = _run({"meta": {"enabled": False}, "publish": {"version": 2}, "run": base + "await E._preview(); await E._publish(); return st.msg"})
    assert ok["state"] == "published" and "已發布" in ok["msg"]
    order = [c for c in ok["calls"] if "/status" not in c]
    assert order[:3] == ["PUT /api/definitions/option_list/customer_type/draft", "POST /api/option-lists/customer_type/preview", "GET /api/def-governance/option_list/customer_type/impact"]
    pend = {"pending": True, "changeId": 3, "effectiveAt": "2026-10-15T09:30:00", "reasons": ["原因甲"]}
    p = _run({"meta": {"enabled": False}, "publish": pend, "run": base + "await E._preview(); await E._publish(); return st.msg"})
    assert p["state"] == "pending" and "待第二位最高管理者核准" in p["msg"] and "2026-10-15 09:30" in p["msg"] and "已發布" not in p["msg"]
    for code in ("preview_required", "preview_stale"):
        g = _run({"meta": {"enabled": False}, "publishStatus": 409, "publish": {"detail": "x", "code": code}, "run": base + "await E._preview(); await E._publish(); return st.msg"})
        assert g["state"] == "error" and "必須先看過" in g["msg"]
