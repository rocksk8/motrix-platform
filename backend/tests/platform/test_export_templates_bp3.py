# -*- coding: utf-8 -*-
"""BP-3 匯出範本（R0 模型＋驗證、R1 先導匯出、R2 預覽與治理）。設定 builder_exports.enabled 預設關。

- R0：範本只收宣告式資料（欄位 id 必須在欄位目錄、標題是純文字、沒有占位符／運算式／控制字元）；CSV 沒有頁首頁尾／浮水印；浮水印不得含官方狀態字樣
- 遮蔽優先：money／有 visible 的欄位在輸出端再驗一次權限，沒權限 ⇒ 整欄省略；money 沒有 visible ⇒ 一律不顯示（fail-closed）
- R1（每日任務歷程 CSV）：旗標關 ⇒ 輸出與預設完全相同，已發布的範本也不套用；開且有範本 ⇒ 欄位／標題／順序依範本、每格仍經 csv_safe
- R2：預覽端點（關 404、非最高管理者 403、不合法 422、不寫資料）；治理開啟時 export_template 發布要帶預覽雜湊、放寬（新增欄位）變待核准
"""
import csv
import io

import pytest

from helpers import export_templates as ET


# ── 測試用的匯出目錄（不依賴任何 L2 模組）────────────────────────────────
def _is_super(u):
    return (u or {}).get("role") == "superadmin"


ET.register_export(
    "t_bp3:csv", label="測試 CSV", formats=("csv",),
    columns=[{"id": "name", "label": "名稱"}, {"id": "note", "label": "備註"},
             {"id": "amount", "label": "金額", "money": True, "visible": _is_super},
             {"id": "secret", "label": "隱藏", "money": True}],                       # money 沒有 visible ⇒ fail-closed
    sample_rows=[{"name": "甲", "note": "=cmd", "amount": 100, "secret": "x"}, {"name": "乙", "note": "-VLAN", "amount": 200, "secret": "y"}])
ET.register_export(
    "t_bp3:pdf", label="測試 PDF", formats=("pdf", "xlsx"),
    columns=[{"id": "a", "label": "甲欄"}, {"id": "b", "label": "乙欄"}], sample_rows=[{"a": 1, "b": 2}])


def _tpl(cols, **kw):
    return dict({"version": 1, "format": "csv", "columns": [{"id": i, "label": l} for i, l in cols]}, **kw)


def _bad(body, key="t_bp3:csv"):
    return ET.definition_problems(key, body)


def _paths(probs):
    return {p["path"] for p in probs}


# ── R0：模型與驗證 ────────────────────────────────────────────────────────
def test_default_template_is_valid_and_matches_the_catalog_order():
    d = ET.default_template("t_bp3:csv")
    assert d["columns"] == [{"id": "name", "label": "名稱"}, {"id": "note", "label": "備註"}, {"id": "amount", "label": "金額"}, {"id": "secret", "label": "隱藏"}]
    assert _bad(d) == []


@pytest.mark.parametrize("body,path", [
    ({"version": 2, "format": "csv", "columns": [{"id": "name", "label": "n"}]}, "version"),
    ({"version": 1, "format": "xlsx", "columns": [{"id": "name", "label": "n"}]}, "format"),
    ({"version": 1, "format": "csv", "columns": []}, "columns"),
    ({"version": 1, "format": "csv", "columns": [{"id": "nope", "label": "n"}]}, "columns[0].id"),
    ({"version": 1, "format": "csv", "columns": [{"id": "name", "label": "a"}, {"id": "name", "label": "b"}]}, "columns[1].id"),
    ({"version": 1, "format": "csv", "columns": [{"id": "name", "label": "同"}, {"id": "note", "label": "同"}]}, "columns[1].label"),
    ({"version": 1, "format": "csv", "columns": [{"id": "name", "label": "{{x}}"}]}, "columns[0].label"),            # 占位符
    ({"version": 1, "format": "csv", "columns": [{"id": "name", "label": "<b>x"}]}, "columns[0].label"),
    ({"version": 1, "format": "csv", "columns": [{"id": "name", "label": "=SUM(A1)"}]}, "columns[0].label"),          # 開頭觸發字元
    ({"version": 1, "format": "csv", "columns": [{"id": "name", "label": "x" * 21}]}, "columns[0].label"),
    ({"version": 1, "format": "csv", "columns": [{"id": "name", "label": "a‮b"}]}, "columns[0].label"),          # 雙向覆寫
    ({"version": 1, "format": "csv", "columns": [{"id": "name", "label": "a\nb"}]}, "columns[0].label"),             # 控制字元
    ({"version": 1, "format": "csv", "columns": [{"id": "name", "label": "n", "formula": "a+b"}]}, "columns[0].formula"),  # 沒有運算式
    ({"version": 1, "format": "csv", "columns": [{"id": "name", "label": "n", "format": "#,##0"}]}, "columns[0].format"),
    ({"version": 1, "format": "csv", "columns": [{"id": "name", "label": "n"}], "script": "x"}, "script"),
    ({"version": 1, "format": "csv", "columns": [{"id": "name", "label": "n"}], "header": {"text": "H"}}, "header"),       # CSV 沒有頁首
    ({"version": 1, "format": "csv", "columns": [{"id": "name", "label": "n"}], "watermark": {"text": "W"}}, "watermark"),
])
def test_validator_rejects(body, path):
    assert path in _paths(_bad(body)), _bad(body)


def test_validator_rejects_unknown_export_and_non_object():
    assert _bad(_tpl([("name", "n")]), key="nope:x")
    assert _bad([1, 2])


def test_header_footer_watermark_only_where_the_format_has_them_and_reserved_words_are_refused():
    base = {"version": 1, "format": "pdf", "columns": [{"id": "a", "label": "甲"}]}
    assert _bad(dict(base, header={"text": "內部資料"}, footer={"text": "第一頁"}, watermark={"text": "內部使用"}), key="t_bp3:pdf") == []
    xl = dict(base, format="xlsx", header={"text": "H"})
    assert _bad(xl, key="t_bp3:pdf") == []
    assert "watermark" in _paths(_bad(dict(xl, watermark={"text": "W"}), key="t_bp3:pdf")), "xlsx 沒有浮水印"
    for w in ("正本", "已核准", "已 付 款", "已簽回", "作廢", "已核可"):
        assert "watermark.text" in _paths(_bad(dict(base, watermark={"text": w}), key="t_bp3:pdf")), w
    assert "watermark.text" in _paths(_bad(dict(base, watermark={"text": "已核准"}), key="t_bp3:pdf")), "全形／近似也擋（NFKC）"
    assert "watermark.text" in _paths(_bad(dict(base, watermark={"text": "ｗ" * 41}), key="t_bp3:pdf"))
    assert "header.text" in _paths(_bad(dict(base, header={"text": "{x}"}), key="t_bp3:pdf"))
    assert "header.x" in _paths(_bad(dict(base, header={"text": "H", "x": 1}), key="t_bp3:pdf"))


# ── 遮蔽優先 ──────────────────────────────────────────────────────────────
def test_money_columns_need_the_permission_check_and_fail_closed_without_one():
    t = _tpl([("name", "名稱"), ("amount", "金額"), ("secret", "隱藏"), ("note", "備註")])
    cols, omitted = ET.effective_columns("t_bp3:csv", t, {"role": "superadmin"})
    assert [c["id"] for c in cols] == ["name", "amount", "note"]
    assert omitted == [{"id": "secret", "reason": "這位使用者沒有這個欄位的檢視權限"}], "money 沒有 visible ⇒ 對誰都不顯示"
    cols, omitted = ET.effective_columns("t_bp3:csv", t, {"role": "viewer"})
    assert [c["id"] for c in cols] == ["name", "note"] and {o["id"] for o in omitted} == {"amount", "secret"}
    # visible 丟例外 ⇒ 當沒權限
    ET._EXPORTS["t_bp3:csv"]["columns"][2]["visible"] = lambda u: 1 / 0
    try:
        cols, _ = ET.effective_columns("t_bp3:csv", t, {"role": "superadmin"})
        assert "amount" not in [c["id"] for c in cols]
    finally:
        ET._EXPORTS["t_bp3:csv"]["columns"][2]["visible"] = _is_super


def test_render_csv_rows_reorders_renames_and_neutralizes_every_cell():
    t = _tpl([("note", "備註欄"), ("name", "名稱")])
    rows = [{"name": "=HYPERLINK(1)", "note": "-VLAN", "amount": 5}, {"name": "乙", "note": None}]
    table, omitted = ET.render_csv_rows("t_bp3:csv", t, rows, {"role": "viewer"})
    assert table == [["備註欄", "名稱"], ["'-VLAN", "'=HYPERLINK(1)"], [None, "乙"]] and omitted == []
    assert not any("amount" in str(r) for r in table), "範本沒選的欄位不會輸出（範本不能新增資料，只能選目錄裡的）"


def test_default_template_renders_the_same_header_and_cells_as_the_hard_coded_export():
    """R1 的『預設＝今天』證明：預設範本渲染 ＝ 端點原本寫死的標題與欄位順序。"""
    ET_ID = "daily_tasks:task-history"
    import modules.daily_tasks.api as dt                      # 註冊 ET 的匯出目錄
    d = ET.default_template(ET_ID)
    row = {c: "v%d" % i for i, c in enumerate(dt._HISTORY_COLS)}
    table, omitted = ET.render_csv_rows(ET_ID, d, [row], {"role": "superadmin"})
    assert table[0] == ["工作事項", "日期", "星期", "指派人員", "完成狀態", "完成時間", "回報內容"] and omitted == []
    assert table[1] == ["v%d" % i for i in range(7)]


# ── API 共用 ──────────────────────────────────────────────────────────────
def _login(client, make_user, name, role="superadmin", modules=None):
    u, pw = make_user(username=name, role=role, **({"modules": modules} if modules is not None else {}))[:2]
    return u, {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]}


def _flag(monkeypatch, on, governance=False):
    monkeypatch.setattr(ET, "enabled", lambda conn=None: on)
    import routers.def_governance as G
    import routers.def_pipeline as P
    import routers.definitions as DF
    monkeypatch.setattr(G, "enabled", lambda conn=None: governance)
    monkeypatch.setattr(P, "enabled", lambda conn=None: governance)
    monkeypatch.setattr(DF, "_governance_enabled", lambda conn=None: governance)


EID = "daily_tasks:task-history"


def _seed_task(client, hd, username, title="=巡檢", report="-VLAN10 異常"):
    from datetime import date
    r = client.post("/api/daily-tasks", json={"task_date": date.today().isoformat(), "title": title, "assigned_to": [username]}, headers=hd)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    c = client.patch("/api/daily-tasks/%d/complete" % tid, json={"completed": True, "report": report}, headers=hd)
    assert c.status_code == 200, c.text
    return tid


def _export(client, hd, tid):
    r = client.get("/api/daily-tasks/%d/history/export" % tid, headers=hd)
    assert r.status_code == 200, r.text
    return r.content


def _publish(client, hd, body, key=EID, note="t", preview_hash=None):
    url = "/api/definitions/export_template/%s" % key
    s = client.put(url + "/draft?scope=company", json={"body": body}, headers=hd)
    assert s.status_code == 200, s.text
    payload = {"note": note}
    if preview_hash:
        payload["preview_hash"] = preview_hash
    return client.post(url + "/publish?scope=company", json=payload, headers=hd)


def _rows(raw):
    return list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))


# ── R1：先導匯出 ──────────────────────────────────────────────────────────
def test_flag_off_export_is_identical_to_default_and_ignores_a_published_template(client, make_user, monkeypatch):
    u, hd = _login(client, make_user, "bp3_sa", "superadmin")
    tid = _seed_task(client, hd, u)
    _flag(monkeypatch, False)
    off = _export(client, hd, tid)
    rows = _rows(off)
    assert rows[0] == ["工作事項", "日期", "星期", "指派人員", "完成狀態", "完成時間", "回報內容"], "旗標關＝今天寫死的標題"
    assert rows[1][0] == "'=巡檢" and rows[1][6] == "'-VLAN10 異常", "公式中和（csv_safe）照舊"
    assert off.startswith(b"\xef\xbb\xbf"), "UTF-8 BOM 照舊"
    _flag(monkeypatch, True)
    assert _export(client, hd, tid) == off, "旗標開、沒有已發布範本 ⇒ 仍與預設逐位元相同"
    r = _publish(client, hd, _tpl([("report", "回報"), ("title", "事項")]))
    assert r.status_code == 200 and not r.json().get("pending"), r.text
    _flag(monkeypatch, False)
    assert _export(client, hd, tid) == off, "旗標關回去 ⇒ 已發布的範本不再套用，輸出與預設逐位元相同"


def test_flag_on_published_template_drives_columns_labels_order_and_keeps_neutralization(client, make_user, monkeypatch):
    u, hd = _login(client, make_user, "bp3_sa2", "superadmin")
    tid = _seed_task(client, hd, u)
    _flag(monkeypatch, True)
    r = _publish(client, hd, _tpl([("report", "回報內容"), ("title", "事項"), ("date", "日期")]))
    assert r.status_code == 200, r.text
    rows = _rows(_export(client, hd, tid))
    assert rows[0] == ["回報內容", "事項", "日期"], "欄位／標題／順序依範本；沒選的欄位不輸出"
    assert rows[1][0] == "'-VLAN10 異常" and rows[1][1] == "'=巡檢", "範本路徑的每個儲存格仍經 csv_safe"
    assert len(rows) == 2


# ── R2：預覽與定義端點 ────────────────────────────────────────────────────
def test_preview_is_404_when_off_403_for_non_superadmin_422_when_invalid_and_writes_nothing(client, make_user, monkeypatch):
    import db
    _, h_sa = _login(client, make_user, "bp3_sa3", "superadmin")
    _, h_ad = _login(client, make_user, "bp3_ad", "admin", modules=["daily_task"])
    url = "/api/export-templates/%s/preview" % EID
    good = {"template": ET.default_template(EID)}
    _flag(monkeypatch, False)
    assert client.post(url, json=good, headers=h_sa).status_code == 404
    _flag(monkeypatch, True)
    assert client.post(url, json=good, headers=h_ad).status_code == 403
    assert client.post(url, json=good).status_code in (401, 403)
    assert client.post("/api/export-templates/nope/preview", json=good, headers=h_sa).status_code == 404
    bad = client.post(url, json={"template": _tpl([("nope", "x")])}, headers=h_sa)
    assert bad.status_code == 422 and bad.json()["detail"]["problems"]
    assert client.post(url, json={"template": good["template"], "n": "x"}, headers=h_sa).status_code == 422

    def count():
        c = db.get_db()
        try:
            return c.execute("SELECT (SELECT COUNT(*) FROM ui_definitions)+(SELECT COUNT(*) FROM audit_log WHERE action LIKE 'export.%')").fetchone()[0]
        finally:
            c.close()
    n0 = count()
    ok = client.post(url, json={"template": _tpl([("title", "事項"), ("report", "回報")])}, headers=h_sa)
    assert ok.status_code == 200, ok.text
    d = ok.json()
    assert d["columns"] == ["事項", "回報"] and d["sample"] == "sample" and d["rows"][0][0] == "每週設備巡檢"
    assert count() == n0, "預覽不寫定義、不留 export.* 稽核、不計匯出"


def test_preview_as_another_user_uses_that_users_visible_rows(client, make_user, monkeypatch):
    u, h_sa = _login(client, make_user, "bp3_sa4", "superadmin")
    other, _ = _login(client, make_user, "bp3_other", "admin", modules=["daily_task"])
    _seed_task(client, h_sa, u, title="只有我的")
    _flag(monkeypatch, True)
    url = "/api/export-templates/%s/preview" % EID
    t = {"template": _tpl([("title", "事項")]), "sample": "visible"}
    mine = client.post(url, json=t, headers=h_sa).json()
    assert mine["sample"] == "visible" and any("只有我的" in r[0] for r in mine["rows"])
    theirs = client.post(url, json=dict(t, user=other), headers=h_sa).json()
    assert theirs["user"] == other and theirs["sample"] == "sample" and theirs["warnings"], "別人沒被指派 ⇒ 看不到這筆，退回樣本並說明"
    assert not any("只有我的" in r[0] for r in theirs["rows"])
    assert client.post(url, json=dict(t, user="no_such_user"), headers=h_sa).status_code == 404


def test_status_endpoint_hides_the_editor_unless_on_and_superadmin(client, make_user, monkeypatch):
    _, h_sa = _login(client, make_user, "bp3_sa5", "superadmin")
    _, h_ad = _login(client, make_user, "bp3_ad2", "admin", modules=["daily_task"])
    url = "/api/export-templates/%s/status" % EID
    _flag(monkeypatch, False)
    assert client.get(url, headers=h_sa).json() == {"enabled": False, "canEdit": False}
    _flag(monkeypatch, True)
    s = client.get(url, headers=h_sa).json()
    assert s["enabled"] and s["canEdit"] and [c["id"] for c in s["columns"]] == ["title", "date", "weekday", "assignee", "status", "at", "report"]
    a = client.get(url, headers=h_ad).json()
    assert a == {"enabled": True, "canEdit": False}, "非最高管理者拿不到欄位目錄"
    assert client.get("/api/export-templates/nope/status", headers=h_sa).status_code == 404
    assert client.get(url).status_code in (401, 403)


def test_definition_is_admin_only_and_rejected_while_off(client, make_user, monkeypatch):
    _, h_sa = _login(client, make_user, "bp3_sa6", "superadmin")
    _, h_ad = _login(client, make_user, "bp3_ad3", "admin", modules=["daily_task"])
    d = "/api/definitions/export_template/%s" % EID
    _flag(monkeypatch, True)
    for who in (h_ad,):
        assert client.get(d + "?scope=company", headers=who).status_code in (401, 403)
        assert client.put(d + "/draft?scope=company", json={"body": ET.default_template(EID)}, headers=who).status_code in (401, 403)
    _flag(monkeypatch, False)
    v = client.post(d + "/validate", json={"body": ET.default_template(EID)}, headers=h_sa)
    assert v.status_code == 200 and any(ET.OFF_REASON in p["message"] for p in v.json()["problems"]), "旗標關：發布驗證擋"
    kinds = client.get("/api/definition-kinds", headers=h_sa).json()
    kinds = kinds.get("kinds", kinds) if isinstance(kinds, dict) else kinds
    assert "export_template" in [k["kind"] if isinstance(k, dict) else k for k in kinds], "kind 有登記（版本／還原／帳本共用定義文件庫）"


# ── R2：治理（版本／預覽雜湊／待核准／還原）──────────────────────────────
def test_governance_requires_preview_hash_and_turns_added_columns_into_pending(client, make_user, monkeypatch):
    u, hd = _login(client, make_user, "bp3_sa7", "superadmin")
    tid = _seed_task(client, hd, u)
    _flag(monkeypatch, True, governance=False)
    assert _publish(client, hd, _tpl([("title", "事項"), ("date", "日期")])).status_code == 200      # 基準：兩欄（治理關 ⇒ 直接發布）
    narrow = _rows(_export(client, hd, tid))
    assert narrow[0] == ["事項", "日期"]
    _flag(monkeypatch, True, governance=True)
    wide = _tpl([("title", "事項"), ("date", "日期"), ("report", "回報內容")])
    url = "/api/definitions/export_template/%s" % EID
    assert client.put(url + "/draft?scope=company", json={"body": wide}, headers=hd).status_code == 200
    no_hash = client.post(url + "/publish?scope=company", json={"note": "x"}, headers=hd)
    assert no_hash.status_code == 409 and no_hash.json()["code"] == "preview_required", "名單內的 kind：治理開啟後發布必須先看過預覽"
    im = client.get("/api/def-governance/export_template/%s/impact?scope=company" % EID, headers=hd)
    assert im.status_code == 200 and im.json()["previewHash"], im.text
    r = client.post(url + "/publish?scope=company", json={"note": "x", "preview_hash": im.json()["previewHash"]}, headers=hd)
    d = r.json()
    assert r.status_code == 200 and d["pending"] is True and d["changeId"] and d["effectiveAt"] and any("新增匯出欄位 report" in x for x in d["reasons"]), d
    assert _rows(_export(client, hd, tid))[0] == ["事項", "日期"], "待核准的放寬還沒生效：匯出仍是舊範本"


def test_governance_tightening_publishes_immediately_and_restore_goes_through_the_same_pipeline(client, make_user, monkeypatch):
    u, hd = _login(client, make_user, "bp3_sa8", "superadmin")
    tid = _seed_task(client, hd, u)
    _flag(monkeypatch, True, governance=False)
    assert _publish(client, hd, _tpl([("title", "事項"), ("date", "日期"), ("report", "回報")])).status_code == 200       # v1（三欄）
    _flag(monkeypatch, True, governance=True)
    url = "/api/definitions/export_template/%s" % EID
    client.put(url + "/draft?scope=company", json={"body": _tpl([("title", "事項"), ("date", "日期")])}, headers=hd)
    h = client.get("/api/def-governance/export_template/%s/impact?scope=company" % EID, headers=hd).json()["previewHash"]
    r = client.post(url + "/publish?scope=company", json={"note": "收緊", "preview_hash": h}, headers=hd)
    assert r.status_code == 200 and not r.json().get("pending"), r.text           # 移除欄位＝收緊 ⇒ 立即生效（照舊）
    assert _rows(_export(client, hd, tid))[0] == ["事項", "日期"]
    back = client.post(url + "/restore/1?scope=company", json={}, headers=hd)       # 還原到三欄版＝放寬 ⇒ 待核准，不立即生效
    assert back.status_code == 200 and back.json().get("pending") is True, back.text
    assert _rows(_export(client, hd, tid))[0] == ["事項", "日期"]


def test_pipeline_comparator_classes():
    from routers.def_pipeline import classify
    a = _tpl([("title", "事項"), ("date", "日期")])
    assert classify("export_template", a, _tpl([("date", "日期"), ("title", "標題改了")]))[0] == "neutral", "只改順序／標題 ⇒ 中性"
    assert classify("export_template", a, _tpl([("title", "事項")]))[0] == "tighten"
    c, why = classify("export_template", a, _tpl([("title", "事項"), ("date", "日期"), ("report", "回報")]))
    assert c == "loosen" and any("report" in x for x in why)
    assert classify("export_template", a, dict(a, format="xlsx"))[0] == "loosen"
    assert classify("export_template", a, dict(a, extra=1))[0] == "loosen", "無法判斷 ⇒ 放寬"
    with_wm = dict(_tpl([("title", "t")]), watermark={"text": "W"})
    assert classify("export_template", with_wm, _tpl([("title", "t")]))[0] == "tighten", "拿掉浮水印＝收緊"


def test_setting_default_is_off_and_registered():
    from helpers import settings_groups  # noqa: F401
    from helpers import settings_registry as SR
    f = {x["key"]: x for x in SR.groups()["builder_exports"]["fields"]}["enabled"]
    assert f["default"] == 0 and (f["min"], f["max"]) == (0, 1)
    assert ET.enabled() is False, "預設關"
