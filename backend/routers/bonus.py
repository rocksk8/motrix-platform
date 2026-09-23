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
from fastapi.responses import Response

from db import get_db
from helpers import _require_user, _audit, _tok, _get_setting
from helpers.bonus import (
    base_amount_for, people_for_item, split_award, pool_for, remainder_of,
    visible_lines, PERSON_SOURCES, BASIS_POINTS,
    bonus_signatures_of, is_paid, BonusChainUnreadable, MAKER_SLOT,
    SETTLEMENT_FIELDS, settlement_fields,
)
from helpers.tiered_approval import (
    approval_flow_setting_key, setting_to_active_tiers, UnresolvedManagerError,
)
from helpers.bonus_pdf import can_export, export_award_pdf

router = APIRouter(prefix="/api/bonus", tags=["bonus"])


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
    admin       **只有自己那一列**（與一般同仁相同）—— 他仍然產生得了獎金單
    其他人       只有自己那一列
    ```
    ⚠️ `admin` 在這一頁是**一般使用者**，而他在別的頁不是 ——
       ☠️ 所以畫面不可以用同一個旗標同時決定「看得到什麼」與「按得到什麼」：
       他按得到「產生獎金單」，而他看不到別人的金額。
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


@router.post("/items")
def create_bonus_item(body: dict = Body(...), authorization: str = Header(None)):
    """新增獎金項目。

    🔴 `person_source` **為空不准儲存** —— 不是存了再算出 0 人。
    ☠️ 存得下去的話，那個項目**每次都算出 0 個人**，而畫面上它只是
       **從來沒有出現在任何一張獎金單上** —— 沒有人會發現一個從來不出現的東西。
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


def _case_names_for(conn, quote_nos):
    """`{quote_no}` 集合 -> `{quote_no: {customer_name, project_name}}`（`BN15`）。

    使用者原話：「獎金單的只有編號，沒有案件名稱」——`bonus_awards` 這張表
    本來就只存 `quote_no`（`db.py:4662`），而「產生獎金單」那個下拉選單早就
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
        live = conn.execute(
            "SELECT id FROM bonus_awards WHERE quote_no = ? AND voided_at = ''",
            (quote_no,)).fetchone()
    finally:
        conn.close()

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
    return {
        "quote_no": quote_no,
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
# 單一片語的路由，但 `BN10`——點開一張獎金單看完整內容——已經在排隊了）。
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
            # ④ 已有有效獎金單：優先於淨利判斷——就算這個案子現在淨利
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
    """獎金單清單。**分錄列依可見性過濾。**

    ⚠️ 非管理者也看得到**單**（否則他不知道自己那一筆屬於哪一案），
       而他只看得到**自己那一列**金額。
    ☠️ 反過來（整張單都不給看）的話，他收到一筆錢而查不到來源。

    🔴 `BN9`（2026-09-23）：「看得到全部」收緊成 **superadmin**。
       ⇒ `admin` 在這一頁與一般同仁相同（只看得到自己那一列），
         而他仍然**產生得了**獎金單 —— 見 `can_create_award`。
       ⚠️ 副作用要講出來：`admin` 產生了一張自己不在裡面的獎金單之後，
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
        # 🔑 **入口**（按得到「產生獎金單」嗎）——`admin` 這兩格答案不同。
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
    finally:
        conn.close()

    award["customer_name"] = cn.get("customer_name", "")
    award["project_name"] = cn.get("project_name", "")
    visible = visible_lines(lines, me, is_admin=manager)
    if not manager and not visible:
        # 🔴 與清單同一條：跟這個人無關的單，連整張單的存在都不透露——
        #    404 不是 403，不要洩漏「這張單存在，只是你看不到」。
        raise HTTPException(404, "找不到這張獎金分潤單。")

    award["lines"] = visible
    award["visible_total"] = sum(l["amount"] for l in visible)
    if not manager:
        award.pop("base_amount", None)
    award["signatures"] = bonus_signatures_of(award)
    award["settlement"] = _settlement_fields(settle)
    return award


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
        planned.append((item, total_pct, split_award(base, total_pct, pairs)))
    return settle, base, planned


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
    finally:
        conn.close()

    lines_out = []
    remainder = 0
    for item, total_pct, lines in planned:
        remainder += remainder_of(base, total_pct, lines)
        for ln in lines:
            lines_out.append({
                "bonus_item_id": item["id"],
                "username": ln["username"],
                "person_source_snapshot": item["person_source"],
                "total_pct": total_pct,
                "person_pct": ln["person_pct"],
                "amount": ln["amount"],
            })

    return {
        "quote_no": quote_no,
        "settlement": _settlement_fields(settle),
        "base": {"ok": True, "amount": base, "error": ""},
        "lines": lines_out,
        # `§6⑤`：尾差要印在表上——不印的話使用者自己加總會發現「對不起來」，
        # 而他不知道那是設計（歸公司，不補給任何人）。
        "remainder": remainder,
    }


@router.post("/awards/{award_id}/submit")
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


@router.post("/awards/{award_id}/approve")
def approve_award(award_id: int, body: dict = Body(default={}),
                  authorization: str = Header(None)):
    """簽核通過。逐層推進；簽完最後一層 -> 已核准。

    ## ⚠️ 沒有設定過簽核流程時，**沒有像傳票 `§161` 那樣的內建兩格 fallback**

    `SPEC-BN8.md §1`：獎金單一格投影欄位都沒有，比傳票乾淨。而三支端點
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


@router.post("/awards/{award_id}/reject")
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
    """
    user = _require_user(authorization, require_superadmin=True)
    now = datetime.now().isoformat()
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM bonus_awards WHERE id = ?",
                           (award_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "找不到這張獎金分潤單。")
        status = dict(row).get("status")
        if status not in ("待審核", "簽核中"):
            raise HTTPException(400, "「%s」的獎金分潤單不能退回。" % status)
        conn.execute(
            "UPDATE bonus_awards SET status='草稿', approval_json='{}',"
            " updated_at=? WHERE id=?", (now, award_id))
        conn.commit()
    finally:
        conn.close()
    reason = (body.get("reason") or "").strip()
    _audit(_tok(authorization), "bonus.award.reject", "bonus_awards",
           str(award_id), "獎金分潤單退回：%s" % (reason or "未填原因"))
    return {"ok": True, "status": "草稿"}


@router.post("/awards/{award_id}/mark-paid")
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


@router.post("/awards/{award_id}/void")
def void_award(award_id: int, body: dict = Body(default={}),
               authorization: str = Header(None)):
    """作廢一張獎金單。**原單留著**（與傳票同一條原則）。

    ☠️ 直接 DELETE 的話，帳上看不到那一次作廢 ——
       而使用者裁的是**作廢重開**，不是刪掉重來。

    🔴 `SPEC-BN8.md §6⑦⑧`（A 裁）：
    ```
    ⑦ 任何狀態都可以作廢，含已核准——不留出路的後果是「開錯了而改不掉」，
       權限同步改成 superadmin（與三支端點一致）
    ⑧ 已發放（is_paid()）的單，作廢不是一個旗標——錢已經出去了，
       只寫 voided_at 的後果是帳上那筆錢還在，而獎金單說它作廢了。
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
            raise HTTPException(404, "找不到這張獎金單。")
        award = dict(row)
        if award["voided_at"]:
            raise HTTPException(400, "這張獎金單已經作廢過了。")
        if is_paid(award):
            raise HTTPException(
                400, "這張獎金單已經發放，不能直接作廢——錢已經出去了，"
                     "請先開立沖銷傳票，沖銷完成後再處理這張單。")
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
