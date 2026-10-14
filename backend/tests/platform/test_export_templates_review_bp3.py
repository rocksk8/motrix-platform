# -*- coding: utf-8 -*-
"""BP-3 審核（04）修正的契約題：預設文字白名單、隱形字元、骨架比對、治理必開、惰性 kind、client-log 權限與間隔。

- 頁首／頁尾／浮水印文字（v1）只能從白名單挑；任何 Cc/Cf/Zl/Zp/Co/Cs 與填充字元一律拒絕；官方狀態字樣在『只留字母與數字的骨架』上比對
- builder_exports 必須同時開啟 builder_governance 才生效（讀不到 ⇒ 關）
- kind `export_template` 惰性登記：旗標關 ⇒ /api/definition-kinds 沒有它
- 任何頁首／頁尾／浮水印文字的改變 ＝ 放寬（客戶可見文字，需核准）
- client-log：旗標開時需要該頁清單的模組權限；同一位使用者同一個名稱 5 秒內只記一筆，過快靜默丟掉（logged:false），不回 429
"""
import pytest

from helpers import export_templates as ET

PDFID = "arap:invoice-voucher-pdf"
BASE = {"version": 1, "format": "pdf", "columns": [{"id": "a", "label": "甲"}]}


def _reg_test_pdf():
    ET.register_export("t_bp3r:pdf", label="測試", formats=("pdf", "xlsx"), columns=[{"id": "a", "label": "甲"}], sample_rows=[{"a": 1}])


_reg_test_pdf()


def _bad(body, key="t_bp3r:pdf"):
    return ET.definition_problems(key, body)


def _paths(probs):
    return {p["path"] for p in probs}


def _login(client, make_user, name, role="superadmin", modules=None):
    u, pw = make_user(username=name, role=role, **({"modules": modules} if modules is not None else {}))[:2]
    return u, {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]}


def _flag(monkeypatch, on):
    monkeypatch.setattr(ET, "enabled", lambda conn=None: on)


def test_decorative_text_is_preset_only_for_header_footer_and_watermark():
    for part in ("header", "footer", "watermark"):
        for t in ET.WATERMARK_PRESETS:
            assert _bad(dict(BASE, **{part: {"text": t}})) == [], (part, t)
        assert part + ".text" in _paths(_bad(dict(BASE, **{part: {"text": "自己寫的文字"}}))), "自由文字一律拒絕"
    assert _bad(dict(BASE, footer={"text": "列印後請妥善保管"})) == [], "頁首頁尾有額外的預設文字"
    assert "watermark.text" in _paths(_bad(dict(BASE, watermark={"text": "列印後請妥善保管"}))), "浮水印只開較短的預設"
    assert set(ET.WATERMARK_PRESETS) <= set(ET.PRESET_TEXTS)
    assert not any(ET._reserved_hit(t) for t in ET.PRESET_TEXTS), "預設文字本身不得含官方狀態字樣"


@pytest.mark.parametrize("sneaky", [
    "正­本", "正⁠本", "正͏本", "正ㅤ本", "正ᅟ本", "正​本", "正‎本", "正‮本", "正️本",
    "正\U000e0041本", "正\u0085本", "正 本", "正 本", "正本", "已᠎核准", "內部ㅤ資料",
])
def test_invisible_characters_are_rejected_in_every_decorative_part(sneaky):
    for part in ("header", "footer", "watermark"):
        assert part + ".text" in _paths(_bad(dict(BASE, **{part: {"text": sneaky}}))), (part, sneaky)


@pytest.mark.parametrize("word", ["正本", "已核准", "核准", "核可", "簽核完成", "已收款", "作废", "作廢", "APPROVED", "Paid", "ORIGINAL", "void", "已 簽 回", "ａｐｐｒｏｖｅｄ"])
def test_reserved_status_words_are_banned_on_a_letters_and_digits_skeleton_in_all_parts(word):
    assert ET._reserved_hit(word), word
    for part in ("header", "footer", "watermark"):
        assert part + ".text" in _paths(_bad(dict(BASE, **{part: {"text": word}}))), (part, word)
    assert not ET._reserved_hit("內部資料") and not ET._reserved_hit("機密")


def test_column_labels_also_reject_invisible_characters_but_stay_free_text():
    ET.register_export("t_bp3r:csv", label="c", formats=("csv",), columns=[{"id": "name", "label": "姓名"}], sample_rows=[])
    t = lambda label: {"version": 1, "format": "csv", "columns": [{"id": "name", "label": label}]}
    assert "columns[0].label" in _paths(_bad(t("姓​名"), "t_bp3r:csv"))
    assert "columns[0].label" in _paths(_bad(t("姓ㅤ名"), "t_bp3r:csv"))
    assert _bad(t("客戶名稱"), "t_bp3r:csv") == []


def test_builder_exports_is_effective_only_with_builder_governance(monkeypatch):
    import helpers.settings_registry as SR
    vals = {"builder_exports": 1, "builder_governance": 0}
    monkeypatch.setattr(SR, "get", lambda g, f, conn=None: vals[g])
    assert ET.enabled() is False, "治理沒開 ⇒ 自訂匯出不生效（放寬沒有核准、預覽雜湊兩道把關）"
    vals["builder_governance"] = 1
    assert ET.enabled() is True
    vals["builder_exports"] = 0
    assert ET.enabled() is False

    def boom(g, f, conn=None):
        raise RuntimeError("unreadable")
    monkeypatch.setattr(SR, "get", boom)
    assert ET.enabled() is False, "讀不到 ⇒ 關（fail-closed）"


def test_kind_is_registered_lazily_only_when_enabled(monkeypatch):
    import core.definitions as D
    saved = D._EXTRA_KINDS.pop(ET.KIND, None)
    try:
        monkeypatch.setattr(ET, "enabled", lambda conn=None: False)
        assert ET.ensure_kind() is False and ET.KIND not in D.kinds(), "旗標關 ⇒ 不登記（/api/definition-kinds 與今天相同）"
        monkeypatch.setattr(ET, "enabled", lambda conn=None: True)
        assert ET.ensure_kind() is True and ET.KIND in D.kinds()
        assert ET.ensure_kind() is True, "冪等"
    finally:
        D._EXTRA_KINDS.pop(ET.KIND, None)
        if saved is not None:
            D._EXTRA_KINDS[ET.KIND] = saved


def test_definition_kinds_listing_has_the_kind_only_when_on(client, make_user, monkeypatch):
    import core.definitions as D
    _, h = _login(client, make_user, "bp3r_sa1", "superadmin")
    saved = D._EXTRA_KINDS.pop(ET.KIND, None)
    try:
        _flag(monkeypatch, False)
        assert ET.KIND not in [k["kind"] for k in client.get("/api/definition-kinds", headers=h).json()["kinds"]]
        _flag(monkeypatch, True)
        assert ET.KIND in [k["kind"] for k in client.get("/api/definition-kinds", headers=h).json()["kinds"]]
    finally:
        D._EXTRA_KINDS.pop(ET.KIND, None)
        if saved is not None:
            D._EXTRA_KINDS[ET.KIND] = saved


def test_status_endpoint_offers_the_preset_lists_to_superadmin_only(client, make_user, monkeypatch):
    import modules.arap.api.invoice_vouchers  # noqa: F401  註冊匯出目錄
    _, h_sa = _login(client, make_user, "bp3r_sa2", "superadmin")
    _, h_ad = _login(client, make_user, "bp3r_ad1", "admin", modules=["daily_task"])
    _flag(monkeypatch, True)
    url = "/api/export-templates/%s/status" % PDFID
    s = client.get(url, headers=h_sa).json()
    assert s["presets"] == list(ET.PRESET_TEXTS) and s["watermarkPresets"] == list(ET.WATERMARK_PRESETS) and s["decorOnly"] is True
    assert "presets" not in client.get(url, headers=h_ad).json()


def test_pipeline_any_decorative_text_change_is_a_loosening():
    from routers.def_pipeline import classify
    base = dict(BASE, footer={"text": "內部資料"})
    assert classify("export_template", base, dict(base, footer={"text": "機密"}))[0] == "loosen"
    assert classify("export_template", base, dict(base, watermark={"text": "機密"}))[0] == "loosen"
    assert classify("export_template", base, dict(base))[0] == "neutral"
    assert classify("export_template", base, {k: v for k, v in base.items() if k != "footer"})[0] == "tighten"


def test_client_log_needs_the_page_permission_and_drops_too_fast_repeats_silently(client, make_user, monkeypatch):
    import routers.export_templates as RT
    _, h_sa = _login(client, make_user, "bp3r_sa3", "superadmin")
    _, h_no = _login(client, make_user, "bp3r_none", "admin", modules=[])
    _, h_cust = _login(client, make_user, "bp3r_cust", "admin", modules=["customer"])
    _flag(monkeypatch, True)
    RT._last_client_log.clear()
    url = "/api/exports/client-log"
    assert client.post(url, json={"name": "customers", "rows": 3}, headers=h_no).status_code == 403, "沒有該頁清單的模組權限 ⇒ 403"
    assert client.post(url, json={"name": "suppliers", "rows": 3}, headers=h_cust).status_code == 200, "customer 模組可看供應商清單（與清單 API 同組）"
    assert client.post(url, json={"name": "parts", "rows": 3}, headers=h_cust).status_code == 403
    first = client.post(url, json={"name": "customers", "rows": 3}, headers=h_sa).json()
    again = client.post(url, json={"name": "customers", "rows": 3}, headers=h_sa)
    assert first == {"ok": True, "logged": True}
    assert again.status_code == 200 and again.json() == {"ok": True, "logged": False}, "太快 ⇒ 靜默丟掉，不是 429"
    assert client.post(url, json={"name": "parts", "rows": 3}, headers=h_sa).json()["logged"] is True, "間隔是『每位使用者每個名稱』"
    monkeypatch.setattr(RT, "CLIENT_LOG_MIN_INTERVAL", 0.0)
    assert client.post(url, json={"name": "customers", "rows": 3}, headers=h_sa).json()["logged"] is True
