"""Quotation hot-path field sync helpers."""
import json
import logging
import os
import re
import traceback
from datetime import date, datetime

from fastapi import HTTPException

from core import txn as _txn
from helpers import row_access


# Prefer real columns; fall back to data_json for rows not yet re-saved (pre-v6 backward compat).
# IMPORTANT: never use bare `SELECT deal_tag` — always use SQL_DEAL_TAG to correctly read pre-v6 rows.
SQL_DEAL_TAG = "COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '')"
SQL_SETTLE_STATUS = (
    "COALESCE(NULLIF(settle_status,''), json_extract(data_json,'$.settlement.status'), '')"
)


# ── 案件存取守門：2026-09-26 下沉 L1 `helpers/case_access.py`（主持裁示）；這裡保留同名匯入 ──
from helpers.case_access import (  # noqa: E402,F401
    CASE_ACCESS, is_document_approver, case_access_allowed, guard_case_access,
)


# 以下三個純函式 2026-09-26 下沉 L1（M01-PLAN §3-8 CA-O4：L1 不再 import M01）；這裡保留同名別名（同一物件）
from helpers.dates import norm_at  # noqa: E402,F401
from helpers.tiered_approval import steps_to_tiers as _steps_to_tiers  # noqa: E402,F401
from helpers.tax_calc import summarize_payment_items  # noqa: E402,F401


# ── 營業稅（AC1，2026-09-24 使用者：「會計稅率1~4%取消，直接依法規進行，用現金折讓就好」）──
#
# 營業稅法 §14 I（逐字）：「…分別按第七條或第十條規定計算其銷項稅額，尾數不滿通用貨幣
# 一元者，按四捨五入計算」；§7 零稅率、§8 免稅。
# ⇒ 稅別只有三種；稅額＝round_half_up(銷售額 × 5%)。報價、開票申請、稅務匯出同一算法。
# 業務讓價走報價的「折讓」欄位，不再用調低稅率。


# ── T（2026-09-26，主持核准）：稅額純函式下沉 L1 `helpers/tax_calc.py`；這裡保留同名別名（同一物件，呼叫端不必改）──
# 守門 tests/platform/test_tax_calc_contract.py：別名與 L1 是同一個物件、tax_calc 不讀表也不 import M01。
from helpers.tax_calc import (  # noqa: E402,F401
    TAX_TYPES, TAX_TYPE_LABELS, LEGAL_TAX_RATE, LEGACY_TAX_NOTE,
    quote_tax_type, tax_split, _invoice_amount, invoice_amounts, payment_item_amounts,
)


def round_half_up(n, rate=1) -> int:
    """四捨五入到元（Python 內建 round 是銀行家捨入：round(490.5) == 490）。

    轉呼叫 L1 `helpers.legal_params.round_half_up`（金額捨入的唯一來源；X-VAT，2026-09-26）。
    保留這個名字是因為既有呼叫端（recognition、reports）從這裡 import。
    """
    from helpers.legal_params import round_half_up as _rhu
    return _rhu(n, rate)


def validate_quote_tax(q: dict) -> None:
    """報價存檔（建立／修改）時的稅別檢查：只能是法定稅別，且稅別與稅率一致。

    舊的 1～4% 單再編輯存檔時必須改選法定稅別（hichan-0a 代裁）；案件記錄、收款等
    其他存檔路徑不經過這裡 ⇒ 舊單仍可收款、登錄發票。
    """
    q = q or {}
    t = q.get("taxType")
    if t not in (None, "") and t not in TAX_TYPES:
        raise HTTPException(400, "稅別不正確（只能是應稅 5%、零稅率或免稅）")
    kind = quote_tax_type(q)
    if kind == "legacy":
        raise HTTPException(400, "此報價使用已停用的稅率 %s%%，請改選法定稅別（應稅 5%%、零稅率或免稅）後再存檔"
                            % q.get("taxRate"))
    if t in TAX_TYPES:
        try:
            rate = float(q.get("taxRate", 5 if t == "taxable" else 0))
        except (TypeError, ValueError):
            rate = -1
        if rate != (5 if t == "taxable" else 0):
            raise HTTPException(400, "稅別與稅率不一致（應稅為 5%%，零稅率與免稅為 0%%）")


# ── R2（2026-09-25，CUSTOMIZATION-SPEC §9.2）：零稅率、免稅要有依據 ─────────────────
#
# 選項與檢查在 L1 `helpers.legal_params`（開票申請等其他模組共用）；這裡只決定「報價何時必填」。
from helpers.legal_params import TAX_BASIS_OPTIONS, tax_basis_error, tax_basis_label  # noqa: E402,F401


def validate_tax_basis(q: dict, status) -> None:
    """報價存檔：零稅率／免稅且**不是草稿** ⇒ 依據必填（草稿可先存，自動存檔不被擋）。
    應稅單的 taxBasis 移除（避免殘留的依據被印出來）。"""
    q = q if isinstance(q, dict) else {}
    kind = quote_tax_type(q)
    if kind not in ("zero", "exempt"):
        q.pop("taxBasis", None)
        return
    if (status or q.get("status") or "草稿") == "草稿":
        return
    err = tax_basis_error(kind, q.get("taxBasis"))
    if err:
        raise HTTPException(400, err)


def validate_invoice_amounts(item: dict) -> None:
    """AC1（使用者選 (a)）：收款登錄發票時選填「發票未稅／稅額」。

    - 兩欄都填 ⇒ 稅務匯出以它為準；都不填 ⇒ 用算式。
    - **只填一欄 ⇒ 拒存**：一半的發票金額不能作為申報依據，而它會讓人以為已經登錄了。
    - 兩欄合計 ≠ 該期金額 ⇒ **只提示、不擋**（提示在畫面；發票本來就可能與約定金額差 ±1）。
    """
    p = _invoice_amount((item or {}).get("invoicePretax"))
    t = _invoice_amount((item or {}).get("invoiceTax"))
    if (p is None) != (t is None):
        raise HTTPException(400, "發票未稅與稅額要一起填寫（只填一欄無法作為申報依據）")


def case_extra_expenses(conn, quote_no: str) -> list:
    """把一張案件的額外支出攤成月度支出彙總用的逐筆資料（讀 `case_extra_expenses` 表）。

    2026-09-11 從 `settlement_extra_expenses(data)` 改名並改讀新表（migration v75
    把資料從 `settlement.extraItems` 搬出來了）。**改名是刻意的**：若沿用舊名只改
    實作，任何漏改的呼叫端會安靜地拿到空陣列，報表數字直接歸零卻不會報錯。

    以下是從舊版保留下來、仍然成立的規則——

    2026-09-09 修：`dashboard.py::dashboard_monthly()` 與 `reports.py::_collect_expenses()`
    原本只撈 `settlement.status='finalized'` 的案件，代表**精算還在草稿階段的額外支出
    完全不會出現在任何月度支出數字裡**。但實際作業順序是「支出當下就先填，案件整個
    結束後才做精算完結」，中間可能隔好幾個月——這段期間當月已經花掉的錢在報表與首頁
    上等於憑空消失。改成**只要填了就算**。

    歸月日期依序取：
      1. `expense_date`（憑證日期，最準）
      2. `created_at`（填寫日期）
    兩者都沒有就跳過——真的無從判斷是哪個月，硬塞會污染月報。
    （舊版還會退回精算完結／最後存檔時間，新表每一筆一定有 created_at，不需要那兩層。）

    **`pending` 的定義 2026-09-11 改了**：舊版是「精算尚未完結」，現在是
    **「送審尚未核准」**（status 不是「已核准」）。使用者指定的規則是
    **送審中的項目照樣算進成本，但畫面要提醒還沒簽完**——所以這裡照樣回傳金額，
    由呼叫端決定怎麼標示。不要因為 pending 就把它濾掉，那會讓當月數字又對不上，
    正是 2026-09-09 修過的那個問題。
    """
    rows = conn.execute(
        "SELECT category, description, total_cost, expense_date, created_at, doc_no, "
        "       files_json, status "
        "FROM case_extra_expenses WHERE quote_no=? ORDER BY id", (quote_no,)
    ).fetchall()

    out = []
    for r in rows:
        cost = float(r["total_cost"] or 0)
        if not cost:
            continue
        item_date = (r["expense_date"] or r["created_at"] or "").strip()
        if not item_date:
            continue
        try:
            files = json.loads(r["files_json"] or "[]")
        except Exception:
            files = []
        out.append({
            "date":     item_date[:10],
            "month":    item_date[:7],
            "cost":     cost,
            "category": r["category"] or "其他",
            "desc":     r["description"] or "",
            "docNo":    r["doc_no"] or "",
            "files":    files,
            "status":   r["status"],
            "pending":  r["status"] != "已核准",
        })
    return out


_INVOICE_NO_RE = re.compile(r"^[A-Z]{2}\d{8}$")


def validate_invoice_no(conn, invoice_no: str, exclude_quote_no: str = None,
                         exclude_idx: int = None, exclude_item_id=None) -> None:
    """統一發票號碼格式檢查（2 碼英文字軌＋8 碼流水號，如 AB12345678）＋重複
    偵測（同一組號碼已經填在別的案件/期別上）——2026-09-02 稽核發現這個欄位
    過去完全是自由文字，格式錯誤或複製貼上打錯號碼、甚至真的重複開立，系統
    都不會有任何提示，而重複發票號碼正是國稅局查核時最先抓的稽核紅旗。
    空字串（尚未開立）視為合法，直接放行。

    排除「自己這筆」有兩種呼叫情境：mark_payment()（PATCH .../payment/{idx}，
    出納快速登錄用）逐筆改動、當下的陣列位置就是穩定的，用 exclude_idx 即可；
    update_case_record()（PATCH .../case-record，案件管理財務Tab 整包存檔，
    是使用者實際填發票號碼最常用的路徑）品項可能同時被新增/刪除/重新排序，
    陣列位置不可靠，要用品項自己的 id（case-management.js 建立品項時固定會
    帶，見該檔 addPaymentItem() 附近註解）比對，改傳 exclude_item_id。兩者
    只會用其中一種，exclude_item_id 有值時優先信任它。"""
    inv = (invoice_no or "").strip()
    if not inv:
        return
    if not _INVOICE_NO_RE.match(inv.upper()):
        raise HTTPException(
            400, f"發票號碼格式錯誤（{invoice_no}），需為 2 碼英文字軌＋8 碼數字，例如 AB12345678"
        )
    rows = conn.execute(
        "SELECT quote_no, json_extract(data_json,'$.caseRecord.payment.items') AS pay_json "
        "FROM quotations WHERE json_extract(data_json,'$.caseRecord.payment.items') IS NOT NULL"
    ).fetchall()
    for r in rows:
        try:
            items = json.loads(r["pay_json"] or "[]")
        except Exception:
            continue
        for i, it in enumerate(items):
            if (it.get("invoiceNo") or "").strip().upper() != inv.upper():
                continue
            if r["quote_no"] == exclude_quote_no:
                if exclude_item_id is not None and it.get("id") == exclude_item_id:
                    continue
                if exclude_item_id is None and exclude_idx is not None and i == exclude_idx:
                    continue
            raise HTTPException(
                400, f"發票號碼 {invoice_no} 已用於案件 {r['quote_no']} 第{i + 1}期款項，請確認是否重複或填錯"
            )


def quote_won_month_map(conn) -> dict:
    """回傳 {quote_no: 'YYYY-MM'}，該報價單應歸入成案趨勢報表的月份
    （2026-08-24 建立，2026-08-25 修正優先順序）。

    優先用 quote_date（報價單自己的日期欄位）。2026-08-24 那版原本反過來優先
    用 audit_log 裡 action='deal_tag.change'、detail.to='已成案' 的事件時間戳，
    理由是它「每次成案動作當下就寫入、不會被後續編輯覆蓋」；但實測上線後發現
    大量舊案件是系統上線後才補登（quote_date 填的是案件本身真正的日期，例如
    2026-01/02，但補登這個動作、也就是 deal_tag 第一次被設成已成案的那個
    audit 事件，發生在補登當下的 2026-07/08），導致這些舊案件全部被錯誤歸到
    補登月份，「近 12 月成案趨勢」變成看起來業績集中爆量在系統剛上線的
    七、八月——這正是本函式原本要避免的同一種失真，只是換了個方向發生。

    因此改成：quote_date 只要不是「未來日期」（不晚於今天）就直接採用；只有
    quote_date 缺漏，或明顯異常（業務員手誤填成未來月份，例如曾實測發現一筆
    達 NT$284 萬的合約 quote_date 誤填在未來月份，導致整筆從報表的近 N 月
    範圍消失）時，才 fallback 回 audit_log 的成案時間戳。"""
    won_events: dict = {}
    for r in conn.execute(
        "SELECT at, target_id, detail FROM audit_log WHERE action='deal_tag.change' ORDER BY at ASC"
    ).fetchall():
        try:
            detail = json.loads(r["detail"] or "{}")
        except Exception:
            continue
        if detail.get("to") == "已成案":
            won_events[r["target_id"]] = r["at"]

    today_str = date.today().isoformat()
    result = {}
    for r in conn.execute(
        f"SELECT quote_no, quote_date FROM quotations WHERE {SQL_DEAL_TAG} IN ('已成案','已結案')"
    ).fetchall():
        qdate = r["quote_date"] or ""
        if qdate and qdate <= today_str:
            chosen = qdate
        else:
            chosen = won_events.get(r["quote_no"]) or qdate
        if chosen:
            result[r["quote_no"]] = chosen[:7]
    return result


def quote_hot_fields(q: dict) -> tuple:
    """Return (deal_tag, settle_status) from a quotation data dict."""
    if not isinstance(q, dict):
        return "", ""
    deal_tag = q.get("dealTag") or ""
    settle = q.get("settlement")
    settle_status = settle.get("status") or "" if isinstance(settle, dict) else ""
    return deal_tag, settle_status


_log = logging.getLogger(__name__)

# 寫鎖本體在 L1 core.txn（2026-09-25 下沉）；這裡只登記案件自己要觀測的讀取：
# 拿鎖之後讀過 quotations.data_json ⇒ 之後的整包寫回是以鎖內最新資料為底。
_QUOTE_READ = "quotations.data_json"
_txn.watch_reads(_QUOTE_READ, lambda sql: "data_json" in sql and "quotations" in sql
                 and sql.lstrip()[:6].upper() == "SELECT")


def _check_read_under_write_lock(conn, quote_no):
    """save_quotation_json 的結構守門（2026-09-25 lost update 稽核後開啟）。

    放行條件：這條連線的寫交易是 core.txn.begin_write 開的，而且**拿鎖之後**讀過 quotations.data_json。
    ⚠️ 仍有的盲點：不比對讀的是不是**同一張**單、也不比對讀的是不是**這一次**要寫回的那份資料。
    違規：預設記 ERROR（含呼叫堆疊）並照寫；設了 MOTRIX_STRICT_DB_GUARDS=1（測試環境）才 raise。"""
    if _txn.read_under_lock(conn, _QUOTE_READ):
        return
    in_lock, st = _txn.lock_state(conn)
    why = ("不在寫交易內" if not conn.in_transaction else
           "寫交易不是 begin_write 開的" if st is None else "拿鎖之後沒有讀過 data_json")
    msg = f"save_quotation_json({quote_no!r})：{why}——讀 data_json 之前要先 begin_write／write_txn（lost update）"
    if _txn.strict_db_guards():
        raise RuntimeError(msg)
    _log.error("%s" + chr(10) + "%s", msg, "".join(traceback.format_stack(limit=8)))


def save_quotation_json(
    conn,
    quote_no: str,
    data: dict,
    status: str = None,
    updated_at: str = None,
) -> str:
    """Persist data_json and keep deal_tag / settle_status columns in sync.

    Optionally updates status. Returns the updated_at timestamp used.
    """
    _check_read_under_write_lock(conn, quote_no)
    now = updated_at or datetime.now().isoformat()
    deal_tag, settle_status = quote_hot_fields(data)
    if status is not None:
        conn.execute(
            "UPDATE quotations "
            "SET data_json=?, updated_at=?, deal_tag=?, settle_status=?, status=? "
            "WHERE quote_no=?",
            (json.dumps(data, ensure_ascii=False), now, deal_tag, settle_status, status, quote_no),
        )
    else:
        conn.execute(
            "UPDATE quotations "
            "SET data_json=?, updated_at=?, deal_tag=?, settle_status=? "
            "WHERE quote_no=?",
            (json.dumps(data, ensure_ascii=False), now, deal_tag, settle_status, quote_no),
        )
    return now


# ── 串接點 IP-12 `case.access`（INTEGRATION-POINTS；2026-09-26 M10 搬遷前置）──────────
# 別組（目前是 M10 網路規劃書）要「確認這個人能不能看這個案件」「讀案件的客戶／專案名稱」時走這裡，
# 不 import 本檔、也不直接讀 quotations。M01 不在 ⇒ 沒有提供者，使用方明說「案件模組未安裝」。
def case_delivery_address(data_json) -> str:
    """一個案件的交貨地點：案件合約的交貨地址優先，其次報價單的交貨地點。**一案一點。**
    （2026-09-26 自 L1 routers/map_points.py `_case_address` 搬來：資料屬 M01，對外經 `case.locations`）

    📌 合約的交貨地址是成案後填的、比較準；報價時的「交貨地點」可能只是說明文字。
    ⚠️ 讀不到／壞掉的 JSON ⇒ 回空字串（那一筆算「沒有地點」，不拖垮其他筆）。
    """
    try:
        data = json.loads(data_json or "{}")
    except (TypeError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    contract = ((data.get("caseRecord") or {}).get("contract") or {}) \
        if isinstance(data.get("caseRecord"), dict) else {}
    addr = str((contract.get("deliveryAddress") if isinstance(contract, dict) else "") or "").strip()
    return addr or str(data.get("deliveryLocation") or "").strip()


_CASE_VIS_COLS = "sales_person_id, sales_person, assigned_user_ids"


def _caller_is_system(user) -> bool:
    """`user`：一般使用者 dict，或 L1 背景工作的 `helpers.case_access.SYSTEM`。`None` ⇒ 拒絕（不猜身分）。
    執行期第二道（稽核 D CS-M1）：傳 SYSTEM 的呼叫端在 `backend/modules/`（L2）⇒ PermissionError；第一道是靜態掃描守門。"""
    from helpers.case_access import SYSTEM
    if user is None:
        raise TypeError("case.summary／case.locations：user 必填；L1 背景工作請傳 helpers.case_access.SYSTEM")
    if user is not SYSTEM:
        return False
    import sys
    here = __file__.replace("\\", "/")
    # frame(1)＝提供者本身（case_summary／_CaseLocations.list）；frame(2)＝**把 SYSTEM 傳進來的那一方**。
    # 那一方是 M01 自己（例：IP-12 summary 轉呼叫——它替 M10 取摘要，本來就不驗權限）⇒ 照常；在 backend/modules/ ⇒ 拒絕。
    f = sys._getframe(2)
    caller = (f.f_code.co_filename if f is not None else "").replace("\\", "/")
    if caller == here:
        return True
    if "/backend/modules/" in caller:
        raise PermissionError("helpers.case_access.SYSTEM 只准 L1 背景呼叫端使用（呼叫端：%s）" % caller)
    return True


def _visible(user, system, row) -> bool:
    return system or row_access.visible("case", user, row, scope="read")


def case_summary(conn, user, quote_nos=None) -> list:
    """`case.summary`（M01 提供；主持裁示 2026-09-26）：案件摘要 `{quote_no, customer_name, project_name, status,
    sales_person_id}`。`quote_nos` 省略 ⇒ 這個人看得到的全部；給清單 ⇒ 只回其中看得到、而且存在的（其餘不回，
    呼叫端要能處理缺席並明說）。只讀。可見性＝`row_access` 的 `case`／scope="read"（同案件列表、地圖）。"""
    system = _caller_is_system(user)
    cols = "quote_no, customer_name, project_name, status, " + _CASE_VIS_COLS
    if quote_nos is None:
        rows = conn.execute("SELECT %s FROM quotations ORDER BY id DESC" % cols).fetchall()
    else:
        qs = [str(x) for x in quote_nos]
        if not qs:
            return []
        rows = conn.execute("SELECT %s FROM quotations WHERE quote_no IN (%s) ORDER BY id DESC"
                            % (cols, ",".join("?" * len(qs))), qs).fetchall()
    return [{"quote_no": r["quote_no"], "customer_name": r["customer_name"] or "",
             "project_name": r["project_name"] or "", "status": r["status"] or "",
             "sales_person_id": r["sales_person_id"]}
            for r in rows if _visible(user, system, r)]


class _CaseLocations:
    """`case.locations`（M01 提供；主持裁示 2026-09-26：地址不放進 summary，另開這一個）。"""

    @staticmethod
    def list(conn, user) -> list:
        """這個人看得到的案件的交貨地點 `{quote_no, customer_name, project_name, deal_tag, address}`（address 可能是空字串）。"""
        system = _caller_is_system(user)
        rows = conn.execute(
            "SELECT id, quote_no, customer_name, project_name, deal_tag, data_json, %s FROM quotations ORDER BY id DESC"
            % _CASE_VIS_COLS).fetchall()
        return [{"quote_no": r["quote_no"], "customer_name": r["customer_name"] or "",
                 "project_name": r["project_name"] or "", "deal_tag": r["deal_tag"] or "",
                 "address": case_delivery_address(r["data_json"])}
                for r in rows if _visible(user, system, r)]

    @staticmethod
    def fingerprint(conn) -> str:
        """會影響地點與可見性的欄位的雜湊（地圖快取失效用；不含整張 data_json）。"""
        import hashlib
        h = hashlib.sha256()
        for row in conn.execute("SELECT quote_no, updated_at, deal_tag, customer_name, project_name, %s "
                                "FROM quotations ORDER BY id" % _CASE_VIS_COLS):
            h.update(repr(tuple(row)).encode("utf-8", "replace"))
        return h.hexdigest()


class _CaseAccess:
    @staticmethod
    def guard(conn, quote_no, user, allow_module=None):
        """同 guard_case_access：不存在 404、無權限 403（擋下時會關連線）；通過回單列。"""
        return guard_case_access(conn, quote_no, user, allow_module=allow_module)

    @staticmethod
    def summary(conn, quote_no):
        """{customer, project}；案件不存在 ⇒ None。
        〔淘汰（主持裁示 2026-09-26）：正式版是 `case.summary`；這裡轉呼叫它（系統身分＝原本就不驗權限，行為不變）。
          新程式不要用；使用方（M10 綁定案件）改用 case.summary 後刪除〕"""
        from helpers.case_access import SYSTEM
        got = case_summary(conn, SYSTEM, [quote_no])
        if not got:
            return None
        return {"customer": got[0]["customer_name"], "project": got[0]["project_name"]}


from core import registry as _registry  # noqa: E402
_registry.provide("case.access", "case", _CaseAccess)
_registry.provide("case.summary", "case", case_summary)          # 2026-09-26 M01-PLAN §3-4（IP 號碼由列車定）
_registry.provide("case.locations", "case", _CaseLocations)


class _CaseRecognition:
    """`case.recognition`（M01 提供；M01-PLAN §3-6）：收入認列、支出歸月與待補登標註——資料在 M01（階段、叫料、額外支出、
    報價），M08 營運報表經本提供者取用，不直接 import `modules.case.recognition`。簽章與 `modules.case.recognition` 同名函式相同。"""

    @staticmethod
    def accrual_income_items(conn, d0, d1, department_id=None):
        from modules.case import recognition as r
        return r.accrual_income_items(conn, d0, d1, department_id)

    @staticmethod
    def dispatch_entries(conn, basis):
        from modules.case import recognition as r
        return r.dispatch_entries(conn, basis)

    @staticmethod
    def material_entries(conn, basis, department_id=None):
        from modules.case import recognition as r
        return r.material_entries(conn, basis, department_id)

    @staticmethod
    def extra_entries(conn, basis):
        from modules.case import recognition as r
        return r.extra_entries(conn, basis)

    @staticmethod
    def recognition_flags(conn, year, department_id=None, money_ok=True):
        from modules.case import recognition as r
        return r.recognition_flags(conn, year, department_id, money_ok)

    @staticmethod
    def dispatch_unavailable(basis="accrual"):
        from modules.case import recognition as r
        return r.dispatch_unavailable(basis)

    @staticmethod
    def won_month_map(conn):
        """{quote_no: 'YYYY-MM'}：案件歸入成案趨勢的月份（`quote_won_month_map`；CA-O4 起 M08 經本提供者取用）。"""
        return quote_won_month_map(conn)


_registry.provide("case.recognition", "case", _CaseRecognition)   # IP 號碼由列車定


def _default_terms() -> dict:
    """`case.default_terms`（M01-PLAN §3-8 CA-O4）：報價單五欄預設條款（唯一來源 `helpers/quote_terms.DEFAULT_TERMS`）。
    L1 `routers/system` 的條款端點經本提供者取用，不 import M01。回傳複本。"""
    from modules.case.quote_terms import DEFAULT_TERMS
    return dict(DEFAULT_TERMS)


def _record_doc_version(quote_no: str, entry: dict, keep: int) -> None:
    """`case.doc_version`（M01-PLAN §3-8「pdf_gen W」）：把一筆 PDF 版本紀錄追加進 quotations.data_json 的 docVersions[]
    （只留最後 `keep` 筆；`entry["seq"]` 由這裡依現有筆數編）。L1 `pdf_gen` 產生 PDF 後呼叫，不再自己寫 M01 的表。
    併發：寫鎖（`core.txn.begin_write`）內「讀-改-寫」（原 pdf_gen 直接 BEGIN IMMEDIATE）。找不到單 ⇒ 不寫。"""
    from db import get_db
    conn = get_db()
    try:
        _txn.begin_write(conn)
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
        if not row:
            conn.rollback()
            return
        data = json.loads(row["data_json"] or "{}")
        versions = data.get("docVersions")
        if not isinstance(versions, list):
            versions = []
        versions.append({"seq": len(versions) + 1, **entry})
        data["docVersions"] = versions[-keep:]
        conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?",
                     (json.dumps(data, ensure_ascii=False), quote_no))
        conn.commit()
    finally:
        conn.close()


_registry.provide("case.default_terms", "case", _default_terms)      # IP 號碼由列車定
_registry.provide("case.doc_version", "case", _record_doc_version)   # IP 號碼由列車定
