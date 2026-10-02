# -*- coding: utf-8 -*-
"""叫料匯款申請（31-C 匯款切片）：額度（跨申請累計上限）、簽核狀態機、付款明細與叫料單 paid* 投影、差額（多付）審核、舊單歷史已付。

不經 HTTP；直接呼叫 `modules/case/material_payment.py`。手算基準（叫料單 L1＝2 台 × 5,000＝小計 10,000，已核准）：
  申請 A 6,000＋申請 B 4,000 ⇒ 額度用完；再申請 1 ⇒ 409。
  A 分兩次付：2,500（剩 3,500）→ 3,500（結清）；叫料單 paid 合計 6,000 ＜ 10,000 ⇒ `partial`，日期＝最後一次付款日。
  B 多付：4,000 應付、實付 4,500 ⇒ 差額 +500 待審核；叫料單 paid 合計 10,500 封頂 10,000 ⇒ `paid`。
舊單（沒有疊加列）L9＝小計 10,000、歷史已付 3,000（2031-02-01）：額度只剩 7,000；歷史已付在第一張申請建立時凍結，之後 paid* 被投影覆寫也不會丟。
"""
import json
import re

import pytest

from tests._requires import skip_module_unless

skip_module_unless("case", "本檔全部是 M01 的叫料匯款申請")

import db  # noqa: E402
from modules.case import material_approval as MA  # noqa: E402
from modules.case import material_payment as MP  # noqa: E402

NO = "MQ-MP-001"
ENG = {"username": "mp_eng", "role": "sales", "display_name": "工程師"}
BOSS = {"username": "mp_boss", "role": "sales", "display_name": "主管"}
ADMIN = {"username": "mp_admin", "role": "admin", "display_name": "管理員"}
SA = {"username": "mp_sa", "role": "superadmin", "display_name": "最高管理員"}
CASHIER = {"username": "mp_cash", "role": "sales", "display_name": "出納"}
PAYEE = {"bankCode": "812", "bankName": "台新", "bankAccountName": "甲供應商有限公司", "bankAccountNumber": "28881234567890"}


def _flow(tiers):
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                     ("unified_approval_flow", json.dumps({"tiers": tiers, "includeSubmitterManagerTier": False}), "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _one_tier():
    _flow([{"order": 0, "approvers": [{"username": BOSS["username"], "displayName": "主管"}]}])


def _order(item="L1", total=10000, **kw):
    o = {"itemId": item, "itemName": "交換器", "quantity": 2, "unit": "台", "unitPrice": total / 2, "totalPrice": total,
         "paidStatus": "pending", "paidAmount": 0, "paidDate": "", "notes": ""}
    o.update(kw)
    return o


@pytest.fixture
def world(client):
    """案件 NO 有三筆叫料：L1（已核准、$10,000）、L9（舊單、$10,000、歷史已付 3,000）、Z0（已核准、$0）、D1（草稿、$500）。回 (conn, 供應商 id)。"""
    _flow([])
    conn = db.get_db()
    orders = [_order("L1"), _order("L9", paidStatus="partial", paidAmount=3000, paidDate="2031-02-01"), _order("Z0", 0, unitPrice=0), _order("D1", 500)]
    conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag)"
                 " VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (NO, "已送出", "匯款客", "匯款專案", 1, 1, json.dumps({"dealTag": "已成案", "caseRecord": {"materialOrders": orders}}),
                  "2031-01-01T00:00:00", "2031-01-01T00:00:00", "已成案"))
    conn.execute("INSERT INTO suppliers (name, code, created_at, updated_at) VALUES (?,?,?,?)", ("甲供應商", "S-001", "2031-01-01", "2031-01-01"))
    sid = conn.execute("SELECT id FROM suppliers WHERE name='甲供應商'").fetchone()["id"]
    for it in ("L1", "Z0", "D1"):
        MA.create_draft(conn, NO, it, ENG)
    MA.submit(conn, NO, _order("L1"), ENG)                                       # 沒簽核層 ⇒ 直接核准
    MA.submit(conn, NO, _order("Z0", 0, unitPrice=0), ENG)
    conn.commit()
    yield conn, sid
    conn.rollback()
    conn.close()


def _o(conn, item):
    data = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
    return next(o for o in data["caseRecord"]["materialOrders"] if o["itemId"] == item)


def _mk(conn, sid, item="L1", amount=None, user=ENG, **kw):
    body = dict(PAYEE, supplierId=sid)
    if amount is not None:
        body["amount"] = amount
    body.update(kw)
    return MP.create(conn, NO, _o(conn, item), user, body)


def _approved(conn, sid, item="L1", amount=None, **kw):
    """建立並（沒簽核層 ⇒）自動核准一張申請。"""
    conn.commit()                                                                    # 設定另開連線寫入：先放掉自己的寫鎖
    _flow([])
    p = _mk(conn, sid, item, amount, **kw)
    assert MP.submit(conn, p["id"], _o(conn, item), ENG)["status"] == MP.S_APPROVED
    return MP.get(conn, p["id"])


def test_migration_is_idempotent_and_code_format(world):
    from importlib import import_module
    conn, sid = world
    m5 = import_module("modules.case.migrations.0005_material_payments")
    m5.up(conn)
    m5.up(conn)
    assert {"doc_code", "quote_no", "item_id", "seq", "amount_approved", "snapshot_json", "status", "approval_json", "over_cap_reason"} <= \
        {r[1] for r in conn.execute("PRAGMA table_info(case_material_payments)")}
    assert {"payment_id", "paid_at", "amount", "fee", "remit_review"} <= {r[1] for r in conn.execute("PRAGMA table_info(case_material_payment_lines)")}
    a, b = _mk(conn, sid, amount=100), _mk(conn, sid, amount=200)
    assert re.fullmatch(r"MP-\d{8}-\d{4}", a["doc_code"]) and a["doc_code"][:-4] == b["doc_code"][:-4] and (a["doc_code"][-4:], b["doc_code"][-4:]) == ("0001", "0002")
    assert (a["seq"], b["seq"], a["status"]) == (1, 2, MP.S_DRAFT)                 # 同一張叫料單的第幾張


def test_cumulative_cap_across_applications_drafts_lock_quota_and_void_releases(world):
    conn, sid = world
    a = _mk(conn, sid, amount=6000)
    assert MP.quota_summary(conn, NO, _o(conn, "L1")) == {"total": 10000.0, "legacyPaid": 0.0, "committed": 6000.0, "remaining": 4000.0}   # 草稿也鎖額度
    b = _mk(conn, sid)                                                              # 金額不帶＝剩餘額度
    assert b["amount_approved"] == 4000.0 and b["seq"] == 2
    with pytest.raises(MP.MaterialPaymentError) as e:
        _mk(conn, sid, amount=1)                                                    # 額度用完
    assert e.value.status == 409 and len(MP.list_for_order(conn, NO, "L1")) == 2    # 沒有多出一張
    MP.void(conn, b["id"], ENG, "不需要了")                                          # 作廢釋出額度
    assert MP.quota_summary(conn, NO, _o(conn, "L1"))["remaining"] == 4000.0
    c = _mk(conn, sid, amount=4000)
    assert (c["seq"], c["amount_approved"]) == (3, 4000.0)                          # seq 不重用
    with pytest.raises(MP.MaterialPaymentError):
        MP.update_draft(conn, a["id"], _o(conn, "L1"), ENG, {"amount": 6001})        # 改大也受上限約束
    assert MP.get(conn, a["id"])["amount_approved"] == 6000.0


def test_returned_application_releases_quota_and_resubmit_rechecks(world):
    conn, sid = world
    conn.commit()
    _one_tier()
    a = _mk(conn, sid, amount=6000)
    assert MP.submit(conn, a["id"], _o(conn, "L1"), ENG)["status"] == MP.S_PENDING
    MP.reject(conn, a["id"], BOSS, "金額不對")
    assert MP.get(conn, a["id"])["status"] == MP.S_RETURNED and MP.quota_summary(conn, NO, _o(conn, "L1"))["remaining"] == 10000.0   # 退回釋出
    d = _mk(conn, sid, amount=8000)                                                  # 額度被別張佔用
    with pytest.raises(MP.MaterialPaymentError) as e:
        MP.submit(conn, a["id"], _o(conn, "L1"), ENG)                                # 重送審時重新檢查
    assert e.value.status == 409 and MP.get(conn, a["id"])["status"] == MP.S_RETURNED
    MP.void(conn, d["id"], ENG, "改回原案")
    assert MP.submit(conn, a["id"], _o(conn, "L1"), ENG)["status"] == MP.S_PENDING


def test_only_superadmin_with_a_reason_may_override_the_cap(world):
    conn, sid = world
    _mk(conn, sid, amount=10000)
    for user, kw in ((ADMIN, {"overCapReason": "客戶加購"}), (SA, {})):
        with pytest.raises(MP.MaterialPaymentError) as e:
            _mk(conn, sid, amount=500, user=user, **kw)                              # admin 不能覆寫；superadmin 沒理由也不行
        assert e.value.status == 409
    over = _mk(conn, sid, amount=500, user=SA, overCapReason="客戶加購，已口頭核准")
    assert over["over_cap_reason"] == "客戶加購，已口頭核准" and over["amount_approved"] == 500.0


def test_preconditions_zero_dollar_unapproved_supplier_and_payee(world):
    conn, sid = world
    for item, why in (("Z0", "$0"), ("D1", "草稿叫料單")):
        with pytest.raises(MP.MaterialPaymentError) as e:
            _mk(conn, sid, item=item, amount=100)
        assert e.value.status == 409, why
    with pytest.raises(MP.MaterialPaymentError) as e:
        MP.create(conn, NO, _o(conn, "L1"), ENG, dict(PAYEE, amount=100))             # 沒有供應商
    assert e.value.status == 400
    with pytest.raises(MP.MaterialPaymentError) as e:
        MP.create(conn, NO, _o(conn, "L1"), ENG, {"supplierId": sid, "amount": 100})   # 沒有收款帳戶
    assert e.value.status == 400
    for bad in (0, -5, "abc", True):
        with pytest.raises(MP.MaterialPaymentError):
            _mk(conn, sid, amount=bad)
    assert MP.list_for_order(conn, NO, "L1") == []                                   # 以上都沒有留下任何申請


def test_snapshot_freezes_order_supplier_and_payee_and_only_approved_applications_can_be_paid(world):
    conn, sid = world
    p = _mk(conn, sid, amount=3000)
    sn = MP.snapshot_of(p)
    assert (sn["itemName"], sn["totalPrice"], sn["supplierName"], sn["supplierCode"], sn["bankAccountNumber"]) == ("交換器", 10000.0, "甲供應商", "S-001", "28881234567890")
    with pytest.raises(ValueError):
        MP.add_line(conn, p["id"], "2031-03-05", CASHIER, {})                        # 草稿不能付款
    assert MP.lines_of(conn, p["id"]) == []


def test_partial_payments_settle_and_project_onto_the_order(world):
    conn, sid = world
    a = _approved(conn, sid, amount=6000)
    r1 = MP.add_line(conn, a["id"], "2031-03-05", CASHIER, {"actualAmount": 2500})
    assert (r1["paid"], r1["remaining"], r1["settled"], r1["remitReview"]) == (2500.0, 3500.0, False, "")        # 少付＝分次付款，無審核
    o = _o(conn, "L1")
    assert (o["paidStatus"], o["paidAmount"], o["paidDate"]) == ("partial", 2500.0, "2031-03-05")
    r2 = MP.add_line(conn, a["id"], "2031-03-09", CASHIER, {"hasFee": True, "fee": 15})                        # 實付不帶＝剩餘 3,500
    assert (r2["actual"], r2["fee"], r2["paid"], r2["remaining"], r2["settled"]) == (3500.0, 15.0, 6000.0, 0.0, True)
    o = _o(conn, "L1")
    assert (o["paidStatus"], o["paidAmount"], o["paidDate"]) == ("partial", 6000.0, "2031-03-09")                # 6,000 ＜ 小計 10,000
    with pytest.raises(ValueError):
        MP.add_line(conn, a["id"], "2031-03-10", CASHIER, {"actualAmount": 1})                                   # 已結清
    assert [(x["amount"], x["fee"]) for x in MP.lines_of(conn, a["id"])] == [(2500.0, 0.0), (3500.0, 15.0)]


def test_overpayment_is_pending_review_and_reject_deletes_the_line(world):
    conn, sid = world
    a = _approved(conn, sid, amount=6000)
    MP.add_line(conn, a["id"], "2031-03-05", CASHIER, {})                                                        # 6,000 付清
    b = _approved(conn, sid, amount=4000)
    r = MP.add_line(conn, b["id"], "2031-03-20", CASHIER, {"actualAmount": 4500})
    assert (r["actual"], r["diff"], r["remitReview"], r["remaining"]) == (4500.0, 500.0, "pending", -500.0)
    o = _o(conn, "L1")
    assert (o["paidStatus"], o["paidAmount"]) == ("paid", 10000.0)                                               # 合計 10,500 封頂在小計
    with pytest.raises(MP.RemitForbidden):
        MP.decide_line(conn, r["lineId"], "approve", CASHIER)                                                    # 登錄人不能自審
    MP.decide_line(conn, r["lineId"], "reject", ADMIN, "多付，請追回")                                              # 退回＝刪除該筆
    assert MP.lines_of(conn, b["id"]) == [] and MP.remaining_of(conn, MP.get(conn, b["id"])) == 4000.0
    o = _o(conn, "L1")
    assert (o["paidStatus"], o["paidAmount"]) == ("partial", 6000.0)                                             # 投影跟著退回
    r2 = MP.add_line(conn, b["id"], "2031-03-21", CASHIER, {"actualAmount": 4200})
    MP.decide_line(conn, r2["lineId"], "approve", ADMIN)
    assert MP.lines_of(conn, b["id"])[0]["remit_review"] == "approved"
    with pytest.raises(ValueError):
        MP.decide_line(conn, r2["lineId"], "approve", ADMIN)                                                     # 已處理
    with pytest.raises(MP.BadRemit):
        MP.parse_line({"actualAmount": 0}, 100)
    with pytest.raises(MP.BadRemit):
        MP.parse_line({"hasFee": True, "fee": -1}, 100)


def test_void_rules_and_the_order_cannot_be_cancelled_while_applications_live(world):
    conn, sid = world
    a = _approved(conn, sid, amount=6000)
    with pytest.raises(MA.MaterialApprovalError) as e:
        MA.cancel(conn, NO, "L1", ADMIN, "不要了")                                  # 還有匯款申請 ⇒ 先作廢申請
    assert e.value.status == 409 and MA.status_of(conn, NO, "L1") == MA.S_APPROVED
    MP.add_line(conn, a["id"], "2031-03-05", CASHIER, {"actualAmount": 1000})
    with pytest.raises(MP.MaterialPaymentError) as e:
        MP.void(conn, a["id"], ADMIN, "想作廢")                                      # 已有付款明細 ⇒ 不可作廢
    assert e.value.status == 409 and MP.get(conn, a["id"])["status"] == MP.S_APPROVED
    b = _approved(conn, sid, amount=1000)
    with pytest.raises(MP.MaterialPaymentError) as e:
        MP.void(conn, b["id"], ENG, "x")                                            # 已核准的申請只有 admin 以上能作廢
    assert e.value.status == 403
    with pytest.raises(MP.MaterialPaymentError) as e:
        MP.void(conn, b["id"], ADMIN, "")                                           # 理由必填
    assert e.value.status == 400
    assert MP.void(conn, b["id"], ADMIN, "改下次付")["status"] == MP.S_VOID
    assert MP.has_live_payments(conn, NO, "L1") and MP.has_any_payments(conn, NO, "L1")


def test_one_tier_flow_permissions_and_withdraw(world):
    conn, sid = world
    conn.commit()
    _one_tier()
    p = _mk(conn, sid, amount=2000)
    r = MP.submit(conn, p["id"], _o(conn, "L1"), ENG)
    assert (r["status"], r["firstApprovers"]) == (MP.S_PENDING, [BOSS["username"]])
    with pytest.raises(MP.MaterialPaymentError) as e:
        MP.approve(conn, p["id"], _o(conn, "L1"), ENG)                              # 不是當層簽核人
    assert e.value.status == 403 and MP.get(conn, p["id"])["status"] == MP.S_PENDING
    with pytest.raises(MP.MaterialPaymentError):
        MP.withdraw(conn, p["id"], {"username": "someone", "role": "sales"})        # 非送審人也非 admin
    MP.withdraw(conn, p["id"], ENG)
    assert MP.get(conn, p["id"])["status"] == MP.S_DRAFT
    MP.submit(conn, p["id"], _o(conn, "L1"), ENG)
    res = MP.approve(conn, p["id"], _o(conn, "L1"), BOSS)
    assert res["done"] and MP.get(conn, p["id"])["status"] == MP.S_APPROVED and MP.get(conn, p["id"])["approved_at"]
    with pytest.raises(MP.MaterialPaymentError):
        MP.update_draft(conn, p["id"], _o(conn, "L1"), ENG, {"amount": 1})          # 已核准不可再改


def test_legacy_paid_history_counts_against_the_cap_and_survives_projection(world):
    conn, sid = world
    assert MP.quota_summary(conn, NO, _o(conn, "L9")) == {"total": 10000.0, "legacyPaid": 3000.0, "committed": 0.0, "remaining": 7000.0}
    with pytest.raises(MP.MaterialPaymentError) as e:
        _mk(conn, sid, item="L9", amount=7001)                                      # 舊單歷史已付 3,000 要扣掉
    assert e.value.status == 409
    a = _approved(conn, sid, item="L9", amount=2000)
    assert MP.snapshot_of(a)["legacyPaid"] == 3000.0 and MP.snapshot_of(a)["legacyPaidDate"] == "2031-02-01"
    MP.add_line(conn, a["id"], "2031-03-05", CASHIER, {})
    o = _o(conn, "L9")
    assert (o["paidStatus"], o["paidAmount"], o["paidDate"]) == ("partial", 5000.0, "2031-03-05")                # 歷史 3,000 ＋ 本次 2,000
    assert MP.legacy_paid(conn, NO, "L9") == (3000.0, "2031-02-01")                  # 投影覆寫了 paid* 之後歷史仍在（來自第一張申請的快照）
    b = _approved(conn, sid, item="L9", amount=5000)
    MP.add_line(conn, b["id"], "2031-04-01", CASHIER, {})
    o = _o(conn, "L9")
    assert (o["paidStatus"], o["paidAmount"], o["paidDate"]) == ("paid", 10000.0, "2031-04-01")
    assert MP.legacy_by_order(conn)[(NO, "L9")] == (3000.0, "2031-02-01")


def test_lines_by_order_feeds_reports(world):
    conn, sid = world
    a = _approved(conn, sid, amount=6000)
    MP.add_line(conn, a["id"], "2031-03-05", CASHIER, {"actualAmount": 2500, "payMethod": "petty_cash", "payAccountCode": "1111"})
    got = MP.lines_by_order(conn)[(NO, "L1")]
    assert [(x["paid_at"], x["amount"], x["review"], x["doc_code"], x["pay_method"], x["pay_account_code"]) for x in got] == \
        [("2031-03-05", 2500.0, "", a["doc_code"], "petty_cash", "1111")]


def test_static_guard_only_sync_order_paid_writes_paid_fields():
    """G-M1（付款面）：`modules/case`（非測試、非閘）裡寫已付欄位（`paidStatus／paidAmount／paidDate` 的指派或 update）只准出現在
    `material_payment.py`（`sync_order_paid`）與寫入閘 `material_guard.py`（重設新列為待付）。"""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    allowed = {"material_payment.py", "material_guard.py"}
    pat = re.compile(r"""\[["'](paidStatus|paidAmount|paidDate)["']\]\s*=(?!=)|\.update\(\{[^}]*["'](paidStatus|paidAmount|paidDate)["']""")
    bad = []
    for p in root.rglob("*.py"):
        rel = p.relative_to(root).as_posix()
        if rel.startswith("tests/") or "/tests/" in rel or "migrations/" in rel or p.name in allowed:
            continue
        if pat.search(p.read_text(encoding="utf-8")):
            bad.append(rel)
    assert not bad, bad
    src = (root / "material_payment.py").read_text(encoding="utf-8")
    i = src.index("def sync_order_paid")
    assert src.count("target.update({") == 2 and i > 0                                # 只有投影函式裡有（兩個分支）
    assert "sync_order_paid(conn" in src[src.index("def add_line"):src.index("def decide_line")] and "sync_order_paid(conn" in src[src.index("def decide_line"):src.index("def lines_by_order")]


def test_amounts_are_rounded_half_up_to_cents_not_python_round(world):
    """金額（元以下兩位）一律 half-up（X-VAT 規則；前端 MotrixLegalRound.halfUp）。Python `round()` 對二進位浮點會得到 0.145→0.14、2.675→2.67。
    手算：0.145→0.15、2.675→2.68、1.005→1.01、-0.145→-0.15（遠離零）、100.1×2 的 200.2 不變、10000→10000。
    付款明細的實付與手續費、叫料單的已付投影、剩餘額都走同一個 `MP.r2`。"""
    for raw, want in ((0.145, 0.15), (2.675, 2.68), (1.005, 1.01), (-0.145, -0.15), (200.2, 200.2), (10000, 10000.0), ("12.345", 12.35)):
        assert MP.r2(raw) == want, (raw, MP.r2(raw))
    conn, sid = world
    a = _approved(conn, sid, amount=1000)
    r = MP.add_line(conn, a["id"], "2031-03-05", CASHIER, {"actualAmount": 10.145, "hasFee": True, "fee": 2.675})
    assert (r["actual"], r["fee"]) == (10.15, 2.68), r                                          # 實付與手續費各自 half-up 到分
    ln = MP.lines_of(conn, a["id"])[0]
    assert (ln["amount"], ln["fee"]) == (10.15, 2.68)
    assert _o(conn, "L1")["paidAmount"] == 10.15 and r["remaining"] == 989.85                 # 投影與剩餘額也是兩位 half-up（1000 − 10.15）；手續費不能大於實付，所以實付取 10.145
