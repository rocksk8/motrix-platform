# -*- coding: utf-8 -*-
"""`BN7` · 獎金分潤單 PDF 匯出 ＋ 用印欄（`SPEC-BN6-BN7.md §4/§5`，使用者
2026-09-23 裁：用印欄列數由簽核設定決定，與傳票、報價單同一套規則）。

```
✅ §5 三選一已解：走 (a) 完整簽核鏈——前提 BN8 已把 submit/approve/reject
   接上（e4572ae／e6cf983），寫規格當下這條路走不通，現在走得通了。
```

# ⚙️ 端點：`GET /api/bonus/awards/{award_id}/pdf-download`

`SPEC-BN6-BN7.md §4` 定案的路徑，沿用既有 16 個呼叫端同一形狀
（`权限`：`_is_manager`，與 `POST /awards` 同一道閘）。

# 🔴 四格，其中 ④ 是 A 已經裁定的（不是我自己假設）

```
① 用印欄列數**來自簽核設定**，不是寫死
   ⚠️ 對照組：**改簽核設定的層數，PDF 的用印欄跟著變**——
      少了這個對照，「印固定兩格」在今天剛好是兩層時也會全綠
② 名字用**顯示名稱**不是帳號（`helpers/voucher.py::_resolve_display_names`
   已經解過同一個問題，這裡驗**輸出**，不驗是不是呼叫同一支函式）
③ 抬頭來自 `company_profile`——`JV9` 的雙重 `json.loads` 坑
   （`_get_setting()` 已經 loads 過，若這支新 builder 又 loads 一次會
   `TypeError`）在這支新的 builder 上有機會**重犯**，照 JV9 的形狀驗
④ 已核准／已過帳 -> 放；草稿／待審核／簽核中 -> 擋；
   任何狀態 ＋ 已作廢 -> 放（A 裁：與傳票 `JV11`／`JV15` 同一條）
```

## ⚠️ `JV11` 踩過的坑，這裡直接抄教訓不重踩

```
A 原話：「條件是未簽核完成，不是狀態不等於已核准」
B 實作成 status == "已核准" => 已過帳的傳票匯不出來（JV15 才補回來）
⇒ 一條「不要用 X 判斷」的界線，要配一份「那用什麼」的清單。
```
⇒ 這裡的驗收**直接沿用 `helpers/voucher.py::approval_done()` 的狀態
清單**（`voided_at` 為真 -> 放；`status == "已核准"` -> 放；其餘視鏈而定），
不自己重寫一條「狀態不等於 X」的判斷。獎金單今天沒有「已過帳」這個
狀態（`BN8` 的狀態機只有草稿／待審核／簽核中／已核准四個），所以本檔
沒有對應 `JV15` 那一題的位置——**若獎金單未來加了終態，這裡要記得回來
補上「終態也放行」那一格**（`§276` 同一課：一組題全綠時要問有沒有涵蓋
每一個終態）。
"""

# ── 2026-09-24 移除（SPEC-BONUS §十一）───────────────────────────────────────
# 舊「獎金項目＋分潤單」流程停用：寫入端點回 410、bonus.html 改為以案件為中心的新頁面
# （使用者：「上一次開發的內容我無法接受」「重做成新流程」、舊單「舊的都是開發機測試用，直接作廢」）。
# 本檔下列題驗的是已停用的流程，已移除；新流程的題見 test_bonus_case_*_2026_09_24.py、
# test_e2e_bonus_case_page_2026_09_24.py、test_bonus_legacy_retired_2026_09_24.py。
# 移除：test_bn7_a_voided_award_can_still_be_exported_regardless_of_status、test_bn7_an_approved_award_can_be_exported、test_bn7_mid_flight_award_cannot_be_exported、test_bn7_signature_names_are_display_names_not_usernames、test_bn7_the_company_header_is_not_blank、test_bn7_the_signature_slots_count_matches_the_configured_tiers
# 同檔其餘題驗的是仍在運作的部分（讀取端點、群組、輔助函式），保留。
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_bonus_award_approval_2026_09_23 import (  # noqa: E402
    AWARDS, _act, _award, _hdr, _seed_award, _set_flow,
)

PDF = "/api/bonus/awards/%s/pdf-download"

#: `§166`：走到端點才會出現的狀態碼。
OK_CODES = (200, 400, 403)


def _reached(r):
    if r.status_code in (404, 405, 422):
        pytest.fail(
            "`GET %s` 走不到（回 %s）。\n" % (PDF % "{award_id}", r.status_code)
            + "📌 路徑是 `SPEC-BN6-BN7.md §4` 定案的，改了退回給我。")
    return r


def _pdf_text(body):
    """PDF 上印出來的文字，`NFKC` 正規化（Edge 會把漢字寫成康熙部首，`§214`）。"""
    import unicodedata
    pypdf = pytest.importorskip("pypdf", reason="抽 PDF 文字要用它")
    reader = pypdf.PdfReader(io.BytesIO(body))
    return unicodedata.normalize(
        "NFKC", "\n".join((p.extract_text() or "") for p in reader.pages))


def _set_company(client, hdr, name):
    """設定公司抬頭。⚠️ `company_profile` 是預設就 seed 的，本檔不驗
    「沒設定」那個狀態（那是 `JV9` 的範圍），只驗「設定了讀不讀得到」。
    """
    r = client.put("/api/settings/company-profile", headers=hdr,
                   json={"name": name})
    assert r.status_code in (200, 204), (
        "設定公司抬頭失敗：%s %s" % (r.status_code, r.text[:200]))


# ══════════════════════════════════════════════════════════════════════
# ① 用印欄列數來自簽核設定
# ══════════════════════════════════════════════════════════════════════

def _walk_to_approved(client, make_user, quote_no, tier_names):
    """建一張獎金單，設定 `len(tier_names)` 層簽核，走完到「已核准」。

    回 `(hdr, aid)` —— `hdr` 是建單人（superadmin）的 headers。
    """
    _u, hdr = _hdr(client, make_user, "bn7_owner_" + quote_no)
    signers = _set_flow(client, hdr, make_user, tier_names)
    aid = _seed_award(quote_no, ["bn7_payee_" + quote_no])
    assert _act(client, hdr, aid, "submit").status_code == 200, "送審失敗"
    for name, shdr in signers.items():
        r = _act(client, shdr, aid, "approve")
        assert r.status_code == 200, (
            "由 %r 簽核失敗：%s %s" % (name, r.status_code, r.text[:200]))
    a = _award(client, hdr, aid)
    assert a.get("status") == "已核准", "前置不對：簽完而狀態不是已核准。"
    return hdr, aid


def test_bn7_a_draft_award_cannot_be_exported(client, make_user):
    """🔴 **`④`：草稿狀態的獎金單不可以匯出。**"""
    _u, hdr = _hdr(client, make_user, "bn7_draft")
    aid = _seed_award("MQ-BN7-DRAFT", ["someone"])
    r = _reached(client.get(PDF % aid, headers=hdr))
    assert r.status_code in OK_CODES, (
        "回 %s：%s" % (r.status_code, r.content[:200]))
    assert r.status_code == 400, (
        "**草稿**的獎金單匯出成功（回 %s）——\n" % r.status_code
        + "☠️ 那是要據以付錢的單據，未簽核就印得出來的失效方式是\n"
          "   有人拿著它去請款。")


