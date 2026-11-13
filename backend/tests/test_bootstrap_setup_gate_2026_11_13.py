# -*- coding: utf-8 -*-
"""bootstrap × 本公司資料設定閘門（COMPANY-SETUP-GATE）：未設定時 bootstrap 不可以成為繞過 428 的後門。

用真的閘門判定（company_gate marker）；每題一個全新測試庫＝未設定。
"""
import pytest

from routers import bootstrap as B

pytestmark = pytest.mark.company_gate


def _login(client, make_user, name, role):
    u, pw = make_user(username=name, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.mark.parametrize("role", ("superadmin", "admin", "sales"))
def test_unconfigured_bootstrap_gives_only_whitelisted_sections(client, make_user, role):
    h = _login(client, make_user, "bg_" + role, role)
    # 前提：原端點確實被 428 擋住（非白名單者）／放行（白名單者）
    for name, path in B.ORIGINAL_PATH.items():
        if name == "onlineUsers" and role != "superadmin":
            continue
        code = client.get(path, headers=h).status_code
        if name in B.SETUP_GATE_OK:
            assert code == 200, (role, name, code)
        elif name in ("totp", "moduleCounts") and role not in ("superadmin", "admin"):
            continue
        else:
            assert code == 428, (role, name, code)
    r = client.get("/api/bootstrap", headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    gave = {k for k in d if k not in ("v", "errors")}
    assert gave == set(B.sections_for(role, True))
    assert gave <= B.SETUP_GATE_OK
    # 被擋的區段：不給資料、errors 記 428，且與原端點的狀態一致
    for name in set(B.sections_for(role, False)) - gave:
        assert d["errors"][name] == 428 and name not in d, (role, name)
    # 給的區段與原端點逐欄相同
    for name in gave:
        assert d[name] == client.get(B.ORIGINAL_PATH[name], headers=h).json(), (role, name)
    assert d["menu"]["companySetup"]["blocked"] is True


def test_configured_bootstrap_gives_everything(client, make_user):
    """正對照：確認本公司資料之後，同一個帳號拿到完整區段（上面那題的限制確實來自閘門，不是別的原因）。"""
    from tests.test_company_setup_core_2026_09_28 import make_ubn
    h = _login(client, make_user, "bg_boss", "superadmin")
    body = {"name": "測試乙股份有限公司", "tax_id": make_ubn("2345670"), "contact_info": "Tel: 02-1234-5678", "confirmIdentity": True}
    assert client.put("/api/settings/company-profile", json=body, headers=h).status_code == 200
    d = client.get("/api/bootstrap", headers=h).json()
    assert {k for k in d if k not in ("v", "errors")} == set(B.sections_for("superadmin", False))
    assert d["errors"] == {}
