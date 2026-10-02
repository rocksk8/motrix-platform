# -*- coding: utf-8 -*-
"""分期金額規則 `remit_split.plan`（31-B S1；使用者裁示 D3 比例或固定金額、D4 逐期算最後一期補到與整筆一致）。純函式題，不碰資料庫。
RK7：最後一期取剩餘額（補尾差）、稅額逐期算最後一期補到與整筆一致（各期稅額合計恆等於整筆稅額）、超額／超過 100%／非整數元一律拒絕。
反向控制：把『最後一期補差』換成逐期算 ⇒ 合計不再等於整筆稅額（見 test_rk7_reverse_control）。"""
import random
from decimal import Decimal

import pytest

from helpers.legal_params import round_half_up
from modules.subcontract import remit_split as RS


def _run(T, r, steps):
    """steps＝[("ratio", p) | ("amount", a)…] ⇒ 逐期累加，回每期結果。"""
    prev, out = [], []
    for mode, v in steps:
        res = RS.plan(T, r, prev, mode, v)
        out.append(res)
        prev.append({"pretax": res["pretax"], "tax": res["tax"], "ratio": float(v) if mode == "ratio" else None})
    return out


# ── worked examples（設計 §4）──────────────────────────────────────────

def test_rk7_example_three_thirds_leaves_no_yuan_and_makes_up_the_tax():
    res = _run(100, 0.05, [("ratio", "0.3333"), ("ratio", "0.3333"), ("ratio", "0.3334")])
    assert [x["pretax"] for x in res] == [33, 33, 34]                     # 最後一期取剩餘額
    assert [x["tax"] for x in res] == [2, 2, 1]                           # 33×5%=1.65→2、2、最後一期 5−4=1（逐期算本是 round(34×5%)=2 ⇒ 補差 −1）
    assert [x["is_last"] for x in res] == [False, False, True]
    assert res[2]["make_up"] == -1 and res[2]["total_tax"] == 5 and res[2]["tax_sum_after"] == 5 and res[2]["remaining_after"] == 0
    assert "補差" in res[2]["warnings"][0] and "待會計確認" in res[2]["warnings"][0]
    assert res[0]["make_up"] == 0 and res[0]["tax_sum_after"] == 2


def test_rk7_example_thirty_thirty_forty_has_no_make_up():
    res = _run(100000, 0.05, [("ratio", "0.3"), ("ratio", "0.3"), ("ratio", "0.4")])
    assert [x["pretax"] for x in res] == [30000, 30000, 40000] and [x["tax"] for x in res] == [1500, 1500, 2000]
    assert all(x["make_up"] == 0 for x in res) and res[2]["is_last"] and not res[2]["warnings"]


def test_rk7_mixed_ratio_and_fixed_amount_in_one_dispatch():
    res = _run(1000, 0.05, [("amount", 333), ("ratio", "0.3"), ("amount", 367)])
    assert [x["pretax"] for x in res] == [333, 300, 367] and res[2]["is_last"]            # 固定 367 剛好等於剩餘額 ⇒ 最後一期
    assert sum(x["tax"] for x in res) == 50                                                  # 整筆稅額 1000×5%
    # 比例期＋固定期混用時，累計比例用『比例期的 p、固定期的 A/T』
    r2 = _run(1000, 0.05, [("amount", 400), ("ratio", "0.6")])
    assert r2[1]["is_last"] and r2[1]["pretax"] == 600 and r2[1]["cum_ratio"] == pytest.approx(1.0)


def test_rk7_ratio_that_rounds_short_of_the_remainder_still_closes_when_cumulative_reaches_100_percent():
    res = _run(101, 0.05, [("ratio", "0.5"), ("ratio", "0.5")])                            # round(101×0.5)=51（half-up）；剩餘 50
    assert res[0]["pretax"] == 51 and res[1]["pretax"] == 50 and res[1]["is_last"]
    assert sum(x["tax"] for x in res) == int(round_half_up(101, 0.05))


def test_rk7_zero_rate_all_periods_zero_tax():
    res = _run(1000, 0, [("ratio", "0.4"), ("ratio", "0.6")])
    assert [x["tax"] for x in res] == [0, 0] and res[1]["total_tax"] == 0


def test_rk7_near_complete_hint_when_one_yuan_remains_but_cumulative_ratio_is_short():
    res = RS.plan(100, 0.05, [{"pretax": 33, "tax": 2, "ratio": 0.33}], "ratio", "0.66")   # 累計 99%、A=66、剩餘 67 ⇒ 差 1 元
    assert res["pretax"] == 66 and not res["is_last"] and res["near_complete"] and "再填一期" in res["warnings"][0]


# ── 驗證 ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("args,needle", [
    ((1000.5, 0.05, [], "amount", 100), "整數元"),
    ((0, 0.05, [], "amount", 100), "大於 0"),
    ((1000, 1, [], "amount", 100), "稅率"),
    ((1000, -0.1, [], "amount", 100), "稅率"),
    ((1000, 0.05, [], "weird", 100), "輸入方式"),
    ((1000, 0.05, [], "amount", 0), "至少 1 元"),
    ((1000, 0.05, [], "amount", 12.5), "整數元"),
    ((1000, 0.05, [], "amount", 1001), "超過剩餘額度"),
    ((1000, 0.05, [], "ratio", 0), "大於 0"),
    ((1000, 0.05, [], "ratio", 1.01), "大於 0 且不超過 100%"),
    ((1000, 0.05, [{"pretax": 700, "tax": 35, "ratio": 0.7}], "ratio", "0.4"), "超過 100%"),
    ((1000, 0.05, [{"pretax": 1000, "tax": 50, "ratio": 1}], "amount", 1), "已經全部申請完"),
    ((10, 0.05, [], "ratio", "0.01"), "不到 1 元"),
    ((1000, 0.05, [], "amount", "abc"), "不是數字"),
    ((1000, 0.05, [{"pretax": 0, "tax": 0}], "amount", 1), "正整數"),
])
def test_rk7_rejections(args, needle):
    with pytest.raises(RS.RemitSplitError) as e:
        RS.plan(*args)
    assert needle in str(e.value), str(e.value)


def test_rk7_voided_periods_are_simply_not_passed_in_so_the_room_comes_back():
    res = RS.plan(1000, 0.05, [{"pretax": 400, "tax": 20, "ratio": None}], "amount", 600)
    assert res["is_last"] and res["tax"] == 30 and res["remaining_before"] == 600


# ── 性質（亂數）：合計恆等於 T 與 X ─────────────────────────────────────

def test_rk7_property_pretax_sums_to_T_and_tax_sums_to_X_for_random_schedules():
    """隨機排程（全比例分割、或全固定金額分割）：最後一期一定收尾，稅前合計＝T、稅額合計＝整筆稅額 X。"""
    rnd = random.Random(20261002)
    closes = 0
    for n in range(500):
        T = rnd.randint(10_000, 5_000_000)
        r = rnd.choice([0, 0.05, 0.1, 0.03])
        parts = rnd.randint(1, 6)
        if rnd.random() < 0.5:
            cuts = sorted(rnd.sample(range(1, 10000), parts - 1)) if parts > 1 else []
            ps = [b - a for a, b in zip([0] + cuts, cuts + [10000])]                     # 4 位小數的比例，加總剛好 100%
            steps = [("ratio", "%.4f" % (p / 10000)) for p in ps]
        else:
            cuts = sorted(rnd.sample(range(1, T), parts - 1)) if parts > 1 else []
            steps = [("amount", b - a) for a, b in zip([0] + cuts, cuts + [T])]
        res = _run(T, r, steps)
        assert [x["is_last"] for x in res] == [False] * (len(res) - 1) + [True], (T, r, steps)
        assert sum(x["pretax"] for x in res) == T and sum(x["tax"] for x in res) == int(round_half_up(T, r)), (T, r, steps)
        assert all(x["pretax"] >= 1 and x["tax"] >= 0 for x in res)
        closes += 1
    assert closes == 500


def test_rk7_reverse_control_without_the_make_up_the_tax_sum_drifts_from_the_whole_amount():
    """若最後一期也逐期算（沒有補差），100 元三期的稅額合計是 2+2+2＝6 ≠ 整筆 5 ⇒ 證明補差規則有在作用。"""
    naive = [int(round_half_up(a, 0.05)) for a in (33, 33, 34)]
    assert sum(naive) == 6 and int(round_half_up(100, 0.05)) == 5
    assert sum(x["tax"] for x in _run(100, 0.05, [("ratio", "0.3333"), ("ratio", "0.3333"), ("ratio", "0.3334")])) == 5


def test_rk7_prior_tax_above_total_tax_does_not_block_the_last_period():
    """da S1：T=100、5%、X=5；前 9 期各 10 元每期稅 round(0.5)=1 ⇒ 前期稅 9 > 5（第 10 期為最後一期）。最後一期仍要開得出來：稅額取 0＋警示（不 raise）。"""
    res = _run(100, 0.05, [("amount", 10)] * 9 + [("amount", 10)])
    last = res[-1]
    assert last["is_last"] and last["remaining_after"] == 0 and last["tax"] == 0
    assert last["tax_sum_after"] == 9 and last["total_tax"] == 5
    assert "超過整筆稅額" in last["warnings"][0] and "待會計確認" in last["warnings"][0]
