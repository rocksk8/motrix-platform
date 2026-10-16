# -*- coding: utf-8 -*-
"""T69 設定群組：刪除暫存區保留天數（recycle_bin.retention_days）。

[單位] helper:settings_groups_recycle_bin    [層] L1    [穩定度] 實驗
[公開介面] （無）
[不變式] 只決定『之後刪除的項目』在暫存區放幾天才自動永久清除；預設 30（＝上線前寫死的 `helpers.recycle_bin.RETENTION_DAYS`，那個常數保留當後備值）。
    下限 7、上限 365。縮短＝放寬（更快永久刪除，無法找回）：確認期間後才生效，且需另一位最高管理者核准；延長立即生效。
    已在暫存區的項目，到期時間（purge_after）在刪除當下就定了，改設定不回頭改寫。
[契約題] backend/modules/recyclebin/tests/test_recyclebin_retention_t69.py
"""


def _register(S, _register_core):
    _register_core(
        "recycle_bin", "刪除暫存區",
        [
            S("retention_days", "int", 30, min=7, max=365, unit="天", risk="legal", loosen="down", recommended=30,
              risk_text="縮短後，之後被刪除的單據會更早被永久清除、無法復原；若事後才發現誤刪，可能已經找不回來。",
              question="被刪除的單據要在「刪除暫存區」放幾天，才自動永久清除？", label="暫存區保留天數（7～365）",
              help="被刪除的單據（含附件）先放在暫存區，這段時間內最高管理者可以還原；超過天數就永久清除。最少 7 天，避免誤設成太短而立刻清空。",
              impact="只影響設定生效之後才被刪除的單據；已經在暫存區的項目到期日不變。縮短會讓之後的刪除項目更早永久消失，所以縮短須另一位最高管理者核准並等確認期間；延長則立即生效。",
              impact_scope={"documents": ["之後送進刪除暫存區的單據與附件"], "roles": ["最高管理者"], "amounts": "不直接涉及金額；但被永久清除的單據無法再還原。", "reversible": False, "effective": "pending"}),
        ],
        sensitive=False, risk="legal",
        help="被刪除的單據在刪除暫存區放多久。隔離資料夾的位置不在這裡設定（在刪除暫存區頁面）。",
    )
