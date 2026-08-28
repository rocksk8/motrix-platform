"""簽核流程套用範圍（2026-08-28，見 MOTRIX-ERP-QUICK.md §12 同日 changelog）：
五種文件類型（報價單／出貨單／發票開立簽核單／請款單／承攬商匯款申請）可各自
勾選要走 unified_approval_flow 還是自己的 {doc_type}_approval_flow，覆蓋預設分組、
切換時的複製起點行為、以及權限限制。"""


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_scope_defaults_and_editing(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)

    # 1) default scope: 4 unified, contractor_voucher independent
    r = client.get("/api/settings/approval-flow-scope", headers=_auth(token))
    assert r.status_code == 200, r.text
    scope = r.json()
    assert scope == {
        "quotation": True, "shipping": True, "invoice_voucher": True,
        "payment_request": True, "contractor_voucher": False,
    }, scope

    # 2) put some tiers into the unified flow
    unified_payload = {
        "includeSubmitterManagerTier": False,
        "tiers": [{"order": 0, "approvers": [
            {"userId": 1, "username": username, "displayName": username}
        ]}],
    }
    r = client.put("/api/settings/approval-flow", headers=_auth(token), json=unified_payload)
    assert r.status_code == 200, r.text

    # 3) contractor_voucher is independent by default — its own key should start empty
    r = client.get("/api/settings/approval-flow/contractor_voucher", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["tiers"] == []

    # 4) switch quotation from unified -> independent: should be SEEDED from
    #    the current unified content (per the chosen default behavior)
    new_scope = dict(scope)
    new_scope["quotation"] = False
    r = client.put("/api/settings/approval-flow-scope", headers=_auth(token), json=new_scope)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["seededFromUnified"] == ["quotation"], body

    r = client.get("/api/settings/approval-flow/quotation", headers=_auth(token))
    assert r.status_code == 200, r.text
    quotation_flow = r.json()
    assert quotation_flow["tiers"][0]["approvers"][0]["username"] == username
    assert quotation_flow["includeSubmitterManagerTier"] is False

    # 5) unified flow itself must be untouched by the switch
    r = client.get("/api/settings/approval-flow", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["tiers"][0]["approvers"][0]["username"] == username

    # 6) switching quotation back to unified should NOT re-seed anything
    #    (only unified->independent seeds) and should not wipe its own key
    new_scope2 = dict(new_scope)
    new_scope2["quotation"] = True
    r = client.put("/api/settings/approval-flow-scope", headers=_auth(token), json=new_scope2)
    assert r.status_code == 200, r.text
    assert r.json()["seededFromUnified"] == []

    r = client.get("/api/settings/approval-flow/quotation", headers=_auth(token))
    assert r.json()["tiers"][0]["approvers"][0]["username"] == username  # untouched, just unused now


def test_scope_requires_superadmin(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    r = client.put(
        "/api/settings/approval-flow-scope", headers=_auth(token),
        json={"quotation": False, "shipping": True, "invoice_voucher": True,
              "payment_request": True, "contractor_voucher": False},
    )
    assert r.status_code == 403, r.text


def test_unknown_doc_type_rejected(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    r = client.get("/api/settings/approval-flow/not_a_real_type", headers=_auth(token))
    assert r.status_code == 404, r.text
