# -*- coding: utf-8 -*-
"""勞報單收款帳號遮蔽（稽核 F1，使用者裁示 2026-10-01：只有最高管理者看得到完整帳號，其餘一律遮蔽、沒有例外）。

規則同 `modules/subcontract/bank_mask.py`（模組之間不互相 import ⇒ 各留一份，測試逐案對照）：
- 遮蔽＝`****末四碼`（不是拿掉欄位：拿掉像「沒有帳號」）；勞報單 PDF 另外不帶存簿影本（影像上就印著帳號）。
- 寫入：遮蔽值被原樣送回 ⇒ **保留原值**；沒有原值可保留 ⇒ 拒絕（400），不可把 `****1234` 當成帳號存起來。
- 非最高管理者建單／改單時沒有（或只有遮蔽的）帳號 ⇒ 伺服器從外包名冊（`contractors`）取真值填進單據——真值只在伺服器內流動、不經過前端。
- 稽核／日誌不寫帳號全碼。
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
    return isinstance(v, str) and bool(_MASKED.match(v.strip()))


def mask_data(user, data: dict) -> dict:
    """就地遮蔽勞報單 `data`（dict）的收款帳號；最高管理者原樣。"""
    if can_see_full(user) or not isinstance(data, dict):
        return data
    if "bankAccountNumber" in data:
        data["bankAccountNumber"] = mask_number(data.get("bankAccountNumber"))
    return data


def resolve_on_write(conn, user, d: dict, old: dict, contractor_id, *, creating: bool):
    """寫入前處理 `d["bankAccountNumber"]`（就地）。回 None；不合規則 ⇒ ValueError（呼叫端轉 400）。

    - 送來的是遮蔽值：修改 ⇒ 沿用舊單的值（舊值也是遮蔽值或空白 ⇒ 拒絕）；新建 ⇒ 非最高管理者改走外包名冊取值，其餘拒絕。
    - 非最高管理者且帳號空白：修改 ⇒ 沿用舊單的值；新建 ⇒ 外包名冊取值（取不到就維持空白）。
    - 最高管理者送空白 ⇒ 就是空白（不自動補）。其餘（有人輸入完整新帳號）照常存。
    """
    new = d.get("bankAccountNumber")
    new_s = new if isinstance(new, str) else ("" if new is None else str(new))
    masked = is_masked_value(new_s)
    blank = not new_s.strip()
    if not masked and not (blank and not can_see_full(user)):
        return
    old_no = str((old or {}).get("bankAccountNumber") or "")
    if not creating and old_no and not is_masked_value(old_no):
        d["bankAccountNumber"] = old_no                         # 沿用舊單真值
        return
    if not can_see_full(user) and contractor_id:
        row = conn.execute("SELECT bank_account_number FROM contractors WHERE id=?", (contractor_id,)).fetchone()
        real = str((row["bank_account_number"] if row else "") or "")
        if real and not is_masked_value(real):
            d["bankAccountNumber"] = real                       # 伺服器端取值：真值不經過前端
            return
        d["bankAccountNumber"] = ""
        return
    if masked:
        raise ValueError("收款帳號是遮蔽值（****末四碼），不可寫入；請輸入完整帳號，或留空")
    d["bankAccountNumber"] = ""
