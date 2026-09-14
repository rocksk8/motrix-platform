"""營運報表業務員績效改以案件管理的「業務負責」歸屬（2026-09-14 使用者交辦）。

使用者：「營運報表的業務員績效比較讀取案件管理的人員角色，業務負責的欄位」。

兩者在實務上會不一致：**報價單的 `salesPerson` 是「開單的人」，
`caseRecord.roles.sales` 才是「這個案子歸誰的績效」**。

⚠️ `roles.sales` 存的是**顯示名稱字串**不是 username（實例：
`{"filler":"黃玉龍","sales":"高晟耀","executor":"黃玉龍"}`），所以要反查帳號；
同名時刻意不猜（見 `_build_name_index()`）。
"""
import json

import pytest

import routers.reports as rp


def _row(sales_person="開單者", sales_person_id=None):
    """模擬 _collect() 拿到的一列（只需要這兩個欄位）。"""
    class R(dict):
        def keys(self):
            return list(super().keys())
    return R(sales_person=sales_person, sales_person_id=sales_person_id)


_USERS = {
    1: {"deptId": None, "deptName": "未分類", "displayName": "高晟耀"},
    2: {"deptId": None, "deptName": "未分類", "displayName": "黃玉龍"},
    3: {"deptId": None, "deptName": "未分類", "displayName": "同名的人"},
    4: {"deptId": None, "deptName": "未分類", "displayName": "同名的人"},
}


@pytest.fixture
def idx():
    return rp._build_name_index(_USERS)


# ── 名稱索引 ────────────────────────────────────────────────────────────────

def test_name_index_resolves_unique_names(idx):
    assert idx["高晟耀"] == 1
    assert idx["黃玉龍"] == 2


def test_name_index_refuses_to_guess_on_duplicates(idx):
    """同名硬猜一個等於把 A 的業績算到 B 頭上。寧可退回名字分組——
    那至少是「兩個同名的人被合成一列」這種看得出來的錯。"""
    assert idx["同名的人"] is None


# ── 歸屬優先序 ──────────────────────────────────────────────────────────────

def test_roles_sales_wins_over_quote_creator(idx):
    """核心：案件的業務負責是高晟耀，報價單是黃玉龍開的 → 算高晟耀的。"""
    cr = {"roles": {"filler": "黃玉龍", "sales": "高晟耀", "executor": "黃玉龍"}}
    key, label = rp._case_sales_owner(cr, _row("黃玉龍", 2), idx, _USERS)
    assert key == ("id", 1)
    assert label == "高晟耀"


def test_falls_back_to_quote_creator_when_roles_sales_empty(idx):
    """舊案件沒有這個欄位——**刻意不回填**，補猜測值只會製造假資料。"""
    for cr in ({}, {"roles": {}}, {"roles": {"sales": ""}}, {"roles": {"sales": "   "}}):
        key, label = rp._case_sales_owner(cr, _row("黃玉龍", 2), idx, _USERS)
        assert key == ("id", 2), cr
        assert label == "黃玉龍"


def test_unresolvable_owner_name_still_counts_as_that_person(idx):
    """反查不到帳號（離職刪帳號、名字打錯）時**不要丟掉這筆歸屬**——
    丟掉會讓案件默默跑到「開單的人」名下，正好是這次要修的問題。"""
    cr = {"roles": {"sales": "已離職的人"}}
    key, label = rp._case_sales_owner(cr, _row("黃玉龍", 2), idx, _USERS)
    assert key == ("name", "已離職的人")
    assert label == "已離職的人"


def test_duplicate_display_name_groups_by_name(idx):
    cr = {"roles": {"sales": "同名的人"}}
    key, _ = rp._case_sales_owner(cr, _row("黃玉龍", 2), idx, _USERS)
    assert key == ("name", "同名的人")


def test_renamed_user_keeps_one_row(idx):
    """反查得到帳號時用 id 當 key——業務員改名後歷史業績不會被拆成兩列。"""
    cr = {"roles": {"sales": "高晟耀"}}
    key, label = rp._case_sales_owner(cr, _row("", None), idx, _USERS)
    assert key == ("id", 1)
    # 顯示用「目前」的名稱，不是案件裡當初存的字串
    renamed = dict(_USERS)
    renamed[1] = {"deptId": None, "deptName": "未分類", "displayName": "高晟耀（已改名）"}
    _, label2 = rp._case_sales_owner(cr, _row("", None), idx, renamed)
    assert label2 == "高晟耀（已改名）"


def test_no_owner_anywhere_is_labelled_not_assigned(idx):
    key, label = rp._case_sales_owner({}, _row("", None), idx, _USERS)
    assert key == ("name", "（未指定）") and label == "（未指定）"


# ── 目標達成率用同一套歸屬 ──────────────────────────────────────────────────

def test_achievement_uses_same_attribution_as_performance():
    """兩張表必須一致——使用者是把「業務員績效」跟「目標達成率」並排看的，
    一邊算業務負責、另一邊算開單者，同一個人的兩個數字會對不起來。"""
    targets = {"year": 2026, "annual": {"revenue": 1_000_000, "newCases": 10},
               "salesperson": [{"name": "高晟耀", "revenue": 600_000, "cases": 6}]}
    cases = [
        # 開單者是黃玉龍，但業務負責是高晟耀 → 應計入高晟耀
        {"total": 300_000, "pretax": 300_000, "receivedAmount": 0,
         "settleStatus": "finalized", "grossProfit": 0, "actualMarginPct": 0.0,
         "quoteDate": "2026-03-01", "wonMonth": "2026-03",
         "salesPerson": "黃玉龍", "salesPersonId": 2,
         "ownerKey": ["name", "高晟耀"], "ownerName": "高晟耀"},
    ]
    r = rp._compute_achievement(2026, targets, cases)
    sp = {s["name"]: s for s in r["salesperson"]}
    assert sp["高晟耀"]["ytdCases"] == 1, sp
    assert sp["高晟耀"]["ytdRevenue"] == 300_000


def test_owner_key_fallback_keeps_legacy_callers_working():
    """`_compute_achievement()` 是純函式，也可能被直接拿手組的 dict 呼叫
    （既有單元測試就是）。缺 ownerKey 時要退回舊欄位，語意跟改動前相同。"""
    assert rp._owner_key_of({"salesPersonId": 7}) == ("id", 7)
    assert rp._owner_key_of({"salesPerson": "Alice"}) == ("name", "Alice")
    assert rp._owner_key_of({}) == ("name", "（未指定）")
    # 有 ownerKey 時以它為準
    assert rp._owner_key_of({"ownerKey": ["id", 9], "salesPersonId": 7}) == ("id", 9)


# ── 端到端：報表 API 真的照新口徑分組 ──────────────────────────────────────

def test_report_groups_by_case_sales_owner(client, make_user):
    from db import get_db

    u, p = make_user(username="rep_sa", role="superadmin")
    tok = client.post("/api/auth/login",
                      json={"username": u, "password": p}).json()["token"]
    headers = {"Authorization": f"Bearer {tok}"}

    conn = get_db()
    conn.execute("UPDATE users SET display_name='高晟耀' WHERE username=?", (u,))
    conn.execute(
        "INSERT INTO users (username, password_hash, display_name, role, modules, active, "
        "created_at, must_change_password) VALUES (?,?,?,?,?,1,?,0)",
        ("huang_r", "x", "黃玉龍", "sales", "[]", "2026-01-01"))
    huang_id = conn.execute("SELECT id FROM users WHERE username='huang_r'").fetchone()["id"]

    data = {"caseRecord": {"roles": {"filler": "黃玉龍", "sales": "高晟耀",
                                     "executor": "黃玉龍"}},
            "dealTag": "已成案"}
    conn.execute(
        "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
        "quote_date, sales_person, sales_person_id, data_json, created_at, updated_at, deal_tag) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("MQ-202609-501", "已送出", "客戶A", "專案A", 300000, 285714, "2026-09-01",
         "黃玉龍", huang_id, json.dumps(data, ensure_ascii=False),
         "2026-09-01", "2026-09-01", "已成案"))
    conn.commit()
    conn.close()

    # 這支端點吃的是 `period`（不是 start/end）；`salesPerf` 本來就用全部案件
    # 彙總、不受期別篩選影響，所以用預設期別即可
    r = client.get("/api/reports/financial", headers=headers)
    assert r.status_code == 200, r.text
    sales = {s["salesPerson"]: s for s in (r.json().get("salesPerf") or [])}
    assert "高晟耀" in sales, f"應歸給案件的業務負責：{list(sales)}"
    assert "黃玉龍" not in sales, f"不該歸給開單的人：{list(sales)}"
    assert sales["高晟耀"]["totalAmount"] == 300000
