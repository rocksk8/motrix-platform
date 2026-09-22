# -*- coding: utf-8 -*-
"""§9 QL · 一份單據要印的「公司身分」。

🔴 **為什麼這一段不在 `pdf_gen.py` 裡**：
`pdf_gen.py` 不可以知道 `company_profile` 的地址結構
（`test_br2b_changing_the_address_shape_cannot_break_the_pdfs`）——
☠️ 把「地址資料長什麼樣」綁進 PDF 產生器之後，**改一次據點結構就會改到
所有單據**，而那種相依看不出來。
⇒ PDF 層問的是「**這份單的抬頭是什麼**」，不是「`company_profile` 裡有什麼鍵」。
"""
from db import get_db
from helpers.settings import _get_setting


# ══════════════════════════════════════════════════════════════════════════════
# §9 QL · 單據抬頭從「據點」取值
# ══════════════════════════════════════════════════════════════════════════════
#
# 使用者 2026-09-22：「在地址的部分可增加複數選項，由使用者新增名稱跟位置，
# 我們有分公司」⇒ 分公司開的單，抬頭與匯款帳號要是分公司自己的。
#
# 🔴 為什麼一次改 8 種，不是先改報價單：
#    這 8 種的抬頭是**同一個模式的 32 行複製**。只改一部分的話，
#    ☠️ **同一個案子的報價單與請款單會印不同抬頭** ——
#    🔑 而那種不一致沒有任何地方會報錯，它只會印在寄給客戶的紙上。
#
# 🔑 **落空的順序是逐欄，不是整筆**（QL5）：
#    這一筆據點的欄 → 主要據點的同一欄 → `company_profile` 的同一欄 → 內建預設
#    ☠️ 「整筆有值就整筆用」會讓一個只想改銀行帳號的分公司，抬頭變成空白。
#
# ⚠️ **全部留空時要與改版前逐字相同**（QL6）——`DEFAULT_IDENTITY` 就是那組值，
#    它不是「範例資料」，它是**既有安裝的行為**。動它等於改所有人的單據。

#: 什麼都沒填時印的那一組 —— **改版前寫死在 32 行裡的值**。
DEFAULT_IDENTITY = {
    "company_name": "允碩整合集創股份有限公司",
    "company_name_en": "MOTRIX Synergy Integration Corp.",
    "tax_id": "60575481",
    "phone": "04-3610-6566",
    "email": "info@miactw.com",
    "bank_name": "",
    "bank_branch": "",
    "bank_account_name": "",
    "bank_account_number": "",
}

#: `company_profile` 頂層那幾個欄位的對照（既有安裝已經在用的鍵）。
_PROFILE_ALIASES = {
    "company_name": ("companyName", "company_name"),
    "company_name_en": ("companyNameEn", "company_name_en"),
    "tax_id": ("taxId", "tax_id"),
    "phone": ("phone",),
    "email": ("email",),
    "bank_name": ("bankName", "bank_name"),
    "bank_branch": ("bankBranch", "bank_branch"),
    "bank_account_name": ("bankAccountName", "bank_account_name"),
    "bank_account_number": ("bankAccountNumber", "bank_account_number"),
}


def _first_filled(*values):
    """第一個非空字串。**逐欄落空用的，不是「整筆有值就整筆用」**（QL5）。"""
    for value in values:
        text = str(value).strip() if value is not None else ""
        if text:
            return text
    return ""


def location_identity(location_id=None) -> dict:
    """一筆單據要印的公司身分。

    `location_id` 給 `None` ⇒ **主要據點**（`locations[0]`，QL8 明著要的行為）。
    找不到那個 id ⇒ 一樣落到主要據點 ——
    ⚠️ 不要丟例外：一張綁著已刪據點的舊單據**仍然要印得出來**，
    ☠️ 而印不出來的那一刻，使用者手上就只剩一張紙。
    """
    profile = _get_setting("company_profile", {}) or {}
    locations = profile.get("locations") or []
    primary = locations[0] if locations else {}
    here = primary
    if location_id:
        for item in locations:
            if str(item.get("id") or "") == str(location_id):
                here = item
                break

    out = {}
    for field, default in DEFAULT_IDENTITY.items():
        out[field] = _first_filled(
            here.get(field),
            primary.get(field),
            *[profile.get(alias) for alias in _PROFILE_ALIASES.get(field, ())],
            default)
    return out


def _location_of(payload) -> str:
    """這份單據屬於哪一個據點。回 `""` ⇒ 主要據點。

    ```
    ① payload 自己的 `locationId`     報價單表單直接送、測試也直接塞
    ② 用 `quoteNo` 去查 quotations    出貨單／三種憑單／完工單／結案報告
    ```
    🔴 **②不可以省。** `generate_pdf_bytes()` 這一族只 `SELECT data_json,…`，
    而 `location_id` 是**欄位不是 `data_json` 的鍵** ⇒ 少了②的話，
    ☠️ 8 支 builder 拿到的永遠是空字串，**每一份真實單據都印總公司抬頭**，
    🔑 而題目會全綠（測試自己塞 `locationId`）—— 接縫有，呼叫者沒有。

    ⚠️ 查不到就回 `""`，**不要丟例外**：一張單據印不出來比印錯抬頭更糟，
    而這裡最壞的情況是退回既有行為（主要據點）。
    """
    payload = payload or {}
    direct = str(payload.get("locationId") or "").strip()
    if direct:
        return direct
    quote_no = str(payload.get("quoteNo") or payload.get("quote_no") or "").strip()
    if not quote_no:
        return ""
    try:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT location_id FROM quotations WHERE quote_no=?",
                (quote_no,)).fetchone()
        finally:
            conn.close()
    except Exception:       # noqa: BLE001 —— 查不到就退回主要據點
        return ""
    return str((row["location_id"] if row else "") or "").strip()
