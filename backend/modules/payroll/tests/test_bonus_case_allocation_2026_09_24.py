"""獎金分潤（以案件為中心）的分配算式（SPEC-BONUS §11.2／§11.6／§11.7）。"""
import pytest

from modules.payroll.bonus_case import BonusCalcError, DEFAULT_RATE_BP, DEFAULT_SPLIT_BP, allocate, pool_amount


def _p(*names, bp=None):
    return [{"username": n, "person_bp": (bp[i] if bp else None)} for i, n in enumerate(names)]


def test_spec_example_net_100():
    """§11.6：淨利 100、10%、50/30/20、業務 1／專案 2／後勤 3 ⇒ 逐一斷言。"""
    r = allocate(100, DEFAULT_RATE_BP, DEFAULT_SPLIT_BP,
                 {"sales": _p("s1"), "project": _p("p1", "p2"), "admin": _p("a1", "a2", "a3")})
    assert r["pool"] == 10
    c = r["categories"]
    assert c["sales"]["amount"] == 5 and [l["amount"] for l in c["sales"]["lines"]] == [5]
    assert c["project"]["amount"] == 3 and [l["amount"] for l in c["project"]["lines"]] == [1, 1]
    assert c["admin"]["amount"] == 2 and [l["amount"] for l in c["admin"]["lines"]] == [0, 0, 0]
    assert r["paid_total"] == 7 and r["remainder"] == 3


def test_average_is_equal_and_remainder_to_company():
    """§11.7：「每人一樣多，零頭留公司」。類金額 30000／7 人 ⇒ 每人 4285，零頭 5 留公司。"""
    r = allocate(1_000_000, 1000, DEFAULT_SPLIT_BP, {"project": _p(*[f"u{i}" for i in range(7)])})
    lines = r["categories"]["project"]["lines"]
    assert {l["amount"] for l in lines} == {4285}
    assert r["categories"]["project"]["mode"] == "average"
    assert r["remainder"] == 100_000 - 7 * 4285


def test_custom_person_ratio_uses_spec_formula():
    """改過個人比例：每人 floor(獎金池 × 類比例 × 個人比例)。"""
    r = allocate(123_457, 1000, DEFAULT_SPLIT_BP, {"sales": _p("a", "b", bp=[3333, 6667])})
    pool = 12_345
    assert r["pool"] == pool
    assert [l["amount"] for l in r["categories"]["sales"]["lines"]] == [
        pool * 5000 * 3333 // 10**8, pool * 5000 * 6667 // 10**8]


def test_empty_category_is_not_paid():
    r = allocate(100_000, 1000, DEFAULT_SPLIT_BP, {"sales": _p("s")})
    assert r["categories"]["admin"]["mode"] == "none" and r["categories"]["admin"]["lines"] == []
    assert r["remainder"] == 10_000 - 5_000


def test_per_case_rate_and_split_override():
    r = allocate(10_000, 1500, {"sales": 6000, "project": 4000, "admin": 0},
                 {"sales": _p("s"), "project": _p("p"), "admin": _p("a")})
    assert r["pool"] == 1500
    assert [r["categories"][c]["lines"][0]["amount"] for c in ("sales", "project", "admin")] == [900, 600, 0]


def test_decimal_net_profit_is_floored_without_float_error():
    assert pool_amount("12345.67", 1000) == 1234
    assert pool_amount(0.3, 10000) == 0      # 0.3 × 100% ⇒ floor 0，不會因為浮點變成 0.29999…


@pytest.mark.parametrize("net", [0, -1, "-5.5"])
def test_non_positive_net_profit_rejected(net):
    with pytest.raises(BonusCalcError, match="不大於 0"):
        pool_amount(net, 1000)


@pytest.mark.parametrize("split", [{"sales": 5000, "project": 3000, "admin": 1000},
                                   {"sales": 5000, "project": 3000, "admin": 2001}])
def test_split_must_sum_to_100(split):
    with pytest.raises(BonusCalcError, match="合計必須是 100%"):
        allocate(1000, 1000, split, {})


def test_custom_person_ratio_must_sum_to_100():
    with pytest.raises(BonusCalcError, match="個人比例合計"):
        allocate(1000, 1000, DEFAULT_SPLIT_BP, {"sales": _p("a", "b", bp=[5000, 4000])})


def test_mixed_average_and_custom_rejected():
    with pytest.raises(BonusCalcError, match="全部平均"):
        allocate(1000, 1000, DEFAULT_SPLIT_BP,
                 {"sales": [{"username": "a", "person_bp": 5000}, {"username": "b", "person_bp": None}]})


@pytest.mark.parametrize("bad", [True, 1.5, -1, 10001, "1000"])
def test_rate_must_be_integer_bp(bad):
    with pytest.raises(BonusCalcError):
        pool_amount(1000, bad)


def test_duplicate_person_in_category_rejected():
    with pytest.raises(BonusCalcError, match="重複"):
        allocate(1000, 1000, DEFAULT_SPLIT_BP, {"sales": _p("a", "a")})
