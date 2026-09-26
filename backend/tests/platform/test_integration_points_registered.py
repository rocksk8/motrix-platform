"""CORE-SPEC §5：串接點登記表（docs/platform/INTEGRATION-POINTS.md）必須與程式碼一致（稽核 X-2，2026-09-25）。

- 程式碼提供的 capability（`*.provide("cap", …)`、`ModuleSpec(providers={("cap", name): …})`）＝登記表裡「形式＝provider」各節標題列出的 capability。
  多一個（寫了 provide 沒登記）或少一個（登記了沒實作）都紅。
- 程式碼取用的 capability（`single_provider("cap")`、`providers("cap")`）必須都已登記（取用一個不存在的能力＝永遠退化）。
- 掃描範圍：`core.source_tree.product_files()`（含 modules/ 底下所有層）。

正對照：比對函式用合成的文件與原始碼跑，多一個／少一個／取用未登記都要回報；另外斷言真實掃描抓得到 L1 每日執行器
（`helpers/daily_checks.py`）取用的 `daily.check`（掃不到任何東西時「兩邊都空＝相等」會是假綠）。正對照不綁 L2：
原本用 M04 提供的 `dispatch.row`，拿掉 M04 時這題一定紅（C 指出，2026-09-26）。

模組不在（選配、PLAYBOOK §B 步驟 11 反向控制）：該節「提供方」列出的路徑**全部**是 `modules/<key>/…`、且那些資料夾都不在
⇒「登記表有、程式碼沒有提供」不算（主持裁定 2026-09-26）。資料夾在就照樣比對；提供方沒寫出模組路徑（例如仍寫 `routers/…`）不豁免。
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


def _provider_paths(sec):
    """一節「提供方」列裡反引號內、含 `/` 的路徑（`::` 之後的名稱去掉）。"""
    row = re.search(r"^\| 提供方 \|([^\n]*)", sec, re.M)
    if not row:
        return []
    return [c.split("::")[0] for c in re.findall(r"`([^`]+)`", row.group(1)) if "/" in c]


def _module_key(path):
    """`modules/<key>/…`／`backend/modules/<key>/…` ⇒ key；其他路徑 ⇒ None。"""
    parts = path.replace(chr(92), "/").split("/")
    if parts[:1] == ["backend"]:
        parts = parts[1:]
    return parts[1] if len(parts) > 2 and parts[0] == "modules" else None


def absent_module_capabilities(text, installed=source_tree.module_installed):
    """提供方全部寫成 `modules/<key>/…` 且那些模組都不在的節 ⇒ 它標題列的 capability（可以沒有人提供）。"""
    caps = set()
    for sec in re.split(r"\n(?=## IP-)", text):
        if not sec.startswith("## IP-"):
            continue
        paths = _provider_paths(sec)
        # installed() 對非模組路徑一律回 True ⇒ 提供方混有 routers／helpers 路徑就不會豁免
        if paths and not any(installed(p) for p in paths):
            caps |= doc_capabilities(sec)
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


def mismatches(doc_caps, provided, consumed, absent=frozenset()):
    """absent：提供方模組不在的 capability（absent_module_capabilities），只豁免「登記表有、程式碼沒有提供」。"""
    out = []
    out += ["程式碼有提供、登記表沒有：%s" % c for c in sorted(provided - doc_caps)]
    out += ["登記表有、程式碼沒有提供：%s" % c for c in sorted(doc_caps - provided - absent)]
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
    assert "daily.check" in consumed, consumed          # L1 helpers/daily_checks.py：任何安裝包都在


# ── 模組不在時（主持裁定 2026-09-26）：合成資料，模組名不綁任何真的 L2 ─────────────────────────

_DOC_MOD = """# x
## IP-1　`g.gone`：提供方模組不在
| 提供方 | M99：`modules/zz_absent/api.py::_X` |
| 形式 | provider，單一提供者 |
## IP-2　`h.here`：提供方模組在
| 提供方 | M98：`modules/{here}/api.py::_Y` |
| 形式 | provider，單一提供者 |
## IP-3　`i.old`：提供方沒寫出模組
| 提供方 | M97：`routers/zz_absent.py::_Z` |
| 形式 | provider，單一提供者 |
## IP-4　`j.mixed`：一個模組不在＋一個不是模組
| 提供方 | M96：`modules/zz_absent/x.py::_A`；M95：`helpers/zz.py::_B` |
| 形式 | provider，多提供者 |
"""


def _installed_name(monkeypatch, tmp_path, key="zz_here"):
    """「模組在」的正對照不綁真實 L2（core-only 反向控制時一個模組都沒有，D 稽核 G-M1）：
    source_tree.BACKEND 指到暫存樹，放一個合成模組（有 module.json），module_installed 照常判定。"""
    d = tmp_path / "backend" / "modules" / key
    d.mkdir(parents=True)
    (d / "module.json").write_text('{"key": "%s"}' % key, encoding="utf-8")
    monkeypatch.setattr(source_tree, "BACKEND", tmp_path / "backend")
    return key


def test_absent_module_green_present_module_still_red(monkeypatch, tmp_path):
    doc = _DOC_MOD.replace("{here}", _installed_name(monkeypatch, tmp_path))
    absent = absent_module_capabilities(doc)
    assert absent == {"g.gone"}
    # 模組不在 ⇒ 沒有人提供也綠
    assert mismatches({"g.gone"}, set(), set(), absent) == []
    # 模組在、但沒有提供 ⇒ 照樣紅；提供方沒寫模組路徑、或混著非模組路徑 ⇒ 不豁免
    assert mismatches(doc_capabilities(doc), set(), set(), absent) == [
        "登記表有、程式碼沒有提供：h.here", "登記表有、程式碼沒有提供：i.old", "登記表有、程式碼沒有提供：j.mixed"]
    # 豁免只蓋「沒有人提供」：取用未登記、提供未登記照樣紅
    assert mismatches(set(), {"g.gone"}, {"g.gone"}, absent) == [
        "程式碼有提供、登記表沒有：g.gone", "程式碼有取用、登記表沒有：g.gone"]


def test_every_installed_module_can_be_removed_without_breaking_the_registry():
    """真實的樹：逐一假裝拿掉每個已安裝模組（它的原始碼不掃、module_installed 說不在），登記表比對仍須一致。

    紅 ⇒ 那個模組提供的串接點，登記表「提供方」沒寫成 `modules/<key>/…`（或與非模組提供者混寫而程式碼只剩模組提供）。"""
    text = DOC.read_text(encoding="utf-8")
    srcs = {source_tree.rel(p): p.read_text(encoding="utf-8") for p in source_tree.product_files()}
    bad = {}
    for d in source_tree.module_dirs():
        key = d.name
        def installed(path, k=key):
            return source_tree.module_installed(path) and _module_key(path) != k
        rest = {r: s for r, s in srcs.items() if _module_key(r) != key}
        assert len(rest) < len(srcs), "拿掉 %s 沒有少掃任何檔 ⇒ 路徑比對失效" % key
        got = mismatches(doc_capabilities(text), *code_capabilities(rest), absent_module_capabilities(text, installed))
        if got:
            bad[key] = got
    assert not bad, "拿掉模組後登記表比對失敗（提供方請寫 modules/<key>/…）：%s" % bad


def test_registry_matches_code():
    provided, consumed = _real()
    text = DOC.read_text(encoding="utf-8")
    bad = mismatches(doc_capabilities(text), provided, consumed, absent_module_capabilities(text))
    assert not bad, "INTEGRATION-POINTS.md 與程式碼不一致（CORE-SPEC §5）：\n  " + "\n  ".join(bad)


# ── 稽核 D M04-S1（2026-09-26）：模組在的時候，登記表寫的提供方檔案必須真的存在 ─────────────
# X-2 豁免只看 `modules/<key>` 資料夾在不在；路徑寫錯（例：漏了 `api/`）時守門不會紅。

def missing_provider_files(text, installed=source_tree.module_installed, backend=source_tree.BACKEND):
    """各節「提供方」列的 `.py` 路徑：所屬模組在（或不是模組路徑）而檔案不存在 ⇒ 列出。"""
    out = []
    for sec in re.split(r"\n(?=## IP-)", text):
        if not sec.startswith("## IP-"):
            continue
        for p in _provider_paths(sec):
            rel = p.replace(chr(92), "/")
            rel = rel[len("backend/"):] if rel.startswith("backend/") else rel
            if rel.endswith(".py") and installed(rel) and not (backend / rel).is_file():
                out.append("%s：%s" % (sec.splitlines()[0][:40], p))
    return out


def test_missing_provider_files_positive_and_reverse_controls(tmp_path):
    (tmp_path / "modules" / "zz" ).mkdir(parents=True)
    (tmp_path / "modules" / "zz" / "api.py").write_text("x", encoding="utf-8")
    doc = ("## IP-1　`a.b`：甲\n| 提供方 | `modules/zz/api.py::f` |\n"
           "## IP-2　`c.d`：乙\n| 提供方 | `modules/zz/wrong.py::g` |\n"
           "## IP-3　`e.f`：丙\n| 提供方 | `modules/gone/api.py::h` |\n")
    got = missing_provider_files(doc, installed=lambda p: "gone" not in p, backend=tmp_path)
    assert got == ["## IP-2　`c.d`：乙：modules/zz/wrong.py"]       # 路徑寫錯的被抓到；模組不在的不算


def test_every_provider_file_in_the_registry_exists():
    bad = missing_provider_files(DOC.read_text(encoding="utf-8"))
    assert not bad, "INTEGRATION-POINTS 的提供方檔案不存在（路徑寫錯？）：\n  " + "\n  ".join(bad)
