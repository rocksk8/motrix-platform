# -*- coding: utf-8 -*-
"""`BN17` · 獎金分潤單退回要有按鈕並且記錄。

使用者原話：「獎金單也要退回的按鈕並且記錄」。

# 🔴 2026-09-23 改名（原檔名 test_bonus_award_reject_record）

**這一支紅著是 `JV22 §3` 的 TRIGGER 沒有人做，不是 `BN17` 沒做完。**
`SPEC-BN17.md §6 AC1` 逐點驗收的主檔是 `test_bn17_award_reject_record_
2026_09_23.py`（12 題全綠）。本檔現在的定位是**追蹤 `JV22 §3` 那道
「TRIGGER 要同時保護 voucher_edit_log 與 bonus_award_edit_log」的裁定
還沒有人落地**——`db.py` 全庫 `grep CREATE TRIGGER` 目前仍是 0 筆命中
`edit_log`。改名理由：兩個 BN17 檔案名字只差一個字（`bonus_award` vs
`bn17_award`），B 交件時看錯檔，誤以為「C 的 12 題全綠」涵蓋了這一支。

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
   全 backend/modules/payroll/api/bonus.py 零筆 append_edit_log 呼叫）
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

# 🔴 2026-09-23 更正（本檔寫完之後才發生）：③「新端點」這個前提是我猜錯的

`SPEC-BN17.md` 後來落地，A-2 明著裁定**不加新端點**——讀取端折進既有的
`GET /awards/{id}`，多一個 `last_reject` 欄位（§4③：「讀取端：只有一半
成得立」，因為獎金單退回後改不動內容，沒有 `JV22` 那種「這次編修」可以
配對）。當時我用 `SPEC-JV22`（傳票）的形狀直接套過來，猜了一個
`GET /awards/{id}/edit-log`，而**那支端點從來不存在**——不是 B 漏做，是
規格後來決定用不同的落點。下面兩題已經改成打真的端點（過程中還抓到
第二個錯：改完第一版直接沿用本檔 import 進來的 `_award()`，而那支打的
是 `GET /awards`**清單**端點，`last_reject` 只算在明細端點裡，清單裡
永遠沒有這個鍵——已改成直接呼叫 `GET /awards/{id}`）。`db.py` 全庫
`grep CREATE TRIGGER` 目前也還是 0 筆命中 `edit_log`（`account_items`
以外沒有任何一張表有防刪 TRIGGER），④ 的**資料庫層 TRIGGER 那一題仍然
是真的紅**（靜態掃描那一題本來就綠，兩道防線只有一道到位）——那是
`JV22 §3` 自己的裁定還沒有人落地，不是這次順便造出來的新缺口，不歸
本檔或 `BN17` 的範圍修，維持原樣讓它繼續紅。
"""

# ── 2026-09-24 移除（SPEC-BONUS §十一）───────────────────────────────────────
# 舊「獎金項目＋分潤單」流程停用：寫入端點回 410、bonus.html 改為以案件為中心的新頁面
# （使用者：「上一次開發的內容我無法接受」「重做成新流程」、舊單「舊的都是開發機測試用，直接作廢」）。
# 本檔下列題驗的是已停用的流程，已移除；新流程的題見 test_bonus_case_*_2026_09_24.py、
# test_e2e_bonus_case_page_2026_09_24.py、test_bonus_legacy_retired_2026_09_24.py。
# 移除：test_bn17_deleting_from_the_edit_log_is_blocked_at_the_database_layer、test_bn17_rejecting_with_a_real_reason_still_succeeds、test_bn17_rejecting_with_only_whitespace_is_also_refused、test_bn17_rejecting_without_a_reason_is_refused_by_the_backend、test_bn17_rejecting_writes_a_structured_entry_to_the_edit_log、test_bn17_the_edit_log_entry_uses_permanent_retention、test_bn17_the_edit_log_is_readable_through_the_existing_detail_endpoint、test_bn17_two_rejections_keep_both_reasons_not_just_the_latest
# 同檔其餘題驗的是仍在運作的部分（讀取端點、群組、輔助函式），保留。
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_bonus_award_approval_2026_09_23 import (  # noqa: E402
    AWARDS, _act, _hdr, _seed_award, _set_flow,
)


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

def test_bn17_the_detail_endpoint_still_requires_login(client, make_user):
    """🔴 **讀退回記錄要走既有的登入閘門，不是誰都能看到誰退回了什麼。**

    ⚙️ 不要求特定的閘門實作，只驗「完全沒登入打不進去」——這是最低限度、
    幾乎不可能被合理地反駁的一條線。與既有的 `GET /awards/{id}` 共用
    同一道閘門，不必另外設計一套。
    """
    aid = _seed_award("MQ-BN17-AUTHZ", ["someone"])
    r = client.get("%s/%s" % (AWARDS, aid))  # 沒帶 Authorization
    assert r.status_code in (401, 403), (
        "沒有登入也能讀到獎金單明細（含退回記錄）（回 %s）：%s"
        % (r.status_code, r.text[:200]))


# ══════════════════════════════════════════════════════════════════════
# ④ 不能刪除：資料層 TRIGGER ＋ 靜態掃描
# ══════════════════════════════════════════════════════════════════════

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
