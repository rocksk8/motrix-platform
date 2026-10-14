# -*- coding: utf-8 -*-
"""T61 S5：自訂欄位的前端（執行時 store、欄位編輯器、案件資訊頁的區塊）——靜態＋node 真的執行。

證明：旗標關閉（讀到 enabled=false 或讀取失敗）頁面什麼都不畫、不掛編輯器；案件頁的取值／設值函式讓
caseRecord.customFields 和伺服器一樣『沒有值就沒有鍵』（存檔基準才對得上）；編輯器的定義 body 只含認得的鍵、不能改已發布欄位的型別、
發布與還原前先在頁內兩段式確認（取消不送請求）、治理待核准如實顯示（不宣稱已發布）；沒有原生對話框。
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
JS = ROOT / "frontend" / "static" / "custom-fields.js"
from core import source_tree   # noqa: E402  頁面路徑一律經 source_tree（守門 test_page_paths_centralized）
PAGE = source_tree.page_file("case-management.html")
NODE = shutil.which("node")
NATIVE = re.compile(r"(?:(?<![\w.$])|(?<=window\.))(alert|confirm|prompt)\s*\(")


def _strip(s):
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", r"\1", line) for line in s.split("\n"))


def _native(text):
    return [m.group(1) for line in _strip(text).split("\n") for m in NATIVE.finditer(line)]


# ── 靜態 ───────────────────────────────────────────────────────────────────
def test_no_native_dialogs_scanner_positive_control():
    assert _native("alert('a'); if (!confirm('b')) return; window.prompt('c'); await this._ask('d')") == ["alert", "confirm", "prompt"]


def test_editor_has_no_native_dialogs():
    assert _native(JS.read_text(encoding="utf-8")) == []


def test_case_page_wiring_is_flag_guarded():
    src = PAGE.read_text(encoding="utf-8")
    assert '<script src="../static/custom-fields.js"></script>' in src
    assert "MotrixCustomFields.init({ recordType: 'case_info'" in src
    i = src.index('<div data-testid="cf-section"')      # C1 起區塊多了 :style 排序綁定，不再是閉合的 '>' 
    before = src[src.rindex("<template", 0, i):i]
    assert "$store.cf && $store.cf.enabled" in before                     # 區塊只在旗標開啟時畫
    sec = src[i:src.index("<!-- 個資蒐集告知（個資法 §8 I", i)]
    for t in ("text", "date", "select", "checkbox"):
        assert "f.type === '%s'" % t in sec
    assert "customFields: '自訂欄位'" in (ROOT / "frontend" / "js" / "case-management-core.js").read_text(encoding="utf-8")


def test_sections_never_show_money_or_number_types():
    sec = JS.read_text(encoding="utf-8")
    assert "['text', '文字'], ['date', '日期'], ['select', '單選'], ['checkbox', '勾選']" in sec
    assert "number" not in sec.split("var TYPES")[1].split("\n")[0]


# ── node：執行時 store ─────────────────────────────────────────────────────
_RT = r"""
const fs = require('fs')
global.window = global
const calls = { fetch: [], appended: 0, style: 0 }
let ROLE = %(role)s
global.localStorage = { getItem() { return JSON.stringify({ token: 't', role: ROLE }) } }
global.document = { addEventListener() {}, getElementById() { return null }, head: { appendChild() { calls.style++ } },
  createElement() { return { innerHTML: '', firstChild: {}, textContent: '', id: '' } },
  body: { appendChild() { calls.appended++ }, classList: { add() {}, remove() {} } } }
let RESP = %(resp)s
global.fetch = async (url) => { calls.fetch.push(String(url)); if (RESP === 'fail') throw new Error('x')
  return { ok: RESP !== 'http', json: async () => RESP } }
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


_INIT = "await window.MotrixCustomFields.init({ recordType: 'case_info', label: '案件資訊' })\n"
_OUT = "console.log(JSON.stringify({ calls, s: { enabled: S.enabled, fields: S.fields, failed: S.failed, list: S.list() } }))"


@pytest.mark.skipif(NODE is None, reason="沒有 node")
@pytest.mark.parametrize("resp", ["{ enabled: false, fields: [] }", "'http'", "'fail'"])
def test_flag_off_or_unreadable_draws_nothing_and_mounts_no_editor(resp):
    """旗標關閉／HTTP 錯誤／斷線：enabled=false、沒有欄位、不掛編輯器；唯一的請求是讀欄位端點。"""
    r = _node(_INIT + "const S = window.MotrixCustomFields._state()\n" + _OUT, resp)
    assert r["s"]["enabled"] is False and r["s"]["fields"] == [] and r["s"]["list"] == []
    assert r["calls"]["appended"] == 0
    assert r["calls"]["fetch"] == ["/api/custom-fields/case_info"]


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_flag_on_loads_fields_and_mounts_editor_only_for_superadmin():
    resp = "{ enabled: true, fields: [{ key: 'f1', label: '工頭', type: 'text' }] }"
    r = _node(_INIT + "const S = window.MotrixCustomFields._state()\n" + _OUT, resp)
    assert r["s"]["enabled"] is True and [f["key"] for f in r["s"]["list"]] == ["f1"]
    assert r["calls"]["appended"] == 1                                   # 超級管理員：編輯器掛上
    r = _node(_INIT + "const S = window.MotrixCustomFields._state()\n" + _OUT, resp, role="'sales'")
    assert r["s"]["enabled"] is True and r["calls"]["appended"] == 0     # 一般人：看得到欄位，沒有編輯器


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_draft_preview_replaces_the_list_until_closed():
    resp = "{ enabled: true, fields: [{ key: 'f1', label: '工頭', type: 'text' }] }"
    body = _INIT + """const S = window.MotrixCustomFields._state()
  window.MotrixCustomFields.show([{ key: 'f9', label: '草稿欄', type: 'date' }], 'edit', '預覽')
  const during = S.list().map(f => f.key), mode = S.mode
  window.MotrixCustomFields.show(null)
  console.log(JSON.stringify({ during, mode, after: S.list().map(f => f.key), mode2: S.mode }))"""
    r = _node(body, resp)
    assert r == {"during": ["f9"], "mode": "edit", "after": ["f1"], "mode2": "live"}


# ── node：案件頁的取值／設值 ──────────────────────────────────────────────
def _page_part():
    src = PAGE.read_text(encoding="utf-8")
    i = src.index("// T61 S5：自訂欄位（案件資訊）")
    a = src.rindex("<script>", 0, i)
    return src[a + len("<script>"):src.index("</script>", i)]


_PART = r"""
global.window = global
window.CM_PARTS = []
window.MotrixCustomFields = { init() {} }
const part = %(code)s
eval(part)
const o = Object.assign({}, window.CM_PARTS[0]())
let dirty = 0
o.setDirty = () => { dirty++ }
o.cr = { caseRecord: { customFields: %(start)s } }
o.session = { role: 'superadmin' }
%(body)s
"""


def _part(body, start="undefined"):
    js = _PART % dict(code=json.dumps(_page_part()), body=body, start=start)
    out = subprocess.run([NODE, "-e", js], capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[:1500]
    return json.loads(out.stdout.decode("utf-8"))


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_set_and_clear_keep_the_record_shape_the_server_stores():
    r = _part("""
  o.cfSet('f1', '王大明'); const a = JSON.stringify(o.cr.caseRecord.customFields)
  o.cfSet('f4', true); const b = JSON.stringify(o.cr.caseRecord.customFields)
  o.cfSet('f4', false); const c = JSON.stringify(o.cr.caseRecord.customFields)
  o.cfSet('f1', ''); const has = 'customFields' in o.cr.caseRecord; const empty = JSON.stringify(o.cr.caseRecord.customFields)
  console.log(JSON.stringify({ a, b, c, has, empty, dirty, gone: o.cfGet('f1') === undefined, admin: o.cfIsAdmin() }))""")
    assert r["a"] == '{"f1":"王大明"}' and r["b"] == '{"f1":"王大明","f4":true}' and r["c"] == '{"f1":"王大明"}'
    assert r["has"] is True and r["empty"] == "{}"    # 原本有值、全部清掉 ⇒ 送 {}（後端「沒送＝保留舊值」，只有 {} 才會清掉；存完伺服端把鍵拿掉）
    assert r["dirty"] == 4 and r["gone"] is True and r["admin"] is True


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_set_never_creates_an_empty_object_and_keeps_disabled_fields_values():
    r = _part("""
  o.cfSet('f1', ''); const none = o.cr.caseRecord.customFields !== undefined      // 夾具起手是 customFields: undefined（鍵在、值無）⇒ 看值不看鍵
  o.cr.caseRecord.customFields = { old: '停用欄位的值' }
  o.cfSet('f2', 'A'); const kept = JSON.stringify(o.cr.caseRecord.customFields)
  o.cfSet('f2', ''); const back = JSON.stringify(o.cr.caseRecord.customFields)
  console.log(JSON.stringify({ none, kept, back }))""")
    assert r == {"none": False, "kept": '{"old":"停用欄位的值","f2":"A"}', "back": '{"old":"停用欄位的值"}'}


# ── node：編輯器元件 ─────────────────────────────────────────────────────
_ED = r"""
const fs = require('fs')
global.window = global
global.localStorage = { getItem() { return JSON.stringify({ token: 't', role: 'superadmin' }) } }
global.document = { addEventListener() {}, getElementById() { return null }, body: { classList: { add() {}, remove() {} } } }
let reloads = 0, shown = []
eval(fs.readFileSync(process.argv[1], 'utf8'))
window.MotrixCustomFields.reload = async () => { reloads++ }
window.MotrixCustomFields.show = (f, m, l) => { shown.push(f) }
window.MotrixCustomFields.init({ recordType: 'case_info', label: '案件資訊' }).catch(() => {})
const c = window.MotrixCustomFields.component()
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
def test_editor_body_only_has_known_keys_and_parses_options():
    r = _ed("""
  c.work = [{ key: 'f1', label: ' 現場工頭 ', type: 'text', disabled: false, help: '', optionsText: 'x', maxLengthText: '50' },
            { key: 'f2', label: '等級', type: 'select', disabled: true, help: '提示', optionsText: 'A\\n B \\nA\\n\\nC', maxLengthText: '9' },
            { key: 'f3', label: '日期', type: 'date', disabled: false, help: '', optionsText: '', maxLengthText: '' }]
  const b = c._body().fields
  console.log(JSON.stringify({ b, view: c._view().map(f => f.key), next: c._nextKey() }))""")
    f1, f2, f3 = r["b"]
    assert f1 == {"key": "f1", "label": "現場工頭", "type": "text", "maxLength": 50}                 # 文字：不帶 options
    assert f2 == {"key": "f2", "label": "等級", "type": "select", "disabled": True, "help": "提示", "options": ["A", "B", "C"]}
    assert f3 == {"key": "f3", "label": "日期", "type": "date"}
    assert r["view"] == ["f1", "f3"] and r["next"] == "f4"                                           # 預覽不含停用欄位


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_published_field_type_is_locked_and_new_one_can_be_removed():
    r = _ed("""
  c.defs = { latest: { version: 1, body: { fields: [{ key: 'f1', label: 'a', type: 'text' }] } }, draft: null, versions: [] }
  c.work = [{ key: 'f1', label: 'a', type: 'text' }]
  c.add()
  const n = c.work.length; c.remove(0)           // f1 已發布：不能移除
  const keep = c.work.length; c.remove(1)          // 新增的可以
  console.log(JSON.stringify({ n, keep, left: c.work.map(f => f.key), newKey: c.isNew({ key: 'f2' }), oldKey: c.isNew({ key: 'f1' }) }))""")
    assert r == {"n": 2, "keep": 2, "left": ["f1"], "newKey": True, "oldKey": False}


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_ask_yes_no_and_close_cancels():
    r = _ed("""
  const p1 = c._ask('發布嗎？'); const shown1 = c.askBar.text; c.answer(true); const a = await p1
  const p2 = c._ask('還原嗎？'); c.answer(false); const b = await p2
  const p3 = c._ask('三'); c.close(); const d = await p3
  console.log(JSON.stringify({ shown1, a, b, d, bar: c.askBar, open: c.open }))""")
    assert r == {"shown1": "發布嗎？", "a": True, "b": False, "d": False, "bar": None, "open": False}


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_publish_cancel_sends_nothing_and_pending_is_reported_honestly():
    body = """
  const calls = []
  c.defs = { latest: null, draft: null, versions: [] }
  c.work = [{ key: 'f1', label: '工頭', type: 'text', disabled: false, help: '', optionsText: '', maxLengthText: '' }]
  c.load = async () => { c.loadError = '' }
  let RESP = null
  c._j = async (url, opt) => { calls.push((opt && opt.method || 'GET') + ' ' + url.replace(/\\?.*/, ''))
    if (url.indexOf('/draft') >= 0) return { ok: true, status: 200, d: { problems: [] } }
    if (url.indexOf('/validate') >= 0) return { ok: true, status: 200, d: { problems: [] } }
    if (url.indexOf('/publish') >= 0) return { ok: true, status: 200, d: RESP }
    return { ok: true, status: 200, d: { draft: null, latest: null, versions: [] } } }
  window.MotrixDefGovernance = undefined
  // 1) 使用者在確認列按取消 ⇒ 沒有 publish 請求
  let pub = c.publish(); await new Promise(r => setTimeout(r, 20)); c.answer(false); await pub
  const cancelled = calls.filter(x => x.indexOf('/publish') >= 0).length
  // 2) 確認後伺服器回待核准 ⇒ 狀態 pending、不重讀已發布欄位、不說已發布
  RESP = { pending: true, version: 3, effectiveAt: '2026-10-21T09:30:00', reasons: ['新增欄位 f1'] }
  calls.length = 0; pub = c.publish(); await new Promise(r => setTimeout(r, 20)); c.answer(true); await pub
  const pend = { state: c.state, msg: c.msg, reloads, published: calls.filter(x => x.indexOf('/publish') >= 0).length }
  // 3) 一般成功 ⇒ 已發布、重讀一次
  RESP = { version: 4 }
  pub = c.publish(); await new Promise(r => setTimeout(r, 20)); c.answer(true); await pub
  console.log(JSON.stringify({ cancelled, pend, ok: { state: c.state, msg: c.msg, reloads } }))"""
    r = _ed(body)
    assert r["cancelled"] == 0
    assert r["pend"]["state"] == "pending" and r["pend"]["reloads"] == 0 and r["pend"]["published"] == 1
    assert r["pend"]["msg"].startswith("已送出發布，待第二位最高管理者核准") and "已發布" not in r["pend"]["msg"]
    assert "生效時間 2026-10-21 09:30 之後" in r["pend"]["msg"] and "新增欄位 f1" in r["pend"]["msg"]
    assert r["ok"] == {"state": "published", "msg": "已發布第 4 版", "reloads": 1}


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_restore_pending_keeps_the_draft_and_ordinary_restore_deletes_it():
    body = """
  const calls = []
  let RESP = { pending: true, version: 5, reasons: [] }
  c.defs = { latest: null, draft: { body: { fields: [] } }, versions: [] }
  c.load = async () => { c.loadError = '' }
  c._j = async (url, opt) => { calls.push((opt && opt.method || 'GET') + ' ' + url.replace(/\\?.*/, '')); return { ok: true, status: 200, d: RESP } }
  let p = c.restore(2); await new Promise(r => setTimeout(r, 20)); c.answer(true); await p
  const pendCalls = calls.slice()
  calls.length = 0; RESP = { version: 6 }
  c.defs = { latest: null, draft: { body: { fields: [] } }, versions: [] }
  p = c.restore(2); await new Promise(r => setTimeout(r, 20)); c.answer(true); await p
  console.log(JSON.stringify({ pendCalls, okCalls: calls, state: c.state }))"""
    r = _ed(body)
    assert not any(x.startswith("DELETE") for x in r["pendCalls"])                  # 待核准的還原：不刪草稿
    assert any(x.startswith("DELETE") and x.endswith("/draft") for x in r["okCalls"])  # 一般還原：照舊刪草稿
    assert r["state"] == "restored"


# ── 供應商頁 ───────────────────────────────────────────────────────────────
SUP_PAGE = source_tree.page_file("suppliers.html")


def test_supplier_page_wiring_is_flag_guarded():
    src = SUP_PAGE.read_text(encoding="utf-8")
    assert '<script src="../static/custom-fields.js"></script>' in src
    assert "MotrixCustomFields.init({ recordType: 'supplier'" in src
    i = src.index('<div class="form-group" data-testid="cf-section"')
    assert "$store.cf && $store.cf.enabled" in src[src.rindex("<template", 0, i):i]
    sec = src[i:src.index('<div class="form-hint" style="color:var(--danger);margin-top:6px" x-show="formError"', i)]
    for t in ("text", "date", "select", "checkbox"):
        assert "f.type === '%s'" % t in sec
    assert "number" not in sec


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_supplier_set_keeps_an_empty_object_so_a_cleared_form_sends_empty_braces():
    """供應商是一次 PUT 整份：清空時要送 {}（伺服器才知道要清掉），而不是省略鍵（省略＝沒有要改）。"""
    src = SUP_PAGE.read_text(encoding="utf-8")
    i = src.index("// T61 S5：自訂欄位（供應商）。值存在 form.customFields")
    block = src[i:src.index("blankForm() {", i)]
    js = r"""
const o = { form: {}, session: { role: 'superadmin' }, isDirty: false,
  %s }
o.cfSet('f1', '小張'); const a = JSON.stringify(o.form.customFields)
o.cfSet('f1', ''); const b = JSON.stringify(o.form.customFields)
o.cfSet('f4', false); const c = JSON.stringify(o.form.customFields)
console.log(JSON.stringify({ a, b, c, dirty: o.isDirty, admin: o.cfIsAdmin(), none: o.cfGet('zz') === undefined }))
""" % block.replace("cfIsAdmin()", "cfIsAdmin()", 1)
    out = subprocess.run([NODE, "-e", js], capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[:1500]
    r = json.loads(out.stdout.decode("utf-8"))
    assert r == {"a": '{"f1":"小張"}', "b": "{}", "c": "{}", "dirty": True, "admin": True, "none": True}


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_editor_shows_usage_and_warns_before_disabling():
    r = _ed("""
  c.defs = { latest: { version: 1, body: { fields: [{ key: 'f1', label: '工頭', type: 'text' }] } }, draft: null, versions: [] }
  c.work = [{ key: 'f1', label: '工頭', type: 'text', disabled: false, help: '', optionsText: '', maxLengthText: '' }]
  c._j = async (url) => url.indexOf('/usage') >= 0 ? { ok: true, status: 200, d: { counts: { f1: 7 }, records: 7 } } : { ok: false, status: 500, d: {} }
  await c.loadUsage()
  const usage = c.usage
  c.work[0].disabled = true; c.onDisable(c.work[0])
  const warn = c.msg
  c._j = async () => { throw new Error('x') }
  await c.loadUsage()
  console.log(JSON.stringify({ usage, warn, after: c.usage }))""")
    assert r["usage"] == {"f1": 7}
    assert "已有 7 筆單據填了" in r["warn"] and "資料仍會保留" in r["warn"]
    assert r["after"] == {}                                           # 讀不到 ⇒ 不顯示數字，不丟例外


# ── 旗標關閉：整個頁面載入期間不多打任何請求（OFF 的網路清單與舊版相同） ────────────────
@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_deferred_init_fires_nothing_until_start():
    body = ("await window.MotrixCustomFields.init({ recordType: 'case_info', label: 'x', deferred: true })\n"
            "const before = calls.fetch.length\n"
            "await window.MotrixCustomFields.start()\n"
            "console.log(JSON.stringify({ before, after: calls.fetch }))")
    r = _node(body, "{ enabled: true, fields: [] }")
    assert r["before"] == 0 and r["after"] == ["/api/custom-fields/case_info"]
    r = _node("await window.MotrixCustomFields.start(); console.log(JSON.stringify({ n: calls.fetch.length }))", "{}")
    assert r["n"] == 0                                                   # 沒有 init 就 start ⇒ 什麼都不做


@pytest.mark.parametrize("name,flag_page_group", [("case-management.html", "builder_layout,builder_custom_fields,builder_rules,builder_slots,builder_status_display,builder_stage_templates"),
                                                  ("suppliers.html", "builder_layout,builder_custom_fields,builder_actions")])
def test_pages_read_the_flag_from_the_existing_settings_request(name, flag_page_group):
    from core import source_tree
    src = source_tree.page_file(name).read_text(encoding="utf-8")
    assert "MotrixCustomFields.init({" in src and "deferred: true" in src.split("MotrixCustomFields.init({")[1].split("})")[0]
    names = ", ".join("'%s'" % g for g in flag_page_group.split(","))
    assert "MotrixPublicFlags.read([" + names + "]" in src and '../static/public-flags.js' in src       # 網址由 public-flags.js 組（一個請求，失敗才逐組）
    assert "builder_custom_fields.enabled === true" in src and "MotrixCustomFields.start()" in src
    # 頁面本身不直接打 /api/custom-fields（只有程式庫在旗標開啟後才打）
    assert "/api/custom-fields" not in re.sub(r"//[^\n]*", "", src.replace("<!--", "//").replace("-->", ""))


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_publish_sends_the_reviewed_preview_hash_only_when_governance_is_on():
    """T62：治理旗標開 ⇒ 先 review 再帶 preview_hash 發布；審閱取消就不發布。關／未載入 ⇒ 請求本體只有 note。"""
    body = """
  c.defs = { latest: null, draft: null, versions: [] }
  c.work = [{ key: 'f1', label: '工頭', type: 'text', disabled: false, help: '', optionsText: '', maxLengthText: '' }]
  c.load = async () => { c.loadError = '' }
  c.note = 'n1'
  const reviewed = []
  async function run(gov, review) {
    const sent = []
    c.note = 'n1'
    c._j = async (url, opt) => { if (url.indexOf('/publish') >= 0) { sent.push(JSON.parse(opt.body)); return { ok: true, status: 200, d: { version: 9 } } }
      if (url.indexOf('/draft') >= 0 || url.indexOf('/validate') >= 0) return { ok: true, status: 200, d: { problems: [] } }
      return { ok: true, status: 200, d: { draft: null, latest: null, versions: [] } } }
    window.MotrixDefGovernance = gov ? { available: async (k) => k === 'custom_fields', review: async (o) => { reviewed.push(o); return review } } : undefined
    const pub = c.publish(); await new Promise(r => setTimeout(r, 20)); c.answer(true); await pub
    return sent
  }
  const on = await run(true, 'H1'), off = await run(false, 'H1'), cancel = await run(true, null)
  console.log(JSON.stringify({ on, off, cancel, reviewed }))"""
    r = _ed(body)
    assert r["on"] == [{"note": "n1", "preview_hash": "H1"}]
    assert r["off"] == [{"note": "n1"}]
    assert r["cancel"] == [] and r["reviewed"][0]["kind"] == "custom_fields"


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_restore_sends_the_reviewed_hash_only_when_governance_is_on():
    """T62：治理旗標開 ⇒ previewRestore 後帶 preview_hash 還原；旗標關／取不到雜湊 ⇒ 請求本體仍是 {}。"""
    body = """
  c.defs = { latest: null, draft: null, versions: [] }
  c.work = [{ key: 'f1', label: '工頭', type: 'text', disabled: false, help: '', optionsText: '', maxLengthText: '' }]
  c.load = async () => { c.loadError = '' }
  async function run(gov, hash) {
    const sent = [], asked = []
    c._j = async (url, opt) => { sent.push({ url, body: opt && opt.body }); return { ok: true, status: 200, d: { version: 8, draft: null, latest: null, versions: [] } } }
    window.MotrixDefGovernance = gov ? { available: async (k) => k === 'custom_fields', previewRestore: async (o, v) => { asked.push([o.kind, o.scope, v]); return hash } } : undefined
    const p = c.restore(2); await new Promise(r => setTimeout(r, 20)); c.answer(true); await p
    return { body: JSON.parse(sent.filter(x => x.url.indexOf('/restore/2') >= 0)[0].body), asked }
  }
  console.log(JSON.stringify({ on: await run(true, 'v2:H'), off: await run(false, 'v2:H'), none: await run(true, null) }))"""
    r = _ed(body)
    assert r["on"]["body"] == {"preview_hash": "v2:H"} and r["on"]["asked"] == [["custom_fields", "company", 2]]
    assert r["off"]["body"] == {} and r["off"]["asked"] == [] and r["none"]["body"] == {}
