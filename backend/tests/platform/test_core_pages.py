"""core.pages（階段 C／C1）：頁面對照與解析。合成目錄，不綁特定 L2 模組。"""
import json

import pytest

from core import pages as P


def _mk(tmp_path, l1=("index.html", "login.html"), legacy=(), moved=None):
    """l1_dir＝frontend/pages；legacy＝還沒搬家、放在 l1_dir 的模組頁；moved＝{key: [檔名]} 已搬進模組資料夾。"""
    l1_dir = tmp_path / "frontend" / "pages"
    l1_dir.mkdir(parents=True)
    for n in tuple(l1) + tuple(legacy):
        (l1_dir / n).write_text(n, encoding="utf-8")
    mods = tmp_path / "modules"
    for key, names in (moved or {}).items():
        (mods / key / "pages").mkdir(parents=True)
        for n in names:
            (mods / key / "pages" / n).write_text(key + "/" + n, encoding="utf-8")
    return l1_dir, mods


def _man(mods, **decl):
    return {k: ({"key": k, "pages": [{"path": n} for n in v]}, mods / k) for k, v in decl.items()}


def test_legacy_and_moved_pages_resolve_when_enabled(tmp_path):
    """正對照：未搬家（在 frontend/pages）與已搬家（在 modules/<key>/pages）都解析得到。"""
    l1_dir, mods = _mk(tmp_path, legacy=("a.html",), moved={"beta": ["b.html"]})
    pm = P.build_page_map(_man(mods, alpha=["a.html"], beta=["b.html"]), l1_dir)
    assert pm["a.html"] == ("alpha", l1_dir / "a.html")
    assert pm["b.html"] == ("beta", mods / "beta" / "pages" / "b.html")
    en = {"alpha", "beta"}
    assert P.resolve("a.html", pm, en, l1_dir) == l1_dir / "a.html"
    assert P.resolve("b.html", pm, en, l1_dir) == mods / "beta" / "pages" / "b.html"
    assert P.resolve("login.html", pm, en, l1_dir) == l1_dir / "login.html"


@pytest.mark.parametrize("where", ["legacy", "moved"])
def test_rc_disabled_module_page_is_not_served(tmp_path, where):
    """反向控制（裁示 D2）：模組停用 ⇒ None，不論頁面在哪裡；L1 頁不受影響。"""
    if where == "legacy":
        l1_dir, mods = _mk(tmp_path, legacy=("a.html",))
    else:
        l1_dir, mods = _mk(tmp_path, moved={"alpha": ["a.html"]})
    pm = P.build_page_map(_man(mods, alpha=["a.html"]), l1_dir)
    assert P.resolve("a.html", pm, set(), l1_dir) is None
    assert P.resolve("index.html", pm, set(), l1_dir) == l1_dir / "index.html"


def test_rc_case_variant_of_a_disabled_page_is_not_served(tmp_path):
    """反向控制：Windows 不分大小寫 ⇒ `A.HTML` 不可以繞過停用落到 frontend/pages。"""
    l1_dir, mods = _mk(tmp_path, legacy=("tender.html",))
    pm = P.build_page_map(_man(mods, alpha=["tender.html"]), l1_dir)
    for n in ("Tender.html", "TENDER.html"):
        assert P.resolve(n, pm, set(), l1_dir) is None
    assert P.resolve("Tender.html", pm, {"alpha"}, l1_dir) == l1_dir / "tender.html"


@pytest.mark.parametrize("name", ["../secret.html", "sub/x.html", "..\\x.html", "C:x.html", "x.html::$DATA",
                                  ".hidden.html", "x.htm", "", None, "x.html/"])
def test_rc_unsafe_names_are_rejected(tmp_path, name):
    l1_dir, mods = _mk(tmp_path)
    (tmp_path / "frontend" / "secret.html").write_text("s", encoding="utf-8")
    assert P.resolve(name, {}, set(), l1_dir) is None


def test_unknown_page_is_none(tmp_path):
    l1_dir, mods = _mk(tmp_path)
    assert P.resolve("nope.html", {}, set(), l1_dir) is None


def test_rc_two_modules_declaring_the_same_page_fail(tmp_path):
    l1_dir, mods = _mk(tmp_path, legacy=("a.html",))
    with pytest.raises(P.PageConflict, match="已由模組 alpha 提供"):
        P.build_page_map(_man(mods, alpha=["a.html"], beta=["A.html"]), l1_dir)


def test_rc_page_in_both_places_fails(tmp_path):
    """搬家後沒刪舊檔 ⇒ 兩份會漂移 ⇒ 失敗，不靜默挑一份。"""
    l1_dir, mods = _mk(tmp_path, legacy=("a.html",), moved={"alpha": ["a.html"]})
    with pytest.raises(P.PageConflict, match="有兩份"):
        P.build_page_map(_man(mods, alpha=["a.html"]), l1_dir)


def test_rc_declared_but_missing_page_fails(tmp_path):
    l1_dir, mods = _mk(tmp_path)
    with pytest.raises(P.PageConflict, match="不存在"):
        P.build_page_map(_man(mods, alpha=["ghost.html"]), l1_dir)


def test_rc_bad_declared_name_fails(tmp_path):
    l1_dir, mods = _mk(tmp_path)
    with pytest.raises(P.PageConflict, match="不合法"):
        P.build_page_map(_man(mods, alpha=["../index.html"]), l1_dir)


def test_real_repo_manifests_build_without_conflict():
    """正對照（真 repo）：現有 module.json 的 pages 宣告在目前的檔案配置下建得起來。"""
    import json
    from core import source_tree
    man = {d.name: (json.loads((d / "module.json").read_text(encoding="utf-8")), d) for d in source_tree.module_dirs()}
    pm = P.build_page_map(man, source_tree.BACKEND.parent / "frontend" / "pages")
    declared = sum(len(m.get("pages") or []) for m, _ in man.values())
    assert len(pm) == declared


# ── 寬鬆收集（比照 P-LD-07）與提供規則 ───────────────────────────────────────

def test_collect_refuses_the_later_module_whole(tmp_path):
    """撞名：先到的（key 排序）保留，後到的整個模組拒絕；它其他的頁面仍記在它名下（不可以漏給 L1 頁面目錄以 200 提供）。"""
    l1_dir, mods = _mk(tmp_path, legacy=("a.html", "b2.html"))
    pm, refused, _ = P.collect(_man(mods, alpha=["a.html"], beta=["A.html", "b2.html"]), l1_dir)
    assert list(refused) == ["beta"] and "已由模組 alpha 提供" in refused["beta"]
    assert pm["a.html"][0] == "alpha" and pm["b2.html"][0] == "beta"


def test_collect_other_problems_refuse_only_that_module(tmp_path):
    """不合法檔名 ⇒ 拒絕該模組；宣告了不存在的頁面 ⇒ 只列 missing、不拒絕（只宣告不建檔的合成模組不可以被改記 failed）。"""
    l1_dir, mods = _mk(tmp_path, legacy=("ok.html",))
    pm, refused, missing = P.collect(_man(mods, good=["ok.html"], ghost=["nope.html"], bad=["../x.html"]), l1_dir)
    assert set(refused) == {"bad"} and missing == {"ghost": ["nope.html"]}
    assert pm == {"ok.html": ("good", l1_dir / "ok.html")}


def _resp(pm, l1_dir, loaded=(), states=None):
    states = states or {}
    return lambda n: P.page_response(n, pm, l1_dir, lambda k: k in loaded, lambda k: states.get(k))


@pytest.mark.parametrize("state,kind", [({"state": "disabled", "name": "標案"}, "disabled"),
                                        ({"state": "unlicensed"}, "unlicensed"),
                                        ({"state": "failed"}, "failed"),
                                        ({"state": "loaded"}, "failed"),     # 狀態說 loaded 但沒載入 ⇒ 不一致 ⇒ failed
                                        (None, "missing")])
def test_unloaded_module_page_gets_the_notice(tmp_path, state, kind):
    l1_dir, mods = _mk(tmp_path, legacy=("t.html",))
    pm = P.build_page_map(_man(mods, alpha=["t.html"]), l1_dir)
    r = _resp(pm, l1_dir, states={"alpha": state} if state else {})("t.html")
    assert r[0] == "notice" and r[2] == kind
    assert 'data-testid="module-unavailable"' in r[1] and 'data-state="%s"' % kind in r[1]
    assert P.NOTICE[kind][0] in r[1]


def test_loaded_module_page_and_l1_page_are_files(tmp_path):
    l1_dir, mods = _mk(tmp_path, legacy=("t.html",))
    pm = P.build_page_map(_man(mods, alpha=["t.html"]), l1_dir)
    f = _resp(pm, l1_dir, loaded={"alpha"})
    assert f("t.html") == ("file", l1_dir / "t.html")
    assert f("login.html") == ("file", l1_dir / "login.html")
    assert f("nope.html") is None and f("../login.html") is None and f("sub/login.html") is None


def test_rc_case_variant_gets_the_notice_not_the_file(tmp_path):
    l1_dir, mods = _mk(tmp_path, legacy=("t.html",))
    pm = P.build_page_map(_man(mods, alpha=["t.html"]), l1_dir)
    assert _resp(pm, l1_dir)("T.html")[0] == "notice"


def test_notice_escapes_module_name():
    h = P.notice_html('<script>x</script>', "disabled")
    assert "<script>x" not in h and "&lt;script&gt;" in h


def test_check_and_register_marks_conflicting_module_failed(tmp_path, monkeypatch):
    """比照 P-LD-07：已載入的撞名模組 unload（路由、排程都不會再取到它）；沒載入的維持原狀態、只記 ERROR。"""
    from core import registry
    l1_dir, mods = _mk(tmp_path, legacy=("a.html",))
    for k, pages in (("alpha", ["a.html"]), ("beta", ["a.html"]), ("gamma", ["a.html"])):
        (mods / k).mkdir(parents=True, exist_ok=True)
        (mods / k / "module.json").write_text(json.dumps({"key": k, "name": k.upper(), "version": "1.0.0",
                                                          "pages": [{"path": p} for p in pages]}), encoding="utf-8")
    monkeypatch.setattr(registry, "_LOADED", {})
    monkeypatch.setattr(registry, "_STATES", {})
    monkeypatch.setattr(registry, "_FAILED", {})
    for k in ("alpha", "beta"):
        registry.register(registry.LoadedModule(key=k, manifest={"key": k}, spec=registry.ModuleSpec(key=k)))
    pm = P.check_and_register(mods, l1_dir)
    assert pm["a.html"][0] == "alpha"
    assert registry.is_loaded("alpha") and not registry.is_loaded("beta")
    st = {s["key"]: s for s in registry.module_states()}
    assert st["beta"]["state"] == "failed" and "頁面衝突" in st["beta"]["reason"]
    assert "gamma" not in st, "沒載入的模組維持原狀態（這裡是沒有狀態），不可以改記 failed 蓋掉停用／未授權原因"


def test_main_serves_pages_before_static_files():
    """/pages 路由要在 StaticFiles（mount "/"）之前，否則永遠輪不到它。以 AST 讀 main.py，不 import（副作用）。"""
    import ast
    from core import source_tree
    src = (source_tree.BACKEND / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    route_line = mount_line = check_line = modules_line = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "module_page":
            route_line = node.lineno
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "mount" and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "/":
                mount_line = node.lineno
            if node.func.attr == "check_and_register":
                check_line = node.lineno
            if node.func.attr == "mount_modules":
                modules_line = node.lineno
    assert None not in (route_line, mount_line, check_line, modules_line)
    assert check_line < modules_line < route_line < mount_line


# ── 稽核 D P-M1：模組不可以宣告 L1 頁面 ──────────────────────────────────────

@pytest.mark.parametrize("name", ["login.html", "Login.html"])
def test_rc_module_declaring_an_l1_page_is_refused(tmp_path, name):
    """探針：模組把 login.html 宣告成自己的 ⇒ 衝突、整個模組拒絕；login.html 不進 page_map（照舊由 L1 提供）。"""
    l1_dir, mods = _mk(tmp_path, legacy=("mine.html",))
    pm, refused, _ = P.collect(_man(mods, evil=[name, "mine.html"]), l1_dir, l1_pages=["login.html"])
    assert "evil" in refused and "L1 頁面" in refused["evil"]
    assert "login.html" not in {n.lower() for n in pm}


def test_rc_disabling_the_module_does_not_take_login_down(tmp_path, monkeypatch):
    """P-M1 的後果本身：宣告 L1 頁面的模組就算沒載入，/pages/login.html 仍是 L1 的檔，不是提示頁或 404。"""
    from core import registry
    l1_dir, mods = _mk(tmp_path)
    (mods / "evil").mkdir(parents=True)
    (mods / "evil" / "module.json").write_text(json.dumps({"key": "evil", "pages": [{"path": "login.html"}]}), encoding="utf-8")
    monkeypatch.setattr(registry, "_LOADED", {})
    monkeypatch.setattr(registry, "_STATES", {})
    monkeypatch.setattr(registry, "_FAILED", {})
    monkeypatch.setattr(P, "load_l1_pages", lambda path=None: {"login.html"})
    pm = P.check_and_register(mods, l1_dir)
    assert P.page_response("login.html", pm, l1_dir, lambda k: False, lambda k: None) == ("file", l1_dir / "login.html")


def test_l1_pages_file_matches_modules_json():
    """core/l1_pages.json 必須等於 docs/platform/modules.json 的 L1 頁面單位（index.html 在 frontend 根、不經 /pages，不列）。"""
    from core import source_tree
    m = json.loads((source_tree.BACKEND.parent / "docs" / "platform" / "modules.json").read_text(encoding="utf-8"))
    want = sorted(u[len("page:pages/"):] for u in m["L1"]["units"] if u.startswith("page:pages/"))
    assert sorted(json.loads(P.L1_PAGES_FILE.read_text(encoding="utf-8"))) == want
    assert "login.html" in P.load_l1_pages()


def test_real_modules_do_not_declare_l1_pages():
    from core import source_tree
    for d in source_tree.module_dirs():
        pages = {p["path"].lower() for p in json.loads((d / "module.json").read_text(encoding="utf-8")).get("pages") or []}
        assert not pages & P.load_l1_pages(), d.name
