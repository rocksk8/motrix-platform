# -*- coding: utf-8 -*-
"""檔案中心（附件目錄 P3，設計 proposal-attachments-search-preview §4-4）：全系統「上傳檔案」的分類搜尋。

`GET /api/filehub/search` ＝把 `registry.providers("attachments.catalog")` 各提供者的 `search`／`count` 合併起來：
- 每個提供者已套**原單據自己的讀取規則**；本檔只合併、排序、分頁，不做任何權限判斷，也不讀任何別組的表（L2 之間零 import）
- **看不到的不列、不回個數**（設計 §8 Q3：`q` 可任意輸入，回「有 N 個檔名含 X 你看不到」本身就是外洩）
- 結果項目只有 `ITEM_KEYS`（沒有 path）；開檔走 L1 `GET /api/attachments/open`，預覽用 `MotrixFilePreview`
- 模組不在 ⇒ `unavailable` 明說那一類沒有列入（不是「沒有檔案」）
- 分頁：每個提供者取 `page×size+1` 筆，合併依上傳時間由新到舊；`page ≤ 20`（再往後請加條件，畫面明說）
權限：沒指定 `quote_no`（全域瀏覽）要有「檔案中心」模組權限（或最高管理者）；指定 `quote_no`（案件頁「全部附件」）任何登入者都可呼叫——
結果本來就只含呼叫者在原單據頁打得開的檔案。"""
import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

from core import registry
from db import get_db
from helpers import _require_user
from helpers import attachment_search as S
from helpers.auth import user_has_module
from helpers.uploads import ATTACHMENTS_CATALOG

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_PAGE = 20
#: 目錄依賴的擁有模組（key ⇒ 顯示名）：不在／沒載入 ⇒ `unavailable` 明說（MODULE-GUIDE：缺席不可以跟「沒有檔案」長一樣）
EXPECTED_OWNERS = {"case": "案件", "supply": "採購・庫存・出貨", "arap": "應收應付", "subcontract": "外包工班",
                   "crm": "業務開發", "accounting": "會計", "payroll": "薪資獎金"}


def _unavailable() -> list:
    states = {st["key"]: st for st in registry.module_states()}
    out = []
    for key, name in EXPECTED_OWNERS.items():
        st = states.get(key)
        if st is None or st["state"] != "loaded":
            out.append({"category": name, "reason": "%s模組未載入：%s的上傳檔案沒有列入搜尋（不是 0 筆）" % (name, name)})
    return out


def _clean(it) -> dict:
    return {k: it[k] for k in S.ITEM_KEYS if k in it}


@router.get("/api/filehub/search")
def search(q: str = Query(""), types: str = Query(""), exts: str = Query(""), date_from: str = Query(""), date_to: str = Query(""),
           uploader: str = Query(""), quote_no: str = Query(""), doc_no: str = Query(""), customer: str = Query(""),
           page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=50), authorization: Optional[str] = Header(None)):
    u = _require_user(authorization)
    if not quote_no.strip() and not (u.get("role") == "superadmin" or user_has_module(u, "file_center")):
        raise HTTPException(403, "沒有「檔案中心」的權限")
    if page > MAX_PAGE:
        raise HTTPException(400, "結果太多：請加條件（關鍵字、日期區間、類別）縮小範圍，最多翻到第 %d 頁" % MAX_PAGE)
    crit = S.normalize_crit({"q": q, "types": types, "exts": exts, "date_from": date_from, "date_to": date_to, "uploader": uploader,
                             "quote_no": quote_no, "doc_no": doc_no, "customer": customer, "take": page * size + 1})
    conn = get_db()
    try:
        pool, counts, cats, failed = [], {}, [], []
        for name, prov in sorted(registry.providers(ATTACHMENTS_CATALOG).items()):
            cats += [dict(type=t, **meta) for t, meta in (getattr(prov, "CATEGORIES", None) or {}).items()]
            try:
                pool += prov.search(conn, u, crit)
                for t, n in prov.count(conn, u, crit).items():
                    counts[t] = counts.get(t, 0) + int(n)
            except Exception:                                    # noqa: BLE001  壞一個提供者只少那一類，並明說
                logger.exception("attachments.catalog 提供者 %s 搜尋失敗", name)
                failed.append({"category": name, "reason": "%s 的附件讀取失敗，這一類沒有列入（不是 0 筆）" % name})
    finally:
        conn.close()
    pool.sort(key=lambda it: (it["uploadedAt"], it["filename"], it["fileId"]), reverse=True)
    pool = pool[:crit["take"]]
    start = (page - 1) * size
    by_ext = {}
    for it in pool:
        by_ext[it["ext"]] = by_ext.get(it["ext"], 0) + 1
    by_module = {}
    for c in cats:
        by_module[c["module"]] = by_module.get(c["module"], 0) + counts.get(c["type"], 0)
    return {"items": [_clean(it) for it in pool[start:start + size]], "page": page, "size": size, "hasMore": len(pool) > start + size,
            "facets": {"byType": counts, "byExt": by_ext, "byModule": by_module},
            "categories": [dict(c, count=counts.get(c["type"], 0)) for c in sorted(cats, key=lambda c: (c["module"], c["type"]))],
            "unavailable": _unavailable() + failed}
