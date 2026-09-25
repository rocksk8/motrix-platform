# -*- coding: utf-8 -*-
"""L0 模組載入器與登錄表的契約（CORE-SPEC §4、§5）。"""
import importlib
import json
import sys

import pytest

from core import loader, registry, source_tree


@pytest.fixture
def clean_registry():
    snap = registry.snapshot()          # 整份複本（含 _STATES）；不自己列舉內部表
    registry._reset()
    yield
    registry.restore(snap)


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


def test_source_tree_covers_core_spec_subdirectories(tmp_path, monkeypatch):
    """稽核 Y-3：照 CORE-SPEC §3 用 `api/`、`service/` 子目錄的模組不可以被守門掃描漏掉（沙盒，不綁任何 L2 模組）。"""
    mod = tmp_path / "modules" / "zz"
    for rel in ("module.json", "__init__.py", "api/__init__.py", "api/x.py", "api/sub/y.py",
                "service/calc.py", "top.py", "tests/test_zz.py", "migrations/0001_a.py"):
        (mod / rel).parent.mkdir(parents=True, exist_ok=True)
        (mod / rel).write_text("{}" if rel.endswith(".json") else "", encoding="utf-8")
    for sub in ("routers", "helpers"):
        (tmp_path / sub).mkdir()
    monkeypatch.setattr(source_tree, "BACKEND", tmp_path.resolve())
    routers = {source_tree.rel(p) for p in source_tree.router_files()}
    logic = {source_tree.rel(p) for p in source_tree.logic_files()}
    assert routers == {"modules/zz/api/__init__.py", "modules/zz/api/x.py", "modules/zz/api/sub/y.py"}
    assert logic == {"modules/zz/service/calc.py", "modules/zz/top.py"}


# ── STATES-PLATFORM P-LD-07：路由衝突 ─────────────────────────────────────────

def _route_module(key, routes, providers=None):
    """合成模組：routes＝[(method, path)]，每條回 {"who": key}。不綁任何真實 L2 模組。"""
    from fastapi import APIRouter
    r = APIRouter()
    for method, path in routes:
        r.add_api_route(path, (lambda k=key: {"who": k}), methods=[method])
    spec = registry.ModuleSpec(key=key, routers=[r], providers=providers or {})
    manifest = {"key": key, "name": key, "version": "0.0.1"}
    registry.register(registry.LoadedModule(key=key, manifest=manifest, spec=spec))
    registry.set_state(key, registry.STATE_LOADED, "", manifest)


def _l1_app():
    from fastapi import APIRouter, FastAPI
    app = FastAPI()
    l1 = APIRouter()
    l1.add_api_route("/api/zzping", lambda: {"who": "L1"}, methods=["GET"])
    app.include_router(l1)
    return app


def test_mount_modules_refuses_route_conflicts(clean_registry):
    from fastapi.testclient import TestClient
    app = _l1_app()
    _route_module("za_hits_l1", [("GET", "/api/zzping"), ("GET", "/api/zza")],
                  providers={("zz.cap", "za"): lambda: 1})
    _route_module("zb_ok", [("GET", "/api/zzok"), ("GET", "/api/zzitem/{item_id}"), ("POST", "/api/zzping")])
    _route_module("zc_hits_module", [("GET", "/api/zzok")])
    _route_module("zd_hits_param", [("GET", "/api/zzitem/{no}")])

    refused = loader.mount_modules(app)

    assert set(refused) == {"za_hits_l1", "zc_hits_module", "zd_hits_param"}
    assert "GET /api/zzping 已由 L1 提供" in refused["za_hits_l1"]
    assert "GET /api/zzok 已由 模組 zb_ok 提供" in refused["zc_hits_module"]
    assert "GET /api/zzitem/{no} 已由 模組 zb_ok 提供" in refused["zd_hits_param"]
    st = {s["key"]: s for s in registry.module_states()}
    for k in refused:
        assert st[k]["state"] == "failed" and st[k]["reason"] == refused[k]
        assert registry.failed()[k] == refused[k]
    assert [m.key for m in registry.loaded()] == ["zb_ok"]
    assert registry.providers("zz.cap") == {}, "不掛的模組，它的 provider 也不可以再被取到"

    c = TestClient(app)
    assert c.get("/api/zzping").json() == {"who": "L1"}, "模組不可以蓋掉 L1"
    assert c.get("/api/zzok").json() == {"who": "zb_ok"}
    assert c.post("/api/zzping").json() == {"who": "zb_ok"}, "不同方法不算衝突"
    assert c.get("/api/zza").status_code == 404, "撞到的模組整個不掛（不掛一半）"


def test_mount_modules_without_conflict_mounts_everything(clean_registry):
    """反向控制：沒有衝突時全部照掛、不誤判。"""
    from fastapi.testclient import TestClient
    app = _l1_app()
    _route_module("zx_one", [("GET", "/api/zzx")])
    _route_module("zy_two", [("GET", "/api/zzy/{a}")])
    assert loader.mount_modules(app) == {}
    assert [m.key for m in registry.loaded()] == ["zx_one", "zy_two"]
    c = TestClient(app)
    assert c.get("/api/zzx").json() == {"who": "zx_one"} and c.get("/api/zzy/1").json() == {"who": "zy_two"}


def test_main_mounts_modules_after_every_l1_router():
    """main.py：mount_modules(app) 在最後一個 include_router 之後、StaticFiles 之前；模組的排程與啟動提示
    （迭代 registry.loaded() 的迴圈）都在它之後——否則被判衝突的模組已經掛上一部分或開始跑了。
    靜態讀 main.py（不 import main：本題不依賴 worker 有沒有先 import 過它）。"""
    import ast
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    include, mount_modules, static_mount, loops = [], [], [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "include_router":
                include.append(node.lineno)
            elif node.func.attr == "mount_modules":
                mount_modules.append(node.lineno)
            elif node.func.attr == "start_schedulers":
                loops.append(node.lineno)
            elif node.func.attr == "mount" and "StaticFiles" in ast.unparse(node):
                static_mount.append(node.lineno)
        if isinstance(node, ast.For) and "registry.loaded()" in ast.unparse(node.iter):
            loops.append(node.lineno)
    assert len(mount_modules) == 1 and include and static_mount and loops, (mount_modules, include, static_mount)
    assert max(include) < mount_modules[0] < min(static_mount)
    assert min(loops) > mount_modules[0], "排程／啟動提示迴圈在 mount_modules 之前：%s" % loops



def test_mount_modules_static_path_shadowed_by_earlier_param_route(clean_registry):
    """先掛的參數路由（L1 `/api/zzdoc/{doc_id}`）會接走模組的 `/api/zzdoc/status` ⇒ 模組那條永遠打不到＝衝突。
    反過來（模組是參數路由、L1 是固定路徑）不衝突：固定路徑仍由 L1 接，其他值由模組接。"""
    from fastapi import APIRouter
    from fastapi.testclient import TestClient
    app = _l1_app()
    l1 = APIRouter()
    l1.add_api_route("/api/zzdoc/{doc_id}", lambda doc_id: {"who": "L1"}, methods=["GET"])
    l1.add_api_route("/api/zzfix/status", lambda: {"who": "L1"}, methods=["GET"])
    app.include_router(l1)
    _route_module("zs_static", [("GET", "/api/zzdoc/status")])
    _route_module("zt_param", [("GET", "/api/zzfix/{x}")])
    refused = loader.mount_modules(app)
    assert set(refused) == {"zs_static"} and "L1" in refused["zs_static"]
    c = TestClient(app)
    assert c.get("/api/zzfix/status").json() == {"who": "L1"}
    assert c.get("/api/zzfix/other").json() == {"who": "zt_param"}


def test_mount_modules_refuses_unreadable_router(clean_registry):
    """模組 router 裡再 include 別的 router：新版 FastAPI 讀不出路徑 ⇒ 不掛（不猜）；舊版讀得出 ⇒ 照常比對。
    兩種版本都不可以「讀不出來就當沒有路由而掛上」。"""
    from fastapi import APIRouter
    inner = APIRouter()
    inner.add_api_route("/api/zzping", lambda: {"who": "inner"}, methods=["GET"])     # 撞 L1
    outer = APIRouter()
    outer.include_router(inner)
    spec = registry.ModuleSpec(key="zn_nested", routers=[outer])
    registry.register(registry.LoadedModule(key="zn_nested", manifest={"key": "zn_nested"}, spec=spec))
    registry.set_state("zn_nested", registry.STATE_LOADED, "", {"key": "zn_nested"})
    refused = loader.mount_modules(_l1_app())
    assert set(refused) == {"zn_nested"}, refused


def test_module_installed_positive_and_negative():
    """守門用的「模組在不在」只有一份（core.source_tree.module_installed）。正對照任取一個已安裝的模組，不綁特定 L2。"""
    mods = source_tree.module_dirs()
    if not mods:
        pytest.skip("沒有任何已安裝的模組 ⇒ 正對照無對象")
    k = mods[0].name
    for form in ("modules/%s/api.py" % k, "backend/modules/%s/x.py" % k, "backend" + chr(92) + "modules" + chr(92) + k + chr(92) + "x.py"):
        assert source_tree.module_installed(form) is True, form
    assert source_tree.module_installed("modules/zz_not_installed/api.py") is False
    assert source_tree.module_installed("routers/quotations.py") is True
