# -*- coding: utf-8 -*-
"""`AC3`：獎金分潤的狀態轉換 → 傳票草稿（SPEC-BONUS §11.8）。

```
進入待發放   轉帳傳票草稿：借 費用（6111）／貸 應付（2191）
標記已發放   支出傳票草稿：借 應付／貸 銀行（實發，出納選，預設 1113）＋貸 代扣稅款、代收補充保費（U4 自動計算）
退回         轉帳草稿還是「草稿」⇒ 作廢；已送審 ⇒ 不動，回一句提示
```
- 只產生**草稿**：之後走傳票自己的簽核（JV30），不自動過帳。
- 科目**不寫死**：存在 `system_settings`，預設值只是初值；以 `account_items` 為準。
- 科目有問題（不存在／已停用）⇒ **不產生傳票、回提示**，不猜科目，也**不擋**獎金本身的狀態轉換。
- 全部在呼叫端的交易裡做，**不 commit**：狀態與傳票連結一起成功、一起失敗。
- 每一行都帶摘要來源 `case`＝案件單號（JV36）⇒ 案件頁「相關傳票」看得到（CORE-SPEC 獎金分潤：財務報表）。
- 會計模組（M06）經連接器取用（INTEGRATION-POINTS.md IP-2）；**M06 不在 ⇒ 獎金照常，
  不產生傳票，回明確提示 `ACCOUNTING_MISSING`**——不可以默默略過。
"""
import json

from core import registry

#: M06 不在時對使用者說的話（回傳 notice／畫面顯示用；不可以默默略過）
ACCOUNTING_MISSING = "未產生傳票：會計模組未安裝"

#: 設定鍵 → (system_settings 的 key, 預設科目, 中文名)
ACCOUNT_SLOTS = {
    "expense":     ("bonus_case_voucher_expense_code",     "6111", "費用（薪資支出）"),
    "payable":     ("bonus_case_voucher_payable_code",     "2191", "應付（應付薪資）"),
    "withholding": ("bonus_case_voucher_withholding_code", "2252", "代扣稅款"),
    "nhi":         ("bonus_case_voucher_nhi_code",         "2252", "代收補充保費"),
    "bank":        ("bonus_case_voucher_bank_code",        "1113", "銀行存款"),
}


def configured_accounts(conn):
    """目前設定的科目代號（沒設定 ⇒ 預設值）。讀同一個連線，不另開。"""
    out = {}
    for slot, (key, default, _label) in ACCOUNT_SLOTS.items():
        row = conn.execute("SELECT value_json FROM system_settings WHERE key = ?", (key,)).fetchone()
        val = default
        if row is not None:
            try:
                v = json.loads(row["value_json"])
            except (TypeError, ValueError):
                v = None
            if isinstance(v, str) and v.strip():
                val = v.strip()
        out[slot] = val
    return out


def accounting_available():
    """M06 的兩個連接器都在才算可用（IP-2）。"""
    return (registry.single_provider("voucher.draft") is not None
            and registry.single_provider("voucher.account_check") is not None)


def account_problem(conn, code):
    """空 ⇒ 「還沒設定」；不存在／已停用 ⇒ M06 的訊息；M06 不在 ⇒ 無法驗證（不當作有效）；沒問題 ⇒ ""。"""
    if not (code or "").strip():
        return "還沒有設定科目"
    check = registry.single_provider("voucher.account_check")
    if check is None:
        return "會計模組未安裝，無法驗證科目"
    ok, err = check(conn, code)
    return "" if ok else err


def _paid_total(conn, award_id):
    row = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM bonus_case_award_lines WHERE award_id = ?",
                       (award_id,)).fetchone()
    return int(row[0] or 0)


def _make(conn, award, kind, lines, summary, who, now):
    """共用：檢科目 → 正規化 → 寫入。回 `(voucher_dict | None, notice)`。"""
    if not accounting_available():
        return None, ACCOUNTING_MISSING + "（獎金狀態照常更新；需要傳票請由會計手動開立）。"
    problems = []
    for ln in lines:
        err = account_problem(conn, ln["account_code"])
        if err:
            problems.append(err)
    if problems:
        return None, "未產生傳票草稿：%s（請到獎金設定改選科目後，由會計手動開立）。" % "；".join(problems)
    # JV36：每一行掛案件來源 ⇒ 案件頁的相關傳票（vouchers_by_case）找得到獎金傳票
    lines = [dict(ln, source_type="case", source_key=award["quote_no"]) for ln in lines]
    v = registry.single_provider("voucher.draft")(
        conn, voucher_date=now[:10], summary=summary, lines=lines, created_by=who, now=now)
    vid, no = v["id"], v["voucher_no"]
    conn.execute("UPDATE bonus_case_awards SET %s_voucher_id = ? WHERE id = ?" % kind, (vid, award["id"]))
    return {"id": vid, "voucher_no": no, "status": "草稿"}, ""


def create_accrual(conn, award, who, now):
    """進入待發放：借 費用／貸 應付，金額＝名單發放合計（不含尾差）。"""
    left = int(award.get("accrual_voucher_id") or 0)
    status = registry.single_provider("voucher.status")
    if left and status is not None:
        v = status(conn, left)
        # 只有「上次退回時會計模組不在、沒能作廢」才會留下仍是草稿的舊連結 ⇒ 不覆蓋、不另開一張
        # （否則舊草稿變孤兒）。已送審的舊連結照原行為：另開新草稿，舊的由會計處理。
        if v is not None and not v["voided"] and v["status"] == "草稿":
            return None, ("上一張轉帳傳票草稿 %s 尚未作廢，未產生新的傳票草稿；"
                          "請會計先作廢那一張後再處理。" % v["voucher_no"])
    total = _paid_total(conn, award["id"])
    if total <= 0:
        return None, "發放合計為 0，未產生傳票草稿。"
    acc = configured_accounts(conn)
    text = "獎金分潤 %s" % award["quote_no"]
    return _make(conn, award, "accrual", [
        {"account_code": acc["expense"], "summary": text, "debit": total, "credit": 0},
        {"account_code": acc["payable"], "summary": text + " 應付", "debit": 0, "credit": total},
    ], text + "（應付）", who, now)


def create_payment(conn, award, who, now, bank_code, deductions=None):
    """標記已發放：借 應付（總額）／貸 銀行（實發）＋貸 代扣稅款＋貸 代收補充保費。

    `deductions`＝`bonus_deductions.compute_bonus_deductions()` 的 totals（U4）。
    None ⇒ 法規參數還沒接上：照舊留一行金額 0 的代扣稅款由出納填（呼叫端另有 notice 明說沒算）。"""
    total = _paid_total(conn, award["id"])
    if total <= 0:
        return None, "發放合計為 0，未產生傳票草稿。"
    acc = configured_accounts(conn)
    text = "獎金分潤 %s" % award["quote_no"]
    if deductions is None:
        return _make(conn, award, "payment", [
            {"account_code": acc["payable"], "summary": text + " 發放", "debit": total, "credit": 0},
            {"account_code": bank_code or acc["bank"], "summary": text + " 發放", "debit": 0, "credit": total},
            {"account_code": acc["withholding"], "summary": "代扣稅款（如適用）", "debit": 0, "credit": 0},
        ], text + "（發放）", who, now)
    wh, nhi = int(deductions["withholding"]), int(deductions["nhiPremium"])
    lines = [
        {"account_code": acc["payable"], "summary": text + " 發放", "debit": total, "credit": 0},
        {"account_code": bank_code or acc["bank"], "summary": text + " 實發", "debit": 0,
         "credit": total - wh - nhi},
        {"account_code": acc["withholding"], "summary": text + " 代扣稅款", "debit": 0, "credit": wh},
    ]
    if nhi:
        lines.append({"account_code": acc["nhi"], "summary": text + " 代收二代健保補充保費",
                      "debit": 0, "credit": nhi})
    return _make(conn, award, "payment", lines, text + "（發放）", who, now)


def withdraw_accrual(conn, award, who, now, reason):
    """退回：轉帳草稿還是草稿 ⇒ 作廢並解除連結；已送審 ⇒ 不動、回提示。回 `(voided_no, notice)`。

    經 M06 的 `voucher.void_draft`（IP-4）。M06 不在 ⇒ 退回照常，**不作廢、保留連結**（之後查得到是哪一張），
    並明說——不可以默默略過，也不可以直接改 M06 的表。"""
    vid = int(award.get("accrual_voucher_id") or 0)
    if not vid:
        return None, ""
    void = registry.single_provider("voucher.void_draft")
    if void is None:
        return None, ("未作廢傳票（#%d）：會計模組未安裝；退回照常，請會計另行處理那一張傳票。" % vid)
    r = void(conn, vid, voided_by=who, now=now, reason="獎金分潤退回：%s" % reason)
    if r["result"] == "not_draft":
        return None, ("傳票 %s 已送審（%s），系統不會自動作廢；請會計另行處理。"
                      % (r["voucher_no"], r["status"]))
    conn.execute("UPDATE bonus_case_awards SET accrual_voucher_id = 0 WHERE id = ?", (award["id"],))
    return (r["voucher_no"] if r["result"] == "voided" else None), ""


def linked_vouchers(conn, award):
    """獎金頁顯示用：這張獎金分潤產生過、目前仍連結的傳票（經 M06 的 `voucher.status`，IP-4）。

    M06 不在 ⇒ 連結的每一張仍列出，標「會計模組未安裝，無法查詢狀態」（`unavailable`）——
    不讓傳票從畫面上消失（消失會被當成「沒有傳票」）。"""
    status = registry.single_provider("voucher.status")
    out = []
    for kind in ("accrual", "payment"):
        vid = int(award.get("%s_voucher_id" % kind) or 0)
        if not vid:
            continue
        if status is None:
            out.append({"kind": kind, "id": vid, "voucher_no": "傳票 #%d" % vid,
                        "status": "會計模組未安裝，無法查詢狀態", "voided": False, "unavailable": True})
            continue
        v = status(conn, vid)
        if v is not None:
            out.append({"kind": kind, **v})
    return out
