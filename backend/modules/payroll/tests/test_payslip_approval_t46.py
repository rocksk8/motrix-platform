# -*- coding: utf-8 -*-
"""第 46 班 P1：勞報單送審／簽核狀態機（設計 PAYSLIP-APPROVAL-T45.md §2、§3、§5、§9）。
草稿 ─送審→ 待審核 ─簽核→ 已核准（沒設簽核層＝送審即核准）；退回＝回草稿；匯出只准核准之後且**不需要付款日**；通知不含金額。"""
import json

import pytest

from modules.payroll.api import payslips as payslips_api
from modules.payroll.tests.test_payslip_edit_guard_2026_08_28 import _auth, _insert_payslip, _login, _payload

_MAKE_USER_DEFAULT_ROLE = "superadmin"


@pytest.fixture(autouse=True)
def _archive_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(payslips_api, "_archive_dir", lambda: str(tmp_path / "payslip_archive"))


def _q(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _x(sql, args=()):
    import db
    c = db.get_db()
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def _flow(*tiers):
    """勞報單簽核流程（獨立一條 `payslip_approval_flow`）；`tiers`＝每層的帳號清單；不給 ⇒ 沒設層。"""
    val = {"includeSubmitterManagerTier": False, "tiers": [{"order": i, "approvers": [{"username": u, "display_name": u} for u in t]} for i, t in enumerate(tiers)]}
    _x("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
       ("payslip_approval_flow", json.dumps(val), "2031-01-01T00:00:00"))


def _clear_flow():
    _x("DELETE FROM system_settings WHERE key='payslip_approval_flow'")


def _su(client, make_user, name):
    u, p = make_user(username=name, role="superadmin")
    return u, _auth(_login(client, u, p))


def _status(no):
    return _q("SELECT status FROM payslips WHERE slip_no=?", (no,))[0]["status"]


def test_migration_registered_and_columns_and_link_table(client):
    import importlib
    import sqlite3
    m = importlib.import_module("modules.payroll.migrations.0004_payslip_approval")
    c = sqlite3.connect(":memory:")
    assert "不存在" in m.up(c)
    c.execute("CREATE TABLE payslips (id INTEGER PRIMARY KEY, slip_no TEXT, status TEXT)")
    c.execute("INSERT INTO payslips (slip_no, status) VALUES ('舊', '已付款')")
    assert m.up(c) is None and m.up(c) is None                                        # 冪等
    row = c.execute("SELECT status, approval_json, planned_pay_date, approved_at, approved_by FROM payslips").fetchone()
    assert row == ("已付款", "", "", "", ""), "舊列不變、新欄預設空"
    assert c.execute("SELECT COUNT(*) FROM payslip_dispatch_links").fetchone()[0] == 0
    cols = {r["name"] for r in _q("PRAGMA table_info(payslips)")}
    assert {"approval_json", "planned_pay_date", "approved_at", "approved_by"} <= cols
    assert _q("SELECT name FROM sqlite_master WHERE name='payslip_dispatch_links'")


def test_draft_cannot_be_exported_and_no_payment_date_is_ever_needed(client, make_user):
    _clear_flow()
    _, h = _su(client, make_user, "ps46_a")
    _insert_payslip("PS-203101-001")
    assert client.post("/api/payslips/PS-203101-001/export", headers=h).status_code == 409
    r = client.post("/api/payslips/PS-203101-001/submit", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "已核准", "沒設簽核層 ⇒ 送審即核准"
    r = client.post("/api/payslips/PS-203101-001/export", headers=h)                    # 不帶任何日期
    assert r.status_code == 200, r.text
    assert _status("PS-203101-001") == "已匯出"
    row = _q("SELECT payment_date, approved_by, approved_at FROM payslips WHERE slip_no='PS-203101-001'")[0]
    assert row["payment_date"] == "" and row["approved_by"] and row["approved_at"]


def test_multi_tier_flow_review_approve_and_edit_locks(client, make_user):
    ua, ha = _su(client, make_user, "ps46_req")
    ub, hb = _su(client, make_user, "ps46_t1")
    uc, hc = _su(client, make_user, "ps46_t2")
    _flow([ub], [uc])
    _insert_payslip("PS-203101-002")
    assert client.post("/api/payslips/PS-203101-002/submit", headers=ha).json() == {"ok": True, "status": "待審核", "tierCount": 2}
    assert client.put("/api/payslips/PS-203101-002", json=_payload(), headers=ha).status_code == 409           # 待審核鎖定
    assert client.delete("/api/payslips/PS-203101-002", headers=ha).status_code == 400
    assert client.post("/api/payslips/PS-203101-002/export", headers=ha).status_code == 409                     # 未核准不可匯出
    assert client.post("/api/payslips/PS-203101-002/approve", headers=hc).status_code in (400, 403, 409), "第 2 層不能搶先簽"
    r = client.post("/api/payslips/PS-203101-002/approve", headers=hb)
    assert r.status_code == 200 and r.json()["status"] == "待審核"
    r = client.post("/api/payslips/PS-203101-002/approve", headers=hc)
    assert r.status_code == 200 and r.json()["status"] == "已核准"
    assert client.put("/api/payslips/PS-203101-002", json=_payload(), headers=ha).status_code == 409           # 核准後鎖定
    hist = json.loads(_q("SELECT approval_json FROM payslips WHERE slip_no='PS-203101-002'")[0]["approval_json"])["history"]
    assert [x["action"] for x in hist] == ["submit", "approve", "approve"]
    assert client.post("/api/payslips/PS-203101-002/approve", headers=hc).status_code == 409                    # 已核准不可再簽


def test_reject_needs_reason_returns_to_draft_keeps_history_and_resubmit(client, make_user):
    ua, ha = _su(client, make_user, "ps46_req2")
    ub, hb = _su(client, make_user, "ps46_t1b")
    _flow([ub])
    _insert_payslip("PS-203101-003")
    client.post("/api/payslips/PS-203101-003/submit", headers=ha)
    assert client.post("/api/payslips/PS-203101-003/reject", headers=hb, json={}).status_code == 400
    r = client.post("/api/payslips/PS-203101-003/reject", headers=hb, json={"reason": "金額不對"})
    assert r.status_code == 200 and r.json()["status"] == "草稿"
    assert client.put("/api/payslips/PS-203101-003", json=_payload(41000), headers=ha).status_code == 200      # 回草稿可改
    hist = json.loads(_q("SELECT approval_json FROM payslips WHERE slip_no='PS-203101-003'")[0]["approval_json"])["history"]
    assert [x["action"] for x in hist] == ["submit", "reject"] and hist[-1]["comment"] == "金額不對"
    assert client.post("/api/payslips/PS-203101-003/submit", headers=ha).json()["status"] == "待審核", "重送"


def test_chain_with_non_superadmin_is_400_and_status_unchanged(client, make_user):
    ua, ha = _su(client, make_user, "ps46_req3")
    make_user(username="ps46_plain", role="user")
    _flow(["ps46_plain"])
    _insert_payslip("PS-203101-004")
    r = client.post("/api/payslips/PS-203101-004/submit", headers=ha)
    assert r.status_code == 400 and "最高管理者" in r.text and _status("PS-203101-004") == "草稿"


def test_non_superadmin_cannot_submit_approve_reject(client, make_user):
    _clear_flow()
    _insert_payslip("PS-203101-005")
    u, p = make_user(username="ps46_user", role="user")
    h = _auth(_login(client, u, p))
    for path, body in (("submit", {}), ("approve", {}), ("reject", {"reason": "x"})):
        assert client.post("/api/payslips/PS-203101-005/%s" % path, headers=h, json=body).status_code in (401, 403), path
    assert _status("PS-203101-005") == "草稿"


def test_put_and_create_cannot_set_status(client, make_user):
    """原本 PUT／POST 會採用前端送來的 data.status（可把單據直接寫成已付款）；第 46 班起狀態只由專用端點改。"""
    _clear_flow()
    _, h = _su(client, make_user, "ps46_b")
    _insert_payslip("PS-203101-006")
    body = _payload()
    body["data"]["status"] = "已付款"
    assert client.put("/api/payslips/PS-203101-006", json=body, headers=h).status_code == 200
    assert _status("PS-203101-006") == "草稿"
    r = client.post("/api/payslips", json=dict(body, contractor_id=None), headers=h)
    if r.status_code == 201:
        assert _status(r.json()["slip_no"]) == "草稿"


def test_approved_can_be_voided_with_reason_but_draft_and_review_cannot(client, make_user):
    ua, ha = _su(client, make_user, "ps46_req4")
    ub, hb = _su(client, make_user, "ps46_t1c")
    _clear_flow()
    _insert_payslip("PS-203101-007")
    assert client.post("/api/payslips/PS-203101-007/void", headers=ha, json={"reason": "x"}).status_code == 409        # 草稿不可作廢
    client.post("/api/payslips/PS-203101-007/submit", headers=ha)
    assert client.post("/api/payslips/PS-203101-007/void", headers=ha, json={}).status_code == 400                     # 原因必填
    assert client.post("/api/payslips/PS-203101-007/void", headers=ha, json={"reason": "重開"}).status_code == 200
    assert _status("PS-203101-007") == "已作廢"
    _flow([ub])
    _insert_payslip("PS-203101-008")
    client.post("/api/payslips/PS-203101-008/submit", headers=ha)
    assert client.post("/api/payslips/PS-203101-008/void", headers=ha, json={"reason": "x"}).status_code == 409        # 待審核要先退回


def test_queue_provider_lists_review_items_without_money_or_person(client, make_user):
    from modules.payroll.api import payslip_approval as PA
    ua, ha = _su(client, make_user, "ps46_req5")
    ub, hb = _su(client, make_user, "ps46_t1d")
    _flow([ub])
    _insert_payslip("PS-203101-009", gross=87654)
    client.post("/api/payslips/PS-203101-009/submit", headers=ha)
    import db
    c = db.get_db()
    try:
        items = PA.queue_items(c)
    finally:
        c.close()
    mine = [i for i in items if i["quoteNo"] == "PS-203101-009"]
    assert len(mine) == 1 and mine[0]["type"] == "payslip" and mine[0]["approveUrl"].endswith("/approve")
    blob = json.dumps(mine[0], ensure_ascii=False)
    assert "87654" not in blob and "87,654" not in blob and "測試承攬人" not in blob
    r = client.get("/api/approval-queue", headers=hb)
    assert r.status_code == 200, r.text
    its = [it for g in r.json()["queue"] for it in g["items"]]
    assert any(i.get("quoteNo") == "PS-203101-009" for i in its), "簽核人的待我簽核佇列看得到"
    cnt = client.get("/api/approval-queue/count", headers=hb).json()
    assert any(i.get("quoteNo") == "PS-203101-009" for i in cnt["items"]), "角標也算進去"


def test_notifications_result_words_no_money_no_self_notice(client, make_user, monkeypatch):
    from helpers import email_notify as en
    sent = []

    class _S:
        outcome = en.SEND_SENT

        def wait(self, timeout=None):
            return self.outcome

    monkeypatch.setattr(en, "_async_send", lambda to, subject, html: sent.append((sorted(to), subject, html)) or _S())
    ua, ha = _su(client, make_user, "ps46_req6")
    ub, hb = _su(client, make_user, "ps46_t1e")
    _x("UPDATE users SET email=? WHERE username=?", ("ps46_t1e@example.com", ub))
    _x("UPDATE users SET email=? WHERE username=?", ("ps46_req6@example.com", ua))
    _flow([ub])
    _insert_payslip("PS-203101-010", gross=76543)
    client.post("/api/payslips/PS-203101-010/submit", headers=ha)
    assert any("待審核" in s[1] and "PS-203101-010" in s[1] for s in sent), [s[1] for s in sent]
    client.post("/api/payslips/PS-203101-010/approve", headers=hb)
    assert any("已核准" in s[1] and "PS-203101-010" in s[1] for s in sent if s[0] == ["ps46_req6@example.com"]), "送審人收到結果"
    for to, subj, html in sent:
        assert "76543" not in html and "76,543" not in html and "NT$" not in html and "測試承攬人" not in html
    notes = _q("SELECT type, message, link FROM notifications WHERE message LIKE '%PS-203101-010%'")
    assert {n["type"] for n in notes} >= {"payslip_submitted", "payslip_approved"}
    assert all(n["link"].startswith("payslips.html?q=PS-203101-010") or n["link"].startswith("cashier.html") for n in notes)
    # 自核：唯一簽核人＝送審人本人 ⇒ 不寄給自己
    sent.clear()
    _flow([ua])
    _insert_payslip("PS-203101-011")
    client.post("/api/payslips/PS-203101-011/submit", headers=ha)
    r = client.post("/api/payslips/PS-203101-011/approve", headers=ha)
    assert r.status_code in (200, 403)
    assert not any(s[0] == ["ps46_req6@example.com"] and "已核准" in s[1] and "PS-203101-011" in s[1] for s in sent), "送審人＝簽核人不寄給自己"
