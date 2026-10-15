# -*- coding: utf-8 -*-
"""T63 F4：請款單款項類別的代碼清單單一來源（helpers/option_lists.BUILTIN["payment_request_stage"]）。
- 驗證集合 PAYMENT_STAGES、PDF 後備字 _PAYMENT_STAGE_LABELS 由它衍生（內容、順序與今天相同）；
- 前端後備 STAGES 逐項等於後端預設（漂移守門）；案件款項期別 STAGE_ITEMS 同樣鎖定等於 payment_stage 預設；
- 新端點 GET /api/payment-requests/stages 在 /{request_no} 之前註冊、需登入、只回代碼與名稱；
- 表單：舊值／未知代碼多畫一顆按鈕的邏輯（純函式式抽出驗證）。
純靜態／函式層，無資料庫、不需 node；端點本身的回應題需要 client（最後一題）。"""
import re
from pathlib import Path

import pytest

from core.source_tree import page_file
from helpers import option_lists as OL

BACKEND = Path(__file__).resolve().parents[1]
FRONT = BACKEND.parent / "frontend"
TODAY = [("full", "全額"), ("deposit", "訂金款"), ("delivery", "交貨款"), ("acceptance", "驗收款"), ("final", "尾款")]


def test_single_source_equals_todays_hard_coded_list():
    assert [(d["value"], d["label"]) for d in OL.request_stage_defaults()] == TODAY
    assert OL.request_stage_codes() == tuple(k for k, _ in TODAY)
    assert list(OL.request_stage_names().items()) == TODAY


def test_validation_set_and_pdf_fallback_are_derived_from_it():
    from modules.arap.api import payment_requests as PR
    import pdf_gen
    assert list(PR.PAYMENT_STAGES.items()) == TODAY
    assert list(pdf_gen._PAYMENT_STAGE_LABELS.items()) == TODAY


def test_no_second_hard_coded_code_set_in_backend():
    for rel in ("modules/arap/api/payment_requests.py", "pdf_gen.py"):
        src = (BACKEND / rel).read_text(encoding="utf-8")
        assert '"acceptance": "驗收款"' not in src and '"acceptance":' not in src, rel + " 又有一份寫死的代碼清單"


def _html():
    return page_file("payment-request-form.html").read_text(encoding="utf-8")


def test_frontend_fallback_equals_backend_defaults():
    m = re.search(r"STAGES: \[(.*?)\],\s*\n", _html(), re.S)
    assert m, "找不到前端後備 STAGES"
    got = re.findall(r"value: '([^']+)',\s*label: '([^']+)'", m.group(1))
    assert got == TODAY


def test_case_payment_stage_fallback_equals_its_backend_default():
    src = (FRONT / "js" / "case-management-core.js").read_text(encoding="utf-8")
    m = re.search(r"STAGE_ITEMS: \[(.*?)\]\.map", src, re.S)
    assert m
    got = re.findall(r"'([^']+)'", m.group(1))
    assert got == [d["value"] for d in OL.BUILTIN["payment_stage"]["defaults"]]


def test_form_uses_the_endpoint_and_renders_unknown_current_stage():
    h = _html()
    assert "/payment-requests/stages" in h and "this.loadStages()" in h
    assert "（舊值）" in h and "base.concat([{ value: cur" in h
    # 驗證：存檔仍送原始代碼
    assert "stage: this.q.stage" in h


def test_endpoint_is_registered_before_the_dynamic_route_and_requires_login():
    src = (BACKEND / "modules/arap/api/payment_requests.py").read_text(encoding="utf-8")
    i, j = src.index('"/api/payment-requests/stages"'), src.index('"/api/payment-requests/{request_no}")')
    assert i < j
    body = src[i:src.index("@router", i + 10)]
    assert "_require_user(authorization)" in body
    assert "amount" not in body.lower() and "total" not in body.lower()


def test_endpoint_returns_defaults_when_the_option_list_is_off(client, make_user):
    u, p = make_user(username="f4_stage_sa", role="superadmin")[:2]
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    assert client.get("/api/payment-requests/stages").status_code in (401, 403)
    j = client.get("/api/payment-requests/stages", headers=h).json()
    assert [(x["value"], x["label"]) for x in j["items"]] == TODAY and j["source"] == "default"
    assert all(x["disabled"] is False for x in j["items"])
