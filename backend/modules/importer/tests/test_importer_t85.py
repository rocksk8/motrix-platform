# -*- coding: utf-8 -*-
"""T85 匯入精靈（importer）：解析安全、範本、API 開關與權限、與既有 import-rows 銜接。"""
import io
import json
import zipfile

import pytest
from openpyxl import Workbook, load_workbook

from modules.importer import parser as P


# ── 工具 ──────────────────────────────────────────────────────────────────────

def _xlsx(rows, sheet="資料", extra=None):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    for r in rows:
        ws.append(r)
    for name, rr in (extra or {}).items():
        w2 = wb.create_sheet(name)
        for r in rr:
            w2.append(r)
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def _parse(rows, kind="customers", **kw):
    return P.parse_file(_xlsx(rows, **kw), "x.xlsx", kind)


CUST_HEAD = ["公司名稱＊", "統一編號", "電話", "Email", "內部標籤", "主要聯絡人", "備註"]


# ── 解析：基本與表頭 ─────────────────────────────────────────────────────────

def test_customer_row_shape_matches_what_import_rows_takes():
    res = _parse([CUST_HEAD, ["大安電腦", "12345675", "02-1234", "a@b.co", "重要, 年約、新客", "王小明", "備註一"]])
    r = res["rows"][0]
    assert r["row"] == 2 and r["name"] == "大安電腦" and r["taxId"] == "12345675" and r["phone"] == "02-1234"
    assert r["data"]["tags"] == ["重要", "年約", "新客"] and r["data"]["email"] == "a@b.co" and r["data"]["notes"] == "備註一"
    assert r["data"]["contacts"][0]["name"] == "王小明"
    assert set(r) == {"row", "name", "taxId", "phone", "data"}


def test_blank_cells_are_empty_strings_never_zero_or_null_and_numbers_have_no_decimal_tail():
    res = _parse([["料號", "品名＊", "成本(未稅)", "安全庫存", "前置天數"], [12345, "線材", None, 5.0, ""], [None, "交換器", 3200.5, "", None]], kind="parts")
    a, b = res["rows"]
    assert a["partNo"] == "12345" and a["cost"] == "" and a["safetyStock"] == "5" and a["leadTimeDays"] == ""
    assert b["partNo"] == "" and b["cost"] == "3200.5" and b["safetyStock"] == "" and b["leadTimeDays"] == ""
    for r in res["rows"]:
        assert all(v is not None and v != 0 for v in r.values())


def test_headers_are_tolerant_synonyms_stars_width_and_case():
    res = _parse([["名稱", "統編", "ＥＭＡＩＬ"], ["甲公司", "12345675", "a@b.co"]])
    assert res["rows"][0]["name"] == "甲公司" and res["rows"][0]["data"]["email"] == "a@b.co" and res["unusedColumns"] == []


def test_unknown_headers_are_listed_not_silently_dropped_and_duplicates_are_rejected():
    res = _parse([["公司名稱", "神秘欄"], ["甲", "x"]])
    assert res["unusedColumns"] == ["神秘欄"]
    with pytest.raises(P.ParseError, match="出現了兩次"):
        _parse([["公司名稱", "名稱"], ["甲", "乙"]])


def test_missing_required_header_and_header_only_and_example_only_files():
    with pytest.raises(P.ParseError, match="必填欄位"):
        _parse([["統一編號"], ["12345675"]])
    with pytest.raises(P.ParseError, match="沒有資料列"):
        _parse([CUST_HEAD])
    with pytest.raises(P.ParseError, match="沒有資料列"):
        _parse([CUST_HEAD, [P.EXAMPLE_MARK + "範例公司", "12345675"]])
    with pytest.raises(P.ParseError, match="第一列要放欄位名稱"):
        _parse([["abc", "def"], [1, 2]])


def test_example_rows_are_skipped_and_counted():
    res = _parse([CUST_HEAD, [P.EXAMPLE_MARK + "範例", "12345675"], ["真公司", ""]])
    assert [r["name"] for r in res["rows"]] == ["真公司"] and res["skippedExamples"] == 1 and res["rows"][0]["row"] == 3


def test_data_sheet_is_picked_by_name_not_position_and_hidden_sheets_are_ignored():
    wb = Workbook()
    help_ws = wb.active
    help_ws.title = "說明"
    help_ws.append(["公司名稱", "x"])
    help_ws.append(["說明頁的假資料", ""])
    ws = wb.create_sheet("資料")
    ws.append(CUST_HEAD)
    ws.append(["真資料", ""])
    hid = wb.create_sheet("隱藏")
    hid.append(CUST_HEAD)
    hid.append(["隱藏的資料", ""])
    hid.sheet_state = "hidden"
    bio = io.BytesIO()
    wb.save(bio)
    assert [r["name"] for r in P.parse_file(bio.getvalue(), "a.xlsx", "customers")["rows"]] == ["真資料"]
    # 沒有名叫「資料」的工作表：略過「說明」與隱藏的，讀第一個可見的
    wb2 = Workbook()
    a = wb2.active
    a.title = "說明"
    b = wb2.create_sheet("Sheet2")
    b.append(CUST_HEAD)
    b.append(["第二張", ""])
    bio2 = io.BytesIO()
    wb2.save(bio2)
    assert P.parse_file(bio2.getvalue(), "a.xlsx", "customers")["rows"][0]["name"] == "第二張"


def test_merged_cells_do_not_crash():
    wb = Workbook()
    ws = wb.active
    ws.title = "資料"
    ws.append(CUST_HEAD)
    ws.append(["甲", "12345675", "02", "", "", "", "備"])
    ws.append(["乙", "", "", "", "", "", ""])
    ws.merge_cells("B2:C3")
    bio = io.BytesIO()
    wb.save(bio)
    assert len(P.parse_file(bio.getvalue(), "m.xlsx", "customers")["rows"]) == 2


# ── 解析：安全 ───────────────────────────────────────────────────────────────

def test_formula_cells_are_not_imported_and_warn():
    wb = Workbook()
    ws = wb.active
    ws.title = "資料"
    ws.append(CUST_HEAD)
    ws.append(["甲公司", "=1+1", "=HYPERLINK(\"http://x\",\"y\")", "", "", "", ""])
    bio = io.BytesIO()
    wb.save(bio)
    res = P.parse_file(bio.getvalue(), "f.xlsx", "customers")
    r = res["rows"][0]
    assert r["taxId"] == "" and r["phone"] == ""
    assert any("公式" in w["message"] for w in res["warnings"])


def test_text_starting_with_equals_in_a_text_cell_is_kept_as_plain_text_not_evaluated():
    res = _parse([CUST_HEAD, ["'=甲", "", "+886-2-1234", "", "", "", "@備註"]])
    r = res["rows"][0]
    assert r["phone"] == "+886-2-1234" and r["data"]["notes"] == "@備註"       # 純文字照收；寫進 xlsx／csv 的匯出另有 xl_safe 防護


def test_rejects_xls_xlsm_wrong_extension_empty_and_content_mismatch():
    good = _xlsx([CUST_HEAD, ["甲", ""]])
    for name, match in (("a.xls", "xls"), ("a.xlsm", "巨集"), ("a.txt", "只收"), ("a", "只收")):
        with pytest.raises(P.ParseError, match=match):
            P.parse_file(good, name, "customers")
    with pytest.raises(P.ParseError, match="空的"):
        P.parse_file(b"", "a.xlsx", "customers")
    with pytest.raises(P.ParseError, match="不是 Excel"):
        P.parse_file(b"not a zip at all", "a.xlsx", "customers")
    with pytest.raises(P.ParseError, match="不是文字"):
        P.parse_file(good, "a.csv", "customers")
    with pytest.raises(P.ParseError, match="不認得"):
        P.parse_file(good, "a.xlsx", "orders")


def test_macro_workbook_with_xlsx_name_is_rejected():
    good = _xlsx([CUST_HEAD, ["甲", ""]])
    src = zipfile.ZipFile(io.BytesIO(good))
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as z:
        for n in src.namelist():
            z.writestr(n, src.read(n))
        z.writestr("xl/vbaProject.bin", b"\x00evil")
    with pytest.raises(P.ParseError, match="巨集"):
        P.parse_file(bio.getvalue(), "a.xlsx", "customers")


def test_zip_without_workbook_and_oversize_unzip_are_rejected():
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as z:
        z.writestr("hello.txt", "hi")
    with pytest.raises(P.ParseError, match="不是有效的 Excel"):
        P.parse_file(bio.getvalue(), "a.xlsx", "customers")
    good = _xlsx([CUST_HEAD, ["甲", ""]])
    src = zipfile.ZipFile(io.BytesIO(good))
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        for n in src.namelist():
            z.writestr(n, src.read(n))
        z.writestr("xl/media/huge.bin", b"\x00" * (60 << 20))             # 解開 60 MB、壓縮後很小
    assert len(bomb.getvalue()) < (5 << 20)
    with pytest.raises(P.ParseError, match="解開後太大"):
        P.parse_file(bomb.getvalue(), "a.xlsx", "customers")


def test_file_size_limit_and_row_cap():
    with pytest.raises(P.ParseError, match="檔案太大"):
        P.parse_file(_xlsx([CUST_HEAD, ["甲", ""]]), "a.xlsx", "customers", max_bytes=100)
    rows = [["帳號", "姓名"]] + [["u%d" % i, "人%d" % i] for i in range(P.MAX_ROWS["users"] + 1)]
    with pytest.raises(P.ParseError, match="上限 300"):
        P.parse_file(_xlsx(rows), "u.xlsx", "users")
    ok = [["帳號", "姓名"]] + [["u%d" % i, "人%d" % i] for i in range(P.MAX_ROWS["users"])]
    assert P.parse_file(_xlsx(ok), "u.xlsx", "users")["rowCount"] == 300


def _raw_xlsx(sheet_xml_body, declared="A1:B2"):
    """用 openpyxl 做一個正常的 xlsx，再把「資料」工作表的 XML 換成自己寫的內容（模擬惡意／不正常的檔案）。"""
    good = _xlsx([["x"]])
    src = zipfile.ZipFile(io.BytesIO(good))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n in src.namelist():
            data = src.read(n)
            if n == "xl/worksheets/sheet1.xml":
                data = ('<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                        '<dimension ref="%s"/><sheetData>%s</sheetData></worksheet>' % (declared, sheet_xml_body)).encode("utf-8")
            z.writestr(n, data)
    return out.getvalue()


def _grid_xml(rows, cols):
    """rows×cols 個空格（每格都有各自的 r 屬性）。"""
    from openpyxl.utils import get_column_letter
    letters = [get_column_letter(c + 1) for c in range(cols)]
    return "".join('<row r="%d">%s</row>' % (r, "".join('<c r="%s%d" s="1"/>' % (L, r) for L in letters)) for r in range(1, rows + 1))


def test_one_million_cell_file_is_rejected_fast_and_with_small_memory():
    # 共用守門（helpers.xlsx_guard）先擋哪一個上限：這份檔的工作表 XML 超過 12MB 就先報「內容太大」，否則報「儲存格太多」——都是白話拒絕、重點是快且不吃記憶體
    import time
    import tracemalloc
    data = _raw_xlsx(_grid_xml(20000, 50), declared="A1:AX20000")        # 100 萬格，壓縮後只有幾 MB
    assert len(data) < (5 << 20)
    t = time.monotonic()                                                  # ① 時間（不開 tracemalloc：它會讓純 Python 迴圈慢十倍以上）
    with pytest.raises(P.ParseError, match="儲存格太多|內容太大"):
        P.parse_file(data, "bomb.xlsx", "customers")
    took = time.monotonic() - t
    assert took < 2, "1M 格的檔案花了 %.2f 秒才拒絕" % took
    tracemalloc.start()                                                   # ② 尖峰記憶體
    try:
        with pytest.raises(P.ParseError, match="儲存格太多|內容太大"):
            P.parse_file(data, "bomb.xlsx", "customers")
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 100 * 1024 * 1024, "尖峰記憶體 %.0fMB" % (peak / 1048576)


def test_lying_dimension_does_not_pad_rows_or_slow_the_parse():
    import time
    head = "".join('<c r="%s1" t="inlineStr"><is><t>%s</t></is></c>' % (L, v) for L, v in (("A", "公司名稱"), ("B", "統一編號")))
    row2 = '<c r="A2" t="inlineStr"><is><t>甲公司</t></is></c>'
    data = _raw_xlsx('<row r="1">%s</row><row r="2">%s</row>' % (head, row2), declared="A1:XFD1048576")
    t = time.monotonic()
    res = P.parse_file(data, "lie.xlsx", "customers")
    assert res["rowCount"] == 1 and res["rows"][0]["name"] == "甲公司" and time.monotonic() - t < 2


def test_row_numbers_far_below_the_data_are_rejected_not_scanned():
    row = '<row r="1"><c r="A1" t="inlineStr"><is><t>公司名稱</t></is></c></row><row r="%d"><c r="A%d" t="inlineStr"><is><t>x</t></is></c></row>' % (P.MAX_SHEET_ROWNUM + 5, P.MAX_SHEET_ROWNUM + 5)
    with pytest.raises(P.ParseError, match="太多或資料放得太下面"):
        P.parse_file(_raw_xlsx(row), "far.xlsx", "customers")


def test_oversized_sheet_xml_is_rejected_before_reading_it():
    from helpers import xlsx_guard as XG
    big = _raw_xlsx('<row r="1">%s</row>' % ('<c r="A1" t="inlineStr"><is><t>%s</t></is></c>' % ("x" * (XG.DEFAULT.max_sheet_xml + 10))))
    with pytest.raises(P.ParseError):
        P.parse_file(big, "big.xlsx", "customers", max_bytes=50 << 20)


def test_deadline_is_enforced(monkeypatch):
    monkeypatch.setattr(P, "DEADLINE_SECONDS", -1.0)
    with pytest.raises(P.ParseError, match="處理太久"):
        _parse([CUST_HEAD, ["甲", ""]])
    with pytest.raises(P.ParseError, match="處理太久"):
        P.parse_file("公司名稱\n甲\n".encode("utf-8"), "d.csv", "customers")


def test_blank_gap_does_not_stop_reading_and_warns_with_the_row_number():
    wb = Workbook()
    ws = wb.active
    ws.title = "資料"
    ws.append(CUST_HEAD)
    ws.append(["甲", ""])
    ws.cell(row=900, column=1, value="乙公司")                            # 中間空 897 列（舊版 500 列空白就會停）
    ws.cell(row=2000, column=1, value="丙公司")
    bio = io.BytesIO()
    wb.save(bio)
    res = P.parse_file(bio.getvalue(), "gap.xlsx", "customers")
    assert [r["name"] for r in res["rows"]] == ["甲", "乙公司", "丙公司"]
    msgs = [w["message"] for w in res["warnings"]]
    assert "第 2 列後有空白區段，之後的資料已一併讀取" in msgs and "第 900 列後有空白區段，之後的資料已一併讀取" in msgs


def test_row_cap_counts_filled_rows_not_blank_ones():
    rows = [CUST_HEAD] + [["公司%d" % i, ""] if i % 2 == 0 else [] for i in range(2 * P.MAX_ROWS["customers"])]
    res = _parse(rows)
    assert res["rowCount"] == P.MAX_ROWS["customers"]
    with pytest.raises(P.ParseError, match="太多"):
        _parse([CUST_HEAD] + [["公司%d" % i, ""] for i in range(P.MAX_ROWS["customers"] + 1)])


def test_too_many_columns_names_the_column_letter():
    head = ["公司名稱"] + ["欄%d" % i for i in range(P.MAX_COLS + 5)]
    with pytest.raises(P.ParseError, match="AY 欄"):
        _parse([head, ["甲"] + [""] * (P.MAX_COLS + 5)])
    with pytest.raises(P.ParseError, match="AY 欄"):                      # 孤零零一格放在很右邊
        _parse([CUST_HEAD, ["甲"], ["乙"] + [""] * (P.MAX_COLS) + ["雜訊"]])
    csv_head = ",".join(["公司名稱"] + ["c%d" % i for i in range(P.MAX_COLS + 2)])
    with pytest.raises(P.ParseError, match="欄"):
        P.parse_file((csv_head + "\n甲\n").encode("utf-8"), "w.csv", "customers")


def test_csv_blank_lines_do_not_count_toward_the_cap_or_stop_reading():
    text = "公司名稱,統一編號\n" + "\n" * 6000 + "甲公司,\n" + "\n" * 600 + "乙公司,\n"
    res = P.parse_file(text.encode("utf-8"), "g.csv", "customers")
    assert [r["name"] for r in res["rows"]] == ["甲公司", "乙公司"]
    assert any("空白區段" in w["message"] for w in res["warnings"])


def test_junk_tax_id_is_reported_per_row_not_dropped_silently():
    res = _parse([CUST_HEAD, ["甲", "N/A"], ["乙", "無"], ["丙", "統編 12345675"], ["丁", "12345675"]])
    by = {}
    for w in res["warnings"]:
        by.setdefault(w["row"], []).append(w["message"])
    assert any("不是統編" in m and "N/A" in m for m in by[2]) and any("不是統編" in m and "無" in m for m in by[3])
    assert any("只取出數字" in m for m in by[4])
    assert 5 not in by
    assert [r["taxId"] for r in res["rows"]] == ["", "", "12345675", "12345675"]


def test_numeric_phone_and_part_no_cells_warn_that_leading_zeros_may_be_lost_and_text_cells_do_not():
    wb = Workbook()
    ws = wb.active
    ws.title = "資料"
    ws.append(CUST_HEAD)
    ws.append(["甲", "", 912345678])                                      # 數字格：0912… 的 0 被吃掉了
    ws.append(["乙", "", "0912345678"])                                    # 文字格：沒事
    ws.append(["丙", "", 223456789])
    bio = io.BytesIO()
    wb.save(bio)
    res = P.parse_file(bio.getvalue(), "z.xlsx", "customers")
    warned = {w["row"] for w in res["warnings"] if "開頭的 0" in w["message"]}
    assert warned == {2, 4}
    pw = _parse([["料號", "品名"], [1234, "A"], ["01234", "B"]], kind="parts")
    assert any("料號" in w["field"] and "數字格式" in w["message"] for w in pw["warnings"])
    assert [r["partNo"] for r in pw["rows"]] == ["1234", "01234"]


# ── CSV ──────────────────────────────────────────────────────────────────────

def _csv(text, enc):
    return text.encode(enc)


@pytest.mark.parametrize("enc", ["utf-8-sig", "utf-8", "cp950"])
def test_csv_encodings(enc):
    res = P.parse_file(_csv("公司名稱,統一編號\n大安電腦,12345675\n", enc), "a.csv", "customers")
    assert res["rows"][0]["name"] == "大安電腦" and res["rows"][0]["taxId"] == "12345675"


def test_csv_undecodable_is_a_plain_message():
    with pytest.raises(P.ParseError, match="編碼"):
        P.parse_file(b"\xff\xfe\xfa\xfb\xfc,\x81\n", "a.csv", "customers")


def test_csv_header_only_and_blank_lines():
    with pytest.raises(P.ParseError, match="沒有資料列"):
        P.parse_file("公司名稱,統一編號\n\n\n".encode("utf-8"), "a.csv", "customers")


# ── 警告（只是警告）、員工密碼 ──────────────────────────────────────────────

def test_ubn_and_email_checks_are_warnings_not_errors():
    res = _parse([CUST_HEAD, ["甲", "12345678", "", "not-an-email", "", "", ""], ["乙", "", "", "", "", "", ""]])
    assert res["rowCount"] == 2
    msgs = " ".join(w["message"] for w in res["warnings"])
    assert "統編" in msgs and "Email" in msgs
    assert res["rows"][0]["taxId"] == "12345678", "仍照原樣交給 import-rows（打錯＝新客戶，所以頁面要先提示）"


def test_user_password_column_is_ignored_and_the_value_never_appears_in_output():
    res = _parse([["帳號＊", "姓名＊", "角色", "密碼"], ["w1", "王", "業務", "Super#Secret99"]], kind="users")
    assert res["rows"][0]["hadPassword"] is True and "Super#Secret99" not in json.dumps(res, ensure_ascii=False)
    assert res["ignoredColumns"] == ["密碼"] and any("密碼" in w["message"] for w in res["warnings"])


# ── 範本 ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", list(P.KINDS))
def test_template_round_trips_through_the_parser_and_example_row_is_skipped(kind):
    data = P.build_template(kind)
    wb = load_workbook(io.BytesIO(data))
    assert wb.sheetnames == ["資料", "說明"]
    head = [c.value for c in wb["資料"][1]]
    assert all(c["label"] in "".join(str(h) for h in head) for c in P.COLUMNS[kind])
    assert any("＊" in str(h) for h in head)
    assert str(wb["資料"]["A2"].value).startswith(P.EXAMPLE_MARK) or str(wb["資料"]["B2"].value or "") != ""
    # 範本原樣（只有範例列）上傳＝「沒有資料列」；用範本的表頭填一列真資料就能解析
    with pytest.raises(P.ParseError, match="沒有資料列"):
        P.parse_file(data, "t.xlsx", kind)
    assert P.parse_file(_xlsx([head, ["甲", "乙"] + [""] * (len(head) - 2)]), "t.xlsx", kind)["rowCount"] == 1


def test_template_text_format_keeps_leading_zeros_and_users_role_has_dropdown():
    wb = load_workbook(io.BytesIO(P.build_template("users")))
    ws = wb["資料"]
    assert ws.column_dimensions["A"].number_format == "@" and ws.column_dimensions["F"].number_format == "@"   # 整欄文字格式，不只前幾百列
    assert any("業務" in (dv.formula1 or "") for dv in ws.data_validations.dataValidation)


# ── API：開關、權限、稽核、無暫存 ───────────────────────────────────────────

def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _flag(on):
    from db import get_db
    from helpers import settings_groups, settings_registry as SR      # noqa: F401
    conn = get_db()
    try:
        SR.publish("import_wizard", {"enabled": 1 if on else 0}, reason="測試", user="imp_test", conn=conn)
    finally:
        conn.close()


def _post(client, h, kind, data, name="a.xlsx"):
    return client.post("/api/importer/parse", data={"kind": kind}, files={"file": (name, data, "application/octet-stream")}, headers=h)


def test_status_probe_works_with_the_flag_off_but_parse_and_template_are_404(client, make_user):
    h = _login(client, *make_user(username="imp_a", role="superadmin"))
    assert client.get("/api/importer/status", headers=h).json() == {"ok": True}
    assert client.get("/api/importer/templates/customers", headers=h).status_code == 404
    assert _post(client, h, "customers", _xlsx([CUST_HEAD, ["甲", ""]])).status_code == 404


def test_flag_on_template_and_parse_work_and_audit_has_no_cell_contents(client, make_user):
    h = _login(client, *make_user(username="imp_b", role="superadmin"))
    _flag(True)
    t = client.get("/api/importer/templates/customers", headers=h)
    assert t.status_code == 200 and t.content[:2] == b"PK" and "attachment" in t.headers["content-disposition"]
    assert t.headers["cache-control"] == "no-store"
    r = _post(client, h, "customers", _xlsx([CUST_HEAD, ["秘密公司名", "12345675", "0912345678", "", "", "", ""]]))
    assert r.status_code == 200 and r.json()["rowCount"] == 1 and r.headers["cache-control"] == "no-store"
    from db import get_db
    c = get_db()
    try:
        rows = [dict(x) for x in c.execute("SELECT * FROM audit_log WHERE action='import.parse'").fetchall()]
    finally:
        c.close()
    assert len(rows) == 1
    dump = json.dumps(rows, ensure_ascii=False, default=str)
    assert "秘密公司名" not in dump and "0912345678" not in dump and "sha256" in dump


def test_parse_errors_are_plain_400s(client, make_user):
    h = _login(client, *make_user(username="imp_c", role="superadmin"))
    _flag(True)
    r = _post(client, h, "customers", b"PK\x03\x04junk", "a.xlsx")
    assert r.status_code == 400 and "Excel" in r.json()["detail"]
    assert _post(client, h, "nope", b"x").status_code == 404


def test_access_users_is_superadmin_only_and_others_follow_module_permission(client, make_user):
    _flag(True)
    adm = _login(client, *make_user(username="imp_adm", role="admin"))
    viewer = _login(client, *make_user(username="imp_view", role="viewer"))
    assert client.get("/api/importer/templates/users", headers=adm).status_code == 403
    assert _post(client, adm, "users", b"x").status_code == 403
    assert client.get("/api/importer/templates/customers", headers=viewer).status_code == 403
    assert client.get("/api/importer/templates/parts", headers=viewer).status_code == 403
    assert client.get("/api/importer/templates/customers", headers=adm).status_code == 200
    assert client.get("/api/importer/templates/customers").status_code in (401, 403)


def test_end_to_end_parse_then_import_rows_preview_and_commit(client, make_user):
    h = _login(client, *make_user(username="imp_d", role="superadmin"))
    _flag(True)
    res = _post(client, h, "customers", _xlsx([CUST_HEAD, ["精靈公司", "12345675", "02-1111", "x@y.co", "", "", ""]])).json()
    pv = client.post("/api/customers/import-rows", json={"rows": res["rows"], "dryRun": True}, headers=h).json()
    assert pv["created"] == 1 and pv["planHash"]
    ok = client.post("/api/customers/import-rows", json={"rows": res["rows"], "dryRun": False, "planHash": pv["planHash"]}, headers=h)
    assert ok.status_code == 200 and ok.json()["created"] == 1
    pres = _post(client, h, "parts", _xlsx([["料號", "品名＊", "成本(未稅)"], ["P-1", "精靈料", 100]])).json()
    pp = client.post("/api/parts/import-rows", json={"rows": pres["rows"], "dryRun": True}, headers=h).json()
    assert pp["created"] == 1
    ures = _post(client, h, "users", _xlsx([["帳號＊", "姓名＊", "角色"], ["imp_new", "新人", "業務"]])).json()
    up = client.post("/api/users/import-rows", json={"rows": ures["rows"], "dryRun": True}, headers=h).json()
    assert up["created"] == 1 and up["planHash"]


def test_parse_writes_no_business_tables_and_keeps_no_upload(client, make_user, tmp_path):
    h = _login(client, *make_user(username="imp_e", role="superadmin"))
    _flag(True)
    from db import get_db

    def snap():
        c = get_db()
        try:
            return {t: c.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in ("customers", "parts", "users")}
        finally:
            c.close()
    before = snap()
    assert _post(client, h, "customers", _xlsx([CUST_HEAD, ["甲", ""]])).status_code == 200
    assert snap() == before


def test_parse_concurrency_is_limited_and_busy_is_a_plain_429(client, make_user, monkeypatch):
    import modules.importer.api as API

    class _Busy:
        def acquire(self, timeout=None):
            return False

        def release(self):
            raise AssertionError("沒拿到就不該釋放")
    h = _login(client, *make_user(username="imp_busy", role="superadmin"))
    _flag(True)
    monkeypatch.setattr(API, "_PARSE_SLOTS", _Busy())
    r = _post(client, h, "customers", _xlsx([CUST_HEAD, ["甲", ""]]))
    assert r.status_code == 429 and "稍等" in r.json()["detail"]


def test_csv_with_an_oversized_field_gets_a_specific_message():
    big = "公司名稱" + chr(10) + "x" * 200000 + chr(10)
    with pytest.raises(P.ParseError, match="內容太長"):
        P.parse_file(big.encode("utf-8"), "big.csv", "customers")


def test_xlsx_busy_is_not_turned_into_a_parse_error(monkeypatch):
    """同時解析太多（XlsxBusy）要原樣丟出去讓端點轉 429，不能被吞成 400 的 ParseError。"""
    from helpers import xlsx_guard as XG

    def _busy(*a, **k):
        raise XG.XlsxBusy("目前有其他人正在匯入檔案，請稍等幾秒再試")
    monkeypatch.setattr(XG, "read_rows", _busy)
    with pytest.raises(XG.XlsxBusy):
        _parse([CUST_HEAD, ["甲", ""]])
