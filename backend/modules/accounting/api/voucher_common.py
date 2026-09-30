# -*- coding: utf-8 -*-
"""傳票 API 的共用輔助（金額／科目／來源驗證、簽核鏈讀取、草稿寫入）。

2026-09-30（W4 總帳 P1）自 vouchers.py **純搬移**（行為不變；vouchers.py 仍以原名重新匯入，外部與測試的 import／monkeypatch 路徑不變）。
"""
import datetime as _dt
import json
import os
from datetime import datetime

from fastapi import APIRouter, Body, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from urllib.parse import quote

from db import get_db
# 🔑 科目代號的規則**只有一份** —— 借用既有那一支，不在這裡再寫。
#    （router 互相 import 在這個 repo 是既有做法，實查 7 處。）
from modules.accounting.api.accounting_export import validate_account_code
# `JV21`：承攬商派工的 grandTotal（含稅費用＋外包人員）算法**只有一份**——在 M04，
# 經 IP-15 成本檢視 `dispatch.cost_for_case` 取用（2026-09-26 起；原本經 IP-1 `dispatch.row`＋自己讀派工表），
# 不 import M04 的私有函式、不讀 M04 的表。
# ⚠️ **不要自己重算**：`total_amount` 少了稅、也少了外包人員費用，`ACC-BN6 §3` 已經踩過這個坑。
from core import registry as _registry
from helpers import _require_user, _tok, _audit, require_any_module
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



def _amount_lines(lines):
    """`JV32`：金額正規化；有問題 ⇒ 422 並指出第幾行（`modules.accounting.voucher.normalize_amount_lines`）。"""
    out, problems = normalize_amount_lines(lines)
    if problems:
        raise HTTPException(422, "。".join(problems) + "。")
    return out


def _refuse_reused_expenses(conn, lines, voucher_id=None):
    """`JV21`（使用者裁示：「擋下，除非前一張已作廢」）：同一筆支出只能帶入一張未作廢的傳票。

    判定與附件的紅字標記同一份（`expense_line_uses()` → `_live_uses()`）：作廢的傳票不算。
    ① 同一張傳票裡帶入同一筆兩次 ⇒ 409，指出第幾行。
    ② 別張**未作廢**傳票已帶入 ⇒ 409，寫出那一張的傳票號；自己（修改時）不算。
    ⚠️ 已知限制：`JV36` 之前的分錄沒有記來源 ⇒ 偵測不到。
    """
    seen = {}
    for i, ln in enumerate(lines or (), start=1):
        st, key = ln.get("source_type") or "", ln.get("source_key") or ""
        if st not in EXPENSE_LINE_SOURCES or not key:
            continue
        if (st, key) in seen:
            raise HTTPException(409, "第 %d 行與第 %d 行帶入了同一筆支出，同一筆支出只能記一次。"
                                % (seen[(st, key)], i))
        seen[(st, key)] = i
    if not seen:
        return
    uses = expense_line_uses(conn)
    for (st, key), i in seen.items():
        others = [u for u in uses.get((st, key), []) if u["voucherId"] != voucher_id]
        if others:
            nos = "、".join(u["voucherNo"] for u in others)
            raise HTTPException(409, "第 %d 行的支出已帶入傳票 %s（未作廢）；同一筆支出只能帶入一張傳票，"
                                     "如需重新帶入，請先作廢該張傳票。" % (i, nos))


def _line_sources(lines):
    """`JV36`：每一行的摘要來源（`source_type`／`source_key`）。空＝沒有來源。

    只接受 `LINE_SOURCES` 三種；其他 ⇒ 422 並指出第幾行。回正規化後的 lines。
    """
    out, problems = [], []
    for i, ln in enumerate(lines or (), start=1):
        ln = dict(ln)
        st = str(ln.get("source_type") or "").strip()
        key = str(ln.get("source_key") or "").strip()
        if st and st not in LINE_SOURCES:
            problems.append("第 %d 行的摘要來源「%s」不支援" % (i, st))
        if st and not key:
            problems.append("第 %d 行的摘要來源缺少編號" % i)
        ln["source_type"], ln["source_key"] = (st, key) if st else ("", "")
        out.append(ln)
    if problems:
        raise HTTPException(422, "。".join(problems) + "。")
    return out


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

    `modules.accounting.api.accounting_export.validate_account_code()` 已經定義了同一條規則，
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
    """傳票的簽核鏈——拿來**修改狀態**用（簽核動作）。**壞掉的 JSON 不要吞成
    空鏈**，那與「沒有設定」一模一樣；讀不出鏈時簽核動作必須擋下來，不能
    猜著簽，fail-closed（同 `approval_done()` 的方向）。

    🔴 `JV27`：解析本身疊在共用的 `parse_approval_json()` 上——上一版這裡
    自己重新 `json.loads` 一次，是一套獨立維護、會漂移的實作。
    ⚠️ **只給需要 fail-closed 的呼叫端用**（簽核動作）。`read_voucher()`
    是顯示用途，不能借這支去擋住整張傳票的讀取——分錄／附件都已經讀出來
    了，一筆壞掉的簽核資料不該連帶讓那些也讀不到，見那裡自己的處理。
    """
    voucher = dict(row) if not isinstance(row, dict) else row
    try:
        return parse_approval_json(voucher)
    except VoucherChainUnreadable:
        raise HTTPException(400, "這張傳票的簽核資料格式不正確，無法繼續簽核。")


def with_final_superadmin_tier(conn, tiers):
    """會計傳票的最終關卡（使用者規則 2026-09-30，主持核准）：**不論設定成什麼流程，最後一層一律是最高管理者（會計主管）**。
    - 流程設定（system_settings voucher_approval_flow／voucher_auto_approval_flow）**一個字都不改**，在送審建立簽核層時才補上這一層；
    - 設定裡最後一層本來就全是在職最高管理者 ⇒ 不重複補；沒有設定流程（內建兩格）⇒ 只有這一層；
    - 這一層的簽核人＝目前所有在職最高管理者（同一層任一人核准即可，與其他層規則相同）；製票人是最高管理者可自簽（使用者 2026-09-24 裁示）。
    - 沒有任何在職最高管理者（不會發生）⇒ 不補，避免傳票永遠送不出去。
    過帳仍要求狀態＝已核准，所以沒經過這一層核准的傳票不可能過帳。"""
    rows = conn.execute("SELECT id, username, display_name FROM users WHERE role='superadmin' AND active=1 ORDER BY id").fetchall()
    if not rows:
        return tiers
    supers = {r["username"] for r in rows}
    tiers = list(tiers or [])
    if tiers:
        last = tiers[-1].get("approvers") or []
        if last and all(a.get("username") in supers for a in last):
            return tiers
    approvers = [{"userId": r["id"], "username": r["username"], "displayName": r["display_name"] or r["username"],
                  "orgRole": "accounting_head", "orgUnit": "會計主管（系統規定）", "selfApproval": False, "status": "pending", "approvedAt": None}
                 for r in rows]
    return tiers + [{"order": len(tiers), "approvers": approvers, "system": True}]


def _require_voucher_actor(conn, appr, user, action):
    """`JV30`：誰可以對這張傳票按核准／退回（商業會計法 §35、電子辦法 §5）。

    ```
    有簽核鏈 ⇒ 操作人必須是**當前層**的簽核人，或其中某人目前有效的代理人
              （已核准＝每層都簽完 ⇒ 退回看**最後一層**）
    superadmin **不例外**（照組織流程，比照 09-15 第八輪）
    ```
    ⚠️ 比的是「在當層 approvers 裡」，**不是** `check_approve_permission()`
       的「排第一個的未簽核人」：傳票是一層一動作（核准時整層都標 approved），
       用那支的話同一層多人時只有第一個人按得動。
    ⚠️ 沒有設定簽核流程（內建兩層 `§161`）時**沒有簽核人名單可以比** ⇒ 不加限制，
       維持模組權限（A 裁示）。
    📌 更正留著：規格原本還有「② 製票人不可核准自己的傳票」，
       **已撤銷**——使用者 2026-09-24 逐字：「更正製票人要能自己簽，目前人數不夠」。
       ⇒ 製票人在當層名單內就可以自簽；不在名單內照樣擋（他沒有比別人多的權限）。
    """
    tiers = appr.get("tiers") or []
    if not tiers:
        return
    idx = min(int(appr.get("currentTier") or 0), len(tiers) - 1)
    approvers = (tiers[idx] or {}).get("approvers") or []
    delegated = active_delegators_for(conn, user["username"])
    if any(a.get("username") == user["username"] or a.get("username") in delegated
           for a in approvers):
        return
    names = "、".join(a.get("displayName") or a.get("username") or "?"
                     for a in approvers) or "（這一層沒有設定簽核人）"
    raise HTTPException(
        403, "這一層的簽核人是 %s；您不是這一層的簽核人或其代理人，不能%s。"
             % (names, "核准" if action == "approve" else "退回"))


#: `read_voucher()` 讀不出簽核鏈時的替代值——**fail-open**，同
#: `signatures_of()` 對 `VoucherChainUnreadable` 的方向：顯示用途，
#: 壞掉的簽核資料不能連帶讓分錄／附件也讀不出來。
#: 形狀維持 `{tiers, currentTier}`（`_appr_of()` 正常回傳的同一組鍵），
#: 讓還沒讀過 `unreadable` 旗標的呼叫端也不會因為缺鍵而壞掉，
#: 額外的 `unreadable`／`message` 給知道要看它的呼叫端用。
_UNREADABLE_APPR = {
    "tiers": [], "currentTier": 0, "unreadable": True,
    "message": "這張傳票的簽核資料讀不出來，無法判斷是否已完成簽核。",
}


def insert_draft_voucher(conn, voucher_date, summary, lines, created_by, now, category, manual=0):
    """寫入一張草稿傳票＋分錄，回 `(id, voucher_no)`。**不 commit**（交易由呼叫端決定）。

    `lines` 必須已經過 `_line_sources(_amount_lines(...))` 正規化、科目也驗過。
    📌 `AC3`：獎金分潤產生傳票草稿也走這一支——單號規則與寫入欄位只有一份。
    """
    no = next_voucher_no(conn, voucher_date)
    try:
        cur = conn.execute(
            "INSERT INTO vouchers_all (voucher_no, voucher_date, category, category_manual,"
            " summary, status, created_by, created_at, updated_at)"
            " VALUES (?,?,?,?,?, '草稿', ?,?,?)",
            (no, voucher_date, category, manual, summary or "", created_by, now, now))
    except Exception as exc:                            # noqa: BLE001
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(
                409, "傳票號碼「%s」剛剛被別人用掉了，請再存一次。" % no)
        raise
    vid = cur.lastrowid
    for i, ln in enumerate(lines, start=1):
        conn.execute(
            "INSERT INTO voucher_lines (voucher_id, line_no, account_code,"
            " summary, debit, credit, source_type, source_key)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (vid, i, (ln.get("account_code") or ""),
             (ln.get("summary") or ""),
             # `JV32`：已由 `_amount_lines()` 正規化成 int；不再 `int()`（它會把 12.5 截成 12）
             ln["debit"], ln["credit"],
             # `JV36`：這一行的摘要來自哪一筆（重開時依它重新帶出來源檔案清單）
             ln["source_type"], ln["source_key"]))
    return vid, no
