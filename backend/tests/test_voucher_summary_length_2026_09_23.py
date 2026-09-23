# -*- coding: utf-8 -*-
"""`JV12` · 傳票摘要的長度要能夠隨著文字調整長度。

使用者原話：「傳票摘要的長度要能夠隨著文字調整長度」。

# 🔴 動工前查過：編輯畫面**已經有**自動長高，這不是使用者在講的那件事

```
frontend/pages/voucher.html:251-253
  <textarea x-model="l.summary" ...
      x-effect="l.summary; $nextTick(() => {
          $el.style.height = 'auto'
          $el.style.height = $el.scrollHeight + 'px'
      })">
```
⇒ 編輯畫面的摘要欄位**今天就會**隨打字內容自動長高——這件事已經做了。

# ⚙️ `JV14` 已結案：使用者目視確認紙本，長摘要印得出來

```
B 原本量到：長摘要匯出後 pypdf 抽不到中段（JV14）
✅ 2026-09-23 使用者用眼睛看過那張 PDF：長摘要在紙上印得出來，
   結案不修——成因是 **pypdf 抽取工具的限制**，不是版面少印。
```
🔑 這裡曾經誤以為它未結案而去問 B 要重現步驟——A 已更正：**它結案了**。
本檔核心題「60 字／323 字合成摘要都完整讀到三個標記」**與使用者的
觀察一致，是佐證不是矛盾**；換句話說，當時「測不出問題」不是題寫得
不夠緊，是**兩種成因（少印 vs. 讀不到）在我的終端機觀測裝置上長得
一樣**——真正解決它的是**換了觀測裝置**（使用者的眼睛），不是把題
寫得更緊。⇒ 本題不再是「防 `JV14` 複發」，改成單純守**字串完整性
本身**（下一節）。

# ⚙️ 本檔怎麼分工

```
自動驗得到的那一半（本檔寫）  長摘要**印出來的文字不可以缺字**
                            —— 字串完整性，用 B 量 JV14 的同一個方法
                               （pypdf 抽字）
自動驗不到的那一半（人工題） 那一列在**視覺上**長什麼樣子
                            —— 見檔尾〈人工檢查清單〉
```
⚠️ **不釘 `height` 這個 CSS 屬性本身** —— 那是實作細節，B 可能改成
`min-height`、改成不換行縮小字級、改成截斷加省略號＋另開視窗看全文
都是合理的修法，本檔只釘**使用者能不能拿到完整的內容**這個結果。
"""
import io

import pytest

_LINES_BASE = [{"account_code": "1113", "debit": 1000, "credit": 0},
              {"account_code": "4111", "debit": 0, "credit": 1000}]

#: 刻意夠長（會在 163.5pt 寬的欄位裡換成好幾行）＋ 頭尾中段各有獨立
#: 可辨識的標記，缺哪一段都認得出來——不是隨便一段長字串。
_LONG_SUMMARY = (
    "起始標記AAA　" + "這是一段刻意拉長的摘要內容用來驗證列印輸出不會把中間截斷　"
    + "中段標記BBB　" + "傳票摘要應該完整出現不可以缺漏任何一個字才符合使用者的要求　"
    + "結尾標記CCC")


def _hdr(client, make_user, username, role="superadmin", modules=("cashier",)):
    u, p = make_user(username=username, role=role, modules=list(modules))
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _create_with_summary(client, hdr, summary):
    lines = [dict(_LINES_BASE[0], summary=summary), dict(_LINES_BASE[1])]
    r = client.post("/api/vouchers", headers=hdr,
                    json={"summary": "JV12 長摘要測試", "lines": lines})
    assert r.status_code == 200, "建不起來：%s %s" % (r.status_code, r.text[:200])
    return r.json()["id"]


def _sign_off(client, hdr, vid):
    r = client.post("/api/vouchers/%s/submit" % vid, json={}, headers=hdr)
    assert r.status_code == 200, "送審失敗：%s %s" % (r.status_code, r.text[:160])
    for _ in range(2):
        r = client.post("/api/vouchers/%s/approve" % vid, json={}, headers=hdr)
        assert r.status_code == 200, "簽核失敗：%s %s" % (r.status_code, r.text[:160])


def _pdf_text(client, hdr, vid):
    r = client.get("/api/vouchers/%s/pdf-download" % vid, headers=hdr)
    assert r.status_code == 200, "匯出失敗：%s %s" % (r.status_code,
                                                    r.content[:200])
    import unicodedata
    pypdf = pytest.importorskip("pypdf", reason="抽 PDF 文字要用它")
    reader = pypdf.PdfReader(io.BytesIO(r.content))
    return unicodedata.normalize(
        "NFKC", "\n".join((p.extract_text() or "") for p in reader.pages))


# ══════════════════════════════════════════════════════════════════════
# 自動驗得到的那一半：字串完整性
# ══════════════════════════════════════════════════════════════════════

def test_jv12_a_long_summary_is_not_truncated_in_the_exported_pdf(client,
                                                                   make_user):
    """🔴🔴 **核心：長摘要匯出成 PDF，三個標記（起始／中段／結尾）都要在。**

    `JV14` 已判定為抽取工具限制（使用者 2026-09-23 目視確認紙本）；
    本題守的是**字串完整性本身**，不是那個現象。

    ⚙️ 三個標記分開驗，紅了看得出**缺哪一段**：
    ```
    只缺中段   ⇒ 中間被蓋掉／裁掉
    全部都缺   ⇒ 這一列可能整個印不出來，成因不同
    只缺結尾   ⇒ 超出邊界的部分被裁切
    ```

    📌 用本檔 `_LONG_SUMMARY`（約 60 字）與另外實測一個 323 字的版本，
    三個標記都完整出現，與使用者目視確認的結果一致（是佐證不是矛盾）。
    """
    _u, hdr = _hdr(client, make_user, "jv12_long")
    vid = _create_with_summary(client, hdr, _LONG_SUMMARY)
    _sign_off(client, hdr, vid)
    text = _pdf_text(client, hdr, vid)

    missing = [tag for tag in ("起始標記AAA", "中段標記BBB", "結尾標記CCC")
              if tag not in text]
    assert not missing, (
        "長摘要匯出之後，PDF 上缺了：%r\n" % missing
        + "紙上抽出來的文字（前 400 字）：\n  %s\n" % text[:400]
        + "☠️ 使用者填了完整的摘要，而印出來的憑證少了一段——\n"
          "   《商業會計法》要保存的那份憑證，內容本身就不完整。")


def test_jv12_a_short_summary_is_unaffected(client, make_user):
    """⚙️ **正對照：短摘要不受影響，確認這不是摘要功能整個壞掉。**

    ☠️ 少了它，若某次改動讓摘要**完全印不出來**（不只是長摘要被裁），
       上一題與這一題都會用同一種方式失敗，分不出「只有長的有事」
       還是「摘要整個壞了」。
    """
    _u, hdr = _hdr(client, make_user, "jv12_short")
    vid = _create_with_summary(client, hdr, "短摘要測試")
    _sign_off(client, hdr, vid)
    text = _pdf_text(client, hdr, vid)
    assert "短摘要測試" in text, (
        "連短摘要都印不出來：\n%s\n" % text[:300]
        + "這代表摘要欄位本身壞了，不是『長摘要才會被截斷』這個更窄的問題。")


# ══════════════════════════════════════════════════════════════════════
# 人工題：版面高度
# ══════════════════════════════════════════════════════════════════════

def test_jv12_the_visual_layout_is_a_human_verification_item():
    """📌 **這一題是人工題，明著寫下要看什麼——不是為了有題可寫而釘一個 CSS 屬性。**

    `helpers/voucher_pdf.py` 目前：
    ```
    td, th { height: 20.1pt; ... word-break: break-all; }
    table  { table-layout: fixed; }
    ```
    `height` 是固定值、`word-break: break-all` 會讓長摘要換成好幾行——
    這是我查到的**頭號嫌疑**，而不是斷言的對象：B 可能改成 `min-height`、
    改成縮小字級不換行、或改成截斷＋另開視窗看全文，這裡都不該紅在
    B 選的那一種正確修法上。

    ## ⇒ 修完之後，請用眼睛看這幾件事（`docs/windows/` 或回報時列出來）：

    ```
    ① 用本檔 `_LONG_SUMMARY` 那種長度的摘要，實際列印／預覽一張傳票
    ② 那一列有沒有把後面的分錄行往下推開（列高真的變高了），
       不是印出來的文字疊在下一列的框線上
    ③ 那一列的框線本身有沒有跟著文字變高（不是文字溢出框線外）
    ④ 若改成縮小字級：字級縮到多小還看得清楚？有沒有一個實務上的下限
    ⑤ 若改成截斷＋另開視窗：使用者知不知道『這裡有更多內容』
       （有沒有提示，不是無聲截斷）
    ```
    """
    assert True, "此題僅作為人工檢查清單的固定位置，永遠是綠的。"
