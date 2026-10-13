# -*- coding: utf-8 -*-
"""材料存檔後的分段基準＝伺服器實際存入的值（2026-10-14，使用者回報：自己一人操作一次就跳『材料已被他人更新』）。
伺服器存檔時會改寫材料卡片（認列的到貨人／時間、過期標記…）；前端若只把『送出的內容』當基準，
下一次存檔的 base 與資料庫現值不同 ⇒ 409。node 直接執行 case-management-core.js（不開瀏覽器）。"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
CORE = ROOT / "frontend" / "js" / "case-management-core.js"
QUOTATIONS = ROOT / "backend" / "modules" / "case" / "api" / "quotations.py"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(not NODE, reason="需要 node")

HARNESS = r"""
const fs = require('fs')
const inp = JSON.parse(process.argv[2])
global.window = {}; global.MotrixLegalRound = { halfUp: (v) => Math.round(v) }
global.MotrixUI = { toast() {} }
global.document = { addEventListener() {}, querySelector() { return null } }
global.alpineStub = true
;(0, eval)(fs.readFileSync(process.argv[3], 'utf8'))
const merged = {}
for (const part of window.CM_PARTS) Object.defineProperties(merged, Object.getOwnPropertyDescriptors(part()))
const ctx = merged
ctx.session = { token: 't' }; ctx.selected = { quote_no: 'MQ-1' }
ctx.cr = { caseRecord: { materials: inp.local } }
ctx._segBase = { materials: JSON.stringify(inp.base) }; ctx._segFill = {}
ctx.badNum = {}; ctx.caseReadOnly = () => false
ctx.loadCaseHealth = () => {}; ctx.loadFinanceSummary = () => {}; ctx.flashSaved = () => {}
ctx._crForSave = function () { return this.cr.caseRecord }
const bodies = []
global.fetch = async (u, o) => { bodies.push(JSON.parse(o.body)); return { ok: true, json: async () => inp.response } }
;(async () => {
  await ctx._saveCaseRecordOnce()
  console.log(JSON.stringify({ local: ctx.cr.caseRecord.materials, base: ctx._segBase.materials === undefined ? null : JSON.parse(ctx._segBase.materials), baseStr: ctx._segBase.materials, sent: bodies[0] }))
})()
"""


def _run(**inp):
    out = subprocess.run([NODE, "-e", HARNESS, "x", json.dumps(inp), str(CORE)],
                         capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


@needs_node
def test_base_becomes_server_stored_value_when_server_rewrote_the_card():
    local = [{"id": "c1", "name": "A", "arrived": True, "poLink": {"key": "k", "arrivedOn": "2026-10-13"}}]
    stored = [{"id": "c1", "name": "A", "arrived": True,
               "poLink": {"key": "k", "arrivedOn": "2026-10-13", "arrivedBy": "u1", "arrivedAt": "2026-10-13 10:00:00"}}]
    out = _run(local=local, base=[{"id": "c1", "name": "A"}], response={"ok": True, "saved": {"materials": stored}})
    assert out["base"] == stored          # 否則下一次存檔 base≠資料庫現值 ⇒ 409
    assert out["local"] == stored         # 畫面還是剛送出的版本 ⇒ 一併換成伺服器版（否則之後每次存檔整段重送）


@needs_node
def test_base_keeps_sent_string_when_server_stored_the_same_content():
    local = [{"id": "c1", "name": "A", "n": 1}]
    same_other_order = [{"n": 1, "name": "A", "id": "c1"}]
    out = _run(local=local, base=[], response={"ok": True, "saved": {"materials": same_other_order}})
    assert out["baseStr"] == json.dumps(local, separators=(",", ":"))   # 鍵順序不同不算改寫：不讓每次存檔都重送該段


@needs_node
def test_saved_null_drops_base_key():
    out = _run(local=[{"id": "c1"}], base=[], response={"ok": True, "saved": {"materials": None}})
    assert out["base"] is None      # 伺服器上沒有這一段：基準鍵移除（比對把缺鍵視為 null）


@needs_node
def test_old_server_without_saved_field_still_uses_sent_content():
    local = [{"id": "c1", "name": "A"}]
    out = _run(local=local, base=[], response={"ok": True})
    assert out["base"] == local


def test_backend_returns_saved_segments():
    src = QUOTATIONS.read_text(encoding="utf-8")
    assert 'out["saved"] = {k: _saved_cr.get(k) for k in seg_keys}' in src
    assert "mask_case_record(_saved_cr" in src       # 與分段比對同一個遮蔽規則：回傳值必須等於下次 GET 看到的


ADOPT = r"""
const fs = require('fs')
const inp = JSON.parse(process.argv[2])
global.window = {}; global.MotrixLegalRound = { halfUp: (v) => Math.round(v) }
global.MotrixUI = { toast() {} }
global.document = { addEventListener() {}, querySelector() { return null } }
global.alpineStub = true
;(0, eval)(fs.readFileSync(process.argv[3], 'utf8'))
const merged = {}
for (const part of window.CM_PARTS) Object.defineProperties(merged, Object.getOwnPropertyDescriptors(part()))
const ctx = merged
ctx.cr = { caseRecord: { materials: inp.mats, materialOrders: inp.orders } }
ctx._segBase = { materials: JSON.stringify(inp.baseMats), materialOrders: JSON.stringify(inp.baseOrders) }
ctx._adoptSavedSegments(inp.saved)
console.log(JSON.stringify({ baseMats: JSON.parse(ctx._segBase.materials), baseOrders: JSON.parse(ctx._segBase.materialOrders), mats: ctx.cr.caseRecord.materials, orders: ctx.cr.caseRecord.materialOrders }))
"""


def _adopt(**inp):
    out = subprocess.run([NODE, "-e", ADOPT, "x", json.dumps(inp), str(CORE)],
                         capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


@needs_node
def test_material_order_save_updates_bases_to_server_value():
    m_old, m_new = [{"id": "c1"}], [{"id": "c1", "poLink": {"key": "k", "stale": True}}]
    o_old, o_new = [{"itemId": "a"}], [{"itemId": "a"}, {"itemId": "b"}]
    out = _adopt(mats=m_old, baseMats=m_old, orders=o_old, baseOrders=o_old, saved={"materials": m_new, "materialOrders": o_new})
    assert out["baseMats"] == m_new and out["baseOrders"] == o_new
    assert out["orders"] == o_new            # 使用者沒動過材料申請 ⇒ 畫面一併換新，免得下次存檔把舊清單送回去蓋掉
    assert out["mats"] == m_new              # 使用者沒動過材料卡片 ⇒ 畫面一併換新（審查必修：否則之後每次存檔整段重送）


@needs_node
def test_material_order_save_keeps_local_unsaved_cards():
    m_old, m_local = [{"id": "c1"}], [{"id": "c1", "name": "typed"}]
    out = _adopt(mats=m_local, baseMats=m_old, orders=[], baseOrders=[], saved={"materials": [{"id": "c1", "poLink": {"key": "k"}}]})
    assert out["mats"] == m_local and out["baseMats"] == [{"id": "c1", "poLink": {"key": "k"}}]


@needs_node
def test_material_order_save_keeps_local_unsaved_orders():
    o_old, o_local = [{"itemId": "a"}], [{"itemId": "a", "x": 1}]
    out = _adopt(mats=[], baseMats=[], orders=o_local, baseOrders=o_old, saved={"materialOrders": [{"itemId": "a"}, {"itemId": "b"}]})
    assert out["orders"] == o_local


def test_material_orders_endpoint_returns_saved_and_exec_adopts():
    src = (ROOT / "backend" / "modules" / "case" / "api" / "material_orders.py").read_text(encoding="utf-8")
    assert 'out["saved"] = {k: _cr.get(k) for k in ("materials", "materialOrders")}' in src
    assert "mask_case_record(_cr" in src
    exe = (ROOT / "frontend" / "js" / "case-management-exec.js").read_text(encoding="utf-8")
    assert "this._adoptSavedSegments(d.saved)" in exe
