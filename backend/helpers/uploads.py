"""通用「已開立/已回簽單據」附件上傳（2026-08-24）：報價單回簽、出貨單回簽、
開票申請憑據開立三處共用同一套存檔邏輯——比照 routers/projects.py 專案照片
既有慣例（uploads/ 目錄 + 通用 /api/uploads/{file_path:path} 簽名 URL 服務，
見該檔案），但那裡的處理函式跟圖片浮水印/GPS 邏輯耦合在一起，這裡刻意獨立
成單純的檔案存檔（不處理浮水印，接受 PDF），供三個 router 共用，避免三份
幾乎一樣的存檔邏輯各自複製。

UPLOADS_ROOT 刻意跟 routers/projects.py 各自獨立計算一份（而不是互相 import），
兩邊路徑運算結果會指向同一個實體 uploads/ 目錄（都是 backend/ 的上一層），
讓既有的 /api/uploads/{file_path:path} serving 端點不必修改就能直接讀到
這裡新存的檔案；這是刻意的最小風險做法，不去動 projects.py 既有程式碼。
"""

#: G1（MODULE-GUIDE §2）：底線開頭但屬於 L1 公開介面的名稱——改簽章或刪除照介面變更升版。
#: L1 以外只可以用這裡列出的底線名稱（守門：test_l1_interface_snapshot::test_l2_uses_only_declared_l1_underscore_names）。
__l1_public__ = (
    "_effective_subfolder",
    "_check_upload_magic",          # 檔頭檢查唯一關卡：自有存檔邏輯的 L2（勞報單回簽檔）也呼叫同一支（2026-09-30）
)

import json
import os
import uuid
from datetime import datetime
from typing import List, NamedTuple

from fastapi import HTTPException, UploadFile

from core import paths as _paths
UPLOADS_ROOT = _paths.UPLOADS_ROOT

_ALLOWED_EXTS = {'.jpg', '.jpeg', '.png', '.pdf'}
#: 個別單據類型另外放行的副檔名（key＝呼叫端傳的 `subfolder`，不含 demo 前綴）。
#: 傳票附件（2026-09-30 使用者裁示）：Word／Excel 也能夾帶；exe 等其他格式照舊擋。大小上限沿用 `_MAX_FILE_SIZE`。
#: 函式簽章不動（L1 介面快照不變）：放行範圍由這張表決定，不是讓每個呼叫端自己傳白名單。
_EXTRA_EXTS_BY_SUBFOLDER = {'voucher_attachments': {'.docx', '.xlsx', '.doc', '.xls'},
                            'case_extra_expense': {'.heic', '.heif'}}      # iPhone 原檔（第44班方案 A：收原檔、檢視＝下載）
_MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB／檔
#: 依資料夾（`subfolder`，不含 demo 前綴）另訂的數量／總量上限（2026-10-07 使用者裁示：支出申請每張單據最多 10 個附件、一次送出合計 50MB；單檔 20MB 沿用 `_MAX_FILE_SIZE`）。
#: 沒列在這張表的資料夾＝只有單檔上限（行為不變）。`max_files`＝「每張單據」累計上限（呼叫端要傳 `existing_count`＝這張單據已有幾個）；
#: `max_request_bytes`＝這一次請求的合計大小。
UPLOAD_LIMITS_BY_SUBFOLDER = {
    'case_extra_expense': {'max_files': 10, 'max_request_bytes': 50 * 1024 * 1024},
}


# ── 檔頭（magic bytes）檢查：副檔名白名單之外的第二道（NIGHT 計畫 line 161，2026-09-30）──────────────────────
# 只驗副檔名 ⇒ 改個名字的 exe／html／腳本就能存進 uploads 並被下載或預覽。**唯一的關卡在這裡**：
# 所有走 `save_document_files` 的上傳都自動套用；自有存檔邏輯的兩處（勞報單回簽檔、工作日誌照片）呼叫同一支函式，
# 不各自抄一份。不符 ⇒ 400（整批擋下）＋寫一筆稽核 `upload.rejected_magic`（只記檔名、副檔名、資料夾、上傳者，不記內容）。
# 白名單裡有副檔名、這張表卻沒有它的規則 ⇒ **一律擋**（fail-closed：日後放行新副檔名時忘了補檔頭規則不會變成無檢查）。
_OLE_SIG = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_HEIF_BRANDS = (b"heic", b"heix", b"hevc", b"heif", b"mif1", b"msf1")
_OOXML_ROOT = {'.docx': 'word/', '.xlsx': 'xl/'}


def _magic_matches(ext: str, raw: bytes) -> bool:
    ext = ext.lower()
    head = raw[:1024]
    if ext in ('.jpg', '.jpeg'):
        return raw[:3] == b"\xff\xd8\xff"
    if ext == '.png':
        return raw[:8] == b"\x89PNG\r\n\x1a\n"
    if ext == '.gif':
        return raw[:6] in (b"GIF87a", b"GIF89a")
    if ext == '.webp':
        return raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
    if ext in ('.heic', '.heif'):               # ISO-BMFF：offset 4 是 "ftyp"，接著是 brand（iPhone 預設拍出的格式）
        return raw[4:8] == b"ftyp" and raw[8:12] in _HEIF_BRANDS
    if ext == '.pdf':
        return b"%PDF-" in head                 # PDF 規格允許標頭前有少量雜訊（前 1024 bytes）
    if ext in ('.doc', '.xls'):
        return raw[:8] == _OLE_SIG
    if ext in _OOXML_ROOT:
        if raw[:4] != b"PK\x03\x04":
            return False
        try:
            import io
            import zipfile
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                names = z.namelist()
        except Exception:                       # noqa: BLE001 — 壞的壓縮檔＝不是 Office 檔
            return False
        return "[Content_Types].xml" in names and any(n.startswith(_OOXML_ROOT[ext]) for n in names)
    return False                                # 沒有規則的副檔名 ⇒ 擋（fail-closed）


def _check_upload_magic(filename: str, ext: str, raw: bytes, subfolder: str = '', uploaded_by: str = '') -> None:
    """副檔名與檔頭不符 ⇒ 稽核＋`HTTPException(400)`。給 `save_document_files` 與兩處自有存檔邏輯共用。"""
    if _magic_matches(ext, raw):
        return
    try:
        from helpers.audit import _audit
        _audit(None, "upload.rejected_magic", "upload", filename or "", filename or "",
               {"ext": ext, "folder": subfolder, "by": uploaded_by, "size": len(raw)})
    except Exception:                           # noqa: BLE001 — 稽核失敗不可以讓「擋下」變成「放行」
        pass
    raise HTTPException(400, f"檔案內容與副檔名不符：{filename}（{ext} 檔的檔頭不正確，請確認是原始檔案）")

# demo 帳號隔離前綴——2026-08-24 補上（原本這裡完全沒有 is_demo_mode() 判斷，
# demo 帳號傳的檔案會直接寫進真實 uploads/ 目錄且永久留存，資料庫那筆記錄
# 卻因為 demo DB 每次登入被清空而變成孤兒檔案，跟 photos.py 既有的
# DEMO_PROJECT_PHOTOS_DIR 隔離慣例不一致）。前綴 `_demo_` 開頭的資料夾名稱
# archive.py::_mirror_uploads() 本來就會自動排除，不需要額外改動備份邏輯；
# db.reset_demo_db() 已補上這個目錄到清空清單（見 db.py DEMO_UPLOADS_DIR）。
_DEMO_SUBFOLDER_PREFIX = '_demo_uploads'


def _effective_subfolder(subfolder: str) -> str:
    from db import is_demo_mode
    if is_demo_mode():
        return f"{_DEMO_SUBFOLDER_PREFIX}/{subfolder}"
    return subfolder


_BAD_PATH_CHARS = ('\\', ':', '\x00')


def _safe_save_dir(subfolder: str, doc_no: str) -> str:
    """回 `UPLOADS_ROOT/subfolder/doc_no` 的絕對路徑；會跑出根目錄就 400（B8）。

    使用者裁示（2026-09-24）：穿越檢查**補在共用函式**。原本直接 `os.path.join`
    ⇒ `doc_no='../../x'` 就寫到根目錄外，能不能被利用取決於呼叫端有沒有先查單據存在，
    而那不是這支函式能保證的。

    ```
    doc_no     單一段：不可含 / \\ : NUL，不可是 . 或 ..
    subfolder  可以有多段（`_pending_case_changes/{id}`、demo 前綴），
               每一段同上規則，且不可以是絕對路徑
    最後       realpath 必須在 realpath(UPLOADS_ROOT) 之下（擋掉連結與漏網的寫法）
    ```
    🔴 檢查在 `makedirs` **之前**：擋下來的路徑上不可以留下空目錄。
    """
    def _seg_ok(seg):
        return bool(seg) and seg not in ('.', '..') and not any(c in seg for c in _BAD_PATH_CHARS)

    doc = str(doc_no or '')
    sub = str(subfolder or '')
    if not _seg_ok(doc) or '/' in doc:
        raise HTTPException(400, "單號格式不正確，無法存放附件。")
    if sub.startswith('/') or os.path.isabs(sub) or not all(_seg_ok(s) for s in sub.split('/')):
        raise HTTPException(400, "附件存放位置不正確。")
    root = os.path.realpath(UPLOADS_ROOT)
    target = os.path.realpath(os.path.join(root, *sub.split('/'), doc))
    if os.path.commonpath([root, target]) != root or target == root:
        raise HTTPException(400, "附件存放位置不正確。")
    return target


async def save_document_files(subfolder: str, doc_no: str, files: List[UploadFile],
                              uploaded_by: str, watermark_by: str = '', existing_count: int = 0) -> list:
    """存檔 files 到 uploads/{subfolder}/{doc_no}/{uuid}{ext}（demo 帳號會被
    導向 uploads/_demo_uploads/{subfolder}/{doc_no}/，見 _effective_subfolder()），
    回傳新增檔案的 metadata 陣列（呼叫端負責把這份陣列追加進資料庫的 JSON
    欄位）。單一檔案副檔名不在白名單或超過大小上限會直接 raise
    HTTPException(400)——寧可整批擋下讓使用者重新選檔，也不要靜默跳過造成
    使用者以為傳成功。

    watermark_by（2026-09-14）：給了名字就把**圖片**先過一次
    photos.py::_process_project_photo()（右下角壓上「上傳者 · 日期時間 · GPS」
    那條，GPS 只在 EXIF 有的時候才出現），再存檔；PDF 不動。
    案件動態與業務開發記錄的照片走這條（使用者裁示要加浮水印與當天日期）。

    **import 刻意寫在函式裡面**：這個模組原本的設計就是「單純存檔、不碰浮水印」
    （見檔頭），module-level import photos 會讓每個只想存 PDF 的呼叫端也被迫
    載入 Pillow 相依。放在用到的分支裡，沒傳 watermark_by 的呼叫端行為與相依
    完全不變。

    `existing_count`（選填，預設 0）：這張單據目前已有幾個附件；該資料夾在 `UPLOAD_LIMITS_BY_SUBFOLDER` 有 `max_files` 時用來檢查累計數量。
    **整批要嘛全存、要嘛全不存**：先把每個檔案驗完（副檔名、單檔大小、空檔、檔頭、整次請求合計大小、累計數量）才開始寫入，
    任何一個不合格就整批擋下，磁碟上不留任何檔案或空目錄（原本會留下前面幾個已寫的檔，成為沒有任何單據引用的孤兒檔）。"""
    if not files:
        raise HTTPException(400, "請至少選擇一個檔案")

    limits = UPLOAD_LIMITS_BY_SUBFOLDER.get(subfolder) or {}
    max_files = limits.get('max_files')
    if max_files and int(existing_count or 0) + len(files) > max_files:
        raise HTTPException(400, f"每張單據最多 {max_files} 個附件（目前已有 {int(existing_count or 0)} 個，這次要加 {len(files)} 個）")
    allowed = _ALLOWED_EXTS | _EXTRA_EXTS_BY_SUBFOLDER.get(subfolder, set())
    allowed_label = 'jpg/png/pdf' + ''.join('/' + e[1:] for e in sorted(allowed - _ALLOWED_EXTS))
    subfolder = _effective_subfolder(subfolder)
    save_dir = _safe_save_dir(subfolder, doc_no)

    # 第一階段：全部驗完才寫（任何一個不合格 ⇒ 整批 400，磁碟上什麼都不留）
    prepared = []
    total = 0
    for upload in files:
        ext = os.path.splitext(upload.filename or '')[1].lower()
        if ext not in allowed:
            raise HTTPException(400, f"不支援的檔案格式：{upload.filename}（僅支援 {allowed_label}）")
        raw = await upload.read()
        if len(raw) > _MAX_FILE_SIZE:
            raise HTTPException(400, f"檔案過大：{upload.filename}（單檔上限 20MB）")
        if not raw:
            raise HTTPException(400, f"檔案是空的：{upload.filename}")
        _check_upload_magic(upload.filename or '', ext, raw, subfolder, uploaded_by)
        total += len(raw)
        cap = limits.get('max_request_bytes')
        if cap and total > cap:
            raise HTTPException(400, f"這次上傳的檔案合計超過 {cap // (1024 * 1024)}MB，請分批上傳")
        prepared.append((upload, ext, raw))

    # 第二階段：寫入
    os.makedirs(save_dir, exist_ok=True)
    saved = []
    now = datetime.now().isoformat()
    for upload, ext, raw in prepared:
        if watermark_by and ext in ('.jpg', '.jpeg', '.png'):
            try:
                from photos import _process_project_photo
                raw = _process_project_photo(raw, watermark_by)[0]
            except Exception:
                # 浮水印失敗不該讓整次上傳失敗——原圖照存，比丟掉使用者的檔案好。
                # （Pillow 沒裝時 _process_project_photo 本身就會原樣回傳。）
                pass
        fname = uuid.uuid4().hex[:16] + ext
        with open(os.path.join(save_dir, fname), 'wb') as f:
            f.write(raw)
        saved.append({
            "id":         uuid.uuid4().hex[:8],
            "filename":   upload.filename or fname,
            "path":       f"{subfolder}/{doc_no}/{fname}",
            "size":       len(raw),
            "mime":       upload.content_type or '',
            "uploadedBy": uploaded_by,
            "uploadedAt": now,
        })
    return saved


def delete_document_file(subfolder: str, doc_no: str, existing_files: list, file_id: str) -> list:
    """從 existing_files 陣列移除指定 file_id 並刪除實體檔案，回傳更新後的
    陣列；找不到該 file_id 會 raise HTTPException(404)。"""
    target = next((f for f in existing_files if f.get("id") == file_id), None)
    if not target:
        raise HTTPException(404, "找不到指定的檔案")
    try:
        # 直接用 target["path"] 存的完整相對路徑（已含 demo 前綴，若有的話）解析，
        # 不要重新呼叫 _effective_subfolder() 再組一次——避免刪除當下的 demo
        # 狀態跟建立當下不一致時解析到錯誤路徑。
        full = os.path.join(UPLOADS_ROOT, target["path"])
        if os.path.isfile(full):
            os.remove(full)
    except Exception:
        pass
    return [f for f in existing_files if f.get("id") != file_id]


def purge_document_files(existing_files: list) -> int:
    """單據被刪除（草稿／已駁回）時，把它名下的實體檔案一併刪掉，並清掉變空的資料夾；回實際刪掉幾個檔。
    只處理 `existing_files` 裡有 `path` 的項目，路徑一律經 `canonical_upload_path` 驗證（不在 uploads 根目錄底下的一律略過）。
    刪檔失敗不丟例外（單據已刪、檔案成了孤兒只是浪費空間，不該讓刪除失敗）。"""
    n = 0
    dirs = set()
    for f in existing_files or []:
        rel = canonical_upload_path((f or {}).get("path")) if isinstance(f, dict) else None
        if not rel:
            continue
        full = os.path.join(UPLOADS_ROOT, *rel.split("/"))
        try:
            if os.path.isfile(full):
                os.remove(full)
                n += 1
            dirs.add(os.path.dirname(full))
        except Exception:                                   # noqa: BLE001
            pass
    for d in dirs:
        try:
            os.rmdir(d)                                     # 只會刪空資料夾；有別的檔就保留
        except OSError:
            pass
    return n


# ── 附件來源（`attachments.for_document`，主持裁示 M06-b，2026-09-26）──────────────────────────
# 單據的已上傳檔案由各擁有模組提供（M01／M04／M05…），取用方（M06 傳票帶入）不直讀別組的表。
# 這裡只放兩件沒有領域知識的共用件：錯誤型別，與「從某表某列的 JSON 欄讀檔案清單」。

class AttachmentSourceError(Exception):
    """附件來源解析不了（資料格式壞掉、來源編號缺少必要的部分…）。訊息是給使用者看的一句話，
    取用方原樣回 400。⚠️ 不可以吞成空清單：「這裡沒有附件」與「這裡的資料壞了」在畫面上會一模一樣。"""


class AttachmentNotVisible(Exception):
    """使用者看不到這筆附件的原單據（稽核 D AT-M1，主持裁示 (b)）：取用方列清單時不列、帶入／預覽時回 403。

    `visible`：逐張過濾的提供者（`doc_nos_for_case`）只看得到其中幾張時，帶上看得到的那幾張（其餘不列）。
    `hidden`：因此沒列出的**附件個數**（只有數字）。取用方**一律明說**「某類 N 個附件因權限無法顯示」
    （主持裁示 2026-09-26：不可以靜默少列；也不可以帶出單號、檔名、金額或任何內容，否則明說本身就是外洩）。"""

    def __init__(self, visible=None, hidden=0):
        super().__init__()
        self.visible = list(visible or [])
        self.hidden = int(hidden or 0)


# ── 附件目錄（`attachments.catalog`，契約 v1，2026-09-30；設計 proposal-attachments-search-preview §4）──────────────
# 「全部文件」的附件目錄：擁有模組各自宣告 `CATEGORIES`（source_type ⇒ 顯示資訊）與 `open()`（取出單一檔案）。
# 與 `attachments.for_document`（IP-21，會計憑證來源政策）分開：範圍不同（全部文件 vs 傳票可帶入的來源）。
# 權限＝擁有模組對**那張單據**自己的讀取規則（多數沿用 `uploads.path_access` 或 `for_document` 已有的判斷，不另寫第二份）。
ATTACHMENTS_CATALOG = "attachments.catalog"


class OpenedFile(NamedTuple):
    """`attachments.catalog` 提供者的 `open()` 回傳：一個已確認存在的實體檔。"""
    abs_path: str
    filename: str
    mime: str
    size: int


def upload_path_key(entry, folder, depth=2):
    """metadata 一筆的 `path` ⇒ 它在 `folder` 底下的「單據鍵」（資料夾之後第一段）；不是 `folder` 底下、段數不是 `depth`
    （單據鍵＋檔名＝2；工作日誌照片 `worklog_<id>/<日期>/<檔名>`＝3）、路徑不合法 ⇒ None。demo 前綴已去掉。
    給 `attachments.catalog` 提供者用：**被提供的檔案路徑必須屬於那張單據自己的資料夾**（安全審查 W3：
    metadata 來自 JSON 欄，前端曾可在案件紀錄 PATCH 帶任意 `files`／`invoiceFiles` 路徑，不能只信它）。"""
    rel = canonical_upload_path((entry or {}).get("path")) if isinstance(entry, dict) else None
    owner = upload_owner(rel) if rel else None
    if owner is None or owner[0] != folder or len(owner[1]) != depth:
        return None
    return owner[1][0]


def pick_file(files, file_id):
    """`files`（`save_document_files` 的 metadata 陣列）裡 id 等於 `file_id` 的那一筆；沒有 ⇒ None。"""
    fid = str(file_id)
    return next((f for f in (files or []) if isinstance(f, dict) and str(f.get("id")) == fid), None)


def opened_upload_file(entry):
    """metadata 一筆（含 `path`＝uploads 相對路徑）⇒ `OpenedFile`；路徑不合法、跑出 uploads、檔案不在 ⇒ None。
    只認 uploads 底下的檔（勞報單封存目錄等別處的檔由各提供者自己組 `OpenedFile`，由 L1 端點驗它宣告的根）。"""
    if not isinstance(entry, dict):
        return None
    rel = canonical_upload_path(entry.get("path"))
    if rel is None:
        return None
    full = os.path.realpath(os.path.join(UPLOADS_ROOT, *rel.split("/")))
    if not os.path.isfile(full):
        return None
    import mimetypes
    name = str(entry.get("filename") or os.path.basename(full))
    mime = str(entry.get("mime") or mimetypes.guess_type(name)[0] or "application/octet-stream")
    return OpenedFile(full, name, mime, os.path.getsize(full))


def files_from_json_column(conn, table: str, key_col: str, key, col: str) -> list:
    """`SELECT <col> FROM <table> WHERE <key_col>=?` 的 JSON 陣列（`save_document_files` 的 metadata）。
    列不存在 ⇒ []；JSON 壞掉 ⇒ raise AttachmentSourceError。表名／欄名由呼叫端寫死（不接使用者輸入）。"""
    row = conn.execute("SELECT %s AS v FROM %s WHERE %s = ?" % (col, table, key_col), (key,)).fetchone()
    if row is None:
        return []
    try:
        return json.loads(row["v"] or "[]") or []
    except (TypeError, ValueError):
        raise AttachmentSourceError("來源「%s」的附件資料格式不正確，無法帶入。" % table)


# ── 上傳檔的讀取權限（`uploads.path_access`，IP-104；2026-09-30 安全修正 P0）──────────────────────────
# 原本 `/api/photo-token` 與 `/api/uploads/…`（Authorization 標頭那條）只要求登入 ⇒ 任何登入者拿得到任何單據
# 附件（路徑形狀可列舉：`<資料夾>/<單號>/<檔名>`）。改為：路徑先正規化，再依第一段資料夾交給**擁有那張單據的
# 模組**，用那張單據自己的讀取規則判斷。沒有提供者認領的資料夾一律不放行（預設拒絕）。

#: 提供者 capability：`Obj.FOLDERS`（負責的第一段資料夾名稱）、`Obj.readable(conn, folder, rest, user) -> bool`
#: （`rest`＝資料夾之後的各段，含檔名；單據不存在或看不到 ⇒ False）。
PATH_ACCESS = "uploads.path_access"

#: demo 隔離前綴 ⇒ 去掉前綴後的第一段（`_demo_projects` 是 `projects` 的 demo 版，見 photos._photo_root）
_DEMO_PREFIXES = {_DEMO_SUBFOLDER_PREFIX: None, "_demo_projects": "projects"}


def _path_seg_ok(seg: str) -> bool:
    return bool(seg) and seg not in ('.', '..') and not any(c in seg for c in _BAD_PATH_CHARS)


def canonical_upload_path(raw):
    """請求帶來的上傳相對路徑 ⇒ 正規形式 `a/b/c`；不合法 ⇒ None。

    ```
    拒絕  空字串、絕對路徑（/ 開頭、磁碟代號）、反斜線、冒號（含 ADS）、NUL、. 與 ..、空段、只有一段
    拒絕  realpath 與字面路徑不同（連結／junction／Windows 尾端點號等 ⇒ 實際指到別處）或跑出 UPLOADS_ROOT
    ```
    不「幫忙正規化」（例如把 `a/../b` 變成 `b`）：合法的呼叫端送的都是存檔當下產生的正規路徑。"""
    s = str(raw or "")
    if not s or os.path.isabs(s):
        return None
    segs = s.split("/")
    if len(segs) < 2 or not all(_path_seg_ok(x) for x in segs):
        return None
    root = os.path.realpath(UPLOADS_ROOT)
    literal = os.path.normpath(os.path.join(root, *segs))
    real = os.path.realpath(literal)
    if os.path.normcase(real) != os.path.normcase(literal):
        return None
    if os.path.commonpath([os.path.normcase(root), os.path.normcase(real)]) != os.path.normcase(root):
        return None
    return "/".join(segs)


def upload_owner(rel: str):
    """正規路徑 ⇒ `(資料夾, 其餘各段)`（去掉 demo 前綴）；形狀不對 ⇒ None。"""
    segs = str(rel or "").split("/")
    if segs and segs[0] in _DEMO_PREFIXES:
        alias = _DEMO_PREFIXES[segs[0]]
        segs = ([alias] if alias else []) + segs[1:]
    if len(segs) < 2:
        return None
    return segs[0], tuple(segs[1:])


def upload_readable(conn, rel: str, user) -> bool:
    """這個人能不能讀這個上傳檔（`rel` 須先經 `canonical_upload_path`）。

    依第一段資料夾找 `uploads.path_access` 的提供者（擁有模組），用那張單據自己的讀取規則判斷。
    沒有提供者（模組不在，或資料夾沒有人認領，例：branding、voucher_attachments 各有自己的端點）⇒ False。
    提供者丟例外 ⇒ False 並記 ERROR（fail closed：壞掉只會少看到，不會多看到）。"""
    owner = upload_owner(rel)
    if owner is None or not isinstance(user, dict):
        return False
    folder, rest = owner
    from core import registry
    for key, prov in sorted(registry.providers(PATH_ACCESS).items()):
        if folder in (getattr(prov, "FOLDERS", ()) or ()):
            try:
                return bool(prov.readable(conn, folder, rest, user))
            except Exception:                                   # noqa: BLE001  fail closed
                import logging
                logging.getLogger(__name__).exception("uploads.path_access 提供者 %s 判斷 %s 失敗", key, rel)
                return False
    return False
