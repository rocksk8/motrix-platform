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

def test_bn18_without_override_a_case_with_no_executor_is_still_refused(
        client, make_user):
    """🔴 **正對照：不宣告覆寫時，既有的拒絕規則沒有被拿掉。**

    `SPEC-BN18.md §1`：`BN18` 不是拿掉「解析出 0 人就拒絕」，是給
    「資料裡沒有，而我知道是誰該領」一條出路。
    """
    _u, hdr = _hdr(client, make_user, "bn18_noexec_a")
    _seed_case("MQ-BN18-A1", stage_people=None)
    item_id = _seed_item("BN18測試項目甲", "case_stages.assigned_to")

    r = client.post(AWARDS, headers=hdr, json={
        "quote_no": "MQ-BN18-A1",
        "allocations": [{"bonus_item_id": item_id, "total_pct": 1000,
                         "person_pct": {}}]})
    assert r.status_code == 400, (
        "沒有執行人、沒有宣告覆寫，卻放行了：%s %s"
        % (r.status_code, r.text[:200]))
    assert "無可發放對象" in r.text, r.text[:200]


def test_bn18_with_override_the_same_case_now_succeeds(client, make_user):
    """🔴🔴 **`③ⓐ` 核心：同一張沒有執行人的案件，手動指定後可以產生成功。**

    這是 `BN18` 的來由——使用者原話「過往很多沒有填寫案件管理專案執行人，
    導致無法帶入」。
    """
    _u, hdr = _hdr(client, make_user, "bn18_noexec_b")
    _seed_case("MQ-BN18-A2", stage_people=None)
    item_id = _seed_item("BN18測試項目乙", "case_stages.assigned_to")

    r = client.post(AWARDS, headers=hdr, json={
        "quote_no": "MQ-BN18-A2",
        "allocations": [{
            "bonus_item_id": item_id, "total_pct": 1000,
            "person_source_override": True,
            "people": ["bn18_manual_x", "bn18_manual_y"],
            "person_pct": {"bn18_manual_x": 5000, "bn18_manual_y": 5000},
        }]})
    assert r.status_code == 400, (
        "指定了未建立的帳號應該先被 400，測試前置需要真帳號：%s"
        % r.text[:200])
    # 上面那筆刻意用不存在帳號驗證「未建帳號會被擋」（③ⓔ另有專題），
    # 這裡换真帳號重試一次驗證「成功路徑」。
    make_user(username="bn18_manual_x", role="user", modules=["reports"])
    make_user(username="bn18_manual_y", role="user", modules=["reports"])
    r = client.post(AWARDS, headers=hdr, json={
        "quote_no": "MQ-BN18-A2",
        "allocations": [{
            "bonus_item_id": item_id, "total_pct": 1000,
            "person_source_override": True,
            "people": ["bn18_manual_x", "bn18_manual_y"],
            "person_pct": {"bn18_manual_x": 5000, "bn18_manual_y": 5000},
        }]})
    assert r.status_code == 200, (
        "手動指定之後仍然被拒絕：%s %s" % (r.status_code, r.text[:200]))


# ══════════════════════════════════════════════════════════════════════
# ③ⓑ person_source_snapshot == "manual"，username 是帳號不是中文名
# ══════════════════════════════════════════════════════════════════════

def test_bn18_manual_lines_are_snapshotted_as_manual_with_real_usernames(
        client, make_user):
    """🔴🔴 **`③ⓑ`：手動指定產生的分錄，`person_source_snapshot` 要是
    `"manual"`，`username` 要是帳號不是中文顯示名。**"""
    _u, hdr = _hdr(client, make_user, "bn18_snap")
    make_user(username="bn18_snap_zhang", role="user", modules=["reports"])
    _seed_case("MQ-BN18-SNAP", stage_people=None)
    item_id = _seed_item("BN18測試項目丙", "case_stages.assigned_to")

    r = client.post(AWARDS, headers=hdr, json={
        "quote_no": "MQ-BN18-SNAP",
        "allocations": [{
            "bonus_item_id": item_id, "total_pct": 1000,
            "person_source_override": True,
            "people": ["bn18_snap_zhang"],
            "person_pct": {"bn18_snap_zhang": 10000},
        }]})
    assert r.status_code == 200, r.text[:200]
    aid = r.json()["id"]

    lines = _award_lines(award_id=aid)
    assert len(lines) == 1, "應該恰好一列：%r" % lines
    assert lines[0]["person_source_snapshot"] == "manual", (
        "`person_source_snapshot` 是 %r，不是 `manual`。"
        % lines[0]["person_source_snapshot"])
    assert lines[0]["username"] == "bn18_snap_zhang", (
        "`username` 是 %r，應該是帳號 `bn18_snap_zhang`，不是中文顯示名。"
        % lines[0]["username"])


def test_bn18_manual_basis_records_the_original_source_type_and_resolution(
        client, make_user):
    """🔴 **`564eedf`：`manual_basis` 要記型別＋解析結果，不是只記型別。**

    使用者知道「這個項目原本宣告的來源是什麼」還不夠，之後案件資料變了
    就永遠查不到「本來解析得出是誰」——`manual_basis` 要是一句完整的話。
    """
    _u, hdr = _hdr(client, make_user, "bn18_basis")
    make_user(username="bn18_basis_x", role="user", modules=["reports"])
    _seed_case("MQ-BN18-BASIS", stage_people=None)
    item_id = _seed_item("BN18測試項目丁", "case_stages.assigned_to")

    r = client.post(AWARDS, headers=hdr, json={
        "quote_no": "MQ-BN18-BASIS",
        "allocations": [{
            "bonus_item_id": item_id, "total_pct": 1000,
            "person_source_override": True,
            "people": ["bn18_basis_x"],
            "person_pct": {"bn18_basis_x": 10000},
        }]})
    assert r.status_code == 200, r.text[:200]
    lines = _award_lines(award_id=r.json()["id"])
    basis = lines[0]["manual_basis"]
    assert "case_stages.assigned_to" in basis, (
        "`manual_basis` 沒有記到原本的來源型別：%r" % basis)
    assert "無可發放對象" in basis, (
        "`manual_basis` 沒有記到覆寫前的解析結果（這個案件本來就沒有執行"
        "人，應該記下『無可發放對象』這個事實）：%r" % basis)


# ══════════════════════════════════════════════════════════════════════
# ③ⓒ 負對照＋誘餌：帶 people 沒有旗標，必須仍然走解析
# ══════════════════════════════════════════════════════════════════════

def test_bn18_people_without_the_override_flag_is_ignored_resolution_wins(
        client, make_user):
    """🔴🔴 **`§4` 誘餌：`alloc` 帶了 `people` 但沒有 `person_source_
    override` 旗標 ⇒ 必須走解析，用解析出來的人，不是 `people` 裡的。**

    ☠️ 這是規格點名的假綠燈來源：若判斷式寫成 `if alloc.get("people"):`
    （用真假值決定分支），這裡會安靜地改用 `people` 裡的人，金額照算、
    總額照樣對得起來，沒有人發現。本題種一個**真的有執行人**的案件
    （`bn18_real_exec`），額外送一個完全不同、也真實存在的 `people`
    名單（`bn18_decoy_x`）——若實作是錯的（真假值判斷），下游會出現
    `bn18_decoy_x`；若實作是對的（明著看旗標），下游只會有
    `bn18_real_exec`。
    """
    _u, hdr = _hdr(client, make_user, "bn18_bait")
    make_user(username="bn18_real_exec", role="user", modules=["reports"])
    make_user(username="bn18_decoy_x", role="user", modules=["reports"])
    _seed_case("MQ-BN18-BAIT", stage_people=["bn18_real_exec"])
    item_id = _seed_item("BN18測試項目戊", "case_stages.assigned_to")

    r = client.post(AWARDS, headers=hdr, json={
        "quote_no": "MQ-BN18-BAIT",
        "allocations": [{
            "bonus_item_id": item_id, "total_pct": 1000,
            # 🔴 刻意帶 people，但不送 person_source_override。
            "people": ["bn18_decoy_x"],
            "person_pct": {"bn18_real_exec": 10000, "bn18_decoy_x": 10000},
        }]})
    assert r.status_code == 200, r.text[:200]
    lines = _award_lines(award_id=r.json()["id"])
    usernames = {ln["username"] for ln in lines}
    assert usernames == {"bn18_real_exec"}, (
        "沒有宣告 `person_source_override`，下游卻是 %r（應該只有解析出來"
        "的 `bn18_real_exec`）——\n" % usernames
        + "☠️ 若混進了 `bn18_decoy_x`，代表判斷式是用 `people` 的真假值"
          "決定分支，不是看明著宣告的旗標，那份 `people` 被安靜地用掉了。")
    assert lines[0]["person_source_snapshot"] == "case_stages.assigned_to", (
        "`person_source_snapshot` 是 %r，不是原本的來源型別——"
        "沒有宣告覆寫時不應該變成 `manual`。"
        % lines[0]["person_source_snapshot"])


# ══════════════════════════════════════════════════════════════════════
# ③ⓓ 兩個項目的單，各自指定不同人——item 層級不是 award 層級
# ══════════════════════════════════════════════════════════════════════

def test_bn18_two_items_each_get_their_own_manual_people_no_cross_talk(
        client, make_user):
    """🔴🔴 **`§2`：手動指定是項目層級，不是單層級——兩個項目各自指定
    不同的人，互不污染。**

    ☠️ `SPEC-BN18.md §2` 明講：做成單層（整張單一份名單）的後果是「這個
    項目該發給誰」這個問題會消失，而今天全部案件都只有一個項目，單層與
    項目層產生的結果會一模一樣，測試會全綠——本題刻意造一張兩個項目的
    單來排除這個假綠燈。
    """
    _u, hdr = _hdr(client, make_user, "bn18_two_items")
    make_user(username="bn18_item1_person", role="user", modules=["reports"])
    make_user(username="bn18_item2_person", role="user", modules=["reports"])
    _seed_case("MQ-BN18-TWOITEMS", stage_people=None)
    item1 = _seed_item("BN18項目一", "case_stages.assigned_to")
    item2 = _seed_item("BN18項目二", "case_stages.assigned_to")

    r = client.post(AWARDS, headers=hdr, json={
        "quote_no": "MQ-BN18-TWOITEMS",
        "allocations": [
            {"bonus_item_id": item1, "total_pct": 500,
             "person_source_override": True,
             "people": ["bn18_item1_person"],
             "person_pct": {"bn18_item1_person": 10000}},
            {"bonus_item_id": item2, "total_pct": 500,
             "person_source_override": True,
             "people": ["bn18_item2_person"],
             "person_pct": {"bn18_item2_person": 10000}},
        ]})
    assert r.status_code == 200, r.text[:200]
    lines = _award_lines(award_id=r.json()["id"])

    item1_lines = [ln for ln in lines if ln["bonus_item_id"] == item1]
    item2_lines = [ln for ln in lines if ln["bonus_item_id"] == item2]
    assert {ln["username"] for ln in item1_lines} == {"bn18_item1_person"}, (
        "項目一的分錄是 %r，應該只有 bn18_item1_person。"
        % [ln["username"] for ln in item1_lines])
    assert {ln["username"] for ln in item2_lines} == {"bn18_item2_person"}, (
        "項目二的分錄是 %r，應該只有 bn18_item2_person——\n"
        "☠️ 若混進了項目一的人，代表手動名單是掛在單層，不是項目層。"
        % [ln["username"] for ln in item2_lines])


# ══════════════════════════════════════════════════════════════════════
# ③ⓔⓕ 帳號驗證：不存在／已停用 ⇒ 整批 400，零副作用
# ══════════════════════════════════════════════════════════════════════

def test_bn18_an_unknown_username_is_refused_with_zero_side_effects(
        client, make_user):
    """🔴🔴 **`③ⓔ`：手動指定一個不存在的帳號 ⇒ 整批 400，沒有任何一列
    寫進資料庫。**"""
    _u, hdr = _hdr(client, make_user, "bn18_unknown")
    make_user(username="bn18_unknown_real", role="user", modules=["reports"])
    _seed_case("MQ-BN18-UNKNOWN", stage_people=None)
    item_id = _seed_item("BN18測試項目己", "case_stages.assigned_to")
    before_a, before_l = _counts()

    r = client.post(AWARDS, headers=hdr, json={
        "quote_no": "MQ-BN18-UNKNOWN",
        "allocations": [{
            "bonus_item_id": item_id, "total_pct": 1000,
            "person_source_override": True,
            "people": ["bn18_unknown_real", "nobody_here_bn18_9912"],
            "person_pct": {"bn18_unknown_real": 5000,
                          "nobody_here_bn18_9912": 5000},
        }]})
    assert r.status_code == 400, (
        "指定了不存在的帳號卻放行了：%s %s" % (r.status_code, r.text[:200]))
    assert "nobody_here_bn18_9912" in r.text, (
        "訊息沒有說出是哪一個帳號：%s" % r.text[:200])

    after_a, after_l = _counts()
    assert (after_a, after_l) == (before_a, before_l), (
        "拒絕的路徑上仍有副作用：before=(%d,%d) after=(%d,%d)"
        % (before_a, before_l, after_a, after_l))


def test_bn18_a_deactivated_username_is_also_refused(client, make_user):
    """🔴 **`③ⓕ`：手動指定一個 `active=0` 的帳號 ⇒ 同樣 400。**

    ⚠️ 少了這題，「只驗帳號存在」的實作會放行離職的人。
    """
    _u, hdr = _hdr(client, make_user, "bn18_deactivated")
    u, _p = make_user(username="bn18_left_company", role="user",
                       modules=["reports"])
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET active = 0 WHERE username = ?", (u,))
        conn.commit()
    finally:
        conn.close()

    _seed_case("MQ-BN18-DEACTIVATED", stage_people=None)
    item_id = _seed_item("BN18測試項目庚", "case_stages.assigned_to")

    r = client.post(AWARDS, headers=hdr, json={
        "quote_no": "MQ-BN18-DEACTIVATED",
        "allocations": [{
            "bonus_item_id": item_id, "total_pct": 1000,
            "person_source_override": True,
            "people": [u],
            "person_pct": {u: 10000},
        }]})
    assert r.status_code == 400, (
        "已停用的帳號被接受了：%s %s" % (r.status_code, r.text[:200]))
    assert u in r.text, "訊息沒有說出是哪一個帳號：%s" % r.text[:200]


# ══════════════════════════════════════════════════════════════════════
# §4 守門：_plan_allocations 不可以用 people 的真假值決定分支
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
    src = (ROOT / "routers" / "bonus.py").read_text(encoding="utf-8")
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
