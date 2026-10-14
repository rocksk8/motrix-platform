# -*- coding: utf-8 -*-
"""T62：發布前強制預覽的範圍可由最高管理者逐 kind 選擇（builder_governance.enforce_<kind>，預設全 0）。
- 全部預設關：版面／自訂欄位／按鈕／輸出版型發布不帶雜湊照常成功（與今天相同）；欄位在設定登錄、預設 0
- 治理旗標關：就算 enforce_<kind>=1 也不強制
- 治理旗標開＋enforce_layout=1：沒帶 ⇒ 409 preview_required；先看過影響預覽、帶同一個戳 ⇒ 成功；只開 layout 不影響 custom_fields
- 選單編輯器：發布前把剛存的草稿送去影響預覽並帶回雜湊；預覽 404（治理關）或失敗 ⇒ 不帶雜湊（請求與過去相同）"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from routers import def_governance as G
from routers import definitions as R

NODE = shutil.which("node")
ROOT = Path(__file__).resolve().parents[2]
LAYOUT = "/api/definitions/layout/module:suppliers"


@pytest.fixture()
def hdr(client, make_user):
    u, p = make_user(username="t62_sa", role="superadmin")
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _enforce(monkeypatch, on_kinds, gov=True):
    monkeypatch.setattr(R, "_governance_enabled", lambda conn=None: gov)
    monkeypatch.setattr(G, "enabled", lambda conn=None: gov)
    monkeypatch.setattr(R, "_opt_in_enforced", lambda conn, kind: kind in on_kinds)


def _layout_draft(client, hdr):
    r = client.put(LAYOUT + "/draft", headers=hdr, json={"body": {"ops": []}})
    assert r.status_code == 200, r.text


def test_defaults_are_off_and_registered():
    from helpers import settings_registry as SR
    for k in R._OPT_IN_PREVIEW_KINDS:
        assert SR.get("builder_governance", "enforce_" + k) == 0


def test_all_off_publish_without_hash_works_as_before(client, hdr):
    _layout_draft(client, hdr)
    assert client.post(LAYOUT + "/publish", headers=hdr, json={"note": "n"}).status_code == 200


def test_governance_flag_off_ignores_the_per_kind_switch(client, hdr, monkeypatch):
    _enforce(monkeypatch, {"layout"}, gov=False)
    _layout_draft(client, hdr)
    assert client.post(LAYOUT + "/publish", headers=hdr, json={"note": "n"}).status_code == 200


def test_layout_enforced_requires_a_seen_preview(client, hdr, monkeypatch):
    _enforce(monkeypatch, {"layout"})
    _layout_draft(client, hdr)
    r = client.post(LAYOUT + "/publish", headers=hdr, json={"note": "n"})
    assert r.status_code == 409 and r.json()["code"] == "preview_required"
    seen = client.get("/api/def-governance/layout/module:suppliers/impact", headers=hdr).json()["previewHash"]
    r = client.post(LAYOUT + "/publish", headers=hdr, json={"note": "n", "preview_hash": seen})
    assert r.status_code == 200


def test_switching_one_kind_does_not_enforce_another(client, hdr, monkeypatch):
    _enforce(monkeypatch, {"layout"})
    cf = "/api/definitions/custom_fields/invoice_vouchers"
    assert client.put(cf + "/draft", headers=hdr, json={"body": {"fields": [{"key": "f0", "label": "甲", "type": "text"}]}}).status_code == 200
    assert client.post(cf + "/publish", headers=hdr, json={"note": "n"}).status_code == 200


def test_unknown_kinds_can_never_be_opted_in():
    assert R._opt_in_enforced(None, "expense_type") is False and R._opt_in_enforced(None, "nope") is False


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_menu_editor_sends_the_hash_only_when_the_preview_gives_one():
    src = (ROOT / "frontend" / "static" / "menu-editor.js").read_text(encoding="utf-8")
    fn = re.search(r"function previewSeen\(m\) \{.*?\n  \}\n", src, re.S).group(0)
    assert "preview_hash = pvh" in src and "previewSeen(m).then" in src
    harness = "var calls=[];var mode;function api(m,u){calls.push(u);return mode==='ok'?Promise.resolve({previewHash:'h1'}):Promise.reject(new Error('404'))}\n" + fn + """
(async()=>{var out=[];mode='ok';out.push(await previewSeen('suppliers'));mode='no';out.push(await previewSeen('suppliers'));
console.log(JSON.stringify([out,calls[0]]))})()"""
    out = subprocess.run([NODE, "-e", harness], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert json.loads(out.stdout.strip()) == [["h1", None], "/api/def-governance/layout/module:suppliers/impact?scope=company"]
