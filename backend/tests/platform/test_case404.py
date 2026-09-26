"""M01-O1（主持裁示 2026-09-26，M01-PLAN §5-4）：案件「看不到＝不存在」。

① 逐案被拒與查無案件：狀態碼（404）與回應內容相同（訊息＝`case_not_found_message`，只差單號本身）
② audit 記真正原因：denied／not_found 兩種
③ 模組權限的 403（沒有該模組，例：出納）不受影響
④ 守門：案件判定路徑（helpers/case_access）之外，沒有對「逐案拒絕」回 403 的寫法——
   `row_access.require("case", …)`、`HTTPException(403, CASE_ACCESS.deny_message)`、`if not case_access_allowed(...)`→403；
   反向控制：植入任一種 ⇒ 紅。⚠ 傳票 summary-sources 的「案件」頁籤（JV7）照舊對 cashier／finance 列出全部案件，
   不在掃描對象裡，也**不為了守門而排除**（稽核 D AT6-O1：「看不到＝不存在」只保護沒有傳票權限的角色）
"""
import ast
import json
import time

import pytest

from core import source_tree


def _login(client, u, p):
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _seed_case(no, sales):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at, "
                     "sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?)",
                     (no, "草稿", "客", "案", "{}", "2026-09-26", "2026-09-26", sales, "[]"))
        conn.commit()
    finally:
        conn.close()


def _denials(no):
    import db
    from helpers.case_access import CASE_DENIAL_AUDIT
    conn = db.get_db()
    try:
        return [json.loads(r["detail"])["reason"] for r in conn.execute(
            "SELECT detail FROM audit_log WHERE action=? AND target_id=?", (CASE_DENIAL_AUDIT, no)).fetchall()]
    finally:
        conn.close()


def _wait_denials(no, n=1, timeout=5.0):
    """audit 在背景執行緒寫（呼叫端可能拿著寫鎖）⇒ 等它落地。"""
    end = time.time() + timeout
    while time.time() < end:
        got = _denials(no)
        if len(got) >= n:
            return got
        time.sleep(0.05)
    return _denials(no)


@pytest.fixture
def outsider(client, make_user):
    if not source_tree.module_installed("modules/case/"):
        pytest.skip("M01 不在這個安裝包 ⇒ 案件端點本來就不存在（PLAYBOOK §B-11）")
    u, p = make_user(username="c404_out", role="viewer", modules=["dashboard", "quotation"])[:2]
    return _login(client, u, p)


# 單筆讀取（row_access 那一路）與案件子端點（_guard_case 那一路）各一支
PATHS = ["/api/quotations/{no}", "/api/quotations/{no}/stages"]


@pytest.mark.parametrize("path", PATHS)
def test_denied_and_missing_look_the_same(client, outsider, path):
    from helpers.case_access import case_not_found_message
    _seed_case("MQ-C404-A", "someone_else")
    denied = client.get(path.format(no="MQ-C404-A"), headers=outsider)
    missing = client.get(path.format(no="MQ-C404-Z"), headers=outsider)
    assert denied.status_code == missing.status_code == 404, (denied.text, missing.text)
    assert denied.json() == {"detail": case_not_found_message("MQ-C404-A")}
    assert missing.json() == {"detail": case_not_found_message("MQ-C404-Z")}
    assert denied.headers.get("content-type") == missing.headers.get("content-type")


def test_audit_keeps_the_real_reason(client, outsider):
    _seed_case("MQ-C404-B", "someone_else")
    client.get("/api/quotations/MQ-C404-B", headers=outsider)
    client.get("/api/quotations/MQ-C404-Y", headers=outsider)
    assert "denied" in _wait_denials("MQ-C404-B")
    assert "not_found" in _wait_denials("MQ-C404-Y")


def test_the_owner_still_gets_the_case(client, make_user):
    """正對照：看得到的人照常 200（沒有被一起改成 404）。"""
    if not source_tree.module_installed("modules/case/"):
        pytest.skip("M01 不在")
    u, p = make_user(username="c404_own", role="viewer", modules=["dashboard", "quotation"])[:2]
    _seed_case("MQ-C404-C", "c404_own")
    r = client.get("/api/quotations/MQ-C404-C", headers=_login(client, u, p))
    assert r.status_code == 200, r.text


def test_module_permission_403_is_untouched(client, make_user):
    """沒有出納模組的人打出納端點：仍是模組權限的 403（不是案件層的判定）。"""
    if not source_tree.module_installed("modules/arap/"):
        pytest.skip("M05 不在")
    u, p = make_user(username="c404_nocash", role="viewer", modules=["dashboard"])[:2]
    r = client.get("/api/cashier/receivable-queue", headers=_login(client, u, p))
    assert r.status_code == 403, r.text


# ── ④ 守門 ─────────────────────────────────────────────────────────────────

OWNER = "helpers/case_access.py"


def per_case_403(files_src):
    """{相對路徑: 原始碼} ⇒ [(路徑, 行, 寫法)]：案件判定路徑（helpers/case_access.py）之外對逐案拒絕回 403 的地方。"""
    out = []
    for rel, src in files_src.items():
        if rel.replace("\\", "/").endswith(OWNER):
            continue
        tree = ast.parse(src)
        for n in ast.walk(tree):
            # row_access.require("case", …)：不可見時丟 403
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "require" \
               and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == "case":
                out.append((rel, n.lineno, 'row_access.require("case")'))
            # HTTPException(403, CASE_ACCESS.deny_message)
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "HTTPException" and len(n.args) >= 2 \
               and isinstance(n.args[0], ast.Constant) and n.args[0].value == 403 \
               and isinstance(n.args[1], ast.Attribute) and n.args[1].attr == "deny_message":
                out.append((rel, n.lineno, "HTTPException(403, deny_message)"))
            # if not case_access_allowed(...): … raise HTTPException(403, …)
            if isinstance(n, ast.If) and isinstance(n.test, ast.UnaryOp) and isinstance(n.test.op, ast.Not) \
               and isinstance(n.test.operand, ast.Call) \
               and getattr(n.test.operand.func, "id", getattr(n.test.operand.func, "attr", None)) == "case_access_allowed":
                for m in ast.walk(ast.Module(body=n.body, type_ignores=[])):
                    if isinstance(m, ast.Call) and getattr(m.func, "id", None) == "HTTPException" and m.args \
                       and isinstance(m.args[0], ast.Constant) and m.args[0].value == 403:
                        out.append((rel, m.lineno, "case_access_allowed → 403"))
    return out


def test_no_per_case_403_outside_the_case_judgement():
    srcs = {source_tree.rel(p): p.read_text(encoding="utf-8") for p in source_tree.product_files()}
    assert len(srcs) > 50                                   # 量尺：掃得到產品程式
    bad = per_case_403(srcs)
    assert not bad, "案件判定之外對逐案拒絕回 403（M01-O1：看不到＝不存在，一律走 helpers.case_access）：%s" % bad


def test_rc_the_scanner_catches_each_form():
    srcs = {
        "modules/zz/a.py": 'from helpers import row_access\ndef f(u, r):\n    row_access.require("case", u, r)\n',
        "modules/zz/b.py": "from fastapi import HTTPException\nfrom helpers.case_access import CASE_ACCESS\n"
                           "def f():\n    raise HTTPException(403, CASE_ACCESS.deny_message)\n",
        "modules/zz/c.py": "from fastapi import HTTPException\nfrom helpers.case_access import case_access_allowed\n"
                           "def f(c, q, u):\n    if not case_access_allowed(c, q, u):\n        raise HTTPException(403, 'x')\n",
        # 反向：模組權限的 403、其他實體的 require、案件判定本檔
        "modules/zz/ok.py": "from fastapi import HTTPException\nfrom helpers import row_access\n"
                            "def f(u, r):\n    row_access.require('voucher', u, r)\n    raise HTTPException(403, '需要出納模組')\n",
        "helpers/case_access.py": 'from helpers import row_access\ndef g(u, r):\n    row_access.require("case", u, r)\n',
    }
    got = {(r, w) for r, _l, w in per_case_403(srcs)}
    assert got == {("modules/zz/a.py", 'row_access.require("case")'), ("modules/zz/b.py", "HTTPException(403, deny_message)"),
                   ("modules/zz/c.py", "case_access_allowed → 403")}, got
