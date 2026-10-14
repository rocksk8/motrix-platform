# -*- coding: utf-8 -*-
"""S-Q2 稽核 MUST-FIX：`clauseTitles` 是伺服器自有欄位——用戶端送的一律不採用，只有『離開草稿／解鎖重簽』由伺服器凍結。

六條寫入路徑 × 範本生效（ON）與沒生效（OFF）：
1 草稿存檔　2 待審核維持原狀的 PUT（被鎖，且資料庫值不變）　3 PUT 離開草稿但目標不是待審核
4 解鎖編輯（重簽 ⇒ 以當下範本重新凍結）　5 收回　6 複製成新單（等同 POST 帶來源的 clauseTitles）
"""
import json

import pytest

from helpers import clause_titles as CT
from helpers import export_templates as ET
from tests._requires import requires_module

pytestmark = requires_module("case", "本檔的題打案件模組的報價單端點")

FORGED = {"paymentTerms": "款項約定", "afterSales": "備註說明"}
ACTIVE = {"paymentTerms": "付款方式"}


def _tpl(monkeypatch, titles):
    body = None if titles is None else {"version": 1, "format": "pdf", "titles": titles}
    monkeypatch.setattr(ET, "resolve", lambda eid, conn=None: body if eid == CT.EXPORT_ID else None)
    from modules.case.api import quotations as QA          # 簽核層與通知不是本檔要測的（測試帳號沒有部門 ⇒ 組層會 400）
    monkeypatch.setattr(QA, "_build_approval_tiers_and_notify", lambda q, appr, no, is_new_submission: q.__setitem__("approval", appr) or appr)


def _h(client, make_user, name):
    u, pw = make_user(username=name, role="superadmin")[:2]
    t = client.post("/api/auth/login", json={"username": u, "password": pw}, headers={"X-Forwarded-For": "203.0.113.77"}).json()["token"]
    return {"Authorization": "Bearer " + t}


def _data(no):
    from modules.case.api import quotations as QA
    conn = QA.get_db()
    try:
        return json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()["data_json"] or "{}")
    finally:
        conn.close()


def _create(client, h, status="草稿", data=None):
    d = {"customerName": "S-Q2客戶"}
    d.update(data or {})
    r = client.post("/api/quotations", headers=h, json={"status": status, "data": d})
    assert r.status_code == 201, r.text[:200]
    return r.json().get("quoteNo") or r.json().get("quote_no")


def _put(client, h, no, status, data=None):
    d = {"customerName": "S-Q2客戶"}
    d.update(data or {})
    return client.put("/api/quotations/%s" % no, headers=h, json={"status": status, "data": d})


def _frozen(no):
    return _data(no).get("clauseTitles")


@pytest.mark.parametrize("on", [True, False])
def test_p1_draft_save_drops_client_value(client, make_user, monkeypatch, on):
    _tpl(monkeypatch, ACTIVE if on else None)
    h = _h(client, make_user, "ct_p1_%d" % on)
    no = _create(client, h, "草稿", {"clauseTitles": FORGED})
    assert _frozen(no) is None
    assert _put(client, h, no, "草稿", {"clauseTitles": FORGED}).status_code == 200
    assert _frozen(no) is None


def test_p6_create_with_copied_titles_is_dropped_and_submit_freezes_server_values(client, make_user, monkeypatch):
    _tpl(monkeypatch, ACTIVE)
    h = _h(client, make_user, "ct_p6")
    assert _frozen(_create(client, h, "草稿", {"clauseTitles": FORGED})) is None, "複製成新單帶的來源凍結值不採用"
    t = _frozen(_create(client, h, "待審核", {"clauseTitles": FORGED}))
    assert t and t["paymentTerms"] == "付款方式" and t["afterSales"] == "售後服務及備註說明", "直接建立即送審 ⇒ 伺服器凍結當下範本"


def test_p6_off_create_submit_has_no_titles(client, make_user, monkeypatch):
    _tpl(monkeypatch, None)
    h = _h(client, make_user, "ct_p6off")
    assert _frozen(_create(client, h, "待審核", {"clauseTitles": FORGED})) is None


def test_p3_put_leaving_draft_to_other_status_freezes(client, make_user, monkeypatch):
    _tpl(monkeypatch, ACTIVE)
    h = _h(client, make_user, "ct_p3")
    no = _create(client, h, "草稿")
    r = _put(client, h, no, "已送出", {"clauseTitles": FORGED})
    assert r.status_code == 200, r.text[:200]
    t = _frozen(no)
    assert t and t["paymentTerms"] == "付款方式" and t["afterSales"] == "售後服務及備註說明"


def test_p2_locked_put_cannot_overwrite_and_stored_value_stays(client, make_user, monkeypatch):
    _tpl(monkeypatch, ACTIVE)
    h = _h(client, make_user, "ct_p2")
    no = _create(client, h, "待審核")
    before = _frozen(no)
    assert before and before["paymentTerms"] == "付款方式"
    _tpl(monkeypatch, {"paymentTerms": "款項約定"})                      # 之後範本又改了
    r = _put(client, h, no, "待審核", {"clauseTitles": FORGED})
    assert r.status_code == 403
    assert _frozen(no) == before


def test_p4_unlock_edit_refreezes_from_server_template_not_client(client, make_user, monkeypatch):
    _tpl(monkeypatch, ACTIVE)
    h = _h(client, make_user, "ct_p4")
    no = _create(client, h, "待審核")
    _tpl(monkeypatch, {"paymentTerms": "款項約定"})
    r = _put(client, h, no, "待審核", {"_isUnlockEdit": True, "clauseTitles": FORGED})
    assert r.status_code == 200, r.text[:200]
    t = _frozen(no)
    assert t["paymentTerms"] == "款項約定" and t["afterSales"] == "售後服務及備註說明", "解鎖重簽 ⇒ 以當下範本重新凍結，不採用用戶端的"
    _tpl(monkeypatch, None)
    assert _put(client, h, no, "待審核", {"_isUnlockEdit": True, "clauseTitles": FORGED}).status_code == 200
    assert _frozen(no) is None, "範本沒生效 ⇒ 清掉（與今天相同）"


def test_p5_recall_clears_frozen_titles(client, make_user, monkeypatch):
    _tpl(monkeypatch, ACTIVE)
    h = _h(client, make_user, "ct_p5")
    no = _create(client, h, "待審核", {"approval": {"requestedBy": "ct_p5"}})
    assert _frozen(no)
    r = client.post("/api/quotations/%s/recall" % no, headers=h)
    assert r.status_code == 200, r.text[:200]
    assert _frozen(no) is None


def test_status_patch_freezes_on_leaving_draft_and_clears_on_return(client, make_user, monkeypatch):
    _tpl(monkeypatch, ACTIVE)
    h = _h(client, make_user, "ct_pp")
    no = _create(client, h, "草稿")
    assert client.patch("/api/quotations/%s/status" % no, headers=h, json={"status": "已送出"}).status_code == 200
    assert _frozen(no)["paymentTerms"] == "付款方式"
    assert client.patch("/api/quotations/%s/status" % no, headers=h, json={"status": "草稿"}).status_code == 200
    assert _frozen(no) is None


def test_return_revision_does_not_carry_the_source_titles():
    import inspect
    from modules.case.api import quotations as QA
    src = inspect.getsource(QA)
    seg = src.split("d.pop(SNAPSHOT_KEY, None)")[1][:200]
    assert 'd.pop("clauseTitles", None)' in seg


def test_form_escapes_clause_titles_in_terms_html():
    from core.source_tree import page_file
    f = page_file("quotation-form.html").read_text(encoding="utf-8")
    assert "${esc(t.title)}" in f and "${t.title}" not in f
