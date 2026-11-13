"""一條龍 P0a（旗標 onepipe.links）：出貨單通知連結不再指向不存在的頁面；入口與連結只在旗標開時出現。

旗標關＝與今天逐位元相同：信件連結照舊、站內通知不帶 link、畫面沒有新入口。
"""
import re
from pathlib import Path

import pytest

from core import source_tree

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


def _flags(monkeypatch, **on):
    from helpers import onepipe_flags
    monkeypatch.setattr(onepipe_flags, "flag_on", lambda field, conn=None: bool(on.get(field)))


def _note(note_no, quote_no):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO shipping_notes (note_no, quote_no, customer_name, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                     (note_no, quote_no, "客戶", "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def test_group_registered_with_all_five_fields_default_off(client):
    from helpers import settings_registry as SR
    import helpers.settings_groups  # noqa: F401
    for f in ("links", "ship_install_ok", "timeline"):
        assert SR.get("onepipe", f) == 0
    from helpers.onepipe_flags import flag_on
    assert not any(flag_on(f) for f in ("links", "ship_install_ok", "timeline", "nope"))


def test_shipping_link_off_unknown_and_on(client, monkeypatch):
    from helpers.email_notify import shipping_link
    _note("SH-OP-1", "MQ OP/1")
    _flags(monkeypatch, links=False)
    assert shipping_link("SH-OP-1") == ""
    _flags(monkeypatch, links=True)
    assert shipping_link("SH-OP-1") == "case-management.html?q=MQ%20OP%2F1&tab=shipping"
    assert shipping_link("SH-NO-SUCH") == ""
    assert shipping_link("") == ""


def test_shipping_mails_point_at_the_case_page_only_when_on(client, monkeypatch):
    from helpers import email_notify as E
    sent = []
    monkeypatch.setattr(E, "_lookup_emails", lambda users, key=None: ["a@example.com"])
    monkeypatch.setattr(E, "_async_send", lambda to, subject, html, *a, **k: sent.append(html))
    _note("SH-OP-2", "MQ-OP-2")
    _flags(monkeypatch, links=False)
    E.notify_shipping_submitted("SH-OP-2", "客戶", ["u1"])
    assert "/pages/shipping-notes.html?no=SH-OP-2" in sent[-1] and "case-management.html" not in sent[-1]
    _flags(monkeypatch, links=True)
    E.notify_shipping_submitted("SH-OP-2", "客戶", ["u1"])
    assert "/pages/case-management.html?q=MQ-OP-2&amp;tab=shipping" in sent[-1] or "/pages/case-management.html?q=MQ-OP-2&tab=shipping" in sent[-1]
    assert "shipping-notes.html" not in sent[-1]
    _flags(monkeypatch, links=True)
    E.notify_shipping_submitted("SH-OP-MISSING", "客戶", ["u1"])           # 查不到案號 ⇒ 維持原本的連結（不丟例外）
    assert "shipping-notes.html?no=SH-OP-MISSING" in sent[-1]


def test_notification_link_is_valid_for_the_bell(client, monkeypatch):
    """站內通知的 link 會被 notif.js 的白名單再驗一次：頁面檔名.html＋選填查詢字串。"""
    from helpers.email_notify import shipping_link
    _flags(monkeypatch, links=True)
    _note("SH-OP-3", "MQ-2026-0001")
    assert re.match(r"^[A-Za-z0-9_-]+\.html(\?[A-Za-z0-9_.=&%:+-]*)?$", shipping_link("SH-OP-3"))


def test_front_end_entries_are_gated_by_the_flag():
    """新入口都掛在 onepipe 旗標上；旗標沒開（或讀不到）時預設值是 false。"""
    cm = source_tree.page_file("case-management.html").read_text(encoding="utf-8")
    assert re.search(r'data-testid="op-open-bar"[^>]*', cm) and 'x-show="onepipe.links && selected"' in cm
    core = (FRONTEND / "js" / "case-management-core.js").read_text(encoding="utf-8")
    assert "onepipe: { links: false, timeline: false }" in core
    wy = source_tree.page_file("warranty.html").read_text(encoding="utf-8")
    assert "op: { links: false }" in wy and 'x-show="!(op.links' in wy
    pr = source_tree.page_file("payment-request.html").read_text(encoding="utf-8")
    assert "(await window.MotrixOnepipe.flags()).links" in pr
    js = (FRONTEND / "static" / "onepipe.js").read_text(encoding="utf-8")
    assert "{ links: false, timeline: false }" in js and "groups=onepipe" in js
