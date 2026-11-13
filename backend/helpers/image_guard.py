# -*- coding: utf-8 -*-
"""使用者上傳圖片的「解壓縮炸彈」守門：先看宣告的長寬，超過上限就不解碼；解碼同時最多 2 件。

[單位] helper:image_guard     [層] L1        [穩定度] 契約（改介面照 §C-7 升版）
[公開介面] MAX_PIXELS, MAX_PIXELS_JPEG, JPEG_FULL_DECODE_MAX, DRAFT_LONG_SIDE, ALLOWED_FORMATS, MAX_CONCURRENT_DECODES, DECODE_WAIT_SECONDS, DECODE_THREAD_WAIT_SECONDS, MAX_WAITING_THREADS, MAX_WAITING_ASYNC,
  USER_MESSAGE, BUSY_MESSAGE, ImageRejected, ImageTooLarge, ImageUnsupported, ImageBusy,
  check_pixels, open_checked, decode_slot, with_decode_slot, run_decode
[不變式] 只讀檔頭宣告的 img.size（Pillow 延遲載入，此時還沒配置像素記憶體）；超過上限 ⇒ 丟 ImageTooLarge，
  呼叫端必須把它轉成 400，不可吞掉後把原檔照存（原檔就是炸彈）。三種拒絕都是 ImageRejected 的子類，各帶 .status 與白話 .user_message：
  `except ImageRejected as e: raise HTTPException(e.status, e.user_message)`（ImageBusy 是 503）
  一個 20000x20000 的調色盤 PNG 檔案只有幾 KB，解碼後 RGBA 約 1.6GB——檔案大小上限擋不住，必須看像素
  上限：非 JPEG（PNG／GIF／WebP）MAX_PIXELS＝2000 萬（截圖、掃描檔遠低於此；經 _process_project_photo 每像素約 22 位元組，2000 萬≈440MB）；
  JPEG／MPO（多圖 JPEG，Pillow 回報格式 "MPO"，同一套解碼器）放寬到 MAX_PIXELS_JPEG＝1.1 億（外勤手機 108MP 原圖，PM 2026-11-13 裁示），
  但超過 JPEG_FULL_DECODE_MAX（4000 萬）的 JPEG，open_checked 會立刻 `Image.draft()` 讓解碼端以 1/2、1/4、1/8 縮小解出
  （長邊 ≤ 約 4000），呼叫端之後 load／convert 拿到的就是縮小後的影像（原檔位元組不動；浮水印處理後存的是縮小後的）；4000 萬以內不縮
  格式白名單 ALLOWED_FORMATS（JPEG／MPO／PNG／GIF／WEBP）：其他格式（TIFF／BMP／PSD／EPS⇒Ghostscript…）依內容也一律不開；
  HEIF／HEIC 沒有解碼器（一直都不支援；上傳端點仍接受、原檔照存不浮水印）⇒ open_checked 丟 ImageUnsupported（不是 ImageRejected，
  呼叫端的「打不開就原檔照存」路徑接得住；從不解碼，所以沒有炸彈問題）
  解碼同時最多 MAX_CONCURRENT_DECODES＝2 件（`decode_slot`／`with_decode_slot`，行程內共用），等不到（20 秒）⇒ ImageBusy ⇒ 503；
  所以呼叫端**不可以在事件迴圈執行緒裡呼叫**（等待會卡住整台）：async 端點用 `await run_decode(fn, ...)`（在迴圈上排隊、不占執行緒池）；
  排隊有上限（執行緒 4 條、協程 16 個，超過立刻 503），否則一個人連發 60 張會把共用的 40 條執行緒全部卡在等名額上（hichan-12 實測 16 秒停擺）
[注意] Pillow 預設 MAX_IMAGE_PIXELS（約 8900 萬）：超過 1 倍只警告（照常解碼）、超過 2 倍（約 1.79 億）才在 open() 丟
  DecompressionBombError——所以 2000 萬～1.79 億像素（如 13000x13000）完全沒人擋；> 1.79 億的 DecompressionBombError
  在這裡一併轉成 ImageTooLarge，呼叫端只要處理一種例外（原本 photos／contractors 的 except Exception 會吞掉它、原檔照存）。
  8950 萬～1.1 億的 JPEG 會觸發 DecompressionBombWarning：已有 draft 保護，本模組一次性把這個警告靜音（避免日誌噪音、也避免 -W error 時逃出）
[契約題] tests/test_image_guard_2026_11_13.py
"""
import asyncio
import functools
import io
import threading
import weakref
from contextlib import contextmanager

from starlette.concurrency import run_in_threadpool

MAX_PIXELS = 20_000_000            # 不能縮小解碼的格式（PNG／GIF／WebP…）
MAX_PIXELS_JPEG = 110_000_000      # JPEG／MPO：可用 draft() 縮小解碼，所以放寬（108MP 手機原圖）
JPEG_FULL_DECODE_MAX = 40_000_000  # JPEG 在這個像素數以內維持原本的全尺寸解碼；超過才 draft
DRAFT_LONG_SIDE = 4000             # JPEG 縮小解碼後長邊的目標上限（實際取 1/2、1/4、1/8 其中一個）
ALLOWED_FORMATS = ("JPEG", "MPO", "PNG", "GIF", "WEBP")
MAX_CONCURRENT_DECODES = 2
DECODE_WAIT_SECONDS = 10.0         # async 端點在事件迴圈上排隊等名額的上限（不占執行緒）；超過 ⇒ ImageBusy
DECODE_THREAD_WAIT_SECONDS = 5.0   # 執行緒（同步端點）等名額的上限；超過 ⇒ ImageBusy
MAX_WAITING_THREADS = 4            # 最多幾條執行緒可以排隊等名額；再多一律立刻 ImageBusy（不讓排隊把共用執行緒池占滿）
MAX_WAITING_ASYNC = 16             # 事件迴圈上最多幾個請求排隊（只是協程，不占執行緒）；再多立刻 ImageBusy

USER_MESSAGE = "圖片解析度過大（一般圖片上限 2000 萬像素，JPEG 照片上限 1.1 億像素），請縮小後再上傳。"
BUSY_MESSAGE = "伺服器忙碌，請稍後再試"

_JPEG_LIKE = ("JPEG", "MPO")


class ImageRejected(Exception):
    """圖片不收（太大／格式不支援／伺服器忙）；.status 是建議的 HTTP 狀態碼，.user_message 是白話訊息。"""
    status = 400
    user_message = USER_MESSAGE

    def __init__(self, detail=""):
        super().__init__(detail or self.user_message)


class ImageTooLarge(ImageRejected, ValueError):
    """圖片宣告的長寬乘積超過上限（或長寬不合理）。"""
    status = 400
    user_message = USER_MESSAGE


class ImageUnsupported(ValueError):
    """HEIC／HEIF：沒有解碼器、本模組不解碼。**刻意不是 ImageRejected**：上傳端點（工作日誌等）一直接受 .heic／.heif、
    原檔照存（不浮水印；`_check_upload_magic` 與既有測試都明講），所以呼叫端的「打不開就原檔照存」路徑要接得住它
    （photos 的 except Exception 回原檔、承攬商 stamp 的 except Exception 存原圖）。"""


class ImageBusy(ImageRejected):
    """同時解碼的件數已滿，等不到空位。"""
    status = 503
    user_message = BUSY_MESSAGE


def _is_jpeg_like(img):
    return (getattr(img, "format", None) or "").upper() in _JPEG_LIKE


def check_pixels(img, max_pixels=None):
    """img 是剛 Image.open 出來、尚未 load() 的影像；超過上限丟 ImageTooLarge，否則回傳 img。
    max_pixels 不給 ⇒ JPEG／MPO 用 MAX_PIXELS_JPEG、其他用 MAX_PIXELS。"""
    cap = max_pixels if max_pixels is not None else (MAX_PIXELS_JPEG if _is_jpeg_like(img) else MAX_PIXELS)
    w, h = img.size
    if w < 1 or h < 1 or w * h > cap:
        raise ImageTooLarge("%dx%d 超過 %d 像素上限" % (w, h, cap))
    return img


def _draft_scale(w, h, long_side):
    s = 1
    while s < 8 and max(w, h) / s > long_side:
        s *= 2
    return s


_QUIET = False


def _silence_bomb_warning():
    """一次性把 DecompressionBombWarning 靜音（模組層級 filter，執行緒安全；不用 catch_warnings，它會改全域狀態）。"""
    global _QUIET
    if _QUIET:
        return
    import warnings
    from PIL import Image
    warnings.filterwarnings("ignore", category=Image.DecompressionBombWarning)
    _QUIET = True


def _looks_like_heif(data):
    """ISO BMFF：offset 4 是 'ftyp'，主品牌 heic／heix／hevc／hevx／heim／heis／mif1／msf1。"""
    return len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in (
        b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1")


def open_checked(data, formats=ALLOWED_FORMATS, max_pixels=None, draft_long_side=DRAFT_LONG_SIDE):
    """Image.open(BytesIO(data), formats=白名單) ＋ 像素檢查；解碼（load／convert）由呼叫端接著做。
    JPEG／MPO 且像素 > JPEG_FULL_DECODE_MAX ⇒ 已呼叫 draft()：之後 .size 是縮小後的尺寸（長邊 ≤ draft_long_side 的最小縮小倍率
    1/2、1/4、1/8）、解碼只花縮小後的記憶體；4000 萬以內的 JPEG 不縮。draft_long_side=None 表示不縮小。
    formats=None 表示不限格式（呼叫端自負；預設是白名單）。"""
    from PIL import Image
    _silence_bomb_warning()
    if _looks_like_heif(data):
        raise ImageUnsupported("HEIF／HEIC")
    if formats:
        Image.init()                                         # 載入全部格式外掛（MPO 等不在預設載入組；沒載入時 formats= 會 KeyError）
        formats = [f for f in formats if f in Image.OPEN]    # 沒有的外掛（例如編譯時沒帶 libwebp）直接略過，不讓整條路徑 KeyError
        if not formats:                                      # 過濾後空了 ⇒ 不可退化成「不限格式」
            raise ImageUnsupported("沒有可用的圖片格式外掛")
    try:
        img = Image.open(io.BytesIO(data), formats=formats) if formats else Image.open(io.BytesIO(data))
    except Image.DecompressionBombError as e:           # Pillow 自己的 2 倍上限：open() 就丟
        raise ImageTooLarge(str(e))
    check_pixels(img, max_pixels)
    if draft_long_side and _is_jpeg_like(img) and img.size[0] * img.size[1] > JPEG_FULL_DECODE_MAX:
        w, h = img.size
        s = _draft_scale(w, h, draft_long_side)
        if s > 1:
            img.draft(img.mode, (w // s, h // s))
    return img


_SEM = threading.BoundedSemaphore(MAX_CONCURRENT_DECODES)
_WAIT_LOCK = threading.Lock()
_waiting = 0


@contextmanager
def decode_slot(wait=None):
    """行程內同時解碼的件數上限（MAX_CONCURRENT_DECODES）；等不到 ⇒ ImageBusy（503）。
    會阻塞呼叫的執行緒（最多 DECODE_THREAD_WAIT_SECONDS；排隊的執行緒超過 MAX_WAITING_THREADS 條就立刻 ImageBusy，
    避免排隊把共用的 40 條執行緒池占滿、拖慢整個應用）。async 端點請用 run_decode（在事件迴圈上排隊，不占執行緒）。
    名額是行程內的：正式機若開多個 worker 行程，上限會倍增。"""
    global _waiting
    if not _SEM.acquire(blocking=False):
        with _WAIT_LOCK:
            if _waiting >= MAX_WAITING_THREADS:
                raise ImageBusy("解碼名額已滿且排隊的人太多")
            _waiting += 1
        try:
            got = _SEM.acquire(timeout=DECODE_THREAD_WAIT_SECONDS if wait is None else wait)
        finally:
            with _WAIT_LOCK:
                _waiting -= 1
        if not got:
            raise ImageBusy("同時解碼的圖片太多")
    try:
        yield
    finally:
        _SEM.release()


def with_decode_slot(fn):
    """decode_slot 的裝飾器版（保留簽章，L1 介面快照看得到原簽章）。"""
    @functools.wraps(fn)
    def wrapper(*a):                    # 只轉發位置參數（不用 ** 轉發；現有三個被裝飾的函式都只用位置參數呼叫，關鍵字參數會直接 TypeError）
        with decode_slot():
            return fn(*a)
    return wrapper


_ASYNC_STATE = weakref.WeakKeyDictionary()      # 事件迴圈 ⇒ [asyncio.Semaphore, 排隊數]（每個迴圈各一份；測試會開多個迴圈）


async def run_decode(fn, *a, **kw):
    """async 端點呼叫會解碼的同步函式（如 photos._process_project_photo）用：先在**事件迴圈上**排隊等名額
    （最多 MAX_CONCURRENT_DECODES 件進執行緒池、排隊上限 MAX_WAITING_ASYNC、等待上限 DECODE_WAIT_SECONDS，
    超過 ⇒ ImageBusy），拿到名額才丟 run_in_threadpool——排隊的請求不占任何執行緒池的執行緒。
    （fn 裡面的 decode_slot 仍在，當作同步端點共用同一組名額的後盾。）"""
    if kw:                              # 簽章保留 **kw（L1 介面快照）；但不再用 ** 轉發——現有呼叫端都只傳位置參數
        raise TypeError("run_decode 只轉發位置參數：%s" % ", ".join(sorted(kw)))
    loop = asyncio.get_running_loop()
    st = _ASYNC_STATE.get(loop)
    if st is None:
        st = _ASYNC_STATE[loop] = [asyncio.Semaphore(MAX_CONCURRENT_DECODES), 0]
    if st[1] >= MAX_WAITING_ASYNC:
        raise ImageBusy("解碼排隊的人太多")
    st[1] += 1
    try:
        await asyncio.wait_for(st[0].acquire(), DECODE_WAIT_SECONDS)
    except asyncio.TimeoutError:
        raise ImageBusy("同時解碼的圖片太多")
    finally:
        st[1] -= 1
    try:
        return await run_in_threadpool(fn, *a)
    finally:
        st[0].release()
