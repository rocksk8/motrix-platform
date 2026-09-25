# -*- coding: utf-8 -*-
"""寫入資料的端點（POST／PUT／PATCH／DELETE）必須寫稽核紀錄。

使用者裁示（2026-09-24 午，N8①）。在此之前沒有任何測試守這一件：
`test_system_audit` 掃的是「有沒有呼叫**權限**守門」，不是有沒有寫稽核；
第一次量出來 364 支寫入端點裡有 43 支成功時不留任何紀錄。

## 規則

- 用 **ast** 掃 `routers/*.py`（不用 regex：字串、註解裡的 `_audit(` 會騙過 regex）。
- 算數的只有：直接呼叫 `_audit`／`_system_audit`，或呼叫 `AUDIT_WRAPPERS` 明列的包裝函式。
- **不做同名函式推論**。☠️ 第一版量尺就是這樣被騙的：案件階段 10 支呼叫
  `_deny_if_case_locked_unsupported()`，而那支**只在拒絕時**寫 audit
  （它的 docstring 寫明「純記錄撞牆」）⇒ 成功路徑一筆都沒有，量尺卻算「有」。
- 不寫業務資料的端點列 `EXEMPT`，每一筆寫原因；另有兩題守這份清單本身
  （端點必須存在、原因不可空泛），避免「全部列成例外」變綠。
"""
import ast
import glob
import os

from core import source_tree

BE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT_CALLS = {"_audit", "_system_audit"}
WRITE_METHODS = {"post", "put", "patch", "delete"}

#: 會在**成功路徑**上寫稽核的包裝函式：名稱 → (定義所在檔, 說明)。
#: 第三題會驗它真的直接呼叫 `_audit`／`_system_audit`。
AUDIT_WRAPPERS = {
    "_issue_session": ("routers/auth.py", "登入成功發 session 時寫 auth.login"),
}

#: 不寫稽核的寫入端點：(檔名, 方法, 路徑) → 原因。
EXEMPT = {
    # ── 用 POST 的純查詢／試算（不改任何資料）────────────────────────────
    ("quotations.py", "POST", "/api/quotations/case-activity"):
        "純查詢：回傳各案件最後動態時間，POST 只是為了帶一長串單號",
    ("quotations.py", "POST", "/api/quotations/preview-html"):
        "純預覽：用表單內容組出 HTML 給預覽框，不存檔",
    ("network_plans.py", "POST", "/api/network-plans/{plan_id}/topology-preview"):
        "純預覽：依送來的參數畫拓樸圖，不存檔",
    ("network_plans_quick.py", "POST", "/api/network-plans-quick/preview"):
        "純預覽：快速拓樸的畫面預覽，沒有資料表",
    ("bonus.py", "POST", "/cases/{quote_no}/preview"):
        "純試算：獎金分潤改比例／人員時即時重算（BN22），與存檔同一個 allocate()，不寫任何資料表",
    ("network_plans_quick.py", "POST", "/api/network-plans-quick/pdf"):
        "即時產生 PDF 回傳下載，沒有資料表也不歸檔",
    ("system.py", "POST", "/api/audit-log/module-counts"):
        "純查詢：選單紅色數字的計數（舊端點，前端已改用 /api/reads/module-counts）",
    ("bonus.py", "POST", "/awards/plan/{quote_no}"):
        "純試算：分潤方案預覽，送審與核准才寫入（那些端點有稽核）",
    ("item_reads.py", "POST", "/api/reads/unread"):
        "純查詢：伺服器判斷哪些項目未讀，POST 只是為了帶一長串鍵",
    # ── 使用者自己的畫面偏好／已讀／心跳（不是業務資料）──────────────────
    ("list_prefs.py", "PUT", "/api/list-prefs/{list_key}"):
        "個人清單排序偏好，只影響自己的畫面",
    ("system.py", "PATCH", "/api/notifications/{notif_id}/read"):
        "個人通知的已讀旗標，每點一則一次，記稽核會淹沒紀錄",
    ("system.py", "PATCH", "/api/notifications/read-all"):
        "個人通知全部標為已讀，只影響自己的通知",
    ("item_reads.py", "POST", "/api/reads"):
        "個人逐筆已讀時間（未讀紅點），每點一筆一次，記稽核會淹沒紀錄",
    ("item_reads.py", "POST", "/api/reads/batch"):
        "個人已讀紀錄從瀏覽器一次性遷移到伺服器",
    ("system.py", "POST", "/api/edit-presence"):
        "同時編輯警示的心跳，每數秒一次，資料只在記憶體",
    ("system.py", "DELETE", "/api/edit-presence"):
        "同時編輯警示的釋放，資料只在記憶體",
    # ── 登入流程的暫時 challenge（不落地）────────────────────────────────
    ("auth.py", "POST", "/api/auth/webauthn/register/begin"):
        "只產生暫時 challenge 放在記憶體，不落地；完成註冊的端點才寫入並稽核",
    ("auth.py", "POST", "/api/auth/webauthn/login/begin"):
        "只產生暫時 challenge 放在記憶體，不落地；登入成功由 _issue_session 稽核",
}

_VAGUE = {"", "不需要", "例外", "n/a", "na", "todo", "無", "略", "同上", "暫時"}


def _called(fn):
    out = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


def write_endpoints(source):
    """[(方法, 路徑, 函式節點)]：module 頂層、被 `@router.<寫入方法>(路徑)` 裝飾的函式。"""
    out = []
    for n in ast.parse(source).body:
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in n.decorator_list:
            if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and d.func.attr in WRITE_METHODS and isinstance(d.func.value, ast.Name)
                    and d.func.value.id in ("router", "app")
                    and d.args and isinstance(d.args[0], ast.Constant)):
                out.append((d.func.attr.upper(), d.args[0].value, n))
    return out


def is_audited(fn):
    return bool(_called(fn) & (AUDIT_CALLS | set(AUDIT_WRAPPERS)))


def _key(f):
    # routers/ 沿用檔名（EXEMPT 既有鍵）；模組的 api.py 同名，用 modules/<key>/api.py
    r = source_tree.rel(f)
    return r if r.startswith("modules/") else os.path.basename(f)


def _all():
    rows = []
    for f in source_tree.router_files():
        src = open(f, encoding="utf-8").read()
        for method, path, fn in write_endpoints(src):
            rows.append((_key(f), method, path, fn))
    return rows


def test_every_write_endpoint_writes_an_audit_record_or_is_exempt_with_a_reason():
    missing = ["%s:%d %s %s（%s）" % (f, fn.lineno, m, p, fn.name)
               for f, m, p, fn in _all()
               if not is_audited(fn) and (f, m, p) not in EXEMPT]
    assert not missing, (
        "這些寫入端點成功時不寫稽核（`_audit`／`_system_audit`）：\n  " + "\n  ".join(missing)
        + "\n⇒ 補呼叫；真的不寫業務資料的才列 EXEMPT 並寫原因。")


def test_exempt_entries_point_at_endpoints_that_exist():
    live = {(f, m, p) for f, m, p, _ in _all()}
    ghosts = sorted(set(EXEMPT) - live)
    assert not ghosts, "EXEMPT 列了不存在的端點（改名或刪了要一起清）：%s" % ghosts


def test_exempt_entries_that_now_audit_are_removed():
    """列了例外、而它其實已經寫稽核 ⇒ 例外清單在說謊，拿掉。"""
    stale = sorted((f, m, p) for f, m, p, fn in _all() if (f, m, p) in EXEMPT and is_audited(fn))
    assert not stale, "這些端點已經寫稽核，請從 EXEMPT 移除：%s" % stale


def test_exempt_reasons_are_specific():
    vague = sorted(k for k, why in EXEMPT.items()
                   if (why or "").strip().lower() in _VAGUE or len((why or "").strip()) < 12)
    assert not vague, "EXEMPT 的原因太空泛（要寫出「為什麼不是業務資料」）：%s" % vague


def test_audit_wrappers_really_call_audit_directly():
    for name, (rel, _why) in AUDIT_WRAPPERS.items():
        tree = ast.parse(open(os.path.join(BE, rel), encoding="utf-8").read())
        fns = [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
        assert fns, "AUDIT_WRAPPERS 的 %s 在 %s 找不到" % (name, rel)
        assert _called(fns[0]) & AUDIT_CALLS, "%s 沒有直接呼叫 _audit／_system_audit" % name


def test_refusal_only_audit_helper_does_not_count():
    """`_deny_if_case_locked_unsupported()` 只在**拒絕**時寫 audit ⇒ 不可以列成包裝函式。"""
    assert "_deny_if_case_locked_unsupported" not in AUDIT_WRAPPERS


def test_the_scanner_sees_what_it_should():
    """量尺：真的掃得到端點；認得出有稽核的；認得出沒有稽核的；不被字串騙。"""
    rows = _all()
    assert len(rows) > 300, len(rows)
    by = {(f, m, p): fn for f, m, p, fn in rows}
    assert is_audited(by[("modules/tender_radar/api.py", "POST", "/api/tender-radar/watches")])
    src = (
        "@router.post('/x')\n"
        "def a():\n"
        "    conn.execute('INSERT INTO t VALUES (1)')\n"
        "    s = '_audit(token, \"fake\")'  # 字串與註解裡的 _audit( 不算\n"
        "@router.delete('/y')\n"
        "def b():\n"
        "    _audit(tok, 'y.delete')\n"
        "@router.get('/z')\n"
        "def c():\n"
        "    pass\n")
    eps = {p: fn for _m, p, fn in write_endpoints(src)}
    assert set(eps) == {"/x", "/y"}
    assert not is_audited(eps["/x"])
    assert is_audited(eps["/y"])


# ── 行為：補上的呼叫真的寫進 audit_log ───────────────────────────────────

def _hdr(client, make_user, username, role="superadmin"):
    u, p = make_user(username=username, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _audit_rows(action):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM audit_log WHERE action=? ORDER BY id", (action,)).fetchall()]
    finally:
        conn.close()


def test_creating_a_work_log_leaves_an_audit_record(client, make_user):
    h = _hdr(client, make_user, "alice")
    import db
    conn = db.get_db()
    uid = conn.execute("SELECT id FROM users WHERE username='alice'").fetchone()["id"]
    conn.close()
    r = client.post("/api/work-logs", json={"log_date": "2026-09-24", "user_id": uid,
                                            "content": "巡檢"}, headers=h)
    assert r.status_code == 200, r.text
    rows = _audit_rows("work_log.create")
    assert len(rows) == 1 and rows[0]["username"] == "alice"
    assert rows[0]["target_id"] == str(r.json()["id"])


def test_totp_setup_is_audited_without_the_secret(client, make_user):
    h = _hdr(client, make_user, "alice")
    r = client.post("/api/auth/totp/setup", headers=h)
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    rows = _audit_rows("auth.totp_setup")
    assert len(rows) == 1
    assert secret not in (rows[0]["detail"] + rows[0]["target_label"] + rows[0]["target_id"])
