# -*- coding: utf-8 -*-
"""T60 S2 接口：排版器如實顯示「待核准」。

治理旗標（builder_governance.enabled）開啟且 kind 在 ACTIVE_KINDS 時，放寬的發布／還原回
`{pending: true, changeId, effectiveAt, reasons, version, message}`（routers/def_pipeline.py）。排版器這時不能說「已發布」：
要說已送出、待第二位最高管理者核准、生效時間、原因；不重讀版面（版面還沒變）。旗標關閉時後端永遠不回 pending，行為與先前相同。
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
EDITOR = ROOT / "frontend" / "static" / "layout-editor.js"
NODE = shutil.which("node")


def _src():
    return EDITOR.read_text(encoding="utf-8")


def test_publish_and_restore_branch_on_pending_before_claiming_success():
    src = _src()
    pub = src[src.index("async _publish()"):src.index("async _restore(")]
    res = src[src.index("async _restore("):src.index("async _discard()")]
    for body, claim in ((pub, "'已發布第 '"), (res, "'已把第 '")):
        assert "r.d.pending === true" in body
        assert body.index("if (pend) {") < body.index(claim)                    # 先處理待核准，才會走到「已發布／已還原」
        assert "if (!pend) await ML().reload()" in body                          # 待核准：版面沒變，不重讀
        assert "this.state = 'pending'" in body


_HARNESS = r"""
const fs = require('fs')
global.window = global
global.document = { addEventListener() {}, body: { classList: { add() {}, remove() {} } }, getElementById() { return null } }
window.MotrixCustomLayout = { compileOps() { return [] }, clone(x) { return x } }
let reloads = 0
window.MotrixLayout = { show() {}, config() { return { module: 'x', page: 'p' } }, reload: async () => { reloads++ } }
eval(fs.readFileSync(process.argv[1], 'utf8'))
const c = window.MotrixLayoutEditor.component()
;(async () => {
%s
})().catch(e => { console.error(String(e)); process.exit(1) })
"""


def _node(body):
    out = subprocess.run([NODE, "-e", _HARNESS % body, str(EDITOR)], capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[:1500]
    return json.loads(out.stdout.decode("utf-8"))


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_pending_text_says_waiting_when_it_takes_effect_and_why():
    r = _node("""
  c.scope = 'company'
  const t = c._pendingText({ pending: true, version: 4, effectiveAt: '2026-10-21T09:30:12', reasons: ['顯示了原本隱藏的欄位', '核心欄位順序改變'] }, '發布')
  const bare = c._pendingText({ pending: true }, '還原第 2 版')
  console.log(JSON.stringify({ t, bare }))""")
    assert "已送出發布" in r["t"] and "待第二位最高管理者核准" in r["t"] and "第 4 版" in r["t"]
    assert "核准前不會生效" in r["t"] and "生效時間 2026-10-21 09:30 之後" in r["t"]
    assert "原因：顯示了原本隱藏的欄位；核心欄位順序改變" in r["t"]
    assert "已發布" not in r["t"] and "已發布" not in r["bare"]               # 絕不宣稱已發布
    assert r["bare"].startswith("已送出還原第 2 版") and "生效時間" not in r["bare"] and "原因" not in r["bare"]


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_publish_pending_response_keeps_the_live_layout_and_reports_pending():
    """node 真的跑 _publish：伺服器回 pending ⇒ 狀態 pending、訊息是待核准、不重讀版面；回一般成功 ⇒ 與先前相同（已發布、重讀版面）。"""
    body = """
  async function run(resp) {
    c.defs = { draft: null, latest: null, versions: [] }
    c.scope = 'company'; c.work = {}; c.lastOps = []; c.note = ''
    c.showDiff = () => {}; c.saveDraft = async () => true; c.loadScope = async () => { c.loadError = '' }; c._mark = () => {}
    c._j = async (url) => url.indexOf('/validate') >= 0 ? { ok: true, status: 200, d: { problems: [] } } : { ok: true, status: 200, d: resp }
    window.MotrixDefGovernance = undefined
    const before = reloads
    await c._publish()
    return { state: c.state, msg: c.msg, reloaded: reloads - before }
  }
  const pend = await run({ pending: true, version: 5, effectiveAt: '2026-10-21T09:30:00', reasons: ['放寬'] })
  const ok = await run({ version: 6 })
  console.log(JSON.stringify({ pend, ok }))"""
    r = _node(body)
    assert r["pend"]["state"] == "pending" and r["pend"]["reloaded"] == 0
    assert r["pend"]["msg"].startswith("已送出發布，待第二位最高管理者核准") and "已發布" not in r["pend"]["msg"]
    assert r["ok"]["state"] == "published" and r["ok"]["reloaded"] == 1 and r["ok"]["msg"].startswith("已發布第 6 版")


def test_no_pending_handling_changes_the_flag_off_path():
    """旗標關閉時後端不回 pending：一般路徑的訊息文字與狀態名稱保持不變（e2e 等待點 published／restored 不動）。"""
    src = _src()
    assert "this.state = 'published'" in src and "this.state = 'restored'" in src
    assert re.search(r"this\.msg = '已發布第 ' \+ r\.d\.version \+ ' 版（' \+ this\.scopeLabel\(\) \+ '）'", src)


def test_pending_restore_does_not_delete_the_draft():
    """待核准的還原（3e：舊內容放進待核准的版本／草稿）：編輯器不可再 DELETE 草稿；一般還原照舊先刪草稿。"""
    src = _src()
    res = src[src.index("async _restore("):src.index("async _discard()")]
    assert "var pend = r.d && r.d.pending === true" in res
    assert "if (!pend && this.defs.draft) await this._j(" in res and "{ method: 'DELETE' }" in res
    assert res.index("var pend =") < res.index("method: 'DELETE'")


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_publish_sends_the_reviewed_preview_hash_only_when_governance_is_on():
    """T62：治理旗標開 ⇒ 先 review，帶 preview_hash 發布；取消就不發布。旗標關／未載入 ⇒ 發布請求本體只有 note（與先前逐位元相同）。"""
    body = """
  async function run(gov, review) {
    c.defs = { draft: null, latest: null, versions: [] }
    c.scope = 'company'; c.work = {}; c.lastOps = []; c.note = 'n1'
    c.showDiff = () => {}; c.saveDraft = async () => true; c.loadScope = async () => { c.loadError = '' }; c._mark = () => {}
    const sent = []
    c._j = async (url, opt) => { if (url.indexOf('/validate') >= 0) return { ok: true, status: 200, d: { problems: [] } }
                                 sent.push({ url, body: opt && opt.body }); return { ok: true, status: 200, d: { version: 7 } } }
    window.MotrixDefGovernance = gov ? { available: async (k) => k === 'layout', review: async (o) => { reviewed.push(o); return review } } : undefined
    await c._publish()
    return { pub: sent.filter(x => x.url.indexOf('/publish') >= 0).map(x => JSON.parse(x.body)), msg: c.msg }
  }
  const reviewed = []
  const on = await run(true, 'H1'), off = await run(false, 'H1'), cancel = await run(true, null)
  console.log(JSON.stringify({ on, off, cancel, reviewed }))"""
    r = _node(body)
    assert r["on"]["pub"] == [{"note": "n1", "preview_hash": "H1"}]
    assert r["off"]["pub"] == [{"note": "n1"}]                                  # 旗標關 ⇒ 請求本體不變
    assert r["cancel"]["pub"] == [] and r["cancel"]["msg"] == "已取消發布"
    assert r["reviewed"][0]["kind"] == "layout" and r["reviewed"][0]["key"].startswith("module:")
