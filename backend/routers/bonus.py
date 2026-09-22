# -*- coding: utf-8 -*-
"""獎金分潤（`FN2`）—— 項目維護、產生獎金單、可見性。

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
from datetime import datetime

from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
from helpers import _require_user, _audit, _tok
from helpers.bonus import (
    base_amount_for, people_for_item, split_award, pool_for, remainder_of,
    visible_lines, PERSON_SOURCES,
)

router = APIRouter(prefix="/api/bonus", tags=["bonus"])


def _is_manager(user):
    """「管理者」＝ 看得到全部的人。

    ⚠️ 施工圖 `§十` 把「最高管理者是否沿用 superadmin」標為**未查**
       （A 🟡 預設沿用，未經使用者確認）⇒ 這裡把 `admin` 一起納入**讀**的範圍，
       而**維護項目**仍然只給 superadmin（見下）。
    🔑 讀與寫分開，是因為猜錯的代價不對稱：
       讀放寬一點 ⇒ 多一個人看得到；寫放寬 ⇒ 多一個人改得動獎金。
    """
    return user.get("role") in ("superadmin", "admin")

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



# ── 獎金項目（最高管理者維護）──────────────────────────────────────
@router.get("/items")
def list_bonus_items(authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM bonus_items ORDER BY sort_order, id")]
    finally:
        conn.close()
    return {"items": rows, "person_sources": list(PERSON_SOURCES),
            "can_edit": user.get("role") == "superadmin"}


@router.post("/items")
def create_bonus_item(body: dict = Body(...), authorization: str = Header(None)):
    """新增獎金項目。

    🔴 `person_source` **為空不准儲存** —— 不是存了再算出 0 人。
    ☠️ 存得下去的話，那個項目**每次都算出 0 個人**，而畫面上它只是
       **從來沒有出現在任何一張獎金單上** —— 沒有人會發現一個從來不出現的東西。
    ⚠️ 資料層的 `NOT NULL` 擋不住空字串，所以這一關是必要的另一半。
    """
    _require_user(authorization, require_superadmin=True)
    name = (body.get("name") or "").strip()
    source = (body.get("person_source") or "").strip()
    if not name:
        raise HTTPException(400, "請填寫獎金項目名稱。")
    if not source:
        raise HTTPException(400, "請選擇人員來源：沒有來源的項目永遠算不出發放對象。")
    if source not in PERSON_SOURCES:
        raise HTTPException(400, "不支援的人員來源「%s」。" % source)
    now = datetime.now().isoformat()
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO bonus_items (name, person_source, sort_order, is_active,"
            " created_by, created_at, updated_at) VALUES (?,?,?,1,?,?,?)",
            (name, source, int(body.get("sort_order") or 0),
             _user_name(user), now, now))
        conn.commit()
        new_id = cur.lastrowid
    finally:
        conn.close()
    _audit(_tok(authorization), "bonus.item.create", "bonus_items",
           str(new_id), "新增獎金項目：%s" % name)
    return {"ok": True, "id": new_id}


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


@router.get("/base/{quote_no}")
def get_bonus_base(quote_no: str, authorization: str = Header(None)):
    """這個案件現在算不算得出獎金基數。

    🔑 **先問再做**：畫面在按下「產生獎金單」之前就該知道答案，
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


# ── 獎金單 ────────────────────────────────────────────────────────
@router.get("/awards")
def list_awards(include_voided: bool = False, authorization: str = Header(None)):
    """獎金單清單。**分錄列依可見性過濾。**

    ⚠️ 非管理者也看得到**單**（否則他不知道自己那一筆屬於哪一案），
       而他只看得到**自己那一列**金額。
    ☠️ 反過來（整張單都不給看）的話，他收到一筆錢而查不到來源。
    """
    user = _require_user(authorization)
    me = user.get("username") or ""
    manager = _is_manager(user)
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
    finally:
        conn.close()

    out = []
    for a in awards:
        lines = visible_lines(by_award.get(a["id"], []), me, is_admin=manager)
        if not manager and not lines:
            # 🔴 與自己無關的單**完全不出現** —— `§七`「其他人看不到」。
            continue
        a["lines"] = lines
        # ⚠️ 非管理者看不到整張單的總額（那等於看得到別人領多少的總和）。
        a["visible_total"] = sum(l["amount"] for l in lines)
        if not manager:
            a.pop("base_amount", None)
        out.append(a)
    return {"awards": out, "is_manager": manager}


@router.post("/awards")
def create_award(body: dict = Body(...), authorization: str = Header(None)):
    """依案件產生一張獎金單（**套用當下凍結**）。

    ## 🔴 一個案件同時只能有一筆**有效**獎金

    靠的是 `v97` 的**部分**唯一索引（`WHERE voided_at = ''`）——
    ⇒ 重複產生會撞 `IntegrityError`，這裡把它翻成一句看得懂的話。

    ## ⚠️ 解析不出人的項目 **拒絕整張單**，不是跳過那一項

    ☠️ 跳過的兩個後果，第二個更糟：
    ```
    ① 那個項目從來沒出現在任何一張獎金單上（沒有人會發現）
    ② **把金額併給別的項目** => 別人領多了，而總額對得起來
    ```
    """
    user = _require_user(authorization)
    if not _is_manager(user):
        raise HTTPException(403, "僅管理員以上可產生獎金單。")
    quote_no = (body.get("quote_no") or "").strip()
    if not quote_no:
        raise HTTPException(400, "請指定案件編號。")
    allocations = body.get("allocations") or []
    if not allocations:
        raise HTTPException(400, "請至少設定一個獎金項目的比例。")

    conn = get_db()
    try:
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

        planned = []
        for alloc in allocations:
            item = items.get(int(alloc.get("bonus_item_id") or 0))
            if item is None:
                raise HTTPException(400, "獎金項目不存在或已停用。")
            good, people, note = people_for_item(item, case)
            if not good:
                raise HTTPException(400, "「%s」%s。" % (item["name"], note))
            total_pct = int(alloc.get("total_pct") or 0)
            shares = alloc.get("person_pct") or {}
            pairs = [(p, int(shares.get(p, 0))) for p in people]
            if sum(p[1] for p in pairs) <= 0:
                raise HTTPException(
                    400, "「%s」的人員比例全部是 0，無法發放。" % item["name"])
            planned.append((item, total_pct, split_award(base, total_pct, pairs)))

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
                    409, "案件「%s」已經有一張有效的獎金單。"
                         "若要重發，請先作廢原本那一張。" % quote_no)
            raise
        award_id = cur.lastrowid
        for item, total_pct, lines in planned:
            for ln in lines:
                conn.execute(
                    "INSERT INTO bonus_award_lines (award_id, bonus_item_id,"
                    " item_name_snapshot, username, person_source_snapshot,"
                    " total_pct, person_pct, amount) VALUES (?,?,?,?,?,?,?,?)",
                    (award_id, item["id"], item["name"], ln["username"],
                     item["person_source"], total_pct, ln["person_pct"],
                     ln["amount"]))
        conn.commit()
    finally:
        conn.close()

    _audit(_tok(authorization), "bonus.award.create", "bonus_awards",
           str(award_id), "產生獎金單：%s（基數 %s）" % (quote_no, f"{base:,}"))
    return {"ok": True, "id": award_id, "base_amount": base}


@router.post("/awards/{award_id}/void")
def void_award(award_id: int, body: dict = Body(default={}),
               authorization: str = Header(None)):
    """作廢一張獎金單。**原單留著**（與傳票同一條原則）。

    ☠️ 直接 DELETE 的話，帳上看不到那一次作廢 ——
       而使用者裁的是**作廢重開**，不是刪掉重來。
    """
    user = _require_user(authorization)
    if not _is_manager(user):
        raise HTTPException(403, "僅管理員以上可作廢獎金單。")
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
            raise HTTPException(404, "找不到這張獎金單。")
        if row["voided_at"]:
            raise HTTPException(400, "這張獎金單已經作廢過了。")
        conn.execute(
            "UPDATE bonus_awards SET voided_at = ?, voided_by = ?,"
            " void_reason = ?, updated_at = ? WHERE id = ?",
            (now, _user_name(user), reason, now, award_id))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "bonus.award.void", "bonus_awards",
           str(award_id), "作廢獎金單：%s" % reason)
    return {"ok": True}


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
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(quotations)")}
    wanted = [c for c in ("quote_no", "sales_person", "owner", "engineer")
              if c in cols]
    row = conn.execute(
        "SELECT %s FROM quotations WHERE quote_no = ?" % ", ".join(wanted),
        (quote_no,)).fetchone()
    case = dict(row) if row else {"quote_no": quote_no}
    case["stages"] = [dict(r) for r in conn.execute(
        "SELECT assigned_to FROM case_stages WHERE quote_no = ?", (quote_no,))]
    return case
