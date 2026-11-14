# -*- coding: utf-8 -*-
"""T87 B1：畫面提示不是權限邊界（PM 2026-11-14）。只有「業務開發」權限的業務：

① 報表中心背後的既有端點（/api/reports/*、/api/report-templates/*）一律 403——標準報表開放給他，不等於這些也開了。
② 標準報表的金額報表（營收、毛利、應收帳齡）資料與匯出端點 403；目錄回 available:false 與原因。
③ 正對照：標準報表目錄與業務漏斗對他是 200（題目問對了——不是路徑打錯才得到非 200）。

②③ 需要後端 feat/t87-b1-be-h8 的 /api/std-reports。
🔴 略過只是「後端還沒併入」的過渡：`BACKEND_PENDING` 開著時 404 才略過；B1 前後端合到整合分支時必須改成 False
（端點不存在就直接紅，免得之後路由壞掉也被當成略過、閘門照樣綠）。`test_skip_switch_is_removed_once_backend_exists`
在路由已存在、開關還開著時會紅，逼人把它關掉。"""
import pytest

#: 既有報表端點（與 tests/platform/test_reports_money_gate_t68.py 的 11 支同一份清單的子集＋自選條件報表）
LEGACY = [
    "/api/reports/financial?period=2026-09",
    "/api/reports/ar-aging",
    "/api/reports/cash-position",
    "/api/reports/monthly-trend?months=6",
    "/api/report-templates",
    "/api/report-templates/case-list/run",
    "/api/report-templates/case-list/excel",
]

STD_MONEY = ["revenue", "gross-margin", "ar-aging"]

#: 🔴 過渡開關：h8 的 /api/std-reports 併入整合分支時改 False（見檔頭）。False ⇒ 路由不存在就紅。
BACKEND_PENDING = True


def _headers(client, make_user, name, role="sales", modules=("dev_crm",)):
    u, p = make_user(name, "Conn-Pass-123", role=role, modules=list(modules), legacy_finance_flag=False)[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


@pytest.mark.parametrize("url", LEGACY)
def test_legacy_report_endpoints_still_refuse_a_dev_crm_only_account(client, make_user, url):
    h = _headers(client, make_user, "sr_b_" + str(abs(hash(url)) % 10 ** 6))
    r = client.get(url, headers=h)
    assert r.status_code == 403, (url, r.status_code, r.text[:200])


def _std_or_skip(client, h):
    r = client.get("/api/std-reports", headers=h)
    if r.status_code == 404:
        if BACKEND_PENDING:
            pytest.skip("後端 /api/std-reports 尚未合入（等 feat/t87-b1-be-h8）；併入後把 BACKEND_PENDING 改 False")
        pytest.fail("/api/std-reports 不存在（404）：標準報表後端路由壞了或沒掛上")
    return r


def test_skip_switch_is_removed_once_backend_exists(client, make_user):
    """後端已併入（路由存在）卻還留著略過開關 ⇒ 紅：略過不能永久留著。"""
    h = _headers(client, make_user, "sr_b_switch")
    exists = client.get("/api/std-reports", headers=h).status_code != 404
    assert not (exists and BACKEND_PENDING), "後端 /api/std-reports 已存在：請把 BACKEND_PENDING 改成 False（拿掉略過）"


def test_positive_control_catalog_and_funnel_are_open_to_dev_crm_only(client, make_user):
    h = _headers(client, make_user, "sr_b_pos")
    r = _std_or_skip(client, h)
    assert r.status_code == 200, r.text[:200]
    by = {x["id"]: x for x in r.json()["reports"]}
    assert by["sales-funnel"]["available"] is True
    f = client.get("/api/std-reports/sales-funnel", headers=h)
    assert f.status_code == 200, f.text[:200]


@pytest.mark.parametrize("rid", STD_MONEY)
def test_money_reports_are_refused_for_dev_crm_only_on_data_excel_and_pdf(client, make_user, rid):
    h = _headers(client, make_user, "sr_b_m_" + rid.replace("-", "_"))
    cat = _std_or_skip(client, h)
    by = {x["id"]: x for x in cat.json()["reports"]}
    assert by[rid]["available"] is False and by[rid].get("reason"), by.get(rid)
    for suffix in ("", "/excel", "/pdf"):
        r = client.get("/api/std-reports/%s%s" % (rid, suffix), headers=h)
        assert r.status_code == 403, (rid, suffix, r.status_code)


def test_funnel_money_is_masked_for_an_account_without_financial_view(client, make_user):
    """沒有金額檢視權限：漏斗件數照給，預估金額一律 null（不是 0）。"""
    h = _headers(client, make_user, "sr_b_mask")
    _std_or_skip(client, h)
    j = client.get("/api/std-reports/sales-funnel", headers=h).json()
    assert j["moneyMasked"] is True
    assert all(d["amount"] is None for d in j["funnel"]["dev"]), j["funnel"]["dev"]
