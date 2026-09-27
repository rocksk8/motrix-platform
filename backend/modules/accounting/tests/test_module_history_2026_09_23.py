"""FN4 的傳票部分（M06 搬遷自 tests/ 同名檔；本模組不在時不跑，L1 的 edit_log 題留在原檔）。

2026-09-26 自 `backend/tests/test_module_history_2026_09_23.py` 移入（PLAYBOOK §B-11：拿掉本模組時這些題跟著消失）。
"""
import json
import pytest
import re
from tests.test_module_history_2026_09_23 import (  # noqa: F401
    VOUCHER_ACCESS,
)


def _voucher_update_path(client):
    """找傳票更新端點。找不到 ⇒ 說出我找過什麼。"""
    from tests._routes import route_paths   # FastAPI 0.14x 不攤平 include_router（見 tests/_routes.py）
    paths = route_paths(client.app)
    cands = [p for p in paths
             if re.search(r"/api/vouchers?/\{[^}]+\}$", p)]
    if not cands:
        pytest.fail(
            "找不到傳票的更新端點（找過 `/api/vouchers/{id}`）。\n"
            "現有 `/api/voucher…` 的路由：%s\n"
            % sorted(p for p in paths if "voucher" in p)
            + "⚠️ 路徑可以換（**退回給我**），而那條路必須存在 ——\n"
              "   `helpers/edit_log.py:88` 的 `append_edit_log()` "
              "**現在沒有任何呼叫端**。")
    return cands[0]


def _seed_draft(conn):
    conn.execute(
        "INSERT INTO vouchers_all (voucher_no, voucher_date, created_by,"
        " created_at, updated_at, status) VALUES "
        "('20260923-900','2026-09-23','C','2026-09-23T00:00:00',"
        "'2026-09-23T00:00:00','草稿')")
    vid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    return vid


def test_fn4_editing_a_draft_voucher_writes_exactly_one_edit_log_row(
        client, make_user):
    """🔴🔴 **在草稿狀態改欄位 ⇒ `voucher_edit_log` 必須多一列。**

    ```
    施工圖 §2.1  voucher_date「可編輯，僅限草稿」＋「改過要進 voucher_edit_log」
    ```
    ☠️ 少了這一列，**沒有人回得出「這張單原本是哪一天」** ——
       而傳票日期決定它落在哪一期，那是會計最在意的一格。
    🔑 這一題打的是**端點**不是函式：〈兩個都對而路不存在〉。

    ⚙️ 而斷言是「**剛好多一列**」不是「至少一列」：
    ```
    0 列  => 沒人叫它
    2 列  => 有人叫了兩次（改一次留兩筆痕，而稽核讀起來像改了兩次）
    ```
    """
    import db as _db
    _u, hdr = _auth_hdr(client, make_user)
    path = _voucher_update_path(client)

    conn = _db.get_db()
    try:
        vid = _seed_draft(conn)
        before = conn.execute(
            "SELECT COUNT(*) FROM voucher_edit_log WHERE voucher_id=?",
            (vid,)).fetchone()[0]
    finally:
        conn.close()

    url = path.replace("{voucher_id}", str(vid)).replace("{id}", str(vid))
    r = client.put(url, json={"voucher_date": "2026-08-31"}, headers=hdr)
    assert r.status_code == 200, (
        "改草稿的日期回 %s：%s" % (r.status_code, r.text[:200]))

    conn = _db.get_db()
    try:
        rows = [dict(x) for x in conn.execute(
            "SELECT * FROM voucher_edit_log WHERE voucher_id=? ORDER BY id",
            (vid,))]
    finally:
        conn.close()

    assert len(rows) - before == 1, (
        "改一個欄位之後 `voucher_edit_log` 多了 %d 列（預期 1）。\n"
        % (len(rows) - before)
        + "☠️ 0 列 ⇒ 沒有人叫 `append_edit_log()`，"
          "**而使用者看不出任何異常**。\n"
          "   2 列以上 ⇒ 改一次留兩筆痕，稽核讀起來像改了兩次。")

    changes = json.loads(rows[-1]["changes_json"])
    assert changes, "`changes_json` 是空的 —— 那一列什麼都沒記。"
    entry = next((c for c in changes if c.get("field") == "voucher_date"), None)
    assert entry is not None, (
        "`changes_json` 裡沒有 `voucher_date`：%r" % (changes,))
    assert "from" in entry and entry["from"] == "2026-09-23", (
        "改前值是 %r，而它原本是 '2026-09-23'。\n" % entry.get("from")
        + "☠️ 少了改前值，那一列**回答不出「原本是什麼」** ——\n"
          "   而那正是逐筆紀錄唯一要回答的問題。")


def test_fn4_no_change_writes_no_row(client, make_user):
    """⚙️ **反向控制：沒有改動時不可以寫入空紀錄。**

    ☠️ 少了它，一個「每次 PUT 都寫一列」的實作也會讓上面那題綠 ——
       而症狀是**紀錄被灌水**：稽核打開看到十列，而使用者只改過一次。
    🔑 而灌水比漏記更難發現：**它看起來像「記得很完整」。**
    """
    import db as _db
    _u, hdr = _auth_hdr(client, make_user)
    path = _voucher_update_path(client)

    conn = _db.get_db()
    try:
        vid = _seed_draft(conn)
    finally:
        conn.close()

    url = path.replace("{voucher_id}", str(vid)).replace("{id}", str(vid))
    r = client.put(url, json={"voucher_date": "2026-09-23"}, headers=hdr)
    assert r.status_code == 200, r.text

    conn = _db.get_db()
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM voucher_edit_log WHERE voucher_id=?",
            (vid,)).fetchone()[0]
    finally:
        conn.close()
    assert n == 0, (
        "送了一組**與現值相同**的資料，而 `voucher_edit_log` 多了 %d 列。\n" % n
        + "☠️ 紀錄被灌水 ⇒ 稽核打開看到十列，而使用者只改過一次。\n"
        + "🔑 灌水比漏記難發現：**它看起來像「記得很完整」。**")


def _auth_hdr(client, make_user, role="superadmin"):
    u, p = make_user(role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _user_with(make_user, client, role, modules, username):
    """建一個**指定模組**的帳號並登入。

    🔴 `users.modules` 存的是 **JSON 字串**（B 實測踩過）——
       餵純字串的話 `json.loads` 失敗 ⇒ `user_has_module` 回 `False`
       ⇒ 一個「明明有權限」的帳號拿到 403，**而那是量具壞了不是產品**。
    ⚠️ 而 `modules=None` 會套角色樣板 ⇒ 要驗「沒有模組」必須明著傳 `[]`。
    """
    u, p = make_user(username=username, role=role, modules=modules)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.mark.parametrize("role,modules,allowed,why", VOUCHER_ACCESS,
                         ids=[f"{r}_{'-'.join(m) or 'none'}"
                              for r, m, _a, _w in VOUCHER_ACCESS])
def test_fn4_who_may_read_a_voucher(client, make_user, role, modules,
                                    allowed, why):
    """🔴 **`GET /api/vouchers/{id}` 的權限：七格全列。**

    ```
    routers/vouchers.py:34  _VOUCHER_MODULES = ("cashier", "finance")
                      :43  require_any_module(user, _VOUCHER_MODULES, "傳票")
    ```
    📌 用 `require_any_module` 而**不是** `role in ("superadmin","admin")` ——
       使用者 2026-09-14 裁示逐字：「**管理者一樣依據有開權限的內容去顯示**」。

    ☠️ 兩個最容易做反的方向，各自都有一格：
    ```
    admin 無模組  => **403**（直通回來的話，`MODULE-AUDIT §5` 那件事就復發）
    user 有 reports => **403**（不是「有任何模組就行」）
    ```
    🔑 而它們**不會報錯** —— 擋錯人的症狀是「他說他看不到」，
       放錯人的症狀是**沒有症狀**。
    """
    import db as _db
    hdr = _user_with(make_user, client, role, modules,
                     "vperm_%s_%s" % (role, "".join(modules) or "none"))
    conn = _db.get_db()
    try:
        vid = _seed_draft(conn)
    finally:
        conn.close()

    r = client.get("/api/vouchers/%d" % vid, headers=hdr)
    if allowed:
        assert r.status_code == 200, (
            "%s（%s／%s）被擋下來了：%s %s\n"
            % (why, role, modules or "無模組", r.status_code, r.text[:120])
            + "⚙️ 這是正對照：少了它，「一律 403」也會讓下面那幾格綠，\n"
              "   **而那樣沒有任何人打得開傳票**。")
    else:
        assert r.status_code == 403, (
            "%s（%s／%s）**通過了**（回 %s）\n"
            % (why, role, modules or "無模組", r.status_code)
            + "☠️ 放錯人**沒有症狀** —— 沒有人會來報修「我看得到我不該看的東西」。")


@pytest.mark.parametrize("role,modules,allowed,why", VOUCHER_ACCESS,
                         ids=[f"{r}_{'-'.join(m) or 'none'}"
                              for r, m, _a, _w in VOUCHER_ACCESS])
def test_fn4_who_may_edit_a_draft_voucher(client, make_user, role, modules,
                                          allowed, why):
    """🔴 **`PUT /api/vouchers/{id}` 走同一道閘。**

    ⚠️ B 自己標了「**沒評估多一支 PUT 對權限稽核的影響**」——
       那一格不能留白：**新增一條路徑就是新增一個入口**。
    ☠️ 而讀與寫用不同判準是最常見的形狀：
    ```
    GET 擋住了、PUT 忘了擋 => 他看不到那張單，**而他改得動它**
    ```
    🔑 而那不會有任何症狀 —— 直到有人問「這張單為什麼變了」。
    """
    import db as _db
    hdr = _user_with(make_user, client, role, modules,
                     "vput_%s_%s" % (role, "".join(modules) or "none"))
    conn = _db.get_db()
    try:
        vid = _seed_draft(conn)
    finally:
        conn.close()

    r = client.put("/api/vouchers/%d" % vid,
                   json={"voucher_date": "2026-08-31"}, headers=hdr)
    if allowed:
        assert r.status_code == 200, (
            "%s（%s／%s）改不了草稿：%s %s"
            % (why, role, modules or "無模組", r.status_code, r.text[:120]))
    else:
        assert r.status_code == 403, (
            "%s（%s／%s）**改得動**（回 %s）\n"
            % (why, role, modules or "無模組", r.status_code)
            + "☠️ 讀擋住了而寫沒擋：**他看不到那張單，而他改得動它** ——\n"
              "   直到有人問「這張單為什麼變了」。")
