"""額外支出「已核准後編輯＝變更申請」＋附件上鎖（2026-09-11 第二輪交辦）。

使用者交辦的兩件事，以及**明確指定的語意**：

1. 已核准之後**上傳照片上鎖**（原本刻意開放「補傳憑證」，這次被推翻）
2. 增加編輯按鈕，**編輯需要審核**，且「原核准金額不動，核准後才生效」

第 2 點是這一輪最容易做錯的地方——最直覺的做法是「把狀態退回草稿再改」，但那樣
人一按編輯，成本與報表數字當場就變了，簽核變成事後追認。所以下面每一個測試都在
守同一條線：**核准之前，本體的金額與附件完全沒被動過**。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import io
import json

from .test_case_extra_expenses_api_2026_09_11 import (  # noqa: F401  (fixtures reused)
    _auth, _base, _login, _make_case, _payload, _set_empty_approval_flow,
)
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


def _cbase(exp_id, no="MQ-XE-001"):
    return f"/api/quotations/{no}/extra-expenses/{exp_id}/change-request"


def _get_item(client, token, exp_id, no="MQ-XE-001"):
    items = client.get(_base(no), headers=_auth(token)).json()["items"]
    return next(i for i in items if i["id"] == exp_id)


def _approved_expense(client, token, no="MQ-XE-001", **over):
    """建一筆走完流程、真的變成「已核准」的額外支出（不是直接塞 DB）。"""
    _set_empty_approval_flow()          # 沒有簽核層 → 送審即核准
    exp_id = client.post(_base(no), headers=_auth(token), json=_payload(**over)).json()["id"]
    r = client.post(f"{_base(no)}/{exp_id}/submit", headers=_auth(token))
    assert r.json()["status"] == "已核准", r.text
    return exp_id


def _single_tier_flow(approver_username):
    """單層簽核流程，簽核人是指定的那個人。"""
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            ("unified_approval_flow",
             json.dumps({"includeSubmitterManagerTier": False,
                         "tiers": [{"order": 0, "approvers": [
                             {"username": approver_username,
                              "display_name": approver_username}]}]},
                        ensure_ascii=False),
             "2026-01-01T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()


# ── 附件上鎖 ────────────────────────────────────────────────────────────────

def test_approved_expense_rejects_file_upload(client, make_user):
    """已核准 → 附件上鎖（使用者交辦第 1 項）。

    這條是**刻意的行為反轉**：2026-09-11 第一輪時開放核准後補傳憑證，理由是
    「補憑證是會計常態」。使用者推翻了它——核准當下簽核人看到的憑證，跟事後被
    換掉的憑證不是同一份。所以擋下來，並把補憑證的路徑改成變更申請。
    """
    username, password = make_user(username="xec_lock1", role="superadmin")
    token = _login(client, username, password)
    _make_case()
    exp_id = _approved_expense(client, token)

    r = client.post(f"{_base()}/{exp_id}/files", headers=_auth(token),
                    files={"files": ("invoice.png", io.BytesIO(b"\x89PNG\r\n\x1a\n fake"), "image/png")})
    assert r.status_code == 409, r.text
    assert "上鎖" in r.json()["detail"], "錯誤訊息要指向變更申請這條路，不能只說不可修改"


def test_draft_expense_still_accepts_file_upload(client, make_user):
    """草稿照樣可以傳——上鎖只針對已核准，不是把附件整個關掉。"""
    username, password = make_user(username="xec_lock2", role="superadmin")
    token = _login(client, username, password)
    _make_case()
    exp_id = client.post(_base(), headers=_auth(token), json=_payload()).json()["id"]

    r = client.post(f"{_base()}/{exp_id}/files", headers=_auth(token),
                    files={"files": ("a.png", io.BytesIO(b"\x89PNG\r\n\x1a\n fake"), "image/png")})
    assert r.status_code == 201, r.text


# ── 變更申請：核准前金額不動 ────────────────────────────────────────────────

def test_change_request_does_not_touch_live_values_until_approved(client, make_user):
    """**本輪最重要的一條**：變更申請送審期間，本體的金額與說明完全不動。

    若這條紅了，代表變成「先生效再補簽核」——那正是使用者指定要避免的東西，
    報表數字會在沒人核准的情況下改變。
    """
    author, author_pw = make_user(username="xec_a1", role="admin")
    approver, approver_pw = make_user(username="xec_ap1", role="superadmin")
    token = _login(client, author, author_pw)
    _make_case()
    exp_id = _approved_expense(client, token, description="原始品項", qty=2, unitCost=1500)
    before = _get_item(client, token, exp_id)
    assert before["totalCost"] == 3000 and before["status"] == "已核准"

    _single_tier_flow(approver)
    r = client.put(_cbase(exp_id), headers=_auth(token),
                   json=_payload(description="改過的品項", qty=10, unitCost=1500))
    assert r.status_code == 200, r.text
    assert client.post(f"{_cbase(exp_id)}/submit", headers=_auth(token)).status_code == 200

    during = _get_item(client, token, exp_id)
    assert during["status"] == "已核准", "本體狀態不能被變更申請動到"
    assert during["totalCost"] == 3000, "核准前金額必須維持原值"
    assert during["description"] == "原始品項", "核准前說明也不能變"
    assert during["changeStatus"] == "待審核"
    assert during["change"]["totalCost"] == 15000, "提議的新值另外存著，供簽核人對照"

    # 核准 → 這一刻才套用
    atoken = _login(client, approver, approver_pw)
    r = client.post(f"{_cbase(exp_id)}/approve", headers=_auth(atoken), json={})
    assert r.status_code == 200, r.text
    assert r.json()["applied"] is True

    after = _get_item(client, token, exp_id)
    assert after["totalCost"] == 15000 and after["description"] == "改過的品項"
    assert after["changeStatus"] == "", "套用後變更申請要清空，不然會一直掛在那"
    assert after["status"] == "已核准"


def test_change_request_keeps_original_approval_and_records_history(client, make_user):
    """原核准紀錄不能被變更申請蓋掉——查帳要看的是「從多少改成多少、誰核准的」。"""
    author, author_pw = make_user(username="xec_a2", role="admin")
    approver, approver_pw = make_user(username="xec_ap2", role="superadmin")
    token = _login(client, author, author_pw)
    _make_case()
    exp_id = _approved_expense(client, token, description="原始", qty=1, unitCost=800)

    _single_tier_flow(approver)
    client.put(_cbase(exp_id), headers=_auth(token),
               json=_payload(description="改後", qty=1, unitCost=1200))
    client.post(f"{_cbase(exp_id)}/submit", headers=_auth(token))
    atoken = _login(client, approver, approver_pw)
    client.post(f"{_cbase(exp_id)}/approve", headers=_auth(atoken), json={})

    it = _get_item(client, token, exp_id)
    hist = it["approval"].get("changeHistory") or []
    assert len(hist) == 1, f"變更軌跡要留下來，實際 {it['approval']}"
    assert hist[0]["from"]["totalCost"] == 800 and hist[0]["to"]["totalCost"] == 1200
    assert hist[0]["byDisplay"] == approver


def test_rejected_change_leaves_live_values_untouched(client, make_user):
    """駁回之後本體完全沒變——因為從頭到尾就沒動過，不需要回滾任何東西。"""
    author, author_pw = make_user(username="xec_a3", role="admin")
    approver, approver_pw = make_user(username="xec_ap3", role="superadmin")
    token = _login(client, author, author_pw)
    _make_case()
    exp_id = _approved_expense(client, token, description="原始", qty=1, unitCost=500)

    _single_tier_flow(approver)
    client.put(_cbase(exp_id), headers=_auth(token),
               json=_payload(description="想改成這樣", qty=1, unitCost=99999))
    client.post(f"{_cbase(exp_id)}/submit", headers=_auth(token))
    atoken = _login(client, approver, approver_pw)
    r = client.post(f"{_cbase(exp_id)}/reject", headers=_auth(atoken),
                    json={"reason": "金額不合理"})
    assert r.status_code == 200, r.text

    it = _get_item(client, token, exp_id)
    assert it["totalCost"] == 500 and it["description"] == "原始"
    assert it["changeStatus"] == "已駁回"
    assert it["changeApproval"]["rejectReason"] == "金額不合理"

    # 已駁回可以改完再送一次
    assert client.put(_cbase(exp_id), headers=_auth(token),
                      json=_payload(description="改合理一點", qty=1, unitCost=600)).status_code == 200


def test_pending_change_files_are_not_visible_until_approved(client, make_user):
    """待核准附件核准前不能進正式附件清單。

    進去的話，結案報表 PDF 與案件財務都會撈到一份還沒被任何人核准的憑證。
    """
    author, author_pw = make_user(username="xec_a4", role="admin")
    approver, approver_pw = make_user(username="xec_ap4", role="superadmin")
    token = _login(client, author, author_pw)
    _make_case()
    exp_id = _approved_expense(client, token)
    assert _get_item(client, token, exp_id)["files"] == []

    _single_tier_flow(approver)
    client.put(_cbase(exp_id), headers=_auth(token), json=_payload(description="補憑證"))
    r = client.post(f"{_cbase(exp_id)}/files", headers=_auth(token),
                    files={"files": ("receipt.png", io.BytesIO(b"\x89PNG\r\n\x1a\n fake"), "image/png")})
    assert r.status_code == 201, r.text

    it = _get_item(client, token, exp_id)
    assert it["files"] == [], "核准前正式附件清單必須還是空的"
    assert len(it["change"]["addFiles"]) == 1, "檔案存在變更申請這邊"

    client.post(f"{_cbase(exp_id)}/submit", headers=_auth(token))
    atoken = _login(client, approver, approver_pw)
    client.post(f"{_cbase(exp_id)}/approve", headers=_auth(atoken), json={})

    it = _get_item(client, token, exp_id)
    assert len(it["files"]) == 1 and it["files"][0]["filename"] == "receipt.png"


def test_cancel_change_request_clears_everything(client, make_user):
    """撤銷草稿 → 變更申請整個消失，本體不受影響。"""
    username, password = make_user(username="xec_a5", role="superadmin")
    token = _login(client, username, password)
    _make_case()
    exp_id = _approved_expense(client, token, description="原始")

    client.put(_cbase(exp_id), headers=_auth(token), json=_payload(description="改一半"))
    assert _get_item(client, token, exp_id)["changeStatus"] == "草稿"

    assert client.delete(_cbase(exp_id), headers=_auth(token)).status_code == 200
    it = _get_item(client, token, exp_id)
    assert it["changeStatus"] == "" and it["description"] == "原始"


def test_change_request_only_for_approved_items(client, make_user):
    """草稿／已駁回本來就能直接編輯，不該繞變更申請這一圈。"""
    username, password = make_user(username="xec_a6", role="superadmin")
    token = _login(client, username, password)
    _make_case()
    exp_id = client.post(_base(), headers=_auth(token), json=_payload()).json()["id"]

    r = client.put(_cbase(exp_id), headers=_auth(token), json=_payload(description="x"))
    assert r.status_code == 409
    assert "直接編輯" in r.json()["detail"]


def test_no_tier_configured_applies_change_immediately(client, make_user):
    """沒設定任何簽核層 → 送審即生效。

    理由同新增流程：這個專案的簽核設定是選配的，若因為沒設定就把變更永久卡在
    「待審核」，等於新功能一上線就把所有人擋住。
    """
    username, password = make_user(username="xec_a7", role="superadmin")
    token = _login(client, username, password)
    _make_case()
    exp_id = _approved_expense(client, token, description="原始", qty=1, unitCost=100)

    client.put(_cbase(exp_id), headers=_auth(token),
               json=_payload(description="直接生效", qty=1, unitCost=250))
    r = client.post(f"{_cbase(exp_id)}/submit", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["autoApproved"] is True

    it = _get_item(client, token, exp_id)
    assert it["totalCost"] == 250 and it["description"] == "直接生效"
    assert it["changeStatus"] == ""


# ── 統一簽核佇列 ────────────────────────────────────────────────────────────

def test_change_request_appears_in_approval_queue_as_its_own_type(client, make_user):
    """變更申請要以**獨立類型**進佇列。

    借用 `extra_expense` 類型的話，簽核人按核准會打到本體的 /approve，那支看到
    status 已經是「已核准」就回 409——變更永遠簽不掉，而且畫面上只會顯示一句
    「簽核失敗」，沒有人查得出為什麼。
    """
    author, author_pw = make_user(username="xec_q1", role="admin")
    approver, approver_pw = make_user(username="xec_qap1", role="superadmin")
    token = _login(client, author, author_pw)
    _make_case("MQ-XEC-Q1")
    exp_id = _approved_expense(client, token, "MQ-XEC-Q1", description="佇列用", qty=1, unitCost=700)

    _single_tier_flow(approver)
    client.put(_cbase(exp_id, "MQ-XEC-Q1"), headers=_auth(token),
               json=_payload(description="佇列用（改）", qty=1, unitCost=900))
    client.post(f"{_cbase(exp_id, 'MQ-XEC-Q1')}/submit", headers=_auth(token))

    atoken = _login(client, approver, approver_pw)
    q = client.get("/api/approval-queue", headers=_auth(atoken))
    items = [it for g in q.json()["queue"] for it in g["items"]
             if it["type"] == "extra_expense_change"]
    assert len(items) == 1, f"變更申請要出現在佇列，實際 {q.json()}"
    it = items[0]
    assert it["extraExpenseId"] == exp_id
    assert it["linkedQuoteNo"] == "MQ-XEC-Q1"
    assert it["total"] == 900
    assert "700" in it["projectName"], "佇列上要看得出原本是多少，不然簽核人得自己去翻"

    # 角標數字也要算進去，否則佇列列得出來但 topbar 是 0（兩邊矛盾更難查）
    assert client.get("/api/approval-queue/count", headers=_auth(atoken)).json()["count"] >= 1
