# -*- coding: utf-8 -*-
"""`QS1-a` · 獎金的 `sales_person` 來源要走 `sales_person_id` 解出真的
`username`，不是 `quotations.sales_person` 那個顯示名字串
（`docs/windows/SPEC-QS1.md §3③`）。

# 🔴 範圍：本檔**只做 QS1 裡跟獎金相依的那一小塊**

`SPEC-QS1.md` 本身範圍大得多（`quotations.sales_person_id` 的兩層
回填 migration、26 個讀取端逐一判斷顯示用／識別用）——那是完整 `QS1`
的範圍，A 交代這一塊是「`BN14`／`BN18` 的前置」，本檔只覆蓋這一塊：

```
✅ modules/payroll/bonus.py::people_for_item() 的 "sales_person" 來源
   要解析出 users.username，不是 quotations.sales_person 的顯示名字串
❌ 不做 26 個讀取端的顯示用／識別用逐一分類（那是完整 QS1 的範圍）
❌ 不做 migration 的兩層回填與 K 筆列名 logging（同上）
```

# ⚙️ 現況（查證）

```
modules/payroll/api/bonus.py::_case_people()：
    SELECT quote_no, sales_person, owner, engineer FROM quotations …
    case["sales_person"] = 那一欄的**顯示名字串**（例如「黃玉龍」）
modules/payroll/bonus.py::people_for_item()：
    source == "sales_person" 時走 case.get(source) —— 拿到顯示名
```
⇒ `bonus_award_lines.username` 存進去的是顯示名，不是真的帳號——同一個
問題 `BN14 §6` 已經在 `bonus_award_lines` 那一端量過（4 列全是測試
資料）。這裡是**上游**：`people_for_item()` 從一開始就沒有拿到真的
`username`，下游存什麼都只是把上游的錯誤原樣搬過去。

# 🔑 修法落點：**在來源解決，不要在消費端各自防**（A 引用的判準）

`_case_people()` 已經是「把案件上的人彙整成 `people_for_item()` 吃得下
的形狀」那個唯一接縫——修法應該是它多查一個 `sales_person_id`，解析出
`users.username` 之後**換掉** `case["sales_person"]` 的值，而不是在
`people_for_item()` 或更下游另外加一層轉換。`BN14 §2` 的「綁帳號不存
自由文字」那條界線因此在**來源**就自動成立，不必在獎金這一側各自防。

# ⚠️ 負對照：**顯示用的地方不可以被一起改成 username**

`pdf_gen.py:2541`／`:3059` 的 `"salesPerson": row["sales_person"] or ""`
是報價單 PDF「業務」欄要印的**顯示名**——這裡**不可以**變成
`sales_person_id` 解出來的 `username`（那會讓紙本印出帳號字串）。
少了這一格，「把 `sales_person` 全部改用 `sales_person_id`」這種
一次改到底的修法會讓上面的核心題綠，而報價單 PDF 上印出 `jeff`。
"""

# ── 2026-09-24 移除（SPEC-BONUS §十一）───────────────────────────────────────
# 舊「獎金項目＋分潤單」流程停用：寫入端點回 410、bonus.html 改為以案件為中心的新頁面
# （使用者：「上一次開發的內容我無法接受」「重做成新流程」、舊單「舊的都是開發機測試用，直接作廢」）。
# 本檔下列題驗的是已停用的流程，已移除；新流程的題見 test_bonus_case_*_2026_09_24.py、
# test_e2e_bonus_case_page_2026_09_24.py、test_bonus_legacy_retired_2026_09_24.py。
# 移除：test_qs1a_generating_an_award_stores_the_username_not_the_display_name、test_qs1a_the_case_stages_source_is_unaffected、test_qs1a_the_sales_person_source_resolves_to_the_real_username
# 同檔其餘題驗的是仍在運作的部分（讀取端點、群組、輔助函式），保留。
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

ITEMS = "/api/bonus/items"
PLAN_GET = "/api/bonus/awards/plan/%s"
AWARDS = "/api/bonus/awards"


def _hdr(client, make_user, username, role="superadmin", modules=None):
    u, p = make_user(username=username, role=role, modules=modules)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _seed_case_with_sales_person(quote_no, sales_person_id, legacy_display_name,
                                 net_profit=1000000):
    """種一張案件，`sales_person`（顯示名字串，**刻意寫舊格式**）與
    `sales_person_id`（真的 FK）分開設定——模擬 `QS1 §2` 描述的現況：
    兩個欄位並存，而只有 `_id` 那個是可靠的識別。
    """
    import json
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, "
            "project_name, total, pretax, deal_tag, sales_person,"
            " sales_person_id, data_json, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試案", 0, 0, "已結案",
             legacy_display_name, sales_person_id,
             json.dumps({"settlement": {"status": "finalized",
                                        "summary": {"netProfit": net_profit}}}),
             "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _create_item(client, hdr, name, person_source):
    return client.post(ITEMS, headers=hdr,
                       json={"name": name, "person_source": person_source})


def _plan_get(client, hdr, quote_no):
    return client.get(PLAN_GET % quote_no, headers=hdr)


def _create_award(client, hdr, quote_no, allocations):
    return client.post(AWARDS, headers=hdr,
                       json={"quote_no": quote_no, "allocations": allocations})


def _lines_of(award_id):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM bonus_award_lines WHERE award_id = ? ORDER BY id",
            (award_id,))]
    finally:
        conn.close()


def _user_id(username):
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT id FROM users WHERE username = ?",
                           (username,)).fetchone()
        assert row is not None, "找不到使用者 %r" % username
        return int(row["id"])
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════
# ① 核心：sales_person 來源要解析出真的 username
# ══════════════════════════════════════════════════════════════════════

def test_qs1a_the_quotation_pdf_still_shows_the_display_name_not_username():
    """⚙️🔴 **負對照：報價單 PDF「業務」欄仍然讀 `quotations.sales_person`
    這個顯示名欄位，不可以被一起改成 `sales_person_id` 解出來的
    `username`。**

    ☠️ 少了這一題，「把 `sales_person` 全部改用 `sales_person_id`」這種
    一次改到底的修法會讓上一題綠，而報價單 PDF 上會印出帳號字串
    （例如 `jeff`）給客戶看。
    ⚙️ 這裡用結構層檢查（原始碼裡 `"salesPerson"` 這個 PDF 欄位的值
    來源），不整份跑 PDF 產生——那條路徑很重，這裡只驗「還沒有人把
    它改掉」。
    """
    root = Path(__file__).resolve().parents[2]
    src = (root / "backend" / "pdf_gen.py").read_text(
        encoding="utf-8", errors="replace")
    import re
    matches = re.findall(
        r'"salesPerson":\s*([^,\n]+)', src)
    assert matches, (
        "`pdf_gen.py` 裡找不到 `\"salesPerson\"` 這個欄位——\n"
        "☠️ 報價單 PDF 的業務欄位可能被搬走了，退回改本題的觀測點。")
    for expr in matches:
        assert "sales_person_id" not in expr, (
            "`pdf_gen.py` 的 `\"salesPerson\"` 欄位值改成讀 "
            "`sales_person_id`：%r\n" % expr
            + "☠️ 那會讓報價單 PDF 印出帳號字串，不是給客戶看的顯示名。")
        assert "row[\"sales_person\"]" in expr or "row['sales_person']" in expr, (
            "`pdf_gen.py` 的 `\"salesPerson\"` 欄位值變成了 %r，"
            "不再是預期的 `row[\"sales_person\"]`——\n" % expr
            + "退回改本題的觀測點，確認它是不是仍然讀顯示名欄位。")


