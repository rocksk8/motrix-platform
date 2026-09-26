"""`case.summary`／`case.locations`（M01 提供；M01-PLAN §3-4，主持裁示 2026-09-26 四點）的契約。

① summary：欄位恰好 {quote_no, customer_name, project_name, status, sales_person_id}；可見性＝row_access `case`／read
   （本人、被分配、admin+、cashier）；不給 quote_nos ⇒ 看得到的全部；給清單 ⇒ 只回其中看得到且存在的
② locations：交貨地點（合約交貨地址優先，其次報價的交貨地點）；可見性同上；fingerprint 隨地點／可見性欄位變
③ 身分：`user=None` ⇒ TypeError（不猜）；`helpers.case_access.SYSTEM` ⇒ 不過濾——**只准 L1 背景呼叫端**：
   掃出每一個引用 `SYSTEM` 的產品檔，必須是 modules.json 的 L1 單位（反向控制：合成的 L2 引用要被抓到）
④ IP-12 的 `summary` 轉呼叫 case.summary（淘汰中；結果與原本相同）
⑤ M01 不在（拿掉兩個 provider）：地圖回 200、案件來源 `skipped: module_absent` 並明說、沒有案件點
"""
import ast
import json

import pytest

from core import registry, source_tree
from tests.test_mp1_map_points_link_to_records_2026_09_24 import _geo  # noqa: F401  （地理查詢換成查表，不連外）


def _q(no, owner_id=None, owner_name="", assigned=None, data=None, customer="客", project="案"):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, "
            "updated_at, sales_person_id, sales_person, assigned_user_ids, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (no, "已送出", customer, project, 0, 0, json.dumps(data or {}, ensure_ascii=False), "2026-09-01T00:00:00",
             "2026-09-01T00:00:00", owner_id, owner_name, json.dumps(assigned or []), "已成案"))
        conn.commit()
    finally:
        conn.close()


def _user(make_user, name, role="sales", modules=("case_manage",)):
    import db
    make_user(username=name, role=role, modules=None if modules is None else list(modules))
    conn = db.get_db()
    try:
        return dict(conn.execute("SELECT * FROM users WHERE username=?", (name,)).fetchone())
    finally:
        conn.close()


def _conn():
    import db
    return db.get_db()


def test_summary_fields_visibility_and_filters(client, make_user):
    from helpers.case_access import SYSTEM
    a = _user(make_user, "cs_a")
    b = _user(make_user, "cs_b")
    adm = _user(make_user, "cs_adm", role="admin", modules=None)
    _q("MQ-CS-A", owner_id=a["id"], owner_name="cs_a", customer="甲客", project="甲案")
    _q("MQ-CS-B", owner_id=b["id"], owner_name="cs_b")
    _q("MQ-CS-AS", owner_id=b["id"], assigned=[a["id"]])
    summary = registry.single_provider("case.summary")
    conn = _conn()
    try:
        got_a = summary(conn, a)
        assert {r["quote_no"] for r in got_a} == {"MQ-CS-A", "MQ-CS-AS"}               # 本人＋被分配
        assert set(got_a[0]) == {"quote_no", "customer_name", "project_name", "status", "sales_person_id"}
        assert [r for r in got_a if r["quote_no"] == "MQ-CS-A"][0]["customer_name"] == "甲客"
        assert {r["quote_no"] for r in summary(conn, adm)} >= {"MQ-CS-A", "MQ-CS-B", "MQ-CS-AS"}
        assert [r["quote_no"] for r in summary(conn, a, ["MQ-CS-B", "MQ-CS-A", "MQ-NOPE"])] == ["MQ-CS-A"]  # 看不到、不存在 ⇒ 不回
        assert summary(conn, a, []) == []
        assert {r["quote_no"] for r in summary(conn, SYSTEM)} >= {"MQ-CS-A", "MQ-CS-B", "MQ-CS-AS"}
        with pytest.raises(TypeError):
            summary(conn, None)
    finally:
        conn.close()


def test_locations_address_rule_visibility_and_fingerprint(client, make_user):
    from helpers.case_access import SYSTEM
    a = _user(make_user, "cl_a")
    _q("MQ-CL-1", owner_id=a["id"], data={"deliveryLocation": "報價地點", "caseRecord": {"contract": {"deliveryAddress": "合約地址"}}})
    _q("MQ-CL-2", owner_id=a["id"], data={"deliveryLocation": "只有報價地點"})
    _q("MQ-CL-X", owner_id=None, owner_name="別人", data={"deliveryLocation": "別人的地址"})
    loc = registry.single_provider("case.locations")
    conn = _conn()
    try:
        mine = {r["quote_no"]: r["address"] for r in loc.list(conn, a)}
        assert mine == {"MQ-CL-1": "合約地址", "MQ-CL-2": "只有報價地點"}
        assert "MQ-CL-X" in {r["quote_no"] for r in loc.list(conn, SYSTEM)}
        with pytest.raises(TypeError):
            loc.list(conn, None)
        f1 = loc.fingerprint(conn)
        conn.execute("UPDATE quotations SET assigned_user_ids=? WHERE quote_no='MQ-CL-X'", (json.dumps([a["id"]]),))
        conn.commit()
        assert loc.fingerprint(conn) != f1                                        # 可見性變了 ⇒ 快取要失效
    finally:
        conn.close()


def test_ip12_summary_forwards_to_case_summary(client):
    _q("MQ-CS-IP12", customer="十二客", project="十二案")
    ca = registry.single_provider("case.access")
    conn = _conn()
    try:
        assert ca.summary(conn, "MQ-CS-IP12") == {"customer": "十二客", "project": "十二案"}
        assert ca.summary(conn, "MQ-NOPE") is None
    finally:
        conn.close()


# ── ③ SYSTEM 只准 L1 ─────────────────────────────────────────────────────────

_SENTINEL_NAMES = {"SYSTEM", "_SystemCaller"}


def _touches_case_access(tree):
    """這個檔有沒有從 case_access 取得任何名稱（任何 import 寫法：from helpers.case_access import …／import *、
    from helpers import case_access [as x]、import helpers.case_access [as x]、from helpers import SYSTEM）。"""
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            if n.module == "helpers.case_access":
                return True
            if n.module == "helpers" and any(a.name in ({"case_access"} | _SENTINEL_NAMES) for a in n.names):
                return True
        elif isinstance(n, ast.Import) and any(a.name == "helpers.case_access" for a in n.names):
            return True
    return False


def _mentions_sentinel(tree):
    """名稱、屬性、字串常數（getattr(x, "SYSTEM")）任一處出現哨兵的名字；`from helpers.case_access import *` 也算
    （看不出拿了什麼 ⇒ 保守當作有）。"""
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and n.id in _SENTINEL_NAMES:
            return True
        if isinstance(n, ast.Attribute) and n.attr in _SENTINEL_NAMES:
            return True
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in _SENTINEL_NAMES:
            return True
        if isinstance(n, ast.alias) and n.name in (_SENTINEL_NAMES | {"*"}):
            return True
    return False


def system_users(files_src):
    """{相對路徑: 原始碼} ⇒ 可能取用系統身分的檔：從 case_access 取得任何名稱、而且提到哨兵的名字（稽核 D CS-M1：
    只比對 `from helpers.case_access import SYSTEM` 與 `case_access.SYSTEM` 兩種寫法時，6 種常見寫法全部漏抓）。"""
    out = set()
    for rel, src in files_src.items():
        tree = ast.parse(src)
        if _touches_case_access(tree) and _mentions_sentinel(tree):
            out.add(rel)
    return out


def _l1_files():
    mj = json.loads((source_tree.BACKEND.parent / "docs" / "platform" / "modules.json").read_text(encoding="utf-8"))
    units = set(mj["L1"]["units"])
    out = set()
    for p in source_tree.product_files():
        rel = source_tree.rel(p)
        stem = rel[:-3]
        cand = {"router:" + stem.split("/")[-1] if rel.startswith("routers/") else None,
                "helper:" + stem.split("/")[-1] if rel.startswith("helpers/") else None,
                "core:" + stem if "/" not in rel else None,
                "plat:" + stem.split("/")[-1] if rel.startswith("core/") else None}
        if cand & units:
            out.add(rel)
    return out


def test_system_caller_is_used_only_by_l1():
    srcs = {source_tree.rel(p): p.read_text(encoding="utf-8") for p in source_tree.product_files() if p.suffix == ".py"}
    users = system_users(srcs)
    allowed = _l1_files() | {"helpers/quotations.py", "helpers/case_access.py"}   # 定義處與 M01 自己（IP-12 轉呼叫）
    assert users, "正對照：至少地圖（routers/map_points.py）在用 SYSTEM"
    assert "routers/map_points.py" in users
    bad = sorted(users - allowed)
    assert not bad, "helpers.case_access.SYSTEM 只准 L1 背景呼叫端使用（主持裁示 2026-09-26）：" + ", ".join(bad)


def test_rc_system_scanner_catches_an_l2_user():
    srcs = {"modules/zz/api.py": "from helpers.case_access import SYSTEM\nx = SYSTEM\n",
            "routers/zz.py": "from helpers import case_access\ny = case_access.SYSTEM\n",
            # 稽核 D CS-M1 列的 6 種寫法
            "modules/c1.py": "from helpers import case_access as ca\nx = ca.SYSTEM\n",
            "modules/c2.py": "import helpers.case_access as ca\nx = ca.SYSTEM\n",
            "modules/c3.py": "import helpers.case_access\nx = helpers.case_access.SYSTEM\n",
            "modules/c4.py": "from helpers.case_access import *\nx = 1\n",
            "modules/c5.py": "from helpers import case_access\nx = getattr(case_access, 'SYSTEM')\n",
            "modules/c6.py": "from helpers.case_access import _SystemCaller\nx = _SystemCaller()\n",
            # 反向控制：只用 guard 的、或提到 SYSTEM 但跟 case_access 無關的，不算
            "routers/clean.py": "from helpers.case_access import guard_case_access\n",
            "routers/other.py": "from core import registry\nSYSTEM = 'x'\n"}
    assert system_users(srcs) == {"modules/zz/api.py", "routers/zz.py", "modules/c1.py", "modules/c2.py",
                                  "modules/c3.py", "modules/c4.py", "modules/c5.py", "modules/c6.py"}


def test_runtime_refuses_system_from_an_l2_module(client):
    """執行期檢查（第二道）：呼叫端在 `backend/modules/` 底下卻傳 SYSTEM ⇒ PermissionError；L1 傳 ⇒ 照常。"""
    import sys
    from helpers.case_access import SYSTEM
    s = registry.single_provider("case.summary")
    fake = source_tree.BACKEND / "modules" / "zz_probe" / "api.py"
    code = compile("def call(s, conn, user):\n    return s(conn, user)\n", str(fake), "exec")
    ns = {}
    exec(code, ns)
    conn = _conn()
    try:
        with pytest.raises(PermissionError):
            ns["call"](s, conn, SYSTEM)
        assert isinstance(s(conn, SYSTEM), list)                                  # 本檔（tests，不在 modules/）照常
    finally:
        conn.close()


# ── ⑤ M01 不在 ─────────────────────────────────────────────────────────────

def test_map_without_m01_says_cases_are_unavailable(client, make_user, monkeypatch, _geo):
    from routers import map_points as mp
    orig = registry.single_provider
    monkeypatch.setattr(registry, "single_provider",
                        lambda cap: None if cap in ("case.locations", "case.summary") else orig(cap))
    u, p = make_user("cs_map_sa", "Conn-Pass-123", role="superadmin")[:2]
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    _q("MQ-CS-MAP", data={"deliveryLocation": "台中市西屯區"})
    r = client.get("/api/map/points?sources=cases", headers=h)
    assert r.status_code == 200, r.text
    src = [s for s in r.json()["sources"] if s["source"] == "cases"]
    assert src and src[0]["skipped"] == "module_absent" and src[0]["note"] == mp.CASES_MODULE_ABSENT
    assert not [pt for pt in r.json()["points"] if pt.get("sourceKey") == "cases"]
