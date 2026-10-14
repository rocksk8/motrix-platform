# -*- coding: utf-8 -*-
"""T60 S0（D8）：`GET /api/platform/menu` 對非最高管理者一律遮蔽 `layout.applied／skipped／dropped` 的操作原文，**不論旗標**。
- 舊洩漏（旗標全關也存在）：針對『使用者看不到的側欄項目』的 hide 操作，原文帶著該項目的目標 id，受限使用者讀得到
- 現在：非最高管理者只剩操作種類（與理由）；最高管理者照舊拿到原文
- 只此而已：把遮蔽函式換回『原樣回傳』（＝舊行為）再讀一次，兩次回應除了這三個欄位完全相同"""
import json

import pytest

import db
from core import definitions as D
from core import registry
from helpers import menu_builder as MB


def _pick_restricted():
    for m in registry.loaded():
        for p in (m.manifest or {}).get("pages") or []:
            perm = (p.get("menu") or {}).get("perm") if isinstance(p, dict) else None
            if isinstance(p, dict) and p.get("menu") and isinstance(perm, list) and perm \
                    and not ({"cashier", "finance", "financial_view"} & set(perm)):
                return m.key, p["path"]
    pytest.skip("沒有宣告模組權限的選單項 ⇒ 沒有『看不到』的對象")


def _login(client, make_user, name, role, modules=None):
    u, pw = make_user(username=name, role=role, **({"modules": modules} if modules is not None else {}))[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]}


@pytest.fixture()
def hidden_op(client, make_user):
    key, href = _pick_restricted()
    tgt = "%s:%s/sidebar" % (key, href)
    conn = db.get_db()
    try:
        D.save_draft(conn, "layout", "module:%s" % key, "company", {"ops": [{"op": "hide", "target": tgt}]}, user="t")
        D.publish(conn, "layout", "module:%s" % key, "company", note="t", user="t")
    finally:
        conn.close()
    return key, href, tgt, _login(client, make_user, "t60s0_none", "admin", modules=[]), _login(client, make_user, "t60s0_sa", "superadmin")


def test_flag_is_off_in_this_test(hidden_op):
    assert MB.enabled() is False                                   # 預設關：這個測試證明『旗標關也遮蔽』


def test_restricted_user_no_longer_reads_the_target_id_with_the_flag_off(client, hidden_op):
    _k, _h, tgt, h_none, _h_sa = hidden_op
    d = client.get("/api/platform/menu", headers=h_none).json()
    assert tgt not in json.dumps(d, ensure_ascii=False)
    assert d["layout"]["skipped"], "仍要告訴他『有操作被略過』（只是不給內容）"
    for x in d["layout"]["skipped"] + d["layout"]["applied"] + d["layout"]["dropped"]:
        flat = x if isinstance(x, dict) else {"op": x}
        op = flat["op"]
        assert (op == {"op": "hide"}) or isinstance(op, str) or set(op) == {"op"}, flat   # 只剩操作種類（可帶理由）


def test_superadmin_still_gets_the_raw_operations(client, hidden_op):
    _k, _h, tgt, _h_none, h_sa = hidden_op
    d = client.get("/api/platform/menu", headers=h_sa).json()
    assert tgt in json.dumps(d["layout"], ensure_ascii=False)


def test_nothing_else_in_the_response_changes(client, hidden_op, monkeypatch):
    """反向控制：遮蔽函式換回『原樣回傳』＝舊行為；兩次讀取除了 applied／skipped／dropped 完全相同。"""
    _k, _h, tgt, h_none, _h_sa = hidden_op
    new = client.get("/api/platform/menu", headers=h_none).json()
    monkeypatch.setattr(MB, "redact_ops", lambda items: items)
    old = client.get("/api/platform/menu", headers=h_none).json()
    assert tgt in json.dumps(old["layout"], ensure_ascii=False)                  # 舊行為確實洩漏（對照組有效）
    for body in (new, old):
        for f in ("applied", "skipped", "dropped"):
            body["layout"].pop(f)
    assert new == old
