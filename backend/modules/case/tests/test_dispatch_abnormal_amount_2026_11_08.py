# -*- coding: utf-8 -*-
"""精算：派發單品項金額是 NaN／Infinity／1e400 這類異常值時，`compute()` 不得丟例外（T77 殘留，T78 修）。

退化來源：`dispatch_rows(with_lines=True)` 對每張派發單都呼叫 `DL.lines_of()`，裡面的 `cents()` 對非有限數 `quantize` 會丟 InvalidOperation，
`compute()` 外層沒有 try/except ⇒ 整個案件的精算讀取／存檔／驗證／完結比對全部 500，跟這張派發單有沒有用逐行對應無關。
修法：異常值 ⇒ 這張派發單「只能整張對應」（與各行金額加總對不上總額時同一條降級路徑）；其他派發單、其他成本不受影響。
"""
import pytest

from modules.case import dispatch_lines as DL
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W  # noqa: F401
from modules.case.tests.test_settlement_dispatch_lines_2026_11_07 import _compute, _ldisp, _lines, _line, _set_items, _unassigned, _validate
from modules.case.tests._t40_won import quote_is_won  # noqa: F401  第 40 班：完結要已成案（autouse）

# json.dumps 會把 float nan／inf 寫成 NaN／Infinity（Python json 預設容許），讀回來是 float；字串形式則是 "NaN"／"Infinity"／"1e400"
ABNORMAL = [float("nan"), float("inf"), float("-inf"), "NaN", "Infinity", "-Infinity", "1e400", "1E999999", "9" * 400]


def _bad_dispatch(bad, which=1):
    """三行 1000／2000／3000（總額 6000），第 `which` 行（0 起算）金額換成異常值；總額欄維持正常的 6000。"""
    did, keys = _ldisp([1000, 2000, 3000])
    items = _lines([1000, 2000, 3000])
    items[which]["amount"] = bad
    _set_items(did, items)
    return did


@pytest.mark.parametrize("bad", ABNORMAL, ids=lambda b: repr(b)[:14])
def test_abnormal_line_amount_does_not_break_compute_and_falls_back_to_whole_dispatch(W, bad):
    good, _ = _ldisp([1000, 2000, 3000])                           # 另一張正常派發單：不得受影響
    did = _bad_dispatch(bad)
    d = _compute([])                                               # 不得丟例外
    ids = {x["itemId"] for x in d["unassigned"]["dispatches"]}
    assert str(good) in ids and str(did) in ids                    # 沒有對應 ⇒ 兩張都留在未對應（整張）
    view = {v["dispatchId"]: v for v in d["dispatchLines"]}         # 畫面檢視：異常的那張不可逐行（有原因），正常的照常
    assert view[str(did)]["linesOk"] is False and view[str(did)]["linesReason"] and all(not l["mappable"] for l in view[str(did)]["lines"])
    assert view[str(good)]["linesOk"] is True and all(l["mappable"] for l in view[str(good)]["lines"])
    assert d["totals"]["dispatchTotal"] > 0


@pytest.mark.parametrize("bad", ABNORMAL, ids=lambda b: repr(b)[:14])
def test_abnormal_dispatch_can_still_be_whole_assigned_and_normal_one_can_be_line_assigned(W, bad):
    good, keys = _ldisp([1000, 2000, 3000])
    did = _bad_dispatch(bad)
    d = _compute([{"kind": "dispatch", "ref": str(did), "itemId": "a"}, _line(good, keys[0], "b")])
    t = d["totals"]
    assert abs(t["dispatchAssignedTotal"] + t["dispatchUnassignedTotal"] - t["dispatchTotal"]) < 1e-6, t
    assert str(did) not in {x["itemId"] for x in d["unassigned"]["dispatches"]}      # 整張對應照舊有效
    assert not any(w["ref"] == str(good) and w["code"] == "dispatch_line_unmappable" for w in d["warnings"])
    # 正常那張的整行對應不受影響：未對應剩下另外兩行
    rem = [x for x in _unassigned(d, good)]
    assert rem and rem[0].get("partial") is True


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "1e400"], ids=lambda b: repr(b)[:10])
def test_line_mapping_to_an_abnormal_dispatch_is_ignored_with_a_warning_not_a_500(W, bad):
    did = _bad_dispatch(bad)
    key = DL.line_key(1730000000000.5 + 1.25)                      # 第 2 行的行鍵
    d = _compute([_line(did, key, "a")])                           # 逐行對應到異常派發單：忽略並警告，不丟例外
    assert str(did) in {x["itemId"] for x in d["unassigned"]["dispatches"]}
    assert any(w["code"] == "dispatch_line_unmappable" for w in d["warnings"]), d["warnings"]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "1e400"], ids=lambda b: repr(b)[:10])
def test_validate_offsets_does_not_raise_for_an_abnormal_dispatch(W, bad):
    did = _bad_dispatch(bad)
    key = DL.line_key(1730000000000.5 + 1.25)
    msg = _validate([_line(did, key, "a")])                        # 存檔／驗證路徑：給明確訊息（或視為無此行），不可丟例外
    assert msg is None or isinstance(msg, str)


def test_dispatch_lines_of_unit_abnormal_values_return_not_ok_and_never_raise():
    for bad in ABNORMAL:
        ld = DL.lines_of([{"id": 1, "amount": 100}, {"id": 2, "amount": bad}], 100, 0.05)
        assert ld["ok"] is False and ld["reason"] and all(not l["mappable"] for l in ld["lines"])
        ld = DL.lines_of([{"id": 1, "amount": 100}], bad, 0.05)
        assert ld["ok"] is False
    ld = DL.lines_of([{"id": 1, "amount": 100}], 100, float("nan"))               # 稅率異常也不丟
    assert ld["ok"] is False


def test_normal_dispatch_lines_of_is_unchanged():
    ld = DL.lines_of([{"id": 1, "amount": 100}, {"id": 2, "amount": "200.5"}], 300.5, 0.05)
    assert ld["ok"] is True and ld["totalCents"] == 30050 and [l["cents"] for l in ld["lines"]] == [10000, 20050]
