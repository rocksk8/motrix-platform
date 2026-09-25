"""程式 import 的第三方套件，都要能從 requirements 裝得到（2026-09-25，專案專用 .venv）。

- 產品碼（backend 扣掉 tests／tools／scripts／migrations_frozen 與 conftest.py）⇒ requirements.txt
- 測試（tests／各模組 tests／conftest.py）⇒ requirements.txt ＋ requirements-dev.txt
「裝得到」＝該套件屬於宣告的套件本身，或它們的相依（依目前環境的套件中繼資料遞迴展開）。
backend/tools 下的一次性工具不在範圍內；例外列 TOOL_ONLY 並寫理由。

☠️ 成因：這台機器的 `python` 是別人的 venv（hermes-agent），測試一直跑在一個
   「剛好什麼都有」的環境裡 ⇒ TestClient 需要的 httpx2、QR 測試的 cv2／numpy 從沒列進 requirements。
"""
import ast
import importlib.metadata as md
import re
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
_SKIP_DIRS = ("tests", "tools", "scripts", "migrations_frozen", "__pycache__", ".venv", "venv")


def _local_names():
    """repo 自己的模組：backend 頂層檔／目錄、backend/tools 與 tools/platform 底下的腳本（測試以 sys.path 引用它們）。"""
    names = {p.stem for p in BACKEND.glob("*.py")} | {p.name for p in BACKEND.iterdir() if p.is_dir()}
    names |= {p.stem for p in (BACKEND / "tools").glob("*.py")}
    names |= {p.stem for p in (BACKEND.parent / "tools" / "platform").glob("*.py")}
    return names


def third_party_imports(files):
    std, local = set(sys.stdlib_module_names), _local_names()
    out = {}
    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8-sig"))
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            mods = []
            if isinstance(n, ast.Import):
                mods = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                mods = [n.module]
            for m in mods:
                top = m.split(".")[0]
                if top in std or top in local or top.startswith("_") or top.startswith("test_"):
                    continue
                out.setdefault(top, set()).add(f.relative_to(BACKEND).as_posix())
    return out


def _norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def declared(req_files):
    names = set()
    for rf in req_files:
        for line in (BACKEND / rf).read_text(encoding="ascii").splitlines():
            line = line.split("#", 1)[0].strip()
            if line and not line.startswith("-"):
                names.add(_norm(re.split(r"[<>=!~\[; ]", line, 1)[0]))
    return names


def closure(dists):
    """宣告的套件＋遞迴相依（依目前環境的中繼資料；沒裝的套件展不開 ⇒ 由別的題負責「有沒有裝」）。"""
    seen, stack = set(), list(dists)
    while stack:
        d = stack.pop()
        if d in seen:
            continue
        seen.add(d)
        try:
            reqs = md.requires(d) or []
        except md.PackageNotFoundError:
            continue
        for r in reqs:
            if "extra ==" in r:
                continue
            stack.append(_norm(re.split(r"[<>=!~\[; (]", r, 1)[0]))
    return seen


def uncovered(imports, allowed):
    p2d = md.packages_distributions()
    bad = {}
    for mod, files in sorted(imports.items()):
        dists = {_norm(d) for d in p2d.get(mod, [])}
        if not dists or not (dists & allowed):
            bad[mod] = (sorted(dists) or ["（目前環境找不到提供它的套件）"], sorted(files)[:3])
    return bad


def _product_files():
    return [p for p in BACKEND.rglob("*.py")
            if not any(x in p.relative_to(BACKEND).parts for x in _SKIP_DIRS) and p.name != "conftest.py"]


def _test_files():
    files = [BACKEND / "conftest.py"] + list((BACKEND / "tests").rglob("*.py"))
    files += [p for p in (BACKEND / "modules").rglob("*.py") if "tests" in p.relative_to(BACKEND).parts]
    return files


def _fmt(bad):
    return "\n".join("  %s  ← 套件 %s；例：%s" % (m, "／".join(d), "、".join(f)) for m, (d, f) in bad.items())


def test_product_imports_are_in_requirements():
    allowed = closure(declared(["requirements.txt"]))
    bad = uncovered(third_party_imports(_product_files()), allowed)
    assert not bad, "產品碼 import 了 requirements.txt 裝不到的套件（正式機會 ImportError）：\n" + _fmt(bad)


def test_test_imports_are_in_requirements():
    allowed = closure(declared(["requirements.txt", "requirements-dev.txt"]))
    bad = uncovered(third_party_imports(_test_files()), allowed)
    assert not bad, "測試 import 了 requirements(-dev).txt 裝不到的套件（全新環境會收集失敗）：\n" + _fmt(bad)


#: 測試夾具在**執行期**才 import 的函式庫（我們的碼只 import 它們，不直接 import 它們依賴的套件）
RUNTIME_IMPORTERS = ("starlette.testclient",)


def runtime_imports(importers=RUNTIME_IMPORTERS):
    """這些函式庫原始碼頂層 import 的、**目前環境有安裝**的第三方模組（沒裝的是 try/except 後備，略過）。"""
    import ast
    import importlib
    import inspect
    p2d = md.packages_distributions()
    out = {}
    for name in importers:
        tree = ast.parse(inspect.getsource(importlib.import_module(name)))
        for n in ast.walk(tree):
            mods = [a.name for a in n.names] if isinstance(n, ast.Import) else \
                [n.module] if isinstance(n, ast.ImportFrom) and n.module and n.level == 0 else []
            for m in mods:
                top = m.split(".")[0]
                if top in p2d and top != name.split(".")[0]:
                    out.setdefault(top, set()).add(name)
    return out


def test_runtime_imports_of_test_fixtures_are_in_requirements():
    """稽核 B-S1：httpx2 是 TestClient 執行期才載入的（starlette 中繼資料裡是 extra=='full'，閉包會跳過）⇒
    只掃直接 import 的話，從 requirements-dev 拿掉它照樣綠（突變 B02 存活過）。"""
    allowed = closure(declared(["requirements.txt", "requirements-dev.txt"]))
    bad = uncovered(runtime_imports(), allowed)
    assert not bad, "測試夾具執行期需要、requirements(-dev).txt 裝不到的套件（全新環境 client 夾具會壞）：\n" + _fmt(bad)


def test_runtime_scan_sees_httpx2():
    """正對照：掃得到 TestClient 需要的 httpx2（掃描壞掉時上一題會安靜地綠）。"""
    assert "httpx2" in runtime_imports()


def test_rc_removing_httpx2_from_dev_requirements_is_caught():
    """反向控制（突變 B02 的重現）：宣告裡沒有 httpx2 ⇒ 紅。"""
    allowed = closure(declared(["requirements.txt", "requirements-dev.txt"]) - {"httpx2"})
    assert "httpx2" in uncovered(runtime_imports(), allowed)


def test_pytest_is_declared_directly():
    """稽核 B-O1：pytest 要直接宣告，不可以只靠 pytest-xdist 的相依帶進來。"""
    assert "pytest" in declared(["requirements-dev.txt"])


def test_scanner_sees_known_imports():
    """正對照：掃得到產品碼的 fastapi 與測試的 pytest（掃描壞掉時上面兩題會安靜地綠）。"""
    assert "fastapi" in third_party_imports(_product_files())
    assert "pytest" in third_party_imports(_test_files())
    assert "fastapi" in declared(["requirements.txt"])


def test_rc_an_undeclared_import_is_caught():
    imports = {"fastapi": {"x.py"}, "definitely_not_installed_pkg": {"x.py"}}
    bad = uncovered(imports, closure(declared(["requirements.txt"])))
    assert list(bad) == ["definitely_not_installed_pkg"]


def test_rc_a_dev_only_package_in_product_code_is_caught():
    """playwright 只在 requirements-dev ⇒ 產品碼 import 它要紅（正式機沒裝）。"""
    bad = uncovered({"playwright": {"x.py"}}, closure(declared(["requirements.txt"])))
    assert "playwright" in bad


def test_rc_transitive_dependency_counts_as_installed():
    """starlette 是 fastapi 的相依 ⇒ 直接 import 它也裝得到（不要求重複宣告）。"""
    allowed = closure(declared(["requirements.txt"]))
    if "starlette" not in allowed:
        pytest.skip("目前環境沒有 fastapi 的中繼資料 ⇒ 展不開相依")
    assert not uncovered({"starlette": {"x.py"}}, allowed)
