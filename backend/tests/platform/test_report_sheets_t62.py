# -*- coding: utf-8 -*-
"""S-F2 B：營運報表的工作表選擇（BP-3 匯出範本『工作表型』；匯出代號 reports:financial）。

①目錄與報表原始碼同步（每張工作表名稱都真的在 `_build_excel` 建立、PDF 段落註解標記都真的在 HTML 裡、順序一致）
②驗證：只能選目錄子集、順序固定、必選不能拿掉、不收欄位／頁首頁尾浮水印
③治理：關掉工作表＝收緊；加回含金額的＝放寬（需第二位核准）；加回不含金額的＝中性；第一次發布以全部工作表為基準
④執行期：旗標關／沒有範本 ⇒ 什麼都不動（逐位元相同）；有範本 ⇒ Excel 拿掉整張表、PDF 拿掉段落（含目標達成率、本季收支兩個以變數插入的段落）
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from helpers import export_templates as ET
import modules.analytics.api.reports as R

ROOT = Path(__file__).resolve().parents[3]
SRC = (ROOT / "backend" / "modules" / "analytics" / "api" / "reports.py").read_text(encoding="utf-8")
EID = R.REPORT_EXPORT_ID


def _bad(body):
    return {p["path"] for p in ET.definition_problems(EID, body)}


def _body(*ids):
    return {"version": 1, "format": "xlsx", "sheets": list(ids)}


ALL = [sid for sid, _t, _m in R.REPORT_SHEETS]


# ── ① 目錄與原始碼同步 ──────────────────────────────────────────────────────
def test_catalog_matches_the_report_sources():
    titles = re.findall(r'create_sheet\("([^"]+)"\)', SRC)
    assert titles == [t for _s, t, _m in R.REPORT_SHEETS], "Excel 工作表建立順序必須等於目錄順序"
    for sid, _t, marker in R.REPORT_SHEETS:
        if marker:
            assert re.search(r"<!-- %s" % re.escape(marker), SRC), "PDF 段落註解標記不存在：%s" % marker
    reg = ET.registered()[EID]
    assert [x["id"] for x in reg["sheets"]] == ALL and reg["decorOnly"] is False and reg["columns"] == []
    assert [x["id"] for x in reg["sheets"] if x["required"]] == ["summary"]
    assert {x["id"] for x in reg["sheets"] if not x["money"]} == {"warranty"}, "執行摘要含公司層級金額合計 ⇒ 標 money；只有保固預警不含金額"
    assert "摘要永遠包含公司層級金額合計" in reg["label"]


def test_pdf_template_contains_every_marker_exactly_once_inside_the_html():
    """產出的 HTML 範本（_build_report_html 的 f-string）必須含全部 11 個段落標記，各一次（缺了就拿不掉；多了會拿錯）。"""
    start = SRC.index('html = f"""<!DOCTYPE html>')
    end = SRC.index("return _drop_pdf_sections(html, _off) if _off else html")
    body = SRC[start:end]
    for sid, _t, marker in R.REPORT_SHEETS:
        if marker:
            assert len(re.findall(r"<!-- %s" % re.escape(marker), body)) == 1, (sid, marker)


def test_dropping_a_section_whose_marker_is_missing_raises_instead_of_leaking():
    with pytest.raises(R.ReportSectionError):
        R._drop_pdf_sections('<body><!-- 摘要 -->S<div class="footer">F</div></body>', ["aging"])


def test_drop_stops_only_at_known_markers_not_at_any_comment():
    html = '<body><!-- 摘要 -->S<!-- 帳齡分析 -->A<!-- 其他註解 -->B<!-- 案件清單 -->C<div class="footer">F</div></body>'
    assert R._drop_pdf_sections(html, ["aging"]) == '<body><!-- 摘要 -->S<!-- 案件清單 -->C<div class="footer">F</div></body>'


def test_every_pdf_marker_is_unique_and_sections_are_dropped_cleanly():
    html = '<body><!-- 摘要 -->S<!-- 本期收款 -->P<!-- 當月收支（2026-08-30） -->M<!-- 帳齡分析 -->A<div class="footer">F</div></body>'
    assert R._drop_pdf_sections(html, ["payments", "month"]) == '<body><!-- 摘要 -->S<!-- 帳齡分析 -->A<div class="footer">F</div></body>'
    assert R._drop_pdf_sections(html, ["aging"]) == '<body><!-- 摘要 -->S<!-- 本期收款 -->P<!-- 當月收支（2026-08-30） -->M<div class="footer">F</div></body>'
    assert R._drop_pdf_sections(html, []) == html and R._drop_pdf_sections(html, ["targets", "quarter"]) == html, "以變數插入的兩段不靠註解標記"
    for _sid, _t, marker in R.REPORT_SHEETS:
        if marker:
            assert len(re.findall(r"<!-- %s" % re.escape(marker), SRC)) >= 1


def test_excel_sheets_are_removed_whole_and_the_rest_keep_their_order():
    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for t in ("執行摘要", "目標達成率", "帳齡分析", "保固到期預警"):
        wb.create_sheet(t)
    R._drop_excel_sheets(wb, ["targets", "aging"])
    assert wb.sheetnames == ["執行摘要", "保固到期預警"] and wb.active.title == "執行摘要"


# ── ② 驗證 ─────────────────────────────────────────────────────────────────
def test_default_template_is_all_sheets_and_valid():
    d = ET.default_template(EID)
    assert d == {"version": 1, "format": "xlsx", "sheets": ALL} and ET.definition_problems(EID, d) == []


def test_validator_rules():
    assert _bad(_body("summary")) == set() and _bad(_body("summary", "aging")) == set()
    assert "sheets" in _bad(_body("aging")), "必選的執行摘要不能拿掉"
    assert "sheets" in _bad(_body("aging", "summary")), "順序固定"
    assert "sheets" in _bad(_body("summary", "nope"))
    assert "sheets" in _bad(_body("summary", "summary"))
    assert "sheets" in _bad({"version": 1, "format": "xlsx", "sheets": []})
    assert "sheets" in _bad({"version": 1, "format": "xlsx", "sheets": "summary"})
    assert "sheets" in _bad({"version": 1, "format": "xlsx"}), "工作表型必須有 sheets"
    assert "columns" in _bad({"version": 1, "format": "xlsx", "sheets": ["summary"], "columns": [{"id": "a", "label": "b"}]})
    assert "footer" in _bad({"version": 1, "format": "xlsx", "sheets": ["summary"], "footer": {"text": "機密"}}), "沒有頁首頁尾浮水印"
    assert "format" in _bad({"version": 1, "format": "csv", "sheets": ["summary"]})


def test_other_exports_do_not_accept_sheets_and_sheet_exports_reject_bad_catalogs():
    ET.register_export("t:plain", label="x", formats=("csv",), columns=[{"id": "a", "label": "A"}], sample_rows=[])
    other = "t:plain"
    assert "sheets" in {p["path"] for p in ET.definition_problems(other, {**ET.default_template(other), "sheets": ["x"]})}
    with pytest.raises(ValueError):
        ET.register_export("t:dup", label="x", formats=("xlsx",), columns=[], sample_rows=[], sheets=[{"id": "a", "label": "A", "required": True}, {"id": "a", "label": "B"}])
    with pytest.raises(ValueError):
        ET.register_export("t:noreq", label="x", formats=("xlsx",), columns=[], sample_rows=[], sheets=[{"id": "a", "label": "A"}])


# ── ③ 治理 ─────────────────────────────────────────────────────────────────
def test_comparator_tighten_loosen_neutral():
    from routers.def_pipeline import classify
    full = _body(*ALL)
    assert classify("export_template", {}, _body("summary", "warranty"))[0] == "tighten", "第一次發布：基準＝全部工作表，拿掉就是收緊"
    assert classify("export_template", full, _body("summary", "warranty"))[0] == "tighten"
    assert classify("export_template", _body("summary"), _body("summary", "warranty"))[0] == "neutral", "加回不含金額的＝中性"
    assert classify("export_template", _body("summary", "warranty"), _body("summary", "warranty", "aging"))[0] == "loosen", "加回含金額的＝放寬"
    assert classify("export_template", _body("summary", "aging"), _body("summary", "aging"))[0] == "neutral"
    assert classify("export_template", _body("summary"), full)[0] == "loosen"
    assert classify("export_template", {}, {"version": 1, "format": "xlsx", "sheets": ["x"]})[0] == "loosen", "看不懂的目錄＝放寬"


# ── ④ 執行期 ───────────────────────────────────────────────────────────────
def test_runtime_hooks_do_nothing_when_off_or_unpublished(monkeypatch):
    monkeypatch.setattr(ET, "resolve", lambda eid, conn=None: None)
    assert ET.enabled_sheets(EID) is None and ET.disabled_sheets(EID) == [] and R._off_sheets() == []
    assert ET.enabled_sheets("no:such") is None


def test_runtime_selection_includes_required_and_reports_the_rest(monkeypatch):
    monkeypatch.setattr(ET, "resolve", lambda eid, conn=None: _body("warranty", "aging") if eid == EID else None)
    assert ET.enabled_sheets(EID) == frozenset({"summary", "warranty", "aging"})
    off = ET.disabled_sheets(EID)
    assert "summary" not in off and "warranty" not in off and "aging" not in off and "targets" in off and len(off) == len(ALL) - 3
    assert R._off_sheets() == off


def test_unreadable_template_with_flag_on_fails_closed(monkeypatch):
    """旗標開著、已發布的範本讀不到 ⇒ 只輸出必選工作表（不整份外送）；旗標關 ⇒ 全部（今天）。"""
    monkeypatch.setattr(ET, "enabled", lambda conn=None: True)
    monkeypatch.setattr(ET, "ensure_kind", lambda: True)

    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(ET.D, "get", boom)
    assert ET.enabled_sheets(EID) == frozenset({"summary"})
    assert R._off_sheets() == [x for x in ALL if x != "summary"]
    monkeypatch.setattr(ET, "enabled", lambda conn=None: False)
    assert ET.enabled_sheets(EID) is None and R._off_sheets() == []


def test_unpublished_with_flag_on_is_everything(monkeypatch):
    monkeypatch.setattr(ET, "enabled", lambda conn=None: True)
    monkeypatch.setattr(ET, "ensure_kind", lambda: True)
    monkeypatch.setattr(ET.D, "get", lambda *a, **k: None)
    assert ET.enabled_sheets(EID) is None and R._off_sheets() == []


def test_audit_and_monthly_log_record_the_omitted_sheets():
    assert SRC.count('"omittedSheets": _off_sheets()') == 2, "Excel 與 PDF 匯出稽核都要記略過的工作表"
    assert "略過的工作表" in SRC[SRC.index("月報已寄送"):][:200]


def test_builders_call_the_hooks_only_through_the_off_list():
    assert "_off = _off_sheets()\n    if _off:" in SRC and "_drop_excel_sheets(wb, _off)" in SRC, "Excel：沒有關掉的工作表就完全不動"
    assert "return _drop_pdf_sections(html, _off) if _off else html" in SRC, "PDF：沒有關掉的工作表就回傳同一個字串"
    assert 'if "targets" in _off:\n        acv_html = ""' in SRC and 'if "quarter" in _off:\n        quarter_section_html = ""' in SRC
    mail = SRC[SRC.index("excel_bytes = _build_excel(mail_data"):][:600]
    assert "_build_excel" in mail, "月報郵件附件用同一個 _build_excel（自動跟著範本）"


def test_preview_lists_which_sheets_appear():
    pv = ET.preview(None, {"username": "u", "role": "superadmin"}, _body("summary", "warranty"), EID)
    assert [s["id"] for s in pv["sheets"] if s["on"]] == ["summary", "warranty"]
    assert pv["columns"] == [] and any("不會出現" in w for w in pv["warnings"])
    assert any("摘要永遠包含公司層級金額合計" in w for w in pv["warnings"])
    assert not any("不會出現" in w for w in ET.preview(None, {"username": "u", "role": "superadmin"}, _body(*ALL), EID)["warnings"])


# ── 編輯器（node 假 DOM）──────────────────────────────────────────────────
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_editor_sheet_checklist_converts_to_a_template_and_keeps_required_on():
    from tests.platform import test_export_editor_bp3 as BE
    cat = {"enabled": True, "canEdit": True, "exportId": EID, "label": "營運報表", "formats": ["xlsx", "pdf"], "decorOnly": False, "columns": [],
           "caps": {"xlsx": [], "pdf": []}, "lockLabels": False, "sheets": ET.registered()[EID]["sheets"]}
    setup = "const E = window.MotrixExportEditor, st = E._state; E._init(%s); " % json.dumps(cat)
    r = BE._run({"status": cat, "run": setup + ("st.sheets['aging'] = false; st.sheets['summary'] = false; st.sheets['targets'] = false;"
                                                 " return [E._toTemplate(), E._problems()]")})
    tpl, probs = r["v"]
    assert tpl["sheets"] == [x for x in ALL if x not in ("aging", "targets")] and tpl["format"] == "xlsx" and "columns" not in tpl
    assert "summary" in tpl["sheets"], "必選的永遠在"
    assert probs == []
    assert ET.definition_problems(EID, tpl) == []


# ── 標題型（S-Q2）與工作表型（S-F2 B）合併：同一個註冊表同時支援，兩種語意都不變 ─────────────────────
BOTH = "t_both:doc"


def _register_both():
    ET.register_export(BOTH, label="兩者", formats=("pdf",), columns=[], sample_rows=[], caps=(),
                       titles={"a": ("甲標題", "甲另一個")},
                       sheets=[{"id": "main", "label": "主表", "required": True}, {"id": "extra", "label": "附表", "money": True}])


def test_registry_supports_titles_sheets_or_both():
    _register_both()
    reg = ET.registered()
    assert reg[BOTH]["titles"] == {"a": ["甲標題", "甲另一個"]} and [x["id"] for x in reg[BOTH]["sheets"]] == ["main", "extra"]
    assert reg[BOTH]["decorOnly"] is False
    from helpers import clause_titles as CT
    assert reg[CT.EXPORT_ID]["titles"] and reg[CT.EXPORT_ID]["sheets"] == [] and reg[CT.EXPORT_ID]["decorOnly"] is True, "標題型維持原樣"
    assert reg[EID]["titles"] == {} and reg[EID]["sheets"], "工作表型維持原樣"


def test_both_validate_default_and_preview_together():
    _register_both()
    d = ET.default_template(BOTH)
    assert d["sheets"] == ["main", "extra"] and ET.definition_problems(BOTH, d) == []
    ok = {"version": 1, "format": "pdf", "sheets": ["main"], "titles": {"a": "甲另一個"}}
    assert ET.definition_problems(BOTH, ok) == []
    bad = {"version": 1, "format": "pdf", "sheets": ["main"], "titles": {"a": "自己寫的"}}
    assert {p["path"] for p in ET.definition_problems(BOTH, bad)} == {"titles.a"}
    assert {p["path"] for p in ET.definition_problems(BOTH, {"version": 1, "format": "pdf", "sheets": ["extra"]})} == {"sheets"}
    pv = ET.preview(None, {"username": "u", "role": "superadmin"}, ok, BOTH)
    assert pv["titlesPreview"]["draft"]["a"] == "甲另一個" and [s["id"] for s in pv["sheets"] if s["on"]] == ["main"] and pv["decorOnly"] is True
    assert "甲另一個" in pv["html"]


def test_titles_only_and_sheets_only_exports_keep_their_old_validation_and_preview_shape():
    from helpers import clause_titles as CT
    assert {p["path"] for p in ET.definition_problems(CT.EXPORT_ID, {"version": 1, "format": "pdf"})} == {""}, "標題型：至少設定一項"
    assert "sheets" in {p["path"] for p in ET.definition_problems(CT.EXPORT_ID, {"version": 1, "format": "pdf", "titles": {}, "sheets": ["x"]})}
    pv = ET.preview(None, {"username": "u", "role": "superadmin"}, {"version": 1, "format": "pdf", "titles": {}}, CT.EXPORT_ID)
    assert pv["decorOnly"] is True and "titlesPreview" in pv and "sheets" not in pv and pv["watermark"] is None
    pv2 = ET.preview(None, {"username": "u", "role": "superadmin"}, _body(*ALL), EID)
    assert "sheets" in pv2 and "titlesPreview" not in pv2 and "decorOnly" not in pv2 and "html" not in pv2


def test_comparator_combines_titles_and_sheets_semantics():
    from routers.def_pipeline import classify
    _register_both()
    a = {"version": 1, "format": "pdf", "sheets": ["main", "extra"], "titles": {}}
    b = {"version": 1, "format": "pdf", "sheets": ["main"], "titles": {"a": "甲另一個"}}
    cls, why = classify("export_template", a, b)
    assert cls == "loosen" and any("條款標題" in w for w in why) and any("關掉工作表" in w for w in why), "換標題＝放寬，同時關工作表＝收緊；合併後以放寬為準"
    assert classify("export_template", b, a)[0] == "loosen", "加回含金額的工作表＝放寬"
    assert classify("export_template", {"version": 1, "format": "pdf", "sheets": ["main", "extra"], "titles": {"a": "甲標題"}},
                    {"version": 1, "format": "pdf", "sheets": ["main"], "titles": {}})[0] == "tighten"
