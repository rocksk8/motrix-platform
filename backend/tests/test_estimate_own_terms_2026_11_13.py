# -*- coding: utf-8 -*-
"""2026-11-13（使用者：「估價單的條款要獨立，報價單有獨立條款，估價單也要」）：估價單自己的條款設定。

釘住：
1. 估價單有自己的條款組（estimate_terms_presets）與預設付款條件（estimate_default_payment_terms）：讀取登入即可、寫入限最高管理者；
   兩邊各改各的、互不影響；報價單的端點與值一個位元都不變。
2. 升級（case migration 0011）把「目前報價單的條款設定」複製成估價單的初始值；冪等、不蓋已有的、報價單沒設過就不建；報價單的鍵不動。
3. 送審重算「報價條件已修改」的比對基準依單據類型：估價單讀自己的條款組／預設付款條件，報價單讀原本那組；
   單據類型以資料庫現值為準（用戶端改 docType 騙不到另一組基準）。
4. 舊估價單資料（已存的條款文字）不被任何設定變動改動。
"""
from tests._requires import requires_module  # noqa: E402
import importlib
import json
import sqlite3

import pytest

from .test_case_extra_expenses_api_2026_09_11 import _set_empty_approval_flow

pytestmark = requires_module("case", "本檔打 M01（案件）的端點與資料（報價單／估價單）")

_TERM_FIELDS = ("paymentTerms", "deliveryTerms", "acceptanceTerms", "warrantyTerms", "afterSales")


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _preset(name, key="", **over):
    d = {"key": key, "name": name, "paymentTerms": name + " 付款", "deliveryTerms": name + " 交貨",
         "acceptanceTerms": name + " 驗收", "warrantyTerms": name + " 保固", "afterSales": name + " 售後"}
    d.update(over)
    return d


def _setting(key):
    import db
    conn = db.get_db()
    try:
        r = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (key,)).fetchone()
        return json.loads(r["value_json"]) if r else None
    finally:
        conn.close()


def _put_setting(key, value):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                     (key, json.dumps(value, ensure_ascii=False), "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _del_setting(*keys):
    import db
    conn = db.get_db()
    try:
        for k in keys:
            conn.execute("DELETE FROM system_settings WHERE key=?", (k,))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _clean_terms_settings():
    keys = ("quote_terms_presets", "estimate_terms_presets", "default_payment_terms", "estimate_default_payment_terms")
    _del_setting(*keys)
    yield
    _del_setting(*keys)


@pytest.fixture
def sa(client, make_user):
    u, p = make_user(username="est_terms_sa", role="superadmin")
    return _login(client, u, p)


# ── 1. 端點：各改各的 ────────────────────────────────────────────

def test_unset_estimate_terms_are_empty_and_readable_by_anyone(client, make_user):
    u, p = make_user(username="est_terms_sales", role="sales")
    h = _login(client, u, p)
    assert client.get("/api/settings/estimate-terms-presets", headers=h).json() == {"presets": [], "defaultKey": ""}
    assert client.get("/api/settings/estimate-payment-terms", headers=h).status_code == 200
    assert client.get("/api/settings/estimate-terms-presets").status_code in (401, 403)


def test_writes_need_superadmin(client, make_user):
    u, p = make_user(username="est_terms_adm", role="admin")
    h = _login(client, u, p)
    assert client.put("/api/settings/estimate-terms-presets", headers=h,
                      json={"presets": [_preset("甲")], "defaultKey": ""}).status_code == 403
    assert client.put("/api/settings/estimate-payment-terms", headers=h, json={"text": "x"}).status_code == 403
    assert _setting("estimate_terms_presets") is None and _setting("estimate_default_payment_terms") is None


def test_each_side_edits_its_own_presets_without_touching_the_other(client, sa):
    assert client.put("/api/settings/quote-terms-presets", headers=sa,
                      json={"presets": [_preset("報價甲", "q1")], "defaultKey": "q1"}).status_code == 200
    quote_before = _setting("quote_terms_presets")
    r = client.put("/api/settings/estimate-terms-presets", headers=sa,
                   json={"presets": [_preset("估價乙", "e1"), _preset("估價丙", "e2")], "defaultKey": "e2"})
    assert r.status_code == 200 and r.json()["defaultKey"] == "e2" and len(r.json()["presets"]) == 2
    assert _setting("quote_terms_presets") == quote_before, "改估價單不動報價單"
    assert client.get("/api/settings/quote-terms-presets", headers=sa).json() == quote_before
    est_before = _setting("estimate_terms_presets")
    assert client.put("/api/settings/quote-terms-presets", headers=sa,
                      json={"presets": [_preset("報價丁", "q9")], "defaultKey": "q9"}).status_code == 200
    assert _setting("estimate_terms_presets") == est_before, "改報價單不動估價單"
    assert client.get("/api/settings/estimate-terms-presets", headers=sa).json() == est_before


def test_estimate_presets_use_the_same_validation(client, sa):
    bad = [{"presets": [_preset("")], "defaultKey": ""},                              # 名稱空白
           {"presets": [_preset("甲", "k"), _preset("乙", "k")], "defaultKey": ""},   # key 重複
           {"presets": [_preset("甲", paymentTerms="x" * 5001)], "defaultKey": ""},   # 內容過長
           {"presets": [_preset("n%d" % i) for i in range(31)], "defaultKey": ""}]    # 超過 30 組
    for body in bad:
        assert client.put("/api/settings/estimate-terms-presets", headers=sa, json=body).status_code == 400, body["presets"][:1]
    assert _setting("estimate_terms_presets") is None
    r = client.put("/api/settings/estimate-terms-presets", headers=sa,
                   json={"presets": [_preset("甲", "a"), _preset("乙", "b")], "defaultKey": "gone"})
    assert r.json()["defaultKey"] == "a", "預設那組不存在 ⇒ 落到第一組（同報價單）"


def test_default_payment_terms_are_independent(client, sa):
    assert client.put("/api/settings/payment-terms", headers=sa, json={"text": "報價付款：月結 30"}).status_code == 200
    assert client.put("/api/settings/estimate-payment-terms", headers=sa, json={"text": "估價付款：先收 50%"}).status_code == 200
    assert client.get("/api/settings/payment-terms", headers=sa).json()["text"] == "報價付款：月結 30"
    assert client.get("/api/settings/estimate-payment-terms", headers=sa).json()["text"] == "估價付款：先收 50%"
    assert client.put("/api/settings/payment-terms", headers=sa, json={"text": "報價付款：月結 60"}).status_code == 200
    assert client.get("/api/settings/estimate-payment-terms", headers=sa).json()["text"] == "估價付款：先收 50%"


def test_unset_estimate_payment_terms_fall_back_to_the_builtin_text_not_to_the_quote_setting(client, sa):
    from modules.case.quote_terms import DEFAULT_TERMS
    assert client.put("/api/settings/payment-terms", headers=sa, json={"text": "只有報價單改過"}).status_code == 200
    assert client.get("/api/settings/estimate-payment-terms", headers=sa).json()["text"] == DEFAULT_TERMS["paymentTerms"]


# ── 2. 升級複製（case migration 0011）─────────────────────────────

def _mig():
    return importlib.import_module("modules.case.migrations.0011_estimate_terms_copy")


def _conn(rows=None):
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE system_settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL DEFAULT '{}', "
              "updated_at TEXT NOT NULL DEFAULT '')")
    for k, v in (rows or {}).items():
        c.execute("INSERT INTO system_settings (key, value_json) VALUES (?,?)", (k, json.dumps(v, ensure_ascii=False)))
    return c


def _get(c, k):
    r = c.execute("SELECT value_json FROM system_settings WHERE key=?", (k,)).fetchone()
    return json.loads(r[0]) if r else None


def test_migration_copies_current_quote_terms_into_estimate_terms():
    q = {"presets": [_preset("報價甲", "q1")], "defaultKey": "q1"}
    c = _conn({"quote_terms_presets": q, "default_payment_terms": "報價付款"})
    assert _mig().up(c) is None
    assert _get(c, "estimate_terms_presets") == q and _get(c, "estimate_default_payment_terms") == "報價付款"
    assert _get(c, "quote_terms_presets") == q and _get(c, "default_payment_terms") == "報價付款", "報價單的鍵不動"


def test_migration_is_idempotent_and_never_overwrites_existing_estimate_terms():
    q = {"presets": [_preset("報價甲", "q1")], "defaultKey": "q1"}
    e = {"presets": [_preset("估價自己的", "e1")], "defaultKey": "e1"}
    c = _conn({"quote_terms_presets": q, "estimate_terms_presets": e})
    _mig().up(c)
    _mig().up(c)
    assert _get(c, "estimate_terms_presets") == e
    c2 = _conn({"quote_terms_presets": q})
    _mig().up(c2)
    snap = _get(c2, "estimate_terms_presets")
    c2.execute("UPDATE system_settings SET value_json=? WHERE key='quote_terms_presets'",
               (json.dumps({"presets": [], "defaultKey": ""}),))
    _mig().up(c2)                                             # 之後報價單改了，再跑一次也不會把估價單帶著走
    assert _get(c2, "estimate_terms_presets") == snap == q


def test_migration_creates_nothing_when_the_quote_side_was_never_set():
    c = _conn({})
    assert _mig().up(c) is None
    assert _get(c, "estimate_terms_presets") is None and _get(c, "estimate_default_payment_terms") is None


def test_migration_reports_a_missing_table_instead_of_crashing():
    assert isinstance(_mig().up(sqlite3.connect(":memory:")), str)


def test_migration_is_registered_on_the_case_module():
    from modules.case import MODULE
    versions = [v for v, _fn in MODULE.migrations]
    assert 11 in versions and versions == sorted(versions)


# ── 3. 送審重算的比對基準依單據類型 ───────────────────────────────

def _data(doc_type=None, **over):
    from modules.case.quote_terms import DEFAULT_TERMS
    d = {"customerName": "條款客戶", "projectName": "條款專案", "salesPerson": "", "quoteDate": "2026-11-13",
         "validDays": 30, "taxRate": 5, "showDiscount": False, "discount": 0,
         "tot": {"total": 1050, "pretax": 1000, "directMarginPct": 0, "netMarginPct": 0},
         "items": [{"description": "品項 A", "qty": 1, "cost": 700, "margin": 0.35, "unitPrice": 1150, "amount": 1150}],
         "approval": {"status": "pending"}}
    d.update(DEFAULT_TERMS)
    if doc_type:
        d["docType"] = doc_type
    d.update(over)
    return d


def _same_as(preset, **over):
    d = {k: preset[k] for k in _TERM_FIELDS}
    d.update(over)
    return d


def _reasons(quote_no):
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    finally:
        conn.close()
    return json.loads(row["data_json"])["approval"]["reasons"]


def _terms_reasons(quote_no):
    return [r for r in _reasons(quote_no) if "報價條件已修改" in r]


@pytest.fixture
def seller(client, make_user):
    _set_empty_approval_flow()
    u, p = make_user(username="est_terms_seller", role="admin")
    return _login(client, u, p)


def _create(client, h, data, status="待審核"):
    r = client.post("/api/quotations", headers=h, json={"status": status, "data": data})
    assert r.status_code == 201, r.text
    return r.json()["quote_no"]


def test_each_doc_type_is_compared_against_its_own_preset_group(client, seller):
    qp = _preset("共用名", "p1", afterSales="報價版售後")
    ep = _preset("共用名", "p1", afterSales="估價版售後")
    _put_setting("quote_terms_presets", {"presets": [qp], "defaultKey": ""})
    _put_setting("estimate_terms_presets", {"presets": [ep], "defaultKey": ""})
    q_ok = _create(client, seller, _data(termsPresetKey="p1", **_same_as(qp)))
    e_ok = _create(client, seller, _data("estimate", termsPresetKey="p1", **_same_as(ep)))
    assert _terms_reasons(q_ok) == [], "報價單內容＝報價單那組 ⇒ 不算改過"
    assert _terms_reasons(e_ok) == [], "估價單內容＝估價單那組 ⇒ 不算改過"
    # 交叉：報價單拿估價版文字 ⇒ 與報價那組不同；估價單拿報價版文字 ⇒ 與估價那組不同
    q_bad = _create(client, seller, _data(termsPresetKey="p1", **_same_as(ep)))
    e_bad = _create(client, seller, _data("estimate", termsPresetKey="p1", **_same_as(qp)))
    assert "報價條件已修改，與條款組「共用名」不同（售後服務及備註說明）" in _reasons(q_bad)
    assert "報價條件已修改，與條款組「共用名」不同（售後服務及備註說明）" in _reasons(e_bad)


def test_estimate_default_payment_terms_are_its_own_baseline(client, seller):
    _put_setting("default_payment_terms", "報價付款基準")
    _put_setting("estimate_default_payment_terms", "估價付款基準")
    q_ok = _create(client, seller, _data(paymentTerms="報價付款基準"))
    e_ok = _create(client, seller, _data("estimate", paymentTerms="估價付款基準"))
    e_bad = _create(client, seller, _data("estimate", paymentTerms="報價付款基準"))
    q_bad = _create(client, seller, _data(paymentTerms="估價付款基準"))
    assert _terms_reasons(q_ok) == [] and _terms_reasons(e_ok) == []
    assert "報價條件已修改，非預設內容（付款條件）" in _reasons(e_bad), "估價單拿報價單的付款文字 ⇒ 與估價單的預設不同"
    assert "報價條件已修改，非預設內容（付款條件）" in _reasons(q_bad), "報價單拿估價單的付款文字 ⇒ 與報價單的預設不同"


def test_changing_doc_type_in_a_put_cannot_pick_the_other_baseline(client, seller):
    qp = _preset("共用名", "p1", afterSales="報價版售後")
    ep = _preset("共用名", "p1", afterSales="估價版售後")
    _put_setting("quote_terms_presets", {"presets": [qp], "defaultKey": ""})
    _put_setting("estimate_terms_presets", {"presets": [ep], "defaultKey": ""})
    qn = _create(client, seller, _data(termsPresetKey="p1", **_same_as(ep)), status="草稿")      # 資料庫裡是報價單
    body = _data("estimate", termsPresetKey="p1", **_same_as(ep))                              # 內容符合「估價版」，卻謊稱類型
    r = client.put("/api/quotations/" + qn, headers=seller, json={"status": "待審核", "data": body})
    assert r.status_code == 200, r.text
    assert "報價條件已修改，與條款組「共用名」不同（售後服務及備註說明）" in _reasons(qn), \
        "類型以資料庫現值（報價單）為準 ⇒ 仍與報價那組比、算不同"


def test_a_real_estimate_submitted_by_put_uses_the_estimate_baseline(client, seller):
    qp = _preset("共用名", "p1", afterSales="報價版售後")
    ep = _preset("共用名", "p1", afterSales="估價版售後")
    _put_setting("quote_terms_presets", {"presets": [qp], "defaultKey": ""})
    _put_setting("estimate_terms_presets", {"presets": [ep], "defaultKey": ""})
    en = _create(client, seller, _data("estimate", termsPresetKey="p1", **_same_as(ep)), status="草稿")
    r = client.put("/api/quotations/" + en, headers=seller,
                   json={"status": "待審核", "data": _data("estimate", termsPresetKey="p1", **_same_as(ep))})
    assert r.status_code == 200, r.text
    assert _terms_reasons(en) == []


# ── 4. 舊估價單資料不變 ──────────────────────────────────────────

def test_saved_estimates_keep_their_own_terms_text_when_settings_change(client, sa, seller):
    ea = _create(client, seller, _data("estimate", deliveryTerms="這張估價單自己的交貨條件"))
    import db

    def _stored():
        conn = db.get_db()
        try:
            return conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (ea,)).fetchone()["data_json"]
        finally:
            conn.close()
    before = _stored()
    assert client.put("/api/settings/estimate-terms-presets", headers=sa,
                      json={"presets": [_preset("新組", "n1")], "defaultKey": "n1"}).status_code == 200
    assert client.put("/api/settings/estimate-payment-terms", headers=sa, json={"text": "新的估價預設付款"}).status_code == 200
    assert client.put("/api/settings/quote-terms-presets", headers=sa,
                      json={"presets": [_preset("新報價組", "n2")], "defaultKey": "n2"}).status_code == 200
    assert _stored() == before, "設定怎麼改，已存的估價單條款文字都不動"


# ── 5. 前端接線（靜態）─────────────────────────────────────────────

def _form():
    from core.source_tree import page_file
    return page_file("quotation-form.html").read_text(encoding="utf-8")


def test_form_picks_the_terms_source_by_doc_type_and_quote_urls_are_unchanged():
    s = _form()
    assert "'estimate-terms-presets' : 'quote-terms-presets'" in s
    assert "'estimate-payment-terms' : 'payment-terms'" in s
    # 沒有任何呼叫端直接寫死報價單的條款網址（都要經 _termsUrl，否則估價單會寫到報價單那組）
    code = [ln for ln in s.splitlines() if not ln.lstrip().startswith("//")]
    hard = [ln for ln in code if "settings/quote-terms-presets" in ln or "settings/payment-terms" in ln]
    assert hard == [], hard
    assert "_termsDocType: 'quote'" in s, "預設＝報價單"
    assert s.count("await this._ensureTermsDocType(") >= 3, "編輯／複製／切換類型都要換成對的那組"
    assert "_applyDefaultTermsForNew" in s
