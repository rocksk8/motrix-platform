# -*- coding: utf-8 -*-
"""T65 C1：報價單清單的個人檢視偏好（設定中心 list_view）。預設全關＝與今天相同；個人只能在公司允許的範圍內縮小／重排；金額欄位只能隱藏或調順序。"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

from helpers import settings_groups  # noqa: F401
from helpers import settings_registry as SR

FRONT = pathlib.Path(__file__).resolve().parents[3] / "frontend"
PAGE = (FRONT / "pages" / "quotations.html").read_text(encoding="utf-8")
JS = FRONT / "static" / "list-view-prefs.js"
OPTS = ("quotes_personal_columns", "quotes_personal_default_tab", "quotes_personal_page_size")


def test_group_defaults_are_off_and_core_owned():
    g = SR._g("list_view")
    assert set(g["fields"]) == set(OPTS)
    for k in OPTS:
        f = g["fields"][k]
        assert f.default == 0 and f.type == "int" and f.risk == "none" and not f.loosen
        for txt in (f.question, f.label, f.help, f.impact):
            assert "_" not in txt and k not in txt
        assert "金額" in f.impact or "頁籤" in f.impact or "筆" in f.impact
        assert SR.get("list_view", k) == 0
    assert SR.groups()["list_view"]["owner"] == "core"


def test_every_option_has_a_consumer_in_the_page():
    for k in OPTS:
        assert "lv.%s === 1" % k in PAGE, k


def test_off_state_adds_no_request_and_no_script_tag():
    # 關閉時：頁面不靜態載入偏好腳本；list_view 只在版面旗標開啟後才讀；原本的 builder_layout 讀取不變
    assert '<script src="../static/list-view-prefs.js">' not in PAGE
    assert "read(['builder_layout'], { token: tk })" in PAGE and "read(['builder_layout', 'list_view']" not in PAGE
    assert PAGE.index("this.layoutOn = true") < PAGE.index("await this.initListView(tk)")
    assert "if (!this.lvAny) return" in PAGE


def test_company_layout_still_wins_over_personal_hide():
    # 個人只能再隱藏：cShown ＝ 公司版面允許 AND 不在個人隱藏名單
    assert re.search(r"cShown\(f\) \{ return \(!this\.layoutOn \|\| this\._qcols\(\)\.some\(c => c\.field === f\)\) && !\(this\.lvOn\.columns && this\.pv\.hidden\.includes\(f\)\)", PAGE)
    assert PAGE.count('data-col="') == 20
    for k in ("quoteNo", "customer", "project", "amount", "margin", "validDays", "filler", "status", "dealTag", "date"):
        assert PAGE.count('data-col="%s"' % k) == 2, k      # 表頭一格、資料列一格


def test_paging_never_applies_to_custom_drag_sort_and_needs_the_option():
    assert re.search(r"get pageSize\(\) \{ return \(this\.lvOn\.size && this\.sortPref\.sortMode !== 'custom' && \[25, 50, 100, 200\]\.includes\(this\.pv\.size\)\) \? this\.pv\.size : 0 \}", PAGE)
    assert "items: this.pagedFiltered," in PAGE and "items: this.filtered," not in PAGE


NODE = shutil.which("node")


def _run(js):
    boot = "global.window = global; global.document = {}; require(%s);\nconst L = window.MotrixListView;\n" % json.dumps(str(JS))
    r = subprocess.run([NODE, "-e", boot + js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skipif(not NODE, reason="needs node")
def test_sanitize_only_shrinks_or_reorders_within_the_allowed_set():
    out = _run("""
const t = ['all', '草稿', '已結案'];
const bad = L.sanitize({ hidden: ['quoteNo', 'status', 'amount', 'nope', 'amount'], order: ['date', 'ghost', 'amount', 'date'], tab: 'not-a-tab', size: 77 }, { tabs: t });
const good = L.sanitize({ hidden: ['margin'], order: ['margin', 'amount'], tab: '已結案', size: 50 }, { tabs: t });
console.log(JSON.stringify({ bad, good, def: L.sanitize(null, { tabs: t }), empty: L.empty() }))""")
    assert out["bad"]["hidden"] == ["amount"]                                     # 必要欄位不可隱藏、未知欄位丟掉、去重
    assert out["bad"]["order"][:2] == ["date", "amount"] and sorted(out["bad"]["order"]) == sorted(out["empty"]["order"])     # 只重排，不增減
    assert out["bad"]["tab"] == "" and out["bad"]["size"] == 0                    # 不在允許集合 ⇒ 退回預設
    assert out["good"] == {"hidden": ["margin"], "order": out["good"]["order"], "tab": "已結案", "size": 50}
    assert out["good"]["order"][:2] == ["margin", "amount"]
    assert out["def"] == out["empty"]
    assert out["empty"] == {"hidden": [], "order": ["quoteNo", "customer", "project", "amount", "margin", "validDays", "filler", "status", "dealTag", "date"], "tab": "", "size": 0}


@pytest.mark.skipif(not NODE, reason="needs node")
def test_serialize_parse_roundtrip_and_old_payloads_fall_back():
    out = _run("""
const o = { hidden: ['amount'], order: L.COLS.slice().reverse(), tab: '草稿', size: 100 };
const p = L.serialize(o);
console.log(JSON.stringify({ cols: L.COLS, rt: L.parse(p), old: L.parse({ sortMode: 'total', sortDir: 'asc', customOrder: ['MQ-1', 'MQ-2'] }), none: L.parse(null), put: p }))""")
    assert out["rt"] == {"hidden": ["amount"], "order": list(reversed(out["cols"])), "tab": "草稿", "size": 100}
    assert out["old"] == out["none"]                                              # 沒有 k=v 的舊排序資料 ⇒ 預設
    assert out["put"]["sortMode"] == "view" and all(isinstance(x, str) and "=" in x for x in out["put"]["customOrder"])


@pytest.mark.skipif(not NODE, reason="needs node")
def test_reorder_moves_only_data_col_cells_and_is_idempotent():
    out = _run("""
function cell(col) { return { dataset: col ? { col } : {}, id: col || 'x', nextSibling: null }; }
function row(cols, lead, tail) {
  const kids = [].concat(lead ? [cell(null)] : [], cols.map(cell), tail ? [cell(null)] : []);
  const tr = { children: kids, insertBefore(c, anchor) { const i = this.children.indexOf(c); this.children.splice(i, 1); const j = anchor ? this.children.indexOf(anchor) : this.children.length; this.children.splice(j, 0, c); this._n = (this._n || 0) + 1 } };
  kids.forEach((k, i) => Object.defineProperty(k, 'nextSibling', { get() { return tr.children[tr.children.indexOf(k) + 1] || null } }));
  return tr;
}
const r1 = row(['quoteNo', 'customer', 'amount', 'date'], true, true);
const table = { querySelectorAll: () => [r1] };
L.reorder(table, ['date', 'amount', 'customer', 'quoteNo']);
const a = r1.children.map(c => c.id);
const n1 = r1._n;
L.reorder(table, ['date', 'amount', 'customer', 'quoteNo']);
console.log(JSON.stringify({ a, again: r1._n === n1 }))""")
    assert out["a"] == ["x", "date", "amount", "customer", "quoteNo", "x"]        # 抓手欄與操作欄留在原位
    assert out["again"] is True                                                    # 已是該順序就不再動 DOM（避免觀察器無限更新）


def test_prefs_use_the_existing_list_prefs_route_and_no_new_route():
    src = JS.read_text(encoding="utf-8")
    assert "/api/list-prefs/" in src and src.count("fetch(") == 2
    assert "quotations.view" in PAGE
