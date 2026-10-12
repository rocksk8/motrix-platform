# -*- coding: utf-8 -*-
"""第 57 班小修：①完工單個資告知紀錄讀取守門（原本只要求登入）；②簽核佇列完工單卡片的金額欄標籤。"""
import json
import re
from pathlib import Path

import db

REPO = Path(__file__).resolve().parents[4]
BASE = "/api/completion-notes"


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _case_and_note(client, make_user):
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, "
            "created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("MQ-FX-001", "已送出", "測試客戶", "測試專案", 1, 1, "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00", ""))
        conn.commit()
    finally:
        conn.close()
    u, p = make_user(username="fx_admin", role="admin")
    h = _login(client, u, p)
    r = client.post(BASE, headers=h, json={"quote_no": "MQ-FX-001", "recipient": "陳經理",
                                           "items": [{"description": "x", "qty": 1, "unit": "式", "status": "完成"}]})
    assert r.status_code == 201, r.text
    return r.json()["note_no"], h


# ── 個資告知紀錄讀取守門 ───────────────────────────────────────────────────────

def test_privacy_notice_read_is_refused_for_users_without_case_access(client, make_user):
    note_no, _h = _case_and_note(client, make_user)
    u, p = make_user(username="fx_viewer", role="viewer", modules=["dashboard"])
    r = client.get(f"{BASE}/{note_no}/privacy-notice", headers=_login(client, u, p))
    assert r.status_code == 404 and r.json()["detail"] == "完工單不存在"


def test_privacy_notice_missing_note_and_hidden_note_look_identical(client, make_user):
    note_no, _h = _case_and_note(client, make_user)
    u, p = make_user(username="fx_viewer2", role="viewer", modules=["dashboard"])
    h = _login(client, u, p)
    a = client.get(f"{BASE}/{note_no}/privacy-notice", headers=h)
    b = client.get(f"{BASE}/CN-NOPE-000/privacy-notice", headers=h)
    assert (a.status_code, a.json()) == (b.status_code, b.json())


def test_privacy_notice_read_still_works_for_admin_and_case_manage(client, make_user):
    note_no, h = _case_and_note(client, make_user)
    r = client.get(f"{BASE}/{note_no}/privacy-notice", headers=h)
    assert r.status_code == 200 and r.json() == {"acks": r.json()["acks"]} and isinstance(r.json()["acks"], (list, dict))
    u, p = make_user(username="fx_eng", role="engineer", modules=["case_manage"])
    assert client.get(f"{BASE}/{note_no}/privacy-notice", headers=_login(client, u, p)).status_code == 200


def test_privacy_notice_requires_login(client, make_user):
    note_no, _h = _case_and_note(client, make_user)
    assert client.get(f"{BASE}/{note_no}/privacy-notice").status_code in (401, 403)


# ── 簽核佇列標籤（完工單的 total 是項目數，不是金額）──────────────────────────────

def _fn_body(src, name):
    m = re.search(r"\n\s*%s\(item\) \{(.*?)\n\s{6,8}\},?\n" % name, src, re.S)
    assert m, name
    return m.group(1)


def test_queue_card_labels_completion_note_as_item_count_not_money():
    src = (REPO / "frontend/pages/approval-queue.html").read_text(encoding="utf-8")
    label = _fn_body(src, "amountLabel")
    shown = _fn_body(src, "amountDisplay")
    assert re.search(r"completion_note'\)\s*return\s*'完成項目'", label)
    assert re.search(r"completion_note'\)\s*return\s*\(item\.total \|\| 0\) \+ ' 項'", shown)
    # 順序：完工單分支必須在『預設＝報價金額 NT$』之前
    assert label.index("completion_note") < label.index("return '報價金額'")
    assert shown.index("completion_note") < shown.index("NT$")


def test_queue_api_still_sends_item_count_for_completion_note():
    src = (REPO / "backend/modules/case/api/quotations.py").read_text(encoding="utf-8")
    assert '"total":               len(real_items)' in src
