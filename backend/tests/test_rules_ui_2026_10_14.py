# -*- coding: utf-8 -*-
"""BP-2 R4 前端證據（node 直接執行 rules-builder.js 與 rule-marks.js，不開瀏覽器；沒有真瀏覽器可用，這組測試就是證據）。
規則面板：
- 旗標關（config 404）⇒ available=false；開面板前什麼都不渲染；列出規則時條件白話、名稱轉義
- 改門檻 ⇒ 去抖後以『目前這份草稿』呼叫預覽；預覽結果顯示筆數、新增／取消、收緊或放寬；預覽失敗 ⇒ 如實顯示、不留舊結果
- 發布一定經治理面板的預覽（帶回 preview_hash）；沒有治理面板 ⇒ 不發布；放寬回 pending ⇒ 畫面不說「已發布」
- 刪除兩段式確認；全程不用原生 confirm／alert
標示疊加層：
- 頁面沒有登記／伺服器 404 ⇒ 不加任何屬性、不裝觀察器、不插樣式；開啟 ⇒ 只加 data-rule-mark／title（不動 class／style），多條取最醒目，沒有標示的列會被清乾淨"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "frontend" / "js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(not NODE, reason="需要 node")

BUILDER_HARNESS = r"""
const fs = require('fs')
const inp = JSON.parse(process.argv[2])
const els = {}
function mk(tag) { return { tag, id: '', attrs: {}, innerHTML: '', textContent: '', listeners: {}, setAttribute(k, v) { this.attrs[k] = v }, getAttribute(k) { return this.attrs[k] },
  addEventListener(t, f) { this.listeners[t] = f }, remove() { delete els[this.id] }, appendChild(c) { els[c.id] = c } } }
global.window = {}
global.localStorage = { getItem: () => JSON.stringify(Object.assign({ token: 'tok', role: 'superadmin' }, inp.session || {})) }
global.location = { pathname: inp.path || '/pages/other.html' }
global.document = { readyState: 'complete', addEventListener() {}, createElement: mk, getElementById: (i) => els[i] || null, head: { appendChild(c) { els[c.id] = c } }, body: { appendChild(c) { els[c.id] = c } } }
const calls = []
const queues = {}
global.fetch = async (url, o) => {
  const method = (o && o.method) || 'GET'
  calls.push({ url, method, body: o && o.body ? JSON.parse(o.body) : null })
  const key = Object.keys(inp.routes).find(k => { const [m, u] = k.split(' '); return m === method && url.indexOf(u) >= 0 })
  let r = key ? inp.routes[key] : { status: 404, body: {} }
  if (Array.isArray(r)) { queues[key] = queues[key] || r.slice(); r = queues[key].length > 1 ? queues[key].shift() : queues[key][0] }
  return { ok: r.status < 400, status: r.status, json: async () => r.body }
}
global.window.confirm = global.confirm = global.alert = global.window.alert = () => { throw new Error('native dialog used') }
if (inp.governance !== undefined) window.MotrixDefGovernance = { review: async (o) => { window.__reviewArg = o; return inp.governance } }
;(0, eval)(fs.readFileSync(process.argv[3], 'utf8'))
const B = window.MotrixRulesBuilder
const P = () => els['rb-panel']
const click = (act) => P().listeners.click({ target: { closest: () => ({ getAttribute: () => act }) } })
const input = (key, value, i, checked) => P().listeners.input({ target: { getAttribute: (k) => k === 'data-rb-in' ? key : k === 'data-i' ? (i == null ? null : String(i)) : null, value, checked } })
const sleep = (ms) => new Promise(r => setTimeout(r, ms))
;(async () => {
  const out = { snaps: [] }
  for (const s of inp.steps) {
    if (s.do === 'available') out.available = await B.available()
    if (s.do === 'panel') out.panelExists = !!P()
    if (s.do === 'open') await B.open(s.opts)
    if (s.do === 'click') await click(s.act)
    if (s.do === 'input') await input(s.key, s.value, s.i, s.checked)
    if (s.do === 'sleep') await sleep(s.ms)
    if (s.do === 'mount') B.mountEntry()
    if (s.do === 'btn') out.btn = els['rb-btn'] ? { text: els['rb-btn'].textContent, id: els['rb-btn'].id } : null
    if (s.do === 'snap') out.snaps.push({ html: P() ? P().innerHTML : '', state: P() ? P().attrs['data-state'] : null })
  }
  out.calls = calls; out.review = window.__reviewArg || null; out.rules = B._state() ? B._state().rules : null
  console.log(JSON.stringify(out))
})()
"""

CONFIG = {"status": 200, "body": {"entities": [{"key": "case", "label": "案件（報價單）", "sourceAvailable": True, "fields": [
    {"id": "netMarginPct", "label": "營業利益率", "type": "number", "unit": "%", "ops": ["lt", "le", "gt", "ge", "eq", "ne", "between", "empty", "not_empty"]},
    {"id": "status", "label": "狀態", "type": "text", "unit": "", "ops": ["eq", "ne", "in", "empty", "not_empty"]}]}],
    "levels": ["red", "yellow", "info"], "limits": {"nodes": 200}}}


def rule(rid="low_margin", name="低毛利", value=15, op="lt", level="red"):
    return {"id": rid, "name": name, "enabled": True, "mode": "mark", "on_failure": "degrade_loud",
            "when": {"op": op, "field": "netMarginPct", "value": value}, "mark": {"level": level, "text": "毛利偏低", "target": "row"}}


DEF = {"status": 200, "body": {"draft": None, "latest": {"version": 2, "body": {"rules": [rule()]}}, "versions": []}}
PREVIEW_OK = {"status": 200, "body": {"entity": "case", "available": True, "sampled": 50, "published": {"records": 2, "hits": {}}, "draft": {"records": 5, "hits": {}},
              "added": 3, "removed": 0, "direction": "tighten", "reasons": ["規則「低毛利」的條件放大了（會標示更多紀錄）"], "degraded": [], "notApplicable": [],
              "samples": [{"id": "Q1", "label": "Q1 甲案", "ruleIds": ["low_margin"], "isNew": True, "values": {}}], "note": "依最近 50 筆估算（不是全部紀錄）"}}


def routes(**over):
    base = {"GET /api/rules/config": CONFIG, "GET /api/rules/summary": {"status": 200, "body": {"available": True, "hits": {"low_margin": 4}}},
            "GET /api/definitions/rule_set/case": DEF, "POST /api/rules/preview": PREVIEW_OK,
            "PUT /api/definitions/rule_set/case/draft": {"status": 200, "body": {"etag": "e1"}},
            "POST /api/definitions/rule_set/case/publish": {"status": 200, "body": {"version": 3}}}
    base.update(over)
    return base


def run(steps, r=None, governance=None, path=None, session=None):
    inp = {"steps": steps, "routes": r or routes(), "path": path, "session": session}
    if governance is not None:
        inp["governance"] = governance if governance != "none" else None
    out = subprocess.run([NODE, "-e", BUILDER_HARNESS, "x", json.dumps(inp), str(JS / "rules-builder.js")], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


OPEN = {"do": "open", "opts": {"entity": "case"}}


@needs_node
@pytest.mark.parametrize("status,expected", [(404, False), (401, False), (403, False), (200, True)])
def test_available_only_when_the_config_route_answers(status, expected):
    r = run([{"do": "available"}], routes(**{"GET /api/rules/config": {"status": status, "body": {}}}))
    assert r["available"] is expected and r["calls"][0]["method"] == "GET" and r["calls"][0]["url"] == "/api/rules/config"


@needs_node
def test_nothing_renders_before_open_and_the_list_shows_plain_language():
    assert run([{"do": "panel"}])["panelExists"] is False
    r = run([OPEN, {"do": "sleep", "ms": 50}, {"do": "snap"}])                                 # 命中數是開面板後另外載入的
    h = r["snaps"][0]["html"]
    assert "營業利益率 低於 15%" in h and "低毛利" in h and "目前命中 4 筆" in h and "已發布第 2 版" in h
    assert "規則只做標示" in h


@needs_node
def test_rule_names_are_escaped():
    d = {"status": 200, "body": {"draft": None, "latest": {"version": 1, "body": {"rules": [rule(name="<img src=x onerror=alert(1)>")]}}}}
    h = run([OPEN, {"do": "snap"}], routes(**{"GET /api/definitions/rule_set/case": d}))["snaps"][0]["html"]
    assert "<img" not in h and "&lt;img" in h


@needs_node
def test_editing_the_threshold_previews_the_current_draft_after_a_debounce():
    r = run([OPEN, {"do": "click", "act": "edit:0"}, {"do": "input", "key": "value", "value": "20"}, {"do": "input", "key": "value", "value": "25"},
             {"do": "sleep", "ms": 700}, {"do": "snap"}])
    pv = [c for c in r["calls"] if c["url"] == "/api/rules/preview"]
    assert len(pv) == 1 and pv[0]["method"] == "POST"                                          # 連續輸入只送一次
    assert pv[0]["body"]["entity"] == "case" and pv[0]["body"]["body"]["rules"][0]["when"]["value"] == 25      # 送的是目前這份草稿（數字，不是字串）
    h = r["snaps"][0]["html"]
    assert "目前已發布會標示 <b>2</b> 筆 → 套用後 <b>5</b> 筆（新增 3、取消 0）" in h and "標示變多（收緊，立即生效）" in h
    assert "Q1 甲案" in h and "新增" in h and "依最近 50 筆估算" in h and r["snaps"][0]["state"] == "ready"
    assert "未儲存的修改" in h


@needs_node
def test_preview_failure_is_shown_and_no_stale_result_is_kept():
    bad = {"status": 422, "body": {"detail": {"problems": [{"path": "x", "message": "門檻必須是數字"}]}}}
    r = run([OPEN, {"do": "click", "act": "edit:0"}, {"do": "input", "key": "value", "value": "20"}, {"do": "sleep", "ms": 600}, {"do": "snap"},
             {"do": "input", "key": "value", "value": "abc"}, {"do": "sleep", "ms": 600}, {"do": "snap"}],
            routes(**{"POST /api/rules/preview": [PREVIEW_OK, bad]}))
    assert 'data-rb-preview="ok"' in r["snaps"][0]["html"]
    assert 'data-rb-preview="error"' in r["snaps"][1]["html"] and "門檻必須是數字" in r["snaps"][1]["html"] and "套用後" not in r["snaps"][1]["html"]
    assert r["snaps"][1]["state"] == "error"


@needs_node
def test_publish_goes_through_the_governance_review_and_sends_its_hash():
    r = run([OPEN, {"do": "click", "act": "edit:0"}, {"do": "input", "key": "value", "value": "25"}, {"do": "click", "act": "publish"}, {"do": "snap"}], governance="H123")
    kinds = [(c["method"], c["url"].split("?")[0]) for c in r["calls"]]
    assert ("PUT", "/api/definitions/rule_set/case/draft") in kinds                              # 先存草稿
    pub = [c for c in r["calls"] if c["url"].startswith("/api/definitions/rule_set/case/publish")][0]
    assert pub["body"]["preview_hash"] == "H123" and r["review"]["kind"] == "rule_set" and r["review"]["key"] == "case"
    assert kinds.index(("PUT", "/api/definitions/rule_set/case/draft")) < kinds.index(("POST", "/api/definitions/rule_set/case/publish"))
    assert "已發布第 3 版" in r["snaps"][0]["html"] and r["snaps"][0]["state"] == "published"


@needs_node
def test_cancelled_review_does_not_publish():
    r = run([OPEN, {"do": "click", "act": "publish"}, {"do": "snap"}], governance="none")
    assert not [c for c in r["calls"] if "/publish" in c["url"]] and "已取消發布" in r["snaps"][0]["html"]


@needs_node
def test_without_the_governance_panel_nothing_is_published():
    r = run([OPEN, {"do": "click", "act": "publish"}, {"do": "snap"}])
    assert not [c for c in r["calls"] if "/publish" in c["url"] or c["method"] == "PUT"]
    assert "無法發布" in r["snaps"][0]["html"] and r["snaps"][0]["state"] == "error"


@needs_node
def test_a_loosening_publish_is_reported_as_pending_not_published():
    pend = {"status": 200, "body": {"pending": True, "version": 3, "status": "submitted", "effectiveAt": "2026-10-21T10:00:00", "reasons": ["規則「低毛利」的條件縮小了"], "changeId": 9}}
    r = run([OPEN, {"do": "click", "act": "publish"}, {"do": "snap"}], routes(**{"POST /api/definitions/rule_set/case/publish": pend}), governance="H1")
    h = r["snaps"][0]["html"]
    assert "待第二位最高管理者核准；核准前不會生效" in h and "2026-10-21 10:00" in h and "規則「低毛利」的條件縮小了" in h
    assert "已發布" not in h.replace("已發布第 2 版", "") and r["snaps"][0]["state"] == "pending"


@needs_node
def test_publish_failure_shows_the_server_reason():
    bad = {"status": 409, "body": {"detail": "發布前必須先看過影響預覽", "code": "preview_required"}}
    r = run([OPEN, {"do": "click", "act": "publish"}, {"do": "snap"}], routes(**{"POST /api/definitions/rule_set/case/publish": bad}), governance="H1")
    assert "發布前必須先看過影響預覽" in r["snaps"][0]["html"] and r["snaps"][0]["state"] == "error"


@needs_node
def test_delete_needs_two_clicks_and_add_creates_a_valid_default_rule():
    r = run([OPEN, {"do": "click", "act": "del:0"}, {"do": "snap"}, {"do": "click", "act": "del-no"}, {"do": "snap"},
             {"do": "click", "act": "del:0"}, {"do": "click", "act": "del-yes:0"}, {"do": "snap"}, {"do": "click", "act": "add"}])
    assert "刪除？" in r["snaps"][0]["html"] and "刪除？" not in r["snaps"][1]["html"] and "低毛利" in r["snaps"][1]["html"]
    assert "還沒有規則" in r["snaps"][2]["html"]
    n = r["rules"][0]
    assert n["id"] == "rule_1" and n["mode"] == "mark" and n["on_failure"] == "degrade_loud" and n["when"] == {"op": "lt", "field": "netMarginPct", "value": 0}


@needs_node
def test_compound_conditions_are_shown_but_not_editable():
    comp = rule()
    comp["when"] = {"op": "and", "args": [{"op": "lt", "field": "netMarginPct", "value": 5}, {"op": "eq", "field": "status", "value": "草稿"}]}
    d = {"status": 200, "body": {"draft": None, "latest": {"version": 1, "body": {"rules": [comp]}}}}
    r = run([OPEN, {"do": "click", "act": "edit:0"}, {"do": "snap"}], routes(**{"GET /api/definitions/rule_set/case": d}))
    h = r["snaps"][0]["html"]
    assert "進階條件（且／或／非）" in h and "不能編輯條件" in h and 'data-rb-in="field"' not in h


@needs_node
def test_changing_field_or_operator_resets_the_value_to_a_valid_default():
    r = run([OPEN, {"do": "click", "act": "edit:0"}, {"do": "input", "key": "op", "value": "between"}, {"do": "snap"},
             {"do": "input", "key": "field", "value": "status"}])
    assert r["rules"][0]["when"] == {"op": "eq", "field": "status", "value": "值"}


@needs_node
def test_entry_button_only_for_superadmin_on_a_declared_page_with_the_flag_on():
    inert = run([{"do": "sleep", "ms": 30}, {"do": "btn"}], path="/pages/case-management.html")
    assert inert["btn"] is None and inert["calls"] == []                                          # 只載入、沒人呼叫 mountEntry ⇒ 完全惰性（旗標關時頁面就是這個狀態）
    r = run([{"do": "mount"}, {"do": "sleep", "ms": 30}, {"do": "btn"}], path="/pages/case-management.html")
    assert r["btn"] == {"text": "標示規則", "id": "rb-btn"} and r["calls"][0]["url"] == "/api/rules/config"
    off = run([{"do": "mount"}, {"do": "sleep", "ms": 30}, {"do": "btn"}], routes(**{"GET /api/rules/config": {"status": 404, "body": {}}}), path="/pages/case-management.html")
    assert off["btn"] is None and len(off["calls"]) == 1                                         # 旗標關：只有一次探測，沒有按鈕
    other_page = run([{"do": "mount"}, {"do": "sleep", "ms": 30}, {"do": "btn"}], path="/pages/suppliers.html")
    assert other_page["btn"] is None and other_page["calls"] == []                               # 沒宣告的頁面：連探測都不送
    not_admin = run([{"do": "mount"}, {"do": "sleep", "ms": 30}, {"do": "btn"}], path="/pages/case-management.html", session={"role": "sales"})
    assert not_admin["btn"] is None and not_admin["calls"] == []                                 # 非最高管理者：連探測都不送


# ── 標示疊加層 ─────────────────────────────────────────────────────────────────
MARKS_HARNESS = r"""
const fs = require('fs')
const inp = JSON.parse(process.argv[2])
function el(id) { return { attrs: { 'data-quote-no': id }, sets: [], setAttribute(k, v) { this.attrs[k] = v; this.sets.push(k) }, getAttribute(k) { return this.attrs[k] == null ? null : this.attrs[k] },
  hasAttribute(k) { return this.attrs[k] != null }, removeAttribute(k) { delete this.attrs[k] } } }
const items = inp.ids.map(el)
const nodes = {}
global.window = {}
global.localStorage = { getItem: () => (inp.token === false ? null : JSON.stringify({ token: 'tok' })) }
global.location = { pathname: inp.path }
let observers = 0, styles = 0
global.MutationObserver = function (cb) { this.observe = () => { observers++ }; this.disconnect = () => { observers-- } }
global.document = { readyState: 'complete', documentElement: { attrs: {}, setAttribute(k, v) { this.attrs[k] = v } }, head: { appendChild(c) { styles++; nodes[c.id] = c } },
  body: { appendChild(c) { nodes[c.id] = c; c.remove = () => { delete nodes[c.id] } } }, getElementById: (i) => nodes[i] || null,
  createElement: (t) => ({ tag: t, id: '', textContent: '', remove() {} }), querySelectorAll: () => items, addEventListener() {} }
const calls = []
global.fetch = async (url) => { calls.push(url); const r = inp.responses.shift() || inp.last; return { ok: r.status < 400, status: r.status, json: async () => r.body } }
global.setTimeout = (f) => { f(); return 1 }; global.clearTimeout = () => {}
;(0, eval)(fs.readFileSync(process.argv[3], 'utf8'))
setTimeout2 = new Promise(r => setImmediate(r))
;(async () => {
  if (!inp.inert) window.MotrixRuleMarks.start()
  await setTimeout2; await new Promise(r => setImmediate(r)); await new Promise(r => setImmediate(r))
  console.log(JSON.stringify({ calls, observers, styles, state: document.documentElement.attrs['data-rule-marks-state'] || null,
    items: items.map(i => ({ attrs: i.attrs, sets: i.sets })), degraded: nodes['rm-degraded'] ? nodes['rm-degraded'].textContent : null }))
})()
"""


def marks_run(path, ids, responses, last=None, token=True, inert=False):
    inp = {"path": path, "ids": ids, "responses": responses, "last": last or {"status": 404, "body": {}}, "token": token, "inert": inert}
    out = subprocess.run([NODE, "-e", MARKS_HARNESS, "x", json.dumps(inp), str(JS / "rule-marks.js")], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


PROBE_OK = {"status": 200, "body": {"entity": "case", "marks": {}, "degraded": False}}


@needs_node
def test_loading_the_overlay_without_start_is_completely_inert():
    r = marks_run("/pages/case-management.html", ["Q1"], [PROBE_OK], inert=True)
    assert r["calls"] == [] and r["observers"] == 0 and r["styles"] == 0 and r["items"][0]["sets"] == [] and r["state"] is None


def test_case_page_starts_rules_only_after_reading_the_flag_from_its_existing_settings_request():
    html = (ROOT / "frontend" / "pages" / "case-management.html").read_text(encoding="utf-8")
    assert "MotrixPublicFlags.read(['builder_layout', 'builder_rules']" in html                 # 同一個設定請求多帶一個群組，沒有新請求（網址由 public-flags.js 組成）
    assert "../static/public-flags.js" in html
    gate = re.search(r"builder_rules\.enabled === 1\) \{([\s\S]*?)\n {6}\}", html).group(1)
    assert "MotrixRuleMarks.start()" in gate and "MotrixRulesBuilder.mountEntry()" in gate
    assert html.count("MotrixRuleMarks.start()") == 1 and html.count("mountEntry()") == 1       # 沒有任何無條件的啟動點
    # 某個群組被隱藏／不存在時整個設定請求會 404：由 public-flags.js 逐組重試，版面編輯器不會因此死掉（讀旗標不再自己 fetch）
    assert "/api/settings-center/public" not in html.split("async initLayout()")[1].split("}))")[0]


@needs_node
def test_pages_not_listed_or_flag_off_leave_the_page_untouched():
    r = marks_run("/pages/other.html", ["Q1"], [])
    assert r["calls"] == [] and r["observers"] == 0 and r["styles"] == 0 and r["items"][0]["sets"] == []
    r = marks_run("/pages/case-management.html", ["Q1"], [{"status": 404, "body": {}}])
    assert len(r["calls"]) == 1 and r["calls"][0].startswith("/api/rules/marks?entity=case") and r["observers"] == 0 and r["styles"] == 0
    assert r["items"][0]["sets"] == [] and r["state"] == "off"
    r = marks_run("/pages/case-management.html", ["Q1"], [], token=False)
    assert r["calls"] == []                                                                    # 沒登入 ⇒ 連探測都不送


@needs_node
def test_marks_are_applied_as_attributes_only_and_the_most_prominent_wins():
    marks = {"Q1": [{"ruleId": "a", "level": "yellow", "text": "尚未送出"}, {"ruleId": "b", "level": "red", "text": "毛利偏低"}], "Q2": [{"ruleId": "a", "level": "info", "text": "留意"}]}
    r = marks_run("/pages/case-management.html", ["Q1", "Q2", "Q3"], [PROBE_OK, {"status": 200, "body": {"entity": "case", "marks": marks, "degraded": False}}])
    q1, q2, q3 = r["items"]
    assert q1["attrs"]["data-rule-mark"] == "red" and q1["attrs"]["title"] == "尚未送出、毛利偏低"
    assert q2["attrs"]["data-rule-mark"] == "info" and "data-rule-mark" not in q3["attrs"]
    for i in r["items"]:
        assert set(i["sets"]) <= {"data-rule-mark", "title", "data-rule-title"}                # 不碰 class／style（Alpine 的 :class／:style 會覆蓋）
    assert r["observers"] == 1 and r["styles"] == 1 and r["state"] == "ready"
    assert "ids=Q1%2CQ2%2CQ3" in r["calls"][1]


@needs_node
def test_degraded_notice_uses_text_content_and_marks_are_cleared_when_gone():
    r = marks_run("/pages/case-management.html", ["Q1"], [PROBE_OK, {"status": 200, "body": {"entity": "case", "marks": {}, "degraded": True}}])
    assert r["degraded"] == "部分提醒暫時無法顯示" and "data-rule-mark" not in r["items"][0]["attrs"]
    assert "innerHTML" not in _code("rule-marks.js")


def _code(name):
    """去掉區塊註解後的原始碼（說明文字裡會提到被禁用的名稱）。"""
    return re.sub(r"/\*[\s\S]*?\*/", "", (JS / name).read_text(encoding="utf-8"))


@needs_node
def test_static_guards_on_both_components():
    for f in ("rules-builder.js", "rule-marks.js"):
        src = _code(f)
        assert not re.search(r"(?<![\w.])(confirm|alert)\(", src), f
        assert not re.search(r"window\.(confirm|alert)", src), f
        assert "eval(" not in src and "new Function" not in src, f
