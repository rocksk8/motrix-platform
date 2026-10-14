# -*- coding: utf-8 -*-
"""C1：案件頁「案件資訊」分頁的區塊（健康總覽、合約資訊、人員角色、專案期間、自訂欄位、個資告知、客戶回簽單）接上版面引擎（list `bizBlocks`）。

1. 登記：7 個區塊，核心＝合約資訊、人員角色、個資告知、客戶回簽單（不可隱藏）；fallback＝登記順序；每個區塊在頁面上都有綁定。
2. 旗標關閉：綁定回中性值（node 實跑）；fieldset 的 flex class 只在 ON 時加；:style 一律物件；x-show 不掛在帶行內 display 的元素。
3. 旗標開啟：隱藏的區塊 bShown 為假；順序用 order（區塊位置*10＋區塊內序號）；用真的版面 runtime 驗證。
4. 隱藏區塊的資料照樣存：發布隱藏專案期間之後，同一個分段以原值存檔不誤報 409、值不變。
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from core import customization, source_tree

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "backend" / "modules" / "case" / "module.json"
NODE = shutil.which("node")
BASE = "/api/definitions/layout/module:case"
PAGE = "case-management.html"
BLOCKS = ["health", "contract", "roles", "timeline", "customFields", "privacy", "signedBack"]
CORE = {"contract", "roles", "privacy", "signedBack"}


def _page():
    return source_tree.page_file(PAGE).read_text(encoding="utf-8")


def _biz():
    s = _page()
    a = s.index("<div x-show=\"activeTab==='biz'\">")
    return s[a:s.index("</div><!-- /biz -->", a)]


def _manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


# ── 1. 登記與綁定 ─────────────────────────────────────────────────────────
def test_manifest_blocks_and_core():
    m = _manifest()
    assert customization.validate_manifest(m) == []
    pg = [p for p in m["customization"]["pages"] if p["page"] == PAGE][0]
    lst = [x for x in pg["lists"] if x["key"] == "bizBlocks"][0]
    assert lst["entity"] == "block" and [c["field"] for c in lst["columns"]] == BLOCKS
    flags = {f["key"]: f["core"] for f in m["customization"]["fields"]["block"]}
    assert list(flags) == BLOCKS and {k for k, v in flags.items() if v} == CORE


def test_page_binds_every_movable_block_and_the_fallback_matches():
    biz = _biz()
    for blk, n in (("contract", 3), ("roles", 2), ("timeline", 3), ("customFields", 1), ("privacy", 1)):
        assert len(re.findall(r"bo\('%s', \d\)" % blk, biz)) == n, blk
    assert "bShown('health')" in biz and biz.count("bShown('timeline')") == 3 and "bShown('customFields')" in biz
    src = _page()
    fb = re.search(r"bizBlocks:\s*\[([^\]]*)\]", src).group(1)
    assert re.findall(r"'([^']+)'", fb) == BLOCKS
    # 核心區塊沒有 x-show 綁定（不可隱藏）；客戶回簽單固定在最下、健康總覽固定在最上
    assert "bShown('contract')" not in biz and "bShown('roles')" not in biz and "bShown('privacy')" not in biz and "bShown('signedBack')" not in src


def test_fieldset_is_a_flex_column_only_through_a_class_and_only_when_on():
    biz = _biz()
    assert biz.count(":class=\"{'cm-biz-lo': layoutOn}\"") == 1
    src = _page()
    assert ".cm-biz-lo{display:flex;flex-direction:column}" in src
    css = src[src.index("cm-layout-css"):src.index("cm-layout-css") + 400]
    assert "cm-biz-lo" in css                                                                  # class 的樣式只在版面啟動（旗標開）時才注入
    for m in re.finditer(r"<fieldset[^>]*>", biz):
        assert "display" not in m.group(0)                                                     # 不用行內 display（會和 x-show 互洗）


def test_all_layout_style_bindings_return_objects():
    src = _page()
    seg = src[src.index("  _bcols()"):src.index("  _bix(f)")]
    assert "[]" in seg
    assert "{ order: (this._bix(f) + 1) * 10 + (n || 0) } : {}" in src and "'order:" not in src[src.index("  _bcols()"):src.index("  _bcols()") + 900]


def test_flag_gated_x_show_has_no_static_inline_display():
    bad = []
    for m in re.finditer(r"<[a-zA-Z][^<>]*?>", _page(), re.S):
        tag = m.group(0)
        xs = re.search(r'x-show="([^"]*)"', tag)
        if not xs or not re.search(r"\b(?:[lfctb]Shown|cShown|tShown|bShown)\(|\blayoutOn\b", xs.group(1)):
            continue
        st = re.search(r'(?<![:\w-])style="([^"]*)"', tag)
        if st and re.search(r"(^|;)\s*display\s*:", st.group(1)):
            bad.append(re.sub(r"\s+", " ", tag)[:120])
    assert not bad, bad


# ── 2/3. node：中性值與 ON 的順序 ─────────────────────────────────────────
def _node(body, cols="[]"):
    from modules.case.tests import test_bp1_layout_cases_2026_10_14 as T
    return T._node(body, cols)


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_off_is_neutral_and_on_follows_the_layout():
    r = _node("const o2 = o\n"
              "console.log(JSON.stringify({ show: BL.map(f => o2.bShown(f)), bo: [o2.bo('contract', 1), o2.bo('timeline', 0)] }))".replace("BL", json.dumps(BLOCKS)))
    assert r == {"show": [True] * 7, "bo": [{}, {}]}                                           # 旗標關閉：全中性
    cols = json.dumps([{"field": f} for f in ("roles", "contract", "privacy", "customFields", "signedBack")])      # 健康總覽、專案期間被隱藏；角色移到最前
    r = _node("o.layoutOn = true\n"
              "console.log(JSON.stringify({ show: BL.map(f => o.bShown(f)), roles: [o.bo('roles', 0), o.bo('roles', 1)], contract: [o.bo('contract', 0), o.bo('contract', 2)],"
              " timeline: o.bo('timeline', 0), cf: o.bo('customFields', 0), privacy: o.bo('privacy', 0) }))".replace("BL", json.dumps(BLOCKS)), cols)
    assert r["show"] == [False, True, True, False, True, True, True]
    assert r["roles"] == [{"order": 10}, {"order": 11}] and r["contract"] == [{"order": 20}, {"order": 22}]       # 區塊位置*10＋區塊內序號
    assert r["timeline"] == {} and r["cf"] == {"order": 40} and r["privacy"] == {"order": 30}                    # 隱藏的區塊沒有 order


# ── 3b. API＋真的 runtime ─────────────────────────────────────────────────
def _h(client, make_user, name, role="superadmin"):
    u, p = make_user(name, "Lay-Pass-123", role=role)[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _col(f):
    return "case:%s/list:bizBlocks/column:%s" % (PAGE, f)


def _publish(client, h, ops):
    r = client.put(BASE + "/draft", headers=h, params={"scope": "company"}, json={"body": {"ops": ops}})
    assert r.status_code == 200, r.text
    return client.post(BASE + "/publish", headers=h, params={"scope": "company"}, json={"note": "t"})


def test_core_blocks_cannot_be_hidden_or_renamed_but_others_can(client, make_user):
    boss = _h(client, make_user, "c1_boss")
    for f in sorted(CORE):
        assert _publish(client, boss, [{"op": "hide", "target": _col(f)}]).status_code == 422, f
        assert _publish(client, boss, [{"op": "relabel", "target": _col(f), "label": "x"}]).status_code == 422, f
    ok = [{"op": "hide", "target": _col("health")}, {"op": "hide", "target": _col("timeline")}, {"op": "relabel", "target": _col("customFields"), "label": "專案備註"}]
    assert _publish(client, boss, ok).status_code == 200


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
  console.log(JSON.stringify({ cols: L.cols('bizBlocks').map(c => c.field), label: L.colLabel('bizBlocks', 'customFields', 'D') })) })().catch(e => { console.error(String(e)); process.exit(1) })
"""


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_real_runtime_applies_hide_relabel_and_reorder(client, make_user, tmp_path):
    boss = _h(client, make_user, "c1_rt")
    ops = [{"op": "hide", "target": _col("health")}, {"op": "relabel", "target": _col("customFields"), "label": "專案備註"},
           {"op": "reorder", "target": "case:%s/list:bizBlocks" % PAGE, "order": [_col(f) for f in ("roles", "contract", "timeline", "customFields", "privacy", "signedBack", "health")]}]
    assert _publish(client, boss, ops).status_code == 200
    pf = tmp_path / "p.json"
    pf.write_text(json.dumps(client.get("/api/layout/case", headers=boss).json()), encoding="utf-8")
    out = subprocess.run([NODE, "-e", _RUNTIME, str(ROOT / "frontend/static/custom-layout.js"), str(ROOT / "frontend/static/layout-runtime.js"), str(pf)],
                         capture_output=True, timeout=30)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[:1500]
    r = json.loads(out.stdout.decode("utf-8"))
    assert r["cols"] == ["roles", "contract", "timeline", "customFields", "privacy", "signedBack"] and r["label"] == "專案備註"


# ── 4. 隱藏區塊的資料照樣存 ───────────────────────────────────────────────
def test_hidden_block_values_still_save_unchanged_without_false_409(client, make_user):
    import db
    from tests.platform import _response_keys as RK
    boss = _h(client, make_user, "c1_save")
    conn = db.get_db()
    try:
        RK.seed_every_table(conn)
        qn = conn.execute("SELECT quote_no FROM quotations ORDER BY id LIMIT 1").fetchone()[0]
        d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (qn,)).fetchone()[0] or "{}")
        d.setdefault("caseRecord", {})["projectTimeline"] = {"startDate": "2026-10-01", "endDate": "2026-12-31"}
        conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), qn))
        conn.commit()
    finally:
        conn.close()
    assert _publish(client, boss, [{"op": "hide", "target": _col("timeline")}]).status_code == 200      # 專案期間區塊被版面隱藏
    seg = {"startDate": "2026-10-01", "endDate": "2026-12-31"}
    for _ in range(3):                                                                                   # 連存三次、以原值存
        r = client.patch("/api/quotations/%s/case-record" % qn, headers=boss,
                         json={"segments": {"projectTimeline": seg}, "base": {"projectTimeline": seg}, "defaults": {}})
        assert r.status_code == 200, r.text
    got = client.get("/api/quotations/" + qn, headers=boss).json()["data"]["caseRecord"]["projectTimeline"]
    assert got["startDate"] == "2026-10-01" and got["endDate"] == "2026-12-31"
    # 區塊用 x-show／x-if 隱藏（輸入框仍在 DOM，x-model 的資料不變）；沒有任何 destroy／清空資料的呼叫
    biz = _biz()
    assert "cr.caseRecord.projectTimeline.startDate = ''" not in biz and "delete cr.caseRecord" not in biz


def test_registry_note_describes_blocks_and_limits():
    reg = {e["flag"]: e for e in json.loads((ROOT / "frontend" / "static" / "layout-pages.json").read_text(encoding="utf-8"))}
    txt = " ".join(reg["case_management"]["notes"])
    assert "區塊" in txt and "核心區塊" in txt and "健康總覽固定在最上" in txt and "照樣保存" in txt
