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
    return sup


def _open(live_server, new_page, login_as, user, prep=None):
    page = new_page(viewport={"width": 1280, "height": 900})
    login_as(page, user)
    if prep:
        page.add_init_script(prep)
    page.goto(live_server + "/pages/quotations.html")
    page.wait_for_function("() => %s.loading === false && %s.quotes.length >= 3" % (DATA, DATA), timeout=20000)
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
