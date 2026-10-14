# -*- coding: utf-8 -*-
"""C3：案件頁區塊標題改名（專案期間、自訂欄位）與按鈕登記（只登記「從報價單帶入」一顆）；編輯器標出「固定位置」與「改名無效」。
OFF 中性；ON 以真的版面 runtime 驗證 action 的隱藏／改名／順序；核心項目不可改；沒有登記有金額／簽核／法定語意的按鈕。"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from core import customization, source_tree

ROOT = Path(__file__).resolve().parents[3]
NODE = shutil.which("node")
PAGE = "case-management.html"
BASE = "/api/definitions/layout/module:case"


def _page():
    return source_tree.page_file(PAGE).read_text(encoding="utf-8")


def _manifest():
    return json.loads((ROOT / "backend" / "modules" / "case" / "module.json").read_text(encoding="utf-8"))


def test_actions_are_register_only_and_just_one_button():
    m = _manifest()
    assert customization.validate_manifest(m) == []
    pg = [p for p in m["customization"]["pages"] if p["page"] == PAGE][0]
    assert [a["key"] for a in pg["actions"]] == ["fillContract"] and "endpoint" not in pg["actions"][0]
    src = _page()
    assert "aShown('fillContract')" in src and "aOrder('fillContract')" in src and "aLabel('fillContract'," in src
    assert len(re.findall(r"\baShown\(", src)) == 2                                          # 定義一次＋使用一次：沒有其他按鈕被綁定
    for forbidden in ("列印告知書", "刪除", "結案", "核准"):                                      # 法定／金額／流程語意的按鈕不登記
        assert forbidden not in json.dumps(pg["actions"], ensure_ascii=False)


def test_block_titles_bind_the_layout_label():
    src = _page()
    assert "bLabel('timeline', secLabel('timeline', '專案期間'))" in src and "bLabel('customFields', '自訂欄位')" in src
    assert "bLabel(f, dflt) { return this.layoutOn ?" in src


def test_editor_shows_fixed_positions_without_arrows():
    ed = (ROOT / "frontend" / "static" / "layout-editor.js").read_text(encoding="utf-8")
    assert ":draggable=\"!fixedPos(lk, c)\"" in ed and 'x-show="!fixedPos(lk, c)"' in ed and "（固定位置）" in ed
    reg = {e["flag"]: e for e in json.loads((ROOT / "frontend" / "static" / "layout-pages.json").read_text(encoding="utf-8"))}
    assert reg["case_management"]["fixedOrder"] == {"bizBlocks": ["health", "signedBack"]} and reg["quotations"]["fixedOrder"] == {"quotes": "all"}
    assert "bizBlocks:health" in reg["case_management"]["relabelIneffective"]


def _node(body, cols="[]"):
    from modules.case.tests import test_bp1_layout_cases_2026_10_14 as T
    return T._node(body, cols)


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_off_is_neutral():
    r = _node("console.log(JSON.stringify({ s: o.aShown('fillContract'), o: o.aOrder('fillContract'), a: o.aLabel('fillContract', '從報價單帶入'),"
              " l: o.bLabel('customFields', '自訂欄位'), t: o.bLabel('timeline', '專案期間') }))")
    assert r == {"s": True, "o": {}, "a": "從報價單帶入", "l": "自訂欄位", "t": "專案期間"}


def _h(client, make_user, name):
    u, p = make_user(name, "Lay-Pass-123", role="superadmin")[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _publish(client, h, ops):
    r = client.put(BASE + "/draft", headers=h, params={"scope": "company"}, json={"body": {"ops": ops}})
    assert r.status_code == 200, r.text
    return client.post(BASE + "/publish", headers=h, params={"scope": "company"}, json={"note": "t"})


_RUNTIME = r"""
const fs = require('fs')
const payload = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'))
global.window = global
const listeners = []
global.localStorage = { getItem(k) { return k === 'motrix_session' ? JSON.stringify({ token: 't', role: 'superadmin' }) : null } }
global.document = { addEventListener(n, f) { if (n === 'alpine:init') listeners.push(f) }, getElementById() { return null }, head: { appendChild() {} },
  documentElement: { setAttribute() {} }, querySelectorAll() { return [] }, createElement() { return { id: '', textContent: '' } } }
const stores = {}
global.Alpine = { store(n, v) { if (v !== undefined) stores[n] = v; return stores[n] } }
global.fetch = async () => ({ ok: true, json: async () => payload })
eval(fs.readFileSync(process.argv[1], 'utf8')); eval(fs.readFileSync(process.argv[2], 'utf8'))
MotrixLayout.init({ module: 'case', page: 'case-management.html', deferred: true, fallback: { lists: {} } })
listeners.forEach(f => f())
;(async () => { await MotrixLayout.start(); const L = Alpine.store('layout')
  console.log(JSON.stringify({ shown: L.shown('action', 'fillContract'), label: L.label('action', 'fillContract', '從報價單帶入'),
    blk: L.colLabel('bizBlocks', 'customFields', '自訂欄位'), tl: L.colLabel('bizBlocks', 'timeline', '專案期間') })) })().catch(e => { console.error(String(e)); process.exit(1) })
"""


@pytest.mark.skipif(NODE is None, reason="沒有 node")
@pytest.mark.parametrize("hide", [False, True])
def test_real_runtime_applies_action_and_block_label_ops(client, make_user, tmp_path, hide):
    boss = _h(client, make_user, "c3_rt_%d" % hide)
    aid = "case:%s/action:fillContract" % PAGE
    ops = [{"op": "relabel", "target": aid, "label": "帶入報價資料"}, {"op": "relabel", "target": "case:%s/list:bizBlocks/column:customFields" % PAGE, "label": "專案備註"},
           {"op": "relabel", "target": "case:%s/list:bizBlocks/column:timeline" % PAGE, "label": "工期"}]
    if hide:
        ops.append({"op": "hide", "target": aid})
    assert _publish(client, boss, ops).status_code == 200
    pf = tmp_path / "p.json"
    pf.write_text(json.dumps(client.get("/api/layout/case", headers=boss).json()), encoding="utf-8")
    out = subprocess.run([NODE, "-e", _RUNTIME, str(ROOT / "frontend/static/custom-layout.js"), str(ROOT / "frontend/static/layout-runtime.js"), str(pf)],
                         capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[:1500]
    r = json.loads(out.stdout.decode("utf-8"))
    assert r["shown"] is (not hide) and r["label"] == "帶入報價資料" and r["blk"] == "專案備註" and r["tl"] == "工期"
