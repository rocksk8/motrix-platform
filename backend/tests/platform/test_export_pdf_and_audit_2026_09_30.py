# -*- coding: utf-8 -*-
"""使用者規則（2026-09-30，第 27 班）：每一個 Excel 匯出都要同時提供 PDF；每一次匯出都要留紀錄（action `export.xlsx`／`export.pdf`，
detail 只有 module／篩選摘要／列數，不含個資值）。

三塊：
① AST 守門（全程式庫）：回 xlsx 的端點 ⇒ 必須 `@export_logged("xlsx", …)`，且同檔有 PDF 姊妹（`add_pdf_sibling(router, path, <handler>, …)`，
   或同 module／name 的既有 `@export_logged("pdf", …)` 端點）；回 CSV／JSON 檔的匯出 ⇒ 必須呼叫 `log_export(`。含反向控制（合成原始碼）。
② `helpers/xlsx_out.py` 的單元題：篩選摘要不洩個資、xlsx→HTML（合併儲存格／跳脫／數字格式／截斷）、稽核列內容。
③ `add_pdf_sibling` 的行為題（合成 FastAPI app，PDF 引擎換成假的）：同參數、同權限來源、PDF 冷卻、不吃 xlsx 冷卻、公司資料閘門、稽核。
"""
import ast
import io
import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

# ══ ① AST 守門 ══════════════════════════════════════════════════════════════════════

XLSX_MARK = "spreadsheetml"
CSV_MARKS = ("text/csv",)


def _deco_call(dec):
    """裝飾器節點 ⇒ (函式名, args, keywords)；不是呼叫 ⇒ None。"""
    if isinstance(dec, ast.Call):
        f = dec.func
        name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
        return name, dec.args, {k.arg: k.value for k in dec.keywords}
    return None


def _const(n):
    return n.value if isinstance(n, ast.Constant) else None


def _export_meta(fn):
    """函式上的 `@export_logged(fmt, module, name)` ⇒ (fmt, module, name)；沒有 ⇒ None。"""
    for dec in fn.decorator_list:
        c = _deco_call(dec)
        if c and c[0] == "export_logged":
            a, kw = c[1], c[2]
            vals = [_const(x) for x in a[:3]]
            fmt = vals[0] if vals else _const(kw.get("fmt"))
            module = vals[1] if len(vals) > 1 else _const(kw.get("module"))
            name = vals[2] if len(vals) > 2 else _const(kw.get("name"))
            return fmt, module, name
    return None


def _has_const(fn, marks):
    for n in ast.walk(fn):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and any(m in n.value for m in marks):
            return True
    return False


def _calls(node, fname):
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if (isinstance(f, ast.Name) and f.id == fname) or (isinstance(f, ast.Attribute) and f.attr == fname):
                yield n


def scan_source(src, label="<src>"):
    """⇒ [問題字串]。"""
    tree = ast.parse(src)
    fns = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    siblings = set()
    for c in _calls(tree, "add_pdf_sibling"):
        h = c.args[2] if len(c.args) > 2 else next((k.value for k in c.keywords if k.arg == "handler"), None)
        if isinstance(h, ast.Name):
            siblings.add(h.id)
    pdf_names = {(m[1], m[2]) for f in fns for m in [_export_meta(f)] if m and m[0] == "pdf"}
    problems = []
    for fn in fns:
        if fn.name.startswith("_") and _export_meta(fn) is None and not _has_const(fn, (XLSX_MARK,)):
            continue
        meta = _export_meta(fn)
        if _has_const(fn, (XLSX_MARK,)) and not _is_helper_builder(fn):
            if not meta or meta[0] != "xlsx":
                problems.append("%s:%s 回 xlsx 卻沒有 @export_logged(\"xlsx\", …)（匯出必須留紀錄）" % (label, fn.name))
                continue
            if fn.name not in siblings and (meta[1], meta[2]) not in pdf_names:
                problems.append("%s:%s 沒有 PDF 姊妹（add_pdf_sibling(router, path, %s, …) 或同 module／name 的 @export_logged(\"pdf\", …) 端點）" % (label, fn.name, fn.name))
        elif _has_const(fn, CSV_MARKS):
            if not meta and not list(_calls(fn, "log_export")):
                problems.append("%s:%s 回 CSV 匯出卻沒有 log_export(…)（匯出必須留紀錄）" % (label, fn.name))
    return problems


def _is_helper_builder(fn):
    """建 workbook 的內部函式（不是端點）：沒有 route 裝飾器。端點才需要稽核與姊妹。"""
    return not any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in ("get", "post", "put", "patch", "delete", "api_route")
                   for d in fn.decorator_list)


def _endpoint_files():
    out = []
    for base in ("modules", "routers", "helpers"):
        for p in (BACKEND / base).rglob("*.py"):
            if "/tests/" in p.as_posix() or "__pycache__" in p.parts:
                continue
            out.append(p)
    return sorted(out)


def test_every_xlsx_and_csv_export_endpoint_is_logged_and_xlsx_has_a_pdf_sibling():
    problems, seen_xlsx = [], 0
    for p in _endpoint_files():
        src = p.read_text(encoding="utf-8-sig")
        if XLSX_MARK not in src and "text/csv" not in src:
            continue
        problems += scan_source(src, p.relative_to(BACKEND).as_posix())
        seen_xlsx += src.count("@export_logged(\"xlsx\"")
    assert seen_xlsx >= 8, "守門的對象不見了：預期至少 8 支 xlsx 匯出端點都掛了 @export_logged（實際 %d）" % seen_xlsx
    assert problems == [], "\n".join(problems)


SYN_OK = '''
from helpers.xlsx_out import add_pdf_sibling, export_logged
@router.get("/x")
@export_logged("xlsx", "m", "x")
def x_export(authorization=None):
    return Response(content=b"", media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
add_pdf_sibling(router, "/x/pdf", x_export, module="m", name="x")
'''


def test_scanner_accepts_a_compliant_endpoint():
    assert scan_source(SYN_OK) == []


@pytest.mark.parametrize("mutate,expect", [
    (lambda s: s.replace('@export_logged("xlsx", "m", "x")\n', ""), "沒有 @export_logged"),
    (lambda s: s.replace('add_pdf_sibling(router, "/x/pdf", x_export, module="m", name="x")', ""), "沒有 PDF 姊妹"),
    (lambda s: s.replace("x_export, module", "other_fn, module"), "沒有 PDF 姊妹"),
    (lambda s: s.replace('@export_logged("xlsx", "m", "x")', '@export_logged("pdf", "m", "x")'), "沒有 @export_logged(\"xlsx\""),
])
def test_scanner_reverse_controls_xlsx(mutate, expect):
    probs = scan_source(mutate(SYN_OK))
    assert probs and expect in probs[0], probs


def test_scanner_accepts_an_existing_pdf_endpoint_with_the_same_module_and_name_as_the_sibling():
    src = SYN_OK.replace('add_pdf_sibling(router, "/x/pdf", x_export, module="m", name="x")', '''
@router.get("/x/pdf")
@export_logged("pdf", "m", "x")
def x_pdf(authorization=None):
    return Response(content=b"", media_type="application/pdf")
''')
    assert scan_source(src) == []
    assert scan_source(src.replace('@export_logged("pdf", "m", "x")', '@export_logged("pdf", "m", "other")'))


def test_scanner_csv_needs_a_log_call():
    bad = '@router.get("/c")\ndef c(authorization=None):\n    return Response("a,b", media_type="text/csv; charset=utf-8")\n'
    ok = '@router.get("/c")\ndef c(authorization=None):\n    log_export(authorization, "csv", "m", "c")\n    return Response("a,b", media_type="text/csv; charset=utf-8")\n'
    assert scan_source(bad) and scan_source(ok) == []


def test_internal_workbook_builders_without_a_route_are_not_treated_as_endpoints():
    src = 'def _build(rows):\n    return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"\n'
    assert scan_source(src) == []


# ══ ② helpers/xlsx_out 單元題 ═══════════════════════════════════════════════════════

def test_summarize_filters_keeps_numbers_dates_and_codes_and_masks_free_text():
    from helpers.xlsx_out import summarize_filters
    s = summarize_filters({"year": 2026, "month": 9, "start": "2026-09-01", "code": "T100", "customer": "王大明", "note": "with space",
                           "flag": True, "ids": ["a", "b", "c"], "authorization": "Bearer secret", "none": None,
                           "body": {"quote_nos": ["MQ-1", "MQ-2"], "keyword": "陳小華", "days": 3}})
    assert s["year"] == 2026 and s["month"] == 9 and s["start"] == "2026-09-01" and s["code"] == "T100" and s["flag"] is True
    assert s["customer"] == "<text:3>" and s["note"] == "<text:10>" and s["ids"] == "<list:3>"
    assert s["body.quote_nos"] == "<list:2>" and s["body.keyword"] == "<text:3>" and s["body.days"] == 3
    assert "authorization" not in s and "none" not in s
    blob = json.dumps(s, ensure_ascii=False)
    assert "王大明" not in blob and "陳小華" not in blob and "secret" not in blob


def test_summarize_filters_flattens_pydantic_models():
    from pydantic import BaseModel
    from helpers.xlsx_out import summarize_filters

    class B(BaseModel):
        quote_nos: list
        who: str = "李四"
    s = summarize_filters({"body": B(quote_nos=[1, 2])})
    assert s == {"body.quote_nos": "<list:2>", "body.who": "<text:2>"}


def _wb_bytes(fill=None):
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "報表<1>"
    ws.merge_cells("A1:C1")
    ws["A1"] = "標題 & <b>粗</b>"
    ws["A1"].font = Font(bold=True)
    ws["A2"], ws["B2"], ws["C2"] = "名稱", "金額", "比率"
    ws["A3"], ws["B3"], ws["C3"] = "<script>alert(1)</script>", 1234567.891, 0.256
    ws["B3"].number_format = "#,##0.00"
    ws["C3"].number_format = "0.0%"
    ws["A4"], ws["B4"] = "整數", 42
    ws["A4"].fill = PatternFill("solid", fgColor="FFFF00")
    ws.column_dimensions["A"].width = 30
    wb.create_sheet("隱藏").sheet_state = "hidden"
    if fill:
        for i in range(5, fill + 5):
            ws.cell(row=i, column=1, value="r%d" % i)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_xlsx_to_html_renders_merges_escapes_formats_and_skips_hidden_sheets():
    from helpers.xlsx_out import xlsx_to_html
    h = xlsx_to_html(_wb_bytes(), "測試標題")
    assert "測試標題" in h and "報表&lt;1&gt;" in h and "隱藏" not in h
    assert "colspan=3" in h and "&lt;script&gt;alert(1)&lt;/script&gt;" in h and "<script>" not in h
    assert "標題 &amp; &lt;b&gt;粗&lt;/b&gt;" in h
    assert "1,234,567.89" in h and "25.6%" in h and ">42<" in h and "font-weight:bold" in h and "background:#FFFF00" in h


def test_xlsx_to_html_truncates_huge_sheets_with_a_notice():
    from helpers.xlsx_out import xlsx_to_html
    h = xlsx_to_html(_wb_bytes(fill=30), "t", max_rows=10)
    assert "只列前 10 列" in h and "r30" not in h


def test_count_xlsx_rows_counts_all_sheets_and_is_zero_on_garbage():
    from helpers.xlsx_out import count_xlsx_rows
    assert count_xlsx_rows(_wb_bytes()) >= 4
    assert count_xlsx_rows(b"not a zip") == 0


# ══ ③ add_pdf_sibling 行為題（合成 app）══════════════════════════════════════════════

@pytest.fixture()
def app_env(monkeypatch):
    from fastapi import APIRouter, FastAPI, Header, Query
    from fastapi.responses import Response
    from fastapi.testclient import TestClient
    import helpers.audit as A
    import helpers.auth as AU
    import helpers.company_identity as CI
    import helpers.xlsx_out as X
    X._export_times.clear()
    audits, gate = [], {"calls": 0, "fail": False}
    monkeypatch.setattr(A, "_audit", lambda token, action, target_type="", target_id="", target_label="", detail=None: audits.append(
        {"token": token, "action": action, "target_type": target_type, "target_id": target_id, "detail": detail}))
    monkeypatch.setattr(AU, "_require_user", lambda authorization, **kw: {"id": 7, "username": "u", "role": "superadmin"})

    def _gate(*a, **k):
        gate["calls"] += 1
        if gate["fail"]:
            from fastapi import HTTPException
            raise HTTPException(428, "公司資料未確認")
    monkeypatch.setattr(CI, "require_for_output", _gate)
    import pdf_gen
    pdfs = {"raise": None, "html": []}

    def fake_pdf(html):
        pdfs["html"].append(html)
        if pdfs["raise"]:
            raise pdfs["raise"]
        return b"%PDF-1.4 fake"
    monkeypatch.setattr(pdf_gen, "html_to_pdf_bytes", fake_pdf)
    router = APIRouter()
    calls = []

    @router.get("/api/x/export")
    @X.export_logged("xlsx", "demo", "x-list")
    def x_export(start: str = Query(None), customer: str = Query(None), authorization: str = Header(None)):
        u = AU._require_user(authorization)
        X.check_export_rate(u["id"], "excel")
        calls.append((start, customer))
        return Response(content=_wb_bytes(), media_type=X.XLSX_MEDIA,
                        headers={"Content-Disposition": "attachment; filename*=UTF-8''%E5%A0%B1%E8%A1%A8_2026.xlsx"})

    X.add_pdf_sibling(router, "/api/x/export/pdf", x_export, module="demo", name="x-list", title="範例報表")
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), audits, gate, pdfs, calls, X


H = {"Authorization": "Bearer tok-1"}


def test_sibling_uses_the_same_handler_params_and_returns_a_pdf_with_a_pdf_filename(app_env):
    c, audits, gate, pdfs, calls, X = app_env
    r = c.get("/api/x/export/pdf", params={"start": "2026-09-01", "customer": "王大明"}, headers=H)
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and r.headers["content-type"] == "application/pdf"
    assert calls == [("2026-09-01", "王大明")], "PDF 姊妹必須用同一個處理函式與同一組篩選"
    assert "%E5%A0%B1%E8%A1%A8_2026.pdf" in r.headers["content-disposition"]
    assert "範例報表" in pdfs["html"][0] and gate["calls"] == 1


def test_both_formats_write_an_audit_row_without_pii_values(app_env):
    c, audits, gate, pdfs, calls, X = app_env
    assert c.get("/api/x/export", params={"start": "2026-09-01", "customer": "王大明"}, headers=H).status_code == 200
    X._export_times.clear()
    assert c.get("/api/x/export/pdf", params={"start": "2026-09-01", "customer": "王大明"}, headers=H).status_code == 200
    got = {a["action"]: a for a in audits}
    assert set(got) == {"export.xlsx", "export.pdf"}
    for a in got.values():
        assert a["token"] == "tok-1" and a["target_type"] == "export" and a["target_id"] == "x-list"
        d = a["detail"]
        assert d["module"] == "demo" and d["filters"] == {"start": "2026-09-01", "customer": "<text:3>"} and d["rows"] >= 4
        assert "王大明" not in json.dumps(d, ensure_ascii=False)


def test_a_failed_export_is_not_logged_as_success(app_env):
    c, audits, gate, pdfs, calls, X = app_env
    gate["fail"] = True
    assert c.get("/api/x/export/pdf", headers=H).status_code == 428
    assert [a for a in audits if a["action"] == "export.pdf"] == []
    gate["fail"] = False
    import fastapi
    pdfs["raise"] = RuntimeError("找不到 Edge")
    X._export_times.clear()
    assert c.get("/api/x/export/pdf", headers=H).status_code == 503
    assert [a for a in audits if a["action"] == "export.pdf"] == []


def test_pdf_has_its_own_cooldown_and_does_not_consume_the_excel_one(app_env):
    c, audits, gate, pdfs, calls, X = app_env
    assert c.get("/api/x/export/pdf", headers=H).status_code == 200
    assert c.get("/api/x/export", headers=H).status_code == 200, "PDF 姊妹不可以吃掉 Excel 的 5 秒冷卻"
    assert c.get("/api/x/export/pdf", headers=H).status_code == 429, "PDF 冷卻 30 秒"
    assert c.get("/api/x/export", headers=H).status_code == 429, "Excel 自己的冷卻照舊"


def test_missing_gate_or_handler_body_is_a_server_error_not_an_empty_pdf(app_env, monkeypatch):
    c, audits, gate, pdfs, calls, X = app_env
    from fastapi.responses import StreamingResponse
    import helpers.xlsx_out as XO
    monkeypatch.setattr(XO, "_response_bytes", lambda resp: None)
    assert c.get("/api/x/export/pdf", headers=H).status_code == 500
