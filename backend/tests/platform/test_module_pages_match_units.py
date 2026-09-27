# -*- coding: utf-8 -*-
"""modules.json 的 page: 單位 ＝ 各模組 module.json 的 pages（稽核 D 建議，wip/b-drill-absent404-2）。

兩份清單各走各的時：modules.json 把頁面歸給某模組、module.json 卻沒列 ⇒ 模組缺席時產品選配不移除那一頁
（removed_pages 看 module.json），D7 前哨的缺席 404 也驗不到它（例：subcontract 的 contractor-voucher-approval-settings、
case 的 sales-orders）；反過來 module.json 列了、modules.json 沒歸 ⇒ 分組與相依圖看不到它。
只比已搬遷（有 module.json）的模組；尚未搬遷的（M01 等）搬遷時由這一題接手。
"""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def page_unit_mismatches(groups, manifests):
    """groups：modules.json 的 modules（{組: {"key", "units"}}）；manifests：{key: module.json dict}。
    ⇒ [(key, 只在 modules.json, 只在 module.json)]，一致的不列。"""
    out = []
    for g in groups.values():
        key = g.get("key")
        if not key or key not in manifests:
            continue
        units = {str(u).split(":", 1)[1].split("/")[-1] for u in g.get("units") or [] if str(u).startswith("page:")}
        decl = {str(p.get("path", "")).split("/")[-1] for p in manifests[key].get("pages") or []}
        if units != decl:
            out.append((key, sorted(units - decl), sorted(decl - units)))
    return out


def _real():
    groups = json.loads((REPO / "docs" / "platform" / "modules.json").read_text(encoding="utf-8"))["modules"]
    manifests = {d.name: json.loads((d / "module.json").read_text(encoding="utf-8"))
                 for d in sorted((REPO / "backend" / "modules").iterdir()) if (d / "module.json").is_file()}
    return groups, manifests


def test_module_pages_match_the_page_units():
    groups, manifests = _real()
    checked = [g["key"] for g in groups.values() if g.get("key") in manifests]
    assert len(checked) >= 3, "正對照：已搬遷的模組只找到 %s——量尺量不到東西" % checked
    bad = page_unit_mismatches(groups, manifests)
    assert not bad, ("modules.json 的 page: 單位與 module.json 的 pages 不一致（key、只在 modules.json、只在 module.json）：%s\n"
                     "⇒ 補進 module.json 的 pages（不進側欄就不帶 menu），或改 modules.json 的歸屬" % bad)


def test_a_page_unit_missing_from_the_manifest_is_caught():
    """反向控制：modules.json 歸給 aa 的頁 module.json 沒列 ⇒ 列出；module.json 多列的 ⇒ 列出；一致 ⇒ 不列；沒有 module.json 的組不比。"""
    groups = {"MA": {"key": "aa", "units": ["page:pages/a1.html", "page:pages/a2.html", "mod:aa/api"]},
              "MB": {"key": "bb", "units": ["page:pages/b1.html"]},
              "MC": {"key": "cc", "units": ["page:pages/c1.html"]},
              "MD": {"key": "dd", "units": ["page:pages/d1.html"]}}
    manifests = {"aa": {"pages": [{"path": "a1.html"}]},
                 "bb": {"pages": [{"path": "b1.html"}, {"path": "b2.html"}]},
                 "cc": {"pages": [{"path": "c1.html", "menu": {"label": "x"}}]}}
    assert page_unit_mismatches(groups, manifests) == [("aa", ["a2.html"], []), ("bb", [], ["b2.html"])]
