# -*- coding: utf-8 -*-
"""T57 認列被拒要『立刻』看得到（MS1d）：node 直接執行 case-management-core.js＋mlink.js（不開瀏覽器）。
- `_matRejected`：認列相關的拒絕用白話訊息直接提示（不套『材料申請審核規則』前綴）、採用伺服器現值、重新載入認列分組；其他拒絕維持原樣
- `mlPickCandidate`：立刻存檔（沿用 saveCaseRecord 的佇列／互斥——存檔途中再改的內容下一輪再送，不重疊、不遺失）；被拒時不顯示成功訊息"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
CORE = ROOT / "frontend" / "js" / "case-management-core.js"
MLINK = ROOT / "frontend" / "js" / "case-management-mlink.js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(not NODE, reason="需要 node")

HARNESS = r"""
const fs = require('fs')
const inp = JSON.parse(process.argv[2])
global.window = {}; global.MotrixLegalRound = { halfUp: (v) => Math.round(v) }
const toasts = []
global.MotrixUI = { toast: (m, o) => toasts.push([m, (o || {}).kind]) }
global.document = { addEventListener() {}, querySelector() { return null } }
global.alpineStub = true
for (const f of [process.argv[3], process.argv[4]]) (0, eval)(fs.readFileSync(f, 'utf8'))
const merged = {}
for (const part of window.CM_PARTS) Object.defineProperties(merged, Object.getOwnPropertyDescriptors(part()))
const ctx = Object.assign(merged, inp.ctx || {})
ctx.session = { token: 't' }; ctx.selected = { quote_no: 'MQ-1' }
ctx.cr = { caseRecord: { materials: inp.local || [] } }; ctx._segBase = { materials: JSON.stringify(inp.base || []) }
let loads = 0; ctx.mlLoadGroups = async () => { loads++ }
global.fetch = async () => ({ ok: true, json: async () => ({ data: { caseRecord: { materials: inp.server || [] } } }) })
;(async () => {
  const out = {}
  if (inp.scenario === 'rejected') {
    await ctx._matRejected(inp.list)
    out.materials = ctx.cr.caseRecord.materials; out.base = JSON.parse(ctx._segBase.materials)
  } else if (inp.scenario === 'pick') {
    ctx.moCanEdit = () => true; ctx.materialOrders = []
    ctx.mlGroups = [{ key: 'item:a', docCodes: ['PO-1'], name: 'A', vendor: 'V', poDocCode: 'PO-1' }]
    let running = 0, maxRun = 0, runs = 0
    ctx._saveCaseRecordOnce = async function () {
      runs++; running++; maxRun = Math.max(maxRun, running)
      await new Promise(r => setTimeout(r, 20))
      if (inp.denied) this.cr.caseRecord.materials = (inp.server || [])      // 模擬 _matRejected 採用伺服器現值
      running--; return inp.saveResult === undefined ? true : inp.saveResult
    }
    ctx.dirty = false; ctx.setDirty = function () { this.dirty = true; this._autoSaveTimer = setTimeout(() => {}, 1500) }
    const mat = { id: 'c1', name: 'A', orderItemId: '' }
    ctx.cr.caseRecord.materials = [mat]
    if (inp.busy) ctx.saveCaseRecord()                                           // 已有一輪存檔在跑
    const okPick = ctx.mlPickCandidate(mat, 'g:item:a')
    out.pick = okPick; out.msgNow = ctx.mlMsg
    while (ctx._saveRun) await new Promise(r => setTimeout(r, 5))
    await new Promise(r => setTimeout(r, 5))
    out.msgAfter = ctx.mlMsg; out.runs = runs; out.maxRun = maxRun
  }
  out.toasts = toasts; out.loads = loads
  console.log(JSON.stringify(out))
})()
"""


def _run(**inp):
    out = subprocess.run([NODE, "-e", HARNESS, "x", json.dumps(inp), str(CORE), str(MLINK)],
                         capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


@needs_node
def test_recognition_denial_shows_plain_message_without_review_prefix_and_refreshes_groups():
    msg = "這個帳號沒有認列採購單的權限，這次認列已取消，並已通知管理員。"
    r = _run(scenario="rejected", list=[{"itemId": "c1", "field": "poLink", "code": "recognize_denied", "message": msg}],
             local=[{"id": "c1", "poLink": {"key": "item:a"}, "ordered": True}], server=[{"id": "c1", "ordered": False}])
    assert r["toasts"] == [[msg, "error"]]                                           # 沒有『材料申請審核規則：』前綴
    assert r["materials"] == [{"id": "c1", "ordered": False}]                          # 採用伺服器現值：poLink 沒了、旗標還原
    assert r["loads"] == 1                                                            # 認列分組重新載入


@needs_node
def test_recognition_denial_restores_only_the_rejected_card_and_keeps_edits_on_other_cards():
    """存檔途中在別張卡片新打的修改，不可被『採用伺服器現值』吃掉；存檔基準只對被拒的卡片換成伺服器版。"""
    msg = "這個帳號沒有認列採購單的權限，這次認列已取消。"
    local = [{"id": "c1", "poLink": {"key": "item:a"}, "ordered": True}, {"id": "c2", "name": "新打的字"}]
    sent_base = [{"id": "c1", "poLink": {"key": "item:a"}, "ordered": True}, {"id": "c2", "name": "舊"}]
    server = [{"id": "c1", "ordered": False}, {"id": "c2", "name": "舊"}]
    r = _run(scenario="rejected", list=[{"itemId": "c1", "field": "poLink", "code": "recognize_denied", "message": msg}],
             local=local, base=sent_base, server=server)
    assert r["materials"] == [{"id": "c1", "ordered": False}, {"id": "c2", "name": "新打的字"}]      # c1 還原；c2 的新修改還在
    assert r["base"] == [{"id": "c1", "ordered": False}, {"id": "c2", "name": "舊"}]               # 基準：c1＝伺服器版、c2＝送出時的版本 ⇒ 下一輪只會送 c2 的修改


@needs_node
def test_deleting_a_recognized_card_is_undone_in_both_the_list_and_the_base():
    """非最高管理者刪除持有認列的卡片：本機已拿掉、伺服器拒絕並保留 ⇒ 兩邊（畫面與存檔基準）都要放回，其他修改保留，否則之後每次自動存檔都會再送一次刪除。"""
    msg = "這個帳號沒有認列採購單的權限，這次認列已取消（已認列的材料卡片不能刪除）。"
    c1 = {"id": "c1", "poLink": {"key": "item:a"}, "ordered": True}
    local = [{"id": "c0", "name": "新打的字"}, {"id": "c2", "name": "尾"}]
    base = [{"id": "c0", "name": "舊"}, {"id": "c2", "name": "尾"}]                      # 刪除之後送出的快照（已沒有 c1）
    server = [{"id": "c0", "name": "舊"}, c1, {"id": "c2", "name": "尾"}]
    r = _run(scenario="rejected", list=[{"itemId": "c1", "field": "poLink", "code": "recognize_denied", "message": msg}], local=local, base=base, server=server)
    assert [m["id"] for m in r["materials"]] == ["c0", "c1", "c2"] and r["materials"][1] == c1          # 依伺服器位置放回
    assert r["materials"][0]["name"] == "新打的字"                                                     # 其他卡片的新修改保留
    assert r["base"] == [{"id": "c0", "name": "舊"}, c1, {"id": "c2", "name": "尾"}]                   # 基準＝送出版本＋伺服器的 c1 ⇒ cr 與基準只差 c0 的修改


@needs_node
def test_success_text_only_when_the_save_really_succeeded():
    for res, expect in ((False, "認列尚未儲存"), ("pending", "待最高管理員審核"), (None, "認列尚未儲存")):
        r = _run(scenario="pick", saveResult=res)
        assert expect in r["msgAfter"] and "已認列採購單" not in r["msgAfter"], (res, r["msgAfter"])
    assert "已認列採購單 PO-1" in _run(scenario="pick", saveResult=True)["msgAfter"]


@needs_node
def test_other_rejections_keep_the_review_prefix_and_do_not_reload_groups():
    r = _run(scenario="rejected", list=[{"itemId": "c1", "field": "ordered", "code": "order_not_approved", "message": "這筆材料申請還沒核准。"}],
             local=[{"id": "c1"}], server=[{"id": "c1"}])
    assert r["toasts"] == [["材料申請審核規則：這筆材料申請還沒核准。", "info"]] and r["loads"] == 0


@needs_node
def test_pick_saves_immediately_and_shows_success_only_when_the_link_survived():
    ok = _run(scenario="pick")
    assert ok["pick"] is True and ok["msgNow"] == "認列中…" and ok["runs"] == 1 and "已認列採購單 PO-1" in ok["msgAfter"]
    denied = _run(scenario="pick", denied=True, server=[{"id": "c1"}])
    assert denied["msgNow"] == "認列中…" and denied["msgAfter"] == ""                  # 被拒：不顯示成功訊息


@needs_node
def test_immediate_save_uses_the_existing_queue_so_saves_never_overlap():
    r = _run(scenario="pick", busy=True)
    assert r["runs"] == 2 and r["maxRun"] == 1                                         # 已有一輪在跑 ⇒ 排隊再跑一輪（帶上最新狀態），不重疊


def test_wiring_is_in_place():
    core, ml = CORE.read_text(encoding="utf-8"), MLINK.read_text(encoding="utf-8")
    assert "recognize_denied" in core and "this.mlLoadGroups(this.selected.quote_no)" in core
    assert "saveCaseRecord()" in ml and "認列中…" in ml
