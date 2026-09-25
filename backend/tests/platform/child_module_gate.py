"""子行程專用（檔名刻意不是 test_*.py：一般收集不會跑到它）。

由 test_module_selection.py 以 `python -m pytest <本檔>` 啟動，並帶 `MOTRIX_TEST_CHILD_GATE`：
  disabled    ⇒ 模擬「管理者停用了 tender_radar 之後重啟」
  unlicensed  ⇒ 模擬「授權開關打開、金鑰沒包含 tender_radar」
  both        ⇒ 兩者同時成立（優先順序：未授權 ＞ 停用）
必須在 `import main` 之前換掉讀取來源——main 在 import 當下呼叫載入器（這正是「重啟後生效」）。
"""
import os

import pytest

GATE = os.environ.get("MOTRIX_TEST_CHILD_GATE", "")
if not GATE:
    pytest.skip("只在子行程裡跑（由 test_module_selection.py 啟動）", allow_module_level=True)

import helpers.licensing as _lic            # noqa: E402
import helpers.module_switches as _ms       # noqa: E402

if GATE in ("disabled", "both"):
    _ms.read_disabled_at_startup = lambda db_path=None: frozenset({"tender_radar"})
if GATE in ("unlicensed", "both"):
    _lic.LICENSE_GATE_ENABLED = True
    _lic.verify_license = lambda blob=None: {"valid": True, "reason": "ok", "modules": ["some_other_module"],
                                             "kind": "subscription"}

EXPECT = {"disabled": "disabled", "unlicensed": "unlicensed", "both": "unlicensed"}[GATE]


def _auth(client, make_user):
    u, p = make_user(username="gate_sa", role="superadmin", modules=[])
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_gate(client, make_user):
    # 授權開關打開時，整體授權守門（main 的 middleware）看 verify_license()：這裡 reason=ok ⇒ 不擋業務 API，
    # 所以驗到的是「模組層級」的未授權，不是整台被擋。
    import db
    h = _auth(client, make_user)
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO tender_watches (name, keywords, excludes) VALUES ('保留測試', '[\"x\"]', '[]')")
        conn.commit()
        before = conn.execute("SELECT COUNT(*) FROM tender_watches").fetchone()[0]
    finally:
        conn.close()

    # 端點 404（路由沒掛）
    for path in ("/api/tender-radar/watches", "/api/tender-radar/status"):
        assert client.get(path, headers=h).status_code == 404, path

    # 狀態與原因（模組管理頁）
    rows = {m["key"]: m for m in client.get("/api/system/modules", headers=h).json()["modules"]}
    assert rows["tender_radar"]["state"] == EXPECT, rows["tender_radar"]
    assert rows["tender_radar"]["reason"]
    if EXPECT == "unlicensed":
        assert "未授權" in rows["tender_radar"]["reason"] and rows["tender_radar"]["canToggle"] is False

    # 選單：頁面入口列為不可用
    assert "tender-radar.html" in client.get("/api/system/modules/unavailable-pages", headers=h).json()["pages"]

    # 資料不動
    conn = db.get_db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM tender_watches").fetchone()[0] == before
    finally:
        conn.close()
    print("CHILD_GATE_OK", GATE)
