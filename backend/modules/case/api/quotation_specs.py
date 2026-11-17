# -*- coding: utf-8 -*-
"""報價單／估價單的「規格文件」（備註事項 B：規格 PDF 併入）。設計見 docs/platform/plans/QUOTE-EXTRA-NOTES-DESIGN.md §4、§10。

資料：
- `quotations.spec_files_json`（case migration 0013；TEXT NOT NULL DEFAULT '[]'）＝這張單**上傳過**的規格 PDF 清單，
  每筆 `{id, name, path, size, pages, status, uploadedAt, uploadedBy}`；`id`＝伺服器產生的 uuid hex；
  `status` ∈ ok／encrypted／broken／empty（上傳當下用 pypdf 試開；非 ok 的檔仍可存放，但**合併時一律略過**）。
- `data_json.mergeFiles`＝**要併進輸出 PDF 的**檔案 id、有順序；沒選就**不存這個鍵**（不存空陣列）。
  這個鍵跟著報價單內容走（簽核綁版本、存檔版本都看得到「當時併了哪幾份」）；清單本身（`spec_files_json`）則是即時的檔案櫃。

端點（都在報價單「可編輯」狀態才能動；規則同 PUT 報價單的狀態鎖，見 `_quote_edit_gate`）：
- `POST   /api/quotations/{no}/spec-files`          多檔、欄位名 `files`、只收 .pdf；單檔不合格不拖垮整批（回 `rejected`）
- `DELETE /api/quotations/{no}/spec-files/{file_id}` 刪檔＋清單＋`mergeFiles` 同一個寫交易，commit 之後才刪實體檔（T83 慣例；失敗＝全部還在）
- 讀：單筆報價單 GET 多一個頂層 `specFiles`（不含路徑）；預覽走既有附件目錄，來源類型 `quotation_spec`（`attachments.py`）。

純函式（給 `quotations.py` 與測試用，**這個檔頂層不 import `quotations.py`**——它們互相需要時由函式內延後載入，避免循環）：
`public_spec_files`、`validate_merge_files`、`merge_for_download`。

⚠️ 不動 `updated_at`：上傳／刪檔不是「內容變更」，且開著的表單帶著 `_expectedUpdatedAt`——這裡一動，使用者上傳完按存檔就會被 409。
"""
import json
import logging
import os
import uuid
from datetime import datetime
from typing import List

from fastapi import APIRouter, File, Header, HTTPException, UploadFile

from db import get_db
from helpers import _audit, _require_user, _tok
from helpers import pdf_merge as _pm
from helpers import uploads as _up
from helpers.uploads import append_json_list, files_txn, remove_physical_file, save_document_files

logger = logging.getLogger(__name__)
router = APIRouter()

SPEC_FOLDER = "quotation_specs"
MAX_SPEC_FILES = 10                       # 每張單最多幾個規格檔（也是 mergeFiles 的上限）
MAX_SPEC_TOTAL_BYTES = 50 * 1024 * 1024   # 每張單規格檔合計大小上限（單檔上限沿用 `uploads.max_file_mb`，預設 20MB）
MAX_MERGE_PAGES = _pm.DEFAULT_MAX_PAGES   # 併入的附件頁數上限（300）
MAX_MERGE_TOTAL_MB = _pm.DEFAULT_MAX_TOTAL_MB

#: 與 `api/quotations.py::update_quotation` 的 `_LOCKED` 同一份（該處是函式內區域變數，無法 import；
#: `tests/test_quote_spec_files_2026_11_17.py` 逐字比對原始碼，兩邊不一致就轉紅）。
EDIT_LOCKED_STATUSES = ("待審核", "簽核中", "已送出", "已成案", "已結案")

#: 上傳被擋的原因代碼（`rejected[].reason`；`message` 是給人看的一句話）
REJECT_REASONS = ("not_pdf", "empty", "too_large", "too_many", "over_total", "invalid")


# ── 純函式 ────────────────────────────────────────────────────────────────────

def load_spec_files(raw) -> list:
    """`spec_files_json`（字串或已解析）⇒ list[dict]；壞資料 ⇒ []（不丟例外：讀取端不可以因為一欄壞掉整張單打不開）。"""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw else []
        except ValueError:
            return []
    return [f for f in raw if isinstance(f, dict) and f.get("id")] if isinstance(raw, list) else []


def public_spec_files(raw) -> list:
    """給前端的清單：**不含 path**（路徑只在伺服器用；預覽走附件目錄 `quotation_spec`）。"""
    return [{"id": f.get("id"), "name": f.get("name") or "", "size": int(f.get("size") or 0), "pages": int(f.get("pages") or 0),
             "status": f.get("status") or "ok", "uploadedAt": f.get("uploadedAt") or "", "uploadedBy": f.get("uploadedBy") or ""}
            for f in load_spec_files(raw)]


def merge_ids_of(data) -> list:
    """`data_json`（dict 或字串）裡的 `mergeFiles`（只取字串元素）；沒有／壞 ⇒ []。"""
    if isinstance(data, str):
        try:
            data = json.loads(data) if data else {}
        except ValueError:
            data = {}
    ids = (data or {}).get("mergeFiles") if isinstance(data, dict) else None
    return [i for i in ids if isinstance(i, str)] if isinstance(ids, list) else []


def validate_merge_files(ids, spec_files) -> List[str]:
    """存檔點用：`ids`（前端送來的 `mergeFiles`）⇒ 清理後的 id 清單（保序）。

    - 不是 list、有非字串元素、**原始**個數超過 `MAX_SPEC_FILES` ⇒ `HTTPException(400)`。
    - 重複的 id 只留第一個；不在這張單 `spec_files_json` 裡的 id 靜默丟掉（例：複製來的單、別張單的 id、已刪的檔）。
    - 回傳可能是空 list——**呼叫端要把空的當成沒選（不存 `mergeFiles` 這個鍵）**。"""
    if not isinstance(ids, list):
        raise HTTPException(400, "mergeFiles 必須是檔案 id 的清單")
    if any(not isinstance(i, str) for i in ids):
        raise HTTPException(400, "mergeFiles 的每一項都必須是字串（檔案 id）")
    if len(ids) > MAX_SPEC_FILES:
        raise HTTPException(400, "最多只能併入 %d 份規格文件" % MAX_SPEC_FILES)
    known = {f["id"] for f in load_spec_files(spec_files)}
    out, seen = [], set()
    for i in ids:
        if i in known and i not in seen:
            seen.add(i)
            out.append(i)
    return out


def _abs_path_of(entry: dict, quote_no: str):
    """這一筆 metadata 的實體檔絕對路徑；路徑不合法／不在這張單自己的資料夾 ⇒ None（不信 JSON 欄裡的路徑，W3）。"""
    if _up.upload_path_key(entry, SPEC_FOLDER) != quote_no:
        return None
    rel = _up.canonical_upload_path(entry.get("path"))
    return os.path.realpath(os.path.join(_up.UPLOADS_ROOT, *rel.split("/"))) if rel else None


def merge_for_download(row, body: bytes):
    """輸出 PDF 用：`row`（要有 `quote_no`、`data_json`、`spec_files_json`）＋ `body`（本體 PDF）⇒ `(bytes, skipped)`。

    - `data_json.mergeFiles` 沒有（或空）⇒ **原樣回 `(body, [])`**（沒用這功能的單，輸出逐位元不變）。
    - 狀態不是 ok 的檔（加密／壞檔／零頁）不開、直接略過（原因＝它的 status）；實體檔不在／路徑不合法 ⇒ missing。
    - 不在清單裡的 id 靜默忽略（與 `validate_merge_files` 同）。
    - 本體永遠保留；略過的原因只回傳、不印進 PDF（見 `helpers/pdf_merge.py`）。`skipped`＝`[{id, name, reason}]`，依 mergeFiles 順序。"""
    keys = row.keys() if hasattr(row, "keys") else ()
    ids = merge_ids_of(row["data_json"] if "data_json" in keys else None)
    if not ids:
        return body, []
    quote_no = row["quote_no"] if "quote_no" in keys else ""
    by_id = {f["id"]: f for f in load_spec_files(row["spec_files_json"] if "spec_files_json" in keys else None)}
    order = [i for i in dict.fromkeys(ids) if i in by_id]
    pre, todo = {}, []
    for i in order:
        f = by_id[i]
        name = f.get("name") or ""
        st = f.get("status") or "ok"
        if st != "ok":
            pre[i] = {"id": i, "name": name, "reason": st if st in _pm.SKIP_REASONS else "broken"}
            continue
        ap = _abs_path_of(f, quote_no)
        if ap is None:
            pre[i] = {"id": i, "name": name, "reason": "missing"}
            continue
        todo.append({"id": i, "name": name, "abs_path": ap})
    merged, skipped = _pm.merge_pdf_bytes(body, todo, max_pages=MAX_MERGE_PAGES, max_total_mb=MAX_MERGE_TOTAL_MB)
    by_skip = dict(pre)
    by_skip.update({s["id"]: s for s in skipped})
    return merged, [by_skip[i] for i in order if i in by_skip]


def skipped_header(skipped) -> str:
    """`X-Pdf-Merge-Skipped` 標頭值：`[{id,name,reason}]` 的 JSON（緊湊）再 URL 編碼（標頭只能 ASCII）；檔名截 30 字（標頭大小有限）。
    沒有略過 ⇒ 空字串（呼叫端不設這個標頭）。專案的 CORS 沒設 `expose_headers`（同源取用）⇒ 不需要另外開放。"""
    if not skipped:
        return ""
    from urllib.parse import quote
    slim = [{"id": s.get("id"), "name": str(s.get("name") or "")[:30], "reason": s.get("reason")} for s in skipped]
    return quote(json.dumps(slim, ensure_ascii=False, separators=(",", ":")), safe="")


def merge_or_keep(row, body: bytes):
    """`merge_for_download` 的保險版（給下載端點與存檔點用）：合併過程出了**我們自己的**非預期錯誤 ⇒ 記 log、原樣回本體
    （附件問題不可以讓報價單 PDF 下載／存檔失敗；本體永遠保留）。`skipped` 為空＝沒有略過。"""
    try:
        return merge_for_download(row, body)
    except Exception:                                              # noqa: BLE001 — 見 docstring
        logger.exception("spec merge failed; returning body only (%s)", row["quote_no"] if row is not None and "quote_no" in row.keys() else "?")
        return body, []


def merge_into_archived_pdf(quote_no: str, pdf_path: str) -> list:
    """背景存檔版 PDF（`pdf_gen._generate_quotation_pdf` 剛用 Edge 寫好的檔）⇒ 就地併入規格 PDF，回 `skipped`。
    沒選規格文件（沒有 `mergeFiles`）⇒ 完全不碰檔案、回 []。寫回用「同資料夾暫存檔 → `os.replace`」：中途失敗＝原檔（只有本體）不變。
    ⚠️ 讀的是**此刻**的 `mergeFiles`（Edge 產生本體之後才讀）：產生途中被改的機會極小（存檔版都由存檔／簽核／結案觸發，狀態已鎖）。"""
    conn = get_db()
    try:
        row = conn.execute("SELECT quote_no, data_json, spec_files_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    finally:
        conn.close()
    if row is None or not merge_ids_of(row["data_json"]):
        return []
    with open(pdf_path, "rb") as fh:
        body = fh.read()
    merged, skipped = merge_or_keep(row, body)
    if merged is not body and merged != body:
        tmp = pdf_path + ".merge.tmp"
        try:
            with open(tmp, "wb") as fh:
                fh.write(merged)
            os.replace(tmp, pdf_path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    return skipped


def record_doc_version_with_merge(quote_no: str, entry: dict, keep: int) -> None:
    """`case.doc_version` 提供者（IP-92；`modules/case/__init__.py` 登記這一支，裡面再呼叫原本的 `quotations._record_doc_version`）：
    L1 `pdf_gen` 產生存檔版 PDF 後呼叫 ⇒ **先把選好的規格 PDF 併進那個檔**，再記版本（`size` 是併入後的大小；有略過 ⇒ 版本紀錄多 `mergeSkipped`
    `[{id,name,reason}]`，沒略過就沒有這個鍵）。L1 不需要認得規格文件（不新增整合點、`pdf_gen.py` 不用動）。
    併入失敗（我們自己的非預期錯誤）⇒ 記 log、版本照記（檔案仍是只有本體的那份）。"""
    from modules.case import quotations as _Q
    try:
        from pdf_gen import _get_pdf_base
        base = os.path.realpath(_get_pdf_base())
        full = os.path.realpath(os.path.join(base, str(entry.get("file") or "").lstrip("/\\")))
        if entry.get("file") and os.path.commonpath([full, base]) == base and os.path.isfile(full):
            skipped = merge_into_archived_pdf(quote_no, full)
            entry = dict(entry, size=os.path.getsize(full))
            if skipped:
                entry["mergeSkipped"] = [{"id": x.get("id"), "name": x.get("name"), "reason": x.get("reason")} for x in skipped]
    except Exception:                                              # noqa: BLE001 — 見 docstring
        logger.exception("archived pdf spec merge failed for %s", quote_no)
    _Q._record_doc_version(quote_no, entry, keep)


# ── 閘門 ──────────────────────────────────────────────────────────────────────

def _quote_edit_gate(row, user=None):
    """可不可以動這張單的規格文件：**與 PUT 報價單的狀態鎖同一條規則**（`update_quotation`：已拒絕、`EDIT_LOCKED_STATUSES` 一律 403）。
    ⚠️ 解鎖編輯（最高管理者）進行中，資料庫的狀態仍是原本的鎖定狀態（要存檔才變）⇒ 這段期間也不能上傳／刪檔；要先存檔或另案決定放寬。
    `row` 需有 `status`。擁有者規則（誰看得到這張單）由呼叫端的 `_guard_case` 負責。"""
    st = row["status"] if row is not None else ""
    if st == "已拒絕":
        raise HTTPException(403, "已駁回結案的報價單不可修改")
    if st in EDIT_LOCKED_STATUSES:
        raise HTTPException(403, "報價單狀態為「%s」，請透過正式流程操作或解鎖後修改" % st)


def _response(spec_list, data_json) -> dict:
    return {"specFiles": public_spec_files(spec_list), "mergeFiles": merge_ids_of(data_json)}


def _reject(rejected: list, name: str, reason: str, message: str) -> None:
    assert reason in REJECT_REASONS, reason
    rejected.append({"name": name, "reason": reason, "message": message})


# ── 端點 ──────────────────────────────────────────────────────────────────────

@router.post("/api/quotations/{quote_no}/spec-files")
async def upload_spec_files(quote_no: str, files: List[UploadFile] = File(...), authorization: str = Header(None)):
    """上傳規格 PDF（多檔）。回 200：`{specFiles, mergeFiles, rejected}`——不合格的檔列在 `rejected`（`reason` 見 `REJECT_REASONS`），
    其餘照存；整批都不合格也是 200（`specFiles` 不變、`rejected` 全列）。不自動勾選：要併哪幾份由使用者在表單選、隨報價單存檔。"""
    user = _require_user(authorization)
    from modules.case.api import quotations as Q          # 延後載入：quotations.py 頂層會 import 本檔
    conn = get_db()
    try:
        Q._guard_case(conn, quote_no, user)
        row = conn.execute("SELECT status, spec_files_json, data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
        if not row:
            raise HTTPException(404, "報價單不存在")
        _quote_edit_gate(row, user)
        cur = load_spec_files(row["spec_files_json"])
        count = len(cur)
        total = sum(int(f.get("size") or 0) for f in cur)
        cap = _up.max_file_bytes()
        by = user.get("display_name") or user["username"]
        new_files, rejected = [], []
        for up in files:
            name = up.filename or ""
            if os.path.splitext(name)[1].lower() != ".pdf":
                _reject(rejected, name, "not_pdf", "只收 PDF 檔")
                continue
            raw = await up.read()
            if not raw:
                _reject(rejected, name, "empty", "檔案是空的")
                continue
            if len(raw) > cap:
                _reject(rejected, name, "too_large", "單檔上限 %dMB" % (cap // (1024 * 1024)))
                continue
            if count + len(new_files) >= MAX_SPEC_FILES:
                _reject(rejected, name, "too_many", "每張單最多 %d 份規格文件" % MAX_SPEC_FILES)
                continue
            if total + len(raw) > MAX_SPEC_TOTAL_BYTES:
                _reject(rejected, name, "over_total", "規格文件合計上限 %dMB" % (MAX_SPEC_TOTAL_BYTES // (1024 * 1024)))
                continue
            await up.seek(0)
            try:
                saved = await save_document_files("quotation_specs", quote_no, [up], by, existing_count=count + len(new_files))
            except HTTPException as exc:                       # 檔頭與副檔名不符等（單檔層級）
                _reject(rejected, name, "invalid", str(exc.detail))
                continue
            s = saved[0]
            status, pages = _pm.probe_pdf(os.path.join(_up.UPLOADS_ROOT, *s["path"].split("/")))
            new_files.append({"id": uuid.uuid4().hex, "name": s["filename"], "path": s["path"], "size": s["size"], "pages": pages,
                              "status": status, "uploadedAt": s["uploadedAt"], "uploadedBy": by})
            total += s["size"]
        if not new_files:
            out = _response(cur, row["data_json"])
            out["rejected"] = rejected
            return out

        def _cap_guard(latest):                                # 寫鎖內重驗：上傳途中別人也傳了
            if len(latest) + len(new_files) > MAX_SPEC_FILES or \
               sum(int(f.get("size") or 0) for f in latest) + sum(f["size"] for f in new_files) > MAX_SPEC_TOTAL_BYTES:
                raise HTTPException(409, "規格文件數量或大小已達上限（上傳途中有人也上傳了檔案），請重新整理後再傳")

        with files_txn(conn, new_files):                       # 任何失敗 ⇒ rollback 並刪掉這批剛存的檔
            fresh = conn.execute("SELECT status, data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
            if not fresh:
                raise HTTPException(404, "報價單不存在")
            _quote_edit_gate(fresh, user)                      # 上傳途中狀態變了（例：被送審）⇒ 擋下、檔收回
            merged = append_json_list(conn, "quotations", "spec_files_json", "quote_no", quote_no, new_files,
                                      guard=_cap_guard, not_found="報價單不存在")
        out = _response(merged, fresh["data_json"])
        out["rejected"] = rejected
    finally:
        conn.close()
    names = "、".join(str(f["name"])[:60] for f in new_files)[:300]
    _audit(_tok(authorization), "quotation.upload_spec_files", "quotation", quote_no,
           "%s（%d 個規格文件：%s）" % (quote_no, len(new_files), names))
    return out


@router.delete("/api/quotations/{quote_no}/spec-files/{file_id}")
def delete_spec_file(quote_no: str, file_id: str, authorization: str = Header(None)):
    """刪除一份規格文件：檔案清單、`data_json.mergeFiles`（若有選它）同一個寫交易；commit 之後才刪實體檔。回 `{specFiles, mergeFiles}`。
    清單裡沒有這個 id ⇒ 404；檔案路徑不在這張單自己的資料夾（資料被竄改）⇒ 409 且不碰磁碟。"""
    user = _require_user(authorization)
    from modules.case.api import quotations as Q
    from modules.case.quotations import save_quotation_json
    conn = get_db()
    try:
        Q._guard_case(conn, quote_no, user)
        pre = conn.execute("SELECT status FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
        if not pre:
            raise HTTPException(404, "報價單不存在")
        _quote_edit_gate(pre, user)
        target = None
        with files_txn(conn, []):                              # 讀 data_json 之前先拿寫鎖（lost update）；任何失敗 ⇒ 全部 rollback
            row = conn.execute("SELECT status, spec_files_json, data_json, updated_at FROM quotations WHERE quote_no=?",
                               (quote_no,)).fetchone()
            if not row:
                raise HTTPException(404, "報價單不存在")
            _quote_edit_gate(row, user)
            cur = load_spec_files(row["spec_files_json"])
            target = next((f for f in cur if f["id"] == file_id), None)
            if target is None:
                raise HTTPException(404, "找不到這份規格文件")
            if _up.upload_path_key(target, SPEC_FOLDER) != quote_no:
                raise HTTPException(409, "這份規格文件的檔案位置不正確，無法刪除；請洽管理員")
            remaining = [f for f in cur if f["id"] != file_id]
            conn.execute("UPDATE quotations SET spec_files_json=? WHERE quote_no=?",
                         (json.dumps(remaining, ensure_ascii=False), quote_no))
            data = json.loads(row["data_json"] or "{}") or {}
            mids = merge_ids_of(data)
            if file_id in mids:
                left = [i for i in mids if i != file_id]
                if left:
                    data["mergeFiles"] = left
                else:
                    data.pop("mergeFiles", None)                # 沒選＝不存這個鍵
                save_quotation_json(conn, quote_no, data, updated_at=row["updated_at"])      # 維持 updated_at（見檔頭）
        out = _response(remaining, data)
    finally:
        conn.close()
    remove_physical_file(target)                                # commit 之後才刪實體檔（失敗＝留下孤兒檔、不影響資料）
    _audit(_tok(authorization), "quotation.delete_spec_file", "quotation", quote_no,
           "%s（%s）" % (quote_no, str(target.get("name") or "")[:60]))
    return out
