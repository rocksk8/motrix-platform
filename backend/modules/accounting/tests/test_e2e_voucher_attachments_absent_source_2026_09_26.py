"""傳票頁：附件來源的模組不在時，已上傳檔案欄要說出是哪個模組不在（attachments.for_document，主持裁示 M06-b）。

拿掉外包工班的提供者 ⇒ 點案件後右欄照常列出案件自己的檔案，另外顯示「外包工班模組未安裝：派工單、承攬商發票的附件沒有列出」。
觀測點：`[data-testid=src-files-unavailable]` 的文字；對照組＝模組在時沒有這一行。
"""
import pytest

pytest.importorskip("playwright.sync_api")
from tests.platform.test_case_stage_connectors import _without  # noqa: E402
from modules.accounting.tests.test_e2e_voucher_source_block_below_2026_09_25 import QNO, _open, _pick_case, _seed  # noqa: E402

UNAV = '[data-testid="src-files-unavailable"]'


@pytest.mark.e2e
def test_absent_attachment_source_is_named_in_the_files_column(live_server, make_user, e2e_browser, client, monkeypatch):
    _without(monkeypatch, "attachments.for_document", "subcontract")
    u = make_user(username="att_abs_e2e", role="superadmin")
    vid = _seed(client, u)
    page = _open(e2e_browser, live_server, u, vid)
    _pick_case(page)                                           # 案件自己的兩個檔照常列出
    box = page.locator(UNAV)
    box.first.wait_for(state="visible", timeout=8000)
    text = box.first.inner_text()
    assert "外包工班模組未安裝" in text and "派工單" in text and "承攬商發票" in text, text


@pytest.mark.e2e
def test_all_sources_present_shows_no_absence_line(live_server, make_user, e2e_browser, client):
    from core import source_tree
    if not source_tree.module_installed("modules/subcontract/"):
        pytest.skip("外包工班不在這個安裝包")
    u = make_user(username="att_all_e2e", role="superadmin")
    vid = _seed(client, u)
    page = _open(e2e_browser, live_server, u, vid)
    _pick_case(page)
    page.wait_for_function("() => !Alpine.$data(document.querySelector('[x-data]')).srcState().loading", timeout=8000)
    assert page.locator(UNAV).count() == 0


@pytest.mark.e2e
def test_sources_hidden_by_permission_are_named_in_the_files_column(live_server, make_user, e2e_browser, client,
                                                                     monkeypatch):
    """主持裁示（2026-09-26）：因權限沒列出的來源要在畫面上明說，不可以跟「沒有」長得一樣。
    合成：案件的提供者對「案件動態」一類說看不到 2 個附件 ⇒ 已上傳檔案欄顯示「案件動態：2 個附件因權限無法顯示」。"""
    from core import registry
    from helpers.uploads import AttachmentNotVisible
    key = ("attachments.for_document", "case")
    real = registry._LEGACY_PROVIDERS[key]

    class _HidesUpdates:
        SOURCE_TYPES = real.SOURCE_TYPES
        LABEL = getattr(real, "LABEL", "")

        @staticmethod
        def doc_nos_for_case(conn, st, quote_no, user):
            if st == "case_update":
                raise AttachmentNotVisible(hidden=2)
            return real.doc_nos_for_case(conn, st, quote_no, user)

        files = staticmethod(real.files)

    monkeypatch.setitem(registry._LEGACY_PROVIDERS, key, _HidesUpdates)
    u = make_user(username="att_hid_e2e", role="superadmin")
    vid = _seed(client, u)
    page = _open(e2e_browser, live_server, u, vid)
    _pick_case(page)
    box = page.locator(UNAV)
    box.first.wait_for(state="visible", timeout=8000)
    texts = " ".join(box.all_inner_texts())
    assert "案件動態" in texts and "2 個附件因權限無法顯示" in texts, texts
