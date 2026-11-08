# -*- coding: utf-8 -*-
"""模組自有前端 JS 的契約（STAGE-C-DESIGN §3；helpers.module_assets、core.loader.declared_assets、main.py 的 /js 掛載）。

網址不變（`/js/<檔名>.js`）、實體檔住 `modules/<key>/js/`。本檔分兩半：
  ① 合成模組樹（不綁任何真的 L2 模組，MODULE-GUIDE §7）：提供規則、四態、缺檔、撞名、路徑逃逸、格式檢查
  ② 真實樹（對現存的任何模組都成立）：宣告與檔案一致、不與 frontend/js 同名、頁面只載入自己模組的資產、L1 頁面不載入模組資產
"""
import json
import logging
import re
import sys
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from core import loader, pages, registry, source_tree
from core.registry import LoadedModule, ModuleSpec
from helpers import module_assets
from tests import _frontend_sources as FS

JS_BODY = "window.__zz = 'module-copy'\n"


def _w(path, text):
    """逐位元組寫入（Windows 的 write_text 會把 LF 換成 CRLF，比對回應本文會差一個字元）。"""
    Path(path).write_bytes(text.encode("utf-8"))


# ── ① 合成樹 ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def world(tmp_path, monkeypatch):
    """合成 modules/ 與 frontend/js；回傳 (client, add_module)。只有 add_module(loaded=True) 的才進 registry.loaded()。"""
    snap = registry.snapshot()
    mods = tmp_path / "modules"
    mods.mkdir()
    fjs = tmp_path / "frontend" / "js"
    fjs.mkdir(parents=True)
    _w(fjs / "plain.js", "window.__plain = 1\n")
    monkeypatch.setattr(loader, "MODULES_DIR", str(mods))
    module_assets._logged.clear()

    def add_module(key, assets, files=None, loaded=True, extra_manifest=None):
        d = mods / key
        (d / "js").mkdir(parents=True, exist_ok=True)
        for name, text in (files or {}).items():
            _w(d / "js" / name, text)
        manifest = {"key": key, "core": ">=1.0", "assets": assets, **(extra_manifest or {})}
        (d / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
        (d / "secret.txt").write_text("not-a-js-asset", encoding="utf-8")
        if loaded:
            registry.register(LoadedModule(key=key, manifest=manifest, spec=ModuleSpec(key=key)))

    app = Starlette(routes=[Mount("/js", module_assets.JsAssetLookup(directory=str(fjs)), name="js")])
    yield TestClient(app), add_module, fjs
    registry.restore(snap)
    module_assets._logged.clear()


def test_loaded_declared_asset_is_served_as_javascript_and_wins_over_a_same_name_frontend_file(world):
    client, add, fjs = world
    _w(fjs / "dup.js", "window.__dup = 'old-orphan'\n")     # 升級後留下的舊檔（孤兒）
    add("zz_a", [{"path": "js/dup.js"}, {"path": "js/only.js"}], {"dup.js": JS_BODY, "only.js": JS_BODY})
    for name in ("dup.js", "only.js"):
        r = client.get("/js/" + name)
        assert r.status_code == 200 and r.text == JS_BODY, name
        assert "javascript" in r.headers["content-type"]
    assert client.head("/js/only.js").status_code == 200


def test_non_module_js_is_still_served_from_frontend_js_and_missing_is_404(world):
    client, add, _ = world
    add("zz_a", [{"path": "js/a.js"}], {"a.js": JS_BODY})
    assert client.get("/js/plain.js").text == "window.__plain = 1\n"
    assert client.get("/js/nope.js").status_code == 404


@pytest.mark.parametrize("state", ["not_loaded", "no_such_module"])
def test_asset_of_a_module_that_is_not_loaded_is_404(world, state):
    """停用／未授權／載入失敗的模組不進 registry.loaded() ⇒ 它的 JS 不提供（乾淨的樹上 /js 也沒有同名檔 ⇒ 404）。"""
    client, add, _ = world
    if state == "not_loaded":
        add("zz_off", [{"path": "js/off.js"}], {"off.js": JS_BODY}, loaded=False)
    assert client.get("/js/off.js").status_code == 404


def test_file_present_but_not_declared_is_not_served(world):
    client, add, _ = world
    add("zz_a", [{"path": "js/a.js"}], {"a.js": JS_BODY, "extra.js": JS_BODY})
    assert client.get("/js/a.js").status_code == 200
    assert client.get("/js/extra.js").status_code == 404
    assert module_assets.undeclared_files("zz_a") == ["extra.js"]


def test_declared_but_missing_logs_error_serves_404_and_the_module_stays_loaded(world, caplog):
    client, add, _ = world
    add("zz_a", [{"path": "js/ghost.js"}, {"path": "js/real.js"}], {"real.js": JS_BODY})
    with caplog.at_level(logging.ERROR):
        assert client.get("/js/ghost.js").status_code == 404
        assert client.get("/js/ghost.js").status_code == 404
    assert client.get("/js/real.js").status_code == 200              # 同模組其他資產不受影響
    msgs = [r.getMessage() for r in caplog.records if "ghost.js" in r.getMessage()]
    assert len(msgs) == 1 and "zz_a" in msgs[0]                      # 記 ERROR，而且同一個問題只記一次（/js 每個請求都查表）
    assert registry.is_loaded("zz_a")                                # 不擋載入


def test_two_loaded_modules_declaring_the_same_name_first_by_key_wins_and_the_loser_is_logged(world, caplog):
    client, add, _ = world
    add("zz_b", [{"path": "js/same.js"}], {"same.js": "window.__who = 'b'\n"})
    add("zz_a", [{"path": "js/same.js"}], {"same.js": "window.__who = 'a'\n"})
    with caplog.at_level(logging.ERROR):
        assert client.get("/js/same.js").text == "window.__who = 'a'\n"
    assert any("same.js" in r.getMessage() and "zz_b" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("url", [
    "/js/../modules/zz_a/module.json", "/js/%2e%2e/modules/zz_a/secret.txt", "/js/..%2fmodules%2fzz_a%2fsecret.txt",
    "/js/sub/a.js", "/js/%5Ca.js", "/js/a.js%00", "/js/A.JS.txt",
])
def test_request_strings_never_reach_files_outside_the_declared_assets(world, url):
    client, add, _ = world
    add("zz_a", [{"path": "js/a.js"}], {"a.js": JS_BODY})
    r = client.get(url)
    assert r.status_code == 404 and "not-a-js-asset" not in r.text and "zz_a" not in r.text


def test_a_declared_asset_whose_realpath_leaves_js_is_not_served(world, tmp_path, monkeypatch):
    """宣告的檔解析後（連結、junction）落在 js/ 外面 ⇒ 不提供。Windows 一般帳號建不了符號連結，所以直接讓 realpath 回報逃出去的結果。"""
    import os
    client, add, _ = world
    add("zz_a", [{"path": "js/link.js"}, {"path": "js/ok.js"}], {"link.js": JS_BODY, "ok.js": JS_BODY})
    outside = tmp_path / "outside.js"
    _w(outside, "window.__leak = 1" + chr(10))
    real = os.path.realpath
    monkeypatch.setattr(module_assets.os.path, "realpath",
                        lambda p, *a, **k: str(outside) if str(p).endswith("link.js") else real(p, *a, **k))
    assert client.get("/js/link.js").status_code == 404
    assert client.get("/js/ok.js").status_code == 200


@pytest.mark.parametrize("bad", [
    [{"path": "js/../x.js"}], [{"path": "../js/x.js"}], [{"path": "x.js"}], [{"path": "js/sub/x.js"}], [{"path": "js/x.css"}],
    [{"path": "js/x.js"}, {"path": "js/x.js"}], [{"path": "js/x.js", "extra": 1}], ["js/x.js"], {"path": "js/x.js"}, [{"path": 1}],
])
def test_declared_assets_rejects_bad_shapes(bad):
    with pytest.raises(ValueError):
        loader.declared_assets({"assets": bad})


def test_declared_assets_accepts_none_empty_and_good():
    assert loader.declared_assets({}) == [] and loader.declared_assets({"assets": []}) == []
    assert loader.declared_assets({"assets": [{"path": "js/a-b_c.1.js"}]}) == ["js/a-b_c.1.js"]


def test_loader_refuses_a_module_with_a_malformed_assets_declaration_before_importing_it(tmp_path, monkeypatch):
    """形狀不對 ⇒ 不載入，而且不執行模組程式碼（import 之前驗；與 settings.groups 同位置）。"""
    snap = registry.snapshot()
    registry._reset()
    pkg = "fake_assets_mods"
    root = tmp_path / pkg
    root.mkdir()
    (root / "__init__.py").write_text("", encoding="utf-8")
    good = "from core.registry import ModuleSpec\nMODULE = ModuleSpec(key='{k}')\n"
    for key, assets in (("good", [{"path": "js/g.js"}]), ("bad", [{"path": "../g.js"}])):
        d = root / key
        d.mkdir()
        (d / "module.json").write_text(json.dumps({"key": key, "core": ">=1.0,<2.0", "assets": assets}), encoding="utf-8")
        (d / "__init__.py").write_text(
            ("raise RuntimeError('imported!')\n" if key == "bad" else good.format(k=key)), encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        got = loader.load_all(str(root), pkg)
        assert [m.key for m in got] == ["good"]
        assert "assets" in registry.failed()["bad"] and "imported!" not in registry.failed()["bad"]
        # 宣告了卻缺檔的 good 照常載入（裁示：記 ERROR 不擋載入）
        assert registry.is_loaded("good")
    finally:
        for k in list(sys.modules):
            if k.startswith(pkg):
                del sys.modules[k]
        registry.restore(snap)


# ── ② 真實樹 ──────────────────────────────────────────────────────────────────

def _module_manifests():
    return {d.name: json.loads((d / "module.json").read_text(encoding="utf-8-sig")) for d in source_tree.module_dirs()}


def test_every_declared_asset_exists_and_every_module_js_file_is_declared():
    """出貨前檢查（module_update check 也跑同一份判斷）：宣告與 `modules/<key>/js/` 的實際檔案一致。"""
    problems = []
    for d in source_tree.module_dirs():
        declared = {p.split("/", 1)[1] for p in loader.declared_assets(_module_manifests()[d.name])}
        have = {p.name for p in (d / "js").glob("*.js")} if (d / "js").is_dir() else set()
        problems += [f"{d.name}: 宣告了 {n} 但 js/ 底下沒有" for n in sorted(declared - have)]
        problems += [f"{d.name}: js/{n} 沒有在 module.json assets 宣告" for n in sorted(have - declared)]
        nested = [p for p in (d / "js").rglob("*.js") if p.parent != d / "js" and "vendor" not in p.parts] if (d / "js").is_dir() else []
        problems += [f"{d.name}: js/ 底下有子目錄的檔 {p.relative_to(d).as_posix()}（目前只支援單層檔名）" for p in nested]
    assert not problems, "\n".join(problems)


def test_no_module_js_name_exists_in_frontend_js_or_in_another_module():
    """同網址只能有一個來源：模組 JS 與 frontend/js／frontend/static 同名，或兩個模組同名 ⇒ 擋。"""
    seen, problems = {}, []
    for d in source_tree.module_dirs():
        for n in ([p.name for p in (d / "js").glob("*.js")] if (d / "js").is_dir() else []):
            if n in seen:
                problems.append(f"{n}: {seen[n]} 與 {d.name} 都有")
            seen[n] = d.name
            if (FS.FRONTEND / "js" / n).exists():
                problems.append(f"{n}: modules/{d.name}/js 與 frontend/js 都有")
    assert not problems, "\n".join(problems)


SCRIPT_SRC = re.compile(r"""<script[^>]+src\s*=\s*["']([^"']+)["']""", re.I)


def _page_script_names(page):
    """頁面載入的 `/js/<檔名>`（含 `../js/`、`js/` 相對寫法；忽略查詢字串）。"""
    out = []
    for src in SCRIPT_SRC.findall(page.read_text(encoding="utf-8-sig", errors="replace")):
        m = re.match(r"^(?:/|(?:\.\./)+|\./)?js/([^/?#]+\.js)(?:[?#].*)?$", src)
        if m:
            out.append(m.group(1))
    return out


def test_pages_load_only_their_own_modules_assets_and_l1_pages_load_none():
    """④ 模組 k 的資產只准 k 宣告的頁面載入；⑤ L1 頁面不得載入任何模組資產（未授權的模組不出貨該 JS，載入它的頁面會壞）。"""
    owner_of_asset, pages_of = {}, {}
    for key, mf in _module_manifests().items():
        for p in loader.declared_assets(mf):
            owner_of_asset[p.split("/", 1)[1]] = key
        pages_of[key] = {pg["path"].lower() for pg in mf.get("pages", []) if isinstance(pg, dict) and "path" in pg}
    l1 = pages.load_l1_pages()
    problems = []
    for page in source_tree.page_files():
        for name in _page_script_names(page):
            owner = owner_of_asset.get(name)
            if owner is None:
                continue
            if page.name.lower() in l1:
                problems.append(f"L1 頁面 {page.name} 載入了模組 {owner} 的資產 {name}")
            elif page.name.lower() not in pages_of[owner]:
                problems.append(f"頁面 {page.name} 載入了模組 {owner} 的資產 {name}，但它不是 {owner} 宣告的頁面")
    assert not problems, "\n".join(problems)


def test_a_page_script_pointing_at_a_module_asset_is_detected_positive_control(tmp_path):
    """正對照：掃描寫法要抓得到 `../js/x.js`、`/js/x.js`、帶查詢字串者，不抓 vendor／外部網址。"""
    p = tmp_path / "p.html"
    p.write_text('<script src="../js/a.js"></script><script src="/js/b.js?v=3"></script>'
                 '<script src="../vendor/c.js"></script><script src="https://x.example/js/d.js"></script>', encoding="utf-8")
    assert _page_script_names(p) == ["a.js", "b.js"]


# ── ③ 出貨前檢查（module_update.asset_problems；執行期不擋載入，擋在這裡）──────────────────────

def _mu():
    import importlib.util
    repo = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("_module_update_assets", repo / "tools" / "platform" / "module_update.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mdir(tmp_path, assets, files, extra_dirs=()):
    d = tmp_path / "zz"
    (d / "js").mkdir(parents=True)
    for n in files:
        _w(d / "js" / n, "1\n")
    for sub in extra_dirs:
        (d / "js" / sub).mkdir()
        _w(d / "js" / sub / "deep.js", "1\n")
    spec = {"key": "zz"} if assets is None else {"key": "zz", "assets": assets}
    _w(d / "module.json", json.dumps(spec))
    return d


def test_ship_check_passes_a_consistent_module_and_blocks_each_kind_of_mismatch(tmp_path):
    MU = _mu()
    ok = _mdir(tmp_path / "ok", [{"path": "js/a.js"}], ["a.js"])
    assert MU.asset_problems(ok) == []
    cases = {
        "宣告了缺檔": _mdir(tmp_path / "m1", [{"path": "js/a.js"}, {"path": "js/ghost.js"}], ["a.js"]),
        "有檔沒宣告": _mdir(tmp_path / "m2", [{"path": "js/a.js"}], ["a.js", "extra.js"]),
        "形狀不對": _mdir(tmp_path / "m3", [{"path": "../a.js"}], ["a.js"]),
        "重複": _mdir(tmp_path / "m4", [{"path": "js/a.js"}, {"path": "js/a.js"}], ["a.js"]),
        "子目錄": _mdir(tmp_path / "m5", [{"path": "js/a.js"}], ["a.js"], extra_dirs=["sub"]),
        "沒宣告區段卻有 js/ 檔": _mdir(tmp_path / "m6", None, ["a.js"]),
    }
    for label, d in cases.items():
        assert MU.asset_problems(d), label


def test_ship_check_is_silent_for_a_module_without_assets_or_js_dir(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    _w(d / "module.json", json.dumps({"key": "plain"}))
    assert _mu().asset_problems(d) == []


def test_loader_and_ship_check_agree_on_which_declarations_are_well_formed(tmp_path):
    """兩邊各有一份格式規則（module_update 不 import backend）⇒ 同一批宣告兩邊的判定必須一致。"""
    MU = _mu()
    samples = [[{"path": "js/a.js"}], [{"path": "js/a-b_c.1.js"}], [{"path": "js/.a.js"}], [{"path": "js/a.JS"}], [{"path": "js/a.mjs"}],
               [{"path": "js/sub/a.js"}], [{"path": "/js/a.js"}], [{"path": "js/a.js", "x": 1}], [{"path": "js/a.js"}, {"path": "js/a.js"}],
               {"path": "js/a.js"}, ["js/a.js"], [], [{"path": "js/ a.js"}], [{"path": "js/a.js\n"}]]
    for i, decl in enumerate(samples):
        try:
            loader.declared_assets({"assets": decl})
            loader_ok = True
        except ValueError:
            loader_ok = False
        d = tmp_path / ("s%d" % i)
        (d / "js").mkdir(parents=True)
        _w(d / "module.json", json.dumps({"key": "zz", "assets": decl}))
        for x in (decl if isinstance(decl, list) else []):
            if isinstance(x, dict) and isinstance(x.get("path"), str) and _is_plain(x["path"]):
                _w(d / x["path"], "1\n")
        shape_bad = any("形狀不對" in p or "重複" in p for p in MU.asset_problems(d))
        assert loader_ok == (not shape_bad), decl


def _is_plain(path):
    return bool(re.fullmatch(r"js/[A-Za-z0-9][A-Za-z0-9_.-]*\.js", path))


# ── ④ 選題不退化：模組 JS 搬家後 test_map／modtest 仍認得它（本檔只管機制，不綁任何真的模組）────────────────────

def _tools():
    repo = Path(__file__).resolve().parents[3]
    if str(repo / "tools" / "platform") not in sys.path:
        sys.path.insert(0, str(repo / "tools" / "platform"))
    import test_map
    return test_map


def test_test_map_names_a_module_js_like_the_url_it_is_served_at():
    TM = _tools()
    assert TM.unit_name("backend/modules/zz/js/a-b.js") == "js:js/a-b.js"
    assert TM.unit_name("frontend/js/a-b.js") == "js:js/a-b.js"                       # 搬前搬後同一個單位名
    assert TM.unit_name("backend/modules/zz/js/vendor/x.js").startswith("file:")       # vendor 不算
    assert TM.unit_name("backend/modules/zz/tests/a.js").startswith("file:")           # 不在 js/ 底下不算
    assert TM.unit_name("backend/modules/zz/api.py") == "mod:zz/api"                   # 其他類型不受影響


def test_test_map_resolver_finds_a_module_js_by_name_and_keeps_the_frontend_js_directory_unambiguous():
    TM = _tools()
    files = ["frontend/js/other.js", "frontend/pages/p.html", "backend/modules/zz/js/mine.js", "backend/modules/zz/module.json"]
    R = TM.Resolver(files)
    assert R.asset("mine.js") == "backend/modules/zz/js/mine.js"
    assert R.asset("js/mine.js") == "backend/modules/zz/js/mine.js"
    assert R.asset("other.js") == "frontend/js/other.js"
    assert R.fragment("js", as_dir=True) == "frontend/js/"        # 模組 js/ 目錄不可以讓「js」這個片段變得不唯一
    assert R.asset("x.css") is None


def test_a_guard_that_lists_js_through_the_shared_enumeration_is_still_picked_when_frontend_js_changes(tmp_path):
    """守門改走 tests/_frontend_sources.py 後字面路徑消失 ⇒ test_map 要補回 `dir:frontend/js/`，modtest 要把模組 JS 的改動算進去。"""
    TM = _tools()
    (tmp_path / "backend" / "tests").mkdir(parents=True)
    (tmp_path / "frontend" / "js").mkdir(parents=True)
    (tmp_path / "backend" / "tests" / "_frontend_sources.py").write_text("X = 1\n", encoding="utf-8")
    t = tmp_path / "backend" / "tests" / "test_zz_guard.py"
    t.write_text("from tests import _frontend_sources as FS\n\ndef test_x():\n    assert FS.top_js() is not None\n", encoding="utf-8")
    R = TM.Resolver(["backend/tests/_frontend_sources.py", "backend/tests/test_zz_guard.py", "frontend/js/a.js"])
    got = TM.scan_test(t, R)
    assert "dir:frontend/js/" in got["units"], got
    assert TM._MODULE_JS_RE.match("backend/modules/zz/js/a.js") and not TM._MODULE_JS_RE.match("backend/modules/zz/js/sub/a.js")
