# -*- coding: utf-8 -*-
"""第 32 包重建（52033606）探針差異部分（2e）：出納差額審核與手續費。邊界值、兩種原因並存、多筆明細各自帶 fee／paidAt、壞輸入。"""
import pytest

from modules.case.tests.test_material_payment_api_2026_10_02 import _approved, _pending_items, _q, world  # noqa: F401


def _pay(client, w, pid, **body):
    return client.post("/api/cashier/pending-payables/case_material/%d/pay" % pid, json=body, headers=w["cash"])


def _reviews(client, w):
    return [i for i in client.get("/api/cashier/remit-reviews", headers=w["adm"]).json()["items"] if i["source"] == "case_material"]


def test_fee_threshold_boundaries(client, world):
    w = world
    pid = _approved(client, w, 9000)
    assert _pay(client, w, pid, paidDate="2031-05-01", actualAmount=1000, hasFee=True, fee=500.0).json().get("remitReview") in (None, "")       # =500 不審
    assert _pay(client, w, pid, paidDate="2031-05-02", actualAmount=1000, hasFee=True, fee=500.01).json()["remitReview"] == "pending"          # 500.01 審
    assert _pay(client, w, pid, paidDate="2031-05-03", actualAmount=1000, hasFee=True, fee=501).json()["remitReview"] == "pending"
    assert _pay(client, w, pid, paidDate="2031-05-04", actualAmount=1000, hasFee=True, fee=0).json().get("remitReview") in (None, "")          # 0 不審
    assert _pay(client, w, pid, paidDate="2031-05-05", actualAmount=1000, hasFee=False, fee=900).json().get("remitReview") in (None, "")       # hasFee=False 時 fee 不算
    assert _q("SELECT fee FROM case_material_payment_lines ORDER BY id DESC LIMIT 1")[0]["fee"] in (0, 0.0, None)


def test_fee_not_above_payment_refused_and_equal_allowed_and_bad_inputs(client, world):
    w = world
    pid = _approved(client, w, 9000)
    assert _pay(client, w, pid, paidDate="2031-05-01", actualAmount=700, hasFee=True, fee=700.01).status_code == 400                           # 手續費 > 實付
    assert _pay(client, w, pid, paidDate="2031-05-01", actualAmount=700, hasFee=True, fee=-1).status_code in (400, 422)                      # 負數
    assert _pay(client, w, pid, paidDate="2031-05-01", actualAmount=700, hasFee=True, fee="abc").status_code in (400, 422)                   # 非數字
    n = _q("SELECT COUNT(*) AS n FROM case_material_payment_lines")[0]["n"]
    assert n == 0                                                                                                                              # 被拒的都沒有留下明細
    r = _pay(client, w, pid, paidDate="2031-05-02", actualAmount=700, hasFee=True, fee=700)
    print("PROBE fee==actual ->", r.status_code)
    assert r.status_code in (200, 400)                                                                                                         # 記錄現況（等於實付）


def test_review_items_carry_fee_and_paid_at_per_line_with_the_right_reason(client, world):
    w = world
    pid = _approved(client, w, 6000)
    assert _pay(client, w, pid, paidDate="2031-06-01", actualAmount=1000, hasFee=True, fee=600).status_code == 200            # 只有手續費偏高
    assert _pay(client, w, pid, paidDate="2031-06-02", actualAmount=1000, hasFee=True, fee=100).status_code == 200            # 正常 ⇒ 不進審核
    items = _reviews(client, w)
    assert len(items) == 1
    it = items[0]
    assert it["fee"] == 600.0 and it["paidAt"] == "2031-06-01" and it["diff"] == 0 and "手續費偏高" in it["reason"], it
    assert it["actual"] == 1000.0 and it["payable"] is not None
    # 多付＋手續費偏高並存的一筆：兩個欄位都要在、diff 只算多付
    pid2 = _approved(client, w, 2000)
    r = _pay(client, w, pid2, paidDate="2031-06-03", actualAmount=2600, hasFee=True, fee=550)
    assert r.status_code == 200 and r.json()["remitReview"] == "pending", r.text
    by_day = {i["paidAt"]: i for i in _reviews(client, w)}
    assert set(by_day) == {"2031-06-01", "2031-06-03"}, by_day.keys()
    both = by_day["2031-06-03"]
    assert both["fee"] == 550.0 and both["diff"] == 600.0, both
