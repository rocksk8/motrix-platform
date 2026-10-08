# -*- coding: utf-8 -*-
"""第 48 班：利潤名詞改名守門（淨利 → 營業利益；淨利率 → 營業利益率；未扣費用淨利 → 扣費用前（直接毛利））。

清單在 backend/data/profit_labels_t48.json。內部鍵不改（ASCII，不受影響）。
規則：畫面／PDF／Excel 的程式與頁面（frontend 的 html／js、backend 非測試的 py）不得再出現「淨利」，
但會計報表（accounting）與科目表排除，並有正對照證明掃描器真的抓得到；尚待別的切片（ab 的報價單／精算、S6 獎金）改的檔
列在 PENDING，該切片合併時要把檔名從 PENDING 拿掉（拿掉才算完成）。
"""
import json
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
ROOT = os.path.dirname(BACKEND)
TABLE = json.load(open(os.path.join(BACKEND, "data", "profit_labels_t48.json"), encoding="utf-8"))

#: 還沒改的檔（原因）——所屬切片合併後必須從這裡移除
PENDING = {
}
#: 只剩歷史說明性註解／DDL 註解，不是畫面字樣
HISTORICAL_COMMENTS = {
    "backend/helpers/profit_rules.py": "ab：docstring「營業利益（舊稱淨利）」",
    "backend/db.py": "bonus_case_awards DDL 註解（凍住的歷史）",
    "backend/routers/system.py": "舊設計說明註解",
    "backend/helpers/financial_mask.py": "修改紀錄欄位名稱：舊紀錄存「淨利率」，新舊並列（test_history_labels_keep_old_and_new）",
    "backend/modules/case/api/quotations.py": "改名註解（舊紀錄存「淨利率」）",
}


def _scan(extra_excluded=()):
    out = {}
    excl = [e for e in TABLE["excluded"]] if extra_excluded is not None else []
    for base, exts in (("frontend", (".html", ".js")), ("backend", (".py", ".json"))):
        for d, dirs, files in os.walk(os.path.join(ROOT, base)):
            dirs[:] = [x for x in dirs if x not in ("node_modules", "__pycache__", "tests", "migrations_frozen", ".git")]
            for fn in files:
                if not fn.endswith(exts) or fn.startswith("test_") or fn in ("version_manifest.json",):
                    continue
                p = os.path.join(d, fn)
                rel = os.path.relpath(p, ROOT).replace(os.sep, "/")
                if any(rel.startswith(e) for e in excl):
                    continue
                try:
                    s = open(p, encoding="utf-8").read()
                except (UnicodeDecodeError, OSError):
                    continue
                if "淨利" in s:
                    out[rel] = s.count("淨利")
    return out


def test_no_old_profit_label_left_outside_the_allowlist():
    found = _scan()
    allowed = set(PENDING) | set(HISTORICAL_COMMENTS)
    stray = {k: v for k, v in found.items() if k not in allowed}
    assert not stray, "這些檔還有舊字樣「淨利」（請改成表內新字樣；表：backend/data/profit_labels_t48.json）：%s" % stray


def test_allowlist_has_no_stale_entries():
    found = _scan()
    stale = [k for k in list(PENDING) + list(HISTORICAL_COMMENTS) if k not in found]
    assert not stale, "這些檔已經沒有「淨利」了，請從 PENDING／HISTORICAL_COMMENTS 移除：%s" % stale


def test_scanner_positive_control_sees_the_excluded_accounting_files():
    """排除會計報表是刻意的；但要證明掃描器本身抓得到（否則「全空」可能只是掃不到）。"""
    everything = _scan(extra_excluded=None)
    hits = [k for k in everything if k.startswith("backend/modules/accounting/") or k == "backend/data/account_items_112.json"]
    assert hits, "掃描器沒有在會計報表／科目表找到「淨利」——掃描壞了"
    s = open(os.path.join(BACKEND, "data", "account_items_112.json"), encoding="utf-8").read()
    assert "稅後淨利" in s, "會計科目表的「稅後淨利」不可被改名"


def test_history_labels_keep_old_and_new():
    from helpers.financial_mask import HISTORY_MONEY_FIELDS
    for old, new in TABLE["history_labels_old_and_new"]:
        assert old in HISTORY_MONEY_FIELDS and new in HISTORY_MONEY_FIELDS, (old, new)
    from modules.case.api import quotations as q
    labels = [lbl for _p, lbl in q._TRACKED_QUOTE_FIELDS]
    assert "營業利益率" in labels and "淨利率" not in labels


def test_threshold_stays_12_in_quotation_form():
    s = open(os.path.join(ROOT, "frontend", "pages", "quotation-form.html"), encoding="utf-8").read()
    assert "netMarginPct < 12" in s and "12%" in s
    assert TABLE["threshold_pct"] == 12


#: 「管銷分攤（10%」寫死的字面只能出現在還沒改的檔（S3：報價單／精算頁）；其餘一律走口徑感知的標籤函式（admin_cost_label／*AdminLabel）
LITERAL = "管銷分攤（10%"
PENDING_LITERAL = {
    "frontend/pages/quotation-form.html": "S3（報價單）",
}


def _literal_hits(extra_excluded=()):
    out = {}
    for base, exts in (("frontend", (".html", ".js")), ("backend", (".py",))):
        for d, dirs, files in os.walk(os.path.join(ROOT, base)):
            dirs[:] = [x for x in dirs if x not in ("node_modules", "__pycache__", "tests", "migrations_frozen", ".git")]
            for fn in files:
                if not fn.endswith(exts) or fn.startswith("test_"):
                    continue
                p = os.path.join(d, fn)
                try:
                    n = open(p, encoding="utf-8").read().count(LITERAL)
                except (UnicodeDecodeError, OSError):
                    continue
                if n:
                    out[os.path.relpath(p, ROOT).replace(os.sep, "/")] = n
    return out


def test_no_hardcoded_10pct_admin_label_outside_pending():
    stray = {k: v for k, v in _literal_hits().items() if k not in PENDING_LITERAL}
    assert not stray, "寫死的「管銷分攤（10%%…」會在新口徑案件上說錯話，請改用 admin_cost_label／*AdminLabel：%s" % stray


def test_literal_pending_entries_are_not_stale():
    hits = _literal_hits()
    assert [k for k in PENDING_LITERAL if k not in hits] == [], "已改掉的檔請從 PENDING_LITERAL 移除"


def test_literal_scanner_positive_control(tmp_path):
    """掃描器真的抓得到：對一個含字面的樣本檔計數（含 pdf_gen 新標籤函式的兩種輸出不含該字面）。"""
    sample = tmp_path / "x.py"
    sample.write_text("<td>管銷分攤（10%）</td>", encoding="utf-8")
    assert sample.read_text(encoding="utf-8").count(LITERAL) == 1
    import pdf_gen
    assert LITERAL not in pdf_gen.admin_cost_label({}) and LITERAL not in pdf_gen.admin_cost_label({"formulaVer": 2, "overheadPct": 25})
    assert pdf_gen.admin_cost_label({}) == "管銷分攤（報價稅前 10%）"
    assert pdf_gen.admin_cost_label({"formulaVer": 2, "overheadPct": 25}) == "管銷分攤（直接毛利 25%）"
    assert pdf_gen.admin_cost_label({"formulaVer": 2, "overheadPct": 7.5}) == "管銷分攤（直接毛利 7.5%）"
    assert pdf_gen.admin_cost_label({"formulaVer": 2, "origFormulaVer": 1}, True) == "管銷分攤（報價稅前 10%）"
