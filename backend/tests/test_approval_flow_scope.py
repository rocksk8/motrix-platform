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
        # 🔴 `AS2` 的第八個。**`False` ＝ 自己一條流程**（A `§234` 裁）。
        #    依據：**這個預設值是可逆的** —— 勾一下就合併；
        #    而反過來（預設合併之後要拆開）**要先有人發現它們被合在一起了**。
        #    🔑 猜錯的代價不對稱時，**先做可逆的那一邊**。
        "voucher": False,
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


#: 一份**完整**的 body。模型欄位全部必填（`routers/system.py:140`）。
#:
#: 🔴 **2026-09-23：`bonus`（第九個 doc type，`BN8`）落地，這裡純機械地
#:    跟著補一欄** —— 這兩題（權限、200 正對照）只在乎 body 完整不完整，
#:    不在乎每一欄的值是什麼。
#: ⚠️ **這裡的 `False` 不是業務裁定**，只是湊出一份能通過驗證的完整 body。
#:    `bonus` 真正的預設分組要登記在下面 `EXPECTED_SCOPE`，
#:    而那一格**不是我能自己決定的** —— A 會問使用者，這裡先留著紅。
FULL_SCOPE_BODY = {
    "quotation": False, "shipping": True, "invoice_voucher": True,
    "payment_request": True, "contractor_voucher": False,
    "completion": True, "extra_expense": True, "voucher": False,
    "bonus": False,
}


def test_scope_requires_superadmin(client, make_user):
    """非 superadmin 不可以改套用範圍。

    ## 🔴 2026-09-23：這一題本來可能拿到一個**假的 403**

    ```
    body 驗證跑在 _require_user(require_superadmin=True) **之前**
    ⇒ body 不完整時永遠是 422，永遠問不到權限那一層
    ```
    舊寫法只送 5 欄，而模型補成 8 欄那一天它就紅了 ——
    ⚠️ 而更危險的是**反方向**：假如題目寫的是
       `assert r.status_code != 200`，那麼權限守門**被拿掉也還是綠的**
       —— 422 自己就把這一題餧飽了。
    ⇒ 送一份**完整的** body，才問得到權限。
    """
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    r = client.put(
        "/api/settings/approval-flow-scope", headers=_auth(token),
        json=dict(FULL_SCOPE_BODY),
    )
    assert r.status_code == 403, (
        "期望 403，實際 %s：%s\n" % (r.status_code, r.text[:200])
        + "🔑 422 代表 body 被擋在權限檢查**之前** ——\n"
          "   那時這一題量到的不是權限，是欄位數。")


def test_scope_the_same_body_really_goes_through_for_a_superadmin(
        client, make_user):
    """⚙️ **正對照：上一題的 403 要來自身分，不是來自 body。**

    ☠️ 少了它，`FULL_SCOPE_BODY` 哪天又落後一欄，
       上一題會從 403 變 422 而**訊息讀起來像權限壞掉了**。
    🔑 同一份 body、同一個端點，**只換身分** ⇒ 差別只能是身分。
    """
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    r = client.put(
        "/api/settings/approval-flow-scope", headers=_auth(token),
        json=dict(FULL_SCOPE_BODY),
    )
    assert r.status_code == 200, (
        "最高管理者送同一份 body 也過不了（%s）：%s\n"
        % (r.status_code, r.text[:300])
        + "📌 這份 body 少了欄位的話，上一題的 403 是**假的** ——\n"
          "   請先把 `FULL_SCOPE_BODY` 補齊再看上一題。")


def test_unknown_doc_type_rejected(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    r = client.get("/api/settings/approval-flow/not_a_real_type", headers=_auth(token))
    assert r.status_code == 404, r.text
