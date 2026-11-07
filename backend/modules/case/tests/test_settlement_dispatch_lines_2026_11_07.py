# -*- coding: utf-8 -*-
"""精算：承攬商派發單「逐行」對應報價品項（規格 docs/platform/plans/DISPATCH-LINE-LINKAGE-PROPOSAL.md；V1–V8、V12–V14、V16 的後端部分）。
ref：整張 `<派發id>`／整行 `<派發id>#<行鍵>`／拆分份 `<派發id>#<行鍵>#<份次>`（拆分份帶未稅 amount）。對應只存在精算的 offsets，派發單一個位元都不改。
品項 a／b 為報價單現有品項（見 test_purchase_item_lines）。"""
import json
import random

import pytest

import db
from helpers.legal_params import round_half_up
from modules.case import dispatch_lines as DL
from modules.case import settlement_actuals as SA
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W  # noqa: F401
from modules.case.tests.test_settlement_tax_basis_2026_10_03 import _dispatch
from modules.case.tests._t40_won import quote_is_won  # noqa: F401  第 40 班：完結要已成案（autouse）


def _lines(amounts, base_id=1730000000000.5):
    """行 id 用帶小數的浮點（與派發表單 Date.now()+Math.random() 同形）。"""
    return [{"id": base_id + i * 1.25, "description": "品項%d" % (i + 1), "qty": 1, "unit": "式", "unitPrice": a, "amount": a} for i, a in enumerate(amounts)]


def _ldisp(amounts, personnel=0, rate=0.05, approval="", total=None):
    items = _lines(amounts)
    did = _dispatch(sum(amounts) if total is None else total, personnel, rate, approval=approval)
    _set_items(did, items)
    return did, [DL.line_key(i["id"]) for i in items]


def _set_items(did, items):
    cn = db.get_db()
    try:
        cn.execute("UPDATE contractor_dispatches SET items_json=? WHERE id=?", (json.dumps(items), did))
        cn.commit()
    finally:
        cn.close()


def _row_snapshot(did):
    cn = db.get_db()
    try:
        return tuple(cn.execute("SELECT * FROM contractor_dispatches WHERE id=?", (did,)).fetchone())
    finally:
        cn.close()


def _compute(offsets, basis=None):
    cn = db.get_db()
    try:
        saved = {"summary": {"dispatchBasis": basis}} if basis else None
        return SA.compute(cn, NO, offsets=offsets, settlement=saved)
    finally:
        cn.close()


def _validate(offsets, previous=None):
    cn = db.get_db()
    try:
        return SA.validate_offsets(cn, NO, offsets, previous=previous)
    finally:
        cn.close()


def _line(did, key, item="a"):
    return {"kind": "dispatch", "ref": DL.format_ref(did, key), "itemId": item}


def _part(did, key, no, item, amount):
    return {"kind": "dispatch", "ref": DL.format_ref(did, key, no), "itemId": item, "amount": amount}


def _orders(d, item):
    return {i["itemId"]: i for i in d["items"]}[item]["dispatch"]["orders"]


def _unassigned(d, did):
    return [x for x in d["unassigned"]["dispatches"] if x["itemId"] == str(did)]


def _conserved(d):
    t = d["totals"]
    assert abs(t["dispatchAssignedTotal"] + t["dispatchUnassignedTotal"] - t["dispatchTotal"]) < 1e-6, t
    return t


# ── 純函式（V7 後端半邊；跨語言向量見 e2e／前端測試）──

def test_line_key_and_ref_roundtrip():
    assert DL.line_key(1.0) == "1" and DL.line_key(1730000000000.5) == "1730000000000.5" and DL.line_key(" x ") == "x"
    assert DL.line_key("a#b%c") == "a%23b%25c" and DL.line_key(None) == "" and DL.line_key(True) == "" and DL.line_key(float("nan")) == ""
    assert DL.line_key(1e21) == "1e+21" and DL.line_key(1e-7) == "1e-7" and DL.line_key(0.000001) == "0.000001" and DL.line_key(-0.0) == "0"
    for raw in ("a#b%c", "%23", 12.5, 7):
        k = DL.line_key(raw)
        for part in (None, 3):
            p = DL.parse_ref(DL.format_ref(101, k, part))
            assert p["dispatch"] == "101" and p["key"] == k and p["part"] == part and DL.decode_key(k) == DL.raw_key(raw)
    for bad in ("", "#a", "1#", "1#a#0", "1#a#01", "1#a#2#3", "1#a%b", "1#a#x", " 1#a", "1##2"):
        assert DL.parse_ref(bad) is None, bad


def test_amount_normalisation_uses_integer_cents():
    assert DL.parse_amount(0.1 + 0.2) == 30 and DL.parse_amount(33.33) == 3333 and DL.parse_amount("12.5") == 1250 and DL.parse_amount(100) == 10000
    for bad in (0, -1, True, None, 33.333, "abc", float("nan"), [1]):
        assert DL.parse_amount(bad) is None, bad
    assert DL.amount_out(1250) == 12.5 and DL.amount_out(10000) == 100 and isinstance(DL.amount_out(10000), int)


def test_tax_examples_from_spec():
    assert DL.line_taxes([1000, 1000, 1000], 3000, 0.05) == [1, 0, 1]                                    # 各行單獨進位會是 1、1、1（差 1 元）
    assert DL.split_tax(5, 10000, [3333, 3333, 3334]) == ([2, 1, 2], 0)
    assert DL.split_tax(5, 10000, [3333, 3333]) == ([2, 1], 2)


def test_tax_properties_random():
    rnd = random.Random(20261107)
    for _ in range(3000):
        n = rnd.randint(1, 8)
        am = [rnd.randint(1, 2_000_000) for _ in range(n)]
        rate = rnd.choice([0, 0.03, 0.05, 0.075, 0.1])
        tot = sum(am)
        lt = DL.line_taxes(am, tot, rate)
        assert sum(lt) == round_half_up(tot / 100, rate) and min(lt) >= 0
        i = rnd.randrange(n)
        cuts = sorted(rnd.randint(0, am[i]) for _ in range(rnd.randint(1, 6)))
        parts = [b - a for a, b in zip([0] + cuts[:-1], cuts) if b > a]
        if parts:
            pt, rt = DL.split_tax(lt[i], am[i], parts)
            assert sum(pt) + rt == lt[i] and min(pt + [rt]) >= 0


# ── normalize／驗證 ──

def test_normalize_keeps_split_amount_and_drops_bad_rows():
    k = "123"
    rows = [{"kind": "dispatch", "ref": "9#%s#1" % k, "itemId": "a", "amount": 33.33, "junk": 1},
            {"kind": "dispatch", "ref": "9#%s#2" % k, "itemId": "b"},                    # 拆分份缺 amount ⇒ 壞列
            {"kind": "dispatch", "ref": "9#%s#3" % k, "itemId": "b", "amount": 0},       # ≤0
            {"kind": "dispatch", "ref": "9#%s#4" % k, "itemId": "b", "amount": 1.234},   # >2 位小數
            {"kind": "dispatch", "ref": "9#%s" % k, "itemId": "a", "amount": 5},         # 整行不可帶 amount
            {"kind": "dispatch", "ref": "9", "itemId": "a", "amount": 5},                # 整張不可帶 amount
            {"kind": "dispatch", "ref": "9#%s#0" % k, "itemId": "a", "amount": 5},       # 份次非正整數
            {"kind": "dispatch", "ref": "9#%s" % k, "itemId": "a"},
            {"kind": "material", "ref": "5", "itemId": "a", "amount": 9}]
    out = SA.normalize_offsets(rows)
    assert out == [{"kind": "dispatch", "ref": "9#123#1", "itemId": "a", "amount": 33.33},
                   {"kind": "dispatch", "ref": "9#123", "itemId": "a"},
                   {"kind": "material", "ref": "5", "itemId": "a"}]
    assert SA.normalize_offsets(out) == out                                               # 往返不丟 amount（V13 後端）


def test_validation_rules(W):
    c, h = W
    did, (k1, k2, k3) = _ldisp([100, 200, 300])
    other, _ = _ldisp([50])
    assert _validate([_line(did, k1), _line(did, k2, "b")]) is None
    assert _validate([_part(did, k1, 1, "a", 40), _part(did, k1, 2, "b", 60)]) is None            # 剛好拆完
    assert _validate([_part(did, k1, 1, "a", 40)]) is None                                          # 只拆一份：餘額留未對應
    bad = {
        "不存在的行": [_line(did, "999")],
        "不存在的派發": [_line(99999, k1)],
        "ref 格式錯": [{"kind": "dispatch", "ref": "%s#" % did, "itemId": "a"}],
        "份次 0": [{"kind": "dispatch", "ref": "%s#%s#0" % (did, k1), "itemId": "a", "amount": 1}],
        "非現有品項": [_line(did, k1, "zzz")],
        "整張與整行並存": [{"kind": "dispatch", "ref": str(did), "itemId": "a"}, _line(did, k1, "b")],
        "整張與拆分並存": [{"kind": "dispatch", "ref": str(did), "itemId": "a"}, _part(did, k1, 1, "b", 10)],
        "整行與拆分並存": [_line(did, k1), _part(did, k1, 1, "b", 10)],
        "份缺 amount": [{"kind": "dispatch", "ref": DL.format_ref(did, k1, 1), "itemId": "a"}],
        "份 amount≤0": [_part(did, k1, 1, "a", 0)],
        "份 amount 超過 2 位小數": [_part(did, k1, 1, "a", 1.005)],
        "整行帶 amount": [dict(_line(did, k1), amount=10)],
        "整張帶 amount": [{"kind": "dispatch", "ref": str(other), "itemId": "a", "amount": 10}],
        "Σ份 > 行": [_part(did, k1, 1, "a", 60), _part(did, k1, 2, "b", 40.01)],
        "超過 20 份": [_part(did, k1, i, "a", 1) for i in range(1, 22)],
    }
    for name, offs in bad.items():
        assert _validate(offs), name
    assert _validate([_part(did, k1, i, "a", 1) for i in range(1, 21)]) is None                   # 剛好 20 份


def test_validation_rejects_unmappable_dispatch_lines(W):
    c, h = W
    mismatch, (k1, _k2) = _ldisp([100, 200], total=999)                                            # Σ行≠總額 ⇒ 只能整張
    assert "不可逐行" in (_validate([_line(mismatch, k1)]) or "")
    assert _validate([{"kind": "dispatch", "ref": str(mismatch), "itemId": "a"}]) is None
    dup = _dispatch(30, 0)
    _set_items(dup, [{"id": 7, "description": "x", "amount": 10}, {"id": 7.0, "description": "y", "amount": 20}])      # 7 與 7.0 同鍵
    assert _validate([_line(dup, "7")])
    noid = _dispatch(30, 0)
    _set_items(noid, [{"description": "x", "amount": 10}, {"id": 5, "description": "y", "amount": 20}])
    assert _validate([_line(noid, "5")]) is None                                                    # 缺 id 的行不可對應，其餘行可
    assert not any(l["mappable"] for l in next(d for d in _compute([])["unassigned"]["dispatches"] if d["itemId"] == str(noid))["lines"] if l["lineKey"] == "")
    draft, (kd, _k) = _ldisp([10, 20], approval="草稿")
    assert _validate([_line(draft, kd)])                                                           # 草稿不在清單


def test_unchanged_saved_rows_pass_even_when_now_invalid(W):
    """上次存檔原樣的列放行（舊草稿不卡住）；但拆分份只改了金額就不算原樣。"""
    c, h = W
    did, (k1, _k2) = _ldisp([100, 200])
    prev = [_part(did, k1, 1, "a", 60), _part(did, k1, 2, "b", 40)]
    assert _validate(prev) is None
    _set_items(did, [dict(i, amount=(50 if n == 0 else 250)) for n, i in enumerate(_lines([100, 200]))])    # 行金額被改小到 50（總額不變 300）
    assert _validate(prev, previous=prev) is None                                                   # 原樣：放行
    changed = [_part(did, k1, 1, "a", 60), _part(did, k1, 2, "b", 41)]
    assert _validate(changed, previous=prev)                                                        # 改了金額：不放行（且 Σ>行）
    assert _validate([_part(did, k1, 1, "a", 20)], previous=prev) is None                           # 刪掉一份、另一份金額改小到合法


# ── 計算：整行 ──

def test_whole_line_mapping_assigns_amount_with_cumulative_tax_and_keeps_remainder(W):
    c, h = W
    did, (k1, k2, k3) = _ldisp([10, 10, 10], personnel=500)                                        # 稅 R(30)=2 → 1、0、1；整張 30+2+500=532
    base = _compute([])
    assert _conserved(base)["dispatchTotal"] == 532
    d = _compute([_line(did, k1, "a"), _line(did, k3, "b")])
    t = _conserved(d)
    oa, ob = _orders(d, "a")[0], _orders(d, "b")[0]
    assert (oa["amount"], oa["tax"], oa["pretaxAmount"], oa["part"], oa["lineKey"]) == (11, 1, 10, "line", k1)
    assert (ob["amount"], ob["tax"]) == (11, 1) and oa["assignedBy"] == "offset"
    un = _unassigned(d, did)[0]
    assert un["amount"] == 532 - 22 and un["tax"] == 0 and un["partial"] is True              # 剩第 2 行（10+0 稅）＋人員 500
    assert t["dispatchAssignedTotal"] == 22
    assert [l["state"] for l in un["lines"]] == ["line", "unassigned", "line"]
    assert "lines" not in oa and "linesOk" not in oa                                              # 已對應的份不帶整張的逐行分解


def test_line_mapping_pretax_basis_excludes_tax(W):
    c, h = W
    did, (k1, k2) = _ldisp([100, 200])
    d = _compute([_line(did, k1)], basis="pretax")
    o = _orders(d, "a")[0]
    assert o["amount"] == 100 and o["tax"] == 5 and o["grandTotal"] == 105
    assert _conserved(d)["dispatchTotal"] == 300 and _unassigned(d, did)[0]["amount"] == 200


def test_all_lines_mapped_leaves_only_personnel_then_nothing(W):
    c, h = W
    did, (k1, k2) = _ldisp([100, 200], personnel=0)
    d = _compute([_line(did, k1), _line(did, k2, "b")])
    assert _unassigned(d, did) == [] and _conserved(d)["dispatchAssignedTotal"] == 315
    did2, (j1,) = _ldisp([100], personnel=70)
    d = _compute([_line(did2, j1)])
    assert _unassigned(d, did2)[0]["amount"] == 70                                                # 外包人員留在未對應（Q2）


def test_no_line_offsets_leaves_existing_behaviour(W):
    """V1：沒有逐行對應時，已對應／未對應金額與整張對應的結果和舊口徑一致。"""
    c, h = W
    did, _k = _ldisp([100, 200], personnel=30)
    d = _compute([{"kind": "dispatch", "ref": str(did), "itemId": "a"}])
    o = _orders(d, "a")[0]
    assert o["amount"] == 345 and o["assignedBy"] == "offset" and "part" not in o and "lines" not in o
    assert _unassigned(d, did) == [] and d["warnings"] == []
    d0 = _compute([])
    assert _conserved(d0)["dispatchTotal"] == 345 and _unassigned(d0, did)[0]["linesOk"] is True and d0["warnings"] == []


# ── 計算：拆分 ──

def test_split_spec_examples_and_remainder(W):
    c, h = W
    did, (k1,) = _ldisp([100])                                                                    # 行 100、稅 5
    full = _compute([_part(did, k1, 1, "a", 33.33), _part(did, k1, 2, "b", 33.33), _part(did, k1, 3, "a", 33.34)])
    assert [(o["partNo"], o["pretaxAmount"], o["tax"], o["amount"]) for o in _orders(full, "a") + _orders(full, "b")] == [(1, 33.33, 2, 35.33), (3, 33.34, 2, 35.34), (2, 33.33, 1, 34.33)]
    assert _unassigned(full, did) == [] and _conserved(full)["dispatchAssignedTotal"] == 105
    part = _compute([_part(did, k1, 1, "a", 33.33), _part(did, k1, 2, "b", 33.33)])
    un = _unassigned(part, did)[0]
    assert un["amount"] == 105 - 35.33 - 34.33 and un["tax"] == 2                                  # 餘額 33.34＋稅 2
    st = un["lines"][0]
    assert st["state"] == "split" and st["remainderPretax"] == 33.34 and st["remainderTax"] == 2
    _conserved(part)


def test_split_exceeding_current_line_is_ignored_with_warning_and_restores(W):
    """V14：行金額被改小（舊單可被改而不重設審核）⇒ 整行拆分忽略、金額全回未對應、有 warning；行金額恢復 ⇒ 拆分恢復。"""
    c, h = W
    did, (k1, k2) = _ldisp([100, 200])
    offs = [_part(did, k1, 1, "a", 60), _part(did, k1, 2, "b", 40)]
    assert _orders(_compute(offs), "a")
    _set_items(did, [dict(i, amount=(50 if n == 0 else 250)) for n, i in enumerate(_lines([100, 200]))])
    d = _compute(offs)
    assert [w["code"] for w in d["warnings"]] == ["dispatch_line_split_exceeds"]
    assert _orders(d, "a") == [] and _orders(d, "b") == [] and _unassigned(d, did)[0]["amount"] == 315 and _conserved(d)["dispatchAssignedTotal"] == 0
    _set_items(did, _lines([100, 200]))
    d = _compute(offs)
    assert d["warnings"] == [] and _conserved(d)["dispatchAssignedTotal"] == 105
    _set_items(did, [dict(i, amount=(150 if n == 0 else 150)) for n, i in enumerate(_lines([100, 200]))])    # 行變大：份不變、餘額變大
    d = _compute(offs)
    assert d["warnings"] == [] and _unassigned(d, did)[0]["lines"][0]["remainderPretax"] == 50


def test_conflicts_in_saved_data_do_not_lose_money(W):
    c, h = W
    did, (k1, k2) = _ldisp([100, 200])
    whole_plus_line = _compute([{"kind": "dispatch", "ref": str(did), "itemId": "a"}, _line(did, k1, "b")])
    assert [w["code"] for w in whole_plus_line["warnings"]] == ["dispatch_line_conflict"]
    assert _orders(whole_plus_line, "a")[0]["amount"] == 315 and _orders(whole_plus_line, "b") == [] and _conserved(whole_plus_line)
    line_plus_split = _compute([_line(did, k1, "a"), _part(did, k1, 1, "b", 10)])
    assert [w["code"] for w in line_plus_split["warnings"]] == ["dispatch_line_conflict"] and _orders(line_plus_split, "a")[0]["part"] == "line"
    _conserved(line_plus_split)
    unmappable, (u1, _u2) = _ldisp([100, 200], total=999)
    d = _compute([_line(unmappable, u1)])
    assert [w["code"] for w in d["warnings"]] == ["dispatch_line_unmappable"] and _conserved(d)["dispatchAssignedTotal"] == 0


def test_dispatch_back_to_draft_then_reapproved_restores_mapping(W):
    """V5：派發單退回草稿（實質欄位被改）⇒ 該張在精算消失、warning、不報錯；重新核准且行 id 不變 ⇒ 對應恢復。"""
    c, h = W
    did, (k1, k2) = _ldisp([100, 200])
    keep, (kk,) = _ldisp([40])
    offs = [_line(did, k1, "a"), _line(keep, kk, "b")]
    assert _conserved(_compute(offs))["dispatchAssignedTotal"] == 105 + 42

    def approval(val):
        cn = db.get_db()
        try:
            cn.execute("UPDATE contractor_dispatches SET approval_status=? WHERE id=?", (val, did))
            cn.commit()
        finally:
            cn.close()
    approval("草稿")
    d = _compute(offs)
    assert [(w["code"], w["ref"]) for w in d["warnings"]] == [("dispatch_line_removed", DL.format_ref(did, k1))]
    assert _orders(d, "a") == [] and _conserved(d)["dispatchTotal"] == 42 and _orders(d, "b")[0]["amount"] == 42
    approval("")
    d = _compute(offs)
    assert d["warnings"] == [] and _orders(d, "a")[0]["amount"] == 105
    _set_items(did, [dict(i, id=i["id"] + 100) for i in _lines([100, 200])])                       # 行 id 改變 ⇒ 失效、金額回未對應
    d = _compute(offs)
    assert [w["code"] for w in d["warnings"]] == ["dispatch_line_removed"] and _orders(d, "a") == [] and _unassigned(d, did)[0]["amount"] == 315


def test_line_item_removed_from_quote_returns_money_to_unassigned(W):
    c, h = W
    did, (k1,) = _ldisp([100])
    d = _compute([_line(did, k1, "no-such-item")])
    assert [w["code"] for w in d["warnings"]] == ["dispatch_line_removed"] and _unassigned(d, did)[0]["amount"] == 105 and _conserved(d)


def test_dispatch_rows_untouched_by_mapping_preview_and_validation(W):
    """V6：對應、預覽、驗證前後，contractor_dispatches 該列所有欄位位元組相同。"""
    c, h = W
    did, (k1, k2) = _ldisp([100, 200])
    before = _row_snapshot(did)
    offs = [_part(did, k1, 1, "a", 60), _line(did, k2, "b")]
    _validate(offs)
    _compute(offs)
    r = c.get("/api/quotations/%s/settlement-actuals" % NO, params={"offsets": json.dumps(offs)}, headers=h)
    assert r.status_code == 200 and _row_snapshot(did) == before


def test_preview_endpoint_round_trips_split_amount(W):
    c, h = W
    did, (k1,) = _ldisp([100])
    offs = [_part(did, k1, 1, "a", 33.33)]
    r = c.get("/api/quotations/%s/settlement-actuals" % NO, params={"offsets": json.dumps(offs)}, headers=h)
    assert r.status_code == 200 and r.json()["offsets"] == offs


# ── 守恆性質（V2／V12）──

@pytest.mark.parametrize("basis", [None, "pretax"])
def test_random_mappings_conserve_every_dispatch_and_the_total(W, basis):
    c, h = W
    rnd = random.Random(7 if basis is None else 8)
    specs = []
    for _ in range(6):
        amts = [rnd.randint(1, 5000) / rnd.choice([1, 4, 100]) for _ in range(rnd.randint(1, 5))]
        amts = [round(a, 2) or 1.0 for a in amts]
        did, keys = _ldisp(amts, personnel=rnd.choice([0, 0, 120]), rate=rnd.choice([0.05, 0.03, 0.075]))
        specs.append((did, keys, amts))
    for _ in range(25):
        offs = []
        for did, keys, amts in specs:
            mode = rnd.choice(["none", "whole", "lines", "split"])
            if mode == "whole":
                offs.append({"kind": "dispatch", "ref": str(did), "itemId": rnd.choice("ab")})
            elif mode == "lines":
                offs += [_line(did, k, rnd.choice("ab")) for k, _a in zip(keys, amts) if rnd.random() < .6]
            elif mode == "split":
                for k, a in zip(keys, amts):
                    left = DL.cents(a)
                    for no in range(1, rnd.randint(1, 4)):
                        if left <= 1:
                            break
                        take = rnd.randint(1, left)
                        left -= take
                        offs.append(_part(did, k, no, rnd.choice("ab"), DL.amount_out(take)))
        assert _validate(offs) is None, offs
        d = _compute(offs, basis=basis)
        assert d["warnings"] == [], d["warnings"]
        t = _conserved(d)
        un = {x["itemId"]: x["amount"] for x in d["unassigned"]["dispatches"]}
        asg = {}
        for it in d["items"]:
            for o in it["dispatch"]["orders"]:
                asg[o["itemId"]] = asg.get(o["itemId"], 0) + o["amount"]
        full = {x["itemId"]: x["amount"] for x in _compute([], basis=basis)["unassigned"]["dispatches"]}
        for did, _k, _a in specs:                                                                 # 每張：已對應各份＋未對應剩餘＝該張金額
            assert abs(asg.get(str(did), 0) + un.get(str(did), 0) - full[str(did)]) < 1e-6, (did, offs)
        assert t["dispatchTotal"] == sum(full.values()) or abs(t["dispatchTotal"] - sum(full.values())) < 1e-6


def test_dispatch_lines_view_lists_every_dispatch_with_mode(W):
    """頂層 `dispatchLines`：整張都被分完（不在未對應清單）的派發單也在，畫面才能編輯；mode＝none／whole／lines。"""
    c, h = W
    a, (ka, kb) = _ldisp([100, 200])
    b, (kc,) = _ldisp([50])
    whole = _dispatch(10, 0)
    d = _compute([_line(a, ka, "a"), _line(a, kb, "b"), {"kind": "dispatch", "ref": str(whole), "itemId": "a"}])
    view = {v["dispatchId"]: v for v in d["dispatchLines"]}
    assert set(view) == {str(a), str(b), str(whole)}
    assert _unassigned(d, a) == [] and view[str(a)]["mode"] == "lines" and [l["state"] for l in view[str(a)]["lines"]] == ["line", "line"]
    assert view[str(b)]["mode"] == "none" and view[str(b)]["linesOk"] is True and view[str(b)]["lines"][0]["lineKey"] == kc
    assert view[str(whole)]["mode"] == "whole" and view[str(whole)]["assignedItemId"] == "a" and view[str(whole)]["linesOk"] is False
    assert d["dispatchLines"] == _compute([_line(a, ka, "a"), _line(a, kb, "b"), {"kind": "dispatch", "ref": str(whole), "itemId": "a"}])["dispatchLines"]
