"""子行程專用（檔名刻意不是 test_*.py：一般收集不會跑到它）。

由 test_module_selection.py 以 `python -m pytest <本檔>` 啟動，並帶：
  MOTRIX_TEST_CHILD_GATE       disabled／unlicensed／both／reenabled／coreonly
  MOTRIX_TEST_CHILD_MODULES    合成模組樹的資料夾（父行程在自己的 tmp 建好）
  MOTRIX_TEST_CHILD_PACKAGE    該資料夾的套件名
  MOTRIX_TEST_CHILD_SETTINGS   （reenabled）父行程用真的 set_enabled 先停用、再啟用的設定庫

🔴 不綁任何真實的 L2 模組（AUDIT-X-9c A-2；MODULE-GUIDE §7）：main 在 import 當下呼叫
`core.loader.load_all()`，而它在**呼叫當下**才讀 `loader.MODULES_DIR`／`MODULES_PACKAGE` ⇒ 這裡在
`import main` 之前把它們換成合成模組樹。拿掉 modules/ 底下任何一個真實模組（core-only 產品），本檔照跑。

  disabled    ⇒ 管理者停用 zz_gate 之後重啟
  unlicensed  ⇒ 授權開關打開、金鑰沒包含 zz_gate
  both        ⇒ 兩者同時（優先順序：未授權 ＞ 停用）
  reenabled   ⇒ 停用後又開回來，再重啟（CORE-SPEC §9c「開回來後恢復」，B-4）
  coreonly    ⇒ modules 資料夾是空的（product/core-only.json）：三支 /api/system/modules* 照常回應
  unreadable  ⇒ 停用清單讀不到、也沒有快取（STATES-PLATFORM P-SW-05）⇒ 所有模組暫不載入
"""
import os
import sys

import pytest

GATE = os.environ.get("MOTRIX_TEST_CHILD_GATE", "")
if not GATE:
    pytest.skip("只在子行程裡跑（由 test_module_selection.py 啟動）", allow_module_level=True)

PKG_DIR = os.environ["MOTRIX_TEST_CHILD_MODULES"]
PKG = os.environ["MOTRIX_TEST_CHILD_PACKAGE"]
KEY, PAGE, PING = "zz_gate", "zz-gate.html", "/api/zz-gate/ping"
SCHED_ENV = "MOTRIX_TEST_CHILD_SCHED_CALLS"      # 合成模組的排程被呼叫時 +1（見父行程的模組原始碼）

sys.path.insert(0, os.path.dirname(PKG_DIR))
from core import loader as _loader          # noqa: E402
import helpers.licensing as _lic            # noqa: E402
import helpers.module_switches as _ms       # noqa: E402

_loader.MODULES_DIR = PKG_DIR
_loader.MODULES_PACKAGE = PKG

# main 讀的是 read_disabled_list()（P-SW-05）；在 import main 之前換掉它的來源。
if GATE in ("disabled", "both"):
    _ms.read_disabled_list = lambda db_path=None: _ms.DisabledList(frozenset({KEY}), False, _ms.SOURCE_DB)
if GATE == "unreadable":
    _ms.read_disabled_list = lambda db_path=None: _ms.DisabledList(frozenset(), True, _ms.SOURCE_UNREADABLE,
                                                                   "停用清單讀取失敗（子行程測試）")
if GATE in ("unlicensed", "both"):
    _lic.LICENSE_GATE_ENABLED = True
    _lic.verify_license = lambda blob=None: {"valid": True, "reason": "ok", "modules": ["some_other_module"],
                                             "kind": "subscription"}
if GATE == "reenabled":
    # 讀的是父行程用真的 set_enabled（停用 → 啟用）寫過的庫，走真的讀取路徑
    _real_read = _ms.read_disabled_list
    _settings_db = os.environ["MOTRIX_TEST_CHILD_SETTINGS"]
    _ms.read_disabled_list = lambda db_path=None: _real_read(_settings_db)

EXPECT = {"disabled": "disabled", "unlicensed": "unlicensed", "both": "unlicensed",
          "reenabled": "loaded", "coreonly": None, "unreadable": "disabled"}[GATE]


def _auth(client, make_user):
    u, p = make_user(username="gate_sa", role="superadmin", modules=[])
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    return {"Authorization": "Bearer " + r.json()["token"]}


def _count(db):
    conn = db.get_db()
    try:
        return conn.execute("SELECT COUNT(*) FROM zz_gate_rows").fetchone()[0]
    finally:
        conn.close()


def test_gate(client, make_user):
    import db
    h = _auth(client, make_user)
    listing = client.get("/api/system/modules", headers=h)
    assert listing.status_code == 200, listing.text
    unavailable = client.get("/api/system/modules/unavailable-pages", headers=h)
    assert unavailable.status_code == 200, unavailable.text

    if GATE == "coreonly":
        # 反向控制：一個模組都沒有 ⇒ 管理頁與選單 API 照常回應、內容是空的，切換不存在的模組 ⇒ 404
        assert listing.json()["modules"] == []
        assert unavailable.json()["pages"] == []
        assert client.get("/api/system/modules/availability", headers=h).json() == {}
        assert client.put("/api/system/modules/" + KEY, headers=h, json={"enabled": False}).status_code == 404
        assert _loader.start_schedulers() == 0
        print("CHILD_GATE_OK", GATE)
        return

    # 資料：模組停用期間留在庫裡的資料列（模組自己不在，直接寫表）
    conn = db.get_db()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS zz_gate_rows (id INTEGER PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO zz_gate_rows (v) VALUES ('保留測試')")
        conn.commit()
    finally:
        conn.close()
    before = _count(db)

    rows = {m["key"]: m for m in listing.json()["modules"]}
    st = rows[KEY]
    assert st["state"] == EXPECT, st
    loaded = EXPECT == "loaded"

    # 端點：載入 ⇒ 200 且讀得到停用期間的資料；沒載入 ⇒ 404（路由沒掛）
    r = client.get(PING, headers=h)
    if loaded:
        assert r.status_code == 200 and r.json()["rows"] == before, r.text
        assert st["reason"] == "" and PAGE not in unavailable.json()["pages"]
        assert "%s.%s" % (PKG, KEY) in sys.modules
    else:
        assert r.status_code == 404, r.text
        assert st["reason"]
        assert PAGE in unavailable.json()["pages"]                     # 選單：入口列為不可用
        assert "%s.%s" % (PKG, KEY) not in sys.modules, "沒載入的模組不可以被 import"
    avail = client.get("/api/system/modules/availability", headers=h).json()
    assert avail[KEY]["state"] == EXPECT and "reason" not in avail[KEY]
    if GATE == "unreadable":
        assert st["reason"] == _ms.UNREADABLE_REASON
        dl = listing.json()["disabledList"]
        assert dl["source"] == "unreadable" and "讀取失敗" in dl["message"]
    if EXPECT == "unlicensed":
        assert "未授權" in st["reason"] and st["canToggle"] is False

    # 排程（B-3）：main 在排程閘門開著時呼叫的就是這個函式；測試 session 的閘門恆關，所以這裡直接呼叫
    os.environ[SCHED_ENV] = "0"
    n = _loader.start_schedulers()
    calls = int(os.environ[SCHED_ENV])
    assert (n, calls) == ((1, 1) if loaded else (0, 0)), (n, calls)

    # 資料不動
    assert _count(db) == before
    print("CHILD_GATE_OK", GATE)
