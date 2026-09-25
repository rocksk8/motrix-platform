# -*- coding: utf-8 -*-
"""`BN18` · 產生獎金單時手動指定人員（`SPEC-BN18.md`，B 已實作
`efbc1c1` + `564eedf`）。

# 🔴 為什麼要補題

B 的實作沒有帶測試（協定：B 不寫測試，C 才寫）。照 `SPEC-BN18.md §6
AC1` 逐點釘驗收，直接打真實端點。

# 🔴 判準：`person_source_override` 是明著宣告，不可以用 `people` 真假值決定分支

`SPEC-BN18.md §4` 逐字：
```
❌ `if alloc.get("people"):`  <= 那等於「有值就覆蓋」
✅ `if alloc.get("person_source_override"):`
```
〈null 不等於 0〉在這一題的落點：「沒送這個鍵」與「送了一個空清單」是
兩件事，若判斷式改成看 `people` 真假值，一個**帶 `people` 而沒有明著
宣告 override**的呼叫端會被安靜地覆蓋掉正確的解析結果——金額照算、
總額照樣對得起來，沒有人發現。本檔 ③ⓒ 就是這個誘餌的下游驗收，
§5 另外補一支 AST 結構守門直接讀原始碼判斷式。

# ⚙️ 觀測點：走 `POST /api/bonus/awards`，驗下游 `bonus_award_lines`

不呼叫 `_plan_allocations()` 本身——它的簽章可能因為 B 的實作決定而變，
全部走既有端點。

# ✅ 牙齒已驗證（方式：資料建構／常設）

③ⓓ（兩個項目各自指定不同人）與 ③ⓒ（負對照：帶 people 沒旗標仍走解析）
都是**構造出「單層實作會蓋掉這件事」的具體反例**去驗——單層或
`if people:` 這兩種錯誤實作都會在這兩題上產生**可觀察、與正確實作不同**
的下游資料，不是靠語意猜測。
"""

# ── 2026-09-24 移除（SPEC-BONUS §十一）───────────────────────────────────────
# 舊「獎金項目＋分潤單」流程停用：寫入端點回 410、bonus.html 改為以案件為中心的新頁面
# （使用者：「上一次開發的內容我無法接受」「重做成新流程」、舊單「舊的都是開發機測試用，直接作廢」）。
# 本檔下列題驗的是已停用的流程，已移除；新流程的題見 test_bonus_case_*_2026_09_24.py、
# test_e2e_bonus_case_page_2026_09_24.py、test_bonus_legacy_retired_2026_09_24.py。
# 移除：test_bn18_a_deactivated_username_is_also_refused、test_bn18_an_unknown_username_is_refused_with_zero_side_effects、test_bn18_manual_basis_records_the_original_source_type_and_resolution、test_bn18_manual_lines_are_snapshotted_as_manual_with_real_usernames、test_bn18_people_without_the_override_flag_is_ignored_resolution_wins、test_bn18_two_items_each_get_their_own_manual_people_no_cross_talk、test_bn18_with_override_the_same_case_now_succeeds、test_bn18_without_override_a_case_with_no_executor_is_still_refused
# 同檔其餘題驗的是仍在運作的部分（讀取端點、群組、輔助函式），保留。
import json

import pytest

AWARDS = "/api/bonus/awards"


def _hdr(client, make_user, username, role="superadmin", modules=None):
    u, p = make_user(username=username, role=role,
                      modules=modules if modules is not None else ["reports"])
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _seed_case(quote_no, net_profit=1000000, sales_person="alice",
               stage_people=None):
    """種一個有精算淨利的案件。`stage_people=None` ⇒ 一個階段負責人都沒有
    （對應 SPEC-BN18.md §5b 的真實現況：`case_stages.assigned_to` 100% 空）。
    """
    import db
    conn = db.get_db()
    try:
        sales_person_id = None
        row = conn.execute(
            "SELECT id FROM users WHERE username = ? AND active = 1",
            (sales_person,)).fetchone()
        if row is not None:
            sales_person_id = int(row["id"])
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, "
            "project_name, total, pretax, sales_person, sales_person_id,"
            " data_json, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已結案", "測試客戶", "測試案", 0, 0, sales_person,
             sales_person_id,
             json.dumps({"settlement": {"summary": {"netProfit": net_profit}}}),
             "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        if stage_people is not None:
            conn.execute(
                "INSERT INTO case_stages (quote_no, assigned_to, "
                "created_at, updated_at) VALUES (?,?,?,?)",
                (quote_no, json.dumps(stage_people),
                 "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _seed_item(name, person_source, is_active=1):
    import db
    conn = db.get_db()
    try:
        cur = conn.execute(
            "INSERT INTO bonus_items (name, person_source, sort_order, "
            "is_active, created_by, created_at, updated_at) "
            "VALUES (?,?,0,?,'seed','2026-09-01','2026-09-01')",
            (name, person_source, is_active))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _award_lines(award_id=None, quote_no=None):
    import db
    conn = db.get_db()
    try:
        if award_id is not None:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM bonus_award_lines WHERE award_id = ?"
                " ORDER BY id", (award_id,))]
        row = conn.execute(
            "SELECT id FROM bonus_awards WHERE quote_no = ? AND voided_at = ''",
            (quote_no,)).fetchone()
        if row is None:
            return []
        return [dict(r) for r in conn.execute(
            "SELECT * FROM bonus_award_lines WHERE award_id = ? ORDER BY id",
            (row["id"],))]
    finally:
        conn.close()


def _counts():
    import db
    conn = db.get_db()
    try:
        a = conn.execute("SELECT COUNT(*) c FROM bonus_awards").fetchone()["c"]
        l = conn.execute(
            "SELECT COUNT(*) c FROM bonus_award_lines").fetchone()["c"]
        return a, l
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════
# ③ⓐ 沒有執行人的案件：不覆寫 400，覆寫成功
# ══════════════════════════════════════════════════════════════════════

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_bn18_the_override_branch_reads_the_named_flag_not_peoples_truthiness():
    """✅ **AST 結構守門：`_plan_allocations()` 判斷分支的條件式必須是
    對 `person_source_override` 的呼叫，不可以是對 `people` 的真假值判斷。**

    ⚙️ 找函式體裡第一個 `if <test>:` 且 `<test>` 的呼叫鏈裡出現
    `.get("person_source_override")` 或 `.get('person_source_override')`
    ——不用 regex（會被字串／註解騙），直接讀 AST 的 `Compare`／`Call`
    節點結構。
    """
    src = (ROOT / "modules" / "payroll" / "api" / "bonus.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef)
               and n.name == "_plan_allocations"), None)
    assert fn is not None, "找不到 `_plan_allocations()`——退回改本題的錨點。"

    def _mentions_override_key(node):
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and sub.value == "person_source_override":
                return True
        return False

    def _mentions_bare_people_key(node):
        """`alloc.get("people")` 這個呼叫本身（不含巢狀在 override 呼叫
        裡的那種），用來判斷是不是誤把 people 真假值當分支條件。"""
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "get":
                if node.args and isinstance(node.args[0], ast.Constant) \
                        and node.args[0].value == "people":
                    return True
        return False

    found_override_branch = False
    bad_people_branch = False
    for node in ast.walk(fn):
        if isinstance(node, ast.If):
            if _mentions_override_key(node.test):
                found_override_branch = True
            # 判斷式本身（不含 body）只看 people 真假值 ⇒ 這是規格明著
            # 禁止的形狀。用 ast.walk(node.test) 而不是 node.body，避免
            # 把「body 裡用到 people」誤判成「條件式看 people」。
            for sub in ast.walk(node.test):
                if _mentions_bare_people_key(sub) and not _mentions_override_key(node.test):
                    bad_people_branch = True

    assert found_override_branch, (
        "`_plan_allocations()` 裡找不到任何檢查 `person_source_override` "
        "的 `if` 分支——退回改本題或確認實作方式。")
    assert not bad_people_branch, (
        "`_plan_allocations()` 裡有一個 `if` 分支的條件式只看 `people` "
        "的真假值，沒有看 `person_source_override`——\n"
        + "☠️ 這正是規格點名要擋的假綠燈來源：`if alloc.get(\"people\"):`"
          "會讓帶 people 卻沒宣告覆寫的呼叫端被安靜地覆蓋。")
