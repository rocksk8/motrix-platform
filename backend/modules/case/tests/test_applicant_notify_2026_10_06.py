# -*- coding: utf-8 -*-
"""第44班（使用者裁示）：核准結果通知申請人——
 ① 主旨與內文標題一律寫出結果（支出申請／材料申請／承攬派發：待審核／輪到您審核／已核准／已退回／待付款／已付款），同一單據不同事件的主旨不可相同；
 ② 補齊申請人信：舊式簡單額外支出（approved／returned；其餘事件不寄）、額外支出變更（核准／駁回）、完工單核准、獎金分潤核准；單號都在主旨；信內不放金額；
 ③ 站內通知訊息帶單號與連結、沒有金額；送審即核准也有站內通知；
 ④ 我的申請有「單號」欄（docCode，沒有就 #id）。
寄信用 monkeypatch `_async_send` 攔截（不碰 SMTP）。"""
import json

import pytest

import db
from helpers import email_notify as en
from modules.case import expense_notify as XN
from modules.case import material_notify as MN
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W, _body, _login  # noqa: F401

pytestmark = pytest.mark.filterwarnings("ignore")


@pytest.fixture
def sent(monkeypatch):
    box = []

    class _H:
        def wait(self, timeout=None):
            return en.SEND_SENT

    monkeypatch.setattr(en, "_async_send", lambda to, subject, html: box.append((sorted(to), subject, html)) or _H())
    return box


def _user(make_user, name="an_user", role="engineer"):
    make_user(username=name, role=role)
    cn = db.get_db()
    try:
        cn.execute("UPDATE users SET email=? WHERE username=?", (name + "@example.test", name))
        cn.commit()
    finally:
        cn.close()
    return name


def _row(kind, code, status="已核准"):
    cn = db.get_db()
    try:
        cur = cn.execute("INSERT INTO case_extra_expenses (quote_no, category, description, total_cost, expense_date, status, created_at, updated_at, kind, doc_code, lines_json, created_by)"
                         " VALUES ('', '雜費', '測試', 100, '2026-10-06', ?, '2026-10-06T00:00:00', '2026-10-06T00:00:00', ?, ?, '[]', 'an_user')", (status, kind, code))
        cn.commit()
        return cn.execute("SELECT * FROM case_extra_expenses WHERE id=?", (cur.lastrowid,)).fetchone(), cn
    except Exception:
        cn.close()
        raise


# ── ① 結果寫在主旨與標題 ───────────────────────────────────────────────

def test_expense_subjects_state_the_outcome_and_differ_per_event(client, make_user, sent):
    u = _user(make_user)
    row, cn = _row("purchase_req", "PR-20261006-0001")
    try:
        XN.fire("submitted", cn, row, approvers=[u])
        XN.fire("next_tier", cn, row, approvers=[u], tier_no=2, total_tiers=3)
        XN.fire("approved", cn, row, requester=u, payable=False)
        XN.fire("returned", cn, row, requester=u, reason="缺附件")
        XN.fire("paid", cn, row, requester=u)
    finally:
        cn.close()
    subs = [s for _, s, _ in sent]
    ident = "請購單 PR-20261006-0001"
    for want, s in zip(("待審核", "輪到您審核", "已核准", "已退回", "已付款"), subs):
        assert s.endswith("%s %s" % (ident, want)), (want, s)
    assert len(set(subs)) == len(subs), subs                      # 同一張單的五個事件，主旨兩兩不同
    html_ok = [h for _, s, h in sent if s.endswith("已核准")][0]
    assert ident + " 已核准" in html_ok, "內文標題（事由）也要寫出結果"
    assert "NT$" not in html_ok


def test_material_and_dispatch_subjects_state_the_outcome(client, make_user, sent):
    u = _user(make_user)
    info = {"docCode": "MA-1", "quoteNo": "Q-1", "itemName": "線材"}
    MN.fire("submitted", info, approvers=[u])
    MN.fire("next_tier", info, approvers=[u], tier_no=2, total_tiers=2)
    MN.fire("approved", info, requester=u)
    MN.fire("returned", info, requester=u, reason="x")
    MN.fire_payment("approved", info, requester=u)
    MN.fire_change("returned", info, requester=u, reason="x")
    from modules.subcontract import dispatch_notify as DN
    cn = db.get_db()
    try:
        cn.execute("INSERT INTO vendor_contractors (name, created_at, updated_at) VALUES ('甲','2026-10-06','2026-10-06')")
        cur = cn.execute("INSERT INTO contractor_dispatches (quote_no, vendor_id, dispatch_date, scope, items_json, total_amount, status, doc_code, created_at, updated_at)"
                         " VALUES ('Q-1', 1, '2026-10-06', 'amount', '[]', 100, 'draft', 'DN-1', '2026-10-06', '2026-10-06')")
        cn.commit()
        row = cn.execute("SELECT * FROM contractor_dispatches WHERE id=?", (cur.lastrowid,)).fetchone()
    finally:
        cn.close()
    DN.fire("dispatch", "submitted", row, "甲", approvers=[u])
    DN.fire("dispatch", "approved", row, "甲", requester=u)
    DN.fire("dispatch", "returned", row, "甲", requester=u, reason="x")
    DN.fire("completion", "approved", row, "甲", requester=u)
    subs = [s for _, s, _ in sent]
    words = ("待審核", "輪到您審核", "已核准", "已退回", "已核准", "已退回", "待審核", "已核准", "已退回", "已核准")
    assert len(subs) == len(words), subs
    for w, s in zip(words, subs):
        assert s.endswith(" " + w), (w, s)
    assert subs[0] != subs[2] != subs[3], subs                    # 同一張單不同事件，主旨不同


# ── ② 補齊申請人信 ─────────────────────────────────────────────────────

def test_simple_extra_expense_mails_the_applicant_only_on_approved_and_returned(client, make_user, sent):
    u = _user(make_user)
    row, cn = _row("", "")
    try:
        assert XN.fire("submitted", cn, row, approvers=[u]) is False
        assert XN.fire("next_tier", cn, row, approvers=[u], tier_no=1, total_tiers=2) is False
        assert XN.fire("paid", cn, row, requester=u) is False
        assert sent == []                                            # 舊行為：這些事件不寄
        assert XN.fire("approved", cn, row, requester=u, payable=True) is True       # payable=True 也只寄申請人，不寄出納（舊式簡單額外支出走原本的待付款）
        assert XN.fire("returned", cn, row, requester=u, reason="缺憑證") is True
    finally:
        cn.close()
    assert [(to, s.split("－", 1)[1]) for to, s, _ in sent] == [(["an_user@example.test"], "支出申請 #%d 已核准" % row["id"]),
                                                                (["an_user@example.test"], "支出申請 #%d 已退回" % row["id"])], sent
    assert all("NT$" not in h for _, _, h in sent)


def test_change_request_approved_and_rejected_mail_the_applicant(client, make_user, sent):
    u = _user(make_user)
    row, cn = _row("travel", "TR-20261006-0001")
    try:
        assert XN.fire_change("approved", cn, row, requester=u) is True
        assert XN.fire_change("returned", cn, row, requester=u, reason="金額不符") is True
        assert XN.fire_change("approved", cn, row, requester="") is False         # 沒有申請人 ⇒ 不寄
    finally:
        cn.close()
    subs = [s for _, s, _ in sent]
    assert subs[0].endswith("TR-20261006-0001 變更已核准") and subs[1].endswith("TR-20261006-0001 變更已駁回"), subs
    assert "金額不符" in sent[1][2] and all("NT$" not in h for _, _, h in sent)


def test_completion_note_approved_mails_the_applicant_with_the_note_number(client, make_user, sent):
    u = _user(make_user)
    assert XN.fire_completion_approved("CN-20261006-0001", "Q-1", "客", u) is True
    assert XN.fire_completion_approved("CN-1", "Q-1", "客", "") is False
    (to, subject, html), = sent
    assert to == ["an_user@example.test"] and subject.endswith("完工單 CN-20261006-0001 已核准") and "NT$" not in html


# ── ③ 站內通知：單號＋連結＋沒有金額 ─────────────────────────────────────

def test_in_app_row_for_a_submit_time_auto_approval_has_the_doc_number_link_and_no_amount(W):
    c, h = W
    r = c.post("/api/quotations/%s/extra-expenses" % NO, headers=h,
               json=_body("purchase_order", [{"summary": "線材", "qty": 1, "unitCost": 700, "amount": 700, "categoryName": "料件"}]))
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    assert c.post("/api/quotations/%s/extra-expenses/%d/submit" % (NO, eid), headers=h).status_code == 200
    cn = db.get_db()
    try:
        code = cn.execute("SELECT doc_code FROM case_extra_expenses WHERE id=?", (eid,)).fetchone()["doc_code"]
        rows = cn.execute("SELECT * FROM notifications WHERE type='extra_expense_approved' AND ref_id=?", (str(eid),)).fetchall()
    finally:
        cn.close()
    assert len(rows) == 1, [dict(x) for x in rows]
    assert code and code in rows[0]["message"] and "已核准" in rows[0]["message"] and "NT$" not in rows[0]["message"], rows[0]["message"]
    got = c.get("/api/notifications/mine", headers=h).json()["items"]
    me = [i for i in got if i["type"] == "extra_expense_approved"]
    assert me and me[0].get("link") == "payment-request.html?tab=mine", me


# ── ④ 我的申請有單號欄 ──────────────────────────────────────────────────

def test_my_requests_list_has_a_doc_number_column_and_the_api_returns_the_code(W):
    from core import source_tree
    c, h = W
    r = c.post("/api/quotations/%s/extra-expenses" % NO, headers=h,
               json=_body("purchase_order", [{"summary": "線材", "qty": 1, "unitCost": 700, "amount": 700, "categoryName": "料件"}]))
    eid = r.json()["id"]
    mine = c.get("/api/extra-expenses/mine", headers=h).json()
    mine_row = next(x for x in mine if x["id"] == eid)
    assert mine_row["docCode"], mine_row
    html = source_tree.page_file("payment-request.html").read_text(encoding="utf-8")
    assert "<th>單號</th>" in html and "e.docCode || ('#' + e.id)" in html and 'data-doc-code' in html


# ── ② 變更申請：真的走 API 核准／駁回，申請人收到信（不只直接呼叫 fire_change）──────────────

def test_change_request_api_approve_and_reject_mail_the_applicant(W, make_user, sent):
    from modules.case.tests.test_purchase_item_lines_2026_10_02 import _set_tiers
    c, h = W
    cn = db.get_db()
    try:
        cn.execute("UPDATE users SET email='pl_sa@example.test' WHERE username='pl_sa'")
        cn.commit()
    finally:
        cn.close()
    ap_u, ap_p = make_user(username="chg_approver", role="admin")
    ap_h = _login(c, ap_u, ap_p)
    ap_id = db.get_db().execute("SELECT id FROM users WHERE username=?", (ap_u,)).fetchone()["id"]
    base = "/api/quotations/%s/extra-expenses" % NO
    eid = c.post(base, headers=h, json=_body("purchase_order", [{"summary": "線材", "qty": 1, "unitCost": 700, "amount": 700, "categoryName": "料件"}])).json()["id"]
    assert c.post("%s/%d/submit" % (base, eid), headers=h).status_code == 200            # 沒簽核層 ⇒ 送審即核准
    _set_tiers([{"order": 0, "approvers": [{"userId": ap_id, "username": ap_u, "displayName": "簽核人"}]}])
    code = db.get_db().execute("SELECT doc_code FROM case_extra_expenses WHERE id=?", (eid,)).fetchone()["doc_code"]
    sent.clear()
    for verb, word in (("approve", "變更已核准"), ("reject", "變更已駁回")):
        r = c.put("%s/%d/change-request" % (base, eid), headers=h, json={"description": "改" + verb, "lines": [{"summary": "線材", "qty": 1, "unitCost": 800, "amount": 800, "categoryName": "料件"}]})
        assert r.status_code == 200, r.text
        assert c.post("%s/%d/change-request/submit" % (base, eid), headers=h).status_code == 200
        sent.clear()
        r = c.post("%s/%d/change-request/%s" % (base, eid, verb), headers=ap_h, json={"reason": "金額不符"})
        assert r.status_code == 200, r.text
        mine = [s for to, s, _ in sent if to == ["pl_sa@example.test"] and s.endswith("%s %s" % (code, word))]   # superadmin 也會收到管理員活動信，只認申請人信
        assert len(mine) == 1, (verb, [s for _, s, _ in sent])
