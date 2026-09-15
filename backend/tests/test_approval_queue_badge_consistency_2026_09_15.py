"""角標數字必須等於佇列裡「待我簽核」的項目數（2026-09-15 使用者回報）。

使用者：「我跟另一位是最高管理者，需要我簽核但簽核佇列未顯示」。

`routers/quotations.py` 裡已經有兩則註解在講同一件事——
「角標數字要跟佇列列表一致，漏掉就會變成『列得出來但 topbar 是 0』，
**兩邊矛盾比兩邊都沒有更難查**」——但那是靠每次新增單據類型時人工記得補，
而 `/api/approval-queue` 與 `/api/approval-queue/count` 是**兩段各自獨立的
查詢**，沒有任何東西在守它們一致。

這支測試把那條不變量變成會紅的東西：對同一組資料，角標數字必須等於佇列裡
`canApprove()` 為真的項目數。`canApprove()` 的規則在前端
（`approval-queue.html`），這裡照抄一份——**兩邊的規則本來就必須一樣**，
不一樣就是 bug。
"""
import json

import pytest


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _can_approve(item, me: str, role: str) -> bool:
    """`approval-queue.html::canApprove()` 的 Python 版，逐條對應。

    2026-09-15 同步更新：有簽核層時**不再一律排除申請人**（組織流程判定「這一關
    歸他管」的自簽層由本人具名簽核，見 tiered_approval.py::resolve_submitter_org_chain()），
    排除規則只留在無簽核層的 superadmin fallback。"""
    tiers = item.get("tiers") or []
    if tiers:
        cur = item.get("currentTier") or 0
        if cur >= len(tiers):
            return False
        approvers = tiers[cur].get("approvers") or []
        first_pending = next((a for a in approvers if a.get("status") != "approved"), None)
        return bool(first_pending and first_pending.get("username") == me)
    # 無 tiers：任一 superadmin（且不是自己送的）
    if item.get("requestedBy") == me:
        return False
    return role == "superadmin"


def _queue_and_count(client, headers):
    q = client.get("/api/approval-queue", headers=headers)
    assert q.status_code == 200, q.text
    c = client.get("/api/approval-queue/count", headers=headers)
    assert c.status_code == 200, c.text
    items = [it for g in q.json()["queue"] for it in g["items"]]
    return items, c.json()["count"]


def _seed_case(quote_no="MQ-202609-900"):
    from db import get_db
    conn = get_db()
    conn.execute(
        "INSERT INTO quotations (quote_no, status, customer_name, project_name, "
        "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?)",
        (quote_no, "已送出", "客戶", "專案", json.dumps({"caseRecord": {}}, ensure_ascii=False),
         "2026-09-01", "2026-09-01", "已結案"))
    conn.commit()
    conn.close()
    return quote_no


# ── ① 沒有簽核層設定的單據：佇列列得出來，角標卻是 0 ────────────────────────

def test_badge_counts_no_tier_document_waiting_for_superadmin(client, make_user):
    """**這是使用者回報的那個症狀**。

    沒有設定簽核流程時，規則是「任一 superadmin 皆可簽核」——`approve_quotation()`
    的 no-tier 分支就是這樣走的（`detail_status = "超級管理員簽核"`），佇列頁的
    `canApprove()` 也是這樣判。但 count 端點的迴圈是 `if tiers and ...`，
    **沒有 tiers 的整批被跳過**，所以 topbar 顯示 0。
    """
    from db import get_db

    me, pw = make_user(username="sa_one", role="superadmin")
    other, _ = make_user(username="sa_two", role="superadmin")
    headers = _login(client, me, pw)

    conn = get_db()
    conn.execute(
        "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, "
        "data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
        ("MQ-202609-901", "待審核", "客戶A", "專案A", 1000,
         json.dumps({"approval": {"requestedBy": other, "requestedByDisplay": other,
                                  "requestedAt": "2026-09-15T01:00:00"}}, ensure_ascii=False),
         "2026-09-15", "2026-09-15"))
    conn.commit()
    conn.close()

    items, count = _queue_and_count(client, headers)
    mine = [i for i in items if _can_approve(i, me, "superadmin")]
    assert mine, "佇列裡應該要有這筆（沒有 tiers ＝ 任一 superadmin 可簽）"
    assert count == len(mine), (
        f"角標 {count} 跟佇列的待我簽核 {len(mine)} 不一致"
        f"——沒有簽核層設定的單據在 count 端點被整批跳過了")


# ── ② 自己送的已結案變更：角標算了，但永遠簽不掉 ────────────────────────────

def test_badge_does_not_count_my_own_case_change(client, make_user):
    """自己送的變更申請自己簽不掉（`check_no_tier_self_approval()` 會擋，
    佇列頁的 `canApprove()` 也回 false）——卻被算進角標，變成一個**永遠清不掉
    的紅點**。這跟①剛好相反：一個少算、一個多算。"""
    from db import get_db

    me, pw = make_user(username="sa_self", role="superadmin")
    make_user(username="sa_other2", role="superadmin")
    headers = _login(client, me, pw)
    quote_no = _seed_case("MQ-202609-902")

    conn = get_db()
    conn.execute(
        "INSERT INTO case_change_requests (quote_no, action_type, summary, payload_json, "
        "staged_files_json, status, requested_by, requested_by_display, requested_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (quote_no, "case_record_update", "我自己送的", "{}", "[]", "pending",
         me, me, "2026-09-15T01:00:00"))
    conn.commit()
    conn.close()

    items, count = _queue_and_count(client, headers)
    mine = [i for i in items if _can_approve(i, me, "superadmin")]
    assert not mine, "自己送的不該出現在待我簽核"
    assert count == 0, f"角標算進了自己送的變更申請（count={count}），那個紅點永遠清不掉"


def test_badge_counts_other_superadmins_case_change(client, make_user):
    """正向控制：別人送的要算。少了這題，上面那題可以靠「一律不算」變綠。"""
    from db import get_db

    me, pw = make_user(username="sa_a", role="superadmin")
    other, _ = make_user(username="sa_b", role="superadmin")
    headers = _login(client, me, pw)
    quote_no = _seed_case("MQ-202609-903")

    conn = get_db()
    conn.execute(
        "INSERT INTO case_change_requests (quote_no, action_type, summary, payload_json, "
        "staged_files_json, status, requested_by, requested_by_display, requested_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (quote_no, "case_record_update", "別人送的", "{}", "[]", "pending",
         other, other, "2026-09-15T01:00:00"))
    conn.commit()
    conn.close()

    items, count = _queue_and_count(client, headers)
    mine = [i for i in items if _can_approve(i, me, "superadmin")]
    assert len(mine) == 1
    assert count == 1, f"別人送的已結案變更沒被算進角標（count={count}）"


# ── ③ 一般情況也要一致 ──────────────────────────────────────────────────────

def test_badge_matches_queue_for_tiered_document(client, make_user):
    """有簽核層的單據：當層輪到我才算。這條原本就對，一起釘住當回歸基準。"""
    from db import get_db

    me, pw = make_user(username="appr_me", role="admin")
    headers = _login(client, me, pw)

    conn = get_db()
    appr = {"requestedBy": "someone", "requestedByDisplay": "某人",
            "requestedAt": "2026-09-15T01:00:00", "currentTier": 0,
            "tiers": [{"approvers": [{"username": me, "status": "pending"}]}]}
    conn.execute(
        "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, "
        "data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
        ("MQ-202609-904", "待審核", "客戶B", "專案B", 500,
         json.dumps({"approval": appr}, ensure_ascii=False), "2026-09-15", "2026-09-15"))
    conn.commit()
    conn.close()

    items, count = _queue_and_count(client, headers)
    mine = [i for i in items if _can_approve(i, me, "admin")]
    assert len(mine) == 1
    assert count == len(mine)


def test_non_superadmin_does_not_get_no_tier_items(client, make_user):
    """沒有 tiers 的單據只有 superadmin 能簽——admin 的角標不該因此變大。"""
    from db import get_db

    me, pw = make_user(username="just_admin", role="admin")
    headers = _login(client, me, pw)

    conn = get_db()
    conn.execute(
        "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, "
        "data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
        ("MQ-202609-905", "待審核", "客戶C", "專案C", 300,
         json.dumps({"approval": {"requestedBy": "someone",
                                  "requestedAt": "2026-09-15T01:00:00"}}, ensure_ascii=False),
         "2026-09-15", "2026-09-15"))
    conn.commit()
    conn.close()

    items, count = _queue_and_count(client, headers)
    mine = [i for i in items if _can_approve(i, me, "admin")]
    assert not mine
    assert count == 0, f"admin 不該被算到無簽核層的單據（count={count}）"
