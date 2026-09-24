# -*- coding: utf-8 -*-
"""`BN17` · 獎金分潤單退回要留記錄（`SPEC-BN17.md`，B 已實作 `8a97a9e`）。

# 🔴 為什麼要補題

B 的實作沒有帶任何測試（協定：B 不寫測試，C 才寫）。本檔照
`SPEC-BN17.md §6 AC1` 逐點釘驗收，直接打真實端點，不呼叫內部函式。

# ⚙️ 觀測點

```
POST /api/bonus/awards/{id}/reject   擋空原因；寫 bonus_award_edit_log
GET  /api/bonus/awards/{id}          帶出 last_reject
```

# 🔴 ⓒ 的前置：先讓單真的被簽過至少一關

`SPEC-BN17.md §6③ⓒ` 明講：少了這個前置，「approval_json 在 UPDATE
之後才讀」那個錯誤實作會把 `from`／`to` 都寫成 `{}`，兩者相等，斷言
`from != to` 或「from 不是 {}」才抓得到差別；本檔設兩層鏈、送審、核准
一層，讓退回前的 `approval_json` 是一個**非空、帶著簽核記錄**的鏈。

# ✅ 牙齒已驗證（方式：資料建構／常設 + 突變驗證／live）

`BN17` 有真實的「修復前」版本可用（`git show 8a97a9e~1`），比自己造一個
突變更硬：

```
③ⓐ／②③ⓑ  直接 exec BN17 之前的 reject_award() 原始碼（從 git history
            取出，未經改寫），用真的 client/make_user 建好前置後直接呼叫
            （繞過 FastAPI 路由分派，因為路由表在 import 當下已經綁定
            現在這支函式物件，monkeypatch 模組屬性換不掉它）：
            - 空原因 -> 舊碼回 {"ok": True, "status": "草稿"}（不擋）
            - 退回一次 -> bonus_award_edit_log 前後都是 0 列
            兩者都證明本檔對應的斷言（400／edit_log +1）對著舊碼會紅。
§5 家族／edit_log 呼叫點  直接把 `_guards_empty_reason()`／AST 呼叫點
            掃描邏輯套用在舊版 `routers/bonus.py` 全文上：`reject_award`
            回 False（沒擋）、`append_edit_log(table="bonus_award_edit_log")`
            呼叫點回 False（不存在）——與現在的實作（True／True）對比，
            證明這兩道守門分辨得出「補之前」與「補之後」。
```
③ⓒ／ⓓ／ⓔ（`approval_json.from` 非空、`last_reject` 有內容、負對照為
`None`）**沒有**另外執行對照組——舊碼完全沒有 `last_reject` 這個回應
欄位、也從不讀寫 `bonus_award_edit_log`，這點已由上面「edit_log 前後
都是 0 列」直接證明，不需要為每一個衍生斷言各自重新執行一次。
"""

# ── 2026-09-24 移除（SPEC-BONUS §十一）───────────────────────────────────────
# 舊「獎金項目＋分潤單」流程停用：寫入端點回 410、bonus.html 改為以案件為中心的新頁面
# （使用者：「上一次開發的內容我無法接受」「重做成新流程」、舊單「舊的都是開發機測試用，直接作廢」）。
# 本檔下列題驗的是已停用的流程，已移除；新流程的題見 test_bonus_case_*_2026_09_24.py、
# test_e2e_bonus_case_page_2026_09_24.py、test_bonus_legacy_retired_2026_09_24.py。
# 移除：test_bn17_detail_shows_who_signed_who_rejected_and_why、test_bn17_empty_reason_is_refused_and_the_award_is_untouched、test_bn17_rejecting_with_a_reason_writes_a_permanent_edit_log_row、test_bn17_the_approval_json_before_value_is_the_real_prior_chain_not_empty、test_bn17_whitespace_only_reason_is_also_refused
# 同檔其餘題驗的是仍在運作的部分（讀取端點、群組、輔助函式），保留。
import json

import pytest

AWARDS = "/api/bonus/awards"
FLOW = "/api/settings/approval-flow/%s"
BONUS_DOC_TYPE = "bonus"


def _hdr(client, make_user, username, role="superadmin", modules=None):
    u, p = make_user(username=username, role=role,
                      modules=modules if modules is not None else ["reports"])
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _user_id(username):
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT id FROM users WHERE username = ?",
                            (username,)).fetchone()
        assert row is not None, "找不到使用者 %r" % username
        return int(row["id"])
    finally:
        conn.close()


def _seed_award(quote_no, people, **cols):
    import db
    status = cols.pop("status", "草稿")
    conn = db.get_db()
    try:
        cur = conn.execute(
            "INSERT INTO bonus_items (name, person_source, sort_order,"
            " is_active, created_by, created_at, updated_at)"
            " VALUES ('業務獎金','sales_person',0,1,'seed',"
            "'2026-09-01','2026-09-01')")
        item_id = cur.lastrowid
        extra_cols = "".join(", %s" % k for k in cols)
        extra_qs = ", ?" * len(cols)
        cur = conn.execute(
            "INSERT INTO bonus_awards (quote_no, base_amount, status,"
            " created_by, created_at, updated_at, voided_at%s)"
            " VALUES (?,?,?,?,?,?,''%s)" % (extra_cols, extra_qs),
            (quote_no, 100000, status, "seed", "2026-09-01", "2026-09-01")
            + tuple(cols.values()))
        aid = cur.lastrowid
        for who in people:
            conn.execute(
                "INSERT INTO bonus_award_lines (award_id, bonus_item_id,"
                " item_name_snapshot, username, person_source_snapshot,"
                " total_pct, person_pct, amount)"
                " VALUES (?,?,?,?,?,1000,10000,?)",
                (aid, item_id, "業務獎金", who, "sales_person", 10000))
        conn.commit()
        return aid
    finally:
        conn.close()


def _act(client, hdr, aid, action, body=None):
    r = client.post("%s/%s/%s" % (AWARDS, aid, action), json=body or {},
                     headers=hdr)
    assert r.status_code not in (404, 405, 422), (
        "`POST %s/{id}/%s` 還不存在（回 %s）：%s"
        % (AWARDS, action, r.status_code, r.text[:200]))
    return r


def _award(client, hdr, aid):
    r = client.get("%s/%s" % (AWARDS, aid), headers=hdr)
    assert r.status_code == 200, r.text[:200]
    return r.json()


def _status_of(aid):
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT status FROM bonus_awards WHERE id = ?",
                            (aid,)).fetchone()
        return row["status"] if row else None
    finally:
        conn.close()


def _edit_log_rows(aid):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM bonus_award_edit_log WHERE award_id = ?"
            " ORDER BY id", (aid,))]
    finally:
        conn.close()


def _set_two_tier_flow(client, hdr, make_user, names):
    """設兩層鏈給 `bonus` doc type（沿用 `test_bonus_award_approval_
    2026_09_23.py::_set_flow` 的形狀，本檔自己複製一份、不跨檔 import）。"""
    approvers = []
    headers_by_name = {}
    for name in names:
        u, h = _hdr(client, make_user, name)
        headers_by_name[u] = h
        approvers.append({"userId": _user_id(u), "username": u,
                           "displayName": u})
    r = client.put(FLOW % BONUS_DOC_TYPE, headers=hdr, json={
        "includeSubmitterManagerTier": False,
        "tiers": [{"approvers": [a]} for a in approvers]})
    assert r.status_code == 200, "存簽核設定失敗：%s %s" % (r.status_code,
                                                        r.text[:200])
    return headers_by_name


def _submitted_and_one_tier_approved(client, hdr, make_user, quote_no):
    """種一張單、設兩層鏈、送審、核准第一層——回到時它是「簽核中」，
    且 `approval_json` 裡有一筆**真的簽核記錄**（不是空鏈）。"""
    headers_by_name = _set_two_tier_flow(client, hdr, make_user,
                                          ("bn17_t1", "bn17_t2"))
    aid = _seed_award(quote_no, ["bn17_payee"])
    r = _act(client, hdr, aid, "submit")
    assert r.status_code == 200, r.text[:200]
    a = _award(client, hdr, aid)
    tiers = (json.loads(a.get("approval_json") or "{}") or {}).get("tiers") \
        if isinstance(a.get("approval_json"), str) else None
    # `GET /awards/{id}` 不一定原樣回傳 `approval_json` 字串，直接讀資料庫。
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT approval_json FROM bonus_awards"
                            " WHERE id = ?", (aid,)).fetchone()
        appr = json.loads(row["approval_json"] or "{}")
    finally:
        conn.close()
    first_tier_username = appr["tiers"][0]["approvers"][0]["username"]
    first_hdr = headers_by_name[first_tier_username]
    r = _act(client, first_hdr, aid, "approve")
    assert r.status_code == 200, r.text[:200]
    assert _status_of(aid) == "簽核中", (
        "核准一層之後應該是「簽核中」，實際是 %r——前置沒建立起來，\n"
        "後面驗『approval_json.from 不是空鏈』這件事會失去意義。"
        % _status_of(aid))
    return aid


# ══════════════════════════════════════════════════════════════════════
# ③ⓐ 空原因：400，且狀態不變（拒絕的路徑上沒有副作用）
# ══════════════════════════════════════════════════════════════════════

def test_bn17_negative_control_an_award_never_rejected_has_no_last_reject(
        client, make_user):
    """⚙️ **正對照：從沒被退回過的單，`last_reject` 是 `None`。**

    ☠️ 少了這題，「永遠回一個假的 last_reject」也會讓上一題綠。
    """
    _u, hdr = _hdr(client, make_user, "bn17_nolreject")
    aid = _seed_award("MQ-BN17-NOLREJECT", ["someone"], status="待審核")

    a = _award(client, hdr, aid)
    assert a.get("last_reject") is None, (
        "從沒被退回過的單，`last_reject` 是 %r，不是 `None`。"
        % a.get("last_reject"))


# ══════════════════════════════════════════════════════════════════════
# §5 守門：釘那一族（reject_award／mark_award_paid／void_voucher）
# ══════════════════════════════════════════════════════════════════════

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _guards_empty_reason(func_src):
    """函式體 AST 裡：先有 `reason = (...).strip()` 賦值給名叫 reason 的
    變數，再有一個對它的 `if not <該名>: raise` 分支。不用 regex（會撿到
    註解），只認真的程式碼結構。"""
    tree = ast.parse(func_src)
    fn = tree.body[0]
    assigned_names = set()
    guarded_names = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            # 粗略比對：右邊呼叫鏈裡有 `.strip()` 且變數名含 reason。
            src = ast.dump(node.value)
            if "strip" in src and "reason" in node.targets[0].id.lower():
                assigned_names.add(node.targets[0].id)
        if isinstance(node, ast.If):
            test = node.test
            # `if not reason:` 形狀
            if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not) \
                    and isinstance(test.operand, ast.Name):
                has_raise = any(isinstance(n, ast.Raise) for n in ast.walk(node))
                if has_raise:
                    guarded_names.add(test.operand.id)
    return bool(assigned_names & guarded_names)


def _extract_function_source(path, func_name):
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    lines = src.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return "\n".join(lines[node.lineno - 1:node.end_lineno])
    return None


#: `§5` 今天的母體。改動這裡**退回給 A**——它是規格點名的清單，不是我
#: 自己盤點的。
_REASON_GUARD_FAMILY = (
    ("routers/bonus.py", "reject_award"),
    ("routers/bonus.py", "mark_award_paid"),
    ("routers/vouchers.py", "void_voucher"),
)


@pytest.mark.parametrize("relpath,func_name", _REASON_GUARD_FAMILY)
def test_bn17_reason_guard_family_all_reject_empty_reason(relpath, func_name):
    """🔴🔴 **這一族裡每一支，讀了 `reason` 就要擋空字串——`reject_award`
    是本題新補上的第三支，另外兩支是既有的正對照。**"""
    path = ROOT / relpath
    src = _extract_function_source(path, func_name)
    assert src is not None, "在 %s 裡找不到 %s()。" % (relpath, func_name)
    assert _guards_empty_reason(src), (
        "%s::%s() 讀了 reason 卻沒有擋空字串——這一族的規則是「讀了就要"
        "擋」，不是「每支各自決定」。" % (relpath, func_name))


def test_bn17_scanner_positive_control_a_bare_endpoint_without_the_guard_is_caught():
    """⚙️ **正對照（誘餌 A）：一支讀了 reason 卻沒擋空的假函式，掃描器要
    抓得到它**——證明掃描器真的會亮，不是永遠回真。"""
    fake_src = (
        "def fake_endpoint(body):\n"
        "    reason = (body.get('reason') or '').strip()\n"
        "    return reason\n"
    )
    assert not _guards_empty_reason(fake_src), (
        "誘餌 A（沒擋空原因）沒有被抓到——掃描器本身壞了，後面那三支"
        "『通過』沒有意義。")


def test_bn17_scanner_positive_control_comment_only_reason_is_not_counted():
    """⚙️ **正對照（誘餌 D）：註解裡寫 `reason = ...` 不算——用 `ast`，
    不是 `regex` 掃字串。**"""
    fake_src = (
        "def fake_endpoint(body):\n"
        "    # reason = (body.get('reason') or '').strip()\n"
        "    if not True:\n"
        "        raise ValueError('x')\n"
        "    return None\n"
    )
    assert not _guards_empty_reason(fake_src), (
        "誘餌 D（reason 只出現在註解裡）被算成『有擋』了——代表掃描器是"
        "用文字比對，不是真的解析 AST。")


def test_bn17_edit_log_write_site_for_bonus_award_exists():
    """✅ **第二道：`bonus_award_edit_log` 的寫入端至少存在一處——
    釘呼叫點存在，不釘資料列數。**

    ☠️ 釘列數的話，一個「測試跑完清空資料庫」的環境會讓這題紅；而
    ⚠️ 表存在超過一整輪都是 0 筆（規格 §5 自己踩過這個坑），只驗
    「表在」證明不了「有人在寫」。
    """
    src = (ROOT / "routers" / "bonus.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else (
                func.attr if isinstance(func, ast.Attribute) else None)
            if name != "append_edit_log":
                continue
            for kw in node.keywords:
                if kw.arg == "table" and isinstance(kw.value, ast.Constant) \
                        and kw.value.value == "bonus_award_edit_log":
                    found = True
    assert found, (
        "`routers/bonus.py` 裡找不到任何一個 `append_edit_log(..., "
        "table=\"bonus_award_edit_log\")` 呼叫點——表存在不代表有人在用它。")
