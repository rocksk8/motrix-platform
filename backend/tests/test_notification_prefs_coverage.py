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
