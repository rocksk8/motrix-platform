# -*- coding: utf-8 -*-
"""精算：派發單品項金額是 NaN／Infinity／1e400 這類異常值時，`compute()` 不得丟例外（T77 殘留，T78 修）。

退化來源：`dispatch_rows(with_lines=True)` 對每張派發單都呼叫 `DL.lines_of()`，裡面的 `cents()` 對非有限數 `quantize` 會丟 InvalidOperation，
`compute()` 外層沒有 try/except ⇒ 整個案件的精算讀取／存檔／驗證／完結比對全部 500，跟這張派發單有沒有用逐行對應無關。
修法：異常值 ⇒ 這張派發單「只能整張對應」（與各行金額加總對不上總額時同一條降級路徑）；其他派發單、其他成本不受影響。
"""
import json

import pytest

import db
from core import registry
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


# ── 第二個來源：subcontract 派發列提供者（總額欄 0／空白時由品項加總；人員合計；稅率欄）──

def _raw_set(did, **cols):
    cn = db.get_db()
    try:
        for k, v in cols.items():
            cn.execute("UPDATE contractor_dispatches SET %s=? WHERE id=?" % k, (v, did))
        cn.commit()
    finally:
        cn.close()


def _provider_row(did):
    cn = db.get_db()
    try:
        return registry.single_provider("dispatch.row")(cn.execute("SELECT cd.*, vc.name AS vendor_name FROM contractor_dispatches cd LEFT JOIN vendor_contractors vc ON vc.id = cd.vendor_id WHERE cd.id=?", (did,)).fetchone())
    finally:
        cn.close()


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "1e400", "NaN", "abc"], ids=lambda b: repr(b)[:10])
def test_total_zero_with_abnormal_item_amount_does_not_break_provider_or_compute(W, bad):
    """總額欄 0／空白 ⇒ 由品項加總：品項有異常值不可讓 `_dispatch_row` 丟例外；異常的品項當 0，其餘照加。"""
    did = _bad_dispatch(bad)
    _raw_set(did, total_amount=0)
    r = _provider_row(did)
    assert r["totalAmount"] == 4000 and r["taxAmount"] == 200                 # 1000＋3000（第 2 行 2000 換成異常值 ⇒ 0）
    d = _compute([])
    assert str(did) in {x["itemId"] for x in d["unassigned"]["dispatches"]}


@pytest.mark.parametrize("bad", [float("inf"), 1e400], ids=lambda b: repr(b)[:10])
def test_abnormal_total_column_and_personnel_do_not_break_provider_or_compute(W, bad):
    did, _ = _ldisp([1000, 2000, 3000])
    _raw_set(did, total_amount=bad, personnel_json=json.dumps([{"name": "甲", "amount": bad}, {"name": "乙", "amount": 500}]))
    r = _provider_row(did)
    assert r["personnelTotal"] == 500 and r["totalAmount"] == 6000            # 總額欄壞 ⇒ 當 0 ⇒ 改由品項加總
    d = _compute([])
    assert d["totals"]["dispatchTotal"] == r["grandTotal"]


def test_abnormal_tax_rate_falls_back_to_default_not_500(W):
    did, _ = _ldisp([1000, 2000, 3000])
    _raw_set(did, tax_rate=float("inf"))
    assert _provider_row(did)["taxRate"] == 0.05
    _compute([])


def test_provider_normal_values_unchanged(W):
    did, _ = _ldisp([1000, 2000, 3000], personnel=500, rate=0.05)
    r = _provider_row(did)
    assert (r["totalAmount"], r["taxAmount"], r["personnelTotal"], r["grandTotal"], r["taxRate"]) == (6000, 300, 500, 6800, 0.05)
    _raw_set(did, tax_rate=0)
    assert _provider_row(did)["taxRate"] == 0 and _provider_row(did)["taxAmount"] == 0      # 稅率 0 是合法值，不可被預設值蓋掉
