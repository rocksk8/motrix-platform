# -*- coding: utf-8 -*-
"""A2-7：費用單據（kind<>''）的通知信六種＋單據輸出（HTML／PDF）。

信：送審→當層簽核人、下一層、核准→申請人（需付款者另通知出納「待撥款」）、退回→申請人（含原因）、出納登錄付款→申請人；
信內**不放金額**；舊額外支出（kind=''）完全不寄（回歸）。輸出：版型取自單據釘住的定義、未核可每頁紅色標示、已核准無標示、
看不到的人 404（看不到＝不存在）、舊額外支出沒有版型 ⇒ 404。
"""
import json

import pytest

SENT = "/api/quotations/-/extra-expenses"
LINES = [{"category": "TRAVEL", "summary": "高鐵來回", "qty": 2, "unitCost": 745, "invoiceNo": "AB12345678"}]
DATA = {"applicant": "xo_req", "dept": 1, "req_date": "2026-10-01"}


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _x(sql, args=()):
    import db
    c = db.get_db()
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def _q(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _flow(tiers):
    _x("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
       ("unified_approval_flow", json.dumps({"tiers": tiers, "includeSubmitterManagerTier": False}), "2026-01-01T00:00:00"))


@pytest.fixture
def world(client, make_user, monkeypatch):
    from helpers import email_notify as en
    sent = []
    monkeypatch.setattr(en, "_async_send", lambda to, subject, html, *a, **k: sent.append({"to": list(to), "subject": subject, "html": html}))
    H, names = {}, {}
    for u, role, mods in (("xo_req", "sales", ["expense_forms"]), ("xo_mgr", "admin", None), ("xo_cash", "engineer", ["cashier", "finance"]),
                          ("xo_other", "sales", [])):
        name, pw = make_user(username=u, role=role, modules=mods)
        H[u] = _login(client, name, pw)
        names[u] = name
        _x("UPDATE users SET email=? WHERE username=?", ("%s@example.test" % u, name))
    _x("INSERT OR IGNORE INTO divisions (id, name, sort_order, created_at) VALUES (1, '營運處', 0, '2026-01-01T00:00:00')")
    _x("INSERT OR IGNORE INTO departments (id, division_id, name, sort_order, created_at) VALUES (1, 1, '工程部', 0, '2026-01-01T00:00:00')")
    _x("INSERT OR IGNORE INTO expense_categories (code, name, default_tax, active, sort, note) VALUES ('TRAVEL', '差旅', '', 1, 0, '')")
    return {"H": H, "sent": sent}


def _mails(sent, key_part):
    return [m for m in sent if key_part in m["subject"] or key_part in m["html"]]


def _has(sent, text, user):
    return any(text in m["html"] and "%s@example.test" % user in m["to"] for m in sent)


def _to(sent, user):
    return [m for m in sent if "%s@example.test" % user in m["to"]]


def test_mail_types_registered_and_in_prefs():
    from helpers import mail_types as mt
    for k in ("submitted", "next_tier", "approved", "returned", "payout_pending", "paid"):
        t = mt.get("expense_form_" + k)
        assert t is not None and t.owner == "case"


def test_auto_approve_then_payout_pending_and_paid_mails(client, world):
    H, sent = world["H"], world["sent"]
    _flow([])
    r = client.post(SENT, headers=H["xo_req"], json={"kind": "purchase_order", "data": DATA, "lines": LINES})
    assert r.status_code == 201, r.text
    eid, code = r.json()["id"], r.json()["docCode"]
    assert client.post("%s/%d/submit" % (SENT, eid), headers=H["xo_req"]).status_code == 200
    assert _has(sent, "採購單已核准", "xo_req") and _has(sent, "採購單待撥款", "xo_cash"), [m["subject"] for m in sent]
    assert any(code in m["html"] for m in _to(sent, "xo_req")) and _to(sent, "xo_cash")           # 申請人收核准、出納收待撥款
    n = len(sent)
    pay = client.post("/api/cashier/pending-payables/case/%d/pay" % eid, headers=H["xo_cash"],
                      json={"paidDate": "2026-10-02", "payTerms": "月結30天", "remitDate": "2026-10-02"})
    assert pay.status_code == 200, pay.text
    new = sent[n:]
    assert _has(new, "採購單已付款", "xo_req")
    for m in sent:                                                                                   # 信內不放金額
        assert "1,490" not in m["html"] and "1490" not in m["html"], m["subject"]


def test_requisition_is_not_payable_so_no_payout_mail(client, world):
    H, sent = world["H"], world["sent"]
    _flow([])
    eid = client.post(SENT, headers=H["xo_req"], json={"kind": "purchase_req", "data": DATA, "lines": LINES}).json()["id"]
    assert client.post("%s/%d/submit" % (SENT, eid), headers=H["xo_req"]).status_code == 200
    assert _has(sent, "請購單已核准", "xo_req")
    assert not any("待撥款" in m["html"] for m in sent)


def test_submit_next_tier_and_return_mails(client, world):
    H, sent = world["H"], world["sent"]
    uid = {u: _q("SELECT id, username FROM users WHERE username LIKE ?", ("%" + u,))[0] for u in ("xo_mgr",)}
    mgr = uid["xo_mgr"]
    _flow([{"order": 0, "approvers": [{"userId": mgr["id"], "username": mgr["username"], "displayName": "主管"}]}])
    eid = client.post(SENT, headers=H["xo_req"], json={"kind": "travel", "data": DATA, "lines": LINES}).json()["id"]
    assert client.post("%s/%d/submit" % (SENT, eid), headers=H["xo_req"]).status_code == 200
    assert _has(sent, "差旅費用請款單簽核申請", "xo_mgr"), [m["subject"] for m in sent]
    n = len(sent)
    rj = client.post("%s/%d/reject" % (SENT, eid), headers=H["xo_mgr"], json={"reason": "發票不清楚"})
    assert rj.status_code == 200, rj.text
    back = [m for m in sent[n:] if "差旅費用請款單被退回" in m["html"]]
    assert back and "xo_req@example.test" in back[0]["to"] and "發票不清楚" in back[0]["html"]


def test_legacy_kind_empty_sends_no_expense_form_mail(client, world):
    H, sent = world["H"], world["sent"]
    _flow([])
    _x("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
       " deal_tag, sales_person, assigned_user_ids) VALUES ('MQ-XO-1','已送出','c','p',1,1,'{}','2026-01-01T00:00:00','2026-01-01T00:00:00','已成案','','[]')")
    r = client.post("/api/quotations/MQ-XO-1/extra-expenses", headers=H["xo_mgr"],
                    json={"category": "差旅", "description": "舊流程", "qty": 1, "unitCost": 100})
    assert r.status_code == 201, r.text
    client.post("/api/quotations/MQ-XO-1/extra-expenses/%d/submit" % r.json()["id"], headers=H["xo_mgr"])
    assert not [m for m in sent if "費用單據" in m["html"] or "差旅費用請款單" in m["html"]]


# ── 輸出 ───────────────────────────────────────────────────────────────

def test_document_unapproved_banner_then_clean_and_visibility(client, world):
    H = world["H"]
    _flow([])
    r = client.post(SENT, headers=H["xo_req"], json={"kind": "travel", "data": DATA, "lines": LINES})
    eid, code = r.json()["id"], r.json()["docCode"]
    url = "%s/%d/document" % (SENT, eid)
    d = client.get(url, headers=H["xo_req"])
    assert d.status_code == 200, d.text
    assert code in d.text and "高鐵來回" in d.text and "尚未核可" in d.text          # 草稿＝未核可標示
    assert client.get(url, headers=H["xo_other"]).status_code == 404                    # 看不到＝不存在
    assert client.get(url, headers=H["xo_cash"]).status_code == 200                     # 出納／財務看得到
    assert client.post("%s/%d/submit" % (SENT, eid), headers=H["xo_req"]).status_code == 200      # 無簽核層 ⇒ 直接核准
    ok = client.get(url, headers=H["xo_req"])
    assert ok.status_code == 200 and "尚未核可" not in ok.text and "1,490" in ok.text            # 已核准：無標示、金額＝後端合計


def test_document_legacy_row_has_no_template(client, world):
    H = world["H"]
    _x("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
       " deal_tag, sales_person, assigned_user_ids) VALUES ('MQ-XO-2','已送出','c','p',1,1,'{}','2026-01-01T00:00:00','2026-01-01T00:00:00','已成案','','[]')")
    r = client.post("/api/quotations/MQ-XO-2/extra-expenses", headers=H["xo_mgr"],
                    json={"category": "差旅", "description": "舊流程", "qty": 1, "unitCost": 100})
    assert client.get("/api/quotations/MQ-XO-2/extra-expenses/%d/document" % r.json()["id"], headers=H["xo_mgr"]).status_code == 404


def test_document_pdf(client, world):
    H = world["H"]
    _flow([])
    eid = client.post(SENT, headers=H["xo_req"], json={"kind": "petty_cash", "data": DATA, "lines": LINES}).json()["id"]
    r = client.get("%s/%d/document?format=pdf" % (SENT, eid), headers=H["xo_req"])
    assert r.status_code == 200, r.text[:200]            # 這台沒有 Edge 時 PDF 端點回 503 ⇒ 題會紅（不 skip：skip 會遮蔽「PDF 出不來」）
    assert r.content[:5] == b"%PDF-" and len(r.content) > 1000


def test_document_visual_defects_regression(client, world):
    """視覺檢查（A2-7）找到的三個缺陷：草稿的類別顯示代碼、只填金額的列單價印 0、出納事後填的付款條件／匯款日印不出來。"""
    import re
    H = world["H"]
    _flow([])
    lines = [{"category": "TRAVEL", "summary": "高鐵", "qty": 2, "unitCost": 745},
             {"category": "TRAVEL", "summary": "只填金額的列", "amount": 3200}]
    r = client.post(SENT, headers=H["xo_req"], json={"kind": "purchase_order", "data": DATA, "lines": lines})
    eid = r.json()["id"]
    url = "%s/%d/document" % (SENT, eid)
    html = client.get(url, headers=H["xo_req"]).text
    assert "差旅" in html and ">TRAVEL<" not in html                                              # ① 草稿也顯示類別名稱
    row2 = re.search(r"只填金額的列.*?</tr>", html, re.S).group(0)
    cells = re.findall(r"<td[^>]*>(.*?)</td>", row2, re.S)
    assert "0" not in [c.strip() for c in cells]                                                  # ② 單價空白，不是 0
    assert "3,200" in row2
    assert client.post("%s/%d/submit" % (SENT, eid), headers=H["xo_req"]).status_code == 200
    pay = client.post("/api/cashier/pending-payables/case/%d/pay" % eid, headers=H["xo_cash"],
                      json={"paidDate": "2026-10-02", "payTerms": "月結30天", "remitDate": "2026-10-02"})
    assert pay.status_code == 200, pay.text
    after = client.get(url, headers=H["xo_req"]).text
    assert "月結30天" in after and "2026-10-02" in after                                           # ③ 出納填的欄位印得出來


def test_document_visibility_follows_the_amount_viewer_rule(client, world):
    """單據含金額 ⇒ 與列表同一條規則：申請人（data.applicant，不一定是建立者）看得到；無關者 404；建立者（管理員）看得到。"""
    H = world["H"]
    _flow([])
    mine = _q("SELECT username FROM users WHERE username LIKE '%xo_req'")[0]["username"]
    r = client.post(SENT, headers=H["xo_mgr"], json={"kind": "travel", "data": dict(DATA, applicant=mine), "lines": LINES})   # 管理員代開
    assert r.status_code == 201, r.text
    url = "%s/%d/document" % (SENT, r.json()["id"])
    assert client.get(url, headers=H["xo_req"]).status_code == 200          # 申請人（data.applicant，不是建立者）
    assert client.get(url, headers=H["xo_mgr"]).status_code == 200          # 建立者／管理員
    assert client.get(url, headers=H["xo_other"]).status_code == 404        # 無關者：看不到＝不存在
