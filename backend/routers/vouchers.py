# -*- coding: utf-8 -*-
"""傳票（`FN4②` 的呼叫端）—— 讀一張、改草稿。

施工圖：`docs/windows/SPEC-VOUCHER.md`。

# 🔴 這一支存在的第一個理由：**讓 `append_edit_log()` 有人叫**

```
helpers/edit_log.py  規則寫好了、測試綠了
routers/vouchers.py  **不存在** => 沒有任何人在「改」的時候叫它
```
☠️ 〈兩個都對而路不存在〉：規則對、函式對、題目也對，**而它不會生效**。
🔑 而這種缺陷**讀規格看不出來** —— 規格說「改過要留痕」，函式也真的會留痕。

# ⚠️ 本輪只做「讀」與「改草稿」

過帳、送審、退回、作廢那幾條走 `helpers.voucher` 的純邏輯，
而它們的端點**沒有派工** ⇒ 不在這裡順手加。
"""
import datetime as _dt
import json
import os
from datetime import datetime

from fastapi import APIRouter, Body, Header, HTTPException, Request
from fastapi.responses import Response
from urllib.parse import quote

from db import get_db
# 🔑 科目代號的規則**只有一份** —— 借用既有那一支，不在這裡再寫。
#    （router 互相 import 在這個 repo 是既有做法，實查 7 處。）
from routers.accounting_export import validate_account_code
from helpers import _require_user, _tok, _audit, require_any_module
from helpers.edit_log import append_edit_log, MissingOldValue
from helpers.tiered_approval import (
    approval_flow_setting_key, setting_to_active_tiers,
    UnresolvedManagerError,
)
from helpers import _get_setting
from helpers.uploads import save_document_files
from helpers.voucher_pdf import export_voucher_pdf
from helpers.voucher_attachments import (
    resolve_picks, copy_into, abs_path, case_attachments,
    COPY_SOURCE_TYPE,
)
from helpers.voucher import (
    EDITABLE_STATUSES, can_edit, describe_balance, get_voucher,
    next_voucher_no, post_voucher, can_send_back, next_revision_no,
    diff_lines,
)

router = APIRouter(prefix="/api/vouchers", tags=["vouchers"])

#: 看得到傳票的人。傳票是會計憑證 ⇒ 與出納同一群受眾。
#:
#: 🔴 用 `require_any_module` 而**不是** `user["role"] in ("superadmin","admin")`：
#:    後者讓 admin 直通，而 2026-09-14 使用者裁示逐字是
#:    「管理者一樣依據有開權限的內容去顯示，沒開的就不顯示」
#:    ⇒ **只有 superadmin 直通**，admin 也必須真的持有模組。
#: ☠️ 而 `_require_user()` 單獨用是不夠的：那等於**任何登入者**都讀得到
#:    全公司的會計憑證，而畫面上看不出來 —— 側欄沒有入口不代表 API 擋得住。
_VOUCHER_MODULES = ("cashier", "finance")


def _require_voucher_access(user):
    require_any_module(user, _VOUCHER_MODULES, "傳票")

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


#: 草稿可以改的欄位。**白名單，不是黑名單。**
#:
#: ☠️ 黑名單的話，日後 DDL 加一欄就自動變成「可以改」——
#:    而沒有人會發現 `posted_by` 突然變得可以從前端改掉。
#: ⚠️ `voucher_no` **不在裡面**：它由退回升版產生，不是使用者填的。
EDITABLE_FIELDS = ("voucher_date", "category", "summary")



def _check_account_codes(conn, lines):
    """分錄的科目代號**必須指得到一個仍在使用中的科目**，否則回一句看得懂的 400。

    ## ☠️ 不擋的話它是 **500**

    ```
    voucher_lines.account_code  TEXT NOT NULL REFERENCES account_items(code)
    空字串 / 不存在的代號  =>  sqlite3.IntegrityError: FOREIGN KEY constraint failed
                          =>  未攔截 => **500**
    ```
    🔑 而 500 對使用者是「系統壞了」，對查的人是「去翻 log」——
       實際上那是一句「這一行還沒選科目」。

    ## 🔑 規則**借用既有那一份**，不在這裡再寫一次

    `routers.accounting_export.validate_account_code()` 已經定義了同一條規則，
    而且分得出「找不到」與「已停用」——兩者的下一步不同：
    ```
    找不到  打錯字
    已停用  那個科目還在，只是不該再用
    ```
    ☠️ 在這裡另寫一份的話，某一天停用規則改了而傳票這邊不會跟
       ⇒ **T100 匯出擋得住的代號，傳票存得進去**。
    📌 router 互相 import 在這個 repo 是既有做法（實查 7 處）。

    ## ⚠️ 它擋得住輸入，擋不住**時間**

    科目代號在寫入之後仍可能被改（`v96` 的 TRIGGER 擋的是「改掉已被引用的代號」）
    ⇒ 這一支只保證**寫入當下**那個代號是有效的。
    """
    problems = []
    for i, ln in enumerate(lines or (), start=1):
        code = (ln.get("account_code") or "").strip()
        if not code:
            # 🔑 空與「打錯」是兩件事，訊息也要分得出來：
            #    空 ＝ 還沒選；打錯 ＝ 選了一個不存在的。
            problems.append("第 %d 行還沒有選會計科目" % i)
            continue
        ok, err = validate_account_code(conn, code)
        if not ok:
            problems.append("第 %d 行：%s" % (i, err))
    if problems:
        raise HTTPException(400, "；".join(problems))



def _appr_of(row):
    """傳票的簽核鏈。**壞掉的 JSON 不要吞成空鏈** —— 那與「沒有設定」一模一樣。"""
    raw = (dict(row) if not isinstance(row, dict) else row).get("approval_json")
    if not raw:
        return {}
    try:
        return json.loads(raw) or {}
    except ValueError:
        raise HTTPException(400, "這張傳票的簽核資料格式不正確，無法繼續簽核。")


@router.post("")
def create_voucher(body: dict = Body(...), authorization: str = Header(None)):
    """建立一張**草稿**傳票（`JV1`）。

    ## 🔴 草稿**允許不平衡**

    使用者正在打，打到一半本來就不平。
    ☠️ 反過來擋的症狀是「**他打不完第一行就被擋住**」——
       而它看起來很嚴謹，所以不會有人覺得那是缺陷。
    ⇒ 借貸平衡是**過帳**那一關的事（`describe_balance`），不是建立這一關。

    ## ⚠️ 單號由後端發，而規則在 `helpers/voucher.py`

    `next_voucher_no()` 取那一天的**最大值 +1**（不是數幾筆）——
    理由見它的 docstring：作廢單留在表上，數筆數會撞號。
    🔑 而併發撞號由 `UNIQUE INDEX` 擋，這裡把它翻成一句人看得懂的話。
    """
    user = _require_user(authorization)
    _require_voucher_access(user)

    # 🔁 日期**可選，預設今天**（使用者 2026-09-23 改裁）——
    #    舊裁示「建檔當天且不可改」已被推翻，理由是月結補登是會計的日常。
    voucher_date = (body.get("voucher_date") or "").strip() or _dt.date.today().isoformat()
    lines = body.get("lines") or []
    now = _dt.datetime.now().isoformat()

    conn = get_db()
    try:
        # 🔑 **先驗再發號**：驗不過就丟例外，而 `next_voucher_no()` 取的是
        #    當天最大值 +1 —— 先發號再失敗的話那個號碼不會被用掉，
        #    但**下一張單會從它後面接**，帳上就少一個號碼而沒有人解釋得了。
        _check_account_codes(conn, lines)
        no = next_voucher_no(conn, voucher_date)
        try:
            cur = conn.execute(
                "INSERT INTO vouchers_all (voucher_no, voucher_date, category,"
                " summary, status, created_by, created_at, updated_at)"
                " VALUES (?,?,?,?, '草稿', ?,?,?)",
                (no, voucher_date, (body.get("category") or "轉"),
                 (body.get("summary") or ""), _user_name(user), now, now))
        except Exception as exc:                            # noqa: BLE001
            if "UNIQUE" in str(exc).upper():
                raise HTTPException(
                    409, "傳票號碼「%s」剛剛被別人用掉了，請再存一次。" % no)
            raise
        vid = cur.lastrowid
        for i, ln in enumerate(lines, start=1):
            conn.execute(
                "INSERT INTO voucher_lines (voucher_id, line_no, account_code,"
                " summary, debit, credit) VALUES (?,?,?,?,?,?)",
                (vid, i, (ln.get("account_code") or ""),
                 (ln.get("summary") or ""),
                 int(ln.get("debit") or 0), int(ln.get("credit") or 0)))
        conn.commit()
    finally:
        conn.close()

    _audit(_tok(authorization), "voucher.create", "vouchers", str(vid),
           "建立傳票草稿：%s" % no)
    return {"ok": True, "id": vid, "voucher_no": no, "status": "草稿"}


@router.get("")
def list_vouchers(include_voided: bool = False,
                  authorization: str = Header(None)):
    """傳票清單。

    ⚠️ 預設**只列有效的**（走 VIEW `vouchers`）——
       作廢單仍查得到（稽核），而要明著要（`include_voided`）。
    📌 清單**不帶分錄**：一次把幾百張單的分錄都撈回來，
       而畫面上那一層根本不顯示它們。
    """
    user = _require_user(authorization)
    _require_voucher_access(user)
    conn = get_db()
    try:
        # 🔑 有效的走 VIEW、要全部才打實表 —— 而不是自己再寫一次 WHERE：
        #    那個條件只該有一個地方寫著（`v95` 的 VIEW 定義）。
        src = "vouchers_all" if include_voided else "vouchers"
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM %s ORDER BY id DESC" % src)]
    finally:
        conn.close()
    return {"vouchers": rows, "count": len(rows)}


#: 摘要來源的兩個頁籤（`§159b` (7) 使用者原話：「摘要部分也要有分頁選單
#: 帶入案件跟哪些已上傳檔案」）。**可數完備**：少一個使用者會報修，
#: 而多一個**不會有人報修** —— 那表示有人加了來源而沒有人決定它的格式。
SUMMARY_TABS = ("案件", "已上傳檔案")

#: 清單長度上限。案件會一直長，而這是一個**選單**不是報表。
_SOURCE_LIMIT = 50


def case_summary(customer_name, quote_no):
    """案件來源帶入的那個字串（`§164`）。

    ```
    京城凱悅報價單MQ-202608-009
    ```

    ## 🔴 取不到的那一段**省略**，不是留一個洞

    `§164` 逐字：「取不到廠商或發票號的欄位就省略那一段，**不要填空字串佔位**」。
    ☠️ 填佔位的樣子很具體，而它**不會報錯**：
    ```
    「3/30  XV15543058」      <= 兩個空白（廠商是空的）
    「3/30 None XV15543058」  <= Python 的 %s
    「3/30 undefined …」      <= JS 的樣板字串
    ```
    ⇒ 使用者只會覺得「怎麼多一個空格」，然後手動刪掉，**每一張單都刪一次**。

    ## ⚠️ 省略的是**缺的那一段**，不是整個字串

    客戶取不到 ⇒ 仍然要帶得出報價單號那一段。
    ☠️ 整串變空的話，使用者點了來源而摘要欄沒反應 —— 那讀起來像「壞了」。

    ## 🔑 字串在**後端**組，不在 JS

    ```
    格式寫在 JS   => JV5 的 PDF 匯出讀不到它 => 兩邊會長不一樣
    格式寫在後端  => 兩邊同一個來源
    ```
    """
    parts = []
    name = (customer_name or "").strip()
    no = (quote_no or "").strip()
    if name:
        parts.append(name)
    if no:
        parts.append("報價單" + no)
    return "".join(parts)


# ══════════════════════════════════════════════════════════════════════
# 🔴 **這一支是靜態 GET 路徑，它必須宣告在下面那條 `/{voucher_id}` 之前。**
# ══════════════════════════════════════════════════════════════════════
# 📌 那不是假設：2026-09-23 這條路徑實測回 **422**，成因就是它當時宣告在
#    下面那條「路徑只有一段、而那一段是整數參數」的 GET 後面
#    ⇒ `summary-sources` 被當成那個整數參數去解析 ⇒ 參數驗證失敗。
# ⚠️ 這一段**刻意不寫出那條路由的字面值** —— 寫了的話，
#    「檢查宣告順序」的掃描器會把這行註解也算成一條路由（我剛踩過）。
# 🔑 **422 讀起來像「我參數傳錯了」，而實際是「這條路還沒做」** ——
#    查的人會去翻自己的呼叫端，而問題在這個檔案的行號順序上。
@router.get("/summary-sources")
def summary_sources(q: str = "", quote_no: str = "",
                    authorization: str = Header(None)):
    """摘要可以從哪些地方帶入（`JV7`）。

    ## ⚠️ 帶入是**起點不是終點**

    `§164`：那張實例 PDF 的三行摘要**沒有一行是同一個格式**，而三行裡兩行都有的
    「事由」**沒有來源可以帶** ⇒ 一定要手打。
    ⇒ 帶入只是**省打字** ⇒ 帶完之後那一格仍然要打得動，
      而最終值是**使用者打的那個**，不是來源 id 再組一次。
    ☠️ 存來源 id、開啟時重組的實作，症狀是「使用者改完、存檔、關掉；
       **下次打開才變回來**」—— 中間隔了幾天，他不會把兩件事連起來。

    ## 🔴 閘門與傳票其餘端點**同一道**

    這裡會列出**案件**（客戶名、報價單號）—— 那是業務資料不是傳票資料。
    ☠️ 閘門放鬆的話，等於**從一個記帳畫面繞過去看客戶清單**。

    ## 📌 頁籤②「已上傳檔案」現在是空的，而它**要出現**

    附件表屬於 `JV3`，還沒建（實查：106 張表裡沒有 attachments／uploads／files）。
    ⚠️ 不回這個頁籤的話，畫面上就少一個選項，而**沒有人會發現一個從來不出現的東西**；
       ⇒ 回一個空清單 ＋ 一句「為什麼是空的」，讓它是**看得見的未完成**。
    """
    _require_voucher_access(_require_user(authorization))
    like = "%" + (q or "").strip() + "%"
    conn = get_db()
    try:
        # ⚠️ 只取要用的四欄，**不要 `SELECT *`** —— `quotations` 有 data_json
        #    那種整包欄位，而下一個人加欄位時不會回來看這支端點回給誰。
        rows = [dict(r) for r in conn.execute(
            "SELECT quote_no, customer_name, project_name, status"
            " FROM quotations WHERE quote_no LIKE ? OR customer_name LIKE ?"
            " ORDER BY id DESC LIMIT ?", (like, like, _SOURCE_LIMIT))]
    finally:
        conn.close()

    # ── 頁籤②：這個案件底下可帶入的憑證（`JV3` 與 `JV7` 共用同一支端點）──
    files = []
    note2 = "請先選一個案件，才看得到它底下可以帶入的憑證。"
    picked = (quote_no or "").strip()
    if picked:
        conn2 = get_db()
        try:
            files = case_attachments(conn2, picked)
        finally:
            conn2.close()
        if not files:
            note2 = "案件「%s」底下目前沒有可帶入的憑證。" % picked
        else:
            note2 = ""
    cases = []
    for r in rows:
        cases.append({
            "quote_no": r["quote_no"],
            "customer_name": r["customer_name"] or "",
            "project_name": r["project_name"] or "",
            "status": r["status"] or "",
            "summary": case_summary(r["customer_name"], r["quote_no"]),
        })
    return {
        "tabs": {
            SUMMARY_TABS[0]: cases,
            # 🔑 空清單**不是**「這個頁籤不存在」——見上面的 docstring。
            #    ⚠️ 要列東西得先知道**是哪一個案件**（`quote_no`）：
            #       憑證是掛在案件底下的，沒有案件就沒有範圍。
            SUMMARY_TABS[1]: files,
        },
        "notes": {
            SUMMARY_TABS[1]: note2,
        },
    }


# ══════════════════════════════════════════════════════════════════════
# 🔴 要加**靜態** GET 路徑（例如 `/summary-sources`）的人：**宣告在這一行之前**
# ══════════════════════════════════════════════════════════════════════
#
# 下面這條 `GET /{voucher_id}` 是本 router 第一條動態 GET 路由。
# FastAPI 依**宣告順序**比對 ⇒ 任何宣告在它後面的靜態 GET 路徑會先命中它，
# 然後 `voucher_id: int` 解析失敗。
#
# ☠️ 而失敗的樣子是 **422，不是 404**：
# ```
# GET /api/vouchers/summary-sources  =>  422 {"detail":"參數不正確…"}
# ```
# 🔑 **422 讀起來像「我參數傳錯了」，而實際是「這條路根本還沒做」** ——
#    查的人會去翻自己的呼叫端，而問題在這個檔案的行號順序上。
# 📌 這一段寫在這裡而不是寫進規格：**下一個加端點的人不會去讀規格，
#    而他一定會看到這一行。**（C 2026-09-23 實測 `summary-sources` 回 422。）
@router.get("/{voucher_id}")
def read_voucher(voucher_id: int, authorization: str = Header(None)):
    """讀一張傳票（含分錄）。科目名稱依 `status` 決定取凍結值或現值。"""
    _require_voucher_access(_require_user(authorization))
    conn = get_db()
    try:
        data = get_voucher(conn, voucher_id)
        # 📌 附件掛在這裡而不是獨立端點：畫面開一張單就要看到它的憑證，
        #    多一次往返只會讓「單子出來了而附件還沒」變成一段可見的空窗。
        atts = _attachments_of(conn, voucher_id) if data is not None else []
        # 🔑 `AS2`：簽核鏈要回出去 —— 版面靠它決定畫幾列，
        #    而「還差誰簽、現在第幾關」也只有它答得出來。
        row = conn.execute("SELECT approval_json FROM vouchers_all"
                           " WHERE id = ?", (voucher_id,)).fetchone()
        appr = _appr_of(row) if row is not None else {}
    finally:
        conn.close()
    if data is None:
        raise HTTPException(404, "找不到這張傳票。")
    data["attachments"] = atts
    data["approval"] = appr
    return data


#: 簽核兩層（A `§161` 裁定，**寫死**）。
#:
#: ```
#: 製票  建立者 => `created_by`／`created_at`，**不算一層**
#: 覆核  第 1 層 => checked_by／checked_at
#: 主管  第 2 層 => manager_by／manager_at
#: ```
#: ⚠️ **不接既有 `approval_settings`** —— 那是承攬商匯款單那一套，層數可設定。
#: 🔑 兩套混在一起的話，改了那邊的設定會**靜默改掉傳票的簽核流程**。
_SIGN_SLOTS = (("checked", "簽核中"), ("manager", "已核准"))


def _load(conn, voucher_id):
    row = conn.execute("SELECT * FROM vouchers_all WHERE id = ?",
                       (voucher_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "找不到這張傳票。")
    v = dict(row)
    if v.get("voided_at"):
        raise HTTPException(400, "這張傳票已經作廢。")
    return v


@router.post("/{voucher_id}/submit")
def submit_voucher(voucher_id: int, body: dict = Body(default={}),
                   authorization: str = Header(None)):
    """送審：草稿 → 待審核。"""
    user = _require_user(authorization)
    _require_voucher_access(user)
    conn = get_db()
    try:
        v = _load(conn, voucher_id)
        if v.get("status") != "草稿":
            raise HTTPException(
                400, "只有草稿可以送審，這一張現在是「%s」。" % v.get("status"))
        # 🔴 `AS2`：簽核鏈**從設定來**，而「兩層」是預設值不是常數。
        #
        # 使用者原話：「傳票的簽核需要在簽核設定中出現」。
        # ⚠️ 而**沒有設定時走內建兩層** —— 那是 `§161` 的既有行為，
        #    不是一個新的特例：一個還沒設定過簽核流程的公司，
        #    ☠️ 若因此變成「送審即核准」或「送不出去」，都是我們替他做了決定。
        # 🔑 ⇒ 設定存在就照設定，不存在就維持現況。
        # ⚠️ **「沒有設定過」與「設定成空的」是兩件事**，而
        #    `resolve_active_flow_setting()` 分不出來：它對缺鍵回
        #    `{"tiers": []}`，與一份存成空的設定**一模一樣**。
        # ☠️ 而那個差別在這裡是有後果的：`setting_to_active_tiers()` 在
        #    `includeSubmitterManagerTier` 缺鍵時**視為 True**
        #    ⇒ 對一個沒有部門的送審人直接 raise
        #    ⇒ 沒有人設定過簽核流程的公司**連送審都送不出去**。
        #    🔑 而我第一版就是這樣寫的，它一次弄紅四支既有測試。
        # ⇒ 用 `_get_setting(key, None)` 判**鍵在不在**（〈null 不等於 0〉）。
        scope = _get_setting("approval_flow_scope", {}) or {}
        flow = _get_setting(approval_flow_setting_key("voucher", scope), None)
        tiers = []
        if flow is not None:
            try:
                tiers = setting_to_active_tiers(flow, conn, user["username"])
            except UnresolvedManagerError as exc:
                # 📌 主管解析不出來要**說得出是哪一層**，那一支已經寫好訊息了。
                raise HTTPException(400, str(exc))
        now = _dt.datetime.now().isoformat()
        appr = json.dumps({"tiers": tiers, "currentTier": 0},
                          ensure_ascii=False) if tiers else "{}"
        conn.execute(
            "UPDATE vouchers_all SET status='待審核', submitted_by=?,"
            " submitted_at=?, updated_at=?, approval_json=? WHERE id=?",
            (_user_name(user), now, now, appr, voucher_id))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "voucher.submit", "vouchers", str(voucher_id),
           "傳票送審")
    return {"ok": True, "status": "待審核"}


@router.post("/{voucher_id}/approve")
def approve_voucher(voucher_id: int, body: dict = Body(default={}),
                    authorization: str = Header(None)):
    """簽核通過。**兩層**：待審核 →（覆核）→ 簽核中 →（主管）→ 已核准。

    ## ⚠️ 每一格寫**自己的**時間戳，不共用 `updated_at`

    ☠️ 共用的話，任何一次編輯都會把「覆核是什麼時候簽的」推掉 ——
       而那一列**看起來完全正常**：有人、有時間，只是時間是錯的。
    ⚙️ 而判準是「簽完主管之後覆核的時間戳沒被改掉」，
       **不是**「三格時間不可以相同」—— 小公司常常同一個人連按兩次，
       🔑 **真的會同一秒**，那種斷言會紅在一個正確的實作上。
    """
    user = _require_user(authorization)
    _require_voucher_access(user)
    conn = get_db()
    try:
        v = _load(conn, voucher_id)
        status = v.get("status")
        if status not in ("待審核", "簽核中"):
            raise HTTPException(
                400, "「%s」的傳票不在簽核流程裡。" % status)
        now = _dt.datetime.now().isoformat()
        appr = _appr_of(v)
        tiers = appr.get("tiers") or []
        if tiers:
            # 🔴 **照鏈走**：簽完第 idx 層就往前一格，全部簽完才是已核准。
            idx = int(appr.get("currentTier") or 0)
            if idx >= len(tiers):
                raise HTTPException(400, "這張傳票的簽核已經完成。")
            tier = tiers[idx] or {}
            tier["approvedBy"] = _user_name(user)
            tier["approvedAt"] = now
            tier["status"] = "已核准"
            tiers[idx] = tier
            idx += 1
            appr["tiers"], appr["currentTier"] = tiers, idx
            nxt = "已核准" if idx >= len(tiers) else "簽核中"
            # 📌 v99 那六欄退成**版面上的簽名格**：前兩層照舊投影過去，
            #    第三層以後**只存在鏈裡** —— 而版面本來就是「回幾格畫幾列」。
            #    ☠️ 反過來（把鏈塞進三個欄位）會在第三層那天靜默掉一格。
            sets, args = ["status=?", "updated_at=?", "approval_json=?"], []
            args += [nxt, now, json.dumps(appr, ensure_ascii=False)]
            slot = {0: "checked", 1: "manager"}.get(idx - 1)
            if slot:
                sets += ["%s_by=?" % slot, "%s_at=?" % slot]
                args += [_user_name(user), now]
            conn.execute("UPDATE vouchers_all SET %s WHERE id=?"
                         % ", ".join(sets), args + [voucher_id])
        else:
            # ⚠️ 沒有設定簽核流程 ⇒ 維持 `§161` 的內建兩層。
            slot, nxt = ("checked", "簽核中") if status == "待審核"                 else ("manager", "已核准")
            # 🔑 只寫**這一格**的兩欄 —— 另一格的時間戳完全不碰。
            conn.execute(
                "UPDATE vouchers_all SET status=?, %s_by=?, %s_at=?, updated_at=?"
                " WHERE id=?" % (slot, slot),
                (nxt, _user_name(user), now, now, voucher_id))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "voucher.approve", "vouchers", str(voucher_id),
           "傳票簽核：%s" % nxt)
    return {"ok": True, "status": nxt}


@router.post("/{voucher_id}/send-back")
def send_back_voucher(voucher_id: int, body: dict = Body(default={}),
                      authorization: str = Header(None)):
    """退回修改：狀態回草稿 ＋ **清除簽核** ＋ **單號升版 `-Rn`**。

    ## 🔴 三件要一起做，少一件都會留下一個看不出來的錯

    ```
    狀態回草稿    少了它 => 退回的單卡在簽核中，沒有人能改
    清除簽核      少了它 => **帶著上一輪的簽名走完流程**
                          而簽過的人不知道他簽的已經被改過了
    單號升版      少了它 => 同一張被退兩次**看不出來**（§103e：財務不可接受）
    ```
    ⚠️ 升版走 `next_revision_no()` —— **不可以**借用報價單那一支：
       它把 `MQ-` 前綴寫死，對不上就無腦 `+ '-R1'` ⇒ 第二次會變 `-R1-R1`，
       而 `UNIQUE INDEX` 擋不住（不同字串）⇒ **不報錯，只是產生一個錯的單號**。
    """
    user = _require_user(authorization)
    _require_voucher_access(user)
    conn = get_db()
    try:
        v = _load(conn, voucher_id)
        if not can_send_back(v.get("status")):
            raise HTTPException(
                400, "「%s」的傳票不能退回。%s"
                     % (v.get("status"),
                        "已過帳只能作廢重開。" if v.get("status") == "已過帳" else ""))
        new_no = next_revision_no(v.get("voucher_no"))
        now = _dt.datetime.now().isoformat()
        conn.execute(
            "UPDATE vouchers_all SET status='草稿', voucher_no=?,"
            " submitted_by='', submitted_at='', checked_by='', checked_at='',"
            " manager_by='', manager_at='', updated_at=? WHERE id=?",
            (new_no, now, voucher_id))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "voucher.send_back", "vouchers",
           str(voucher_id), "傳票退回：%s（%s）"
           % (new_no, (body or {}).get("reason") or "未填原因"))
    return {"ok": True, "status": "草稿", "voucher_no": new_no}


@router.post("/{voucher_id}/void")
def void_voucher(voucher_id: int, body: dict = Body(default={}),
                 authorization: str = Header(None)):
    """作廢。**原單留著**，只是從有效清單消失。

    ⚙️ 這是「已過帳」唯一的出路（退回被擋）——
    ☠️ 少了它，一張開錯的已過帳傳票**從此沒有出路**。
    """
    user = _require_user(authorization)
    _require_voucher_access(user)
    reason = ((body or {}).get("reason") or "").strip()
    if not reason:
        # 🔑 沒有理由的作廢等於沒有留痕：事後沒有人回得出為什麼。
        raise HTTPException(400, "請填寫作廢原因。")
    # 🔴 `reopen` 用**鍵在不在**判斷不到，它是真假值 ⇒ 明著轉 bool。
    #    ⚠️ 而**預設是不重開** —— 重開會多出一張單，那不該是順手發生的。
    reopen = bool((body or {}).get("reopen"))
    now = _dt.datetime.now().isoformat()
    who = _user_name(user)
    new_id = new_no = None
    copied = 0
    conn = get_db()
    try:
        cur = _load(conn, voucher_id)    # 已作廢的會在這裡被擋掉
        conn.execute(
            "UPDATE vouchers_all SET voided_at=?, voided_by=?, void_reason=?,"
            " updated_at=? WHERE id=?",
            (now, who, reason, now, voucher_id))
        if reopen:
            # 🔴 **另開一張**（新的 `voucher_id`）—— 與「退回升版」不同：
            #    退回是同一張單換個號碼，作廢重開是兩張單。
            #    ⇒ 所以附件要**複製**，不複製的話新單是空的。
            src = dict(cur)
            new_no = next_voucher_no(conn, src.get("voucher_date") or "")
            c2 = conn.execute(
                "INSERT INTO vouchers_all (voucher_no, voucher_date, category,"
                " summary, status, created_by, created_at, updated_at)"
                " VALUES (?,?,?,?, '草稿', ?,?,?)",
                (new_no, src.get("voucher_date"), src.get("category") or "轉",
                 src.get("summary") or "", who, now, now))
            new_id = c2.lastrowid
            for ln in conn.execute(
                    "SELECT * FROM voucher_lines WHERE voucher_id = ?"
                    " ORDER BY line_no", (voucher_id,)).fetchall():
                ln = dict(ln)
                conn.execute(
                    "INSERT INTO voucher_lines (voucher_id, line_no,"
                    " account_code, summary, debit, credit)"
                    " VALUES (?,?,?,?,?,?)",
                    (new_id, ln["line_no"], ln["account_code"],
                     ln["summary"], ln["debit"], ln["credit"]))
            copied = _copy_attachments_to(conn, voucher_id, new_id, who, now)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "voucher.void", "vouchers", str(voucher_id),
           "傳票作廢：%s" % reason)
    out = {"ok": True, "voided_at": now}
    if reopen:
        out["new_id"] = new_id
        out["new_voucher_no"] = new_no
        out["copied_attachments"] = copied
    return out


@router.post("/{voucher_id}/post")
def post_voucher_endpoint(voucher_id: int, body: dict = Body(default={}),
                          authorization: str = Header(None)):
    """過帳（`JV1`，A `§162` 從 `JV2` 移進來）。

    ## 🔴 這一支是 `helpers.voucher.post_voucher()` 的**薄包裝**

    ☠️ 在這裡再寫一份平衡檢查的話，就是**第二份判準** ——
       而兩份會分岔，分岔之後沒有人知道哪一份是真的，
       🔑 **而它一開始是綠的**。
    ⇒ 借貸差額那句話由 `describe_balance()` 算（它已經說得出「貸方少 100」），
      狀態、凍結科目名稱、`posted_at`／`posted_by` 全在那支 helper 裡。

    ## ⚠️ 本輪**只有過帳**

    `submit`／`approve`／`send-back`／`void` 是 `JV2`，不在這裡順手加。
    """
    user = _require_user(authorization)
    _require_voucher_access(user)
    conn = get_db()
    try:
        ok, err = post_voucher(conn, voucher_id, _user_name(user))
        if not ok:
            # 🔑 `err` 是**給使用者看的字串**（含差額）⇒ 原樣帶出去，
            #    不要在這裡改寫成一句更短的話。
            conn.rollback()
            raise HTTPException(400, err)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "voucher.post", "vouchers", str(voucher_id),
           "傳票過帳")
    return {"ok": True, "status": "已過帳"}


@router.put("/{voucher_id}")
def update_voucher(voucher_id: int, body: dict = Body(...),
                   authorization: str = Header(None)):
    """改一張**草稿**傳票。有改到東西才寫一列編寫紀錄。

    ## 🔴 「剛好一列」，不是「至少一列」

    ```
    0 列  => 改過而沒有留痕（這一題要抓的）
    2 列+ => 改一次留兩筆痕，**稽核讀起來像改了兩次**
    ```
    ⇒ 一次 `PUT` 把所有變動收成**一筆** `changes_json`，不是每欄寫一列。

    ## ⚙️ 沒有改動 ⇒ **不寫**

    ☠️ 一列 `changes_json='[]'` 的留痕看起來像有記錄，而它什麼都沒說；
       而使用者按了「儲存」卻沒改東西是**日常**，不是例外
       ⇒ 那樣稽核紀錄會被灌滿沒有內容的列。

    ## ⚠️ 比對用**原值**，而寫入前先算好差異

    🔑 先算差異再寫，順序不可以反：
    ☠️ 先寫再算的話，`from` 會變成**新值**（因為它已經被覆蓋了），
       而那一列**看起來完全正常** —— 它有時間、有人、有欄位名，
       只是 `from` 與 `to` 一樣。
    """
    user = _require_user(authorization)
    # ⚠️ 改與讀用**同一道閘**，而不是「讀鬆一點、改緊一點」——
    #    再緊的那一層是 `can_edit(status)`：只有草稿改得動。
    #    🔑 兩道閘各自回答不同的問題：**誰**可以碰／這張單**現在**可不可以碰。
    _require_voucher_access(user)
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM vouchers_all WHERE id = ?",
                           (voucher_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "找不到這張傳票。")
        current = dict(row)
        if current.get("voided_at"):
            raise HTTPException(400, "這張傳票已經作廢，不能修改。")
        if not can_edit(current.get("status")):
            raise HTTPException(
                400, "只有「%s」可以修改，這一張現在是「%s」。"
                     % ("／".join(EDITABLE_STATUSES), current.get("status")))

        # 🔑 **先算差異**（用原值），再寫入。
        changes = []
        updates = {}
        for field in EDITABLE_FIELDS:
            if field not in body:
                continue
            new = body[field]
            old = current.get(field)
            # ⚠️ 用 `!=` 比對原值：兩者都可能是空字串，
            #    而「空 → 空」不是改動。
            if new == old:
                continue
            changes.append({"field": field, "from": old, "to": new})
            updates[field] = new

        # 🔴 **分錄：`lines` 有帶才動它，沒帶就一個字都不碰。**
        #
        # ☠️ 最自然的實作是「刪掉舊的 -> 重寫新的」，而**沒帶 `lines` 的 PUT
        #    若照樣走刪除那一步，分錄會全沒** —— 那比「存不進去」更糟：
        #    單子還在、狀態還是草稿，**只是內容空了**，而且不報錯。
        # 🔑 ⇒ 判斷用 `"lines" in body`（鍵在不在），**不用值的真假**：
        #    送 `lines: []` 是「把分錄清空」，與「沒提到分錄」是兩件事。
        line_changes = []
        new_lines = None
        if "lines" in body:
            new_lines = body.get("lines") or []
            old_lines = [dict(r) for r in conn.execute(
                "SELECT * FROM voucher_lines WHERE voucher_id = ?"
                " ORDER BY line_no", (voucher_id,))]
            # 📌 逐行 diff（`§103e`）—— 整包記一筆的話，同一張被退兩次
            #    **看不出來第二次改了什麼**，而那在財務上不可接受。
            # ⚠️ 與 `create_voucher` **同一道** —— 兩邊不一致的話，
            #    新建擋得住而修改會炸成 500。
            _check_account_codes(conn, new_lines)
            line_changes = diff_lines(old_lines, new_lines)

        # ⚙️ 反向控制的那一格：沒有改動就什麼都不做，**包括不寫紀錄**。
        #    ⚠️ 而「沒有改動」現在要把分錄一起算進來 ——
        #    ☠️ 只看 `changes` 的話，一次「只改了分錄」的儲存會在這裡
        #       提早 return，而分錄**根本沒被寫進去**。
        if not changes and not line_changes:
            return {"ok": True, "changed": 0}

        now = datetime.now().isoformat()
        if updates:
            sets = ", ".join("%s = ?" % f for f in updates)
            conn.execute(
                "UPDATE vouchers_all SET %s, updated_at = ? WHERE id = ?" % sets,
                list(updates.values()) + [now, voucher_id])
        else:
            conn.execute("UPDATE vouchers_all SET updated_at = ? WHERE id = ?",
                         (now, voucher_id))
        if new_lines is not None:
            # ⚠️ 重寫整組（刪舊寫新）—— 而它只在 `lines` 有帶的時候才發生。
            #    🔑 行號在這裡**重新編**：它是位置不是身分，
            #       而 `diff_lines()` 刻意不比對它（整行搬動不算改動）。
            conn.execute("DELETE FROM voucher_lines WHERE voucher_id = ?",
                         (voucher_id,))
            for n, ln in enumerate(new_lines, start=1):
                conn.execute(
                    "INSERT INTO voucher_lines (voucher_id, line_no,"
                    " account_code, summary, debit, credit)"
                    " VALUES (?,?,?,?,?,?)",
                    (voucher_id, n, (ln.get("account_code") or ""),
                     (ln.get("summary") or ""),
                     int(ln.get("debit") or 0), int(ln.get("credit") or 0)))
        try:
            append_edit_log(conn, voucher_id, _user_name(user),
                            changes + line_changes,
                            table="voucher_edit_log", changed_at=now)
        except MissingOldValue as exc:
            # 🔑 規則擋下來 ⇒ **整筆退回**，不要留下「改了而沒有紀錄」的狀態。
            conn.rollback()
            raise HTTPException(400, str(exc))
        conn.commit()
    finally:
        conn.close()

    _audit(_tok(authorization), "voucher.update", "vouchers",
           str(voucher_id),
           "修改傳票：%s"
           % "／".join(c["field"] for c in (changes + line_changes)))
    return {"ok": True, "changed": len(changes) + len(line_changes)}


def _attachments_of(conn, voucher_id, include_deleted=False):
    """這張傳票看得到的附件。**預設不列已刪的**。

    ⚠️ 而已刪的那幾列**留在表裡也留在備份裡** —— 一個被刪掉的憑證與一個
       從來不存在的憑證，在紀錄上必須分得開。
    """
    sql = ("SELECT * FROM voucher_attachments WHERE voucher_id = ?"
           + ("" if include_deleted else " AND deleted_at = ''")
           + " ORDER BY id")
    return [dict(r) for r in conn.execute(sql, (voucher_id,))]


def _insert_attachment(conn, voucher_id, file_id, filename, path, size, mime,
                       source_type, source_doc_no, source_file_id,
                       uploaded_by, uploaded_at):
    conn.execute(
        "INSERT INTO voucher_attachments (voucher_id, file_id, filename, path,"
        " size, mime, source_type, source_doc_no, source_file_id,"
        " uploaded_by, uploaded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (voucher_id, file_id, filename, path, int(size or 0), mime or "",
         source_type or "", source_doc_no or "", source_file_id or "",
         uploaded_by, uploaded_at))


@router.post("/{voucher_id}/attachments")
async def add_voucher_attachments(voucher_id: int, request: Request,
                                  authorization: str = Header(None)):
    """上傳（multipart）或帶入（`{"picks": [...]}`）附件。**同一支端點兩種形態。**

    ## 🔴 帶入**不可以讓前端傳路徑進來**

    只收 `(type, docNo, fileId)`，路徑由後端依來源表自己組 ——
    ☠️ 收路徑等於開一個**任意檔案讀取**。

    ## 🔴 先把全部來源檔檢查完，再開始複製

    ☠️ 邊複製邊檢查的話，第三筆失敗時**前兩筆已經落地了**，
       而回應說失敗 ⇒ 使用者重試 ⇒ 前兩筆變成兩份。
    🔑 拒絕的路徑上不可以留下副作用。

    ## ⚠️ 缺欄位與缺檔案，**處置相反**

    ```
    metadata 缺 size／mime／uploadedBy／uploadedAt  => 照樣複製，缺的留空，
                                                     **而在回應裡回報**
    實體檔不存在                                    => **整批拒絕 400**
    ```
    ☠️ 前者靜默補預設值的話，傳票上會顯示一個看起來正常的上傳者與時間，
       **而那是我們編的**。
    ☠️ 後者跳過的話，使用者以為附件帶進來了，
       **過帳之後才發現那張憑證從來沒存在過**。
    """
    user = _require_user(authorization)
    _require_voucher_access(user)
    now = _dt.datetime.now().isoformat()
    who = _user_name(user)

    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM vouchers_all WHERE id = ?",
                           (voucher_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "找不到這張傳票。")
        if dict(row).get("voided_at"):
            raise HTTPException(400, "這張傳票已經作廢，不能再加附件。")

        ctype = (request.headers.get("content-type") or "").lower()
        incomplete = []
        added = 0
        if ctype.startswith("multipart/"):
            form = await request.form()
            files = [f for f in form.getlist("files") if getattr(f, "filename", None)]
            if not files:
                raise HTTPException(400, "請至少選擇一個檔案。")
            # 🔑 實體檔的白名單／大小上限**沿用既有那一份**（三處共用同一份常數）。
            #    ⚠️ 路徑的 doc_no 用 `str(voucher_id)` ⇒ **不含單號**（單號會升版）。
            saved = await save_document_files(
                "voucher_attachments", str(voucher_id), files, who)
            for meta in saved:
                _insert_attachment(
                    conn, voucher_id, meta["id"], meta["filename"], meta["path"],
                    meta.get("size"), meta.get("mime"), "", "", "", who, now)
                added += 1
        else:
            try:
                body = await request.json()
            except Exception:                                   # noqa: BLE001
                raise HTTPException(400, "請求格式不正確。")
            picks = (body or {}).get("picks")
            if not picks:
                raise HTTPException(400, "請至少選擇一個檔案或一筆來源。")
            # 🔴 **全部檢查完才開始複製**（見 docstring）。
            resolved = resolve_picks(conn, picks)
            for item in resolved:
                meta = item["meta"]
                name = meta.get("filename") or meta.get("name") or "附件"
                file_id, rel, size = copy_into(voucher_id, item["src"], name)
                _insert_attachment(
                    conn, voucher_id, file_id, name, rel,
                    meta.get("size") or size, meta.get("mime"),
                    item["source_type"], item["source_doc_no"],
                    item["source_file_id"], who, now)
                added += 1
                if item["missing"]:
                    incomplete.append({"filename": name,
                                       "missing": item["missing"]})
        conn.commit()
        attachments = _attachments_of(conn, voucher_id)
    finally:
        conn.close()

    _audit(_tok(authorization), "voucher.attachment.add", "vouchers",
           str(voucher_id), "傳票附件 +%d" % added)
    out = {"ok": True, "added": added, "attachments": attachments}
    if incomplete:
        # ⚠️ 明著回報而不是靜默補值：使用者要知道哪幾筆的上傳者／時間是空的。
        out["incomplete"] = incomplete
        out["warning"] = ("有 %d 筆來源附件的資訊不完整（上傳者或時間缺漏），"
                          "檔案已經帶入，缺的欄位留空。" % len(incomplete))
    return out


@router.delete("/{voucher_id}/attachments/{file_id}")
def delete_voucher_attachment(voucher_id: int, file_id: str,
                              authorization: str = Header(None)):
    """刪一個附件。**只有草稿可刪，而且是軟刪 —— 實體檔留著。**

    ## ☠️ `helpers/uploads.py::delete_document_file()` **不可以拿來用**

    ```
    它會  os.remove(full)            <= **真的刪掉實體檔**
    也會  回傳「移除該筆之後的陣列」   <= 而我們用資料表，不是 JSON 陣列
    ```
    🔑 它的名字正好、簽章也接近 —— **下一個人會很自然地拿它來用**，
       而後果是 bytes 沒了：一個無聲的違裁（使用者裁定 `§163` ②）。
    ⚠️ 這段註解刻意寫在這裡而不是只寫在規格裡：
       **下一個人是在寫這支函式的時候動念頭的**，不是在讀規格的時候。

    ## 🔴 為什麼保留 bytes

    `archive.py::_mirror_uploads()` 逐字：「鏡像只增不減 —— 即使來源檔案被刪除，
    鏡像裡的舊副本仍保留」⇒ 已進雲端的檔刪了也還在，
    ☠️ **而當天上傳、當天刪掉的檔從來沒被鏡像過** ⇒ 硬刪等於不可復原。

    ## 🔴 離開草稿就完全不可刪（不是「刪除要簽核」）

    送審後可刪 ＝ 簽核人看過的東西可以在他不知情時消失。
    要移除 ⇒ 作廢整張傳票重開。
    ⚠️ 而**拒絕的路徑上不可以留下副作用** —— 先擋再寫，不是先寫再擋。
    """
    user = _require_user(authorization)
    _require_voucher_access(user)
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM vouchers_all WHERE id = ?",
                           (voucher_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "找不到這張傳票。")
        cur = dict(row)
        att = conn.execute(
            "SELECT * FROM voucher_attachments WHERE voucher_id = ? AND file_id = ?",
            (voucher_id, file_id)).fetchone()
        if att is None:
            raise HTTPException(404, "找不到這個附件。")
        att = dict(att)
        if not can_edit(cur.get("status")) or cur.get("voided_at"):
            raise HTTPException(
                400, "只有「%s」的傳票可以移除附件，這一張現在是「%s」。"
                     "若要移除，請作廢整張傳票再重開。"
                     % ("／".join(EDITABLE_STATUSES),
                        "已作廢" if cur.get("voided_at") else cur.get("status")))
        if att.get("deleted_at"):
            return {"ok": True, "already": True}
        now = _dt.datetime.now().isoformat()
        # 🔴 **只 UPDATE**，一個 `os.remove` 都沒有。
        conn.execute(
            "UPDATE voucher_attachments SET deleted_at = ?, deleted_by = ?"
            " WHERE id = ?", (now, _user_name(user), att["id"]))
        # 📌 附件的增刪也是「這張傳票被改過什麼」的一部分。
        append_edit_log(conn, voucher_id, _user_name(user),
                        [{"field": "attachment", "from": att.get("filename") or "",
                          "to": ""}],
                        table="voucher_edit_log", changed_at=now)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "voucher.attachment.delete", "vouchers",
           str(voucher_id), "移除傳票附件：%s" % (att.get("filename") or file_id))
    return {"ok": True}


def _copy_attachments_to(conn, old_id, new_id, who, now):
    """作廢重開：把**未刪**的附件複製到新單。回複製的筆數。

    ## 🔴 兩格不可以省

    ```
    ① 已刪的那一筆（deleted_at 非空）**不複製**
       => 使用者刪掉它是有意的，重開不該把它撿回來
    ② file_id **不可共用**，每一筆重新產生；**實體檔也真的複製一份**
       => 共用的話：在新單刪掉一個，**原單的憑證跟著不見**
    ```
    🔑 ② 的理由比 ① 硬，而硬在它**不由使用者的行為決定**：
    ```
    ① 尊重使用者的意圖          —— 意圖可以改變，規則就跟著可議
    ② 已作廢的歷史不可被後來的動作改寫 —— **稽核的不可變性**
    ```
    ⚠️ `idx_vatt_file` 是 UNIQUE，它擋得住「同一個 file_id 兩列」，
       **擋不住「兩列指向同一個實體檔」** ⇒ 所以要真的複製 bytes。
    """
    n = 0
    for att in _attachments_of(conn, old_id):
        src = abs_path(att["path"])
        if not os.path.isfile(src):
            # ⚠️ 原檔不見了就**不要造一筆指向空氣的新列** ——
            #    那會讓新單看起來有憑證而點不開。
            continue
        file_id, rel, size = copy_into(new_id, src, att["filename"])
        _insert_attachment(conn, new_id, file_id, att["filename"], rel,
                           size, att["mime"], COPY_SOURCE_TYPE,
                           str(old_id), att["file_id"], who, now)
        n += 1
    return n


@router.get("/{voucher_id}/pdf-download")
def download_voucher_pdf(voucher_id: int, with_attachments: bool = False,
                         authorization: str = Header(None)):
    """匯出傳票 PDF。`?with_attachments=1` 連附件一起。

    ## ⚠️ 路由順序：**這一支不受上面那條限制**

    上面那條說的是「**路徑只有一段、而那一段是整數參數**」的 GET 會吃掉
    後面宣告的**靜態**路徑。本支是 `/{voucher_id}/pdf-download`
    —— 動態在前、字面值在後，**段數不同** ⇒ 不會互相攔截。
    🔑 寫在這裡是因為下一個人會照抄那條規則搬家，**而搬了反而製造問題**。

    ## 🔴 附件壞掉／不見 ⇒ **照印**，把缺口印在輸出裡

    `JV3` 的帶入遇到同樣情況是整批拒絕 400，**而那個類比在這裡不成立**：
    ```
    JV3 帶入   **寫入** —— 部分成功會留下一句謊
    JV5 匯出   **唯讀** —— 不改變任何主張，只是把既有的主張印出來
    ```
    ⇒ 一份法定要保存五年的憑證，不可以因為一個附件而印不出來。
    ☠️ 而靜默略過更糟：使用者拿到一份**看起來完整**的 PDF。

    ## ⚠️ 而它必須同時反映在**回應**上

    只印在紙上的話，呼叫端（前端／自動化）分不出「完整」與「缺了東西」。
    ⇒ 回 `X-Voucher-Missing-Attachments`（筆數）與 `...-Names`（檔名）。
    🔑 **header 的值只能是 latin-1** ⇒ 檔名用 URL 編碼，
       ☠️ 直接塞中文檔名會讓整個回應在送出的那一刻炸掉，
          而那會變成「匯出壞了」——比缺一個附件嚴重得多。
    """
    _require_voucher_access(_require_user(authorization))
    data, missing = export_voucher_pdf(voucher_id, with_attachments)
    if data is None:
        raise HTTPException(404, "找不到這張傳票。")

    conn = get_db()
    try:
        row = conn.execute("SELECT voucher_no FROM vouchers_all WHERE id = ?",
                           (voucher_id,)).fetchone()
    finally:
        conn.close()
    name = (dict(row).get("voucher_no") if row else "") or str(voucher_id)

    headers = {
        # ⚠️ 檔名走 ASCII：單號是 `YYYYMMDD-NNN[-Rn]`，本來就不含非 ASCII。
        "Content-Disposition": 'attachment; filename="voucher-%s.pdf"' % name,
    }
    if missing:
        headers["X-Voucher-Missing-Attachments"] = str(len(missing))
        headers["X-Voucher-Missing-Attachment-Names"] = quote(
            "、".join((m.get("filename") or "") for m in missing))
    _audit(_tok(authorization), "voucher.pdf", "vouchers", str(voucher_id),
           "匯出傳票 PDF：%s%s" % (name, "（含附件）" if with_attachments else ""))
    return Response(content=data, media_type="application/pdf", headers=headers)
