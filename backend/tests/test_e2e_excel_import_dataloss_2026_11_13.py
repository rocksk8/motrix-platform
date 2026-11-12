# -*- coding: utf-8 -*-
"""客戶頁／料號頁「匯入 Excel」毀損資料的回歸題（票 fix/excel-import-dataloss；審查發現見 docs/platform/plans/IMPORT-WIZARD-PROPOSAL.md §0-1）。

舊行為（修之前，這些題要是紅的）：
- 客戶：更新既有客戶時 PUT 整包覆蓋 data_json ⇒ 拜訪紀錄 visits、別名、聯絡人、標籤全部消失；名稱相同就當同一家（同名不同公司被併成一筆）。
- 料號：空白儲存格被預設值覆蓋（成本 0、單位「台」）；只給「廠牌」時既有「型號」被洗掉；安全庫存、前置天數無法匯入。
- 每一列都觸發一次整表雲端備份。

新規則：空白儲存格＝不更新；統編相同才算同一家（只有名稱相同＝可能重複，列出、不合併、不匯入）；
匯入前顯示確認（新增／更新／可能重複幾筆）；同一次匯入只備份一次。
"""
import json
import time

import pytest

_MAKE_USER_DEFAULT_ROLE = "superadmin"

pytestmark = pytest.mark.e2e

CUSTOMER_COLS = ["公司名稱", "統一編號", "電話", "備註", "產業別", "主要聯絡人"]
PART_COLS = ["料號", "品名", "廠牌", "型號", "單位", "成本(未稅)", "定價(含稅)", "類別", "備註", "安全庫存", "前置天數"]


def _xlsx(path, header, rows):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header)
    for r in rows:
        ws.append(r)
    wb.save(str(path))
    return str(path)


def _hdr(token):
    return {"Authorization": "Bearer " + token}


@pytest.fixture()
def env(client, live_server, make_user, new_context, login_as):
    pytest.importorskip("playwright.sync_api")
    u = make_user(username="imp_admin")
    sess = None
    ctx = new_context()
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    sess = login_as(ctx, u)
    return {"client": client, "page": page, "base": live_server, "h": _hdr(sess["token"]), "errors": errors}


_CLICKED = {"ok": False}


def _confirm_if_shown(page, wait_ms=4000):
    """新版會先在匯入視窗內顯示確認（import-confirm-*）；舊版沒有。回傳確認摘要文字（沒有＝None）。"""
    try:
        page.wait_for_selector('[data-testid="import-confirm-ok"]', timeout=wait_ms)
    except Exception:                                                  # noqa: BLE001 — 沒跳＝舊行為
        return None
    txt = page.locator('[data-testid="import-confirm-summary"]').inner_text()
    _CLICKED["ok"] = page.locator('[data-testid="import-confirm-ok"]').is_enabled()
    if _CLICKED["ok"]:                                                     # 沒有任何可匯入的列時按鈕停用，畫面停在確認清單
        page.click('[data-testid="import-confirm-ok"]')
    return txt


def _import(env, page_name, path, confirm=True):
    page = env["page"]
    page.goto(env["base"] + "/pages/%s.html" % page_name)
    page.wait_for_selector('input[type="file"][accept*="xlsx"]', state="attached")
    page.wait_for_load_state("networkidle")
    page.set_input_files('input[type="file"][accept*="xlsx"]', path)
    txt = _confirm_if_shown(page) if confirm else None
    if txt is None or _CLICKED["ok"]:
        page.get_by_text("失敗", exact=True).first.wait_for(timeout=20000)      # 結果面板的「失敗」格
    return txt


def _mk_customer(env, name, tax="", **data):
    r = env["client"].post("/api/customers", json={"name": name, "tax_id": tax, "phone": data.pop("phone", ""), "data": data}, headers=env["h"])
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _customers(env):
    r = env["client"].get("/api/customers", headers=env["h"])
    assert r.status_code == 200, r.text
    return r.json()


def _by_tax(env, tax):
    return [c for c in _customers(env) if c.get("taxId") == tax]


# ── 客戶 ─────────────────────────────────────────────────────────────

def test_customer_update_merges_and_keeps_visits_alias_contacts_tags(env, tmp_path):
    cid = _mk_customer(env, "既有科技", "12345678", alias="既有", tags=["VIP"], industry="資訊",
                       contacts=[{"id": 1, "name": "王小明", "phone": "02-1111"}], notes="原備註", active=True)
    visits = [{"id": 7, "date": "2026-10-01", "note": "拜訪過"}]
    r = env["client"].patch("/api/customers/%d/visits" % cid, json={"visits": visits}, headers=env["h"])
    assert r.status_code == 200, r.text
    path = _xlsx(tmp_path / "c.xlsx", CUSTOMER_COLS, [["既有科技", "12345678", "02-9999", "", "", ""]])
    _import(env, "customers", path)
    c = _by_tax(env, "12345678")
    assert len(c) == 1, "統編相同必須更新同一筆，不可新增"
    c = c[0]
    assert c["phone"] == "02-9999", "檔案有給的欄位要更新"
    assert c.get("visits") == visits, "拜訪紀錄被抹掉了（舊行為）"
    assert c.get("alias") == "既有" and c.get("tags") == ["VIP"], "別名／標籤被抹掉了"
    assert [x["name"] for x in c.get("contacts") or []] == ["王小明"], "聯絡人被抹掉了"
    assert c.get("notes") == "原備註" and c.get("industry") == "資訊", "空白儲存格必須代表『不更新』"
    assert c.get("active") is True


def test_customer_update_does_not_reactivate_a_deactivated_customer(env, tmp_path):
    _mk_customer(env, "停用公司", "22222222", active=False)
    path = _xlsx(tmp_path / "c.xlsx", CUSTOMER_COLS, [["停用公司", "22222222", "02-1", "", "", ""]])
    _import(env, "customers", path)
    assert _by_tax(env, "22222222")[0].get("active") is False, "匯入把停用的客戶重新啟用了"


def test_customer_name_only_match_is_listed_not_merged(env, tmp_path):
    _mk_customer(env, "同名公司", "", phone="02-0000", notes="原備註")
    _mk_customer(env, "別家同名", "33333333", phone="02-3333")
    path = _xlsx(tmp_path / "c.xlsx", CUSTOMER_COLS, [
        ["同名公司", "", "02-8888", "新備註", "", ""],             # 只有名稱相同（既有沒統編）
        ["別家同名", "44444444", "02-4444", "", "", ""],         # 名稱相同、統編不同＝可能重複
    ])
    _import(env, "customers", path)
    same = [c for c in _customers(env) if c["name"] == "同名公司"]
    assert len(same) == 1 and same[0]["phone"] == "02-0000" and same[0].get("notes") == "原備註", "名稱相同不可自動合併"
    other = [c for c in _customers(env) if c["name"] == "別家同名"]
    assert len(other) == 1 and other[0]["taxId"] == "33333333" and other[0]["phone"] == "02-3333", "名稱相同、統編不同也不可動"
    assert not _by_tax(env, "44444444"), "可能重複的列不可自動新增"
    body = env["page"].locator("body").inner_text()
    assert "可能重複" in body and "同名公司" in body, "結果裡要列出可能重複的列"


def test_customer_import_asks_for_confirmation_with_counts(env, tmp_path):
    _mk_customer(env, "舊客戶", "55555555", phone="02-5")
    _mk_customer(env, "疑似重複", "")
    path = _xlsx(tmp_path / "c.xlsx", CUSTOMER_COLS, [
        ["新客戶甲", "66666666", "", "", "", ""],
        ["新客戶乙", "77777777", "", "", "", ""],
        ["舊客戶", "55555555", "02-55", "", "", ""],
        ["疑似重複", "", "", "", "", ""],
    ])
    txt = _import(env, "customers", path)
    assert txt, "匯入前沒有顯示確認"
    assert "新增 2 筆" in txt and "更新 1 筆" in txt and "可能重複 1 筆" in txt, txt


def test_customer_cancel_at_confirmation_changes_nothing(env, tmp_path):
    path = _xlsx(tmp_path / "c.xlsx", CUSTOMER_COLS, [["不該出現", "88888888", "", "", "", ""]])
    page = env["page"]
    page.goto(env["base"] + "/pages/customers.html")
    page.wait_for_selector('input[type="file"][accept*="xlsx"]', state="attached")
    page.wait_for_load_state("networkidle")
    page.set_input_files('input[type="file"][accept*="xlsx"]', path)
    page.wait_for_selector('[data-testid="import-confirm-cancel"]', timeout=8000)
    page.click('[data-testid="import-confirm-cancel"]')
    time.sleep(0.5)
    assert not _by_tax(env, "88888888"), "按取消仍然匯入了"


def test_customer_import_triggers_one_cloud_backup_per_import(env, tmp_path, monkeypatch):
    import routers.customers as RC
    calls = []
    monkeypatch.setattr(RC, "_backup_customers", lambda *a, **k: calls.append(1))
    rows = [["批次客戶%d" % i, "9000000%d" % i, "", "", "", ""] for i in range(6)]
    path = _xlsx(tmp_path / "c.xlsx", CUSTOMER_COLS, rows)
    _import(env, "customers", path)
    time.sleep(1.0)
    assert len(_customers(env)) >= 6
    assert len(calls) <= 1, "匯入 6 筆觸發了 %d 次整表備份（應只有 1 次）" % len(calls)


# ── 料號 ─────────────────────────────────────────────────────────────

def _mk_part(env, **kw):
    body = {"partNo": "CAM-001", "name": "攝影機", "brand": "Hikvision / DS-2CD", "unit": "支", "cost": 1200, "listPrice": 2000,
            "category": "監控設備", "note": "原備註", "safetyStock": 5, "leadTimeDays": 7}
    body.update(kw)
    r = env["client"].post("/api/parts", json=body, headers=env["h"])
    assert r.status_code == 201, r.text
    return r.json()


def _part(env, part_no):
    r = env["client"].get("/api/parts", headers=env["h"])
    rows = [p for p in r.json()["items"] if p["part_no"] == part_no]
    return rows[0] if rows else None


def test_part_update_blank_cells_do_not_overwrite(env, tmp_path):
    _mk_part(env)
    path = _xlsx(tmp_path / "p.xlsx", PART_COLS, [["CAM-001", "攝影機", "Hikvision", "", "", "", 2500, "", "", "", ""]])
    _import(env, "parts", path)
    p = _part(env, "CAM-001")
    assert p["cost"] == 1200, "空白成本被清成 %s（舊行為）" % p["cost"]
    assert p["unit"] == "支", "空白單位被預設值『台』覆蓋了"
    assert p["list_price"] == 2500, "檔案有給的欄位要更新"
    assert p["note"] == "原備註" and p["category"] == "監控設備"
    assert p["safety_stock"] == 5 and p["lead_time_days"] == 7, "沒給的欄位不可動"


def test_part_update_brand_and_model_are_independent(env, tmp_path):
    _mk_part(env)
    path = _xlsx(tmp_path / "p.xlsx", PART_COLS, [["CAM-001", "攝影機", "", "DS-2CD9999", "", "", "", "", "", "", ""]])
    _import(env, "parts", path)
    assert _part(env, "CAM-001")["brand"] == "Hikvision / DS-2CD9999", "只給型號時廠牌被洗掉"
    path = _xlsx(tmp_path / "p2.xlsx", PART_COLS, [["CAM-001", "攝影機", "Dahua", "", "", "", "", "", "", "", ""]])
    _import(env, "parts", path)
    assert _part(env, "CAM-001")["brand"] == "Dahua / DS-2CD9999", "只給廠牌時既有型號被洗掉（舊行為）"


def test_part_import_reads_safety_stock_and_lead_time(env, tmp_path):
    _mk_part(env)
    path = _xlsx(tmp_path / "p.xlsx", PART_COLS, [
        ["CAM-001", "攝影機", "", "", "", "", "", "", "", 9, 14],                       # 更新
        ["NET-NEW", "新交換器", "", "", "個", 100, 150, "網通設備", "", 3, ""],         # 新增；前置天數空白＝未知
    ])
    _import(env, "parts", path)
    p = _part(env, "CAM-001")
    assert p["safety_stock"] == 9 and p["lead_time_days"] == 14, "安全庫存／前置天數沒有匯入"
    n = _part(env, "NET-NEW")
    assert n and n["safety_stock"] == 3 and n["unit"] == "個" and n["cost"] == 100
    assert n["lead_time_days"] is None, "空白前置天數必須是未知（NULL），不是 0"


def test_part_non_numeric_cost_is_rejected_not_zeroed(env, tmp_path):
    _mk_part(env)
    path = _xlsx(tmp_path / "p.xlsx", PART_COLS, [["CAM-001", "攝影機", "", "", "", "abc", "", "", "", "", ""]])
    _import(env, "parts", path)
    assert _part(env, "CAM-001")["cost"] == 1200, "亂碼成本被當成 0 寫入"


def test_part_import_asks_for_confirmation_with_counts(env, tmp_path):
    _mk_part(env)
    path = _xlsx(tmp_path / "p.xlsx", PART_COLS, [
        ["CAM-001", "攝影機", "", "", "", "", "", "", "", "", ""],
        ["NEW-001", "新料一", "", "", "", "", "", "", "", "", ""],
        ["NEW-002", "新料二", "", "", "", "", "", "", "", "", ""],
    ])
    txt = _import(env, "parts", path)
    assert txt, "匯入前沒有顯示確認"
    assert "新增 2 筆" in txt and "更新 1 筆" in txt, txt


def test_customer_same_tax_different_name_is_listed_and_written_only_when_ticked(env, tmp_path):
    _mk_customer(env, "甲公司", "12345678", phone="02-1")
    path = _xlsx(tmp_path / "c.xlsx", CUSTOMER_COLS, [["乙公司", "12345678", "02-9", "", "", ""]])
    page = env["page"]
    page.goto(env["base"] + "/pages/customers.html")
    page.wait_for_selector('input[type="file"][accept*="xlsx"]', state="attached")
    page.wait_for_load_state("networkidle")
    page.set_input_files('input[type="file"][accept*="xlsx"]', path)
    page.wait_for_selector('[data-testid="import-confirm-list"]', timeout=8000)
    body = page.locator('[data-testid="import-confirm"]').inner_text()
    assert "甲公司" in body and "乙公司" in body, "要把系統裡的舊名稱與檔案的新名稱並排顯示"
    assert page.locator('[data-testid="import-confirm-ok"]').is_disabled(), "沒勾選、也沒有其他可匯入的列時不可確認"
    page.check('[data-testid="import-confirm-tick-2"]')
    page.click('[data-testid="import-confirm-ok"]')
    page.get_by_text("失敗", exact=True).first.wait_for(timeout=20000)
    c = _by_tax(env, "12345678")[0]
    assert c["name"] == "甲公司" and c["phone"] == "02-9"
