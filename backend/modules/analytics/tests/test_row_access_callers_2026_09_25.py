"""自 `tests/test_row_access_callers_2026_09_25.py` 拆出（M08 搬遷反向控制：這幾題需要營運分析模組，拿掉模組時一起消失）。"""
import dataclasses
import json
from tests.test_row_access_2026_09_25 import CASE, DEV
from tests.test_row_access_callers_2026_09_25 import (  # noqa: E402,F401  含 fixture
    QNO,
    _setup,
)


def test_activity_feed_matches_case_list_rule(client, make_user):
    h = _setup(client, make_user)
    got = {}
    for who, hdr in h.items():
        r = client.get("/api/dashboard/activity-feed", headers=hdr)
        assert r.status_code == 200, r.text
        got[who] = any(x.get("source") == "comment" and QNO in (x.get("link") or "")
                       for x in r.json()["items"])
    assert got == {"owner": True, "asg": True, "cash": True, "outsider": False}
