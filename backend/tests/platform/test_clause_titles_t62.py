# -*- coding: utf-8 -*-
"""S-Q2 報價單條款標題（匯出代號 case:quotation-clause-titles）：管理者只能從預設清單挑；送審時凍結進單據。

- 預設（第一個）＝今天寫死的字（逐項對照 TERMS_FIELD_DEFS、PDF、表單）
- 旗標關／沒有已發布範本 ⇒ 標題與過去相同、送審原因文字相同、預設條款端點不多任何鍵
- 範本生效 ⇒ PDF／表單／送審原因文字用新標題；**送審當下凍結**（clauseTitles），之後改範本不影響已送審的單據；凍結值再驗證（不在清單 ⇒ 忽略）
- 只能改標題（不能改條款本文、順序）；任何標題變更＝放寬（客戶可見文字），走治理核准
"""
import re
from pathlib import Path

import pytest

from core.source_tree import page_file
from helpers import clause_titles as CT
from helpers import export_templates as ET

ROOT = Path(__file__).resolve().parents[3]
DEFAULTS = {"paymentTerms": "付款條件", "deliveryTerms": "交貨條件", "acceptanceTerms": "驗收標準", "warrantyTerms": "保固條件", "afterSales": "售後服務及備註說明"}


def _bad(body):
    return ET.definition_problems(CT.EXPORT_ID, body)


def _paths(p):
    return {x["path"] for x in p}


def _active(monkeypatch, titles=None):
    """讓範本『生效』（不碰資料庫）：titles=None ⇒ 沒有已發布範本。"""
    body = None if titles is None else {"version": 1, "format": "pdf", "titles": titles}
    monkeypatch.setattr(ET, "resolve", lambda eid, conn=None: body if eid == CT.EXPORT_ID else None)


# ── 預設 = 今天寫死的字 ────────────────────────────────────────────────────
def test_first_preset_of_each_clause_is_the_old_hard_coded_title():
    from modules.case import quote_terms as QT
    assert {k: v[0] for k, v in CT.CLAUSE_PRESETS.items()} == DEFAULTS
    assert dict(QT.TERMS_FIELD_DEFS) == DEFAULTS
    form = page_file("quotation-form.html").read_text(encoding="utf-8")
    m = re.search(r"\(\{ paymentTerms: '([^']+)', deliveryTerms: '([^']+)', acceptanceTerms: '([^']+)', warrantyTerms: '([^']+)', afterSales: AFTERSALES_LABEL \}\)", form)
    assert m and list(m.groups()) == [DEFAULTS[k] for k in ("paymentTerms", "deliveryTerms", "acceptanceTerms", "warrantyTerms")]
    assert "const AFTERSALES_LABEL = '售後服務及備註說明'" in form


def test_off_or_unpublished_everything_is_the_old_behavior(monkeypatch):
    _active(monkeypatch, None)
    assert CT.active_titles() is None and CT.titles_for(None) == DEFAULTS and CT.titles_for({"x": 1}) == DEFAULTS
    q = {"clauseTitles": {"paymentTerms": "付款方式"}, "paymentTerms": "x"}
    CT.freeze(q)
    assert "clauseTitles" not in q, "沒生效 ⇒ 清掉舊的凍結值（重新送審以目前為準）"
    for k in CT.CLAUSE_KEYS:
        assert CT.title(k) == DEFAULTS[k]


def test_active_template_changes_titles_and_freeze_wins_over_later_template_changes(monkeypatch):
    _active(monkeypatch, {"paymentTerms": "付款方式", "afterSales": "售後服務"})
    t = CT.active_titles()
    assert t["paymentTerms"] == "付款方式" and t["afterSales"] == "售後服務" and t["deliveryTerms"] == "交貨條件"
    q = {}
    CT.freeze(q)
    assert q["clauseTitles"] == t, "送審當下把五個標題存進單據"
    _active(monkeypatch, {"paymentTerms": "款項約定"})                                        # 之後範本又改了
    assert CT.titles_for(q)["paymentTerms"] == "付款方式", "已凍結的單據不受影響"
    assert CT.titles_for({})["paymentTerms"] == "款項約定", "草稿（沒凍結）用目前的範本"
    CT.freeze(q)
    assert q["clauseTitles"]["paymentTerms"] == "款項約定", "重新送審 ⇒ 以送審當下的範本重新凍結"


def test_frozen_values_are_revalidated_against_the_presets(monkeypatch):
    _active(monkeypatch, None)
    q = {"clauseTitles": {"paymentTerms": "<script>", "deliveryTerms": "交付條件", "bogus": "x", "afterSales": 5}}
    t = CT.titles_for(q)
    assert t["paymentTerms"] == "付款條件" and t["deliveryTerms"] == "交付條件" and t["afterSales"] == "售後服務及備註說明" and "bogus" not in t


# ── 驗證 ──────────────────────────────────────────────────────────────────
def test_validator_accepts_only_presets_for_known_clauses():
    base = {"version": 1, "format": "pdf"}
    assert _bad(dict(base, titles={})) == [] and _bad(dict(base, titles={"paymentTerms": "付款方式", "warrantyTerms": "保固說明"})) == []
    assert "titles.paymentTerms" in _paths(_bad(dict(base, titles={"paymentTerms": "自己寫的標題"})))
    assert "titles.deliveryTerms" in _paths(_bad(dict(base, titles={"deliveryTerms": "付款方式"}))), "別的條款的預設也不行"
    assert "titles.nope" in _paths(_bad(dict(base, titles={"nope": "x"})))
    assert "titles" in _paths(_bad(dict(base, titles=["x"])))
    assert "footer" in _paths(_bad(dict(base, titles={}, footer={"text": "機密"}))), "這個匯出只有標題，沒有頁尾／浮水印"
    assert "columns" in _paths(_bad(dict(base, titles={}, columns=[{"id": "a", "label": "b"}])))
    assert "" in _paths(_bad(base)), "至少要設定一項"


def test_every_preset_passes_the_status_word_ban():
    for k, presets in CT.CLAUSE_PRESETS.items():
        for t in presets:
            assert not ET._reserved_hit(t), (k, t)


def test_titles_are_a_loosening_in_the_pipeline_and_resetting_is_a_tightening():
    from routers.def_pipeline import classify
    a = {"version": 1, "format": "pdf", "titles": {}}
    b = {"version": 1, "format": "pdf", "titles": {"paymentTerms": "付款方式"}}
    assert classify("export_template", a, b)[0] == "loosen"
    assert classify("export_template", b, dict(b, titles={"paymentTerms": "款項約定"}))[0] == "loosen", "換成另一個說法也要核准"
    assert classify("export_template", b, b)[0] == "neutral"
    assert classify("export_template", b, a)[0] == "tighten", "恢復預設＝收緊"


def test_preview_lists_current_and_draft_titles_without_touching_anything(monkeypatch):
    _active(monkeypatch, {"paymentTerms": "款項約定"})
    pv = ET.preview(None, {"username": "u", "role": "superadmin"}, {"version": 1, "format": "pdf", "titles": {"paymentTerms": "付款方式"}}, CT.EXPORT_ID)
    assert pv["decorOnly"] and pv["titlesPreview"]["current"]["paymentTerms"] == "款項約定" and pv["titlesPreview"]["draft"]["paymentTerms"] == "付款方式"
    assert "付款方式" in pv["html"] and "<script" not in pv["html"].lower()


# ── 消費者：送審原因文字、PDF、表單、端點 ──────────────────────────────────
def test_approval_reasons_use_the_frozen_or_current_titles(monkeypatch):
    from modules.case import quote_terms as QT
    q = {"validDays": 30, "taxRate": 5, "items": [], "paymentTerms": "我改過的付款條件"}
    _active(monkeypatch, None)
    off = [r for r in QT.compute_approval_reasons(q, [], "預設的") if r.startswith("報價條件已修改")]
    assert off and "付款條件" in off[0]
    _active(monkeypatch, {"paymentTerms": "付款方式"})
    on = [r for r in QT.compute_approval_reasons(q, [], "預設的") if r.startswith("報價條件已修改")]
    assert on and "付款方式" in on[0] and "付款條件" not in on[0]
    q2 = dict(q, clauseTitles={"paymentTerms": "款項約定"})
    frozen = [r for r in QT.compute_approval_reasons(q2, [], "預設的") if r.startswith("報價條件已修改")]
    assert frozen and "款項約定" in frozen[0]


def test_pdf_builder_reads_titles_from_the_helper_and_the_payment_request_pdf_is_untouched():
    src = (ROOT / "backend" / "pdf_gen.py").read_text(encoding="utf-8")
    assert src.count("_ct = _titles_for(q)") == 1
    for k in CT.CLAUSE_KEYS:
        assert "_ct['%s']" % k in src, k
    assert "term_block('付款條件', q.get" not in src and "term_block('驗收標準', q.get" not in src
    assert "term_block('付款條件', terms.get('paymentTerms'" in src, "第二個 builder 是請款單的『請款條件』，不是報價單條款，不動"


def test_submit_freezes_before_computing_reasons_and_the_defaults_endpoint_adds_titles_only_when_active():
    qs = (ROOT / "backend" / "modules" / "case" / "api" / "quotations.py").read_text(encoding="utf-8")
    body = qs.split("def _apply_server_submit_reasons")[1].split("@router")[0]
    assert body.index("_CT.freeze(q)") < body.index("submit_reasons(")
    sysr = (ROOT / "backend" / "routers" / "system.py").read_text(encoding="utf-8")
    assert "terms[\"titles\"] = titles" in sysr and "_CT.active_titles()" in sysr


def test_form_uses_ct_for_the_five_headings_and_the_preview_and_keeps_defaults():
    f = page_file("quotation-form.html").read_text(encoding="utf-8")
    for k in CT.CLAUSE_KEYS:
        assert "ct('%s')" % k in f, k
    assert "title: '付款條件'" not in f and "title: '驗收標準'" not in f
    assert "if (d.titles && typeof d.titles === 'object') this.clauseTitles = d.titles" in f
    assert '<meta name="motrix-export-id" content="case:quotation-clause-titles">' in f
    assert "export-editor.js" not in f


def test_defaults_endpoint_has_no_titles_key_when_off_and_has_it_when_active(client, make_user, monkeypatch):
    u, pw = make_user(username="ct_sa", role="superadmin")[:2]
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]}
    _active(monkeypatch, None)
    assert "titles" not in client.get("/api/settings/quote-terms-defaults", headers=h).json()
    _active(monkeypatch, {"paymentTerms": "付款方式"})
    assert client.get("/api/settings/quote-terms-defaults", headers=h).json()["titles"]["paymentTerms"] == "付款方式"
