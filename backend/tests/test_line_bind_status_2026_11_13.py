"""T83「誰還沒綁 LINE」：綁定狀況三種狀態（已綁定／尚未綁定／綁定失效）、「綁好後原本會收到哪些通知」、提醒綁定（Email＋站內、一天一次、稽核）。

夾具沿用 `test_line_events_all_2026_11_13`（LINE 啟用、五位使用者、攔截 LINE push 與 Email 寄送）。
"""
import json

import pytest

from tests.test_line_events_all_2026_11_13 import _grant_crm, _hdr, env, login_ready  # noqa: F401  夾具與小工具共用


def _users(client, headers):
    j = client.get("/api/settings/line-notify/bindings", headers=headers).json()
    return j, {u["username"]: u for u in j["users"]}


def test_state_is_bound_unbound_or_expired_and_counts_add_up(client, env, login_ready):
    from helpers import line_notify as L
    L.unlink_user("dan")                                    # dan：尚未綁定
    L.set_confirmed("carol", False)                          # carol：綁了但 LINE 拒收確認訊息 ⇒ 綁定失效
    L.set_confirmed("amy", True)
    j, u = _users(client, _hdr(client, "sa"))
    assert u["dan"]["state"] == "unbound" and u["carol"]["state"] == "expired" and u["amy"]["state"] == "bound" and u["bob"]["state"] == "bound"
    assert j["unlinked"] == 1 and j["expired"] == 1 and j["needBind"] == 2 and j["linked"] == 4
    assert j["total"] == 5


def test_no_line_user_id_or_token_in_the_response(client, env, login_ready):
    from helpers import line_notify as L
    L.unlink_user("dan")
    body = json.dumps(client.get("/api/settings/line-notify/bindings", headers=_hdr(client, "sa")).json(), ensure_ascii=False)
    for uid in env["uid"].values():
        assert uid not in body, "LINE userId 不可回到瀏覽器"
    assert "channel_access_token" not in body and "userId" not in body


def test_missed_events_use_the_same_rules_as_the_personal_page_including_dev_crm(client, env, login_ready):
    from helpers import line_notify as L, line_recipients as LR
    L.set_event("approval_request", True)
    L.set_event("crm_case_status", True)
    L.set_event("voucher_submitted", True)                   # 會計：要 finance／cashier
    _grant_crm("amy")                                        # amy 有業務開發權限；dan 沒有
    L.unlink_user("amy")
    L.unlink_user("dan")
    _, u = _users(client, _hdr(client, "sa"))
    amy = u["amy"]
    assert "業務開發：案件狀態（階段）變更" in amy["missed"], "有 dev_crm ⇒ 綁好後會收到業務開發通知"
    assert "業務開發：案件狀態（階段）變更" not in u["dan"]["missed"], "沒有 dev_crm ⇒ 不會收到，也就不算「收不到」"
    names_amy = [e["name"] for e in LR.prefs_view("amy", "sales") if e["enabled"]]
    assert amy["missedCount"] == len(names_amy) and amy["missed"] == names_amy[:len(amy["missed"])], "與本人設定頁同一套規則"
    assert u["bob"]["missed"] == [] and u["bob"]["missedCount"] == 0, "綁好的人不列"


def test_events_the_person_muted_or_the_company_did_not_enable_are_not_counted(client, env, login_ready):
    from helpers import line_notify as L, line_recipients as LR
    L.set_event("approval_request", True)
    L.unlink_user("dan")
    _, u = _users(client, _hdr(client, "sa"))
    n_before = u["dan"]["missedCount"]
    assert n_before >= 1
    LR.set_muted("dan", "approval_request", True)
    _, u2 = _users(client, _hdr(client, "sa"))
    assert u2["dan"]["missedCount"] == n_before - 1, "本人自己關掉的不算"
    L.set_event("approval_request", False)
    _, u3 = _users(client, _hdr(client, "sa"))
    assert u3["dan"]["missedCount"] == n_before - 1, "公司沒勾選的本來就不會發"


def test_missed_list_is_capped_but_count_is_exact(client, env, login_ready):
    from helpers import line_notify as L
    wired = [k for k in L.WIRED_EVENTS][:15]
    for k in wired:
        L.set_event(k, True)
    L.unlink_user("sa")                                       # 最高管理者對所有事件都「輪得到」
    _, u = _users(client, _hdr(client, "sa"))
    assert len(u["sa"]["missed"]) <= 8 and u["sa"]["missedCount"] >= len(u["sa"]["missed"])


def test_remind_covers_unbound_and_expired_with_matching_wording_and_audit_lists_names(client, env, login_ready):
    from db import get_db
    from helpers import line_notify as L
    L.unlink_user("dan")
    L.set_confirmed("carol", False)
    sa = _hdr(client, "sa")
    r = client.post("/api/settings/line-notify/bindings/remind", json={}, headers=sa)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["targets"] == 2 and j["notified"] == 2 and sorted(j["names"]) == ["carol", "dan"]
    mails = {m[0][0]: m for m in env["mail"]}
    assert set(mails) == {"dan@example.com", "carol@example.com"}, "只有 Email（不是 LINE）"
    assert env["line"] == [], "提醒綁定不發 LINE"
    assert "重新" in mails["carol@example.com"][1] + mails["carol@example.com"][2], "綁定失效的人收到「重新綁定」的說法"
    assert "重新" not in mails["dan@example.com"][1], "沒綁過的人是一般綁定說明"
    assert "my-account.html?tab=notify" in mails["dan@example.com"][2] and "my-account.html?tab=notify" in mails["carol@example.com"][2]
    c = get_db()
    try:
        row = c.execute("SELECT detail FROM audit_log WHERE action='line.binding.remind'").fetchone()
        assert sorted(json.loads(row["detail"])["usernames"]) == ["carol", "dan"], "稽核列記被提醒的帳號"
    finally:
        c.close()
    env["mail"].clear()
    j2 = client.post("/api/settings/line-notify/bindings/remind", json={}, headers=sa).json()
    assert j2["notified"] == 0 and sorted(j2["skippedRecent"]) == ["carol", "dan"] and env["mail"] == [], "一天一次"


def test_a_working_binding_is_never_reminded_and_endpoints_are_superadmin_only(client, env, login_ready):
    sa, ad = _hdr(client, "sa"), _hdr(client, "bob")
    assert client.get("/api/settings/line-notify/bindings", headers=ad).status_code == 403
    assert client.post("/api/settings/line-notify/bindings/remind", json={}, headers=ad).status_code == 403
    j = client.post("/api/settings/line-notify/bindings/remind", json={"usernames": ["amy", "bob"]}, headers=sa).json()
    assert j["targets"] == 0 and sorted(j["ignored"]) == ["amy", "bob"] and env["mail"] == []


def test_state_of_is_a_pure_function():
    from helpers import line_binding as LB
    assert LB.state_of({"linked": False, "confirmed": None}) == "unbound"
    assert LB.state_of({"linked": True, "confirmed": False}) == "expired"
    assert LB.state_of({"linked": True, "confirmed": True}) == "bound" and LB.state_of({"linked": True, "confirmed": None}) == "bound"
