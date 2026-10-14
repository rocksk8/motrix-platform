# -*- coding: utf-8 -*-
"""版面頁面登錄（frontend/static/layout-pages.json）＝單一來源：設定中心旗標、編輯器提示、頁面接線都由它對齊。
新增一頁（顧客、報價…）＝加一筆登錄＋該頁接線；這裡的題目會逐項指出少了哪一塊。"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from core import customization, source_tree

ROOT = Path(__file__).resolve().parents[2].parent
REG = json.loads((ROOT / "frontend" / "static" / "layout-pages.json").read_text(encoding="utf-8"))
MODS = ROOT / "backend" / "modules"
EDITOR = (ROOT / "frontend" / "static" / "layout-editor.js").read_text(encoding="utf-8")
NODE = shutil.which("node")
KEYS = {"flag", "module", "page", "pageLabel", "flagLabel", "question", "help", "impact", "offLabel", "offText",
        "onLabel", "onText", "relabelIneffective", "notes"}


def _manifest(e):
    return json.loads((MODS / e["module"] / "module.json").read_text(encoding="utf-8"))


def _page_entry(e):
    return [p for p in _manifest(e)["customization"]["pages"] if p["page"] == e["page"]][0]


def test_registry_shape_and_uniqueness():
    assert len(REG) >= 5
    for e in REG:
        assert set(e) - {"fixedOrder"} == KEYS, e["flag"]
        assert set(e.get("fixedOrder", {})) <= {l["key"] for l in _page_entry(e)["lists"]}      # 固定位置只能指到本頁的清單
        assert isinstance(e["relabelIneffective"], dict) and isinstance(e["notes"], list)
    assert len({e["flag"] for e in REG}) == len(REG)
    assert len({(e["module"], e["page"]) for e in REG}) == len(REG)


def test_settings_group_is_generated_from_the_registry():
    from helpers import settings_groups  # noqa: F401
    from helpers import settings_registry as r
    g = r.groups()["builder_layout"]
    assert [f["key"] for f in g["fields"]] == [e["flag"] for e in REG]
    assert all(f["default"] is False for f in g["fields"])


@pytest.mark.parametrize("e", REG, ids=lambda e: e["flag"])
def test_each_entry_is_wired(e):
    m = _manifest(e)
    assert customization.validate_manifest(m) == []
    pg = _page_entry(e)
    ents = {lst["entity"] for lst in pg["lists"]}                    # 只看這一頁的清單用到的實體（不同頁可有同名欄位）
    fields = {f["key"]: f for e in ents for f in m["customization"]["fields"][e]}
    listed = {c["field"] for lst in pg["lists"] for c in lst["columns"]}
    for k in e["relabelIneffective"]:
        lk, _, fld = k.rpartition(":")
        pool = {c["field"] for lst in pg["lists"] if (not lk or lst["key"] == lk) for c in lst["columns"]}
        assert fld in pool, "%s 不是這頁列表的欄位" % k
        flags = {f["key"]: f for ent in ents for f in m["customization"]["fields"][ent]}
        assert not flags[fld]["core"], "%s 是核心欄位（本來就不能改名），不必登記" % k
    html = source_tree.page_file(e["page"]).read_text(encoding="utf-8")
    assert "page: '%s'" % e["page"] in html and "deferred: true" in html
    assert re.search(r"builder_layout\.%s\b|builder_layout\[?['\"]?%s" % (e["flag"], e["flag"]), html), "頁面沒有讀 builder_layout.%s" % e["flag"]


@pytest.mark.skipif(not NODE, reason="no node")
def test_editor_marks_ineffective_relabels_and_fixed_positions_with_node():
    from tests.platform.test_layout_editor_pending_2026_10_14 import _node as ed
    reg = {e["flag"]: e for e in REG}
    case = json.dumps(reg["case_management"], ensure_ascii=False)
    quo = json.dumps(reg["quotations"], ensure_ascii=False)
    r = ed("""
  const case_ = %s, quo = %s
  c.pageInfo = case_
  const out = { sales: c.ineffective({ field: 'sales', core: false }, 'cases'), amount: c.ineffective({ field: 'amount', core: false }, 'cases'),
    core: c.ineffective({ field: 'quoteNo', core: true }, 'cases'), health: c.ineffective({ field: 'health', core: false }, 'bizBlocks'),
    timeline: c.ineffective({ field: 'timeline', core: false }, 'bizBlocks'),
    fixHealth: c.fixedPos('bizBlocks', { field: 'health' }), fixSigned: c.fixedPos('bizBlocks', { field: 'signedBack' }),
    fixTimeline: c.fixedPos('bizBlocks', { field: 'timeline' }), fixOtherList: c.fixedPos('cases', { field: 'health' }), notes: c.pageNotes().length }
  c.pageInfo = quo
  out.fixQuotes = c.fixedPos('quotes', { field: 'amount' })
  c.pageInfo = null
  out.none = c.ineffective({ field: 'amount', core: false }, 'cases'); out.nonotes = c.pageNotes().length; out.nofix = c.fixedPos('quotes', { field: 'amount' })
  console.log(JSON.stringify(out))""" % (case, quo))
    assert r["sales"] == "" and r["amount"] and r["core"] == "" and r["health"] and r["timeline"] == ""        # 健康總覽卡沒有標題 ⇒ 改名無效；專案期間有
    assert r["fixHealth"] is True and r["fixSigned"] is True and r["fixTimeline"] is False and r["fixOtherList"] is False
    assert r["fixQuotes"] is True and r["notes"] >= 1
    assert r["none"] == "" and r["nonotes"] == 0 and r["nofix"] is False                                    # 登錄讀不到＝不顯示提示


def test_ask_bar_flex_is_a_class_not_inline_style():
    tag = re.search(r'<div[^>]*data-testid="ml-ask"[^>]*>', EDITOR).group(0)
    assert "x-show" in tag and "style=" not in tag
