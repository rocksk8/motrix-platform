# -*- coding: utf-8 -*-
"""靜態檔自動版本化與快取表頭（2026-11-13，「外網載入效能」票）。

## 為什麼
外網（Cloudflare 隧道）每個請求約 1 秒（edge 繞到 LAX／SJC，RTT ~133 ms；伺服器本身 14–24 ms）。以前所有 `/`、`/static/*`、`/js/*`、`/css/*`
都是 `no-cache, no-store, must-revalidate`，JS 引用又沒有版本字串（只有 style.css 有手寫的 `?v=`）⇒ **每換一頁都把 sidebar.js（108 KB）、
首頁（74 KB）等全部重抓一遍**，而每次要抓的都是 ~1 秒的往返。目標是「瀏覽器根本不發請求」：資源網址帶內容版本 ＋ `immutable`。

## 做法（伺服器端注入，不手改每一頁——hichan-1／4 同時在改 HTML，手改必衝突）
1. **內容版本（`AssetVersion`）**：所有 `frontend/static`（不含 vendor）、`frontend/js`、`frontend/css`、已載入模組的 JS、以及動態產生的
   `/static/sidebar.js`（含選單宣告）的**內容雜湊**。一個全域版本、不是每檔一個：檔案之間互相引用（sidebar.js 動態載入別的 js），
   每檔各自版本會有「A 的雜湊含 B 的網址、B 的網址含 B 的雜湊」的遞迴依賴。任何一個資源內容變 ⇒ 版本變 ⇒ 所有資源網址都變
   （一次部署後整批重抓一次，之後都從快取拿）。沒有人工維護的版本號。內容沒變（只是 mtime 變）⇒ 版本不變。
2. **改寫引用（`rewrite_refs`）**：送出 HTML 與 JS／CSS 本體前，把引號包起來的 `static/…`、`js/…`、`css/…` 資源網址
   （含 `../`、`./`、`/` 前綴；含動態載入的 `'static/ux-help.js'` 這類字串）補上／換成 `?v=<版本>`。
3. **表頭**：
   - 資源（`/static`、`/js`、`/css` 的 js／css／圖）請求的 `v` ＝目前版本 ⇒ `Cache-Control: public, max-age=31536000, immutable`；
     `v` 不是目前版本（舊頁面、手打網址）或沒有 `v` ⇒ `no-cache` ＋ ETag（會問、沒變回 304，不是 no-store）。
   - HTML（`.html`、`/`、`/pages/*`）⇒ `no-cache` ＋ ETag（改寫後內容的雜湊）；`If-None-Match` 命中回 **304**（省 74 KB）。
   - `/static/vendor/`、`/fonts/` 維持原規則；`/api/*`、其他沒列到的維持原規則（`no-store`）。
4. **安全**：舊版本網址請求拿到的是**現在**的內容但標 `no-cache`（不會把新內容用 immutable 釘在舊網址上）；版本重算最多每 `TTL_S` 秒一次
   （stat 簽章沒變就不重雜湊）。已知的窗口：檔案剛改完、版本重算之前的 ≤ `TTL_S` 秒內，帶舊 `v` 的請求會拿到新內容並被標 immutable——
   只有之後內容又**回到**同一個舊版本（回滾）時才會有人看到不對的快取，且 HTML 每次都重新驗證、會換成新 `v`。
"""
import hashlib
import logging
import os
import re
import threading
import time

from starlette.responses import Response

logger = logging.getLogger(__name__)

#: 版本重算的最短間隔（秒）。stat 簽章沒變就不重雜湊。
TTL_S = 3.0

IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"

_VERSIONED_EXTS = (".js", ".css", ".png", ".svg", ".jpg", ".jpeg", ".webp", ".gif", ".ico")
_TEXT_EXTS = (".js", ".css")

#: 引號包起來的本站資源網址（'…' "…" `…`）。⚠️ 排除 `vendor/`（檔名本身帶版本、另有 immutable 規則）。
#: 只認「沒有查詢字串」或「只有 ?v=…」的寫法——別的查詢字串（`?x=1`）不動，由守門題抓出來。
REF_RE = re.compile(
    r"""(?P<q>['"`])(?P<path>(?:\.\./|\./|/)?(?:static|js|css)/(?!vendor/)[A-Za-z0-9_./-]+\.(?:js|css|png|svg|jpg|jpeg|webp|gif|ico))"""
    r"""(?:\?v=[A-Za-z0-9._-]*)?(?P=q)"""
)


def rewrite_refs(text, version):
    """把 `text` 裡所有本站資源引用補上／換成 `?v=<version>`。"""
    return REF_RE.sub(lambda m: "%s%s?v=%s%s" % (m.group("q"), m.group("path"), version, m.group("q")), text)


def classify(path):
    """⇒ "html" | "asset_text"（.js/.css，本體要改寫）| "asset_bin"（圖）| "other"。"""
    p = path.split("?", 1)[0]
    if p in ("/", "") or p.endswith(".html") or p.startswith("/pages/"):
        return "html"
    if p.startswith(("/static/", "/js/", "/css/")) and not p.startswith("/static/vendor/"):
        low = p.lower()
        if low.endswith(_TEXT_EXTS):
            return "asset_text"
        if low.endswith(_VERSIONED_EXTS):
            return "asset_bin"
    return "other"


class AssetVersion:
    """全站資源的內容版本（見模組說明 §1）。`current()` 執行緒安全、最多每 TTL_S 秒重算一次。"""

    def __init__(self, frontend_dir, sidebar_source=None, module_assets=None):
        self.frontend_dir = frontend_dir
        self._sidebar_source = sidebar_source      # () -> str：動態產生的 /static/sidebar.js 內容
        self._module_assets = module_assets        # () -> {檔名: 實體路徑}：已載入模組提供的 /js 檔
        self._lock = threading.Lock()
        self._checked = 0.0
        self._sig = None
        self._content_digest = ""
        self._version = None

    def _files(self):
        out = []
        base = self.frontend_dir
        for sub in ("static", "js", "css"):
            root = os.path.join(base, sub)
            for dirpath, dirnames, filenames in os.walk(root):
                if sub == "static" and os.path.normpath(dirpath) == os.path.normpath(root):
                    dirnames[:] = [d for d in dirnames if d != "vendor"]
                for fn in filenames:
                    if fn.lower().endswith(_VERSIONED_EXTS):
                        out.append(os.path.join(dirpath, fn))
        if self._module_assets is not None:
            try:
                out.extend(sorted(self._module_assets().values()))
            except Exception:                                    # noqa: BLE001  版本計算不可以讓請求失敗
                logger.exception("static_cache: module assets lookup failed")
        return sorted(set(out))

    @staticmethod
    def _stat_sig(paths):
        sig = []
        for p in paths:
            try:
                st = os.stat(p)
                sig.append((p, st.st_mtime_ns, st.st_size))
            except OSError:
                sig.append((p, 0, -1))
        return tuple(sig)

    def _digest_files(self, paths):
        h = hashlib.sha1()
        for p in paths:
            h.update(os.path.relpath(p, self.frontend_dir).replace("\\", "/").encode("utf-8", "replace") if p.startswith(self.frontend_dir) else p.replace("\\", "/").encode("utf-8", "replace"))
            h.update(b"\0")
            try:
                with open(p, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        h.update(chunk)
            except OSError:
                h.update(b"<missing>")
            h.update(b"\1")
        return h.hexdigest()

    def current(self):
        now = time.monotonic()
        if self._version is not None and now - self._checked < TTL_S:
            return self._version
        with self._lock:
            now = time.monotonic()
            if self._version is not None and now - self._checked < TTL_S:
                return self._version
            paths = self._files()
            sig = self._stat_sig(paths)
            if sig != self._sig:
                self._content_digest = self._digest_files(paths)      # mtime 變而內容沒變 ⇒ 雜湊相同 ⇒ 版本不變
                self._sig = sig
            h = hashlib.sha1(self._content_digest.encode("ascii"))
            if self._sidebar_source is not None:
                try:
                    h.update(self._sidebar_source().encode("utf-8"))
                except Exception:                                      # noqa: BLE001
                    logger.exception("static_cache: sidebar source failed")
            self._version = h.hexdigest()[:12]
            self._checked = time.monotonic()
            return self._version


# ── 回應處理 ────────────────────────────────────────────────────────────────

_SKIP_HEADERS = {b"content-length", b"etag", b"last-modified", b"cache-control", b"pragma", b"expires", b"content-encoding", b"transfer-encoding"}
_CONDITIONAL = (b"if-none-match", b"if-modified-since", b"if-range")

_REWRITE_CACHE = {}          # (sha1(body), version) -> (bytes, etag)
_REWRITE_CACHE_MAX = 256
_REWRITE_LOCK = threading.Lock()


def _etag_matches(header_value, etag):
    """`If-None-Match` 是否命中（弱比對：忽略 W/；支援逗號分隔與 *）。"""
    if not header_value:
        return False
    want = etag[2:] if etag.startswith("W/") else etag
    for part in header_value.split(","):
        t = part.strip()
        if t == "*":
            return True
        if (t[2:] if t.startswith("W/") else t) == want:
            return True
    return False


def _rewritten(body, version, rewrite=True):
    """⇒ (新本體 bytes, etag)。同內容同版本的改寫結果快取（HTML 每頁都要過一次）。"""
    key = (hashlib.sha1(body).hexdigest(), version, rewrite)
    with _REWRITE_LOCK:
        hit = _REWRITE_CACHE.get(key)
    if hit is not None:
        return hit
    out = body
    if rewrite:
        try:
            out = rewrite_refs(body.decode("utf-8"), version).encode("utf-8")
        except UnicodeDecodeError:
            out = body
    res = (out, 'W/"%s"' % hashlib.sha1(out).hexdigest()[:20])
    with _REWRITE_LOCK:
        if len(_REWRITE_CACHE) >= _REWRITE_CACHE_MAX:
            _REWRITE_CACHE.clear()
        _REWRITE_CACHE[key] = res
    return res


def _strip_conditional_headers(request):
    """StaticFiles／FileResponse 會拿**原始檔**的 ETag 比對 If-None-Match 而自己回 304——我們改寫過本體，那個 ETag 對不上，
    所以交給我們自己比（拿掉下游看到的條件式表頭；原始值先存起來）。"""
    inm = request.headers.get("if-none-match")
    request.scope["headers"] = [(k, v) for (k, v) in request.scope["headers"] if k.lower() not in _CONDITIONAL]
    return inm


async def handle(request, call_next, version, legacy):
    """取代原本的 `no_cache_static` middleware 本體。`legacy(path, response)` 套用舊規則（vendor／fonts／其他 no-store）。"""
    path = request.url.path
    kind = classify(path)
    if kind == "other":
        return legacy(path, await call_next(request))

    is_get = request.method == "GET"
    inm = _strip_conditional_headers(request) if is_get and kind != "asset_bin" else None
    response = await call_next(request)

    if response.status_code != 200:
        return legacy(path, response)

    ver = version.current()
    if kind == "html":
        cache_control = REVALIDATE
    else:
        cache_control = IMMUTABLE if request.query_params.get("v") == ver else REVALIDATE

    if not is_get or kind == "asset_bin":
        # HEAD 不改寫（Content-Length 會對不上）；圖不改寫。只決定快取表頭。
        response.headers["Cache-Control"] = cache_control
        for h in ("Pragma", "Expires"):
            if h in response.headers:
                del response.headers[h]
        return response

    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode("utf-8"))
    body = b"".join(chunks)
    new_body, etag = _rewritten(body, ver)

    if _etag_matches(inm, etag):
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": cache_control})

    out = Response(content=new_body, status_code=200)
    raw = [(k, v) for (k, v) in response.raw_headers if k.lower() not in _SKIP_HEADERS and k.lower() != b"content-type"]
    ctype = response.headers.get("content-type")
    if ctype:
        raw.append((b"content-type", ctype.encode("latin-1")))
    raw.append((b"content-length", str(len(new_body)).encode("ascii")))
    raw.append((b"etag", etag.encode("ascii")))
    raw.append((b"cache-control", cache_control.encode("ascii")))
    out.raw_headers = raw
    return out
