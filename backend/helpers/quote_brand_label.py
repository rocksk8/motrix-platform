# -*- coding: utf-8 -*-
"""報價單品項表欄名可自訂（2026-11-17 使用者裁示）：「品名 / 規格說明」與「廠牌 / 型號」兩欄。

報價人可在每張單自由輸入欄名（有常用選項，也可自己打字）。欄名存在單據本身
（`data_json.columnLabels = {"item": "…", "brand": "…"}`，只存有改的欄）；沒有這個鍵、某欄空白、
或與該欄預設名稱相同 ⇒ 一律視為「沒改」＝預設名稱（舊單行為與 PDF 不變）。日後要擴充欄位：在 `COLUMNS` 加一列即可。

- `normalize(col, raw)`  任意輸入 → 已清理的自訂欄名；空白／與預設相同／不是字串 ⇒ ''
- `sanitize(q)`          就地清理 `q["columnLabels"]`（寫入單據前呼叫；只留認得的欄、清理後空的欄與整個物件都移除）
- `label_of(q, col)`     這張單該欄實際要顯示的名稱（沒自訂 ⇒ 預設）
- `change_reasons(q)`    簽核依據用的文字（每個被改的欄一行；沒變更 ⇒ []）：「欄名已由「廠牌 / 型號」變更為「○○」」

目前只有「報價單」套用；估價單（共用同一個範本與表單）暫不跟進——要跟進時只改 `APPLIES_TO`。
輸出到 HTML 的地方一律自己 esc（PDF 用 pdf_gen.esc；前端用 x-text／textContent）。

[單位] helper:quote_brand_label    [層] L1    [穩定度] 契約
[公開介面] APPLIES_TO, COLUMNS, KEY, MAX_LEN, applies, change_reasons, default_of, label_of, labels_of, normalize, presets_of, sanitize
"""
import re

from helpers import doc_type as _DT

KEY = "columnLabels"
MAX_LEN = 20                                   # 字元數上限（表頭很窄；超過就截斷，不拒收，避免存檔被擋）
#: 欄代號 → (預設名稱, 常用選項)。預設名稱就是今天寫死在表頭的字；常用選項前端下拉用同一份（quotation-form.html 的 COLUMN_LABEL_*）。
COLUMNS = {
    "item":  ("品名 / 規格說明", ("品名 / 規格說明", "品名", "品項", "項目", "規格說明")),
    "brand": ("廠牌 / 型號", ("料號", "型號", "規格", "廠牌 / 型號")),
}
APPLIES_TO = frozenset({_DT.QUOTE})            # 哪些單據類型套用自訂欄名

_CTRL_RE = re.compile(r"[\x00-\x1f\x7f​-‏  ﻿]")
_WS_RE = re.compile(r"\s+")


def applies(doc_type) -> bool:
    return _DT.norm(doc_type) in APPLIES_TO


def default_of(col: str) -> str:
    return COLUMNS[col][0]


def presets_of(col: str) -> tuple:
    return COLUMNS[col][1]


def normalize(col: str, raw) -> str:
    """清理自訂欄名：非字串、空白、與該欄預設相同 ⇒ ''。換行／tab 壓成空格、去其餘控制字元與零寬字元、頭尾去空白、截斷到 MAX_LEN。"""
    if col not in COLUMNS or not isinstance(raw, str):
        return ""
    s = _CTRL_RE.sub("", _WS_RE.sub(" ", raw)).strip()[:MAX_LEN].strip()      # 先壓空白再去控制字元（反過來會把換行直接吃掉、兩個字黏在一起）
    return "" if s == default_of(col) else s


def sanitize(q: dict) -> None:
    """就地清理 q 裡的欄名物件。不適用的單據類型（估價單）、非物件、沒有任何有效欄 ⇒ 整個鍵移除，免得直接打 API 也寫得進去。"""
    if not isinstance(q, dict) or KEY not in q:
        return
    raw = q.get(KEY)
    clean = {}
    if applies(q.get("docType")) and isinstance(raw, dict):
        for col in COLUMNS:
            s = normalize(col, raw.get(col))
            if s:
                clean[col] = s
    if clean:
        q[KEY] = clean
    else:
        q.pop(KEY, None)


def label_of(q, col: str) -> str:
    """這張單該欄要顯示的名稱。沒自訂／不適用 ⇒ 預設。"""
    if not isinstance(q, dict) or not applies(q.get("docType")):
        return default_of(col)
    raw = q.get(KEY)
    return normalize(col, raw.get(col) if isinstance(raw, dict) else None) or default_of(col)


def labels_of(q) -> dict:
    return {col: label_of(q, col) for col in COLUMNS}


def change_reasons(q) -> list:
    """送簽註記（寫進 approval.reasons，簽核畫面與簽核紀錄都讀它）；每個被改過的欄一行，欄名沒變 ⇒ []。"""
    out = []
    for col in COLUMNS:
        lab = label_of(q, col)
        if lab != default_of(col):
            out.append(f"欄名已由「{default_of(col)}」變更為「{lab}」")
    return out
