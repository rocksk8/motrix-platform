"""2026-09-02 反派視角複查 MOTRIX-ERP-QUICK.md 營運報表模組，抓到並修復 5 項：
①Excel 匯出未防公式注入（CWE-1236）——set_row()/xl_safe() 補上（2026-09-25 下沉 helpers/xlsx_out.py）
②GET /api/settings/operating-targets 完全沒有角色檢查，任何登入者皆可讀取年度目標
③《月支出》「其他支出」月度加總用精算完結日期分月，跟明細顯示的 expenseDate 對不上
④_parse_period() 格式錯誤（如 2026-13）會丟未捕捉例外變成 500
⑤業務員績效/目標達成率用可變動的顯示名稱字串比對，改名後歷史業績被靜默拆散
"""
import json

import pytest
from fastapi import HTTPException


def _sync_extra_to_table(conn, quote_no):
    """把剛種進 data_json 的 settlement.extraItems 搬進 case_extra_expenses。

    2026-09-11（migration v75）之後額外支出住在獨立資料表，data_json 裡那份只是
    唯讀備份、報表不再讀它。用 migration 自己那支搬移函式，欄位對應與歸月的
    fallback 才不會跟正式路徑漂移。"""
    import db as _db
    import json as _json
    row = conn.execute(
        "SELECT data_json, sales_person FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if not row:
        return
    _db._move_extra_items_for_quote(
        conn, quote_no, _json.loads(row["data_json"] or "{}"), row["sales_person"] or "")

def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _insert_case(quote_no, quote_date="2026-01-05", deal_tag="已成案",
                  payment_items=None, settlement=None, total=100000,
                  sales_person=None, sales_person_id=None, extra_data=None):
    import db
    conn = db.get_db()
    try:
        data = {"dealTag": deal_tag}
        if payment_items is not None:
            data["caseRecord"] = {"payment": {"items": payment_items}}
        if settlement is not None:
            data["settlement"] = settlement
        if extra_data:
            data.update(extra_data)
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date, sales_person, sales_person_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", total, round(total / 1.05),
             json.dumps(data, ensure_ascii=False), "2026-01-01T00:00:00", "2026-01-01T00:00:00",
             deal_tag, quote_date, sales_person, sales_person_id),
        )
        conn.commit()
    finally:
        conn.close()


# ── ①Excel 公式注入防護 ──────────────────────────────────────────────────────

def test_xl_safe_neutralizes_formula_triggers():
    from helpers.xlsx_out import xl_safe
    assert xl_safe("=HYPERLINK(\"http://evil\",\"x\")").startswith("'=")
    assert xl_safe("+1+1").startswith("'+")
    assert xl_safe("-1").startswith("'-")
    assert xl_safe("@SUM(1)").startswith("'@")
    assert xl_safe("正常客戶名稱") == "正常客戶名稱"
    assert xl_safe(12345) == 12345  # 非字串（金額欄位）原樣通過


def test_set_row_writes_malicious_string_as_literal_text():
    import openpyxl
    from helpers.xlsx_out import set_row
    wb = openpyxl.Workbook()
    ws = wb.active
    set_row(ws, 1, ["=cmd|'/c calc'!A1", "正常文字"])
    cell = ws.cell(row=1, column=1)
    # openpyxl 對開頭 "=" 的字串預設會標成公式（data_type == 'f'）；修復後
    # 應該被中和成純文字，data_type 仍是字串。
    assert cell.data_type != "f"
    assert cell.value.startswith("'=")


# ── ②operating-targets 權限 ──────────────────────────────────────────────────

def test_operating_targets_get_requires_admin(client, make_user):
    username, password = make_user(role="engineer")
    token = _login(client, username, password)
    r = client.get("/api/settings/operating-targets", headers=_auth(token))
    assert r.status_code == 403, r.text


def test_operating_targets_get_allows_admin(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)
    r = client.get("/api/settings/operating-targets", headers=_auth(token))
    assert r.status_code == 200, r.text


# ── ③《其他支出》月度分桶改用 expenseDate ───────────────────────────────────


# ── ④period 格式驗證 ─────────────────────────────────────────────────────────


# ── ⑤業務員改名後績效/目標達成率不應被拆散 ──────────────────────────────────


