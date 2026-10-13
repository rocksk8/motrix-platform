# -*- coding: utf-8 -*-
"""第 51 班：材料卡片『對應材料申請』下拉列出『已核准採購單、尚未帶入材料申請』的候選；選取＝認列該採購單（T57；不再建立草稿列）（node 直接執行 mlink.js，不開瀏覽器）。"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
JS = ROOT / "frontend" / "js" / "case-management-mlink.js"
from core import source_tree as _st  # noqa: E402
HTML = _st.page_file("case-management.html")
EXEC = ROOT / "frontend" / "js" / "case-management-exec.js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(not NODE, reason="需要 node")

HARNESS = r"""
const fs = require('fs'); const src = fs.readFileSync(process.argv[2], 'utf8'); const inp = JSON.parse(process.argv[3])
global.window = {}; global.MotrixLegalRound = { halfUp: (v) => Math.round(v) }; eval(src); const part = window.CM_PARTS[0]()
let n = 0
const ctx = Object.assign({}, part, { materialOrders: inp.orders || [], mlGroups: inp.groups, moCanEdit() { return inp.canEdit !== false },
  _moNewId() { return 'new' + (++n) }, dirty: 0, setDirty() { this.dirty++ }, moDirty: false, moMsg: '' })
const out = {}
for (const step of inp.steps) {
  if (step[0] === 'cands') out.cands = ctx.mlCandidatesFor(step[1]).map(g => g.key)
  if (step[0] === 'pick') out.pick = ctx.mlPickCandidate(step[1], step[2])
  if (step[0] === 'change') ctx.mlOnLinkChange(step[1])
  if (step[0] === 'unrecognize') ctx.mlUnrecognize(step[1])
}
out.mat = (inp.steps.find(st => st[1] && typeof st[1] === 'object' && st[0] !== 'cands') || inp.steps[0])[1]
out.orders = ctx.materialOrders.map(o => [o.itemId, o.itemName, o.poDocCode, o.totalPrice, o._saved])
out.msg = ctx.mlMsg; out.dirty = ctx.dirty; out.moDirty = ctx.moDirty
console.log(JSON.stringify(out))
"""


def _run(groups, steps, orders=None, can_edit=True):
    out = subprocess.run([NODE, "-e", HARNESS, "x", str(JS), json.dumps({"groups": groups, "steps": steps, "orders": orders or [], "canEdit": can_edit})],
                         capture_output=True, text=True, encoding="utf-8", check=True, timeout=30).stdout
    return json.loads(out)


def _g(key, name, po="PO-1", **kw):
    d = {"key": key, "name": name, "quantity": 2, "unit": "台", "unitPrice": 100, "totalPrice": 200, "docCodes": [po], "poDocCode": po, "poLine": 1,
         "lineCount": 1, "quoteItemId": "q-" + key, "existing": None}
    d.update(kw)
    return d


@needs_node
def test_candidate_matches_by_name_or_model_ignoring_case_and_spaces():
    gs = [_g("a", "交換器 X1"), _g("b", "線材")]
    assert _run(gs, [["cands", {"name": " 交換器  x1 "}]])["cands"] == ["a"]
    assert _run(gs, [["cands", {"name": "交換器", "model": "X1"}]])["cands"] == ["a"]
    assert _run(gs, [["cands", {"name": "不相干"}]])["cands"] == []
    assert _run(gs, [["cands", {"name": ""}]])["cands"] == []


@needs_node
def test_groups_with_existing_request_or_already_imported_draft_are_not_candidates():
    gs = [_g("a", "A", existing={"docCode": "MR-1", "status": "已核准"}), _g("b", "A")]
    drafts = [{"itemId": "d", "quoteItemId": "q-b", "_saved": False, "poDocCode": "PO-1"}]
    assert _run(gs, [["cands", {"name": "A"}]], orders=drafts)["cands"] == []


@needs_node
def test_already_linked_or_read_only_card_has_no_candidates():
    gs = [_g("a", "A")]
    assert _run(gs, [["cands", {"name": "A", "orderItemId": "o1"}]])["cands"] == []
    assert _run(gs, [["cands", {"name": "A"}]], can_edit=False)["cands"] == []


@needs_node
def test_amount_visibility_is_not_needed_to_recognize():
    # T57 認列：只連結、不帶金額，所以看不到金額的帳號也有候選（誰能認列由伺服器的 who_may 決定）
    assert _run([_g("a", "A", totalPrice=None)], [["cands", {"name": "A"}]])["cands"] == ["a"]
    assert _run([_g("a", "A")], [["cands", {"name": "A"}]])["cands"] == ["a"]


@needs_node
def test_pick_recognizes_po_ticks_ordered_and_creates_no_draft_row():
    mat = {"name": "A", "ordered": False, "arrived": False, "orderItemId": "g:a", "supplier": ""}
    r = _run([_g("a", "A", vendor="某廠商")], [["change", mat], ["cands", mat]])
    assert r["orders"] == [] and r["moDirty"] is False and r["dirty"] == 1                 # 不再建立前端草稿列
    m = r["mat"]
    assert m["poLink"]["key"] == "a" and m["poLink"]["vendor"] == "某廠商" and m["orderItemId"] == "" and m["ordered"] is True and m["supplier"] == "某廠商"
    assert r["cands"] == []                                                                  # 已認列 ⇒ 不再有候選
    assert "已認列" in r["msg"]


@needs_node
def test_recognized_group_is_blocked_for_other_cards_and_unrecognize_clears_flags():
    mat = {"name": "A", "orderItemId": "g:a"}
    gs = [_g("a", "A", recognized="c9", existing={"itemId": "", "docCode": "", "status": "已認列"})]
    r = _run(gs, [["cands", {"name": "A"}], ["change", mat]])
    assert r["cands"] == [] and "poLink" not in r["mat"] and "已認列" in r["msg"]
    m2 = {"name": "A", "poLink": {"key": "a"}, "ordered": True, "arrived": True, "orderItemId": ""}
    r = _run([_g("a", "A")], [["unrecognize", m2]])
    assert r["mat"]["poLink"] is None and r["mat"]["ordered"] is False and r["mat"]["arrived"] is False


@needs_node
def test_pick_without_edit_right_is_refused():
    r = _run([_g("a", "A")], [["change", {"name": "A", "orderItemId": "g:a"}]], can_edit=False)
    assert r["orders"] == [] and "poLink" not in r["mat"]


@needs_node
def test_normal_selection_keeps_old_behaviour():
    r = _run([_g("a", "A")], [["change", {"name": "A", "orderItemId": "o1"}]])
    assert r["orders"] == [] and r["dirty"] == 1


def test_markup_and_load_path_wired():
    h = HTML.read_text(encoding="utf-8")
    assert '@change="mlOnLinkChange(mat)"' in h and 'data-testid="mat-order-candidate"' in h and 'data-testid="mat-order-oneclick"' in h
    e = EXEC.read_text(encoding="utf-8")
    assert e.count("mlLoadGroups(quoteNo)") == 1 and e.index("mlLoadGroups(quoteNo)") < e.index("mlAutoLinkMaterials()")
