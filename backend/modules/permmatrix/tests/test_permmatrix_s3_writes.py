# -*- coding: utf-8 -*-
"""權限矩陣 PM-S3：寫入端點（角色格、個人覆寫、待生效撤銷／核准、版本回溯、一鍵復原）。服務層規則已由 test_permmatrix_m2.py 守；這裡守端點層：
最高管理者限定、輸入嚴格驗證、白話預覽不外露能力鍵、高風險放寬走待生效＋第二位最高管理者核准、稽核同交易、超管不可被鎖死。規格 SPEC PMX17。"""
import re

import pytest

import db
from core import capabilities as C
from helpers import auth as A
from helpers import perm as P
from modules.permmatrix import service as S


def _d(key, label, legacy, **kw):
    return dict(key=key, label=label, desc=label + "（測試用的一句話說明）", impact="勾選後可以" + label + "（測試用的影響說明）", legacy=legacy, **kw)


DECLS = [
    _d("zz.doc.view", "檢視測試單", {"role": ["admin", "sales"]}),
    _d("zz.doc.pay", "付款測試單", {"role": ["admin"]}),
    _d("zz.doc.config", "設定測試單", {"role": ["admin"]}, delegable=False),
]
CAPS, PROBLEMS = C.collect({"zz": {"capabilities": DECLS}}, valid_roles=A.VALID_ROLES)
B = "/api/permmatrix"


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture(autouse=True)
def _env(client, monkeypatch):
    assert not PROBLEMS, PROBLEMS
    monkeypatch.setattr(C, "all_caps", lambda: dict(CAPS))
    monkeypatch.setattr(C, "get", lambda k: CAPS.get(k))
    monkeypatch.setattr(C, "signature", lambda: "s3-test")
    monkeypatch.setattr(A, "_finance_mode", lambda: "off")
    monkeypatch.setattr(P, "_source", None)
    monkeypatch.setattr(P, "_provider", lambda: S.load_matrix)
    monkeypatch.setattr(P, "_last_good", {"m": None})
    monkeypatch.setattr(P, "_degraded", {"on": False})
    P.invalidate()
    yield
    P.invalidate()


@pytest.fixture
def su(client, make_user):
    u, p = make_user(username="pm_s3_su", role="superadmin")
    return _login(client, u, p)


@pytest.fixture
def su2(client, make_user):
    u, p = make_user(username="pm_s3_su2", role="superadmin")
    return _login(client, u, p)


def _uid(name):
    c = db.get_db()
    try:
        return c.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()["id"]
    finally:
        c.close()


def _cell(client, h, key, role):
    return {c["key"]: c for c in client.get(B + "/matrix", headers=h).json()["caps"]}[key]["cells"][role]


def _count(sql):
    c = db.get_db()
    try:
        return c.execute(sql).fetchone()[0]
    finally:
        c.close()


WRITES = [("post", "/role-cap", {"role": "sales", "cap": "zz.doc.view", "granted": False}),
          ("post", "/role-cap/preview", {"role": "sales", "cap": "zz.doc.view", "granted": False}),
          ("post", "/user-override", {"user_id": 1, "cap": "zz.doc.view", "effect": "deny"}),
          ("post", "/user-override/preview", {"user_id": 1, "cap": "zz.doc.view", "effect": "deny"}),
          ("delete", "/user-override?user_id=1&cap=zz.doc.view", None),
          ("post", "/pending/1/cancel", {"reason": "測試撤銷"}),
          ("post", "/pending/1/approve", {"reason": "測試核准"}),
          ("post", "/versions/1/restore", {"reason": "測試回溯"}),
          ("post", "/undo", None),
          ("post", "/role-cap/batch", {"changes": [{"role": "sales", "cap": "zz.doc.view", "granted": False}], "planHash": "x"}),
          ("post", "/role-cap/batch/preview", {"changes": [{"role": "sales", "cap": "zz.doc.view", "granted": False}]})]


@pytest.mark.parametrize("method,path,body", WRITES)
def test_every_write_requires_superadmin_and_changes_nothing(client, make_user, method, path, body):
    before = _count("SELECT COUNT(*) FROM perm_role_caps") + _count("SELECT COUNT(*) FROM perm_user_overrides") + _count("SELECT COUNT(*) FROM perm_versions")
    kw = {"json": body} if body is not None else {}
    assert getattr(client, method)(B + path, **kw).status_code in (401, 403)
    u, p = make_user(username="pm_s3_admin", role="admin")
    assert getattr(client, method)(B + path, headers=_login(client, u, p), **kw).status_code == 403
    assert before == _count("SELECT COUNT(*) FROM perm_role_caps") + _count("SELECT COUNT(*) FROM perm_user_overrides") + _count("SELECT COUNT(*) FROM perm_versions")


def test_low_risk_role_cap_applies_immediately_with_audit_and_version(client, su):
    r = client.post(B + "/role-cap", headers=su, json={"role": "sales", "cap": "zz.doc.view", "granted": False, "reason": ""})
    assert r.status_code == 200 and r.json()["changed"] is True and r.json()["version"]
    assert _cell(client, su, "zz.doc.view", "sales") == {"granted": False, "seeded": True, "changed": True}
    assert _count("SELECT COUNT(*) FROM audit_log WHERE action='permmatrix.role_cap.set'") == 1
    assert client.post(B + "/role-cap", headers=su, json={"role": "sales", "cap": "zz.doc.view", "granted": False}).json()["changed"] is False


def test_high_risk_grant_waits_for_confirm_period_and_second_superadmin(client, su, su2):
    r = client.post(B + "/role-cap", headers=su, json={"role": "sales", "cap": "zz.doc.pay", "granted": True, "reason": "業務需要代為登錄付款"})
    j = r.json()
    assert r.status_code == 200 and j["pending"] is True and j["approvalsRequired"] == 1
    assert _cell(client, su, "zz.doc.pay", "sales")["granted"] is False                 # 還沒生效
    items = client.get(B + "/pending", headers=su).json()["items"]
    assert [i["id"] for i in items] == [j["id"]]
    assert client.post(B + "/pending/%d/approve" % j["id"], headers=su, json={"reason": "自己核准"}).status_code == 409      # 申請人不能核准自己的
    ok = client.post(B + "/pending/%d/approve" % j["id"], headers=su2, json={"reason": "同意"})
    assert ok.status_code == 200 and ok.json()["approvals"] == 1
    assert _cell(client, su, "zz.doc.pay", "sales")["granted"] is False                 # 核准不等於立刻生效，仍要等確認期間


def test_high_risk_grant_requires_reason(client, su):
    r = client.post(B + "/role-cap", headers=su, json={"role": "sales", "cap": "zz.doc.pay", "granted": True, "reason": ""})
    assert r.status_code == 400 and "原因" in r.json()["detail"]
    assert client.get(B + "/pending", headers=su).json()["items"] == []


def test_cancel_pending_needs_reason_and_removes_it(client, su):
    pid = client.post(B + "/role-cap", headers=su, json={"role": "sales", "cap": "zz.doc.pay", "granted": True, "reason": "業務需要代為登錄付款"}).json()["id"]
    assert client.post(B + "/pending/%d/cancel" % pid, headers=su, json={"reason": ""}).status_code == 400
    assert client.post(B + "/pending/%d/cancel" % pid, headers=su, json={"reason": "不需要了"}).status_code == 200
    assert client.get(B + "/pending", headers=su).json()["items"] == []
    assert client.post(B + "/pending/%d/cancel" % pid, headers=su, json={"reason": "再撤一次"}).status_code == 409


def test_strict_input_validation(client, su):
    base = {"role": "sales", "cap": "zz.doc.view", "reason": ""}
    assert client.post(B + "/role-cap", headers=su, json={**base, "granted": "yes"}).status_code == 422       # 不收字串當布林
    assert client.post(B + "/role-cap", headers=su, json={**base, "granted": 1}).status_code == 422
    assert client.post(B + "/role-cap", headers=su, json={"role": "sales", "cap": "zz.doc.view"}).status_code == 422
    assert client.post(B + "/role-cap", headers=su, json={**base, "cap": "no.such.cap", "granted": True}).status_code == 400
    assert client.post(B + "/role-cap", headers=su, json={**base, "role": "nobody", "granted": True}).status_code == 400
    assert client.post(B + "/user-override", headers=su, json={"user_id": "1", "cap": "zz.doc.view", "effect": "deny"}).status_code == 422


def test_superadmin_cannot_be_locked_out(client, su):
    r = client.post(B + "/role-cap", headers=su, json={"role": "superadmin", "cap": "zz.doc.view", "granted": False})
    assert r.status_code == 400
    me = _uid("pm_s3_su")
    r = client.post(B + "/user-override", headers=su, json={"user_id": me, "cap": "zz.doc.view", "effect": "deny"})
    assert r.status_code == 400
    assert _count("SELECT COUNT(*) FROM perm_role_caps") == 0 and _count("SELECT COUNT(*) FROM perm_user_overrides") == 0


def test_non_delegable_cap_cannot_be_granted(client, su):
    r = client.post(B + "/role-cap", headers=su, json={"role": "sales", "cap": "zz.doc.config", "granted": True, "reason": "想給業務設定權"})
    assert r.status_code == 400 and "不可委派" in r.json()["detail"]


def test_user_override_set_and_clear_roundtrip(client, su, make_user):
    make_user(username="pm_s3_eng", role="engineer")
    uid = _uid("pm_s3_eng")
    assert client.post(B + "/user-override", headers=su, json={"user_id": uid, "cap": "zz.doc.view", "effect": "deny", "reason": "測試"}).json()["changed"] is True
    ov = [u for u in client.get(B + "/users", headers=su).json()["users"] if u["id"] == uid][0]["overrides"]
    assert ov and ov[0]["effect"] == "deny"
    assert client.post(B + "/user-override", headers=su, json={"user_id": uid, "cap": "zz.doc.view", "effect": "bogus"}).status_code == 400
    r = client.delete(B + "/user-override?user_id=%d&cap=zz.doc.view" % uid, headers=su)
    assert r.status_code == 200 and r.json()["changed"] is True
    assert [u for u in client.get(B + "/users", headers=su).json()["users"] if u["id"] == uid][0]["overrides"] == []


def test_preview_is_plain_chinese_and_does_not_write(client, su, make_user):
    make_user(username="pm_s3_eng2", role="engineer")
    uid = _uid("pm_s3_eng2")
    before = _count("SELECT COUNT(*) FROM perm_versions") + _count("SELECT COUNT(*) FROM audit_log")
    p1 = client.post(B + "/role-cap/preview", headers=su, json={"role": "sales", "cap": "zz.doc.pay", "granted": True}).json()
    p2 = client.post(B + "/user-override/preview", headers=su, json={"user_id": uid, "cap": "zz.doc.pay", "effect": "allow"}).json()
    assert before == _count("SELECT COUNT(*) FROM perm_versions") + _count("SELECT COUNT(*) FROM audit_log")
    for p in (p1, p2):
        assert p["pending"] is True and "確認期間" in p["effective"]
        text = " ".join(str(v) for v in p.values())
        assert not re.search(r"\bzz\.doc\.\w+", text), text           # 畫面文字不外露能力鍵
        assert any("一" <= ch <= "鿿" for ch in p["sentence"])
    assert client.post(B + "/role-cap/preview", headers=su, json={"role": "sales", "cap": "zz.doc.view", "granted": True}).json()["pending"] is False


def test_undo_and_restore_walk_back_step_by_step(client, su):
    assert client.post(B + "/undo", headers=su).status_code == 400                      # 還沒有任何變更
    client.post(B + "/role-cap", headers=su, json={"role": "sales", "cap": "zz.doc.view", "granted": False})
    v1 = client.get(B + "/versions", headers=su).json()["items"][0]["id"]
    client.post(B + "/role-cap", headers=su, json={"role": "admin", "cap": "zz.doc.view", "granted": False})
    assert client.post(B + "/undo", headers=su).status_code == 200
    assert _cell(client, su, "zz.doc.view", "admin")["granted"] is True and _cell(client, su, "zz.doc.view", "sales")["granted"] is False
    assert client.post(B + "/undo", headers=su).status_code == 200
    assert _cell(client, su, "zz.doc.view", "sales")["granted"] is True
    assert client.post(B + "/versions/%d/restore" % v1, headers=su, json={"reason": ""}).status_code == 400
    assert client.post(B + "/versions/%d/restore" % v1, headers=su, json={"reason": "回到第一次調整"}).status_code == 200
    assert _cell(client, su, "zz.doc.view", "sales")["granted"] is False
    assert client.post(B + "/versions/999999/restore", headers=su, json={"reason": "不存在的版本"}).status_code == 404


def test_page_edits_only_through_preview_and_has_init_guard():
    """頁面靜態守門：每個寫入都先走 preview 或確認對話框；有 _initDone 守衛；不顯示能力鍵（鍵只出現在 :data-testid 與請求內容）。"""
    from pathlib import Path
    from core import source_tree
    html = source_tree.page_file("permission-matrix.html").read_text(encoding="utf-8")
    assert "_initDone" in html and "/role-cap/batch/preview" in html and "/user-override/preview" in html
    assert html.count("this._open(") >= 5 and "confirmDlg" in html and "applyStage" in html            # 所有寫入都經確認對話框；角色格改走暫存區批次（預覽之後才寫）
    assert "/role-cap'" not in html and "/role-cap/preview" not in html          # 點格子不再直接送單格請求
    assert "!c.wired" in html                                                  # 未接入的格子不可勾
    visible = re.findall(r'x-text="([^"]*)"', html)
    assert not [t for t in visible if "c.key" in t and "testid" not in t and "option" not in t], visible


# ── 暫存區批次（設定矩陣 S4c）────────────────────────────────────────────────────────────
def _batch(client, h, changes, reason="", preview_only=False, plan_hash=None):
    pv = client.post(B + "/role-cap/batch/preview", headers=h, json={"changes": changes})
    if preview_only:
        return pv
    assert pv.status_code == 200, pv.text
    return client.post(B + "/role-cap/batch", headers=h, json={"changes": changes, "reason": reason, "planHash": plan_hash or pv.json()["planHash"]})


MIX = [{"role": "sales", "cap": "zz.doc.view", "granted": False},      # 低風險：立即
       {"role": "sales", "cap": "zz.doc.pay", "granted": True},        # 放寬高風險：待生效
       {"role": "admin", "cap": "zz.doc.view", "granted": True}]       # 已經是這個狀態：不變


def test_batch_preview_writes_nothing_and_classifies_every_cell(client, su):
    before = _count("SELECT COUNT(*) FROM perm_role_caps") + _count("SELECT COUNT(*) FROM perm_versions") + _count("SELECT COUNT(*) FROM config_changes")
    d = _batch(client, su, MIX, preview_only=True).json()
    assert {(x["role"], x["cap"]): x["status"] for x in d["cells"]} == {("sales", "zz.doc.view"): "immediate", ("sales", "zz.doc.pay"): "pending", ("admin", "zz.doc.view"): "nochange"}
    assert d["needsReason"] is True and d["summary"] == {"changed": 2, "immediate": 1, "pending": 1, "unchanged": 1} and d["planHash"]
    assert before == _count("SELECT COUNT(*) FROM perm_role_caps") + _count("SELECT COUNT(*) FROM perm_versions") + _count("SELECT COUNT(*) FROM config_changes")


def test_batch_apply_mixes_immediate_and_pending_with_one_version(client, su):
    v0 = _count("SELECT COUNT(*) FROM perm_versions")
    r = _batch(client, su, MIX, reason="業務需要代為登錄付款")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["applied"] == [{"role": "sales", "cap": "zz.doc.view"}] and len(j["pending"]) == 1 and j["version"]
    assert _cell(client, su, "zz.doc.view", "sales")["granted"] is False
    assert _cell(client, su, "zz.doc.pay", "sales")["granted"] is False, "高風險放寬要等確認期間，不可立刻生效"
    assert _count("SELECT COUNT(*) FROM perm_versions") == v0 + 1, "整批立即生效的格合併成一個版本（一鍵復原＝整批還原）"
    assert _count("SELECT COUNT(*) FROM audit_log WHERE action='permmatrix.role_cap.set'") == 1
    assert len(client.get(B + "/pending", headers=su).json()["items"]) == 1


def test_batch_with_high_risk_loosening_needs_a_reason_and_writes_nothing_without_it(client, su):
    r = _batch(client, su, MIX, reason="")
    assert r.status_code == 400 and "原因" in r.json()["detail"]
    assert _cell(client, su, "zz.doc.view", "sales")["granted"] is True, "沒填原因時，連低風險的那格也不可寫（整批同一交易）"
    assert client.get(B + "/pending", headers=su).json()["items"] == []


def test_batch_without_high_risk_needs_no_reason(client, su):
    r = _batch(client, su, [{"role": "sales", "cap": "zz.doc.view", "granted": False}])
    assert r.status_code == 200 and r.json()["needsReason"] is False and len(r.json()["applied"]) == 1


def test_batch_stale_preview_is_409_and_writes_nothing(client, su):
    pv = _batch(client, su, MIX, preview_only=True).json()
    assert client.post(B + "/role-cap", headers=su, json={"role": "sales", "cap": "zz.doc.view", "granted": False}).status_code == 200       # 預覽之後有人先改了一格
    r = client.post(B + "/role-cap/batch", headers=su, json={"changes": MIX, "reason": "業務需要代為登錄付款", "planHash": pv["planHash"]})
    assert r.status_code == 409, r.text
    assert client.get(B + "/pending", headers=su).json()["items"] == []
    assert client.post(B + "/role-cap/batch", headers=su, json={"changes": MIX, "reason": "業務需要代為登錄付款"}).status_code == 400    # 沒帶 planHash


def test_batch_input_validation(client, su):
    for bad in ([], [{"role": "sales", "cap": "zz.doc.view", "granted": "yes"}], [{"role": "sales", "cap": "zz.doc.view"}], ["x"],
                [{"role": "sales", "cap": "zz.doc.view", "granted": False}] * 2,
                [{"role": "superadmin", "cap": "zz.doc.view", "granted": False}], [{"role": "sales", "cap": "no.such.cap", "granted": True}],
                [{"role": "sales", "cap": "zz.doc.config", "granted": True}]):
        r = _batch(client, su, bad, preview_only=True)
        assert r.status_code in (400, 422), (bad, r.status_code)
    assert client.post(B + "/role-cap/batch/preview", headers=su, json={"changes": [{"role": "sales", "cap": "zz.doc.view", "granted": False}] * 201}).status_code == 400


def test_batch_undo_with_the_existing_one_click_undo_restores_the_whole_batch(client, su):
    # 注意：復原＝把取消的格子再授予回去；高風險項（如 zz.doc.pay）的再授予依既有規則要等確認期間，不在「立即復原」之列，所以這裡用一般項
    cells = [{"role": "sales", "cap": "zz.doc.view", "granted": False}, {"role": "admin", "cap": "zz.doc.view", "granted": False}]
    assert _batch(client, su, cells).status_code == 200
    assert _cell(client, su, "zz.doc.view", "admin")["granted"] is False
    assert client.post(B + "/undo", headers=su).status_code == 200
    assert _cell(client, su, "zz.doc.view", "sales")["granted"] is True and _cell(client, su, "zz.doc.view", "admin")["granted"] is True
