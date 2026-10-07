# -*- coding: utf-8 -*-
"""材料卡片自動連結（前端 mlAutoLinkMaterials）：用 node 直接執行 case-management-mlink.js 的函式（不開瀏覽器、不碰資料庫）。"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
JS = ROOT / "frontend" / "js" / "case-management-mlink.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="需要 node")

HARNESS = r"""
const fs = require('fs'); const src = fs.readFileSync(process.argv[2], 'utf8'); const inp = JSON.parse(process.argv[3])
global.window = {}; eval(src); const part = window.CM_PARTS[0]()
const ctx = Object.assign({}, part, { cr: { caseRecord: { materials: inp.mats } }, materialOrders: inp.orders, moApprovals: inp.apps, moCanEdit() { return inp.canEdit !== false }, dirty: 0, setDirty() { this.dirty++ } })
const n = part.mlAutoLinkMaterials.call(ctx)
console.log(JSON.stringify({ n, links: inp.mats.map(m => m.orderItemId || ''), dirty: ctx.dirty }))
"""


def _run(mats, orders, apps, can_edit=True):
    out = subprocess.run([NODE, "-e", HARNESS, "x", str(JS), json.dumps({"mats": mats, "orders": orders, "apps": apps, "canEdit": can_edit})],
                         capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return json.loads(out)


def _o(i, name, po="PO-1", saved=True):
    return {"itemId": i, "itemName": name, "poDocCode": po, "_saved": saved}


OK = {"o1": {"status": "已核准"}, "o2": {"status": "已核准"}}


def test_unique_match_links_and_dirties():
    r = _run([{"id": "m1", "name": " 交換器 "}], [_o("o1", "交換器")], OK)
    assert r == {"n": 1, "links": ["o1"], "dirty": 1}


def test_no_match_or_no_po_or_not_approved_stays_manual():
    assert _run([{"id": "m1", "name": "線材"}], [_o("o1", "交換器")], OK)["links"] == [""]
    assert _run([{"id": "m1", "name": "交換器"}], [_o("o1", "交換器", po="")], OK)["links"] == [""]
    assert _run([{"id": "m1", "name": "交換器"}], [_o("o1", "交換器")], {"o1": {"status": "待審核"}})["links"] == [""]
    assert _run([{"id": "m1", "name": "交換器"}], [_o("o1", "交換器", saved=False)], OK)["links"] == [""]


def test_multiple_matches_stays_manual():
    r = _run([{"id": "m1", "name": "交換器"}], [_o("o1", "交換器"), _o("o2", "交換器")], OK)
    assert r["links"] == [""] and r["dirty"] == 0


def test_already_linked_or_taken_by_other_card():
    r = _run([{"id": "m1", "name": "交換器", "orderItemId": "o1"}, {"id": "m2", "name": "交換器"}], [_o("o1", "交換器")], OK)
    assert r["links"] == ["o1", ""] and r["n"] == 0
    r = _run([{"id": "m1", "name": "A"}], [_o("o1", "A")], OK)
    assert "ordered" not in json.dumps(r)                                   # 不動已申購／已到料


def test_read_only_role_never_links_or_dirties():
    r = _run([{"id": "m1", "name": "交換器"}], [_o("o1", "交換器")], OK, can_edit=False)
    assert r == {"n": 0, "links": [""], "dirty": 0}


def test_only_called_on_load_path_not_after_every_action():
    import re
    src = (ROOT / "frontend" / "js" / "case-management-exec.js").read_text(encoding="utf-8")
    assert len(re.findall(r"mlAutoLinkMaterials\(\)", src)) == 1
    assert "this.mlAutoLinkMaterials) this.mlAutoLinkMaterials()" in src.split("async loadMoApprovals")[0]
