# -*- coding: utf-8 -*-
"""欄位可見求值（T64 F7 S1a：只有『天花板』查表；政策規則是 S2，這裡沒有）。

[單位] helper:field_policy    [層] L1    [穩定度] 實驗（沒有旗標、沒有路由；S1a 沒有任何出口呼叫它）
[公開介面] mask_flags, tier_allowed, visible, visible_many
[不變式] ①`visible(field_id, user)` ＝ 該欄位 `ceiling` 對應的**既有**角色函式的結果，一對一，不新增任何判斷、不複製任何角色集合
    （`financial_mask.quote_money_visible／money_visible／material_money_visible`、`auth.has_cashier_access`）；
    財務權限旗標 `finance_via_effective`（off／shadow／on）因此自動繼承，不會出現第二套答案。
    ②fail-closed：未知欄位、未知天花板、目錄或角色函式丟例外 ⇒ `False`（絕不因錯誤回 True）。
    ③`financial_mask` 不 import 本檔（避免環）；本檔只在呼叫當下才 import `financial_mask`／`auth`。
    ⑤`visible()` 回答的是**欄位自己的天花板層級**（報價單層級＝`quote_money_visible`），**不是出口的整套短路**：今天的出口（例：quotations.py 讀單）先看
    `money_visible(user)`——為真（例如持有 `cashier` 模組的工程師）就**整份不遮**，連報價單層級欄位也看得到；`visible('quote_item.cost', 該使用者)` 則為 False
    （比出口窄、fail-closed）。遷移出口時**必須保留出口的短路**：用 `mask_flags(user)["money"]` 判斷是否整份跳過遮蔽，再用 `keep_quote`／`keep_orders` 傳給 `mask_*`，
    不可改成逐欄位 `visible()` 取代短路（會讓這類帳號突然看不到，行為變更）。金標以 `test_exit_short_circuit_*` 釘住這個差異。
    ④資料相關的例外（例：本單簽核人可下載內部 PDF）不在這裡——`visible()` 只回答『使用者層級』，例外留在呼叫端（目錄以 `exceptions` 標示）。
設計：docs/platform/plans/T64-F7-S1-DESIGN.md §3（與 T64-F7-FIELD-POLICY-DESIGN.md 同目錄）。
[契約題] backend/tests/platform/test_field_policy_t65.py
"""
import logging

from helpers import field_catalog as FC

_log = logging.getLogger(__name__)


def tier_allowed(ceiling, user) -> bool:
    """天花板 → 既有角色函式（唯一的對映處）。未知天花板 ⇒ False。"""
    from helpers import financial_mask as FM
    from helpers import auth
    if ceiling == "quote_money":
        return bool(FM.quote_money_visible(user))
    if ceiling == "finance_money":
        return bool(FM.money_visible(user))
    if ceiling == "material_money":
        return bool(FM.material_money_visible(user))
    if ceiling == "cashier":
        return bool(auth.has_cashier_access(user))
    return False


def visible(field_id, user) -> bool:
    """這位使用者（使用者層級）看不看得到這個欄位。永不丟例外；不確定 ⇒ False。"""
    try:
        f = FC.by_id(field_id)
        if f is None:
            return False
        return tier_allowed(f["ceiling"], user)
    except Exception:                                       # noqa: BLE001 — fail-closed
        _log.warning("field_policy.visible failed for %r; treating as hidden", field_id, exc_info=True)
        return False


def visible_many(field_ids, user) -> dict:
    """一次算多個欄位：同一個天花板只問一次角色函式。⇒ {field_id: bool}。"""
    out, memo = {}, {}
    for fid in field_ids:
        try:
            f = FC.by_id(fid)
            if f is None:
                out[fid] = False
                continue
            c = f["ceiling"]
            if c not in memo:
                memo[c] = tier_allowed(c, user)
            out[fid] = memo[c]
        except Exception:                                   # noqa: BLE001 — fail-closed
            _log.warning("field_policy.visible_many failed for %r; treating as hidden", fid, exc_info=True)
            out[fid] = False
    return out


def mask_flags(user) -> dict:
    """給 `financial_mask.mask_*` 既有旗標參數用：`keep_quote`（報價單層級不遮）、`keep_orders`（叫料不遮）、`money`（財務層級可見）。
    任何一個算不出來 ⇒ 該旗標 False（＝遮）。"""
    flags = {}
    for name, ceiling in (("keep_quote", "quote_money"), ("keep_orders", "material_money"), ("money", "finance_money")):
        try:
            flags[name] = tier_allowed(ceiling, user)
        except Exception:                                   # noqa: BLE001 — fail-closed
            _log.warning("field_policy.mask_flags failed for %s; masking", ceiling, exc_info=True)
            flags[name] = False
    return flags
