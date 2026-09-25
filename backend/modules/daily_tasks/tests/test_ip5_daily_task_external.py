"""IP-5 `daily_task.external`（M12 提供，M01 案件執行進度取用）：M12 在的時候的正對照。

2026-09-26 自 tests/platform/test_case_stage_connectors.py 移入本模組（拿掉 M12 時這兩題一起消失）；
「M12 不在時勾選照常、明說原因」那一題留在 tests/platform（它驗的是 M01 的退化，M12 不在時也要綠）。
"""
import pytest

from core import registry
from tests.platform.test_case_stage_connectors import _login, _case, _q, _tick  # noqa: F401


@pytest.fixture(autouse=True)
def _inline_bg(monkeypatch):
    """端點的背景同步改成當場執行（同 tests/platform/test_case_stage_connectors.py 的同名夾具）。

    搬檔時漏了這個 ⇒ 斷言與背景執行緒賽跑：單跑多半綠，前面先跑 netplan 測試就穩定紅（2026-09-26 M10 閘門）。"""
    from routers import quotations as q
    monkeypatch.setattr(q, "spawn_bg_thread", lambda target, args=(), **kw: target(*args))


def test_daily_task_connector_provider_is_registered_by_m12(client):
    # 2026-09-26：M12 搬進 modules/，提供者改由 ModuleSpec 宣告，載入器掛模組時登記（client 夾具）
    p = registry.single_provider("daily_task.external")
    assert p is not None and callable(p.upsert) and callable(p.withdraw)


def test_daily_task_connector_with_m12_the_task_and_completion_are_created(client, make_user):
    u, h = _login(client, make_user, "ip5_on")
    _case("MQ-IP5-ON")
    sid, body = _tick(client, h, "MQ-IP5-ON")
    assert "notice" not in body
    tasks = _q("SELECT * FROM daily_tasks WHERE case_no=? AND is_deleted=0", "MQ-IP5-ON")
    assert len(tasks) == 1 and tasks[0]["title"] == "串接工程｜客戶驗收"
    assert _q("SELECT daily_task_id FROM case_stages WHERE id=?", sid)[0]["daily_task_id"] == tasks[0]["id"]
    assert _q("SELECT completed FROM daily_task_completions WHERE task_id=?", tasks[0]["id"])[0]["completed"] == 1
    # 取消勾選 ⇒ 收回
    client.put(f"/api/quotations/MQ-IP5-ON/stages/{sid}", headers=h, json={"done": False})
    assert _q("SELECT is_deleted FROM daily_tasks WHERE id=?", tasks[0]["id"])[0]["is_deleted"] == 1


def test_with_m12_uncheck_and_delete_carry_no_notice(client, make_user):
    """正對照（B-1）：M12 在 ⇒ 取消勾選與刪除階段都真的收回，回應不帶提示。"""
    u, h = _login(client, make_user, "ip5_on2")
    _case("MQ-IP5-ON2")
    sid, _ = _tick(client, h, "MQ-IP5-ON2")
    r = client.put(f"/api/quotations/MQ-IP5-ON2/stages/{sid}", headers=h, json={"done": False, "doneAt": ""})
    assert r.status_code == 200 and "notice" not in r.json(), r.json()
    sid2, _ = _tick(client, h, "MQ-IP5-ON2")
    tid = _q("SELECT daily_task_id FROM case_stages WHERE id=?", sid2)[0]["daily_task_id"]
    assert tid
    assert client.delete(f"/api/quotations/MQ-IP5-ON2/stages/{sid2}", headers=h).json() == {"ok": True}
    assert _q("SELECT is_deleted FROM daily_tasks WHERE id=?", tid)[0]["is_deleted"] == 1
