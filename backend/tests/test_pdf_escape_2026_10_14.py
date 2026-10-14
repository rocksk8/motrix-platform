# -*- coding: utf-8 -*-
"""PDF／HTML 輸出的逸出稽核（04 資安線，b4 指派 G-C；與通知信那刀同一類問題）。

盤點結論（b77485f41）：pdf_gen／completion_pdf 有 11 份各自複製貼上的 `esc()`——三種寫法（`(s or '')`＋換行轉 `<br>`／`str(s) if s is not None else ''`＋換行轉 `<br>`／
`(s or '')` 不轉換行，唯一用在 `_voucher_sign_html`），全部引號都由 `esc_quotes` 統一處理；另有 `html.escape`（bonus_pdf、voucher_pdf、reports、netplan 的小型 `_esc`）。
差異不在跳脫規則，而在『有些輸出點根本沒呼叫 esc』：使用者可寫入的欄位直接 f-string 內插（報價品項數量、報價有效日數、款項百分比、階段起訖日…），
儲存型 XSS（PDF 由無頭瀏覽器轉出，腳本會在伺服器端執行）。

本檔：
①共用 `helpers.doc_template.html_text`（兩個旗標）逐案例重現三種舊寫法——純文字資料輸出逐位元相同
②五個確認的輸出點已加 esc，純文字／數字資料輸出不變；邪惡字元 `<b>name&'"</b>` 進去 ⇒ 沒有原字串、逸出後的字串出現
③AST 棘輪：builder 檔案裡『直接內插字典取值、又沒經過 esc／格式化』的位置只能是已審過的清單（tests/pdf_raw_sinks_baseline.json；新增＝紅燈）
"""
import ast
import collections
import json
import re
from pathlib import Path

import pytest

from helpers import doc_template as DT

ROOT = Path(__file__).resolve().parents[1]
BASELINE = Path(__file__).with_name("pdf_raw_sinks_baseline.json")
FILES = ["pdf_gen.py", "modules/case/completion_pdf.py", "modules/accounting/voucher_pdf.py", "modules/payroll/bonus_pdf.py",
         "modules/netplan/export.py", "modules/netplan/topology.py", "modules/case/api/expense_form_pdf.py",
         "modules/analytics/api/reports.py", "helpers/doc_template.py", "helpers/doc_render.py"]
_SAFE = re.compile(r"esc\(|_esc\(|attr\(|_attr\(|_esc_q\(|html\.escape|\be\(|fmt\(|money\(|_fn\(|len\(|int\(|round\(|attr_esc|escape\(|_h\.|html_text\(")


def _esc_q(t):
    return t.replace('"', '&quot;').replace("'", '&#x27;')


# 舊寫法（凍結副本）
def old_v1(s):
    return _esc_q((s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>'))


def old_v2(s):
    return _esc_q((str(s) if s is not None else '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>'))


def old_v3(s):
    return _esc_q((s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


PLAIN = ["", None, "abc", "客戶 甲乙", "A&B", "<b>x</b>", '"q" \'s\'', "第一行\n第二行", "\n", " ", "０１２ 全形", "a" * 300]


@pytest.mark.parametrize("s", PLAIN)
def test_html_text_reproduces_the_three_old_variants(s):
    assert DT.html_text(s, falsy_empty=True) == old_v1(s)
    assert DT.html_text(s) == old_v2(s)
    assert DT.html_text(s, br=False, falsy_empty=True) == old_v3(s)
    assert DT._esc(s) == old_v2(s) and DT.attr_esc(s) == old_v2(s).replace("<br>", "\n")


def test_html_text_falsy_and_non_string_semantics():
    assert DT.html_text(0) == "0" and DT.html_text(0, falsy_empty=True) == "", "0：舊的 `(s or '')` 寫法印成空字串，`str(s)` 寫法印成 0"
    assert DT.html_text(12.5) == "12.5" and DT.html_text(7, falsy_empty=True) == "7", "非字串先轉字串（舊 `(s or '')` 對數字會丟例外）"
    assert DT.html_text(None) == "" and DT.html_text(False, falsy_empty=True) == ""


def test_local_esc_copies_are_gone_from_the_builders():
    for rel in ("pdf_gen.py", "modules/case/completion_pdf.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert not re.search(r"return _esc_q\(\(", src), "%s 還有複製貼上的跳脫實作（改用 helpers.doc_template.html_text）" % rel


# ── ② 五個確認的輸出點 ──────────────────────────────────────────────────────
EVIL = "<b>%s&'\"</b>"
ESC = "&lt;b&gt;%s&amp;&#x27;&quot;&lt;/b&gt;"


@pytest.mark.parametrize("x", [5, 2.5, "3", "", None, 0, "10"])
def test_wrapping_numbers_and_plain_text_does_not_change_the_output(x):
    esc = lambda s: DT.html_text(s, falsy_empty=True)           # noqa: E731  pdf_gen 的區域 esc
    assert esc(str(x)) == "%s" % (x,), "esc(str(x)) 必須與 f-string 直接內插相同（None 仍印 'None'，與舊行為一致）"


def _quote(**over):
    q = {"quoteNo": "MQ-202610-001", "customerName": "甲公司", "projectName": "專案", "status": "草稿", "validDays": 30,
         "items": [{"description": "品項", "brand": "", "unit": "式", "qty": 2, "unitPrice": 100, "amount": 200, "type": "item"}]}
    q.update(over)
    return q


def test_quote_pdf_escapes_qty_and_valid_days():
    import pdf_gen
    tot = {"subtotal": 200, "pretax": 200, "tax": 10, "total": 210}
    for internal in (False, True):
        q = _quote(validDays=EVIL % "validDays", items=[{"description": "品項", "brand": "", "unit": "式", "qty": EVIL % "qty", "unitPrice": 100, "amount": 200, "type": "item", "cost": 50, "margin": 10}])
        html = pdf_gen._build_quote_html(q, tot, internal=internal)
        assert EVIL % "qty" not in html and EVIL % "validDays" not in html, internal
        assert ESC % "qty" in html and ESC % "validDays" in html, internal
    base = pdf_gen._build_quote_html(_quote(), tot)
    assert "2</td>" in base and "30 日內" in base, "數字資料輸出不變"


def test_shipping_pdf_escapes_qty():
    import pdf_gen
    n = {"noteNo": "DN-202610-001", "status": "草稿", "customerName": "甲", "items": [{"description": "品", "qty": EVIL % "qty", "unit": "台"}]}
    html = pdf_gen._build_shipping_html(n)
    assert EVIL % "qty" not in html and ESC % "qty" in html


# ── ③ 棘輪：直接內插字典取值、又沒經過逸出／格式化的位置 ───────────────────────
def scan(rel):
    src = (ROOT / rel).read_text(encoding="utf-8")
    out = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.JoinedStr):
            for v in node.values:
                if isinstance(v, ast.FormattedValue):
                    seg = ast.get_source_segment(src, v.value) or ""
                    if _SAFE.search(seg) or v.format_spec is not None:
                        continue
                    if re.search(r"\[|\.get\(", seg):
                        out.append(seg.strip())
    return out


def _current():
    c = collections.Counter()
    for rel in FILES:
        for seg in scan(rel):
            c["%s::%s" % (rel, seg)] += 1
    return c


def test_no_new_unescaped_interpolations_in_the_html_builders():
    """新增的『f-string 直接內插字典取值』必須先審過（確定是數字／常數／系統產生）再加進基線；使用者可寫入的欄位一律要經 esc()。"""
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    cur = _current()
    new = {k: v for k, v in cur.items() if v > base.get(k, 0)}
    assert not new, "新的未逸出內插（確認不是使用者輸入後才能加進基線）：\n" + "\n".join("%dx %s" % (v, k[:150]) for k, v in sorted(new.items()))


def test_baseline_has_no_stale_entries():
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    cur = _current()
    stale = [k for k in base if k not in cur]
    assert not stale, "基線有已經不存在的項目（請刪掉，棘輪只能往下）：\n" + "\n".join(k[:150] for k in stale)


def test_the_five_fixed_sinks_are_no_longer_in_the_baseline():
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    joined = "\n".join(base)
    for dead in ('item.get("qty","")', 'q.get("validDays",30)', 'pr["pct"]', "_stage_period(st)"):
        assert dead not in joined, dead
