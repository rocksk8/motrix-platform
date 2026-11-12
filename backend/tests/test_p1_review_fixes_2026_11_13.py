# -*- coding: utf-8 -*-
"""UX P1 審查（hichan-9，fbfabee5a）修正的契約題：M1～M6、L3。純靜態＋node，可用 --noconftest 單跑。"""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.abspath(os.path.join(HERE, ".."))
FRONT = os.path.abspath(os.path.join(BACKEND, "..", "frontend"))
sys.path.insert(0, BACKEND)
from helpers import status_display as S  # noqa: E402

NODE = shutil.which("node")


def read(rel):
    with open(os.path.join(FRONT, rel), encoding="utf-8") as f:
        return f.read()


def _node(code):
    r = subprocess.run([NODE, "-e", code], cwd=FRONT, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# ── M1：4 頁要啟用管理者自訂的狀態名稱 ───────────────────────────────────────────
@pytest.mark.parametrize("page", ["pages/quotation-form.html", "pages/bonus.html", "pages/bonus-corrections.html", "pages/payslips.html"])
def test_m1_page_loads_chip_script_flags_script_and_calls_init(page):
    s = read(page)
    js = read("js/bonus.js") if page.endswith("bonus.html") else ""
    assert "status-chip.js" in s and "public-flags.js" in s, "沒載入腳本，MotrixStatus.init 讀不到旗標"
    assert "MotrixStatus.init(" in s + js, "沒呼叫 MotrixStatus.init：管理者自訂的名稱不會生效"
    # 腳本順序：status-chip 與 public-flags 都在使用處之前（<head>）
    assert s.index("status-chip.js") < s.index("<body")


def test_m1_quotation_form_reuses_the_existing_flag_read_no_extra_request():
    s = read("pages/quotation-form.html")
    assert "'ui_format', 'builder_status_display'], { token: tk })" in s
    assert "MotrixStatus.init({ token: tk, flags: g })" in s


# ── M2：會計傳票維持「審核」，其餘簽核流程用「待簽核」 ───────────────────────────────
def test_m2_voucher_context_keeps_old_word_other_contexts_use_new():
    d = S.defaults()["待審核"]
    assert "voucher" in S.CONTEXTS and d["names"]["voucher"] == "待審核" and d["label"] == "待簽核"
    assert d["names"]["quote_list"] == "待簽核"
    for ctx in ("quote_form", "case", "cashier", "report", "settlement"):
        assert S._texts(S.defaults(), "待審核")[ctx] == "待簽核", ctx


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_m2_js_voucher_context_shows_old_word_and_payment_request_new_word():
    out = _node("global.window=undefined;const S=require('./static/status-chip.js');"
                "console.log(JSON.stringify([S.label('待審核','voucher'),S.label('待審核','cashier'),S.label('待審核','quote_list'),S.label('待審核'),S.label('差額待審核','cashier')]))")
    assert out == ["待審核", "待簽核", "待簽核", "待簽核", "差額待簽核"]


def test_m2_voucher_page_label_defaults_to_voucher_context_and_button_stays():
    js = read("js/voucher.js")
    assert "label(raw, ctx || 'voucher', fallback)" in js
    assert ">送出審核</button>" in read("pages/voucher.html")           # 按鈕在傳票頁維持不變


# ── M3：頁籤／下拉走 label ──────────────────────────────────────────────────────
def test_m3_bonus_tabs_and_corrections_dropdown_use_label():
    assert 'x-text="MotrixStatus.label(st)"' in read("pages/bonus.html")
    assert 'x-text="MotrixStatus.label(s)"' in read("pages/bonus-corrections.html")


# ── M4：結束狀態＝深灰藍，紫色不再用在已付款／已結算／已結案／已發放／已完成 ─────────────────
def test_m4_end_states_use_slate_not_purple():
    for rel in ("pages/bonus.html", "pages/bonus-corrections.html"):
        s = read(rel)
        assert ".st-slate{" in s and "st-purple" not in s, rel
    assert "'已發放': 'st-slate'" in read("js/bonus.js") and "st-purple" not in read("js/bonus.js")
    assert "'已完成': 'st-slate'" in read("pages/bonus-corrections.html")
    for rel in ("pages/reports.html", "pages/cashier.html"):
        m = re.search(r"\.rb-fin\{([^}]*)\}", read(rel))
        assert m and "tone-slate" in m.group(1) and "#EDE9FE" not in m.group(1) and "#7C3AED" not in m.group(1), rel


# ── M5：泳道「送審中」，摘要卡／分頁「待簽核」，三處對得上 ───────────────────────────
def test_m5_lane_is_in_review_summary_and_tab_are_pending_sign():
    s = read("pages/quotations.html")
    assert "{ key: 'review', label: '送審中'" in s
    assert "<div class=\"summary-item__label\">待簽核</div>" in s and "{ key: '待審核', label: '待簽核' }" in s
    # 摘要卡與分頁「都只算待審核這個狀態值」；泳道＝待審核＋簽核中（兩個名字不同、範圍也不同）
    assert "this.quotes.filter(q => q.status === '待審核').length" in s
    assert "if (s === '待審核' || s === '簽核中') return 'review'" in s


# ── M6：前端殘留的舊用語 ────────────────────────────────────────────────────────
@pytest.mark.parametrize("rel,gone", [
    ("pages/approval-queue.html", ["審核原因", "最高管理員", "單層審核"]),
    ("pages/quotation-form.html", ["送出審核失敗", "已送出審核申請"]),
    ("js/case-management-close.js", ["最高管理員", "簽核佇列", "既有待審核項目"]),
    ("pages/payment-request-form.html", [">送出審核<"]),
    ("static/notif.js", ["'quotation.submit':        '送出審核'"]),
    ("static/ux-help.js", ["送出審核"]),
    ("pages/settlement.html", ["待簽照計成本"]),
])
def test_m6_old_words_are_gone(rel, gone):
    s = read(rel)
    for g in gone:
        assert g not in s, "%s 還有舊用語：%s" % (rel, g)


def test_m6_audit_log_shows_new_word_but_keeps_action_values():
    s = read("pages/audit-log.html")
    for a in ("quotation.submit", "contractor_voucher.submit", "invoice_voucher.submit"):
        assert '<option value="%s">送出簽核</option>' % a in s, a            # value（稽核紀錄存的 action）不動，只改顯示字
        assert re.search(r"'%s':\s*'送出簽核'" % re.escape(a), s), a
    assert "送出審核" not in s


# ── L3：重複的顯示字要提出警告 ──────────────────────────────────────────────────
def test_l3_defaults_have_no_unexpected_duplicate_display_text():
    assert S.duplicate_warnings() == [], S.duplicate_warnings()


def test_l3_duplicate_is_reported_even_for_unchanged_default_fields():
    # 把「簽核中」改成「待簽核」：與（內建改名後的）『待審核』撞名
    tbl = S.effective_table({"statuses": {"簽核中": {"label": "待簽核"}}})
    w = S.duplicate_warnings(tbl)
    assert w and any("待簽核" in x["message"] and "待審核" in x["message"] and "簽核中" in x["message"] for x in w), w
    # 舊的、有意保留的『已退回』重複不算
    assert not any("已退回" in x["message"] for x in S.duplicate_warnings())


def test_l3_known_duplicate_is_only_the_quote_list_returned_pair():
    assert S._KNOWN_DUPLICATES == {("quote_list", "已退回")}


def test_l3_payload_carries_warnings_and_never_raises(monkeypatch):
    monkeypatch.setattr(S, "_texts", lambda *a, **k: 1 / 0)
    assert S.duplicate_warnings() == []
