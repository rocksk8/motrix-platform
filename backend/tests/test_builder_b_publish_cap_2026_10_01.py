# -*- coding: utf-8 -*-
"""建構器方案 B：同一個掛載點最多 MAX_TABS_PER_POINT 個已發布自訂模組頁籤——**發布時**擋（2e 骨架只有函式、沒接上發布）。
正對照：第 8 個通過；第 9 個 ⇒ 422（附問題清單）；已發布的模組自己再發新版不被自己擋。"""
POINT = "daily_tasks.daily-tasks"


def _body(key):
    return {"name": "掛載%s" % key, "permission": "custom.%s" % key, "numbering": {"prefix": "MC", "date": "", "digits": 3},
            "fields": [{"key": "a", "label": "甲", "type": "text", "dataClass": "T1"}],
            "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿"}, {"key": "done", "label": "完成", "final": True}],
                         "transitions": [{"key": "submit", "label": "送出", "from": "draft", "to": "done"}]},
            "ui": {"form": {"groups": []}, "list": {"columns": []}}, "mount": {"point": POINT}}


def _pub(client, h, key):
    r = client.put("/api/definitions/custom_module/%s/draft" % key, headers=h, json={"body": _body(key)})
    assert r.status_code == 200 and r.json()["problems"] == [], r.text
    return client.post("/api/definitions/custom_module/%s/publish" % key, headers=h, json={})


def test_ninth_tab_on_one_mount_point_is_refused_at_publish(client, make_user):
    from core import mounts
    u, p = make_user(username="mc_sa", role="superadmin")[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    for i in range(mounts.MAX_TABS_PER_POINT):
        assert _pub(client, h, "mc_%d" % i).status_code == 200, i                       # 正對照：到上限為止都能發布
    r = _pub(client, h, "mc_over")
    assert r.status_code == 422, r.text
    assert any(x["path"] == "mount.point" for x in r.json()["problems"]), r.text
    assert _pub(client, h, "mc_0").status_code == 200                                    # 已在點上的模組發新版：不被自己算進去
