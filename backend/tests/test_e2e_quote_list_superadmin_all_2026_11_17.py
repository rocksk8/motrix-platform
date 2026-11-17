"""瀏覽器端對端：最高管理者進報價單列表預設看全部（2026-11-17 使用者交辦）。

- 最高管理者第一次進來（沒記過）：不套「我負責的」，看得到他人的草稿
- 舊 key（T84 對所有人預設寫進去的 motrix_quote_mine:<人>='1'）一次性被忽略 ⇒ 仍是全部
- 他自己按「僅顯示我負責的」⇒ 記在新 key（_v2），重新整理後仍是只看自己的
- 其他角色（admin／sales）預設不變：舊 key 照讀，沒記過 ⇒ 只看我負責的
"""
import pytest

pytest.importorskip("playwright.sync_api")

from playwright.sync_api import expect  # noqa: E402

from tests._requires import requires_module  # noqa: E402
from tests.test_e2e_quote_list_t84_2026_11_13 import DATA, _seed, _uid  # noqa: E402

pytestmark = requires_module("case", "本檔打 M01（報價單）的清單頁")


def _world(make_user, tag):
    sup = make_user(username=f"sae_{tag}_super", role="superadmin")
    make_user(username=f"sae_{tag}_other", role="sales")
    _seed(f"MQ-SAE{tag}-001", _uid(f"sae_{tag}_other"), "草稿")
    _seed(f"MQ-SAE{tag}-002", _uid(f"sae_{tag}_other"), "已核准")
    _seed(f"MQ-SAE{tag}-003", _uid(f"sae_{tag}_super"), "草稿")
    # 他人的：簽核中 1、已成案（本月）1、已結案（本月）1、未成案 1
    _seed(f"MQ-SAE{tag}-004", _uid(f"sae_{tag}_other"), "待審核")
    _seed(f"MQ-SAE{tag}-005", _uid(f"sae_{tag}_other"), "已送出", deal_tag="已成案")
    _seed(f"MQ-SAE{tag}-006", _uid(f"sae_{tag}_other"), "已送出", deal_tag="已結案")
    _seed(f"MQ-SAE{tag}-007", _uid(f"sae_{tag}_other"), "已送出", deal_tag="未成案")
    return sup


def _open(live_server, new_page, login_as, user, prep=None, n=3):
    page = new_page(viewport={"width": 1280, "height": 900})
    login_as(page, user)
    if prep:
        page.add_init_script(prep)
    page.goto(live_server + "/pages/quotations.html")
    page.wait_for_function("() => %s.loading === false && %s.quotes.length >= %d" % (DATA, DATA, n), timeout=20000)
    return page


def _rows(page):
    return page.evaluate("() => [...document.querySelectorAll('tr.ql-row')].map(r => r.dataset.quoteNo)")


@pytest.mark.e2e
def test_superadmin_first_visit_sees_everyones_quotes_including_drafts(live_server, make_user, new_page, login_as):
    sup = _world(make_user, "A")
    page = _open(live_server, new_page, login_as, sup)
    assert page.evaluate("() => %s.onlyMine" % DATA) is False
    assert page.evaluate("() => %s._mineLimit" % DATA) is False
    rows = _rows(page)
    assert {"MQ-SAEA-001", "MQ-SAEA-002", "MQ-SAEA-003"} <= set(rows), rows
    assert page.get_by_test_id("ql-cond-mine").count() == 0, "目前條件不再出現「我負責的」"
    expect(page.get_by_test_id("ql-mine-toggle")).to_have_attribute("aria-pressed", "false")
    assert page.get_by_test_id("ql-mine-note").inner_text().strip() == ""


@pytest.mark.e2e
def test_old_default_key_written_by_t84_is_ignored_once_for_superadmin(live_server, make_user, new_page, login_as):
    sup = _world(make_user, "B")
    page = _open(live_server, new_page, login_as, sup,
                 prep="try { localStorage.setItem('motrix_quote_mine:sae_B_super', '1') } catch (e) {}")
    assert page.evaluate("() => %s.onlyMine" % DATA) is False, "舊 key 的 '1' 是 T84 預設寫進去的，不當成他的選擇"
    assert len(_rows(page)) >= 3


@pytest.mark.e2e
def test_superadmin_manual_choice_is_remembered_in_the_new_key(live_server, make_user, new_page, login_as):
    sup = _world(make_user, "C")
    page = _open(live_server, new_page, login_as, sup)
    page.get_by_test_id("ql-mine-toggle").click()
    assert page.evaluate("() => %s._mineLimit" % DATA) is True
    assert _rows(page) == ["MQ-SAEC-003"]
    assert page.evaluate("() => localStorage.getItem('motrix_quote_mine_v2:sae_C_super')") == "1"
    page.reload()
    page.wait_for_function("() => %s.loading === false && %s.quotes.length >= 3" % (DATA, DATA), timeout=20000)
    assert page.evaluate("() => %s.onlyMine" % DATA) is True, "自己選的有記住"
    assert _rows(page) == ["MQ-SAEC-003"]
    page.get_by_test_id("ql-mine-toggle").click()           # 關掉也記住
    page.reload()
    page.wait_for_function("() => %s.loading === false && %s.quotes.length >= 3" % (DATA, DATA), timeout=20000)
    assert page.evaluate("() => %s.onlyMine" % DATA) is False


@pytest.mark.e2e
def test_other_roles_keep_the_mine_default(live_server, make_user, new_page, login_as):
    _world(make_user, "D")
    sales = make_user(username="sae_D_sales", role="sales")
    _seed("MQ-SAED-010", _uid("sae_D_sales"), "草稿")
    _seed("MQ-SAED-011", _uid("sae_D_sales"), "已核准")
    _seed("MQ-SAED-012", _uid("sae_D_sales"), "已送出")
    page = new_page(viewport={"width": 1280, "height": 900})
    login_as(page, sales)
    page.goto(live_server + "/pages/quotations.html")
    page.wait_for_function("() => %s.loading === false && %s.quotes.length >= 3" % (DATA, DATA), timeout=20000)
    assert page.evaluate("() => %s.onlyMine" % DATA) is True, "一般業務沒記過 ⇒ 預設只看我負責的（T84 不變）"
    assert page.evaluate("() => %s._mineLimit" % DATA) is True


def _sum(page, key):
    return page.get_by_test_id("ql-sum-" + key).inner_text()


@pytest.mark.e2e
def test_superadmin_defaults_to_all_tab_and_sees_closed_quotes(live_server, make_user, new_page, login_as):
    sup = _world(make_user, "E")
    page = _open(live_server, new_page, login_as, sup, n=7)
    assert page.evaluate("() => %s.activeTab" % DATA) == "every"
    rows = _rows(page)
    assert {"MQ-SAEE-006", "MQ-SAEE-007", "MQ-SAEE-001"} <= set(rows), "已結案、未成案、他人的草稿都在：%s" % rows
    assert "全部" in page.get_by_test_id("ql-cond").inner_text() and "進行中" not in page.get_by_test_id("ql-cond").inner_text()
    assert not page.get_by_test_id("ql-clear-conditions").is_visible(), "預設頁籤不算有套用條件"
    assert page.locator(".filter-tab.active").inner_text().strip().startswith("全部")
    # 仍可點其他頁籤篩選；回到「全部」又看得到
    page.locator(".filter-tab", has_text="進行中").click()
    page.wait_for_function("() => !document.querySelector(\"tr.ql-row[data-quote-no='MQ-SAEE-006']\")", timeout=5000)
    assert "MQ-SAEE-007" not in _rows(page)
    page.locator(".filter-tab", has_text="全部").first.click()
    page.wait_for_function("() => !!document.querySelector(\"tr.ql-row[data-quote-no='MQ-SAEE-006']\")", timeout=5000)
    # 清除條件回到「全部」（不是進行中）
    page.locator(".filter-tab", has_text="進行中").click()
    page.get_by_test_id("ql-clear-conditions").click()
    assert page.evaluate("() => %s.activeTab" % DATA) == "every"


@pytest.mark.e2e
def test_superadmin_number_cards_are_company_wide_and_labelled(live_server, make_user, new_page, login_as):
    sup = _world(make_user, "F")
    page = _open(live_server, new_page, login_as, sup, n=7)
    assert page.get_by_test_id("ql-sum-todo-lbl").inner_text() == "全公司待處理"
    assert page.get_by_test_id("ql-sum-waiting-lbl").inner_text() == "全公司簽核中"
    assert page.get_by_test_id("ql-sum-won-lbl").inner_text() == "全公司本月已成案"
    # 待處理＝他人草稿＋他人已核准＋自己的草稿
    assert "3 張" in _sum(page, "todo")
    assert "1 張" in _sum(page, "waiting") and "待簽核 1・簽核中 0" in _sum(page, "waiting")
    assert "2 張" in _sum(page, "won"), "已成案＋已結案（本月）"
    # 點卡片＝全公司的篩選：待處理 3 張（含他人的），條件列寫「全公司」
    page.get_by_test_id("ql-sum-todo").click()
    assert sorted(_rows(page)) == ["MQ-SAEF-001", "MQ-SAEF-002", "MQ-SAEF-003"]
    expect(page.get_by_test_id("ql-cond-company")).to_have_count(1)
    expect(page.get_by_test_id("ql-cond-mine")).to_have_count(0)
    page.get_by_test_id("ql-sum-todo").click()
    page.get_by_test_id("ql-sum-won").click()
    assert sorted(_rows(page)) == ["MQ-SAEF-005", "MQ-SAEF-006"]
    page.get_by_test_id("ql-sum-won").click()
    assert page.evaluate("() => %s.activeTab" % DATA) == "every"
    # 就算他手動開了「僅顯示我負責的」，數字仍是全公司
    page.get_by_test_id("ql-mine-toggle").click()
    assert "3 張" in _sum(page, "todo")


@pytest.mark.e2e
def test_superadmin_cards_work_even_when_the_mine_list_cannot_be_read(live_server, make_user, new_page, login_as):
    sup = _world(make_user, "G")
    page = new_page(viewport={"width": 1280, "height": 900})
    login_as(page, sup)
    page.route("**/api/quotations?*mine=1*", lambda r: r.abort())
    page.goto(live_server + "/pages/quotations.html")
    page.wait_for_function("() => %s.loading === false && %s.quotes.length >= 7" % (DATA, DATA), timeout=20000)
    assert "3 張" in _sum(page, "todo") and not page.get_by_test_id("ql-sum-todo").is_disabled()


@pytest.mark.e2e
def test_sales_and_admin_keep_in_progress_tab_and_mine_cards(live_server, make_user, new_page, login_as):
    _world(make_user, "H")
    sales = make_user(username="sae_H_sales", role="sales")
    adm = make_user(username="sae_H_adm", role="admin")
    for no, st, tag in (("MQ-SAEH-010", "草稿", ""), ("MQ-SAEH-011", "已送出", "已結案"), ("MQ-SAEH-012", "待審核", "")):
        _seed(no, _uid("sae_H_sales"), st, deal_tag=tag)
    _seed("MQ-SAEH-020", _uid("sae_H_adm"), "草稿")
    for user, n in ((sales, 3), (adm, 1)):
        page = new_page(viewport={"width": 1280, "height": 900})
        login_as(page, user)
        page.goto(live_server + "/pages/quotations.html")
        page.wait_for_function("() => %s.loading === false && %s.quotes.length >= %d" % (DATA, DATA, n), timeout=20000)
        assert page.evaluate("() => %s.activeTab" % DATA) == "all"
        assert page.get_by_test_id("ql-sum-todo-lbl").inner_text() == "待我處理"
        assert page.get_by_test_id("ql-sum-waiting-lbl").inner_text() == "等待他人"
        assert page.get_by_test_id("ql-sum-won-lbl").inner_text() == "本月已成案"
        assert "進行中" in page.get_by_test_id("ql-cond").inner_text()
        assert page.locator(".filter-tab", has_text="全部").count() == 1, "「全部」頁籤每個角色都有，只是預設不同"
    # 業務：已結案不在預設頁籤，點「全部」才看得到
    page = new_page(viewport={"width": 1280, "height": 900})
    login_as(page, sales)
    page.goto(live_server + "/pages/quotations.html")
    page.wait_for_function("() => %s.loading === false && %s.quotes.length >= 3" % (DATA, DATA), timeout=20000)
    assert "MQ-SAEH-011" not in _rows(page)
    page.get_by_test_id("ql-mine-toggle").click()
    page.locator(".filter-tab", has_text="全部").first.click()
    page.wait_for_function("() => !!document.querySelector(\"tr.ql-row[data-quote-no='MQ-SAEH-011']\")", timeout=5000)
