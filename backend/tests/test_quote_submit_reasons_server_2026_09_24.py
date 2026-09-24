"""報價單送審的特殊條件由後端重算（2026-09-24，N13）。

使用者裁示：N13「要，後端重算」；R1「預設條款搬到後端當唯一來源」；R2「只看毛利率欄位」；
R3 項次照移植（含區段標題的位置）。

原本 approval.reasons 是前端 checkApproval() 算好帶上來的，後端照收 ⇒ 直接打 API
不帶 reasons（或帶假的），簽核人就看不到「低毛利」等特殊條件。

⚠️ 已知且使用者接受的限制（R2）：只看 `margin` 欄位——margin 可以假造，
搭配真實的低單價仍能隱瞞低毛利。
"""
import json

import pytest

from .test_case_extra_expenses_api_2026_09_11 import _set_empty_approval_flow


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _terms():
    from helpers.quote_terms import DEFAULT_TERMS
    return dict(DEFAULT_TERMS)


def _data(**over):
    d = {"customerName": "重算客戶", "projectName": "重算專案", "salesPerson": "",
         "quoteDate": "2026-09-24", "validDays": 30, "taxRate": 5,
         "showDiscount": False, "discount": 0,
         "tot": {"total": 1050, "pretax": 1000, "directMarginPct": 0, "netMarginPct": 0},
         "items": [{"description": "品項 A", "qty": 1, "cost": 700, "margin": 0.35,
                    "unitPrice": 1000, "amount": 1000}],
         "approval": {"status": "pending"}}
    d.update(_terms())
    d.update(over)
    return d


def _reasons(quote_no):
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    finally:
        conn.close()
    return json.loads(row["data_json"])["approval"]["reasons"]


@pytest.fixture
def token(client, make_user):
    _set_empty_approval_flow()
    u, p = make_user(username="n13_sales", role="admin")
    return _login(client, u, p)


def _create(client, token, data, status="待審核"):
    r = client.post("/api/quotations", headers=_auth(token), json={"status": status, "data": data})
    assert r.status_code == 201, r.text
    return r.json()["quote_no"]


# ── 直接打 API ─────────────────────────────────────────────────────────────

def test_low_margin_listed_even_if_client_sends_no_reasons(client, token):
    items = [{"type": "header", "description": "區段"},
             {"description": "低毛利", "qty": 1, "cost": 900, "margin": 0.2, "unitPrice": 1000, "amount": 1000}]
    no = _create(client, token, _data(items=items))
    assert "第 2 項毛利率 20.00% 低於 30%" in _reasons(no), "R3：項次照移植，含區段標題的位置"


def test_fake_client_reasons_are_replaced(client, token):
    items = [{"description": "低毛利", "qty": 1, "cost": 900, "margin": 0.1, "unitPrice": 1000, "amount": 1000}]
    no = _create(client, token, _data(items=items, validDays=60,
                                      approval={"status": "pending", "reasons": ["標準報價單送出"]}))
    rs = _reasons(no)
    assert "標準報價單送出" not in rs
    assert "第 1 項毛利率 10.00% 低於 30%" in rs
    assert "有效期限 60 天（超過 30 天）" in rs


def test_no_condition_gives_standard_reason(client, token):
    no = _create(client, token, _data(approval={"status": "pending", "reasons": ["假的原因"]}))
    assert _reasons(no) == ["標準報價單送出"]


def test_update_path_recomputes_on_submit(client, token):
    no = _create(client, token, _data(status="草稿"), status="草稿")
    r = client.put(f"/api/quotations/{no}", headers=_auth(token),
                   json={"status": "待審核", "data": _data(quoteNo=no, showDiscount=True, discount=12345.5,
                                                          approval={"status": "pending", "reasons": []})})
    assert r.status_code == 200, r.text
    assert "含折讓（NT$12,345.5）" in _reasons(no)


def test_delegate_line_uses_server_identity(client, token):
    appr = {"status": "pending", "delegateSubmitter": "n13_sales", "delegateSubmitterDisplay": "冒名",
            "delegateNote": "  出差代送  ", "reasons": []}
    no = _create(client, token, _data(salesPerson="王業務", approval=appr))
    rs = _reasons(no)
    assert rs[0] == "代理送出：由 n13_sales 代 王業務 送出，原因：出差代送", rs
    assert rs[1:] == ["標準報價單送出"]


def test_terms_changed_against_backend_defaults_and_presets(client, token):
    no = _create(client, token, _data(deliveryTerms="改過的交貨條件", taxRate=3))
    rs = _reasons(no)
    assert "調整營業稅額為 3%（標準 5%）" in rs
    assert "報價條件已修改，非預設內容（交貨條件）" in rs

    import db
    conn = db.get_db()
    try:
        preset = dict(_terms(), key="p1", name="純購料", afterSales="購料不含售後")
        conn.execute(
            "INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            ("quote_terms_presets", json.dumps({"presets": [preset], "defaultKey": ""}, ensure_ascii=False),
             "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()
    no2 = _create(client, token, _data(termsPresetKey="p1"))
    assert "報價條件已修改，與條款組「純購料」不同（售後服務）" in _reasons(no2)


# ── 唯一來源 ───────────────────────────────────────────────────────────────

def test_terms_defaults_endpoint_is_the_single_source(client, token):
    from helpers.quote_terms import DEFAULT_TERMS
    import routers.system as system
    r = client.get("/api/settings/quote-terms-defaults", headers=_auth(token))
    assert r.status_code == 200 and r.json() == DEFAULT_TERMS
    assert system.DEFAULT_PAYMENT_TERMS is DEFAULT_TERMS["paymentTerms"]
    assert client.get("/api/settings/quote-terms-defaults").status_code in (401, 403)


def test_frontend_no_longer_carries_its_own_copy():
    """前端不可以再有一份預設條款的內容（兩份分岔沒有任何地方會報錯）。"""
    from pathlib import Path
    from helpers.quote_terms import DEFAULT_TERMS
    src = (Path(__file__).resolve().parents[2] / "frontend" / "pages" / "quotation-form.html").read_text(encoding="utf-8")
    for k, v in DEFAULT_TERMS.items():
        first_line = v.splitlines()[0]
        assert first_line not in src, f"{k} 的內容仍寫死在前端"


# ── 移植細節（JS 行為）──────────────────────────────────────────────────────

@pytest.mark.parametrize("x,expected", [(28.125, "28.13"), (10.0, "10.00"), (29.995, "30.00"), (0.1 * 100, "10.00")])
def test_to_fixed_matches_js(x, expected):
    from helpers.quote_terms import _js_to_fixed
    assert _js_to_fixed(x, 2) == expected
