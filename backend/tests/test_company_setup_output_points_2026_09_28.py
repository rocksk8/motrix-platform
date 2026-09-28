# -*- coding: utf-8 -*-
"""本公司資料設定閘門 §7-②：**新輸出點要經第二道**（COMPANY-SETUP-GATE §5、§7-②；D CG5-M1）。

掃描器（AST＋文字）找「會產生對外檔案」的函式（最內層那一個）：PDF 產生、Workbook、csv、Content-Disposition、
FileResponse、帶附件的信。每一點必須：
  (a) **經第二道**：函式本身、或它（依名稱、遞移）呼叫到的函式，呼叫了第二道（`require_for_output`／
      `identity_for_output`／`company_setup.require`）或含第二道的輸出 helper（`company_name`、`company_heading`、
      `contact_line`、`name_pair`、`footer_line`、pdf_gen 的 `_identity_head／_identity_foot／_identity_foot_short`）；或
  (b) 登記在 `GATED_BY_CALLER`（自己不問，**所有呼叫端**都已經問過）；或
  (c) 登記在 `NO_COMPANY_DATA`（不含本公司資料，附理由 ≥ 20 字）。
正對照：§1 的已知輸出點（8 種單據 PDF、傳票、報表、規劃書、自訂模組、排程信…）全部要被掃到、而且判定為 (a)／(b)。
反向控制：合成一個新端點產 XLSX 不經第二道 ⇒ 掃描器報出來；登記了不存在的點 ⇒ 紅。

⚠ 遞移是「依函式名稱」：同名函式會互相沾光（已知的寬鬆，換來不必維護呼叫圖）；正對照逐點點名以抵銷。
"""
import ast
import os
import re

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 產生對外檔案的樣式
OUTPUT_PAT = re.compile(r"html_to_pdf_bytes|run_edge_pdf|_render_pdf_via_edge|Workbook\(|csv\.writer|text/csv"
                        r"|Content-Disposition|FileResponse\(|_send_with_attachments")
#: 第二道本身，以及「一進來就問第二道」的輸出 helper（helpers/company_identity.py、pdf_gen.py）
GATE_CALLS = ("require_for_output", "identity_for_output", "_cs.require", "company_setup.require",
              "company_name", "company_heading", "contact_line", "name_pair", "footer_line",
              "_identity_head", "_identity_foot", "_identity_foot_short", "_monthly_report_blocked")

#: (b) 自己不問、所有呼叫端都問過：{(檔, 函式): 理由}
GATED_BY_CALLER = {
    ("helpers/email_notify.py", "notify_monthly_report"):
        "每月報表信：唯一呼叫端 reports._send_monthly_report_for 開頭先問第二道（_monthly_report_blocked）",
    ("modules/accounting/voucher_pdf.py", "_render"):
        "傳票 HTML 轉 PDF；呼叫端（匯出傳票 PDF 的兩支）先以 _company_name() 取抬頭＝經第二道",
    ("modules/analytics/api/reports.py", "_html_to_pdf"):
        "報表 HTML 轉 PDF；呼叫端 report_pdf 與月報排程（_send_monthly_report_for）都已經過第二道",
}

#: (c) 不含本公司資料：{(檔, 函式): 理由}
NO_COMPANY_DATA = {
    ("helpers/startup.py", "run_edge_pdf"): "Edge 轉 PDF 的底層（只轉呼叫端給的 HTML）；內容由呼叫端決定並各自經第二道",
    ("helpers/email_notify.py", "_send_with_attachments"):
        "寄附件的共用底層（以 target= 參考傳給背景執行緒，不是直接呼叫）；附件由呼叫端產生並各自經第二道",
    ("modules/netplan/export.py", "_render_pdf_via_edge"):
        "規劃書／拓樸 HTML 轉 PDF 的底層；規劃書的產生端 build_plan_pdf_bytes 經第二道，拓樸不含本公司資料",
    ("modules/payroll/bonus_pdf.py", "_pdf_parts"):
        "只回傳函式參考（import 聚合），自己不產生檔案；呼叫端 export 時會呼叫 company_name() 經第二道",
    ("pdf_gen.py", "html_to_pdf_bytes"): "HTML 轉 PDF 的底層（只轉呼叫端給的 HTML）；抬頭／頁尾由 builder 的 _identity_head 經第二道",
    ("main.py", "module_page"): "模組頁面 HTML（FileResponse 送靜態頁），頁面內容不含本公司資料；資料由 API 取（受第一道擋）",
    ("main.py", "map_overlay_script"): "地圖覆蓋層腳本（靜態 JS），不含本公司資料",
    ("main.py", "root"): "首頁靜態檔（FileResponse），不含本公司資料；登入頁品牌經 /api/system/branding（公開、非文件）",
    ("routers/uploads.py", "serve_upload"): "使用者上傳的原始檔（照片、附件）原樣送回；不是系統產生的文件",
    ("routers/system.py", "get_branding_asset"): "品牌圖檔（LOGO／favicon，§2-① 使用者裁示維持）；不是文件輸出",
    ("modules/accounting/api/vouchers.py", "line_source_file_endpoint"): "傳票分錄的原始憑證檔（使用者上傳）原樣送回",
    ("modules/accounting/api/vouchers.py", "download_voucher_attachment"): "傳票附件（使用者上傳的原始檔）原樣送回，不是系統產生的文件",
    ("modules/arap/api/cashier.py", "export_execution_history"): "出納執行紀錄 XLSX：只有交易明細，不印本公司抬頭（§1.3）",
    ("modules/case/api/quotations.py", "download_quotation_version"): "已存檔的歷史版本 PDF 原樣下載（§1.4：產生當時已凍結）",
    ("modules/case/api/quotations.py", "case_batch_export"): "案件批次 XLSX：案件欄位清單，不印本公司抬頭（§1.3）",
    ("modules/daily_tasks/api.py", "export_task_history"): "每日任務 CSV：任務紀錄，不含本公司資料（§1.3）",
    ("modules/lodging/api_records.py", "lodging_record_export"): "附近旅宿 CSV／JSON：查詢結果，不含本公司資料（§1.3）",
    ("modules/netplan/api.py", "export_quick_topology_pdf"): "快速拓樸 PDF：標題由請求帶入，不印本公司抬頭（§1.3）",
    ("modules/netplan/export.py", "build_topology_only_pdf_bytes"): "快速拓樸 PDF 的產生端（同上），不印本公司抬頭（§1.3）",
    ("modules/payroll/api/payslips.py", "get_archive_pdf"): "已存檔的勞報單 PDF 原樣下載（§1.4：產生當時已凍結）",
    ("modules/subcontract/api/contractors.py", "export_contractors"): "承攬人員 XLSX：人員清單，不印本公司抬頭（§1.3）",
    ("routers/definitions.py", "preview_output_template"): "自訂模組版型預覽：用假資料（無本公司資料）排版給設計者看",
}

#: 正對照：§1 的已知輸出點，一定要被掃到而且判定為經第二道
KNOWN_GATED = [
    ("modules/case/api/quotations.py", "download_quotation_pdf"),
    ("modules/case/api/quotations.py", "download_case_closing_report_pdf"),
    ("modules/case/api/quotations.py", "download_project_execution_report_pdf"),
    ("modules/case/api/completion_notes.py", "download_completion_pdf"),
    ("modules/supply/api/shipping_notes.py", "download_shipping_pdf"),
    ("modules/subcontract/api/contractor_vouchers.py", "download_contractor_voucher_pdf"),
    ("modules/arap/api/invoice_vouchers.py", "download_invoice_voucher_pdf"),
    ("modules/arap/api/payment_requests.py", "download_payment_request_pdf"),
    ("modules/accounting/api/vouchers.py", "download_voucher_pdf"),
    ("modules/accounting/api/accounting_export.py", "t100_export_vouchers"),
    ("modules/analytics/api/reports.py", "report_excel"),
    ("modules/analytics/api/reports.py", "report_pdf"),
    ("modules/analytics/api/reports.py", "tax_export_excel"),
    ("modules/netplan/api.py", "export_network_plan_excel"),
    ("modules/netplan/api.py", "export_network_plan_pdf"),
    ("modules/payroll/api/bonus.py", "download_award_pdf"),
    ("modules/payroll/api/payslips.py", "pdf_download"),
    ("routers/custom_records.py", "output_custom_record"),
    ("routers/custom_records.py", "preview_custom_output"),
    ("helpers/email_notify.py", "notify_monthly_report"),
]


def product_sources():
    """backend 底下的產品程式（不含 tests／tools／conftest）：{相對路徑: 原始碼}"""
    out = {}
    for dp, dn, fn in os.walk(BACKEND):
        dn[:] = [d for d in dn if d not in ("tests", "tools", "__pycache__", "_frozen") and not d.startswith(".")]
        for f in fn:
            if not f.endswith(".py") or f == "conftest.py":
                continue
            p = os.path.join(dp, f)
            out[os.path.relpath(p, BACKEND).replace(os.sep, "/")] = open(p, encoding="utf-8").read()
    return out


def _functions(sources):
    """[(檔, 名稱, 原始碼, 是否最內層輸出點)]"""
    out = []
    for rel, src in sources.items():
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        lines = src.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = "\n".join(lines[node.lineno - 1:node.end_lineno])
            is_out = bool(OUTPUT_PAT.search(body)) and not any(
                isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef)) and c is not node
                and OUTPUT_PAT.search("\n".join(lines[c.lineno - 1:c.end_lineno])) for c in ast.walk(node))
            out.append((rel, node.name, body, is_out))
    return out


_CALL_RE = re.compile(r"([A-Za-z_][\w.]*)\s*\(")


def _call_names(body):
    """函式內呼叫到的名稱集合：`a.b.c(` 記 `c` 與 `b.c`（`_cs.require` 這類要連模組別名一起比）。"""
    out = set()
    for full in _CALL_RE.findall(body):
        parts = full.split(".")
        out.add(parts[-1])
        if len(parts) >= 2:
            out.add(".".join(parts[-2:]))
    return out


def _calls(body, name):
    return name in _call_names(body)


def scan(sources):
    """回 {"points": {(檔, 函式): 判定}}；判定＝"gated"／"by_caller"／"no_company_data"／"UNREGISTERED"。"""
    funcs = _functions(sources)
    calls = [_call_names(body) for _r, _n, body, _o in funcs]
    gate_set = set(GATE_CALLS)
    gated = {name for (_r, name, _b, _o), cs in zip(funcs, calls) if cs & gate_set}
    changed = True
    while changed:                                  # 依名稱遞移（見模組說明的已知寬鬆）
        changed = False
        for (_r, name, _b, _o), cs in zip(funcs, calls):
            if name not in gated and cs & gated:
                gated.add(name)
                changed = True
    points = {}
    for rel, name, body, is_out in funcs:
        if not is_out:
            continue
        key = (rel, name)
        if key in NO_COMPANY_DATA:
            points[key] = "no_company_data"
        elif key in GATED_BY_CALLER:
            points[key] = "by_caller"
        elif name in gated:
            points[key] = "gated"
        else:
            points[key] = "UNREGISTERED"
    return {"points": points, "gated_names": gated, "funcs": funcs}


def test_every_output_point_goes_through_the_second_gate_or_is_registered():
    r = scan(product_sources())
    bad = sorted("%s::%s" % k for k, v in r["points"].items() if v == "UNREGISTERED")
    assert not bad, ("新的輸出點沒有經第二道（require_for_output 等），也沒有登記「不含本公司資料」：\n  "
                     + "\n  ".join(bad) + "\n⇒ 輸出含本公司資料就呼叫 company_identity.require_for_output()；"
                     "不含就登記在本檔 NO_COMPANY_DATA（附理由）")


def test_known_output_points_are_found_and_gated():
    """正對照（盤點工具要先讓已知的亮起來）：§1 的已知點全部掃得到、全部判定經第二道。"""
    r = scan(product_sources())
    assert len(r["points"]) >= 50, len(r["points"])
    for key in KNOWN_GATED:
        assert key in r["points"], "掃描器沒掃到已知輸出點 %s::%s（樣式或範圍漏了）" % key
        assert r["points"][key] in ("gated", "by_caller"), (key, r["points"][key])


def test_registrations_are_live_and_explained():
    r = scan(product_sources())
    for reg in (NO_COMPANY_DATA, GATED_BY_CALLER):
        for key, why in reg.items():
            assert key in r["points"], "登記了不存在（或不再是輸出點）的 %s::%s ⇒ 刪掉這條登記" % key
            assert len(why) >= 20, key
    assert not set(NO_COMPANY_DATA) & set(KNOWN_GATED)


def test_gated_by_caller_really_has_only_gated_callers():
    r = scan(product_sources())
    for (rel, name), _why in GATED_BY_CALLER.items():
        callers = [(fr, fn) for fr, fn, body, _o in r["funcs"] if fn != name and _calls(body, name)]
        assert callers, "%s 沒有任何呼叫端（登記失效）" % name
        for fr, fn in callers:
            ok = fn in r["gated_names"] or (fr, fn) in GATED_BY_CALLER
            assert ok, "%s 的呼叫端 %s::%s 沒有經第二道" % (name, fr, fn)


def test_reverse_control_a_new_unchecked_xlsx_endpoint_is_reported():
    src = dict(product_sources())
    src["modules/zz_synthetic/api.py"] = (
        "import openpyxl\n"
        "def export_something():\n"
        "    wb = openpyxl.Workbook()\n"
        "    return wb\n"
        "def export_ok():\n"
        "    from helpers.company_identity import require_for_output\n"
        "    require_for_output()\n"
        "    return openpyxl.Workbook()\n")
    pts = scan(src)["points"]
    assert pts[("modules/zz_synthetic/api.py", "export_something")] == "UNREGISTERED"
    assert pts[("modules/zz_synthetic/api.py", "export_ok")] == "gated"


def test_reverse_control_removing_the_gate_from_pdf_identity_head_turns_pdfs_red():
    """把 pdf_gen._identity_head 的第二道拿掉 ⇒ 8 種單據 PDF 不再被判定經第二道（證明判定真的依賴那一行）。"""
    src = dict(product_sources())
    pg = src["pdf_gen.py"]
    for fn in ("_identity_head", "_identity_foot", "_identity_foot_short"):
        pg = pg.replace("def %s(" % fn, "def %s_x(" % fn).replace("%s(_ident)" % fn, "%s_x(_ident)" % fn)
    pg = pg.replace("require_for_output(", "_nothing(")
    src["pdf_gen.py"] = pg
    src["modules/case/completion_pdf.py"] = src["modules/case/completion_pdf.py"].replace(
        "_identity_head(", "_identity_head_x(").replace("_identity_foot(", "_identity_foot_x(")
    src["helpers/custom_modules.py"] = src["helpers/custom_modules.py"].replace(
        "_identity_head(", "_identity_head_x(").replace("_identity_foot(", "_identity_foot_x(")
    pts = scan(src)["points"]
    assert pts[("modules/case/api/quotations.py", "download_quotation_pdf")] == "UNREGISTERED"
    assert pts[("modules/supply/api/shipping_notes.py", "download_shipping_pdf")] == "UNREGISTERED"


def test_output_endpoints_do_not_swallow_the_428():
    """經第二道的輸出端點若有 `except Exception`，同一個 try 前面要先有 `except HTTPException: raise`
    （否則 CompanySetupRequired 被吞成 500；§5）。"""
    src = product_sources()
    bad = []
    for rel, name in KNOWN_GATED:
        tree = ast.parse(src[rel])
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                for tr in ast.walk(node):
                    if not isinstance(tr, ast.Try):
                        continue
                    seen_http = False
                    for h in tr.handlers:
                        t = ast.unparse(h.type) if h.type is not None else "BaseException"
                        if "HTTPException" in t or "CompanySetupRequired" in t:
                            seen_http = True
                        if t in ("Exception", "BaseException") and not seen_http:
                            body = ast.unparse(tr.body[0]) if tr.body else ""
                            if "location_identity" in body:          # 稽核用的即時值查詢（不經第二道、不會丟 428）
                                continue
                            bad.append("%s::%s:%d" % (rel, name, h.lineno))
    assert not bad, bad
