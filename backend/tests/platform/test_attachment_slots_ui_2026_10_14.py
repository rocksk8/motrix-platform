# -*- coding: utf-8 -*-
"""BP-4 S3：附件種類編輯器（static/attachment-slots.js）與案件頁完工單分頁的入口——靜態＋node 真的執行。

證明：旗標關閉／非最高管理者 ⇒ 這個檔什麼都不做、不發請求；入口的旗標從案件頁**既有的那一個設定請求**取得；
編輯器的定義 body 只含認得的鍵（空值不送、角色只會縮小）；發布先走審閱面板（治理旗標開才帶 preview_hash）、取消就不發布、待核准如實說；
還原帶 previewRestore；模擬上傳的請求形狀；沒有原生對話框；標籤不當 HTML 插入。
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from core import source_tree

ROOT = Path(__file__).resolve().parents[3]
JS = ROOT / "frontend" / "static" / "attachment-slots.js"
NODE = shutil.which("node")
NATIVE = re.compile(r"(?<![\w$])(alert|confirm|prompt)\s*\(")


def _strip(text):
    return re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.S)


def test_no_native_dialogs_and_labels_never_become_html():
    src = _strip(JS.read_text(encoding="utf-8"))
    assert [m.group(1) for m in NATIVE.finditer(src)] == []
    assert "x-html" not in src and src.count("innerHTML") == 1 and "wrap.innerHTML = tpl()" in src
    probe = [m.group(1) for m in NATIVE.finditer("alert('a'); if (!confirm('b')) return; window.prompt('c'); await this._ask('d')")]
    assert probe == ["alert", "confirm", "prompt"]                                            # 掃描器的正對照


def test_case_page_wiring_reads_the_flag_from_the_existing_settings_request():
    src = source_tree.page_file("case-management.html").read_text(encoding="utf-8")
    assert '<script src="../static/attachment-slots.js"></script>' in src
    assert "'builder_rules', 'builder_slots'" in src                                            # 同一個請求（MotrixPublicFlags 名單），只多一個群組名
    assert "Number(g.builder_slots.enabled) === 1" in src and "MotrixAttachmentSlots.mount(" in src
    assert "asOn: false," in src                                                               # 預設關
    i = src.index('data-testid="as-edit-open"')
    tag = src[src.rindex("<button", 0, i):src.index(">", i)]
    assert 'x-show="asOn"' in tag and "display:" not in tag                                    # OFF 守門：x-show 不掛在帶行內 display 的元素
    code = re.sub(r"//[^\n]*", "", src.replace("<!--", "//").replace("-->", ""))
    assert "/api/attachment-slots" not in code                                                 # 頁面本身不打；只有編輯器打


_RT = r"""
const fs = require('fs')
global.window = global
const calls = { fetch: [], appended: 0 }
let ROLE = %(role)s
global.localStorage = { getItem() { return JSON.stringify({ token: 'tok', role: ROLE }) } }
global.document = { addEventListener() {}, getElementById() { return null }, head: { appendChild() {} },
  createElement() { return { innerHTML: '', firstChild: {}, textContent: '', id: '' } },
  body: { appendChild() { calls.appended++ }, classList: { add() {}, remove() {} } } }
global.fetch = async (u) => { calls.fetch.push(String(u)); return { ok: true, json: async () => ({}) } }
eval(fs.readFileSync(process.argv[1], 'utf8'))
;(async () => {
%(body)s
})().catch(e => { console.error(String(e)); process.exit(1) })
"""

_ED = r"""
const fs = require('fs')
global.window = global
global.localStorage = { getItem() { return JSON.stringify({ token: 't', role: 'superadmin' }) } }
global.document = { addEventListener() {}, getElementById() { return null }, head: { appendChild() {} },
  createElement() { return { innerHTML: '', firstChild: {}, textContent: '', id: '' } },
  body: { appendChild() {}, classList: { add() {}, remove() {} } } }
eval(fs.readFileSync(process.argv[1], 'utf8'))
window.MotrixAttachmentSlots.mount({ docType: 'completion_note', label: '完工單' })
const c = window.MotrixAttachmentSlots.component()
c.open = true
;(async () => {
%(body)s
})().catch(e => { console.error(String(e)); process.exit(1) })
"""


def _run(tpl, **kw):
    out = subprocess.run([NODE, "-e", tpl % kw, str(JS)], capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[:1500]
    return json.loads(out.stdout.decode("utf-8"))


def _rt(body, role="'superadmin'"):
    return _run(_RT, body=body, role=role)


def _ed(body):
    return _run(_ED, body=body)


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_mount_is_inert_for_non_superadmins_and_never_fetches():
    r = _rt("""const m = window.MotrixAttachmentSlots.mount({ docType: 'completion_note', label: 'x' })
  console.log(JSON.stringify({ m, calls }))""", role="'sales'")
    assert r["m"] is False and r["calls"]["appended"] == 0 and r["calls"]["fetch"] == []
    r = _rt("""const m = window.MotrixAttachmentSlots.mount({ docType: 'completion_note', label: 'x' })
  console.log(JSON.stringify({ m, calls }))""")
    assert r["m"] is True and r["calls"]["appended"] == 1 and r["calls"]["fetch"] == []                  # 掛上編輯器本身也不發請求
    assert _rt("console.log(JSON.stringify({ n: calls.fetch.length }))")["n"] == 0                       # 光是載入這個檔：零請求


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_body_has_only_known_keys_blank_values_are_omitted_and_roles_only_narrow():
    r = _ed("""
  c.catalog.slotExts = ['.pdf', '.jpg']
  c.add(); c.add()
  c.work[0].label = ' 驗收單 '; c.work[0].accept = ['.pdf']; c.work[0].maxFiles = '5'; c.work[0].subfolder = ' 驗收 '; c.work[0].roles = ['admin']; c.work[0].required = true
  c.work[1].label = '照片'; c.work[1].accept = ['.jpg']; c.work[1].maxFileMb = ''; c.work[1].disabled = true
  c.toggleExt(c.work[1], '.pdf', true); c.toggleExt(c.work[1], '.jpg', false); c.toggleRole(c.work[1], 'sales', true); c.toggleRole(c.work[1], 'sales', false)
  console.log(JSON.stringify({ body: c._body(), next: c._nextKey() }))""")
    a, b = r["body"]["slots"]
    assert a == {"key": "slot1", "label": "驗收單", "accept": [".pdf"], "maxFiles": 5, "subfolder": "驗收", "uploaders": {"roles": ["admin"], "modules": []}, "required": True}
    assert b == {"key": "slot2", "label": "照片", "accept": [".pdf"], "disabled": True} and r["next"] == "slot3"                # 空值不送、沒勾角色＝沒有 uploaders
    assert "signed" not in json.dumps(r["body"])                                                                              # 內建簽回單不在定義裡


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_load_reports_a_closed_flag_honestly_and_locks_editing():
    r = _ed("""
  c._j = async (url) => url.indexOf('/catalog') >= 0 ? { ok: false, status: 404, d: {} } : { ok: true, status: 200, d: {} }
  await c.load()
  console.log(JSON.stringify({ err: c.loadError, loading: c.loading }))""")
    assert "尚未開放" in r["err"] and "版本帳本與影響預覽" in r["err"] and r["loading"] is True            # 鎖住，不讓人在關閉狀態下編輯


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_load_reads_catalog_then_the_definition_and_continues_from_the_draft():
    r = _ed("""
  const urls = []
  c._j = async (url) => { urls.push(url)
    if (url.indexOf('/catalog') >= 0) return { ok: true, status: 200, d: { slotExts: ['.pdf'], roles: ['admin'], platform: { maxFileMb: 20, maxFiles: 20, maxRequestMb: 100, maxSlots: 10 }, docTypes: [{ docType: 'completion_note', subfolderSupported: true }] } }
    return { ok: true, status: 200, d: { draft: { body: { slots: [{ key: 'a', label: 'A', accept: ['.pdf'], maxFiles: 3, uploaders: { roles: ['admin'] } }] } }, latest: null, versions: [] } } }
  await c.load()
  console.log(JSON.stringify({ urls, work: c.work, msg: c.msg, sub: c.subfolderOk() }))""")
    assert r["urls"][0] == "/api/attachment-slots/catalog" and r["urls"][1] == "/api/definitions/attachment_slot/doc%3Acompletion_note?scope=company"
    assert r["work"][0]["maxFiles"] == 3 and r["work"][0]["roles"] == ["admin"] and r["msg"] == "從草稿繼續" and r["sub"] is True


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_simulate_posts_the_draft_and_shows_the_result_without_saving_anything():
    r = _ed("""
  const sent = []
  c.add(); c.work[0].label = '驗收'; c.work[0].accept = ['.pdf']
  c.sim = { slot: 'slot1', filename: 'a.pdf', kb: 2, existing: 1, docNo: ' N-1 ' }
  c._j = async (url, opt) => { sent.push({ url, method: opt && opt.method, body: JSON.parse(opt.body) })
    return { ok: true, status: 200, d: { ok: true, reasons: [], displayPath: 'uploads/completion_notes/N-1/x.pdf', readers: { admin: { canRead: 1, accounts: 1 } } } } }
  await c.simulate()
  console.log(JSON.stringify({ sent, res: c.simResult, roles: c.readerRoles(), msg: c.msg }))""")
    s = r["sent"][0]
    assert s["url"] == "/api/attachment-slots/completion_note/simulate" and s["method"] == "POST" and len(r["sent"]) == 1               # 只有模擬一個請求（沒有存草稿）
    assert s["body"]["slot"] == "slot1" and s["body"]["docNo"] == "N-1" and s["body"]["sample"] == {"filename": "a.pdf", "size": 2048, "existing": 1}
    assert s["body"]["definition"]["slots"][0]["label"] == "驗收" and r["roles"] == ["admin"] and "沒有存任何檔案" in r["msg"]


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_simulate_problems_are_marked_on_the_slot_and_no_result_is_shown():
    r = _ed("""
  c.add()
  c._j = async () => ({ ok: false, status: 422, d: { detail: { problems: [{ path: 'slots[0].accept', message: '副檔名不允許' }] } } })
  await c.simulate()
  console.log(JSON.stringify({ probs: c.probs, res: c.simResult, msg: c.msg }))""")
    assert r["probs"]["0"] == "副檔名不允許" and r["res"] is None and "無法模擬" in r["msg"]


_PUB = """
  const calls = []
  c.defs = { latest: null, draft: null, versions: [] }
  c.add(); c.work[0].label = '驗收'
  c.load = async () => { c.loadError = '' }
  let RESP = { version: 4 }
  c._j = async (url, opt) => { calls.push({ m: (opt && opt.method) || 'GET', u: url.replace(/\\?.*/, ''), b: opt && opt.body ? JSON.parse(opt.body) : null })
    if (url.indexOf('/draft') >= 0 || url.indexOf('/validate') >= 0) return { ok: true, status: 200, d: { problems: [] } }
    if (url.indexOf('/publish') >= 0) return { ok: true, status: 200, d: RESP }
    return { ok: true, status: 200, d: { draft: null, latest: null, versions: [] } } }
  const reviewed = []
  async function run(gov, review, answer) {
    calls.length = 0
    window.MotrixDefGovernance = gov ? { available: async (k) => k === 'attachment_slot', review: async (o) => { reviewed.push(o); return review } } : undefined
    const p = c.publish(); await new Promise(r => setTimeout(r, 20)); c.answer(answer); await p
    return calls.filter(x => x.u.indexOf('/publish') >= 0).map(x => x.b)
  }
"""


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_publish_asks_first_sends_the_preview_hash_only_with_governance_and_cancel_sends_nothing():
    r = _ed(_PUB + """
  const noGov = await run(false, 'H', true), gov = await run(true, 'H1', true), cancelAsk = await run(true, 'H', false), cancelReview = await run(true, null, true)
  console.log(JSON.stringify({ noGov, gov, cancelAsk, cancelReview, reviewed, state: c.state }))""")
    assert r["noGov"] == [{"note": ""}]                                                         # 治理關：請求本體只有 note
    assert r["gov"] == [{"note": "", "preview_hash": "H1"}]
    assert r["cancelAsk"] == [] and r["cancelReview"] == []                                     # 兩段確認取消／審閱取消 ⇒ 不發布
    assert r["reviewed"][0]["kind"] == "attachment_slot" and r["reviewed"][0]["key"] == "doc:completion_note" and r["reviewed"][0]["scope"] == "company"


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_pending_publish_is_reported_honestly_and_ordinary_publish_says_published():
    r = _ed(_PUB + """
  RESP = { pending: true, version: 5, effectiveAt: '2026-10-21T09:30:00', reasons: ['新增可收：.docx（放寬）'] }
  await run(false, null, true)
  const pend = { state: c.state, msg: c.msg }
  RESP = { version: 6 }
  await run(false, null, true)
  console.log(JSON.stringify({ pend, ok: { state: c.state, msg: c.msg } }))""")
    assert r["pend"]["state"] == "pending" and r["pend"]["msg"].startswith("已送出發布，待第二位最高管理者核准") and "已發布" not in r["pend"]["msg"]
    assert "生效時間 2026-10-21 09:30 之後" in r["pend"]["msg"] and "放寬" in r["pend"]["msg"]
    assert r["ok"] == {"state": "published", "msg": "已發布第 6 版"}


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_restore_sends_the_restore_hash_only_with_governance_and_pending_keeps_the_draft():
    r = _ed("""
  c.load = async () => { c.loadError = '' }
  async function run(gov, hash, resp, draft) {
    const sent = []
    c.defs = { latest: null, draft: draft ? { body: {} } : null, versions: [] }
    c._j = async (url, opt) => { sent.push({ m: (opt && opt.method) || 'GET', u: url.replace(/\\?.*/, ''), b: opt && opt.body ? JSON.parse(opt.body) : null }); return { ok: true, status: 200, d: resp } }
    window.MotrixDefGovernance = gov ? { available: async (k) => k === 'attachment_slot', previewRestore: async (o, v) => hash } : undefined
    const p = c.restore(2); await new Promise(r => setTimeout(r, 20)); c.answer(true); await p
    return sent
  }
  const on = await run(true, 'v2:H', { version: 8 }, true), off = await run(false, 'v2:H', { version: 8 }, false), pend = await run(true, 'v2:H', { pending: true, version: 9 }, true)
  console.log(JSON.stringify({ on, off, pend }))""")
    assert r["on"][0]["b"] == {"preview_hash": "v2:H"} and r["off"][0]["b"] == {}
    assert any(x["m"] == "DELETE" for x in r["on"])                                              # 一般還原先刪草稿
    assert not any(x["m"] == "DELETE" for x in r["pend"])                                        # 待核准的還原不刪草稿
