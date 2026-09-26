"""勞報單稅額計算的純函式（無 DB）。

（2026-09-26 自 tests/test_core.py 拆出：需要本模組在，隨模組搬走——反向控制（刪掉 modules/payroll、不帶 --continue-on-collection-errors）抓到模組層 import 讓整檔收集中斷，PLAYBOOK §B-11）
"""
import pytest

from modules.payroll.api.payslips import _calc, _get_tax_rules


# ── _calc (payslip tax) ───────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def rules():
    return _get_tax_rules()


class TestCalc:
    def test_resident_50_below_threshold(self, rules):
        # gross 50000 < resident 50 threshold 90501 → no withholding
        r = _calc(50_000, "50", "本國籍", False, rules)
        assert r["taxWithheld"] == 0
        assert r["taxRate"] == 0.0

    def test_resident_50_above_threshold(self, rules):
        # gross 100000 >= 90501 → 5%
        r = _calc(100_000, "50", "本國籍", False, rules)
        assert r["taxRate"] == 0.05
        assert r["taxWithheld"] == 5_000

    def test_resident_9A_above_threshold(self, rules):
        # gross 30000 >= 20010 → 10%
        r = _calc(30_000, "9A", "本國籍", False, rules)
        assert r["taxRate"] == 0.10
        assert r["taxWithheld"] == 3_000

    def test_non_resident_50_high_salary(self, rules):
        # 44250 > 29500*1.5=44250? no, 29500*1.5=44250, so 44251 → 18%
        r = _calc(44_251, "50", "外國籍（未滿183天）", False, rules)
        assert r["taxRate"] == 0.18

    def test_non_resident_50_low_salary(self, rules):
        # gross 29500 <= 44250 → low_salary_rate = 6%
        r = _calc(29_500, "50", "外國籍（未滿183天）", False, rules)
        assert r["taxRate"] == 0.06
        assert r["taxWithheld"] == 1_770  # floor(29500 * 0.06)

    def test_nhi_supplement_no_union(self, rules):
        # type 50, resident, no union, gross 50000 >= nhi threshold 29500
        r = _calc(50_000, "50", "本國籍", False, rules)
        assert r["nhiRate"] == 0.0211
        expected = round(50_000 * 0.0211)
        assert r["nhiSupplement"] == expected

    def test_nhi_supplement_has_union(self, rules):
        # has_union=True → no NHI supplement
        r = _calc(50_000, "50", "本國籍", True, rules)
        assert r["nhiRate"] == 0.0
        assert r["nhiSupplement"] == 0

    def test_net_amount(self, rules):
        # gross=100000, 5% tax=5000, nhi=round(100000*0.0211)=2110 → net=92890
        r = _calc(100_000, "50", "本國籍", False, rules)
        expected_net = 100_000 - r["taxWithheld"] - r["nhiSupplement"]
        assert r["netAmount"] == expected_net

    def test_nhi_below_threshold(self, rules):
        # gross 20000 < nhi threshold 29500 for type 50
        r = _calc(20_000, "50", "本國籍", False, rules)
        assert r["nhiSupplement"] == 0
