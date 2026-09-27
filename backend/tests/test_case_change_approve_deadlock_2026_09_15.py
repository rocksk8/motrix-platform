"""已結案變更申請核准會卡十幾秒（2026-09-15 使用者回報）。

**根因是這個 codebase 已經記載過的同一個坑**（2026-09-10 `create_quotation`
踩過，見 `modules/case/api/quotations.py` 該函式的註解）：

    save_quotation_json(conn, ...)   # 只 execute、不 commit → conn 持有寫鎖
    _audit(...)                      # 用 get_db() 另開一條連線寫入 → 撞自己的鎖

SQLite 同時只允許一個 writer。`db.py::_connect()` 是 `connect(timeout=30)`，
所以第二條連線會**等到逾時才放棄**——使用者感受到的「卡住十幾秒」就是這個；
而 `_audit()` 的 `except` 會把逾時例外吞掉，**稽核紀錄同時被靜默丟掉**。

這裡的兩個觀測點刻意都挑「事後看得出來」的下游效果：
  ① 整個請求的耗時（卡住 vs 正常）
  ② 稽核紀錄有沒有真的寫進去（被吞掉的話就沒有）
只驗回傳碼是看不出來的——這支端點在卡完之後仍然回 200。
"""
import json
import time

import pytest


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _seed(quote_no="MQ-202608-555"):
    """一張已結案案件 ＋ 一筆 pending 的變更申請。"""
    from db import get_db
    cr = {
        "stages": [],
        "payment": {"items": [{"type": "訂金款", "amount": 1000, "received": False}]},
        "materials": [], "devices": [],
        "contract": {"deliveryAddress": "台北市"},
        "roles": {"filler": "甲", "sales": "乙", "executor": "丙"},
    }
    conn = get_db()
    conn.execute(
        "INSERT INTO quotations (quote_no, status, customer_name, project_name, "
        "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?)",
        (quote_no, "已送出", "客戶", "專案",
         json.dumps({"caseRecord": cr}, ensure_ascii=False),
         "2026-08-01", "2026-08-01", "已結案"))
    new_cr = dict(cr)
    new_cr["contract"] = {"deliveryAddress": "新北市"}
    cur = conn.execute(
        "INSERT INTO case_change_requests (quote_no, action_type, summary, payload_json, "
        "staged_files_json, status, requested_by, requested_by_display, requested_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (quote_no, "case_record_update", "更新交貨地址",
         json.dumps({"case_record": new_cr}, ensure_ascii=False), "[]", "pending",
         "someone_else", "申請人", "2026-09-15T01:00:00"))
    cid = cur.lastrowid
    conn.commit()
    conn.close()
    return quote_no, cid


def test_approve_does_not_block_on_its_own_write_lock(client, make_user):
    """核准要在合理時間內完成。

    有 bug 時這題會跑滿 SQLite 的 30 秒 busy_timeout 才失敗——**慢得很明顯，
    那正是重點**：使用者回報的就是「卡住十幾秒」。修好之後它是毫秒等級。
    """
    u, p = make_user(username="dl_sa", role="superadmin")
    headers = _login(client, u, p)
    quote_no, cid = _seed()

    t0 = time.monotonic()
    r = client.post(f"/api/case-changes/{cid}/approve", headers=headers)
    elapsed = time.monotonic() - t0

    assert r.status_code == 200, r.text
    assert elapsed < 5, (
        f"核准花了 {elapsed:.1f} 秒——外層 conn 還握著寫鎖時又另開一條連線寫入，"
        f"撞上 SQLite 單一 writer，等到 busy_timeout 才放行")


def test_approve_actually_writes_the_audit_record(client, make_user):
    """稽核紀錄要真的進得去。

    這一題才是「卡住」之外真正危險的部分：`_audit()` 的 except 會把逾時例外
    吞掉，所以撞鎖的時候**畫面顯示核准成功、稽核紀錄卻不存在**——事後要查
    「這筆已結案變更是誰核准的」會查不到。
    """
    from db import get_db

    u, p = make_user(username="dl_sa2", role="superadmin")
    headers = _login(client, u, p)
    quote_no, cid = _seed("MQ-202608-556")

    r = client.post(f"/api/case-changes/{cid}/approve", headers=headers)
    assert r.status_code == 200, r.text

    conn = get_db()
    rows = [dict(x) for x in conn.execute(
        "SELECT action, target_id FROM audit_log WHERE target_id=? AND action='case.update'",
        (quote_no,)).fetchall()]
    conn.close()
    assert rows, "核准成功但沒有留下 case.update 稽核紀錄（被撞鎖的例外吞掉了）"


def test_the_change_is_actually_applied(client, make_user):
    """正向控制：不要靠「什麼都沒做」讓上面兩題變綠。"""
    from db import get_db

    u, p = make_user(username="dl_sa3", role="superadmin")
    headers = _login(client, u, p)
    quote_no, cid = _seed("MQ-202608-557")

    r = client.post(f"/api/case-changes/{cid}/approve", headers=headers)
    assert r.status_code == 200, r.text

    conn = get_db()
    row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?",
                       (quote_no,)).fetchone()
    req = conn.execute("SELECT status FROM case_change_requests WHERE id=?",
                       (cid,)).fetchone()
    conn.close()
    cr = json.loads(row["data_json"])["caseRecord"]
    assert cr["contract"]["deliveryAddress"] == "新北市", "變更沒有被套用"
    assert req["status"] == "approved"


def test_payment_mark_branch_also_does_not_block(client, make_user):
    """另一條分支（標記收款）走的是同一個「先寫後 audit」的形狀，一起釘住。"""
    from db import get_db

    u, p = make_user(username="dl_sa4", role="superadmin")
    headers = _login(client, u, p)
    quote_no = "MQ-202608-558"
    cr = {"payment": {"items": [{"type": "訂金款", "amount": 1000, "received": False}]}}
    conn = get_db()
    conn.execute(
        "INSERT INTO quotations (quote_no, status, customer_name, project_name, "
        "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?)",
        (quote_no, "已送出", "客戶", "專案",
         json.dumps({"caseRecord": cr}, ensure_ascii=False),
         "2026-08-01", "2026-08-01", "已結案"))
    cur = conn.execute(
        "INSERT INTO case_change_requests (quote_no, action_type, summary, payload_json, "
        "staged_files_json, status, requested_by, requested_by_display, requested_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (quote_no, "payment_mark", "標記已收款",
         json.dumps({"idx": 0, "body": {"received": True, "receivedAt": "2026-09-15"}},
                    ensure_ascii=False),
         "[]", "pending", "someone_else", "申請人", "2026-09-15T01:00:00"))
    cid = cur.lastrowid
    conn.commit()
    conn.close()

    t0 = time.monotonic()
    r = client.post(f"/api/case-changes/{cid}/approve", headers=headers)
    elapsed = time.monotonic() - t0
    assert r.status_code == 200, r.text
    assert elapsed < 5, f"payment_mark 分支也卡住了（{elapsed:.1f} 秒）"

    conn = get_db()
    rows = conn.execute(
        "SELECT 1 FROM audit_log WHERE target_id=? AND action='payment.mark'",
        (quote_no,)).fetchall()
    conn.close()
    assert rows, "payment_mark 分支的稽核紀錄被吞掉了"
