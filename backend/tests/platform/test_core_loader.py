# -*- coding: utf-8 -*-
"""L0 模組載入器與登錄表的契約（CORE-SPEC §4、§5）。"""
import importlib
import json
import sys

import pytest

from core import loader, registry, source_tree


@pytest.fixture
def clean_registry():
    saved_loaded, saved_failed = dict(registry._LOADED), dict(registry._FAILED)
    registry._reset()
    yield
    registry._reset()
    registry._LOADED.update(saved_loaded)
    registry._FAILED.update(saved_failed)


@pytest.mark.parametrize("spec,ok", [
    (">=1.0,<2.0", True), (">=1.0", True), ("==1.0", True), ("<1.0", False),
    (">=1.1", False), (">=0.9,<1.0", False), (" >= 1 , < 2 ", True),
])
def test_core_range(spec, ok):
    assert loader.core_compatible(spec, "1.0") is ok


@pytest.mark.parametrize("spec", ["", "~1.0", "1.x", ">=a"])
def test_unparsable_core_range_raises_not_guesses(spec):
    with pytest.raises(ValueError):
        loader.core_compatible(spec, "1.0")


def _make_pkg(tmp_path, pkg, mods):
    root = tmp_path / pkg
    root.mkdir()
    (root / "__init__.py").write_text("", encoding="utf-8")
    for key, (manifest, init_src) in mods.items():
        d = root / key
        d.mkdir()
        (d / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
        (d / "__init__.py").write_text(init_src, encoding="utf-8")
    return root


_GOOD = ("from core.registry import ModuleSpec\n"
         "MODULE = ModuleSpec(key='{k}')\n")


def test_broken_module_is_isolated_and_reported(tmp_path, monkeypatch, clean_registry):
    pkg = "fake_mods_a"
    root = _make_pkg(tmp_path, pkg, {
        "good": ({"key": "good", "core": ">=1.0,<2.0"}, _GOOD.format(k="good")),
        "boom": ({"key": "boom", "core": ">=1.0,<2.0"}, "raise RuntimeError('boom')\n"),
        "newer": ({"key": "newer", "core": ">=2.0"}, _GOOD.format(k="newer")),
        "badrange": ({"key": "badrange", "core": "~1"}, _GOOD.format(k="badrange")),
        "wrongkey": ({"key": "other", "core": ">=1.0"}, _GOOD.format(k="wrongkey")),
        "nospec": ({"key": "nospec", "core": ">=1.0"}, "x = 1\n"),
    })
    monkeypatch.syspath_prepend(str(tmp_path))
    got = loader.load_all(str(root), pkg)
    assert [m.key for m in got] == ["good"]
    assert set(registry.failed()) == {"boom", "newer", "badrange", "wrongkey", "nospec"}
    for k in list(sys.modules):
        if k.startswith(pkg):
            del sys.modules[k]


def test_missing_modules_dir_is_not_an_error(tmp_path, clean_registry):
    assert loader.load_all(str(tmp_path / "nope"), "nope") == []


def test_providers_absent_is_empty_not_error(clean_registry):
    assert registry.providers("map.points") == {}
    assert registry.runtime_switches() == []


def test_every_module_api_router_is_declared_in_its_spec():
    """modules/<key>/api.py 的 router 必須在 MODULE.routers 裡——否則端點全部不可達
    （對應 routers/ 的 test_router_registration）。"""
    for d in source_tree.module_dirs():
        if not (d / "api.py").is_file():
            continue
        api = importlib.import_module(f"modules.{d.name}.api")
        spec = importlib.import_module(f"modules.{d.name}").MODULE
        assert api.router in spec.routers, d.name


def test_real_modules_all_load(clean_registry):
    got = {m.key for m in loader.load_all()}
    assert registry.failed() == {}
    assert got == {d.name for d in source_tree.module_dirs()}


def test_source_tree_includes_module_files():
    """正對照：搬進 modules/ 的檔一定在守門掃描範圍內。

    不綁特定 L2 模組（2026-09-25 刪 M11 反向控制）：任取一個有 api.py 的已安裝模組；
    一個都沒有 ⇒ 明確 skip（不是默默通過）。M11 自己的那一份在 modules/tender_radar/tests/。
    """
    rels = {source_tree.rel(p) for p in source_tree.router_files()}
    assert "routers/system.py" in rels
    mods = [d for d in source_tree.module_dirs() if (d / "api.py").is_file()]
    if not mods:
        pytest.skip("沒有任何已安裝且帶 api.py 的模組（modules/*/module.json）⇒ 模組端的正對照無對象")
    d = mods[0]
    api = source_tree.rel(d / "api.py")
    assert api in rels
    logic = {source_tree.rel(p) for p in source_tree.logic_files()}
    assert api not in logic
    others = [source_tree.rel(p) for p in d.glob("*.py") if p.name not in ("api.py", "__init__.py")]
    assert set(others) <= logic, sorted(set(others) - logic)
