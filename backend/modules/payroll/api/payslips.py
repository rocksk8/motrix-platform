"""勞報單 CRUD、稅務計算、序號、PDF 下載 — superadmin only."""
import json
import logging
import os
import re
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, Header, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from db import get_db, is_demo_mode, DEMO_PAYSLIP_ARCHIVE_DIR
from helpers import _require_user, _tok, _audit, _get_setting, notify_module_activity, user_has_module
from helpers.uploads import _check_upload_magic
from helpers.errors import trace_id
from core.txn import write_txn
from modules.payroll import payslip_bank as _pb
from core import registry

router = APIRouter()
logger = logging.getLogger(__name__)

# 匯出存檔目錄（預設 backend/export_archive/；system_settings.payslip_archive_path 可覆寫，
# 比照 pdf_gen 的 6 個 *_pdf_base_path——DATA-COMPAT §4 A-3）
#
# 2026-09-22（§12 BK19）：這裡原本在**模組層**就 `os.makedirs()`。
# 🔑 那表示「有人 import 這支檔案」就會在磁碟上長出一個目錄 ——
# ☠️ 而 import 會發生在測試、健檢工具、任何一支腳本裡，
#    全都繞過測試的暫存隔離（隔離是在 fixture 裡建立的，比 import 晚）。
# ⇒ 目錄改成**用到的時候才建**：`_archive_path()` 本來就已經在寫入前
#    `os.makedirs(archive_dir, exist_ok=True)`，所以這一行純粹是多的。
# 📌 判準是〈降級之後它還是會動〉的反面：這一行拿掉之後**行為完全不變**，
#    少掉的只有「匯入即寫磁碟」這個副作用。
from core import paths as _paths
_ARCHIVE_SETTING_KEY, _ARCHIVE_DIR = _paths.PDF_ARCHIVES["payslip"]


def _archive_dir() -> str:
    # ⚠️ 改了設定之後，舊的勞報單留在原目錄、下載會找不到——與其餘 6 種 PDF 相同，搬檔是另一個動作。
    if is_demo_mode():
        return DEMO_PAYSLIP_ARCHIVE_DIR
    configured = (_get_setting(_ARCHIVE_SETTING_KEY) or "").strip()
    return configured if configured else _ARCHIVE_DIR

# 唯一合法格式，防止 slip_no 被用來做路徑穿越（2026-08-24 安全審查修正）：
# _archive_path() 直接用 slip_no 拼檔案路徑，slip_no 若可被前端任意指定
# （create_payslip 曾允許 body.slip_no 覆蓋自動產生的序號，完全沒驗證格式）
# 就能組出 "..\..\..\x" 這種跳出 export_archive/ 目錄的路徑。
_SLIP_NO_RE = re.compile(r"^PS-\d{6}-\d{3}$")

def _archive_path(slip_no: str, idx: int) -> str:
    if not _SLIP_NO_RE.match(slip_no):
        raise ValueError(f"invalid slip_no: {slip_no!r}")
    # demo 帳號：存至隔離目錄（reset_demo_db() 每次登入清空），不進真實存檔
    archive_dir = _archive_dir()
    os.makedirs(archive_dir, exist_ok=True)
    return os.path.join(archive_dir, f"{slip_no}_{idx}.pdf")


# ── 稅務計算 ──────────────────────────────────────────────────────────────────

# R1（2026-09-25，CUSTOMIZATION-SPEC §9.1）：規則改由 L1 `helpers.legal_params` 依**單據日期**挑版本；
# 原本這裡只有一套寫死的規則，修改舊單會用「當下」的規則重算。
from helpers import legal_params as _lp


def _get_tax_rules(on=None) -> dict:
    """`on`（YYYY-MM-DD 或 date；None＝今天）適用的那一版。沒有 ⇒ NoApplicableRules。"""
    return _lp.rules_for_date(_lp.load_versions(), on or _lp.today())


def _slip_date(d: dict) -> str:
    return (str(d.get("slipDate") or "").strip()[:10]) or _lp.today().isoformat()


def _rules_for_slip(d: dict) -> dict:
    try:
        return _get_tax_rules(_slip_date(d))
    except ValueError as e:          # NoApplicableRules 或日期格式錯
        raise HTTPException(400, str(e))


def _apply_privacy_ack(d: dict, old, user: dict, conn) -> None:
    """R3（個資法 §8）：「已告知當事人」由伺服器蓋時間與人員；已記錄的不可被前端覆蓋或清除。
    前端只送 `privacyNoticeAcked: true`；送來的 `privacyNotice` 一律不採用。
    `old` 必須是**拿到寫鎖之後**讀的舊單（稽核 D-2）；新寫的紀錄把告知全文存檔（稽核 S-5，同一交易）。"""
    from helpers import privacy_notice as _pn
    requested = d.pop("privacyNoticeAcked", False) is True
    d.pop("privacyNotice", None)
    existing = (old or {}).get("privacyNotice") if isinstance(old, dict) else None
    text = _pn.current_notice() if requested and not existing else ""
    rec = _pn.merge_ack(existing, requested, user, text)
    if rec:
        d["privacyNotice"] = rec
        if rec is not existing:
            try:
                _pn.archive_text(conn, text)
            except _pn.AcksCorrupted as e:
                raise HTTPException(409, str(e))


def _freeze_rules(d: dict, rules: dict) -> None:
    """單據凍結：版本號＋參數快照（修改舊單沿用它）。"""
    d["taxRulesVersion"] = rules.get("version", "")
    d["taxRulesSnapshot"] = rules


def _calc(gross: int, income_type: str, nationality: str, has_union: bool, rules: dict) -> dict:
    is_resident = nationality != "外國籍（未滿183天）"
    tax_withheld = 0
    tax_rate = 0.0

    if is_resident:
        r = rules["resident"][income_type]
        if gross >= r["tax_threshold"]:
            tax_rate = r["tax_rate"]
            tax_withheld = _lp.floor_amount(gross, tax_rate)
    else:
        r = rules["non_resident"][income_type]
        if gross >= r.get("tax_threshold", 0):
            if "low_salary_rate" in r:
                min_1_5 = rules["minimum_wage"]["monthly"] * 1.5
                tax_rate = r["low_salary_rate"] if gross <= min_1_5 else r["tax_rate"]
            else:
                tax_rate = r["tax_rate"]
            tax_withheld = _lp.floor_amount(gross, tax_rate)

    nhi_supplement = 0
    nhi_rate = 0.0
    if not has_union:
        threshold = rules["nhi"]["thresholds"][income_type]
        if gross >= threshold:
            nhi_rate = rules["nhi"]["rate"]
            base = min(gross, rules["nhi"]["max_single_payment"])
            # 稽核 D-1：健保署「角以下 4 捨 5 入」；內建 round() 是銀行家捨入（35,000 × 2.11% ⇒ 738，應為 739）
            nhi_supplement = _lp.round_half_up(base, nhi_rate)

    return {
        "taxRate":       tax_rate,
        "taxWithheld":   tax_withheld,
        "nhiRate":       nhi_rate,
        "nhiSupplement": nhi_supplement,
        "netAmount":     gross - tax_withheld - nhi_supplement,
    }


# ── 序號（peek-only，同報價單設計）────────────────────────────────────────────

def _peek_next_slip_no(conn, month: str) -> str:
    row_max = conn.execute(
        "SELECT COALESCE(MAX(CAST(SUBSTR(slip_no, 11, 3) AS INTEGER)), 0) AS mx "
        "FROM payslips WHERE slip_no GLOB ? AND LENGTH(slip_no) = 13",
        (f"PS-{month}-???",)
    ).fetchone()
    db_max = row_max["mx"] if row_max else 0
    row = conn.execute("SELECT seq FROM payslip_seq WHERE month=?", (month,)).fetchone()
    seq = max(row["seq"] if row else 0, db_max) + 1
    while conn.execute("SELECT 1 FROM payslips WHERE slip_no=?",
                       (f"PS-{month}-{seq:03d}",)).fetchone():
        seq += 1
    return f"PS-{month}-{seq:03d}"


# ── Models ────────────────────────────────────────────────────────────────────

class PayslipIn(BaseModel):
    slip_no:             Optional[str]  = None
    contractor_id:       Optional[int]  = None
    data:                dict           = {}


# ── Routes ────────────────────────────────────────────────────────────────────

# 匯出之後的單向終結／下游狀態：不可修改、不可刪除
#: 第46班：`待審核`（送審中，要改請先退回）與 `已核准`（核准後鎖定，要改＝作廢重開）也鎖定。
_LOCKED_STATUSES = ("待審核", "已核准", "已匯出", "已簽回", "已付款", "已作廢")

_SIGNED_EXTS = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
_SIGNED_MAX_BYTES = 20 * 1024 * 1024   # 單檔 20MB


@router.get("/api/tax-rules")
def get_tax_rules(date: Optional[str] = None, version: Optional[str] = None,
                  authorization: str = Header(None)):
    """單一版規則（勞報單頁試算用）。`version` 優先；否則依 `date`（空＝今天）。
    回應另附 `status`（跨年提示），勞報單頁據此顯示「下一年度規則未設定」。"""
    _require_user(authorization, require_superadmin=True, module='payslip')
    versions = _lp.load_versions()
    if version:
        rules = _lp.rules_by_version(versions, version)
        if rules is None:
            raise HTTPException(404, f"找不到法規參數版本 {version}")
    else:
        try:
            rules = _lp.rules_for_date(versions, date or _lp.today())
        except ValueError as e:
            raise HTTPException(400, str(e))
    rules["status"] = _lp.year_status(versions, _lp.today())
    return rules


@router.get("/api/next-slip-no")
def next_slip_no(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True, module='payslip')
    month = datetime.now().strftime("%Y%m")
    conn  = get_db()
    conn.execute("INSERT INTO payslip_seq (month, seq) VALUES (?, 0) ON CONFLICT(month) DO NOTHING",
                 (month,))
    conn.commit()
    result = _peek_next_slip_no(conn, month)
    conn.close()
    return {"slip_no": result}


@router.get("/api/payslips")
def list_payslips(month: Optional[str] = None, contractor_id: Optional[int] = None,
                  limit: int = 100, offset: int = 0,
                  authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True, module='payslip')
    conn = get_db()
    sql = ("SELECT id, slip_no, contractor_id, contractor_name, income_type, "
           "gross_amount, tax_withheld, nhi_supplement, net_amount, "
           "payment_method, slip_date, status, tax_rules_version, "
           "export_count, created_by, created_at, updated_at, "
           "voided_at, voided_by, void_reason, signed_at, signed_by, "
           "payment_date, voucher_no, paid_by, paid_at, signed_files_json, "
           "planned_pay_date, approved_at, approved_by "
           "FROM payslips WHERE 1=1")
    params = []
    if month:
        sql += " AND slip_no LIKE ?"
        params.append(f"PS-{month}%")
    if contractor_id:
        sql += " AND contractor_id=?"
        params.append(contractor_id)
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    rows = conn.execute(sql, params).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM payslips WHERE 1=1" +
                         (" AND slip_no LIKE ?" if month else "") +
                         (" AND contractor_id=?" if contractor_id else ""),
                         ([f"PS-{month}%" if month else None] +
                          [contractor_id if contractor_id else None])
                         if (month or contractor_id) else []).fetchone()[0]
    conn.close()
    return {"items": [dict(r) for r in rows], "total": total}


@router.post("/api/payslips", status_code=201)
def create_payslip(body: PayslipIn, authorization: str = Header(None)):
    user  = _require_user(authorization, require_superadmin=True, module='payslip')
    now   = datetime.now().isoformat()
    month = datetime.now().strftime("%Y%m")
    d     = body.data
    d.pop("recalcTaxRules", None)
    dispatch_id = d.pop("dispatchId", None)                        # 第46班 P3（Q8）：建立時可選填來源派發（不存進單據 data）
    rules = _rules_for_slip(d)            # R1：依開單（給付）日期挑版本；沒有適用版本 ⇒ 400
    if dispatch_id not in (None, ""):
        try:
            dispatch_id = int(dispatch_id)
        except (TypeError, ValueError):
            raise HTTPException(400, "來源派發編號格式不正確")
        _brief = registry.single_provider("dispatch.brief")
        _c = get_db()
        try:
            if _brief is None or _brief(_c, dispatch_id) is None:
                raise HTTPException(400, "查無來源派發 #%s（或外包工班模組未安裝）" % dispatch_id)
        finally:
            _c.close()
    else:
        dispatch_id = None

    conn = get_db()
    conn.execute("INSERT INTO payslip_seq (month, seq) VALUES (?, 0) ON CONFLICT(month) DO NOTHING",
                 (month,))
    try:
        _apply_privacy_ack(d, None, user, conn)   # R3：已告知紀錄由伺服器蓋時間與人員（全文存檔跟著本交易）
    except HTTPException:
        conn.rollback()
        conn.close()
        raise

    try:
        _pb.resolve_on_write(conn, user, d, None, body.contractor_id, creating=True)
    except ValueError as e:
        conn.rollback()
        conn.close()
        raise HTTPException(400, str(e))
    slip_no = body.slip_no or d.get("slipNo") or _peek_next_slip_no(conn, month)
    if not _SLIP_NO_RE.match(slip_no):
        conn.close()
        raise HTTPException(400, f"勞報單號碼格式錯誤（須為 PS-YYYYMM-NNN）：{slip_no}")

    gross       = int(d.get("grossAmount", 0))
    income_type = d.get("incomeType", "9A")
    nationality = d.get("contractorNationality", "本國籍")
    has_union   = bool(d.get("contractorHasUnionInsurance", False))
    calc        = _calc(gross, income_type, nationality, has_union, rules)

    d["slipNo"]         = slip_no
    d["calc"]           = calc
    _freeze_rules(d, rules)

    def _insert(no: str):
        conn.execute("""
            INSERT INTO payslips
              (slip_no, contractor_id, contractor_name, income_type,
               gross_amount, tax_withheld, nhi_supplement, net_amount,
               payment_method, slip_date, status, tax_rules_version,
               data_json, created_by, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            no, body.contractor_id, d.get("contractorName", ""),
            income_type, gross,
            calc["taxWithheld"], calc["nhiSupplement"], calc["netAmount"],
            d.get("paymentMethod", "匯款"), d.get("slipDate", ""),
            "草稿", d["taxRulesVersion"],                                  # 第46班：新單一律草稿（原本 d["status"] 可由前端指定成已付款等）
            json.dumps(d, ensure_ascii=False),
            user["username"], now, now
        ))

    try:
        _insert(slip_no)
    except Exception:
        slip_no = _peek_next_slip_no(conn, month)
        d["slipNo"] = slip_no
        try:
            _insert(slip_no)
        except Exception:
            conn.close()
            raise HTTPException(409, "勞報單號碼衝突，請重試")

    seq_no = int(slip_no.split("-")[-1]) if slip_no.count("-") == 2 else 0
    if seq_no:
        conn.execute("INSERT INTO payslip_seq (month, seq) VALUES (?, ?) "
                     "ON CONFLICT(month) DO UPDATE SET seq=MAX(seq, excluded.seq)",
                     (month, seq_no))
    if dispatch_id is not None:                                     # 與勞報單同一個交易：連結失敗就整張不建
        from modules.payroll import payslip_links as _pl
        try:
            _pl.link(conn, slip_no, dispatch_id, user)
        except _pl.LinkError as e:
            conn.rollback()
            conn.close()
            raise HTTPException(e.status, str(e))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'payslip.create', 'payslip', slip_no,
           f"{slip_no}（{d.get('contractorName', '')}）")
    notify_module_activity("勞報單", "建立", user.get("display_name") or user["username"],
                            f"{slip_no}（{d.get('contractorName', '')}）", "payslips.html")
    return {"slip_no": slip_no, "calc": calc, "created_at": now,
            "taxRulesVersion": d["taxRulesVersion"], "privacyNotice": d.get("privacyNotice")}


@router.get("/api/payslips/{slip_no}")
def get_payslip(slip_no: str, authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True, module='payslip')
    conn = get_db()
    row = conn.execute("SELECT * FROM payslips WHERE slip_no=?", (slip_no,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "找不到此勞報單")
    r = dict(row)
    r["data"] = _pb.mask_data(user, json.loads(r.pop("data_json") or "{}"))      # F1：非最高管理者只看 ****末四碼
    r["bankMasked"] = not _pb.can_see_full(user)
    return r


@router.put("/api/payslips/{slip_no}")
def update_payslip(slip_no: str, body: PayslipIn, authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True, module='payslip')
    now    = datetime.now().isoformat()
    d      = body.data
    recalc = d.pop("recalcTaxRules", False) is True
    # 稽核 D-2（2026-09-26）：讀舊單 → 合併（已告知紀錄、快照）→ 整包寫回，全部在同一個寫交易裡。
    # 原本在交易外讀：兩人同時修改時，後寫的一方用「讀的當下」的舊單整包蓋回，
    # 別人剛記下的「已告知」紀錄被清掉（CUSTOMIZATION-SPEC §9.3「已記錄的不能被覆蓋或清除」）。
    # write_txn：區塊內任何例外（含 4xx）⇒ 回滾並關連線，不會把寫鎖留著。
    conn = get_db()
    with write_txn(conn):
        existing = conn.execute("SELECT status, tax_rules_version, data_json FROM payslips WHERE slip_no=?",
                                (slip_no,)).fetchone()
        if not existing:
            raise HTTPException(404, "找不到此勞報單")
        # 2026-08-28（模組逐步檢查）：匯出成 PDF 封存後（record_export 設 status='已匯出'）
        # 沒有取消匯出的還原機制，屬單向終結狀態；比照 delete_payslip() 既有的同一道鎖，
        # 避免封存的 PDF 內容跟資料庫最新金額/稅額悄悄兜不起來。
        if existing["status"] in _LOCKED_STATUSES:
            raise HTTPException(409, f"{existing['status']}的勞報單不可修改")
        try:
            old = json.loads(existing["data_json"] or "{}")
        except ValueError:
            old = {}
        # R1：修改舊單沿用**建立當時**的規則（資料庫裡的快照；前端送來的快照一律不採用）。
        #     只有使用者明確勾選「依給付日重新套用規則」才改用日期挑版。
        if recalc:
            rules = _rules_for_slip(d)
        else:
            rules = old.get("taxRulesSnapshot") if isinstance(old.get("taxRulesSnapshot"), dict) else None
            if rules is None:            # 本功能之前建立的舊單：依版本號查
                ver = existing["tax_rules_version"] or old.get("taxRulesVersion") or ""
                rules = _lp.rules_by_version(_lp.load_versions(), ver)
                if rules is None:
                    raise HTTPException(409, f"本單建立時的法規參數版本「{ver}」已不存在；"
                                             "請勾選「依給付日重新套用規則」後再存檔")
        _apply_privacy_ack(d, old, user, conn)
        try:
            _pb.resolve_on_write(conn, user, d, old, body.contractor_id, creating=False)
        except ValueError as e:
            raise HTTPException(400, str(e))

        gross       = int(d.get("grossAmount", 0))
        income_type = d.get("incomeType", "9A")
        nationality = d.get("contractorNationality", "本國籍")
        has_union   = bool(d.get("contractorHasUnionInsurance", False))
        calc        = _calc(gross, income_type, nationality, has_union, rules)

        d["slipNo"]          = slip_no
        d["calc"]            = calc
        _freeze_rules(d, rules)

        conn.execute("""
            UPDATE payslips SET
              contractor_id=?, contractor_name=?, income_type=?,
              gross_amount=?, tax_withheld=?, nhi_supplement=?, net_amount=?,
              payment_method=?, slip_date=?, status=?, tax_rules_version=?,
              data_json=?, updated_at=?
            WHERE slip_no=?
        """, (
            body.contractor_id, d.get("contractorName", ""),
            income_type, gross,
            calc["taxWithheld"], calc["nhiSupplement"], calc["netAmount"],
            d.get("paymentMethod", "匯款"), d.get("slipDate", ""),
            existing["status"], d["taxRulesVersion"],                 # 第46班：狀態只由送審／匯出／簽回／付款端點改，PUT 不採用前端送來的 status
            json.dumps(d, ensure_ascii=False), now, slip_no
        ))
        conn.commit()
    conn.close()
    _audit(_tok(authorization), 'payslip.update', 'payslip', slip_no,
           f"{slip_no}（{d.get('contractorName', '')}）",
           {"taxRulesVersion": d["taxRulesVersion"], "recalcTaxRules": recalc})
    return {"slip_no": slip_no, "calc": calc, "updated_at": now,
            "taxRulesVersion": d["taxRulesVersion"], "privacyNotice": d.get("privacyNotice")}


@router.delete("/api/payslips/{slip_no}", status_code=204)
def delete_payslip(slip_no: str, authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    conn = get_db()
    row = conn.execute("SELECT status FROM payslips WHERE slip_no=?", (slip_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "找不到此勞報單")
    if row["status"] in _LOCKED_STATUSES:
        conn.close()
        raise HTTPException(400, f"{row['status']}的勞報單須保留備查，不可刪除")
    conn.execute("DELETE FROM payslip_dispatch_links WHERE slip_no=?", (slip_no,))       # 第46班：派發連結隨草稿一併刪除（同一個交易，不留孤列）
    conn.execute("DELETE FROM payslips WHERE slip_no=?", (slip_no,))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'payslip.delete', 'payslip', slip_no, slip_no)
    notify_module_activity("勞報單", "刪除", user.get("display_name") or user["username"],
                            slip_no, "payslips.html")


@router.post("/api/payslips/{slip_no}/export")
def record_export(slip_no: str, authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True, module='payslip')
    conn = get_db()
    row = conn.execute("SELECT export_log, export_count, status FROM payslips WHERE slip_no=?",
                       (slip_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "找不到此勞報單")
    if row["status"] == "已作廢":
        conn.close()
        raise HTTPException(409, "已作廢的勞報單不可再匯出")
    if row["status"] in ("草稿", "待審核"):                          # 第46班：匯出只准核准之後（**不需要付款日**；付款日只在出納登錄付款時填）
        conn.close()
        raise HTTPException(409, "請先送審並核准後再匯出（目前「%s」）" % row["status"])
    log = json.loads(row["export_log"] or "[]")
    now = datetime.now().isoformat()
    new_count = (row["export_count"] or 0) + 1

    # 產生 PDF 並儲存存檔（失敗不中斷流程）
    archived = False
    try:
        from pdf_gen import generate_payslip_pdf_bytes
        pdf_bytes = generate_payslip_pdf_bytes(slip_no, mask_bank=False)       # 存檔（F2 資料夾）是完整的法定紀錄；誰按匯出都一樣
        with open(_archive_path(slip_no, new_count), "wb") as f:
            f.write(pdf_bytes)
        archived = True
    except Exception:
        pass

    log.append({
        "at": now,
        "by": user.get("display_name") or user["username"],
        "idx": new_count,
        "archived": archived,
    })
    conn.execute("UPDATE payslips SET export_count=?, export_log=?, updated_at=?, "
                 "status=CASE WHEN status IN ('已核准','已匯出') THEN '已匯出' ELSE status END "
                 "WHERE slip_no=?",
                 (new_count, json.dumps(log, ensure_ascii=False), now, slip_no))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'payslip.export', 'payslip', slip_no, slip_no, {'exportCount': new_count, 'archived': archived})
    return {"export_count": new_count}


@router.post("/api/payslips/{slip_no}/archive/{orig_idx}/record")
def record_archive_download(slip_no: str, orig_idx: int, authorization: str = Header(None)):
    """記錄「調閱存檔」動作（不產生新 PDF，不覆寫舊存檔，計次）。"""
    user = _require_user(authorization, require_superadmin=True, module='payslip')
    conn = get_db()
    row = conn.execute("SELECT export_log, export_count FROM payslips WHERE slip_no=?",
                       (slip_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "找不到此勞報單")
    log = json.loads(row["export_log"] or "[]")
    now = datetime.now().isoformat()
    new_count = (row["export_count"] or 0) + 1
    log.append({
        "at": now,
        "by": user.get("display_name") or user["username"],
        "idx": new_count,
        "redownload_of": orig_idx,
    })
    conn.execute("UPDATE payslips SET export_count=?, export_log=?, updated_at=? WHERE slip_no=?",
                 (new_count, json.dumps(log, ensure_ascii=False), now, slip_no))
    conn.commit()
    conn.close()
    notify_module_activity("勞報單", "調閱存檔", user.get("display_name") or user["username"],
                            slip_no, "payslips.html")
    _audit(_tok(authorization), 'payslip.archive_redownload', 'payslip', slip_no, slip_no, {'origIdx': orig_idx, 'exportCount': new_count})
    return {"export_count": new_count}


@router.get("/api/payslips/{slip_no}/archive/{idx}")
def get_archive_pdf(slip_no: str, idx: int, authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True, module='payslip')
    # 先確認 DB 裡真的有這張勞報單，避免 slip_no 被拿來做路徑穿越讀取任意檔案
    # （_archive_path 本身也有格式檢查，這裡是第二層防禦：即使格式合法，也必須
    # 對應到真實存在的勞報單）。
    conn = get_db()
    exists = conn.execute("SELECT 1 FROM payslips WHERE slip_no=?", (slip_no,)).fetchone()
    conn.close()
    if not exists:
        raise HTTPException(404, "找不到此勞報單")
    try:
        path = _archive_path(slip_no, idx)
    except ValueError:
        raise HTTPException(400, "勞報單號碼格式錯誤")
    if os.path.exists(path) and _pb.can_see_full(user):
        with open(path, "rb") as f:
            pdf_bytes = f.read()
    else:
        # 無存檔（舊記錄）→ 以當前資料重新產生；非最高管理者一律重新產生遮蔽版（存檔的那份帶完整帳號，只給最高管理者）
        from pdf_gen import generate_payslip_pdf_bytes
        try:
            pdf_bytes = generate_payslip_pdf_bytes(slip_no, mask_bank=not _pb.can_see_full(user))
        except ValueError as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            tid = trace_id()
            logger.exception("payslip pdf (inline) failed trace=%s", tid)
            raise HTTPException(500, f"PDF 產生失敗（代碼 {tid}）")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{slip_no}.pdf"'},
    )


@router.get("/api/payslips/{slip_no}/pdf-download")
def pdf_download(slip_no: str, authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True, module='payslip')
    from pdf_gen import generate_payslip_pdf_bytes
    try:
        pdf_bytes = generate_payslip_pdf_bytes(slip_no, mask_bank=not _pb.can_see_full(user))      # F1：非最高管理者 ****末四碼、不帶存簿影本
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:          # 第二道 428（COMPANY-SETUP-GATE §5）不可以被下面的 except Exception 吞成 500
        raise
    except Exception as e:
        tid = trace_id()
        logger.exception("payslip pdf (download) failed trace=%s", tid)
        raise HTTPException(500, f"PDF 產生失敗（代碼 {tid}）")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{slip_no}.pdf"'}
    )


# ── 作廢（已匯出 → 已作廢）／簽回（→ 已簽回）／出納付款（→ 已付款）────────────────────
# 簽回檔含個資（簽名、身分資料）＝F2：實體檔放在勞報單存檔目錄（與 PDF 同一個 F2 資料夾，鏡像流程照走）。


def _require_payer(authorization):
    """出納付款動作：財務角色或最高管理者（使用者 2026-10-07 Q1；與出納 IP-100 同一條 `has_cashier_access`，不再認 `cashier` 模組勾選）。"""
    from helpers.auth import has_cashier_access
    user = _require_user(authorization)
    if not has_cashier_access(user):
        raise HTTPException(403, "僅財務角色或最高管理者可執行")
    return user


class VoidIn(BaseModel):
    reason: str = ""


@router.post("/api/payslips/{slip_no}/void")
def void_payslip(slip_no: str, body: VoidIn, authorization: str = Header(None)):
    """作廢已匯出的勞報單（終結狀態，不可還原）。原因必填。"""
    user = _require_user(authorization, require_superadmin=True, module='payslip')
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(400, "請填寫作廢原因")
    conn = get_db()
    row = conn.execute("SELECT status FROM payslips WHERE slip_no=?", (slip_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "找不到此勞報單")
    if row["status"] == "已作廢":
        conn.close()
        raise HTTPException(409, "此勞報單已作廢")
    if row["status"] not in ("已匯出", "已核准"):                    # 第46班 Q5 預設：已核准（尚未匯出）也可作廢（原因必填，同已匯出）
        conn.close()
        raise HTTPException(409, "已簽回／已付款的勞報單不可直接作廢，請先退回簽回"
                            if row["status"] in ("已簽回", "已付款")
                            else "只有已核准或已匯出的勞報單可以作廢（草稿請直接刪除、待審核請先退回）")
    now = datetime.now().isoformat()
    who = user.get("display_name") or user["username"]
    conn.execute("UPDATE payslips SET status='已作廢', voided_at=?, voided_by=?, void_reason=?, "
                 "updated_at=? WHERE slip_no=? AND status IN ('已匯出','已核准')",
                 (now, who, reason, now, slip_no))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'payslip.void', 'payslip', slip_no, slip_no, {'reason': reason})
    notify_module_activity("勞報單", "作廢", who, slip_no, "payslips.html")
    return {"status": "已作廢", "voided_at": now, "voided_by": who, "void_reason": reason}


def _signed_path(slip_no: str, fid: str, ext: str) -> str:
    if not _SLIP_NO_RE.match(slip_no) or not re.fullmatch(r"[0-9a-f]{16}", fid):
        raise ValueError("invalid signed file name")
    if ext not in _SIGNED_EXTS:                       # 安全審查 W3：`ext` 來自 signed_files_json 的 metadata，不可以把任意字串拼進檔案路徑
        raise ValueError("invalid signed file extension")
    archive_dir = _archive_dir()
    os.makedirs(archive_dir, exist_ok=True)
    return os.path.join(archive_dir, f"{slip_no}_signed_{fid}{ext}")


@router.post("/api/payslips/{slip_no}/signed-files", status_code=201)
async def upload_signed_files(slip_no: str, files: List[UploadFile] = File(...),
                              authorization: str = Header(None)):
    """上傳對方簽回檔：已匯出 → 已簽回（已簽回可再補傳）。"""
    user = _require_user(authorization, require_superadmin=True, module='payslip')
    who = user.get("display_name") or user["username"]
    if not _SLIP_NO_RE.match(slip_no):
        raise HTTPException(400, "勞報單號碼格式錯誤")
    conn = get_db()
    try:
        row = conn.execute("SELECT status, signed_files_json FROM payslips WHERE slip_no=?",
                           (slip_no,)).fetchone()
        if not row:
            raise HTTPException(404, "找不到此勞報單")
        if row["status"] not in ("已匯出", "已簽回"):
            raise HTTPException(409, "只有已匯出的勞報單可以上傳簽回檔")
        staged = []
        for up in files:
            ext = os.path.splitext(up.filename or "")[1].lower()
            if ext not in _SIGNED_EXTS:
                raise HTTPException(400, f"不支援的檔案格式：{up.filename}（僅支援 pdf/jpg/png）")
            raw = await up.read()
            if not raw:
                raise HTTPException(400, f"檔案是空的：{up.filename}")
            if len(raw) > _SIGNED_MAX_BYTES:
                raise HTTPException(400, f"檔案過大：{up.filename}（單檔上限 20MB）")
            _check_upload_magic(up.filename or "", ext, raw, "payslips", who)
            staged.append((up.filename or "", ext, raw))
        now = datetime.now().isoformat()
        new_files = []
        for name, ext, raw in staged:
            fid = uuid.uuid4().hex[:16]
            with open(_signed_path(slip_no, fid, ext), "wb") as f:
                f.write(raw)
            new_files.append({"id": fid, "filename": name, "ext": ext, "size": len(raw),
                              "uploadedBy": who, "uploadedAt": now})
        existing = json.loads(row["signed_files_json"] or "[]")
        conn.execute("UPDATE payslips SET signed_files_json=?, updated_at=?, status='已簽回', "
                     "signed_at=CASE WHEN signed_at='' THEN ? ELSE signed_at END, "
                     "signed_by=CASE WHEN signed_by='' THEN ? ELSE signed_by END "
                     "WHERE slip_no=?",
                     (json.dumps(existing + new_files, ensure_ascii=False), now, now, who, slip_no))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), 'payslip.signed_upload', 'payslip', slip_no,
           f"{slip_no}（{len(new_files)} 個檔案）")
    return {"status": "已簽回", "added": len(new_files),
            "files": [{k: v for k, v in f.items()} for f in new_files]}


@router.get("/api/payslips/{slip_no}/signed-files/{file_id}")
def get_signed_file(slip_no: str, file_id: str, authorization: str = Header(None)):
    """讀簽回檔：最高管理者（勞報單模組），或出納（付款時要看簽回檔）。"""
    from helpers.auth import has_finance_access
    user = _require_user(authorization)
    if not has_finance_access(user):
        raise HTTPException(403, "僅財務角色或最高管理者可檢視")
    conn = get_db()
    try:
        row = conn.execute("SELECT signed_files_json FROM payslips WHERE slip_no=?", (slip_no,)).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(404, "找不到此勞報單")
    meta = next((f for f in json.loads(row["signed_files_json"] or "[]") if f.get("id") == file_id), None)
    if not meta:
        raise HTTPException(404, "找不到指定的檔案")
    try:
        path = _signed_path(slip_no, file_id, meta.get("ext", ""))
    except ValueError:
        raise HTTPException(400, "檔案識別格式錯誤")
    if not os.path.isfile(path):
        raise HTTPException(404, "簽回檔實體檔案不存在")
    with open(path, "rb") as f:
        data = f.read()
    return Response(content=data, media_type=_SIGNED_EXTS.get(meta.get("ext", ""), "application/octet-stream"),
                    headers={"Content-Disposition": "inline"})


@router.delete("/api/payslips/{slip_no}/signed-files/{file_id}")
def delete_signed_file(slip_no: str, file_id: str, authorization: str = Header(None)):
    """刪除簽回檔（僅「已簽回」；已付款不可動）。刪光後退回「已匯出」。實體檔保留備查（F2，不刪）。"""
    _require_user(authorization, require_superadmin=True, module='payslip')
    conn = get_db()
    try:
        row = conn.execute("SELECT status, signed_files_json FROM payslips WHERE slip_no=?",
                           (slip_no,)).fetchone()
        if not row:
            raise HTTPException(404, "找不到此勞報單")
        if row["status"] != "已簽回":
            raise HTTPException(409, "只有已簽回（尚未付款）的勞報單可以刪除簽回檔")
        files = json.loads(row["signed_files_json"] or "[]")
        if not any(f.get("id") == file_id for f in files):
            raise HTTPException(404, "找不到指定的檔案")
        remaining = [f for f in files if f.get("id") != file_id]
        if remaining:
            conn.execute("UPDATE payslips SET signed_files_json=?, updated_at=? WHERE slip_no=?",
                         (json.dumps(remaining, ensure_ascii=False), datetime.now().isoformat(), slip_no))
        else:
            conn.execute("UPDATE payslips SET signed_files_json='[]', status='已匯出', signed_at='', "
                         "signed_by='', updated_at=? WHERE slip_no=?", (datetime.now().isoformat(), slip_no))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), 'payslip.signed_delete', 'payslip', slip_no, slip_no)
    return {"ok": True, "status": "已簽回" if remaining else "已匯出"}


@router.post("/api/payslips/{slip_no}/unsign")
def unsign_payslip(slip_no: str, authorization: str = Header(None)):
    """退回簽回：已簽回（未付款）→ 已匯出，才可作廢。簽回檔保留備查。"""
    _require_user(authorization, require_superadmin=True, module='payslip')
    conn = get_db()
    try:
        row = conn.execute("SELECT status FROM payslips WHERE slip_no=?", (slip_no,)).fetchone()
        if not row:
            raise HTTPException(404, "找不到此勞報單")
        if row["status"] != "已簽回":
            raise HTTPException(409, "只有已簽回（尚未付款）的勞報單可以退回簽回；已付款請先由出納退回")
        conn.execute("UPDATE payslips SET status='已匯出', signed_at='', signed_by='', updated_at=? "
                     "WHERE slip_no=?", (datetime.now().isoformat(), slip_no))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), 'payslip.unsign', 'payslip', slip_no, slip_no)
    return {"status": "已匯出"}


class PayIn(BaseModel):
    payment_date: str = ""
    voucher_no: str = ""


@router.post("/api/payslips/{slip_no}/mark-paid")
def payslip_mark_paid(slip_no: str, body: PayIn, authorization: str = Header(None)):
    """出納填付款日期＋既有傳票單號：已核准／已匯出／已簽回 → 已付款（Q4：不需已簽回）。付款日期是營運報表成本（IP-9）的歸月依據。"""
    user = _require_payer(authorization)
    try:
        pd = datetime.strptime((body.payment_date or "").strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "付款日期格式須為 YYYY-MM-DD")
    vno = (body.voucher_no or "").strip()
    if not vno:
        raise HTTPException(400, "請填寫傳票單號")
    who = user.get("display_name") or user["username"]
    from modules.payroll import payslip_payables as _pp
    conn = get_db()
    try:
        try:
            res = _pp.mark_payslip_paid(conn, slip_no, pd, vno, who)             # 第46班：付款唯一實作（與出納 IP-100 共用）；已核准即可付款（Q4）
        except _pp.PayError as e:
            raise HTTPException(e.status, str(e))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), 'payslip.paid', 'payslip', slip_no, slip_no,
           {'paymentDate': pd, 'voucherNo': vno})
    _pp._Payables.after_paid(slip_no)                                        # commit 之後：通知送審人已付款（不含金額）
    return res


@router.post("/api/payslips/{slip_no}/unpay")
def payslip_unpay(slip_no: str, authorization: str = Header(None)):
    """付款填錯時退回：已付款 → 付款前最近的狀態（有簽回檔＝已簽回；匯出過＝已匯出；否則已核准；由資料推得），清付款日期與傳票單號。"""
    _require_payer(authorization)
    from modules.payroll import payslip_payables as _pp
    conn = get_db()
    try:
        row = conn.execute("SELECT status, signed_files_json, export_count FROM payslips WHERE slip_no=?", (slip_no,)).fetchone()
        if not row:
            raise HTTPException(404, "找不到此勞報單")
        if row["status"] != "已付款":
            raise HTTPException(409, "只有已付款的勞報單可以退回")
        via = conn.execute("SELECT data_json FROM payslips WHERE slip_no=?", (slip_no,)).fetchone()["data_json"]
        try:
            via = (json.loads(via or "{}") or {}).get("paid_via_remit") or ""
        except (TypeError, ValueError):
            via = ""
        if via:
            raise HTTPException(409, "此勞報單由承攬商匯款單 %s 付款，請到該匯款單取消已匯款" % via)
        back = _pp.unpay_status(row)
        conn.execute("UPDATE payslips SET status=?, payment_date='', voucher_no='', "
                     "paid_by='', paid_at='', updated_at=? WHERE slip_no=?",
                     (back, datetime.now().isoformat(), slip_no))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), 'payslip.unpay', 'payslip', slip_no, slip_no, {'backTo': back})
    return {"status": back}
