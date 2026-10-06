# -*- coding: utf-8 -*-
"""第 44 班：採購單「從請購單帶入」（使用者裁示 2026-10-06）。
- 一張採購單可混合同案件**多張已核准請購單**的明細；每個請購明細可部分採購，累計不超過請購量（認領量＝計入狀態採購單同一 prDocCode／prLine 的 qty 加總）
- 建立／修改（草稿不佔量）與送審（寫鎖內）各驗一次；變更申請（送審與核准當下）也不能繞過
- 採購單作廢／駁回釋放；已被認領的請購單不能作廢（409）、其明細不能被刪／改品名／改到低於已認領量
- `data.fromPr`（清單）＋`pr_no` 由明細同步；挑選器 `GET …/purchase-requests/lines`：只列已核准、被遮蔽的不列、沒有財務可視不回單價
- 預設不變：沒有 prDocCode 的明細與今天完全相同
斷言打在 API 狀態碼與資料庫落地值。⚙️ 突變：拿掉累計比較／計入狀態判斷／作廢檢查／遮蔽判斷 ⇒ 紅。"""
import json

import pytest

import db
from modules.case import purchase_items as PI
from modules.case.tests.test_purchase_item_lines_2026_10_02 import BASE, NO, W, _body, _login, _ln, _mk, _status, _stored, _submit  # noqa: F401


def _pr(c, h, lines, no=NO):
    """已核准的請購單（沒設簽核層 ⇒ 送審即核准）；回 (id, 單號)。"""
    r = _mk(c, h, "purchase_req", lines, no=no)
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    assert _submit(c, h, eid, no=no).status_code == 200
    return eid, r.json()["docCode"]


def L(summary, qty, price=100, **kw):
    d = {"category": "雜項", "summary": summary, "qty": qty, "unitCost": price}
    d.update(kw)
    return d


def P(doc, n, qty, price=100, summary="x", **kw):
    return L(summary, qty, price, prDocCode=doc, prLine=n, **kw)


def _po(c, h, lines, no=NO):
    return _mk(c, h, "purchase_order", lines, no=no)


def _claims(no=NO):
    cn = db.get_db()
    try:
        return PI.pr_claims(PI._pr_rows(cn, no))
    finally:
        cn.close()


# ── 認領與累計 ────────────────────────────────────────────────────────

def test_po_can_mix_lines_from_several_prs_and_snapshots_the_pr_qty(W):
    c, h = W
    _, a = _pr(c, h, [L("線材", 10), L("接頭", 4)])
    _, b = _pr(c, h, [L("交換器", 3)])
    r = _po(c, h, [P(a, 1, 6, summary="線材"), P(a, 2, 4, summary="接頭"), P(b, 1, 3, summary="交換器", prQty=999)])
    assert r.status_code == 201, r.text
    got = _stored(r.json()["id"])
    assert [(l["prDocCode"], l["prLine"], l["prQty"]) for l in got] == [(a, 1, 10.0), (a, 2, 4.0), (b, 1, 3.0)], "prQty 由伺服器依請購單寫入，不信前端"
    cn = db.get_db()
    d = json.loads(cn.execute("SELECT data_json FROM case_extra_expenses WHERE id=?", (r.json()["id"],)).fetchone()["data_json"])
    cn.close()
    assert d["fromPr"] == [a, b] and d["pr_no"] == "、".join([a, b]), "fromPr（驗證用）與 pr_no（顯示用）由明細同步"


def test_partial_claims_accumulate_and_cannot_exceed_the_pr_qty(W):
    c, h = W
    _, a = _pr(c, h, [L("線材", 10)])
    po1 = _po(c, h, [P(a, 1, 6)]).json()["id"]
    assert _submit(c, h, po1).status_code == 200
    assert _claims()[(a, 1)] == 6.0
    r2 = _po(c, h, [P(a, 1, 5)])                                       # 6 + 5 > 10：建立草稿時就驗（計入狀態的其他採購單 ＋ 本單）
    assert r2.status_code == 400 and "剩餘 4" in r2.text, r2.text
    ok = _po(c, h, [P(a, 1, 4)])                                      # 剛好用完
    assert ok.status_code == 201
    assert _submit(c, h, ok.json()["id"]).status_code == 200
    assert _po(c, h, [P(a, 1, 1)]).status_code == 400                 # 已用完


def test_same_pr_line_twice_in_one_po_is_summed(W):
    c, h = W
    _, a = _pr(c, h, [L("線材", 10)])
    assert _po(c, h, [P(a, 1, 6), P(a, 1, 5)]).status_code == 400
    assert _po(c, h, [P(a, 1, 6), P(a, 1, 4)]).status_code == 201


def test_drafts_do_not_hold_quantity_but_submit_rechecks_under_the_lock(W):
    """兩張草稿各認領 7（請購 10）：建立時各自合法（草稿不佔量）；先送審的過、後送審的 400——寫鎖內再驗。突變：送審時不再驗 ⇒ 兩張都過 ⇒ 紅。"""
    c, h = W
    _, a = _pr(c, h, [L("線材", 10)])
    p1 = _po(c, h, [P(a, 1, 7)]).json()["id"]
    p2 = _po(c, h, [P(a, 1, 7)]).json()["id"]
    assert _submit(c, h, p1).status_code == 200
    s = _submit(c, h, p2)
    assert s.status_code == 400 and "超過請購量" in s.text, s.text
    assert _claims()[(a, 1)] == 7.0


def test_editing_my_own_po_does_not_count_my_old_claim_twice(W):
    c, h = W
    _, a = _pr(c, h, [L("線材", 10)])
    po = _po(c, h, [P(a, 1, 8)]).json()["id"]
    assert _submit(c, h, po).status_code == 200
    r = c.put("%s/%d/change-request" % (BASE, po), headers=h, json=_body("purchase_order", [P(a, 1, 10)]))
    assert r.status_code == 200, r.text
    assert c.post("%s/%d/change-request/submit" % (BASE, po), headers=h).status_code == 200      # 自己原本的 8 不重複算：10 ≤ 10
    r = c.put("%s/%d/change-request" % (BASE, po), headers=h, json=_body("purchase_order", [P(a, 1, 11)]))
    assert c.post("%s/%d/change-request/submit" % (BASE, po), headers=h).status_code in (400, 409)


def test_rejects_unknown_unapproved_foreign_case_and_bad_line_numbers(W):
    c, h = W
    r = _mk(c, h, "purchase_req", [L("線材", 10)])                   # 草稿請購單（未核准）
    draft_code = r.json()["docCode"]
    _, a = _pr(c, h, [L("線材", 10)])
    assert _po(c, h, [P("PR-NOPE-1", 1, 1)]).status_code == 400                    # 不存在
    assert _po(c, h, [P(draft_code, 1, 1)]).status_code == 400                     # 未核准
    assert _po(c, h, [P(a, 2, 1)]).status_code == 400 and _po(c, h, [P(a, 0, 1)]).status_code == 400   # 列序不在範圍
    assert _po(c, h, [P(a, "x", 1)]).status_code == 400
    assert _po(c, h, [P(a, 1, 0)]).status_code == 400 and _po(c, h, [P(a, 1, -2)]).status_code == 400  # 數量須 > 0
    _, other = _pr(c, h, [L("線材", 10)], no="MQ-PL-2")
    assert _po(c, h, [P(other, 1, 1)]).status_code == 400                          # 別的案件的請購單
    assert _mk(c, h, "purchase_order", [P(a, 1, 1)], no="-").status_code == 400     # 無案件的採購單不能連請購單


def test_only_purchase_orders_may_link_to_prs_and_plain_lines_are_unchanged(W):
    c, h = W
    r = _mk(c, h, "purchase_req", [L("線材", 3, prDocCode="PR-X", prLine=1)])
    assert r.status_code == 400, "請購單／其他類型的明細不能連請購單"
    plain = _po(c, h, [L("線材", 3)], )
    assert plain.status_code == 201
    s = _stored(plain.json()["id"])
    assert "prDocCode" not in s[0] and "prQty" not in s[0]
    ghost = _po(c, h, [L("線材", 3, prQty=9, prLine=4)])                              # 沒有 prDocCode 的殘留保留鍵一律拿掉（不能偽造請購量）
    assert ghost.status_code == 201 and "prQty" not in _stored(ghost.json()["id"])[0] and "prLine" not in _stored(ghost.json()["id"])[0]


# ── 釋放與保護 ─────────────────────────────────────────────────────────

def test_void_and_reject_of_the_po_release_the_claim(W):
    c, h = W
    _, a = _pr(c, h, [L("線材", 10)])
    po = _po(c, h, [P(a, 1, 10)]).json()["id"]
    assert _submit(c, h, po).status_code == 200
    assert _po(c, h, [P(a, 1, 1)]).status_code == 400
    v = c.post("%s/%d/void" % (BASE, po), headers=h, json={"reason": "重開"})
    assert v.status_code == 200, v.text
    assert _claims().get((a, 1), 0.0) == 0.0
    assert _po(c, h, [P(a, 1, 10)]).status_code == 201                              # 釋放後可以重新認領
    po2 = _po(c, h, [P(a, 1, 10)]).json()["id"]
    _status(po2, "已駁回")
    assert _claims().get((a, 1), 0.0) == 0.0


def test_a_claimed_pr_cannot_be_voided_until_the_po_is_released(W):
    """突變：拿掉作廢前的認領檢查 ⇒ 200 ⇒ 紅。"""
    c, h = W
    pr_id, a = _pr(c, h, [L("線材", 10)])
    po = _po(c, h, [P(a, 1, 2)]).json()["id"]
    assert _submit(c, h, po).status_code == 200
    v = c.post("%s/%d/void" % (BASE, pr_id), headers=h, json={"reason": "不要了"})
    assert v.status_code == 409 and a in v.text, v.text
    assert c.post("%s/%d/void" % (BASE, po), headers=h, json={"reason": "先作廢採購單"}).status_code == 200
    assert c.post("%s/%d/void" % (BASE, pr_id), headers=h, json={"reason": "現在可以"}).status_code == 200


def test_a_claimed_pr_line_cannot_be_deleted_renamed_or_cut_below_the_claim(W):
    c, h = W
    pr_id, a = _pr(c, h, [L("線材", 10), L("接頭", 4)])
    po = _po(c, h, [P(a, 1, 6)]).json()["id"]
    assert _submit(c, h, po).status_code == 200

    def put(lines):
        return c.put("%s/%d/change-request" % (BASE, pr_id), headers=h, json=_body("purchase_req", lines))
    assert put([L("線材", 5), L("接頭", 4)]).status_code == 409                    # 6 已被認領，不能降到 5（提出變更當下就擋）
    assert put([L("接頭", 4)]).status_code == 409                                  # 刪掉被認領的那列（列序位移）
    assert put([L("別的品名", 10), L("接頭", 4)]).status_code == 409               # 改品名
    r = put([L("線材", 6), L("接頭", 9)])                                           # 降到剛好 6、別的列隨便改
    assert r.status_code == 200, r.text
    assert c.post("%s/%d/change-request/submit" % (BASE, pr_id), headers=h).status_code == 200
                   # 降到剛好 6、別的列隨便改


def test_change_request_submit_rechecks_claims_made_by_other_pos(W):
    c, h = W
    _, a = _pr(c, h, [L("線材", 10)])
    po = _po(c, h, [P(a, 1, 4)]).json()["id"]
    assert _submit(c, h, po).status_code == 200
    assert c.put("%s/%d/change-request" % (BASE, po), headers=h, json=_body("purchase_order", [P(a, 1, 9)])).status_code == 200
    other = _po(c, h, [P(a, 1, 6)]).json()["id"]                                      # 送審前別張採購單先認領 6（4 + 6 = 10 用完）
    assert _submit(c, h, other).status_code == 200
    s = c.post("%s/%d/change-request/submit" % (BASE, po), headers=h)
    assert s.status_code == 400 and "超過請購量" in s.text, s.text                       # 變更成 9 ⇒ 9 + 6 > 10


def test_applying_a_change_rechecks_claims_at_approval_time(W):
    """核准套用當下（`_apply_change`）再驗：送審後才被別張採購單認領的量，核准時不能超額套用。突變：拿掉 `_apply_change` 裡的檢查 ⇒ 沒有例外 ⇒ 紅。"""
    from fastapi import HTTPException
    from modules.case.api import case_extra_expenses as X
    c, h = W
    _, a = _pr(c, h, [L("線材", 10)])
    po = _po(c, h, [P(a, 1, 4)]).json()["id"]
    assert _submit(c, h, po).status_code == 200
    other = _po(c, h, [P(a, 1, 6)]).json()["id"]
    assert _submit(c, h, other).status_code == 200
    cn = db.get_db()
    try:
        row = cn.execute("SELECT * FROM case_extra_expenses WHERE id=?", (po,)).fetchone()
        with pytest.raises(HTTPException) as e:
            X._apply_change(cn, row, {"description": "x", "qty": 1, "unitCost": 1, "lines": [P(a, 1, 9)]}, "tester", "2026-10-06T00:00:00")
        assert e.value.status_code == 400
        cn.rollback()
        X._apply_change(cn, row, {"description": "x", "qty": 1, "unitCost": 1, "lines": [P(a, 1, 4)]}, "tester", "2026-10-06T00:00:00")   # 量沒變 ⇒ 套用得過
    finally:
        cn.rollback()
        cn.close()


# ── 挑選器端點 ──────────────────────────────────────────────────────────

def test_picker_lists_only_approved_prs_with_claimed_and_remaining(W):
    c, h = W
    _, a = _pr(c, h, [L("線材", 10, 120), L("接頭", 4, 30)])
    _mk(c, h, "purchase_req", [L("草稿線", 5)])                                     # 草稿：不列
    po = _po(c, h, [P(a, 1, 6)]).json()["id"]
    assert _submit(c, h, po).status_code == 200
    r = c.get("/api/quotations/%s/purchase-requests/lines" % NO, headers=h)
    assert r.status_code == 200, r.text
    reqs = r.json()["requests"]
    assert [q["docCode"] for q in reqs] == [a]
    l1, l2 = reqs[0]["lines"]
    assert (l1["prLine"], l1["qty"], l1["claimed"], l1["remaining"], l1["unitCost"]) == (1, 10.0, 6.0, 4.0, 120.0)
    assert (l2["claimed"], l2["remaining"]) == (0.0, 4.0)
    assert c.get("/api/quotations/-/purchase-requests/lines", headers=h).status_code == 400
    assert c.get("/api/quotations/%s/purchase-requests/lines" % NO).status_code == 401


def test_picker_hides_masked_prs_and_omits_prices_without_financial_visibility(W, make_user):
    """被遮蔽的請購單（別人的、自己不是申請人／簽核人）不列；沒有財務可視的申請人看得到自己的請購單但沒有單價。突變：拿掉遮蔽判斷 ⇒ 紅。"""
    c, h = W
    u, p = make_user(username="pr_sales", role="sales", modules=["dashboard", "quotation", "case_manage"])[:2]
    hs = _login(c, u, p)
    cn = db.get_db()
    cn.execute("UPDATE quotations SET sales_person=?, assigned_user_ids=? WHERE quote_no=?", ("pr_sales", "[]", NO))
    cn.commit()
    cn.close()
    _, others = _pr(c, h, [L("別人的請購", 5, 77)])                                   # superadmin 填的
    mine = _mk(c, hs, "purchase_req", [L("我的請購", 5, 55)], data=None)
    assert mine.status_code == 201, mine.text
    my_code = mine.json()["docCode"]
    _status(mine.json()["id"], "已核准")
    r = c.get("/api/quotations/%s/purchase-requests/lines" % NO, headers=hs)
    assert r.status_code == 200, r.text
    reqs = r.json()["requests"]
    assert [q["docCode"] for q in reqs] == [my_code], "別人的（金額遮蔽）不列；自己的看得到"
    assert all("unitCost" not in l for l in reqs[0]["lines"]), "沒有財務金額可視 ⇒ 不回單價（不複製價格）"
    full = c.get("/api/quotations/%s/purchase-requests/lines" % NO, headers=h).json()["requests"]
    assert {q["docCode"] for q in full} == {my_code, others} and all("unitCost" in l for q in full for l in q["lines"])


def test_claim_math_pure_function_counts_only_counted_po_rows():
    rows = [{"id": 1, "kind": "purchase_order", "status": "已核准", "lines_json": json.dumps([{"prDocCode": "PR-1", "prLine": 1, "qty": 3}])},
            {"id": 2, "kind": "purchase_order", "status": "待審核", "lines_json": json.dumps([{"prDocCode": "PR-1", "prLine": 1, "qty": 2}, {"prDocCode": "PR-1", "prLine": 2, "qty": 1}])},
            {"id": 3, "kind": "purchase_order", "status": "草稿", "lines_json": json.dumps([{"prDocCode": "PR-1", "prLine": 1, "qty": 99}])},
            {"id": 4, "kind": "purchase_order", "status": "已作廢", "lines_json": json.dumps([{"prDocCode": "PR-1", "prLine": 1, "qty": 99}])},
            {"id": 5, "kind": "purchase_order", "status": "已駁回", "lines_json": json.dumps([{"prDocCode": "PR-1", "prLine": 1, "qty": 99}])},
            {"id": 6, "kind": "purchase_req", "status": "已核准", "lines_json": json.dumps([{"prDocCode": "PR-1", "prLine": 1, "qty": 99}])},
            {"id": 7, "kind": "purchase_order", "status": "已核准", "lines_json": "{bad"},
            {"id": 8, "kind": "purchase_order", "status": "已核准", "lines_json": json.dumps([{"prDocCode": "PR-1", "prLine": "x", "qty": 5}, {"qty": 5}, "junk"])}]
    assert PI.pr_claims(rows) == {("PR-1", 1): 5.0, ("PR-1", 2): 1.0}
    assert PI.pr_claims(rows, exclude_id=2) == {("PR-1", 1): 3.0}
