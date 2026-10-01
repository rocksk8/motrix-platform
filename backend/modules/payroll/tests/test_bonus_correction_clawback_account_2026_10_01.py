# -*- coding: utf-8 -*-
"""獎金更正（追回）— 追回應收科目無效 ⇒ 沖轉、重開、追回三張傳票**整組都不開**並回 notice（W4 低風險 #2）。
原行為：沖轉＋重開已開、追回傳票沒開 ⇒ 應付少一個追回額。正對照：科目有效時三張都開（既有測試也驗）。"""
import json

from modules.payroll import bonus_correction as bc
from modules.payroll.tests.test_bonus_correction_2026_09_30 import (  # noqa: F401
    people, _to_pending, _corr, _db, _q, needs_accounting)


def _set_receivable(code):
    c = _db()
    try:
        c.execute("INSERT OR REPLACE INTO system_settings(key, value_json) VALUES (?, ?)", (bc.CLAWBACK_RECEIVABLE_KEY, json.dumps(code)))
        c.commit()
    finally:
        c.close()


@needs_accounting
def test_invalid_clawback_account_opens_no_voucher_at_all(client, people):
    _set_receivable("9999")                                                         # 不存在的科目
    no = "MQ-BCR-CB1"
    cn, res = _to_pending(client, people, no, bc_s1=1000)                           # 原 5000 → 1000（追回 4000）
    c = _corr(cn)
    assert c["clawback_total"] == 4000
    assert (c["reversal_voucher_id"], c["rebook_voucher_id"], c["clawback_voucher_id"]) == (0, 0, 0)
    assert "追回應收科目有問題" in c["voucher_notice"] and "整組" in c["voucher_notice"]
    assert _q("SELECT COUNT(*) AS n FROM vouchers_all WHERE origin IN ('bonus_corr_reversal','bonus_corr_accrual','bonus_corr_clawback')"
              " AND summary LIKE ?", "%" + cn + "%")[0]["n"] == 0
    assert res["status"] == "已完成"                                                # 更正單本身照常往下走


@needs_accounting
def test_valid_clawback_account_still_opens_all_three(client, people):
    _set_receivable("1213")
    cn, _res = _to_pending(client, people, "MQ-BCR-CB2", bc_s1=1000)
    c = _corr(cn)
    assert c["reversal_voucher_id"] and c["rebook_voucher_id"] and c["clawback_voucher_id"] and not c["voucher_notice"]
