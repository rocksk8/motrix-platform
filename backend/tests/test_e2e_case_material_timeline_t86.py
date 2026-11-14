# -*- coding: utf-8 -*-
"""瀏覽器層級：案件「執行管理 › 材料申請」的物料時間軸（T86 第 3 項）。

每個材料一列、申請→採購→到貨（＋入庫／出貨，讀得到時）；目前這一關有就地按鈕；明細欄位仍在下方；手機寬度不橫向捲動。
截圖存到 MOTRIX_SHOTS_DIR（預設系統暫存）。
"""
import json
import os
import tempfile

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._requires import requires_module  # noqa: E402

pytestmark = requires_module("case", "本檔的題打 M01（案件）的案件管理頁")

NO = "MQ-MTL-T86"


def _case():
    import db
    data = {"dealTag": "已成案", "items": [
        {"description": "網路攝影機 4MP", "brand": "Hikvision", "qty": 18, "unit": "台"},
        {"description": "NVR 錄影主機 16 路", "brand": "Dahua", "qty": 1, "unit": "台"}], "caseRecord": {"materials": [
        {"id": "ma", "name": "壁掛機櫃", "model": "9U", "qty": 1, "unit": "座", "ordered": False, "arrived": False},
        {"id": "mb", "name": "網路交換器", "model": "SG350", "qty": 4, "unit": "台", "ordered": True, "arrived": True,
         "poLink": {"key": "g:sw", "docCodes": ["PO-2611-014"], "arrivedOn": "2026-11-10"}},
    ]}}
    c = db.get_db()
    try:
        c.execute("INSERT OR REPLACE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (NO, "已送出", "時間軸客戶", "時間軸工程", 1000, 952, json.dumps(data), "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"))
        c.commit()
    finally:
        c.close()


def _shot(page, name):
    d = os.environ.get("MOTRIX_SHOTS_DIR") or os.path.join(tempfile.gettempdir(), "t86-mtl")
    try:
        os.makedirs(d, exist_ok=True)
        page.screenshot(path=os.path.join(d, name + ".png"), full_page=True)
    except Exception:  # noqa: BLE001 — 截圖只是附件；BK19 不允許寫到 repo／暫存以外時略過
        pass


def _open(live_server, make_user, e2e_browser, name, width):
    u, p = make_user(username=name, role="superadmin")
    _case()
    page = e2e_browser.new_page(viewport={"width": width, "height": 1000})
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/case-management.html?q={NO}")
    page.wait_for_selector(f"text={NO}", timeout=15000)
    page.get_by_role("button", name="執行管理").first.click()
    page.get_by_role("button", name="材料申請").first.click()
    page.locator('[data-testid="mtl-row-ma"]').wait_for(state="visible", timeout=15000)
    page.locator('[data-testid="mtl-st-mb-ship"]').wait_for(state="attached", timeout=15000)       # 物料流程摘要讀到後才有入庫／出貨關
    page.wait_for_function("() => !document.querySelector('.mtl').innerText.includes('載入中')", timeout=15000)
    return page


@pytest.mark.e2e
def test_timeline_rows_states_and_inline_actions(live_server, make_user, e2e_browser):
    page = _open(live_server, make_user, e2e_browser, "mtl_t86a", 1440)
    st = lambda m, k: page.locator(f'[data-testid="mtl-st-{m}-{k}"]')          # noqa: E731
    # 機櫃：還沒申請 ⇒ 申請是目前這一關，按鈕開請購單（案件已帶好）
    assert st("ma", "req").get_attribute("data-state") == "cur"
    assert st("ma", "po").get_attribute("data-state") == "todo"
    href = page.get_attribute('[data-testid="mtl-act-ma-req"]', "href")
    assert href == f"payment-request.html?case={NO}&type=purchase_req", href
    # 交換器：採購單已認列且已到貨 ⇒ 前三關完成、沒有按鈕
    for k in ("req", "po", "arrive"):
        assert st("mb", k).get_attribute("data-state") == "done", k
    assert "PO-2611-014" in st("mb", "po").inner_text() and "2026-11-10" in st("mb", "arrive").inner_text()
    for k in ("req", "po", "arrive"):
        assert page.locator(f'[data-testid="mtl-act-mb-{k}"]').count() == 0, k       # 已完成的關卡沒有按鈕
    assert st("mb", "stock").get_attribute("data-state") == "cur" and "尚無入庫紀錄" in st("mb", "stock").inner_text()
    assert st("mb", "ship").get_attribute("data-state") == "todo"                 # 已到貨、尚無出貨單：出貨關可直接開單
    assert page.locator('[data-testid="mtl-act-mb-ship"]').inner_text() == "開出貨單"
    assert "已到貨 1" in page.locator('[data-testid="mtl-sum"]').inner_text()
    # 明細欄位仍在（原本的材料卡）
    assert page.locator('[data-testid="mat-ordered"]').count() == 2
    _shot(page, "desktop")


@pytest.mark.e2e
def test_timeline_phone_width_has_no_horizontal_scroll(live_server, make_user, e2e_browser):
    page = _open(live_server, make_user, e2e_browser, "mtl_t86b", 390)
    assert page.locator('[data-testid="mtl-st-ma-req"]').is_visible()
    over = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert over <= 1, "手機寬度頁面不可橫向捲動（超出 %s px）" % over
    _shot(page, "mobile390")


@pytest.mark.e2e
@pytest.mark.parametrize("width", [1440, 390])
def test_material_flow_page_is_a_summary_that_points_back_into_the_case(live_server, make_user, e2e_browser, width):
    """第 3、26 項：摘要頁帶回案件；有「申請→採購→到貨→入庫→出貨」進度條；沒有 #app-topbar／data-no-topbar 的 console 錯誤。"""
    u, p = make_user(username="mtl_t86c%d" % width, role="superadmin")
    _case()
    page = e2e_browser.new_page(viewport={"width": width, "height": 900})
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/material-flow.html?q={NO}")
    page.locator('[data-testid="mf-cell-call"]').wait_for(state="visible", timeout=15000)
    assert page.get_attribute('[data-testid="mf-open-case"]', "href") == f"case-management.html?q={NO}&tab=exec&sub=materials"
    assert page.locator(".mf-go").count() == 0, "各格不再各自帶往不同的相關頁面"
    bar = page.locator('[data-testid="mf-bar"]')
    bar.wait_for(state="visible", timeout=10000)
    labels = [t.strip() for t in bar.locator(".mf-bar__lb").all_inner_texts()]
    assert labels[:3] == ["申請", "採購", "到貨"], labels
    assert set(labels) <= {"申請", "採購", "到貨", "入庫", "出貨"}
    xs = [e.bounding_box()["x"] for e in bar.locator(".mf-bar__st").all()]
    assert xs == sorted(xs), "進度條要橫向由左到右"
    assert page.locator("#app-topbar").count() == 1
    page.wait_for_timeout(500)
    assert not [e for e in errors if "topbar" in e or "data-no-topbar" in e], errors
    over = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert over <= 1, "頁面不可橫向捲動（超出 %s px）" % over
    _shot(page, "item26_material_flow_%d" % width)


@pytest.mark.e2e
@pytest.mark.parametrize("width", [1440, 390])
def test_import_from_quote_dialog_is_centered_with_aligned_rows(live_server, make_user, e2e_browser, width):
    """第 12、24 項：視窗置中（手機不超出螢幕）；勾選框、品名、數量同一列；數量欄靠右對齊；主要按鈕用主色。"""
    page = _open(live_server, make_user, e2e_browser, "mtl_t86d%d" % width, width)
    page.get_by_role("button", name="從報價單匯入").first.click()
    box = page.locator('[data-testid="import-modal"] .imp-box')
    box.wait_for(state="visible", timeout=10000)
    vp = page.viewport_size
    b = box.bounding_box()
    assert abs((b["x"] + b["width"] / 2) - vp["width"] / 2) <= 4, "視窗要水平置中"
    assert abs((b["y"] + b["height"] / 2) - vp["height"] / 2) <= 4, "視窗要垂直置中"
    rows = [page.locator(f'[data-testid="import-row-{i}"]') for i in (0, 1)]
    for r in rows:
        cb, nm = r.locator("input").bounding_box(), r.locator(".imp-name").bounding_box()
        assert abs((cb["y"] + cb["height"] / 2) - (nm["y"] + nm["height"] / 2)) <= 4, "勾選框與品名要同一列"
    q0, q1 = (r.locator(".imp-qty").bounding_box() for r in rows)
    assert abs((q0["x"] + q0["width"]) - (q1["x"] + q1["width"])) <= 1, "數量欄右緣要對齊"
    assert page.locator('[data-testid="import-confirm"]').is_enabled()
    bb = box.bounding_box()
    assert bb["x"] >= 0 and bb["x"] + bb["width"] <= width + 1, "視窗不可超出螢幕：%s" % bb
    paint = page.evaluate("""() => { const p = document.createElement('i'); p.style.background = 'var(--accent)'; document.body.appendChild(p); const a = getComputedStyle(p).backgroundColor; p.remove();
        return [getComputedStyle(document.querySelector('[data-testid=import-confirm]')).backgroundColor, a] }""")
    assert paint[0] == paint[1], "確認鈕要用主色：%s" % paint
    ok = page.locator('[data-testid="import-confirm"]').bounding_box()
    assert ok["height"] >= (38 if width == 390 else 24), ok
    over = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert over <= 1, "頁面不可橫向捲動（超出 %s px）" % over
    _shot(page, "item12_24_import_dialog_%d" % width)
    page.locator('[data-testid="import-confirm"]').click()
    page.locator('[data-testid="mtl-row-ma"]').wait_for(state="visible")
    assert page.locator('[data-testid^="mtl-row-"]').count() >= 4, "匯入的品項進入時間軸"


@pytest.mark.e2e
@pytest.mark.parametrize("width", [1440, 390])
def test_stage_fields_look_editable_and_ratio_hint_is_one_line(live_server, make_user, e2e_browser, width):
    """第 13 項：階段名稱有邊框與底色；收入比例提示是 12px、單行（含圖示）。"""
    u, p = make_user(username="mtl_t86e%d" % width, role="superadmin")
    _case()
    page = e2e_browser.new_page(viewport={"width": width, "height": 1000})
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/case-management.html?q={NO}")
    page.wait_for_selector(f"text={NO}", timeout=15000)
    page.get_by_role("button", name="執行管理").first.click()
    name = page.locator("input.stage-name").first
    name.wait_for(state="visible", timeout=15000)
    css = name.evaluate("e => { const s = getComputedStyle(e); return [s.borderTopWidth, s.borderTopStyle, s.backgroundColor] }")
    assert css[0] != "0px" and css[1] == "solid" and css[2] != "rgba(0, 0, 0, 0)", css
    hint = page.locator(".stage-ratio-sum")
    hint.wait_for(state="visible", timeout=10000)
    fs, h = hint.evaluate("e => [getComputedStyle(e).fontSize, e.getBoundingClientRect().height]")
    assert fs == "12px" and h <= 24, (fs, h)
    over = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert over <= 1, "頁面不可橫向捲動（超出 %s px）" % over
    _shot(page, "stage_fields_%d" % width)


@pytest.mark.e2e
def test_shipping_tab_has_an_add_entry_and_timeline_leads_to_the_same_place(live_server, make_user, e2e_browser):
    """T86-25：出貨單分頁空狀態有「新增出貨單」；時間軸的「開出貨單」開同一個新增視窗；不能建的人看到說明並被帶到分頁。"""
    page = _open(live_server, make_user, e2e_browser, "t86_ship_admin", 1440)
    page.locator('[data-testid="mtl-act-mb-ship"]').click()
    page.wait_for_function("() => Alpine.$data(document.querySelector('[x-data]')).showShippingModal === true", timeout=10000)
    assert page.evaluate("() => Alpine.$data(document.querySelector('[x-data]')).activeTab") == "shipping"
    page.evaluate("() => { const d = Alpine.$data(document.querySelector('[x-data]')); d.showShippingModal = false }")
    page.locator('[data-testid="ship-empty"]').wait_for(state="visible", timeout=10000)
    assert page.locator('[data-testid="ship-empty-new"]').is_visible()
    assert page.locator('[data-testid="ship-new"]').is_visible()
    assert not page.locator('[data-testid="ship-empty-hint"]').is_visible()
    page.locator('[data-testid="ship-empty-new"]').click()
    page.wait_for_function("() => Alpine.$data(document.querySelector('[x-data]')).showShippingModal === true", timeout=10000)
    _shot(page, "item25_ship_empty_desktop")
    page.evaluate("() => { const d = Alpine.$data(document.querySelector('[x-data]')); d.showShippingModal = false; d.session.role = 'sales' }")
    page.locator('[data-testid="ship-empty-new"]').wait_for(state="hidden", timeout=5000)      # x-show 隔一個影格才更新
    page.locator('[data-testid="ship-empty-hint"]').wait_for(state="visible", timeout=5000)
    page.evaluate("() => { Alpine.$data(document.querySelector('[x-data]')).activeTab = 'exec' }")
    page.locator('[data-testid="mtl-act-mb-ship"]').wait_for(state="visible", timeout=10000)
    assert page.locator('[data-testid="mtl-act-mb-ship"]').inner_text().strip() == "前往出貨單"


@pytest.mark.e2e
@pytest.mark.parametrize("width", [1440, 390])
def test_stage_card_fits_the_screen_in_two_rows_on_phone(live_server, make_user, e2e_browser, width):
    """T86-17：手機階段卡右側不被切掉——名稱一行、比例／完成日／負責人／狀態一行；前往日期／人次／工作內容欄位有邊框。桌面維持單列。"""
    u, p = make_user(username="mtl_t86s%d" % width, role="superadmin")
    _case()
    page = e2e_browser.new_page(viewport={"width": width, "height": 1000})
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/case-management.html?q={NO}")
    page.wait_for_selector(f"text={NO}", timeout=15000)
    page.get_by_role("button", name="執行管理").first.click()
    card = page.locator(".stage-card").first
    card.wait_for(state="visible", timeout=15000)
    card.locator("button.btn-add", has_text="新增記錄").click()
    card.locator(".visit-row input[type=date]").first.wait_for(state="visible", timeout=10000)
    geo = card.evaluate("""c => {
      const r = c.getBoundingClientRect(), q = s => c.querySelector(s).getBoundingClientRect()
      const head = [...c.querySelector('.stage-card__head').querySelectorAll('.stage-name, [data-testid=stage-ratio], .stage-toggle-detail, .btn-del')]
      return {right: r.right, left: r.left, items: head.map(e => e.getBoundingClientRect().right), nameTop: q('.stage-name').top, ratioTop: q('[data-testid=stage-ratio]').top,
              scroll: c.querySelector('.stage-card__head').scrollWidth - c.querySelector('.stage-card__head').clientWidth}
    }""")
    assert all(x <= geo["right"] + 1 for x in geo["items"]), "階段卡右側被切掉：%s" % geo
    assert geo["scroll"] <= 1, geo
    if width == 390:
        assert geo["ratioTop"] > geo["nameTop"] + 10, "手機應分兩行：%s" % geo
    else:
        assert abs(geo["ratioTop"] - geo["nameTop"]) < 20, "桌面維持單列：%s" % geo
    for sel in ("input[type=date]", "input[type=number]", "textarea"):
        b = card.locator(".visit-row " + sel).first.evaluate("e => { const s = getComputedStyle(e); return [s.borderTopWidth, s.borderTopStyle] }")
        assert b[0] != "0px" and b[1] == "solid", (sel, b)
    over = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert over <= 1, "頁面不可橫向捲動（超出 %s px）" % over
    _shot(page, "item17_stage_card_%d" % width)


_D = "Alpine.$data(document.querySelector('[x-data]'))"


@pytest.mark.e2e
def test_review_fixes_batch1_arrival_pending_no_access_and_single_load(live_server, make_user, e2e_browser):
    """h5／h11 審查回修：①PO 連結的「確認到貨」只標記未存檔⇒顯示待儲存＋提示 ②材料申請讀不到⇒「—／無權限」③?sub=materials 在時間軸旗標開時也落在材料申請，且材料申請清單只讀一次。"""
    u, p = make_user(username="mtl_t86fix", role="superadmin")
    _case()
    page = e2e_browser.new_page(viewport={"width": 1440, "height": 1000})
    loads = []
    page.on("request", lambda r: loads.append(r.url) if r.method == "GET" and "/material-orders" in r.url and "/material-orders-" not in r.url and "approvals" not in r.url and "payments" not in r.url and "suppliers" not in r.url else None)
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/case-management.html?q={NO}&sub=materials")
    page.locator('[data-testid="mtl-row-ma"]').wait_for(state="visible", timeout=20000)
    page.wait_for_function("() => !document.querySelector('.mtl').innerText.includes('載入中')", timeout=15000)
    page.wait_for_timeout(500)
    assert len(loads) == 1, "材料申請清單只該讀一次：%s" % loads
    # ① PO 連結、未到貨 → 確認到貨 → 待儲存
    page.evaluate("() => { const m = %s.cr.caseRecord.materials.find(x => x.id === 'mb'); m.arrived = false; m.ordered = true }" % _D)
    page.locator('[data-testid="mtl-act-mb-arrive"]').click()
    assert "待儲存" in page.locator('[data-testid="mtl-st-mb-arrive"]').inner_text()
    page.get_by_text("已標記到貨，請按「儲存」").first.wait_for(state="visible", timeout=5000)
    # ② 讀不到材料申請（403／404）
    page.evaluate("() => { %s.materialOrders = []; %s.moNoAccess = true }" % (_D, _D))
    st = page.locator('[data-testid="mtl-st-ma-req"]')
    assert "無權限" in st.inner_text()
    assert page.locator('[data-testid="mtl-act-ma-req"]').count() == 0


@pytest.mark.e2e
def test_ratio_warning_wraps_on_phone_instead_of_truncating(live_server, make_user, e2e_browser):
    """審查回修：收入比例合計不等於 100% 的警示句在手機要換行顯示完整，不能被截成「…」。"""
    u, p = make_user(username="mtl_t86warn", role="superadmin")
    _case()
    page = e2e_browser.new_page(viewport={"width": 390, "height": 900})
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/case-management.html?q={NO}")
    page.wait_for_selector(f"text={NO}", timeout=15000)
    page.get_by_role("button", name="執行管理").first.click()
    page.locator(".stage-card").first.wait_for(state="visible", timeout=15000)
    page.evaluate("() => { const s = %s.cr.caseRecord.stages; s[0].ratioBp = 6000 }" % _D)
    hint = page.locator(".stage-ratio-sum--warn")
    hint.wait_for(state="visible", timeout=5000)
    txt = page.locator('[data-testid="stage-ratio-summary"]')
    assert txt.evaluate("e => e.scrollWidth <= e.clientWidth + 1"), "警示句被截斷"
    assert "不等於 100%" in txt.inner_text()
    assert hint.bounding_box()["height"] > 20, "手機應換成多行"
    _shot(page, "review_ratio_warn_390")


@pytest.mark.e2e
def test_pending_arrival_mark_is_cleared_after_save(live_server, make_user, e2e_browser):
    """審查 nit：存檔後「待儲存」標記清掉，之後別的編輯讓 dirty 再變 true 也不會回來。"""
    page = _open(live_server, make_user, e2e_browser, "t86_pend", 1440)
    page.evaluate("() => { const m = %s.cr.caseRecord.materials.find(x => x.id === 'mb'); m.arrived = false; m.ordered = true }" % _D)
    page.locator('[data-testid="mtl-act-mb-arrive"]').click()
    assert "待儲存" in page.locator('[data-testid="mtl-st-mb-arrive"]').inner_text()
    page.evaluate("() => { const d = %s; d.dirty = false }" % _D)            # 模擬存檔成功
    page.evaluate("() => { const d = %s; d.dirty = true }" % _D)             # 之後別的編輯
    page.wait_for_timeout(300)
    assert "待儲存" not in page.locator('[data-testid="mtl-st-mb-arrive"]').inner_text()


@pytest.mark.e2e
def test_material_detail_is_collapsed_by_default_and_expands_in_the_row(live_server, make_user, e2e_browser):
    """h3 複測尾巴：每個材料的明細欄位預設收合在時間軸那一列下面，按「明細」展開／收合；「新增品項」的新列直接展開。"""
    page = _open(live_server, make_user, e2e_browser, "t86_collapse", 1440)
    card = page.locator('[data-testid="mat-card-ma"]')
    assert not card.is_visible(), "明細預設收合"
    more = page.locator('[data-testid="mtl-more-ma"]')
    assert more.inner_text().startswith("明細")
    more.click()
    card.wait_for(state="visible", timeout=5000)
    assert card.locator('input[placeholder="品名"]').input_value() == "壁掛機櫃"
    assert page.locator('[data-testid="mat-card-mb"]').is_visible() is False, "只展開按的那一列"
    more.click()
    card.wait_for(state="hidden", timeout=5000)
    page.get_by_role("button", name="新增品項").first.click()
    newc = page.locator('.mat-card:visible')
    newc.first.wait_for(state="visible", timeout=5000)
    assert newc.count() == 1 and newc.first.locator('input[placeholder="品名"]').input_value() == ""


@pytest.mark.e2e
def test_open_buttons_do_not_touch_the_subtab_underline_on_phone(live_server, make_user, e2e_browser):
    """h3 複測尾巴：390 寬時「開請購單／開採購單」按鈕與子頁籤底線之間要有間距。"""
    u, p = make_user(username="t86_opbar", role="superadmin")
    _case()
    page = e2e_browser.new_page(viewport={"width": 390, "height": 900})
    inject_login(page, live_server, u, p)
    page.goto(f"{live_server}/pages/case-management.html?q={NO}&sub=materials")
    bar = page.locator('[data-testid="op-open-bar"]')
    bar.wait_for(state="visible", timeout=20000)
    tabs_bottom = page.get_by_role("button", name="材料申請").first.evaluate("e => e.parentElement.getBoundingClientRect().bottom")
    assert bar.bounding_box()["y"] - tabs_bottom >= 8, "按鈕貼著子頁籤"
    assert bar.evaluate("e => getComputedStyle(e).display") == "flex"
    _shot(page, "tail_openbar_390")
