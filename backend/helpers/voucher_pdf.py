# -*- coding: utf-8 -*-
"""傳票 PDF 匯出與附件合併（`JV5`）。

施工圖：`docs/windows/SPEC-JV5-PDF.md`。版面的唯一來源是使用者提供的那張實例
（`docs/reference/傳票-實例-20260330-006.pdf`，逐欄分析在 `STATE.md §103b`）。

# 🔴 兩種附件、兩條路

```
圖片  <img> 進同一份 HTML（每張一頁）=> Edge 一次印出 => **零新增套件、零額外 Edge**
PDF   Edge 做不到 => pypdf 合併
```
⚠️ Edge 有 `EDGE_PDF_SEMAPHORE` 限併發、逾時 120 秒 ⇒ 它是**稀缺資源**，
   所以本體與所有圖片**一次印完**，不要一張一張印。

# ☠️ 附件壞掉／不見**不可以讓匯出失敗**

```
JV3 帶入   **寫入** —— 它在資料庫裡建立一個主張「這張傳票有這份憑證」
           部分成功 => 留下一句謊 => 整批拒絕是對的
JV5 匯出   **唯讀** —— 它不改變任何主張，只是把既有的主張印出來
```
🔑 **一個唯讀動作拒絕執行，擋住的是使用者；靜默略過，騙的是使用者。
   第三條路是把缺口輸出出來。**
⇒ 併不進去的附件：在最後加一頁逐筆列出來，**並在回應上說**。

# 🔴 `pypdf` 的三件實查（2026-09-23，pypdf 6.19.0）

```
① 壞檔在 **PdfReader() 當下**就丟
   0 byte => EmptyFileError／純文字・PNG・只有檔頭・被截斷 => PdfStreamError
   trailer 壞 => PdfReadError
② **加密的 PDF 不在那裡丟** —— PdfReader() 成功，
   `len(pages)` 與 `append()` 才丟 FileNotDecryptedError
   ⇒ `try` 只包住讀檔那一行**接不到它**
③ ☠️ **零頁 PDF 一個例外都不丟**：PdfReader OK、pages == 0、append OK、write OK
   ⇒ **合併「成功」而頁數沒有變**
```
⇒ 所以「這個附件有沒有真的併進去」**只能數頁數**，不能靠「有沒有丟例外」。
⇒ 接 `PyPdfError`（全部都是它的子類），**不接 `Exception`** —— 那會把我們自己的 bug 一起吞掉。
"""
import datetime as _dt
import html
import json
import logging
import os
import tempfile

from db import get_db
from helpers import _get_edge_path, _get_setting, run_edge_pdf
from helpers.voucher import CATEGORY_TITLES, approval_done, get_voucher
from helpers.voucher_attachments import abs_path

logger = logging.getLogger(__name__)

#: 圖片副檔名 —— 這幾種走 `<img>`，不經 `pypdf`。
_IMAGE_EXTS = (".jpg", ".jpeg", ".png")


def classify_attachment_kind(filename):
    """`JV16③`：這個檔名副檔名看起來屬於哪一類——`"image"／"pdf"／"unsupported"`。

    🔴 這是**唯一一支**做副檔名分類的函式：`split_attachments()`（下面）
    與 `routers/vouchers.py` 的 `GET /{voucher_id}`（畫面標「預計併入」用）
    都呼叫這一支，不各寫一份條件式——理由見 `SPEC-JV16-JV17.md §4`：
    「哪些併得進去」的規則現在寫在後端，前端不可以重寫一份。

    ⚠️ 只看副檔名，**不代表實際併得進去**：零頁 PDF／加密 PDF 要到
    `_merge_pdfs()` 真的呼叫 `pypdf` 才知道（見模組 docstring 的三件
    實查）。這裡回的是「預計」，不是「保證」——畫面措辭也要照這個分寸
    寫（「預計併入」不是「會併入」）。
    """
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in _IMAGE_EXTS:
        return "image"
    if ext == ".pdf":
        return "pdf"
    # 🔑 今天上傳端點（`helpers/uploads.py::_ALLOWED_EXTS`）只准
    #    jpg/jpeg/png/pdf 四種，這一支不會遇到；但「帶入」（`copy_into()`）
    #    複製的是**其他來源**（案件更新／請款附件…）的既有檔案，
    #    那幾條路沒有這道副檔名白名單，帶進來的可能是 .docx／.xlsx 之類——
    #    這裡明著標「不支援」，讓使用者在預覽階段就知道，不必等匯出失敗。
    return "unsupported"

#: A4 直式，單位 pt（`§2` 量出來的）。
_PAGE_W, _PAGE_H = 595.32, 841.92
#: 左右邊距 42.6 / 41.5 pt（≈15mm，左右對稱）。
_MARGIN = 42.6
#: 表格欄寬（`§2` 的欄界相減）：會計科目／科目名稱／摘要／借方／貸方。
_COL_W = (61.4, 102.2, 163.5, 92.1, 92.0)


# 2026-09-26 下沉 L1 `pdf_gen.fmt_money_blank_zero`（獎金分潤單也用）；本檔照舊用 `_fmt_money`
from pdf_gen import fmt_money_blank_zero as _fmt_money  # noqa: E402


def _company_name():
    """公司抬頭。**不可以寫死** —— 這個 repo 已經寫死在 14 個檔、56 行。

    ## ☠️ `JV9`：這一支原本回空字串，而紙上印「（尚未設定公司抬頭）」

    ```
    helpers/settings.py::_get_setting()  ->  json.loads(...)  **已經是物件**
    而這裡又 json.loads() 了一次          ->  TypeError
    再被 `except Exception: return ""` 吞掉
    ```
    ⇒ 使用者的設定**有值**（實查 12 個字），而畫面告訴他「尚未設定」。
    🔑 **一行 bug ＋ 一個太寬的 except ＝ 一句會誤導使用者的話。**
       而那個 except 的理由是對的（抬頭讀不到不該讓整份 PDF 產不出來）——
       ☠️ 錯的是它**沒有分開兩件事**：
    ```
    設定讀不到／沒設定   => 靜默退路是對的（使用者自己會看到「尚未設定」）
    **我們的程式錯了**   => 必須留下線索，否則它會偽裝成前者
    ```

    ## 📌 只取 `name`，不要整包

    `company_profile` 裡有 `bank_account_number`／`google_maps_api_key` 等
    ⇒ 這一支只回一個字串，**不讓那包東西流進 PDF 的任何一層**。
    而 `pdf_gen.py:510` 逐字：「`pdf_gen.py` 不可以知道 `company_profile` 的
    地址結構」⇒ 沿用那個邊界。
    """
    prof = _get_setting("company_profile", {})
    # ⚠️ 舊資料可能是**字串**（某些版本把整包 JSON 當字串存）⇒ 兩種都吃。
    #    🔑 而 `isinstance` 判斷寫在這裡，不是靠 try 去撞 —— 用例外做流程控制
    #       正是上面那個 bug 能藏起來的原因。
    if isinstance(prof, str):
        try:
            prof = json.loads(prof or "{}")
        except ValueError:
            logger.warning("company_profile 的值不是合法 JSON，抬頭留空")
            return ""
    if not isinstance(prof, dict):
        logger.warning("company_profile 的型別是 %s（預期 dict），抬頭留空",
                       type(prof).__name__)
        return ""
    return prof.get("name") or ""


def split_attachments(rows):
    """把附件分成 `(圖片, PDF, 併不進去的)` 三堆。**只看得到的那些**（未刪）。

    ⚠️ 「併不進去」在這一層只判**實體檔在不在**；PDF 讀不讀得了要到合併那一步
       才知道（見模組 docstring 的三件實查）⇒ 那一堆會在後面再長。
    """
    images, pdfs, missing = [], [], []
    for a in rows or ():
        try:
            p = abs_path(a.get("path"))
        except Exception:                                    # noqa: BLE001
            missing.append(dict(a, reason="附件路徑不合法"))
            continue
        if not os.path.isfile(p):
            missing.append(dict(a, reason="原始檔案已遺失"))
            continue
        # 🔑 `unsupported`（例如帶入的 .docx）**照舊丟給 pdfs 那一堆**——
        #    這裡不改變既有的合併行為，只是把「是不是圖片」這個判斷改用
        #    共用的 classify_attachment_kind()，避免同一條副檔名判斷式
        #    出現第二份。它會在 pypdf 讀不出來時被 _merge_pdfs()
        #    自己的例外處理接住（「檔案不是可讀的 PDF」），與今天一樣。
        kind = classify_attachment_kind(a.get("filename"))
        (images if kind == "image" else pdfs).append(dict(a, _abs=p))
    return images, pdfs, missing


def watermark_html(voucher):
    """要不要蓋浮水印、蓋哪一句。回傳值本身沒有變過——`JV23`（依據使用者
    2026-09-23 裁示）改的是**呼叫端**：`preview_voucher_pdf()` 與
    `export_voucher_pdf()` 現在都會呼叫這支，不是只有預覽路徑。這支的
    判斷邏輯不用跟著改，壞的一直是匯出路徑沒有接上這個參數。

    ## 🔴 作廢優先於未簽核（使用者裁示②）

    一張**還沒簽核就被作廢**的單，紙上要印「已作廢」不是「尚未簽核」——
    ☠️ 印「尚未簽核」的話，有人會去把它簽完。與 `approval_done()`
    「作廢一律放行」是同一條裁定的兩面：那支管**能不能匯出**，這支管
    **蓋哪一句話**，判斷順序必須一致（都是先看 `voided_at`）。
    """
    e = html.escape
    if voucher.get("voided_at"):
        title, sub = "本傳票已作廢", "僅供稽核存查"
    else:
        ok, _msg = approval_done(voucher)
        if ok:
            return ""
        title, sub = "傳票尚未簽核完成", "預覽稿・尚未正式生效"
    items = "".join(
        "<div class='wm-item'><b>%s</b><small>%s</small></div>" % (e(title), e(sub))
        for _ in range(12))
    return "<div class='wm'>%s</div>" % items


def _sign_cells(voucher):
    """簽核格。**從資料算幾格，不是寫死三個**。

    🔴 使用者 2026-09-23 裁：「**超過兩層就把版面往下加列**」
    ⇒ 簽核區是**依設定層數往下長**的，而那張實例 PDF 的三格只是「目前的層數」。
    ☠️ 寫死三個的話，`AS2`（傳票簽核接進簽核設定）上線那天版面要整個重做。
    """
    sigs = voucher.get("signatures") or {}
    return [(k, (v or {}).get("by") or "", (v or {}).get("at") or "")
            for k, v in sigs.items()]


def build_html(voucher, images, missing, exported_at, watermark=""):
    """組出要餵給 Edge 的那一份 HTML（本體 ＋ 圖片附件 ＋ 未併入清單）。

    ⚠️ 版面座標是**量出來的**（`§2`），而字型／粗細／字距**量不到**
       —— 來源 PDF 沒有文字層。對不上時若是座標是實作問題，
       若是字型**沒有人有權威答案**，要回去問使用者。

    `watermark`：`watermark_html()` 產的 HTML。

    🔴 **這一段的「匯出路徑一律傳空字串」是舊的，已經不對了**（依據
    `JV23`，使用者 2026-09-23 回報「重大缺失」）——`JV11` 當時的前提是
    「未簽核完成根本匯不出來，所以匯出的一定是有效單」，那時只有預覽稿
    需要蓋「尚未簽核完成」；但 `JV15` 之後「已過帳／已作廢一律放行
    匯出」，前提被推翻了，而這裡沒有跟著翻面——已作廢的傳票被匯出成一份
    看起來完全有效的會計憑證。
    ⇒ **匯出路徑現在也要傳 `watermark_html(v)`**（見 `export_voucher_pdf()`）。
    `watermark_html()` 本身對「作廢優先於未簽核」的判斷沒有變、也不需要
    變（`voided_at` 優先，已核准／已過帳回空字串）——**壞的一直是呼叫端
    沒有把這個參數接上，不是這支函式的邏輯**。`§228` 的分工原則
    （預覽與匯出是兩支不同端點、兩套不同閘門）仍然成立，變的只是「匯出
    是不是也可能印出非空的 watermark」這一格。
    """
    e = html.escape
    lines = voucher.get("lines") or []
    total_d = sum(int(l.get("debit") or 0) for l in lines)
    total_c = sum(int(l.get("credit") or 0) for l in lines)

    rows = []
    for l in lines:
        rows.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td>"
            "<td class='num'>%s</td><td class='num'>%s</td></tr>"
            % (e(l.get("account_code") or ""), e(l.get("account_name") or ""),
               e(l.get("summary") or ""),
               _fmt_money(l.get("debit")), _fmt_money(l.get("credit"))))
    rows.append(
        "<tr class='total'><td></td><td></td><td class='lbl'>合　計</td>"
        "<td class='num'>%s</td><td class='num'>%s</td></tr>"
        % (_fmt_money(total_d), _fmt_money(total_c)))

    signs = _sign_cells(voucher)
    sign_html = "".join(
        "<div class='sig'><span>%s</span><b>%s</b><i>%s</i></div>"
        % (e(k), e(by), e((at or "")[:10])) for k, by, at in signs)

    img_pages = "".join(
        "<div class='att'><div class='att-h'>附件：%s</div>"
        "<img src='file:///%s'></div>"
        % (e(a.get("filename") or ""), e(a["_abs"].replace("\\", "/")))
        for a in images)

    miss_page = ""
    if missing:
        items = "".join(
            "<li><b>%s</b><span>%s</span><span>%s</span></li>"
            % (e(a.get("filename") or ""), e(a.get("reason") or ""),
               e((a.get("uploaded_at") or "")[:19]))
            for a in missing)
        # 🔴 **印出來**而不是靜默略過：使用者拿到一份看起來完整的 PDF
        #    而少了一張憑證 —— 那比印不出來更糟。
        miss_page = (
            "<div class='att miss'><div class='att-h'>未能併入的附件"
            "（%d 筆）</div><ul>%s</ul>"
            "<p>以上附件仍登記在這張傳票上，而它們的檔案這一次沒有併進來。"
            "請到傳票頁的附件區確認。</p></div>" % (len(missing), items))

    cols = "".join("<col style='width:%.1fpt'>" % w for w in _COL_W)
    return """<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">
<style>
  /* `JV34③`：頁碼「第 x／y 頁」用 @page 頁邊框（Chromium／Edge 131 以上；
     舊版只是不顯示，不會報錯）。只編傳票本體——併入的 PDF 附件是別人的文件，
     `_merge_pdfs()` 接在後面，不經過這一段。底邊留 {m}pt 給頁碼。 */
  @page {{ size: {pw}pt {ph}pt; margin: 0 0 {m}pt 0;
          @bottom-center {{ content: "第 " counter(page) "／" counter(pages) " 頁";
                            font-size: 8.5pt; font-family: "Microsoft JhengHei", sans-serif; }} }}
  /* `JV34③`：分錄跨頁時每一頁重印表頭 */
  thead {{ display: table-header-group; }}
  body {{ margin: 0; font-family: "Microsoft JhengHei", "PingFang TC", sans-serif;
          color: #000; }}
  .sheet {{ padding: {m}pt {m}pt 0 {m}pt; position: relative; }}
  /* `JV11`：浮水印 —— 沿用 quotation-form.html 的 3x4 格線平鋪，
     rotate(-28deg)，顏色極淡（rgba(185,28,28,0.09)／小字 0.07）不影響閱讀。
     🔴 `JV23`（依據使用者 2026-09-23 裁示，翻掉下面這段舊註解）：
     不是只有 preview_voucher_pdf() 會餵非空的 {watermark}——已作廢的
     傳票被 export_voucher_pdf() 匯出時**也要**蓋這一層，因為 .head
     那一列的「已作廢」是 9.3pt 小字狀態列，使用者容易看漏，而這是一張
     要拿去對帳／報稅的憑證。已核准／已過帳的正常匯出仍然是空字串。 */
  .wm {{ position: absolute; inset: 0; pointer-events: none; z-index: 5;
         overflow: hidden; display: grid; grid-template-columns: repeat(3, 1fr);
         grid-template-rows: repeat(4, 1fr); align-items: center;
         justify-items: center; box-sizing: border-box; }}
  .wm-item {{ transform: rotate(-28deg); white-space: nowrap; text-align: center;
              line-height: 1.5; }}
  .wm-item b {{ display: block; font-size: 15pt; font-weight: 900;
               letter-spacing: 0.1em; color: rgba(185,28,28,0.09); }}
  .wm-item small {{ display: block; font-size: 7.5pt; font-weight: 700;
                    letter-spacing: 0.05em; color: rgba(185,28,28,0.07); }}
  .org {{ text-align: center; font-size: 13pt; }}
  .doc {{ text-align: center; font-size: 18.4pt; font-weight: 700;
          letter-spacing: 8pt; margin: 10pt 0 12pt; }}
  .head {{ display: flex; font-size: 9.3pt; margin-bottom: 8pt; }}
  .head div {{ flex: 1; }}
  .head div:nth-child(2) {{ text-align: center; }}
  .head div:nth-child(3) {{ text-align: right; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 9.3pt;
           table-layout: fixed; }}
  td, th {{ border: 0.6pt solid #000; height: 20.1pt; padding: 0 4pt;
            vertical-align: middle; word-break: break-all; }}
  th {{ font-weight: 600; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .total td {{ font-weight: 700; }}
  .total .lbl {{ text-align: center; letter-spacing: 6pt; }}
  .note {{ border: 0.6pt solid #000; border-top: none; min-height: 20.1pt;
           font-size: 9.3pt; padding: 3pt 4pt; }}
  .signs {{ display: flex; margin-top: 12pt; border: 0.6pt solid #000; }}
  .sig {{ flex: 1; border-right: 0.6pt solid #000; padding: 5pt 6pt;
          font-size: 9.2pt; min-height: 26pt; }}
  .sig:last-child {{ border-right: none; }}
  .sig span {{ color: #444; margin-right: 6pt; }}
  .sig i {{ display: block; font-style: normal; color: #444; font-size: 8pt; }}
  .foot {{ margin-top: 10pt; font-size: 7.5pt; color: #444; }}
  .att {{ page-break-before: always; padding: {m}pt; }}
  .att-h {{ font-size: 10pt; margin-bottom: 8pt; }}
  .att img {{ max-width: 100%; max-height: {imgh}pt; }}
  .miss ul {{ font-size: 9.3pt; padding-left: 16pt; }}
  .miss li {{ margin-bottom: 4pt; }}
  .miss li span {{ color: #444; margin-left: 10pt; font-size: 8.5pt; }}
  .miss p {{ font-size: 8.5pt; color: #444; margin-top: 12pt; }}
</style></head><body>
<div class="sheet">
  {watermark}
  <div class="org">{org}</div>
  <div class="doc">{doc_title}</div>
  <div class="head"><div>傳票號碼　{no}</div><div>傳票日期　{date}</div>
    <div>附件 {att_count} 張</div><div>狀態　{status}</div></div>
  <table><colgroup>{cols}</colgroup>
    <thead><tr><th>會計科目</th><th>科目名稱</th><th>摘要</th>
        <th class="num">借方金額</th><th class="num">貸方金額</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <div class="note">備註：{note}</div>
  <div class="signs">{signs}</div>
  <div class="foot">{foot}</div>
</div>
{imgs}{miss}
</body></html>""".format(
        pw=_PAGE_W, ph=_PAGE_H, m=_MARGIN, imgh=_PAGE_H - 2 * _MARGIN - 30,
        org=e(voucher.get("_company") or "（尚未設定公司抬頭）"),
        # `JV29`：標題印傳票名稱（準則 §6）；查不到的類別退回舊標題，不猜名稱。
        doc_title=e(CATEGORY_TITLES.get(voucher.get("category") or "", "傳　票")),
        no=e(voucher.get("voucher_no") or ""),
        date=e(voucher.get("voucher_date") or ""),
        att_count=int(voucher.get("attachment_count") or 0),
        status=e("已作廢" if voucher.get("voided_at") else (voucher.get("status") or "")),
        cols=cols, rows="".join(rows), note=e(voucher.get("summary") or ""),
        signs=sign_html, imgs=img_pages, miss=miss_page, watermark=watermark,
        # 🔴 匯出的 PDF 是**快照**，要自己說出它是什麼時候的：
        #    附件可以在匯出之後再新增 ⇒ 兩份同一張傳票的 PDF 內容可以不同。
        #    ☠️ 沒有這一行的話，兩份不同的 PDF 拿在手上**分不出哪一份比較新**。
        foot=e("匯出時間 %s　／　併入附件 %d 筆%s"
               % (exported_at, voucher.get("_merged", 0),
                  ("　／　未能併入 %d 筆" % len(missing)) if missing else "")))


def _render(html_text):
    """HTML -> PDF bytes（Edge Headless）。

    🔴 `run_edge_pdf()` **吞掉逾時不丟例外**（它的 docstring 逐字說明為什麼），
       靠緊接的「沒產出或 0 byte 就 raise」那道檢查報錯。
    ⚠️ 十六個既有呼叫端分兩種寫法，而判準是**誰在等這個結果**：
    ```
    raise 的 10 處   使用者正在等一個下載 => 失敗必須讓他看到
    只記錄的 6 處    背景封存 => 沒有人在等，而失敗有留痕
    ```
    ⇒ 本項是使用者按下匯出 ⇒ **走 raise 那一種**。
    """
    edge = _get_edge_path()
    tmp_html = tmp_pdf = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html",
                                         encoding="utf-8", delete=False) as f:
            f.write(html_text)
            tmp_html = f.name
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            tmp_pdf = f.name
        run_edge_pdf(
            [edge, "--headless", "--disable-gpu", "--no-sandbox",
             "--print-to-pdf=%s" % tmp_pdf,
             "--no-pdf-header-footer",
             "--run-all-compositor-stages-before-draw",
             "file:///" + tmp_html.replace("\\", "/")])
        if not os.path.exists(tmp_pdf) or os.path.getsize(tmp_pdf) == 0:
            raise ValueError("Edge 執行完畢但未產生 PDF 檔案")
        with open(tmp_pdf, "rb") as f:
            return f.read()
    finally:
        for p in (tmp_html, tmp_pdf):
            if p:
                try:
                    os.unlink(p)
                except Exception:                            # noqa: BLE001
                    pass


def _merge_pdfs(body, pdfs):
    """本體 ＋ PDF 附件。回 `(bytes, 併不進去的那幾筆)`。

    ## 🔴 判「有沒有併進去」用**頁數差**，不是「有沒有丟例外」

    ☠️ 零頁 PDF **一個例外都不丟**：`PdfReader()` OK、`pages == 0`、
       `append()` OK、`write()` OK ⇒ **合併「成功」而頁數沒有變**。

    ## ⚠️ `try` 要包到 `append()`

    加密的 PDF 在 `PdfReader()` **不丟**，到 `len(pages)`／`append()` 才丟
    `FileNotDecryptedError` ⇒ 只包住讀檔那一行接不到它。

    ## 📌 順序：**傳票在前、附件依上傳順序**（使用者 2026-09-23 裁示）

    ⇒ 排序鍵只有一個（`uploaded_at`／`id`），日後要改只改那一個。
    """
    import pypdf
    from pypdf.errors import PyPdfError

    writer = pypdf.PdfWriter()
    writer.append(pypdf.PdfReader(_io_bytes(body)))
    skipped = []
    for a in pdfs:
        before = len(writer.pages)
        try:
            reader = pypdf.PdfReader(a["_abs"])
            writer.append(reader)
        except PyPdfError as exc:
            # 🔑 只接 pypdf 自己的例外 —— 接 `Exception` 會把我們的 bug 也吞掉。
            skipped.append(dict(a, reason="檔案不是可讀的 PDF（%s）"
                                          % type(exc).__name__))
            continue
        if len(writer.pages) == before:
            # ☠️ 沒丟例外而一頁都沒多 —— 零頁 PDF 就是這一格。
            skipped.append(dict(a, reason="這份 PDF 沒有任何頁面"))
    out = _io_bytes(b"")
    writer.write(out)
    return out.getvalue(), skipped


def _io_bytes(b):
    import io
    return io.BytesIO(b)


def export_voucher_pdf(voucher_id, with_attachments=False):
    """回 `(pdf_bytes, missing)`。`missing` 是**併不進去的那幾筆**。

    ⚠️ 已作廢的傳票**也要印得出來** —— `get_voucher()` 讀的是實表 `vouchers_all`
       不是 `vouchers` 那個 VIEW（`WHERE voided_at = ''`）。
    ☠️ 讀 VIEW 的症狀是 404，**而它讀起來像資料被刪了**。

    🔴 `JV23`（依據使用者 2026-09-23 裁示）：算**一次** `watermark_html(v)`
    存成變數，下面兩次 `build_html()` 呼叫都要傳——不是各自呼叫一次。
    `voided_at`／`approval_done()` 的結果不會在這兩次呼叫之間改變（同一
    次匯出，中途沒有人會去簽核或作廢它），算兩次只是浪費，而**各自傳參數
    的寫法容易漏掉第二次那一個**（那正是這次踩到的缺陷形狀）。
    """
    conn = get_db()
    try:
        v = get_voucher(conn, voucher_id)
        if v is None:
            return None, []
        v["_company"] = _company_name()
        rows = []
        if with_attachments:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM voucher_attachments"
                " WHERE voucher_id = ? AND deleted_at = ''"
                " ORDER BY uploaded_at, id", (voucher_id,))]
    finally:
        conn.close()

    images, pdfs, missing = split_attachments(rows)
    exported_at = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    wm = watermark_html(v)

    # ⚙️ 先用「預期會併進去的筆數」組一次，合併之後若有 PDF 併不進去，
    #    那個數字與清單都會變 ⇒ **重印一次本體**（Edge 跑第二次）。
    #    🔑 寧可多跑一次，也不要讓紙上的數字與實際不符。
    v["_merged"] = len(images) + len(pdfs)
    body = _render(build_html(v, images, missing, exported_at, watermark=wm))
    if not pdfs:
        return body, missing

    merged, skipped = _merge_pdfs(body, pdfs)
    if skipped:
        missing = missing + skipped
        v["_merged"] = len(images) + len(pdfs) - len(skipped)
        body = _render(build_html(v, images, missing, exported_at, watermark=wm))
        merged, _again = _merge_pdfs(body, [p for p in pdfs if p not in skipped])
    return merged, missing


def preview_html(voucher_id):
    """`JV11`：預覽稿 HTML。回 `None` 表示這張傳票不存在。

    ## 🔴 `§228`：**這是唯一產生「傳票長什麼樣」這份 HTML 的地方**

    預覽塞進前端 modal 的那一份，跟匯出成 PDF 前 Edge 印的那一份，
    是**同一個 `build_html()` 呼叫**（只差 `watermark` 參數）——版面只有
    一份，不會分岔。與 `BN6` 驗收④（預覽的 `lines` 必須與產生後逐筆相等）
    是同一條原則：**預覽與正式輸出必須來自同一個來源，否則預覽會騙人。**

    ## ⚠️ 刻意不帶附件圖片

    `build_html()` 的圖片走 `<img src="file:///...">`——那是給 Edge **在
    伺服器本機**印 PDF 用的絕對路徑，瀏覽器（使用者的用戶端）連不到伺服器
    的檔案系統，塞進 `<iframe>`／`innerHTML` 只會是一堆破圖。預覽只需要
    傳票本體、分錄、簽核格與浮水印，附件本來就有自己的檢視入口
    （傳票頁的附件區）。
    """
    conn = get_db()
    try:
        v = get_voucher(conn, voucher_id)
        if v is None:
            return None
        v["_company"] = _company_name()
    finally:
        conn.close()
    exported_at = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    v["_merged"] = 0
    return build_html(v, [], [], exported_at, watermark=watermark_html(v))
