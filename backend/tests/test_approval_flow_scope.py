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
    # 2026-09-11 新增 extra_expense（案件額外支出送審）、2026-09-12 新增 completion
    # （完工單）。兩者預設 True＝跟著統一流程走，要獨立就在設定頁把它取消勾選。
    #
    # 🔴 **2026-09-23 改寫，而原本那個「完整相等」的意圖要留著**
    #
    # 原本寫 `assert scope == {...}`，註解逐字說那是**刻意的**：
    # 「新增類型時一定要回來確認它的預設分組是不是你要的，而不是讓它悄悄
    #   跟著統一流程走」。
    # ⚠️ 而 `AS2` 加了第八個（voucher）、`BN8` 馬上要加第九個
    #    ⇒ 它會**在每一次正常擴充時變紅**，而那種守門最後會被改成不擋任何東西。
    #
    # 🔑 ⇒ 不是放寬成子集合，是**把那個意圖做成一張登記表**：
    # ```
    # ① 登記過的每一個 key，值要一模一樣   <= 既有的不可以被改掉
    # ② 回應裡**每一個 key 都要登記過**     <= 新增類型仍然會紅
    # ```
    # ⇒ 新增一個類型時要做的事**沒有變**（回來確認它的預設分組），
    #   而修法從「改一個字面 dict」變成「在登記表加一行並寫下預期」。
    EXPECTED_SCOPE = {
        "quotation": True, "shipping": True, "invoice_voucher": True,
        "payment_request": True, "contractor_voucher": False,
        "extra_expense": True, "completion": True,
    }
    for key, want in EXPECTED_SCOPE.items():
        assert key in scope, f"既有的文件類型 {key} 從 scope 裡消失了：{scope}"
        assert scope[key] is want, (
            f"{key} 的預設分組被改掉了（{scope[key]}，原本 {want}）——\n"
            "☠️ 那會靜默改變那一類單據走哪一條簽核流程。")
    extra = sorted(set(scope) - set(EXPECTED_SCOPE))
    assert not extra, (
        f"有 {len(extra)} 個文件類型沒有登記：{extra}\n"
        "📌 新增類型時**一定要回來確認它的預設分組是不是你要的** ——\n"
        "   而不是讓它悄悄跟著統一流程走。\n"
        "⇒ 請在上面的 EXPECTED_SCOPE 加一行，並寫下你要的預設值。")

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


def test_round_trip_switch_does_not_clobber_custom_independent_flow(client, make_user):
    """2026-08-28 code review finding: re-toggling a doc type unified→independent
    a second time must NOT overwrite content the admin already configured for its
    independent flow in the meantime — only the transition into a still-blank
    independent flow should seed from the current unified content."""
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)

    scope = client.get("/api/settings/approval-flow-scope", headers=_auth(token)).json()

    # unified flow starts out with content A
    content_a = {"includeSubmitterManagerTier": False,
                 "tiers": [{"order": 0, "approvers": [{"userId": 1, "username": "alice", "displayName": "alice"}]}]}
    r = client.put("/api/settings/approval-flow", headers=_auth(token), json=content_a)
    assert r.status_code == 200, r.text

    # 1st switch to independent: seeds from content A
    scope1 = dict(scope); scope1["shipping"] = False
    r = client.put("/api/settings/approval-flow-scope", headers=_auth(token), json=scope1)
    assert r.status_code == 200, r.text
    assert r.json()["seededFromUnified"] == ["shipping"]

    # admin now customizes shipping's OWN independent flow directly — content B
    content_b = {"includeSubmitterManagerTier": True,
                 "tiers": [{"order": 0, "approvers": [{"userId": 2, "username": "bob", "displayName": "bob"}]}]}
    r = client.put("/api/settings/approval-flow/shipping", headers=_auth(token), json=content_b)
    assert r.status_code == 200, r.text

    # unified flow changes to content C in the meantime
    content_c = {"includeSubmitterManagerTier": False,
                 "tiers": [{"order": 0, "approvers": [{"userId": 3, "username": "carol", "displayName": "carol"}]}]}
    r = client.put("/api/settings/approval-flow", headers=_auth(token), json=content_c)
    assert r.status_code == 200, r.text

    # switch shipping back to unified, then back to independent again
    scope2 = dict(scope1); scope2["shipping"] = True
    r = client.put("/api/settings/approval-flow-scope", headers=_auth(token), json=scope2)
    assert r.status_code == 200, r.text
    assert r.json()["seededFromUnified"] == []  # was already unified->unified is a no-op transition

    scope3 = dict(scope2); scope3["shipping"] = False
    r = client.put("/api/settings/approval-flow-scope", headers=_auth(token), json=scope3)
    assert r.status_code == 200, r.text
    # must NOT re-seed — shipping's own key already has real (non-empty) content
    assert r.json()["seededFromUnified"] == []

    r = client.get("/api/settings/approval-flow/shipping", headers=_auth(token))
    assert r.status_code == 200, r.text
    shipping_flow = r.json()
    # still content B (bob), not re-seeded to content C (carol)
    assert shipping_flow["tiers"][0]["approvers"][0]["username"] == "bob"
    assert shipping_flow["includeSubmitterManagerTier"] is True


def test_scope_put_requires_all_fields(client, make_user):
    """A partial/empty body must 422, not silently fall back to per-field
    defaults and reset an admin's already-customized scope (2026-08-28 code
    review finding)."""
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    r = client.put("/api/settings/approval-flow-scope", headers=_auth(token), json={})
    assert r.status_code == 422, r.text
    r = client.put("/api/settings/approval-flow-scope", headers=_auth(token), json={"quotation": False})
    assert r.status_code == 422, r.text


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
