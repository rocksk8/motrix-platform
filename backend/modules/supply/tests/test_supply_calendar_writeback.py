"""IP-6：出貨單（M03）的行事曆 event id 回寫（2026-09-26 自 tests/platform/test_case_stage_connectors.py 移入，PLAYBOOK §B-11）。

檢查本身是 L1 那兩支（以別名匯入，不重複收集）；拿掉 M03 時這一列跟著消失。
"""
from tests.platform.test_case_stage_connectors import (  # noqa: F401
    distinct_google,
    test_calendar_writeback_document_kinds_do_not_overwrite_concurrent_edits as _no_overwrite,
    test_calendar_writeback_document_kinds_write_their_own_row as _own_row,
)

_ROW = ("shipping_note", "shipping_notes", "note_no", "push_event_for_shipping_note")


def test_shipping_note_writeback_writes_its_own_row(client, distinct_google):
    _own_row(client, distinct_google, *_ROW)


def test_shipping_note_writeback_does_not_overwrite_concurrent_edits(client, distinct_google):
    _no_overwrite(client, distinct_google, *_ROW)
