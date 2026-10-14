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
LAYOUT = None          # 由 autouse 夾具在每題開頭依『實際載入的模組』填入（寫死 suppliers 在 t60 基底不存在 ⇒ 版面驗證 422）
MOD = None


@pytest.fixture(autouse=True)
def _layout_target(client):
    """版面發布的驗證器要求模組真的存在：挑第一個有宣告選單項的已載入模組，不寫死名稱。"""
    global LAYOUT, MOD
    from core import registry
    for m in registry.loaded():
        if any(isinstance(p, dict) and p.get("menu") for p in (m.manifest or {}).get("pages") or []):
            MOD = "module:" + m.key
            break
    else:
        pytest.skip("沒有宣告選單項的模組")
    LAYOUT = "/api/definitions/layout/" + MOD


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


def test_governance_flag_off_alone_does_not_enforce_an_opt_in_kind(client, hdr, monkeypatch):
    """總開關關著、而且沒有任何 enforce_<kind> 開著 ⇒ 不強制（與今天相同）。
    （舊版這題寫成『總開關關 ⇒ 忽略 enforce_layout』，與已定案的設計相反：enforce_<kind> 獨立於總開關，
    開了就不會因為關總開關而被繞過，見 test_turning_the_master_switch_off_does_not_bypass_an_enabled_enforcement。）"""
    _enforce(monkeypatch, set(), gov=False)
    _layout_draft(client, hdr)
    assert client.post(LAYOUT + "/publish", headers=hdr, json={"note": "n"}).status_code == 200


def test_enabled_enforcement_is_not_bypassed_by_a_disabled_master_switch(client, hdr, monkeypatch):
    _enforce(monkeypatch, {"layout"}, gov=False)
    _layout_draft(client, hdr)
    r = client.post(LAYOUT + "/publish", headers=hdr, json={"note": "n"})
    assert r.status_code == 409 and r.json()["code"] == "preview_required"


def test_layout_enforced_requires_a_seen_preview(client, hdr, monkeypatch):
    _enforce(monkeypatch, {"layout"})
    _layout_draft(client, hdr)
    r = client.post(LAYOUT + "/publish", headers=hdr, json={"note": "n"})
    assert r.status_code == 409 and r.json()["code"] == "preview_required"
    seen = client.get("/api/def-governance/layout/" + MOD + "/impact", headers=hdr).json()["previewHash"]
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
    h = client.get("/api/def-governance/layout/" + MOD + "/impact", headers=hdr).json()["previewHash"]
    assert client.post(LAYOUT + "/publish", headers=hdr, json={"note": "n", "preview_hash": h}).status_code == 200
    _layout_draft(client, hdr)
    client.put(LAYOUT + "/draft", headers=hdr, json={"body": {"ops": []}, "note": "x"})
    r = client.post(LAYOUT + "/restore/1", headers=hdr, json={})
    assert r.status_code == 409 and r.json()["code"] == "preview_required"
    pv = client.get("/api/def-governance/layout/" + MOD + "/impact?version=1", headers=hdr).json()
    assert pv["restoreVersion"] == 1 and pv["previewHash"].startswith("v1@live")
    assert client.post(LAYOUT + "/restore/1", headers=hdr, json={"preview_hash": "v1@live1:0000000000000000"}).status_code == 409
    assert client.post(LAYOUT + "/restore/1", headers=hdr, json={"preview_hash": pv["previewHash"]}).status_code == 200


def test_restore_is_unchanged_when_not_enforced(client, hdr):
    _layout_draft(client, hdr)
    assert client.post(LAYOUT + "/publish", headers=hdr, json={"note": "n"}).status_code == 200
    assert client.post(LAYOUT + "/restore/1", headers=hdr, json={}).status_code == 200


def test_publish_is_pinned_to_the_previewed_draft_in_the_write_lock(client, hdr, monkeypatch):
    """TOCTOU：閘門通過後、寫鎖內草稿被改 ⇒ D.publish 以預覽戳比對 ⇒ 409 DraftConflict，不發布。"""
    _enforce(monkeypatch, {"layout"})
    _layout_draft(client, hdr)
    h = client.get("/api/def-governance/layout/" + MOD + "/impact", headers=hdr).json()["previewHash"]
    seen = {}
    real = R.D.publish

    def spy(conn, kind, key, scope, note="", user="", base_etag=None):
        seen["base_etag"] = base_etag
        return real(conn, kind, key, scope, note, user, base_etag=base_etag)
    monkeypatch.setattr(R.D, "publish", spy)
    assert client.post(LAYOUT + "/publish", headers=hdr, json={"note": "n", "preview_hash": h}).status_code == 200
    assert seen["base_etag"] == h                                    # 發布一定帶著預覽戳進寫鎖


def _fail_setting_reads(monkeypatch):
    """讓『資料庫讀設定』失敗（不是換掉包裝函式）：設定群組存在定義表裡，kind＝setting_group 的讀取一律丟錯。"""
    from helpers import settings_registry as SR
    real = R.D.get

    def flaky(conn, kind, *a, **k):
        if kind == SR.KIND:
            raise RuntimeError("database is locked")
        return real(conn, kind, *a, **k)
    monkeypatch.setattr(R.D, "get", flaky)


def test_unreadable_enforcement_setting_blocks_instead_of_allowing(client, hdr, monkeypatch):
    _layout_draft(client, hdr)
    _fail_setting_reads(monkeypatch)
    r = client.post(LAYOUT + "/publish", headers=hdr, json={"note": "n"})
    assert r.status_code == 503
    assert client.post(LAYOUT + "/restore/1", headers=hdr, json={}).status_code == 503


def _enable_layout_enforcement(only_layout=True):
    import db
    from helpers import settings_registry as SR
    c = db.get_db()
    try:
        vals = {"enforce_layout": 1} if only_layout else {"enabled": 1, "enforce_layout": 1}
        SR.publish("builder_governance", vals, reason="t62", user="t62_sa", conn=c)
        c.commit()
    finally:
        c.close()


def test_defaults_only_escape_hatch_does_not_open_the_gate(client, hdr, monkeypatch):
    _enable_layout_enforcement()
    _layout_draft(client, hdr)
    monkeypatch.setenv("MOTRIX_SETTINGS_DEFAULTS_ONLY", "1")
    r = client.post(LAYOUT + "/publish", headers=hdr, json={"note": "n"})
    assert r.status_code == 409 and r.json()["code"] == "preview_required"


def test_turning_the_master_switch_off_does_not_bypass_an_enabled_enforcement(client, hdr):
    """enforce_layout=1、builder_governance.enabled=0：仍強制；預覽路由仍可用（否則該類永遠無法發布）。"""
    _enable_layout_enforcement()
    _layout_draft(client, hdr)
    assert client.post(LAYOUT + "/publish", headers=hdr, json={"note": "n"}).status_code == 409
    j = client.get("/api/def-governance/layout/" + MOD + "/impact", headers=hdr)
    assert j.status_code == 200
    assert client.post(LAYOUT + "/publish", headers=hdr, json={"note": "n", "preview_hash": j.json()["previewHash"]}).status_code == 200


def test_caller_base_etag_that_differs_from_the_previewed_hash_conflicts(client, hdr, monkeypatch):
    _enforce(monkeypatch, {"layout"})
    _layout_draft(client, hdr)
    h1 = client.get("/api/def-governance/layout/" + MOD + "/impact", headers=hdr).json()["previewHash"]
    r = client.post(LAYOUT + "/publish", headers=hdr, json={"note": "n", "preview_hash": h1, "base_etag": "0123456789abcdef"})
    assert r.status_code == 409 and r.json().get("code") == "draft_conflict"


def test_restore_preview_is_bound_to_the_live_version(client, hdr, monkeypatch):
    """預覽之後又發布了別的版本 ⇒ 舊預覽不能再用來還原（戳含生效版）。"""
    _enforce(monkeypatch, set())
    for n in ("a", "b"):
        client.put(LAYOUT + "/draft", headers=hdr, json={"body": {"ops": []}, "note": n})
        assert client.post(LAYOUT + "/publish", headers=hdr, json={"note": n}).status_code == 200
    _enforce(monkeypatch, {"layout"})
    pv = client.get("/api/def-governance/layout/" + MOD + "/impact?version=1", headers=hdr).json()["previewHash"]
    monkeypatch.setattr(R, "_opt_in_enforced", lambda conn, kind: False)
    client.put(LAYOUT + "/draft", headers=hdr, json={"body": {"ops": []}, "note": "c"})
    assert client.post(LAYOUT + "/publish", headers=hdr, json={"note": "c"}).status_code == 200      # 生效版變成 3
    monkeypatch.setattr(R, "_opt_in_enforced", lambda conn, kind: kind == "layout")
    r = client.post(LAYOUT + "/restore/1", headers=hdr, json={"preview_hash": pv})
    assert r.status_code == 409 and r.json()["code"] == "preview_stale"


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
    assert json.loads(out.stdout.strip()) == [["h1", None], "/api/def-governance/layout/module:suppliers/impact?scope=company"]   # 前端腳本的輸入就是 suppliers（與後端夾具無關）


def test_every_restore_caller_that_has_governance_sends_the_version_preview():
    """還原端點在強制範圍內要帶『這一版』的預覽雜湊：面板與三個有 govOn 的編輯器都要先取（layout-editor.js 屬 3c，另行接）。"""
    for f in ("def-governance.js", "expense-types.js", "remit-kinds-settings.js", "module-builder-output.js"):
        src = (ROOT / "frontend" / "js" / f).read_text(encoding="utf-8")
        assert "preview_hash = " in src and ("previewRestore" in src or "&version=" in src), f
