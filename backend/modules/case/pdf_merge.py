# -*- coding: utf-8 -*-
"""PDF 併檔（報價單／估價單的規格文件併入；設計 docs/platform/plans/QUOTE-EXTRA-NOTES-DESIGN.md §4）。

本檔是純函式（**放在 case 模組內、不是 L1 helper**：只有 case 用，登記成 L1 要升核心 minor 版；下次升核心版時評估收斂為 L1）：**不碰資料庫、不碰 HTTP、不認得報價單**。呼叫端（`modules/case/api/quotation_specs.py`）把要併的檔案
（id／檔名／絕對路徑）交進來，這裡只負責「本體＋附件 ⇒ 一份 PDF」與「哪些檔併不進去、為什麼」。

## 固定的「略過原因」詞彙（`SKIP_REASONS`；畫面與稽核都用這幾個字串，不接受別的）
| 代碼 | 意思 |
|---|---|
| encrypted | 有加密（含「空密碼可開」的也一律略過：客戶端的瀏覽器開得起來不代表本機可信任地併入） |
| broken | pypdf 讀不開／解析途中丟例外 |
| empty | 讀得開，但零頁（pypdf 對零頁 PDF 不丟任何例外，只有頁數能看出來） |
| missing | 實體檔不在（清單有、磁碟沒有） |
| over_pages | 併入後附件合計頁數會超過 `max_pages`（這個檔略過，後面較小的檔仍可併入） |
| over_size | 併入後附件檔案合計大小會超過 `max_total_mb`（同上） |

## 四條不變式（`backend/tests/test_pdf_merge_2026_11_17.py` 逐條鎖）
1. **本體永遠保留**：任何附件的任何問題都只會讓那個附件被略過，本體頁面一頁不少、不重複。
2. **不留殘頁**：附件在途中丟例外（例：第 7 頁壞掉）⇒ 整份輸出從頭重建、該檔不在裡面；不會有「前 6 頁已併進去」。
   做法：每個附件先過「便宜檢查」（加密／頁數／大小），再整批併；併的途中某檔出事 ⇒ 標 broken、從頭重建（最多重建 n 次，n＝檔數）。
3. **頁數與大小在併之前判斷**：超過上限的檔不會先併進去再回頭拆。
4. **略過原因不印進 PDF**：這裡不加任何文字、註解、書籤；原因只回傳給呼叫端（標頭／版本紀錄／畫面）。
"""
import io
import logging
import os

logger = logging.getLogger(__name__)

SKIP_REASONS = ("encrypted", "broken", "empty", "missing", "over_pages", "over_size")

#: 一次併入的附件頁數／大小預設上限（設計 D1～D5：300 頁、50MB）
DEFAULT_MAX_PAGES = 300
DEFAULT_MAX_TOTAL_MB = 50


def _skip(f: dict, reason: str) -> dict:
    assert reason in SKIP_REASONS, reason
    return {"id": f.get("id"), "name": f.get("name"), "reason": reason}


def probe_pdf(path: str):
    """試開一個 PDF 檔 ⇒ `(status, pages)`；status ∈ ok／encrypted／broken／empty（上傳當下記進 `spec_files_json`）。

    ⚠️ 加密檔在 `PdfReader()` 不丟，要讀頁數才丟 ⇒ 先看 `is_encrypted`，一律回 encrypted，不去猜密碼。
    ⚠️ 零頁 PDF 不丟任何例外 ⇒ 要看頁數。
    pypdf 讀的是不可信輸入，什麼例外都可能出來（遞迴過深、型別錯誤…）⇒ 這一格刻意接 Exception，一律當 broken（並記 log）。"""
    import pypdf
    try:
        with open(path, "rb") as fh:
            reader = pypdf.PdfReader(fh)
            if reader.is_encrypted:
                return "encrypted", 0
            n = len(reader.pages)
    except Exception as exc:                                        # noqa: BLE001 — 見 docstring
        logger.info("pdf probe failed (%s): %s", type(exc).__name__, os.path.basename(str(path)))
        return "broken", 0
    return ("empty", 0) if n == 0 else ("ok", n)


def _build(body: bytes, files: list):
    """本體＋這幾個檔 ⇒ `(bytes, 出事的檔 or None)`。**任何一個檔丟例外就回報是哪一個**（呼叫端排除它後從頭重建）。"""
    import pypdf
    writer = pypdf.PdfWriter()
    writer.append(pypdf.PdfReader(io.BytesIO(body)), import_outline=False)
    for f in files:
        try:
            with open(f["abs_path"], "rb") as fh:
                writer.append(pypdf.PdfReader(fh), import_outline=False)
        except Exception as exc:                                    # noqa: BLE001 — 第三方解析不可信輸入
            logger.info("pdf merge failed on %s (%s)", f.get("id"), type(exc).__name__)
            return None, f
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue(), None


def merge_pdf_bytes(body: bytes, files: list, *, max_pages: int = DEFAULT_MAX_PAGES,
                    max_total_mb: int = DEFAULT_MAX_TOTAL_MB):
    """`body`（本體 PDF bytes）＋ `files`（`[{id, name, abs_path}]`，依序）⇒ `(合併後 bytes, skipped)`。

    `skipped`＝`[{id, name, reason}]`，reason 見 `SKIP_REASONS`；沒有略過 ⇒ `[]`。
    `files` 為空 ⇒ 原樣回傳 `(body, [])`（不重新序列化本體）。本體永遠保留（見檔頭不變式）。"""
    if not files:
        return body, []
    skipped = []
    cand = []
    pages_total = 0
    bytes_total = 0
    cap_bytes = int(float(max_total_mb) * 1024 * 1024)
    for f in files:                                                  # 便宜檢查：不併、只看（不變式 3）
        path = f.get("abs_path")
        if not path or not os.path.isfile(path):
            skipped.append(_skip(f, "missing"))
            continue
        status, n = probe_pdf(path)
        if status != "ok":
            skipped.append(_skip(f, status))
            continue
        size = os.path.getsize(path)
        if pages_total + n > max_pages:
            skipped.append(_skip(f, "over_pages"))
            continue
        if bytes_total + size > cap_bytes:
            skipped.append(_skip(f, "over_size"))
            continue
        pages_total += n
        bytes_total += size
        cand.append(f)
    while cand:
        try:
            merged, bad = _build(body, cand)
        except Exception as exc:                                     # noqa: BLE001 — 本體自己讀不開／寫出失敗
            logger.warning("pdf merge: body unreadable or write failed (%s); returning body only", type(exc).__name__)
            # 本體永遠保留：原樣回本體；所有想併的檔都沒併進去（原因取 broken：最接近「這次併不進去」，且不增加詞彙）
            return body, skipped + [_skip(f, "broken") for f in cand]
        if bad is None:
            return merged, skipped
        skipped.append(_skip(bad, "broken"))                         # 不變式 2：該檔整個排除、從頭重建
        cand = [f for f in cand if f is not bad]
    return body, skipped
