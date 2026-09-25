"""信件類型登記、收件人、用語（CORE-SPEC「使用者裁示」信件與通知的收件人、用語，2026-09-26）。

守門（靜態，掃 `core.source_tree.product_files()`）：
  ① 收件人呼叫（_lookup_emails／_admin_emails／_superadmin_emails／_group_emails／_department_manager_emails）
     一律帶字面 key，而且 key 已登記（helpers/mail_types.py 或模組的 `register("key", …)`）
  ② 寄送呼叫（_async_send／_send_raising／_send／_send_with_attachments）的主旨一律由 `subject(key, 事由)` 產生
  ③ `_build_html` 的第一個參數是已登記的字面 key（內文的影響／建議處理從登記表來）
  ④ 信件內文與主旨的字串不可以出現禁用詞（MODULE-GUIDE §11）
行為：預設收件群組、僅超級管理員、指定帳號／角色、未登記 fail closed、系統技術類一般管理員不收、
      個人退訂只能移除、收得到的清單、設定端點驗證。
正對照用合成原始碼（不綁 L2 模組）；另斷言真實掃描抓得到已知的呼叫。
"""
import ast
import json

import pytest

from core import source_tree
from helpers import mail_types as mt

RECIP = ("_lookup_emails", "_admin_emails", "_superadmin_emails", "_group_emails", "_department_manager_emails")
SEND = ("_async_send", "_send_raising", "_send", "_send_with_attachments")
#: 禁用詞（口語、猜測、情緒化符號）。「您好」屬正式用語，不禁。
BANNED = ("多半", "不會自己好", "看起來", "好像", "應該", "大概", "其實", "不用擔心", "救不回",
          "吧", "喔", "啦", "唷", "你", "⚠", "☠", "🔴", "📌", "——")
#: 寄信原語與收件人包裝函式本身（參數是變數，屬於實作；守門看的是它們的呼叫端）
PRIMITIVES = {"_send", "_async_send", "_send_raising", "_send_with_attachments", "_smtp_send_blocked",
              "_admin_emails", "_superadmin_emails", "_group_emails", "_lookup_emails",
              "_department_manager_emails", "_monthly_report_recipient_emails", "_with_event_recipients",
              # 只查詢「群組收件人是否為空」、不寄信（routers/mail_settings.py，稽核 M-S1）
              "_no_recipient"}


def _name(call):
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")


def _lit(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _docstrings(tree):
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body \
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant):
            out.add(id(n.body[0].value))
    return out


def scan(sources):
    """回 (registered, problems)。registered＝原始碼裡 `register("key", …)` 的字面 key。"""
    registered, problems = set(), []
    trees = {rel: ast.parse(src) for rel, src in sources.items()}
    for rel, t in trees.items():
        for n in ast.walk(t):
            if isinstance(n, ast.Call) and _name(n) == "register" and n.args and _lit(n.args[0]):
                registered.add(_lit(n.args[0]))
    known = set(mt.keys()) | registered
    for rel, t in trees.items():
        docs = _docstrings(t)
        prim = [(x.lineno, x.end_lineno) for x in ast.walk(t)
                if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)) and x.name in PRIMITIVES]
        for fn in [x for x in ast.walk(t) if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            if any(a <= fn.lineno <= b for a, b in prim):      # 原語本身與它裡面的巢狀函式
                continue
            mailish = False
            for n in ast.walk(fn):
                if not isinstance(n, ast.Call):
                    continue
                nm = _name(n)
                if nm in RECIP:
                    mailish = True
                    keys = [_lit(a) for a in n.args if _lit(a)]
                    if not keys:
                        problems.append("%s:%d %s() 沒有帶字面的信件類型 key" % (rel, n.lineno, nm))
                    for k in keys:
                        if k not in known:
                            problems.append("%s:%d 信件類型 %r 未登記" % (rel, n.lineno, k))
                elif nm in SEND and len(n.args) >= 2:
                    mailish = True
                    sub = n.args[1]
                    if not (isinstance(sub, ast.Call) and _name(sub) == "subject"):
                        problems.append("%s:%d %s() 的主旨不是由 subject(key, 事由) 產生" % (rel, n.lineno, nm))
                    elif not (_lit(sub.args[0]) in known if sub.args else False):
                        problems.append("%s:%d 主旨的信件類型未登記" % (rel, n.lineno))
                elif nm == "_build_html":
                    mailish = True
                    k = _lit(n.args[0]) if n.args else None
                    if k not in known:
                        problems.append("%s:%d _build_html 的第一個參數必須是已登記的信件類型 key" % (rel, n.lineno))
            if mailish:
                for n in ast.walk(fn):
                    if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs:
                        for w in BANNED:
                            if w in n.value:
                                problems.append("%s:%d 信件用語含禁用詞「%s」" % (rel, n.lineno, w))
    return registered, problems


def _real():
    return scan({source_tree.rel(p): p.read_text(encoding="utf-8") for p in source_tree.product_files()})


# ── 靜態守門 ──────────────────────────────────────────────────────────────────

_OK = {"m.py": (
    'register("zz_ok", "甲", "business", "admins", "", "影響", "處理")\n'
    'def notify_x():\n'
    '    to = _admin_emails("zz_ok")\n'
    '    html = _build_html("zz_ok", "t", "b", "#000", [], "", "u", intro="正式說明。")\n'
    '    _async_send(to, _mt.subject("zz_ok", "事由"), html)\n')}


def test_positive_control_clean_source_passes():
    reg, problems = scan(_OK)
    assert reg == {"zz_ok"} and problems == []


@pytest.mark.parametrize("old, new, expect", [
    ('    to = _admin_emails("zz_ok")', '    to = _admin_emails("zz_nope")', "未登記"),
    ('    to = _admin_emails("zz_ok")', '    to = _admin_emails()', "沒有帶字面"),
    ('_mt.subject("zz_ok", "事由")', '"【MOTRIX】事由"', "主旨不是由"),
    ('_build_html("zz_ok", ', '_build_html(', "第一個參數"),
    ('intro="正式說明。"', 'intro="這件事不會自己好"', "禁用詞"),
])
def test_reverse_controls_each_violation_is_reported(old, new, expect):
    assert _OK["m.py"].count(old) == 1
    _reg, problems = scan({"m.py": _OK["m.py"].replace(old, new)})
    assert any(expect in p for p in problems), problems


def test_real_scan_sees_known_mail_code():
    reg, _p = _real()
    assert {"tender_found", "tender_fetch_failed", "tender_source_changed"} <= reg   # 模組自己登記的
    srcs = {source_tree.rel(p): p.read_text(encoding="utf-8") for p in source_tree.product_files()}
    assert "_async_send(to, _mt.subject(" in srcs["helpers/email_notify.py"]


def test_every_mail_path_is_registered_formal_and_uses_the_registry():
    _reg, problems = _real()
    assert not problems, "信件守門（MODULE-GUIDE §11）：\n  " + "\n  ".join(problems)


def test_registry_rules():
    for t in mt.all_types():
        assert t.impact and t.action, t.key
        if t.category == "system":
            assert t.group == "superadmins", t.key
    with pytest.raises(ValueError):
        mt.register("zz_bad_sys", "x", "system", "admins", "", "i", "a")
    assert mt.subject("backup_error", "備份嚴重錯誤") == "【MOTRIX 系統通知】系統技術－備份嚴重錯誤"


def test_every_registered_key_is_mutable_in_personal_settings():
    from helpers.notification_prefs import EVENT_KEYS
    missing = [k for k in mt.keys() if k not in EVENT_KEYS]
    assert not missing, missing


# ── 行為 ─────────────────────────────────────────────────────────────────────

def _tok(client, make_user, u, role, email=True, muted=None):
    name, pw = make_user(username=u, role=role)
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET email=?, notification_muted=? WHERE username=?",
                     ("%s@example.com" % u if email else "", json.dumps(muted or []), u))
        conn.commit()
    finally:
        conn.close()
    r = client.post("/api/auth/login", json={"username": name, "password": pw})
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def staff(client, make_user):
    import db
    conn = db.get_db()
    try:   # 題目只看自己建的帳號：其他帳號的 email 清掉
        conn.execute("UPDATE users SET email=''")
        conn.commit()
    finally:
        conn.close()
    return {"sa": _tok(client, make_user, "ms_sa", "superadmin"),
            "adm": _tok(client, make_user, "ms_adm", "admin"),
            "eng": _tok(client, make_user, "ms_eng", "engineer")}


def test_system_mail_goes_to_superadmins_only(staff):
    from helpers import email_notify as en
    assert en._group_emails("backup_stale") == ["ms_sa@example.com"]           # 系統技術類
    assert set(en._group_emails("settlement_finalized")) == {"ms_sa@example.com", "ms_adm@example.com"}


def test_unregistered_key_is_fail_closed(staff, caplog):
    from helpers import email_notify as en
    assert en._lookup_emails(["ms_eng"], "zz_not_registered") == ["ms_sa@example.com"]
    assert any("未登記" in r.message for r in caplog.records)


def test_overrides_superadmin_only_and_custom(client, staff):
    from helpers import email_notify as en
    h = staff["sa"]
    r = client.put("/api/mail-types/approval_request/recipients", headers=h, json={"mode": "superadmin_only"})
    assert r.status_code == 200, r.text
    assert en._lookup_emails(["ms_eng"], "approval_request") == ["ms_sa@example.com"]
    r = client.put("/api/mail-types/approval_request/recipients", headers=h,
                   json={"mode": "custom", "users": ["ms_adm"], "roles": []})
    assert r.status_code == 200, r.text
    assert en._lookup_emails(["ms_eng"], "approval_request") == ["ms_eng@example.com", "ms_adm@example.com"]
    r = client.put("/api/mail-types/settlement_finalized/recipients", headers=h,
                   json={"mode": "custom", "users": [], "roles": ["engineer"]})
    assert en._group_emails("settlement_finalized") == ["ms_eng@example.com"]
    client.put("/api/mail-types/approval_request/recipients", headers=h, json={"mode": "default"})
    assert en._lookup_emails(["ms_eng"], "approval_request") == ["ms_eng@example.com"]


def test_settings_endpoint_validates_and_is_superadmin_only(client, staff):
    h = staff["sa"]
    assert client.get("/api/mail-types", headers=staff["adm"]).status_code == 403
    assert client.put("/api/mail-types/approval_request/recipients", headers=staff["adm"],
                      json={"mode": "default"}).status_code == 403
    assert client.put("/api/mail-types/zz/recipients", headers=h, json={"mode": "default"}).status_code == 404
    for body in ({"mode": "x"}, {"mode": "custom"}, {"mode": "custom", "users": ["nobody"]},
                 {"mode": "custom", "roles": ["god"]}):
        assert client.put("/api/mail-types/approval_request/recipients", headers=h, json=body).status_code == 400, body
    d = client.get("/api/mail-types", headers=h).json()
    keys = {t["key"] for t in d["items"]}
    assert set(mt.keys()) <= keys and all(t["impact"] and t["action"] for t in d["items"])


def test_personal_mute_only_removes_and_list_shows_receivable(client, staff):
    import db
    from helpers import email_notify as en
    h = staff["sa"]
    conn = db.get_db()
    try:
        ids = {r["username"]: r["id"] for r in conn.execute("SELECT id, username FROM users")}
    finally:
        conn.close()
    items = {t["key"]: t["receivable"] for t in client.get(
        "/api/mail-types/receivable?user_id=%d" % ids["ms_adm"], headers=h).json()["items"]}
    assert items["settlement_finalized"] is True and items["backup_stale"] is False   # 一般管理員收不到系統技術類
    assert items["approval_request"] is True                                           # 事件相關（輪到他簽）
    r = client.put("/api/users/%d" % ids["ms_adm"], headers=h, json={"notification_muted": ["settlement_finalized"]})
    assert r.status_code == 200, r.text
    assert en._group_emails("settlement_finalized") == ["ms_sa@example.com"]
    assert client.put("/api/users/%d" % ids["ms_adm"], headers=h,
                      json={"notification_muted": ["zz_typo"]}).status_code == 400
    # 退訂清單不會讓人收到原本收不到的類型：清空退訂，系統技術類仍不寄給一般管理員
    client.put("/api/users/%d" % ids["ms_adm"], headers=h, json={"notification_muted": []})
    assert en._group_emails("backup_stale") == ["ms_sa@example.com"]


def test_mail_body_has_the_fixed_sections():
    from helpers import email_notify as en
    html = en._build_html("backup_stale", "備份已停止運作", "x", "#000", [("甲", "乙")], "", "https://h",
                          intro="系統已超過 36 小時沒有完成備份。")
    for sec in ("事由", "影響", "建議處理", "發送時間與來源", mt.get("backup_stale").impact):
        assert sec in html, sec


def test_pages_bind_the_registry():
    from pathlib import Path
    fe = Path(__file__).resolve().parents[3] / "frontend"
    from core import source_tree
    users = source_tree.page_file("users.html").read_text(encoding="utf-8")   # 頁面位置一律經 page_file（階段 C）
    assert "/api/mail-types/receivable?user_id=" in users and ":disabled=\"!item.receivable\"" in users
    assert "{key:'approval_request'" not in users              # 不再有寫死的副本
    page = source_tree.page_file("mail-settings.html").read_text(encoding="utf-8")
    assert "'/api/mail-types/' + encodeURIComponent(t.key) + '/recipients'" in page
    assert "mail-settings.html" in (fe / "static" / "sidebar.js").read_text(encoding="utf-8")


# ── 稽核 D（AUDIT-D-A-mail-settings）────────────────────────────────────────────

def test_no_superadmin_does_not_fall_back_to_admins(staff, caplog):
    """M-M1：找不到可收信的超級管理員時，系統技術類**不退回一般管理員**（使用者：「普通管理員不需要收到這類信」）。"""
    import db
    from helpers import email_notify as en
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET email='' WHERE role='superadmin'")
        conn.commit()
    finally:
        conn.close()
    assert en._group_emails("backup_stale") == []                    # 不是 ["ms_adm@example.com"]
    assert en._lookup_emails(["ms_eng"], "zz_not_registered") == []  # 未登記 fail closed 也不退回
    assert any("超級管理員" in r.message for r in caplog.records)


def test_settings_page_says_when_nobody_receives(client, staff):
    """M-S1：所有超級管理員都退訂某一種系統技術類 ⇒ 設定頁標出「目前沒有人會收到」。"""
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET notification_muted=? WHERE role='superadmin'", (json.dumps(["disk_space_low"]),))
        conn.commit()
    finally:
        conn.close()
    items = {t["key"]: t for t in client.get("/api/mail-types", headers=staff["sa"]).json()["items"]}
    assert items["disk_space_low"]["noRecipient"] is True
    assert items["backup_stale"]["noRecipient"] is False              # 正對照：沒退訂的那一類有人收
    assert items["approval_request"]["noRecipient"] is False          # 有事件收件人的不判定


def test_receivable_in_superadmin_only_mode(client, staff):
    """M-S2：「僅超級管理員」模式下，一般管理員的清單裡這一類是收不到的。"""
    import db
    h = staff["sa"]
    conn = db.get_db()
    try:
        ids = {r["username"]: r["id"] for r in conn.execute("SELECT id, username FROM users")}
    finally:
        conn.close()
    assert client.put("/api/mail-types/settlement_finalized/recipients", headers=h,
                      json={"mode": "superadmin_only"}).status_code == 200
    items = {t["key"]: t["receivable"] for t in client.get(
        "/api/mail-types/receivable?user_id=%d" % ids["ms_adm"], headers=h).json()["items"]}
    assert items["settlement_finalized"] is False
    items = {t["key"]: t["receivable"] for t in client.get(
        "/api/mail-types/receivable?user_id=%d" % ids["ms_sa"], headers=h).json()["items"]}
    assert items["settlement_finalized"] is True


def test_monthly_report_has_one_recipient_source(client, staff):
    """M-S3：每月營運報表的收件人只在「報表收件人設定」維護；本頁不接受覆寫，也不會被舊覆寫影響。"""
    from helpers import email_notify as en
    from helpers.settings import _set_setting
    h = staff["sa"]
    r = client.put("/api/mail-types/monthly_report/recipients", headers=h, json={"mode": "superadmin_only"})
    assert r.status_code == 400
    item = next(t for t in client.get("/api/mail-types", headers=h).json()["items"] if t["key"] == "monthly_report")
    assert item["managedElsewhere"]
    import db
    conn = db.get_db()
    try:
        adm_id = conn.execute("SELECT id FROM users WHERE username='ms_adm'").fetchone()["id"]
    finally:
        conn.close()
    _set_setting("monthly_report_recipients", {"userIds": [adm_id]})
    _set_setting(mt.OVERRIDES_KEY, {"monthly_report": {"mode": "superadmin_only", "users": [], "roles": []}})
    assert en._monthly_report_recipient_emails() == ["ms_adm@example.com"]    # 舊覆寫不影響


def test_settings_page_shows_no_recipient_and_elsewhere():
    from pathlib import Path
    page = (Path(__file__).resolve().parents[3] / "frontend" / "pages" / "mail-settings.html").read_text(encoding="utf-8")
    assert 'x-show="t.noRecipient"' in page and "t.managedElsewhere" in page
