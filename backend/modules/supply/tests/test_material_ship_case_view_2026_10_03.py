# -*- coding: utf-8 -*-
"""34-S3（M01 側經 M03 提供者）：材料申請摘要的出貨欄與取消阻擋。
- GET material-order-approvals 帶 `shipping`：已申請／已到料／占用中／已出貨／出貨單號；出貨提供者不在 ⇒ 只剩申請／到貨
- 取消材料申請：有活的出貨連結（占用中或已出貨）⇒ 409 並列出貨單號；退回／草稿的出貨單不擋；提供者丟例外 ⇒ 擋（fail closed）
⚙️ 突變：拿掉取消前檢查 ⇒ 紅。"""
import pytest

from tests._requires import requires_module
from modules.supply.tests.test_shipping_material_link_2026_10_03 import DOC, ITEM, Q, _note, _set, world  # noqa: F401

pytestmark = requires_module("case", "需要 M01 的材料申請")

URL = "/api/quotations/%s/material-order-approvals" % Q
CANCEL = "/api/quotations/%s/material-orders/%s/cancel" % (Q, ITEM)


def L(qty):
    return {"description": "電纜", "materialLink": {"materialItemId": ITEM, "docCode": DOC, "qty": qty}}


def test_summary_carries_shipping_numbers_and_note_numbers(world):
    client, h = world
    a = _note(client, h, [L(4)], status="已核准")
    b = _note(client, h, [L(2)], status="待審核")
    _note(client, h, [L(9)])                                                # 草稿不計
    r = client.get(URL, headers=h)
    assert r.status_code == 200, r.text
    s = r.json()["shipping"][ITEM]
    assert (s["appliedQty"], s["arrivedQty"], s["shipped"], s["reserved"]) == (10.0, 10.0, 4.0, 2.0) and sorted(s["notes"]) == sorted([a, b]), s
    assert "it2" not in r.json()["shipping"]                                # 沒到料也沒出貨的不列


def test_summary_without_the_shipping_provider_keeps_applied_and_arrived_only(world, monkeypatch):
    client, h = world
    _note(client, h, [L(4)], status="已核准")
    from core import registry
    real = registry.providers
    monkeypatch.setattr(registry, "providers", lambda cap: {} if cap == "shipping.material_shipped" else real(cap))
    s = client.get(URL, headers=h).json()["shipping"][ITEM]
    assert (s["appliedQty"], s["arrivedQty"], s["shipped"], s["reserved"], s["notes"]) == (10.0, 10.0, 0.0, 0.0, [])


def test_cancel_is_refused_while_a_live_shipping_link_exists_and_lists_the_notes(world):
    client, h = world
    n = _note(client, h, [L(4)], status="待審核")
    r = client.post(CANCEL, headers=h, json={"reason": "不要了"})
    assert r.status_code == 409 and n in r.json()["detail"] and "占用中 4" in r.json()["detail"], r.text
    _set(n, status="已核准")
    r = client.post(CANCEL, headers=h, json={"reason": "不要了"})
    assert r.status_code == 409 and "已出貨 4" in r.json()["detail"], r.text


def test_cancel_goes_through_when_only_draft_or_returned_notes_exist(world):
    client, h = world
    _note(client, h, [L(4)])                                                 # 草稿
    _note(client, h, [L(3)], status="已退回")
    r = client.post(CANCEL, headers=h, json={"reason": "不要了"})
    assert r.status_code == 200, r.text


def test_cancel_fails_closed_when_the_shipping_provider_raises(world, monkeypatch):
    client, h = world
    from core import registry
    real = registry.providers

    def boom(conn, quote_no, exclude_note_no=None):
        raise RuntimeError("boom")
    monkeypatch.setattr(registry, "providers", lambda cap: {"supply": boom} if cap == "shipping.material_shipped" else real(cap))
    r = client.post(CANCEL, headers=h, json={"reason": "x"})
    assert r.status_code == 409 and "暫時無法確認" in r.json()["detail"], r.text
