# -*- coding: utf-8 -*-
"""守門：測試檔之間的 `from tests.<x> import …` 必須指到存在的檔案。

2026-11-14（T84 診斷）：test-prune 刪了一個 0 題空殼檔，但其中兩個小工具仍被 modules/supply/tests 與
test_conn_reaper_t80 匯入，三個檔在收集階段才 ModuleNotFoundError。刪／搬測試檔時，靜態掃一次就能提前發現。
只掃 `tests.` 開頭的匯入（`tests.platform.x`、`tests._helper` 都算）；純靜態、不匯入任何被測檔。
"""
import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]


def _test_files():
    for p in list((BACKEND / "tests").rglob("*.py")) + list((BACKEND / "modules").glob("*/tests/**/*.py")):
        if "__pycache__" not in p.parts:
            yield p


def _targets(tree):
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.level == 0 and n.module and (n.module == "tests" or n.module.startswith("tests.")):
            yield n.lineno, n.module, [a.name for a in n.names]
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name == "tests" or a.name.startswith("tests."):
                    yield n.lineno, a.name, []


def _resolves(module, names):
    base = BACKEND.joinpath(*module.split("."))
    if base.with_suffix(".py").is_file():
        return True
    if base.is_dir():
        # `from tests import x` / `from tests.platform import x`：x 是子模組或套件
        return all(base.joinpath(n).with_suffix(".py").is_file() or base.joinpath(n).is_dir()
                   or n in ("*",) or _name_in_init(base, n) for n in names) if names else True
    return False


def _name_in_init(pkg_dir, name):
    init = pkg_dir / "__init__.py"
    return init.is_file() and name in init.read_text(encoding="utf-8", errors="replace")


def test_every_tests_import_points_at_an_existing_file():
    missing = []
    for p in _test_files():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for lineno, module, names in _targets(tree):
            if not _resolves(module, names):
                missing.append(f"{p.relative_to(BACKEND).as_posix()}:{lineno} → {module}")
    assert not missing, "匯入了不存在的測試檔（被刪／搬走？）：\n" + "\n".join(missing)


def test_scanner_sees_a_missing_target(tmp_path):
    # 正對照：確認掃描邏輯真的會抓到不存在的目標，不是永遠綠
    tree = ast.parse("from tests.__no_such_helper_xyz import a\nimport tests._login_helpers\n")
    found = list(_targets(tree))
    assert [m for _, m, _ in found] == ["tests.__no_such_helper_xyz", "tests._login_helpers"]
    assert not _resolves("tests.__no_such_helper_xyz", ["a"])
    assert _resolves("tests._login_helpers", [])
