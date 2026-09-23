# -*- coding: utf-8 -*-
"""`BN17` · 獎金分潤單退回要有按鈕並且記錄。

使用者原話：「獎金單也要退回的按鈕並且記錄」。

# 🔴 動工前查證：①「按鈕」前提不成立，已回報 A

```
bonus.html:544-561  退回按鈕／原因輸入框／確定鈕**都已經存在**，
                    確定鈕已經 `:disabled="... || !awardReasonText.trim()"`
                    （前端已經擋空原因）
bonus.js:545        rejectAward() 已經把 reason 送進 POST /reject
```
⇒ 本檔**不測「按鈕看不看得見」**——那格已經對了。

# ⚙️ 真正缺的，與 `SPEC-JV22`（傳票退回要留長期記憶）同一個形狀

```
❌ 後端 reject_award()（bonus.py:867）完全沒驗 reason 非空
   ——前端擋得住 UI，直接打 API 繞得過去（〈前端過濾是假的〉）
❌ 沒有寫進 bonus_award_edit_log（表存在，v98 建的，
   全 backend/routers/bonus.py 零筆 append_edit_log 呼叫）
❌ 沒有 GET 端點可以讀這張表
❌ bonus_award_edit_log 沒有防刪 TRIGGER
```

# 🔑 本檔直接照抄 `SPEC-JV22` 已經裁過的答案，不重新想一套

```
② 理由必填          照 void_voucher 的先例（「沒有理由的作廢等於沒有留痕」）
③ 記錄落點          bonus_award_edit_log（既有表，不加欄不加表）
   retention        "permanent"（JV22 §2b 的裁定：長期記憶的承諾要標成
                    不會被清理排程掃到的值，不是新增一條規則）
④ 「不能刪除」       資料庫層 TRIGGER（BEFORE DELETE -> RAISE(ABORT)）
                    ＋ 靜態掃描 backend/** 沒有 `DELETE FROM
                    bonus_award_edit_log`，兩道都要（一道擋「有人寫」，
                    一道擋「寫了會成功」）
```

# ⚠️ 這一件比 `JV22` 簡單一格：**沒有換單號**

傳票的 `send_back` 會把 `voucher_no` 升版（`-R1`），`JV22 §5` 花了一整節
確認下游沒有存字串型的單號才不受影響。獎金單的 `reject_award()` 完全
不碰 `award_id`（整數主鍵），**award_id 不會變**——這一格不必驗證。

# ⚠️ 與 `JV22` 共用的那道 TRIGGER 可能會撞

`SPEC-JV22 §3` 的裁定原話：「TRIGGER 要**同時保護** `bonus_award_edit_log`」
——若做 `JV22` 的人已經把兩張表一起蓋了，本檔的 `④` 會提早變綠，那是
好事，不是重複勞動：兩邊各自的紅測試互為對方的正對照。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_bonus_award_approval_2026_09_23 import (  # noqa: E402
    AWARDS, _act, _hdr, _seed_award, _set_flow,
)

EDIT_LOG = AWARDS + "/%s/edit-log"


def _to_pending(client, make_user, quote_no, tier_names, people=("someone",)):
    """建一張獎金單，設定簽核層，送審到「待審核」／「簽核中」。回 `(hdr, aid)`。"""
    _u, hdr = _hdr(client, make_user, "bn17_owner_" + quote_no)
    _set_flow(client, hdr, make_user, tier_names)
    aid = _seed_award(quote_no, list(people))
    r = _act(client, hdr, aid, "submit")
    assert r.status_code == 200, "送審失敗：%s %s" % (r.status_code, r.text[:200])
    return hdr, aid


def _edit_log(client, hdr, aid):
    r = client.get(EDIT_LOG % aid, headers=hdr)
    if r.status_code in (404, 405, 422):
        pytest.fail(
            "`GET %s` 走不到（回 %s）——路徑是我單方面定的，"
            "改了退回給我。" % (EDIT_LOG % "{award_id}", r.status_code))
    return r


# ══════════════════════════════════════════════════════════════════════
# ① 後端必須驗 reason 非空（前端的檢查繞得過去）
# ══════════════════════════════════════════════════════════════════════

def test_bn17_rejecting_without_a_reason_is_refused_by_the_backend(
        client, make_user):
    """🔴🔴 **核心：退回不填原因，後端要拒絕，不是只靠前端擋。**

    ⚙️ 照 `void_voucher()` 的先例：「請填寫作廢原因」——這裡直接打 API，
    繞過前端 `:disabled` 那一關，模擬有人用別的用戶端呼叫。
    """
    hdr, aid = _to_pending(client, make_user, "MQ-BN17-EMPTY", ("bn17_e_a",))
    r = _act(client, hdr, aid, "reject", {"reason": ""})
    assert r.status_code == 400, (
        "沒填原因的退回被接受了（回 %s）：%s\n" % (r.status_code, r.text[:200])
        + "☠️ 前端的 `:disabled` 擋得住畫面，擋不住直接打 API 的人——\n"
          "   〈前端過濾是假的：值仍然在 API 回應裡〉。")


def test_bn17_rejecting_with_only_whitespace_is_also_refused(client, make_user):
    """🔴 **只有空白字元的「原因」要視同沒填——不能靠字串非空這種寬鬆判準。**"""
    hdr, aid = _to_pending(client, make_user, "MQ-BN17-WS", ("bn17_w_a",))
    r = _act(client, hdr, aid, "reject", {"reason": "　  "})
    assert r.status_code == 400, (
        "只有空白字元的原因被接受了（回 %s）。" % r.status_code)


def test_bn17_rejecting_with_a_real_reason_still_succeeds(client, make_user):
    """⚙️ **正對照：填了真的原因，退回照樣成功——不是把整支端點都擋死了。**"""
    hdr, aid = _to_pending(client, make_user, "MQ-BN17-OK", ("bn17_ok_a",))
    r = _act(client, hdr, aid, "reject", {"reason": "科目金額算錯了"})
    assert r.status_code == 200, (
        "填了原因卻被拒絕（回 %s）：%s" % (r.status_code, r.text[:200]))


# ══════════════════════════════════════════════════════════════════════
# ② 退回要寫進 bonus_award_edit_log（結構化、長期）
# ══════════════════════════════════════════════════════════════════════

def test_bn17_rejecting_writes_a_structured_entry_to_the_edit_log(
        client, make_user):
    """🔴🔴 **退回要寫一筆結構化紀錄進 `bonus_award_edit_log`，
    不是只進 `audit_log`（`audit_log` 有 730 天清理排程）。**

    ⚙️ 直接讀資料表，不猜 GET 端點的回應格式——這一題只驗「有沒有寫」，
    下一題才驗「讀不讀得到」。
    """
    hdr, aid = _to_pending(client, make_user, "MQ-BN17-LOG", ("bn17_log_a",))
    reason = "承辦人資料填錯"
    r = _act(client, hdr, aid, "reject", {"reason": reason})
    assert r.status_code == 200, r.text[:200]

    import db
    conn = db.get_db()
    try:
        rows = [dict(x) for x in conn.execute(
            "SELECT * FROM bonus_award_edit_log WHERE award_id = ?"
            " ORDER BY id", (aid,))]
    finally:
        conn.close()
    assert rows, (
        "退回之後 `bonus_award_edit_log` 一筆都沒有——\n"
        "☠️ 唯一的紀錄只進了 `audit_log`，而它兩年後會被清理排程刪掉。")

    import json
    all_changes = []
    for row in rows:
        all_changes.extend(json.loads(row["changes_json"] or "[]"))
    reason_entries = [c for c in all_changes if reason in str(c.get("to") or "")]
    assert reason_entries, (
        "寫進 `bonus_award_edit_log` 的內容裡找不到退回原因「%s」：%r"
        % (reason, all_changes))


def test_bn17_the_edit_log_entry_uses_permanent_retention(client, make_user):
    """🔴 **退回那一筆的 `retention` 要是 `\"permanent\"`，不是預設值 `\"term\"`。**

    📌 `SPEC-JV22 §2b` 的裁定：長期記憶的承諾要指出它存在哪一張不會被
    清理排程碰的表；`retention` 欄位已經是這張表的既有概念，標成
    `permanent` 不是新增規則，是把它標對。
    """
    hdr, aid = _to_pending(client, make_user, "MQ-BN17-PERM", ("bn17_perm_a",))
    r = _act(client, hdr, aid, "reject", {"reason": "測試永久保留"})
    assert r.status_code == 200, r.text[:200]

    import db
    conn = db.get_db()
    try:
        rows = [dict(x) for x in conn.execute(
            "SELECT retention FROM bonus_award_edit_log WHERE award_id = ?",
            (aid,))]
    finally:
        conn.close()
    assert rows, "退回之後找不到任何 `bonus_award_edit_log` 記錄——先看上一題。"
    assert any(r_["retention"] == "permanent" for r_ in rows), (
        "沒有任何一筆的 `retention` 是 `\"permanent\"`：%r\n" % rows
        + "☠️ 用預設值 `\"term\"` 的話，這筆紀錄有一天會被清理排程當成"
          "可以刪的東西處理——那正是使用者說「不能刪除」要防的事。")


def test_bn17_two_rejections_keep_both_reasons_not_just_the_latest(
        client, make_user):
    """🔴🔴 **`§4`：退回之後再送審、又被退回，前一次的退回理由不可以消失。**

    🔑 這是使用者說的「並且記錄」的重點——他要看得到**上一次**為什麼被退，
    不是只有最新一次。
    """
    hdr, aid = _to_pending(client, make_user, "MQ-BN17-TWICE", ("bn17_t_a",))
    r1 = _act(client, hdr, aid, "reject", {"reason": "第一次退回：金額錯"})
    assert r1.status_code == 200, r1.text[:200]

    r_submit = _act(client, hdr, aid, "submit")
    assert r_submit.status_code == 200, (
        "重新送審失敗：%s %s" % (r_submit.status_code, r_submit.text[:200]))

    r2 = _act(client, hdr, aid, "reject", {"reason": "第二次退回：人員名單錯"})
    assert r2.status_code == 200, r2.text[:200]

    import db
    import json
    conn = db.get_db()
    try:
        rows = [dict(x) for x in conn.execute(
            "SELECT changes_json FROM bonus_award_edit_log WHERE award_id = ?"
            " ORDER BY id", (aid,))]
    finally:
        conn.close()
    all_changes = []
    for row in rows:
        all_changes.extend(json.loads(row["changes_json"] or "[]"))
    joined = json.dumps(all_changes, ensure_ascii=False)
    assert "第一次退回：金額錯" in joined, (
        "第一次的退回原因不見了——只剩最新一次：%r" % all_changes)
    assert "第二次退回：人員名單錯" in joined, (
        "第二次的退回原因反而沒寫進去：%r" % all_changes)


# ══════════════════════════════════════════════════════════════════════
# ③ 讀取端：GET 端點要讀得到
# ══════════════════════════════════════════════════════════════════════

def test_bn17_the_edit_log_is_readable_through_a_new_endpoint(client,
                                                               make_user):
    """🔴🔴 **新端點要能讀到退回記錄——訊號在，不能只寫不讀。**

    📌 〈缺欄位≠缺訊號〉的反面：這裡兩邊都要有，寫了沒有讀的入口，
    使用者一樣看不到。
    """
    hdr, aid = _to_pending(client, make_user, "MQ-BN17-READ", ("bn17_r_a",))
    reason = "讀取端測試原因"
    r = _act(client, hdr, aid, "reject", {"reason": reason})
    assert r.status_code == 200, r.text[:200]

    got = _edit_log(client, hdr, aid)
    assert got.status_code == 200, (
        "讀退回記錄失敗：%s %s" % (got.status_code, got.text[:200]))
    assert reason in got.text, (
        "端點回應裡找不到退回原因「%s」：%s" % (reason, got.text[:300]))


def test_bn17_the_edit_log_endpoint_requires_voucher_style_access_control(
        client, make_user):
    """🔴 **讀取端要有權限閘門，不是誰登入都能看到誰退回了什麼。**

    ⚙️ 不要求特定的閘門實作，只驗「完全沒登入打不進去」——這是最低限度、
    幾乎不可能被合理地反駁的一條線。
    """
    aid_hdr = _hdr(client, make_user, "bn17_authz_owner")
    _u, hdr = aid_hdr
    aid = _seed_award("MQ-BN17-AUTHZ", ["someone"])
    r = client.get(EDIT_LOG % aid)  # 沒帶 Authorization
    assert r.status_code in (401, 403), (
        "沒有登入也能讀到退回記錄（回 %s）：%s" % (r.status_code, r.text[:200]))


# ══════════════════════════════════════════════════════════════════════
# ④ 不能刪除：資料層 TRIGGER ＋ 靜態掃描
# ══════════════════════════════════════════════════════════════════════

def test_bn17_deleting_from_the_edit_log_is_blocked_at_the_database_layer(
        client, make_user):
    """🔴🔴 **資料庫層要擋得住 `DELETE FROM bonus_award_edit_log`。**

    📌 依據 `SPEC-JV22 §3`：「這是『沒有人寫』的保護，不是資料庫層擋下來
    的保護……若之後有人比照 `_prune_audit_log()` 寫一支保留期清理，今天
    沒有任何機制擋得住。」照 `account_items` 那 5 個既有 TRIGGER 的形狀：
    `BEFORE DELETE -> RAISE(ABORT)`。

    🔴 **這一題與 `JV22` 共用同一個實作**——`SPEC-JV22 §3` 裁定這道
    TRIGGER 要「同時保護 `bonus_award_edit_log`」，不是各自蓋一份。
    ⇒ 誰先做 `JV22` 或 `BN17`，這道 TRIGGER 就會**順便**做完另一邊；
    後做的人看到這一題已經綠了，**不是漏做，是先做的人已經覆蓋了兩張
    表**（A 已裁：不要重複做，兩邊互為正對照）。
    """
    hdr, aid = _to_pending(client, make_user, "MQ-BN17-DEL", ("bn17_d_a",))
    r = _act(client, hdr, aid, "reject", {"reason": "測試防刪"})
    assert r.status_code == 200, r.text[:200]

    import db
    import sqlite3
    conn = db.get_db()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM bonus_award_edit_log WHERE award_id = ?",
                        (aid,))
            conn.commit()
    finally:
        conn.rollback()
        conn.close()


def test_bn17_no_code_path_deletes_from_the_edit_log():
    """✅ **靜態掃描：`backend/**` 裡不可以有任何
    `DELETE FROM bonus_award_edit_log`（不含 `tests/`／`rollback_snapshots/`）。**

    🎣 **正對照**：先確認掃描器抓得到已知會命中的字串（合成一句，不用
    產品碼裡的真實案例——那天產品碼修好了，正對照也會跟著失效）。
    """
    import re
    root = Path(__file__).resolve().parents[2]
    pattern = re.compile(r"DELETE\s+FROM\s+bonus_award_edit_log", re.I)

    synthetic = "conn.execute(\"DELETE FROM bonus_award_edit_log WHERE 1=1\")"
    assert pattern.search(synthetic), "掃描器的正則本身抓不到誘餌字串——退回改本題。"

    hits = []
    for py in (root / "backend").rglob("*.py"):
        parts = py.relative_to(root).parts
        if "tests" in parts or "rollback_snapshots" in parts:
            continue
        text = py.read_text(encoding="utf-8", errors="replace")
        if pattern.search(text):
            hits.append(str(py.relative_to(root)))
    assert not hits, (
        "找到會刪除 `bonus_award_edit_log` 的程式碼：%r\n" % hits
        + "☠️ 使用者說「不能刪除」——這張表不應該有任何 DELETE 路徑。")
