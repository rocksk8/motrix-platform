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


def test_real_settings_layer_turns_enforcement_on_and_off(client, hdr):
    """不 monkeypatch 閘門：用真的設定層。開（收緊）立即生效；關（放寬）要走待生效，所以關掉後仍然強制。"""
    import db
    from helpers import settings_registry as SR
    c = db.get_db()
    try:
        SR.publish("builder_governance", {"enabled": 1}, reason="t62", user="t62_sa", conn=c)
        SR.publish("builder_governance", {"enforce_layout": 1}, reason="t62", user="t62_sa", conn=c)
        c.commit()
    finally:
        c.close()
    _layout_draft(client, hdr)
    r = client.post(LAYOUT + "/publish", headers=hdr, json={"note": "n"})
    assert r.status_code == 409 and r.json()["code"] == "preview_required"
    c = db.get_db()
    try:
        out = SR.publish("builder_governance", {"enforce_layout": 0}, reason="t62 off", user="t62_sa", conn=c)
        c.commit()
    finally:
        c.close()
    assert out["pending"], "關閉強制屬於放寬（loosen=down），必須待生效"
    assert client.post(LAYOUT + "/publish", headers=hdr, json={"note": "n"}).status_code == 409      # 待生效期間仍強制


def test_restore_is_gated_with_a_version_preview(client, hdr, monkeypatch):
    _enforce(monkeypatch, {"layout"})
    _layout_draft(client, hdr)
    h = client.get("/api/def-governance/layout/module:suppliers/impact", headers=hdr).json()["previewHash"]
    assert client.post(LAYOUT + "/publish", headers=hdr, json={"note": "n", "preview_hash": h}).status_code == 200
    _layout_draft(client, hdr)
    client.put(LAYOUT + "/draft", headers=hdr, json={"body": {"ops": []}, "note": "x"})
    r = client.post(LAYOUT + "/restore/1", headers=hdr, json={})
    assert r.status_code == 409 and r.json()["code"] == "preview_required"
    pv = client.get("/api/def-governance/layout/module:suppliers/impact?version=1", headers=hdr).json()
    assert pv["restoreVersion"] == 1 and pv["previewHash"].startswith("v1:")
    assert client.post(LAYOUT + "/restore/1", headers=hdr, json={"preview_hash": "v1:0000000000000000"}).status_code == 409
    assert client.post(LAYOUT + "/restore/1", headers=hdr, json={"preview_hash": pv["previewHash"]}).status_code == 200


def test_restore_is_unchanged_when_not_enforced(client, hdr):
    _layout_draft(client, hdr)
    assert client.post(LAYOUT + "/publish", headers=hdr, json={"note": "n"}).status_code == 200
    assert client.post(LAYOUT + "/restore/1", headers=hdr, json={}).status_code == 200


def test_publish_is_pinned_to_the_previewed_draft_in_the_write_lock(client, hdr, monkeypatch):
    """TOCTOU：閘門通過後、寫鎖內草稿被改 ⇒ D.publish 以預覽戳比對 ⇒ 409 DraftConflict，不發布。"""
    _enforce(monkeypatch, {"layout"})
    _layout_draft(client, hdr)
    h = client.get("/api/def-governance/layout/module:suppliers/impact", headers=hdr).json()["previewHash"]
    seen = {}
    real = R.D.publish

    def spy(conn, kind, key, scope, note="", user="", base_etag=None):
        seen["base_etag"] = base_etag
        return real(conn, kind, key, scope, note, user, base_etag=base_etag)
    monkeypatch.setattr(R.D, "publish", spy)
    assert client.post(LAYOUT + "/publish", headers=hdr, json={"note": "n", "preview_hash": h}).status_code == 200
    assert seen["base_etag"] == h                                    # 發布一定帶著預覽戳進寫鎖


def test_unreadable_enforcement_setting_blocks_instead_of_allowing(client, hdr, monkeypatch):
    from helpers import settings_registry as SR
    _layout_draft(client, hdr)

    def boom(*a, **k):
        raise RuntimeError("settings down")
    monkeypatch.setattr(SR, "get", boom)
    r = client.post(LAYOUT + "/publish", headers=hdr, json={"note": "n"})
    assert r.status_code == 503
    assert client.post(LAYOUT + "/restore/1", headers=hdr, json={}).status_code == 503


def test_unknown_kind_never_reads_the_setting(monkeypatch):
    from helpers import settings_registry as SR
    monkeypatch.setattr(SR, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert R._preview_enforced(None, "something_else") is False                  # 不是可強制的 kind ⇒ 與今天相同，不受設定讀取影響


def test_enforce_fields_are_loosen_down():
    from helpers import settings_registry as SR
    g = SR._g("builder_governance")
    for k in R._OPT_IN_PREVIEW_KINDS:
        assert g["fields"]["enforce_" + k].loosen == "down"


def test_unknown_kinds_can_never_be_opted_in():
    assert R._opt_in_enforced(None, "expense_type") is False and R._opt_in_enforced(None, "nope") is False
    assert R._preview_enforced(None, "nope") is False


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


def test_every_restore_caller_that_has_governance_sends_the_version_preview():
    """還原端點在強制範圍內要帶『這一版』的預覽雜湊：面板與三個有 govOn 的編輯器都要先取（layout-editor.js 屬 3c，另行接）。"""
    for f in ("def-governance.js", "expense-types.js", "remit-kinds-settings.js", "module-builder-output.js"):
        src = (ROOT / "frontend" / "js" / f).read_text(encoding="utf-8")
        assert "preview_hash = " in src and ("previewRestore" in src or "&version=" in src), f
