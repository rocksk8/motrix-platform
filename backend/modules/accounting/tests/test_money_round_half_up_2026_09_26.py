"""傳票匯出的四捨五入（M06 搬遷自 tests/ 同名檔）。

2026-09-26 自 `backend/tests/test_money_round_half_up_2026_09_26.py` 移入（PLAYBOOK §B-11：拿掉本模組時這些題跟著消失）。
"""



def test_accounting_voucher_line_rounds_half_up():
    """傳票匯出的借貸金額：10.5 ⇒ 11（舊：10）、12.5 ⇒ 13（舊：12）。accounting_export L251"""
    from modules.accounting.api.accounting_export import _voucher_line
    ln = _voucher_line("2026-01-01", "c", "s", "1101", "現金", 10.5, 12.5, "", "", "")
    assert (ln["debit"], ln["credit"]) == (11, 13)
    ln = _voucher_line("2026-01-01", "c", "s", "1101", "現金", 11.5, 0, "", "", "")      # 正對照
    assert (ln["debit"], ln["credit"]) == (12, 0)
