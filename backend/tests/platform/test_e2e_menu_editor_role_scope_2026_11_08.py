"""瀏覽器層級：選單編輯器的角色層（T78）。

超管開「調整選單」→ 範圍選「角色：管理員」→ 改一個項目的名稱 → 預覽（用該角色的帳號）→ 發布；
然後：管理員登入看到角色層的名稱，別的角色（業務）仍看公司預設。面板上要看得出目前編輯的是哪一層。
不綁特定 L2：任取一個已載入、有選單項的模組；沒有 ⇒ skip 寫明。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from core import registry  # noqa: E402
from helpers import menu_builder as MB  # noqa: E402

pytestmark = pytest.mark.e2e


def _pick():
    for m in registry.loaded():
        for p in (m.manifest or {}).get("pages") or []:
            perm = (p.get("menu") or {}).get("perm") if isinstance(p, dict) else None
            if isinstance(p, dict) and p.get("menu") and not ({"cashier", "finance", "financial_view"} & set(perm if isinstance(perm, list) else [])):
                return m.key, p["path"], (list(perm) if isinstance(perm, list) else [])
    pytest.skip("沒有已載入、宣告選單項的模組 ⇒ 無對象")


def _label(client, h, key, href):
    for g in client.get("/api/platform/menu", headers=h).json()["layout"]["groups"]:
        for it in g["items"]:
            if it["href"] == href and it.get("module") == key:
                return it["label"]
    return None


def _auth(client, user):
    u, pw = user[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]}


def test_superadmin_edits_role_layer_and_only_that_role_sees_it(live_server, make_user, new_page, login_as, client, monkeypatch):
    key, href, perm = _pick()
    monkeypatch.setattr(MB, "enabled", lambda conn=None: True)
    sa = make_user(username="rse_sa", role="superadmin", modules=[])
    ad = make_user(username="rse_ad", role="admin", modules=perm)
    sl = make_user(username="rse_sl", role="sales", modules=perm)
    h_ad, h_sl = _auth(client, ad), _auth(client, sl)
    before = _label(client, h_ad, key, href)
    assert before and _label(client, h_sl, key, href) == before, "正對照：兩個角色一開始看到同一個名稱"

    page = new_page()
    login_as(page, sa)
    page.goto(f"{live_server}/index.html")
    page.wait_for_selector("[data-testid=me-open]", timeout=15000)
    page.click("[data-testid=me-open]")
    page.wait_for_selector("[data-testid=me-scope-select]")
    assert "公司預設" in page.inner_text("[data-testid=me-scope-now]"), "預設編輯公司層，且畫面上寫明"

    page.select_option("[data-testid=me-scope-select]", "role:admin")
    page.wait_for_function("() => /角色/.test(document.querySelector('[data-testid=me-scope-now]').textContent)", timeout=10000)
    now = page.inner_text("[data-testid=me-scope-now]")
    assert "管理員" in now and "角色層" in now, now
    assert "角色層 ＞ 公司層" in page.inner_text("[data-testid=me-scope]"), "要寫出套用順序"
    page.wait_for_selector("#me-panel[data-busy='0']", timeout=10000)      # 切換範圍會重讀；讀完才編輯（讀取中整個編輯區是 inert）
    page.wait_for_selector("[data-testid=me-who]", timeout=10000)
    assert page.input_value("[data-testid=me-who]") == "rse_ad", "預覽身分＝該角色的在職帳號"

    row = page.locator('#me-panel .me-i[data-id="%s:%s/sidebar"]' % (key, href))
    row.locator("input[type=text]").fill("管理員專用名")
    row.locator("input[type=text]").dispatch_event("change")
    page.click("[data-testid=me-preview-btn]")
    page.wait_for_selector("[data-testid=me-preview]", timeout=10000)
    page.click("[data-testid=me-publish]")
    # 發布完會先標 published、再重讀選單（訊息暫為「讀取中…」）、讀完才寫結果訊息——等結果訊息，不等第一個狀態
    page.wait_for_function("() => /已發布/.test((document.querySelector('#me-panel .me-msg') || {}).textContent || '')", timeout=15000)
    assert "角色層" in page.inner_text("#me-panel .me-msg")

    assert _label(client, h_ad, key, href) == "管理員專用名", "該角色登入看到角色層的名稱"
    assert _label(client, h_sl, key, href) == before, "沒有角色層的 sales 仍是公司預設"
