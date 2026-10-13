# -*- coding: utf-8 -*-
"""T60 S2 接口：選單編輯器（menu-editor.js）如實顯示「待核准」。

治理旗標（builder_governance.enabled）開啟時，放寬的發布可能回 `{pending: true, changeId, effectiveAt, reasons, version}`。
這時不能說「已發布」，也不重讀選單（選單沒有變）。旗標關閉時後端不回 pending ⇒ 行為與以前相同（說已發布、重讀）。
node 以假 DOM／假 fetch 驅動 doPublish：①一般回應 ②待核准 ③混合（一個直接發布、一個待核准）。
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

EDITOR = Path(__file__).resolve().parents[3] / "frontend" / "static" / "menu-editor.js"
NODE = shutil.which("node")

_HARNESS = r"""
const fs = require('fs')
function mk() { return { setAttribute() {}, appendChild() {}, addEventListener() {}, remove() {}, querySelector() { return null }, textContent: '', style: {} } }
global.document = { createElement: mk, getElementById: () => null, head: mk(), body: mk() }
global.localStorage = { getItem: () => null }
global.window = global
const calls = []
const publishResp = JSON.parse(process.argv[2])          // 每個模組依序的 publish 回應
let pubN = 0
global.fetch = async (url, opt) => {
  const m = (opt && opt.method) || 'GET'
  calls.push(m + ' ' + url.split('?')[0])
  let body = {}
  if (m === 'PUT') body = { etag: 'e1' }
  else if (m === 'POST' && /publish/.test(url)) body = publishResp[pubN++] || {}
  else if (m === 'GET' && /platform\/menu/.test(url)) body = { groups: [] }
  return { ok: true, status: 200, json: async () => body }
}
eval(fs.readFileSync(process.argv[1], 'utf8'))
const E = window.MotrixMenuEditor, st = E._state
st.decl = [{ key: 'g', label: 'G', items: [{ module: 'ma', href: 'a.html', label: 'A' }, { module: 'mb', href: 'b.html', label: 'B' }] }]
const A = 'ma:a.html/sidebar', B = 'mb:b.html/sidebar'
st.base = { [A]: { id: A, group: 'g', label: 'A', module: 'ma' }, [B]: { id: B, group: 'g', label: 'B', module: 'mb' } }
st.work = { [A]: { label: 'A2', hidden: false }, [B]: { label: 'B2', hidden: false } }
st.order = { g: [A, B] }
st.mods = { ma: { ops: [], etag: '' }, mb: { ops: [], etag: '' } }
st.preview = { user: 'x', role: 'superadmin', current: [], preview: [], skipped: [] }
st.previewKey = JSON.stringify(E._buildOps())
;(async () => {
  await E._publish()
  await new Promise(r => setTimeout(r, 50))
  console.log(JSON.stringify({ msg: st.msg, state: st.state, bad: st.msgBad, reloaded: calls.filter(c => c === 'GET /api/platform/menu').length, calls }))
})().catch(e => { console.error(String(e)); process.exit(1) })
"""


def _run(resp):
    out = subprocess.run([NODE, "-e", _HARNESS, str(EDITOR), json.dumps(resp)], capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[:1500]
    return json.loads(out.stdout.decode("utf-8"))


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_normal_publish_says_published_and_reloads():
    r = _run([{"version": 3}, {"version": 2}])
    assert r["state"] == "published" and "已發布（2 個模組" in r["msg"] and "待" not in r["msg"]
    assert r["reloaded"] >= 1, "一般發布後重讀選單資料（旗標關閉時行為不變）"


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_pending_publish_says_waiting_and_does_not_reload_or_claim_published():
    pend = {"pending": True, "changeId": 7, "version": 4, "effectiveAt": "2026-10-15T09:30:00", "reasons": ["放寬可見範圍", {"message": "第二個原因"}]}
    r = _run([pend, pend])
    assert r["state"] == "pending" and r["bad"] is False
    assert "已送出發布" in r["msg"] and "待第二位最高管理者核准" in r["msg"] and "核准前不會生效" in r["msg"]
    assert "2026-10-15 09:30" in r["msg"] and "放寬可見範圍；第二個原因" in r["msg"]
    assert "已發布（" not in r["msg"]
    assert r["reloaded"] == 0, "待核准：選單沒有變，不重讀"


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_mixed_pending_and_direct_says_both_honestly():
    r = _run([{"version": 3}, {"pending": True, "changeId": 8, "version": 2, "reasons": ["r"]}])
    assert r["state"] == "pending" and "1 個模組的版面）" in r["msg"] and "另有 1 個模組已直接發布" in r["msg"]
    assert r["reloaded"] == 0


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_pending_false_or_missing_is_treated_as_published():
    r = _run([{"pending": False}, {}])
    assert r["state"] == "published" and "已發布（2 個模組" in r["msg"]
