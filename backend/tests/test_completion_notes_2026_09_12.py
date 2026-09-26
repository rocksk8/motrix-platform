"""完工單 CRUD ＋ 分層簽核 ＋ 客戶驗收回簽（2026-09-12 交辦）。

使用者：「在案件管理內增加完工單的選項，參考出貨單的形式跟內容建立完工單，
一樣走流程申請完工。」所以行為**刻意比照出貨單**，測試也照著守同一批不變量。

**跟出貨單刻意不同、因此值得個別釘住的三件事**

1. 完工單**不碰庫存**——東西在出貨單那一關就出掉了，跟著抄庫存扣減會讓同一批
   序號被扣兩次。
2. 送審前強制要有**完工日期**——保固起算與工期都以它為準，缺了這張單就沒有意義。
3. 項目有**完成狀態**（完成／部分完成／未施作）。完工不等於零缺失；允許填
   「未施作」才有辦法把缺失留在「遺留事項」而不是假裝做完了。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import io
import json
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_case(quote_no="MQ-CN-001"):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "台中廠房監控工程", 100000, 95238,
             json.dumps({"dealTag": "已成案"}, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"),
        )
        conn.commit()
    finally:
        conn.close()


def _payload(**over):
    d = {
        "quote_no": "MQ-CN-001",
        "site_address": "台中市西屯區工業區一路 1 號",
        "start_date": "2026-08-01",
        "completion_date": "2026-09-10",
        "site_manager": "王工程師",
        "recipient": "陳經理",
        "warranty_months": 12,
        "items": [{"description": "監控主機安裝", "qty": 1, "unit": "式", "status": "完成"}],
        "work_summary": "完成 16 路監控主機與攝影機安裝並設定遠端連線。",
        "test_result": "全部通道影像正常、錄影可回放、遠端連線測試通過。",
    }
    d.update(over)
    return d


def _set_empty_flow():
    """完全沒有簽核層（含關掉「申請人部門主管自動簽核」那一層）。"""
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            ("unified_approval_flow",
             json.dumps({"tiers": [], "includeSubmitterManagerTier": False}),
             "2026-01-01T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()


def _single_tier_flow(approver):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            ("unified_approval_flow",
             json.dumps({"includeSubmitterManagerTier": False,
                         "tiers": [{"order": 0, "approvers": [
                             {"username": approver, "display_name": approver}]}]},
                        ensure_ascii=False),
             "2026-01-01T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()


BASE = "/api/completion-notes"


def _create(client, token, **over):
    r = client.post(BASE, headers=_auth(token), json=_payload(**over))
    assert r.status_code == 201, r.text
    return r.json()["note_no"]


def _get(client, token, note_no):
    r = client.get(f"{BASE}/{note_no}", headers=_auth(token))
    assert r.status_code == 200, r.text
    return r.json()


# ── CRUD ────────────────────────────────────────────────────────────────────

def test_create_uses_cn_prefix_and_inherits_case_fields(client, make_user):
    """單號用 CN 前綴，客戶／案件名稱沒填就從報價單帶。"""
    username, password = make_user(username="cn1", role="admin")
    token = _login(client, username, password)
    _make_case()
    note_no = _create(client, token)
    assert note_no.startswith("CN-"), note_no
    d = _get(client, token, note_no)
    assert d["customerName"] == "測試客戶"
    assert d["projectName"] == "台中廠房監控工程"
    assert d["status"] == "草稿"


def test_warranty_range_computed_from_completion_date(client, make_user):
    """保固**自完工日起算**——這是完工單跟出貨單最關鍵的差別之一。"""
    username, password = make_user(username="cn2", role="admin")
    token = _login(client, username, password)
    _make_case()
    note_no = _create(client, token, completion_date="2026-09-10", warranty_months=18)
    d = _get(client, token, note_no)
    assert d["warrantyStart"] == "2026-09-10"
    # 2026-09 + 18 個月 = 2028-03（第一版我自己算成 2027-03，是測試錯不是程式錯）
    assert d["warrantyEnd"] == "2028-03-10", d["warrantyEnd"]


def test_completion_before_start_is_rejected(client, make_user):
    username, password = make_user(username="cn3", role="admin")
    token = _login(client, username, password)
    _make_case()
    r = client.post(BASE, headers=_auth(token),
                    json=_payload(start_date="2026-09-10", completion_date="2026-08-01"))
    assert r.status_code == 400
    assert "完工日期" in r.json()["detail"]


def test_invalid_item_status_is_rejected(client, make_user):
    """完成狀態只能是那三種——放行任意字串的話 PDF 上會印出一個沒人看得懂的值。"""
    username, password = make_user(username="cn4", role="admin")
    token = _login(client, username, password)
    _make_case()
    r = client.post(BASE, headers=_auth(token), json=_payload(
        items=[{"description": "x", "qty": 1, "unit": "式", "status": "做一半"}]))
    assert r.status_code == 400


def test_only_draft_editable_and_deletable(client, make_user):
    username, password = make_user(username="cn5", role="superadmin")
    token = _login(client, username, password)
    _make_case()
    _set_empty_flow()
    note_no = _create(client, token)
    assert client.post(f"{BASE}/{note_no}/submit", headers=_auth(token)).status_code == 200

    assert client.put(f"{BASE}/{note_no}", headers=_auth(token),
                      json=_payload(site_manager="偷改")).status_code == 409
    assert client.delete(f"{BASE}/{note_no}", headers=_auth(token)).status_code == 409


# ── 送審門檻 ────────────────────────────────────────────────────────────────

def test_submit_requires_completion_date(client, make_user):
    """沒有完工日期就送審 → 擋下。保固起算與工期都以它為準。"""
    username, password = make_user(username="cn6", role="superadmin")
    token = _login(client, username, password)
    _make_case()
    note_no = _create(client, token, completion_date="")
    r = client.post(f"{BASE}/{note_no}/submit", headers=_auth(token))
    assert r.status_code == 400
    assert "完工日期" in r.json()["detail"]


def test_submit_requires_at_least_one_item(client, make_user):
    username, password = make_user(username="cn7", role="superadmin")
    token = _login(client, username, password)
    _make_case()
    note_no = _create(client, token, items=[])
    r = client.post(f"{BASE}/{note_no}/submit", headers=_auth(token))
    assert r.status_code == 400
    assert "完工項目" in r.json()["detail"]


def test_unfinished_items_are_counted_not_blocked(client, make_user):
    """有未完成項目**不擋送審**，但要數出來讓簽核人看到。

    擋下來的話現場會被迫把沒做完的也填「完成」，遺留事項那欄就永遠是空的
    ——那比讓帶缺失的完工單進簽核更糟。
    """
    username, password = make_user(username="cn8", role="superadmin")
    token = _login(client, username, password)
    _make_case()
    _set_empty_flow()
    note_no = _create(client, token, items=[
        {"description": "主機安裝", "qty": 1, "unit": "式", "status": "完成"},
        {"description": "戶外攝影機", "qty": 2, "unit": "台", "status": "未施作"},
        {"description": "佈線", "qty": 1, "unit": "式", "status": "部分完成"},
    ], pending_items="戶外攝影機待客戶確認位置後補裝")
    assert _get(client, token, note_no)["unfinishedCount"] == 2
    assert client.post(f"{BASE}/{note_no}/submit", headers=_auth(token)).status_code == 200


# ── 簽核流程 ────────────────────────────────────────────────────────────────

def test_full_approval_round_trip(client, make_user):
    author, author_pw = make_user(username="cn_a", role="admin")
    approver, approver_pw = make_user(username="cn_ap", role="superadmin")
    token = _login(client, author, author_pw)
    _make_case()
    _single_tier_flow(approver)
    note_no = _create(client, token)

    assert client.post(f"{BASE}/{note_no}/submit", headers=_auth(token)).status_code == 200
    assert _get(client, token, note_no)["status"] == "待審核"

    atoken = _login(client, approver, approver_pw)
    r = client.post(f"{BASE}/{note_no}/approve", headers=_auth(atoken), json={})
    assert r.status_code == 200, r.text
    assert r.json()["allDone"] is True
    assert _get(client, token, note_no)["status"] == "已核准"


def test_reject_returns_to_draft(client, make_user):
    author, author_pw = make_user(username="cn_a2", role="admin")
    approver, approver_pw = make_user(username="cn_ap2", role="superadmin")
    token = _login(client, author, author_pw)
    _make_case()
    _single_tier_flow(approver)
    note_no = _create(client, token)
    client.post(f"{BASE}/{note_no}/submit", headers=_auth(token))

    atoken = _login(client, approver, approver_pw)
    r = client.post(f"{BASE}/{note_no}/reject", headers=_auth(atoken),
                    json={"note": "測試報告要附上"})
    assert r.status_code == 200, r.text
    d = _get(client, token, note_no)
    assert d["status"] == "草稿"
    assert not d["approval"], "退回後 approval 要清空，否則重新送審會沿用舊的簽核層"
    # 退回草稿就能再編輯
    assert client.put(f"{BASE}/{note_no}", headers=_auth(token),
                      json=_payload(test_result="補上測試報告")).status_code == 200


def test_appears_in_approval_queue_with_unfinished_count(client, make_user):
    """要進統一簽核佇列，而且佇列上要看得出有幾項未完成。

    不進佇列的話送審之後只剩站內通知，沒有任何地方列得出「該我簽的」。
    """
    author, author_pw = make_user(username="cn_q", role="admin")
    approver, approver_pw = make_user(username="cn_qap", role="superadmin")
    token = _login(client, author, author_pw)
    _make_case("MQ-CN-Q1")
    _single_tier_flow(approver)
    note_no = _create(client, token, quote_no="MQ-CN-Q1", items=[
        {"description": "主機", "qty": 1, "unit": "式", "status": "完成"},
        {"description": "攝影機", "qty": 2, "unit": "台", "status": "未施作"},
    ])
    client.post(f"{BASE}/{note_no}/submit", headers=_auth(token))

    atoken = _login(client, approver, approver_pw)
    q = client.get("/api/approval-queue", headers=_auth(atoken))
    hits = [it for g in q.json()["queue"] for it in g["items"] if it["type"] == "completion_note"]
    assert len(hits) == 1, f"完工單要出現在佇列，實際 {q.json()}"
    assert hits[0]["quoteNo"] == note_no
    assert hits[0]["unfinishedCount"] == 1
    assert "未完成" in hits[0]["projectName"], "佇列上要看得出這是一張帶缺失的完工單"
    assert client.get("/api/approval-queue/count", headers=_auth(atoken)).json()["count"] >= 1


# ── 客戶驗收回簽 ────────────────────────────────────────────────────────────

def test_signed_toggle_requires_approved_and_blocks_revoke(client, make_user):
    """只有已核准才能標記驗收；標記之後不可撤銷核准（客戶都簽了）。"""
    username, password = make_user(username="cn_s", role="admin")
    # 沒有簽核層時由最高管理員直接核准，而且**申請人不得自審**
    # （check_no_tier_self_approval），所以簽核人一定要是另一個人
    approver, approver_pw = make_user(username="cn_s_ap", role="superadmin")
    token = _login(client, username, password)
    _make_case()
    _set_empty_flow()
    note_no = _create(client, token)

    r = client.post(f"{BASE}/{note_no}/signed-toggle", headers=_auth(token),
                    json={"action": "sign"})
    assert r.status_code == 409, "草稿不可標記驗收"

    client.post(f"{BASE}/{note_no}/submit", headers=_auth(token))
    # 完工單比照出貨單：沒有設定簽核層時停在「待審核」，由最高管理員直接核准，
    # **不是**額外支出那種「送審即核准」。兩者行為不同，不要互相抄。
    assert client.post(f"{BASE}/{note_no}/approve",
                       headers=_auth(_login(client, approver, approver_pw)),
                       json={}).status_code == 200
    assert _get(client, token, note_no)["status"] == "已核准"

    assert client.post(f"{BASE}/{note_no}/signed-toggle", headers=_auth(token),
                       json={"action": "sign", "note": "陳經理現場簽收"}).status_code == 200
    d = _get(client, token, note_no)
    assert d["isSigned"] is True
    assert d["signedLog"][-1]["note"] == "陳經理現場簽收"

    r = client.post(f"{BASE}/{note_no}/revoke-approval", headers=_auth(token), json={})
    assert r.status_code == 409, "已回簽的不可撤銷核准"
    assert "取消回簽" in r.json()["detail"]

    # 取消回簽之後才可以撤銷
    client.post(f"{BASE}/{note_no}/signed-toggle", headers=_auth(token), json={"action": "unsign"})
    assert client.post(f"{BASE}/{note_no}/revoke-approval", headers=_auth(token),
                       json={}).status_code == 200
    assert _get(client, token, note_no)["status"] == "草稿"


def test_signed_files_upload_and_delete(client, make_user):
    """驗收簽回附件（客戶簽名掃描檔／現場照片）。刻意不限制單據狀態。"""
    username, password = make_user(username="cn_f", role="admin")
    token = _login(client, username, password)
    _make_case()
    note_no = _create(client, token)

    r = client.post(f"{BASE}/{note_no}/signed-files", headers=_auth(token),
                    files={"files": ("signed.png", io.BytesIO(b"\x89PNG\r\n\x1a\n fake"), "image/png")})
    assert r.status_code == 201, r.text
    file_id = r.json()["files"][0]["id"]
    assert len(_get(client, token, note_no)["signedFiles"]) == 1

    assert client.delete(f"{BASE}/{note_no}/signed-files/{file_id}",
                         headers=_auth(token)).status_code == 200
    assert _get(client, token, note_no)["signedFiles"] == []


# ── 不碰庫存 ────────────────────────────────────────────────────────────────

def test_approval_does_not_touch_stock(client, make_user):
    """完工單核准**不能**動到庫存——東西在出貨單那一關就出掉了。

    跟著抄出貨單的庫存扣減，同一批序號會被扣兩次，而且第二次扣的時候第一次
    已經不是 in_stock 了，核准會直接 409，變成完工單永遠簽不掉。
    """
    username, password = make_user(username="cn_st", role="admin")
    approver, approver_pw = make_user(username="cn_st_ap", role="superadmin")
    token = _login(client, username, password)
    _make_case()
    _set_empty_flow()

    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO stock_items (part_no, serial_no, status, created_at, updated_at) "
            "VALUES (?,?,?,?,?)",
            ("P-001", "SN-CN-1", "in_stock", "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()

    note_no = _create(client, token, items=[
        {"description": "監控主機", "qty": 1, "unit": "台", "status": "完成",
         "part_no": "P-001", "serials": ["SN-CN-1"]}])
    assert client.post(f"{BASE}/{note_no}/submit", headers=_auth(token)).status_code == 200
    assert client.post(f"{BASE}/{note_no}/approve",
                       headers=_auth(_login(client, approver, approver_pw)),
                       json={}).status_code == 200
    assert _get(client, token, note_no)["status"] == "已核准"

    conn = db.get_db()
    try:
        st = conn.execute("SELECT status FROM stock_items WHERE serial_no='SN-CN-1'").fetchone()
    finally:
        conn.close()
    assert st["status"] == "in_stock", "完工單核准不該動到庫存"


def test_requires_auth_and_admin_to_create(client, make_user):
    assert client.get(BASE).status_code in (401, 403)
    # 2026-09-13（模組權限稽核）：帳號補上 `case_manage`——實際用 UI 建立的工程師
    # 帳號本來就會帶（users.html::ROLE_MODULES.engineer），而完工單清單現在要求
    # 「具案件管理模組」才看得到（不帶 quote_no 是跨案件總覽）。
    username, password = make_user(username="cn_eng", role="engineer",
                                   modules=["case_manage"])
    token = _login(client, username, password)
    _make_case()
    assert client.post(BASE, headers=_auth(token), json=_payload()).status_code == 403
    # 但看得到（列表不要求 admin，比照出貨單）
    assert client.get(BASE, headers=_auth(token)).status_code == 200

    # 反向：沒有案件管理模組的帳號連清單都看不到（先前這行會是 200）
    u2, p2 = make_user(username="cn_nomod", role="viewer", modules=["dashboard"])
    assert client.get(BASE, headers=_auth(_login(client, u2, p2))).status_code == 403


# ── 可自訂標題 ＋ 保固可隱藏（2026-09-12 使用者回饋）──────────────────────────
#
# 第一版用語全部偏工程（施工地點／工程期間／施工說明／承攬商·工程負責人…），但公司
# 除了工程還有專案、零組件販售、系統設定、網路架構、防火牆等業務。改成：預設值中性、
# 每張單可自己覆寫標題、保固期間留空就不印（比照報價單「條件留空就不印」的慣例）。

def test_default_labels_are_business_neutral(client, make_user):
    """預設用語不能再綁死工程。"""
    username, password = make_user(username="cn_l1", role="admin")
    token = _login(client, username, password)
    _make_case()
    d = _get(client, token, _create(client, token))
    lab = d["labels"]
    assert lab["siteLabel"] == "服務地點"
    assert lab["sectionSummary"] == "四、執行說明"
    assert lab["signVendor"] == "執行單位 · 負責人"
    joined = "".join(lab.values())
    for word in ("施工", "工程", "承攬商", "業主"):
        assert word not in joined, f"預設標題不該再出現「{word}」：{lab}"


def test_labels_can_be_overridden_per_note(client, make_user):
    """每一張完工單各自覆寫——不同業務的單子用不同用語，這正是使用者要的。"""
    username, password = make_user(username="cn_l2", role="admin")
    token = _login(client, username, password)
    _make_case()
    note_no = _create(client, token, labels={
        "sectionSummary": "四、系統設定說明",
        "itemColumn": "系統項目 / 設定內容",
        "siteLabel": "建置環境",
    })
    d = _get(client, token, note_no)
    assert d["labels"]["sectionSummary"] == "四、系統設定說明"
    assert d["labels"]["itemColumn"] == "系統項目 / 設定內容"
    assert d["labels"]["siteLabel"] == "建置環境"
    # 沒覆寫的仍是預設
    assert d["labels"]["sectionTest"] == "五、測試與檢驗結果"
    # labelOverrides 只回使用者真正改過的，前端表單才不會被預設值塞滿
    assert set(d["labelOverrides"]) == {"sectionSummary", "itemColumn", "siteLabel"}


def test_blank_label_falls_back_to_default(client, make_user):
    """留空＝用預設，不是留一個空白標題——標題整個消失只會讓人以為版面壞了。"""
    username, password = make_user(username="cn_l3", role="admin")
    token = _login(client, username, password)
    _make_case()
    d = _get(client, token, _create(client, token, labels={"sectionItems": "   "}))
    assert d["labels"]["sectionItems"] == "三、完成項目明細"


def test_unknown_or_overlong_label_is_rejected(client, make_user):
    username, password = make_user(username="cn_l4", role="admin")
    token = _login(client, username, password)
    _make_case()
    r = client.post(BASE, headers=_auth(token), json=_payload(labels={"bogusKey": "x"}))
    assert r.status_code == 400 and "未知" in r.json()["detail"]
    r = client.post(BASE, headers=_auth(token), json=_payload(labels={"siteLabel": "字" * 41}))
    assert r.status_code == 400


def test_labels_survive_update_without_clobbering_approval(client, make_user):
    """編輯時 data_json 要 read-modify-write——整包覆蓋會把 approval 洗掉。

    情境：送審 → 被駁回退回草稿（approval 已被 pop，但其他欄位還在）→ 再編輯。
    這裡改用「手動塞一段 data_json 的其他內容」來驗證不被清掉，比真的跑一輪簽核短。
    """
    username, password = make_user(username="cn_l5", role="superadmin")
    token = _login(client, username, password)
    _make_case()
    note_no = _create(client, token, labels={"siteLabel": "交付地點"})

    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE completion_notes SET data_json=? WHERE note_no=?",
                     (json.dumps({"labels": {"siteLabel": "交付地點"},
                                  "someOtherKey": "不可以被洗掉"}, ensure_ascii=False), note_no))
        conn.commit()
    finally:
        conn.close()

    assert client.put(f"{BASE}/{note_no}", headers=_auth(token),
                      json=_payload(labels={"siteLabel": "點交地點"})).status_code == 200

    conn = db.get_db()
    try:
        dj = json.loads(conn.execute(
            "SELECT data_json FROM completion_notes WHERE note_no=?", (note_no,)).fetchone()[0])
    finally:
        conn.close()
    assert dj["labels"]["siteLabel"] == "點交地點"
    assert dj.get("someOtherKey") == "不可以被洗掉", "data_json 被整包覆蓋了"


def test_warranty_can_be_hidden_by_leaving_it_blank(client, make_user):
    """保固月數 0＝這張單不顯示保固（零組件販售、系統設定那類常常沒有保固可言）。

    比照報價單「條件留空就不印」的既有慣例，不另外開一個顯示旗標。
    """
    username, password = make_user(username="cn_l6", role="admin")
    token = _login(client, username, password)
    _make_case()

    on = _get(client, token, _create(client, token, warranty_months=12))
    assert on["showWarranty"] is True and on["warrantyEnd"]

    off = _get(client, token, _create(client, token, warranty_months=0))
    assert off["showWarranty"] is False
    assert off["warrantyEnd"] == "", "保固關掉時不該還算出迄日"


def test_pdf_uses_custom_labels_and_hides_warranty(client, make_user):
    """PDF 真的要吃到自訂標題，而且保固關掉時那一列不能出現。

    直接組 HTML 檢查字串，不跑 Edge——這裡要驗的是內容有沒有換掉，不是 PDF 產得出來
    （產得出來由 test_cn_pdf 那支實跑驗證）。
    """
    from modules.case.completion_pdf import _build_completion_html, _completion_note_dict
    import db

    username, password = make_user(username="cn_l7", role="admin")
    token = _login(client, username, password)
    _make_case()
    note_no = _create(client, token, warranty_months=0, labels={
        "sectionItems": "三、交付品項明細", "itemColumn": "品名 / 規格",
        "signVendor": "供應單位 · 負責人", "siteLabel": "交付地點",
    })
    conn = db.get_db()
    try:
        row = conn.execute("SELECT * FROM completion_notes WHERE note_no=?", (note_no,)).fetchone()
    finally:
        conn.close()
    html = _build_completion_html(_completion_note_dict(row))

    assert "三、交付品項明細" in html and "品名 / 規格" in html
    assert "供應單位 · 負責人" in html and "交付地點" in html
    assert "保固期間" not in html, "保固月數 0 時不該印保固那一列"
    # 舊的工程用語不該再出現
    for word in ("施工地點", "工程期間", "承攬商 · 工程負責人"):
        assert word not in html, f"PDF 仍有舊用語「{word}」"
    # meta 第三欄改成案件名稱（使用者指定），案件編號移到第二區
    assert "案件名稱：" in html and "關聯報價單" not in html
    assert "案件編號" in html
