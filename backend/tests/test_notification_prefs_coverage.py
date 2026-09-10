"""通知偏好涵蓋度回歸測試（2026-08-28）。

稽核發現 notify_case_change_requested() 傳給 _superadmin_emails() 的 event_key 字串
打錯字（"case_change_request" 缺一個 d），跟 notification_prefs.py::EVENT_GROUPS 定義的
"case_change_requested" 對不上，導致使用者就算在通知設定裡關掉這項，也永遠攔不住這封信
（is_enabled() 是精確字串比對，見 notification_prefs.py）。這裡直接測 _superadmin_emails()
用的是否為 EVENT_GROUPS 裡實際存在的 key，以及靜音後確實會被排除——以後這個 event_key
字串若再被改錯，這個測試會失敗，及早抓到。
"""
import db
from helpers.notification_prefs import EVENT_KEYS


def _set_email_and_mute(username, email, muted):
    import json
    conn = db.get_db()
    try:
        conn.execute(
            "UPDATE users SET email=?, notification_muted=? WHERE username=?",
            (email, json.dumps(muted), username),
        )
        conn.commit()
    finally:
        conn.close()


def test_case_change_requested_event_key_matches_event_groups():
    """email_notify.py 呼叫端傳的字串必須是 EVENT_GROUPS 裡真的定義過的 key，
    否則使用者的靜音設定形同虛設（見上方模組說明的 2026-08-28 事故）。"""
    assert "case_change_requested" in EVENT_KEYS


def test_every_event_key_used_in_email_notify_is_registered():
    """2026-09-10 一般化：原本這個檔案只釘死 case_change_requested 一個 key，
    結果 f8198e9 新增「案件專案期間超期」通知時，
    notify_case_project_overdue() 呼叫 _admin_emails("case_project_overdue")，
    但那個 key 沒有加進 EVENT_GROUPS——測試全綠、功能照常寄信，只是使用者
    在通知偏好頁永遠看不到也關不掉這一項，跟當初那次打錯字的後果一樣。

    改成掃描 email_notify.py 裡所有 _admin_emails(...)／_superadmin_emails(...)
    的字面字串引數，逐一比對 EVENT_KEYS。之後任何人新增通知函式卻忘了註冊
    event key，這裡就會失敗，不用再靠人工複查。

    只掃字面字串（變數傳入的情況掃不到），但既有寫法全部都是字面字串，
    而「新增一個通知函式時順手複製貼上一個字串」正是會出錯的那種寫法。

    **只驗單向（用到的都要註冊），不驗反向**：EVENT_KEYS 目前有 20 幾個 key
    掃不到，那是正常的——簽核類通知（approval_request、shipping_submitted…）
    的收件人是「當層簽核人」，走的是各自的查詢邏輯而不是這兩支 admin 廣播
    helper，所以掃不到不代表是死開關。反向檢查若要做，得逐一追每個通知函式
    的收件人來源，成本高很多且容易誤判，這裡刻意不做。
    """
    import ast
    import pathlib

    src_path = pathlib.Path(__file__).resolve().parent.parent / "helpers" / "email_notify.py"
    tree = ast.parse(src_path.read_text(encoding="utf-8"))

    recipient_fns = {"_admin_emails", "_superadmin_emails"}
    used = {}  # event_key -> 呼叫它的函式名稱（錯誤訊息用）
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Name)
                    and inner.func.id in recipient_fns
                    and inner.args
                    and isinstance(inner.args[0], ast.Constant)
                    and isinstance(inner.args[0].value, str)):
                used.setdefault(inner.args[0].value, node.name)

    assert used, "沒有掃到任何 event key，掃描邏輯可能已與 email_notify.py 的寫法脫節"
    missing = {k: fn for k, fn in used.items() if k not in EVENT_KEYS}
    assert not missing, (
        "下列 event key 有在 email_notify.py 使用、但沒有註冊進 "
        "notification_prefs.py::EVENT_GROUPS，使用者將無法在通知偏好頁關閉它們：\n"
        + "\n".join(f"  {k!r}（{fn}）" for k, fn in sorted(missing.items()))
    )


def test_case_change_requested_respects_mute_preference(client, make_user):
    from helpers.email_notify import _superadmin_emails

    sa_muted, _ = make_user(username="sa_muted", role="superadmin")
    sa_normal, _ = make_user(username="sa_normal", role="superadmin")
    _set_email_and_mute("sa_muted", "muted@example.com", ["case_change_requested"])
    _set_email_and_mute("sa_normal", "normal@example.com", [])

    to = _superadmin_emails("case_change_requested")
    assert "normal@example.com" in to
    assert "muted@example.com" not in to


def test_normalize_flow_preserves_legitimately_empty_tiers():
    """_normalize_flow() 曾用 raw.get('tiers')（真值判斷），空陣列在 Python 是 falsy，
    會被誤判成舊格式、繞去 _steps_to_tiers(raw.get('steps') or [])——目前殊途同歸都是
    空，但這個判斷本身是脆弱的，2026-08-28 改成 'tiers' in raw（鍵存在判斷）。"""
    from routers.system import _normalize_flow

    # 合法存過的空 tiers：不該被誤判走舊格式轉換路徑
    result = _normalize_flow({"tiers": [], "includeSubmitterManagerTier": True})
    assert result == {"tiers": [], "includeSubmitterManagerTier": True}

    # 真的是舊格式（沒有 tiers 鍵，只有 steps）：才應該走轉換路徑
    result2 = _normalize_flow({"steps": []})
    assert result2 == {"tiers": []}


def test_dead_project_deadline_keys_removed():
    """project_deadline / project_deadline_manager 對應的檢查函式已是空殼 no-op
    （routers/daily_tasks.py::_check_project_deadline()，專案管理併入案件管理時遺留），
    勾了也沒有任何實際效果，2026-08-28 已從 EVENT_GROUPS 移除，避免使用者看到假開關。"""
    assert "project_deadline" not in EVENT_KEYS
    assert "project_deadline_manager" not in EVENT_KEYS
