# -*- coding: utf-8 -*-
"""`BN14` · 獎金人員來源要有群組（`docs/windows/SPEC-BN14.md`）。

使用者原話：「獎金分潤的人員來源要有群組的區分，可以把後勤單位的人列入
人員來源，如有複數人員自動計算比例」。

# 🔴 `BN14` 併掉 `BN3`，本檔取代 `test_bonus_manual_and_picker_2026_09_23.py`
# 裡「BN3：manual 來源」那一段（4 題，`person_source="manual"` ＋ 項目直接
# 掛一份 `people` 清單那個形狀）

```
舊（未落地，產品碼一行都還沒寫）  bonus_item_people(bonus_item_id, username)
新（本檔）                       bonus_groups ＋ bonus_group_members
```
⚠️ **更正（本檔寫完之後才發生）**：A 後來又收回「BN14 取代 BN3」這個
判斷——使用者給了一個一次性名單的真實用例（「過往很多沒有填寫案件管理
專案執行人，導致無法帶入」），⇒ 「manual／一次性名單」另外開
`BN18`（規格待交），與本檔的「群組」是**兩種不同的東西**（群組先定義
再選、手動是當下挑人不留下可重用的東西），不是二選一。

⇒ **`test_bonus_manual_and_picker_2026_09_23.py` 的 BN3 那 4 題本檔
沒有動它**（本檔原本規劃「保留過去、加一段指到本檔的說明」，而在
執行前收到 A 的 hold，改成「表換了，哪幾題可留由 C 判斷，等 `BN18`
規格出來再決定」——那 4 題**目前仍原封不動留在原檔**，不要假設本檔
已經幫它們寫了任何指標）。

# ⚙️ 從 `BN3` 帶過來、沒有被併掉的那一半

```
✅ 「綁帳號，不存自由文字」這條界線——本檔的群組成員一律存 `username`
   ❌ 存 display_name／自由輸入 => 打錯一個字那個人就領不到，畫面上一切正常
✅ 「解析出 0 人 ⇒ 拒絕該項目」——空群組同一條路（§3）
```

# ⚙️ 觀測點：走下游／走既有的「先問再做」端點，不猜內部函式簽章

`people_for_item(item, case)` 的簽章要不要為了讀群組成員而改
（多一個 `conn` 參數？把群組資料塞進 `case` 字典？）是 B 的實作決定，
本檔不猜。全部走已經存在的端點：
```
POST /api/bonus/items                  建項目（person_source="group"）
GET  /api/bonus/awards/plan/{quote_no} 先問：這個案件現在可以發給誰
POST /api/bonus/awards/plan/{quote_no} 預覽：帶 allocations，只算不寫
                                        （與 POST /awards 共用同一支
                                        _plan_allocations()，`§6④` 已經
                                        裁定兩者必須逐筆相等——用預覽
                                        驗證均分結果，不必每次都真的
                                        產生一張獎金單再清乾淨）
POST /api/bonus/awards                 真的產生（③ⓒ 凍結那一題需要）
```

# 🔴 一個做了但尚未證實的假設：**自動計算比例在後端算，不是前端**

`_plan_allocations()` 今天**一律**從呼叫端拿 `person_pct`
（`alloc.get("person_pct") or {}`，`routers/bonus.py:596`）——目前**沒有
任何一個來源**做自動均分，連 `case_stages.assigned_to`（本來就可能是
多人）也是前端自己組好送進來。

本檔假設：`person_source == "group"` 時，`_plan_allocations()`（或它
呼叫的某個共用點）**看到呼叫端沒有送 `person_pct`（或送的是空字典）
就自動算均分**，因為「如有複數人員自動計算比例」讀起來是系統的責任，
不是叫使用者自己心算 `10000 // 人數`。⚠️ **若 B 的設計是反過來
（前端算好送進來，後端只驗證）**，本檔的端到端測試（③）會在錯的
地方紅——退回給我改觀測點，不影響①②④⑤⑥⑦（那幾題不依賴這個假設）。
"""

# ── 2026-09-24 移除（SPEC-BONUS §十一）───────────────────────────────────────
# 舊「獎金項目＋分潤單」流程停用：寫入端點回 410、bonus.html 改為以案件為中心的新頁面
# （使用者：「上一次開發的內容我無法接受」「重做成新流程」、舊單「舊的都是開發機測試用，直接作廢」）。
# 本檔下列題驗的是已停用的流程，已移除；新流程的題見 test_bonus_case_*_2026_09_24.py、
# test_e2e_bonus_case_page_2026_09_24.py、test_bonus_legacy_retired_2026_09_24.py。
# 移除：test_bn14_a_deactivated_group_item_is_refused_for_new_awards、test_bn14_a_generated_award_is_frozen_against_later_group_changes、test_bn14_a_group_item_pays_all_active_members、test_bn14_an_empty_group_item_is_refused_not_zero_lines、test_bn14_equal_split_with_four_people_has_a_different_remainder_shape、test_bn14_equal_split_with_three_people_puts_the_remainder_aside、test_bn14_equal_split_with_two_people_has_no_remainder、test_bn14_the_existing_person_sources_are_unaffected、test_bn14_two_items_on_the_same_award_do_not_bleed_into_each_other
# 同檔其餘題驗的是仍在運作的部分（讀取端點、群組、輔助函式），保留。
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

ITEMS = "/api/bonus/items"
PLAN_GET = "/api/bonus/awards/plan/%s"
PLAN_POST = "/api/bonus/awards/plan/%s"
AWARDS = "/api/bonus/awards"


def _hdr(client, make_user, username, role="superadmin", modules=None):
    u, p = make_user(username=username, role=role, modules=modules)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _seed_case(quote_no, net_profit, settle_status="finalized"):
    import json
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, "
            "project_name, total, pretax, deal_tag, data_json, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試案", 0, 0, "已結案",
             json.dumps({"settlement": {"status": settle_status,
                                        "summary": {"netProfit": net_profit}}}),
             "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _table_columns(name):
    import db
    conn = db.get_db()
    try:
        return {r["name"] for r in conn.execute("PRAGMA table_info(%s)" % name)}
    finally:
        conn.close()


def _seed_group(name, usernames, is_active=1):
    """直接種一個群組——群組管理 CRUD 端點還沒有人建，這裡繞過去。

    ⚠️ 欄位逐字照抄 `SPEC-BN14.md §2b`：
    `bonus_groups(id, name, is_active, created_by, created_at, updated_at)`
    `bonus_group_members(group_id, username)`。若 B 落地時欄位不同，
    這支會先因為 `OperationalError` 紅，不會是別的原因。
    """
    import db
    conn = db.get_db()
    try:
        cur = conn.execute(
            "INSERT INTO bonus_groups (name, is_active, created_by,"
            " created_at, updated_at) VALUES (?,?,?,?,?)",
            (name, is_active, "seed", "2026-09-01", "2026-09-01"))
        gid = cur.lastrowid
        for u in usernames:
            conn.execute(
                "INSERT INTO bonus_group_members (group_id, username)"
                " VALUES (?,?)", (gid, u))
        conn.commit()
        return gid
    finally:
        conn.close()


def _remove_member(gid, username):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "DELETE FROM bonus_group_members WHERE group_id = ? AND username = ?",
            (gid, username))
        conn.commit()
    finally:
        conn.close()


def _set_group_active(gid, is_active):
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE bonus_groups SET is_active = ? WHERE id = ?",
                     (is_active, gid))
        conn.commit()
    finally:
        conn.close()


def _create_item(client, hdr, name, person_source, person_source_ref=None):
    body = {"name": name, "person_source": person_source}
    if person_source_ref is not None:
        body["person_source_ref"] = person_source_ref
    r = client.post(ITEMS, headers=hdr, json=body)
    return r


def _plan_get(client, hdr, quote_no):
    return client.get(PLAN_GET % quote_no, headers=hdr)


def _preview(client, hdr, quote_no, allocations):
    return client.post(PLAN_POST % quote_no, headers=hdr,
                       json={"allocations": allocations})


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


# ══════════════════════════════════════════════════════════════════════
# ① 結構：新表／新欄位／新來源值存在
# ══════════════════════════════════════════════════════════════════════

def test_bn14_the_group_tables_and_column_exist(client):
    """🔴🔴 **`bonus_groups`／`bonus_group_members` 兩張新表、
    `bonus_items.person_source_ref` 新欄位都要存在。**

    ⚙️ 欄位集合逐一核對，不是只看表在不在——少一欄的症狀是「表看起來對，
    某個查詢一用到那欄就 `OperationalError`」，比表不存在更晚被發現。
    """
    groups_cols = _table_columns("bonus_groups")
    assert groups_cols, "`bonus_groups` 這張表不存在。"
    for col in ("id", "name", "is_active", "created_by", "created_at",
               "updated_at"):
        assert col in groups_cols, (
            "`bonus_groups` 少了欄位 `%s`（現有：%r）" % (col, sorted(groups_cols)))

    members_cols = _table_columns("bonus_group_members")
    assert members_cols, "`bonus_group_members` 這張表不存在。"
    for col in ("group_id", "username"):
        assert col in members_cols, (
            "`bonus_group_members` 少了欄位 `%s`（現有：%r）"
            % (col, sorted(members_cols)))

    items_cols = _table_columns("bonus_items")
    assert "person_source_ref" in items_cols, (
        "`bonus_items` 沒有 `person_source_ref` 欄位（現有：%r）——\n"
        % sorted(items_cols)
        + "📌 `SPEC-BN14.md §3` 建議甲案：型別（`person_source`）與實例"
          "（哪一個群組）分開存，不要編碼成 `\"group:2\"` 這種字串。")


def test_bn14_person_sources_includes_group():
    """🔴 **`PERSON_SOURCES` 要多一個 `\"group\"` 值。**"""
    from helpers.bonus import PERSON_SOURCES
    assert "group" in PERSON_SOURCES, (
        "`PERSON_SOURCES` 現在是 %r，沒有 `\"group\"`。" % (PERSON_SOURCES,))


def test_bn14_group_membership_rejects_an_unknown_username(client):
    """🔴 **群組成員只能是真實帳號——資料層要擋得住，不是只靠應用層記得檢查。**

    ☠️ 打錯一個字那個人就領不到，而畫面上一切正常——這是 `BN3` 保留下來
    那條界線（〈綁帳號不存自由文字〉）在群組成員上的版本。這裡直接測
    **資料層**：試著塞一個不存在的帳號當成員，預期被擋（`FOREIGN KEY`
    或等價的資料層約束），不是等到「產生獎金單」那一刻才在應用層發現。

    # 🔴 補記（2026-09-23）：本題原本沒 request `client`，打的是共用開發庫

    `_seed_group()` 直接呼叫 `db.get_db()`，沒有 `client` fixture 就沒有
    任何東西把 `db.DB_PATH` 導去隔離的 tmp DB（見 `conftest.py:402`）——
    這支會**真的寫進共用開發庫**。而 `bonus_groups.name` 是
    `NOT NULL UNIQUE`（`db.py:4339`），本題每次都種同一個名字
    `"BN14-測試群組-髒資料"`，**第二次重跑就會在 `_seed_group()` 那一行
    （在 `pytest.raises` 區塊外）撞 `IntegrityError`**——不是「假綠燈」，
    是**直接 ERROR 且弄髒共用庫**，B 重跑時真的撞到，手動清過殘留列。

    ⚠️ 這是**一支的修法**——〈診斷的層級決定覆蓋率〉：答「一支」就只修
    一支，不動 `conftest.py`。**母體已量**：D（2026-09-23，AST 遞迴展開
    fixture 依賴鏈，含跨檔 `import`）掃過全部 2,227 支 test 函式，「碰
    DB 且展開不到隔離根」= 0 支（加總自檢 0+1127+1100=2227 ✓）——本題
    是修好之前那唯一一支。⚠️ D 自己標了射程：他的尺靠解析 `import` 接
    跨檔 fixture，**子目錄自己的 `conftest.py`（不需要 `import` 就生效）
    那種形狀他看不見**，這件已另外派他去查。

    # ✅ 牙齒已驗證（方式：突變驗證／live，非常設）

    用同一個 tmp db 路徑連續呼叫兩次「未 request `client`」版本的邏輯
    （真實失效模式：沒有隔離 fixture 導致殘留跨執行緒留存），第二次在
    `_seed_group()` 就 raise `IntegrityError`（撞 `name` UNIQUE），與 B
    回報的現象一致；改回本題現在的寫法（request `client`）後，同一段
    邏輯連續呼叫兩次都拿到全新空庫，兩次都在預期的那一行（成員 FK）
    raise，不會在 `_seed_group()` 那一行提早炸開。
    """
    import sqlite3
    import db
    gid = _seed_group("BN14-測試群組-髒資料", [])
    conn = db.get_db()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO bonus_group_members (group_id, username)"
                " VALUES (?,?)", (gid, "nobody_here_9912"))
            conn.commit()
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════
# ② 端到端：群組來源的項目，產生時展開成 N 列並自動均分
# ══════════════════════════════════════════════════════════════════════

def test_bn14_deactivating_a_group_does_not_clear_its_member_list(
        client, make_user):
    """🔴 **`§7`：停用群組時成員清單要保留，重新啟用還是同一群人。**

    ☠️ 清空的話，重新啟用會是一個空群組，而畫面上看起來完全正常——
    使用者不會發現整批成員不見了，直到有人抱怨自己沒領到錢。
    """
    a, _ = _hdr(client, make_user, "bn14_keep1")
    b, _ = _hdr(client, make_user, "bn14_keep2")
    gid = _seed_group("BN14-保留成員測試", [a, b])

    _set_group_active(gid, 0)

    import db
    conn = db.get_db()
    try:
        members = {r["username"] for r in conn.execute(
            "SELECT username FROM bonus_group_members WHERE group_id = ?",
            (gid,))}
    finally:
        conn.close()
    assert members == {a, b}, (
        "群組停用之後成員清單變成 %r，預期仍是 %r——\n" % (members, {a, b})
        + "☠️ 停用不應該清空成員，那會讓重新啟用之後變成一個空群組。")


# ══════════════════════════════════════════════════════════════════════
# ④ 凍結：產生之後群組怎麼變都不影響已產生的單
# ══════════════════════════════════════════════════════════════════════

def test_bn14_the_group_source_check_is_not_scattered_across_the_codebase():
    """✅ **守門：字面比對 `person_source == "group"`（或等價寫法）
    只應該出現在人員解析那一支共用邏輯附近，不是散在各個呼叫端各自
    判斷一次。**

    🔑 規格原話：「`PERSON_SOURCES` 是唯一真相，`people_for_item()` 是
    唯一解析點……在呼叫端加 `if source == "group"` = 把接縫拆成兩個，
    而第二個接縫沒有人會記得去維護。」

    ⚠️ 本題**只掃字面比對次數當警訊，不判定對錯**——多於一處不必然是
    錯的（例如 `_plan_allocations()` 為了自動均分而多看一次
    `person_source` 是合理的，見檔頭「一個做了但尚未證實的假設」），
    但超過某個數字時**要有人回頭看一眼是不是把判斷拆散了**，不是自動
    判紅；本題印出所有命中位置供人工核對。
    """
    import ast
    root = Path(__file__).resolve().parents[2]
    hits = []
    for py in (root / "backend").rglob("*.py"):
        parts = py.relative_to(root).parts
        if "tests" in parts or "rollback_snapshots" in parts:
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare) and len(node.ops) == 1 and \
                    isinstance(node.ops[0], (ast.Eq, ast.NotEq)):
                for side in (node.left, node.comparators[0]):
                    if isinstance(side, ast.Constant) and side.value == "group":
                        hits.append("%s:%d" % (py.relative_to(root), node.lineno))
    assert len(hits) <= 3, (
        "字面比對 `\"group\"` 出現在 %d 個地方，超過預期的少數幾處"
        "（多半是人員解析＋自動均分兩處）：\n%s\n"
        % (len(hits), "\n".join("  %s" % h for h in hits))
        + "📌 這不是自動判紅，是提醒回頭看一下是不是把判斷拆散了——\n"
          "   每一處新增的比對都要能講出「為什麼這裡也要看一次」。")
