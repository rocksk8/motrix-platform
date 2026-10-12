# -*- coding: utf-8 -*-
"""已回簽擇一單的鎖定比對（M3 T9b；P1／P4；T57）。純函式，不碰資料庫。

不變式（H1）：比對一律在**伺服器端**，以**已存列的值**為準；不看用戶端旗標（`_isUnlockEdit` 只是用戶端的意圖，不是放行理由）。
範圍（P1，fail-closed）：只限『報價本文』。
- ① 鎖定整份報價本文：品項（每一欄含逐項備註）、金額類頂層鍵、擇一鍵、**其餘全部頂層鍵**（以『已存的鍵 ∪ 送來的鍵』扣掉下面的流程／伺服器自有鍵）。
- ② 只鎖品項與金額：品項（不含逐項備註）、金額類頂層鍵、擇一鍵；報價備註與條款文字放行。
不在範圍（放行）：流程與伺服器自有的鍵（簽核、編輯紀錄、案件執行紀錄、精算、回簽產物、擇一選定與快照、據點身分快照等）。
比對語意：空字串、None、缺鍵視為相同；數字以數值比較（1000 與 1000.0 相同）；品項金額 `amount` 是衍生值不比對。"""
import json

#: 流程／伺服器自有（不屬報價本文）：不比對。
PROCESS_KEYS = frozenset({
    "approval", "editHistory", "tot", "caseRecord", "settlement", "dealTag", "statusLog", "status", "quoteNo", "updatedAt", "createdAt",
    "isSigned", "signedBy", "signedAt", "signedLog", "signedFiles", "docVersions",
    "altPicks", "altPickedAt", "altPickedBy", "altTexts", "overheadPct", "locationIdentity", "locationId",
    "_isUnlockEdit", "_expectedUpdatedAt",
})
#: 金額類頂層鍵（financial_mask.QUOTE_MONEY_KEYS 去掉 tot／overheadPct，加上稅別與依據）＋擇一鍵
MONEY_KEYS = ("discount", "freight", "indirectLogistics", "indirectInstallation", "indirectTravel", "indirectWarranty", "indirectOther",
              "taxRate", "taxType", "taxBasis", "showDiscount")
ALT_KEYS = ("totalsByAlt",)
#: 品項欄位：金額與結構（②也鎖）／逐項備註（只有①鎖）
ITEM_CORE = ("id", "type", "description", "brand", "qty", "unit", "cost", "margin", "unitPrice", "unitPriceOverride", "altGroup")
ITEM_NOTE = ("notes",)

SCOPE_ALL, SCOPE_ITEMS_MONEY = 1, 2
LOCKED_MSG = "已回簽，請管理員取消回簽"


def _n(v):
    """正規化：空值一致；數字以數值比較；其餘轉 JSON 字串（穩定排序）。"""
    if v is None or v == "" or v == [] or v == {}:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        try:
            return float(s) if s and s.replace(".", "", 1).lstrip("-").isdigit() else s
        except ValueError:
            return s
    return json.dumps(v, sort_keys=True, ensure_ascii=False)


def _items(d, fields):
    out = []
    for i in (d.get("items") or []):
        if isinstance(i, dict):
            out.append(tuple(_n(i.get(f)) for f in fields))
    return out


def changed(new: dict, old: dict, scope: int) -> list:
    """回傳被改動的『項目名稱』清單（空＝沒改）。`scope` 見 SCOPE_*；未知值一律當成 ①（fail-closed）。"""
    new, old = new or {}, old or {}
    fields = ITEM_CORE if scope == SCOPE_ITEMS_MONEY else ITEM_CORE + ITEM_NOTE
    out = []
    if _items(new, fields) != _items(old, fields):
        out.append("items")
    for k in MONEY_KEYS + ALT_KEYS:
        if _n(new.get(k)) != _n(old.get(k)):
            out.append(k)
    if scope != SCOPE_ITEMS_MONEY:
        skip = PROCESS_KEYS | set(MONEY_KEYS) | set(ALT_KEYS) | {"items"}
        for k in sorted((set(new) | set(old)) - skip):
            if _n(new.get(k)) != _n(old.get(k)):
                out.append(k)
    return out


def body_keys(old: dict) -> set:
    """本文欄位目錄（被 ① 比對到的頂層鍵）；測試用來確認『本文欄位目錄 ⊆ 比對集合』。"""
    return set(old) - PROCESS_KEYS
