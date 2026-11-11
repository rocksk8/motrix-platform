# -*- coding: utf-8 -*-
"""正式機 case.access_denied 48 筆的根因與修正（2026-11-11，T79 維運票）。

正式機資料（denial_report）：44/48 筆是 finance 角色（持 cashier＋case_manage）開「別人業務的已成案／已結案」案件頁，
同一秒 `case-bundle` 回 200——案件頁本體讀得到（CM14b：cashier＝讀取規則 scope="read"），但案件整包裡的
「完結案五關」（close-gates）、以及案件頁上順手載入的 PDF 版本清單、PDF 下載、材料申請審核摘要，
用的是擁有者規則 scope="owner" → 每次靜默被拒（bundle 的 parts 吞掉例外、頁面照常開，使用者看不出哪裡被擋）。

修正：這幾支**唯讀**端點改用與案件頁本體相同的讀取規則（可見範圍＝原單據，不寬也不嚴）。
本檔守：
① 財務（cashier）開別人的案件：五關、版本清單、材料審核摘要都 200，且**不再寫 case.access_denied**；
② 反向對照（牙齒）：沒有讀取資格的人（一般業務、只有 case_manage 的工程師）照舊 404——規則沒有被放太寬；
③ denial audit 現在記 method／path／role／case_manage（只加鍵，reason 照舊），下次不必再靠 server.log 對時。
"""
import json
import time

import pytest

from tests._requires import requires_module

needs_m01 = requires_module("case", "本題打 M01（案件）的端點")

NO = "MQ-READRULE-001"


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _seed(make_user):
    """別人業務的已成案案件（擁有者是另一位業務，測試使用者都不是擁有者）。"""
    import db
    owner = make_user(username="rr_owner", role="sales")
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        oid = conn.execute("SELECT id FROM users WHERE username=?", (owner[0],)).fetchone()[0]
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, sales_person_id, sales_person) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "客", "案", 100, 95, json.dumps({"dealTag": "已成案"}, ensure_ascii=False),
             now, now, "已成案", oid, "擁有者"))
        conn.commit()
    finally:
        conn.close()


def _denials():
    import db
    conn = db.get_db()
    try:
        return [json.loads(r["detail"]) | {"user": r["username"]}
                for r in conn.execute("SELECT username, detail FROM audit_log WHERE action='case.access_denied'")]
    finally:
        conn.close()


def _wait_denials(n, timeout=5.0):
    """audit 由背景執行緒寫：等到至少 n 筆（或逾時）。"""
    end = time.time() + timeout
    while time.time() < end:
        d = _denials()
        if len(d) >= n:
            return d
        time.sleep(0.1)
    return _denials()


READ_ONLY_ENDPOINTS = [
    "/api/quotations/{no}/close-gates",
    "/api/quotations/{no}/material-order-approvals",
    "/api/quotations/{no}/versions",
]


@needs_m01
def test_cashier_reader_gets_every_case_page_readonly_endpoint_and_no_denial_is_logged(client, make_user):
    u = make_user(username="rr_fin", role="finance", modules=["case_manage", "cashier"])
    _seed(make_user)
    h = _login(client, *u)
    for url in READ_ONLY_ENDPOINTS:
        r = client.get(url.format(no=NO), headers=h)
        assert r.status_code == 200, (url, r.status_code, r.text)
    b = client.get(f"/api/quotations/{NO}/case-bundle", headers=h).json()
    assert b["parts"]["health"]["ok"] is True, b["parts"]["health"]          # 五關那段不再被擋
    time.sleep(0.5)                                                           # 給背景 audit 寫入機會（若有）
    assert _denials() == [], "財務讀別人的案件頁不該再留下 case.access_denied"


@needs_m01
@pytest.mark.parametrize("role,modules", [("sales", None), ("engineer", ["case_manage"])])
def test_non_readers_are_still_denied(client, make_user, role, modules):
    """牙齒：沒有讀取資格（不是擁有者、沒有 cashier）的人，這幾支照舊 404——放寬的是『案件頁讀得到的人』，不是所有人。"""
    u = make_user(username=f"rr_no_{role}", role=role, modules=modules)
    _seed(make_user)
    h = _login(client, *u)
    assert client.get(f"/api/quotations/{NO}", headers=h).status_code == 404       # 前提：案件頁本體本來就讀不到
    for url in READ_ONLY_ENDPOINTS:
        assert client.get(url.format(no=NO), headers=h).status_code == 404, url


@needs_m01
def test_denial_audit_records_endpoint_and_role(client, make_user):
    u = make_user(username="rr_eng", role="engineer", modules=["case_manage"])
    _seed(make_user)
    h = _login(client, *u)
    assert client.get(f"/api/quotations/{NO}/close-gates", headers=h).status_code == 404
    d = _wait_denials(1)
    assert len(d) == 1, d
    assert d[0]["reason"] == "denied"
    assert d[0]["method"] == "GET" and d[0]["path"] == f"/api/quotations/{NO}/close-gates", d[0]
    assert d[0]["role"] == "engineer" and d[0]["case_manage"] is True, d[0]
    assert d[0]["user"] == "rr_eng"
