# -*- coding: utf-8 -*-
"""獎金分潤（`FN2`）—— 項目維護、產生獎金分潤單、可見性。

施工圖：`docs/windows/SPEC-BONUS.md`。
使用者原話：「新開發案件精算完結後，會有獎金分潤的衍生，一樣加在營運報表那個模組獨立」
「項目可由**最高管理者**定義，由案件**結案的最終金額**按比例去撥付」。

# 🔴 可見性是這一支最重要的事

`§七` 逐字：**現行營運報表的可見範圍不可沿用** —— 沿用＝**全公司看得到每個人領多少**。
```
管理者  全部
本人    **只看得到自己那一列**
其他人  看不到
```
📌 「本人」是一條**規則**不是一個角色 ⇒ 明著比對 `username`，不從角色推論。
⚠️ 而過濾要發生在**後端**：前端過濾的話，值仍然在 API 回應裡。

# 🔴 基數不在這裡算

`helpers.bonus.base_amount_for()` 讀 `settlement.summary.netProfit` 的**已存值**。
這一支**不乘 10%／1%** —— 那兩個係數只寫在 `settlement.html`，
再寫一份就是第三份實作，而三份一定會分岔。
"""
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from fastapi.responses import HTMLResponse, Response

from db import get_db
from helpers import _require_user, _audit, _tok, _get_setting
from helpers.edit_log import append_edit_log
from helpers.bonus import (
    base_amount_for, people_for_item, split_award, pool_for, remainder_of,
    visible_lines, PERSON_SOURCES, BASIS_POINTS,
    bonus_signatures_of, is_paid, BonusChainUnreadable, MAKER_SLOT,
    SETTLEMENT_FIELDS, settlement_fields,
)
from helpers.tiered_approval import (
    approval_flow_setting_key, setting_to_active_tiers, UnresolvedManagerError,
)
from helpers.bonus_pdf import can_export, export_award_pdf, display_names_for, preview_award_html

router = APIRouter(prefix="/api/bonus", tags=["bonus"])
logger = logging.getLogger(__name__)

#: 2026-09-24（SPEC-BONUS §十一／§11.7）：舊的「獎金項目＋分潤單」流程停用。
#: 使用者：舊單「舊的都是開發機測試用，直接作廢」⇒ 舊的**寫入**端點一律 410，
#: 讀取端點（清單／明細／PDF／試算）保留。不以 migration 作廢任何資料。
LEGACY_GONE_MESSAGE = "舊的獎金分潤流程已停用，請改用「獎金分潤」頁面（以案件為中心）。"


def _legacy_write_gone():
    raise HTTPException(410, LEGACY_GONE_MESSAGE)


_GONE = [Depends(_legacy_write_gone)]


def _is_manager(user):
    """**寫**得動獎金的人（產生／作廢／查基數與發放對象）。

    ⚠️ 這一把**不再兼任「看得到全部」** —— 讀的那一把是 `_sees_all_lines()`。
    📌 原本一把兼兩用，理由是施工圖 `§十` 把「最高管理者是否沿用 superadmin」
       標為未查 ⇒ 讀先放寬。2026-09-23 `BN9` 裁定之後那個理由沒有了，
       ☠️ 而**留著一把兼兩用的旗標，收緊其中一側時另一側會跟著動，
          而跟著動的那一側沒有人在看**。
    🔑 讀與寫的代價仍然不對稱，所以仍然分開：
       讀放寬 ⇒ 多一個人**看得到別人領多少**；寫放寬 ⇒ 多一個人改得動獎金。
    """
    return user.get("role") in ("superadmin", "admin")


def _sees_all_lines(user):
    """看得到**別人那幾列**的人 —— 只有 `superadmin`（`BN9`）。

    ## 🔴 這是「誰領多少」的可見範圍，不是「誰改得動」

    ```
    superadmin  整張單、所有人的金額
    admin       **只有自己那一列**（與一般同仁相同）—— 他仍然產生得了獎金分潤單
    其他人       只有自己那一列
    ```
    ⚠️ `admin` 在這一頁是**一般使用者**，而他在別的頁不是 ——
       ☠️ 所以畫面不可以用同一個旗標同時決定「看得到什麼」與「按得到什麼」：
       他按得到「產生獎金分潤單」，而他看不到別人的金額。
    📌 ⇒ 回應裡送**兩個**旗標（`is_manager`／`can_create_award`），
       前端各用各的。少送一個的話，收緊可見範圍會連入口一起收掉，
       **而那是一個沒有人要求的權限變更**。
    """
    return user.get("role") == "superadmin"

def _user_name(user):
    """寫進 `*_by` 欄位的值：**`username`，不是 token，也不是 id**。

    ## ☠️ 原本寫的是 `_tok(authorization)` —— 那是**原始 bearer token**

    ```
    寫入  created_by / submitted_by / checked_by / manager_by / voided_by / posted_by
    讀出  SELECT * -> dict(row)  => 任何有 cashier／finance 的人都拿得到
    ```
    而 token 有效期 **30 天**，且 `auth.py:216` 的條件讓 **NULL 等於永不過期**。
    🔑 ⇒ 那不是「欄位存錯東西」，是**把別人的憑證發給其他使用者**。

    ## ⚠️ 用 `username` 而不是 `id`

    `auth.py:1502` 的可更新白名單是 display_name／email／phone／modules／
    notification_muted／department_id／password ⇒ **`username` 不可改**
    ⇒ 它當歷史紀錄是穩定的。
    📌 而 `visible_lines(lines, username, …)` 與獎金的可見性判斷**已經用 username**
       ⇒ 零轉換層。

    ## 🔴 而版面上那一格會印出它

    `signatures_of()` 把這些欄位當成「簽名的人」回傳
    ⇒ 舊寫法會讓傳票的「製票」格印出一串 64 字元的 token。
    """
    return (user or {}).get("username") or ""


def _pct_text(bp):
    """把**基點**印成人看得懂的百分比字串。`5000 -> "50"`、`10001 -> "100.01"`。

    ☠️ 單位是基點（1/10000）而欄位名字叫 `pct` ⇒ 送 `50` 當 50% 的話，
       獎金變成應得的 **1/100**，**而畫面上它是一個格式正確的金額**。
    ⇒ 錯誤訊息要印**使用者認得的那個數**，不是印基點。
    """
    return ("%g" % (bp / 100.0))



# ── 獎金項目（最高管理者維護）──────────────────────────────────────
@router.get("/items")
def list_bonus_items(authorization: str = Header(None)):
    """獎金項目清單。**只有最高管理者讀得到**（`BN2`，使用者 2026-09-23 裁）。

    ## 🔴 寫已經擋住了，而**讀沒有** —— 那是兩道不同的閘

    ```
    POST /items  require_superadmin=True   <= 一直都擋著
    GET  /items  _require_user()           <= **任何登入者**都讀得到
    ```
    ☠️ 而這份清單上有 `person_source`：「**誰有資格領這一類獎金**」——
       那是**薪酬結構**，不是一個中性的設定值。
    🔑 ⇒ 一個看得到寫入閘門的人，**不代表**他該看得到那張表。

    ## ⚠️ 403 與「空清單」**不可以長得一樣**

    兩者都回 200 的話，前端沒有任何依據說出不同的話 ⇒ 它只能說「沒有資料」，
    **而那是假的**。⇒ 擋住就回 403，讓畫面說得出「你沒有權限看」。
    """
    user = _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM bonus_items ORDER BY sort_order, id")]
    finally:
        conn.close()
    return {"items": rows, "person_sources": list(PERSON_SOURCES),
            "can_edit": user.get("role") == "superadmin"}


@router.post("/items", dependencies=_GONE)
def create_bonus_item(body: dict = Body(...), authorization: str = Header(None)):
    """新增獎金項目。

    🔴 `person_source` **為空不准儲存** —— 不是存了再算出 0 人。
    ☠️ 存得下去的話，那個項目**每次都算出 0 個人**，而畫面上它只是
       **從來沒有出現在任何一張獎金分潤單上** —— 沒有人會發現一個從來不出現的東西。
    ⚠️ 資料層的 `NOT NULL` 擋不住空字串，所以這一關是必要的另一半。
    """
    # 🔴 `BI1`：**回傳值要接住**。這一支原本只把 `_require_user` 當檢查用，
    #    而 `dd50d2e` 把 `created_by` 從 `_tok(...)` 改成 `_user_name(user)`
    #    之後，下面就讀得到一個從來沒有被綁定的 `user` ⇒ **NameError -> 500**。
    # ☠️ 而全量是綠的：`grep "api/bonus/items" tests/` 當時是 **0 筆** ——
    #    這支端點從來沒有人量過。⇒ 綠燈證明的是「有人量過的那些」。
    # ⚠️ 不可以改成 `_user_name(None)` 或寫死空字串：那會讓 500 消失，
    #    **而稽核欄位變成空的** —— 壞掉會被報修，降級不會。
    user = _require_user(authorization, require_superadmin=True)
    name = (body.get("name") or "").strip()
    source = (body.get("person_source") or "").strip()
    if not name:
        raise HTTPException(400, "請填寫獎金項目名稱。")
    if not source:
        raise HTTPException(400, "請選擇人員來源：沒有來源的項目永遠算不出發放對象。")
    if source not in PERSON_SOURCES:
        raise HTTPException(400, "不支援的人員來源「%s」。" % source)
    # `BN14`：型別（`person_source`）與實例（哪一個群組）分開存——
    # 不編碼成 `"group:2"`，見 `db.py::_m104_bonus_groups()` 的理由。
    # 這裡不逐一判斷是哪個來源才收這個值：其他來源送了也只是存一個
    # 用不到的 NULL 以外的值，`people_for_item()` 只有 `"group"` 那支
    # 分支會讀它，不會誤用到別的來源上。
    raw_ref = body.get("person_source_ref")
    ref = int(raw_ref) if raw_ref not in (None, "") else None
    # `BN3`：`manual` 綁**帳號**（users.username），不存顯示名稱或自由文字——
    # 打錯一個字那個人就領不到，而畫面上一切正常（`SPEC-BN2-BN5 §2`）。
    manual_people = []
    if source == "manual":
        raw = body.get("people") or []
        if not isinstance(raw, list):
            raise HTTPException(400, "人員清單格式不正確。")
        for u in raw:
            u = str(u or "").strip()
            if u and u not in manual_people:
                manual_people.append(u)
        if not manual_people:
            raise HTTPException(400, "「手動指定」需要至少指定一位人員，"
                                     "否則這個項目永遠不會出現在任何一張獎金分潤單上。")
    now = datetime.now().isoformat()
    conn = get_db()
    try:
        if manual_people:
            ph = ",".join("?" for _ in manual_people)
            ok_names = {r["username"] for r in conn.execute(
                "SELECT username FROM users WHERE active = 1 AND username IN (%s)" % ph,
                tuple(manual_people))}
            bad = [u for u in manual_people if u not in ok_names]
            if bad:
                # ⚠️ 說出是哪一個：一次指定好幾個人，說不出是哪一個等於要他自己試。
                raise HTTPException(400, "找不到這些帳號，或帳號已停用：%s" % "、".join(bad))
        cur = conn.execute(
            "INSERT INTO bonus_items (name, person_source, person_source_ref,"
            " sort_order, is_active, created_by, created_at, updated_at)"
            " VALUES (?,?,?,?,1,?,?,?)",
            (name, source, ref, int(body.get("sort_order") or 0),
             _user_name(user), now, now))
        new_id = cur.lastrowid
        for u in manual_people:
            conn.execute(
                "INSERT INTO bonus_item_people (bonus_item_id, username, created_at)"
                " VALUES (?,?,?)", (new_id, u, now))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "bonus.item.create", "bonus_items",
           str(new_id), "新增獎金項目：%s" % name)
    return {"ok": True, "id": new_id}


# ── `BN14`：獎金模組自己建的群組 ──────────────────────────────────
# 🔴 閘門與獎金項目同一道（`require_superadmin=True`）——群組是獎金項目
#    的附屬設定（`SPEC-BN14.md §7b`，A 裁），權限判斷只留一處，不要讓
#    「誰能維護群組」與「誰看得到獎金項目」在兩處各自判斷、遲早漂移
#    （`EM13` 那一族就是這樣長出來的）。

@router.get("/groups")
def list_bonus_groups(authorization: str = Header(None)):
    """群組清單，**含成員帳號**——維護畫面與項目建立的群組下拉共用這一支。

    ⚠️ 停用的群組**照樣列出**（`is_active` 標出來，不是濾掉）：維護畫面
    要看到它才能重新啟用；前端自己決定「建新項目的下拉」要不要濾掉
    停用的（`§7②`），這裡不揣測用途先幫忙濾。
    """
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        groups = [dict(r) for r in conn.execute(
            "SELECT * FROM bonus_groups ORDER BY name")]
        members_by_group = {}
        for r in conn.execute(
                "SELECT group_id, username FROM bonus_group_members"
                " ORDER BY username"):
            members_by_group.setdefault(r["group_id"], []).append(r["username"])
    finally:
        conn.close()
    for g in groups:
        g["members"] = members_by_group.get(g["id"], [])
    return {"groups": groups}


@router.post("/groups")
def create_bonus_group(body: dict = Body(...), authorization: str = Header(None)):
    """新增群組（例：「後勤單位」）。**只建群組本身，不帶成員**——
    加成員是另一支端點，避免「建立」與「加人」哪一步失敗要分開重試時
    糾纏在一起。
    """
    user = _require_user(authorization, require_superadmin=True)
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "請填寫群組名稱。")
    now = datetime.now().isoformat()
    conn = get_db()
    try:
        try:
            cur = conn.execute(
                "INSERT INTO bonus_groups (name, is_active, created_by,"
                " created_at, updated_at) VALUES (?,1,?,?,?)",
                (name, _user_name(user), now, now))
        except Exception as exc:                            # noqa: BLE001
            if "UNIQUE" in str(exc).upper():
                raise HTTPException(409, "群組「%s」已經存在。" % name)
            raise
        conn.commit()
        new_id = cur.lastrowid
    finally:
        conn.close()
    _audit(_tok(authorization), "bonus.group.create", "bonus_groups",
           str(new_id), "新增獎金群組：%s" % name)
    return {"ok": True, "id": new_id}


@router.patch("/groups/{group_id}/active")
def set_bonus_group_active(group_id: int, body: dict = Body(...),
                           authorization: str = Header(None)):
    """停用／重新啟用群組。**只改 `is_active`，成員清單不動**

    ☠️ `SPEC-BN14.md §7`：停用時清空成員的話，重新啟用會是一個空群組，
    而畫面上看起來完全正常——使用者不會發現整批成員不見了，直到有人
    抱怨自己沒領到錢。⇒ 這支**不碰** `bonus_group_members`。
    """
    _require_user(authorization, require_superadmin=True)
    is_active = 1 if body.get("is_active") else 0
    conn = get_db()
    try:
        row = conn.execute("SELECT id, name FROM bonus_groups WHERE id = ?",
                           (group_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "找不到這個群組。")
        conn.execute(
            "UPDATE bonus_groups SET is_active = ?, updated_at = ? WHERE id = ?",
            (is_active, datetime.now().isoformat(), group_id))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "bonus.group.set_active", "bonus_groups",
           str(group_id), "%s群組：%s" % ("啟用" if is_active else "停用", row["name"]))
    return {"ok": True}


@router.post("/groups/{group_id}/members")
def add_bonus_group_member(group_id: int, body: dict = Body(...),
                           authorization: str = Header(None)):
    """加一個成員。**只能是真實帳號**（〈綁帳號不存自由文字〉，`BN3` 留下來
    的界線）——資料層用 FK 擋（`bonus_group_members.username` 參照
    `users(username)`），這裡把資料層的拒絕翻成看得懂的話，不是應用層
    自己重新判斷一次「這個帳號存不存在」（那會變成第二份判斷，兩份會
    漂移）。
    """
    _require_user(authorization, require_superadmin=True)
    username = (body.get("username") or "").strip()
    if not username:
        raise HTTPException(400, "請指定要加入的帳號。")
    conn = get_db()
    try:
        group = conn.execute("SELECT id FROM bonus_groups WHERE id = ?",
                             (group_id,)).fetchone()
        if group is None:
            raise HTTPException(404, "找不到這個群組。")
        try:
            conn.execute(
                "INSERT INTO bonus_group_members (group_id, username)"
                " VALUES (?,?)", (group_id, username))
        except Exception as exc:                            # noqa: BLE001
            msg = str(exc).upper()
            if "UNIQUE" in msg:
                raise HTTPException(409, "「%s」已經在這個群組裡了。" % username)
            if "FOREIGN KEY" in msg:
                raise HTTPException(400, "帳號「%s」不存在。" % username)
            raise
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "bonus.group.add_member", "bonus_groups",
           str(group_id), "加入成員：%s" % username)
    return {"ok": True}


@router.delete("/groups/{group_id}/members/{username}")
def remove_bonus_group_member(group_id: int, username: str,
                              authorization: str = Header(None)):
    """移出一個成員。**不影響已經產生的獎金分潤單**（`§5` 凍結——那些單存的是
    快照，不會即時展開群組）。
    """
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM bonus_group_members WHERE group_id = ? AND username = ?",
            (group_id, username))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "bonus.group.remove_member", "bonus_groups",
           str(group_id), "移出成員：%s" % username)
    return {"ok": True}


def _attach_manual_people(conn, items):
    """`BN3`：幫每個 `person_source == "manual"` 的項目補上 `_manual_people`
    （**只含在職帳號**，`users.active = 1`）。同 `_attach_group_people()`：
    `people_for_item()` 維持純函式，查詢放在呼叫端、一次查完。

    ⚠️ 停用的人**不在名單裡** ⇒ 新的獎金分潤單不會再發給他；已經產生的單
    存的是當時的明細列，不受影響（`SPEC-BN2-BN5 §2` ③）。
    """
    manual = [it for it in items if it.get("person_source") == "manual"]
    ids = {it["id"] for it in manual if it.get("id") is not None}
    if not ids:
        return
    ph = ",".join("?" for _ in ids)
    by_item = {}
    for r in conn.execute(
            "SELECT p.bonus_item_id, p.username FROM bonus_item_people p"
            " JOIN users u ON u.username = p.username AND u.active = 1"
            " WHERE p.bonus_item_id IN (%s) ORDER BY p.username" % ph, tuple(ids)):
        by_item.setdefault(r["bonus_item_id"], []).append(r["username"])
    for it in manual:
        it["_manual_people"] = by_item.get(it.get("id"), [])


def _attach_group_people(conn, items):
    """`BN14`：幫每個 `person_source == "group"` 的項目補上
    `_group_members`／`_group_error`，`people_for_item()` 只讀這兩個鍵，
    自己不查資料庫（維持純函式，`helpers/bonus.py` 的既有規則——同
    `QS1-a` `_case_people()` 那條「解析放在呼叫端」）。

    一次查完全部群組，不逐項目各查一次（同 `BN15`／`QS1-a` 那幾支的
    批次查詢規則）。沒有 `person_source_ref` 的群組項目**不設任何一個
    鍵**——`people_for_item()` 自然落到「沒有成員」那個共用檢查，訊息
    不夠精準但不算錯（新增項目時前端會擋，不會真的送出這種資料）。
    """
    group_items = [it for it in items if it.get("person_source") == "group"]
    gids = {it["person_source_ref"] for it in group_items
            if it.get("person_source_ref")}
    if not gids:
        return
    placeholders = ",".join("?" for _ in gids)
    groups = {r["id"]: dict(r) for r in conn.execute(
        "SELECT id, name, is_active FROM bonus_groups WHERE id IN (%s)"
        % placeholders, tuple(gids))}
    members_by_group = {}
    for r in conn.execute(
            "SELECT group_id, username FROM bonus_group_members"
            " WHERE group_id IN (%s)" % placeholders, tuple(gids)):
        members_by_group.setdefault(r["group_id"], []).append(r["username"])

    for it in group_items:
        gid = it.get("person_source_ref")
        g = groups.get(gid)
        if g is None:
            it["_group_error"] = "設定的群組不存在，請重新選擇人員來源。"
        elif not g["is_active"]:
            it["_group_error"] = (
                "群組「%s」已停用，無法用來產生新的獎金分潤。" % g["name"])
        else:
            it["_group_members"] = members_by_group.get(gid, [])


# ── 案件的獎金基數（唯讀，給畫面先看）────────────────────────────
def _settlement_of(conn, quote_no):
    row = conn.execute(
        "SELECT json_extract(data_json, '$.settlement') AS s"
        " FROM quotations WHERE quote_no = ?", (quote_no,)).fetchone()
    if row is None:
        return None
    raw = row["s"]
    if not raw:
        return {}
    return json.loads(raw) if isinstance(raw, str) else raw


def _case_names_for(conn, quote_nos):
    """`{quote_no}` 集合 -> `{quote_no: {customer_name, project_name}}`（`BN15`）。

    使用者原話：「獎金單的只有編號，沒有案件名稱」——`bonus_awards` 這張表
    本來就只存 `quote_no`（`db.py:4662`），而「產生獎金分潤單」那個下拉選單早就
    在查 `quotations`（`award_candidates()` 上面那支）。

    🔴 **不把 customer_name／project_name 存進 `bonus_awards`**——那會變成
    第二份快照，案件改名之後這裡不會跟著動，兩邊會漂移。⇒ 每次讀的時候
    查一次 `quotations`，與 `award_candidates()` 同一條規則（那支也是
    每次即時查，不是存起來的）。查不到就落回空字串，不擋清單顯示。
    """
    names = {q for q in (quote_nos or ()) if q}
    if not names:
        return {}
    placeholders = ",".join("?" for _ in names)
    rows = conn.execute(
        "SELECT quote_no, customer_name, project_name FROM quotations"
        " WHERE quote_no IN (%s)" % placeholders, tuple(names))
    return {r["quote_no"]: {"customer_name": r["customer_name"] or "",
                            "project_name": r["project_name"] or ""}
            for r in rows}


#: `BN11` 搬到 `helpers/bonus.py`（`SETTLEMENT_FIELDS`／`settlement_fields`）
#: ——`bonus_pdf.py` 也要用同一份，helper 不能 import router，只能反過來。
#: 這兩個名字留著、行為不變，call site 全部不用改。
_SETTLEMENT_FIELDS = SETTLEMENT_FIELDS
_settlement_fields = settlement_fields


@router.get("/base/{quote_no}")
def get_bonus_base(quote_no: str, authorization: str = Header(None)):
    """這個案件現在算不算得出獎金基數。

    🔑 **先問再做**：畫面在按下「產生獎金分潤單」之前就該知道答案，
       而不是按下去才收到一句拒絕。
    """
    user = _require_user(authorization)
    if not _is_manager(user):
        raise HTTPException(403, "僅管理員以上可查閱獎金基數。")
    conn = get_db()
    try:
        settle = _settlement_of(conn, quote_no)
    finally:
        conn.close()
    if settle is None:
        raise HTTPException(404, "找不到案件「%s」。" % quote_no)
    ok, base, err = base_amount_for(settle)
    return {"quote_no": quote_no, "ok": ok, "base_amount": base, "error": err}


# ── 獎金分潤單 ────────────────────────────────────────────────────────

# ── 獎金產生單：先問再做 ──────────────────────────────────────────
# 🔴 **這一支必須宣告在任何 `/awards/{award_id}` 之前。**
#
# ```
# 日後有人加 GET /awards/{award_id} 並宣告在這之前
#   -> /awards/plan/MQ-1  把 "plan" 當成 award_id  -> int 解析失敗 -> **422**
# ```
# 📌 不是假設：`GET /api/vouchers/summary-sources` 2026-09-23 就是這樣變成 422 的
#    （成因是同 prefix 的 `@router.get("/{voucher_id}")` 先宣告）。
# ⚠️ 依據寫在這裡是刻意的（A 裁，`SPEC-BN1-PLAN §1`）：
#    **下一個加端點的人不會去讀規格**，寫在他眼前才擋得到；
#    而不寫依據的禁令，會在裁示翻面的那天變成「擋住正確實作的東西」。
@router.get("/awards/plan/{quote_no}")
def plan_award(quote_no: str, authorization: str = Header(None)):
    """這個案件現在可以發哪些獎金、各發給誰。**畫面組 request body 的唯一來源。**

    ## 🔴 為什麼是後端算，而不是前端自己組

    `POST /awards` 要 `allocations[].person_pct = {username: pct}`，
    而那些 `username` 由 `people_for_item()` 決定 —— **六支端點沒有一支吐出它**。
    前端**做得到**自己照 `person_source` 組（案件 API 有 `assignedTo`），
    ☠️ 而那是把同一條規則抄到第二個地方：
    ```
    helpers/bonus.py 已標「已知的未來來源 quotations.assigned_user_ids」
    ⇒ 加它的那天：後端改、JS 不會跟
    ⇒ 症狀是**少發一個人，而總額對得起來**
    ```
    🔑 **對不起來還有人會查，對得起來沒有人會查。** ⇒ 規則只有一份。

    ## ⚠️ 三件刻意的

    ```
    ① 閘門與 POST /awards **同一道**（_is_manager），不可以更鬆
       ☠️ 更鬆 ⇒ 一般員工看得到全案每個人的發放對象名單，
          而 visible_lines() 那條「本人只看得到自己那一列」就被繞過去了
    ② ok=false 的項目**要留在清單裡**並說出為什麼，不可以濾掉
       ☠️ 濾掉 ⇒ 那個項目從來不出現，而**沒有人會發現一個從來不出現的東西**
    ③ items 用 `WHERE is_active = 1`，與 create_award **同一條**
       ☠️ 不同的話：畫面列出已停用的項目 -> 填完比例 -> 按下去收到 400
          ⇒ 那是「先問再做」失效的形狀 —— **問過了，而答案是錯的**
    ```

    ## ☠️ 單位是**基點**（1/10000），而欄位名字叫 `pct`

    `50%` 要送 `5000` 不是 `50`。送 `50` 的話獎金變成應得的 1/100，
    **而畫面上它是一個格式正確的金額** ⇒ 沒有人會看成錯誤。
    ⇒ 回應裡明著標單位（`pct_unit`），欄位名 `pct` 不改（改名要動 DDL 與 API）。
    """
    user = _require_user(authorization)
    if not _is_manager(user):
        raise HTTPException(403, "僅管理員以上可查閱獎金發放對象。")
    conn = get_db()
    try:
        settle = _settlement_of(conn, quote_no)
        if settle is None:
            # ⚠️ 與 GET /base 同一條（404）。一致比「這一支自己想一個」重要。
            raise HTTPException(404, "找不到案件「%s」。" % quote_no)
        ok, base, err = base_amount_for(settle)
        case = _case_people(conn, quote_no)
        items = [dict(r) for r in conn.execute(
            "SELECT * FROM bonus_items WHERE is_active = 1"
            " ORDER BY sort_order, id")]
        _attach_group_people(conn, items)
        _attach_manual_people(conn, items)
        live = conn.execute(
            "SELECT id FROM bonus_awards WHERE quote_no = ? AND voided_at = ''",
            (quote_no,)).fetchone()

        out = []
        for item in items:
            good, people, note = people_for_item(item, case)
            out.append({
                "bonus_item_id": item["id"],
                "name": item["name"],
                "person_source": item["person_source"],
                # 🔑 `ok` 與 `people` 從**同一次呼叫**取，不各算一次
                #    ⇒ 「可以發放，但沒有人」在結構上就不可能出現。
                "ok": bool(good),
                "people": list(people or ()),
                # 📌 `note` 直接用後端回的字串，前端不重寫文案 ⇒ 規則只有一份。
                "note": note or "",
            })
        # `QS1-a §3③`：`people` 現在是帳號（`_case_people()` 已解析），畫面
        # 要印顯示名稱——比照 `list_awards()`／`get_award()`，一次查完全部
        # 不逐筆查，不在前端自己對照（那會變成第二份「帳號->顯示名」邏輯）。
        display_names = display_names_for(
            conn, (p for it in out for p in it["people"]))
    finally:
        conn.close()

    return {
        "quote_no": quote_no,
        "display_names": display_names,
        # `SPEC-BN6-BN7.md §2`：整張精算明細，逐字抄 settlement.html 的鍵名，
        # 原樣帶出、不重算（見 `_settlement_fields()` docstring）。
        "settlement": _settlement_fields(settle),
        # ⚠️ 與 GET /base 同一個計算來源（base_amount_for）
        #    ☠️ 各算一次而算法漂移的話，畫面顯示的基數與實際入帳的基數會不同，
        #       **而兩個數字都看起來合理**。
        "base": {"ok": bool(ok), "amount": base, "error": err or ""},
        # 🔑 先問再做：POST /awards 撞到部分唯一索引會回 409，
        #    而畫面在按下產生之前就該知道答案。
        "has_active_award": live is not None,
        "active_award_id": int(live["id"]) if live is not None else 0,
        "items": out,
        # ☠️ 明著標單位 —— 送 50 當 50% 的話金額是應得的 1/100，而它看起來正常。
        "pct_unit": "basis_points",
        "pct_full": BASIS_POINTS,
    }

#: `BN5`：「已結案」不在 `status` 欄位裡——那裡只有「已送出／已拒絕」。
#: `deal_tag` 才是（實查：`quotations.py:271` 已經用它判斷「已結案」，
#: 這裡沿用同一個字面值，不是另外定義一次「已結案」是什麼）。
_CLOSED_DEAL_TAG = "已結案"


# 🔴 這一支必須宣告在任何 `GET /awards/{award_id}` 之前（今天還沒有這種
# 單一片語的路由，但 `BN10`——點開一張獎金分潤單看完整內容——已經在排隊了）。
# `/awards/candidates` 與 `/awards/{award_id}` 是**同一種形狀**（`/awards/`
# 後面都只有一段）：`{award_id}` 若宣告在前，`/awards/candidates` 會被
# 它接走，`"candidates"` 當 `award_id` 做 int 轉換失敗 -> 422。
# 📌 依據見 `routers/bonus.py` 頂端 `GET /awards/plan/{quote_no}` 的同款
# 註解——同一個坑，這裡先把話留給下一個加端點的人。
@router.get("/awards/candidates")
def award_candidates(authorization: str = Header(None)):
    """獎金分潤單「案件編號」下拉的候選清單（`BN5`）。

    ## 🔴 母體是 `deal_tag = '已結案'`，不是 `status`

    `quotations.status` 只有「已送出／已拒絕」，沒有「已結案」這個值——
    照 `status` 查會查到 0 筆，而那與「沒有可選的案件」長得一模一樣。

    ## 🔴 兩件不可以被濾掉的事（`SPEC-BN2-BN5.md §4`）

    ```
    ① 淨利 <= 0／精算是舊格式的案件  -> 列出來、標原因、不可選
    ② 已經有有效獎金分潤單的案件    -> 標示「已產生（#id）」、不可選
       ⚠️ 判斷用 voided_at = ''，不是「有沒有紀錄」——作廢重開是正常
          流程，作廢之後同一個案件要能再選一次。
    ```
    ☠️ 濾掉的症狀是使用者只看到選單裡沒有它，而他不知道為什麼——
       與 `BN1` 的「`ok=false` 的項目不可以濾掉」同一條規則。

    ## 🔑 「淨利<=0」與「精算是舊格式」是兩件不同的事，訊息不可以合併

    直接重用 `base_amount_for()` 的 `err`——那一支對這兩種情況本來就回
    不同的訊息（前者「沒有可分配的獎金基數」，後者
    `LEGACY_SETTLEMENT_MESSAGE` 那句「請重新開啟並儲存」），這裡不用
    自己判斷是哪一種再各寫一句，直接原樣搬過來就是兩句不同的話。
    """
    user = _require_user(authorization)
    if not _is_manager(user):
        raise HTTPException(403, "您沒有產生獎金分潤單的權限。")
    conn = get_db()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT quote_no, customer_name, project_name, data_json"
            " FROM quotations WHERE deal_tag = ?"
            " AND json_extract(data_json, '$.settlement.status') = 'finalized'"
            " ORDER BY quote_no DESC", (_CLOSED_DEAL_TAG,))]
        live_by_quote = {r["quote_no"]: r["id"] for r in conn.execute(
            "SELECT id, quote_no FROM bonus_awards WHERE voided_at = ''")}
    finally:
        conn.close()

    items = []
    for r in rows:
        try:
            data = json.loads(r["data_json"] or "{}")
        except (TypeError, ValueError):
            data = {}
        settle = data.get("settlement") or {}
        net_profit = (settle.get("summary") or {}).get("netProfit")

        aid = live_by_quote.get(r["quote_no"])
        if aid is not None:
            # ④ 已有有效獎金分潤單：優先於淨利判斷——就算這個案子現在淨利
            #    算不出來，「已經有一張單」仍然是使用者最需要知道的事。
            selectable, reason = False, "已產生（#%s）" % aid
        else:
            ok, _base, err = base_amount_for(settle)
            selectable, reason = bool(ok), (err or "")

        items.append({
            "quote_no": r["quote_no"],
            "customer_name": r.get("customer_name") or "",
            "project_name": r.get("project_name") or "",
            "netProfit": net_profit,
            "selectable": selectable,
            "reason": reason,
        })
    return {"items": items}


@router.get("/awards")
def list_awards(include_voided: bool = False, authorization: str = Header(None)):
    """獎金分潤單清單。**分錄列依可見性過濾。**

    ⚠️ 非管理者也看得到**單**（否則他不知道自己那一筆屬於哪一案），
       而他只看得到**自己那一列**金額。
    ☠️ 反過來（整張單都不給看）的話，他收到一筆錢而查不到來源。

    🔴 `BN9`（2026-09-23）：「看得到全部」收緊成 **superadmin**。
       ⇒ `admin` 在這一頁與一般同仁相同（只看得到自己那一列），
         而他仍然**產生得了**獎金分潤單 —— 見 `can_create_award`。
       ⚠️ 副作用要講出來：`admin` 產生了一張自己不在裡面的獎金分潤單之後，
          **那張單不會出現在他的清單上**（他沒有任何一列）。
          那是這個裁定的直接後果，不是缺陷。
    """
    user = _require_user(authorization)
    me = user.get("username") or ""
    # 🔴 `BN9`：**讀**的範圍是 superadmin，不是 `_is_manager`。
    manager = _sees_all_lines(user)
    conn = get_db()
    try:
        # 🔑 預設只看有效的：作廢單仍查得到（稽核），而要明著要。
        sql = "SELECT * FROM bonus_awards"
        if not include_voided:
            sql += " WHERE voided_at = ''"
        awards = [dict(r) for r in conn.execute(sql + " ORDER BY id DESC")]
        by_award = {}
        for r in conn.execute(
                "SELECT * FROM bonus_award_lines ORDER BY id"):
            by_award.setdefault(r["award_id"], []).append(dict(r))
        # `BN15`：清單只有案件編號，使用者原話「沒有案件名稱」。
        case_names = _case_names_for(conn, (a["quote_no"] for a in awards))
        # `QS1-a §3③`：`username` 現在存帳號，畫面要印顯示名稱——
        # 一次查完全部，不逐列查（同 `BN15` 的 `_case_names_for` 那條規則）。
        names = display_names_for(
            conn, (ln["username"] for lines in by_award.values() for ln in lines))
    finally:
        conn.close()

    out = []
    for a in awards:
        lines = visible_lines(by_award.get(a["id"], []), me, is_admin=manager)
        if not manager and not lines:
            # 🔴 與自己無關的單**完全不出現** —— `§七`「其他人看不到」。
            continue
        for ln in lines:
            ln["displayName"] = names.get(ln["username"], ln["username"])
        a["lines"] = lines
        # ⚠️ 非管理者看不到整張單的總額（那等於看得到別人領多少的總和）。
        a["visible_total"] = sum(l["amount"] for l in lines)
        # `BN15`：即時查，不存快照——案件改名不會讓這裡跟著漂移。
        cn = case_names.get(a["quote_no"]) or {}
        a["customer_name"] = cn.get("customer_name", "")
        a["project_name"] = cn.get("project_name", "")
        if not manager:
            a.pop("base_amount", None)
        # 🔴 `BN8`：簽核格。誰簽了、簽了沒都不是金額，不用跟著可見範圍收緊
        #    ——與 `get_voucher()` 把 signatures 一起帶出去同一個道理。
        a["signatures"] = bonus_signatures_of(a)
        out.append(a)
    return {
        "awards": out,
        # 🔑 **可見範圍**（看得到別人那幾列嗎）
        "is_manager": manager,
        # 🔑 **入口**（按得到「產生獎金分潤單」嗎）——`admin` 這兩格答案不同。
        #    ⚠️ 與 `bonus.html:158` 那一條同一個道理：入口要看真正的那道閘門，
        #       用可見範圍去擋的話，有權限的人會看不到按鈕（反過來就是
        #       看得到按鈕、按下去收 403）。
        "can_create_award": _is_manager(user),
    }


@router.get("/awards/{award_id}")
def get_award(award_id: int, authorization: str = Header(None)):
    """一張獎金分潤單的完整內容（`BN10`）。

    使用者原話：「獎金單要跟報價單的頁面一樣……點選後可載入完整資料跟
    明細」——這支端點就是那個「點選後載入」打的那一支，回應要包含畫面
    上需要顯示的**全部**東西：案件精算明細（與 `GET /plan` 同一支
    `_settlement_fields()`，不重算）＋分錄明細＋簽核狀態，一次拿齊，
    不必再讀第二支端點。

    可見性與 `GET /awards`（清單）**同一條規則**：非管理者只看得到自己
    那一列，且看不到 `base_amount`——這裡不能因為是「點進去看詳情」就
    放寬，那樣等於用另一個入口繞過清單端點已經擋住的東西。
    """
    user = _require_user(authorization)
    me = user.get("username") or ""
    manager = _sees_all_lines(user)
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM bonus_awards WHERE id = ?",
                           (award_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "找不到這張獎金分潤單。")
        award = dict(row)
        lines = [dict(r) for r in conn.execute(
            "SELECT * FROM bonus_award_lines WHERE award_id = ? ORDER BY id",
            (award_id,))]
        settle = _settlement_of(conn, award["quote_no"])
        # `BN15`：彈窗標題也要有案件名稱，不只清單列。
        cn = _case_names_for(conn, (award["quote_no"],)).get(
            award["quote_no"]) or {}
        # `QS1-a §3③`：同 list_awards()，username 存帳號、畫面印顯示名稱。
        names = display_names_for(conn, (ln["username"] for ln in lines))
        # `BN17`：上次退回的記錄——沿用 `JV22 §6` 的顯示精神，只是這裡
        # 沒有「這次編修」那一半（退回後改不了內容，見 §3b／使用者裁乙）。
        last_reject = _last_reject_of(conn, award_id, award)
    finally:
        conn.close()

    award["customer_name"] = cn.get("customer_name", "")
    award["project_name"] = cn.get("project_name", "")
    visible = visible_lines(lines, me, is_admin=manager)
    if not manager and not visible:
        # 🔴 與清單同一條：跟這個人無關的單，連整張單的存在都不透露——
        #    404 不是 403，不要洩漏「這張單存在，只是你看不到」。
        raise HTTPException(404, "找不到這張獎金分潤單。")

    for ln in visible:
        ln["displayName"] = names.get(ln["username"], ln["username"])
    award["lines"] = visible
    award["visible_total"] = sum(l["amount"] for l in visible)
    if not manager:
        award.pop("base_amount", None)
    award["signatures"] = bonus_signatures_of(award)
    award["settlement"] = _settlement_fields(settle)
    award["last_reject"] = last_reject
    award["can_recall"] = _can_recall(award, me)
    return award


def _last_reject_of(conn, award_id, award):
    """最近一次退回的記錄（`BN17`）。回 `None` 或
    `{at, by, reason, prior_signatures}`。

    `reject_award()` 把「狀態轉換／舊簽核鏈／退回原因」三筆寫進**同一列**
    `bonus_award_edit_log`（同一次退回，同一個 changed_at）——這裡找的是
    `field == "status" and to == "草稿"` 那一列，其餘兩個 field 就在
    同一列的 `changes_json` 裡，不必再對到別的列。

    `prior_signatures` 重用 `bonus_signatures_of()`——那支只讀
    `award["approval_json"]`，餵一個裝著**舊**鏈的假 `award` 進去就能拿到
    退回當下「誰簽過」的同一種格式，不必為了「這是舊資料」重寫一次
    解析規則。
    """
    for r in conn.execute(
            "SELECT changed_by, changed_at, changes_json"
            " FROM bonus_award_edit_log WHERE award_id = ? ORDER BY id DESC",
            (award_id,)):
        changes = json.loads(r["changes_json"] or "[]")
        status_change = next(
            (c for c in changes
             if c.get("field") == "status" and c.get("to") == "草稿"), None)
        if status_change is None:
            continue
        reason_change = next(
            (c for c in changes if c.get("field") == "退回原因"), None)
        approval_change = next(
            (c for c in changes if c.get("field") == "approval_json"), None)
        old_json = (approval_change or {}).get("from") or "{}"
        prior_signatures = bonus_signatures_of({
            "approval_json": old_json,
            "created_by": award.get("created_by") or "",
            "created_at": award.get("created_at") or "",
        })
        return {
            "at": r["changed_at"],
            "by": r["changed_by"],
            "reason": (reason_change or {}).get("to") or "",
            "prior_signatures": prior_signatures,
        }
    return None


def _validate_manual_people(conn, usernames):
    """`BN18 §3`：手動指定人員的資料層驗證。**硬性要求：挑人只能從清單
    選，送 username，不是打字輸入**——這裡是那條界線最後一道防線：查不到
    或已停用的帳號**整批 400**，不寫入任何一列（〈拒絕的路徑上不可以留
    下副作用〉，同 `resolve_picks()` 的做法）。

    ⚠️ 不可以用 `display_name` 當鍵去反查——那正是 `_m010` 回填失敗的
    那條路（同名或改過名就查不到，而它不會報錯）。
    """
    names = []
    for u in (usernames or ()):
        u = str(u or "").strip()
        if u and u not in names:
            names.append(u)
    if not names:
        raise HTTPException(400, "手動指定至少要選一個人。")
    placeholders = ",".join("?" for _ in names)
    valid = {r["username"] for r in conn.execute(
        "SELECT username FROM users WHERE username IN (%s) AND active = 1"
        % placeholders, tuple(names))}
    missing = [n for n in names if n not in valid]
    if missing:
        raise HTTPException(
            400, "手動指定的帳號查不到或已停用：%s。" % "、".join(missing))
    return names


def _plan_allocations(conn, quote_no, allocations):
    """`allocations` -> `(settle, base, planned)`，`planned` 是
    `[(item, total_pct, lines)]`。擋不過就直接 `raise HTTPException`。

    ## 🔴 `POST /awards`（真的產生）與 `POST /awards/plan/{quote_no}`
       （只預覽）**共用這一支**，不各寫一份

    `SPEC-BN6-BN7.md §6④`（核心）：預覽回的 `lines` 必須與產生後寫進
    `bonus_award_lines` 的值**逐筆相等**。兩支端點各自重寫一次同樣的
    驗證＋`split_award()` 呼叫的話，「一致」只是碰巧兩份實作現在長得
    一樣，改一邊而忘了改另一邊那天就會分岔，而**分岔了也不會有任何
    測試失敗**（因為兩邊各自對自己的邏輯一致）。⇒ 讓它們在結構上
    不可能分岔：只有一份算法，兩支端點都呼叫它。
    """
    settle = _settlement_of(conn, quote_no)
    if settle is None:
        raise HTTPException(404, "找不到案件「%s」。" % quote_no)
    ok, base, err = base_amount_for(settle)
    if not ok:
        # 🔑 這句話是使用者唯一看得到的東西，而它**講得出出路**。
        raise HTTPException(400, err)

    case = _case_people(conn, quote_no)
    items = {r["id"]: dict(r) for r in conn.execute(
        "SELECT * FROM bonus_items WHERE is_active = 1")}
    _attach_group_people(conn, items.values())
    _attach_manual_people(conn, items.values())

    planned = []
    for alloc in allocations:
        item = items.get(int(alloc.get("bonus_item_id") or 0))
        if item is None:
            raise HTTPException(400, "獎金項目不存在或已停用。")
        # `BN18`：使用者原話「產生獎金單時能手動指定人」——給「案件資料裡
        # 沒有執行人，而我知道是誰該領」一條出路（`case_stages.assigned_to`
        # 今天 100% 是空的，這條路目前是唯一走得通的方式）。**不是拿掉
        # 既有的拒絕**：沒有明著宣告覆寫時，解析出 0 人一樣被擋。
        #
        # 🔴 判斷式**只能看這個明著宣告的旗標**，不可以寫成
        # `if alloc.get("people"):`——那是〈null 不等於 0〉的另一個形狀：
        # 「沒送這個鍵」與「送了一個空清單」是兩件事，合併之後會安靜地
        # 蓋掉正確的解析結果（金額照算、總額照樣對得起來，沒有人發現）。
        if alloc.get("person_source_override"):
            people = _validate_manual_people(conn, alloc.get("people"))
            source_snapshot = "manual"
            # `§4c`：完全取代，不是在來源之上加減——`manual_basis` 記的是
            # 「覆寫前解析出來的來源是什麼」，這裡要包含**型別＋解析結果**
            # 兩件事，不能只記型別：那一欄的用途是事後看得出這張單本來
            # 會發給誰，只記型別的話，半年後案件資料變了，「本來解析得出
            # 是誰」就永遠查不到了。⚠️ 一筆紀錄（純文字），不是新增可
            # 查詢／可篩選的欄位——不落地成結構化資料，只是把
            # `people_for_item()` 這次順手也算出來的結果寫成一句話存起來。
            basis_good, basis_people, basis_note = people_for_item(item, case)
            basis_result = (
                "、".join(basis_people) if basis_good
                else (basis_note or "無可發放對象"))
            manual_basis = "%s：%s" % (item.get("person_source") or "",
                                      basis_result)
        else:
            good, people, note = people_for_item(item, case)
            if not good:
                raise HTTPException(400, "「%s」%s。" % (item["name"], note))
            source_snapshot = item["person_source"]
            manual_basis = ""
        total_pct = int(alloc.get("total_pct") or 0)
        shares = alloc.get("person_pct") or {}
        # `BN14`：使用者原話「如有複數人員自動計算比例」——群組來源且
        # 呼叫端沒有送 person_pct 時，系統自動均分，不是叫使用者自己
        # 心算 `10000 // 人數`。均分後分不盡的餘數**留白不分給任何
        # 人**（不進 `shares`），會自然併入 `remainder_of()` 算出來的
        # 尾差——與 `split_award()` 既有「尾差歸公司」同一條規則，不用
        # 另外處理一次。
        if item.get("person_source") == "group" and not shares:
            share = BASIS_POINTS // len(people)
            shares = {p: share for p in people}
        pairs = [(p, int(shares.get(p, 0))) for p in people]
        # 🔴 上界**釘在 `base` 上，不釘在 `pool` 上**。
        #
        # ☠️ 兩種超額的症狀相反，而第二種看不見：
        # ```
        # Σperson_pct > 10000   兩人各 100%
        #   pool=61728  Σamount=123456  remainder_of() = **-61728**  看得見
        # total_pct   > 10000   20000（200%）
        #   pool=**246912**（=base×2）    remainder_of() = **0**     看不見
        # ```
        # 而 `split_award()` docstring 的兩條不變量在後者**也都成立**
        # （`246912 <= 246912`、餘 `0 < 1`）——
        # 🔑 **因為 pool 本身已經被撐大了，而不變量拿 pool 當基準。**
        #    *一個以受污染的值為基準的檢查，永遠不會發現污染。*
        # ⇒ 所以這道關卡不可以改寫成「檢查 remainder_of() 是不是負的」。
        #
        # ⚠️ 邊界是 `<=` 不是 `<`：少發（例如只發 80%）是**合法的公司政策**，
        #    剛好 100% 也要放行。寫成 `>= BASIS_POINTS` 就擋掉了整數的 100%。
        # ⚠️ 而**不可以只在前端擋** —— `bonus.js` 自己的註解逐字：
        #    「前端過濾是假的：值仍然在 API 回應裡」，同一個道理套在輸入上。
        if total_pct < 0:
            # 📌 `base` 那一側已經擋了（base_amount_for 對負淨利回 False），
            #    缺的只有 `pct` 這一側：pool_for(123456, -5000) = -61728
            #    ⇒ 負的獎金池在傳票上是一筆反向分錄，**帳是平的**。
            raise HTTPException(
                400, "「%s」的發放比例不可以是負數。" % item["name"])
        if total_pct > BASIS_POINTS:
            raise HTTPException(
                400, "「%s」的發放比例 %s%% 超過 100%%，"
                     "獎金池會大於案件淨利。"
                     % (item["name"], _pct_text(total_pct)))
        person_sum = sum(p[1] for p in pairs)
        if person_sum <= 0:
            raise HTTPException(
                400, "「%s」的人員比例全部是 0，無法發放。" % item["name"])
        if person_sum > BASIS_POINTS:
            raise HTTPException(
                400, "「%s」的人員比例合計 %s%% 超過 100%%，"
                     "公司留存會變成負數。"
                     % (item["name"], _pct_text(person_sum)))
        planned.append((item, total_pct, split_award(base, total_pct, pairs),
                       source_snapshot, manual_basis))
    return settle, base, planned


@router.post("/awards", dependencies=_GONE)
def create_award(body: dict = Body(...), authorization: str = Header(None)):
    """依案件產生一張獎金分潤單（**套用當下凍結**）。

    ## 🔴 一個案件同時只能有一筆**有效**獎金

    靠的是 `v97` 的**部分**唯一索引（`WHERE voided_at = ''`）——
    ⇒ 重複產生會撞 `IntegrityError`，這裡把它翻成一句看得懂的話。

    ## ⚠️ 解析不出人的項目 **拒絕整張單**，不是跳過那一項

    ☠️ 跳過的兩個後果，第二個更糟：
    ```
    ① 那個項目從來沒出現在任何一張獎金分潤單上（沒有人會發現）
    ② **把金額併給別的項目** => 別人領多了，而總額對得起來
    ```
    """
    user = _require_user(authorization)
    if not _is_manager(user):
        raise HTTPException(403, "僅管理員以上可產生獎金分潤單。")
    quote_no = (body.get("quote_no") or "").strip()
    if not quote_no:
        raise HTTPException(400, "請指定案件編號。")
    allocations = body.get("allocations") or []
    if not allocations:
        raise HTTPException(400, "請至少設定一個獎金項目的比例。")

    conn = get_db()
    try:
        _settle, base, planned = _plan_allocations(conn, quote_no, allocations)

        now = datetime.now().isoformat()
        try:
            cur = conn.execute(
                "INSERT INTO bonus_awards (quote_no, base_amount, template_id,"
                " template_version, status, created_by, created_at, updated_at)"
                " VALUES (?,?,?,?,'草稿',?,?,?)",
                (quote_no, base, int(body.get("template_id") or 0),
                 int(body.get("template_version") or 0),
                 _user_name(user), now, now))
        except Exception as exc:                            # noqa: BLE001
            if "UNIQUE" in str(exc).upper():
                raise HTTPException(
                    409, "案件「%s」已經有一張有效的獎金分潤單。"
                         "若要重發，請先作廢原本那一張。" % quote_no)
            raise
        award_id = cur.lastrowid
        for item, total_pct, lines, source_snapshot, manual_basis in planned:
            for ln in lines:
                conn.execute(
                    "INSERT INTO bonus_award_lines (award_id, bonus_item_id,"
                    " item_name_snapshot, username, person_source_snapshot,"
                    " total_pct, person_pct, amount, manual_basis)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (award_id, item["id"], item["name"], ln["username"],
                     source_snapshot, total_pct, ln["person_pct"],
                     ln["amount"], manual_basis))
        conn.commit()
    finally:
        conn.close()

    _audit(_tok(authorization), "bonus.award.create", "bonus_awards",
           str(award_id), "產生獎金分潤單：%s（基數 %s）" % (quote_no, f"{base:,}"))
    return {"ok": True, "id": award_id, "base_amount": base}


@router.post("/awards/plan/{quote_no}")
def preview_award(quote_no: str, body: dict = Body(default={}),
                  authorization: str = Header(None)):
    """`SPEC-BN6-BN7.md §2`：**既有路徑多一個動詞**，只算不寫。

    `body` 與 `POST /awards` 的 `allocations` 完全相同——這裡回的
    `lines` 與 `POST /awards` 產生後寫進 `bonus_award_lines` 的值
    **逐筆相等**，因為兩支端點共用同一支 `_plan_allocations()`
    （`§6④`：這一題紅而其他全綠 = 預覽會騙人，而那比沒有預覽更糟）。

    ⚠️ 這裡**不寫任何一列進資料庫**——不開 `INSERT`、不 `commit`，
    只讀（`_settlement_of`／`bonus_items`／`_case_people`）再回傳算好的
    結果。
    """
    user = _require_user(authorization)
    if not _is_manager(user):
        raise HTTPException(403, "僅管理員以上可預覽獎金分潤。")
    allocations = body.get("allocations") or []
    if not allocations:
        raise HTTPException(400, "請至少設定一個獎金項目的比例。")

    conn = get_db()
    try:
        settle, base, planned = _plan_allocations(conn, quote_no, allocations)

        lines_out = []
        remainder = 0
        for item, total_pct, lines, source_snapshot, manual_basis in planned:
            remainder += remainder_of(base, total_pct, lines)
            for ln in lines:
                lines_out.append({
                    "bonus_item_id": item["id"],
                    "username": ln["username"],
                    "person_source_snapshot": source_snapshot,
                    "manual_basis": manual_basis,
                    "total_pct": total_pct,
                    "person_pct": ln["person_pct"],
                    "amount": ln["amount"],
                })
        # `QS1-a §3③`：同 `plan_award()`（GET）——username 存帳號，畫面印
        # 顯示名稱，一次查完全部。
        display_names = display_names_for(
            conn, (ln["username"] for ln in lines_out))
    finally:
        conn.close()

    return {
        "quote_no": quote_no,
        "display_names": display_names,
        "settlement": _settlement_fields(settle),
        "base": {"ok": True, "amount": base, "error": ""},
        "lines": lines_out,
        # `§6⑤`：尾差要印在表上——不印的話使用者自己加總會發現「對不起來」，
        # 而他不知道那是設計（歸公司，不補給任何人）。
        "remainder": remainder,
    }


@router.post("/awards/{award_id}/submit", dependencies=_GONE)
def submit_award(award_id: int, body: dict = Body(default={}),
                 authorization: str = Header(None)):
    """送審：草稿 -> 待審核。`SPEC-BN8.md §3`：三支端點一律 superadmin。

    建鏈照 `submit_voucher()` 的做法：設定存在就照設定，不存在就維持現況
    （這裡的「現況」是鏈為空，`approve_award()` 的 no-tiers 分支接手，
    見那支的 docstring）。
    """
    user = _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM bonus_awards WHERE id = ?",
                           (award_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "找不到這張獎金分潤單。")
        award = dict(row)
        if award.get("status") != "草稿":
            raise HTTPException(
                400, "只有草稿可以送審，這一張現在是「%s」。" % award.get("status"))
        # ⚠️ 「沒有設定過」與「設定成空的」是兩件事（〈null 不等於 0〉）：
        #    用 `_get_setting(key, None)` 判鍵在不在，不要用
        #    `resolve_active_flow_setting()`（它對缺鍵回 `{"tiers": []}`，
        #    與存成空的設定一模一樣）。
        scope = _get_setting("approval_flow_scope", {}) or {}
        flow = _get_setting(approval_flow_setting_key("bonus", scope), None)
        tiers = []
        if flow is not None:
            try:
                tiers = setting_to_active_tiers(flow, conn, user["username"])
            except UnresolvedManagerError as exc:
                raise HTTPException(400, str(exc))
        now = datetime.now().isoformat()
        # 🔴 `requestedBy` 要嵌進來（同 `submit_voucher()`）——簽核佇列的
        #    count 端點（`quotations.py::get_approval_queue_count()`）沒有
        #    鏈時靠 `appr.get("requestedBy") != my_username` 判「自己送的
        #    不算」；漏了這欄的話，送審的那個 superadmin 自己的角標數字
        #    也會 +1（因為空字串永遠不等於任何使用者名稱）。
        appr = json.dumps(
            {"tiers": tiers, "currentTier": 0, "requestedBy": user["username"]},
            ensure_ascii=False)
        conn.execute(
            "UPDATE bonus_awards SET status='待審核', approval_json=?,"
            " updated_at=? WHERE id=?", (appr, now, award_id))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "bonus.award.submit", "bonus_awards",
           str(award_id), "獎金分潤單送審")
    return {"ok": True, "status": "待審核"}


@router.post("/awards/{award_id}/approve", dependencies=_GONE)
def approve_award(award_id: int, body: dict = Body(default={}),
                  authorization: str = Header(None)):
    """簽核通過。逐層推進；簽完最後一層 -> 已核准。

    ## ⚠️ 沒有設定過簽核流程時，**沒有像傳票 `§161` 那樣的內建兩格 fallback**

    `SPEC-BN8.md §1`：獎金分潤單一格投影欄位都沒有，比傳票乾淨。而三支端點
    本來就只有 superadmin 打得到（`§3`），沒有「一般員工」這種角色需要
    內建兩格去代表——鏈是空的時候，任一 superadmin 一次核准即完成，
    不必假造一層只為了跟傳票同形。
    """
    user = _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM bonus_awards WHERE id = ?",
                           (award_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "找不到這張獎金分潤單。")
        award = dict(row)
        status = award.get("status")
        if status not in ("待審核", "簽核中"):
            raise HTTPException(400, "「%s」的獎金分潤單不在簽核流程裡。" % status)
        now = datetime.now().isoformat()
        try:
            appr = json.loads(award.get("approval_json") or "{}") or {}
        except (TypeError, ValueError):
            raise HTTPException(400, "這張獎金分潤單的簽核資料格式不正確，無法繼續簽核。")
        tiers = appr.get("tiers") or []
        if tiers:
            idx = int(appr.get("currentTier") or 0)
            if idx >= len(tiers):
                raise HTTPException(400, "這張獎金分潤單的簽核已經完成。")
            tier = tiers[idx] or {}
            tier["approvedBy"] = _user_name(user)
            tier["approvedAt"] = now
            tiers[idx] = tier
            idx += 1
            appr["tiers"], appr["currentTier"] = tiers, idx
            nxt = "已核准" if idx >= len(tiers) else "簽核中"
            conn.execute(
                "UPDATE bonus_awards SET status=?, approval_json=?,"
                " updated_at=? WHERE id=?",
                (nxt, json.dumps(appr, ensure_ascii=False), now, award_id))
        else:
            nxt = "已核准"
            conn.execute(
                "UPDATE bonus_awards SET status=?, updated_at=? WHERE id=?",
                (nxt, now, award_id))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "bonus.award.approve", "bonus_awards",
           str(award_id), "獎金分潤單簽核：%s" % nxt)
    return {"ok": True, "status": nxt}


@router.post("/awards/{award_id}/reject", dependencies=_GONE)
def reject_award(award_id: int, body: dict = Body(default={}),
                 authorization: str = Header(None)):
    """退回：回草稿，**清除簽核**。

    `SPEC-BN8.md §5d`：**不要照抄傳票現在那段 SQL**——`send_back_voucher`
    當時清了 v99 那六欄卻沒碰 `approval_json`，AS2 之後鏈才是真相，
    只清六欄的話一張退回的草稿仍然照鏈畫出上一輪已簽的名字。這裡只有
    一份來源（`approval_json`），一起清：用 `'{}'` 不是 `''`（與 `v102`
    的 `DEFAULT` 一致，`_bonus_chain_tiers()` 對兩者都回 `[]`，查過）。

    ⚙️ 驗收釘的是 `bonus_signatures_of()` 的**輸出**：簽核那幾格（覆核／
    主管／第 N 層）`by` 都是空的，**不是「每一格」**——「製表」是
    `created_by`（建檔人，不是簽核），退回不該動它。

    ## 🔴 `BN17`：擋空原因＋寫 `bonus_award_edit_log`（`retention='permanent'`）

    與 `mark_award_paid()`／`vouchers.py::void_voucher()` 同一條規則——
    「日後沒有人回得出這張單為什麼被退回」。`_audit()` 留著不拿掉：
    `audit_log` 是操作軌跡（730 天會被清），`bonus_award_edit_log` 是
    憑證的一部分（永久保留），兩者職責不同。

    ⚠️ **`approval_json` 的舊值要在 `UPDATE` 之前讀出來**——晚讀的話那一列
    會寫成 `{} -> {}`，看起來是一筆正常的紀錄，而它什麼都沒記住。
    """
    user = _require_user(authorization, require_superadmin=True)
    reason = (body.get("reason") or "").strip()
    if not reason:
        raise HTTPException(400, "請填寫退回原因。")
    now = datetime.now().isoformat()
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM bonus_awards WHERE id = ?",
                           (award_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "找不到這張獎金分潤單。")
        award = dict(row)
        status = award.get("status")
        if status not in ("待審核", "簽核中"):
            raise HTTPException(400, "「%s」的獎金分潤單不能退回。" % status)
        old_approval_json = award.get("approval_json") or "{}"
        conn.execute(
            "UPDATE bonus_awards SET status='草稿', approval_json='{}',"
            " updated_at=? WHERE id=?", (now, award_id))
        append_edit_log(conn, award_id, _user_name(user), [
            {"field": "status", "from": status, "to": "草稿"},
            {"field": "approval_json", "from": old_approval_json, "to": "{}"},
            {"field": "退回原因", "from": "", "to": reason},
        ], table="bonus_award_edit_log", retention="permanent", changed_at=now)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "bonus.award.reject", "bonus_awards",
           str(award_id), "獎金分潤單退回：%s" % reason)
    return {"ok": True, "status": "草稿"}


@router.post("/awards/{award_id}/mark-paid", dependencies=_GONE)
def mark_award_paid(award_id: int, body: dict = Body(default={}),
                    authorization: str = Header(None)):
    """手動標記已發放（`SPEC-BN8.md §5c` 的退路）：錢走系統外管道
    （例如臨時現金），沒有真的傳票號可以回填。

    ## 🔴 不可以偽造一個傳票號

    ```
    自動回填（主路，本規格未做）  voucher_no_payment = 'V-xxxx'  <= 有傳票號，可追
    手動標記（這支）              voucher_no_payment = **不碰**   <= 沒有傳票號，另外記
    ```
    ☠️ 兩條路若寫進同一個欄位而分不出來，這支就變成一個繞過帳務的合法
    入口（〈降級之後它還是會動〉）。另外記**誰標的／何時／為什麼**，
    ⚠️ 原因不可為空：空字串存得下去的話，日後沒有人回得出這筆錢為什麼
    走系統外。

    三個擋：`reason` 空 -> 400；已經 `is_paid()` -> 400（不可重複標記，
    不管是走哪一條路已發放的）；`status` 非「已核准」-> 400（錢還沒核定
    金額就先說發出去了，順序反了）。
    """
    user = _require_user(authorization, require_superadmin=True)
    reason = (body.get("reason") or "").strip()
    if not reason:
        raise HTTPException(400, "請填寫標記已發放的原因。")
    now = datetime.now().isoformat()
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM bonus_awards WHERE id = ?",
                           (award_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "找不到這張獎金分潤單。")
        award = dict(row)
        if award.get("status") != "已核准":
            raise HTTPException(
                400, "只有已核准的獎金分潤單可以標記已發放，這一張現在是「%s」。"
                     % award.get("status"))
        if is_paid(award):
            raise HTTPException(400, "這張獎金分潤單已經標記為發放過了。")
        conn.execute(
            "UPDATE bonus_awards SET paid_manually_by=?, paid_manually_at=?,"
            " paid_manually_reason=?, updated_at=? WHERE id=?",
            (_user_name(user), now, reason, now, award_id))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "bonus.award.mark_paid", "bonus_awards",
           str(award_id), "獎金分潤單手動標記已發放：%s" % reason)
    return {"ok": True}


@router.post("/awards/{award_id}/void", dependencies=_GONE)
def void_award(award_id: int, body: dict = Body(default={}),
               authorization: str = Header(None)):
    """作廢一張獎金分潤單。**原單留著**（與傳票同一條原則）。

    ☠️ 直接 DELETE 的話，帳上看不到那一次作廢 ——
       而使用者裁的是**作廢重開**，不是刪掉重來。

    🔴 `SPEC-BN8.md §6⑦⑧`（A 裁）：
    ```
    ⑦ 任何狀態都可以作廢，含已核准——不留出路的後果是「開錯了而改不掉」，
       權限同步改成 superadmin（與三支端點一致）
    ⑧ 已發放（is_paid()）的單，作廢不是一個旗標——錢已經出去了，
       只寫 voided_at 的後果是帳上那筆錢還在，而獎金分潤單說它作廢了。
       本輪擋下來（400，訊息提到沖銷），沖銷流程本規格不做。
    ```
    """
    user = _require_user(authorization, require_superadmin=True)
    reason = (body.get("reason") or "").strip()
    if not reason:
        # 🔑 沒有理由的作廢等於沒有留痕：事後沒有人回得出為什麼。
        raise HTTPException(400, "請填寫作廢原因。")
    now = datetime.now().isoformat()
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM bonus_awards WHERE id = ?",
                           (award_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "找不到這張獎金分潤單。")
        award = dict(row)
        if award["voided_at"]:
            raise HTTPException(400, "這張獎金分潤單已經作廢過了。")
        if is_paid(award):
            raise HTTPException(
                400, "這張獎金分潤單已經發放，不能直接作廢——錢已經出去了，"
                     "請先開立沖銷傳票，沖銷完成後再處理這張單。")
        conn.execute(
            "UPDATE bonus_awards SET voided_at = ?, voided_by = ?,"
            " void_reason = ?, updated_at = ? WHERE id = ?",
            (now, _user_name(user), reason, now, award_id))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "bonus.award.void", "bonus_awards",
           str(award_id), "作廢獎金分潤單：%s" % reason)
    return {"ok": True}


def _can_recall(award, username):
    """`BN12 §1①`：只有**原送審申請人**、且在待審核／簽核中才收得回來。
    比照 `quotations.py::recall_quotation()`（「只有原送審申請人可以收回」）。"""
    if award.get("status") not in ("待審核", "簽核中"):
        return False
    try:
        appr = json.loads(award.get("approval_json") or "{}")
    except ValueError:
        return False
    return bool(username) and appr.get("requestedBy") == username


@router.get("/awards/{award_id}/preview")
def preview_award(award_id: int, authorization: str = Header(None)):
    """`BN12`：預覽稿 HTML。**隨時可看，不看簽核狀態**；匯出（`pdf-download`）才擋。

    🔑 閘門綁在端點上，不綁在參數上（同 `JV11`）：兩支各自寫死自己的規則，
    沒有一個「條件」可以寫錯。權限與匯出同一道（`_is_manager`）。
    📌 與 PDF 來自同一支 `helpers/bonus_pdf.py::_award_html()`，版面只有一份。
    """
    user = _require_user(authorization)
    if not _is_manager(user):
        raise HTTPException(403, "僅管理員以上可預覽獎金分潤單。")
    body = preview_award_html(award_id)
    if body is None:
        raise HTTPException(404, "找不到這張獎金分潤單。")
    return HTMLResponse(content=body)


@router.post("/awards/{award_id}/recall", dependencies=_GONE)
def recall_award(award_id: int, authorization: str = Header(None)):
    """`BN12 §1①`：申請人把送審中的獎金分潤單**收回草稿**，清簽核。

    🔑 A 的理由：缺席的代價是「申請人送錯只能請簽核人退回」——那是每天會遇到的麻煩。
    ⚠️ 留編寫紀錄（permanent），與退回同一張表：收回也是這張單的歷史。
    """
    user = _require_user(authorization)
    me = user.get("username") or ""
    now = datetime.now().isoformat()
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM bonus_awards WHERE id = ?",
                           (award_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "找不到這張獎金分潤單。")
        award = dict(row)
        status = award.get("status")
        if status not in ("待審核", "簽核中"):
            raise HTTPException(
                400, "只有待審核或簽核中的獎金分潤單可以收回（目前是「%s」）。" % status)
        if not _can_recall(award, me):
            raise HTTPException(403, "只有原送審申請人可以收回這張獎金分潤單。")
        old_approval_json = award.get("approval_json") or "{}"
        conn.execute(
            "UPDATE bonus_awards SET status='草稿', approval_json='{}',"
            " updated_at=? WHERE id=?", (now, award_id))
        append_edit_log(conn, award_id, _user_name(user), [
            {"field": "status", "from": status, "to": "草稿"},
            {"field": "approval_json", "from": old_approval_json, "to": "{}"},
            {"field": "收回", "from": "", "to": "申請人收回草稿"},
        ], table="bonus_award_edit_log", retention="permanent", changed_at=now)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "bonus.award.recall", "bonus_awards",
           str(award_id), "獎金分潤單由申請人收回草稿")
    return {"ok": True, "status": "草稿"}


@router.get("/awards/{award_id}/pdf-download")
def download_award_pdf(award_id: int, authorization: str = Header(None)):
    """匯出獎金分潤單 PDF（`BN7`）。`SPEC-BN6-BN7.md §4` 定案的路徑，沿用
    既有 16 個呼叫端同一形狀。**權限與 `POST /awards` 同一道閘**
    （`_is_manager`）。

    閘門：`helpers/bonus_pdf.py::can_export()`——`voided_at` 優先於
    `status`（已作廢的單不管簽到哪裡都放行；`JV11`／`JV15` 同一條裁定）。
    """
    user = _require_user(authorization)
    if not _is_manager(user):
        raise HTTPException(403, "僅管理員以上可匯出獎金分潤單。")
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM bonus_awards WHERE id = ?",
                           (award_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, "找不到這張獎金分潤單。")
    # 🔑 先擋再算：草稿／待審核／簽核中直接拒絕，不必先跑一次 Edge
    #    headless 印出一份注定被丟掉的 PDF——那是稀缺資源（EDGE_PDF_SEMAPHORE）。
    ok, msg = can_export(dict(row))
    if not ok:
        raise HTTPException(400, msg)
    _award, pdf_bytes = export_award_pdf(award_id)
    _audit(_tok(authorization), "bonus.award.pdf_download", "bonus_awards",
           str(award_id), "匯出獎金分潤單 PDF")
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition":
                "attachment; filename=bonus-award-%s.pdf" % award_id})


def _username_of_sales_person(conn, sales_person_id, sales_person_name):
    """業務的顯示名 -> 帳號（`SPEC-QS1-a §3①`）。**先 FK 再退路**：

    ```
    ① sales_person_id -> users.username     可靠（FK）
    ② 解不出：users.display_name == sales_person_name AND active=1   退路
       ⚠️ 走到這裡留一筆 log，不要靜默——同名或改過名會查不到，
          而它不會報錯，那正是 `_m010` 踩過的坑（`QS1 §2`）。
    ```
    兩條都解不出回 `None`——呼叫端（`_case_people`）不落回顯示名，
    比照 `people_for_item()` 自己「查不到人就是沒有人，不是靜默退回一個
    不能拿去比對 username 的字串」那條規則。
    """
    if sales_person_id:
        row = conn.execute("SELECT username FROM users WHERE id = ?",
                           (sales_person_id,)).fetchone()
        if row and row["username"]:
            return row["username"]
    if sales_person_name:
        row = conn.execute(
            "SELECT username FROM users WHERE display_name = ? AND active = 1",
            (sales_person_name,)).fetchone()
        if row and row["username"]:
            logger.warning(
                "sales_person 帳號解析走退路（display_name 比對）：%r -> %r",
                sales_person_name, row["username"])
            return row["username"]
    return None


def _case_people(conn, quote_no):
    """把案件上的人彙整成 `people_for_item()` 吃得下的形狀。

    ⚠️ `case_stages.assigned_to` 是 **JSON text**（`db.py` 註解逐字：
       「刻意維持 JSON text 欄位，不再往下正規化成 join table」）
       ⇒ 彙整**不能用一句 SQL JOIN**，要在應用層逐筆解析。

    ## 🔴 施工圖 `§四` 列的四個來源裡，**有兩個沒有對應的欄位**

    實查（2026-09-23，`PRAGMA table_info`）：
    ```
    quotations.sales_person      ✅ 存在
    quotations.owner             🔴 **不存在**
    quotations.engineer          🔴 **不存在**
    case_stages.assigned_to      ✅ 存在
    ```
    ⇒ 寫死 `SELECT … owner, engineer` 會直接 `OperationalError`。
    ⚠️ 所以這裡**問資料庫有哪些欄再取**：日後真的加了 `owner`，
       這一支不必改就會跟上；而現在拿不到的那兩個會讓
       `people_for_item()` 回「無可發放對象」——**明著拒絕，不是靜默算 0**。
    📌 而「那兩個來源的獎金項目永遠發不出去」是一個**規格與現實的落差**，
       不是這一支要解的：已回報 A。

    ## 🔴 `QS1-a`：`sales_person` 這一格在這裡就解析成帳號

    `people_for_item()` 保持純函式（不吃 `conn`）——解析放在呼叫端
    （`SPEC-QS1-a §3①` 的「甲」案），`case["sales_person"]` 被**覆寫**
    成帳號，不是另外新增一個鍵：這支函式的兩個呼叫端都只把 `case` 餵給
    `people_for_item()`，沒有別的地方要顯示名。解不出時覆寫成 `None`——
    比照 `people_for_item()` 自己「沒有值 ⇒ 沒有人」的規則，不留一個
    查不到帳號的顯示名在裡面（那正是這支規格要修的洞）。
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(quotations)")}
    wanted = [c for c in ("quote_no", "sales_person", "sales_person_id",
                          "owner", "engineer") if c in cols]
    row = conn.execute(
        "SELECT %s FROM quotations WHERE quote_no = ?" % ", ".join(wanted),
        (quote_no,)).fetchone()
    case = dict(row) if row else {"quote_no": quote_no}
    case["stages"] = [dict(r) for r in conn.execute(
        "SELECT assigned_to FROM case_stages WHERE quote_no = ?", (quote_no,))]
    if "sales_person" in case:
        case["sales_person"] = _username_of_sales_person(
            conn, case.get("sales_person_id"), case.get("sales_person"))
    return case


# ══════════════════════════════════════════════════════════════════════════════
# 以案件為中心的獎金分潤（SPEC-BONUS §十一／§11.7，2026-09-24）
# ══════════════════════════════════════════════════════════════════════════════
#
# 表：bonus_case_awards／bonus_case_award_lines／bonus_case_award_edit_log（db.py v113）。
# 算式：helpers/bonus_case.py（純函式）。舊的 bonus_awards 流程不理會（§11.7「直接作廢」
# ⇒ 新頁面不顯示、不擋；不以 migration 作廢任何資料）。
#
#   已精算 ──建立──▶ 草稿 ──送審──▶ 待審核 ──簽核完成──▶ 待發放 ──出納標記──▶ 已發放
#                    ▲________ 最高管理者退回（已發放前任何時點）／簽核人駁回 ________|
#
# 「未精算／已精算」不存，依 settlement.status 推得。
# 可見性（§11.4 字面）：見 _case_award_view()。
# 簽核人只能是最高管理者（W1，使用者 2026-09-24「簽核人只能是最高管理者」）：
# 送審時鏈上（含有效代理人）出現非 superadmin 就擋；核准時再確認一次。

from helpers.bonus_case import (  # noqa: E402
    BonusCalcError, CATEGORIES, CATEGORY_LABELS, DEFAULT_RATE_BP, DEFAULT_SPLIT_BP, allocate,
)
from helpers.bonus import BASE_FIELD, LEGACY_SETTLEMENT_MESSAGE  # noqa: E402
from helpers.tiered_approval import (  # noqa: E402
    check_approve_permission, check_reject_permission, check_no_tier_self_approval,
)
from helpers.auth import user_has_module  # noqa: E402
from helpers import bonus_vouchers  # noqa: E402  `AC3`：狀態轉換 → 傳票草稿

_CASE_DEAL_TAGS = ("已成案", "已結案")
_RATE_KEY = "bonus_case_default_rate_bp"
_SPLIT_KEY = "bonus_case_default_split_bp"
_PAYOUT_VISIBLE = ("待發放", "已發放")
_SOURCES_OK = ("auto_sales", "auto_executor", "manual")


def _case_defaults():
    rate = _get_setting(_RATE_KEY, None)
    split = _get_setting(_SPLIT_KEY, None)
    if not isinstance(rate, int) or isinstance(rate, bool):
        rate = DEFAULT_RATE_BP
    if not isinstance(split, dict):
        split = dict(DEFAULT_SPLIT_BP)
    return rate, {c: split.get(c, 0) for c in CATEGORIES}


def _unique_username_by_display(conn, display_name):
    """顯示名稱 → 帳號。**剛好一個**在職帳號才算；同名或查無回 None（§11.7：不帶、標「請手動指定」）。"""
    name = (display_name or "").strip()
    if not name:
        return None
    rows = conn.execute(
        "SELECT username FROM users WHERE display_name = ? AND active = 1", (name,)).fetchall()
    return rows[0]["username"] if len(rows) == 1 else None


def _auto_members(conn, quote_no):
    """§11.7：業務＝quotations.sales_person；專案＝caseRecord.roles.executor；後勤不自動帶。
    回 (members, notes)。解不出（同名／查無）⇒ 不帶，notes 說明要手動指定。"""
    row = conn.execute(
        "SELECT sales_person, sales_person_id,"
        " json_extract(data_json, '$.caseRecord.roles.executor') AS executor"
        " FROM quotations WHERE quote_no = ?", (quote_no,)).fetchone()
    members = {c: [] for c in CATEGORIES}
    notes = {}
    if row is None:
        return members, notes
    sales_user = None
    if row["sales_person_id"]:
        r = conn.execute("SELECT username FROM users WHERE id = ? AND active = 1",
                         (row["sales_person_id"],)).fetchone()
        sales_user = r["username"] if r else None
    if not sales_user:
        sales_user = _unique_username_by_display(conn, row["sales_person"])
    if sales_user:
        members["sales"].append({"username": sales_user, "person_bp": None, "source": "auto_sales"})
    else:
        notes["sales"] = ("報價單業務人員「%s」對不到唯一的帳號，請手動指定" % (row["sales_person"] or "")
                          if row["sales_person"] else "報價單沒有業務人員，請手動指定")
    exe_user = _unique_username_by_display(conn, row["executor"])
    if exe_user:
        members["project"].append({"username": exe_user, "person_bp": None, "source": "auto_executor"})
    else:
        notes["project"] = ("案件「執行負責」「%s」對不到唯一的帳號，請手動指定" % row["executor"]
                            if row["executor"] else "案件沒有設定「執行負責」，請手動指定")
    notes["admin"] = "後勤不自動帶入，請手動指定人員或群組"
    return members, notes


def _case_row(conn, quote_no):
    row = conn.execute(
        "SELECT quote_no, customer_name, project_name, deal_tag FROM quotations WHERE quote_no = ?",
        (quote_no,)).fetchone()
    if row is None:
        raise HTTPException(404, "找不到這個案件。")
    return dict(row)


def _net_profit_or_error(settle):
    """（ok, net, err）。§二禁令：只用 settlement.summary.netProfit 已存值，不重算、不退回 grossProfit。"""
    if not settle or settle.get("status") != "finalized":
        return False, None, "這個案件尚未完成精算，不能建立獎金分潤。"
    raw = (settle.get("summary") or {}).get(BASE_FIELD)
    if raw is None:
        return False, None, LEGACY_SETTLEMENT_MESSAGE
    return True, raw, None


def _load_case_award(conn, quote_no):
    row = conn.execute("SELECT * FROM bonus_case_awards WHERE quote_no = ?", (quote_no,)).fetchone()
    if row is None:
        return None, []
    award = dict(row)
    lines = [dict(r) for r in conn.execute(
        "SELECT * FROM bonus_case_award_lines WHERE award_id = ? ORDER BY id", (award["id"],))]
    return award, lines


def _case_log(conn, award_id, user, action, changes):
    conn.execute(
        "INSERT INTO bonus_case_award_edit_log (award_id, changed_by, changed_at, action, changes_json)"
        " VALUES (?,?,?,?,?)",
        (award_id, _user_name(user), datetime.now().isoformat(), action,
         json.dumps(changes, ensure_ascii=False)))


_ONLY_SUPERADMIN_MSG = "獎金分潤的簽核人只能是最高管理者，請調整簽核設定。"


def _non_superadmin_in_chain(conn, tiers):
    """鏈上的簽核人，以及他們今天有效的代理人，是否有人不是 superadmin。回違規的帳號清單。"""
    from datetime import date
    today = date.today().isoformat()
    bad = []
    for t in tiers or []:
        for a in (t or {}).get("approvers") or []:
            uname = a.get("username") or ""
            names = [uname] + [r["delegate_username"] for r in conn.execute(
                "SELECT delegate_username FROM approval_delegates WHERE delegator_username=? AND active=1"
                " AND start_date<=? AND end_date>=?", (uname, today, today))]
            for n in names:
                r = conn.execute("SELECT role FROM users WHERE username=?", (n,)).fetchone()
                if r is None or r["role"] != "superadmin":
                    bad.append(n)
    return bad


def _case_award_view(conn, award, lines, user):
    """依身分決定回多少（過濾在後端，§七／§11.4 字面）。

    superadmin                         整張
    待發放／已發放＋出納模組持有者（C1）   整張的每人金額、合計、尾差；**不含**淨利、比率、個人比例、獎金池
    待發放／已發放＋名單上的人             **只有自己那幾列**（金額＋比例），不含淨利、獎金池、別人
    其他                                 None（當作不存在）
    （簽核人只能是 superadmin，W1 (c)，所以不需要「簽核人可見」這一格。）
    C1：使用者「待發放／已發放的整張，不含淨利與比率」——出納要照著發錢，看不到就發不了。
    """
    if _sees_all_lines(user):
        return {"award": award, "lines": lines, "scope": "all"}
    uname = _user_name(user)
    if award["status"] in _PAYOUT_VISIBLE and user_has_module(user, "cashier"):
        slim = {k: award[k] for k in ("id", "quote_no", "status", "paid_at", "paid_by")}
        paid = sum(l["amount"] for l in lines)
        stripped = [{k: l[k] for k in ("id", "category", "username", "display_name_snapshot", "amount")}
                    for l in lines]
        return {"award": slim, "lines": stripped, "scope": "cashier",
                "summary": {"paidTotal": paid, "remainder": award["pool_amount"] - paid}}
    if award["status"] in _PAYOUT_VISIBLE:
        mine = [l for l in lines if l["username"] == uname]
        if mine:
            slim = {k: award[k] for k in ("id", "quote_no", "status", "paid_at")}
            return {"award": slim, "lines": mine, "scope": "self"}
    return None


def _derive_status(settle, award):
    if award:
        return award["status"]
    return "已精算" if (settle or {}).get("status") == "finalized" else "未精算"


def _members_from_lines(lines):
    out = {c: [] for c in CATEGORIES}
    for l in lines:
        out[l["category"]].append({"username": l["username"], "person_bp": l["person_bp"],
                                   "source": l["source"]})
    return out


def _normalize_members(conn, raw):
    """草稿送來的名單 → {cat: [{username, person_bp, source}]}；帳號必須存在且在職。"""
    if not isinstance(raw, dict):
        raise HTTPException(400, "名單格式不正確。")
    out = {c: [] for c in CATEGORIES}
    for c in CATEGORIES:
        people = raw.get(c) or []
        if not isinstance(people, list):
            raise HTTPException(400, "名單格式不正確。")
        for p in people:
            if not isinstance(p, dict) or not isinstance(p.get("username"), str) or not p["username"].strip():
                raise HTTPException(400, "名單格式不正確。")
            uname = p["username"].strip()
            if conn.execute("SELECT 1 FROM users WHERE username = ? AND active = 1", (uname,)).fetchone() is None:
                raise HTTPException(400, "「%s」不是在職的帳號。" % uname)
            src = p.get("source") or "manual"
            if not (src in _SOURCES_OK or (isinstance(src, str) and src.startswith("group:"))):
                src = "manual"
            bp = p.get("person_bp")
            out[c].append({"username": uname, "person_bp": bp, "source": src})
    return out


def _write_lines(conn, award_id, members, result):
    conn.execute("DELETE FROM bonus_case_award_lines WHERE award_id = ?", (award_id,))
    names = {r["username"]: r["display_name"] for r in conn.execute(
        "SELECT username, COALESCE(display_name, '') AS display_name FROM users")}
    for c in CATEGORIES:
        for p, l in zip(members[c], result["categories"][c]["lines"]):
            conn.execute(
                "INSERT INTO bonus_case_award_lines (award_id, category, username, display_name_snapshot,"
                " source, person_bp, amount) VALUES (?,?,?,?,?,?,?)",
                (award_id, c, p["username"], names.get(p["username"], ""), p["source"],
                 p["person_bp"], l["amount"]))


def _calc_or_400(net, rate_bp, split, members):
    try:
        return allocate(net, rate_bp, split, members)
    except BonusCalcError as e:
        raise HTTPException(400, str(e))


def _summary(award, lines):
    """整張單的衍生數字（只給看得到整張的人）。"""
    paid = sum(l["amount"] for l in lines)
    return {"poolAmount": award["pool_amount"], "paidTotal": paid,
            "remainder": award["pool_amount"] - paid}


@router.get("/cases/settings")
def get_case_bonus_settings(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    rate, split = _case_defaults()
    return {"rate_bp": rate, "split_bp": split}


@router.put("/cases/settings")
def put_case_bonus_settings(body: dict = Body(...), authorization: str = Header(None)):
    """全域預設（§11.2：比率 10%、三類 50／30／20），只有最高管理者能改；草稿可逐案覆寫。"""
    user = _require_user(authorization, require_superadmin=True)
    rate = (body or {}).get("rate_bp")
    split = (body or {}).get("split_bp") or {}
    try:
        allocate(1, rate, split, {})
    except BonusCalcError as e:
        if "不大於 0" not in str(e):
            raise HTTPException(400, str(e))
    from helpers.settings import _set_setting
    _set_setting(_RATE_KEY, rate)
    _set_setting(_SPLIT_KEY, {c: split.get(c, 0) for c in CATEGORIES})
    _audit(_tok(authorization), "bonus.case.settings", "settings", "bonus_case_defaults",
           "獎金分潤預設：比率 %s、業務／專案／後勤 %s" % (_pct_text(rate), "／".join(
               _pct_text(split.get(c, 0)) for c in CATEGORIES)))
    return {"ok": True}


def _payout_bank_choices(award):
    """`AC3`：待發放時給出納選付款銀行（支出傳票草稿的貸方）。

    清單沿用 T100 設定頁維護的 bankAccounts（出納頁同一份）。⚠️ 不叫前端去打
    `/api/settings/t100-export-config`：那支只給 admin+，非 admin 的出納會 403、選單變空的。
    這裡只帶名稱與科目代號（不含設定頁其他內容）。
    """
    if award.get("status") != "待發放":
        return {}
    from routers.accounting_export import _t100_config
    cfg = _t100_config()
    return {"bankAccounts": [{"name": b.get("name") or "", "acctCode": b.get("acctCode") or ""}
                             for b in (cfg.get("bankAccounts") or []) if b.get("acctCode")],
            "defaultBankAccountCode": cfg.get("defaultBankAccountCode") or ""}


@router.get("/cases/voucher-accounts")
def get_case_bonus_voucher_accounts(authorization: str = Header(None)):
    """`AC3`：獎金分潤產生傳票時用的科目（不寫死；預設 6111／2191／2252／1113）。
    已存的值若後來被停用 ⇒ `problems` 明著列出，要求重選（不靜默失效）。"""
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        acc = bonus_vouchers.configured_accounts(conn)
        problems = {k: bonus_vouchers.account_problem(conn, v) for k, v in acc.items()}
    finally:
        conn.close()
    return {"accounts": acc, "problems": {k: v for k, v in problems.items() if v},
            "labels": {k: v[2] for k, v in bonus_vouchers.ACCOUNT_SLOTS.items()}}


@router.put("/cases/voucher-accounts")
def put_case_bonus_voucher_accounts(body: dict = Body(...), authorization: str = Header(None)):
    """只改有給的鍵；任何一個不存在或已停用 ⇒ 400，**一個都不寫**。"""
    _require_user(authorization, require_superadmin=True)
    body = body or {}
    changes = {k: (body.get(k) if isinstance(body.get(k), str) else "").strip()
               for k in bonus_vouchers.ACCOUNT_SLOTS if k in body}
    if not changes:
        raise HTTPException(400, "沒有要修改的科目。")
    conn = get_db()
    try:
        problems = ["%s：%s" % (bonus_vouchers.ACCOUNT_SLOTS[k][2], bonus_vouchers.account_problem(conn, v))
                    for k, v in changes.items() if bonus_vouchers.account_problem(conn, v)]
    finally:
        conn.close()
    if problems:
        raise HTTPException(400, "；".join(problems))
    from helpers.settings import _set_setting
    for k, v in changes.items():
        _set_setting(bonus_vouchers.ACCOUNT_SLOTS[k][0], v)
    _audit(_tok(authorization), "bonus.case.voucher_accounts", "settings", "bonus_case_voucher_accounts",
           "獎金分潤傳票科目：%s" % "、".join("%s=%s" % (bonus_vouchers.ACCOUNT_SLOTS[k][2], v)
                                        for k, v in changes.items()))
    return {"ok": True}


@router.get("/cases")
def list_case_bonuses(status: str = "", q: str = "", authorization: str = Header(None)):
    """左側案件清單。最高管理者看全部；其他人只看得到「自己在名單上、而且已到待發放」的案件
    （以及 W1：待審核且自己在簽核鏈上的案件）。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT quote_no, customer_name, project_name, deal_tag,"
            " json_extract(data_json, '$.settlement') AS s FROM quotations"
            " WHERE deal_tag IN (?, ?) ORDER BY quote_no DESC", _CASE_DEAL_TAGS)]
        awards = {r["quote_no"]: dict(r) for r in conn.execute("SELECT * FROM bonus_case_awards")}
        lines_by = {}
        for r in conn.execute("SELECT * FROM bonus_case_award_lines ORDER BY id"):
            lines_by.setdefault(r["award_id"], []).append(dict(r))
        items = []
        needle = (q or "").strip().lower()
        for r in rows:
            try:
                settle = json.loads(r["s"]) if isinstance(r["s"], str) and r["s"] else (r["s"] or {})
            except (TypeError, ValueError):
                settle = {}
            award = awards.get(r["quote_no"])
            st = _derive_status(settle, award)
            view = None
            if award:
                view = _case_award_view(conn, award, lines_by.get(award["id"], []), user)
                if view is None and not _sees_all_lines(user):
                    continue
            elif not _sees_all_lines(user):
                continue
            if status and st != status:
                continue
            if needle and not any(needle in (r.get(k) or "").lower()
                                  for k in ("quote_no", "customer_name", "project_name")):
                continue
            ok, net, _err = _net_profit_or_error(settle)
            item = {"quote_no": r["quote_no"], "customer_name": r["customer_name"] or "",
                    "project_name": r["project_name"] or "", "status": st}
            if _sees_all_lines(user):
                item["noBonus"] = bool(ok and not award and float(net) <= 0)
            if view and view["scope"] == "self":
                item["myAmount"] = sum(l["amount"] for l in view["lines"])
            if view and view["scope"] == "cashier":
                item["paidTotal"] = view["summary"]["paidTotal"]
            items.append(item)
    finally:
        conn.close()
    return {"items": items}


@router.get("/cases/{quote_no}")
def get_case_bonus(quote_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        case = _case_row(conn, quote_no)
        settle = _settlement_of(conn, quote_no) or {}
        award, lines = _load_case_award(conn, quote_no)
        full = _sees_all_lines(user)
        if award is None:
            if not full:
                raise HTTPException(404, "找不到這個案件的獎金分潤。")
            ok, net, err = _net_profit_or_error(settle)
            members, notes = _auto_members(conn, quote_no)
            rate, split = _case_defaults()
            preview = None
            if ok and float(net) > 0:
                preview = _calc_or_400(net, rate, split, {c: [{"username": m["username"], "person_bp": None}
                                                              for m in members[c]] for c in CATEGORIES})
            return {"case": case, "status": _derive_status(settle, None), "scope": "all",
                    "netProfit": net, "canCreate": bool(ok and float(net) > 0),
                    "reason": err or ("" if not ok or float(net) > 0 else "淨利不大於 0，無獎金"),
                    "defaults": {"rate_bp": rate, "split_bp": split},
                    "autoMembers": members, "memberNotes": notes, "preview": preview}
        view = _case_award_view(conn, award, lines, user)
        if view is None:
            raise HTTPException(404, "找不到這個案件的獎金分潤。")
        out = {"case": case, "status": award["status"], "scope": view["scope"], "lines": view["lines"]}
        if view["scope"] == "cashier":
            out["award"] = view["award"]
            out["summary"] = view["summary"]
            out["vouchers"] = bonus_vouchers.linked_vouchers(conn, award)   # `AC3`
            out.update(_payout_bank_choices(award))
        elif view["scope"] != "self":
            a = dict(award)
            a["split_bp"] = json.loads(a.pop("split_json") or "{}")
            a["approval"] = json.loads(a.pop("approval_json") or "{}")
            out["award"] = a
            out["summary"] = _summary(award, lines)
            out["vouchers"] = bonus_vouchers.linked_vouchers(conn, award)   # `AC3`
            out.update(_payout_bank_choices(award))
            if full:
                out["log"] = [dict(r) for r in conn.execute(
                    "SELECT changed_by, changed_at, action, changes_json FROM bonus_case_award_edit_log"
                    " WHERE award_id = ? ORDER BY id", (award["id"],))]
        else:
            out["award"] = view["award"]
    finally:
        conn.close()
    out["categoryLabels"] = CATEGORY_LABELS
    return out


@router.post("/cases/{quote_no}")
def create_case_bonus(quote_no: str, body: dict = Body(default={}), authorization: str = Header(None)):
    """建立草稿（最高管理者）。名單預設自動帶入（§11.7）；body 可帶 members 覆蓋。"""
    user = _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _case_row(conn, quote_no)
        if conn.execute("SELECT 1 FROM bonus_case_awards WHERE quote_no = ?", (quote_no,)).fetchone():
            raise HTTPException(409, "這個案件已經有獎金分潤單。")
        ok, net, err = _net_profit_or_error(_settlement_of(conn, quote_no) or {})
        if not ok:
            raise HTTPException(400, err)
        rate, split = _case_defaults()
        body = body or {}
        rate = body.get("rate_bp", rate)
        split = body.get("split_bp", split)
        if "members" in body:
            members = _normalize_members(conn, body["members"])
        else:
            members, _notes = _auto_members(conn, quote_no)
        result = _calc_or_400(net, rate, split, members)
        now = datetime.now().isoformat()
        uname = _user_name(user)
        cur = conn.execute(
            "INSERT INTO bonus_case_awards (quote_no, status, net_profit, rate_bp, split_json, pool_amount,"
            " created_by, created_at, updated_by, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "草稿", str(net), rate, json.dumps(split), result["pool"], uname, now, uname, now))
        award_id = cur.lastrowid
        _write_lines(conn, award_id, members, result)
        _case_log(conn, award_id, user, "create",
                  {"net_profit": str(net), "rate_bp": rate, "split_bp": split, "pool": result["pool"]})
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "bonus.case.create", "bonus_case_awards", quote_no, "建立獎金分潤草稿")
    return {"ok": True, "status": "草稿"}


@router.put("/cases/{quote_no}")
def update_case_bonus(quote_no: str, body: dict = Body(...), authorization: str = Header(None)):
    """編輯草稿：比率、三類比例、名單與個人比例。淨利快照在草稿期間每次存檔重讀。"""
    user = _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        award, lines = _load_case_award(conn, quote_no)
        if award is None:
            raise HTTPException(404, "這個案件還沒有獎金分潤單。")
        if award["status"] != "草稿":
            raise HTTPException(409, "只有草稿可以編輯，這一張現在是「%s」。" % award["status"])
        ok, net, err = _net_profit_or_error(_settlement_of(conn, quote_no) or {})
        if not ok:
            raise HTTPException(400, err)
        body = body or {}
        rate = body.get("rate_bp", award["rate_bp"])
        split = body.get("split_bp", json.loads(award["split_json"] or "{}"))
        members = _normalize_members(conn, body["members"]) if "members" in body else _members_from_lines(lines)
        result = _calc_or_400(net, rate, split, members)
        before = {"net_profit": award["net_profit"], "rate_bp": award["rate_bp"],
                  "split_bp": json.loads(award["split_json"] or "{}"),
                  "members": {c: [(p["username"], p["person_bp"]) for p in _members_from_lines(lines)[c]]
                              for c in CATEGORIES}}
        after = {"net_profit": str(net), "rate_bp": rate, "split_bp": split,
                 "members": {c: [(p["username"], p["person_bp"]) for p in members[c]] for c in CATEGORIES}}
        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE bonus_case_awards SET net_profit=?, rate_bp=?, split_json=?, pool_amount=?,"
            " updated_by=?, updated_at=? WHERE id=?",
            (str(net), rate, json.dumps(split), result["pool"], _user_name(user), now, award["id"]))
        _write_lines(conn, award["id"], members, result)
        changes = [{"field": k, "old": before[k], "new": after[k]} for k in before if before[k] != after[k]]
        if changes:
            _case_log(conn, award["id"], user, "edit", changes)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "bonus.case.update", "bonus_case_awards", quote_no, "獎金分潤編輯")
    return {"ok": True}


@router.post("/cases/{quote_no}/submit")
def submit_case_bonus(quote_no: str, authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        award, lines = _load_case_award(conn, quote_no)
        if award is None:
            raise HTTPException(404, "這個案件還沒有獎金分潤單。")
        if award["status"] != "草稿":
            raise HTTPException(409, "只有草稿可以送審，這一張現在是「%s」。" % award["status"])
        if not lines:
            raise HTTPException(400, "名單是空的，不能送審。")
        scope = _get_setting("approval_flow_scope", {}) or {}
        flow = _get_setting(approval_flow_setting_key("bonus", scope), None)
        tiers = []
        if flow is not None:
            try:
                tiers = setting_to_active_tiers(flow, conn, user["username"])
            except UnresolvedManagerError as exc:
                raise HTTPException(400, str(exc))
        bad = _non_superadmin_in_chain(conn, tiers)
        if bad:
            raise HTTPException(400, _ONLY_SUPERADMIN_MSG + "（非最高管理者：%s）" % "、".join(dict.fromkeys(bad)))
        appr = {"tiers": tiers, "currentTier": 0, "requestedBy": user["username"],
                "requestedAt": datetime.now().isoformat()}
        conn.execute("UPDATE bonus_case_awards SET status='待審核', approval_json=?, updated_by=?, updated_at=?"
                     " WHERE id=?", (json.dumps(appr, ensure_ascii=False), _user_name(user),
                                     datetime.now().isoformat(), award["id"]))
        _case_log(conn, award["id"], user, "submit", {"tiers": len(tiers)})
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "bonus.case.submit", "bonus_case_awards", quote_no, "獎金分潤送審")
    return {"ok": True, "status": "待審核"}


@router.post("/cases/{quote_no}/approve")
def approve_case_bonus(quote_no: str, authorization: str = Header(None)):
    """走共用簽核引擎：有鏈 ⇒ 當層簽核人（或代理人）；沒鏈 ⇒ superadmin，且不可自簽（唯一最高管理者例外）。
    簽完最後一層 ⇒ 待發放。簽核人只能是最高管理者（W1）⇒ 操作者本身也必須是 superadmin。"""
    user = _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        award, _lines = _load_case_award(conn, quote_no)
        if award is None or award["status"] != "待審核":
            raise HTTPException(409, "這張獎金分潤不在簽核流程裡。")
        appr = json.loads(award["approval_json"] or "{}") or {}
        tiers = appr.get("tiers") or []
        now = datetime.now().isoformat()
        if tiers:
            ct = int(appr.get("currentTier") or 0)
            ok, code, msg = check_approve_permission(tiers, ct, user["username"], conn)
            if not ok:
                raise HTTPException(code, msg)
            for a in tiers[ct].get("approvers") or []:
                if not a.get("approvedAt"):
                    a["approvedAt"] = now
                    a["approvedBy"] = _user_name(user)
                    break
            appr["currentTier"] = ct + 1
            nxt = "待發放" if ct + 1 >= len(tiers) else "待審核"
        else:
            if user.get("role") != "superadmin":
                raise HTTPException(403, "僅超級管理員可執行此操作")
            err = check_no_tier_self_approval(conn, appr, user)
            if err:
                raise HTTPException(403, err)
            appr["approvedBy"], appr["approvedAt"] = _user_name(user), now
            nxt = "待發放"
        conn.execute("UPDATE bonus_case_awards SET status=?, approval_json=?, updated_by=?, updated_at=?"
                     " WHERE id=?", (nxt, json.dumps(appr, ensure_ascii=False), _user_name(user), now,
                                     award["id"]))
        _case_log(conn, award["id"], user, "approve", {"status": nxt})
        voucher, notice = None, ""
        if nxt == "待發放":
            # `AC3`（§11.8）：進入待發放 ⇒ 轉帳傳票草稿（借 費用／貸 應付）；科目有問題只提示、不擋簽核
            voucher, notice = bonus_vouchers.create_accrual(conn, award, _user_name(user), now)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "bonus.case.approve", "bonus_case_awards", quote_no, "獎金分潤簽核：%s" % nxt)
    if voucher:
        _audit(_tok(authorization), "voucher.create", "vouchers", str(voucher["id"]),
               "獎金分潤 %s 進入待發放，產生傳票草稿：%s" % (quote_no, voucher["voucher_no"]))
    return {"ok": True, "status": nxt, "voucher": voucher, "notice": notice}


def _back_to_draft(conn, award, user, action, reason):
    conn.execute("UPDATE bonus_case_awards SET status='草稿', approval_json='{}', updated_by=?, updated_at=?"
                 " WHERE id=?", (_user_name(user), datetime.now().isoformat(), award["id"]))
    _case_log(conn, award["id"], user, action,
              {"from": award["status"], "reason": reason, "approval_before": award["approval_json"]})


@router.post("/cases/{quote_no}/reject")
def reject_case_bonus(quote_no: str, body: dict = Body(default={}), authorization: str = Header(None)):
    """簽核人駁回（待審核）⇒ 回草稿。當層簽核人／代理人或 superadmin（check_reject_permission）；
    簽核人只能是最高管理者（W1）⇒ 操作者本身也必須是 superadmin。"""
    user = _require_user(authorization, require_superadmin=True)
    reason = ((body or {}).get("reason") or "").strip()
    if not reason:
        raise HTTPException(400, "請填寫駁回原因。")
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        award, _lines = _load_case_award(conn, quote_no)
        if award is None or award["status"] != "待審核":
            raise HTTPException(409, "這張獎金分潤不在簽核流程裡。")
        appr = json.loads(award["approval_json"] or "{}") or {}
        tiers = appr.get("tiers") or []
        ok, code, msg = check_reject_permission(tiers, int(appr.get("currentTier") or 0), user, conn)
        if not ok:
            raise HTTPException(code, msg)
        _back_to_draft(conn, award, user, "reject", reason)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "bonus.case.reject", "bonus_case_awards", quote_no, "獎金分潤駁回：%s" % reason)
    return {"ok": True, "status": "草稿"}


@router.post("/cases/{quote_no}/return")
def return_case_bonus(quote_no: str, body: dict = Body(default={}), authorization: str = Header(None)):
    """最高管理者退回（已發放前任何時點）⇒ 草稿，留紀錄。已發放後不可退回（§11.4）。"""
    user = _require_user(authorization, require_superadmin=True)
    reason = ((body or {}).get("reason") or "").strip()
    if not reason:
        raise HTTPException(400, "請填寫退回原因。")
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        award, _lines = _load_case_award(conn, quote_no)
        if award is None:
            raise HTTPException(404, "這個案件還沒有獎金分潤單。")
        if award["status"] == "已發放":
            raise HTTPException(409, "已發放的獎金分潤不可以退回。")
        if award["status"] == "草稿":
            raise HTTPException(409, "這張已經是草稿。")
        _back_to_draft(conn, award, user, "return", reason)
        # `AC3`：待發放時產生的轉帳草稿——還沒送審 ⇒ 作廢；已送審 ⇒ 不動、提示
        voided_no, notice = bonus_vouchers.withdraw_accrual(
            conn, award, _user_name(user), datetime.now().isoformat(), reason)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "bonus.case.return", "bonus_case_awards", quote_no, "獎金分潤退回：%s" % reason)
    if voided_no:
        _audit(_tok(authorization), "voucher.void", "vouchers", voided_no,
               "獎金分潤 %s 退回，作廢未送審的傳票草稿：%s" % (quote_no, voided_no))
    return {"ok": True, "status": "草稿", "notice": notice}


@router.post("/cases/{quote_no}/mark-paid")
def mark_case_bonus_paid(quote_no: str, body: dict = Body(default={}), authorization: str = Header(None)):
    """出納標記已發放（出納模組持有者；superadmin 本來就持有全部模組）。記日期與操作者。

    `AC3`：同時產生支出傳票草稿；`bank_account_code` 可選（出納選哪一個銀行），
    沒給 ⇒ 用獎金設定的銀行科目。給了而無效 ⇒ 400，**狀態不變**。"""
    user = _require_user(authorization)
    if user.get("role") != "superadmin" and not user_has_module(user, "cashier"):
        raise HTTPException(403, "只有出納可以標記已發放。")
    bank = ((body or {}).get("bank_account_code") or "").strip()
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        award, _lines = _load_case_award(conn, quote_no)
        if award is None or award["status"] != "待發放":
            raise HTTPException(409, "只有「待發放」的獎金分潤可以標記已發放。")
        if bank:
            err = bonus_vouchers.account_problem(conn, bank)
            if err:
                raise HTTPException(400, "銀行科目：%s" % err)
        now = datetime.now().isoformat()
        conn.execute("UPDATE bonus_case_awards SET status='已發放', paid_by=?, paid_at=?, updated_by=?,"
                     " updated_at=? WHERE id=?", (_user_name(user), now, _user_name(user), now, award["id"]))
        _case_log(conn, award["id"], user, "mark_paid", {"paid_at": now})
        voucher, notice = bonus_vouchers.create_payment(conn, award, _user_name(user), now, bank)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "bonus.case.mark_paid", "bonus_case_awards", quote_no, "獎金分潤標記已發放")
    if voucher:
        _audit(_tok(authorization), "voucher.create", "vouchers", str(voucher["id"]),
               "獎金分潤 %s 已發放，產生傳票草稿：%s" % (quote_no, voucher["voucher_no"]))
    return {"ok": True, "status": "已發放", "voucher": voucher, "notice": notice}
