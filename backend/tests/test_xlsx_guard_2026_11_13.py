# -*- coding: utf-8 -*-
"""xlsx 上傳的「小檔案展開」守門（2026-11-13，hichan-9 稽核 H1 類；T82 共用 helper）。

事實：幾十 KB 的 xlsx 可以宣告 1,048,576 列×16,384 欄、塞一百萬個只有格式的空格、把資料放在第 1,000 萬列。
zip 比例／解壓總量擋不住；openpyxl 唯讀模式也會每列補滿宣告欄數。`helpers.xlsx_guard` 在讀任何儲存格之前先串流預掃。

觀測點：
- 單元：每個上限的拒絕（含恰好在線上／線外）、拒絕時**沒有讀內容**且很快（< 2s）、正常檔照常讀、deadline、slot
- 兩個既有匯入端點（外包名冊 `/api/contractors/import`、網路規劃書 `/api/network-plans/{id}/import/excel`）：
  炸彈 ⇒ 400（白話訊息）、正常檔 ⇒ 仍成功、列號對得上（空白列不能讓「第 N 列」錯位）
"""
import asyncio
import io
import os
import subprocess
import sys
import time
import zipfile

import pytest

pytest.importorskip("openpyxl")
from openpyxl import Workbook

from helpers import xlsx_guard as X

CT = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
      '<Default Extension="xml" ContentType="application/xml"/>'
      '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
      '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
RELS = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
WB = ('<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="資料" sheetId="1" r:id="rId1"/></sheets></workbook>')
WBR = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
       '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
HEAD = ('<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>')
TAIL = '</sheetData></worksheet>'


def _col(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _mk(chunks, title_xml=WB):
    """用串流壓縮組一個 xlsx（工作表 XML 由 chunks 產生，不在記憶體裡整份展開）。"""
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS)
        z.writestr("xl/workbook.xml", title_xml)
        z.writestr("xl/_rels/workbook.xml.rels", WBR)
        with z.open("xl/worksheets/sheet1.xml", "w") as f:
            for c in chunks:
                f.write(c.encode("utf-8"))
    return bio.getvalue()


def _cell(ref, text="x"):
    return '<c r="%s" t="inlineStr"><is><t>%s</t></is></c>' % (ref, text)


def _normal(rows=3):
    def g():
        yield HEAD + '<row r="1">' + _cell("A1", "姓名") + _cell("B1", "電話") + '</row>'
        for r in range(2, rows + 2):
            yield '<row r="%d">%s%s</row>' % (r, _cell("A%d" % r, "人%d" % r), _cell("B%d" % r, "09%08d" % r))
        yield TAIL
    return _mk(g())


def _rejected(data, **kw):
    t = time.time()
    with pytest.raises(X.XlsxRejected) as ei:
        X.guard(data, **kw)
    assert time.time() - t < 2.0, "拒絕要很快（沒有讀內容）"
    return str(ei.value)


# ───────────── 單元：guard ─────────────

def test_normal_file_passes_and_loads():
    data = _normal(5)
    X.guard(data)
    wb = X.load(data)
    try:
        got = list(X.rows(wb.active, values_only=True))
    finally:
        wb.close()
    assert got[0][:2] == ("姓名", "電話") and len(got) == 6 and got[5][0] == "人6"


def test_one_million_blank_styled_cells_rejected_fast():
    def g():
        yield HEAD + '<row r="1">'
        for i in range(1_000_000):
            yield '<c r="B1"/>'
        yield '</row>' + TAIL
    msg = _rejected(_mk(g()))
    assert "儲存格太多" in msg


def test_cells_cap_is_exact():
    lim = X.with_limits(max_cells=1000, max_row_tags=10_000)

    def rows(n):
        def g():
            yield HEAD
            for r in range(1, n // 10 + 1):
                yield '<row r="%d">%s</row>' % (r, "".join('<c r="%s%d"/>' % (_col(c), r) for c in range(1, 11)))
            yield TAIL
        return _mk(g())
    X.guard(rows(1000), lim)                          # 恰好 1000 格：過
    with pytest.raises(X.XlsxRejected):
        X.guard(rows(1010), lim)                      # 1010 格：拒


def test_column_over_limit_names_the_column():
    def g():
        yield HEAD + '<row r="1">' + _cell("A1") + _cell("AY1") + '</row>' + TAIL      # AY＝第 51 欄
    msg = _rejected(_mk(g()))
    assert "AY" in msg and "50" in msg
    def ok():
        yield HEAD + '<row r="1">' + _cell("A1") + _cell("AX1") + '</row>' + TAIL      # AX＝第 50 欄：過
    X.guard(_mk(ok()))


def test_row_number_far_below_rejected():
    def g():
        yield HEAD + '<row r="2">' + _cell("A2") + '</row><row r="10000000">' + _cell("A10000000") + '</row>' + TAIL
    assert "列太多" in _rejected(_mk(g()))


def test_row_tag_count_rejected():
    lim = X.with_limits(max_row_tags=100)

    def g():
        yield HEAD
        for r in range(1, 102):
            yield '<row r="%d"/>' % r
        yield TAIL
    with pytest.raises(X.XlsxRejected):
        X.guard(_mk(g()), lim)


def test_sheet_xml_size_rejected():
    lim = X.with_limits(max_sheet_xml=1 << 20)

    def g():
        yield HEAD
        for r in range(1, 20000):
            yield '<row r="%d">%s</row>' % (r, _cell("A%d" % r, "x" * 60))
        yield TAIL
    assert "太大" in _rejected(_mk(g()), limits=lim)


def test_cells_cap_is_total_across_sheets():
    """多張工作表：格數是全部合計，不是各表各算（否則拆成 100 張表就繞過）。"""
    lim = X.with_limits(max_cells=150)
    bio = io.BytesIO()
    wbk = Workbook()
    for i in range(3):
        ws = wbk.active if i == 0 else wbk.create_sheet()
        for r in range(1, 11):
            for c in range(1, 6):
                ws.cell(r, c, "v")          # 每表 50 格，三表 150 格＝剛好
    wbk.save(bio)
    X.guard(bio.getvalue(), lim)
    wbk.create_sheet().cell(1, 1, "v")
    b2 = io.BytesIO()
    wbk.save(b2)
    with pytest.raises(X.XlsxRejected):
        X.guard(b2.getvalue(), lim)         # 151 格


def test_zip_structure_rejections():
    with pytest.raises(X.XlsxRejected):
        X.guard(b"not a zip")
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as z:
        z.writestr("hello.txt", "x")
    with pytest.raises(X.XlsxRejected):
        X.guard(bio.getvalue())
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as z:
        z.writestr("xl/workbook.xml", WB)
        z.writestr("xl/vbaProject.bin", b"\x00")
    assert "巨集" in str(pytest.raises(X.XlsxRejected, X.guard, bio.getvalue()).value)


def test_zip_ratio_bomb_rejected():
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("xl/workbook.xml", WB)
        z.writestr("xl/media/image1.bin", b"\x00" * (20 << 20))          # 20MB 全 0：壓縮比極高
    assert len(bio.getvalue()) < (200 << 10)
    assert "太大" in str(pytest.raises(X.XlsxRejected, X.guard, bio.getvalue()).value)


def test_deadline_is_enforced_in_rows_and_prescan():
    wb = X.load(_normal(600))
    try:
        past = time.monotonic() - 1
        with pytest.raises(X.XlsxRejected):
            list(X.rows(wb.active, deadline=past, values_only=True))
    finally:
        wb.close()
    with pytest.raises(X.XlsxRejected):
        X.guard(_normal(3), deadline=time.monotonic() - 1)


def test_rows_max_rows():
    wb = X.load(_normal(20))
    try:
        with pytest.raises(X.XlsxRejected):
            list(X.rows(wb.active, max_rows=10, values_only=True))
        assert len(list(X.rows(wb.active, max_rows=21, values_only=True))) == 21      # 表頭＋20 列，恰好在線上
    finally:
        wb.close()


def test_declared_dimension_is_not_trusted():
    """宣告 A1:XFD1048576、實際只有兩列：讀出來只有那兩列（不補空格）。"""
    def g():
        yield HEAD.replace("<sheetData>", '<dimension ref="A1:XFD1048576"/><sheetData>')
        yield '<row r="1">' + _cell("A1", "姓名") + '</row><row r="2">' + _cell("A2", "甲") + '</row>' + TAIL
    wb = X.load(_mk(g()))
    try:
        t = time.time()
        got = list(X.rows(wb.active, values_only=True))
        assert time.time() - t < 2
    finally:
        wb.close()
    assert [r[0] for r in got] == ["姓名", "甲"] and all(len(r) == 50 for r in got)      # 截成 max_cols 寬，不是 16384


def test_slot_limits_concurrency():
    lim = X.with_limits(max_concurrent=1)
    with X.slot("t_conc", lim):
        with pytest.raises(X.XlsxBusy):
            with X.slot("t_conc", lim, wait=0.05):
                pass
    with X.slot("t_conc", lim, wait=0.05):          # 釋放後可再取
        pass
    assert issubclass(X.XlsxBusy, X.XlsxRejected)


def test_read_upload_stops_at_limit():
    from starlette.datastructures import UploadFile
    big = UploadFile(file=io.BytesIO(b"x" * (3 << 20)), filename="a.xlsx")
    with pytest.raises(X.XlsxRejected):
        asyncio.run(X.read_upload(big, X.with_limits(max_bytes=1 << 20)))
    ok = UploadFile(file=io.BytesIO(b"x" * 100), filename="a.xlsx")
    assert asyncio.run(X.read_upload(ok)) == b"x" * 100


def test_col_letters_roundtrip():
    for n in (1, 26, 27, 50, 51, 702, 703, 16384):
        assert X.col_number(X.col_letters(n)) == n


# ───────────── 既有匯入端點 ─────────────

def _auth(client, make_user, username, role="superadmin"):
    u, p = make_user(username=username, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _bomb_cells():
    def g():
        yield HEAD + '<row r="1">'
        for i in range(400_000):
            yield '<c r="B1"/>'
        yield '</row>' + TAIL
    return _mk(g())


def _contractor_xlsx(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(["姓名", "證件號碼"])
    for r in rows:
        ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_contractors_import_rejects_bomb_with_400(client, make_user):
    h = _auth(client, make_user, "xg_ct")
    t = time.time()
    r = client.post("/api/contractors/import", headers=h,
                    files={"file": ("a.xlsx", _bomb_cells(), "application/octet-stream")})
    assert r.status_code == 400 and "儲存格太多" in r.text, (r.status_code, r.text[:200])
    assert time.time() - t < 12


def test_contractors_import_rejects_oversized_upload(client, make_user):
    h = _auth(client, make_user, "xg_ct2")
    r = client.post("/api/contractors/import", headers=h,
                    files={"file": ("a.xlsx", b"x" * ((5 << 20) + 10), "application/octet-stream")})
    assert r.status_code == 400 and "太大" in r.text


def test_contractors_import_normal_file_and_row_numbers(client, make_user):
    """正對照：正常檔照常匯入；中間夾空白列時「第 N 列」仍對應試算表的列號（唯讀模式不可讓列號錯位）。"""
    h = _auth(client, make_user, "xg_ct3")
    data = _contractor_xlsx([["王大明", "A123456789"], [None, None], [None, "Z999999999"], ["李小華", "B223456789"]])
    r = client.post("/api/contractors/import", headers=h, files={"file": ("a.xlsx", data, "application/octet-stream")})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("created") == 2, j
    errs = j.get("errors") or []
    assert any(e["row"] == 4 and "沒有姓名" in e["message"] for e in errs), errs     # 第 4 列：有證件、沒姓名


def test_contractors_import_row_cap(client, make_user):
    h = _auth(client, make_user, "xg_ct4")
    data = _contractor_xlsx([["P%d" % i, ""] for i in range(5001)])
    r = client.post("/api/contractors/import", headers=h, files={"file": ("a.xlsx", data, "application/octet-stream")})
    assert r.status_code == 400 and "5000" in r.text, (r.status_code, r.text[:200])


def _plan_id(client, h):
    r = client.post("/api/network-plans", headers=h, json={"siteName": "守門測試案場"})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_netplan_import_rejects_bomb_with_400(client, make_user):
    h = _auth(client, make_user, "xg_np")
    pid = _plan_id(client, h)
    r = client.post("/api/network-plans/%s/import/excel" % pid, headers=h,
                    files={"file": ("a.xlsx", _bomb_cells(), "application/octet-stream")})
    assert r.status_code == 400 and "儲存格太多" in r.text, (r.status_code, r.text[:200])


def test_netplan_import_roundtrip_still_works(client, make_user):
    """正對照：本系統匯出的範本（含多個分頁）改幾格再匯入，仍成功。"""
    from modules.netplan.export import SECTIONS
    h = _auth(client, make_user, "xg_np2")
    pid = _plan_id(client, h)
    key, title, columns = SECTIONS[0]
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws.append([label for _k, label in columns])
    ws.append(["中華電信"] + [None] * (len(columns) - 1))
    b = io.BytesIO()
    wb.save(b)
    r = client.post("/api/network-plans/%s/import/excel" % pid, headers=h,
                    files={"file": ("a.xlsx", b.getvalue(), "application/octet-stream")})
    assert r.status_code == 200, (r.status_code, r.text[:300])


# ───────────── 第二輪（hichan-12 審查 H1／M1＋PM 的子行程隔離層）─────────────
# 每個案例都是 hichan-12 實測過「舊版預掃放行」的繞法；現在要在預掃（真的 XML 解析）就被擋，且子行程隔離層再兜一層。

def _sheet_zip(sheet_xml_chunks, rels_target="worksheets/sheet1.xml", sheet_part="xl/worksheets/sheet1.xml", extra=None):
    bio = io.BytesIO()
    wbr = WBR.replace('Target="worksheets/sheet1.xml"', 'Target="%s"' % rels_target)
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS)
        z.writestr("xl/workbook.xml", WB)
        z.writestr("xl/_rels/workbook.xml.rels", wbr)
        for name, content in (extra or {}).items():
            z.writestr(name, content)
        with z.open(sheet_part, "w") as f:
            for c in sheet_xml_chunks:
                f.write(c.encode("utf-8"))
    return bio.getvalue()


def test_evasion_a_spaces_and_single_quotes_in_cell_ref():
    data = _sheet_zip([HEAD, "<row r='1'><c r = 'XFD1' t='inlineStr'><is><t>x</t></is></c></row>", TAIL])
    assert "XFD" in _rejected(data)


def test_evasion_b_gt_inside_attribute_value():
    data = _sheet_zip([HEAD, '<row r="1"><c r="A1" s="a&gt;b" note="x>y"/><c r="XFD1"/></row>', TAIL])
    assert "XFD" in _rejected(data)


def test_evasion_c_namespace_prefixed_tags():
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    data = _sheet_zip(['<?xml version="1.0"?><x:worksheet xmlns:x="%s"><x:sheetData>' % ns,
                       '<x:row r="1"><x:c r="XFD1"/></x:row></x:sheetData></x:worksheet>'])
    assert "XFD" in _rejected(data)


def test_evasion_c2_cells_without_r_attribute_count_columns():
    """沒有 r 屬性的儲存格靠順序決定欄：一列 60 個 <c/> 也要拒（欄數上限）。"""
    data = _sheet_zip([HEAD, '<row r="1">' + "<c/>" * 60 + "</row>", TAIL])
    assert "欄" in _rejected(data)


def test_evasion_d_rels_target_with_dotdot_is_normalized_and_scanned():
    """rels 的目標寫成 ../xl/worksheets/sheet1.xml：舊版 KeyError ⇒ 整張表沒掃卻照讀。現在 normpath 後照樣掃到。"""
    data = _sheet_zip([HEAD, '<row r="1"><c r="XFD1"/></row>', TAIL], rels_target="../xl/worksheets/sheet1.xml")
    assert "XFD" in _rejected(data)


def test_rels_target_outside_archive_or_missing_is_rejected_not_skipped():
    assert "結構" in _rejected(_sheet_zip([HEAD, TAIL], rels_target="../../evil.xml", sheet_part="evil.xml"))
    assert "結構" in _rejected(_sheet_zip([HEAD, TAIL], rels_target="worksheets/nope.xml"))


def test_dtd_and_entities_rejected():
    xml = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]>' + HEAD.split("?>", 1)[1] + TAIL
    assert "格式不正常" in _rejected(_sheet_zip([xml]))


def test_styles_xf_bomb_rejected_fast():
    """styles.xml 放 40 萬個 <xf>（zip 只有幾百 KB）：舊版 load_workbook 要 9 秒、757MB。"""
    xfs = "".join('<xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>' for _ in range(400_000))
    styles = ('<?xml version="1.0"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              '<cellXfs count="400000">%s</cellXfs></styleSheet>' % xfs)
    data = _sheet_zip([HEAD, '<row r="1">' + _cell("A1") + "</row>", TAIL], extra={"xl/styles.xml": styles})
    assert len(data) < (2 << 20)
    msg = _rejected(data, limits=X.with_limits(max_styles_xml=64 << 20))        # 放寬大小上限，單看 xf 數
    assert "格式太多" in msg
    assert "格式資訊太多" in _rejected(data)                                      # 預設的大小上限（5MB）也擋得住


def test_junk_after_sheetdata_is_bounded_by_part_size():
    """資料只有 3 列、後面接 25MB 的 mergeCell：舊版 rows() 最後一次 next() 解析尾巴 12.6 秒。大小上限（12MB）與位置無關。"""
    def g():
        yield HEAD + '<row r="1">' + _cell("A1") + "</row></sheetData><mergeCells>"
        for i in range(850_000):
            yield '<mergeCell ref="A%d:B%d"/>' % (i + 2, i + 2)
        yield "</mergeCells></worksheet>"
    assert "太大" in _rejected(_sheet_zip(g()))


def test_hidden_sheets_are_scanned_too():
    """只掃可見表不夠：隱藏的工作表一樣會被 openpyxl 解析。"""
    wb_two = WB.replace("</sheets>", '<sheet name="藏" sheetId="2" state="hidden" r:id="rId2"/></sheets>')
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS)
        z.writestr("xl/workbook.xml", wb_two)
        z.writestr("xl/_rels/workbook.xml.rels", WBR.replace("</Relationships>", '<Relationship Id="rId2" Type="x" Target="worksheets/sheet2.xml"/></Relationships>'))
        z.writestr("xl/worksheets/sheet1.xml", HEAD + '<row r="1">' + _cell("A1") + "</row>" + TAIL)
        z.writestr("xl/worksheets/sheet2.xml", HEAD + '<row r="1"><c r="XFD1"/></row>' + TAIL)
    assert "XFD" in _rejected(bio.getvalue())


def test_rows_pads_to_max_col_not_to_declared_width():
    """就算預掃被繞過，rows() 的 max_col 也讓每列最多 max_cols 寬（openpyxl 自己截寬，不管 XML 怎麼寫）。"""
    wb = Workbook()
    ws = wb.active
    ws.append(["a", "b"])
    ws["XFD3"] = "far"
    b = io.BytesIO()
    wb.save(b)
    from openpyxl import load_workbook
    w = load_workbook(io.BytesIO(b.getvalue()), read_only=True)
    s = w.active
    s.reset_dimensions()
    got = list(X.rows(s, values_only=True))
    w.close()
    assert all(len(r) == 50 for r in got) and got[2][49] is None


# ───────────── read_rows：子行程隔離 ─────────────

def test_read_rows_basic_in_child_process():
    res = X.read_rows(_normal(4), slot_name="t_basic")
    assert res["titles"] == ["資料"]
    rows_ = res["sheets"][0]["rows"]
    assert rows_[0] == ["姓名", "電話"] and rows_[4] == ["人5", "0900000005"]


def test_read_rows_matches_in_process_result():
    data = _normal(6)
    a = X.read_rows(data, slot_name="t_cmp1")
    b = X.read_rows(data, isolated=False, slot_name="t_cmp2")
    assert a == b


def test_read_rows_types_dates_formulas_pick_and_trim():
    import datetime
    wb = Workbook()
    ws = wb.active
    ws.title = "說明"
    ws.append(["這是說明"])
    d = wb.create_sheet("資料")
    d.append(["日期", "數字", "公式", "文字"])
    d.append([datetime.datetime(2026, 11, 13, 9, 30), 12, "=B2+1", "x"])
    d.append([None, None, None, None])
    d.append(["a"])
    b = io.BytesIO()
    wb.save(b)
    res = X.read_rows(b.getvalue(), pick={"prefer": "資料", "exclude": ["說明"]}, with_types=True, data_only=False, slot_name="t_types")
    assert [s["name"] for s in res["sheets"]] == ["資料"] and res["titles"] == ["說明", "資料"]
    rows_ = res["sheets"][0]["rows"]
    assert rows_[1][0] == [datetime.datetime(2026, 11, 13, 9, 30), "d"]          # 日期還原成 datetime
    assert rows_[1][1] == [12, "n"] and rows_[1][2][1] == "f" and rows_[1][3] == ["x", "s"]
    assert rows_[2] == [] and rows_[3] == [["a", "s"]]                            # 空白列＝空、尾端空格去掉；列號不錯位
    # 只給 prefer 找不到時退到第一張不在 exclude 的
    res2 = X.read_rows(b.getvalue(), pick={"prefer": "不存在", "exclude": ["說明"]}, slot_name="t_types2")
    assert [s["name"] for s in res2["sheets"]] == ["資料"]
    # sheets＝指定名稱
    res3 = X.read_rows(b.getvalue(), sheets=["說明"], slot_name="t_types3")
    assert res3["sheets"][0]["rows"] == [["這是說明"]]


def test_read_rows_rejects_bombs_without_touching_openpyxl_cost():
    t = time.time()
    with pytest.raises(X.XlsxRejected):
        X.read_rows(_sheet_zip([HEAD, '<row r="1"><c r="XFD1"/></row>', TAIL]), slot_name="t_bomb")
    assert time.time() - t < 8


def test_read_rows_max_rows_and_busy():
    with pytest.raises(X.XlsxRejected) as ei:
        X.read_rows(_normal(30), max_rows=11, header_rows=1, slot_name="t_cap")
    assert "10" in str(ei.value)
    lim = X.with_limits(max_concurrent=1)
    with X.slot("t_busy", lim):
        with pytest.raises(X.XlsxBusy):
            X.read_rows(_normal(2), lim, slot_name="t_busy")


def test_hard_timeout_kills_the_child():
    """硬逾時：到了父行程直接殺子行程（deadline＋margin 都壓到 0 ⇒ 子行程連開機都來不及）。"""
    lim = X.with_limits(deadline_seconds=0.001, hard_margin=0.0)
    t = time.time()
    with pytest.raises(X.XlsxRejected) as ei:
        X.read_rows(_normal(3), lim, slot_name="t_kill")
    assert "太久" in str(ei.value) and time.time() - t < 5


def test_child_memory_limit_is_applied():
    """子行程記憶體上限真的生效：壓到 24MB，連 openpyxl 都載不進去（光 import 就約 27MB commit）⇒ 子行程失敗 ⇒ 拒絕（不是 200）；
    同一份檔案在預設上限（768MB）下是成功的（見 test_read_rows_basic_in_child_process）——證明上限有咬到、而且預設值夠用。
    （numpy 的 OpenBLAS 不壓成單執行緒會預留約 750MB commit，上限就形同虛設：子行程環境變數已設 OPENBLAS_NUM_THREADS=1。）"""
    lim = X.with_limits(max_child_memory=24 << 20)
    with pytest.raises(X.XlsxRejected) as ei:
        X.read_rows(_normal(3), lim, slot_name="t_mem")
    assert "處理失敗" in str(ei.value) or "記憶體" in str(ei.value) or "讀不出來" in str(ei.value), str(ei.value)


def test_result_size_cap():
    lim = X.with_limits(max_result_bytes=2000)
    with pytest.raises(X.XlsxRejected):
        X.read_rows(_normal(200), lim, slot_name="t_res")


def test_contractors_5001_rows_with_xfd_cell_is_rejected_not_700mb(client, make_user):
    """hichan-12 實測：41KB、5001 列、每列一個 XFD 儲存格 ⇒ 舊版放行、單一請求 RSS 699MB。"""
    h = _auth(client, make_user, "xg_ct9")

    def g():
        yield HEAD + '<row r="1">' + _cell("A1", "姓名") + "</row>"
        for r in range(2, 5003):
            yield '<row r="%d">%s<c r="XFD%d" t="inlineStr"><is><t>z</t></is></c></row>' % (r, _cell("A%d" % r, "P%d" % r), r)
        yield TAIL
    data = _sheet_zip(g())
    assert len(data) < (500 << 10)
    t = time.time()
    r = client.post("/api/contractors/import", headers=h, files={"file": ("a.xlsx", data, "application/octet-stream")})
    assert r.status_code == 400 and "XFD" in r.text, (r.status_code, r.text[:200])
    assert time.time() - t < 12


def test_netplan_import_styles_bomb_400(client, make_user):
    h = _auth(client, make_user, "xg_np9")
    pid = _plan_id(client, h)
    xfs = "".join('<xf numFmtId="0"/>' for _ in range(400_000))
    styles = ('<?xml version="1.0"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              '<cellXfs>%s</cellXfs></styleSheet>' % xfs)
    data = _sheet_zip([HEAD, '<row r="1">' + _cell("A1") + "</row>", TAIL], extra={"xl/styles.xml": styles})
    r = client.post("/api/network-plans/%s/import/excel" % pid, headers=h, files={"file": ("a.xlsx", data, "application/octet-stream")})
    assert r.status_code == 400, (r.status_code, r.text[:200])


# ───────────── 第三輪（hichan-12 抽查）：DTD 藏在長註解後、巢狀深度、排隊上限、子行程直譯器 ─────────────

def test_dtd_hidden_after_long_comment_is_rejected():
    """hichan-12 L1：以前只掃前 4096 位元組；DOCTYPE 放在 5000 位元組的註解後面會放行。"""
    sheet = ('<?xml version="1.0"?><!--' + "p" * 5000 + '-->' + '<!DOCTYPE worksheet [<!ENTITY a "hello">]>'
             + HEAD.split("?>", 1)[1] + '<row r="1">' + _cell("A1", "&a;") + "</row>" + TAIL)
    assert "格式不正常" in _rejected(_sheet_zip([sheet]))


def test_dtd_split_across_stream_chunks_and_in_small_parts():
    """DOCTYPE 出現在工作表很後面（跨過串流讀取的區塊邊界）也要擋；workbook 這類小部件整份掃。"""
    pad = "<!--" + "p" * 70000 + "-->"
    body = '<row r="1">' + _cell("A1") + "</row>"
    sheet = HEAD + body + pad + "<!DOCTYPE x>" + TAIL
    assert "格式不正常" in _rejected(_sheet_zip([sheet]))
    wb = '<?xml version="1.0"?><!--' + "p" * 5000 + '--><!DOCTYPE x [<!ENTITY a "b">]>' + WB.split("?>", 1)[1]
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS)
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", WBR)
        z.writestr("xl/worksheets/sheet1.xml", HEAD + body + TAIL)
    assert "格式不正常" in _rejected(bio.getvalue())


def test_utf16_xml_part_is_rejected():
    """UTF-16 的 XML 逐位元組掃不到 DOCTYPE；xlsx 的 XML 一律 UTF-8，直接拒絕。"""
    sheet = (HEAD + '<row r="1">' + _cell("A1") + "</row>" + TAIL).replace("UTF-8", "UTF-16")
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS)
        z.writestr("xl/workbook.xml", WB)
        z.writestr("xl/_rels/workbook.xml.rels", WBR)
        z.writestr("xl/worksheets/sheet1.xml", b"\xff\xfe" + sheet.encode("utf-16-le"))
    assert "格式不正常" in _rejected(bio.getvalue())


def test_deep_nesting_rejected_fast_and_normal_depth_ok():
    """hichan-12 L2：170 萬層巢狀（zip 只有 16KB）以前放行、7.9 秒、子行程 532MB。"""
    deep = HEAD + '<row r="1">' + _cell("A1") + "</row>" + "<q>" * 200_000 + "</q>" * 200_000 + TAIL
    t = time.time()
    assert "格式不正常" in _rejected(_sheet_zip([deep]))
    assert time.time() - t < 2
    X.guard(_normal(3))                                 # 正對照：真檔（約 6 層）不受影響
    ok = HEAD + '<row r="1">' + _cell("A1") + "</row>" + "<q>" * 40 + "</q>" * 40 + TAIL
    X.guard(_sheet_zip([ok]))                           # 40 層仍在上限內


def test_slot_waiters_are_capped_fail_fast():
    """hichan-12 L3：排隊等名額的執行緒超過 max_waiting 就立刻 XlsxBusy，不讓排隊占滿共用執行緒池。"""
    import threading
    lim = X.with_limits(max_concurrent=1, max_waiting=2)
    results = []
    gate = threading.Event()

    def waiter():
        try:
            with X.slot("t_waiters", lim, wait=3.0):
                results.append("ok")
        except X.XlsxBusy:
            results.append("busy")

    with X.slot("t_waiters", lim):
        ts = [threading.Thread(target=waiter) for _ in range(2)]
        [t.start() for t in ts]
        time.sleep(0.3)                                 # 兩個排隊中
        t0 = time.time()
        with pytest.raises(X.XlsxBusy):                 # 第三個：立刻拒絕（不等 wait 的秒數）
            with X.slot("t_waiters", lim, wait=3.0):
                pass
        assert time.time() - t0 < 1.0
    [t.join(10) for t in ts]
    assert results == ["ok", "ok"]                      # 前兩個排隊的最後都拿到名額


def test_child_uses_real_interpreter_not_venv_trampoline():
    """hichan-12：虛擬環境的 python.exe 只是轉接殼（真直譯器是孫行程）；子行程要直接用真直譯器，記憶體上限才算得到它。"""
    exe, paths = X._child_python()
    if sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        assert exe == sys._base_executable and paths, (exe, paths)
    else:
        assert exe == sys.executable and paths == []
    res = X.read_rows(_normal(3), slot_name="t_real_py")           # 無論哪種環境：照樣讀得出來（openpyxl 在子行程可 import）
    assert res["sheets"][0]["rows"][0][:2] == ["姓名", "電話"]


def test_kill_tree_takes_children_too():
    """逾時殺行程要連底下的行程一起殺（不留孫行程）。"""
    code = ("import subprocess,sys,time;"
            "c=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);print(c.pid,flush=True);time.sleep(60)")
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    child_pid = int(p.stdout.readline())
    X._kill_tree(p)
    p.wait(10)
    time.sleep(0.5)
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", "PID eq %d" % child_pid], capture_output=True, text=True).stdout
        assert str(child_pid) not in out, "孫行程還活著"
    else:
        with pytest.raises(OSError):
            os.kill(child_pid, 0)
