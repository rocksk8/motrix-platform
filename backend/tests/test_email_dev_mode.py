"""開發機測試模式（2026-08-26）：system_settings.email_notify.dev_mode 開啟時，
寄出信件標題加註「【開發機測試】」，避免開發機觸發的通知信被收件人誤認為正式
環境的真實通知。純函式測試，不需要真的連 SMTP。"""
from helpers.email_notify import _apply_dev_subject_prefix, _DEV_SUBJECT_PREFIX


def test_dev_mode_off_leaves_subject_unchanged():
    assert _apply_dev_subject_prefix({"dev_mode": False}, "測試主旨") == "測試主旨"
    assert _apply_dev_subject_prefix({}, "測試主旨") == "測試主旨"


def test_dev_mode_on_prefixes_subject():
    result = _apply_dev_subject_prefix({"dev_mode": True}, "【MOTRIX】案件到期提醒")
    assert result == f"{_DEV_SUBJECT_PREFIX}【MOTRIX】案件到期提醒"


def test_dev_mode_on_does_not_double_prefix():
    already = f"{_DEV_SUBJECT_PREFIX}【MOTRIX】案件到期提醒"
    assert _apply_dev_subject_prefix({"dev_mode": True}, already) == already
