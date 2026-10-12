# -*- coding: utf-8 -*-
"""擇一方案報價的設定讀取（M3；T57）。所有數值、文字範本與回簽政策 P1～P8 都在設定中心群組 `quote_alt`（`helpers/settings_groups.py`），
這裡只是唯一的讀取入口：程式裡不放業務常數。

- `setting(key)`：讀一個欄位（設定中心的有效值；讀不到一律回程式預設，永不丟例外）。
- `policy(key)`：讀回簽政策代碼（整數，第一項＝預設＝最嚴）。**『尚未提供』的選項即使被寫進資料庫也一律夾回預設**（`UNAVAILABLE_ALT_CHOICES`），
  實作尚未存在的放寬路徑不可能因設定值而被走到。
"""
from helpers import settings_registry as sr
from helpers.settings_groups import UNAVAILABLE_ALT_CHOICES

GROUP = "quote_alt"
POLICY_KEYS = ("lock_scope", "cancel_after_deal", "move_out_of_sent", "reject_final_keep", "unlock_edit_signed",
               "approval_basis", "cancel_after_export", "cancel_after_invoice", "cancel_after_settle")


def setting(key, conn=None):
    return sr.get(GROUP, key, conn=conn)


def policy(key, conn=None) -> int:
    if key not in POLICY_KEYS:
        raise KeyError("不是回簽政策：%r" % (key,))
    v = sr.get(GROUP, key, conn=conn)
    if v in UNAVAILABLE_ALT_CHOICES.get(key, ()):
        return 1
    return v
