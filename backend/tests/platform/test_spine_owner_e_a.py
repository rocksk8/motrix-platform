# -*- coding: utf-8 -*-
"""脊柱 E-a：設定群組的擁有者（載入器 import 範圍）、module.json `settings` 宣告⇔實際登錄、失敗時移除群組。"""
import ast
import json
import sys
from pathlib import Path

import pytest

from core import loader, registry
from helpers import settings_groups  # noqa: F401  核心群組（測試要確認 core 不會被移除）
from helpers import settings_registry as R


@pytest.fixture
def clean_registry():
    snap = registry.snapshot()
    registry._reset()
    yield
    registry.restore(snap)
    for g in [g for g in R._GROUPS if g.startswith("zz_ea")]:
        R._GROUPS.pop(g, None)
    R.invalidate()


def _field(key="n"):
    return R.SettingDef(key, "int", 1, min=0, max=9, question="這項要設多少？", label="測試項目", help="測試用的設定項目。", impact="影響測試用的畫面。")


def _reg(group, owner=None):
    kw = {} if owner is None else {"owner": owner}
    R.register_group(group, "測試群組", [_field()], help="測試用的設定群組。", **kw)


# --- 擁有者章 -------------------------------------------------------------------------------

def test_owner_is_core_outside_any_scope_and_module_inside(clean_registry):
    _reg("zz_ea_core")
    with registry.owner_scope("zz_mod"):
        assert registry.current_owner() == "zz_mod"
        _reg("zz_ea_inmod")
    assert registry.current_owner() is None
    _reg("zz_ea_explicit", owner="other")                          # 範圍之外可顯式指定（範圍之內指定成別人會被拒，見下方 r2 題）
    owners = {g: m["owner"] for g, m in R.groups().items() if g.startswith("zz_ea")}
    assert owners == {"zz_ea_core": "core", "zz_ea_inmod": "zz_mod", "zz_ea_explicit": "other"}
    assert R.owner_groups("zz_mod") == {"zz_ea_inmod"}


def test_owner_scope_is_restored_even_when_import_raises(clean_registry):
    with pytest.raises(RuntimeError):
        with registry.owner_scope("zz_mod"):
            raise RuntimeError("boom")
    assert registry.current_owner() is None


def test_unregister_owner_removes_only_that_owner_and_never_core(clean_registry):
    _reg("zz_ea_a", owner="zz_m1")
    _reg("zz_ea_b", owner="zz_m2")
    assert R.unregister_owner("zz_m1") == 1
    assert "zz_ea_a" not in R.groups() and "zz_ea_b" in R.groups()
    assert R.unregister_owner("core") == 0 and "change_control" in R.groups()


def test_mark_failed_and_unload_remove_the_modules_groups(clean_registry):
    _reg("zz_ea_f", owner="zz_failed")
    registry.mark_failed("zz_failed", "測試")
    assert "zz_ea_f" not in R.groups()
    _reg("zz_ea_u", owner="zz_unloaded")
    registry.register(registry.LoadedModule(key="zz_unloaded", manifest={}, spec=registry.ModuleSpec(key="zz_unloaded")))
    registry.unload("zz_unloaded", "路由衝突")
    assert "zz_ea_u" not in R.groups()


def test_unload_hook_failure_does_not_block_other_hooks(clean_registry):
    seen = []

    def bad(key):
        raise RuntimeError("hook down")

    def good(key):
        seen.append(key)
    n = len(registry._UNLOAD_HOOKS)
    registry.on_unload(bad)
    registry.on_unload(good)
    try:
        registry.mark_failed("zz_hookmod", "x")
        assert seen == ["zz_hookmod"]
    finally:
        del registry._UNLOAD_HOOKS[n:]


def test_owned_resolver_none_when_nobody_registered(clean_registry):
    assert registry.owned("zz_no_such_kind", "x") is None
    assert registry.owned("settings", "zz_none") == set()
    with pytest.raises(ValueError):
        registry.register_owned("settings", lambda o: set())


# --- 載入器：宣告⇔登錄 ---------------------------------------------------------------------

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


_HEAD = ("from core.registry import ModuleSpec\nfrom helpers import settings_registry as R\n")
_FIELD = ("R.SettingDef('n', 'int', 1, min=0, max=9, question='這項要設多少？', label='測試項目', help='測試用的設定項目。', impact='影響測試用的畫面。')")


def _src(*groups):
    body = "".join("R.register_group(%r, '測試群組', [%s], help='測試用的設定群組。')\n" % (g, _FIELD) for g in groups)
    return _HEAD + body + "MODULE = ModuleSpec(key='%s')\n"


def _mod(key, groups, decl):
    manifest = {"key": key, "core": ">=1.0,<2.0"}
    if decl is not None:
        manifest["settings"] = {"groups": decl}
    return (manifest, _src(*groups) % key)


def test_loader_checks_declared_settings_against_actual_registration(tmp_path, monkeypatch, clean_registry):
    pkg = "fake_mods_ea"
    root = _make_pkg(tmp_path, pkg, {
        "ea_ok": _mod("ea_ok", ["zz_ea_ok"], ["zz_ea_ok"]),
        "ea_plain": _mod("ea_plain", [], None),                                  # 沒有設定：不受影響
        "ea_miss": _mod("ea_miss", ["zz_ea_m1"], ["zz_ea_m1", "zz_ea_m2"]),     # 宣告了沒登記
        "ea_extra": _mod("ea_extra", ["zz_ea_x1"], None),                        # 登記了沒宣告
        "ea_baddecl": ({"key": "ea_baddecl", "core": ">=1.0,<2.0", "settings": {"groups": ["Bad-Code"]}},
                       "import sys\nsys._ea_baddecl_ran = True\n" + _src() % "ea_baddecl"),   # 宣告格式不合：模組程式碼不可被執行
    })
    monkeypatch.syspath_prepend(str(tmp_path))
    got = loader.load_all(str(root), pkg)
    try:
        assert sorted(m.key for m in got) == ["ea_ok", "ea_plain"]
        assert set(registry.failed()) == {"ea_miss", "ea_extra", "ea_baddecl"}
        assert "宣告了沒登記" in registry.failed()["ea_miss"] and "zz_ea_m2" in registry.failed()["ea_miss"]
        assert "登記了沒宣告" in registry.failed()["ea_extra"] and "zz_ea_x1" in registry.failed()["ea_extra"]
        owners = {g: m["owner"] for g, m in R.groups().items() if g.startswith("zz_ea")}
        assert owners == {"zz_ea_ok": "ea_ok"}                                     # 失敗模組的群組都已移除
        assert not hasattr(sys, "_ea_baddecl_ran")                                  # 宣告形狀在 import 之前驗：壞宣告的模組程式碼沒有被執行
    finally:
        for k in list(sys.modules):
            if k.startswith(pkg):
                del sys.modules[k]


def test_declared_settings_shape_is_checked_before_import():
    assert loader.declared_settings_groups({}) == []
    assert loader.declared_settings_groups({"settings": {"groups": ["a_b"]}}) == ["a_b"]
    for bad in ({"settings": []}, {"settings": {"groups": "a"}}, {"settings": {"groups": ["A"]}}, {"settings": {"groups": ["a", "a"]}}, {"settings": {}}):
        if bad == {"settings": {}}:
            assert loader.declared_settings_groups(bad) == []                      # 空區段＝沒宣告
            continue
        with pytest.raises(ValueError):
            loader.declared_settings_groups(bad)


# --- 0d 稽核（E-a r2）：核心群組不被 import 範圍搶走、不准替別人登記 ---------------------------------

def test_core_groups_stay_core_even_when_first_imported_inside_a_module_scope(clean_registry, monkeypatch):
    import importlib
    saved = dict(R._GROUPS)
    core_names = [g for g, v in saved.items() if v["owner"] == "core" and not g.startswith("zz_")]
    assert {"change_control", "retention", "uploads", "system_hub"} <= set(core_names)
    old_mod = sys.modules.get("helpers.settings_groups")
    try:
        for g in core_names:
            R._GROUPS.pop(g, None)
        monkeypatch.delitem(sys.modules, "helpers.settings_groups", raising=False)
        with registry.owner_scope("zz"):                                           # 某模組 import 期間第一次 import 本檔
            importlib.import_module("helpers.settings_groups")
        owners = {g: R._GROUPS[g]["owner"] for g in core_names}
        assert set(owners.values()) == {"core"}
        registry.mark_failed("zz", "那個模組後來載入失敗")                            # 失敗清理不可帶走核心群組
        assert all(g in R._GROUPS for g in core_names)
    finally:
        R._GROUPS.update(saved)
        if old_mod is not None:
            sys.modules["helpers.settings_groups"] = old_mod
        R.invalidate()


def test_a_module_scope_cannot_register_for_another_owner(clean_registry):
    with registry.owner_scope("zz_a"):
        _reg("zz_ea_same", owner="zz_a")                                           # 指定成自己 ⇒ 可以
        with pytest.raises(ValueError):
            _reg("zz_ea_other", owner="zz_b")                                      # 替別人登記 ⇒ 拒絕
        with pytest.raises(ValueError):
            _reg("zz_ea_core", owner="core")                                       # 冒充 core ⇒ 拒絕
    assert "zz_ea_other" not in R._GROUPS and "zz_ea_core" not in R._GROUPS
    _reg("zz_ea_free", owner="zz_b")                                               # 範圍之外（測試／核心）可顯式指定
    assert R._GROUPS["zz_ea_free"]["owner"] == "zz_b"


def test_settings_groups_still_exposes_register_group_and_keeps_blocks_core_owned(clean_registry):
    """合併安全：別的分支在 settings_groups.py 追加的區塊會呼叫 register_group(...)——名稱不能消失，且其群組屬 core（即使在模組 import 範圍內第一次載入）。"""
    from helpers import settings_groups as SG
    assert callable(getattr(SG, "register_group", None))
    with registry.owner_scope("zz_other"):
        SG.register_group("zz_ea_appended", "追加區塊群組", [_field()], help="測試用的設定群組。")
    assert R._GROUPS["zz_ea_appended"]["owner"] == "core"
    registry.mark_failed("zz_other", "x")
    assert "zz_ea_appended" in R._GROUPS                                      # 其他擁有者失敗時不被帶走


_FORBIDDEN_IN_MODULES = {"call": {"owner_scope"}, "name": {"_register_core", "_OWNER"}}


def _forbidden_uses(tree):
    """AST：呼叫 owner_scope(...)、或提到 _register_core／_OWNER 的位置。"""
    hits = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            nm = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
            if nm in _FORBIDDEN_IN_MODULES["call"]:
                hits.append((n.lineno, nm))
        elif isinstance(n, (ast.Name, ast.Attribute)):
            nm = getattr(n, "id", None) or getattr(n, "attr", None)
            if nm in _FORBIDDEN_IN_MODULES["name"]:
                hits.append((n.lineno, nm))
    return hits


def test_modules_never_touch_the_owner_machinery():
    """靜態守門：modules/** 不得自己呼叫 owner_scope、也不得使用 _register_core／_OWNER（擁有者只能來自載入器；否則模組可替別人登記）。"""
    root = Path(__file__).resolve().parents[2] / "modules"
    bad = []
    for f in root.rglob("*.py"):
        if "tests" in f.parts:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        bad += ["%s:%d %s" % (f.relative_to(root), ln, nm) for ln, nm in _forbidden_uses(tree)]
    assert bad == [], "模組不可碰擁有者機制：%s" % bad
    # 正對照：三種違規寫法都抓得到
    assert _forbidden_uses(ast.parse("with registry.owner_scope('core'):\n    pass")) == [(1, "owner_scope")]
    assert (1, "_register_core") in _forbidden_uses(ast.parse("settings_groups._register_core('g')"))
    assert (1, "_OWNER") in _forbidden_uses(ast.parse("registry._OWNER.set('core')"))


def test_modules_never_pass_owner_to_register_group():
    """靜態守門：modules/** 的程式碼不得以 owner= 呼叫 register_group（擁有者只能來自載入器的 import 範圍）。"""
    root = Path(__file__).resolve().parents[2] / "modules"
    bad = []
    for f in root.rglob("*.py"):
        if "tests" in f.parts:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                name = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
                if name == "register_group" and any(k.arg == "owner" for k in n.keywords):
                    bad.append("%s:%d" % (f.relative_to(root), n.lineno))
    assert bad == [], "模組不可自己指定設定群組的擁有者：%s" % bad
    # 正對照：掃描器抓得到違規寫法
    sample = ast.parse("register_group('g', 'x', [], owner='core')")
    assert any(isinstance(n, ast.Call) and any(k.arg == "owner" for k in n.keywords) for n in ast.walk(sample))
