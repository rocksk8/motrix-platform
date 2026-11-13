# -*- coding: utf-8 -*-
"""T82 整合（2026-11-13）：報價單與估價單的 PDF「E-mail」都是業務員的「報價用公司信箱」（hichan-1 的我的帳號／quote_email 三層解析），
不是個人信箱；偽造的 salesEmail 被伺服器覆寫。估價單走同一條路徑（hichan-4：沒有第二個信箱來源）。"""
import json

import pytest

from helpers import quote_email as QE


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _snap(qno):
    from db import get_db
    conn = get_db()
    try:
        return json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (qno,)).fetchone()["data_json"])
    finally:
        conn.close()


@pytest.mark.parametrize("doc_type", ["quote", "estimate"])
def test_pdf_sales_email_is_the_per_user_company_email_for_quotes_and_estimates(client, make_user, doc_type):
    import pdf_gen
    from db import get_db
    su_u, su_p = make_user(username="t82qe_root_" + doc_type, role="superadmin")
    su = _login(client, su_u, su_p)
    u, p = make_user(username="t82qe_sales_" + doc_type, role="sales")
    conn = get_db()
    uid = conn.execute("SELECT id FROM users WHERE username=?", (u,)).fetchone()["id"]
    conn.execute("UPDATE users SET email=? WHERE username=?", ("personal-%s@gmail.com" % doc_type, u))
    conn.commit()
    conn.close()
    assert client.put(f"/api/users/{uid}", json={"quote_email": "sales-%s@corp.example" % doc_type}, headers=su).status_code == 200
    h = _login(client, u, p)
    data = {"customerName": "甲", "projectName": "專案", "quoteDate": "2026-11-13", "items": [{"description": "品項"}],
            "tot": {"total": 1000, "pretax": 952, "directMarginPct": 0, "netMarginPct": 0},
            "salesPerson": u, "salesPersonUsername": u, "docType": doc_type,
            "salesEmail": "forged@evil.example"}                            # 客戶端偽造 ⇒ 伺服器覆寫成三層解析的結果
    r = client.post("/api/quotations", headers=h, json={"data": data, "status": "草稿"})
    assert r.status_code in (200, 201), r.text
    qno = r.json().get("quote_no") or r.json().get("quoteNo")
    snap = _snap(qno)
    assert snap["salesEmail"] == "sales-%s@corp.example" % doc_type, snap["salesEmail"]
    assert snap.get("docType", "quote") == doc_type
    assert QE.reply_to_for_quote(qno) == "sales-%s@corp.example" % doc_type
    html = pdf_gen._build_quote_html(snap, snap.get("tot") or data["tot"])
    assert "sales-%s@corp.example" % doc_type in html                     # PDF 印的是報價用公司信箱
    assert "personal-%s@gmail.com" % doc_type not in html and "forged@evil.example" not in html
    assert ("估　價　單" in html) == (doc_type == "estimate")             # 同一份 PDF 的標題隨類型（確認走的真的是對應類型）
