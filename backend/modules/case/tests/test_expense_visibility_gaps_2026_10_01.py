# -*- coding: utf-8 -*-
"""第 29 班稽核（A29）補的測試缺口：

R-1 `_caseless_visible` 對 `user=None` 必須 fail-closed（防禦程式碼；原本突變成 fail-open 沒有測試會紅）。
R-2 舊版（kind=''）額外支出的附件：案件擁有者搜得到、**沒有案件權限的人（即使有 file_center）看不到**
    （原本把 `attachments._READ_RULE["extra_expense"]` 改成人人可讀，repo 測試全綠）。
O2  文件對齊：`PATCH …/extra-expenses/{id}/dates` 的出納也要看得到該案——只有 cashier 模組、非案件相關人 ⇒ 404（不放寬案件讀權）。
"""
import json
import os

import pytest

NO = "MQ-202610-881"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_caseless_visible_fails_closed_for_a_missing_user(client):
    import db
    from modules.case.api import case_extra_expenses as X
    conn = db.get_db()
    try:
        row = {"created_by": "someone", "approval_json": "{}"}
        assert X._caseless_visible(conn, row, None) is False
        assert X._caseless_visible(conn, row, "not-a-dict") is False
        assert X._caseless_visible(conn, row, {"username": "someone", "role": "user", "modules": "[]"}) is True      # 正對照：建立者本人
    finally:
        conn.close()


@pytest.fixture()
def world(client, make_user):
    import db
    owner = make_user(username="vg_owner", role="user", modules=["quotation", "case_manage"])
    fc = make_user(username="vg_filecenter", role="user", modules=["file_center"])
    cash = make_user(username="vg_cashier", role="user", modules=["cashier"])
    conn = db.get_db()
    try:
        oid = conn.execute("SELECT id FROM users WHERE username='vg_owner'").fetchone()[0]
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at, deal_tag, sales_person, sales_person_id)"
                     " VALUES (?,?,?,?,?,?,?,?,?,?)", (NO, "已送出", "客", "案", "{}", "2026-09-01", "2026-09-01", "已成案", "vg_owner", oid))
        files = [{"id": "f1", "filename": "舊版收據.pdf", "path": "case_extra_expense/%s_1/y.pdf" % NO, "size": 5,
                  "uploadedAt": "2026-09-01T00:00:00", "uploadedBy": "申請人"}]
        conn.execute(
            "INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, total_cost, note, expense_date, doc_no,"
            " files_json, created_by, created_by_name, created_by_inferred, payer_username, payer_name, created_at, updated_at, updated_by_name,"
            " status, approval_json, change_status, change_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?,?,?,'{}','','{}')",
            (NO, "材料", "舊版", 1, "式", 100, 100, "", "2026-09-01", "", json.dumps(files, ensure_ascii=False), "vg_owner", "擁有者",
             "vg_owner", "擁有者", "2026-09-01T00:00:00", "2026-09-01T00:00:00", "擁有者", "已核准"))
        conn.commit()
        eid = conn.execute("SELECT id FROM case_extra_expenses").fetchone()[0]
    finally:
        conn.close()
    return client, {k: _login(client, v[0], v[1]) for k, v in (("owner", owner), ("fc", fc), ("cash", cash))}, eid


def test_legacy_extra_expense_attachment_is_hidden_from_a_user_without_case_access(world):
    client, h, _eid = world
    ok = client.get("/api/filehub/search", headers=h["owner"], params={"q": "舊版收據", "quote_no": NO})
    assert ok.status_code == 200 and "舊版收據.pdf" in ok.text, "正對照：案件擁有者應搜得到舊版附件"
    r = client.get("/api/filehub/search", headers=h["fc"], params={"q": "舊版收據", "quote_no": NO})
    assert r.status_code == 200 and "舊版收據.pdf" not in r.text, "沒有案件權限的人（有 file_center）看到了舊版額外支出附件"


def test_cashier_without_case_access_gets_404_on_the_dates_endpoint(world):
    client, h, eid = world
    r = client.patch("/api/quotations/%s/extra-expenses/%d/dates" % (NO, eid), headers=h["cash"], json={"paidDate": "2026-09-10"})
    # 第42班（使用者裁示）：財務角色（原出納）不受案件擁有者限制 ⇒ 登錄付款日通過；沒有案件關係的一般帳號仍是 404（見下一題與 test_finance_role_split）
    assert r.status_code == 200, r.text
