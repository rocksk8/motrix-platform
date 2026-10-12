# -*- coding: utf-8 -*-
"""M3 T3（T57）：擇一方案『計入品項』前後端同式。同一份黃金向量 tests/data/quote_alt_vectors.json：
後端 profit_guard.counted_items／server_totals／server_profit 與前端 static/alt-items.js（node 載入）逐案比對。
前端 calcTotals 的接線隨 T6（表單 UI＋FORM_VERSION 升版）一起進，這裡只守計算規則本身。"""
import json
import pathlib
import shutil
import subprocess

import pytest

from modules.case import profit_guard as PG

ROOT = pathlib.Path(__file__).resolve().parents[2]
VECTORS = json.loads((pathlib.Path(__file__).parent / "data" / "quote_alt_vectors.json").read_text(encoding="utf-8"))["cases"]
NODE = shutil.which("node")


def test_vectors_cover_the_edge_cases():
    names = {c["name"] for c in VECTORS}
    assert {"no_alt", "all_unpicked", "one_group_picked", "both_picked", "pick_other_group_item", "unknown_group_pick",
            "group_trimmed", "header_altgroup_is_plain", "numeric_id_vs_string_pick"} <= names


@pytest.mark.parametrize("c", VECTORS, ids=[c["name"] for c in VECTORS])
def test_backend_matches_vectors(c):
    q = c["q"]
    assert [i["id"] for i in PG.counted_items(q)] == c["expect"]["ids"]
    t = PG.server_totals(q)
    p = PG.server_profit(dict(q, tot=t), 25, 2, pretax=t["pretax"], total=t["total"])
    assert t["subtotal"] == c["expect"]["subtotal"] and p["totalCost"] == c["expect"]["totalCost"]


_JS = r"""
const fs = require('fs')
const A = require(process.argv[2])
const cases = JSON.parse(fs.readFileSync(process.argv[3], 'utf8')).cases
const out = cases.map(c => {
  const items = A.countedItems(c.q)
  const sum = (f) => items.reduce((s, i) => s + (i.type === 'header' ? 0 : f(i)), 0)
  return { ids: items.map(i => i.id), subtotal: sum(i => (i.qty || 0) * (i.unitPrice || 0)), totalCost: sum(i => (i.qty || 0) * (i.cost || 0)) }
})
process.stdout.write(JSON.stringify(out))
"""


@pytest.mark.skipif(not NODE, reason="沒有 node：前端等值題略過（同 profit-rules 前例）")
def test_frontend_js_equals_vectors(tmp_path):
    runner = tmp_path / "run_alt_items.js"
    runner.write_text(_JS, encoding="utf-8")
    cp = subprocess.run([NODE, str(runner), str(ROOT / "frontend/static/alt-items.js"),
                         str(pathlib.Path(__file__).parent / "data" / "quote_alt_vectors.json")],
                        capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert cp.returncode == 0, cp.stderr
    got = json.loads(cp.stdout)
    bad = [(c["name"], g, c["expect"]) for c, g in zip(VECTORS, got) if g != c["expect"]]
    assert len(got) == len(VECTORS) and not bad, bad[:3]


@pytest.mark.skipif(not NODE, reason="沒有 node")
def test_frontend_helpers_and_no_mutation(tmp_path):
    js = r"""
const A = require(process.argv[2])
const q = {items:[{id:'a'},{id:'x1',altGroup:'G'},{id:'x2',altGroup:'G'},{id:'y1',altGroup:'H'},{id:'y2',altGroup:'H'}], altPicks:{G:'x1'}}
const snap = JSON.stringify(q)
const r = {unpicked: A.unpickedGroupCount(q), u1: A.isUncounted(q, q.items[1]), u2: A.isUncounted(q, q.items[2]), u0: A.isUncounted(q, q.items[0]),
  over: A.countedItems(q, {G:'x2', H:'y1'}).map(i=>i.id), same: JSON.stringify(q) === snap}
process.stdout.write(JSON.stringify(r))
"""
    runner = tmp_path / "h.js"
    runner.write_text(js, encoding="utf-8")
    cp = subprocess.run([NODE, str(runner), str(ROOT / "frontend/static/alt-items.js")], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert cp.returncode == 0, cp.stderr
    assert json.loads(cp.stdout) == {"unpicked": 1, "u1": False, "u2": True, "u0": False, "over": ["a", "x2", "y1"], "same": True}
