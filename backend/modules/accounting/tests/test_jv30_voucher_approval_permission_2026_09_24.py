# -*- coding: utf-8 -*-
"""`JV30` · 傳票簽核權限（商業會計法 §35、電子方式處理會計資料辦法 §5）。

權威原文：`docs/windows/SPEC-JV28-ATTACHMENT-PREVIEW.md` 後半段 `JV30`。

```
① 有設定簽核流程時，approve／send_back 的操作人必須是**當前層**的簽核人
   （含有效期間內的代理人）；superadmin **不例外**
② 製票人在當層名單內 ⇒ **可以自簽**；沒有設定流程 ⇒ 維持模組權限
```
📌 更正留著：規格原本的 ② 是「製票人不可核准自己的傳票」，**已撤銷**——
使用者 2026-09-24 逐字：「更正製票人要能自己簽，目前人數不夠」。
那一組題翻面成「可以自簽」，沒有刪掉（翻面後它們釘的是「不要又把自簽擋回去」）。

# 🔴 HEAD 上的現況

`approve_voucher()`／`send_back_voucher()` 只檢查 `_require_voucher_access`
（有 cashier／finance 模組）⇒ 任何有傳票權限的人都能替任何一層按核准，
而畫面上簽核欄照樣印出他的名字——**看起來完全正常**。

# ⚙️ 觀測點

回應碼＋**資料庫裡的狀態沒有前進**（只看 403 不夠：一個先寫入再回 403 的
實作會讓狀態已經被推進）。每一支擋下的題都配一支放行的對照組。
"""
import datetime as _dt
import json

VOUCHERS = "/api/vouchers"

_LINES = [{"account_code": "1113", "debit": 1000, "credit": 0},
          {"account_code": "4111", "debit": 0, "credit": 1000}]


def _login(client, make_user, username, role="superadmin", modules=("cashier",)):
    u, p = make_user(username=username, role=role, modules=list(modules))
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _user_id(username):
    import db
    conn = db.get_db()
    try:
        return int(conn.execute("SELECT id FROM users WHERE username=?",
                                (username,)).fetchone()["id"])
    finally:
        conn.close()


def _set_flow(client, hdr, *approver_usernames):
    """一層，簽核人＝手動挑的這幾位。"""
    r = client.put("/api/settings/approval-flow/voucher", headers=hdr, json={
        "includeSubmitterManagerTier": False,
        "tiers": [{"approvers": [{"userId": _user_id(u), "username": u,
                                  "displayName": u}
                                 for u in approver_usernames]}]})
    assert r.status_code == 200, "存簽核設定失敗：%s %s" % (r.status_code, r.text[:200])


def _clear_flow():
    """讓送審走「沒有設定過簽核流程」的內建兩層（`§161`）。"""
    import db
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM system_settings WHERE key IN"
                     " ('voucher_approval_flow', 'unified_approval_flow')")
        conn.commit()
    finally:
        conn.close()


def _create_and_submit(client, hdr):
    r = client.post(VOUCHERS, headers=hdr, json={"summary": "JV30", "lines": _LINES})
    assert r.status_code == 200, r.text[:200]
    vid = r.json()["id"]
    r = client.post("%s/%s/submit" % (VOUCHERS, vid), headers=hdr)
    assert r.status_code == 200, r.text[:200]
    return vid


def _status(vid):
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT status, approval_json FROM vouchers_all WHERE id=?",
                           (vid,)).fetchone()
        return row["status"], json.loads(row["approval_json"] or "{}")
    finally:
        conn.close()


def _delegate(delegator, delegate, start, end):
    import db
    conn = db.get_db()
    try:
        now = "2026-01-01T00:00:00"
        conn.execute(
            "INSERT INTO approval_delegates (delegator_username, delegate_username, start_date,"
            " end_date, reason, active, created_by, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (delegator, delegate, start, end, "JV30", 1, delegator, now, now))
        conn.commit()
    finally:
        conn.close()


def _approve(client, hdr, vid):
    return client.post("%s/%s/approve" % (VOUCHERS, vid), headers=hdr)


def _send_back(client, hdr, vid):
    return client.post("%s/%s/send-back" % (VOUCHERS, vid), headers=hdr,
                       json={"reason": "JV30"})


# ══════════════════════════════════════════════════════════════════════
# ① ③ 非當層簽核人不可核准——superadmin 也一樣
# ══════════════════════════════════════════════════════════════════════

def test_jv30_superadmin_who_is_not_the_tier_approver_cannot_approve(client, make_user):
    maker, mh = _login(client, make_user, "jv30a_maker")
    appr, _ah = _login(client, make_user, "jv30a_appr")
    other, oh = _login(client, make_user, "jv30a_other", role="superadmin")
    _set_flow(client, mh, appr)
    vid = _create_and_submit(client, mh)

    r = _approve(client, oh, vid)
    assert r.status_code == 403, (
        "superadmin %s 不是這一層的簽核人，按核准卻得到 %s：%s"
        % (other, r.status_code, r.text[:200]))
    assert appr in r.json().get("detail", ""), (
        "403 的訊息要說出這一層的簽核人是誰（%s）：%r" % (appr, r.json()))
    assert _status(vid)[0] == "待審核", "被擋下了，狀態卻已經前進：%r" % (_status(vid),)


def test_jv30_the_designated_tier_approver_can_approve(client, make_user):
    """對照組：同一個設定下，正確的簽核人要能過。"""
    _maker, mh = _login(client, make_user, "jv30b_maker")
    appr, ah = _login(client, make_user, "jv30b_appr")
    _set_flow(client, mh, appr)
    vid = _create_and_submit(client, mh)

    r = _approve(client, ah, vid)
    assert r.status_code == 200, r.text[:200]
    assert _status(vid)[0] == "已核准"


def test_jv30_a_delegate_within_the_period_can_approve_but_not_after_it(client, make_user):
    """代理人：期間內可以（對照組），期間已過不可以。"""
    _maker, mh = _login(client, make_user, "jv30c_maker")
    appr, _ah = _login(client, make_user, "jv30c_appr")
    dele, dh = _login(client, make_user, "jv30c_dele")
    old, olh = _login(client, make_user, "jv30c_old")
    today = _dt.date.today()
    _delegate(appr, dele, (today - _dt.timedelta(days=1)).isoformat(),
              (today + _dt.timedelta(days=1)).isoformat())
    _delegate(appr, old, (today - _dt.timedelta(days=10)).isoformat(),
              (today - _dt.timedelta(days=5)).isoformat())
    _set_flow(client, mh, appr)

    v1 = _create_and_submit(client, mh)
    r = _approve(client, olh, v1)
    assert r.status_code == 403, "代理期間已過還能簽：%s %s" % (r.status_code, r.text[:200])
    assert _status(v1)[0] == "待審核"

    r = _approve(client, dh, v1)
    assert r.status_code == 200, "代理期間內的代理人被擋：%s" % r.text[:200]
    assert _status(v1)[0] == "已核准"


# ══════════════════════════════════════════════════════════════════════
# ② 製票人可以自簽（使用者更正：「製票人要能自己簽，目前人數不夠」）
# ══════════════════════════════════════════════════════════════════════

def test_jv30_the_maker_listed_as_the_tier_approver_can_approve_own_voucher(client, make_user):
    """製票人被挑成這一層的簽核人 ⇒ 可以核准自己的傳票。
    對照組：同一個人**不在**名單內 ⇒ 擋下（製票人沒有比別人多的權限）。"""
    maker, mh = _login(client, make_user, "jv30d_maker")
    other, _oh = _login(client, make_user, "jv30d_other")

    _set_flow(client, mh, other)
    v_not_listed = _create_and_submit(client, mh)
    r = _approve(client, mh, v_not_listed)
    assert r.status_code == 403, (
        "製票人不在當層名單內卻核准了：%s %s" % (r.status_code, r.text[:200]))
    assert _status(v_not_listed)[0] == "待審核"

    _set_flow(client, mh, maker)
    v_listed = _create_and_submit(client, mh)
    r = _approve(client, mh, v_listed)
    assert r.status_code == 200, (
        "製票人就是當層簽核人，自簽卻被擋：%s %s" % (r.status_code, r.text[:200]))
    assert _status(v_listed)[0] == "已核准"


def test_jv30_without_a_configured_flow_the_maker_can_still_approve(client, make_user):
    """沒有設定簽核流程（內建兩層 `§161`）：維持模組權限，製票人自己簽得完兩層。"""
    _maker, mh = _login(client, make_user, "jv30e_maker")
    _clear_flow()
    vid = _create_and_submit(client, mh)
    assert _status(vid)[1].get("tiers") in (None, []), (
        "量尺：這一題要走內建兩層，而送審寫進了簽核鏈：%r" % (_status(vid)[1],))

    for expect in ("簽核中", "已核准"):
        r = _approve(client, mh, vid)
        assert r.status_code == 200, "內建兩層下製票人自簽被擋：%s" % r.text[:200]
        assert _status(vid)[0] == expect


# ══════════════════════════════════════════════════════════════════════
# ① ③ 退回：同樣只限當層簽核人（含代理人），superadmin 不例外
# ══════════════════════════════════════════════════════════════════════

def test_jv30_only_the_tier_approver_can_send_back(client, make_user):
    _maker, mh = _login(client, make_user, "jv30f_maker")
    appr, ah = _login(client, make_user, "jv30f_appr")
    _other, oh = _login(client, make_user, "jv30f_other", role="superadmin")
    _set_flow(client, mh, appr)
    vid = _create_and_submit(client, mh)

    r = _send_back(client, oh, vid)
    assert r.status_code == 403, (
        "非當層簽核人（superadmin）退回了傳票：%s %s" % (r.status_code, r.text[:200]))
    assert _status(vid)[0] == "待審核"

    r = _send_back(client, ah, vid)
    assert r.status_code == 200, r.text[:200]
    assert _status(vid)[0] == "草稿"


def test_jv30_an_approved_voucher_can_be_sent_back_only_by_the_last_tier_approver(
        client, make_user):
    """已核准（每一層都簽完）：`can_send_back` 允許退回，而退回的人要是最後一層的簽核人。"""
    _maker, mh = _login(client, make_user, "jv30g_maker")
    appr, ah = _login(client, make_user, "jv30g_appr")
    _other, oh = _login(client, make_user, "jv30g_other", role="superadmin")
    _set_flow(client, mh, appr)
    vid = _create_and_submit(client, mh)
    assert _approve(client, ah, vid).status_code == 200
    assert _status(vid)[0] == "已核准"

    r = _send_back(client, oh, vid)
    assert r.status_code == 403, "已核准的傳票被非簽核人退回：%s" % r.text[:200]
    assert _status(vid)[0] == "已核准"

    r = _send_back(client, ah, vid)
    assert r.status_code == 200, r.text[:200]
    assert _status(vid)[0] == "草稿"
