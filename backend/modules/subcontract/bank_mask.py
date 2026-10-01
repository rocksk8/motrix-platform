# -*- coding: utf-8 -*-
"""承攬商／承攬人員收款帳號遮蔽（使用者裁示 2026-10-01：只有最高管理者看得到完整帳號，其餘一律遮蔽）。

- 遮蔽＝換成字串 `****末四碼`（不是拿掉欄位：拿掉像「沒有帳號」）；存簿影本（影像上就印著帳號）同樣只給最高管理者，
  其他人只回「有沒有」旗標。
- 寫入：遮蔽值被原樣送回（編輯表單載入遮蔽值再存檔）⇒ **保留原值**，不可把真帳號覆蓋成 `****1234`。
- 稽核／日誌不寫帳號全碼。
設計參照 W3 `modules/payroll/bank_account.py`（`****末四碼`）；差別：這裡沒有「本人」「出納／財務」例外——裁示只有最高管理者。
"""
import re

MASK_PREFIX = "****"
_MASKED = re.compile(r"^\*{3,}\d{0,4}$")


def can_see_full(user) -> bool:
    return bool(user) and user.get("role") == "superadmin"


def mask_number(number) -> str:
    n = str(number or "")
    return "" if not n else (MASK_PREFIX + n[-4:] if len(n) > 4 else MASK_PREFIX)


def is_masked_value(v) -> bool:
    """前端把遮蔽值原樣送回（沒改這個欄位）。"""
    return isinstance(v, str) and bool(_MASKED.match(v.strip()))


def number_for(user, number) -> str:
    return str(number or "") if can_see_full(user) else mask_number(number)


def mask_record(user, rec: dict, number_keys=("bankAccountNumber", "bank_account_number"),
                image_keys=("bankPassbookImage", "bank_passbook_image")) -> dict:
    """就地遮蔽一筆（dict）：帳號 ⇒ ****末四碼；存簿影像 ⇒ 清空（旗標由呼叫端自己的 hasPassbook 提供）。最高管理者原樣。"""
    if can_see_full(user) or not isinstance(rec, dict):
        return rec
    for k in number_keys:
        if k in rec:
            rec[k] = mask_number(rec.get(k))
    for k in image_keys:
        if k in rec and rec[k]:
            rec[k] = ""
    return rec
