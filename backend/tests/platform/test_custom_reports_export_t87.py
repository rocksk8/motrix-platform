# -*- coding: utf-8 -*-
"""T87 B2-S3：自訂報表匯出（Excel＋PDF 姊妹）。

- 閘門：旗標 ⇒ 登入 ⇒ 能力 view ⇒ 能力 export ⇒ 設定 export_scope ⇒ 擁有者／被分享者（分享設定每次重讀）⇒ 來源模組存取。
- 以執行者當下權限重算：看不到的欄位不出現、列範圍照舊；被分享者的原始定義若含他看不到的篩選 ⇒ 422（不外帶）。
- 輸出：哨兵值只出現在有權限者的檔；無權限者整包 xlsx 解壓逐檔掃不到；稽核 detail 不含值；公式注入中和；列數上限；冷卻；並行名額。
"""
import io
import json
import re
import threading
import zipfile

import openpyxl
import pytest

from db import get_db
from helpers import settings_registry as R
from helpers import xlsx_out as X
from modules.analytics.api import custom_reports as CR

BASE = "/api/custom-reports"
SENT = 7654321


def _login(client, make_user, name, role="sales", modules=None):
    kw = {"username": name, "role": role}
    if modules is not None:
        kw["modules"] = modules
    u, p = make_user(**kw)
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _set(**kv):
    c = get_db()
    try:
        R.publish("custom_reports", kv, reason="測試", user="sa_ex", conn=c)
    finally:
        c.close()
    R.invalidate()


@pytest.fixture(autouse=True)
def _on(client):
    CR.reset_rate_limit()
    X._export_times.clear()
    _set(enabled=1)
    yield
    X._export_times.clear()
    R.invalidate()


def _quote(**kw):
    row = {"quote_no": kw.pop("no", "EX-1"), "status": "草稿", "customer_name": "匯出客戶", "project_name": "專案", "total": 0, "pretax": 0,
           "data_json": "{}", "created_at": "2026-11-14T09:00:00", "updated_at": "2026-11-14T09:00:00", "deal_tag": "",
           "sales_person": "", "assigned_user_ids": "[]"}
    row.update(kw)
    c = get_db()
    try:
        cols = list(row)
        c.execute("INSERT INTO quotations (%s) VALUES (%s)" % (",".join(cols), ",".join("?" * len(cols))), [row[k] for k in cols])
        c.commit()
    finally:
        c.close()


def _mk(client, h, name="匯出報表", **kw):
    d = {"version": 1, "source": "quotation", "columns": ["quote_no", "customer_name", "total"]}
    d.update(kw)
    r = client.post(BASE, json={"name": name, "definition": d}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _xlsx(resp):
    assert resp.status_code == 200, resp.text
    return openpyxl.load_workbook(io.BytesIO(resp.content))


def _all_text(data: bytes) -> str:
    """整包解壓、逐檔串起來（工作表、共用字串、docProps…）。"""
    z = zipfile.ZipFile(io.BytesIO(data))
    return "\n".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist())


def _audits(action):
    c = get_db()
    try:
        return [dict(r) for r in c.execute("SELECT action, target_id, target_label, detail FROM audit_log WHERE action=? ORDER BY id", (action,))]
    finally:
        c.close()


# ── 內容 ──────────────────────────────────────────────────────────────────

def test_export_contains_title_conditions_rows_and_the_explanation_sheet(client, make_user):
    _quote(no="EX-10", total=SENT)
    h = _login(client, make_user, "ex_sa1", role="superadmin")
    rep = _mk(client, h, "季報", filters=[{"field": "customer_name", "op": "contains", "value": "匯出"}])
    r = client.post("%s/%d/export" % (BASE, rep["id"]), headers=h)
    wb = _xlsx(r)
    assert wb.sheetnames == ["報表", "說明"]
    ws = wb["報表"]
    assert "季報" in ws["A1"].value and "MOTRIX PLATFORM" in ws["A1"].value
    assert "匯出" in ws["A2"].value and ws["A5"].value == "報價單號"
    vals = [[c.value for c in row] for row in ws.iter_rows(min_row=6)]
    assert ["EX-10", "匯出客戶", SENT] in vals                                      # 正對照：有權限者的檔一定含哨兵
    assert ws.cell(row=6, column=3).number_format == "#,##0"
    info = {row[0].value: row[1].value for row in wb["說明"].iter_rows()}
    assert info["資料來源"] == "報價單" and info["已隱藏欄位數"] == 0 and info["列數"] == 1
    assert "attachment" in r.headers["content-disposition"] and ".xlsx" in r.headers["content-disposition"].lower()
    assert not any(isinstance(c.value, str) and c.value.startswith("=") for sh in wb for row in sh.iter_rows() for c in row)


def test_formula_injection_is_neutralised(client, make_user):
    _quote(no="EX-11", customer_name='=HYPERLINK("http://evil","x")')
    h = _login(client, make_user, "ex_sa2", role="superadmin")
    rep = _mk(client, h, "=cmd|' /c calc'!A1")
    wb = _xlsx(client.post("%s/%d/export" % (BASE, rep["id"]), headers=h))
    cells = [c for sh in wb for row in sh.iter_rows() for c in row if isinstance(c.value, str)]
    assert any("HYPERLINK" in c.value for c in cells)
    assert all(c.data_type != "f" and not c.value.startswith("=") for c in cells)


def test_summary_layout_exports_group_rows_and_total(client, make_user):
    _quote(no="EX-12", total=100)
    _quote(no="EX-13", total=200)
    h = _login(client, make_user, "ex_sa3", role="superadmin")
    rep = _mk(client, h, "彙總", layout="summary", columns=[], groupBy=[{"field": "customer_name"}], aggregates=[{"field": "total", "fn": "sum"}])
    ws = _xlsx(client.post("%s/%d/export" % (BASE, rep["id"]), headers=h))["報表"]
    flat = [[c.value for c in row] for row in ws.iter_rows(min_row=6)]
    assert ["匯出客戶", 300] in flat and flat[-1][0] == "總計" and flat[-1][1] == 300


# ── 以執行者權限重算（不外帶） ─────────────────────────────────────────────

def test_user_without_financial_access_gets_a_file_without_the_money_column_or_value(client, make_user):
    _quote(no="EX-20", total=SENT)
    h = _login(client, make_user, "ex_eng1", role="engineer", modules=["quotation"])
    rep = _mk(client, h, "工程師報表")
    r = client.post("%s/%d/export" % (BASE, rep["id"]), headers=h)
    wb = _xlsx(r)
    assert [c.value for c in wb["報表"][5]] == ["報價單號", "客戶"]
    text = _all_text(r.content)
    assert str(SENT) not in text and "含稅總額" not in text
    info = {row[0].value: row[1].value for row in wb["說明"].iter_rows()}
    assert info["已隱藏欄位數"] == 1
    d = json.dumps(_audits("export.xlsx"), ensure_ascii=False)
    assert str(SENT) not in d and "匯出客戶" not in d and "工程師報表" not in d


def test_shared_reader_cannot_export_a_report_whose_filters_use_fields_he_cannot_see(client, make_user):
    _set(sharing=1)
    _quote(no="EX-21", total=SENT)
    owner = _login(client, make_user, "ex_o4", role="superadmin")
    eng = _login(client, make_user, "ex_e4", role="engineer", modules=["quotation"])
    rep = _mk(client, owner, "金額門檻", filters=[{"field": "total", "op": "gte", "value": 5000000}])
    client.put("%s/%d" % (BASE, rep["id"]), json={"sharedWith": ["ex_e4"]}, headers=dict(owner, **{"If-Match": rep["etag"]}))
    r = client.post("%s/%d/export" % (BASE, rep["id"]), headers=eng)
    assert r.status_code == 422 and "5000000" not in r.text and str(SENT) not in r.text
    ok = client.post("%s/%d/export" % (BASE, rep["id"]), headers=owner)                  # 正對照：擁有者匯得出來
    assert str(SENT) in _all_text(ok.content)


def test_shared_reader_exports_with_own_row_scope(client, make_user):
    _set(sharing=1)
    owner = _login(client, make_user, "ex_o5", role="superadmin")
    sal = _login(client, make_user, "ex_s5", role="sales", modules=["quotation", "case_manage"])
    _quote(no="EX-OTHER", customer_name="別人的客戶")
    rep = _mk(client, owner, "全部", columns=["quote_no", "customer_name"])
    client.put("%s/%d" % (BASE, rep["id"]), json={"sharedWith": ["ex_s5"]}, headers=dict(owner, **{"If-Match": rep["etag"]}))
    r = client.post("%s/%d/export" % (BASE, rep["id"]), headers=sal)
    assert "別人的客戶" not in _all_text(r.content)
    assert "別人的客戶" in _all_text(client.post("%s/%d/export" % (BASE, rep["id"]), headers=owner).content)


# ── 閘門 ──────────────────────────────────────────────────────────────────

def test_gates_flag_capability_scope_ownership_and_module(client, make_user, monkeypatch):
    from helpers import perm
    h = _login(client, make_user, "ex_g1", role="sales", modules=["quotation", "case_manage"])
    other = _login(client, make_user, "ex_g2", role="sales", modules=["quotation", "case_manage"])
    rid = _mk(client, h)["id"]
    url = "%s/%d/export" % (BASE, rid)
    assert client.post(url, headers=other).status_code == 404 and client.post("%s/999999/export" % BASE, headers=h).status_code == 404
    assert client.post(url).status_code == 401
    real = perm.can
    monkeypatch.setattr(perm, "can", lambda u, k: False if k == CR.CAP_EXPORT else real(u, k))
    assert client.post(url, headers=h).status_code == 403
    monkeypatch.setattr(perm, "can", real)
    _set(export_scope=1)                                                                  # 只有最高管理者
    assert client.post(url, headers=h).status_code == 403
    sa = _login(client, make_user, "ex_g3", role="superadmin")
    sid = _mk(client, sa)["id"]
    X._export_times.clear()
    assert client.post("%s/%d/export" % (BASE, sid), headers=sa).status_code == 200
    _set(export_scope=2)                                                                  # 全關
    X._export_times.clear()
    assert client.post("%s/%d/export" % (BASE, sid), headers=sa).status_code == 403
    _set(export_scope=0, enabled=0)                                                       # 旗標關 ⇒ 404
    assert client.post(url, headers=h).status_code == 404


def test_module_access_is_rechecked_at_export(client, make_user):
    h = _login(client, make_user, "ex_g4", role="sales", modules=["quotation", "case_manage"])
    rid = _mk(client, h)["id"]
    c = get_db()
    try:
        c.execute("UPDATE users SET modules='[]' WHERE username='ex_g4'")
        c.commit()
    finally:
        c.close()
    h2 = _login(client, make_user, "ex_g4b", role="sales", modules=[])
    assert client.post("%s/%d/export" % (BASE, rid), headers=h2).status_code in (403, 404)


def test_sharing_turned_off_closes_the_shared_export(client, make_user):
    _set(sharing=1)
    a = _login(client, make_user, "ex_g5a", role="sales", modules=["quotation", "case_manage"])
    b = _login(client, make_user, "ex_g5b", role="sales", modules=["quotation", "case_manage"])
    rep = _mk(client, a)
    client.put("%s/%d" % (BASE, rep["id"]), json={"sharedWith": ["ex_g5b"]}, headers=dict(a, **{"If-Match": rep["etag"]}))
    assert client.post("%s/%d/export" % (BASE, rep["id"]), headers=b).status_code == 200
    _set(sharing=0)
    X._export_times.clear()
    assert client.post("%s/%d/export" % (BASE, rep["id"]), headers=b).status_code == 404


# ── 上限、冷卻、並行 ──────────────────────────────────────────────────────

def test_row_cap_refuses_without_truncating(client, make_user, monkeypatch):
    from helpers import report_runner as RR
    for i in range(3):
        _quote(no="EX-3%d" % i)
    h = _login(client, make_user, "ex_sa6", role="superadmin")
    rid = _mk(client, h)["id"]
    monkeypatch.setattr(RR, "MAX_EXPORT_ROWS", 2)
    r = client.post("%s/%d/export" % (BASE, rid), headers=h)
    assert r.status_code == 422 and r.json()["detail"]["reason"] == "too_many_rows" and "application/vnd" not in r.headers.get("content-type", "")


def test_excel_cooldown_429_and_validation_errors_do_not_consume_it(client, make_user):
    h = _login(client, make_user, "ex_sa7", role="superadmin")
    rid = _mk(client, h)["id"]
    c = get_db()
    try:                                                                                  # 存檔後才變壞的定義（欄位被拿掉）
        bad = json.dumps({"version": 1, "source": "quotation", "columns": ["quote_no"], "filters": [{"field": "gone", "op": "eq", "value": "x"}]})
        c.execute("INSERT INTO custom_reports (username, name, source_id, definition_json, created_at, updated_at) VALUES ('ex_sa7','壞','quotation',?,?,?)",
                  (bad, "2026-11-14T10:00:00", "2026-11-14T10:00:00"))
        bad_id = c.execute("SELECT id FROM custom_reports WHERE name='壞'").fetchone()[0]
        c.commit()
    finally:
        c.close()
    assert client.post("%s/%d/export" % (BASE, bad_id), headers=h).status_code == 422
    assert client.post("%s/%d/export" % (BASE, rid), headers=h).status_code == 200       # 422 沒有吃掉冷卻
    r = client.post("%s/%d/export" % (BASE, rid), headers=h)
    assert r.status_code == 429 and "請等待" in r.text


def test_export_shares_the_concurrency_slot_and_releases_it(client, make_user, monkeypatch):
    h = _login(client, make_user, "ex_sa8", role="superadmin")
    rid = _mk(client, h)["id"]
    sem = threading.BoundedSemaphore(1)
    monkeypatch.setattr(CR, "_runs", sem)
    sem.acquire()
    r = client.post("%s/%d/export" % (BASE, rid), headers=h)
    assert r.status_code == 429 and r.json()["detail"]["reason"] == "busy"
    sem.release()
    assert client.post("%s/%d/export" % (BASE, rid), headers=h).status_code == 200
    assert sem.acquire(blocking=False) is True                                            # 成功後已歸還
    sem.release()
    X._export_times.clear()
    assert client.post("%s/%d/export" % (BASE, rid), headers=h).status_code == 200
    X._export_times.clear()
    monkeypatch.setattr(CR.RR, "assemble", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom internals")))
    r = client.post("%s/%d/export" % (BASE, rid), headers=h)
    assert r.status_code == 500 and "boom" not in r.text and "internals" not in r.text
    assert sem.acquire(blocking=False) is True                                            # 失敗路徑也歸還
    sem.release()


# ── 稽核與時間戳 ──────────────────────────────────────────────────────────

def test_export_writes_an_audit_row_without_values_and_stamps_last_exported_for_the_owner_only(client, make_user):
    _set(sharing=1)
    _quote(no="EX-40", customer_name="稽核客戶-5531", total=SENT)
    a = _login(client, make_user, "ex_a9", role="superadmin")
    b = _login(client, make_user, "ex_b9", role="superadmin")
    rep = _mk(client, a, "稽核報表", filters=[{"field": "customer_name", "op": "eq", "value": "稽核客戶-5531"}])
    client.put("%s/%d" % (BASE, rep["id"]), json={"sharedWith": ["ex_b9"]}, headers=dict(a, **{"If-Match": rep["etag"]}))
    assert client.post("%s/%d/export" % (BASE, rep["id"]), headers=b).status_code == 200
    assert client.get("%s/%d" % (BASE, rep["id"]), headers=a).json()["lastExportedAt"] is None   # 被分享者匯出不改擁有者的列
    X._export_times.clear()
    assert client.post("%s/%d/export" % (BASE, rep["id"]), headers=a).status_code == 200
    assert client.get("%s/%d" % (BASE, rep["id"]), headers=a).json()["lastExportedAt"]
    rows = _audits("export.xlsx")
    assert len(rows) == 2 and all(r["target_id"] == "custom_report" for r in rows)
    d = json.dumps(rows, ensure_ascii=False)
    assert "稽核客戶-5531" not in d and str(SENT) not in d and "稽核報表" not in d
    assert json.loads(rows[0]["detail"])["rows"] >= 1


# ── PDF 姊妹 ──────────────────────────────────────────────────────────────

def test_pdf_sibling_same_permissions_audit_and_does_not_use_the_excel_cooldown(client, make_user, monkeypatch):
    import pdf_gen
    from helpers import company_identity as CI
    html = []
    monkeypatch.setattr(CI, "require_for_output", lambda *a, **k: None)
    monkeypatch.setattr(pdf_gen, "html_to_pdf_bytes", lambda h: (html.append(h), b"%PDF-1.4 fake")[1])
    _quote(no="EX-50", total=SENT)
    eng = _login(client, make_user, "ex_eng_pdf", role="engineer", modules=["quotation"])
    sa = _login(client, make_user, "ex_sa_pdf", role="superadmin")
    rid_e = _mk(client, eng, "工程師")["id"]
    rid_s = _mk(client, sa, "管理員")["id"]
    assert client.post("%s/%d/export-pdf" % (BASE, rid_e), headers=sa).status_code == 404      # 同一套擁有者規則
    r = client.post("%s/%d/export-pdf" % (BASE, rid_e), headers=eng)
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and "7,654,321" not in html[-1] and str(SENT) not in html[-1] and "含稅總額" not in html[-1]
    assert client.post("%s/%d/export" % (BASE, rid_e), headers=eng).status_code == 200            # PDF 沒吃掉 Excel 冷卻
    r2 = client.post("%s/%d/export-pdf" % (BASE, rid_s), headers=sa)
    assert r2.status_code == 200 and "7,654,321" in html[-1]                                        # 正對照
    assert len(_audits("export.pdf")) == 2
    assert str(SENT) not in json.dumps(_audits("export.pdf"))
    from helpers import perm
    monkeypatch.setattr(perm, "can", lambda u, k: False if k == CR.CAP_EXPORT else True)
    assert client.post("%s/%d/export-pdf" % (BASE, rid_s), headers=sa).status_code == 403
