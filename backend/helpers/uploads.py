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
)

import os
import uuid
from datetime import datetime
from typing import List

from fastapi import HTTPException, UploadFile

from core import paths as _paths
UPLOADS_ROOT = _paths.UPLOADS_ROOT

_ALLOWED_EXTS = {'.jpg', '.jpeg', '.png', '.pdf'}
_MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB／檔

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
                              uploaded_by: str, watermark_by: str = '') -> list:
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
    完全不變。"""
    if not files:
        raise HTTPException(400, "請至少選擇一個檔案")

    subfolder = _effective_subfolder(subfolder)
    save_dir = _safe_save_dir(subfolder, doc_no)
    os.makedirs(save_dir, exist_ok=True)

    saved = []
    now = datetime.now().isoformat()
    for upload in files:
        ext = os.path.splitext(upload.filename or '')[1].lower()
        if ext not in _ALLOWED_EXTS:
            raise HTTPException(400, f"不支援的檔案格式：{upload.filename}（僅支援 jpg/png/pdf）")
        raw = await upload.read()
        if len(raw) > _MAX_FILE_SIZE:
            raise HTTPException(400, f"檔案過大：{upload.filename}（單檔上限 20MB）")
        if not raw:
            raise HTTPException(400, f"檔案是空的：{upload.filename}")
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
