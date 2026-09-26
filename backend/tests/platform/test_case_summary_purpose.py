"""IP-96 `case.summary` 的用途參數（2026-09-26 A；主持裁示對齊 AT6-O1／JV7）。

- `purpose="voucher_link"` ＋ 有傳票權限（cashier／finance）⇒ 全部案件、只回摘要欄位（單號、客戶名、案名；不回地址等個資）
- 同一個用途、沒有傳票權限 ⇒ 照案件可見性過濾（「看不到＝不存在」只保護沒有傳票權限的角色）
- 權限判斷在 L1 `helpers.case_access.case_summary_scope`，不在呼叫端（M06 只說用途）
- 未登錄的用途 ⇒ ValueError（打錯字不可以默默變成「照可見性」）
"""
import ast
import json

import pytest

from core import registry, source_tree

ADDR = "臺北市中正區測試路 1 號"


def _seed(no, owner_id=None):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at,"
                     " updated_at, sales_person_id) VALUES (?,?,?,?,?,?,?,?)",
                     (no, "已送出", "客戶" + no, "案名" + no,
                      json.dumps({"deliveryLocation": ADDR, "caseRecord": {"contract": {"deliveryAddress": ADDR}}}),
                      "2026-01-01", "2026-01-01", owner_id))
        conn.commit()
    finally:
        conn.close()


def _user(make_user, name, role, modules):
    import db
    make_user(username=name, role=role, modules=modules)
    conn = db.get_db()
    try:
        return dict(conn.execute("SELECT * FROM users WHERE username = ?", (name,)).fetchone())
    finally:
        conn.close()


def _summary(user, purpose=None):
    import db
    fn = registry.single_provider("case.summary")
    if fn is None:
        pytest.skip("案件（M01）不在：沒有 case.summary")
    conn = db.get_db()
    try:
        return fn(conn, user, purpose=purpose)
    finally:
        conn.close()


def test_voucher_users_see_every_case_with_summary_fields_only(client, make_user):
    """有傳票權限（finance）＋ voucher_link ⇒ 別人的案件也列出；每筆只有三個摘要欄位、沒有地址。"""
    _seed("CSP-OTHER-1")
    fin = _user(make_user, "csp_fin", "engineer", ["finance"])
    got = {r["quote_no"]: r for r in _summary(fin, "voucher_link")}
    assert "CSP-OTHER-1" in got, "有傳票權限的人要列得到別人的案件（JV7／AT6-O1）"
    assert all(set(r) == {"quote_no", "customer_name", "project_name"} for r in got.values()), list(got.values())[:2]
    assert ADDR not in json.dumps(list(got.values()), ensure_ascii=False), "摘要不可以帶地址"
    cash = _user(make_user, "csp_cash", "engineer", ["cashier"])
    assert "CSP-OTHER-1" in {r["quote_no"] for r in _summary(cash, "voucher_link")}


def test_without_voucher_rights_the_purpose_changes_nothing(client, make_user):
    """沒有傳票權限的人帶同一個用途 ⇒ 照案件可見性過濾（看不到的案件不列）；看得到自己的案件（正對照）。"""
    eng = _user(make_user, "csp_eng", "engineer", ["case_manage"])
    _seed("CSP-OTHER-2")
    _seed("CSP-MINE-2", owner_id=eng["id"])
    got = {r["quote_no"] for r in _summary(eng, "voucher_link")}
    assert "CSP-OTHER-2" not in got, "沒有傳票權限 ⇒ 用途不放寬"
    assert "CSP-MINE-2" in got, "正對照：自己的案件照常列出"
    assert got == {r["quote_no"] for r in _summary(eng)}, "沒有傳票權限時，帶用途與不帶用途要一樣"


def test_without_a_purpose_voucher_users_are_filtered_as_before(client, make_user):
    """同一個有傳票權限的人不帶用途 ⇒ 照可見性（用途要明說才放寬，不是看角色就全開）。"""
    _seed("CSP-OTHER-3")
    fin = _user(make_user, "csp_fin3", "engineer", ["finance"])
    assert "CSP-OTHER-3" not in {r["quote_no"] for r in _summary(fin)}


def test_unknown_purpose_is_refused():
    from helpers.case_access import case_summary_scope
    with pytest.raises(ValueError):
        case_summary_scope({"role": "engineer", "modules": "[]"}, "voucher-link")   # 打錯字
    assert case_summary_scope({"role": "engineer", "modules": "[]"}) == "visible"


def test_the_voucher_case_tab_lists_every_case_for_voucher_users(client, make_user):
    """端到端：傳票摘要來源的「案件」頁籤，finance 看得到別人的案件（JV7 照現行），而且沒有範圍縮窄的註明。"""
    if not source_tree.module_installed("modules/accounting/"):
        pytest.skip("會計（M06）不在這個安裝包（PLAYBOOK §B-11）")
    _seed("CSP-OTHER-4")
    u, p = make_user(username="csp_fin4", role="engineer", modules=["finance"])
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    r = client.get("/api/vouchers/summary-sources?q=CSP-OTHER-4", headers=h)
    assert r.status_code == 200, r.text[:200]
    assert [c["quote_no"] for c in r.json()["tabs"]["案件"]] == ["CSP-OTHER-4"]
    assert r.json()["notes"]["案件"] == "", "範圍沒有縮窄 ⇒ 不該有範圍說明"


# ── 稽核 D M06-M3：誰可以帶這個用途（比照 SYSTEM 的靜態守門）────────────────────────────────
#: `voucher_link` 會把範圍放寬到全部案件 ⇒ 只准 M06（傳票摘要）帶；新增呼叫者要主持裁示，改這張表。
#: helpers/case_access.py 是登錄處（SUMMARY_PURPOSE_MODULES 的鍵），不是呼叫者。
PURPOSE = "voucher_link"
PURPOSE_ALLOWED = {"helpers/case_access.py", "modules/accounting/api/vouchers.py"}


#: 用途登錄表只准 case_access 自己引用（別處拿到它就能不寫字面值取出用途值；稽核 D M06-M3b）
PURPOSE_TABLE = "SUMMARY_PURPOSE_MODULES"
PURPOSE_TABLE_OWNER = "helpers/case_access.py"
#: 既有的非字面值 `**`（2026-09-26 實掃，與 case.summary 無關；只准變少）：(檔, 最內層函式) ⇒ 次數
KNOWN_STAR_KWARGS = {
    ("cloud_storage.py", "s3_list_prefixes"): 1, ("cloud_storage.py", "s3_delete_prefix"): 1,
    ("pdf_gen.py", "build_quote_preview_html"): 1, ("pdf_gen.py", "generate_pdf_bytes"): 1,
    ("routers/quotations.py", "part"): 1, ("helpers/licensing.py", "_run"): 1,
}
#: 上面那張表的總數上限（稽核 D M06-S3）：只准變少。往表裡加一筆來放行新的 ** ⇒ 超過上限 ⇒ 紅
#: （放行新的要主持裁示，並同時調高這個數字——兩處一起改，review 看得到）
KNOWN_STAR_KWARGS_CAP = 6


def star_cap_problems(known, cap=KNOWN_STAR_KWARGS_CAP):
    total = sum(known.values())
    return [] if total <= cap else ["KNOWN_STAR_KWARGS 共 %d 處，超過上限 %d（只准變少；放行新的 ** 要主持裁示）" % (total, cap)]


def _star_kwargs(rel, tree):
    """(檔, 最內層函式) ⇒ 非字面值 `**` 的次數（`**{"a": 1}` 這種字面字典不算）。"""
    out = {}

    def visit(node, fn):
        for ch in ast.iter_child_nodes(node):
            name = ch.name if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
            if isinstance(ch, ast.Call):
                for kw in ch.keywords:
                    if kw.arg is None and not isinstance(kw.value, ast.Dict):
                        out[(rel, name)] = out.get((rel, name), 0) + 1
            visit(ch, name)
    visit(tree, "<module>")
    return out


def purpose_violations(sources, allowed=PURPOSE_ALLOWED, known_star=None):
    """sources：{相對 backend 的路徑: 原始碼} ⇒ 問題清單。
    ① 字面值 "voucher_link"（不含 docstring；相鄰／`+` 串接先合併）只准出現在 allowed 的檔；
    ② 任何呼叫的 `purpose=` 必須是字串字面值（用變數傳 ⇒ 靜態看不出是誰、帶什麼 ⇒ 一律禁止）；
    ③ 用途登錄表 `SUMMARY_PURPOSE_MODULES`（名稱、屬性、import、同名字串）只准 case_access 自己引用；
    ④ 非字面值的 `**` 一律禁止（既有的列在 KNOWN_STAR_KWARGS、只准變少）。
    〔位置參數由 `case_summary(..., *, purpose=None)` 在執行期擋（TypeError），見 test_purpose_is_keyword_only〕

    ⚠ 射程（主持裁示 2026-09-26：擋的是「不小心借用」，不是蓄意繞過）：`"".join([...])`、`getattr(mod, "SUMMARY_" + x)`、
      字元碼拼字串、從設定檔讀用途這類刻意混淆靜態看不出來，本守門不追。"""
    known_star = KNOWN_STAR_KWARGS if known_star is None else known_star
    import ast
    import sys
    sys.path.insert(0, str(source_tree.BACKEND.parent / "tools" / "platform"))
    import dep_scan
    out = []
    for rel, src in sorted(sources.items()):
        tree = ast.parse(src)
        if rel not in allowed and any(c.strip() == PURPOSE for c in dep_scan.string_chunks(tree)):
            out.append("%s：帶了用途 %r（只准 %s；新增要主持裁示）" % (rel, PURPOSE, sorted(allowed)))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "purpose" and not (isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str)):
                        out.append("%s:%d：purpose= 不是字串字面值（禁止用變數傳用途）" % (rel, node.lineno))
            if rel != PURPOSE_TABLE_OWNER and (
                    (isinstance(node, ast.Name) and node.id == PURPOSE_TABLE)
                    or (isinstance(node, ast.Attribute) and node.attr == PURPOSE_TABLE)
                    or (isinstance(node, ast.alias) and node.name == PURPOSE_TABLE)
                    or (isinstance(node, ast.Constant) and node.value == PURPOSE_TABLE)):
                out.append("%s:%s：引用了用途登錄表 %s（只准 %s）" % (rel, getattr(node, "lineno", "?"), PURPOSE_TABLE,
                                                                PURPOSE_TABLE_OWNER))
        for key, n in sorted(_star_kwargs(rel, tree).items()):
            if n > known_star.get(key, 0):
                out.append("%s::%s：非字面值的 ** 呼叫 %d 處（基線 %d；禁止用 ** 傳參數，改寫成明列的關鍵字）"
                           % (key[0], key[1], n, known_star.get(key, 0)))
    return out


def _product_sources():
    return {source_tree.rel(p): p.read_text(encoding="utf-8") for p in source_tree.product_files()}


def test_only_the_voucher_module_passes_the_voucher_link_purpose():
    bad = purpose_violations(_product_sources())
    assert not bad, "\n".join(bad)


def test_the_guard_sees_the_real_caller():
    """正對照：M06 在時，accounting 的實際呼叫點要被掃到（掃不到 ⇒ 守門空轉）。"""
    srcs = _product_sources()
    if source_tree.module_installed("modules/accounting/"):
        assert 'purpose="voucher_link"' in srcs["modules/accounting/api/vouchers.py"]
        assert purpose_violations(srcs, allowed={"helpers/case_access.py"}) == [
            "modules/accounting/api/vouchers.py：帶了用途 'voucher_link'（只准 ['helpers/case_access.py']；新增要主持裁示）"]
    assert "helpers/case_access.py" in srcs and PURPOSE in srcs["helpers/case_access.py"]


def test_reverse_control_other_callers_and_variables_are_caught():
    """反向控制（沙盒原始碼）：別的模組帶這個用途、用變數傳、拆字串串接 ⇒ 都紅；允許的檔照過。"""
    ok = {"modules/accounting/api/vouchers.py": 's(conn, user, purpose="voucher_link")\n'}
    assert purpose_violations(ok) == []
    other = {"modules/supply/api/x.py": 's(conn, user, purpose="voucher_link")\n'}
    assert purpose_violations(other) == [
        "modules/supply/api/x.py：帶了用途 'voucher_link'（只准 %s；新增要主持裁示）" % sorted(PURPOSE_ALLOWED)]
    var = {"modules/accounting/api/vouchers.py": 'p = "x"\ns(conn, user, purpose=p)\n'}
    assert purpose_violations(var) == ["modules/accounting/api/vouchers.py:2：purpose= 不是字串字面值（禁止用變數傳用途）"]
    concat = {"routers/y.py": 'P = "voucher_" + "link"\ns(conn, user, None, P)\n'}
    assert purpose_violations(concat)[0].startswith("routers/y.py：帶了用途")
    doc_only = {"routers/z.py": '"""說明裡提到 voucher_link 不算"""\n'}
    assert purpose_violations(doc_only) == []


def test_purpose_is_keyword_only():
    """③b：case.summary 的 purpose 只能用關鍵字傳（位置參數 ⇒ TypeError）——反向控制：真的用位置參數傳要被擋。"""
    import inspect
    import db
    fn = registry.single_provider("case.summary")
    if fn is None:
        pytest.skip("案件（M01）不在：沒有 case.summary")
    assert inspect.signature(fn).parameters["purpose"].kind is inspect.Parameter.KEYWORD_ONLY
    conn = db.get_db()
    try:
        with pytest.raises(TypeError):
            fn(conn, {"id": 1, "role": "superadmin", "modules": "[]"}, None, "voucher_link")
    finally:
        conn.close()


def test_known_star_kwargs_baseline_is_not_stale():
    """④ 的基線只准變少：基線上某個函式已經沒有非字面值 ** ⇒ 從 KNOWN_STAR_KWARGS 刪掉。"""
    import ast
    found = {}
    for rel, src in _product_sources().items():
        found.update(_star_kwargs(rel, ast.parse(src)))
    stale = sorted("%s::%s（基線 %d，實有 %d）" % (k[0], k[1], n, found.get(k, 0))
                   for k, n in KNOWN_STAR_KWARGS.items()
                   if found.get(k, 0) < n and source_tree.module_installed(k[0]))
    assert not stale, "基線過期 ⇒ 自 KNOWN_STAR_KWARGS 刪除或改小：\n  " + "\n  ".join(stale)


def test_reverse_control_table_star_kwargs_and_positional():
    """反向控制（沙盒原始碼）：別處引用用途登錄表（名稱／屬性／import／字串）、新增非字面值 ** ⇒ 紅；字面字典 ** 與基線上的不算。"""
    for src in ('from helpers.case_access import SUMMARY_PURPOSE_MODULES\n',
                'import helpers.case_access as ca\nx = ca.SUMMARY_PURPOSE_MODULES\n',
                'x = getattr(ca, "SUMMARY_PURPOSE_MODULES")\n'):
        bad = purpose_violations({"modules/supply/api/x.py": src})
        assert bad and all("用途登錄表" in b for b in bad), (src, bad)
    assert purpose_violations({"helpers/case_access.py": "SUMMARY_PURPOSE_MODULES = {}\n"}) == []
    star = {"modules/supply/api/x.py": "def f(kw):\n    return s(conn, user, **kw)\n"}
    assert purpose_violations(star) == [
        "modules/supply/api/x.py::f：非字面值的 ** 呼叫 1 處（基線 0；禁止用 ** 傳參數，改寫成明列的關鍵字）"]
    assert purpose_violations({"modules/supply/api/x.py": 'def f():\n    return s(**{"a": 1})\n'}) == []
    base = {"pdf_gen.py": "def generate_pdf_bytes(kw):\n    return g(**kw)\n"}
    assert purpose_violations(base) == []
    assert purpose_violations(base, known_star={})[0].startswith("pdf_gen.py::generate_pdf_bytes")


def test_known_star_kwargs_total_is_capped():
    """M06-S3：基線總數不可以超過上限（加一筆就紅）；反向控制：合成多一筆 ⇒ 紅，少一筆 ⇒ 過。"""
    assert star_cap_problems(KNOWN_STAR_KWARGS) == []
    more = dict(KNOWN_STAR_KWARGS)
    more[("modules/supply/api/x.py", "f")] = 1
    assert star_cap_problems(more) == [
        "KNOWN_STAR_KWARGS 共 %d 處，超過上限 %d（只准變少；放行新的 ** 要主持裁示）" % (KNOWN_STAR_KWARGS_CAP + 1, KNOWN_STAR_KWARGS_CAP)]
    fewer = dict(list(KNOWN_STAR_KWARGS.items())[1:])
    assert star_cap_problems(fewer) == []

