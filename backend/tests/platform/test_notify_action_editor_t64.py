# -*- coding: utf-8 -*-
"""T64 BP-4 S5：額外通知編輯器（frontend/static/notify-action-editor.js）以 node 假 DOM／假 fetch 驅動。

①旗標關／不是最高管理者 ⇒ 什麼都不畫，只多一個 status GET  ②清單、新增、一鍵建議內容、收件人挑選器、條件、通道、節流
③前端檢查與後端 `_text_problems` 同判斷（逐案例對照）④試跑：命中、約幾個人、每天幾則、逐角色文字、放寬警告（紅框＋原因）
⑤發布：存草稿 → 後端檢查 → 影響預覽（取消 ⇒ 不發布）→ 發布；待核准如實說；一鍵停用  ⑥畫面不出現代號／列舉值／內部鍵
⑦不用 innerHTML／原生對話框  ⑧頁面有掛載點與載入器。
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from helpers import notify_actions as NA
from helpers import notify_templates as NT

ROOT = Path(__file__).resolve().parents[3]
EDITOR = ROOT / "frontend" / "static" / "notify-action-editor.js"
from core import source_tree      # noqa: E402
PAGE = source_tree.page_file("approval-settings.html")
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="沒有 node")

PICKER = {"roles": [{"value": r, "label": NA.ROLE_LABELS[r]} for r in ("superadmin", "admin", "sales", "engineer", "viewer", "finance")],
          "groups": [{"value": g, "label": NA.GROUP_LABELS[g]} for g in ("admins", "superadmins", "finance")],
          "people": [{"value": k, "label": v} for k, v in NA.PEOPLE_LABELS.items()],
          "users": [{"username": "u_wang", "displayName": "王小明"}, {"username": "u_lee", "displayName": "李大華"}]}


def _status(enabled=True, can_edit=True):
    if not enabled or not can_edit:
        return {"enabled": enabled, "canEdit": can_edit}
    return {"enabled": True, "canEdit": True, "events": NA.event_catalog(), "caps": dict(NA.CAPS), "picker": PICKER}


PREVIEW_LOOSEN = {
    "event": "completion_note.state_changed", "matches": True, "conditions": [], "recipients": [{"kind": "owner", "value": None, "count": None}, {"kind": "role", "value": "admin", "count": 3}],
    "knownRecipientCount": 3, "eventDependentRecipients": 1, "overCap": 0, "estimate": {"last30DaysSent": 60, "perDay": 2.0},
    "classification": {"class": "loosen", "reasons": ["新增通知動作（有人會開始收到額外通知）"]},
    "renders": [{"role": r, "roleName": NA.ROLE_LABELS[r], "title": "T-" + r, "body": "B-" + r} for r in ("superadmin", "admin", "sales", "engineer", "viewer", "finance")],
    "warnings": ["試跑不寄信、不寫通知、不發事件。"], "readable": "未檢查：試跑用的不是真實單據"}

_HARNESS = r"""
const fs = require('fs')
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.handlers = {}; this._text = ''; this.style = {}; this.parent = null }
  setAttribute(k, v) { this.attrs[k] = String(v) }
  getAttribute(k) { return this.attrs[k] === undefined ? null : this.attrs[k] }
  appendChild(c) { c.parent = this; this.children.push(c); return c }
  removeChild(c) { this.children = this.children.filter(x => x !== c); return c }
  get firstChild() { return this.children[0] || null }
  addEventListener(ev, fn) { (this.handlers[ev] = this.handlers[ev] || []).push(fn) }
  set textContent(v) { this._text = String(v) }
  get textContent() { return this._text + this.children.map(c => c.textContent).join('') }
  get value() { return this._value !== undefined ? this._value : (this.attrs.value || this._text || '') }
  set value(v) { this._value = v }
  focus() {} setSelectionRange() {} remove() {}
  walk(fn) { fn(this); this.children.forEach(c => c.walk(fn)) }
  all(pred) { const out = []; this.walk(n => { if (pred(n)) out.push(n) }); return out }
  matches(sel) {
    const m = /^\[([a-z-]+)="([^"]*)"\]$/.exec(sel); if (m) return this.attrs[m[1]] === m[2]
    return false
  }
  querySelector(sel) { return this.all(n => n !== this && n.matches(sel))[0] || null }
  querySelectorAll(sel) { return this.all(n => n !== this && n.matches(sel)) }
}
global.document = { createElement: t => new Node(t), getElementById: id => id === 'notify-action-editor-mount' ? MOUNT : null, body: new Node('body') }
const MOUNT = new Node('div')
global.localStorage = { getItem: () => JSON.stringify({ token: 't' }) }
global.window = global
const calls = [], bodies = {}
const scen = JSON.parse(process.argv[1])
window.MotrixDefGovernance = { review: async () => scen.review === undefined ? 'hash1' : scen.review, open: (o) => { window.__opened = o } }
let reviewCalls = 0
global.fetch = async (url, opt) => {
  const m = (opt && opt.method) || 'GET'
  const path = url.split('?')[0]
  calls.push(m + ' ' + path)
  if (opt && opt.body) bodies[m + ' ' + path] = JSON.parse(opt.body)
  let status = 200, body = {}
  if (/api\/notify-actions\/status$/.test(path)) body = scen.status
  else if (/api\/notify-actions\/[^/]+\/preview$/.test(path)) { status = scen.previewStatus || 200; body = scen.preview || {} }
  else if (m === 'GET' && /api\/definitions\/notify_action$/.test(path)) body = scen.list || []
  else if (m === 'GET' && /api\/definitions\/notify_action\//.test(path)) { const k = decodeURIComponent(path.split('/').pop()); body = (scen.defs || {})[k] || { draft: null, latest: null } }
  else if (m === 'PUT') body = { etag: 'e1' }
  else if (/\/publish$/.test(path)) { status = scen.publishStatus || 200; body = scen.publish || {} }
  return { ok: status < 400, status, json: async () => body }
}
eval(fs.readFileSync(process.argv[2], 'utf8'))
const E = window.MotrixNotifyActionEditor
const R = () => E._root()
const byRole = (role) => R().all(n => n.attrs['data-role'] === role)
const click = (role, i) => { const n = byRole(role)[i || 0]; if (!n) throw new Error('沒有按鈕 ' + role); (n.handlers.click || []).forEach(f => f({ target: n })) }
const change = (node, v) => { (node.handlers.change || []).forEach(f => f({ target: { value: v, checked: v === true } })) }
const input = (node, v) => { (node.handlers.input || []).forEach(f => f({ target: { value: v } })) }
const allText = () => R().textContent
const optionTexts = () => R().all(n => n.tag === 'option').map(n => n.textContent)
const sleep = (ms) => new Promise(r => setTimeout(r, ms))
;(async () => {
  const st = E._state
  if (scen.start) { E.start(); await sleep(20) }
  const out = { drawn: !!R() && R().children.length > 0 }
  if (scen.run) await eval('(async () => {' + scen.run + '})()').then(v => { out.v = v })
  out.calls = calls; out.bodies = bodies; out.msg = st.msg; out.state = st.state; out.bad = st.msgBad
  console.log(JSON.stringify(out))
})().catch(e => { console.error(String(e && e.stack || e)); process.exit(1) })
"""


def _run(scen):
    out = subprocess.run([NODE, "-e", _HARNESS, json.dumps(scen), str(EDITOR)], capture_output=True, timeout=60)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[:2000]
    return json.loads(out.stdout.decode("utf-8"))


_SETUP = "E._init(%s); E._render(); " % json.dumps({"events": NA.event_catalog(), "picker": PICKER, "caps": dict(NA.CAPS)})
_EV = "completion_note.state_changed"
_OPEN_NEW = _SETUP + "E._startNew(); const sel = byRole('event')[0]; change(sel, '%s'); " % _EV
_FILL = _OPEN_NEW + "click('suggest'); "


# ── ① 旗標關／不是最高管理者 ──────────────────────────────────────────────────
@pytest.mark.parametrize("status", [{"enabled": False, "canEdit": False}, {"enabled": True, "canEdit": False}])
def test_nothing_is_drawn_when_off_or_not_superadmin(status):
    r = _run({"status": status, "start": True})
    assert r["drawn"] is False and r["calls"] == ["GET /api/notify-actions/status"]


def test_draws_a_collapsed_toggle_when_on_and_superadmin():
    r = _run({"status": _status(), "start": True, "run": "return [byRole('toggle').length, byRole('form').length, allText()]"})
    assert r["drawn"] is True and r["calls"] == ["GET /api/notify-actions/status"], "收合時不多打請求"
    assert r["v"][0] == 1 and r["v"][1] == 0 and "額外通知" in r["v"][2]


# ── ② 清單與表單 ─────────────────────────────────────────────────────────────
def test_list_shows_names_events_and_status_in_plain_chinese_and_empty_hint():
    defs = {"na_aaa": {"draft": None, "latest": {"body": {"version": 1, "label": "完工單送審通知", "enabled": True, "event": _EV, "when": [], "channels": ["in_app"],
                                                         "recipients": [{"kind": "owner"}], "template": {"title": "t", "body": "b"}, "throttle": {"dedupeMinutes": 60, "maxPerRecipientPerDay": 5}}}},
            "na_bbb": {"draft": {"body": {"label": "還沒發布的草稿", "event": "case.deadline_near"}, "etag": "e9"}, "latest": None}}
    r = _run({"status": _status(), "list": [{"key": "na_aaa"}, {"key": "na_bbb"}], "defs": defs,
              "run": _SETUP + "st_ = E._state; await E._loadList(); return [byRole('item').length, allText()]"})
    n, text = r["v"]
    assert n == 2 and "完工單送審通知" in text and "使用中" in text and "還沒發布" in text and "當「完工單狀態改變」時通知" in text and "當「案件階段即將到期」時通知" in text
    assert "na_aaa" not in text and "na_bbb" not in text, "內部代號不可顯示"
    r = _run({"status": _status(), "list": [], "run": _SETUP + "await E._loadList(); return allText()"})
    assert "還沒有額外通知" in r["v"]


def test_one_click_suggestion_fills_a_valid_definition_and_matches_the_backend():
    r = _run({"status": _status(), "run": _FILL + "return [E._problems(E._state.f), E._toBody(E._state.f)]"})
    problems, body = r["v"]
    assert problems == []
    sg = NA.EVENTS[_EV]["suggest"]
    assert body["template"] == {"title": sg["title"], "body": sg["body"]} and body["recipients"] == sg["recipients"] and body["channels"] == ["in_app"]
    assert body["throttle"] == {"dedupeMinutes": 60, "maxPerRecipientPerDay": 5} and body["enabled"] is True and body["when"] == [] and body["version"] == 1
    assert NA.definition_problems("na_ok1", body) == [], "前端組出來的定義必須通過後端驗證"


def test_recipient_picker_offers_only_the_catalogue_with_plain_labels():
    r = _run({"status": _status(), "run": _OPEN_NEW + "return optionTexts()"})
    texts = r["v"]
    joined = "\n".join(texts)
    for want in ("事件裡的人：操作人／申請人", "事件裡的人：案件負責業務", "角色：業務（所有人）", "角色：最高管理者（所有人）", "群組：財務角色與最高管理者", "指定人員：王小明", "指定人員：李大華"):
        assert want in joined, want
    for raw in ("superadmin", "u_wang", "role:", "group:", "requester", "owner"):
        assert raw not in joined, raw
    # 自訂模組事件沒有案件負責業務
    r = _run({"status": _status(), "run": _SETUP + "E._startNew(); change(byRole('event')[0], 'custom_module.transitioned'); return optionTexts()"})
    assert "事件裡的人：案件負責業務" not in "\n".join(r["v"]) and "事件裡的人：操作人／申請人" in "\n".join(r["v"])


def test_adding_recipients_shows_chips_in_plain_chinese_and_enforces_limits():
    r = _run({"status": _status(), "run": _OPEN_NEW + "E._addRecipient('role:sales'); E._addRecipient('group:finance'); E._addRecipient('user:u_wang'); E._addRecipient('owner:'); E._addRecipient('role:sales');"
              "const chips = byRole('chip').map(c => c.textContent); const f = E._state.f; return [chips, f.recipients]"})
    chips, recs = r["v"]
    assert len(chips) == 4 and len(recs) == 4, "重複的不重複加入"
    text = " ".join(chips)
    assert "角色「業務」的所有人" in text and "群組「財務角色與最高管理者」" in text and "指定人員：王小明" in text and "案件負責業務" in text
    r = _run({"status": _status(), "run": _OPEN_NEW + "for (let i = 0; i < 12; i++) E._addRecipient('role:' + ['admin','sales','engineer','viewer','finance','superadmin'][i % 6]); "
              "E._addRecipient('user:u_wang'); E._addRecipient('user:u_lee'); E._addRecipient('group:admins'); return E._state.f.recipients.length"})
    assert r["v"] == 8


def test_switching_event_drops_recipients_the_new_event_cannot_provide_and_says_so():
    r = _run({"status": _status(), "run": _FILL + "change(byRole('event')[0], 'custom_module.transitioned'); return [E._state.f.recipients, E._state.msg]"})
    recs, msg = r["v"]
    assert recs == [] and "案件負責業務" in msg and "換了事件" in msg


def test_conditions_email_channel_and_throttle_round_trip_into_the_body():
    r = _run({"status": _status(), "run": _FILL + "const f = E._state.f; f.when.push({field: '新狀態', values: '待審核、已核准'}); f.email = true; f.dedupe = '30'; f.perDay = '3'; f.enabled = false; return [E._toBody(f), E._problems(f)]"})
    body, problems = r["v"]
    assert problems == [] and body["when"] == [{"field": "新狀態", "in": ["待審核", "已核准"]}] and body["channels"] == ["in_app", "email"]
    assert body["throttle"] == {"dedupeMinutes": 30, "maxPerRecipientPerDay": 3} and body["enabled"] is False
    assert NA.definition_problems("na_ok2", body) == []
    # 反向：定義 → 表單
    r = _run({"status": _status(), "run": _SETUP + "const f = E._fromBody('na_x', %s); return [f.when, f.email, f.recipients, f.dedupe]" % json.dumps(body)})
    assert r["v"][0] == [{"field": "新狀態", "values": "待審核、已核准"}] and r["v"][1] is True and r["v"][3] == 30


@pytest.mark.parametrize("mut,frag", [
    ("f.label = ''", "名稱"),
    ("f.recipients = []", "至少加入一位"),
    ("f.title = '看 http://x.example'", "標題"),
    ("f.body = '{金額} 元'", "不認得的占位符"),
    ("f.body = '已核准的單'", "官方狀態字樣"),
    ("f.dedupe = '0'", "分鐘"),
    ("f.perDay = '21'", "每人每天"),
    ("f.when.push({field: '', values: ''})", "還沒選欄位"),
    ("f.when.push({field: '新狀態', values: ''})", "1～10 個值"),
])
def test_client_side_problems_are_plain_chinese(mut, frag):
    r = _run({"status": _status(), "run": _FILL + "const f = E._state.f; %s; return E._problems(f)" % mut})
    assert any(frag in p for p in r["v"]), r["v"]


_TEXTS = ["正常文字", "{單號} 有事", "{完工單號}", "{未知}", "<b>x</b>", "網址 https://x.example", "a/b", "已核准", "A&B", "'x'", "{單號", "x" * 61, "", "   ", "bit.ly 連結", "approved", "核 准"]


def test_client_text_rules_match_the_server_for_title_and_body():
    ev = NA.EVENTS[_EV]
    allowed = [p for p in ev["ph"] if p not in ev["internal"]]
    for field, limit in (("title", 60), ("body", 400)):
        r = _run({"status": _status(), "run": _SETUP + "return %s.map(t => !!E._textProblem(t, %d, %s))" % (json.dumps(_TEXTS), limit, json.dumps(allowed))})
        server = [bool(NA.NT._text_problems(t, {"default": None, "limit": limit, "placeholders": tuple(allowed), "need": (), "allow_status": False})) for t in _TEXTS]
        assert r["v"] == server, list(zip(_TEXTS, r["v"], server))


# ── ④ 試跑 ───────────────────────────────────────────────────────────────────
def test_preview_posts_the_draft_and_shows_impact_loosen_box_and_per_role_text():
    r = _run({"status": _status(), "preview": PREVIEW_LOOSEN,
              "run": _FILL + "await E._preview(); return [allText(), byRole('loosen').length, byRole('impact')[0].textContent, byRole('recipients')[0].textContent, byRole('pv-title')[0].textContent]"})
    text, loosen, impact, recs, title = r["v"]
    post = [c for c in r["calls"] if c.endswith("/preview")]
    assert len(post) == 1 and post[0].startswith("POST /api/notify-actions/na_")
    body = r["bodies"][post[0]]["template"]
    assert body["event"] == _EV and body["version"] == 1
    assert loosen == 1 and "放寬" in text and "第二位最高管理者核准" in text and "新增通知動作" in text, "放寬要有紅框、原因與範圍"
    assert "預計會通知約 3 人" in impact and "另有 1 項" in impact and "每天寄出約 2 則" in impact
    assert "角色「管理員」的所有人：3 人" in recs and "案件負責業務：依實際發生的事而定" in recs
    assert title == "T-admin"
    # 切換角色
    r = _run({"status": _status(), "preview": PREVIEW_LOOSEN,
              "run": _FILL + "await E._preview(); const b = byRole('role-tabs')[0].children.filter(c => c.attrs['data-render-role'] === 'sales')[0]; (b.handlers.click || []).forEach(f => f({})); return byRole('pv-title')[0].textContent"})
    assert r["v"] == "T-sales"
    tight = dict(PREVIEW_LOOSEN, classification={"class": "tighten", "reasons": ["停用"]})
    r = _run({"status": _status(), "preview": tight, "run": _FILL + "await E._preview(); return [byRole('loosen').length, byRole('tighten')[0].textContent]"})
    assert r["v"][0] == 0 and "立即生效" in r["v"][1]


def test_preview_with_invalid_input_sends_nothing_and_backend_422_is_plain():
    r = _run({"status": _status(), "run": _OPEN_NEW + "await E._preview(); return E._state.msg"})
    assert r["calls"] == [] and "名稱" in r["v"]
    r = _run({"status": _status(), "previewStatus": 422, "preview": {"detail": {"problems": [{"path": "recipients[0].value", "message": "必須是現有的啟用帳號"}]}},
              "run": _FILL + "await E._preview(); return E._state.msg"})
    assert "必須是現有的啟用帳號" in r["v"] and "recipients" not in r["v"], "不顯示欄位路徑"


# ── ⑤ 發布 ───────────────────────────────────────────────────────────────────
def test_publish_flow_saves_draft_checks_reviews_then_publishes_with_the_preview_hash():
    r = _run({"status": _status(), "preview": PREVIEW_LOOSEN, "publish": {"pending": False}, "list": [], "run": _FILL + "await E.publish(); return E._state.state"})
    c = r["calls"]
    key = [x for x in c if x.startswith("PUT ")][0].split("/")[-2]
    assert c.index("PUT /api/definitions/notify_action/%s/draft" % key) < c.index("POST /api/notify-actions/%s/preview" % key) < c.index("POST /api/definitions/notify_action/%s/publish" % key)
    assert r["bodies"]["POST /api/definitions/notify_action/%s/publish" % key]["preview_hash"] == "hash1"
    assert r["v"] == "published" and "已發布" in r["msg"]


def test_review_cancel_sends_no_publish():
    r = _run({"status": _status(), "preview": PREVIEW_LOOSEN, "review": None, "run": _FILL + "await E.publish(); return E._state.state"})
    assert not any(c.endswith("/publish") for c in r["calls"]) and "已取消發布" in r["msg"]


def test_pending_response_is_reported_honestly():
    r = _run({"status": _status(), "preview": PREVIEW_LOOSEN, "publish": {"pending": True, "reasons": ["新增通知動作（有人會開始收到額外通知）"], "effectiveAt": "2026-10-20T09:00:00"},
              "run": _FILL + "await E.publish(); return E._state.state"})
    assert r["v"] == "pending" and "待第二位最高管理者核准" in r["msg"] and "核准前不會生效" in r["msg"] and "已發布。" not in r["msg"]


def test_preview_required_error_is_explained():
    r = _run({"status": _status(), "preview": PREVIEW_LOOSEN, "publishStatus": 409, "publish": {"code": "preview_required", "detail": "發布前必須先看過影響預覽"},
              "run": _FILL + "await E.publish(); return E._state.state"})
    assert r["v"] == "error" and "影響預覽" in r["msg"]


def test_one_click_disable_publishes_enabled_false_for_a_live_action():
    live = {"version": 1, "label": "完工單送審通知", "enabled": True, "event": _EV, "when": [], "channels": ["in_app"], "recipients": [{"kind": "owner"}],
            "template": {"title": "完工單 {完工單號}", "body": "{原狀態} 到 {新狀態}"}, "throttle": {"dedupeMinutes": 60, "maxPerRecipientPerDay": 5}}
    r = _run({"status": _status(), "preview": dict(PREVIEW_LOOSEN, classification={"class": "tighten", "reasons": ["停用"]}), "list": [{"key": "na_live"}],
              "defs": {"na_live": {"draft": None, "latest": {"body": live}}}, "publish": {},
              "run": _SETUP + "await E._loadList(); click('disable'); await new Promise(r => setTimeout(r, 50)); return E._state.state"})
    assert r["bodies"]["PUT /api/definitions/notify_action/na_live/draft"]["body"]["enabled"] is False
    assert any(c == "POST /api/definitions/notify_action/na_live/publish" for c in r["calls"])


def test_versions_and_restore_open_the_governance_panel_for_that_action():
    live = {"version": 1, "label": "甲", "enabled": True, "event": _EV, "when": [], "channels": ["in_app"], "recipients": [{"kind": "owner"}],
            "template": {"title": "t {單號}", "body": "b"}, "throttle": {"dedupeMinutes": 60, "maxPerRecipientPerDay": 5}}
    r = _run({"status": _status(), "list": [{"key": "na_live"}], "defs": {"na_live": {"draft": None, "latest": {"body": live}}},
              "run": _SETUP + "await E._loadList(); const b = R().all(n => n.tag === 'button' && n.textContent === '版本與還原')[0]; (b.handlers.click || []).forEach(f => f({})); return [window.__opened.kind, window.__opened.key, window.__opened.title]"})
    assert r["v"][0] == "notify_action" and r["v"][1] == "na_live" and "版本與還原" in r["v"][2]


# ── ⑥ 白話：畫面不出現代號／列舉值／內部鍵 ────────────────────────────────────
RAW = ("completion_note", "custom_module", "case.deadline", "in_app", "requester", "owner", "role:", "group:", "superadmin", "u_wang", "u_lee", "na_", "dedupeMinutes",
       "maxPerRecipientPerDay", "notify_action", "recipients", "undefined", "null", "[object", "NaN")


def test_no_raw_codes_in_the_rendered_form_or_preview():
    run = _FILL + "E._addRecipient('role:admin'); E._addRecipient('group:finance'); E._addRecipient('user:u_wang'); E._state.f.email = true; E._state.f.when.push({field: '新狀態', values: '已核准'}); E._render(); await E._preview(); return allText() + ' ' + optionTexts().join(' ')"
    r = _run({"status": _status(), "preview": PREVIEW_LOOSEN, "run": run})
    text = r["v"]
    for raw in RAW:
        assert raw not in text, raw
    assert "放寬" in text and "預計會通知約" in text


def test_no_raw_codes_for_every_event_form():
    for ev in NA.EVENTS:
        r = _run({"status": _status(), "run": _SETUP + "E._startNew(); change(byRole('event')[0], '%s'); click('suggest'); return allText() + ' ' + optionTexts().join(' ')" % ev})
        for raw in RAW:
            assert raw not in r["v"], (ev, raw)


# ── ⑦ 不用 innerHTML／原生對話框 ───────────────────────────────────────────────
def test_source_uses_no_innerhtml_or_native_dialogs():
    src = EDITOR.read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "alert(", "confirm(", "prompt(", "eval(", "new Function"):
        assert bad not in code, bad


# ── ⑧ 頁面載入器 ─────────────────────────────────────────────────────────────
def test_page_has_the_mount_and_loads_the_editor_only_behind_the_flag():
    html = PAGE.read_text(encoding="utf-8")
    assert 'id="notify-action-editor-mount"' in html and "notify-action-editor.js" in html
    assert html.index("builder_notify") < html.index("notify-action-editor.js")
    assert html.count("notify-action-editor.js") == 1 and "MotrixNotifyActionEditor.start()" in html
    assert "<script src=\"../static/notify-action-editor.js\"" not in html, "只能在旗標開啟後由載入器載入"
