# -*- coding: utf-8 -*-
"""靜態資源版本化＋快取表頭（2026-11-13，「外網載入效能」票；實作 helpers/static_cache.py、接線 main.py::no_cache_static）。

守的四件事：
  1. 版本守門：伺服器送出的每一頁 HTML、每一支 JS/CSS 裡，本站資源引用（/static、/js、/css；vendor 除外）一律帶**目前**的 `?v=`；
     原始碼裡有「改寫器看不見」的引用寫法（串接字串、模板字串、帶別的查詢字串）⇒ 紅燈（漏帶版本＝使用者瀏覽器永遠拿舊檔或永遠不快取）。
  2. 表頭：帶目前版本的資源 `public, max-age=31536000, immutable`；沒帶／舊版本 ⇒ `no-cache`＋ETag；HTML `no-cache`＋ETag；
     vendor／fonts／API 的規則不動。
  3. 改版後 URL 一定會變：內容任何一支變 ⇒ 版本變 ⇒ 所有引用的網址變；只有 mtime 變（內容同）⇒ 版本不變。
  4. HTML 304：`If-None-Match` 命中 ⇒ 304 空本體；版本變了 ETag 就變（不會誤回 304 給舊內容）。
"""
import os
import re
import time
from pathlib import Path

import pytest

from core import source_tree
from tests import _frontend_sources as FS
from helpers import static_cache as sc

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"

#: 本站資源引用（不含 vendor）——寬鬆版，用來找「改寫器沒辦法處理」的寫法
_LOCAL_ATTR = re.compile(r"""\b(?:src|href)\s*=\s*(["'])(?P<v>[^"']*?(?:static|js|css)/[^"']*?\.(?:js|css|png|svg|jpg|jpeg|webp|gif|ico)[^"']*)\1""")


def _version(client):
    import main
    return main.ASSET_VERSION.current()


def _page_files():
    # 頁面位置一律經 source_tree（含各模組 pages/；有些頁面已搬進模組，不在 frontend 底下）
    return [FRONTEND / "index.html"] + list(source_tree.page_files())


def _is_vendor(path_text):
    return "/vendor/" in path_text or path_text.startswith("vendor/") or "static/vendor/" in path_text


# ── 1. 版本守門 ─────────────────────────────────────────────────────────────────

def test_source_attr_refs_are_all_rewritable():
    """原始碼的 `src=／href=` 引用本站資源時，整個值必須是改寫器認得的形狀（路徑＋可有 `?v=…`），否則改寫會漏掉它。"""
    bad = []
    for f in _page_files():
        text = f.read_text(encoding="utf-8")
        for m in _LOCAL_ATTR.finditer(text):
            v = m.group("v")
            if v.startswith(("http://", "https://", "//", "data:")) or _is_vendor(v):
                continue
            if not sc.REF_RE.fullmatch(m.group(1) + v + m.group(1)):
                bad.append("%s: %s" % (f.relative_to(FRONTEND.parent), v))
    assert not bad, "這些引用改寫器認不得（漏帶版本）。寫成 '<路徑>.js' 或 '<路徑>.js?v=…' 的單純字串：\n" + "\n".join(bad)


_JS_ASSIGN = re.compile(r"""\.(?:src|href)\s*=\s*([^;\n]+)""")
_CONCAT = re.compile(r"""(["'`])(?:\.\./|\./|/)?(?:static|js|css)/\1\s*\+|(?:static|js|css)/\$\{""")


def _js_sources():
    yield from FS.all_js()                       # frontend 全部 .js（不含 vendor）∪ 模組自有 js/（共用列舉入口）
    for d in source_tree.module_dirs():          # 模組 pages/ 底下的 .js（地圖覆蓋層等；不在共用入口的範圍）
        pd = d / "pages"
        if pd.is_dir():
            yield from sorted(q for q in pd.iterdir() if q.suffix == ".js")
    for f in _page_files():
        yield f


def test_script_built_urls_are_rewritable():
    """JS／頁內 `<script>` 動態組網址：`el.src = '…static/x.js'` 的右側若提到 static/js/css 資源，必須含改寫器認得的字串字面值；
    `'static/' + name`、`` `static/${name}` `` 這種拼接改寫器看不見 ⇒ 紅燈（請改成完整字面值，每個檔一行）。"""
    bad = []
    for f in _js_sources():
        text = f.read_text(encoding="utf-8", errors="replace")
        for m in _JS_ASSIGN.finditer(text):
            rhs = m.group(1)
            if not re.search(r"(?:static|js|css)/", rhs) or _is_vendor(rhs):
                continue
            if not sc.REF_RE.search(rhs):
                bad.append("%s: %s" % (f.name, rhs.strip()[:100]))
        for m in _CONCAT.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            ctx = text[max(0, m.start() - 40):m.end() + 40].replace("\n", " ")
            if _is_vendor(ctx):
                continue
            bad.append("%s:%d: %s" % (f.name, line, ctx))
    assert not bad, "動態組出的資源網址改寫器認不得：\n" + "\n".join(bad)


def test_rewriter_catches_and_skips_what_it_should():
    """正對照（守門不是空轉）：認得的會被補版本、vendor 與外部網址不動、別的查詢字串不吞掉。"""
    v = "abc123"
    assert sc.rewrite_refs('<script src="../static/a.js"></script>', v) == '<script src="../static/a.js?v=abc123"></script>'
    assert sc.rewrite_refs("<link href='css/style.css?v=20260805g'>", v) == "<link href='css/style.css?v=abc123'>"
    assert sc.rewrite_refs("sc.src = (p ? '../' : '') + 'static/ux-help.js'", v).endswith("'static/ux-help.js?v=abc123'")
    assert sc.rewrite_refs('<script src="../static/vendor/alpine-3.17.1.min.js">', v) == '<script src="../static/vendor/alpine-3.17.1.min.js">'
    assert sc.rewrite_refs('<script src="https://cdn.example/static/a.js">', v) == '<script src="https://cdn.example/static/a.js">'
    assert sc.rewrite_refs('<script src="/static/a.js?x=1">', v) == '<script src="/static/a.js?x=1">'
    assert sc.rewrite_refs('"static/a.js"', "v2") == '"static/a.js?v=v2"'
    # 守門的正對照：這種寫法改寫器看不見，守門必須抓得到
    assert not sc.REF_RE.search("el.src = '../static/' + name + '.js'")
    assert _CONCAT.search("el.src = '../static/' + name + '.js'")
    assert _CONCAT.search("el.src = `../static/${name}.js`")
    assert not sc.REF_RE.fullmatch('"../static/a.js?x=1"')


def test_every_served_page_references_only_the_current_version(client):
    """伺服器**實際送出**的每一頁：本站資源引用一律帶目前版本（不是只看原始碼）。"""
    ver = _version(client)
    bad = []
    names = ["/"] + ["/pages/" + p.name for p in source_tree.page_files()]
    for url in names:
        r = client.get(url)
        assert r.status_code == 200, url
        for m in _LOCAL_ATTR.finditer(r.text):
            v = m.group("v")
            if v.startswith(("http://", "https://", "//", "data:")) or _is_vendor(v):
                continue
            if not v.endswith("?v=" + ver):
                bad.append("%s: %s" % (url, v))
    assert not bad, bad[:10]


def test_dynamic_loaders_in_served_js_carry_the_version(client):
    """sidebar.js 動態載入 ux-help.js／menu-editor.js 等：送出的本體裡這些字串也帶版本（否則每次換頁又抓一次舊網址）。"""
    ver = _version(client)
    r = client.get("/static/sidebar.js?v=" + ver)
    assert r.status_code == 200
    assert "static/ux-help.js?v=" + ver in r.text
    assert "/static/menu-editor.js?v=" + ver in r.text
    assert not re.search(r"""['"]/?(?:\.\./)?static/(?:ux-help|menu-editor|export-editor|option-list-editor)\.js['"]""", r.text)


# ── 2. 表頭 ────────────────────────────────────────────────────────────────────

def test_versioned_assets_are_immutable(client):
    ver = _version(client)
    for url in ("/static/sidebar.js", "/css/style.css", "/static/notif.js", "/static/logo.png"):
        r = client.get(url + "?v=" + ver)
        assert r.status_code == 200, url
        assert r.headers["cache-control"] == "public, max-age=31536000, immutable", (url, r.headers["cache-control"])
        assert "pragma" not in r.headers and "expires" not in r.headers


def test_assets_without_or_with_stale_version_are_revalidated(client):
    for url in ("/static/notif.js", "/static/notif.js?v=stale000", "/css/style.css?v=20260805g"):
        r = client.get(url)
        assert r.status_code == 200, url
        assert r.headers["cache-control"] == "no-cache", (url, r.headers["cache-control"])
        assert "no-store" not in r.headers["cache-control"]
        assert r.headers.get("etag"), url
    # 舊版本網址拿到的是**現在**的內容（不可以回 404 讓舊分頁壞掉）
    cur = client.get("/static/notif.js?v=" + _version(client))
    old = client.get("/static/notif.js?v=stale000")
    assert cur.content == old.content


def test_html_is_no_cache_with_etag_and_pages_with_errors_are_not_cached(client):
    r = client.get("/pages/login.html")
    assert r.headers["cache-control"] == "no-cache" and r.headers["etag"]
    r = client.get("/")
    assert r.headers["cache-control"] == "no-cache" and r.headers["etag"]
    nf = client.get("/pages/__no_such_page__.html")
    assert nf.status_code == 404
    assert "immutable" not in nf.headers.get("cache-control", "")


def test_vendor_fonts_and_api_rules_unchanged(client):
    r = client.get("/static/vendor/alpine-3.17.1.min.js")
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert r.content == (FRONTEND / "static" / "vendor" / "alpine-3.17.1.min.js").read_bytes()      # vendor 本體不改寫
    r = client.get("/api/auth/me")
    cc = r.headers.get("cache-control", "")
    assert "immutable" not in cc and "public" not in cc and "max-age" not in cc, cc


def test_head_request_has_headers_and_no_body(client):
    ver = _version(client)
    r = client.head("/static/notif.js?v=" + ver)
    assert r.status_code == 200 and r.content == b""
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


# ── 3. 改版後 URL 一定會變 ───────────────────────────────────────────────────────

def _tree(tmp_path):
    for sub in ("static", "js", "css"):
        (tmp_path / sub).mkdir()
    (tmp_path / "static" / "a.js").write_text("var a=1;", encoding="utf-8")
    (tmp_path / "js" / "b.js").write_text("var b=1;", encoding="utf-8")
    (tmp_path / "css" / "c.css").write_text("body{}", encoding="utf-8")
    return str(tmp_path)


def test_version_changes_when_any_asset_content_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "TTL_S", 0.0)
    root = _tree(tmp_path)
    av = sc.AssetVersion(root)
    v0 = av.current()
    assert av.current() == v0
    html = '<script src="../static/a.js"></script><script src="../js/b.js"></script><link href="../css/c.css">'
    out0 = sc.rewrite_refs(html, v0)
    for rel, new in (("static/a.js", "var a=2;"), ("js/b.js", "var b=2;"), ("css/c.css", "body{x:1}")):
        p = tmp_path / rel
        old = p.read_text(encoding="utf-8")
        p.write_text(new, encoding="utf-8")
        v1 = av.current()
        assert v1 != v0, rel
        out1 = sc.rewrite_refs(html, v1)
        assert out1 != out0
        # 每一個引用的網址都換了（不是只換改到的那支）
        for a, b in zip(re.findall(r"\?v=\w+", out0), re.findall(r"\?v=\w+", out1)):
            assert a != b
        p.write_text(old, encoding="utf-8")
        assert av.current() == v0, "內容還原 ⇒ 版本回到原值（雜湊只看內容）"


def test_new_or_removed_asset_changes_version_but_touch_does_not(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "TTL_S", 0.0)
    root = _tree(tmp_path)
    av = sc.AssetVersion(root)
    v0 = av.current()
    p = tmp_path / "static" / "a.js"
    os.utime(p, (time.time() + 100, time.time() + 100))
    assert av.current() == v0, "只有 mtime 變 ⇒ 版本不變（不要白白讓全站快取失效）"
    (tmp_path / "static" / "new.js").write_text("x", encoding="utf-8")
    v1 = av.current()
    assert v1 != v0
    (tmp_path / "static" / "new.js").unlink()
    assert av.current() == v0
    # vendor 底下的檔不進版本（檔名自帶版本）
    (tmp_path / "static" / "vendor").mkdir()
    (tmp_path / "static" / "vendor" / "lib-1.0.js").write_text("x", encoding="utf-8")
    assert av.current() == v0


def test_sidebar_source_and_module_assets_feed_the_version(tmp_path, monkeypatch):
    """動態產生的 sidebar.js（選單宣告）、已載入模組的 JS 變了 ⇒ 版本也變。"""
    monkeypatch.setattr(sc, "TTL_S", 0.0)
    root = _tree(tmp_path)
    box = {"menu": "m1"}
    modjs = tmp_path / "mod.js"
    modjs.write_text("1", encoding="utf-8")
    av = sc.AssetVersion(root, sidebar_source=lambda: box["menu"], module_assets=lambda: {"mod.js": str(modjs)})
    v0 = av.current()
    box["menu"] = "m2"
    v1 = av.current()
    assert v1 != v0
    modjs.write_text("2", encoding="utf-8")
    assert av.current() not in (v0, v1)


def test_version_survives_missing_or_failing_sources(tmp_path, monkeypatch):
    """版本計算不可以讓請求失敗：sidebar／模組查表丟例外也只是少算那一塊。"""
    monkeypatch.setattr(sc, "TTL_S", 0.0)
    root = _tree(tmp_path)

    def boom():
        raise RuntimeError("x")
    assert sc.AssetVersion(root, sidebar_source=boom, module_assets=boom).current()


def test_served_version_changes_after_edit_of_a_real_frontend_file(client, monkeypatch):
    """端到端：改一支真的 frontend 資源（不實際寫檔，換掉 AssetVersion 的來源）⇒ 頁面裡的所有 ?v= 換成新值。"""
    import main
    monkeypatch.setattr(sc, "TTL_S", 0.0)
    old = client.get("/pages/account-items.html")
    v_old = main.ASSET_VERSION.current()
    assert ("?v=" + v_old) in old.text
    monkeypatch.setattr(main.ASSET_VERSION, "_sidebar_source", lambda: "changed-menu")
    new = client.get("/pages/account-items.html")
    v_new = main.ASSET_VERSION.current()
    assert v_new != v_old
    assert ("?v=" + v_new) in new.text and ("?v=" + v_old) not in new.text
    assert old.headers["etag"] != new.headers["etag"]


# ── 4. HTML 304 ────────────────────────────────────────────────────────────────

def test_html_conditional_get_returns_304(client):
    r1 = client.get("/pages/login.html")
    etag = r1.headers["etag"]
    assert r1.status_code == 200 and len(r1.content) > 1000
    r2 = client.get("/pages/login.html", headers={"If-None-Match": etag})
    assert r2.status_code == 304
    assert r2.content == b""
    assert r2.headers["etag"] == etag and r2.headers["cache-control"] == "no-cache"
    r3 = client.get("/pages/login.html", headers={"If-None-Match": 'W/"nope"'})
    assert r3.status_code == 200 and r3.content == r1.content
    r4 = client.get("/", headers={"If-None-Match": client.get("/").headers["etag"]})
    assert r4.status_code == 304


def test_asset_conditional_get_returns_304_and_matches_weak_etag(client):
    r1 = client.get("/static/notif.js")
    r2 = client.get("/static/notif.js", headers={"If-None-Match": r1.headers["etag"]})
    assert r2.status_code == 304 and r2.content == b""


def test_etag_helpers():
    assert sc._etag_matches('W/"a", "b"', 'W/"b"')
    assert sc._etag_matches("*", 'W/"x"')
    assert not sc._etag_matches('W/"a"', 'W/"b"')
    assert not sc._etag_matches(None, 'W/"b"')


def test_etag_differs_when_version_differs():
    body = b'<script src="../static/a.js"></script>'
    _b1, e1 = sc._rewritten(body, "v1")
    _b2, e2 = sc._rewritten(body, "v2")
    assert e1 != e2 and sc._rewritten(body, "v1")[1] == e1


# ── 5. 請求耗時 ─────────────────────────────────────────────────────────────────

def test_server_timing_only_on_static_content_and_authenticated_api(client, make_user):
    """P1：登入端點對「帳號不存在」與「密碼錯」的耗時不同 ⇒ 公開／未登入的 /api 不可帶 Server-Timing（帳號列舉的尺）。"""
    pat = r"app;dur=\d+(\.\d+)?"
    assert re.fullmatch(pat, client.get("/pages/login.html").headers.get("server-timing", ""))
    assert re.fullmatch(pat, client.get("/static/notif.js").headers.get("server-timing", ""))
    u, pw = make_user(username="st_user", role="admin")
    assert "server-timing" not in client.post("/api/auth/login", json={"username": "st_user", "password": "wrong-pass"}).headers
    assert "server-timing" not in client.post("/api/auth/login", json={"username": "no_such_user", "password": "wrong-pass"}).headers
    assert "server-timing" not in client.get("/api/system/branding").headers
    assert "server-timing" not in client.get("/api/notifications/mine").headers          # 未登入 ⇒ 401，不帶
    tok = client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]
    r = client.get("/api/notifications/mine", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 200 and re.fullmatch(pat, r.headers.get("server-timing", ""))


def test_request_ms_logged_for_slow_and_failed_requests(client, caplog, monkeypatch):
    import logging
    import main
    monkeypatch.setattr(main, "_REQ_LOG_MS", 0.0)
    with caplog.at_level(logging.INFO, logger="motrix.req"):
        client.get("/pages/login.html")
        client.post("/api/auth/login", json={"username": "x", "password": "y"})      # 401（公開端點、走得到）⇒ 也記
    lines = [r.getMessage() for r in caplog.records if r.name == "motrix.req"]
    assert any(re.fullmatch(r"REQ GET /pages/login\.html 200 \d+ms", l) for l in lines), lines
    assert any(re.fullmatch(r"REQ POST /api/auth/login 401 \d+ms", l) for l in lines), lines
    caplog.clear()
    monkeypatch.setattr(main, "_REQ_LOG_MS", 10 ** 9)
    with caplog.at_level(logging.INFO, logger="motrix.req"):
        client.get("/pages/login.html")                  # 快又成功 ⇒ 不寫（不浪費磁碟）
        client.get("/pages/login.html?token=SECRET")
    assert not [r for r in caplog.records if r.name == "motrix.req"]
    with caplog.at_level(logging.INFO, logger="motrix.req"):
        monkeypatch.setattr(main, "_REQ_LOG_MS", 0.0)
        client.get("/pages/login.html?token=SECRET")
    assert "SECRET" not in caplog.text, "只記路徑，不記 query（token 曾放在 query string）"


# ── 6. 輪詢（/api/online-users）──────────────────────────────────────────────────

def test_online_users_polling_is_slow_and_pauses_when_hidden():
    """在線成員輪詢：間隔 >= 120 秒、走 motrixVisiblePoll（document.hidden 時不打、回前景補一次）；不可退回裸 setInterval。
    （/api/reads 沒有輪詢：只在載頁與 `motrix:reads-changed`／回前景（60 秒節流）時打——見 notif.js。）"""
    side = (FRONTEND / "static" / "sidebar.js").read_text(encoding="utf-8")
    assert re.search(r"var ONLINE_POLL_MS = (\d+)", side) and int(re.search(r"var ONLINE_POLL_MS = (\d+)", side).group(1)) >= 120000
    assert "motrixVisiblePoll(refreshOnlineWidget, ONLINE_POLL_MS)" in side
    assert not re.search(r"setInterval\(\s*refreshOnlineWidget", side)
    helper = side[side.index("window.motrixVisiblePoll = "):side.index("function refreshOnlineWidget")]
    assert "document.hidden" in helper and "visibilitychange" in helper
    stats = source_tree.page_file("online-stats.html").read_text(encoding="utf-8")
    assert "motrixVisiblePoll(() => this.loadOnline()" in stats


def test_menu_declaration_change_changes_version_and_sidebar_url():
    """sidebar.js 的選單宣告隨模組狀態變 ⇒ 進版本雜湊 ⇒ 版本變 ⇒ 網址變（否則 immutable 會把舊選單釘在使用者瀏覽器一年）。"""
    import main
    from routers import platform_menu
    src = platform_menu.sidebar_js_source(main._PAGE_MAP, main.FRONTEND_DIR)
    assert src.startswith("window.MOTRIX_MENU = ")
    av = sc.AssetVersion(main.FRONTEND_DIR, sidebar_source=lambda: src)
    av2 = sc.AssetVersion(main.FRONTEND_DIR, sidebar_source=lambda: src.replace("window.MOTRIX_MENU", "window.MOTRIX_MENU ", 1))
    assert av.current() != av2.current()


def test_kill_switch_restores_legacy_headers_and_unrewritten_bodies(client, monkeypatch):
    """MOTRIX_STATIC_CACHE=0（緊急退回）：no-store、本體不改寫、沒有 ETag 改寫——與 2026-11-12 以前一致。"""
    import main
    monkeypatch.setattr(main, "_STATIC_CACHE_ON", False)
    r = client.get("/pages/account-items.html")
    assert "no-store" in r.headers["cache-control"]
    assert r.content == source_tree.page_file("account-items.html").read_bytes()
    r = client.get("/static/notif.js?v=anything")
    assert "no-store" in r.headers["cache-control"] and "immutable" not in r.headers["cache-control"]
    assert client.get("/static/vendor/alpine-3.17.1.min.js").headers["cache-control"] == "public, max-age=31536000, immutable"


# ── 7. 審查修正（hichan-2：P2 HEAD／304 表頭、P3 內容快照、P4 query）──────────────────────────

@pytest.mark.parametrize("url", ["/pages/account-items.html", "/static/notif.js", "/css/style.css", "/static/logo.png"])
def test_head_matches_get_headers_and_length(client, url):
    """P2：HEAD 與 GET 一樣改寫——ETag、Content-Length、Cache-Control 一致，本體為空。"""
    ver = _version(client)
    if not url.startswith("/pages"):
        url += "?v=" + ver
    g, h = client.get(url), client.head(url)
    assert g.status_code == h.status_code == 200
    assert h.content == b""
    assert h.headers["etag"] == g.headers["etag"]
    assert h.headers["content-length"] == str(len(g.content)) == g.headers["content-length"]
    assert h.headers["cache-control"] == g.headers["cache-control"]
    assert "server-timing" in h.headers and "server-timing" in g.headers


def test_304_carries_server_timing_and_vary(client):
    """P2：暖載入的 HTML 就是 304 的情形——要帶內層的 Server-Timing 與 Vary（CORS 的 Vary: Origin），不帶實體表頭。"""
    import main
    origin = {"Origin": main._DEFAULT_CORS_ORIGINS[0]}              # 帶白名單內的 Origin ⇒ CORS 中介層才會加 Vary: Origin（沒帶就沒有，測試不可依賴別題的副作用）
    r1 = client.get("/pages/account-items.html", headers=origin)
    r2 = client.get("/pages/account-items.html", headers={"If-None-Match": r1.headers["etag"], **origin})
    assert r2.status_code == 304 and r2.content == b""
    assert "server-timing" in r2.headers
    assert r2.headers.get("vary") == r1.headers.get("vary") and r1.headers.get("vary")
    assert r2.headers["cache-control"] == "no-cache" and r2.headers["etag"] == r1.headers["etag"]
    assert "content-type" not in r2.headers and r2.headers.get("content-length") in (None, "0")
    assert "x-content-type-options" in r2.headers          # 外層的安全標頭照樣加得上（不是 304 專屬的光禿回應）
    h = client.head("/pages/account-items.html", headers={"If-None-Match": r1.headers["etag"]})
    assert h.status_code == 304


def _mini_app(tmp_path, av, sidebar=None):
    """只裝 static_cache.handle 的最小 app（根目錄＝暫存樹）：不經過 main，可以自由改檔、控制 TTL。"""
    from starlette.applications import Starlette
    from starlette.responses import Response
    from starlette.routing import Mount, Route
    from starlette.staticfiles import StaticFiles
    from starlette.testclient import TestClient
    routes = []
    if sidebar is not None:
        routes.append(Route("/static/sidebar.js", lambda request: Response(sidebar(), media_type="application/javascript"), methods=["GET", "HEAD"]))
    routes.append(Mount("/", StaticFiles(directory=str(tmp_path))))
    app = Starlette(routes=routes)

    from starlette.middleware.base import BaseHTTPMiddleware

    class _MW(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            return await sc.handle(request, call_next, av, lambda p, r: r)
    app.add_middleware(_MW)
    return TestClient(app)


def test_immutable_requires_body_in_the_snapshot(tmp_path, monkeypatch):
    """P3：`?v=` 字串對、但本體不是快照裡的內容（檔案剛改完、版本還沒重算的窗口）⇒ 不給 immutable；版本重算後才給。"""
    monkeypatch.setattr(sc, "TTL_S", 3600.0)
    root = _tree(tmp_path)
    (tmp_path / "static" / "logo.png").write_bytes(b"PNG-old")
    av = sc.AssetVersion(root)
    c = _mini_app(tmp_path, av)
    ver = av.current()
    for u in ("/static/a.js", "/js/b.js", "/css/c.css", "/static/logo.png"):
        assert c.get(u + "?v=" + ver).headers["cache-control"] == sc.IMMUTABLE, u
    (tmp_path / "static" / "a.js").write_text("var a=2;", encoding="utf-8")
    (tmp_path / "static" / "logo.png").write_bytes(b"PNG-new")
    assert c.get("/static/a.js?v=" + ver).headers["cache-control"] == sc.REVALIDATE, "改完後版本還沒重算：舊 v 配新本體不可 immutable"
    assert c.get("/static/logo.png?v=" + ver).headers["cache-control"] == sc.REVALIDATE
    assert c.get("/js/b.js?v=" + ver).headers["cache-control"] == sc.IMMUTABLE, "沒改的檔不受影響"
    monkeypatch.setattr(sc, "TTL_S", 0.0)
    ver2 = av.current()
    assert ver2 != ver
    assert c.get("/static/a.js?v=" + ver2).headers["cache-control"] == sc.IMMUTABLE
    assert c.get("/static/a.js?v=" + ver).headers["cache-control"] == sc.REVALIDATE


def test_dynamic_sidebar_body_must_match_snapshot_too(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "TTL_S", 3600.0)
    root = _tree(tmp_path)
    box = {"src": "window.MOTRIX_MENU={a:1};"}
    av = sc.AssetVersion(root, sidebar_source=lambda: box["src"])
    c = _mini_app(tmp_path, av, sidebar=lambda: box["src"])
    ver = av.current()
    assert c.get("/static/sidebar.js?v=" + ver).headers["cache-control"] == sc.IMMUTABLE
    box["src"] = "window.MOTRIX_MENU={a:2};"                     # 模組狀態變了、版本還沒重算
    assert c.get("/static/sidebar.js?v=" + ver).headers["cache-control"] == sc.REVALIDATE


def test_immutable_only_when_query_is_exactly_the_version(tmp_path):
    """P4：`?v=<ver>&x=1`、`?x=1&v=<ver>` 之類不給 immutable（每種 query 在 CDN 各佔一份；也擋掉用 query 灌快取）。"""
    root = _tree(tmp_path)
    av = sc.AssetVersion(root)
    c = _mini_app(tmp_path, av)
    ver = av.current()
    assert c.get("/static/a.js?v=" + ver).headers["cache-control"] == sc.IMMUTABLE
    for q in ("v=%s&x=1", "x=1&v=%s", "v=%s&", "v=%s&v=%s", "V=%s"):
        r = c.get("/static/a.js?" + (q % ((ver,) * q.count("%s"))))
        assert r.status_code == 200 and r.headers["cache-control"] == sc.REVALIDATE, q
    assert c.get("/static/a.js?v=").headers["cache-control"] == sc.REVALIDATE


def test_visible_poll_refreshes_on_return_after_30s():
    """P5：回到前景距上次 >= 30 秒就補一次（不是等滿整個 120 秒）。"""
    side = (FRONTEND / "static" / "sidebar.js").read_text(encoding="utf-8")
    assert "Date.now() - last >= Math.min(ms, 30000)" in side
