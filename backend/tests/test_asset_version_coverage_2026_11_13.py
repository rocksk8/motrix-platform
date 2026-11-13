# -*- coding: utf-8 -*-
"""靜態資源版本守門（2026-11-13，PM 小票）：所有頁面／載入器引用的 js／css 網址，一律會被 `helpers/static_cache.rewrite_refs` 補上 `?v=`。

## 為什麼
沒帶 `?v=` 的 `.js`／`.css` 網址對 Cloudflare 是「可預設快取」的副檔名（預設約 4 小時）：發版後使用者最多 4 小時內拿到舊檔、
新舊 JS 混在一起跑。`tests/test_static_cache_versioning_2026_11_13.py` 已經守了一部分，但它有三個盲點（本檔補上）：
  ① 只認「路徑裡含 static／js／css 目錄」的 `src=／href=`——寫成 `<script src="foo.js">`、`<script src=foo.js>`、
     `<link rel=stylesheet href="x.css">` 之類的，根本不會被它**看見**（安靜地少守一塊）；
  ② 動態載入只看 `.src =` 同一行右側；`js.src = src`（變數傳入）、`link.href = …`、`setAttribute('src', …)`、`import()`、
     `importScripts`、`Worker`、`serviceWorker.register` 都沒人數；
  ③ 引號包起來但改寫器吃不下的字串（跳脫引號 `\\"…\\"`、路徑含奇怪字元、別的查詢字串）沒有一道全域掃描。

## 規則
- 本站 js／css 引用 ＝ 改寫器認得的形狀（`REF_RE`）⇒ 送出時一定帶 `?v=<目前版本>`。
- 唯一的例外：`static/vendor/<名稱>` 底下**檔名（或資料夾名）自帶版本號**的第三方函式庫，登記在 `VENDOR_VERSIONED`（附理由）。
  新增 vendor 檔而沒登記 ⇒ 紅燈；登記的檔不見了 ⇒ 紅燈（清單不留過期項）；登記了但名字裡沒有版本號 ⇒ 紅燈。
- 外部網址（`https://…`）不歸我們的快取管，但要登記在 `EXTERNAL_ALLOW`（附理由）——目前沒有頁面直接引用外部腳本。
- 動態組網址的載入器：右側必須含改寫器認得的字串字面值（＝走同一個加版本的函式 `rewrite_refs`）；做不到的列在 `DYNAMIC_ALLOW`
  （附理由），清單外的新載入點 ⇒ 紅燈。
"""
import re
from pathlib import Path

from core import source_tree
from helpers import static_cache as sc
from tests import _frontend_sources as FS

BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend"

_VER_IN_NAME = re.compile(r"\d+\.\d+\.\d+")

#: `static/vendor/<第一層名稱>` ⇒ 理由。名稱必須存在、必須帶版本號。
_VENDOR_REASON = ("檔名（資料夾名）自帶版本號 ⇒ 升版必改網址、同名檔內容不變；`/static/vendor/` 走 immutable 規則"
                  "（main._legacy_cache_headers），改寫器刻意不動（REF_RE 的 `(?!vendor/)`）")
VENDOR_VERSIONED = {
    "alpine-3.17.1.min.js": _VENDOR_REASON,
    "chart-4.4.0.umd.min.js": _VENDOR_REASON,
    "frappe-gantt-0.6.1.css": _VENDOR_REASON,
    "frappe-gantt-0.6.1.min.js": _VENDOR_REASON,
    "leaflet-1.9.4": _VENDOR_REASON,
    "leaflet.markercluster-1.5.3": _VENDOR_REASON,
    "markerclusterer-2.6.2": _VENDOR_REASON,
    "sortable-1.15.3.min.js": _VENDOR_REASON,
    "xlsx-0.18.5.full.min.js": _VENDOR_REASON,
}

#: 外部（不是我們送出的）腳本／樣式網址 ⇒ 理由。目前沒有。
EXTERNAL_ALLOW = {}

#: 動態載入點的例外：(檔名, 右側文字) ⇒ 理由。右側文字沒有改寫器認得的字面值、也不是 vendor 字面值的載入點。
DYNAMIC_ALLOW = {
    ("map.html", "o.scriptUrl"): (
        "同源 `/map-overlays/<模組>/<檔名>`（main.map_overlay_script，網址只由 L1 依已載入模組宣告組出）。不在 /static、/js、/css 底下 ⇒ "
        "`classify` 判為 other ⇒ 舊規則 `.js` 一律 no-store（不會被任何快取留住），不需要 `?v=`；見 test_map_overlay_scripts_are_never_cached"),
    ("map-google.js", "src"): (
        "通用 `loadScript(src)`；呼叫端只有兩個（Google Maps API 外部網址、CLUSTER_JS＝vendor 已登記資料夾），"
        "見 test_variable_loader_callers_pass_only_known_urls"),
    ("approval-settings.html", "src"): (
        "通用 `load(src)`；每個呼叫端的引數都是改寫器認得的字串字面值，見 test_variable_loader_callers_pass_only_known_urls"),
}

#: 其他載入方式（不是 createElement 的 script／link）。(檔名, 該行去頭尾空白) ⇒ 理由。目前沒有。
OTHER_LOADER_ALLOW = {}


# ── 原始碼範圍 ──────────────────────────────────────────────────────────────────

def _page_files():
    return [FRONTEND / "index.html"] + list(source_tree.page_files())


def _text_sources():
    """所有會被送出、而且可能含資源引用的文字檔：頁面、前端與模組自有 JS（列舉走 `_frontend_sources.all_js()`）、frontend 的 css（vendor 除外）、模組頁面旁的 js。"""
    out = list(_page_files()) + list(FS.all_js())
    out += [f for f in sorted(FRONTEND.rglob("*.css")) if "vendor" not in f.parts]
    for d in source_tree.module_dirs():                     # 模組頁面旁的 js（例：lodging/pages/lodging-overlay.js；不在 all_js 的範圍）
        pd = d / "pages"
        if pd.is_dir():
            out += [f for f in sorted(pd.iterdir()) if f.suffix == ".js"]
    return sorted(set(out))


def _read(f):
    return f.read_text(encoding="utf-8", errors="replace")


# ── ① 頁面的 <script src>／<link href> ───────────────────────────────────────────

_TAG = re.compile(r"""<(script|link)\b[^>]*>""", re.I | re.S)
_ATTR = re.compile(r"""\b(src|href)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""", re.I)
_REL = re.compile(r"""\brel\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""", re.I)
_VENDOR_SEG = re.compile(r"""(?:^|/)static/vendor/([^/?#'"\s]+)""")
_EXTERNAL = re.compile(r"""^(?:[a-z][a-z0-9+.-]*:)?//|^https?:""", re.I)


def _asset_refs(text):
    """⇒ [(標籤, 網址)]：`<script src>`、與是 stylesheet／preload／modulepreload／prefetch 或網址是 .css／.js 的 `<link href>`。"""
    out = []
    for m in _TAG.finditer(text):
        tag = m.group(1).lower()
        body = m.group(0)
        want = "src" if tag == "script" else "href"
        for a in _ATTR.finditer(body):
            if a.group(1).lower() != want:
                continue
            url = next(g for g in a.groups()[1:] if g is not None)
            if tag == "link":
                rel = _REL.search(body)
                rel_v = (next(g for g in rel.groups() if g is not None) if rel else "").lower()
                path = url.split("?", 1)[0].lower()
                if not (re.search(r"stylesheet|preload|modulepreload|prefetch", rel_v) or path.endswith((".css", ".js"))):
                    continue
            out.append((tag, url.strip()))
    return out


def _ref_problems(text, ver=None):
    """⇒ [說明]。`ver` 給了 ⇒ 還要求本站引用的查詢字串**剛好**是 `v=<ver>`（伺服器送出的版本）。"""
    out = []
    for tag, u in _asset_refs(text):
        if u.startswith(("data:", "#")):
            continue
        if _EXTERNAL.match(u):
            if u not in EXTERNAL_ALLOW:
                out.append("外部網址未登記（EXTERNAL_ALLOW）：<%s> %s" % (tag, u))
            continue
        if "/vendor/" in u or u.startswith("vendor/"):
            m = _VENDOR_SEG.search(u)
            if not m or m.group(1) not in VENDOR_VERSIONED:
                out.append("vendor 檔未登記（VENDOR_VERSIONED）：<%s> %s" % (tag, u))
            continue
        path, _, query = u.partition("?")
        if not sc.REF_RE.fullmatch('"' + path + '"'):
            out.append("改寫器認不得（不會補 ?v=）：<%s> %s" % (tag, u))
        elif ver is not None and query != "v=" + ver:
            out.append("沒帶目前版本 ?v=%s：<%s> %s" % (ver, tag, u))
    return out


def test_vendor_registry_matches_the_directory_and_every_name_carries_a_version():
    real = {p.name for p in (FRONTEND / "static" / "vendor").iterdir()}
    assert real == set(VENDOR_VERSIONED), (
        "vendor 目錄與 VENDOR_VERSIONED 不一致（新增請登記並寫理由、移除請刪登記）：多出 %s、缺少 %s"
        % (sorted(real - set(VENDOR_VERSIONED)), sorted(set(VENDOR_VERSIONED) - real)))
    unversioned = sorted(n for n in real if not _VER_IN_NAME.search(n))
    assert not unversioned, "vendor 檔（資料夾）名稱沒有版本號 ⇒ 升版時網址不變，會被快取住舊檔：%s" % unversioned
    assert all(VENDOR_VERSIONED.values()), "每一項登記都要寫理由"


def test_every_page_script_and_stylesheet_ref_is_versioned_or_registered():
    """原始碼層：所有頁面的 js／css 引用不是改寫器認得的形狀、就是登記過的 vendor（盲點 ①）。"""
    bad = []
    n = 0
    for f in _page_files():
        text = _read(f)
        n += len(_asset_refs(text))
        bad += ["%s: %s" % (f.name, p) for p in _ref_problems(text)]
    assert n > 300, "頁面引用數量不合理（解析器壞了？）：%d" % n
    assert not bad, "這些引用不會被補上 ?v=：\n" + "\n".join(bad)


def test_served_pages_reference_only_the_current_version(client):
    """伺服器**實際送出**的首頁與每一頁：每個 js／css 引用都是 `?v=<目前版本>`（或登記的 vendor）。比對的是送出的 HTML，不是原始碼。"""
    import main
    ver = main.ASSET_VERSION.current()
    bad = []
    n = 0
    names = ["/"] + ["/pages/" + p.name for p in source_tree.page_files()]
    for url in names:
        r = client.get(url)
        assert r.status_code == 200, url
        n += len(_asset_refs(r.text))
        bad += ["%s: %s" % (url, p) for p in _ref_problems(r.text, ver)]
    assert n > 300, n
    assert not bad, bad[:15]


def test_ref_parser_positive_controls():
    """正對照：守門不是空轉——舊守門看不見的寫法，這支一定抓得到。"""
    ok = '<script src="../static/a.js?v=abc"></script><link rel="stylesheet" href="../css/s.css">'
    assert _ref_problems(ok) == [] and _ref_problems(ok, "abc") and len(_asset_refs(ok)) == 2
    assert _ref_problems('<script src="../static/a.js?v=abc"></script>', "abc") == []
    for bad in ('<script src="foo.js"></script>',                       # 沒有目錄
                "<script src=foo.js></script>",                         # 無引號
                '<script defer src="../static/a.js?x=1"></script>',     # 別的查詢字串
                '<link rel=stylesheet href="x.css">',
                '<link href="../modules/x/y.css" rel="stylesheet">',    # 不在 static／js／css 底下
                '<script src="https://cdn.example/x.js"></script>',
                '<script src="//cdn.example/x.js"></script>',
                '<script src="../static/vendor/unknown-lib.js"></script>',
                '<link rel="preload" href="../js/a.js" as="script">' + '<script src="../js/a.js?v=old"></script>'):
        assert _ref_problems(bad, "abc"), bad
    assert not _ref_problems('<script src="../static/vendor/alpine-3.17.1.min.js"></script>')
    assert not _ref_problems('<link rel="icon" href="x.png"><script>var a=1</script>')       # 不是 js／css、沒有 src
    assert _ref_problems('<script src="../static/a.js?v=old"></script>', "new"), "舊版本字串要被抓"


# ── ② 動態載入點 ────────────────────────────────────────────────────────────────

_CREATE = re.compile(r"""createElement\(\s*['"](script|link)['"]\s*\)""")
_ASSIGN = re.compile(r"""\.(src|href)\s*=(?!=)\s*([^;\n]+)""")
_VENDOR_LIT = re.compile(r"""static/vendor/([^/'"`\s]+)""")
_OTHER_LOADERS = [
    ("setAttribute(src|href, 資源)", re.compile(r"""setAttribute\(\s*['"](?:src|href)['"]\s*,[^)\n]*(?:\.js|\.css|\b(?:static|js|css)/)""")),
    ("import()", re.compile(r"""(?<![\w.$])import\s*\(""")),
    ("importScripts／Worker／serviceWorker.register",
     re.compile(r"""importScripts\s*\(|new\s+(?:Shared)?Worker\s*\(|serviceWorker\s*\.\s*register""")),
    ("fetch(*.js|*.css)", re.compile(r"""fetch\(\s*[^)\n]*\.(?:js|css)\b""")),
]


def _loader_sites(name, text):
    """⇒ [(種類, 右側, 問題或 None)]。createElement('script'|'link') 之後最近的 `.src =`／`.href =` 就是它的網址。"""
    out = []
    for m in _CREATE.finditer(text):
        tag = m.group(1)
        nxt = _CREATE.search(text, m.end())
        window = text[m.end():min(nxt.start() if nxt else len(text), m.end() + 900)]
        want = "src" if tag == "script" else "href"
        rhs = None
        for a in _ASSIGN.finditer(window):
            if a.group(1) == want:
                rhs = a.group(2).strip()
                break
        if rhs is None:
            out.append((tag, "", "看不到網址的指派（%s.%s =）：請把網址寫在 createElement 附近的一行字面值" % (tag, want)))
        elif sc.REF_RE.search(rhs):
            out.append((tag, rhs, None))
        elif _VENDOR_LIT.search(rhs):
            seg = _VENDOR_LIT.search(rhs).group(1)
            out.append((tag, rhs, None if seg in VENDOR_VERSIONED else "vendor 檔未登記（VENDOR_VERSIONED）：%s" % seg))
        elif (name, rhs) in DYNAMIC_ALLOW:
            out.append((tag, rhs, None))
        else:
            out.append((tag, rhs, "右側沒有改寫器認得的字面值，也不在 DYNAMIC_ALLOW：%s" % rhs[:100]))
    return out


def _other_loader_hits(name, text):
    out = []
    for kind, rx in _OTHER_LOADERS:
        for m in rx.finditer(text):
            line = text.splitlines()[text.count("\n", 0, m.start())].strip()
            if (name, line) not in OTHER_LOADER_ALLOW:
                out.append("%s: %s：%s" % (name, kind, line[:120]))
    return out


def test_dynamic_script_and_link_loaders_use_versioned_literals_or_are_listed():
    """盲點 ②：每個 `createElement('script'|'link')` 的網址右側都要是改寫器認得的字面值（走 `rewrite_refs`）、已登記的 vendor，
    或列在 DYNAMIC_ALLOW；其他載入方式（import()、Worker…）一律要列在 OTHER_LOADER_ALLOW。清單不留過期項。"""
    bad, sites, used = [], 0, set()
    for f in _text_sources():
        if f.suffix == ".css":
            continue
        text = _read(f)
        for tag, rhs, problem in _loader_sites(f.name, text):
            sites += 1
            if problem:
                bad.append("%s: <%s> %s" % (f.name, tag, problem))
            elif (f.name, rhs) in DYNAMIC_ALLOW:
                used.add((f.name, rhs))
        bad += _other_loader_hits(f.name, text)
    assert sites >= 15, "找到的載入點數量不合理（掃描壞了？）：%d" % sites
    assert not bad, "新的動態載入點（請改成字面值、或列入白名單並寫理由）：\n" + "\n".join(bad)
    stale = sorted(set(DYNAMIC_ALLOW) - used)
    assert not stale, "DYNAMIC_ALLOW 有已經不存在的項目，請刪除：%s" % stale
    assert all(DYNAMIC_ALLOW.values()) and all(OTHER_LOADER_ALLOW.values())


def test_variable_loader_callers_pass_only_known_urls():
    """DYNAMIC_ALLOW 裡的通用載入函式（`load(src)`／`loadScript(src)`）：每個呼叫端的引數都是已知的——改寫器認得的字面值、
    或 Google Maps 外部 API、或 vendor 已登記資料夾。新增呼叫端而傳了別的 ⇒ 紅燈。"""
    appr = _read(source_tree.page_file("approval-settings.html"))
    calls = re.findall(r"""\bload\(\s*(['"][^'"\n]+['"])\s*\)""", appr)
    assert len(calls) >= 4, calls
    assert all(sc.REF_RE.fullmatch(c) for c in calls), [c for c in calls if not sc.REF_RE.fullmatch(c)]
    gm = _read(FRONTEND / "static" / "map-google.js")
    callers = sorted(c.strip() for c in re.findall(r"""\bloadScript\(([^)\n]*)\)""", gm) if c.strip() != "src")
    assert callers == ["API + q", "CLUSTER_JS"], callers
    api = re.search(r"""var API = '([^']+)'""", gm).group(1)
    cluster = re.search(r"""var CLUSTER_JS = '([^']+)'""", gm).group(1)
    assert api.startswith("https://maps.googleapis.com/"), "外部網址只允許 Google Maps API（改了要重審條款）"
    assert _VENDOR_LIT.search(cluster) and _VENDOR_LIT.search(cluster).group(1) in VENDOR_VERSIONED, cluster


def test_map_overlay_scripts_are_never_cached():
    """DYNAMIC_ALLOW 的 `/map-overlays/…` 例外成立的前提：它不在版本化範圍、而舊規則給 no-store。"""
    import main
    from starlette.responses import Response
    p = "/map-overlays/some_module/overlay.js"
    assert sc.classify(p) == "other"
    cc = main._legacy_cache_headers(p, Response()).headers["cache-control"]
    assert "no-store" in cc and "immutable" not in cc and "max-age" not in cc.replace("no-cache", ""), cc


def test_loader_scan_positive_controls():
    """正對照：變數傳入、`link.href`、setAttribute、import()、Worker 等舊守門看不見的寫法，這裡一定抓得到。"""
    js = "var s = document.createElement('script'); s.src = '../static/a.js'; document.head.appendChild(s)"
    assert _loader_sites("x.js", js) == [("script", "'../static/a.js'", None)]
    var = "const js = document.createElement('script')\njs.src = someUrl\n"
    assert _loader_sites("x.js", var)[0][2], "變數傳入的載入點要被抓（除非列在 DYNAMIC_ALLOW）"
    link = "const c = document.createElement('link')\nc.rel = 'stylesheet'\nc.href = base + 'theme.css'\n"
    assert _loader_sites("x.js", link)[0][2], "link.href 的拼接要被抓"
    link_ok = "const c = document.createElement('link')\nc.href = '../css/theme.css'\n"
    assert _loader_sites("x.js", link_ok)[0][2] is None
    vend = "var c = document.createElement('link'); c.href = '../static/vendor/leaflet-1.9.4/leaflet.css'"
    assert _loader_sites("x.js", vend)[0][2] is None
    vend_bad = "var c = document.createElement('link'); c.href = '../static/vendor/newlib/new.css'"
    assert _loader_sites("x.js", vend_bad)[0][2]
    no_assign = "var s = document.createElement('script'); document.head.appendChild(s)"
    assert _loader_sites("x.js", no_assign)[0][2]
    for hit in ("el.setAttribute('src', '../static/a.js')", "const m = await import('./a.js')", "importScripts('a.js')",
                "new Worker('../js/w.js')", "navigator.serviceWorker.register('/sw.js')", "fetch('../js/a.js')"):
        assert _other_loader_hits("x.js", hit), hit
    assert not _other_loader_hits("x.js", "img.setAttribute('src', url); fetch('/api/x')")


# ── ③ 全域：引號包起來、改寫器吃不下的資源字串 ─────────────────────────────────────

_ASSETISH = re.compile(
    r"""(?P<esc>\\?)(?P<q>['"`])(?:\.\./|\./|/)?(?:static|js|css)/(?!vendor/)[^'"`\s\\]*?\.(?:js|css)(?![A-Za-z0-9_])[^'"`\s\\]*(?P=esc)(?P=q)""")


def _unrewritten_strings(text):
    """⇒ [字串]：看起來是本站 js／css 網址、但經 `rewrite_refs` 之後仍沒有 `?v=<版本>` 的引號字串。"""
    out = []
    for m in _ASSETISH.finditer(sc.rewrite_refs(text, "VVVV")):
        if not m.group(0).endswith("?v=VVVV" + m.group("esc") + m.group("q")):
            out.append(m.group(0))
    return out


def test_no_served_source_holds_a_local_asset_string_the_rewriter_cannot_version():
    """盲點 ③：頁面、所有 js／css、模組 js 裡，凡是引號包起來的 `static|js|css/….js|css` 字串，改寫後都必須帶 `?v=`。
    （跳脫引號的 `\\"../static/a.js\\"`、含空白以外怪字元、`?x=1` 這類改寫器吃不下的寫法會紅燈。）"""
    bad = []
    for f in _text_sources():
        for s in _unrewritten_strings(_read(f)):
            bad.append("%s: %s" % (f.name, s[:100]))
    assert not bad, "這些字串不會被補 ?v=：\n" + "\n".join(bad)


def test_served_sidebar_and_a_module_js_have_no_unversioned_strings(client):
    """送出的 sidebar.js（含動態載入器與選單宣告）本體裡，沒有任何未帶版本的本站資源字串。"""
    import main
    ver = main.ASSET_VERSION.current()
    r = client.get("/static/sidebar.js?v=" + ver)
    assert r.status_code == 200
    assert not [s for s in _ASSETISH.finditer(r.text) if not s.group(0).endswith("?v=%s%s%s" % (ver, s.group("esc"), s.group("q")))]
    assert "?v=" + ver in r.text


def test_unrewritten_string_scan_positive_controls():
    assert not _unrewritten_strings("var a = '../static/a.js'; var b = \"js/b.js?v=old\"; var c = `css/c.css`")
    assert _unrewritten_strings("var a = '../static/a.js?x=1'")
    assert _unrewritten_strings('var h = "<script src=\\"../static/a.js\\"></script>"'), "跳脫引號的寫法改寫器看不見"
    assert _unrewritten_strings("var a = '../static/a.js#frag'"), "查詢字串以外的尾巴也不會被補版本"
    assert not _unrewritten_strings("var msg = 'cannot load static/a.js now'"), "含空白的整句訊息不是資源網址"
    assert not _unrewritten_strings("var v = '../static/vendor/alpine-3.17.1.min.js'")
