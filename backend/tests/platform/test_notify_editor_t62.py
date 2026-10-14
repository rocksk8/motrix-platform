# -*- coding: utf-8 -*-
"""S-X3：簽核通知用語編輯器（frontend/static/notify-editor.js）以 node 假 DOM／假 fetch 驅動。

①旗標關／不是最高管理者 ⇒ 什麼都不畫，只多一個 status GET  ②前端驗證與後端 `_text_problems` 同判斷（逐案例對照）
③全部留空 ⇒ 發布等於預設字的範本；只填的才進範本  ④檢查不過 ⇒ 不送任何請求  ⑤取消影響預覽 ⇒ 不發布
⑥待核准 ⇒ 如實說待核准、不說已發布  ⑦一般發布 ⇒ 帶預覽雜湊、說已發布並重讀  ⑧不用 innerHTML／原生對話框
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from helpers import notify_templates as NT

ROOT = Path(__file__).resolve().parents[3]
EDITOR = ROOT / "frontend" / "static" / "notify-editor.js"
PAGE = ROOT / "frontend" / "pages" / "approval-settings.html"
NODE = shutil.which("node")
KEY = "approval:submitted"
DEF = "approval%3Asubmitted"


def _cat():
    ev = NT.EVENTS[KEY]
    return {"enabled": True, "canEdit": True, "event": KEY, "label": ev["label"], "sample": ev["sample"],
            "fields": [{"field": p, "label": s["label"], "default": s["default"], "limit": s["limit"],
                        "placeholders": list(s["placeholders"]), "need": list(s["need"])} for p, s in ev["fields"].items()]}


_HARNESS = r"""
const fs = require('fs')
const appended = []
function mk(tag) { const n = { tag, children: [], attrs: {}, setAttribute(k, v) { this.attrs[k] = v }, appendChild(c) { this.children.push(c); appended.push(c); return c }, removeChild(c) { this.children = this.children.filter(x => x !== c) },
  get firstChild() { return this.children[0] || null }, addEventListener() {}, remove() {}, querySelector() { return null }, querySelectorAll() { return [] }, textContent: '', style: {} }; return n }
global.document = { createElement: mk, getElementById: () => null, body: mk('body') }
global.localStorage = { getItem: () => JSON.stringify({ token: 't' }) }
global.window = global
const calls = [], bodies = {}
const scen = JSON.parse(process.argv[1])
window.MotrixDefGovernance = { review: async () => scen.review === undefined ? 'hash1' : scen.review }
global.fetch = async (url, opt) => {
  const m = (opt && opt.method) || 'GET'
  const path = url.split('?')[0]
  calls.push(m + ' ' + path)
  if (opt && opt.body) bodies[m + ' ' + path] = JSON.parse(opt.body)
  let status = 200, body = {}
  if (/\/status$/.test(path)) body = scen.status
  else if (m === 'GET' && /api\/definitions\/notify_template/.test(path)) body = { draft: null, latest: null, versions: [] }
  else if (m === 'PUT') body = { etag: 'e1' }
  else if (/\/preview$/.test(path)) body = { rows: [] }
  else if (/\/publish$/.test(path)) { status = scen.publishStatus || 200; body = scen.publish || {} }
  return { ok: status < 400, status, json: async () => body }
}
eval(fs.readFileSync(process.argv[2], 'utf8'))
;(async () => {
  const E = window.MotrixNotifyEditor, st = E._state
  if (scen.start) { E.start(); await new Promise(r => setTimeout(r, 20)) }
  const out = { drawn: appended.length }
  if (scen.run) await eval('(async () => {' + scen.run + '})()').then(v => { out.v = v })
  out.calls = calls; out.bodies = bodies; out.msg = st.msg; out.state = st.state; out.bad = st.msgBad
  console.log(JSON.stringify(out))
})().catch(e => { console.error(String(e && e.stack || e)); process.exit(1) })
"""


def _run(scen):
    out = subprocess.run([NODE, "-e", _HARNESS, json.dumps(scen), str(EDITOR)], capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[:1500]
    return json.loads(out.stdout.decode("utf-8"))


_SETUP = "const E = window.MotrixNotifyEditor, st = E._state; E._init(%s); " % json.dumps(_cat())
pytestmark = pytest.mark.skipif(NODE is None, reason="沒有 node")


@pytest.mark.parametrize("status", [{"enabled": False, "canEdit": False}, {"enabled": True, "canEdit": False}])
def test_nothing_is_drawn_when_off_or_not_superadmin(status):
    r = _run({"status": status, "start": True})
    assert r["drawn"] == 0
    assert r["calls"] == ["GET /api/notify-templates/%s/status" % DEF]


def test_draws_when_on_and_superadmin():
    assert _run({"status": _cat(), "start": True})["drawn"] >= 1


_CASES = ["請審核 {單號}", "{單號}", "沒有單號", "{單號}{標記}（{對象}）", "{金額} {單號}", "<b>{單號}</b>", "{單號} https://x.example", "{單號}​",
          "{單號} 已 核 准", "{單號} {", "{單號 }", "{單號}" + "字" * 120, "{單號} 已簽核完成", "{單號} A&B", "{單號} 'x'", "{單號} bit.ly/x", "{單號} a/b", "{單號} 已通過", "{單號} 批准", "{單號} 审核通过", "{單號} Final", "{單號} finally", "{單號} unpaid", "{單號} ａｐｐｒｏｖｅｄ", "{單號} v1.0", "請盡快 {單號}\\"]


def test_client_validation_matches_server_for_the_inapp_message():
    r = _run({"status": _cat(), "run": _SETUP + "return " + json.dumps(_CASES) + ".map(t => !!E._problemOf('inapp.message', t))"})
    spec = NT.EVENTS[KEY]["fields"]["inapp.message"]
    server = [bool(NT._text_problems(t, spec)) for t in _CASES]
    assert r["v"] == server, list(zip(_CASES, r["v"], server))


def test_client_validation_matches_server_for_each_other_field():
    for path, spec in NT.EVENTS[KEY]["fields"].items():
        texts = ["正常文字", "含 {單號}", "含 {對象}", "x" * (spec["limit"] + 1), "<i>x</i>", "已核准通知", "{未知}"]
        r = _run({"status": _cat(), "run": _SETUP + "return " + json.dumps(texts) + ".map(t => !!E._problemOf(%s, t))" % json.dumps(path)})
        server = [bool(NT._text_problems(t, spec)) for t in texts]
        assert r["v"] == server, (path, list(zip(texts, r["v"], server)))


def test_template_conversion_blank_means_defaults_and_filled_means_only_filled():
    r = _run({"status": _cat(), "run": _SETUP + "const a = E._toTemplate(); st.vals['mail.badge'] = '請處理'; return [a, E._toTemplate()]"})
    blank, one = r["v"]
    assert blank == NT.default_template(KEY) and NT.definition_problems(KEY, blank) == []
    assert one == {"version": 1, "mail": {"badge": "請處理"}} and NT.definition_problems(KEY, one) == []


def test_invalid_input_is_reported_and_publish_sends_nothing():
    r = _run({"status": _cat(), "run": _SETUP + "st.vals['inapp.message'] = '沒有單號'; await E.publish(); return E._problems()"})
    assert r["v"] and "必須包含 {單號}" in r["v"][0]
    assert r["calls"] == [] and r["state"] == "error"


def test_review_cancel_pending_and_normal_publish():
    pub = _SETUP + "st.vals['mail.badge'] = '請處理'; st.open = true; await E.publish(); return 1"
    # 取消影響預覽 ⇒ 不發布
    r = _run({"status": _cat(), "review": None, "run": pub})
    assert not any(c.startswith("POST") and c.endswith("/publish") for c in r["calls"])
    assert r["bodies"]["PUT /api/definitions/notify_template/%s/draft" % DEF]["body"] == {"version": 1, "mail": {"badge": "請處理"}}
    assert any(c.endswith("/preview") for c in r["calls"])
    # 待核准：如實說，不說已發布
    r = _run({"status": _cat(), "publish": {"pending": True, "reasons": ["新增自訂用語 mail.badge（收件人看到的字，需核准）"]}, "run": pub})
    assert r["state"] == "pending" and "待第二位最高管理者核准" in r["msg"] and "已發布。" not in r["msg"]
    # 一般發布：帶預覽雜湊並重讀
    r = _run({"status": _cat(), "publish": {"ok": True}, "run": pub})
    assert r["state"] == "published" and "已發布" in r["msg"]
    assert r["bodies"]["POST /api/definitions/notify_template/%s/publish" % DEF]["preview_hash"] == "hash1"
    assert r["calls"].count("GET /api/definitions/notify_template/%s" % DEF) == 1, "發布後重讀（測試起點沒有先載入，所以只有這一次）"


def test_source_hygiene_and_page_wiring():
    js = EDITOR.read_text(encoding="utf-8")
    assert "innerHTML" not in js and "outerHTML" not in js and "insertAdjacentHTML" not in js
    assert not re.search(r"\b(alert|confirm|prompt)\s*\(", js)
    page = PAGE.read_text(encoding="utf-8")
    assert 'id="notify-editor-mount"' in page and "MotrixPublicFlags.read(['builder_notify']" in page
    assert "notify-editor.js" in page and "s.role !== 'superadmin'" in page
    assert '<script src="../static/notify-editor.js"' not in page, "只能在旗標開啟時動態載入"
