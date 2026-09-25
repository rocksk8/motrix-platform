"""IP-5 `daily_task.external`（M12 提供，M01 案件執行進度取用）：M12 在的時候的正對照。

2026-09-26 自 tests/platform/test_case_stage_connectors.py 移入本模組（拿掉 M12 時這兩題一起消失）；
「M12 不在時勾選照常、明說原因」那一題留在 tests/platform（它驗的是 M01 的退化，M12 不在時也要綠）。
"""
from core import registry
from tests.platform.test_case_stage_connectors import _login, _case, _q, _tick  # noqa: F401


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
