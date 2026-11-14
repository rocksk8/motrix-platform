# -*- coding: utf-8 -*-
"""T87 修：款項明細裡的金額／比例不是數字（例如 "5x00"）時，應收帳齡與收款明細不可 500。

規則：壞掉的那一筆略過、記 warning，回應帶「有 N 筆資料格式異常未計入」；其餘款項照算。
三個出口（營運報表 ar-aging／B1 標準報表 ar-aging／自選條件報表「收款明細」）遇到同一批髒資料都回 200，
未收合計一致、異常筆數一致。乾淨資料的回應與過去逐鍵相同（沒有 dirtyCount）。
"""
import json

import pytest

from tests._requires import requires_module
from tests.test_std_reports_t87_2026_11_14 import _case, _login, _uid

pytestmark = requires_module("case", "本檔的題讀寫案件（報價單）資料並打應收帳齡端點")

_MAKE_USER_DEFAULT_ROLE = "superadmin"


@pytest.fixture()
def hdr(client, make_user):
    cred = make_user("dirty_sa", role="superadmin")
    import helpers.xlsx_out as X
    X._export_times.clear()
    return _login(client, *cred), _uid("dirty_sa")


def _ok_and_dirty(i):
    _case("DR-OK", i, "dirty_sa", pay=[
        {"type": "訂金", "amount": 50000, "received": False}, {"type": "尾款", "amount": 55000, "received": False}])
    _case("DR-BADAMT", i, "dirty_sa", pay=[
        {"type": "訂金", "amount": "5x00", "received": False}, {"type": "尾款", "amount": 55000, "received": False}])
    _case("DR-BADSECOND", i, "dirty_sa", pay=[
        {"type": "訂金", "amount": 1000, "received": False}, {"type": "尾款", "amount": "oops", "received": False}])
    _case("DR-BADPCT", i, "dirty_sa", pay=[
        {"type": "訂金", "pct": "abc", "received": False}, {"type": "尾款", "pct": 50, "received": False}])


def _three(client, h):
    a = client.get("/api/reports/ar-aging", headers=h)
    b = client.get("/api/std-reports/ar-aging", headers=h)
    c = client.get("/api/report-templates/payments/run", headers=h)
    return a, b, c


def test_same_dirty_data_gives_200_and_same_totals_everywhere(client, hdr):
    h, i = hdr
    _ok_and_dirty(i)
    a, b, c = _three(client, h)
    assert (a.status_code, b.status_code, c.status_code) == (200, 200, 200), (a.text[:200], b.text[:200], c.text[:200])
    aj, bj, cj = a.json(), b.json(), c.json()
    # 好的款項照算：DR-OK 50000＋55000；DR-BADAMT 的尾款 55000；DR-BADSECOND 的訂金 1000；DR-BADPCT 的尾款＝105000×50%
    expect = 50000 + 55000 + 55000 + 1000 + 52500
    assert aj["total"]["amount"] == expect and aj["total"]["count"] == 5
    assert bj["kpis"][0]["value"] == expect                                       # 與 /api/reports/ar-aging 同一個數字
    unrecv = sum(r["amount"] for r in cj["rows"] if r["state"] == "未收")
    assert unrecv == expect and len(cj["rows"]) == 5                              # 收款明細的未收＝同一批款項
    # 異常筆數一致，且回應裡有講
    assert aj["dirtyCount"] == 3 and bj["dirtyCount"] == 3
    assert "有 3 筆資料格式異常未計入" in aj["note"]
    assert any("有 3 筆資料格式異常未計入" in n for n in bj["notes"])
    assert any("有 3 筆資料格式異常未計入" in n for n in cj["notes"])
    assert not any(r["quoteNo"] == "DR-BADAMT" and r["type"] == "訂金" for r in cj["rows"])   # 壞的那一筆沒有出現


def test_cash_position_also_survives(client, hdr):
    h, i = hdr
    _ok_and_dirty(i)
    r = client.get("/api/reports/cash-position", headers=h)
    assert r.status_code == 200, r.text[:200]
    assert r.json()["ar"]["total"] == 213500


def test_clean_data_response_unchanged(client, hdr):
    h, i = hdr
    _case("DR-C1", i, "dirty_sa", pay=[{"type": "全額", "amount": 105000, "received": False}])
    a, b, c = _three(client, h)
    assert (a.status_code, b.status_code, c.status_code) == (200, 200, 200)
    assert "dirtyCount" not in a.json() and "dirtyCount" not in b.json()
    assert "資料格式異常" not in a.json()["note"]
    assert not any("資料格式異常" in n for n in b.json()["notes"] + c.json()["notes"])


def test_numeric_strings_are_converted_not_dropped(client, hdr):
    h, i = hdr
    _case("DR-STR", i, "dirty_sa", pay=[
        {"type": "訂金", "amount": "5000", "received": False}, {"type": "尾款", "amount": "1,250.5", "received": False}])
    a = client.get("/api/reports/ar-aging", headers=h).json()
    assert a["total"]["amount"] == pytest.approx(6250.5) and "dirtyCount" not in a


def test_bad_total_or_non_dict_item_or_received_dirty_item(client, hdr):
    h, i = hdr
    _case("DR-T", i, "dirty_sa", total="一百", pay=[{"type": "全額", "amount": 100, "received": False}])
    _case("DR-ND", i, "dirty_sa", pay=["垃圾", {"type": "尾款", "amount": 700, "received": False}])
    _case("DR-RCV", i, "dirty_sa", pay=[{"type": "訂金", "amount": "x", "received": True, "receivedAt": "2026-10-20"},
                                         {"type": "尾款", "amount": 300, "received": False}])
    _case("DR-NAN", i, "dirty_sa", pay=[{"type": "全額", "amount": float("inf"), "received": False}])
    a, b, c = _three(client, h)
    assert (a.status_code, b.status_code, c.status_code) == (200, 200, 200), (a.text[:200], b.text[:200], c.text[:200])
    aj = a.json()
    assert aj["total"]["amount"] == 700 + 300 and aj["dirtyCount"] == 4
    assert b.json()["dirtyCount"] == 4
    assert [r["amount"] for r in c.json()["rows"]] and sum(r["amount"] for r in c.json()["rows"] if r["state"] == "未收") == 1000


def test_template_excel_export_with_dirty_data(client, hdr):
    h, i = hdr
    _ok_and_dirty(i)
    r = client.get("/api/report-templates/payments/excel", headers=h)
    assert r.status_code == 200, r.text[:200]


def test_clean_pay_items_returns_same_list_when_clean():
    from modules.analytics.api import reports as R
    pay = [{"amount": 10, "pct": 50}, {"amount": 20, "pct": 50, "received": True, "actualAmount": 19, "feeAmount": 1}]
    t, pt, items, bad = R._clean_pay_items(100, 95, pay)
    assert items is pay and bad == set() and (t, pt) == (100, 95)
    t, pt, items, bad = R._clean_pay_items(None, None, [{"amount": "x"}])
    assert bad == {0} and items == [{"amount": 0, "pct": 0, "received": None}]


# ── 共同入口（helpers.tax_calc.payment_item_amounts／receipt_amounts／summarize_payment_items）──────────────

def _orig_amounts(total, pay_items, pretax=None, apply_tax_exempt=True):
    """修改前的 payment_item_amounts（逐字複本）：乾淨資料的回傳值必須與它逐位相同（含型別）。"""
    from helpers.legal_params import round_half_up
    if not pay_items:
        return []
    others = sum(p["amount"] if p.get("amount") is not None else round_half_up(total * (p.get("pct") or 0) / 100)
                 for p in pay_items[1:])
    out = []
    for idx, pi in enumerate(pay_items):
        if pi.get("amount") is not None:
            amt = pi["amount"]
        elif idx == 0:
            amt = int(total - others)
        else:
            amt = round_half_up(total * (pi.get("pct") or 0) / 100)
        if apply_tax_exempt and pi.get("taxExempt") and pretax and total:
            amt = round_half_up(amt * pretax / total)
        out.append(amt)
    return out


@pytest.mark.parametrize("total,pretax,pay", [
    (105000, 100000, [{"amount": 52500}, {"amount": 52500}]),
    (105000, 100000, [{"pct": 30}, {"pct": 70}]),
    (105000, 100000, [{"pct": 33.3}, {"pct": 33.3}, {"pct": 33.4}]),
    (105000, 100000, [{"amount": 50000, "taxExempt": True}, {"amount": 55000}]),
    (99999.5, None, [{"amount": 1000.5, "pct": None}, {"pct": 0}, {}]),
    (0, 0, [{"amount": 0}, {"pct": 50}]),
    (105000, 100000, [{"amount": 0}, {"amount": None, "pct": 25}]),
])
def test_payment_item_amounts_clean_data_is_bit_identical(total, pretax, pay):
    from helpers import payment_item_amounts
    for ex in (True, False):
        got, want = payment_item_amounts(total, pay, pretax, apply_tax_exempt=ex), _orig_amounts(total, pay, pretax, ex)
        assert got == want and [type(x) for x in got] == [type(x) for x in want]


def test_payment_item_amounts_never_raises_on_dirty_input(caplog):
    from helpers import payment_item_amounts
    pay = [{"amount": "5x00"}, {"amount": "1,000"}, {"pct": "abc"}, {"amount": float("nan")}, {"amount": True}]
    with caplog.at_level("WARNING"):
        got = payment_item_amounts("x", pay, "y")
    assert got == [0, 1000, 0, 0, 0]
    assert any("格式異常" in r.getMessage() for r in caplog.records)
    assert payment_item_amounts(None, [{"pct": 50}, {"pct": 50}]) == [0, 0]


def test_receipt_amounts_and_summary_survive_dirty_fee_and_actual():
    from helpers import receipt_amounts, summarize_payment_items
    assert receipt_amounts(1000, None, 0) == (1000.0, 1000.0, 0.0)             # 乾淨：與過去相同
    assert receipt_amounts(1000, 900, 100) == (900.0, 1000.0, 100.0)
    assert receipt_amounts(1000, "zz", "abc") == (1000.0, 1000.0, 0.0)         # 髒：當沒填
    s = summarize_payment_items(2000, [{"amount": 1000, "received": True, "feeAmount": "abc", "actualAmount": "zz"},
                                       {"amount": "5x00", "received": False}], None)
    assert s["receivableTotal"] == 1000 and s["feeTotal"] == 0 and s["items"][0]["actualAmount"] is None


# ── 所有 GET 無參數端點（報表／儀表板／出納／標準報表等）遇到同一批髒資料都不 500 ──────────────────────────

_PREFIXES = ("/api/reports", "/api/dashboard", "/api/std-reports", "/api/cashier", "/api/receiv", "/api/report-templates",
             "/api/quotations", "/api/cases", "/api/finance", "/api/case", "/api/ledger", "/api/payment")


def _sweep(client, h):
    import main
    from tests.platform import _response_keys as RK
    urls = sorted(u for k, u in RK.get_targets(main.app) if "{" not in k and u.startswith(_PREFIXES))
    assert len(urls) >= 40, "掃到的端點太少：%d（模組沒載入？）" % len(urls)
    bad = {}
    for u in urls:
        try:
            if client.get(u, headers=h).status_code >= 500:
                bad[u] = "5xx"
        except Exception as e:                                       # noqa: BLE001  TestClient 把未處理例外直接丟出來
            bad[u] = type(e).__name__ + ": " + str(e)[:80]
    return bad


def test_every_report_endpoint_survives_dirty_payment_items(client, hdr):
    h, i = hdr
    _case("DS-OK", i, "dirty_sa", pay=[{"type": "訂金", "amount": 50000, "received": True, "receivedAt": "2026-10-20"},
                                        {"type": "尾款", "amount": 55000, "received": False}])
    before = _sweep(client, h)
    _case("DS-BAD", i, "dirty_sa", pay=[
        {"type": "訂金", "amount": "5x00", "received": True, "receivedAt": "2026-10-20", "feeAmount": "abc", "actualAmount": "zz"},
        {"type": "尾款", "pct": "q", "received": False}])
    _case("DS-BAD2", i, "dirty_sa", pay=[
        {"type": "訂金", "amount": float("inf"), "received": True, "receivedAt": "2026-10-21", "feeAmount": True},
        {"type": "尾款", "amount": "1,000", "received": False}])
    after = _sweep(client, h)
    assert after == before == {} or set(after) <= set(before), "髒資料讓這些端點 500：%r" % {k: v for k, v in after.items() if k not in before}


# ── 第 1 筆沒填金額＝餘數：後面的壞筆不能被併進第 1 筆（h11 審查必修；應收只能偏小、不能偏大）────────────

def _ar_items(client, h, qno):
    j = client.get("/api/reports/ar-aging", headers=h).json()
    return j, {(it["type"]): it["amount"] for b in j["bands"] for it in b["items"] if it["quoteNo"] == qno}


def test_clean_control_remainder_first_item(client, hdr):
    h, i = hdr
    _case("RM-C", i, "dirty_sa", pretax=100000, total=100000,
          pay=[{"type": "訂金", "received": False}, {"type": "尾款", "pct": 50, "received": False}])
    j, got = _ar_items(client, h, "RM-C")
    assert got == {"訂金": 50000, "尾款": 50000} and "dirtyCount" not in j


def test_dirty_amount_after_remainder_item_does_not_inflate_first_item(client, hdr):
    h, i = hdr
    _case("RM-A", i, "dirty_sa", pretax=100000, total=100000,
          pay=[{"type": "訂金", "received": False}, {"type": "尾款", "amount": "5x00", "received": False}])
    j, got = _ar_items(client, h, "RM-A")
    assert got == {}                                    # 訂金（餘數）算不出來，也略過；不是 100000
    assert j["dirtyCount"] == 2 and j["total"]["amount"] == 0


def test_dirty_pct_after_remainder_item_does_not_inflate_first_item(client, hdr):
    h, i = hdr
    _case("RM-P", i, "dirty_sa", pretax=100000, total=100000,
          pay=[{"type": "訂金", "received": False}, {"type": "二期", "pct": 30, "received": False},
               {"type": "尾款", "pct": "20%", "received": False}])
    j, got = _ar_items(client, h, "RM-P")
    assert got == {"二期": 30000}                       # 訂金不是 70000；二期照算
    assert j["dirtyCount"] == 2


def test_dirty_fee_or_pct_with_valid_amount_does_not_poison_first_item(client, hdr):
    h, i = hdr
    _case("RM-F", i, "dirty_sa", pretax=100000, total=100000,
          pay=[{"type": "訂金", "received": False}, {"type": "尾款", "amount": 40000, "pct": "x", "feeAmount": "y", "received": False}])
    j, got = _ar_items(client, h, "RM-F")
    # 尾款金額有效，不受壞比例／手續費影響：照算，也不算壞資料；第 1 筆餘數＝100000−40000
    assert got == {"訂金": 60000, "尾款": 40000} and "dirtyCount" not in j


def test_pay_items_not_a_list_counts_as_one_bad_item(client, hdr):
    h, i = hdr
    _case("RM-L", i, "dirty_sa", pay={"oops": 1})
    j = client.get("/api/reports/ar-aging", headers=h)
    assert j.status_code == 200 and j.json().get("dirtyCount") == 1


def test_helper_forces_first_item_to_zero_when_remainder_is_undeterminable():
    from helpers import payment_item_amounts
    assert payment_item_amounts(100000, [{}, {"amount": "5x00"}]) == [0, 0]
    assert payment_item_amounts(100000, [{}, {"pct": 30}, {"pct": "20%"}]) == [0, 30000, 0]
    assert payment_item_amounts(100000, [{}, {"pct": 50}]) == [50000, 50000]                  # 乾淨：不變
    assert payment_item_amounts(100000, [{"amount": 10}, {"amount": "5x00"}]) == [10, 0]      # 第 1 筆有金額：不動
    assert payment_item_amounts(100000, [{}, {"amount": 40000, "pct": "x"}]) == [60000, 40000]  # 壞比例但金額有效：不動


def test_analytics_copy_and_l1_private_helpers_agree():
    """L1 `tax_calc` 與 analytics `reports` 各有一份同規則的轉換（L1 不外露，避免升核心版）——逐項比對，防止兩邊各自演進。"""
    from helpers import tax_calc as T
    from modules.analytics.api import reports as R
    vals = [None, "", "  ", 0, 5, -3, 1.5, "5000", " 12 ", "1,250.5", "5x00", "abc", "20%", "1e3", True, False, float("nan"),
            float("inf"), "inf", "nan", [], {}, (1,)]
    for v in vals:
        a, b = T._parse_money(v), R._num_or_bad(v)
        assert (a is T._MONEY_BAD) == (b is R._BAD), v
        if a is not T._MONEY_BAD:
            assert a == b and type(a) is type(b), v
        assert T._money(v) == R._money(v), v
    items = [{}, {"amount": "x"}, {"amount": 5, "pct": "x"}, {"pct": "x"}, {"pct": 5}, {"amount": None, "pct": "x"}, "垃圾", None, {"amount": ""}]
    for pi in items:
        assert T._amount_unknown(pi) == R._amount_unknown(pi), pi


def test_public_interface_of_l1_has_no_new_names():
    """新輔助函式不進 L1 公開介面（否則要升核心次版號、重錄快照）。"""
    from helpers import tax_calc as T
    assert not [n for n in dir(T) if n in ("parse_money", "money", "MONEY_BAD", "amount_unknown")]
    assert not {"parse_money", "money", "MONEY_BAD", "amount_unknown"} & set(T.__all__)


# ── 營運報表／營收／毛利共用的 reports._collect：款項項目不是物件（例如字串）⇒ 略過並計數，不 500 ────────────

def test_collect_skips_non_object_payment_items_and_counts_them(client, hdr):
    h, i = hdr
    _case("CL-OK", i, "dirty_sa", pay=[{"type": "全額", "amount": 105000, "received": True, "receivedAt": "2026-10-20"}])
    _case("CL-STR", i, "dirty_sa", pay=["垃圾", {"type": "尾款", "amount": 700, "received": False}], total=700, pretax=700)
    _case("CL-NONE", i, "dirty_sa", pay=[None, 5, {"type": "尾款", "amount": "5x00", "received": False}])
    from modules.analytics.api import reports as R
    d = R._collect("0000-01-01", "9999-12-31")
    assert d["dirtyCount"] == 4                                              # "垃圾"、None、5、"5x00"
    qs = {(it["quoteNo"], it["type"]) for it in d["allItems"]}
    assert ("CL-OK", "全額") in qs and ("CL-STR", "尾款") in qs
    assert not [q for q in qs if q[0] == "CL-NONE"]                          # 三筆全壞的案件沒有任何款項列
    for path in ("/api/reports/financial", "/api/std-reports/revenue", "/api/std-reports/gross-margin"):
        r = client.get(path, headers=h)
        assert r.status_code == 200, (path, r.text[:200])
    rev = client.get("/api/std-reports/revenue", headers=h).json()
    gm = client.get("/api/std-reports/gross-margin", headers=h).json()
    assert any("有 4 筆資料格式異常未計入" in n for n in rev["notes"]) and any("有 4 筆資料格式異常未計入" in n for n in gm["notes"])


def test_collect_clean_data_has_no_dirty_count_and_notes_unchanged(client, hdr):
    h, i = hdr
    _case("CL-C", i, "dirty_sa", pay=[{"type": "全額", "amount": 105000, "received": True, "receivedAt": "2026-10-20"}])
    from modules.analytics.api import reports as R
    assert "dirtyCount" not in R._collect("0000-01-01", "9999-12-31")
    for path in ("/api/std-reports/revenue", "/api/std-reports/gross-margin"):
        j = client.get(path, headers=h).json()
        assert "dirtyCount" not in j and not any("資料格式異常" in n for n in j["notes"])
