# -*- coding: utf-8 -*-
"""舊資料 quotations.total／pretax 存成文字（"12,345"）時，除了應收帳齡（T87 已防）以外的頁面也不可 500。

做法：①模組內輔助 `modules/arap/money_num.py`、`modules/case/money_num.py`（analytics 沿用 `reports._money`、pdf_gen 沿用 `tax_calc._parse_money`；與 `tax_calc._parse_money`／`reports._num_or_bad` 同規則，逐項比對）
②掃全部沒有路徑參數（單號參數代入文字單）的 GET 端點，不可丟例外或回 5xx ③原始碼守門：不再有 `float(<列>["total"|"pretax"] or 0)`
④數字正確（轉成數字，不是壞值當 0）；乾淨資料不變。不改任何正式機資料。
"""
import math
import re
from pathlib import Path

import pytest

from modules.arap.money_num import money_num
from modules.case.money_num import money_num as case_money_num
from tests._requires import requires_module
from tests.test_std_reports_t87_2026_11_14 import _case, _login, _uid

BACKEND = Path(__file__).resolve().parents[1]

# 外連型端點（地圖圖磚等）：測試網路守門會擋，與本題無關
_SKIP = re.compile(r"tile|geocode|/map|photo|attachments/open|download")


# ── ① 共用輔助 ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("v,exp", [
    (None, 0), ("", 0), ("   ", 0), (0, 0), (12345, 12345), (12.5, 12.5), ("12,345", 12345), ("1,250.5", 1250.5),
    (" 7 ", 7), ("5x00", 0), ("abc", 0), (True, 0), (float("nan"), 0), (float("inf"), 0), ("nan", 0), ("inf", 0), ([], 0), ({}, 0),
])
def test_money_num_values(v, exp):
    assert money_num(v) == exp


def test_arap_and_case_copies_are_identical_in_behaviour():
    import inspect
    from modules.arap import money_num as A
    from modules.case import money_num as C
    assert inspect.getsource(A.money_num) == inspect.getsource(C.money_num)         # 兩份模組內副本不可漂移（升核心版時一起收斂）
    for v in (None, "", "12,345", "5x00", True, 7, 7.25, float("nan"), "inf", " 9 "):
        assert A.money_num(v) == C.money_num(v)


def test_pdf_gen_wrapper_agrees():
    import pdf_gen
    for v in (None, "", "12,345", "1,250.5", "5x00", True, 7, float("nan"), "inf"):
        assert pdf_gen._money_num(v) == money_num(v)


def test_money_num_default_and_identity():
    assert money_num("x", default=None) is None and money_num(None, default=-1) == -1
    n = 105000
    assert money_num(n) is n                                  # 乾淨的數字原樣（既有輸出逐位元不變）
    assert isinstance(money_num("12,345"), int) and isinstance(money_num("1.5"), float)


@pytest.mark.parametrize("v", [None, "", "12,345", "1,250.5", "5x00", True, 7, 7.25, float("nan"), float("inf"), "inf", " 9 "])
def test_money_num_agrees_with_t87_rules(v):
    """與 T87 款項防禦的兩份既有規則一致：能解析的數字相同，壞值 ⇒ 都「不是數字」（這裡以 default 表示）。"""
    from helpers.tax_calc import _parse_money, _MONEY_BAD
    from modules.analytics.api import reports as R
    a, b = _parse_money(v), R._num_or_bad(v)
    for t in (a, b):
        if t is None or t is _MONEY_BAD or t is R._BAD:
            assert money_num(v) == 0
        else:
            assert money_num(v) == t and not (isinstance(t, float) and math.isnan(t))


# ── ② 端點掃描 ─────────────────────────────────────────────────────────────
pytestmark_case = requires_module("case", "本檔建立報價單資料並打各報表／案件端點")


@pytest.fixture()
def world(client, make_user):
    import helpers.xlsx_out as X
    X._export_times.clear()
    cred = make_user("txt_sa", role="superadmin")
    h = _login(client, *cred)
    i = _uid("txt_sa")
    return h, i


@pytestmark_case
def test_every_plain_get_endpoint_survives_text_total(client, world, _app):
    h, i = world
    _case("TXT-1", i, "txt_sa", pretax="11,757", total="12,345",
          pay=[{"type": "訂金", "amount": 5000, "received": False}, {"type": "尾款", "received": False}])
    _case("TXT-2", i, "txt_sa", pretax="abc", total="oops", pay=[{"type": "全額", "amount": 100, "received": True}])   # 壞到無法解析也不 500
    _case("TXT-OK", i, "txt_sa", pay=[{"type": "全額", "amount": 105000, "received": False}])
    bad, n = [], 0
    for path, ops in _app.openapi()["paths"].items():
        if "get" not in ops or not path.startswith("/api/"):
            continue
        for no in ("TXT-1", "TXT-2"):
            p2 = re.sub(r"\{(quote_no|no|qno|quoteNo|quote_id)\}", no, path)
            if "{" in p2 or _SKIP.search(p2):
                continue
            n += 1
            try:
                resp = client.get(p2, headers=h)
            except Exception as e:                                           # noqa: BLE001  TestClient 會把伺服器例外直接丟出來
                bad.append((p2, "EXC " + repr(e)[:160]))
                continue
            if resp.status_code >= 500:
                bad.append((p2, resp.status_code, resp.text[:120]))
            if "{" not in path:
                break                                                         # 沒有單號參數的端點只打一次
    assert n > 150, n                                                         # 正對照：確實掃到一大批端點
    assert not bad, bad


@pytestmark_case
def test_listing_sorting_and_case_pages_with_text_total(client, world):
    h, i = world
    _case("TXT-1", i, "txt_sa", pretax="11,757", total="12,345")
    for url in ("/api/quotations?sort=total&dir=desc&counts=1&with_sales_owner=1&include_project_margin=1&with_waiting_on=1&with_dev_case=1",
                "/api/quotations?mine=1", "/api/quotations/TXT-1", "/api/quotations/TXT-1/finance-summary",
                "/api/reports/financial", "/api/reports/customer-history", "/api/reports/monthly-trend",
                "/api/reports/expenses-monthly", "/api/reports/tax-export/pdf", "/api/reports/financial/excel", "/api/reports/financial/pdf"):
        r = client.get(url, headers=h)
        assert r.status_code < 500, (url, r.status_code, r.text[:200])


# ── ④ 數字正確（轉成數字，而不是壞值當 0） ──────────────────────────────────
@pytestmark_case
def test_values_are_converted_not_zeroed(client, world):
    h, i = world
    _case("TXT-1", i, "txt_sa", pretax="11,757", total="12,345", pay=[{"type": "全額", "amount": 12345, "received": False}])
    r = client.get("/api/reports/customer-history", headers=h)
    assert r.status_code == 200, r.text[:200]
    txns = [t for c in r.json()["customers"] for t in c.get("transactions", []) if t["quoteNo"] == "TXT-1"]
    assert txns and txns[0]["total"] == 12345
    r = client.get("/api/quotations/TXT-1/finance-summary", headers=h)
    assert r.status_code == 200, r.text[:200]
    assert r.json()["receivable"]["receivableTotal"] == 12345



@pytestmark_case
def test_approval_queue_detail_with_text_total_does_not_500(client, world):
    """簽核佇列詳情（detail_quotation）的「總金額」用 format(…, ",.0f")：total 是文字會 ValueError ⇒ 簽核頁打不開。"""
    from db import get_db
    from modules.case.api.quotations import detail_quotation
    h, i = world
    _case("TXT-1", i, "txt_sa", pretax="11,757", total="12,345")
    _case("TXT-2", i, "txt_sa", pretax="abc", total="oops")
    _case("TXT-OK", i, "txt_sa")
    conn = get_db()
    try:
        vals = {no: next(f["value"] for f in detail_quotation(conn, no)["fields"] if f["label"] == "總金額") for no in ("TXT-1", "TXT-2", "TXT-OK")}
    finally:
        conn.close()
    assert vals == {"TXT-1": "12,345", "TXT-2": "0", "TXT-OK": "105,000"}, vals


@pytestmark_case
def test_recognition_flags_null_or_unparseable_amount_stays_null_not_zero(client, world):
    """沒有金額（NULL／壞值）在旗標清單裡輸出 null（改前就是 null）；能解析的文字轉成數字；乾淨數字不變。"""
    from db import get_db
    from modules.case.recognition import recognition_flags
    h, i = world
    _case("TXT-N", i, "txt_sa", pretax=None, total=None)
    _case("TXT-B", i, "txt_sa", pretax="abc", total="oops")
    _case("TXT-T", i, "txt_sa", pretax="11,757", total="12,345")
    _case("TXT-OK", i, "txt_sa")
    conn = get_db()
    try:
        flags = recognition_flags(conn, 2026)
    finally:
        conn.close()
    amt = {}
    for k in ("stage_ratio_unset", "stage_ratio_not_100"):                  # case_incomplete 的金額是 stage_revenue 的「未認列」數字，改前 NULL 就是 0，不在這條
        for it in flags[k]["items"]:
            amt.setdefault(it["quoteNo"], set()).add(it["amount"])
    assert {"TXT-N", "TXT-B", "TXT-T", "TXT-OK"} <= set(amt), amt           # 正對照：四張都有進旗標清單
    assert amt["TXT-N"] == {None} and amt["TXT-B"] == {None}, amt
    assert amt["TXT-T"] == {11757} and amt["TXT-OK"] == {100000}, amt

@pytestmark_case
def test_clean_numeric_data_unchanged(client, world):
    h, i = world
    _case("TXT-OK", i, "txt_sa", pay=[{"type": "全額", "amount": 105000, "received": False}])
    r = client.get("/api/reports/customer-history", headers=h)
    txns = [t for c in r.json()["customers"] for t in c.get("transactions", []) if t["quoteNo"] == "TXT-OK"]
    assert txns and txns[0]["total"] == 105000


# ── ③ 原始碼守門 ───────────────────────────────────────────────────────────
_RAW = re.compile(r"""float\(\s*\w+\[["'](?:total|pretax)["']\]\s*or\s*0\s*\)""")


def _scan(src):
    return _RAW.findall(src)


def test_scanner_positive_control():
    assert _scan('x = float(row["total"] or 0)') and _scan("y = float( q['pretax']  or 0 )")
    assert not _scan('x = float(money_num(row["total"]))')


def test_no_raw_float_of_quotation_money_columns_left():
    hits = []
    for p in BACKEND.rglob("*.py"):
        rel = p.relative_to(BACKEND).as_posix()
        if rel.startswith(("tests/", "tools/", "migrations_frozen/")) or "/tests/" in rel or ".venv" in rel:
            continue
        for m in _scan(p.read_text(encoding="utf-8", errors="replace")):
            hits.append((rel, m))
    assert not hits, "金額欄不可直接 float(列[\"total\"/\"pretax\"] or 0)（文字金額會 500），改用模組內的 money_num／_money_num：%s" % hits
