# -*- coding: utf-8 -*-
"""獎金更正單（2026-09-30，使用者核准）：**已發放**的獎金分潤單事後更正的資料規則與跨模組寫入。

```
草稿 ──送審──▶ 待審核 ──核准──▶ 待補發（有人要補發）──出納標記補發──▶ 已完成
  │              │   └─駁回─▶ 草稿                └（沒有人要補發：核准時直接）▶ 已完成
  └─作廢─▶ 已作廢
```
- 原單（`bonus_case_awards`）與原名單**一律不改**（歷史）；每人的更正後金額／差額存在更正單 `lines_json`。
- 某人「目前金額」＝原名單合計＋已完成更正單的差額（`effective_amounts`）；所以可以連續更正。
- 同一張原單同時只有一張未結案的更正單（部分唯一索引）。

# R1：跨模組寫入落點（每一處都在下面的函式註解標出「下游影響」；總表在 MONEY-FLOWS §9）
| 寫入點 | 下游 |
|---|---|
| `open_vouchers`（核准）沖轉傳票＋重開應付傳票（草稿） | 財務會計／總帳：原應付的費用被沖掉、以更正後金額重開；傳票自己再走簽核與過帳 |
| `create_supplement_payment`（出納標記補發）補發支出傳票（草稿） | 財務會計／總帳：應付→銀行（實發）＋代扣稅款＋補充保費；出納 |
| `expense_entries`（IP-9 提供者 `bonus_correction`） | 營運報表：補發以補發日列支出、追回以核准日列負數支出；原單的那一筆不動 |
| `ytd_adjustments`（給 `bonus_deductions.ytd_in_motrix`） | 後續發放的扣繳／補充保費：全年累計含補發與追回 |
| `cashier_pending`／`cashier_paid`（IP-8 `bonus.payouts`） | 出納：待補發列在「獎金待發放」、已補發列在發放紀錄 |

# 沒有帳可沖的情況（明說、不靜默略過）
會計模組不在／科目有問題 ⇒ 不開傳票，`voucher_notice` 記原因、更正單本身照常往下走（與原單的 AC3 同一規則）。
"""
import json
from datetime import datetime

from modules.payroll import bonus_vouchers

EXPENSE_CATEGORY = "獎金分潤"
STATUSES = ("草稿", "待審核", "待補發", "已完成", "已作廢")
OPEN_STATUSES = ("草稿", "待審核", "待補發")
REASON_MAX = 200
AMOUNT_MAX = 99_999_999


class CorrectionError(ValueError):
    """輸入不合法（API 轉成 400；文字就是給使用者看的）。"""


def parse_json(text, default):
    try:
        v = json.loads(text or "")
    except (TypeError, ValueError):
        return default
    return v if isinstance(v, type(default)) else default


def corr_no_for(quote_no, seq):
    return "%s-C%d" % (quote_no, seq)


def log(conn, corr_id, who, action, detail):
    conn.execute("INSERT INTO bonus_correction_log (corr_id, changed_by, changed_at, action, detail_json)"
                 " VALUES (?,?,?,?,?)",
                 (corr_id, who, datetime.now().isoformat(), action, json.dumps(detail, ensure_ascii=False)))


# ── 目前金額 ─────────────────────────────────────────────────────────────────

def effective_amounts(conn, award_id):
    """{username: {"name": 顯示名稱, "amount": 目前金額}}：原名單（同一人跨類別合併）＋已完成更正單的每人差額。"""
    out = {}
    for r in conn.execute("SELECT username, display_name_snapshot AS n, amount FROM bonus_case_award_lines"
                          " WHERE award_id = ? ORDER BY id", (award_id,)):
        cur = out.setdefault(r["username"], {"name": r["n"] or r["username"], "amount": 0})
        cur["amount"] += int(r["amount"] or 0)
    for c in conn.execute("SELECT lines_json FROM bonus_corrections WHERE award_id = ? AND status = '已完成'"
                          " ORDER BY seq", (award_id,)):
        for ln in parse_json(c["lines_json"], []):
            cur = out.setdefault(ln["username"], {"name": ln.get("name") or ln["username"], "amount": 0})
            cur["amount"] += int(ln.get("delta") or 0)
    return out


def build_lines(conn, award_id, wanted):
    """`wanted`＝[{username, amount}]（更正後金額；沒列到的人維持原金額）。
    回 `(lines, totals)`；lines＝[{username, name, old, new, delta}]（含沒變的人）。不合法 ⇒ `CorrectionError`。"""
    if not isinstance(wanted, list) or not wanted:
        raise CorrectionError("請至少填一位的更正後金額。")
    cur = effective_amounts(conn, award_id)
    new_map = {}
    for w in wanted:
        if not isinstance(w, dict):
            raise CorrectionError("名單格式不正確。")
        u, amt = w.get("username"), w.get("amount")
        if not isinstance(u, str) or not u.strip():
            raise CorrectionError("名單裡有一列沒有帳號。")
        u = u.strip()
        if u in new_map:
            raise CorrectionError("%s 重複出現在名單裡。" % u)
        if isinstance(amt, bool) or not isinstance(amt, int) or amt < 0 or amt > AMOUNT_MAX:
            raise CorrectionError("%s 的更正後金額必須是 0～%d 的整數（元）。" % (u, AMOUNT_MAX))
        new_map[u] = amt
    lines = []
    for u in list(cur) + [u for u in new_map if u not in cur]:
        old = cur.get(u, {}).get("amount", 0)
        if u in cur:
            name = cur[u]["name"]
        else:
            row = conn.execute("SELECT display_name, active FROM users WHERE username = ?", (u,)).fetchone()
            if row is None or not row["active"]:
                raise CorrectionError("%s 不是在職帳號，不能加入更正名單。" % u)
            name = row["display_name"] or u
        new = new_map.get(u, old)
        lines.append({"username": u, "name": name, "old": old, "new": new, "delta": new - old})
    if not any(l["delta"] for l in lines):
        raise CorrectionError("更正後的金額與目前完全相同，沒有需要更正的地方。")
    return lines, totals_of(lines)


def totals_of(lines):
    return {"old_total": sum(l["old"] for l in lines), "new_total": sum(l["new"] for l in lines),
            "supplement_total": sum(l["delta"] for l in lines if l["delta"] > 0),
            "clawback_total": sum(-l["delta"] for l in lines if l["delta"] < 0)}


def validate_reason(reason):
    reason = (reason or "").strip() if isinstance(reason, str) else ""
    if not reason:
        raise CorrectionError("請填寫更正原因。")
    if len(reason) > REASON_MAX:
        raise CorrectionError("更正原因最多 %d 字（目前 %d 字）。" % (REASON_MAX, len(reason)))
    return reason


# ── 傳票（R1：財務會計／總帳）────────────────────────────────────────────────

def _draft(conn, corr, summary, lines, who, now, origin, reverses_voucher_id=None):
    """經 `voucher.draft`（IP-2）開草稿；回 (id, voucher_no, blocked)。給 `reverses_voucher_id` ⇒ 由總帳依原傳票分錄組反向草稿
    （`kind='reversal'`，與總帳引擎的沖轉同一種類）；總帳拒絕時回 `{"blocked": 原因}`，這裡轉成 blocked 字串、不丟例外。"""
    from core import registry
    rev_id = int(reverses_voucher_id) if reverses_voucher_id is not None else None
    if rev_id is None:
        lines = [dict(ln, source_type="case", source_key=corr["quote_no"]) for ln in lines]
    v = registry.single_provider("voucher.draft")(       # 明列關鍵字（守門：不准用 ** 傳參數）
        conn, voucher_date=now[:10], summary=summary, lines=lines, created_by=who, now=now, origin=origin,
        reverses_voucher_id=rev_id)
    if v.get("blocked"):
        return 0, "", str(v["blocked"])
    return v["id"], v["voucher_no"], ""


#: 追回（差額為負）＝員工應退回的獎金；依使用者規則先記為「其他應收款」，處理方式（薪資扣回／收款／免追）尚待使用者確認
CLAWBACK_PENDING_LABEL = "追回處理方式待確認"
CLAWBACK_RECEIVABLE_KEY = "bonus_corr_clawback_receivable_code"
CLAWBACK_RECEIVABLE_DEFAULT = "1213"   # 其他應收款—其他


def clawback_receivable_code(conn):
    row = conn.execute("SELECT value_json FROM system_settings WHERE key = ?", (CLAWBACK_RECEIVABLE_KEY,)).fetchone()
    if row is not None:
        try:
            v = json.loads(row["value_json"])
        except (TypeError, ValueError):
            v = None
        if isinstance(v, str) and v.strip():
            return v.strip()
    return CLAWBACK_RECEIVABLE_DEFAULT


def live_accrual_voucher_id(conn, award):
    """這張原單「目前有效的應付傳票」：最近一張已核准（待補發／已完成）更正單的重開應付傳票；沒有就是原核准應付傳票。
    連續更正時沖轉的對象是它（不是原單那張——那張已被前一次更正沖掉）。"""
    row = conn.execute("SELECT rebook_voucher_id FROM bonus_corrections WHERE award_id = ? AND status IN ('待補發','已完成')"
                       " AND rebook_voucher_id > 0 ORDER BY seq DESC LIMIT 1", (award["id"],)).fetchone()
    if row:
        return int(row["rebook_voucher_id"])
    return int(award.get("accrual_voucher_id") or 0)


def open_vouchers(conn, corr, award, who, now):
    """核准時：沖轉原應付（借 應付／貸 費用，原金額）＋以更正後金額重開應付（借 費用／貸 應付）。兩張都是**草稿**。

    R1 下游：財務會計／總帳——傳票自己再走簽核與過帳；營運報表不讀傳票（讀 `expense_entries`）。
    沖轉傳票由總帳依「目前有效的應付傳票」分錄組反向（`reverses_voucher_id`；連續更正時是前一次的重開傳票）。
    總帳拒絕（原傳票未過帳／已作廢／已被沖轉／期間已鎖）⇒ 沖轉與重開**都不開**（只重開會讓應付重複），回 notice 由會計手動處理。
    回 notice（空字串＝兩張都開了或金額為 0 不需要開）；寫入 corr 的 `*_voucher_id`（呼叫端交易內，不 commit）。"""
    if not bonus_vouchers.accounting_available():
        return bonus_vouchers.ACCOUNTING_MISSING + "（更正單照常往下；沖轉與重開應付請由會計手動開立）。"
    acc = bonus_vouchers.configured_accounts(conn)
    problems = [p for p in (bonus_vouchers.account_problem(conn, acc["expense"]),
                            bonus_vouchers.account_problem(conn, acc["payable"])) if p]
    if problems:
        return "未產生傳票草稿：%s（請到獎金設定改選科目後，由會計手動開立）。" % "；".join(problems)
    clawback = int(corr["clawback_total"])
    rec = clawback_receivable_code(conn)
    if clawback > 0:
        err = bonus_vouchers.account_problem(conn, rec)
        if err:        # 追回傳票開不出來 ⇒ 整組都不開（只開沖轉＋重開會讓應付少一個追回額）；回 notice 由會計手動處理
            return "未產生沖轉、重開與追回傳票：追回應收科目有問題：%s（追回處理方式待確認；請由會計手動處理整組）。" % err
    text = "獎金分潤更正 %s" % corr["corr_no"]
    old_total, new_total = int(corr["old_total"]), int(corr["new_total"])
    if old_total > 0:
        target = live_accrual_voucher_id(conn, award)
        if not target:
            return "原核准應付傳票查不到（舊資料），未產生沖轉與重開傳票（請由會計手動開立）。"
        rid, rno, blocked = _draft(conn, corr, "【沖轉】" + text, [], who, now, "bonus_corr_reversal", reverses_voucher_id=target)
        if blocked:
            return "未產生沖轉與重開傳票：%s（請由會計手動處理）。" % blocked
        conn.execute("UPDATE bonus_corrections SET reversal_voucher_id = ? WHERE id = ?", (rid, corr["id"]))
    if new_total > 0:
        bid, _bno, _blk = _draft(conn, corr, text + "（重開應付）", [
            {"account_code": acc["expense"], "summary": text + " 重開費用", "debit": new_total, "credit": 0},
            {"account_code": acc["payable"], "summary": text + " 重開應付", "debit": 0, "credit": new_total},
        ], who, now, "bonus_corr_accrual")
        conn.execute("UPDATE bonus_corrections SET rebook_voucher_id = ? WHERE id = ?", (bid, corr["id"]))
    if clawback > 0:
        cid, _cno, _blk = _draft(conn, corr, text + "（追回＝應收；" + CLAWBACK_PENDING_LABEL + "）", [
            {"account_code": rec, "summary": text + " 追回（應收員工）", "debit": clawback, "credit": 0},
            {"account_code": acc["payable"], "summary": text + " 追回（沖減應付）", "debit": 0, "credit": clawback},
        ], who, now, "bonus_corr_clawback")
        conn.execute("UPDATE bonus_corrections SET clawback_voucher_id = ? WHERE id = ?", (cid, corr["id"]))
    return ""


def create_supplement_payment(conn, corr, who, now, bank_code, deductions):
    """出納標記補發：借 應付（補發總額）／貸 銀行（實發）＋貸 代扣稅款＋貸 代收補充保費。**草稿**。

    R1 下游：財務會計／總帳（支出傳票草稿）、出納（發放紀錄）。追回（差額為負）的部分不在這裡：
    追回（負差額）在核准時另開「應收」傳票（借 其他應收款／貸 應付，標 追回處理方式待確認），這裡不處理。回 notice；寫入 `supplement_voucher_id`。"""
    if not bonus_vouchers.accounting_available():
        return bonus_vouchers.ACCOUNTING_MISSING + "（標記補發照常，不會產生支出傳票）。"
    acc = bonus_vouchers.configured_accounts(conn)
    bank = bank_code or acc["bank"]
    problems = [p for p in (bonus_vouchers.account_problem(conn, acc["payable"]),
                            bonus_vouchers.account_problem(conn, bank),
                            bonus_vouchers.account_problem(conn, acc["withholding"])) if p]
    if problems:
        return "未產生傳票草稿：%s（請到獎金設定改選科目後，由會計手動開立）。" % "；".join(problems)
    total = int(corr["supplement_total"])
    wh, nhi = int(deductions["withholding"]), int(deductions["nhiPremium"])
    text = "獎金分潤更正補發 %s" % corr["corr_no"]
    lines = [
        {"account_code": acc["payable"], "summary": text, "debit": total, "credit": 0},
        {"account_code": bank, "summary": text + " 實發", "debit": 0, "credit": total - wh - nhi},
        {"account_code": acc["withholding"], "summary": text + " 代扣稅款", "debit": 0, "credit": wh},
    ]
    if nhi:
        lines.append({"account_code": acc["nhi"], "summary": text + " 代收二代健保補充保費", "debit": 0, "credit": nhi})
    vid, _no, _blk = _draft(conn, corr, text + "（發放）", lines, who, now, "bonus_corr_payment")
    conn.execute("UPDATE bonus_corrections SET supplement_voucher_id = ? WHERE id = ?", (vid, corr["id"]))
    return ""


def linked_vouchers(conn, corr):
    """畫面顯示用：更正單產生的傳票（經 `voucher.status`）。會計模組不在 ⇒ 仍列出並標註，不讓傳票消失。"""
    from core import registry
    status = registry.single_provider("voucher.status")
    out = []
    for kind, col in (("reversal", "reversal_voucher_id"), ("rebook", "rebook_voucher_id"),
                      ("supplement", "supplement_voucher_id"), ("clawback", "clawback_voucher_id")):
        vid = int(corr.get(col) or 0)
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


# ── 營運報表（R1：營運報表）／ 出納 ／ 累計 ──────────────────────────────────

def expense_entries(conn, start, end):
    """IP-9 `expense.entries`（名稱 `bonus_correction`）。

    R1 下游：營運報表。原單那一筆（`bonus`，發放日、原金額）不動；更正另列：
    補發 ⇒ 補發日（paid_at）列 +補發總額；追回 ⇒ 核准日列 −追回總額（已核准即生效，不等會計收款）。
    權責與現金兩種口徑相同（與原單一致）。"""
    out = []
    for c in conn.execute("SELECT corr_no, quote_no, status, supplement_total, clawback_total, approved_at, paid_at"
                          " FROM bonus_corrections WHERE status IN ('待補發','已完成')"):
        if c["status"] == "已完成" and c["supplement_total"] > 0 and start <= (c["paid_at"] or "")[:10] <= end:
            out.append({"date": c["paid_at"][:10], "quoteNo": c["quote_no"], "amount": int(c["supplement_total"]),
                        "desc": "%s 更正補發（%s）" % (EXPENSE_CATEGORY, c["corr_no"]), "category": EXPENSE_CATEGORY})
        if c["clawback_total"] > 0 and start <= (c["approved_at"] or "")[:10] <= end:
            out.append({"date": c["approved_at"][:10], "quoteNo": c["quote_no"], "amount": -int(c["clawback_total"]),
                        "desc": "%s 更正追回（%s）" % (EXPENSE_CATEGORY, c["corr_no"]), "category": EXPENSE_CATEGORY})
    return sorted(out, key=lambda e: e["date"])


def ytd_adjustments(conn, year, exclude_corr_id=None):
    """{username: 差額合計}：該年度已生效的更正（補發＝補發日所屬年；追回＝核准日所屬年）。
    R1 下游：後續發放的扣繳與補充保費計算（`bonus_deductions.ytd_in_motrix`）。"""
    y = str(year)
    out = {}
    for c in conn.execute("SELECT id, status, lines_json, approved_at, paid_at FROM bonus_corrections"
                          " WHERE status IN ('待補發','已完成')"):
        if exclude_corr_id is not None and c["id"] == exclude_corr_id:
            continue
        for ln in parse_json(c["lines_json"], []):
            d = int(ln.get("delta") or 0)
            if d > 0 and c["status"] == "已完成" and (c["paid_at"] or "")[:4] == y:
                out[ln["username"]] = out.get(ln["username"], 0) + d
            elif d < 0 and (c["approved_at"] or "")[:4] == y:
                out[ln["username"]] = out.get(ln["username"], 0) + d
    return out


def cashier_pending(conn):
    """IP-8 `bonus.payouts.pending` 的補充列（`kind='correction'`）：待補發。"""
    return [{"quoteNo": c["corr_no"], "customer": "", "project": "更正補發（原單 %s）" % c["quote_no"],
             "total": int(c["supplement_total"]), "people": sum(1 for l in parse_json(c["lines_json"], []) if l.get("delta", 0) > 0),
             "approvedAt": (c["approved_at"] or "")[:10], "kind": "correction", "originQuoteNo": c["quote_no"]}
            for c in conn.execute("SELECT * FROM bonus_corrections WHERE status = '待補發' ORDER BY approved_at")]


def cashier_paid(conn, start, end):
    """IP-8 `bonus.payouts.paid` 的補充列：補發日在區間內的已補發更正單。"""
    out = []
    for c in conn.execute("SELECT * FROM bonus_corrections WHERE status = '已完成' AND supplement_total > 0"
                          " AND substr(paid_at, 1, 10) BETWEEN ? AND ? ORDER BY paid_at DESC", (start, end)):
        tot = (parse_json(c["deductions_json"], {}).get("totals") or {})
        out.append({"quoteNo": c["corr_no"], "customer": "", "project": "更正補發（原單 %s）" % c["quote_no"],
                    "total": int(c["supplement_total"]),
                    "people": sum(1 for l in parse_json(c["lines_json"], []) if l.get("delta", 0) > 0),
                    "paidAt": c["paid_at"][:10], "paidBy": c["paid_by"],
                    "withholding": tot.get("withholding"), "nhiPremium": tot.get("nhiPremium"), "net": tot.get("net"),
                    "kind": "correction", "originQuoteNo": c["quote_no"]})
    return out
