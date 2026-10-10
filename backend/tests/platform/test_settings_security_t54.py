# -*- coding: utf-8 -*-
"""第 54 班 Train A：放寬需雙人核准、版本邊界、預設組（使用者 2026-10-10 裁示：安全項目雙向可調、放寬要最強管制、可販售的政策預設組）。"""
from datetime import datetime, timedelta

import pytest

from db import get_db
from helpers import config_ledger as L
from helpers import settings_groups  # noqa: F401
from helpers import settings_registry as R


def _field():
    return R.SettingDef("max_mb", "int", 20, min=1, max=500, unit="MB", risk="security", loosen="up", recommended=20,
                        question="每個檔案最大可以多大？", label="單檔上限", help="超過的檔案會被擋下。",
                        impact="影響之後的上傳，立即套用於新上傳。", risk_text="調大後可能讓過大的檔案進入系統。",
                        presets={"嚴格": 5, "標準": 20, "寬鬆": 100})


@pytest.fixture()
def secgrp(client, make_user):
    make_user(username="sec_a", role="superadmin")
    make_user(username="sec_b", role="superadmin")
    c = get_db()
    R.invalidate()
    R.register_group("zz_sec_t54", "安全測試群組", [_field()], help="測試用的安全設定群組。", risk="security")
    yield c
    R._GROUPS.pop("zz_sec_t54", None)
    R.clear_edition_bounds()
    c.close()
    R.invalidate()


def _later(hours=25):
    return (datetime.now() + timedelta(hours=hours)).isoformat(timespec="seconds")


def test_tightening_is_immediate_loosening_needs_second_person(secgrp):
    c = secgrp
    assert R.publish("zz_sec_t54", {"max_mb": 10}, reason="收緊", user="sec_a", conn=c)["changed"] is True
    assert R.get("zz_sec_t54", "max_mb", conn=c) == 10
    out = R.publish("zz_sec_t54", {"max_mb": 100}, reason="放寬", user="sec_a", conn=c)
    assert out["changed"] is False and out["pending"][0]["approvalsRequired"] == 1
    cid = out["pending"][0]["id"]
    assert R.get("zz_sec_t54", "max_mb", conn=c, now=_later()) == 10            # 到時間沒人核准也不生效
    assert L.approve(c, cid, "sec_a")["ok"] is False                            # 申請人不能核准自己的
    assert L.approve(c, cid, "sec_b")["ok"] is True
    assert L.approve(c, cid, "sec_b")["ok"] is False                            # 同一人不能投兩次
    c.commit()
    assert R.get("zz_sec_t54", "max_mb", conn=c) == 10                          # 核准了但還沒滿 24 小時
    assert R.get("zz_sec_t54", "max_mb", conn=c, now=_later()) == 100


def test_materialize_waits_for_approval(secgrp):
    c = secgrp
    cid = R.publish("zz_sec_t54", {"max_mb": 100}, reason="放寬", user="sec_a", conn=c)["pending"][0]["id"]
    assert R.materialize_due(c, now=_later()) == 0                              # 沒核准 ⇒ 不寫進定義
    L.approve(c, cid, "sec_b")
    assert R.materialize_due(c, now=_later()) == 1
    assert R.get("zz_sec_t54", "max_mb", conn=c) == 100


def test_loosening_with_a_single_superadmin_falls_back_to_pending_plus_warning(client, make_user):
    c = get_db()
    try:
        c.execute("UPDATE users SET active=0 WHERE role='superadmin'")
        c.commit()
        make_user(username="only_sa", role="superadmin")
        R.register_group("zz_sec_t54", "安全測試群組", [_field()], help="測試用的安全設定群組。", risk="security")
        out = R.publish("zz_sec_t54", {"max_mb": 50}, reason="放寬", user="only_sa", conn=c)
        assert out["pending"][0]["approvalsRequired"] == 0 and out["warnings"]
        assert R.get("zz_sec_t54", "max_mb", conn=c, now=_later()) == 50
    finally:
        R._GROUPS.pop("zz_sec_t54", None)
        c.close()
        R.invalidate()


def test_edition_bounds_are_code_only_and_enforced(secgrp):
    R.set_edition_bounds("zz_sec_t54", "max_mb", min=5, max=50)
    with pytest.raises(R.SettingError):
        R.publish("zz_sec_t54", {"max_mb": 1}, reason="x", user="sec_a", conn=secgrp)
    with pytest.raises(R.SettingError):
        R.publish("zz_sec_t54", {"max_mb": 200}, reason="x", user="sec_a", conn=secgrp)
    f = [x for x in R.groups()["zz_sec_t54"]["fields"] if x["key"] == "max_mb"][0]
    assert (f["min"], f["max"]) == (5, 50)


def test_profiles_preview_and_apply(secgrp):
    assert set(R.profiles()) == {"嚴格", "標準", "寬鬆"}
    assert [(x["old"], x["new"]) for x in R.profile_preview("嚴格", conn=secgrp)] == [(20, 5)]
    assert R.apply_profile("嚴格", reason="新客戶", user="sec_a", conn=secgrp)["zz_sec_t54"]["changed"] is True
    res = R.apply_profile("寬鬆", reason="放寬", user="sec_a", conn=secgrp)["zz_sec_t54"]      # 放寬走雙人核准
    assert res["changed"] is False and res["pending"][0]["approvalsRequired"] == 1
    with pytest.raises(R.SettingError):
        R.apply_profile("不存在", user="sec_a", conn=secgrp)


def test_no_customer_api_can_set_edition_bounds(client):
    """版本邊界只由程式設定：路由表裡沒有任何端點能改它（正對照：設定中心的寫入端點確實存在）。"""
    from tests._routes import all_routes
    paths = {p for p, methods, _r in all_routes(client.app) if methods & {"POST", "PUT", "PATCH", "DELETE"}}
    assert "/api/settings-center/groups/{group}" in paths
    assert not [p for p in paths if "edition" in p.lower() or "bounds" in p.lower()]
