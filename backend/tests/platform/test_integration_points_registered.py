"""CORE-SPEC §5：串接點登記表（docs/platform/INTEGRATION-POINTS.md）必須與程式碼一致（稽核 X-2，2026-09-25）。

- 程式碼提供的 capability（`*.provide("cap", …)`、`ModuleSpec(providers={("cap", name): …})`）＝登記表裡「形式＝provider」各節標題列出的 capability。
  多一個（寫了 provide 沒登記）或少一個（登記了沒實作）都紅。
- 程式碼取用的 capability（`single_provider("cap")`、`providers("cap")`）必須都已登記（取用一個不存在的能力＝永遠退化）。
- 掃描範圍：`core.source_tree.product_files()`（含 modules/ 底下所有層）。

正對照：比對函式用合成的文件與原始碼跑，多一個／少一個／取用未登記都要回報；另外斷言真實掃描抓得到已知的 `dispatch.row`
（掃不到任何東西時「兩邊都空＝相等」會是假綠）。
"""
import ast
import re
from pathlib import Path

from core import source_tree

DOC = Path(__file__).resolve().parents[3] / "docs" / "platform" / "INTEGRATION-POINTS.md"
_CAP = re.compile(r"`([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+)`")


def doc_capabilities(text):
    """各節（`## IP-…`）中「形式」列以 provider 開頭者，標題列反引號內的 capability。"""
    caps = set()
    for sec in re.split(r"\n(?=## IP-)", text):
        if not sec.startswith("## IP-"):
            continue
        head = sec.splitlines()[0]
        form = re.search(r"^\| 形式 \|\s*([^|]*)", sec, re.M)
        if form and form.group(1).strip().startswith("provider"):
            caps |= set(_CAP.findall(head))
    return caps


def _str0(call):
    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        return call.args[0].value
    return None


def code_capabilities(sources):
    """sources：{名稱: 原始碼}。回 (provided, consumed)。"""
    provided, consumed = set(), set()
    for src in sources.values():
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else "")
            if name == "provide" and _str0(node):
                provided.add(_str0(node))
            elif name in ("single_provider", "providers") and _str0(node):
                consumed.add(_str0(node))
            elif name == "ModuleSpec":
                for kw in node.keywords:
                    if kw.arg == "providers" and isinstance(kw.value, ast.Dict):
                        for k in kw.value.keys:
                            if isinstance(k, ast.Tuple) and k.elts and isinstance(k.elts[0], ast.Constant):
                                provided.add(k.elts[0].value)
    return provided, consumed


def mismatches(doc_caps, provided, consumed):
    out = []
    out += ["程式碼有提供、登記表沒有：%s" % c for c in sorted(provided - doc_caps)]
    out += ["登記表有、程式碼沒有提供：%s" % c for c in sorted(doc_caps - provided)]
    out += ["程式碼有取用、登記表沒有：%s" % c for c in sorted(consumed - doc_caps)]
    return out


def _real():
    srcs = {source_tree.rel(p): p.read_text(encoding="utf-8") for p in source_tree.product_files()}
    return code_capabilities(srcs)


# ── 正對照（合成資料，不綁任何 L2 模組）───────────────────────────────────────

_DOC = """# x
## IP-1　`a.one`：甲
| 形式 | provider，單一提供者 |
## IP-2　`b.two`＋`b.three`：乙
| 形式 | provider，多提供者 |
## 其他　`not.cap`：不是串接點
| 形式 | provider |
## IP-3　`c.four`：L1 直接呼叫
| 形式 | L1 函式直接呼叫（非 provider） |
"""
_SRC = {"m.py": 'registry.provide("a.one", "x", f)\n_registry.provide("b.two", "y", g)\n'
                'MODULE = ModuleSpec(key="k", providers={("b.three", "z"): h})\n'
                'registry.single_provider("a.one")\nregistry.providers("b.two")\n'}


def test_positive_control_parser_and_scanner():
    assert doc_capabilities(_DOC) == {"a.one", "b.two", "b.three"}
    assert code_capabilities(_SRC) == ({"a.one", "b.two", "b.three"}, {"a.one", "b.two"})
    assert mismatches({"a.one", "b.two", "b.three"}, *code_capabilities(_SRC)) == []


def test_reverse_controls_each_kind_of_drift_is_reported():
    doc = doc_capabilities(_DOC)
    prov, cons = code_capabilities(_SRC)
    extra_code = dict(_SRC, n='registry.provide("d.new", "x", f)\n')
    assert mismatches(doc, *code_capabilities(extra_code)) == ["程式碼有提供、登記表沒有：d.new"]
    assert mismatches(doc | {"e.ghost"}, prov, cons) == ["登記表有、程式碼沒有提供：e.ghost"]
    assert mismatches(doc, prov, cons | {"f.unknown"}) == ["程式碼有取用、登記表沒有：f.unknown"]


def test_real_scan_sees_a_known_capability():
    provided, consumed = _real()
    assert "dispatch.row" in provided and "dispatch.row" in consumed, (provided, consumed)


def test_registry_matches_code():
    provided, consumed = _real()
    bad = mismatches(doc_capabilities(DOC.read_text(encoding="utf-8")), provided, consumed)
    assert not bad, "INTEGRATION-POINTS.md 與程式碼不一致（CORE-SPEC §5）：\n  " + "\n  ".join(bad)
