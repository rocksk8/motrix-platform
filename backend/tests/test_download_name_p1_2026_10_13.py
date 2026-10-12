# -*- coding: utf-8 -*-
"""A7 下載檔名第一期：helper 純函式、範本、權限降級、標頭、設定缺席（設計 DOWNLOAD-FILENAME-CASE-T56.md r6 §6）。

[單位] helper:download_name 的契約題。純函式題不碰資料庫；權限題以 monkeypatch 的案件標籤替身驗證三種情境。
"""
import unicodedata
from urllib.parse import unquote

import pytest

from helpers import download_name as D
from helpers import financial_mask as FM


def _build(doc_type="completion", quote_no="Q2026-0001", doc_no="CN0007", ext="pdf", user=None, extra=None, label=(True, "新竹廠區網路建置", "某某科技"), cfg=None, monkeypatch=None):
    monkeypatch.setattr(D, "_case_label", lambda conn, qn, u: label if qn else (False, "", ""))
    monkeypatch.setattr(D, "_settings", lambda: {**D.DEFAULTS, **(cfg or {})})
    return D.build(doc_type, quote_no=quote_no, doc_no=doc_no, ext=ext, user=user, conn=object(), extra=extra)


USER = {"id": 1, "role": "admin", "username": "a"}


# ── 淨化（純函式）─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ('a\\b/c:d*e?f"g<h>i|j', "a＼b／c：d＊e？f＂g＜h＞i｜j"),
    ("  前後空白  ", "前後空白"),
    ("結尾的點...", "結尾的點"),
    (".開頭的點", "開頭的點"),
    ("換行\r\n注入", "換行 注入"),
    ("零寬​字‏元﻿", "零寬字元"),
    ("覆寫‮fdp.exe", "覆寫fdp.exe"),
    ("全形　空白", "全形 空白"),
    ("", ""),
    ("   ", ""),
    ('\\/:*?"<>|', "＼／：＊？＂＜＞｜"),
])
def test_clean_table(raw, expected):
    assert D._clean(raw) == expected


def test_clean_nfc_and_cf_removed():
    nfd = unicodedata.normalize("NFD", "é")
    assert D._clean(nfd) == "é" and len(D._clean(nfd)) == 1
    for cp in ("‮", "​", "‏", "⁠", "﻿"):
        assert D._clean("a" + cp + "b") == "ab"


@pytest.mark.parametrize("stem", ["con", "CON", "Con.txt", " Con. ", "nul", "COM1", "lpt9", "AUX"])
def test_reserved_names_prefixed(stem):
    out = D._protect_reserved(D._clean(stem))
    assert out.startswith("_")


@pytest.mark.parametrize("stem", ["console", "CN0007", "com10", "報價單"])
def test_non_reserved_untouched(stem):
    assert D._protect_reserved(stem) == stem


def test_fit_bytes_and_chars_cjk():
    stem = D._fit([{"k": "n", "t": "字" * 100}], "_", 100, 250)
    assert len(stem) <= 83 and len(stem.encode("utf-8")) <= 250
    assert all(ord(c) > 0x4E00 for c in stem)            # 不切壞多位元組字元


def test_fit_truncation_order_keeps_doc_no():
    parts = [{"k": "case_no", "t": "Q2026-0001"}, {"k": "case_name", "t": "長" * 80, "shrink": True},
             {"k": "doc_type", "t": "完工單"}, {"k": "doc_no", "t": "CN0007"}]
    s = D._fit(parts, "_", 100, 255 - 4)
    assert s.endswith("_完工單_CN0007") and s.startswith("Q2026-0001_")
    assert len(s.encode("utf-8")) <= 251


def test_fit_hard_truncate_when_type_and_no_too_long():
    parts = [{"k": "doc_type", "t": "類" * 60}, {"k": "doc_no", "t": "N" * 300}]
    s = D._fit(parts, "_", 100, 251)
    assert len(s) <= 100 and len(s.encode("utf-8")) <= 251


def test_ascii_fallback_latin1_safe_for_any_input():
    for raw in ('報價單"\\%.pdf', "‮\u0000\r\n.pdf", "😀.pdf", "a" * 20, "測試", ""):
        h = D.content_disposition(raw or "x")
        h.encode("latin-1")                              # 不丟例外
        assert "\r" not in h and "\n" not in h
    assert D._ascii_fallback('測"\\%試.pdf').endswith(".pdf")
    assert '"' not in D._ascii_fallback('a"b')[0:1]


def test_filename_star_attr_chars_and_roundtrip():
    name = "Q-1 完工單(A,B);'x'=1.pdf"
    h = D.content_disposition(name)
    star = h.split("filename*=UTF-8''", 1)[1]
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!#$&+-.^_`|~%")
    assert set(star) <= allowed
    assert unquote(star) == D._clean(name)
    assert h.startswith('attachment; filename="')
    assert D.content_disposition(name, inline=True).startswith("inline;")


# ── 範本與權限降級 ────────────────────────────────────────────────────────────

def test_default_layout_with_access(monkeypatch):
    r = _build(user=USER, monkeypatch=monkeypatch)
    assert r.name == "Q2026-0001_新竹廠區網路建置_完工單_CN0007.pdf"
    assert r.header.encode("latin-1")


def test_no_access_keeps_case_no_omits_name(monkeypatch):
    r = _build(user=USER, label=(False, "新竹廠區網路建置", "某某科技"), monkeypatch=monkeypatch)
    assert r.name == "Q2026-0001_完工單_CN0007.pdf"
    assert "新竹" not in r.name and "新竹" not in unquote(r.header)


def test_no_access_omit_both_option(monkeypatch):
    r = _build(user=USER, label=(False, "新竹廠區網路建置", ""), cfg={"no_access": 0}, monkeypatch=monkeypatch)
    assert r.name == "完工單_CN0007.pdf"


def test_no_access_show_name_option_loosens(monkeypatch):
    r = _build(user=USER, label=(False, "新竹廠區網路建置", ""), cfg={"no_access": 2}, monkeypatch=monkeypatch)
    assert "新竹廠區網路建置" in r.name


def test_user_none_never_names_even_if_setting_loosest(monkeypatch):
    for mode in (0, 1, 2):
        r = _build(user=None, cfg={"no_access": mode}, monkeypatch=monkeypatch)
        assert "新竹" not in r.name and "某某" not in r.name


def test_customer_name_only_when_chosen_and_readable(monkeypatch):
    r = _build(user=USER, cfg={"case_name_source": 2}, monkeypatch=monkeypatch)
    assert "某某科技" in r.name and "新竹" not in r.name
    r2 = _build(user=USER, label=(False, "新竹", "某某科技"), cfg={"case_name_source": 2}, monkeypatch=monkeypatch)
    assert "某某科技" not in r2.name
    r3 = _build(user=USER, cfg={"case_name_source": 1}, monkeypatch=monkeypatch)
    assert "新竹廠區網路建置（某某科技）" in r3.name


def test_separator_and_layout_options(monkeypatch):
    assert _build(user=USER, cfg={"separator": 1}, monkeypatch=monkeypatch).name == "Q2026-0001-新竹廠區網路建置-完工單-CN0007.pdf"
    assert _build(user=USER, cfg={"name_layout": 3}, monkeypatch=monkeypatch).name == "CN0007.pdf"
    assert _build(user=USER, cfg={"name_layout": 2}, monkeypatch=monkeypatch).name == "完工單_CN0007.pdf"


def test_no_case_degrades_to_type_and_no(monkeypatch):
    assert _build(user=USER, quote_no=None, monkeypatch=monkeypatch).name == "完工單_CN0007.pdf"


def test_internal_variant_and_suffix(monkeypatch):
    r = _build("quotation", user=USER, doc_no="Q2026-0001", extra={"variant": "internal"}, monkeypatch=monkeypatch)
    assert r.name.endswith("_報價單（內部）_Q2026-0001.pdf")
    r2 = _build("quotation_version", user=USER, extra={"suffix": "送審_20261013"}, monkeypatch=monkeypatch)
    assert r2.name.endswith("_報價單存檔版本_CN0007_送審_20261013.pdf")


def test_case_name_max_chars_and_total_cap(monkeypatch):
    r = _build(user=USER, label=(True, "名" * 60, ""), monkeypatch=monkeypatch)
    stem = r.name[:-4]
    assert len(stem) <= 100 and len(stem.encode("utf-8")) <= 251
    assert stem.endswith("_完工單_CN0007") and stem.count("名") <= 20


def test_ext_sanitized_and_kept(monkeypatch):
    r = _build(user=USER, ext=".xlsx", monkeypatch=monkeypatch)
    assert r.name.endswith(".xlsx")
    r2 = _build(user=USER, ext="p/d f", monkeypatch=monkeypatch)
    assert "." not in r2.name.rsplit("_", 1)[-1]          # 不合法副檔名被丟棄，不夾帶


def test_payslip_keeps_contractor_date_and_nth(monkeypatch):
    extra = {"contractor": "王小明", "contractor_allowed": True, "date": "2026-10-13", "nth": 2}
    r = _build("payslip", doc_no="PS001", user=USER, extra=extra, monkeypatch=monkeypatch)
    assert r.name == "Q2026-0001_新竹廠區網路建置_勞報單_王小明_20261013_第2次.pdf"
    r2 = _build("payslip", doc_no="PS001", user=USER, extra={**extra, "date": ""}, monkeypatch=monkeypatch)
    assert r2.name == "Q2026-0001_新竹廠區網路建置_勞報單_王小明_PS001_第2次.pdf"


def test_payslip_name_requires_setting_and_endpoint_permission(monkeypatch):
    base = {"contractor": "王小明", "date": "2026-10-13"}
    off = _build("payslip", doc_no="PS001", user=USER, extra={**base, "contractor_allowed": True}, cfg={"payslip_show_name": 0}, monkeypatch=monkeypatch)
    assert "王小明" not in off.name
    no_perm = _build("payslip", doc_no="PS001", user=USER, extra=base, monkeypatch=monkeypatch)
    assert "王小明" not in no_perm.name


def test_exception_falls_back_to_today_name(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(D, "_case_label", boom)
    r = D.build("completion", quote_no="Q1", doc_no="CN0007", ext="pdf", user=USER, conn=object())
    assert r.name == "CN0007.pdf" and r.header.encode("latin-1")


def test_settings_absent_uses_constant_defaults(monkeypatch):
    import helpers.settings_registry as R
    monkeypatch.setattr(R, "get_group", lambda *a, **k: (_ for _ in ()).throw(KeyError("download_name")))
    assert D._settings() == D.DEFAULTS


def test_settings_wrong_types_fall_back(monkeypatch):
    import helpers.settings_registry as R
    monkeypatch.setattr(R, "get_group", lambda *a, **k: {"name_layout": "x", "label_completion": "", "separator": 1, "total_max_chars": True})
    s = D._settings()
    assert s["name_layout"] == D.DEFAULTS["name_layout"] and s["label_completion"] == "完工單"
    assert s["separator"] == 1 and s["total_max_chars"] == D.DEFAULTS["total_max_chars"]


# ── 守門 ──────────────────────────────────────────────────────────────────────

def test_tokens_exclude_every_money_key():
    money = set(FM.ITEM_MONEY_KEYS) | set(FM.QUOTE_MONEY_KEYS) | set(FM.QUOTATION_MONEY_COLS) | set(FM.PAYMENT_MONEY_KEYS)
    assert not (set(D.TOKENS) & money)
    for layout in D._LAYOUTS.values():
        assert set(layout) <= set(D.TOKENS)


def test_defaults_match_registered_group():
    from helpers import settings_registry as R
    import helpers.settings_groups  # noqa: F401  確保登錄
    fields = {f["key"]: f for f in R.groups()["download_name"]["fields"]}
    assert set(fields) == set(D.DEFAULTS)
    for k, v in D.DEFAULTS.items():
        assert fields[k]["default"] == v, k


@pytest.mark.parametrize("mode", [0, 1])
@pytest.mark.parametrize("who", ["admin", "none"])
def test_modes_0_and_1_never_put_case_or_customer_name_in_any_header(monkeypatch, mode, who):
    """設定 0（兩者都省略）與 1（保留編號省略名稱）：沒有案件可見度的呼叫者，名稱絕不出現在檔名、ASCII 退路或 filename*。"""
    user = USER if who == "admin" else None
    r = _build(user=user, label=(False, "新竹廠區網路建置", "某某科技"), cfg={"no_access": mode, "case_name_source": 1}, monkeypatch=monkeypatch)
    blob = r.name + r.header + unquote(r.header)
    assert "新竹" not in blob and "某某" not in blob


def test_label_cross_check_rejects_bad_labels_with_plain_message():
    from helpers import settings_groups as G
    assert G._download_name_check({"label_completion": "完工單"}) == []
    assert G._download_name_check({"label_completion": ""}) == ["文件類型用語要 1～10 個字"]
    assert G._download_name_check({"label_completion": "一二三四五六七八九十甲"}) == ["文件類型用語要 1～10 個字"]
    assert G._download_name_check({"label_completion": "完工\n單"}) == ["文件類型用語不可含換行或控制字元"]
    for msg in G._download_name_check({"label_completion": ""}):
        assert "label_" not in msg and "download_name" not in msg
