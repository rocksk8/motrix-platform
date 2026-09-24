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

def test_bn14_a_group_item_pays_all_active_members(client, make_user):
    """🔴🔴 **核心：3 人群組的項目，預覽出來要有 3 個人，都是群組成員。**

    ⚙️ 先驗「誰」，下一題再驗「均分算得對不對」——分開驗，紅了才知道是
    人員解析錯還是均分算式錯。
    """
    a, _ = _hdr(client, make_user, "bn14_p1")
    b, _ = _hdr(client, make_user, "bn14_p2")
    c, _ = _hdr(client, make_user, "bn14_p3")
    gid = _seed_group("BN14-核心群組", [a, b, c])

    quote_no = "MQ-BN14-CORE"
    _seed_case(quote_no, 1000000)
    _u, hdr = _hdr(client, make_user, "bn14_core_sup")

    r = _create_item(client, hdr, "後勤獎金", "group", person_source_ref=gid)
    assert r.status_code == 200, (
        "建立 `person_source=\"group\"` 的項目失敗：%s %s"
        % (r.status_code, r.text[:300]))
    item_id = (r.json() or {}).get("id")
    assert item_id, "回應沒有 id：%r" % r.json()

    plan = _plan_get(client, hdr, quote_no)
    assert plan.status_code == 200, plan.text[:300]
    entry = next((it for it in plan.json().get("items") or ()
                 if it.get("bonus_item_id") == item_id), None)
    assert entry is not None, "先問端點的清單裡找不到這個項目。"
    assert entry.get("ok") is True, (
        "群組項目解析失敗：%r" % entry)
    assert set(entry.get("people") or ()) == {a, b, c}, (
        "群組項目解析出的人員是 %r，預期群組的 3 個成員 %r。"
        % (entry.get("people"), {a, b, c}))


def test_bn14_equal_split_with_three_people_puts_the_remainder_aside(
        client, make_user):
    """🔴🔴 **`§8③ⓐⓑ`：3 人均分 10000 基點 => 3333/3333/3333，
    餘 1 基點進尾差；各列金額加總＋尾差＝總發放額，一元不差。**
    """
    a, _ = _hdr(client, make_user, "bn14_e1")
    b, _ = _hdr(client, make_user, "bn14_e2")
    c, _ = _hdr(client, make_user, "bn14_e3")
    gid = _seed_group("BN14-均分3人", [a, b, c])

    quote_no = "MQ-BN14-SPLIT3"
    _seed_case(quote_no, 1000000)
    _u, hdr = _hdr(client, make_user, "bn14_split3_sup")
    r = _create_item(client, hdr, "均分測試3人", "group", person_source_ref=gid)
    assert r.status_code == 200, r.text[:300]
    item_id = r.json()["id"]

    prev = _preview(client, hdr, quote_no,
                    [{"bonus_item_id": item_id, "total_pct": 10000}])
    assert prev.status_code == 200, (
        "預覽失敗：%s %s\n" % (prev.status_code, prev.text[:300])
        + "⚠️ 若這裡因為「人員比例全部是 0」被拒，見檔頭的假設說明——\n"
          "   可能後端設計是要呼叫端自己送均分好的 `person_pct`，退回改本題。")
    body = prev.json()
    lines = [l for l in body["lines"] if l["bonus_item_id"] == item_id]
    assert len(lines) == 3, "應該有 3 列，實際 %d：%r" % (len(lines), lines)

    pcts = sorted(l["person_pct"] for l in lines)
    assert pcts == [3333, 3333, 3333], (
        "3 人均分 10000 基點，person_pct 應該是 [3333, 3333, 3333]，"
        "實際 %r" % pcts)

    pool = 1000000  # base=1,000,000，total_pct=10000（100%）=> pool=base
    total_amount = sum(l["amount"] for l in lines)
    assert total_amount + body["remainder"] == pool, (
        "各列金額加總（%d）＋ 尾差（%d）＝ %d，預期等於獎金池 %d——\n"
        % (total_amount, body["remainder"], total_amount + body["remainder"], pool)
        + "☠️ 差一塊錢，使用者自己加總會發現對不起來。")
    assert body["remainder"] > 0, (
        "3 人分不盡，尾差應該 > 0，實際 %r——\n" % body["remainder"]
        + "☠️ 只測分得盡的情況，尾差的路徑一次都不會跑到。")


def test_bn14_equal_split_with_four_people_has_a_different_remainder_shape(
        client, make_user):
    """🔴 **4 人均分：另一種分不盡（`10000 // 4 = 2500`，剛好整除）。**

    ⚠️ 4 人剛好整除基點層（2500×4=10000），但**金額層**仍可能有餘數
    （`pool × 2500 // 10000` 對奇數的 `pool` 會截斷）——這一題釘的是
    「基點層分得盡」時金額層尾差**仍然可能不是 0**，不要假設兩層尾差
    同進同出。
    """
    people = []
    for i in range(4):
        u, _ = _hdr(client, make_user, "bn14_f%d" % i)
        people.append(u)
    gid = _seed_group("BN14-均分4人", people)

    quote_no = "MQ-BN14-SPLIT4"
    _seed_case(quote_no, 1000001)  # 刻意用奇數，讓金額層截斷有機會出現
    _u, hdr = _hdr(client, make_user, "bn14_split4_sup")
    r = _create_item(client, hdr, "均分測試4人", "group", person_source_ref=gid)
    assert r.status_code == 200, r.text[:300]
    item_id = r.json()["id"]

    prev = _preview(client, hdr, quote_no,
                    [{"bonus_item_id": item_id, "total_pct": 10000}])
    assert prev.status_code == 200, prev.text[:300]
    body = prev.json()
    lines = [l for l in body["lines"] if l["bonus_item_id"] == item_id]
    assert len(lines) == 4, "應該有 4 列，實際 %d" % len(lines)
    pcts = sorted(l["person_pct"] for l in lines)
    assert pcts == [2500, 2500, 2500, 2500], (
        "4 人均分應該是 [2500]*4，實際 %r" % pcts)

    pool = 1000001
    total_amount = sum(l["amount"] for l in lines)
    assert total_amount + body["remainder"] == pool, (
        "4 人：金額加總＋尾差應該等於獎金池 %d，實際 %d"
        % (pool, total_amount + body["remainder"]))


def test_bn14_equal_split_with_two_people_has_no_remainder(client, make_user):
    """⚙️ **正對照：2 人剛好分得盡，尾差＝0——不是每次都硬擠出一個尾差。**

    ☠️ 少了這一題，「均分永遠留 1 基點尾差」這種寫死的錯誤實作也會讓
    上面兩題綠（它們都是分不盡的情況）。
    """
    a, _ = _hdr(client, make_user, "bn14_two1")
    b, _ = _hdr(client, make_user, "bn14_two2")
    gid = _seed_group("BN14-均分2人", [a, b])

    quote_no = "MQ-BN14-SPLIT2"
    _seed_case(quote_no, 1000000)
    _u, hdr = _hdr(client, make_user, "bn14_split2_sup")
    r = _create_item(client, hdr, "均分測試2人", "group", person_source_ref=gid)
    assert r.status_code == 200, r.text[:300]
    item_id = r.json()["id"]

    prev = _preview(client, hdr, quote_no,
                    [{"bonus_item_id": item_id, "total_pct": 10000}])
    assert prev.status_code == 200, prev.text[:300]
    body = prev.json()
    lines = [l for l in body["lines"] if l["bonus_item_id"] == item_id]
    assert len(lines) == 2
    pcts = sorted(l["person_pct"] for l in lines)
    assert pcts == [5000, 5000], "2 人均分應該是 [5000, 5000]，實際 %r" % pcts
    assert body["remainder"] == 0, (
        "2 人剛好分得盡，尾差應該是 0，實際 %r——\n" % body["remainder"]
        + "☠️ 若永遠不是 0，代表均分算式寫死了一個固定尾差，"
          "不是真的按人數計算。")


# ══════════════════════════════════════════════════════════════════════
# ③ 拒絕：空群組 ／ 停用群組
# ══════════════════════════════════════════════════════════════════════

def test_bn14_an_empty_group_item_is_refused_not_zero_lines(client, make_user):
    """🔴🔴 **`§8③ⓓ`：選一個空群組（建了沒加人）=> 拒絕該項目，
    不是產生 0 列。**

    🔑 這一題的價值在**正式機可能大量出現空群組**這條路會真的被走到
    （群組剛建立、還沒來得及加人）——不是理論案例。
    """
    gid = _seed_group("BN14-空群組", [])

    quote_no = "MQ-BN14-EMPTY"
    _seed_case(quote_no, 1000000)
    _u, hdr = _hdr(client, make_user, "bn14_empty_sup")
    r = _create_item(client, hdr, "空群組項目", "group", person_source_ref=gid)
    assert r.status_code == 200, r.text[:300]
    item_id = r.json()["id"]

    plan = _plan_get(client, hdr, quote_no)
    assert plan.status_code == 200, plan.text[:300]
    entry = next((it for it in plan.json().get("items") or ()
                 if it.get("bonus_item_id") == item_id), None)
    assert entry is not None, "先問端點的清單裡找不到這個項目——它不可以被濾掉。"
    assert entry.get("ok") is False, (
        "空群組的項目被判定成 `ok=True`：%r\n" % entry
        + "☠️ 那會讓它在均分那一步除以 0，或悄悄產生 0 列。")
    assert str(entry.get("note") or "").strip(), (
        "它不可用，而沒有說為什麼：%r" % entry)


def test_bn14_a_deactivated_group_item_is_refused_for_new_awards(client,
                                                                  make_user):
    """🔴 **`§7③`：用已停用的群組產生新獎金單 => 拒絕，不是靜默解析成 0 人。**

    ⚠️ 群組**可停用，不可刪除**（`CA1` 那一族的形狀）——這一題驗的是
    「停用之後不能再被用來產生新單」，不是「停用等於刪除」。
    """
    a, _ = _hdr(client, make_user, "bn14_deact1")
    gid = _seed_group("BN14-停用測試", [a])
    _set_group_active(gid, 0)

    quote_no = "MQ-BN14-DEACT"
    _seed_case(quote_no, 1000000)
    _u, hdr = _hdr(client, make_user, "bn14_deact_sup")
    r = _create_item(client, hdr, "停用群組項目", "group", person_source_ref=gid)
    assert r.status_code == 200, r.text[:300]
    item_id = r.json()["id"]

    plan = _plan_get(client, hdr, quote_no)
    assert plan.status_code == 200, plan.text[:300]
    entry = next((it for it in plan.json().get("items") or ()
                 if it.get("bonus_item_id") == item_id), None)
    assert entry is not None, "先問端點的清單裡找不到這個項目——它不可以被濾掉。"
    assert entry.get("ok") is False, (
        "已停用的群組仍然被判定成 `ok=True`：%r\n" % entry
        + "☠️ 停用的群組不可以再被用來產生新獎金單。")


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

def test_bn14_a_generated_award_is_frozen_against_later_group_changes(
        client, make_user):
    """🔴🔴 **`§8③ⓒ`：產生後把其中一人從群組移除，重開那張獎金單，
    仍然是 3 列（凍結，不是即時展開）。**

    📌 `bonus_award_lines` 已經是這張表的形狀（`item_name_snapshot`／
    `person_source_snapshot` 都是快照）——這一題確認群組來源也遵守
    同一條規則，不必新增機制，但要驗證它真的有遵守。
    """
    a, _ = _hdr(client, make_user, "bn14_frz1")
    b, _ = _hdr(client, make_user, "bn14_frz2")
    c, _ = _hdr(client, make_user, "bn14_frz3")
    gid = _seed_group("BN14-凍結測試", [a, b, c])

    quote_no = "MQ-BN14-FREEZE"
    _seed_case(quote_no, 1000000)
    _u, hdr = _hdr(client, make_user, "bn14_freeze_sup")
    r = _create_item(client, hdr, "凍結測試項目", "group", person_source_ref=gid)
    assert r.status_code == 200, r.text[:300]
    item_id = r.json()["id"]

    ar = _create_award(client, hdr, quote_no,
                       [{"bonus_item_id": item_id, "total_pct": 10000}])
    assert ar.status_code == 200, (
        "產生獎金單失敗：%s %s" % (ar.status_code, ar.text[:300]))
    award_id = ar.json()["id"]

    lines = _lines_of(award_id)
    usernames = {l["username"] for l in lines if l["bonus_item_id"] == item_id}
    assert usernames == {a, b, c}, (
        "產生當下應該是 3 個人，實際 %r" % usernames)

    # 群組異動：移除一個人。
    _remove_member(gid, c)

    # 已產生的那一張不應該跟著變——重新讀一次同一個 award_id。
    lines_after = _lines_of(award_id)
    usernames_after = {l["username"] for l in lines_after
                       if l["bonus_item_id"] == item_id}
    assert usernames_after == {a, b, c}, (
        "移除群組成員之後，已產生的獎金單變成 %r（原本 %r）——\n"
        % (usernames_after, {a, b, c})
        + "☠️ `bonus_award_lines` 是快照，不應該隨群組異動而改變；\n"
          "   若這裡真的即時展開群組，代表凍結沒有生效。")


def test_bn14_two_items_on_the_same_award_do_not_bleed_into_each_other(
        client, make_user):
    """🔴🔴 **項目層 vs 單層：一張單同時有兩個項目時，各自的人員與均分
    不可以互相污染。**

    ⚠️ A 指出的假綠燈風險：今天每張獎金單只有一個項目，「項目層的計算」
    與「整張單的計算」在單一項目的情況下**看起來一樣**，差別驗不出來。
    ⇒ 造一張有**兩個項目**的單：一個 `sales_person`（1 人）＋ 一個
    `group`（3 人，分不盡），驗兩件事：
    ```
    ① 群組項目的均分不會被 sales_person 那個項目的 total_pct 影響
       （各自的 pool 各自算，`pool_for()` 是逐項目呼叫的）
    ② bonus_award_lines 裡兩個項目的人員名單互不交疊、各自的
       bonus_item_id 對得上
    ```
    """
    seller, _ = _hdr(client, make_user, "bn14_multi_seller")
    a, _ = _hdr(client, make_user, "bn14_multi_a")
    b, _ = _hdr(client, make_user, "bn14_multi_b")
    c, _ = _hdr(client, make_user, "bn14_multi_c")
    gid = _seed_group("BN14-多項目測試", [a, b, c])

    quote_no = "MQ-BN14-MULTI"
    _seed_case(quote_no, 1000000)
    _u, hdr = _hdr(client, make_user, "bn14_multi_sup")

    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE quotations SET sales_person = ? WHERE quote_no = ?",
                     (seller, quote_no))
        conn.commit()
    finally:
        conn.close()

    r1 = _create_item(client, hdr, "多項目測試-業務獎金", "sales_person")
    assert r1.status_code == 200, r1.text[:300]
    item_sales = r1.json()["id"]

    r2 = _create_item(client, hdr, "多項目測試-後勤獎金", "group",
                      person_source_ref=gid)
    assert r2.status_code == 200, r2.text[:300]
    item_group = r2.json()["id"]

    prev = _preview(client, hdr, quote_no, [
        {"bonus_item_id": item_sales, "total_pct": 2000,
         "person_pct": {seller: 10000}},
        {"bonus_item_id": item_group, "total_pct": 3000},
    ])
    assert prev.status_code == 200, (
        "兩個項目同時送出的預覽失敗：%s %s" % (prev.status_code, prev.text[:300]))
    body = prev.json()

    sales_lines = [l for l in body["lines"] if l["bonus_item_id"] == item_sales]
    group_lines = [l for l in body["lines"] if l["bonus_item_id"] == item_group]

    assert {l["username"] for l in sales_lines} == {seller}, (
        "業務獎金項目的人員是 %r，預期只有業務 %r——\n"
        % ({l["username"] for l in sales_lines}, seller)
        + "☠️ 若混進了群組成員，代表兩個項目的人員解析互相污染了。")
    assert {l["username"] for l in group_lines} == {a, b, c}, (
        "後勤獎金項目的人員是 %r，預期是群組 3 人 %r——\n"
        % ({l["username"] for l in group_lines}, {a, b, c})
        + "☠️ 若混進了業務，代表兩個項目的人員解析互相污染了。")

    sales_pool = 1000000 * 2000 // 10000  # total_pct=2000（20%）
    group_pool = 1000000 * 3000 // 10000  # total_pct=3000（30%）
    assert sum(l["amount"] for l in sales_lines) == sales_pool, (
        "業務獎金項目（20%%）的金額加總應該是 %d，實際 %d——\n"
        % (sales_pool, sum(l["amount"] for l in sales_lines))
        + "☠️ 若這裡被後勤獎金項目（30%%）的比例污染，加總會對不上。")
    group_pcts = sorted(l["person_pct"] for l in group_lines)
    assert group_pcts == [3333, 3333, 3333], (
        "後勤獎金項目（3 人群組）應該均分成 [3333,3333,3333]，實際 %r——\n"
        % group_pcts
        + "⚠️ 若這裡受業務獎金項目（1 人，100%%）影響變成 [10000]，"
          "代表項目層的均分計算被單層污染了。")


# ══════════════════════════════════════════════════════════════════════
# ⑤ 負對照：既有來源不受影響
# ══════════════════════════════════════════════════════════════════════

def test_bn14_the_existing_person_sources_are_unaffected(client, make_user):
    """⚙️🔴 **負對照：`sales_person`／`case_stages.assigned_to` 的行為
    完全不變（既有的 `BN3` 負對照，換一條觀測路徑：走 `GET /awards/plan`
    這個下游端點，不直接呼叫 `people_for_item()`——那支的簽章可能為了
    群組解析而改變，直接呼叫會誤傷這一題）。**

    ☠️ 最容易踩的是「把 `people_for_item` 改成先查群組表」——那會讓既有
    來源在查不到群組關聯時被誤判成 0 人 ⇒ **全部發不出去**。
    """
    quote_no = "MQ-BN14-EXISTING"
    _seed_case(quote_no, 1000000)
    seller, _ = _hdr(client, make_user, "bn14_existing_seller")
    _u, hdr = _hdr(client, make_user, "bn14_existing_sup")

    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE quotations SET sales_person = ? WHERE quote_no = ?",
                     (seller, quote_no))
        conn.commit()
    finally:
        conn.close()

    r = _create_item(client, hdr, "既有來源負對照", "sales_person")
    assert r.status_code == 200, r.text[:300]
    item_id = r.json()["id"]

    plan = _plan_get(client, hdr, quote_no)
    assert plan.status_code == 200, plan.text[:300]
    entry = next((it for it in plan.json().get("items") or ()
                 if it.get("bonus_item_id") == item_id), None)
    assert entry is not None, "先問端點的清單裡找不到既有來源的項目。"
    assert entry.get("ok") is True, (
        "既有的 `sales_person` 來源在加了群組之後壞掉了：%r" % entry)
    assert entry.get("people") == [seller], (
        "`sales_person` 解析出 %r，預期 [%r]" % (entry.get("people"), seller))


# ══════════════════════════════════════════════════════════════════════
# ⑥ 守門：`== "group"` 這類判斷不可以散在多處
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
