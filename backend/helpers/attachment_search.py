# -*- coding: utf-8 -*-
"""附件目錄的搜尋共用件（`attachments.catalog` 契約 v1 的 `search`／`count`；附件目錄 P3，
設計 proposal-attachments-search-preview §4-2、§4-4）。

[單位] helper:attachment_search    [層] L1    [穩定度] 契約（只增）
[公開介面] CRIT_KEYS, ITEM_KEYS, MAX_TAKE, case_names, count_by_type, finish, make_item, matches, normalize_crit, owned
[不變式]
  - 提供者 `search(conn, user, crit)` ⇒ 已套權限、已依 crit 篩過、`uploadedAt` 由新到舊、最多 `crit["take"]` 筆；
    項目鍵**固定**為 `ITEM_KEYS`（**沒有 path**：搜尋結果不可以把「猜不到的路徑」變成「列得出來」；開檔一律走 `/api/attachments/open`）
  - 提供者 `count(conn, user, crit)` ⇒ `{source_type: 命中數}`（已套權限；不套 `types` 條件，給分類側欄的數字）
  - **看不到的不列、也不回「因權限未列出 N 個」**：`q` 可任意輸入，回「有 3 個檔名含『X』你看不到」本身就是外洩（設計 §8 Q3）
  - 權限必須用**原單據自己的讀取規則**（提供者沿用各自 `open()` 用的那一支）；本檔只管篩選、排序、項目形狀，不碰權限
  - **路徑綁單據**：`open()` 只開「路徑在這張單據自己資料夾」的檔（W3），搜尋列出的檔必須是同一批——
    `owned(entry, 資料夾, 單據鍵)` 為真才可以 `make_item`（否則搜尋會列出一個開不了、或指到別張單據的檔）
[契約題] tests/test_filehub_search_2026_09_30.py
"""
import os


#: 搜尋條件（`filehub` API 與案件頁「全部附件」都只傳這些；未知鍵忽略）
CRIT_KEYS = ("q", "types", "exts", "date_from", "date_to", "uploader", "quote_no", "doc_no", "customer", "take")
#: 搜尋結果項目的鍵（守門：提供者回的鍵 ⊆ 這份；沒有 path）
ITEM_KEYS = ("sourceType", "docNo", "docLabel", "quoteNo", "customerName", "projectName", "fileId", "filename", "ext",
             "size", "mime", "uploadedBy", "uploadedAt", "link")
MAX_TAKE = 1050          # page≤20 × size≤50 ＋ 1（hasMore 判斷）


def normalize_crit(raw) -> dict:
    """任意 dict ⇒ 乾淨的搜尋條件（字串去頭尾空白、清單去空白與重複、`take` 夾在 1～MAX_TAKE）。"""
    raw = raw if isinstance(raw, dict) else {}

    def s(k):
        return str(raw.get(k) or "").strip()

    def lst(k):
        v = raw.get(k) or []
        v = [x.strip() for x in v.split(",")] if isinstance(v, str) else [str(x).strip() for x in v]
        return [x for i, x in enumerate(v) if x and x not in v[:i]]

    try:
        take = int(raw.get("take") or 50)
    except (TypeError, ValueError):
        take = 50
    return {"q": s("q"), "types": lst("types"), "exts": [e.lower().lstrip(".") for e in lst("exts")],
            "date_from": s("date_from")[:10], "date_to": s("date_to")[:10], "uploader": s("uploader"),
            "quote_no": s("quote_no"), "doc_no": s("doc_no"), "customer": s("customer"),
            "take": max(1, min(MAX_TAKE, take))}


def _ext(name) -> str:
    return os.path.splitext(str(name or ""))[1].lower().lstrip(".")


def make_item(source_type, doc_no, doc_label, f, *, quote_no="", customer="", project="", link="") -> dict:
    """檔案 metadata（`save_document_files` 的一筆，或等形狀的 dict：id／filename／size／mime／uploadedBy／uploadedAt）⇒ 搜尋項目。"""
    f = f if isinstance(f, dict) else {}
    name = str(f.get("filename") or f.get("name") or "")
    return {"sourceType": source_type, "docNo": str(doc_no), "docLabel": str(doc_label), "quoteNo": str(quote_no or ""),
            "customerName": str(customer or ""), "projectName": str(project or ""), "fileId": str(f.get("id") or ""),
            "filename": name, "ext": _ext(name), "size": int(f.get("size") or 0), "mime": str(f.get("mime") or ""),
            "uploadedBy": str(f.get("uploadedBy") or ""), "uploadedAt": str(f.get("uploadedAt") or ""), "link": str(link or "")}


def matches(it, c, *, ignore_types=False) -> bool:
    """項目是否符合條件 `c`（`normalize_crit` 的結果）。`ignore_types`＝算分類數字時不套 `types`。"""
    if not ignore_types and c["types"] and it["sourceType"] not in c["types"]:
        return False
    if c["exts"] and it["ext"] not in c["exts"]:
        return False
    day = it["uploadedAt"][:10]
    if c["date_from"] and (not day or day < c["date_from"]):
        return False
    if c["date_to"] and (not day or day > c["date_to"]):
        return False
    if c["uploader"] and c["uploader"].lower() not in it["uploadedBy"].lower():
        return False
    if c["quote_no"] and it["quoteNo"].lower() != c["quote_no"].lower():
        return False
    if c["doc_no"] and c["doc_no"].lower() not in it["docNo"].lower():
        return False
    if c["customer"] and c["customer"].lower() not in it["customerName"].lower():
        return False
    if c["q"]:
        q = c["q"].lower()
        if not any(q in str(it[k]).lower() for k in ("filename", "docNo", "quoteNo", "customerName", "projectName", "docLabel")):
            return False
    return True


def finish(items, c) -> list:
    """篩選、依上傳時間由新到舊（同時間依檔名、檔案 id 定序，翻頁穩定）、最多 `take` 筆。"""
    out = [it for it in items if matches(it, c)]
    out.sort(key=lambda it: (it["uploadedAt"], it["filename"], it["fileId"]), reverse=True)
    return out[:c["take"]]


def count_by_type(items, c) -> dict:
    """命中數依 source_type（不套 `types` 條件）。"""
    out = {}
    for it in items:
        if matches(it, c, ignore_types=True):
            out[it["sourceType"]] = out.get(it["sourceType"], 0) + 1
    return out


def owned(entry, folder, key) -> bool:
    """檔案 entry 的路徑是否在這張單據自己的資料夾（與各提供者 `open()` 同一支判斷 `helpers.uploads.upload_path_key`）。"""
    from helpers.uploads import upload_path_key
    return isinstance(entry, dict) and upload_path_key(entry, folder) == str(key)


def case_names(conn, quote_nos) -> dict:
    """案件單號 ⇒ `(客戶名, 案名)`（經 M01 的 `case.summary` 提供者；M01 不在或查無 ⇒ 空字串）。
    搜尋項目只帶客戶名與案名（顯示用），不帶案件內容；權限判斷由各提供者在列出之前已做。"""
    from core import registry
    qs = sorted({q for q in quote_nos if q})
    summary = registry.single_provider("case.summary")
    if summary is None or not qs:
        return {q: ("", "") for q in qs}
    try:
        from .case_access import SYSTEM
        rows = summary(conn, SYSTEM, qs)        # 權限已在提供者判斷完，這裡只取顯示名（同 routers/approval_queue）
    except Exception:                                   # noqa: BLE001  顯示用的欄位，取不到不擋搜尋
        return {q: ("", "") for q in qs}
    by = {r["quote_no"]: (r["customer_name"] or "", r["project_name"] or "") for r in rows}
    return {q: by.get(q, ("", "")) for q in qs}


__all__ = ["CRIT_KEYS", "ITEM_KEYS", "MAX_TAKE", "case_names", "count_by_type", "finish", "make_item", "matches", "normalize_crit", "owned"]
