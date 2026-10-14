# -*- coding: utf-8 -*-
"""S-ST2：階段樣板編輯器（frontend/static/stage-template-editor.js）以 node 假 DOM／假 fetch 驅動。
①轉換與前端驗證（比例合計 100%、全有或全無、鍵格式、前置階段）  ②發布前一定要先預覽同一份  ③待核准如實說  ④載入時惰性（不送請求）
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

EDITOR = Path(__file__).resolve().parents[3] / "frontend" / "static" / "stage-template-editor.js"
NODE = shutil.which("node")

_HARNESS = r"""
const fs = require('fs')
function mk(tag) { return { tag, children: [], attrs: {}, style: {}, setAttribute(k, v) { this.attrs[k] = v }, appendChild(c) { this.children.push(c); return c },
  removeChild(c) { this.children = this.children.filter(x => x !== c) }, get firstChild() { return this.children[0] || null }, addEventListener() {}, textContent: '' } }
global.document = { createElement: mk, getElementById: () => null, body: mk('body'), querySelector: () => null }
global.localStorage = { getItem: () => JSON.stringify({ token: 't' }) }
global.window = global
const calls = []
const scen = JSON.parse(process.argv[1])
global.fetch = async (url, opt) => {
  const m = (opt && opt.method) || 'GET', path = url.split('?')[0]
  calls.push(m + ' ' + path)
  let status = 200, body = {}
  if (m === 'PUT') body = { etag: 'e1' }
  else if (/stage-templates\/preview$/.test(path)) body = { stages: [], notes: [] }
  else if (/\/impact$/.test(path)) body = { previewHash: 'h1', classification: 'neutral', reasons: [] }
  else if (/\/publish$/.test(path)) { status = scen.publishStatus || 200; body = scen.publish || {} }
  return { ok: status < 400, status, json: async () => body }
}
const before = calls.length
eval(fs.readFileSync(process.argv[2], 'utf8'))
;(async () => {
  await new Promise(r => setTimeout(r, 20))
  const E = window.MotrixStageTemplateEditor, st = E._state
  const out = { loadCalls: before === calls.length ? calls.length : -1 }
  if (scen.run) await eval('(async () => {' + scen.run + '})()').then(v => { out.v = v })
  out.calls = calls; out.msg = st.msg; out.state = st.state; out.bad = st.msgBad
  console.log(JSON.stringify(out))
})().catch(e => { console.error(String(e && e.stack || e)); process.exit(1) })
"""
_BODY = {"label": "標準施工案", "stages": [
    {"key": "survey", "label": "現場勘查", "offsetDays": 0, "durationDays": 3, "ratioBp": 3000, "dependsOn": []},
    {"key": "install", "label": "設備安裝", "offsetDays": 3, "durationDays": 14, "ratioBp": 7000, "dependsOn": ["survey"]}]}


def _run(scen):
    out = subprocess.run([NODE, "-e", _HARNESS, json.dumps(scen), str(EDITOR)], capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[:1500]
    return json.loads(out.stdout.decode("utf-8"))


def _setup():
    return "const E = window.MotrixStageTemplateEditor, st = E._state; E._init(%s, {survey:true,install:true}); st.key = 'std'; " % json.dumps(_BODY)


pytestmark = pytest.mark.skipif(NODE is None, reason="沒有 node")


def test_loading_is_inert_no_requests():
    r = _run({})
    assert r["calls"] == [] and r["loadCalls"] == 0


def test_body_conversion_and_ratio_rules():
    run = _setup() + """
      const b1 = E._toBody(), p1 = E._problems()
      st.stages[1].ratioPct = 60; const p2 = E._problems()
      st.useRatio = false; const b3 = E._toBody(), p3 = E._problems()
      st.stages[0].key = 'Bad Key'; const p4 = E._problems()
      return { b1, p1, p2, b3, p3, p4 }"""
    r = _run({"run": run})["v"]
    assert r["b1"]["stages"][0]["ratioBp"] == 3000 and r["b1"]["stages"][1]["ratioBp"] == 7000 and r["b1"]["version"] == 1
    assert r["p1"] == []
    assert any("合計必須剛好 100%" in x for x in r["p2"])
    assert all("ratioBp" not in s for s in r["b3"]["stages"]) and r["p3"] == []          # 不設比例 ⇒ 不送這個鍵
    assert any("種類鍵" in x for x in r["p4"])


def test_publish_requires_preview_of_the_same_template_and_sends_hash():
    run = _setup() + """
      await E._publish(); const blocked = st.msg
      await E._preview(); const ok = st.state
      st.label = '改過'; await E._publish(); const stale = st.msg
      return { blocked, ok, stale }"""
    r = _run({"run": run})
    assert "請先預覽" in r["v"]["blocked"] and r["v"]["ok"] == "previewed" and "請先預覽" in r["v"]["stale"]
    assert not any(c.startswith("POST") and c.endswith("/publish") for c in r["calls"])   # 沒預覽或預覽過期 ⇒ 沒有發布請求


def test_publish_pending_is_reported_as_pending():
    run = _setup() + "await E._preview(); await E._publish(); return st.state"
    r = _run({"publish": {"pending": True, "reasons": ["移除階段"]}, "run": run})
    assert r["v"] == "pending" and "待第二位最高管理者核准" in r["msg"] and "移除階段" in r["msg"]
    assert any(c.endswith("/publish") for c in r["calls"])
