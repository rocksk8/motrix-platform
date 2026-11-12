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

## 保留期
輪替出來的舊檔（`access.log.N.gz`、`app.log.N.gz`、舊的 `server.log.N`）超過 `retention.log_keep_days`（設定中心「保存期限」群組，預設 30 天）
就刪——由 `archive._daily_backup` 每天呼叫 `prune_rotated_logs`（納入既有的備份／保留機制）。現行檔（`access.log`、`app.log`、`server.log`）永遠不刪。
"""
import gzip
import logging
import logging.handlers
import os
import re
import sys
import threading
import time

APP_LOG_NAME = "app.log"
ACCESS_LOG_NAME = "access.log"
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
_ROTATED_RE = re.compile(r"^(?:access\.log|app\.log|server\.log)\.\d+(?:\.gz)?(?:\.pending|\.tmp)?$")


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
    return out


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
