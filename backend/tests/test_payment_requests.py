"""API-level integration tests for 請款單 (payment_requests) — mirrors the
existing invoice_vouchers design (frozen snapshot + remaining-quota
over-collection guard), see routers/payment_requests.py docstring."""
import json


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _use_no_tier_flow(client, token):
    """submit()/setting_to_active_tiers() defaults to auto-including a
    'submitter's department manager' first tier (includeSubmitterManagerTier
    defaults True) — the test users here have no department assigned, so that
    would raise UnresolvedManagerError. Explicitly configure the (now unified)
    approval flow with no tiers and that default off, matching how a fresh
    deployment reaches the documented no-tier superadmin-approves-anything
    fallback."""
    r = client.put(
        "/api/settings/approval-flow", headers=_auth(token),
        json={"tiers": [], "includeSubmitterManagerTier": False},
    )
    assert r.status_code == 200, r.text


def _make_quotation(quote_no, total=100000, pretax=95238, items=None):
    import db
    conn = db.get_db()
    try:
        data_json = json.dumps({
            "dealTag": "已成案",
            "items": items if items is not None else [
                {"id": 1, "description": "測試品項A", "brand": "", "qty": 2, "unit": "式",
                 "unitPrice": 47619, "amount": 95238},
            ],
            "paymentTerms": "訂金 30%，尾款 70%",
            "deliveryTerms": "簽約後 30 個工作天",
        })
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", total, pretax, data_json,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"),
        )
        conn.commit()
    finally:
        conn.close()


def test_create_payment_request_by_amount(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-PR-001")

    r = client.post(
        "/api/payment-requests", headers=_auth(token),
        json={"quote_no": "MQ-PR-001", "scope": "amount", "stage": "deposit", "amount": 30000},
    )
    assert r.status_code == 201, r.text
    request_no = r.json()["request_no"]
    assert request_no.startswith("PR-")

    detail = client.get(f"/api/payment-requests/{request_no}", headers=_auth(token))
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["amount"] == 30000
    assert body["status"] == "草稿"
    # terms pre-filled from the quotation at creation time
    assert body["terms"]["paymentTerms"] == "訂金 30%，尾款 70%"


def test_create_payment_request_by_ratio_pct(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-PR-002", total=100000, pretax=95238)

    r = client.post(
        "/api/payment-requests", headers=_auth(token),
        json={"quote_no": "MQ-PR-002", "scope": "amount", "stage": "deposit", "ratio_pct": 30},
    )
    assert r.status_code == 201, r.text
    request_no = r.json()["request_no"]

    body = client.get(f"/api/payment-requests/{request_no}", headers=_auth(token)).json()
    assert body["amount"] == 30000  # 100000 * 30%
    assert body["ratioPct"] == 30


def test_payment_request_blocks_overcollection(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-PR-003", total=100000, pretax=95238)

    r1 = client.post(
        "/api/payment-requests", headers=_auth(token),
        json={"quote_no": "MQ-PR-003", "scope": "amount", "stage": "deposit", "ratio_pct": 60},
    )
    assert r1.status_code == 201, r1.text

    r2 = client.post(
        "/api/payment-requests", headers=_auth(token),
        json={"quote_no": "MQ-PR-003", "scope": "amount", "stage": "final", "ratio_pct": 50},
    )
    assert r2.status_code == 409, r2.text


def test_payment_request_remaining_reflects_drafts(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-PR-004", total=100000, pretax=95238)

    client.post(
        "/api/payment-requests", headers=_auth(token),
        json={"quote_no": "MQ-PR-004", "scope": "amount", "stage": "deposit", "ratio_pct": 40},
    )
    r = client.get("/api/payment-requests/remaining", headers=_auth(token), params={"quote_no": "MQ-PR-004"})
    assert r.status_code == 200, r.text
    info = r.json()
    assert info["requestedAmount"] == 40000
    assert info["remainingAmount"] == 60000


def test_payment_request_full_approval_cycle_no_tiers(client, make_user):
    # No-tier fallback requires a *different* superadmin to approve than the
    # requester (check_no_tier_self_approval) — the seeded 'demo' showcase
    # account (helpers.init_demo_account(), role=superadmin) already satisfies
    # "another superadmin exists", so a single requester/approver would be
    # correctly blocked; use two real superadmins to exercise the normal path.
    requester_username, requester_password = make_user(username="requester", role="superadmin")
    approver_username, approver_password = make_user(username="approver", role="superadmin")
    requester_token = _login(client, requester_username, requester_password)
    approver_token = _login(client, approver_username, approver_password)
    _use_no_tier_flow(client, requester_token)
    _make_quotation("MQ-PR-005", total=100000, pretax=95238)

    r = client.post(
        "/api/payment-requests", headers=_auth(requester_token),
        json={"quote_no": "MQ-PR-005", "scope": "amount", "stage": "deposit", "amount": 50000},
    )
    request_no = r.json()["request_no"]

    sub = client.post(f"/api/payment-requests/{request_no}/submit", headers=_auth(requester_token))
    assert sub.status_code == 200, sub.text
    assert sub.json()["status"] == "待審核"

    appr = client.post(f"/api/payment-requests/{request_no}/approve", headers=_auth(approver_token))
    assert appr.status_code == 200, appr.text
    assert appr.json()["allDone"] is True

    body = client.get(f"/api/payment-requests/{request_no}", headers=_auth(requester_token)).json()
    assert body["status"] == "已核准"


def test_payment_request_delete_only_allowed_in_draft(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _use_no_tier_flow(client, token)
    _make_quotation("MQ-PR-006", total=100000, pretax=95238)

    r = client.post(
        "/api/payment-requests", headers=_auth(token),
        json={"quote_no": "MQ-PR-006", "scope": "amount", "stage": "deposit", "amount": 10000},
    )
    request_no = r.json()["request_no"]
    client.post(f"/api/payment-requests/{request_no}/submit", headers=_auth(token))

    d = client.delete(f"/api/payment-requests/{request_no}", headers=_auth(token))
    assert d.status_code == 409, d.text


def test_payment_request_terms_editable_only_in_draft(client, make_user):
    # /terms（單獨改條款）端點已被整頁編輯介面用的統一 PUT /api/payment-requests/
    # {request_no} 取代（見 routers/payment_requests.py update_payment_request()），
    # 這裡改用新端點，其餘「僅草稿可改」的行為驗證不變。
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _use_no_tier_flow(client, token)
    _make_quotation("MQ-PR-007", total=100000, pretax=95238)

    r = client.post(
        "/api/payment-requests", headers=_auth(token),
        json={"quote_no": "MQ-PR-007", "scope": "amount", "stage": "deposit", "amount": 10000},
    )
    request_no = r.json()["request_no"]

    ok = client.put(
        f"/api/payment-requests/{request_no}", headers=_auth(token),
        json={
            "scope": "amount", "stage": "deposit", "amount": 10000,
            "terms": {"paymentTerms": "改為分四期付款", "deliveryTerms": "", "acceptanceTerms": "", "warrantyTerms": ""},
        },
    )
    assert ok.status_code == 200, ok.text
    body = client.get(f"/api/payment-requests/{request_no}", headers=_auth(token)).json()
    assert body["terms"]["paymentTerms"] == "改為分四期付款"

    client.post(f"/api/payment-requests/{request_no}/submit", headers=_auth(token))
    blocked = client.put(
        f"/api/payment-requests/{request_no}", headers=_auth(token),
        json={
            "scope": "amount", "stage": "deposit", "amount": 10000,
            "terms": {"paymentTerms": "應該被擋下", "deliveryTerms": "", "acceptanceTerms": "", "warrantyTerms": ""},
        },
    )
    assert blocked.status_code == 409, blocked.text


def test_payment_request_appears_in_unified_approval_queue(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _use_no_tier_flow(client, token)
    _make_quotation("MQ-PR-008", total=100000, pretax=95238)

    r = client.post(
        "/api/payment-requests", headers=_auth(token),
        json={"quote_no": "MQ-PR-008", "scope": "amount", "stage": "deposit", "amount": 20000},
    )
    request_no = r.json()["request_no"]
    client.post(f"/api/payment-requests/{request_no}/submit", headers=_auth(token))

    q = client.get("/api/approval-queue", headers=_auth(token))
    assert q.status_code == 200, q.text
    all_items = [item for group in q.json()["queue"] for item in group["items"]]
    matches = [i for i in all_items if i["quoteNo"] == request_no]
    assert len(matches) == 1, all_items
    assert matches[0]["type"] == "payment_request"
    assert matches[0]["linkedQuoteNo"] == "MQ-PR-008"

    # /count only tracks per-user pending-tier turns (not the no-tier
    # superadmin-open fallback used by this test), so it stays 0 here — this
    # just confirms the endpoint tolerates payment_requests rows without error.
    count = client.get("/api/approval-queue/count", headers=_auth(token))
    assert count.status_code == 200, count.text
