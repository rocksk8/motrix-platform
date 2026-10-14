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
        assert set(e) == KEYS, e["flag"]
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
        assert k in listed, "%s 不是這頁列表的欄位" % k
        assert not fields[k]["core"], "%s 是核心欄位（本來就不能改名），不必登記" % k
    html = source_tree.page_file(e["page"]).read_text(encoding="utf-8")
    assert "page: '%s'" % e["page"] in html and "deferred: true" in html
    assert re.search(r"builder_layout\.%s\b|builder_layout\[?['\"]?%s" % (e["flag"], e["flag"]), html), "頁面沒有讀 builder_layout.%s" % e["flag"]


NODE_TEST = r"""
const fs=require('fs');const src=fs.readFileSync(process.argv[2],'utf8');
const reg=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
const m=src.match(/ineffective\(c\) \{[^\r\n]*\},?\r?\n/);const n=src.match(/pageNotes\(\) \{[^\r\n]*\},?\r?\n/);
const o=eval('({pageInfo:null,'+m[0].replace(/,?\r?\n$/,'')+','+n[0].replace(/,?\r?\n$/,'')+'})');
o.pageInfo=reg.find(e=>e.page==='case-management.html');
const out={sales:o.ineffective({field:'sales',core:false}),amount:o.ineffective({field:'amount',core:false}),
 quote:o.ineffective({field:'quoteNo',core:true}),notes:o.pageNotes().length};
o.pageInfo=null;out.none=o.ineffective({field:'amount',core:false});out.nonotes=o.pageNotes().length;
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(not NODE, reason="no node")
def test_editor_marks_ineffective_relabels_with_node(tmp_path):
    f = tmp_path / "t.js"
    f.write_text(NODE_TEST, encoding="utf-8")
    r = subprocess.run([NODE, str(f), str(ROOT / "frontend/static/layout-editor.js"),
                        str(ROOT / "frontend/static/layout-pages.json")], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert d["sales"] == "" and d["amount"] and d["quote"] == "" and d["notes"] >= 1
    assert d["none"] == "" and d["nonotes"] == 0       # 登錄讀不到＝不顯示提示


def test_ask_bar_flex_is_a_class_not_inline_style():
    tag = re.search(r'<div[^>]*data-testid="ml-ask"[^>]*>', EDITOR).group(0)
    assert "x-show" in tag and "style=" not in tag
