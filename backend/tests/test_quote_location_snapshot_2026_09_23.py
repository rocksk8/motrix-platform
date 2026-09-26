# -*- coding: utf-8 -*-
"""`QL25` · 報價單的據點身分要在「送出」那一刻凍結。

使用者原話：
```
「預設據點的部分，會強制帶到已經成立或是未成立的報價單，
  應該以報價單成立當下的據點為主」
```

A 裁定四點（`STATE.md §29094`）：
```
① 凍結時機 = 按「送出」那一刻（草稿階段仍跟著設定走）
② 舊單 = 等使用者填完設定後一次補快照（現在因為每個 quotation 都是
   loc_1 且沒填內容 ⇒ 補了零差異）
③ 快照要存內容不只 id
④ 沒有快照的舊單落回即時查，不可以印空白
```

# 🔴 動工前查過的一件事：這看起來像牴觸 `QL10`，而查完發現不牴觸

```
QL10（A 裁，理由要留著）：請款單等「現在該匯到哪」的單據 —— 讀即時值，
     不做快照；代價（改一次據點，所有歷史 PDF 重印都會變）用稽核記錄
     變成可追查，不假裝它不存在。
QL16（A 裁，推翻我當時查完的錯誤方向）：薪資單維持快照 ——
     「QL10 讀即時值是為了回答『現在該匯到哪』，
       而薪資單的抬頭回答的是『當初是誰付的』—— 那不是同一個問題」
```
🔑 判準是**這份文件回答的是哪一個問題**：
```
請款單／開票憑據等付款類單據  問「現在該匯到哪」    ⇒ 讀即時值（QL10）
薪資單（已交給員工）          問「當初是誰付的」    ⇒ 凍結（QL16）
報價單（已送出給客戶）        問「當初報的是什麼」  ⇒ 凍結（QL25，同 QL16 那條）
```
⇒ `QL25` 不是牴觸 `QL10`，是把 `QL16` 已經立過的判準**套用到第二種文件**上。
**不要因為看到「讀即時值」四個字就假設 `QL25` 撞到既有裁定** —— 兩者管的
是不同的文件，而區分的判準是「這份文件回答哪一個問題」，不是「有沒有據點」。

# ⚙️ 觀測點：只看**印出來的文字**，不猜資料存在哪個鍵

`③` 「快照要存內容不只 id」是**存放方式**的要求，不是我要斷言的介面——
本檔全部走 `GET /api/quotations/{quote_no}/pdf-download`（真實端點，Edge
headless）＋ `pypdf` 抽文字，不 import 任何尚未存在的函式名字。這樣不管
B 把快照放在 `data_json` 的哪個鍵，題目都不必跟著改。

# ⚠️ 我沒有寫的：`②` 舊單一次補快照的**遷移腳本**本身

那是一次性的資料操作，不是「送出即凍結」這個行為的一部分；而 A 的裁定
已經指出「現在因為每個 quotation 都是 loc_1 且沒填內容 ⇒ 補了零差異」——
今天測試資料庫是空的，這個遷移在測試環境裡沒有可觀察的差異可驗。
`④`（沒有快照的舊單落回即時查）才是這裡要驗的：一張**從來沒有走過送出
凍結流程**的單（例如直接用 SQL 種一筆 status='已送出' 而沒有走 PATCH），
印出來仍然要有內容，不可以是空白。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_quote_location_2026_09_22 import (  # noqa: E402
    BRANCH, PRIMARY, _set_locations, _superadmin,
)
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')

#: `§166`：走到端點才會出現的狀態碼。
OK_CODES = (200, 400, 403)

_LINES_KEY_NOTE = None  # 報價單本身不需要分錄行，PDF 只印抬頭與內容。


def _hdr(token):
    return {"Authorization": "Bearer %s" % token}


def _create_quote(client, token, location_id, customer="QL25測試客戶"):
    r = client.post("/api/quotations", headers=_hdr(token),
                    json={"status": "草稿", "locationId": location_id,
                          "data": {"customerName": customer}})
    assert r.status_code == 201, "建不起來：%s %s" % (r.status_code, r.text[:200])
    return r.json().get("quoteNo") or r.json().get("quote_no")


def _submit(client, token, quote_no):
    """`送出` —— `PATCH .../status` 從草稿直接送出，繞過分層簽核設定。

    ⚠️ 只有 superadmin 可以直接改狀態；而從「草稿」送出**不會**撞到
       `_STATUS_PATCH_WHITELIST` 那個擋分層簽核的檢查
       （那個檢查只在「待審核／簽核中 -> 已送出」時才擋）。
    """
    r = client.patch("/api/quotations/%s/status" % quote_no,
                     headers=_hdr(token), json={"status": "已送出"})
    assert r.status_code == 200, "送出失敗：%s %s" % (r.status_code, r.text[:200])


def _pdf_text(client, token, quote_no):
    r = client.get("/api/quotations/%s/pdf-download" % quote_no,
                   headers=_hdr(token))
    if r.status_code in (404, 405, 422):
        pytest.fail(
            "`GET /api/quotations/{id}/pdf-download` 走不到（回 %s）。\n"
            % r.status_code)
    assert r.status_code == 200, (
        "PDF 匯出失敗：%s %s" % (r.status_code, r.content[:200]))
    pypdf = pytest.importorskip("pypdf", reason="抽 PDF 文字要用它")
    import unicodedata
    reader = pypdf.PdfReader(io.BytesIO(r.content))
    text = "\n".join((p.extract_text() or "") for p in reader.pages)
    return unicodedata.normalize("NFKC", text)


def _seed_locations(client, make_user, name):
    """種一個有兩個據點的 `company_profile`，回 `(token, primary, branch)`。"""
    token = _superadmin(client, make_user, name)
    primary = dict(PRIMARY)
    branch = dict(BRANCH)
    _set_locations(client, token, [primary, branch])
    return token, primary, branch


# ══════════════════════════════════════════════════════════════════════
# ① 草稿階段仍跟著設定走
# ══════════════════════════════════════════════════════════════════════

def test_ql25_a_draft_still_tracks_live_settings(client, make_user):
    """🔴 **`①` 的另一半（正對照）：草稿階段改設定，重印要跟著變。**

    ☠️ 少了這一題，一個「一律凍結（包含草稿）」的實作也會讓 `②` 那題綠——
       而那樣使用者在報價單還沒送出前**改不動抬頭**，草稿階段本來就該
       跟著設定即時走（`STATE.md`：「草稿階段仍跟著設定走」）。
    """
    token, _primary, branch = _seed_locations(client, make_user, "ql25_draft")
    quote_no = _create_quote(client, token, branch["id"])

    before = _pdf_text(client, token, quote_no)
    assert branch["company_name"] in before, (
        "草稿的 PDF 沒有印出所屬據點的抬頭：\n%s" % before[:300])

    branch2 = dict(branch, company_name="QL25草稿改名後股份有限公司")
    _set_locations(client, token, [dict(_primary_of(client, token)), branch2])

    after = _pdf_text(client, token, quote_no)
    assert "QL25草稿改名後股份有限公司" in after, (
        "草稿階段改了據點設定，重印卻沒有跟著變：\n%s\n" % after[:300]
        + "☠️ 若草稿也被凍結，使用者在送出前**改不動抬頭**——\n"
          "   `STATE.md` 明著裁定「草稿階段仍跟著設定走」。")


def _primary_of(client, token):
    r = client.get("/api/settings/company-profile", headers=_hdr(token))
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    locs = body.get("locations") or (body.get("profile") or {}).get(
        "locations") or []
    for l in locs:
        if l.get("id") == PRIMARY["id"]:
            return l
    return dict(PRIMARY)


# ══════════════════════════════════════════════════════════════════════
# ② 核心：送出那一刻凍結
# ══════════════════════════════════════════════════════════════════════

def test_ql25_submitting_freezes_the_location_identity(client, make_user):
    """🔴🔴 **`①②③` 核心：送出之後改設定，重印不變 —— 存的是內容不是 id。**

    ⚙️ 這一題同時驗到 `③`（存內容不只 id）：改的是**同一個據點自己的
    欄位**（不是換一個 `locationId`）。若快照只存了 id、重印時再查一次
    活的 `locations` 表，這一題會紅在「印出了改過的新名字」——
    因為 id 沒變，活查會查到已經被編輯過的那一筆。
    """
    token, _primary, branch = _seed_locations(client, make_user, "ql25_freeze")
    quote_no = _create_quote(client, token, branch["id"])

    before = _pdf_text(client, token, quote_no)
    assert branch["company_name"] in before, (
        "送出前的 PDF 沒有印出所屬據點的抬頭：\n%s" % before[:300])

    _submit(client, token, quote_no)

    branch_edited = dict(branch, company_name="QL25送出後被改掉的名字")
    _set_locations(client, token,
                   [dict(_primary_of(client, token)), branch_edited])

    after = _pdf_text(client, token, quote_no)
    assert branch["company_name"] in after, (
        "送出之後改了據點設定，重印的抬頭卻變了：\n%s\n" % after[:300]
        + "☠️ 使用者送出報價單之後改了公司資料，"
          "已經在客戶手上的報價單內容**不應該跟著變**——\n"
        + "🔑 `location_identity()` 是**每次重印即時查**，\n"
          "   凍結要在送出那一刻把值存下來，不是存一個 id 再查。")
    assert "QL25送出後被改掉的名字" not in after, (
        "送出之後印出的抬頭是**改過之後**的名字：\n%s\n" % after[:300]
        + "☠️ 若快照只存了 `location_id`，重印時活查會查到已經被編輯過的\n"
          "   那一筆 —— id 沒變，內容變了，這就是『存內容不只 id』要擋的事。")


#: 🔴 **這裡本來想寫「凍結的是整組身分，包含銀行帳號」，動工前查證推翻了它**：
#:
#: `pdf_gen.py:520-544`（`_identity_head`／`_identity_foot`）只印
#: `company_name`／`company_name_en`／`tax_id`／`phone`／`email` ——
#: **報價單的版型上根本沒有銀行帳號欄位**（不像請款單／開票憑據，
#: 報價單不是要人匯款的單據）。
#:
#: ☠️ 若照原計畫寫這一題（改銀行帳號、斷言 PDF 沒印出新帳號），
#:    它會是一句**必然成立的空話**：銀行帳號從來不會出現在報價單上，
#:    不管快照做得對不對，斷言都會通過 —— 那與〈守門的正對照〉裡
#:    「一個必然相等的斷言證明不了任何事」是同一族。
#: ⇒ 不寫這一題，不留占位；`②③` 的凍結範圍靠
#:   `test_ql25_submitting_freezes_the_location_identity` 涵蓋
#:   （它驗的 `company_name` 確實會被印出來，斷言不是空話）。


# ══════════════════════════════════════════════════════════════════════
# ④ 沒有快照的舊單落回即時查，不可以印空白
# ══════════════════════════════════════════════════════════════════════

def test_ql25_an_old_quote_without_a_snapshot_falls_back_not_blank(
        client, make_user):
    """🔴🔴 **`④`：沒有快照的舊單（沒走過送出凍結流程）落回即時查。**

    ⚙️ 模擬「這個功能上線前就已經送出」的舊單：直接用 SQL 把狀態改成
    `已送出`，**不經過 `_submit()`**——那樣新程式碼不會有機會替它寫快照，
    正是 `④` 要處理的那一種舊資料。

    ☠️ 這一題失敗的兩種樣子完全不同，要分清楚是哪一種：
    ```
    印出空白／缺欄位   ⇒ 落回即時查那條路本身有問題（④ 真正要擋的）
    500／例外          ⇒ 讀不到快照時**丟例外**而不是優雅退回
    ```
    """
    token, _primary, branch = _seed_locations(client, make_user, "ql25_old")
    quote_no = _create_quote(client, token, branch["id"])

    import db
    conn = db.get_db()
    try:
        conn.execute(
            "UPDATE quotations SET status = '已送出' WHERE quote_no = ?",
            (quote_no,))
        conn.commit()
    finally:
        conn.close()

    after = _pdf_text(client, token, quote_no)
    assert branch["company_name"] in after, (
        "沒有快照的舊單（狀態是已送出，但沒走過送出流程）印出來是：\n%s\n"
        % after[:300]
        + "☠️ **落回即時查那一條路壞了** —— 印出空白比印錯內容更糟，\n"
          "   使用者拿到一張連公司名稱都沒有的報價單。\n"
        + "🔑 `④`：沒有快照時要落回 `location_identity()` 的即時查，\n"
          "   不可以因為『快照優先』的判斷本身出錯就整段印不出來。")
