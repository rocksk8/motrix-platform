"""2026-08-28（案件管理邏輯稽核）發現並修復的 2 個問題：
①payment_item_amounts() 沒有處理已核准稅額沖銷（taxExempt），導致沖銷後
  營運報表/AR帳齡/dashboard應收帳款仍把已沖銷的稅額算進已收/應收金額
②list_case_updates()（案件管理「動態」Tab）合併 5 種來源時，只有其中一種
  （audit_log）做了跨表時間格式正規化，dev_logs 用空白分隔格式，跟其餘多數
  來源的 'T' 分隔格式排序時永遠排在前面（不管實際時間點），已抽成共用的
  modules/case/quotations.py::norm_at() 套用到全部來源。"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── ①payment_item_amounts() taxExempt 換算 ──────────────────────────────────

def test_payment_item_amounts_reduces_tax_exempt_item_to_pretax_value():
    from modules.case.quotations import payment_item_amounts
    # 模擬 5% 稅率：total=105000（含稅），pretax=100000（未稅）
    items = [{"amount": 105000, "taxExempt": True}]
    amounts = payment_item_amounts(105000, items, pretax=100000)
    assert amounts[0] == 100000  # 換算後只剩未稅價


def test_payment_item_amounts_leaves_non_exempt_item_unchanged():
    from modules.case.quotations import payment_item_amounts
    items = [{"amount": 105000, "taxExempt": False}, {"amount": 50000}]
    amounts = payment_item_amounts(155000, items, pretax=147619)
    assert amounts == [105000, 50000]


def test_payment_item_amounts_without_pretax_keeps_old_behavior():
    """呼叫端沒有提供 pretax 時（極少數呼叫路徑），維持原本（未修正）行為，
    不要用未知比例硬換算。"""
    from modules.case.quotations import payment_item_amounts
    items = [{"amount": 105000, "taxExempt": True}]
    amounts = payment_item_amounts(105000, items)  # pretax 省略
    assert amounts[0] == 105000


# ── ②norm_at() 跨來源時間格式正規化 ──────────────────────────────────────────

def test_norm_at_unifies_space_and_t_separated_formats():
    from modules.case.quotations import norm_at
    assert norm_at("2026-07-23T20:18:03.980190") == "2026-07-23 20:18:03"
    assert norm_at("2026-07-23 20:18:03") == "2026-07-23 20:18:03"
    assert norm_at("2026-07-23T20:18:03") == "2026-07-23 20:18:03"
    assert norm_at("") == ""
    assert norm_at(None) == ""


def test_case_updates_feed_sorts_same_day_entries_correctly_across_sources(client, make_user):
    """整合測試：同一天內，dev_log（空白分隔格式）發生在較晚的時間，case_updates
    留言（T 分隔格式）發生在較早的時間——修正前 dev_log 會被誤判成較舊排到後面，
    修正後應該正確排在最前面（最新）。"""
    username, password = make_user(role="admin")
    token = _login(client, username, password)

    import db
    conn = db.get_db()
    try:
        user_id = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
        now = "2026-08-20T00:00:00"
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("MQ-FEEDSORT-001", "已送出", "測試客戶", "測試專案", 100000, 95238, "{}", now, now),
        )
        # 較早的留言（T 分隔格式，早上）
        conn.execute(
            "INSERT INTO case_updates (quote_no, author, content, type, created_at) VALUES (?,?,?,?,?)",
            ("MQ-FEEDSORT-001", username, "早上的留言", "comment", "2026-08-20T09:00:00"),
        )
        # 業務開發案 + 較晚的 dev_log（空白分隔格式，晚上）
        conn.execute(
            "INSERT INTO dev_cases (case_name, customer_name, status, converted_quote_no, created_by, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            ("測試開發案", "測試客戶", "成案", "MQ-FEEDSORT-001", user_id, now, now),
        )
        case_id = conn.execute("SELECT id FROM dev_cases WHERE converted_quote_no=?",
                                ("MQ-FEEDSORT-001",)).fetchone()["id"]
        conn.execute(
            "INSERT INTO dev_logs (case_id, log_date, log_by, channel, content, needs_approval, "
            "created_by, created_at) VALUES (?,?,?,?,?,0,?,?)",
            (case_id, "2026-08-20", user_id, "電話", "晚上的開發記錄", user_id, "2026-08-20 21:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    r = client.get("/api/quotations/MQ-FEEDSORT-001/updates", headers=_auth(token))
    assert r.status_code == 200, r.text
    items = r.json()
    contents = [it["content"] for it in items]
    # 晚上的開發記錄應該排在早上的留言「之前」（比較新）
    assert contents.index("晚上的開發記錄") < contents.index("早上的留言")
