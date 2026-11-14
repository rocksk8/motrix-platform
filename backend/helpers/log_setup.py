# -*- coding: utf-8 -*-
"""日誌分流與輪替（2026-11-13，正式機 server.log 53 MB 且持續增長；jeff：日誌必須分流和輪替，不可以無限變大）。

## 以前
`autostart.bat` 把 `uvicorn … >> logs\\server.log 2>&1` 的 stdout／stderr 全部倒進**一個檔**：uvicorn access（每個請求一行）、
uvicorn error、應用程式 logger、`print`、Traceback 全混在一起，沒有大小上限。`archive._rotate_server_log_if_large` 事後用 copytruncate
輪替，但那個檔是 cmd 的 `>>` 開的（不給寫入共用），要靠本行程用自己的 fd 清空（見該函式）——能用，但治標。

## 現在（兩層）
1. **分流（本檔）**：server 行程自己用 `RotatingFileHandler` 寫兩個檔，由行程內輪替、不經過任何外部 handle，所以不會被鎖：
   - `logs\\access.log`：uvicorn access（每個請求一行）。
   - `logs\\app.log`：應用程式 logger、uvicorn error、asyncio 等所有其他 logger（含 ERROR／Traceback）。
   單檔上限 15 MB、保留 10 份；輪替出來的舊檔在背景執行緒 **gzip 壓縮**（`app.log.1.gz`…）。
2. **stdout／stderr 兜底（`server.log`，仍是 cmd 的 `>>`）**：只剩 ① 開機那一段（見下）② WARNING 以上 ③ `print`／未被 logging 接住的輸出。
   分流之後它應該只剩少量內容；超過 50 MB 時仍由 `archive._rotate_server_log_if_large` 用 ftruncate 方案清（兜底，不是主角）。

## ⚠️ 為什麼 server.log 還要留開機那一段（不可以全部關掉）
`apply_update.ps1`／`apply_module_update.ps1` 的健康檢查**讀 server.log**：找「MOTRIX ERP starting」（cmd 寫）＋「Uvicorn running on」＋
`模組 <key> <版本> 已載入`＋`MOTRIX_GEO=1` 之類開關行（都是 INFO），再掃之後有沒有 `Traceback|ERROR`。
所以 console handler 的規則是：**WARNING 以上永遠照寫；INFO 只在開機期間照寫**（到「Uvicorn running on」出現為止，最長 10 分鐘），
開機之後的 INFO（一般運作訊息、access）只進 app.log／access.log。ERROR／Traceback 兩邊都有 ⇒ 健康檢查的錯誤掃描不受影響。
任何一個檔打不開（磁碟滿、權限）⇒ **整個分流不啟用**、維持舊行為（console 照舊全寫）——日誌設定不可以變成起不來的理由。

## 噪音：ConnectionResetError WinError 10054
Windows 的 asyncio proactor 事件迴圈，在**客戶端突然斷線**（關分頁、手機換網路、Cloudflare 隧道重連）時，會在
`_ProactorBasePipeTransport._call_connection_lost` 這個 callback 裡噴一段 `ConnectionResetError: [WinError 10054]` 的整段 traceback
（`asyncio` logger，ERROR 層級）。這是 CPython 在 Windows 上眾所皆知的現象（bpo-39010 等），對服務健康完全無影響、也沒有辦法在應用層避免。
正式機 server.log 裡 742 筆。⇒ 在 `asyncio` logger 掛 filter：認得這一種就**只計數**（`noise_count()`），預設不寫；
把 asyncio logger 開到 DEBUG 時留一行不帶 traceback 的摘要。其他例外（包含別種 ConnectionResetError）照舊完整記錄。
（部署腳本掃 log 時本來就會把這個區塊濾掉，行為相容。）

## 請求耗時（T86，PM 裁示 C：不動資料表，改寫獨立輪替檔）
`logs\\request_timing.log`：一行一筆「時間 方法 路由樣板 狀態碼 耗時ms」（例：`2026-11-14 10:00:00,123 GET /api/dev-cases/{case_id} 200 37`）。
用途＝正式機統計「最耗時的請求」。**只記 /api/ 請求**；**不含使用者、IP、查詢參數、實際路徑**（只有路由樣板，編號已被樣板去掉；
沒比對到路由的一律寫 `(unmatched)`，不寫原始路徑）。寫入走 `QueueHandler`＋背景 `QueueListener`：請求執行緒只做一次 `put_nowait`，
佇列滿了就丟掉並計數（`dropped`），絕不等檔案 I/O、絕不擋請求；檔案打不開 ⇒ 不啟用（`install_request_timing` 回 None），請求照常。
輪替／gzip／保留天數與 access.log 同一套（`GzipRotatingFileHandler`、`retention.log_keep_days`）。pytest 之下不建檔。
契約測試：tests/test_request_timing_log_2026_11_14.py。

## 保留期
輪替出來的舊檔（`access.log.N.gz`、`app.log.N.gz`、`request_timing.log.N.gz`、舊的 `server.log.N`）超過 `retention.log_keep_days`（設定中心「保存期限」群組，預設 30 天）
就刪——由 `archive._daily_backup` 每天呼叫 `prune_rotated_logs`（納入既有的備份／保留機制）。現行檔（`access.log`、`app.log`、`server.log`）永遠不刪。
"""
import asyncio
import gzip
import logging
import logging.handlers
import os
import queue
import re
import sys
import threading
import time

APP_LOG_NAME = "app.log"
ACCESS_LOG_NAME = "access.log"
TIMING_LOG_NAME = "request_timing.log"
#: 單檔 15 MB（PM：10～20 MB）× 保留 10 份（輪替出來的是 gzip，實際佔用遠小於 150 MB）
DEFAULT_MAX_BYTES = 15 * 1024 * 1024
DEFAULT_BACKUPS = 10
#: console（＝server.log）在開機期間照寫 INFO 的最長時間；正常情況在「Uvicorn running on」出現時就結束
BOOT_WINDOW_MAX_S = 600
#: 輪替失敗（舊檔被別的程式開著、磁碟滿）後，多久之後才再試——不可以每一筆 log 都重試一次
ROLLOVER_RETRY_S = 300

_APP_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_ACCESS_FORMAT = "%(asctime)s %(message)s"

#: 保留期清理要認的檔名：輪替出來的世代（含壓縮中的暫存檔）。⚠️ 現行檔與 `server.log.rotating`（接手用）不在內
_ROTATED_RE = re.compile(r"^(?:access\.log|app\.log|request_timing\.log|server\.log)\.\d+(?:\.gz)?(?:\.pending|\.tmp)?$")


# ── 輪替＋gzip 的 handler ───────────────────────────────────────────────────

class GzipRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """`RotatingFileHandler`，輪替出來的檔案改名 `<檔>.N.gz` 並在背景執行緒壓縮。

    - 輪替本身只是改名（微秒級）；gzip 15 MB 要一秒左右，放在背景，不卡住正在寫 log 的請求執行緒。
    - 輪替失敗（Windows 上舊檔被別的程式——防毒、備份軟體——開著）⇒ 不丟例外、不每筆重試：重開現行檔繼續寫，
      `ROLLOVER_RETRY_S` 之後才再試，並在 stderr 留一行（進 server.log 兜底）。標準 `RotatingFileHandler` 在這種情況會每筆 log 都
      重試並印一整段 `--- Logging error ---`。
    """

    def __init__(self, filename, maxBytes=DEFAULT_MAX_BYTES, backupCount=DEFAULT_BACKUPS, retry_after_s=ROLLOVER_RETRY_S):
        super().__init__(filename, maxBytes=maxBytes, backupCount=backupCount, encoding="utf-8")
        self.namer = lambda name: name + ".gz"
        self.rotator = self._rotate_and_compress
        self._retry_after_s = retry_after_s
        self._next_try = 0.0
        self.last_rollover_error = None

    # 標準流程：shouldRollover ⇒ doRollover。兩處都加保護。
    def shouldRollover(self, record):
        if time.monotonic() < self._next_try:
            return False
        return super().shouldRollover(record)

    def doRollover(self):
        try:
            super().doRollover()
        except OSError as exc:
            self.last_rollover_error = exc
            self._next_try = time.monotonic() + self._retry_after_s
            try:
                if self.stream is None:
                    self.stream = self._open()           # 標準流程在失敗時已把串流關掉了：重開，否則之後每筆都 handleError
            except OSError:
                pass
            try:
                sys.stderr.write("[log_setup] %s 輪替失敗（%s: %s）；%d 秒後再試，這段時間檔案會繼續長大\n"
                                 % (self.baseFilename, type(exc).__name__, exc, self._retry_after_s))
            except Exception:                                     # noqa: BLE001
                pass

    def _rotate_and_compress(self, source, dest):
        pending = dest + ".pending"
        os.replace(source, pending)                               # 這一步失敗 ⇒ 丟 OSError，由 doRollover 接住；現行檔原封不動
        threading.Thread(target=_compress_file, args=(pending, dest), name="log-gzip", daemon=True).start()


def _compress_file(pending, dest):
    """pending（已改名的舊檔）→ dest（.gz）。失敗時把 pending 改回無壓縮的世代檔，**不丟資料**。"""
    tmp = dest + ".tmp"
    try:
        with open(pending, "rb") as src, gzip.open(tmp, "wb", compresslevel=6) as out:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        os.replace(tmp, dest)
        os.remove(pending)
    except Exception as exc:                                      # noqa: BLE001
        for p in (tmp,):
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            os.replace(pending, dest[:-3])                        # 留成沒壓縮的 app.log.N：保留期清理照樣認得
        except OSError:
            pass
        try:
            sys.stderr.write("[log_setup] 壓縮 %s 失敗（%s: %s），保留為未壓縮檔\n" % (dest, type(exc).__name__, exc))
        except Exception:                                         # noqa: BLE001
            pass


def recover_pending(log_dir):
    """上次行程在壓縮到一半被結束，會留下 `*.gz.pending`（舊檔的完整內容）。開機時把它們壓完。回處理的檔數。"""
    n = 0
    try:
        names = os.listdir(log_dir)
    except OSError:
        return 0
    for name in names:
        if not name.endswith(".gz.pending"):
            continue
        pending = os.path.join(log_dir, name)
        dest = pending[:-len(".pending")]
        if os.path.exists(dest):                                  # 同號世代已被新的佔走 ⇒ 另存，不覆蓋
            dest = dest[:-3] + ".recovered.%d.gz" % int(time.time())
        threading.Thread(target=_compress_file, args=(pending, dest), name="log-gzip-recover", daemon=True).start()
        n += 1
    return n


# ── console（server.log 兜底）的過濾 ─────────────────────────────────────────

class BootState:
    """開機期間的共用狀態。⚠️ 必須**所有 console handler 共用同一個**：「Uvicorn running on」只會走 uvicorn.error 的 handler，
    root 的 console handler 永遠看不到它——各自一份狀態的話，root 那邊要拖到逾時才會收斂（實跑 uvicorn 時抓到：開機後的 INFO 還是灌進 server.log）。"""

    def __init__(self, boot_window_s=BOOT_WINDOW_MAX_S):
        self.deadline = time.monotonic() + boot_window_s
        self.done = False

    def is_open(self):
        return not self.done and time.monotonic() <= self.deadline


class ConsoleBootFilter(logging.Filter):
    """WARNING 以上一律通過；INFO 只在開機期間通過（見模組說明：部署腳本的健康檢查靠 server.log 的開機那一段）。"""

    def __init__(self, state=None):
        super().__init__()
        self.state = state if state is not None else BootState()

    @property
    def boot_done(self):
        return not self.state.is_open()

    def filter(self, record):
        if record.levelno >= logging.WARNING:
            return True
        if not self.state.is_open():
            return False
        try:
            if "Uvicorn running on" in record.getMessage():
                self.state.done = True                            # 這一行本身還要寫（健康檢查就是找它）；之後所有 console 的 INFO 都不再通過
        except Exception:                                         # noqa: BLE001
            pass
        return True


# ── 噪音：Windows asyncio proactor 的客戶端斷線 ───────────────────────────────

class ClientDisconnectNoiseFilter(logging.Filter):
    """見模組說明「噪音」。認得 ⇒ 計數、不寫（asyncio logger 開 DEBUG 時留一行摘要，不帶 traceback）。"""

    def __init__(self):
        super().__init__()
        self.count = 0
        self._lock = threading.Lock()

    @staticmethod
    def matches(record):
        ei = record.exc_info
        if not ei or ei[0] is None or not issubclass(ei[0], ConnectionResetError):
            return False
        if getattr(ei[1], "winerror", None) != 10054:
            return False
        try:
            msg = record.getMessage()
        except Exception:                                         # noqa: BLE001
            return False
        return "_call_connection_lost" in msg

    def filter(self, record):
        if not self.matches(record):
            return True
        with self._lock:
            self.count += 1
            n = self.count
        if not logging.getLogger(record.name).isEnabledFor(logging.DEBUG):
            return False
        record.levelno, record.levelname = logging.DEBUG, "DEBUG"
        record.exc_info = record.exc_text = None
        record.msg, record.args = "客戶端突然斷線（Windows asyncio proactor 的 WinError 10054，無害）；本行程累計 %d 次" % n, ()
        return True


_NOISE = ClientDisconnectNoiseFilter()


def attach_noise_filter():
    """只掛噪音 filter（不建檔）。開發機／測試也要靜音；`install()` 也會呼叫（重複掛無妨）。"""
    ag = logging.getLogger("asyncio")
    ag.addFilter(_NOISE)
    return ag


def noise_count():
    """本行程到目前為止被濾掉的客戶端斷線次數。"""
    return _NOISE.count


# ── 查詢字串遮罩（2026-11-13）：token 不可以進任何日誌檔 ─────────────────────────────
# 為什麼：uvicorn 的 access 行會把**整個 URL 含 query** 寫進去（`GET /api/x?pt=<token> HTTP/1.1`）；`<script src>`／下載連結帶不了
# Authorization，所以有些端點的憑證放在 query（`?pt=`、`?code=` 這一類，見 auth_middleware 註解）——那些值就會躺在
# access.log／app.log／server.log 裡（保留 30 天、還會被備份、被人貼進工單）。對外呼叫失敗時 requests 的錯誤訊息也會帶完整網址
# （`...url: /maps/api/geocode/json?address=...&key=AIza...`），網址的 `user:password@` 也一樣。
# 規則：**path 照留；query 每個參數的「名字」留下、「值」一律遮成 `***`**（`?type=***&id=***`：除錯時看得出是哪一類請求、查哪一筆要看 path）。
# 名字不是單純的識別字（有 `%`、太長、沒有 `=` 的裸 token、像 JWT 的長串）⇒ 整段換成 `***`，不把它當名字留下來。
# 兩層：① `uvicorn.access` logger 的 filter 精準改請求行的 path 參數（access.log、server.log 兜底都吃到，不論分流有沒有啟用）；
# ② 文字層保險網：其他 logger 的訊息與例外文字裡出現的「網址?query」同樣遮罩（掛在每個 handler 上）。
# ⚠️ 文字層**不用正則在整段文字上找網址**（`/[\w%~.\-/]*\?` 這種寫法每個 `/` 都重試一次、失敗時是 O(n²)——16000 個 `/` 要 1 秒以上，
# 而訊息裡有攻擊者可控的文字：`request.url.path` 是解碼過的路徑，`%3F`＝`?`、`%20`＝空白，hichan-10 審查實測）；改成**照空白／引號切成 token**，
# 每個 token 只處理一次（線性），而且過長的網址型 token 先截斷（`TOKEN_MAX`）。
# 用 `***` 不用 `…`：Windows 主控台／檔案編碼不一定吃得下全形符號，日誌輸出不可以因此丟例外。
QUERY_MASK = "***"
#: 網址型 token（含 `/` 或 `://`）超過這個長度就截斷：日誌行本來就不需要幾 KB 的路徑；同時是 O(n) 之外的第二道上限
TOKEN_MAX = 2048
_PARAM_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.\-\[\]]{0,22}")          # 名字最長 23 字：再長的多半是 token 本身（base64／雜湊）
_HEXISH_RE = re.compile(r"[0-9A-Fa-f]{12,}")                                 # 全是十六進位的長串也不當名字（`?<hex token>=`）
_TOKEN_RE = re.compile(r"""[^\s"'<>]+""")


def _name_is_token(name):
    """名字的「形狀」像 token 而不像識別字（base64／雜湊／隨機串）⇒ 整段遮（hichan-11 M1）：長度不夠當名字上限也照樣抓得到
    （`?<22 字 base64>==` 的名字只有 22 字）。蛇形（`department_id`）／駝峰（`activityLimit`）都過不了這兩條：
    ① 長 ≥16 且大寫 ≥3；② 長 ≥8 且大寫 ≥2 且數字 ≥2。守門：test_log_query_redact 掃遍所有路由參數名，證明沒有一個被誤遮。"""
    up = sum(1 for c in name if c.isupper())
    dg = sum(1 for c in name if c.isdigit())
    return (len(name) >= 16 and up >= 3) or (len(name) >= 8 and up >= 2 and dg >= 2)
_TRAILING = ")]},.;"


def redact_query(query):
    """`type=quote&pt=SECRET&abc` ⇒ `type=***&pt=***&***`（名字留、值遮；不像名字的整段遮；相鄰的整段遮合併成一個）。"""
    parts = []
    for piece in (query or "").split("&"):
        if not piece:
            continue
        name, eq, _val = piece.partition("=")
        keep = (bool(eq) and _PARAM_NAME_RE.fullmatch(name) and not _HEXISH_RE.fullmatch(name)
                and not _name_is_token(name))
        item = name + "=" + QUERY_MASK if keep else QUERY_MASK
        if item == QUERY_MASK and parts and parts[-1] == QUERY_MASK:
            continue
        parts.append(item)
    return "&".join(parts)


def redact_target(target):
    """請求目標（path＋可有 query）⇒ path＋遮過的 query。沒有 query ⇒ 原樣。`#fragment` 一併丟掉。"""
    if not isinstance(target, str) or "?" not in target:
        return target
    path, _, rest = target.partition("?")
    rest = rest.partition("#")[0]
    masked = redact_query(rest)
    return path + "?" + masked if masked else path


def _mask_userinfo(tok):
    """`scheme://user:password@host/…` ⇒ `scheme://***@host/…`（只看第一個 `://` 之後、第一個 `/?#` 之前的授權段）。"""
    i = tok.find("://")
    if i < 0:
        return tok
    j = i + 3
    end = len(tok)
    for ch in "/?#":
        k = tok.find(ch, j)
        if 0 <= k < end:
            end = k
    at = tok.rfind("@", j, end)
    return tok if at < 0 else tok[:j] + QUERY_MASK + tok[at:]


def _mask_token(tok):
    if "?" not in tok and "://" not in tok and "#" not in tok:
        return tok
    if len(tok) > TOKEN_MAX and ("/" in tok):
        tok = tok[:TOKEN_MAX] + "...[+%d chars]" % (len(tok) - TOKEN_MAX)
    h = tok.find("#")
    if h >= 0 and ("/" in tok[:h] or "://" in tok[:h]):               # 網址的 fragment 可能帶憑證（#access_token=…，requests 的錯誤文字會回顯整個網址）⇒ 一律丟掉
        tok = tok[:h]
    k = tok.find("?")
    if k >= 0 and k + 1 < len(tok) and "/" in tok[:k]:               # 像網址或路徑（`a/b?c`）而且 `?` 後面真的有東西才處理；一般句子裡的問號不動
        base, rest = tok[:k], tok[k + 1:]
        rest = rest.partition("#")[0]                                # fragment 也可能帶憑證（#access_token=…）⇒ 丟掉
        trail = ""
        while rest and rest[-1] in _TRAILING:                        # 句尾標點不算 query 的一部分
            trail = rest[-1] + trail
            rest = rest[:-1]
        masked = redact_query(rest)
        tok = base + ("?" + masked if masked else "") + trail
    return _mask_userinfo(tok)


def redact_text(text):
    """訊息／例外文字裡的「網址?query」與網址的 userinfo 遮罩（見上）。沒有 `?`、`://`、`#` ⇒ 原樣回傳（快路徑）。線性時間。"""
    if not text or ("?" not in text and "://" not in text and "#" not in text):
        return text
    return _TOKEN_RE.sub(lambda m: _mask_token(m.group(0)), text)


class QueryRedactFilter(logging.Filter):
    """見上。掛在 `uvicorn.access` logger（精準）與每個 handler（保險網）。filter 永遠回 True、任何例外都吞掉——日誌遮罩壞了不可以讓請求或日誌本身壞掉。"""

    def filter(self, record):
        try:
            a = record.args
            if record.name == "uvicorn.access" and isinstance(a, tuple) and len(a) >= 3 and isinstance(a[2], str):
                record.args = a[:2] + (redact_target(a[2]),) + a[3:]       # uvicorn 的請求行：(client, method, full_path, http_version, status)
                return True
            msg = record.getMessage()
            new = redact_text(msg)                                          # 快路徑在 redact_text 裡（不能在這裡只看 `?`：fragment／userinfo 的網址沒有 `?`，hichan-11 H1）
            if new != msg:
                record.msg, record.args = new, ()
            ei = record.exc_info
            if ei and ei[0] is not None and not record.exc_text:
                txt = logging.Formatter().formatException(ei)                # 先轉成文字再遮（Formatter 會沿用 exc_text）
                record.exc_text = redact_text(txt)
        except Exception:                                                    # noqa: BLE001
            pass
        return True


_REDACT = QueryRedactFilter()


def attach_redact_filter():
    """掛上查詢字串遮罩：`uvicorn.access` logger（精準）＋ root／uvicorn／uvicorn.access 現有的每個 handler（保險網）。
    重複呼叫無妨；`install()` 在加完檔案 handler 後會再呼叫一次。開發機／測試／分流沒啟用時 main.py 也呼叫它。"""
    acc = logging.getLogger("uvicorn.access")
    if _REDACT not in acc.filters:
        acc.addFilter(_REDACT)
    for lg in (logging.getLogger(), logging.getLogger("uvicorn"), acc):
        for h in lg.handlers:
            if _REDACT not in h.filters:
                h.addFilter(_REDACT)
    return acc


# ── 安裝 ──────────────────────────────────────────────────────────────────

class Installed:
    """`install()` 的結果：讓測試與關閉流程可以把它拆掉。"""

    def __init__(self):
        self.app_handler = None
        self.access_handler = None
        self.console_filters = []        # [(handler, filter)]
        self.removed_access_console = []  # [(logger, handler)]
        self.noise_logger = None

    def uninstall(self):
        root = logging.getLogger()
        uv = logging.getLogger("uvicorn")
        acc = logging.getLogger("uvicorn.access")
        if self.app_handler is not None:
            root.removeHandler(self.app_handler)
            uv.removeHandler(self.app_handler)
            self.app_handler.close()
        if self.access_handler is not None:
            acc.removeHandler(self.access_handler)
            self.access_handler.close()
        for h, f in self.console_filters:
            h.removeFilter(f)
        for lg, h in self.removed_access_console:
            lg.addHandler(h)
        if self.noise_logger is not None:
            self.noise_logger.removeFilter(_NOISE)


def enabled_by_environment():
    """測試（pytest）與明確關閉的環境不建檔：避免測試往真的 logs 目錄寫、也避免 import main 就開檔。"""
    if os.environ.get("MOTRIX_FILE_LOGS", "").strip() == "0":
        return False
    return "pytest" not in sys.modules


def install(log_dir, max_bytes=DEFAULT_MAX_BYTES, backups=DEFAULT_BACKUPS, boot_window_s=BOOT_WINDOW_MAX_S):
    """裝上 access.log／app.log 兩個輪替 handler、收斂 console、掛噪音 filter。成功回 `Installed`；
    任何一個檔打不開 ⇒ 什麼都不改、回 None（維持舊行為，原因寫 stderr）。"""
    try:
        os.makedirs(log_dir, exist_ok=True)
        recover_pending(log_dir)
        app_h = GzipRotatingFileHandler(os.path.join(log_dir, APP_LOG_NAME), maxBytes=max_bytes, backupCount=backups)
        try:
            access_h = GzipRotatingFileHandler(os.path.join(log_dir, ACCESS_LOG_NAME), maxBytes=max_bytes, backupCount=backups)
        except Exception:
            app_h.close()
            raise
    except Exception as exc:                                      # noqa: BLE001
        try:
            sys.stderr.write("[log_setup] 日誌分流沒有啟用（%s: %s）——維持單一 server.log\n" % (type(exc).__name__, exc))
        except Exception:                                         # noqa: BLE001
            pass
        return None

    app_h.setLevel(logging.INFO)
    app_h.setFormatter(logging.Formatter(_APP_FORMAT))
    access_h.setLevel(logging.INFO)
    access_h.setFormatter(logging.Formatter(_ACCESS_FORMAT))

    root = logging.getLogger()
    uv = logging.getLogger("uvicorn")             # uvicorn.error 往它傳（它自己 propagate=False，所以要單獨掛，不會重複寫）
    acc = logging.getLogger("uvicorn.access")
    out = Installed()
    out.app_handler, out.access_handler = app_h, access_h

    # 收斂 console：access 的 console handler 整個拿掉（部署腳本不讀 access）；其餘 console handler 掛 boot filter
    for lg in (acc,):
        for h in list(lg.handlers):
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
                lg.removeHandler(h)
                out.removed_access_console.append((lg, h))
    state = BootState(boot_window_s)
    for lg in (root, uv):
        for h in list(lg.handlers):
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
                f = ConsoleBootFilter(state)
                h.addFilter(f)
                out.console_filters.append((h, f))

    root.addHandler(app_h)
    uv.addHandler(app_h)
    acc.addHandler(access_h)

    out.noise_logger = attach_noise_filter()
    attach_redact_filter()                        # 新加的檔案 handler 也要有（查詢字串遮罩）
    return out


# ── 請求耗時（request_timing.log）────────────────────────────────────────

#: 佇列上限：背景執行緒寫不動時最多積這麼多筆，再多就丟（寧可少一筆耗時資料，也不能讓記憶體或請求受影響）
TIMING_QUEUE_MAX = 20000
_TIMING_METHOD_RE = re.compile(r"^[A-Z]{3,10}$")
_TIMING = None                                  # 目前裝上的 TimingInstalled；None ＝ 沒啟用（中介層直接放行）


class _DropQueueHandler(logging.handlers.QueueHandler):
    """佇列滿了就丟（`dropped` 計數），不阻塞、不丟例外。"""

    def __init__(self, q):
        super().__init__(q)
        self.dropped = 0

    def enqueue(self, record):
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            self.dropped += 1


class TimingInstalled:
    def __init__(self, logger, qh, listener, file_handler):
        self.logger, self.queue_handler, self.listener, self.file_handler = logger, qh, listener, file_handler
        self._stopped = False

    @property
    def dropped(self):
        return self.queue_handler.dropped

    def stop(self):
        """停掉背景執行緒（把佇列裡剩的寫完）並關檔、解除登記。可重複呼叫。"""
        global _TIMING
        if self._stopped:
            return
        self._stopped = True
        if _TIMING is self:
            _TIMING = None
        self.logger.removeHandler(self.queue_handler)
        try:
            try:
                self.listener.stop()
            except queue.Full:                    # 佇列塞滿、結束訊號放不進去 ⇒ 丟掉積壓的再試一次
                q = self.queue_handler.queue
                while True:
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        break
                self.listener.stop()
        except Exception:                         # noqa: BLE001  已經停過（_thread 是 None）等：收尾不可以丟例外
            pass
        finally:
            self.file_handler.close()


def install_request_timing(log_dir, max_bytes=DEFAULT_MAX_BYTES, backups=DEFAULT_BACKUPS, queue_max=TIMING_QUEUE_MAX):
    """裝上 request_timing.log（輪替＋gzip，背景寫入）。成功回 `TimingInstalled`；打不開檔 ⇒ 什麼都不改、回 None（原因寫 stderr）。"""
    global _TIMING
    if _TIMING is not None:                       # 重複安裝（重載、測試）⇒ 先停掉上一個，不留執行緒與檔案控制代碼
        _TIMING.stop()
    try:
        os.makedirs(log_dir, exist_ok=True)
        # 不呼叫 recover_pending：main.py 先跑 install()，它已掃整個目錄（含 request_timing.log.*.gz.pending）；
        # 這裡再掃一次會對同一個 pending 檔起第二條壓縮執行緒、兩條同時寫同一個 .tmp
        fh = GzipRotatingFileHandler(os.path.join(log_dir, TIMING_LOG_NAME), maxBytes=max_bytes, backupCount=backups)
    except Exception as exc:                                      # noqa: BLE001
        try:
            sys.stderr.write("[log_setup] 請求耗時記錄沒有啟用（%s: %s）\n" % (type(exc).__name__, exc))
        except Exception:                                         # noqa: BLE001
            pass
        return None
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    q = queue.Queue(maxsize=queue_max)
    qh = _DropQueueHandler(q)
    listener = logging.handlers.QueueListener(q, fh, respect_handler_level=True)
    lg = logging.getLogger("motrix.request_timing")
    lg.setLevel(logging.INFO)
    lg.propagate = False                          # 不進 app.log／server.log：這是獨立的資料檔
    for h in list(lg.handlers):
        lg.removeHandler(h)
    lg.addHandler(qh)
    listener.start()
    _TIMING = TimingInstalled(lg, qh, listener, fh)
    return _TIMING


def route_template(scope):
    """路由樣板（`/api/dev-cases/{case_id}`）。沒比對到路由 ⇒ `(unmatched)`——**絕不回原始路徑**（原始路徑含編號、可能含個資）。"""
    try:
        route = scope.get("route")
        path = getattr(route, "path", None) or getattr(route, "path_format", None)
        if isinstance(path, str) and path.startswith("/"):
            return path
    except Exception:                                             # noqa: BLE001
        pass
    return "(unmatched)"


def record_request_timing(method, route, status, ms):
    """寫一行。沒啟用 ⇒ 立刻返回。任何例外都吞掉。"""
    t = _TIMING
    if t is None:
        return
    try:
        m = method if isinstance(method, str) and _TIMING_METHOD_RE.match(method) else "?"
        t.logger.info("%s %s %d %d", m, route, int(status or 0), int(ms))
    except Exception:                                             # noqa: BLE001
        pass


class RequestTimingMiddleware:
    """純 ASGI 中介層：量一個 /api/ 請求從進來到回應送完的耗時。沒啟用時只多一次全域變數判斷。
    狀態碼取自 `http.response.start`；回應送完（最後一個 body 區塊）才算結束；處理時丟例外 ⇒ 記 500 再把例外原樣丟出去。
    客戶端在回應開始前就斷線（沒有狀態碼也沒有例外）⇒ 不記。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if _TIMING is None or scope.get("type") != "http" or not str(scope.get("path", "")).startswith("/api/"):
            return await self.app(scope, receive, send)
        t0 = time.perf_counter()
        state = {"status": 0, "done": False}

        def _finish(status):
            if state["done"]:
                return
            state["done"] = True
            record_request_timing(scope.get("method"), route_template(scope), status, (time.perf_counter() - t0) * 1000)

        async def _send(message):
            kind = message.get("type")
            if kind == "http.response.start":
                state["status"] = message.get("status", 0)
            await send(message)
            if kind == "http.response.body" and not message.get("more_body", False):
                _finish(state["status"])

        try:
            await self.app(scope, receive, _send)
        except BaseException as exc:
            if isinstance(exc, (asyncio.CancelledError, GeneratorExit)) and not state["status"]:
                state["done"] = True                      # 客戶端中途斷線／被取消：不是真的 500，不記（會污染「最耗時請求」統計）
            else:
                _finish(state["status"] or 500)
            raise
        else:
            if state["status"]:
                _finish(state["status"])


# ── 保留期 ────────────────────────────────────────────────────────────────

def prune_rotated_logs(log_dir, keep_days, now=None):
    """刪除 `log_dir` 裡超過 `keep_days` 天的**輪替出來的**日誌（`access.log.N.gz`、`app.log.N.gz`、`server.log.N`；含壓縮中殘留的暫存檔）。
    現行檔（`access.log`、`app.log`、`server.log`）與 `server.log.rotating` 永遠不刪。回被刪的檔名清單。
    `keep_days` 不是正整數 ⇒ 什麼都不刪（設定壞掉時寧可多留）。"""
    try:
        days = int(keep_days)
    except (TypeError, ValueError):
        return []
    if days < 1:
        return []
    cutoff = (time.time() if now is None else now) - days * 86400
    removed = []
    try:
        names = os.listdir(log_dir)
    except OSError:
        return []
    for name in names:
        if not _ROTATED_RE.match(name):
            continue
        path = os.path.join(log_dir, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
                removed.append(name)
        except OSError:
            continue                                              # 被占用、剛好被別人刪掉 ⇒ 下一輪再說
    return removed
