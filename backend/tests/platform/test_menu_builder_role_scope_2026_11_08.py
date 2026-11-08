# -*- coding: utf-8 -*-
"""BP-1 選單建構器補「角色層」（T78；CUSTOMIZATION-SPEC）。

驗證通用的 `/api/definitions/layout/module:<模組>?scope=role:<角色>` 對側欄的 relabel／move.to 的整條路：
存草稿 → 發布 → 該角色登入後 `/api/platform/menu` 的 `layout` 套到 → 沒有角色層的人仍看公司層 → 角色層「整份取代」公司層（不是合併）。
再加預覽端點的 `scope`：角色層預覽必須指定一位該角色的在職帳號（模組勾選是每個人的，不是每個角色的）。
不綁特定 L2：任取一個已載入、有選單項的模組。
"""
import json

import pytest

from core import registry
from helpers import menu_builder as MB


def _pick():
    for m in registry.loaded():
        for p in (m.manifest or {}).get("pages") or []:
            perm = (p.get("menu") or {}).get("perm") if isinstance(p, dict) else None
            if isinstance(p, dict) and p.get("menu") and not ({"cashier", "finance", "financial_view"} & set(perm if isinstance(perm, list) else [])):
                return m.key, p["path"], m.manifest
    pytest.skip("沒有已載入、宣告選單項的模組 ⇒ 無對象")


def _perm_of(man, href):
    for p in man.get("pages") or []:
        if isinstance(p, dict) and p.get("path") == href and p.get("menu"):
            perm = p["menu"]["perm"]
            return list(perm) if isinstance(perm, list) else []
    return []


def _login(client, make_user, name, role, modules=None):
    u, pw = make_user(username=name, role=role, **({"modules": modules} if modules is not None else {}))[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]}


def _on(monkeypatch, value=True):
    monkeypatch.setattr(MB, "enabled", lambda conn=None: value)


def _find(groups, key, href):
    return [(g["key"], it) for g in groups for it in g["items"] if it["href"] == href and it.get("module") == key]


def _publish(client, h, key, scope, ops):
    """走 HTTP（跟 menu-editor.js 同一條）：存草稿 → 發布。⇒ 發布回應。"""
    url = "/api/definitions/layout/module:%s" % key
    r = client.put(url + "/draft?scope=" + scope, json={"body": {"ops": ops}}, headers=h)
    assert r.status_code == 200 and r.json()["problems"] == [], r.text
    r2 = client.post(url + "/publish?scope=" + scope, json={"note": "t", "base_etag": r.json()["etag"]}, headers=h)
    assert r2.status_code == 200, r2.text
    assert not r2.json().get("pending"), "治理旗標預設關 ⇒ 直接發布"
    return r2.json()


def _other_group(client, h, key, href):
    """這位使用者看得到、不含 hub 項、且不是該項目所在的另一個群組鍵；找不到 ⇒ skip。"""
    groups = client.get("/api/platform/menu", headers=h).json()["groups"]
    here = _find(groups, key, href)
    assert here, "正對照：這位使用者看得到被測項目"
    for g in groups:
        if g["key"] != here[0][0] and not any(it.get("hub") for it in g["items"]):
            return here[0][0], g["key"]
    pytest.skip("這位使用者只看得到一個群組 ⇒ 沒有可換的目的群組")


def _setup(client, make_user, monkeypatch, tag):
    key, href, man = _pick()
    perm = _perm_of(man, href)
    h_sa = _login(client, make_user, "rs_sa_" + tag, "superadmin")
    h_ad = _login(client, make_user, "rs_ad_" + tag, "admin", modules=perm)
    h_sl = _login(client, make_user, "rs_sl_" + tag, "sales", modules=perm)
    _on(monkeypatch, True)
    return key, href, "%s:%s/sidebar" % (key, href), h_sa, h_ad, h_sl


def test_role_layer_relabel_and_move_to_apply_to_that_role_only(client, make_user, monkeypatch):
    """(1) 角色層的改名＋換群組：發布後該角色登入看到；沒有該角色層的人仍看公司層（公司層的改名）。"""
    key, href, tgt, h_sa, h_ad, h_sl = _setup(client, make_user, monkeypatch, "a")
    g0, g1 = _other_group(client, h_ad, key, href)
    _publish(client, h_sa, key, "company", [{"op": "relabel", "target": tgt, "label": "公司名"}])
    for h in (h_ad, h_sl):
        got = _find(client.get("/api/platform/menu", headers=h).json()["layout"]["groups"], key, href)
        assert got and got[0][1]["label"] == "公司名" and got[0][0] == g0, "正對照：公司層對兩個角色都生效"
    _publish(client, h_sa, key, "role:admin", [{"op": "relabel", "target": tgt, "label": "管理員名"},
                                                {"op": "move", "target": tgt, "to": "group:" + g1}])
    ad = client.get("/api/platform/menu", headers=h_ad).json()
    got = _find(ad["layout"]["groups"], key, href)
    assert got and got[0][1]["label"] == "管理員名" and got[0][0] == g1, ad["layout"]
    assert got[0][1]["href"] == href and ad["denied"] == client.get("/api/platform/menu", headers=h_ad).json()["denied"], "只是顯示：href／denied 不變"
    sl = client.get("/api/platform/menu", headers=h_sl).json()
    got = _find(sl["layout"]["groups"], key, href)
    assert got and got[0][1]["label"] == "公司名" and got[0][0] == g0, "沒有角色層的 sales 仍看公司層"
    sa = _find(client.get("/api/platform/menu", headers=h_sa).json()["layout"]["groups"], key, href)
    assert sa and sa[0][1]["label"] == "公司名", "別的角色（superadmin）也不受 admin 的角色層影響"


def test_role_layer_replaces_company_layer_for_that_module(client, make_user, monkeypatch):
    """(2) 角色層存在 ⇒ 該角色在這個模組『整份』改用角色層（不是和公司層逐項合併）：公司層的改名在 admin 身上消失。"""
    key, href, tgt, h_sa, h_ad, _h_sl = _setup(client, make_user, monkeypatch, "b")
    g0, g1 = _other_group(client, h_ad, key, href)
    _publish(client, h_sa, key, "company", [{"op": "relabel", "target": tgt, "label": "公司名"}])
    _publish(client, h_sa, key, "role:admin", [{"op": "move", "target": tgt, "to": "group:" + g1}])
    got = _find(client.get("/api/platform/menu", headers=h_ad).json()["layout"]["groups"], key, href)
    assert got and got[0][0] == g1 and got[0][1]["label"] != "公司名", "角色層沒寫改名 ⇒ 不繼承公司層的改名"


def test_role_layer_publish_rejected_when_builder_off(client, make_user, monkeypatch):
    """(3) 旗標關著時，角色層同樣不接受改名／換群組（驗證在 layout 驗證器，與 scope 無關）；開啟後正對照通過。"""
    key, href, tgt, h_sa, _h_ad, _h_sl = _setup(client, make_user, monkeypatch, "c")
    body = {"body": {"ops": [{"op": "relabel", "target": tgt, "label": "新名"}]}}
    url = "/api/definitions/layout/module:%s/draft?scope=role:admin" % key
    _on(monkeypatch, False)
    assert MB.OFF_REASON in json.dumps(client.put(url, json=body, headers=h_sa).json(), ensure_ascii=False)
    _on(monkeypatch, True)
    r = client.put(url, json=body, headers=h_sa)
    assert r.status_code == 200 and r.json()["problems"] == []


def test_preview_scope_role_needs_a_user_of_that_role(client, make_user, monkeypatch):
    """(4) 預覽端點 scope：company／不帶 ⇒ 與過去相同；role:<R> ⇒ 必須指定一位角色是 R 的在職帳號（否則 422，說明原因）；
    預覽的『目前』＝該帳號角色實際生效的選單（有角色層用角色層）。"""
    key, href, tgt, h_sa, h_ad, _h_sl = _setup(client, make_user, monkeypatch, "d")
    g0, g1 = _other_group(client, h_ad, key, href)
    op = {"op": "relabel", "target": tgt, "label": "預覽名"}
    url = "/api/platform/menu/preview"
    assert client.post(url, json={"ops": [op]}, headers=h_sa).status_code == 200
    assert client.post(url, json={"ops": [op], "scope": "company"}, headers=h_sa).status_code == 200
    for bad in ({"scope": "role:admin"},                                  # 沒指定帳號
                {"scope": "role:admin", "user": "rs_sl_d"},               # 帳號是 sales
                {"scope": "role:admin", "user": "rs_sa_d"},               # 帳號是 superadmin
                {"scope": "role:???"}, {"scope": "global"}, {"scope": 5}):
        r = client.post(url, json=dict({"ops": [op]}, **bad), headers=h_sa)
        assert r.status_code == 422, (bad, r.status_code, r.text)
    _publish(client, h_sa, key, "role:admin", [{"op": "move", "target": tgt, "to": "group:" + g1}])
    r = client.post(url, json={"ops": [op], "scope": "role:admin", "user": "rs_ad_d"}, headers=h_sa)
    assert r.status_code == 200, r.text
    d = r.json()
    assert _find(d["current"], key, href)[0][0] == g1, "目前＝角色層已生效（已搬到 g1）"
    assert _find(d["preview"], key, href)[0][1]["label"] == "預覽名" and d["role"] == "admin"


# ── 治理（builder_governance.enabled）：角色層首次發布的放寬分類基準 ────────────────────────────
def _draft_publish(client, h, key, scope, ops):
    """存草稿 → 發布；不斷言結果，⇒ 發布回應（可能是 pending）。"""
    url = "/api/definitions/layout/module:%s" % key
    r = client.put(url + "/draft?scope=" + scope, json={"body": {"ops": ops}}, headers=h)
    assert r.status_code == 200 and r.json()["problems"] == [], r.text
    return client.post(url + "/publish?scope=" + scope, json={"note": "t", "base_etag": r.json()["etag"]}, headers=h)


def test_governance_role_layer_first_publish_is_compared_with_the_company_layer(client, make_user, monkeypatch):
    """K 審必修：角色層第一次發布以『公司層』為基準（角色層整份取代公司層）——
    公司層有 hide、角色層首發不帶那個 hide ＝ 放寬（待第二位最高管理者核准），不能因為角色層自己是空的就當成『全新增』直接發布。
    原樣複製公司層的 hide ＝ 不變（直接發布）；已有角色層 ⇒ 跟自己的上一版比（維持舊行為）。"""
    from routers import def_pipeline as P
    key, href, tgt, h_sa, _h_ad, _h_sl = _setup(client, make_user, monkeypatch, "g")
    monkeypatch.setattr(P, "enabled", lambda conn=None: True)
    hide, rel = {"op": "hide", "target": tgt}, {"op": "relabel", "target": tgt, "label": "角色名"}
    r = _draft_publish(client, h_sa, key, "company", [hide])
    assert r.status_code == 200 and not r.json().get("pending"), "公司層收緊（加 hide）⇒ 直接發布"
    # 對照組：公司層拿掉 hide 本來就是放寬（分類器本身沒問題）
    # 角色層首發、不含公司層的 hide ⇒ 放寬 ⇒ pending
    r = _draft_publish(client, h_sa, key, "role:admin", [rel])
    assert r.status_code == 200 and r.json().get("pending") is True, r.text
    assert any("hide" in x for x in r.json()["reasons"]), r.json()
    # 原樣複製公司層的 hide（UI 沒動它）＋改名 ⇒ 不變 ⇒ 直接發布
    r = _draft_publish(client, h_sa, key, "role:sales", [hide, rel])
    assert r.status_code == 200 and not r.json().get("pending") and r.json().get("version") == 1, r.text
    # 已有角色層（sales v1 = [hide, rel]）：跟自己的上一版比 ⇒ 拿掉 hide ＝ 放寬 ⇒ pending；只改名 ⇒ 直接發布
    r = _draft_publish(client, h_sa, key, "role:sales", [rel])
    assert r.json().get("pending") is True, r.text


def test_governance_baseline_does_not_apply_without_a_company_layer_or_to_company_scope(client, make_user, monkeypatch):
    """沒有公司層 ⇒ 基準＝空（與過去相同）：角色層首發 [relabel] ⇒ 不變；公司層首發不受影響。"""
    from routers import def_pipeline as P
    key, href, tgt, h_sa, _h_ad, _h_sl = _setup(client, make_user, monkeypatch, "h")
    monkeypatch.setattr(P, "enabled", lambda conn=None: True)
    r = _draft_publish(client, h_sa, key, "role:engineer", [{"op": "relabel", "target": tgt, "label": "x"}])
    assert r.status_code == 200 and not r.json().get("pending"), r.text
    r = _draft_publish(client, h_sa, key, "company", [{"op": "hide", "target": tgt}])
    assert r.status_code == 200 and not r.json().get("pending"), "公司層首發 hide（收緊）照舊直接發布"


def test_impact_of_first_role_layer_diffs_against_the_company_layer(client, make_user, monkeypatch):
    """影響預覽：角色層首發的差異跟公司層比（實際效果），並標明比的是哪一層；已有角色層 ⇒ 沒有這個標記。"""
    from routers import def_governance as G
    from routers import def_pipeline as P
    key, href, tgt, h_sa, _h_ad, _h_sl = _setup(client, make_user, monkeypatch, "i")
    monkeypatch.setattr(P, "enabled", lambda conn=None: True)
    monkeypatch.setattr(G, "enabled", lambda conn=None: True)
    hide, rel = {"op": "hide", "target": tgt}, {"op": "relabel", "target": tgt, "label": "角色名"}
    _draft_publish(client, h_sa, key, "company", [hide])
    url = "/api/definitions/layout/module:%s/draft?scope=role:admin" % key
    assert client.put(url, json={"body": {"ops": [hide, rel]}}, headers=h_sa).status_code == 200
    d = client.get("/api/def-governance/layout/module:%s/impact?scope=role%%3Aadmin" % key, headers=h_sa).json()
    assert d.get("changesBase") == "company"
    assert len(d["changes"]) == 1 and "relabel" in json.dumps(d["changes"], ensure_ascii=False), "只有改名是新的；複製來的 hide 不是變更"
    assert client.get("/api/def-governance/layout/module:%s/impact?scope=company" % key, headers=h_sa).json().get("changesBase") is None
