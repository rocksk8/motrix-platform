# -*- coding: utf-8 -*-
"""31-A S2：寫入口的閘——狀態只能經 `dispatch_flow.set_status`（G-D1）；建立忽略 status、編輯不能改狀態、審核前不能往下推、
驗收人≠建立者、取消規則、刪除守門、實質編輯要重新送審；舊單（approval_status=''）每個閘都照舊。"""
import json
import os
import re

import pytest

import db

pytestmark = pytest.mark.no_dispatch_shim

NOW = "2026-10-01T10:00:00"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def W(client, make_user):
    h = {n: _login(client, *make_user(username=n, role=r)) for n, r in (("da_sa", "superadmin"), ("da_a", "admin"), ("da_b", "admin"), ("da_f", "finance"))}
    c = db.get_db()
    c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at) VALUES ('MQ-DA-1','已送出','客','案','{}',?,?)", (NOW, NOW))
    c.commit()
    c.close()
    return client, h


_N = [900]


def _code():
    _N[0] += 1
    return "DP-20261001-%04d" % _N[0]


def _mk(status="draft", approval="草稿", completion="", created_by="da_a", items=None, vendor=None, voucher=False):
    doc = _code() if approval else ""
    c = db.get_db()
    try:
        cur = c.execute("INSERT INTO contractor_dispatches (quote_no, vendor_id, status, items_json, personnel_json, total_amount, tax_rate, created_by, created_at, updated_at,"
                        " approval_status, completion_status, doc_code) VALUES ('MQ-DA-1',?,?,?,'[{\"id\": 1, \"name\": \"甲\", \"amount\": 100}]',1000,0.05,?,?,?,?,?,?)",
                        (vendor, status, json.dumps(items if items is not None else [{"description": "x", "amount": 1000}]), created_by, NOW, NOW, approval, completion, doc))
        did = cur.lastrowid
        if voucher:
            c.execute("INSERT INTO contractor_payment_vouchers (voucher_no, dispatch_id, quote_no, status, snapshot_json, data_json, created_by, created_at, updated_at)"
                      " VALUES (?,?, 'MQ-DA-1','草稿','{}','{}','x',?,?)", ("PV-DA-%d" % did, did, NOW, NOW))
        c.commit()
        return did
    finally:
        c.close()


def _row(did):
    c = db.get_db()
    try:
        return dict(c.execute("SELECT * FROM contractor_dispatches WHERE id=?", (did,)).fetchone())
    finally:
        c.close()


def _body(**kw):
    b = {"quote_no": "MQ-DA-1", "vendor_id": None, "items_json": [{"description": "x", "amount": 1000}],
         "personnel_json": [{"id": 1, "name": "甲", "amount": 100}], "tax_rate": 0.05}
    b.update(kw)
    return b


# ── 建立／編輯 ──────────────────────────────────────────────────────────────

def test_create_ignores_status_and_issues_sequential_codes(W):
    client, h = W
    codes = []
    for st in ("completed", "accepted", "draft"):
        r = client.post("/api/contractor-dispatches", headers=h["da_a"], json=_body(status=st))
        assert r.status_code == 201, r.text
        d = r.json()
        assert d["status"] == "draft" and d["approvalStatus"] == "草稿" and re.match(r"^DP-\d{8}-\d{4}$", d["docCode"])
        codes.append(d["docCode"])
        row = _row(d["id"])
        assert row["status"] == "draft" and row["approval_status"] == "草稿" and row["doc_code"] == d["docCode"]
    assert len(set(codes)) == 3 and codes == sorted(codes)


def test_put_cannot_change_status_but_same_status_is_fine(W):
    client, h = W
    did = _mk()
    r = client.put("/api/contractor-dispatches/%d" % did, headers=h["da_a"], json=_body(status="completed"))
    assert r.status_code == 400 and "操作按鈕" in r.json()["detail"]
    assert _row(did)["status"] == "draft"
    assert client.put("/api/contractor-dispatches/%d" % did, headers=h["da_a"], json=_body(status="draft", notes="可以改備註")).status_code == 200
    assert _row(did)["notes"] == "可以改備註"


@pytest.mark.parametrize("approval, completion", [("待審核", ""), ("簽核中", ""), ("已核准", "待審核"), ("已核准", "簽核中")])
def test_put_is_blocked_while_any_stage_is_under_review(W, approval, completion):
    client, h = W
    did = _mk(status="accepted" if completion else "draft", approval=approval, completion=completion)
    r = client.put("/api/contractor-dispatches/%d" % did, headers=h["da_a"], json=_body(notes="x"))
    assert r.status_code == 409 and "審核中" in r.json()["detail"]
    assert _row(did)["notes"] != "x"


def test_substantive_edit_requires_resubmit_but_notes_do_not(W, approval="已核准"):
    """已核准的派發：實質欄位有變 ⇒ 重新送審（回草稿）。舊單（''）不重設——使用者裁示 S-1，見 test_dispatch_legacy_edit_2026_10_02。"""
    client, h = W
    did = _mk(status="sent", approval=approval)
    r = client.put("/api/contractor-dispatches/%d" % did, headers=h["da_a"], json=_body(status="sent", notes="只改備註", invoice_no="AB12345678"))
    assert r.status_code == 200 and r.json()["needsResubmit"] is False and _row(did)["approval_status"] == approval          # 非實質：不動
    # 第42班（Q5）：改金額＝財務角色；admin 改金額 ⇒ 403（反向探針），財務角色 ⇒ 200 且需重送審
    r = client.put("/api/contractor-dispatches/%d" % did, headers=h["da_a"], json=_body(status="sent", items_json=[{"description": "x", "amount": 9999}]))
    assert r.status_code == 403
    r = client.put("/api/contractor-dispatches/%d" % did, headers=h["da_f"], json=_body(status="sent", items_json=[{"description": "x", "amount": 9999}]))
    assert r.status_code == 200 and r.json()["needsResubmit"] is True
    row = _row(did)
    assert row["approval_status"] == "草稿" and row["approved_hash"] == "" and re.match(r"^DP-\d{8}-\d{4}$", row["doc_code"])
    # 作業狀態因此被審核閘擋住：不能再往下推
    assert client.post("/api/contractor-dispatches/%d/status" % did, headers=h["da_b"], json={"target": "confirmed"}).status_code == 409


def test_tax_rate_change_is_substantive(W):
    client, h = W
    did = _mk(status="draft", approval="已核准")
    assert client.put("/api/contractor-dispatches/%d" % did, headers=h["da_a"], json=_body(tax_rate=0.0)).status_code == 403     # 第42班（Q5）：稅率＝財務角色
    r = client.put("/api/contractor-dispatches/%d" % did, headers=h["da_f"], json=_body(tax_rate=0.0))
    assert r.json()["needsResubmit"] is True


# ── 閘：審核前不能往下推；舊單照舊 ───────────────────────────────────────────────

@pytest.mark.parametrize("approval, ok", [("草稿", False), ("待審核", False), ("簽核中", False), ("已退回", False), ("已核准", True), ("", True)])
def test_approval_gate_on_work_status(W, approval, ok):
    client, h = W
    did = _mk(approval=approval)
    r = client.post("/api/contractor-dispatches/%d/status" % did, headers=h["da_b"], json={"target": "sent"})
    assert (r.status_code == 200) is ok, (approval, r.status_code, r.text)
    assert _row(did)["status"] == ("sent" if ok else "draft")


def test_completed_can_never_be_set_directly(W):
    client, h = W
    from modules.subcontract import dispatch_flow as F
    for approval in ("已核准", ""):
        did = _mk(status="accepted", approval=approval)
        r = client.post("/api/contractor-dispatches/%d/status" % did, headers=h["da_sa"], json={"target": "completed"})
        assert r.status_code == 409 and "完工審核" in r.json()["detail"], r.text
        assert _row(did)["status"] == "accepted"
    c = db.get_db()
    try:
        row = c.execute("SELECT * FROM contractor_dispatches WHERE id=?", (did,)).fetchone()
        with pytest.raises(F.FlowError):
            F.set_status(c, row, "completed", {"username": "x", "role": "superadmin"})                     # 函式層也擋
        F.set_status(c, row, "completed", {"username": "x", "role": "admin"}, via_completion=True)         # 唯一的通路
        assert c.execute("SELECT status FROM contractor_dispatches WHERE id=?", (did,)).fetchone()[0] == "completed"
    finally:
        c.close()


@pytest.mark.parametrize("cur, tgt, ok", [("draft", "sent", True), ("draft", "pending_acceptance", True), ("sent", "confirmed", True), ("confirmed", "pending_acceptance", True),
                                          ("pending_acceptance", "accepted", True), ("draft", "accepted", False), ("sent", "draft", False), ("accepted", "sent", False),
                                          ("completed", "cancelled", False), ("cancelled", "draft", False), ("draft", "bogus", False)])
def test_transition_table(W, cur, tgt, ok):
    client, h = W
    did = _mk(status=cur, approval="已核准", created_by="da_a")
    r = client.post("/api/contractor-dispatches/%d/status" % did, headers=h["da_b"], json={"target": tgt})
    assert (r.status_code == 200) is ok, (cur, tgt, r.status_code, r.text)


# ── 驗收人≠建立者 ───────────────────────────────────────────────────────────

def test_acceptance_needs_someone_other_than_the_creator(W):
    client, h = W
    did = _mk(status="pending_acceptance", approval="已核准", created_by="da_a")
    r = client.patch("/api/contractor-dispatches/%d/accept" % did, headers=h["da_a"], json={"action": "accepted"})
    assert r.status_code == 409 and "職責分離" in r.json()["detail"] and _row(did)["status"] == "pending_acceptance"
    r = client.patch("/api/contractor-dispatches/%d/accept" % did, headers=h["da_b"], json={"action": "accepted"})
    assert r.status_code == 200
    row = _row(did)
    assert row["status"] == "accepted" and row["accepted_by"] and row["accepted_at"]
    # 最高管理者是建立者時可例外，稽核標註
    did2 = _mk(status="pending_acceptance", approval="", created_by="da_sa")
    assert client.patch("/api/contractor-dispatches/%d/accept" % did2, headers=h["da_sa"], json={"action": "accepted"}).status_code == 200
    rows = db.get_db().execute("SELECT detail FROM audit_log WHERE action='vendor.dispatch.accepted' ORDER BY id").fetchall()
    assert "同人驗收" in rows[-1]["detail"]


def test_legacy_accept_flow_unchanged(W):
    client, h = W
    did = _mk(status="draft", approval="", created_by="old_user")
    assert client.patch("/api/contractor-dispatches/%d/accept" % did, headers=h["da_b"], json={"action": "pending_acceptance"}).status_code == 200
    assert client.patch("/api/contractor-dispatches/%d/accept" % did, headers=h["da_b"], json={"action": "accepted"}).status_code == 200
    assert client.patch("/api/contractor-dispatches/%d/accept" % did, headers=h["da_b"], json={"action": "accepted"}).status_code == 409          # 來源狀態限制照舊


# ── 取消／刪除 ──────────────────────────────────────────────────────────────

def test_cancel_rules(W):
    client, h = W

    def cancel(did, who="da_b", **b):
        return client.post("/api/contractor-dispatches/%d/status" % did, headers=h[who], json={"target": "cancelled", **b})
    a = _mk(status="sent", approval="已核准")
    assert cancel(a).status_code == 400 and _row(a)["status"] == "sent"                                      # 已核准要理由
    assert cancel(a, reason="客戶取消").status_code == 200
    row = _row(a)
    assert row["status"] == "cancelled" and row["cancel_reason"] == "客戶取消" and row["cancelled_at"]
    assert cancel(_mk(status="draft", approval="草稿")).status_code == 200                                    # 草稿不必理由
    v = _mk(status="accepted", approval="已核准", voucher=True)
    assert cancel(v, reason="x").status_code == 403 and _row(v)["status"] == "accepted"                      # 已有匯款申請：admin 不行
    assert cancel(v, "da_sa", reason="處理完申請").status_code == 200
    assert cancel(_mk(status="sent", approval="")).status_code == 200                                         # 舊單、未進驗收：照舊不需理由


@pytest.mark.parametrize("approval, code", [("待審核", 409), ("簽核中", 409), ("已核准", 409), ("草稿", 200), ("已退回", 200), ("", 200)])
def test_delete_guard(W, approval, code):
    client, h = W
    did = _mk(approval=approval)
    r = client.delete("/api/contractor-dispatches/%d" % did, headers=h["da_a"])
    assert r.status_code == code, (approval, r.status_code, r.text)


# ── G-D1：只有 set_status 寫狀態 ─────────────────────────────────────────────

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _py_files():
    for dp, _dn, fns in os.walk(_ROOT):
        if "tests" in dp.split(os.sep) or "__pycache__" in dp:
            continue
        for fn in fns:
            if fn.endswith(".py"):
                yield os.path.join(dp, fn)


def status_writes(src):
    """原始碼裡把 contractor_dispatches 的 `status`（作業狀態）寫成值的 SQL（不含 approval_status／completion_status）。"""
    out = []
    for m in re.finditer(r"UPDATE\s+contractor_dispatches\s+SET\s+(.*?)(?:WHERE|\"\s*\)|\"\s*,|$)", src, re.S | re.I):
        if re.search(r"(?<![A-Za-z_])status\s*=", m.group(1)):
            out.append(m.group(0)[:80])
    for m in re.finditer(r"INSERT\s+INTO\s+contractor_dispatches\s*\((.*?)\)", src, re.S | re.I):
        if re.search(r"(?<![A-Za-z_])status\b", m.group(1)):
            out.append(m.group(0)[:80])
    return out


def test_g_d1_only_dispatch_flow_writes_the_work_status():
    offenders = {}
    for f in _py_files():
        hits = status_writes(open(f, encoding="utf-8").read())
        if hits and os.path.basename(f) != "dispatch_flow.py":
            offenders[os.path.relpath(f, _ROOT)] = hits
    # 唯一的例外：建立（INSERT）把 status 寫成字面常數 'draft'（不吃任何參數）
    unexpected = {k: v for k, v in offenders.items() if k != os.path.join("api", "vendor_contractors.py")}
    assert not unexpected, "這些檔案直接寫派發 status（要改走 dispatch_flow.set_status）：%s" % unexpected
    src = open(os.path.join(_ROOT, "api", "vendor_contractors.py"), encoding="utf-8").read()
    for m in re.finditer(r"UPDATE\s+contractor_dispatches\s+SET\s+([^\"]*)", src, re.I):
        assert not re.search(r"(?<![A-Za-z_])status\s*=", m.group(1)), "vendor_contractors 的 UPDATE 不可寫 status：%s" % m.group(0)[:80]
    ins = re.search(r"INSERT\s+INTO\s+contractor_dispatches.*?VALUES\s*\((.*?)\)\"", src, re.S)
    assert ins and "'draft'" in ins.group(1)                                                              # 建立固定寫 'draft'
    assert len([ln for ln in src.splitlines() if "body.status" in ln]) == 1                                  # body.status 只出現在「不能改狀態」的那一行比對


def test_g_d1_scanner_catches_known_violations():
    """正對照：掃描器抓得到各種寫法。"""
    assert status_writes('c.execute("UPDATE contractor_dispatches SET status=?, updated_at=? WHERE id=?", (a,b,c))')
    assert status_writes("c.execute('UPDATE contractor_dispatches SET notes=?, status = ? WHERE id=?')")
    assert status_writes('c.execute("INSERT INTO contractor_dispatches (quote_no, status) VALUES (?,?)")')
    assert not status_writes('c.execute("UPDATE contractor_dispatches SET approval_status=?, completion_status=? WHERE id=?")')
    assert not status_writes('c.execute("UPDATE contractor_dispatches SET files_json=? WHERE id=?")')
