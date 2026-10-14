# -*- coding: utf-8 -*-
"""401 對帳檢查的發票合計進位（04 查證 10-14）：以前 tax401.py 用內建 round()（銀行家捨入），x.5 且 x 為偶數時比總帳（round_half_up）少 1，
只有對帳檢查 invoices_pretax／invoices_tax 會誤紅（申報數字不受影響）。改走 helpers.legal_params.round_half_up。"""
from modules.accounting.ledger import tax401 as T
from tests.platform import test_legal_amount_rounding_guard as G


def _legacy(inv, key):
    return sum(int(round(float(i.get(key) or 0))) for i in inv)


INV = [{"amountPretax": 1000.5, "taxAmount": 52.5}]


def test_half_amounts_round_half_up_like_the_ledger():
    assert T._invoice_sum(INV, "amountPretax") == 1001 and T._invoice_sum(INV, "taxAmount") == 53      # 總帳端 gl_events._i：1001／53


def test_mutation_control_the_old_builtin_round_disagrees_with_the_ledger():
    assert _legacy(INV, "amountPretax") == 1000 and _legacy(INV, "taxAmount") == 52                    # 修正前的口徑：兩邊差 1 ⇒ 檢查誤紅


def test_other_values_unchanged():
    inv = [{"amountPretax": "2000", "taxAmount": 100}, {"amountPretax": None}, {"amountPretax": 99.4, "taxAmount": 4.9}, {}]
    assert T._invoice_sum(inv, "amountPretax") == 2000 + 0 + 99 + 0 and T._invoice_sum(inv, "taxAmount") == 100 + 0 + 5 + 0
    assert T._invoice_sum([], "taxAmount") == 0


def test_the_file_is_in_the_money_scope_and_has_no_builtin_round():
    assert "modules/accounting/ledger/tax401.py" in G.MONEY_PY_FILES
    import re
    from pathlib import Path
    src = (Path(T.__file__)).read_text(encoding="utf-8")
    assert not re.search(r"(?<![\w.])round\(", src), "金額進位只能走 round_half_up"
