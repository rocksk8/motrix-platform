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
