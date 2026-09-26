"""傳票頁：附件來源的模組不在時，已上傳檔案欄要說出是哪個模組不在（attachments.for_document，主持裁示 M06-b）。

拿掉外包工班的提供者 ⇒ 點案件後右欄照常列出案件自己的檔案，另外顯示「外包工班模組未安裝：派工單、承攬商發票的附件沒有列出」。
觀測點：`[data-testid=src-files-unavailable]` 的文字；對照組＝模組在時沒有這一行。
"""
import pytest

pytest.importorskip("playwright.sync_api")
from tests.platform.test_case_stage_connectors import _without  # noqa: E402
from tests.test_e2e_voucher_source_block_below_2026_09_25 import QNO, _open, _pick_case, _seed  # noqa: E402

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
