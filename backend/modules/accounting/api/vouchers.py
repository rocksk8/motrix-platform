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

過帳、送審、退回、作廢那幾條走 `modules.accounting.voucher` 的純邏輯，
而它們的端點**沒有派工** ⇒ 不在這裡順手加。
"""
import datetime as _dt
import json
import logging
import os
from datetime import datetime

from fastapi import APIRouter, Body, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from urllib.parse import quote

from core.txn import begin_write as _begin_write
from db import get_db
from modules.accounting import notify as _notify
# 🔑 科目代號的規則**只有一份** —— 借用既有那一支，不在這裡再寫。
#    （router 互相 import 在這個 repo 是既有做法，實查 7 處。）
from modules.accounting.api.accounting_export import validate_account_code
# `JV21`：承攬商派工的 grandTotal（含稅費用＋外包人員）算法**只有一份**——在 M04，
# 經 IP-15 成本檢視 `dispatch.cost_for_case` 取用（2026-09-26 起；原本經 IP-1 `dispatch.row`＋自己讀派工表），
# 不 import M04 的私有函式、不讀 M04 的表。
# ⚠️ **不要自己重算**：`total_amount` 少了稅、也少了外包人員費用，`ACC-BN6 §3` 已經踩過這個坑。
from core import registry as _registry
from helpers.validation import body_flag, strict_bool  # noqa: E402  第49班 W1c-P2：旗標嚴格解析
from helpers import _require_user, _tok, _audit, require_any_module
from helpers.tiered_approval import require_reject_reason  # noqa: E402  退回一律要填原因
from helpers.edit_log import append_edit_log, MissingOldValue
from helpers.tiered_approval import (
    approval_flow_setting_key, setting_to_active_tiers,
    UnresolvedManagerError, active_delegators_for,
)
from helpers import _get_setting
from helpers.uploads import save_document_files
from modules.accounting.voucher_pdf import (
    export_voucher_pdf, preview_html, classify_attachment_kind,
)
from modules.accounting.voucher_attachments import (
    resolve_picks, copy_into, abs_path, case_attachments,
    line_source_files, LINE_SOURCES, EXPENSE_LINE_SOURCES, expense_line_uses, unavailable_sources, hidden_sources, CaseNotVisible, CASE_NOT_FOUND,
)
from modules.accounting.ledger import periods as _ledger_periods
from modules.accounting.voucher import (
    EDITABLE_STATUSES, can_edit, describe_balance, get_voucher,
    next_voucher_no, post_voucher, can_send_back, next_revision_no,
    diff_lines, approval_done, parse_approval_json, VoucherChainUnreadable,
    normalize_amount_lines, classify_category,
)

_log = logging.getLogger(__name__)


def _my_actions(conn, v, appr, user):
    """目前登入者對這張傳票的簽核／退回／作廢，各自 `{allowed, reason}`；reason 是給人看的一句話（不能按才有）。
    判準與動作端點同一套：簽核／退回＝當層簽核人或其代理人（沒設流程的內建兩層：第二層只有最高管理者）；
    作廢＝已過帳只有最高管理者、系統產生的傳票不可作廢。狀態不對的動作不列（畫面本來就不顯示）。"""
    out = {}
    status = v.get("status")
    is_super = (user or {}).get("role") == "superadmin"
    has_super = bool(conn.execute("SELECT 1 FROM users WHERE role='superadmin' AND active=1 LIMIT 1").fetchone())

    def check(action):
        try:
            _require_voucher_actor(conn, appr, user, action)
            if action == "approve" and not (appr.get("tiers") or []) and status == "簽核中" and has_super and not is_super:
                raise HTTPException(403, "最後一層由最高管理者（會計主管，系統規定）核准，您不是這一層的簽核人。")
            return {"allowed": True, "reason": ""}
        except HTTPException as exc:
            return {"allowed": False, "reason": str(exc.detail)}
    if status in ("待審核", "簽核中"):
        out["approve"] = check("approve")
    if status in ("待審核", "簽核中", "已核准"):
        out["send_back"] = check("send_back")
    if not v.get("voided_at"):
        why = _system_generated_reason(v)
        if why:
            out["void"] = {"allowed": False, "reason": why}
        elif status == "已過帳" and not is_super:
            out["void"] = {"allowed": False, "reason": "只有最高管理者（會計主管）可以作廢已過帳的傳票。"}
        else:
            out["void"] = {"allowed": True, "reason": ""}
    return out


def _system_generated_reason(v):
    """系統產生的傳票（總帳引擎的自動草稿 `kind='auto'`、反向傳票 `kind='reversal'`、獎金入帳 `origin='bonus_*'`）不可以從傳票頁直接作廢：
    直接作廢會讓它和來源單據脫鉤（來源還在、帳上沒了，引擎又會依來源再產生一次，或永遠對不上）。
    更正的路：回到來源單據修改（引擎偵測來源變動，已過帳的產生反向草稿與新草稿），或在『總帳作業』處理該事件。⇒ 回傳說明字串；一般傳票回 ''。"""
    kind, origin = (v.get("kind") or ""), str(v.get("origin") or "")
    if kind == "auto" or kind == "reversal" or origin.startswith("bonus"):
        label = {"auto": "總帳引擎產生的自動傳票", "reversal": "總帳引擎產生的反向傳票"}.get(kind, "獎金入帳產生的傳票")
        return ("這張是%s，不能從傳票頁直接作廢（作廢後會和來源單據脫鉤）。"
                "要更正請回到來源單據修改，系統會自動產生反向傳票與新草稿；或到「總帳作業」處理對應的事件。" % label)
    return ""


def _mail_safe(fn, *args):
    """通知信是附帶動作：任何例外只記 log，不可以讓簽核動作失敗。"""
    try:
        fn(*args)
    except Exception:  # noqa: BLE001
        _log.exception("傳票通知信失敗（不影響簽核）")


def _tier_users(tier):
    return [a.get("username") for a in ((tier or {}).get("approvers") or []) if a.get("username")]


def _superadmin_usernames(conn):
    return [r["username"] for r in conn.execute("SELECT username FROM users WHERE role='superadmin' AND active=1")]


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
#: 📌 `JV29`：類別改由伺服器依分錄判斷（存檔時重算，只限草稿）。
#: 📌 `N6`（2026-09-24 使用者晨間表單「要能手動改」）：類別**也接受**，但不走這裡的
#:    通用迴圈——它牽涉「手動／自動」旗標與重算，由 `_category_update()` 處理
#:    （只在草稿：PUT 本來就只收草稿）。
EDITABLE_FIELDS = ("voucher_date", "summary")

#: `N6`：傳票類別的合法值（商業會計法 §17）。
_CATEGORIES = ("收", "支", "轉")
_MODE_LABEL = {0: "自動判斷", 1: "手動指定"}


def _category_update(conn, voucher_id, current, body, new_lines, line_changes):
    """`N6`：這次 PUT 之後的 `(category, category_manual)`。

    ```
    body.category_manual == True   ⇒ 手動：採用 body.category（須為 收／支／轉）
    body.category_manual == False  ⇒ 恢復自動：依分錄重算（有帶分錄用新的，否則用現有的）
    沒帶 category_manual（舊前端）  ⇒ body.category 與現值不同 ⇒ 視為手動改
                                     否則：自動模式且分錄有改 ⇒ 重算；手動模式 ⇒ 不動
    ```
    """
    cur_cat = current.get("category") or ""
    cur_manual = int(current.get("category_manual") or 0)
    if "category_manual" in body:
        if body_flag(body, "category_manual"):
            cat = body.get("category")
            if cat not in _CATEGORIES:
                raise HTTPException(422, "傳票類別只能是收入、支出或轉帳。")
            return cat, 1
        lines = new_lines if new_lines is not None else [dict(r) for r in conn.execute(
            "SELECT account_code, debit, credit FROM voucher_lines WHERE voucher_id = ?",
            (voucher_id,))]
        return classify_category(conn, lines), 0
    cat = body.get("category")
    if cat is not None and cat != cur_cat:
        if cat not in _CATEGORIES:
            raise HTTPException(422, "傳票類別只能是收入、支出或轉帳。")
        return cat, 1
    if cur_manual == 0 and new_lines is not None and line_changes:
        return classify_category(conn, new_lines), 0
    return cur_cat, cur_manual



from modules.accounting.api.voucher_common import (  # noqa: F401  純搬移後重新匯入，名稱與外部／測試的 import 路徑不變
    _amount_lines,
    _refuse_reused_expenses,
    _line_sources,
    _check_account_codes,
    _appr_of,
    _require_voucher_actor,
    require_final_superadmin,
    with_final_superadmin_tier,
    _UNREADABLE_APPR,
    insert_draft_voucher,
)

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
    lines = _line_sources(_amount_lines(body.get("lines") or []))
    now = _dt.datetime.now().isoformat()

    conn = get_db()
    try:
        # 🔑 **先驗再發號**：驗不過就丟例外，而 `next_voucher_no()` 取的是
        #    當天最大值 +1 —— 先發號再失敗的話那個號碼不會被用掉，
        #    但**下一張單會從它後面接**，帳上就少一個號碼而沒有人解釋得了。
        _check_account_codes(conn, lines)
        _refuse_reused_expenses(conn, lines)
        # `N6`：明確說要手動（`category_manual`）才採用請求的類別；否則依分錄判斷。
        if body_flag(body, "category_manual"):
            if body.get("category") not in _CATEGORIES:
                raise HTTPException(422, "傳票類別只能是收入、支出或轉帳。")
            cat, manual = body.get("category"), 1
        else:
            cat, manual = classify_category(conn, lines), 0
        vid, no = insert_draft_voucher(conn, voucher_date, body.get("summary") or "",
                                       lines, _user_name(user), now, cat, manual)
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


from modules.accounting.api.voucher_summary import (  # noqa: F401  純搬移後重新匯入，名稱與外部／測試的 import 路徑不變
    SUMMARY_TABS,
    CASES_UNAVAILABLE,
    _SOURCE_LIMIT,
    case_summary,
    _fmt_money,
    _dispatch_expense_entry,
    _extra_expense_entry,
    DISPATCH_COST_FORBIDDEN,
    DISPATCH_COST_UNAVAILABLE,
    _dispatch_costs,
    _case_expense_sources,
)

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
@router.get("/by-case/{quote_no}")
def vouchers_by_case(quote_no: str, authorization: str = Header(None)):
    """這個案件相關的有效傳票（2026-09-24，案件頁跨模組連結）。

    相關＝有分錄的來源（`JV36` source_type／source_key）指向這個案件本身、它的額外支出
    或承攬派工。作廢單不列（走 VIEW `vouchers`）。權限同傳票清單。"""
    user = _require_user(authorization)
    _require_voucher_access(user)
    no = (quote_no or "").strip()
    # 承攬派工的 id 經 IP-15 成本檢視取得（不再自己讀 M04 的表）；不在或讀不到 ⇒ 派工那一段不比
    dids = [str(d["id"]) for d in _dispatch_costs(no, authorization)[0]]
    marks = ",".join("?" * len(dids)) or "NULL"
    conn = get_db()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT DISTINCT v.id, v.voucher_no, v.voucher_date, v.status, v.summary"
            " FROM vouchers v JOIN voucher_lines l ON l.voucher_id = v.id"
            " WHERE (l.source_type = 'case' AND l.source_key = ?)"
            "    OR (l.source_type = 'extra_expense' AND l.source_key IN"
            "        (SELECT CAST(id AS TEXT) FROM case_extra_expenses WHERE quote_no = ?))"
            "    OR (l.source_type = 'contractor_dispatch' AND l.source_key IN (%s))"
            " ORDER BY v.id DESC" % marks, (no, no, *dids))]
    finally:
        conn.close()
    return {"vouchers": rows}


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
    user = _require_user(authorization)
    _require_voucher_access(user)
    # 案件清單：M01 的 IP-96 `case.summary`（2026-09-26 起；原本直讀 quotations ⇒ 到期守門 a 列觸發）。
    # 範圍照 JV7／AT6-O1 裁示：有傳票權限就列全部案件——由 L1 依 purpose="voucher_link" 判斷（只回摘要欄位）；
    # 新到舊，比對單號或客戶名稱（不分大小寫，同原本 LIKE）。
    summary = _registry.single_provider("case.summary")
    needle = (q or "").strip().lower()
    rows, note1 = [], CASES_UNAVAILABLE
    if summary is not None:
        note1 = ""
        conn = get_db()
        try:
            visible = summary(conn, user, purpose="voucher_link")
        finally:
            conn.close()
        rows = [r for r in visible
                if not needle or needle in (r["quote_no"] or "").lower()
                or needle in (r["customer_name"] or "").lower()][:_SOURCE_LIMIT]

    # ── 頁籤②：這個案件底下可帶入的憑證（`JV3` 與 `JV7` 共用同一支端點）──
    files = []
    note2 = "請先選一個案件，才看得到它底下可以帶入的憑證。"
    picked = (quote_no or "").strip()
    hidden = {}                     # 因權限沒列出的附件：類別 ⇒ 個數（明說，不可以靜默少列）
    if picked:
        not_found = False
        conn2 = get_db()
        try:
            files = case_attachments(conn2, picked, user, hidden)
        except CaseNotVisible:
            files, not_found = [], True   # 不存在與整個看不到同一句（不可以讓人探知案件編號）
        finally:
            conn2.close()
        if not_found:
            note2 = CASE_NOT_FOUND % picked + "。"
        elif not files and hidden:
            note2 = "案件「%s」底下沒有你有權限查看的憑證。" % picked
        elif not files:
            note2 = "案件「%s」底下目前沒有可帶入的憑證。" % picked
        else:
            note2 = ""

    # ── 頁籤③：這個案件底下的支出項（`JV21`）──
    expenses = []
    note3 = "請先選一個案件，才看得到它底下的支出項。"
    if picked:
        conn3 = get_db()
        try:
            expenses = _case_expense_sources(conn3, picked, authorization)
            # `JV21`：前端標紅字要的資料——這一筆被哪幾張未作廢的傳票帶入過
            uses = expense_line_uses(conn3)
            for e in expenses:
                e["usedBy"] = uses.get((e["kind"], str(e["id"])), [])
        finally:
            conn3.close()
        note3 = "" if expenses else "案件「%s」底下目前沒有支出項。" % picked
    # 稽核 X-1：承攬商派工這一類整個缺（IP-15 成本檢視不在）或因權限讀不到 ⇒ 明說，不可以跟「沒有派工」長得一樣
    unavailable = []
    if _registry.single_provider("dispatch.cost_for_case") is None:
        unavailable.append({"category": "contractor_dispatch", "reason": DISPATCH_COST_UNAVAILABLE})
    elif picked and _dispatch_costs(picked, authorization)[1]:
        unavailable.append({"category": "contractor_dispatch", "reason": DISPATCH_COST_FORBIDDEN})

    cases = []
    for r in rows:
        cases.append({
            "quote_no": r["quote_no"],
            "customer_name": r["customer_name"] or "",
            "project_name": r["project_name"] or "",
            "status": r.get("status") or "",          # 用途 voucher_link 放寬到全部案件時只回摘要欄位（沒有狀態）
            "summary": case_summary(r["customer_name"], r["quote_no"]),
        })
    return {
        "tabs": {
            SUMMARY_TABS[0]: cases,
            # 🔑 空清單**不是**「這個頁籤不存在」——見上面的 docstring。
            #    ⚠️ 要列東西得先知道**是哪一個案件**（`quote_no`）：
            #       憑證是掛在案件底下的，沒有案件就沒有範圍。
            SUMMARY_TABS[1]: files,
            SUMMARY_TABS[2]: expenses,
        },
        "notes": {
            SUMMARY_TABS[0]: note1,
            SUMMARY_TABS[1]: note2,
            SUMMARY_TABS[2]: note3,
        },
        "unavailable": unavailable,
        "hidden": hidden_sources(hidden),
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
@router.get("/line-source-files")
def line_source_files_endpoint(source_type: str = "", ref: str = "",
                               authorization: str = Header(None)):
    """`JV36`：某一行摘要的來源 XXX「本身的已上傳檔案」（只列出，勾選才帶入）。

    📌 查詢參數叫 `ref`（＝`voucher_lines.source_key`）不叫 `source_key`：`FX23a` 守門擋
       名稱含 `key`／`token`… 的 GET 查詢參數（它們會進 access log）——這個值不是憑證，
       但不為了它放寬守門，改名即可。

    範圍逐字等於 `resolve_picks()` 帶得進來的範圍（`line_source_files()` 的 docstring）。
    """
    user = _require_user(authorization)
    _require_voucher_access(user)
    conn = get_db()
    try:
        hidden = {}
        files = line_source_files(conn, source_type, ref, user, hidden)
    except CaseNotVisible:
        raise HTTPException(404, CASE_NOT_FOUND % (ref or "").strip())   # 同案件不存在（主持裁示：不回個數）
    finally:
        conn.close()
    # 附件來源的模組不在（attachments.for_document，主持裁示 M06-b）⇒ 那幾類整個沒有列出，要明說（案件那一欄才會涵蓋多個模組）
    # 因權限沒列出的附件類別 ⇒ 也要明說（主持裁示 2026-09-26）
    return {"files": files, "unavailable": unavailable_sources() if source_type == "case" else [],
            "hidden": hidden_sources(hidden)}


@router.get("/line-source-file")
def line_source_file_endpoint(source_type: str = "", ref: str = "",
                              file_id: str = "", authorization: str = Header(None)):
    """`JV36`：勾選帶入**之前**預覽來源檔（A 裁示准做，條件如下）。

    ```
    type   只接受 LINE_SOURCES 三種（其他 400）
    範圍   只在「這個來源」的檔案清單裡找 file_id —— 屬於別的案件／支出項 ⇒ 404
    路徑   再走一次 resolve_picks()（白名單＋abs_path＋實體檔存在），與帶入同一道
    權限   _require_voucher_access（今天就能透過帶入複製同樣的檔，可讀範圍沒有擴大）
    ```
    🔴 一律回 `application/octet-stream` ＋ attachment：前端自己決定能不能內嵌（`JV28` 的
       mime＋副檔名雙重判斷），不讓瀏覽器照伺服器給的類型直接渲染（SVG／HTML）。
    """
    user = _require_user(authorization)
    _require_voucher_access(user)
    fid = str(file_id or "").strip()
    conn = get_db()
    try:
        files = line_source_files(conn, source_type, ref, user)
        hit = next((f for f in files if f["fileId"] == fid), None) if fid else None
        if hit is None:
            raise HTTPException(404, "在這個來源裡找不到這個檔案。")
        item = resolve_picks(conn, [{"type": hit["type"], "docNo": hit["docNo"],
                                     "fileId": hit["fileId"]}], user)[0]
    except CaseNotVisible:
        raise HTTPException(404, CASE_NOT_FOUND % (ref or "").strip())   # 同案件不存在（主持裁示）
    finally:
        conn.close()
    return FileResponse(item["src"], media_type="application/octet-stream",
                        filename=hit["filename"] or "attachment")


@router.get("/{voucher_id}")
def read_voucher(voucher_id: int, authorization: str = Header(None)):
    """讀一張傳票（含分錄）。科目名稱依 `status` 決定取凍結值或現值。"""
    _user = _require_user(authorization)
    _require_voucher_access(_user)
    conn = get_db()
    try:
        data = get_voucher(conn, voucher_id)
        # 📌 附件掛在這裡而不是獨立端點：畫面開一張單就要看到它的憑證，
        #    多一次往返只會讓「單子出來了而附件還沒」變成一段可見的空窗。
        atts = _attachments_of(conn, voucher_id) if data is not None else []
        # `JV16③`：每一筆附件標「預計併入」的種類——由 voucher_pdf.py
        # 唯一那支分類函式算，這裡不重寫一次副檔名判斷式。
        for a in atts:
            a["mergeKind"] = classify_attachment_kind(a.get("filename"))
        # 🔑 `AS2`：簽核鏈要回出去 —— 版面靠它決定畫幾列，
        #    而「還差誰簽、現在第幾關」也只有它答得出來。
        row = conn.execute("SELECT approval_json FROM vouchers_all"
                           " WHERE id = ?", (voucher_id,)).fetchone()
        # 🔴 `JV27`：**不**借 `_appr_of()`（那支是 fail-closed，給簽核動作
        # 用）——讀取是顯示用途，一筆壞掉的 approval_json 不該讓分錄／附件
        # 也連帶讀不到（`data`／`atts` 這一刻都已經成功讀出來了）。
        if row is None:
            appr = {}
        else:
            try:
                appr = parse_approval_json(dict(row))
            except VoucherChainUnreadable:
                appr = _UNREADABLE_APPR
        # R3（W1 非工程師視角）：這個人現在可以按哪些鍵、不能按的原因——由後端用**同一套判準**算（不是前端自己再判一份）
        data["my_actions"] = _my_actions(conn, data, appr, _user) if data is not None else {}
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


@router.get("/{voucher_id}/edit-log")
def voucher_edit_log(voucher_id: int, authorization: str = Header(None)):
    """`JV22`：這張傳票的編寫紀錄（退回、欄位／分錄編修、附件增刪），**舊到新**。

    閘門與其餘傳票端點相同（`_require_voucher_access`）。**只讀**：這一支之外
    也沒有任何端點能改或刪這張表（資料庫層另有 TRIGGER，v109）。
    ⚠️ 作廢的傳票照樣讀得到 —— 作廢是「不生效」不是「不存在」，而它的編修史
       正是事後稽核要看的那一份（`SPEC-JV22 §3`）。
    """
    _require_voucher_access(_require_user(authorization))
    conn = get_db()
    try:
        if conn.execute("SELECT 1 FROM vouchers_all WHERE id = ?",
                        (voucher_id,)).fetchone() is None:
            raise HTTPException(404, "找不到這張傳票。")
        rows = [dict(r) for r in conn.execute(
            "SELECT changed_by, changed_at, changes_json FROM voucher_edit_log"
            " WHERE voucher_id = ? ORDER BY changed_at, id", (voucher_id,))]
        names = {r["username"]: (r["display_name"] or r["username"]) for r in conn.execute(
            "SELECT username, display_name FROM users")}
    finally:
        conn.close()
    entries = []
    for r in rows:
        try:
            changes = json.loads(r["changes_json"] or "[]")
        except ValueError:
            # ⚠️ 讀不出來要**說出來**，不要吞成空的一列（那看起來像「沒改什麼」）。
            changes = [{"field": "（紀錄格式無法讀取）", "from": "", "to": ""}]
        entries.append({"at": r["changed_at"], "by": r["changed_by"],
                        "byName": names.get(r["changed_by"], r["changed_by"]),
                        "changes": changes})
    return {"entries": entries}


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
        if v.get("kind") == "auto":                     # 總帳 C1：引擎產生的傳票可另設簽核流程（system_settings.voucher_auto_approval_flow）；沒設定＝與手工傳票同流程
            auto_flow = _get_setting("voucher_auto_approval_flow", None)
            if auto_flow is not None:
                flow = auto_flow
        tiers = []
        if flow is not None:
            try:
                tiers = setting_to_active_tiers(flow, conn, user["username"])
            except UnresolvedManagerError as exc:
                # 📌 主管解析不出來要**說得出是哪一層**，那一支已經寫好訊息了。
                raise HTTPException(400, str(exc))
        if tiers:          # 有設定流程 ⇒ 補最終關卡；沒設定（內建兩層）⇒ 第二層在 approve 時要求最高管理者
            tiers = with_final_superadmin_tier(conn, tiers)          # 最終關卡：最高管理者（會計主管），系統規定、不改儲存的流程設定
        now = _dt.datetime.now().isoformat()
        # 🔴 `AS3`：其餘七種文件類型的 approval JSON 都嵌著
        #    `requestedBy`／`requestedByDisplay`／`requestedAt`（簽核佇列
        #    `_queue_tier_fields()` 靠這三個欄位畫出「誰送的、什麼時候送的」）。
        #    ⚠️ 這裡原本只存 `{tiers, currentTier}` ⇒ 傳票進佇列之後那一欄會是空的。
        #    佇列端點對舊資料另外退回讀 `submitted_by`／`submitted_at` 兩欄，
        #    這裡補上是讓新送審的資料跟其他七種文件類型走同一個形狀，
        #    不必每個消費端都對傳票另外寫一次 fallback。
        # ⚠️ **不要**用 `if tiers else "{}"` —— 沒有設定流程時 `tiers` 是 `[]`，
        #    而 requestedBy 這三欄跟「有沒有設定流程」無關，兩種情況都要寫。
        #    （`_chain_tiers()` 對 `{}` 與 `{"tiers":[],...}` 回的都是 `[]`，
        #    功能上沒有差別，只是後者多帶了佇列要用的三欄。）
        appr = json.dumps({"tiers": tiers, "currentTier": 0,
                           "requestedBy": user["username"],
                           "requestedByDisplay": user.get("display_name") or user["username"],
                           "requestedAt": now},
                          ensure_ascii=False)
        conn.execute(
            "UPDATE vouchers_all SET status='待審核', submitted_by=?,"
            " submitted_at=?, updated_at=?, approval_json=? WHERE id=?",
            (_user_name(user), now, now, appr, voucher_id))
        conn.commit()
        _first = _tier_users(tiers[0]) if tiers else []
    finally:
        conn.close()
    if _first:
        _mail_safe(_notify.notify_voucher_submitted, v.get("voucher_no"), v.get("summary"), _first)
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
        _begin_write(conn)          # 先拿寫鎖再讀狀態（並行核准同一張時，第二個看到新狀態；W3 2026-09-30）
        v = _load(conn, voucher_id)
        status = v.get("status")
        if status not in ("待審核", "簽核中"):
            raise HTTPException(
                400, "「%s」的傳票不在簽核流程裡。" % status)
        now = _dt.datetime.now().isoformat()
        appr = _appr_of(v)
        _require_voucher_actor(conn, appr, user, "approve")
        tiers = appr.get("tiers") or []
        _nxt_users, _tier_no, _tier_total = [], 0, 0
        if tiers:
            # 🔴 **照鏈走**：簽完第 idx 層就往前一格，全部簽完才是已核准。
            idx = int(appr.get("currentTier") or 0)
            if idx >= len(tiers):
                raise HTTPException(400, "這張傳票的簽核已經完成。")
            tier = tiers[idx] or {}
            tier["approvedBy"] = _user_name(user)
            tier["approvedAt"] = now
            tier["status"] = "已核准"
            # 🔴 A `§253`：**加不是換**——上面那個中文欄位留著（畫面可能讀），
            #    另外標**每一個簽核人**自己的 `status`。
            #    ⚠️ 通用簽核佇列頁的「同人連續簽核一次簽完」功能
            #    （`approval-cascade.js::selfCascadeTiers()`）比對的是
            #    `approvers[i].status === 'approved'`（英文字面值，
            #    `approve_quotation()` 那支寫的格式）——只標層級的中文欄位，
            #    cascade 永遠讀不到「這層已經簽完」，便利功能對傳票永遠不觸發。
            #    📌 這裡沒有「當層哪一個人簽的」這個概念（`§161` 內建兩層是
            #    一層一動作，不像報價單可能一層多人輪流簽），簽完這層代表
            #    這層**全部**人都算數，所以是標「這一層的每一個」不是標一個。
            for _ap in (tier.get("approvers") or []):
                _ap["status"] = "approved"
                _ap["approvedAt"] = now
            tiers[idx] = tier
            idx += 1
            appr["tiers"], appr["currentTier"] = tiers, idx
            nxt = "已核准" if idx >= len(tiers) else "簽核中"
            if nxt == "簽核中":
                _nxt_users, _tier_no, _tier_total = _tier_users(tiers[idx]), idx + 1, len(tiers)
            # 📌 v99 那六欄退成**版面上的簽名格**：前兩層照舊投影過去，
            #    第三層以後**只存在鏈裡** —— 而版面本來就是「回幾格畫幾列」。
            #    ☠️ 反過來（把鏈塞進三個欄位）會在第三層那天靜默掉一格。
            sets, args = ["status=?", "updated_at=?", "approval_json=?"], []
            args += [nxt, now, json.dumps(appr, ensure_ascii=False)]
            slot = {0: "checked", 1: "manager"}.get(idx - 1)
            if slot:
                sets += ["%s_by=?" % slot, "%s_at=?" % slot]
                args += [_user_name(user), now]
            _cur = conn.execute("UPDATE vouchers_all SET %s WHERE id=? AND status=?"
                                % ", ".join(sets), args + [voucher_id, status])
            if _cur.rowcount != 1:
                raise HTTPException(409, "這張傳票剛被其他人處理過，請重新整理。")
        else:
            # ⚠️ 沒有設定簽核流程 ⇒ 維持 `§161` 的內建兩層。
            slot, nxt = ("checked", "簽核中") if status == "待審核"                 else ("manager", "已核准")
            if slot == "manager":
                require_final_superadmin(conn, user)        # 最終關卡：內建兩層的第二層（主管）一律最高管理者（系統規定）
            # 🔑 只寫**這一格**的兩欄 —— 另一格的時間戳完全不碰。
            _cur = conn.execute(
                "UPDATE vouchers_all SET status=?, %s_by=?, %s_at=?, updated_at=?"
                " WHERE id=? AND status=?" % (slot, slot),
                (nxt, _user_name(user), now, now, voucher_id, status))
            if _cur.rowcount != 1:
                raise HTTPException(409, "這張傳票剛被其他人處理過，請重新整理。")
            if nxt == "簽核中":
                _nxt_users, _tier_no, _tier_total = _superadmin_usernames(conn), 2, 2          # 內建兩層：第二層一律最高管理者
        conn.commit()
    finally:
        conn.close()
    if nxt == "簽核中":
        _mail_safe(_notify.notify_voucher_next_tier, v.get("voucher_no"), v.get("summary"), _tier_no, _tier_total, _nxt_users)
    else:
        _mail_safe(_notify.notify_voucher_approved, v.get("voucher_no"), v.get("summary"), _user_name(user), appr.get("requestedBy"))
    _audit(_tok(authorization), "voucher.approve", "vouchers", str(voucher_id),
           "傳票簽核：%s" % nxt)
    # 🔴 `AS3`：`allDone` 是**通用簽核佇列頁**（`approval-queue.html`）拿來判斷
    #    「這一層簽完了還是全部簽完了」的欄位，其餘七種文件類型的 `/approve`
    #    都會回這個鍵。少了它的後果不是報錯，是**訊息說錯**：
    #    ☠️ `resp.allDone` 讀到 `undefined`（假值）⇒ 明明已經簽到「已核准」，
    #       畫面卻顯示「等待下一層簽核人」——而使用者看不出這句話是錯的。
    return {"ok": True, "status": nxt, "allDone": nxt == "已核准"}


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

    ## ⚠️ 而「清除簽核」從 `AS2` 開始是**兩份資料**，不是一份

    ```
    checked_* / manager_*   內建兩格（沒有設定過簽核流程的公司走這條）
    approval_json           `AS2` 的簽核鏈（有設定流程時走這條）
    ```
    ☠️ 只清前者的後果：`signatures_of()` **優先讀鏈** ⇒ 六欄清得乾乾淨淨，
       而畫面與 PDF 上照樣印著上一輪簽過的名字。
    📌 〈守門守的對象被搬走〉：**清除的動作沒變、字面值沒變，
       而決定行為的已經不是它了** —— 上面那句「少了它 =>」仍然是真的，
       它守的東西卻被搬到另一個欄位去了。
    🔑 ⇒ 驗收要釘 `signatures_of()` 的**輸出**（每一格的 `by` 都是空的），
       不要釘 `checked_by == ''` —— 欄位是哪幾個還會再變，輸出不會。
    📌 用 `'{}'` 不用 `''`：與 `v101` 的 `DEFAULT '{}'` 一致
       （兩者 `_chain_tiers` 都回 `[]` —— `not raw` 對空字串也成立，查過了）。
    ⚠️ 升版走 `next_revision_no()` —— **不可以**借用報價單那一支：
       它把 `MQ-` 前綴寫死，對不上就無腦 `+ '-R1'` ⇒ 第二次會變 `-R1-R1`，
       而 `UNIQUE INDEX` 擋不住（不同字串）⇒ **不報錯，只是產生一個錯的單號**。
    """
    user = _require_user(authorization)
    _require_voucher_access(user)
    conn = get_db()
    try:
        _begin_write(conn)          # 先拿寫鎖再讀狀態（W3 2026-09-30）
        v = _load(conn, voucher_id)
        if not can_send_back(v.get("status")):
            raise HTTPException(
                400, "「%s」的傳票不能退回。%s"
                     % (v.get("status"),
                        "已過帳只能作廢重開。" if v.get("status") == "已過帳" else ""))
        _appr_before = _appr_of(v)
        _require_voucher_actor(conn, _appr_before, user, "send_back")
        new_no = next_revision_no(v.get("voucher_no"))
        now = _dt.datetime.now().isoformat()
        reason = require_reject_reason((body or {}).get("reason"))
        _cur = conn.execute(
            "UPDATE vouchers_all SET status='草稿', voucher_no=?,"
            " submitted_by='', submitted_at='', checked_by='', checked_at='',"
            " manager_by='', manager_at='', approval_json='{}',"
            " updated_at=? WHERE id=? AND status=?",
            (new_no, now, voucher_id, v.get("status")))
        if _cur.rowcount != 1:
            raise HTTPException(409, "這張傳票剛被其他人處理過，請重新整理。")
        # 🔴 `JV22`：「上次退回」要是**結構化**紀錄，不能只有 audit_log 那一句字串
        #    —— audit_log 有 730 天清理（`archive.py::_prune_audit_log`），
        #    而使用者要的是「長期記憶」⇒ 落點是 voucher_edit_log（資料庫層刪不掉，v109），
        #    並**明著標 permanent**，不靠預設值 term（`SPEC-JV22 §2b`）。
        # ⚠️ 「退回原因」的 from 是空字串：它是新增不是修改，而 `validate_changes()`
        #    只要求 from 這個鍵存在（「原本是空的」是合法答案）。
        append_edit_log(
            conn, voucher_id, _user_name(user),
            [{"field": "status", "from": v.get("status") or "", "to": "草稿"},
             {"field": "退回原因", "from": "", "to": reason},
             {"field": "voucher_no", "from": v.get("voucher_no") or "", "to": new_no}],
            table="voucher_edit_log", retention="permanent", changed_at=now)
        conn.commit()
    finally:
        conn.close()
    _mail_safe(_notify.notify_voucher_returned, new_no, v.get("summary"), reason, _appr_before.get("requestedBy"))
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
    reopen = body_flag(body, "reopen")
    now = _dt.datetime.now().isoformat()
    who = _user_name(user)
    new_id = new_no = None
    copied = 0
    conn = get_db()
    try:
        cur = _load(conn, voucher_id)    # 已作廢的會在這裡被擋掉
        why = _system_generated_reason(cur)
        if why:                          # L9（W2 寫入串接矩陣）：系統產生的傳票不能從傳票頁作廢，要回來源或走反向
            raise HTTPException(409, why)
        # 總帳 P1：已過帳傳票落在已結帳／鎖定期間 ⇒ 不可作廢，改開沖轉傳票或先重開期間（DB 觸發器是第三層）
        if cur["status"] == "已過帳":
            if user.get("role") != "superadmin":       # B：已過帳傳票的作廢只有最高管理者（未過帳的照舊）
                raise HTTPException(403, "只有最高管理者（會計主管）可以作廢已過帳的傳票。")
            lock_msg = _ledger_periods.lock_error(conn, cur["voucher_date"])
            if lock_msg:
                raise HTTPException(409, lock_msg + "已過帳傳票不可作廢；請開沖轉傳票，或先重開該期間。")
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
            # 🔴 `JV24 §5②`（A 裁甲）：`supersedes_no` 寫舊單的 `voucher_no`——
            # 新舊兩張單之間本來完全沒有任何欄位把它們連起來（沒有附件的
            # 傳票作廢重開之後在資料庫裡找不到任何關聯）。這個欄位存在已久
            # （`db.py` 的 schema 註解逐字「本張取代了哪一張」）卻從來沒被
            # 寫入過，`helpers/voucher.py` 的 docstring 也一直說「作廢落在
            # 四個欄位上」——現在讓那句話變成真的。
            c2 = conn.execute(
                "INSERT INTO vouchers_all (voucher_no, voucher_date, category, category_manual,"
                " summary, status, supersedes_no, created_by, created_at,"
                " updated_at) VALUES (?,?,?,?,?, '草稿', ?,?,?,?)",
                (new_no, src.get("voucher_date"), src.get("category") or "轉",
                 int(src.get("category_manual") or 0),
                 src.get("summary") or "", src.get("voucher_no") or "",
                 who, now, now))
            new_id = c2.lastrowid
            for ln in conn.execute(
                    "SELECT * FROM voucher_lines WHERE voucher_id = ?"
                    " ORDER BY line_no", (voucher_id,)).fetchall():
                ln = dict(ln)
                conn.execute(
                    "INSERT INTO voucher_lines (voucher_id, line_no,"
                    " account_code, summary, debit, credit, source_type, source_key)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (new_id, ln["line_no"], ln["account_code"],
                     ln["summary"], ln["debit"], ln["credit"],
                     ln.get("source_type") or "", ln.get("source_key") or ""))
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

    ## 🔴 這一支是 `modules.accounting.voucher.post_voucher()` 的**薄包裝**

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
        src_changed = False
        if "lines" in body:
            new_lines = _line_sources(_amount_lines(body.get("lines") or []))
            old_lines = [dict(r) for r in conn.execute(
                "SELECT * FROM voucher_lines WHERE voucher_id = ?"
                " ORDER BY line_no", (voucher_id,))]
            # 📌 逐行 diff（`§103e`）—— 整包記一筆的話，同一張被退兩次
            #    **看不出來第二次改了什麼**，而那在財務上不可接受。
            # ⚠️ 與 `create_voucher` **同一道** —— 兩邊不一致的話，
            #    新建擋得住而修改會炸成 500。
            _check_account_codes(conn, new_lines)
            _refuse_reused_expenses(conn, new_lines, voucher_id=voucher_id)
            line_changes = diff_lines(old_lines, new_lines)
            # `JV36`：只換了來源（摘要／金額都沒變）也要寫回，並留下編寫紀錄——
            #    `diff_lines()` 不比對來源，而編寫紀錄不收空的改動。
            _lbl = {"case": "案件", "extra_expense": "額外支出", "contractor_dispatch": "承攬商派工"}

            def _src(ln):
                st = ln.get("source_type") or ""
                return ("%s %s" % (_lbl.get(st, st), ln.get("source_key") or "")) if st else ""
            for n in range(min(len(old_lines), len(new_lines))):
                if _src(old_lines[n]) != _src(new_lines[n]):
                    src_changed = True
                    line_changes.append({"field": "lines[%d].source" % (n + 1),
                                         "from": _src(old_lines[n]), "to": _src(new_lines[n])})
            if len(old_lines) != len(new_lines):
                src_changed = True

        # `JV29`＋`N6`：類別——自動模式下分錄改了就重算；手動改過的不再自動覆蓋。
        new_cat, new_manual = _category_update(
            conn, voucher_id, current, body, new_lines, line_changes)
        if new_cat != (current.get("category") or ""):
            changes.append({"field": "category", "from": current.get("category") or "",
                            "to": new_cat})
            updates["category"] = new_cat
        cur_manual = int(current.get("category_manual") or 0)
        if new_manual != cur_manual:
            changes.append({"field": "category_manual", "from": _MODE_LABEL[cur_manual],
                            "to": _MODE_LABEL[new_manual]})
            updates["category_manual"] = new_manual

        # ⚙️ 反向控制的那一格：沒有改動就什麼都不做，**包括不寫紀錄**。
        #    ⚠️ 而「沒有改動」現在要把分錄一起算進來 ——
        #    ☠️ 只看 `changes` 的話，一次「只改了分錄」的儲存會在這裡
        #       提早 return，而分錄**根本沒被寫進去**。
        if not changes and not line_changes and not src_changed:
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
                    " account_code, summary, debit, credit, source_type, source_key)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (voucher_id, n, (ln.get("account_code") or ""),
                     (ln.get("summary") or ""),
                     ln["debit"], ln["credit"], ln["source_type"], ln["source_key"]))
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
        # W2 稽核 S4：與刪除同一條規則——離開草稿就不可再加（加了也刪不掉）；前端入口本來就只在草稿顯示，這裡補上後端那一半。
        if not can_edit(dict(row).get("status")):
            raise HTTPException(
                400, "只有「%s」的傳票可以加附件，這一張現在是「%s」。若要補附件，請作廢整張傳票再重開。"
                     % ("／".join(EDITABLE_STATUSES), dict(row).get("status")))

        ctype = (request.headers.get("content-type") or "").lower()
        incomplete = []
        added = 0
        added_names = []
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
                added_names.append(meta["filename"])
        else:
            try:
                body = await request.json()
            except Exception:                                   # noqa: BLE001
                raise HTTPException(400, "請求格式不正確。")
            picks = (body or {}).get("picks")
            if not picks:
                raise HTTPException(400, "請至少選擇一個檔案或一筆來源。")
            # 🔴 **全部檢查完才開始複製**（見 docstring）。
            resolved = resolve_picks(conn, picks, user)
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
                added_names.append(name)
                if item["missing"]:
                    incomplete.append({"filename": name,
                                       "missing": item["missing"]})
        # `JV22 §4` 缺口一：新增也要留「動過什麼」——先前只有 audit_log 的「+N」，
        # 連檔名都沒有（刪除那一側早就有檔名）。
        if added_names:
            append_edit_log(conn, voucher_id, who,
                            [{"field": "attachment", "from": "", "to": n}
                             for n in added_names],
                            table="voucher_edit_log", changed_at=now)
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


@router.get("/{voucher_id}/attachments/{file_id}")
def download_voucher_attachment(voucher_id: int, file_id: str,
                                authorization: str = Header(None)):
    """取出單一附件本身（`JV16`）。與 `POST`／`DELETE` 同一個資源路徑，
    只是換方法——不是新資源。

    ## 🔴 閘門與其他 14 支一致，**不因為「只是一張圖」降級**

    `_require_voucher_access(_require_user(authorization))`——沒有 `cashier`
    ／`finance` 模組的人一律 403，即使他知道 `voucher_id`／`file_id`。

    ## 🔴 `file_id` 必須核對屬於**這一張** `voucher_id`

    `voucher_attachments` 的實體檔放在 `/api/uploads/` 底下，那一層的
    保護完全站在「檔名猜不到」（`uuid4().hex[:16]`，64 bit）——**不是
    站在授權上**：目錄名可猜、任何登入者都進得了。⇒ 這裡（核對
    `file_id` 是不是屬於這個 `voucher_id`）是這條路上**唯一一道真正的
    授權檢查**：查詢直接把 `voucher_id` 和 `file_id` 一起當條件，換一張
    傳票的 id 配另一張的 `file_id` 查不到，回 404（不是拿到別人的附件
    再事後判斷）。

    ## ⚠️ 不接受任何形式的 query-string 憑證

    這支端點**沒有加過** `?token=`／`?pt=` 這類口子——比「拿掉」更便宜的
    是「沒加過」。前端一律 `fetch` 帶 `Authorization` header 取 blob。

    擋：① 傳票不存在 -> 404　② 附件不屬於這張傳票／已刪／查無此
    `file_id` -> 統一 404（不是 403，不要洩漏「有這個 file_id，只是你看
    不到」）　③ 實體檔路徑不合法或已遺失 -> 404。
    """
    _require_voucher_access(_require_user(authorization))
    conn = get_db()
    try:
        row = conn.execute("SELECT id FROM vouchers_all WHERE id = ?",
                           (voucher_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "找不到這張傳票。")
        att = conn.execute(
            "SELECT * FROM voucher_attachments"
            " WHERE voucher_id = ? AND file_id = ? AND deleted_at = ''",
            (voucher_id, file_id)).fetchone()
    finally:
        conn.close()
    if att is None:
        raise HTTPException(404, "找不到這個附件。")
    att = dict(att)
    try:
        p = abs_path(att.get("path"))
    except Exception:                                        # noqa: BLE001
        # 同 `split_attachments()` 的做法：路徑不合法與檔案不見，
        # 對使用者是同一件事——「這個附件現在拿不到」。
        raise HTTPException(404, "這個附件的檔案已經遺失。")
    if not os.path.isfile(p):
        raise HTTPException(404, "這個附件的檔案已經遺失。")
    return FileResponse(p, media_type=att.get("mime") or None,
                        filename=att.get("filename") or None)


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
        # 🔴 `JV24`：原樣帶過去 `source_*`，不要改寫成指向舊傳票——
        # `used_map` 的鍵是 `(source_type, source_doc_no, source_file_id)`，
        # 那三個欄位回答的是「這份憑證從哪個業務文件來的」，這個答案不會
        # 因為傳票作廢重開而改變。改寫成指向舊傳票會讓新舊兩列的鍵都對不上
        # 業務文件查詢，候選憑證清單上會顯示「未使用」，使用者因此可能
        # 再帶入一次——這正是 JV18 那個紅字標記要防的事。
        # 直接上傳的附件 `source_*` 全是空字串，原樣帶過去仍是空字串，
        # 一樣被 used_map 的 `!= ''` 排除——那是對的，不要為了讓它「有值」
        # 而填別的東西（`voucher_attachments.py` 警告過：三個欄位要一起
        # 比對，填錯會把一份從未被帶入的憑證誤標成已使用）。
        _insert_attachment(conn, new_id, file_id, att["filename"], rel,
                           size, att["mime"],
                           att["source_type"], att["source_doc_no"],
                           att["source_file_id"], who, now)
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

    # 🔴 `JV11`：閘門在後端——只藏前端按鈕的話，直接打這支端點照樣拿得到
    #    未簽核的傳票 PDF，那份 PDF 上有三個空的簽名格，看起來像正式單據。
    #    條件是 approval_done() 的「未簽核完成」，不是「狀態不等於已核准」
    #    ——後者會擋掉作廢單，牴觸 voucher_pdf.py 既有裁定（已作廢的傳票
    #    也要印得出來）。訊息說得出還差誰簽，不是一句「不可匯出」。
    conn = get_db()
    try:
        v = get_voucher(conn, voucher_id)
    finally:
        conn.close()
    if v is None:
        raise HTTPException(404, "找不到這張傳票。")
    ok, msg = approval_done(v)
    if not ok:
        raise HTTPException(400, msg)

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


@router.get("/{voucher_id}/preview")
def preview_voucher(voucher_id: int, authorization: str = Header(None)):
    """`JV11`：預覽稿。回 **HTML**，**隨時可看**，不看簽核狀態。

    ## 🔴 `§228` 裁定：獨立端點，不是 `pdf-download?preview=1`

    **閘門綁在參數上，漏傳就穿透；綁在端點上，穿不過去。** 少寫一個
    `not`、參數名打錯、預設值被改——三種都讓 `?preview=1` 那種寫法的
    閘門靜默失效，而回應看起來完全正常。這支端點**沒有簽核閘門**，
    `download_voucher_pdf()`（`pdf-download`）**才有**——兩支各自寫死
    自己的規則，沒有一個「條件」可以寫錯。

    ⚠️ 而**混在一起的後果比穿透更糟**：還沒簽核的單連看都看不到，
       而看是為了檢查——簽核的人要先看過才知道要不要簽。
    📌 回的 HTML 與匯出前 Edge 印的是**同一個 `build_html()` 呼叫**
       （`preview_html()` 的 docstring），版面只有一份，不會分岔。
    """
    _require_voucher_access(_require_user(authorization))
    body = preview_html(voucher_id)
    if body is None:
        raise HTTPException(404, "找不到這張傳票。")
    return HTMLResponse(content=body)


from modules.accounting.api.voucher_providers import (  # noqa: F401  純搬移後重新匯入，名稱與外部／測試的 import 路徑不變
    _provide_voucher_draft,
    _provide_voucher_void_draft,
    _provide_voucher_status,
    _provide_voucher_by_no,
    _queue_items,
    _VoucherReassign,
)
