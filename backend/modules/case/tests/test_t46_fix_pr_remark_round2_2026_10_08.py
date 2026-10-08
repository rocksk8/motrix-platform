# -*- coding: utf-8 -*-
"""第 46 班第二輪修正（獨立稽核 S1／S2）：
S1 簽核佇列詳情不再把「費用歸屬單位」（參照欄，非金額）當金額類欄位藏掉——用**真實**差旅／零用金定義驗，不用假標籤。
S2 採購單／零用金的收款對象在表單上：不論 payee_type 是什麼、有沒有填 payee_name，都不能退回「申請人」的員工收款帳戶。"""
import pytest

from modules.case.tests.test_queue_detail_real_forms_2026_10_07 import (  # noqa: F401  (world 是 fixture)
    _approve_row, _db, _detail, _pending, _save, world)
from tests._requires import requires_module

pytestmark = requires_module("case", "額外支出在 M01")

_MAKE_USER_DEFAULT_ROLE = "superadmin"


@pytest.mark.parametrize("kind", ["travel", "petty_cash"])
def test_cost_dept_ref_field_is_shown_in_the_queue_detail(client, world, kind):
    d = _detail(client, world, _save(client, world, kind))
    f = {x["label"]: x["value"] for x in d["fields"]}
    assert f.get("費用歸屬單位") == "工務部", (kind, sorted(f))


def test_money_like_labels_are_still_hidden(client, world):
    from modules.case.api import quotations as Q
    for lab in ("金額", "單價", "預算上限", "報價單價", "小計"):
        assert lab in Q._MONEY_FIELD_LABELS or any(w in lab for w in Q._MONEY_LABEL_WORDS), lab
    assert "費用" in Q._MONEY_LABEL_WORDS, "文字欄「其他費用說明」之類仍過濾；只有 ref 型欄位（費用歸屬單位）免過濾（見 test_cost_dept_ref_field_is_shown…）"


def _set_payee(eid, **cols):
    c = _db()
    try:
        c.execute("UPDATE case_extra_expenses SET " + ", ".join("%s=?" % k for k in cols) + " WHERE id=?", [*cols.values(), eid])
        c.commit()
    finally:
        c.close()


@pytest.mark.parametrize("payee_type", ["", "employee", "vendor"])
@pytest.mark.parametrize("kind", ["purchase_order", "petty_cash"])
def test_form_payee_docs_never_offer_the_requesters_account(client, world, kind, payee_type):
    eid = _save(client, world, kind)
    _approve_row(eid)
    _set_payee(eid, payee_name="乙廠商", payee_type=payee_type)               # 有收款人名稱、沒有銀行資料——舊判斷會落到申請人帳號
    got = _pending(client, world["h"])[str(eid)]
    assert got["payeeUsername"] == "", (kind, payee_type, got["payeeUsername"])
    r = client.get("/api/cashier/pending-payables/case/%d/payee-bank" % eid, headers=world["h"])
    assert r.status_code == 200, r.text
    assert r.json()["source"] != "profile", "不得出現申請人的個人收款帳戶"
    from modules.case.payables import _payee_username
    c = _db()
    try:
        row = c.execute("SELECT * FROM case_extra_expenses WHERE id=?", (eid,)).fetchone()
        assert _payee_username(row) == ""
    finally:
        c.close()


def test_travel_still_uses_the_employee_account(client, world):
    eid = _save(client, world, "travel")
    _approve_row(eid)
    assert _pending(client, world["h"])[str(eid)]["payeeUsername"] == world["user"], "差旅（員工）照舊"


# ── S6：payable_calendar_resync 不建空庫 ───────────────────────────────

def _rs():
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "tools"))
    import payable_calendar_resync as RS
    return RS


def test_resync_missing_db_exits_2_and_creates_no_file(tmp_path, monkeypatch):
    RS = _rs()
    nope = tmp_path / "nope.db"
    with pytest.raises(SystemExit) as e:
        RS.main(["--db", str(nope)])
    assert e.value.code == 2 and not nope.exists()
    import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "default.db"))
    for argv in ([], ["--apply"]):
        with pytest.raises(SystemExit) as e2:
            RS.main(argv)
        assert e2.value.code == 2 and not (tmp_path / "default.db").exists(), argv
    assert list(tmp_path.iterdir()) == []


def test_resync_with_an_existing_db_still_works(client, capsys):
    RS = _rs()
    assert RS.main([]) == 0
    assert "dry-run" in capsys.readouterr().out
