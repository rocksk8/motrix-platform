# -*- coding: utf-8 -*-
"""email 寄不寄（2026-09-25 使用者裁示：預設寄信；開發機以 .no_email_send 或 MOTRIX_EMAIL_SEND=off 擋）。"""
import logging

import pytest

from helpers import email_notify as en


@pytest.fixture()
def no_marker(monkeypatch, tmp_path):
    monkeypatch.setattr(en, "_NO_EMAIL_SEND_MARKER_PATH", str(tmp_path / ".no_email_send"))
    return tmp_path / ".no_email_send"


def test_default_sends(no_marker):
    allowed, why = en.email_send_policy(env={})
    assert allowed and "預設" in why


@pytest.mark.parametrize("val", ["off", "OFF", "0", "false", "no", "disabled", " off "])
def test_env_off_blocks(no_marker, val):
    allowed, why = en.email_send_policy(env={en.EMAIL_SEND_ENV: val})
    assert not allowed and en.EMAIL_SEND_ENV in why


def test_marker_blocks_and_names_the_file(no_marker):
    no_marker.write_text("")
    allowed, why = en.email_send_policy(env={})
    assert not allowed and str(no_marker) in why


def test_either_one_blocks_env_on_cannot_override_marker(no_marker):
    no_marker.write_text("")
    assert en.email_send_policy(env={en.EMAIL_SEND_ENV: "on"})[0] is False


def test_unrecognised_env_value_does_not_silently_block(no_marker):
    allowed, why = en.email_send_policy(env={en.EMAIL_SEND_ENV: "of"})
    assert allowed and "無法辨識" in why


def test_blocked_send_logs_reason_once_then_per_message(no_marker, monkeypatch, caplog):
    no_marker.write_text("")
    monkeypatch.delenv(en.EMAIL_SEND_ENV, raising=False)
    monkeypatch.setitem(en._email_policy_state, "allowed", None)
    with caplog.at_level(logging.INFO, logger=en.logger.name):
        assert en._smtp_send_blocked("s1") is True
        assert en._smtp_send_blocked("s2") is True
    infos = [r for r in caplog.records if r.levelno == logging.INFO and "不寄信" in r.getMessage()]
    assert len(infos) == 1 and str(no_marker) in infos[0].getMessage()
    warns = [r for r in caplog.records if r.levelno == logging.WARNING and "BLOCKED" in r.getMessage()]
    assert len(warns) == 2


def test_allowed_send_is_not_blocked(no_marker, monkeypatch):
    monkeypatch.delenv(en.EMAIL_SEND_ENV, raising=False)
    assert en._smtp_send_blocked("s") is False


def test_install_path_detection_is_gone():
    assert not hasattr(en, "_is_production_install")
    assert not hasattr(en, "_PRODUCTION_INSTALL")
