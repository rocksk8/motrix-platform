"""勞報單 CRUD、稅務計算、序號、PDF 下載 — superadmin only."""
import json
import logging
import math
import os
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import Response
from pydantic import BaseModel

from db import get_db, is_demo_mode, DEMO_PAYSLIP_ARCHIVE_DIR
from helpers import _require_user, _tok, _audit, _get_setting, notify_module_activity
from helpers.errors import trace_id

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


def _apply_privacy_ack(d: dict, old, user: dict) -> None:
    """R3（個資法 §8）：「已告知當事人」由伺服器蓋時間與人員；已記錄的不可被前端覆蓋或清除。
    前端只送 `privacyNoticeAcked: true`；送來的 `privacyNotice` 一律不採用。"""
    from helpers import privacy_notice as _pn
    requested = d.pop("privacyNoticeAcked", False) is True
    d.pop("privacyNotice", None)
    existing = (old or {}).get("privacyNotice") if isinstance(old, dict) else None
    rec = _pn.merge_ack(existing, requested, user,
                        _pn.current_notice() if requested and not existing else "")
    if rec:
        d["privacyNotice"] = rec


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
            tax_withheld = math.floor(gross * tax_rate)
    else:
        r = rules["non_resident"][income_type]
        if gross >= r.get("tax_threshold", 0):
            if "low_salary_rate" in r:
                min_1_5 = rules["minimum_wage"]["monthly"] * 1.5
                tax_rate = r["low_salary_rate"] if gross <= min_1_5 else r["tax_rate"]
            else:
                tax_rate = r["tax_rate"]
            tax_withheld = math.floor(gross * tax_rate)

    nhi_supplement = 0
    nhi_rate = 0.0
    if not has_union:
        threshold = rules["nhi"]["thresholds"][income_type]
        if gross >= threshold:
            nhi_rate = rules["nhi"]["rate"]
            base = min(gross, rules["nhi"]["max_single_payment"])
            nhi_supplement = round(base * nhi_rate)

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
           "export_count, created_by, created_at, updated_at "
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
    rules = _rules_for_slip(d)            # R1：依開單（給付）日期挑版本；沒有適用版本 ⇒ 400
    _apply_privacy_ack(d, None, user)     # R3：已告知紀錄由伺服器蓋時間與人員

    conn = get_db()
    conn.execute("INSERT INTO payslip_seq (month, seq) VALUES (?, 0) ON CONFLICT(month) DO NOTHING",
                 (month,))

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
            d.get("status", "草稿"), d["taxRulesVersion"],
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
    _require_user(authorization, require_superadmin=True, module='payslip')
    conn = get_db()
    row = conn.execute("SELECT * FROM payslips WHERE slip_no=?", (slip_no,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "找不到此勞報單")
    r = dict(row)
    r["data"] = json.loads(r.pop("data_json") or "{}")
    return r


@router.put("/api/payslips/{slip_no}")
def update_payslip(slip_no: str, body: PayslipIn, authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True, module='payslip')
    conn0 = get_db()
    existing = conn0.execute("SELECT status, tax_rules_version, data_json FROM payslips WHERE slip_no=?",
                             (slip_no,)).fetchone()
    conn0.close()
    if not existing:
        raise HTTPException(404, "找不到此勞報單")
    # 2026-08-28（模組逐步檢查）：匯出成 PDF 封存後（record_export 設 status='已匯出'）
    # 沒有取消匯出的還原機制，屬單向終結狀態；比照 delete_payslip() 既有的同一道鎖，
    # 避免封存的 PDF 內容跟資料庫最新金額/稅額悄悄兜不起來。
    if existing["status"] == "已匯出":
        raise HTTPException(409, "已匯出的勞報單不可修改")
    now   = datetime.now().isoformat()
    d     = body.data
    try:
        old = json.loads(existing["data_json"] or "{}")
    except ValueError:
        old = {}
    # R1：修改舊單沿用**建立當時**的規則（資料庫裡的快照；前端送來的快照一律不採用）。
    #     只有使用者明確勾選「依給付日重新套用規則」才改用日期挑版。
    recalc = d.pop("recalcTaxRules", False) is True
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
    _apply_privacy_ack(d, old, user)

    gross       = int(d.get("grossAmount", 0))
    income_type = d.get("incomeType", "9A")
    nationality = d.get("contractorNationality", "本國籍")
    has_union   = bool(d.get("contractorHasUnionInsurance", False))
    calc        = _calc(gross, income_type, nationality, has_union, rules)

    d["slipNo"]          = slip_no
    d["calc"]            = calc
    _freeze_rules(d, rules)

    conn = get_db()
    res = conn.execute("""
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
        d.get("status", "草稿"), d["taxRulesVersion"],
        json.dumps(d, ensure_ascii=False), now, slip_no
    ))
    conn.commit()
    conn.close()
    if res.rowcount == 0:
        raise HTTPException(404, "找不到此勞報單")
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
    if row["status"] == "已匯出":
        conn.close()
        raise HTTPException(400, "已匯出的勞報單不可刪除")
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
    row = conn.execute("SELECT export_log, export_count FROM payslips WHERE slip_no=?",
                       (slip_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "找不到此勞報單")
    log = json.loads(row["export_log"] or "[]")
    now = datetime.now().isoformat()
    new_count = (row["export_count"] or 0) + 1

    # 產生 PDF 並儲存存檔（失敗不中斷流程）
    archived = False
    try:
        from pdf_gen import generate_payslip_pdf_bytes
        pdf_bytes = generate_payslip_pdf_bytes(slip_no)
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
    conn.execute("UPDATE payslips SET export_count=?, export_log=?, status='已匯出', updated_at=? "
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
    _require_user(authorization, require_superadmin=True, module='payslip')
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
    if os.path.exists(path):
        with open(path, "rb") as f:
            pdf_bytes = f.read()
    else:
        # 無存檔（舊記錄）→ 以當前資料重新產生
        from pdf_gen import generate_payslip_pdf_bytes
        try:
            pdf_bytes = generate_payslip_pdf_bytes(slip_no)
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
    _require_user(authorization, require_superadmin=True, module='payslip')
    from pdf_gen import generate_payslip_pdf_bytes
    try:
        pdf_bytes = generate_payslip_pdf_bytes(slip_no)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        tid = trace_id()
        logger.exception("payslip pdf (download) failed trace=%s", tid)
        raise HTTPException(500, f"PDF 產生失敗（代碼 {tid}）")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{slip_no}.pdf"'}
    )
