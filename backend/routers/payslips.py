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

# 匯出存檔目錄（backend/export_archive/）
#
# 2026-09-22（§12 BK19）：這裡原本在**模組層**就 `os.makedirs()`。
# 🔑 那表示「有人 import 這支檔案」就會在磁碟上長出一個目錄 ——
# ☠️ 而 import 會發生在測試、健檢工具、任何一支腳本裡，
#    全都繞過測試的暫存隔離（隔離是在 fixture 裡建立的，比 import 晚）。
# ⇒ 目錄改成**用到的時候才建**：`_archive_path()` 本來就已經在寫入前
#    `os.makedirs(archive_dir, exist_ok=True)`，所以這一行純粹是多的。
# 📌 判準是〈降級之後它還是會動〉的反面：這一行拿掉之後**行為完全不變**，
#    少掉的只有「匯入即寫磁碟」這個副作用。
_ARCHIVE_DIR = os.path.join(os.path.dirname(__file__), "..", "export_archive")

# 唯一合法格式，防止 slip_no 被用來做路徑穿越（2026-08-24 安全審查修正）：
# _archive_path() 直接用 slip_no 拼檔案路徑，slip_no 若可被前端任意指定
# （create_payslip 曾允許 body.slip_no 覆蓋自動產生的序號，完全沒驗證格式）
# 就能組出 "..\..\..\x" 這種跳出 export_archive/ 目錄的路徑。
_SLIP_NO_RE = re.compile(r"^PS-\d{6}-\d{3}$")

def _archive_path(slip_no: str, idx: int) -> str:
    if not _SLIP_NO_RE.match(slip_no):
        raise ValueError(f"invalid slip_no: {slip_no!r}")
    # demo 帳號：存至隔離目錄（reset_demo_db() 每次登入清空），不進真實存檔
    archive_dir = DEMO_PAYSLIP_ARCHIVE_DIR if is_demo_mode() else _ARCHIVE_DIR
    os.makedirs(archive_dir, exist_ok=True)
    return os.path.join(archive_dir, f"{slip_no}_{idx}.pdf")


# ── 稅務計算 ──────────────────────────────────────────────────────────────────

def _get_tax_rules() -> dict:
    return _get_setting("tax_rules", {
        "version": "2026",
        "resident": {
            "50":  {"tax_rate": 0.05, "tax_threshold": 90501},
            "9A":  {"tax_rate": 0.10, "tax_threshold": 20010},
            "9B":  {"tax_rate": 0.10, "tax_threshold": 20010}
        },
        "non_resident": {
            "50":  {"tax_rate": 0.18, "tax_threshold": 0, "low_salary_rate": 0.06},
            "9A":  {"tax_rate": 0.20, "tax_threshold": 0},
            "9B":  {"tax_rate": 0.20, "tax_threshold": 5001}
        },
        "nhi": {
            "rate": 0.0211,
            "max_single_payment": 10000000,
            "thresholds": {"50": 29500, "9A": 20000, "9B": 20000}
        },
        "minimum_wage": {"monthly": 29500}
    })


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
def get_tax_rules(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True, module='payslip')
    return _get_tax_rules()


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
    rules = _get_tax_rules()

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
    d["taxRulesVersion"] = rules.get("version", "2026")

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
            d.get("status", "草稿"), rules.get("version", "2026"),
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
    return {"slip_no": slip_no, "calc": calc, "created_at": now}


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
    _require_user(authorization, require_superadmin=True, module='payslip')
    conn0 = get_db()
    existing = conn0.execute("SELECT status FROM payslips WHERE slip_no=?", (slip_no,)).fetchone()
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
    rules = _get_tax_rules()

    gross       = int(d.get("grossAmount", 0))
    income_type = d.get("incomeType", "9A")
    nationality = d.get("contractorNationality", "本國籍")
    has_union   = bool(d.get("contractorHasUnionInsurance", False))
    calc        = _calc(gross, income_type, nationality, has_union, rules)

    d["slipNo"]          = slip_no
    d["calc"]            = calc
    d["taxRulesVersion"] = rules.get("version", "2026")

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
        d.get("status", "草稿"), rules.get("version", "2026"),
        json.dumps(d, ensure_ascii=False), now, slip_no
    ))
    conn.commit()
    conn.close()
    if res.rowcount == 0:
        raise HTTPException(404, "找不到此勞報單")
    _audit(_tok(authorization), 'payslip.update', 'payslip', slip_no,
           f"{slip_no}（{d.get('contractorName', '')}）")
    return {"slip_no": slip_no, "calc": calc, "updated_at": now}


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
