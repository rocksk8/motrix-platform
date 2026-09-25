# -*- coding: utf-8 -*-
"""獎金分潤單 PDF 匯出（`BN7`）。

依 `docs/windows/SPEC-BN6-BN7.md §4` ／使用者 2026-09-23 裁：**用印欄
列數由簽核設定決定，與傳票、報價單同一套規則**（走 (a) 完整簽核鏈——
這條路走得通的前提是 `BN8` 已經把 submit/approve/reject 接上，`e4572ae`
／`e6cf983`）。

# 🔴 只有一張表，無附件 ⇒ 不需要 `pypdf`

`voucher_pdf.py` 因為要合併 PDF／圖片附件才需要 `pypdf`；獎金分潤單沒有
附件這件事，`HTML -> run_edge_pdf(--print-to-pdf) -> bytes` 這一段與既有
16 個呼叫端同一形狀，比 `JV5` 簡單（`SPEC-BN6-BN7.md §4` 逐字）。

# 🔴 閘門：與傳票 `JV11`／`JV15` 同一條，不是「狀態不等於已核准」

```
voided_at 為真          -> 放（不管簽到哪裡，稽核優先）
status == "已核准"      -> 放
其餘（草稿／待審核／簽核中） -> 擋
```
⚠️ `JV11` 踩過的坑：把「未簽核完成」寫成「狀態不等於已核准」，
`JV15` 才補回「已過帳也放」那一格。獎金分潤單今天**沒有「已過帳」這個終態**
（`BN8` 的狀態機只有草稿／待審核／簽核中／已核准四個）——這裡的閘門
只寫上面三條，**不是漏寫第四條**。⚠️ **若獎金分潤單未來加了終態**（例如
接了自動回填 `voucher_no_payment` 之後的某種「已請款」狀態），
`can_export()` 要回來補「終態也放行」那一格，不然會重蹈
`JV11 -> JV15` 的覆轍（`test_bonus_award_pdf_export_2026_09_23.py`
檔頭原話）。
"""
import logging

from db import get_db
from modules.payroll.bonus import bonus_signatures_of, SETTLEMENT_ROWS, settlement_fields
# X-VAT（2026-09-26）：金額一律四捨五入（內建 round() 是銀行家捨入：.5 取偶數）
from helpers.legal_params import round_half_up

# 2026-09-26（M07 搬遷）：組 PDF／預覽要用的四樣都在 L1——簽核格顯示名稱 `helpers.tiered_approval`、
# 公司抬頭 `helpers.company_identity`（主要據點，QL8）、HTML→PDF `pdf_gen.html_to_pdf_bytes`（Edge 參數與傳票相同）、
# 金額 `pdf_gen.fmt_money_blank_zero`。原本借 M06 的 `helpers.voucher`／`helpers.voucher_pdf`（稽核 Y-2：用到時才 import，
# M06 不在就 503）⇒ 現在 M06 不在時獎金分潤單照樣能預覽與匯出，l2_import_baseline 那兩筆邊刪除。


def _pdf_parts():
    """回 `(resolve_display_names, company_name, render, fmt_money)`，全部是 L1。"""
    from helpers.company_identity import company_name
    from helpers.tiered_approval import resolve_display_names
    from pdf_gen import fmt_money_blank_zero, html_to_pdf_bytes
    return resolve_display_names, company_name, html_to_pdf_bytes, fmt_money_blank_zero

logger = logging.getLogger(__name__)

#: A4 直式，單位 pt——沿用 `voucher_pdf.py` 量出來的那份（同一種紙、
#: 同一台印表機），不必重新量一次。
_PAGE_W, _PAGE_H = 595.32, 841.92
_MARGIN = 42.6


def can_export(award):
    """這張獎金分潤單現在放不放行匯出。回 `(ok, message)`。

    見模組 docstring 的閘門說明——`voided_at` 優先於 `status`。
    """
    if award.get("voided_at"):
        return True, ""
    if award.get("status") == "已核准":
        return True, ""
    return False, (
        "這張獎金分潤單還沒有簽核完成（現在是「%s」），不能匯出。"
        % (award.get("status") or ""))


def award_watermark_html(award):
    """要不要蓋浮水印、蓋哪一句。視覺同 `voucher_pdf.py::watermark_html()`
    （3x4 格線平鋪、`rotate(-28deg)`、顏色極淡不影響閱讀）。

    ## 🔴 作廢優先於未簽核（`BN12 §4`，照搬 `JV11` 的使用者裁示）

    一張**還沒簽核就被作廢**的單要印「已作廢」不是「尚未簽核」——
    ☠️ 印「尚未簽核」的話，有人會去把它簽完。

    📌 更正留著（`BN13` 當時的版本只做「已作廢」這一半）：那時的理由是
    「`can_export()` 已經把未簽核的擋在匯出之外，那一句到不了這裡」——
    **對匯出路徑仍然成立**（匯出只放行已核准／已作廢，結果與舊版相同）；
    而 `BN12` 加了**預覽**這條路，預覽不看簽核狀態，「未簽核」從此到得了。
    """
    e = _esc
    if award.get("voided_at"):
        title, sub = "本獎金分潤單已作廢", "僅供稽核存查"
    elif award.get("status") != "已核准":
        title, sub = "獎金分潤單尚未簽核完成", "預覽稿・尚未正式生效"
    else:
        return ""
    items = "".join(
        "<div class='wm-item'><b>%s</b><small>%s</small></div>" % (e(title), e(sub))
        for _ in range(12))
    return "<div class='wm'>%s</div>" % items


def _sign_cells(signatures):
    """簽核格。**從資料算幾格，不是寫死**——同 `voucher_pdf.py::_sign_cells()`
    的道理，這裡不 import 那一支（它綁在 `voucher` 這個名字上，僅僅是
    「把 dict 攤成 tuple 列表」這三行本身不含任何規則，複製它不算複製
    規則——規則本身在 `bonus_signatures_of()` 裡，那一支才是唯一來源）。
    """
    return [(k, (v or {}).get("by") or "", (v or {}).get("at") or "")
            for k, v in (signatures or {}).items()]


def _line_rows(lines, display_names):
    """每一筆 `bonus_award_lines` 一列。`display_names` 是
    `{username: 顯示名稱}`——查不到就落回 username 本身（同
    `resolve_display_names()` 的「查不到落回帳號，不印空白」那一條規則，
    套在收款人這個不同的資料形狀上）。
    """
    e = _esc
    _fmt_money = _pdf_parts()[3]
    rows = []
    for ln in lines or ():
        username = ln.get("username") or ""
        who = display_names.get(username, username)
        rows.append(
            "<tr><td>%s</td><td>%s</td>"
            "<td class='num'>%s</td><td class='num'>%s</td>"
            "<td class='num'>%s</td></tr>"
            % (e(ln.get("item_name_snapshot") or ""), e(who),
               e(_pct_text(ln.get("total_pct"))),
               e(_pct_text(ln.get("person_pct"))),
               _fmt_money(ln.get("amount"))))
    return rows


def _pct_text(bp):
    """基點 -> 人看得懂的百分比字串。與 `modules/payroll/api/bonus.py::_pct_text()` 同一條
    規則（那一支不對外公開，這裡只是同樣的格式化，不是重複的業務規則）。
    """
    return ("%g%%" % ((int(bp or 0)) / 100.0))


def _esc(s):
    import html
    return html.escape(str(s if s is not None else ""))


def _settle_money(n):
    """精算明細表的金額格式。**`None` 印「—」，`0` 印「NT$ 0」**——與
    `_fmt_money()`（傳票用，0 印空白）不是同一條規則，不可以共用：精算
    欄位的 0 是有意義的值（例如某案的額外支出真的是 0，`SPEC-BN11-BN12.md
    §5 ⓑ` 就是拿一張額外支出非 0、一張是 0 的案子互相對照），〈null 不
    等於 0〉——缺欄位（`None`）與「真的是 0」不可以印成同一種樣子。
    """
    if n is None:
        return "—"
    return "NT$ %s" % "{:,}".format(round_half_up(n))


def _settle_pct(n):
    """精算明細表的百分比格式，同 `bonus.html::fmtPct()` 的規則（1 位小數，
    缺值印「—」）——PDF 這裡沒有 JS，格式化規則不能共用程式碼，只能兩邊
    對齊寫法。
    """
    if n is None:
        return "—"
    return "%.1f%%" % float(n)


def _settlement_of(conn, quote_no):
    """案件精算存值。與 `modules/payroll/api/bonus.py::_settlement_of()` 同形狀的一次
    查詢——`modules/payroll/bonus.py` 的 `settlement_fields()` 已經是唯一一份
    「挑哪些鍵、缺值回 `None`」的規則，會分岔的風險在那裡，已經只有一份；
    這裡只是換一種資料存取路徑把值撈出來，不算重刻規則本身。
    """
    row = conn.execute(
        "SELECT json_extract(data_json, '$.settlement') AS s"
        " FROM quotations WHERE quote_no = ?", (quote_no,)).fetchone()
    if row is None:
        return None
    raw = row["s"]
    if not raw:
        return {}
    import json
    return json.loads(raw) if isinstance(raw, str) else raw


def _settlement_rows_html(settle):
    """精算明細表的 11 列 `<tr>`（`BN11`）。**唯一列定義是 `SETTLEMENT_ROWS`**
    （`modules/payroll/bonus.py`）——順序、標籤逐字照它，值來自 `settlement_fields()`
    （原樣帶出，這裡不重算任何係數）。

    `quotedTotal`（含稅總額）不是獨立一列，是 `quotedPretax` 那一列的
    註記——同 `bonus.html` 的 `bn-settle__note` 那一格。
    """
    e = _esc
    fields = settlement_fields(settle)
    rows = []
    for key, label, kind, note in SETTLEMENT_ROWS:
        val = fields.get(key)
        text = _settle_pct(val) if kind == "pct1" else _settle_money(val)
        lbl = e(label)
        if note:
            lbl += "<small>%s</small>" % e(note)
        if key == "quotedPretax":
            qt = fields.get("quotedTotal")
            if qt is not None:
                text += "<small>（含稅 %s）</small>" % _settle_money(qt)
        rows.append("<tr><td>%s</td><td class='num'>%s</td></tr>"
                    % (lbl, text))
    return "".join(rows)


def build_award_html(award, lines, signatures, display_names, exported_at,
                     settle=None):
    """組出要餵給 Edge 的 HTML。**只有一張表，沒有附件頁。**

    `display_names`：`{username: 顯示名稱}`，收款人那一欄用它——與簽核
    格同一條規則（`§6②` 逐字：內部帳號印在對外／對稽核的憑證上，
    使用者要看到的是姓名），只是套用在收款人清單而不是簽核格上。

    🔴 `BN13`／`BN12`：浮水印一律由 `award_watermark_html(award)` 算，這裡不自己
    判斷 `voided_at`——已作廢時印，其餘一律空字串（同 `JV23` 的分工）。

    🔴 `BN11`：`settle` 是案件的精算存值（`_settlement_of()` 的回傳，
    passthrough 給 `settlement_fields()`）——**這裡不重算任何係數**，
    值與 `bonus.html` 的 `bn-settle`、`GET /awards/{id}` 回應裡的
    `settlement` 是同一份資料。`settle=None`（呼叫端沒帶）時整張精算表
    仍然印出來，11 列全部是「—」，不是整段消失——使用者原話「最後算出
    真實淨利，才能用真實淨利去算獎金」，這張表在說明基數怎麼來的，
    印不出值也要讓人看到「這裡本來該有 11 個數字」。
    """
    e = _esc
    _resolve, _company_name, _render, _fmt_money = _pdf_parts()
    watermark = award_watermark_html(award)
    total = sum(int(ln.get("amount") or 0) for ln in lines or ())
    settle_rows_html = _settlement_rows_html(settle)

    rows = _line_rows(lines, display_names)
    rows.append(
        "<tr class='total'><td colspan='4' class='lbl'>合　計</td>"
        "<td class='num'>%s</td></tr>" % _fmt_money(total))

    sign_html = "".join(
        "<div class='sig'><span>%s</span><b>%s</b><i>%s</i></div>"
        % (e(k), e(by), e((at or "")[:10])) for k, by, at in _sign_cells(signatures))

    return """<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="utf-8">
<style>
  @page {{ size: {pw}pt {ph}pt; margin: 0; }}
  body {{ margin: 0; font-family: "Microsoft JhengHei", "PingFang TC", sans-serif;
          color: #000; }}
  .sheet {{ padding: {m}pt {m}pt 0 {m}pt; position: relative; }}
  /* `BN13`：已作廢的浮水印——與 voucher_pdf.py 的 .wm/.wm-item 同一套
     視覺（3x4 格線平鋪、rotate(-28deg)、顏色極淡不影響閱讀）。 */
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
  /* `BN11`：精算明細表——與 `bonus.html` 的 `.bn-settle__tbl` 同一種
     長相（label／value 兩欄，小字註記跟在後面），紙上版本沒有邊框
     （沿用這支檔案原本「表格才有格線」的視覺，`.settle` 是說明性質的
     兩欄清單，不是要對齊填寫的表格）。 */
  .settle-t {{ font-size: 9.8pt; font-weight: 700; margin: 2pt 0 4pt; }}
  .settle {{ width: 100%; border-collapse: collapse; font-size: 9.3pt;
             margin-bottom: 10pt; }}
  .settle td {{ border: none; height: 15.8pt; padding: 1pt 2pt; }}
  .settle td:first-child {{ color: #333; width: 55%; }}
  .settle small {{ color: #666; font-size: 7.6pt; margin-left: 4pt; }}
  .signs {{ display: flex; margin-top: 12pt; border: 0.6pt solid #000; }}
  .sig {{ flex: 1; border-right: 0.6pt solid #000; padding: 5pt 6pt;
          font-size: 9.2pt; min-height: 26pt; }}
  .sig:last-child {{ border-right: none; }}
  .sig span {{ color: #444; margin-right: 6pt; }}
  .sig i {{ display: block; font-style: normal; color: #444; font-size: 8pt; }}
  .foot {{ margin-top: 10pt; font-size: 7.5pt; color: #444; }}
</style></head><body>
<div class="sheet">
  {watermark}
  <div class="org">{org}</div>
  <div class="doc">獎金分潤單</div>
  <div class="head"><div>案件編號　{quote}</div><div>基數　{base}</div>
    <div>狀態　{status}</div></div>
  <div class="settle-t">案件精算明細（比照精算頁面）</div>
  <table class="settle">
    {settle_rows}
  </table>
  <table>
    <tr><th>獎金項目</th><th>領款人</th><th class="num">發放比例</th>
        <th class="num">個人比例</th><th class="num">金額</th></tr>
    {rows}
  </table>
  <div class="signs">{signs}</div>
  <div class="foot">{foot}</div>
</div>
</body></html>""".format(
        pw=_PAGE_W, ph=_PAGE_H, m=_MARGIN,
        org=e(_company_name() or "（尚未設定公司抬頭）"),
        quote=e(award.get("quote_no") or ""),
        base=_fmt_money(award.get("base_amount")),
        status=e("已作廢" if award.get("voided_at") else (award.get("status") or "")),
        watermark=watermark,
        settle_rows=settle_rows_html,
        rows="".join(rows), signs=sign_html,
        foot=e("匯出時間 %s" % exported_at))


def display_names_for(conn, usernames):
    """`{username}` 集合 -> `{username: 顯示名稱}`，查不到就落回 username 本身。

    與 `helpers/voucher.py::resolve_display_names()` 是**同一條規則**
    （查不到落回帳號，不印空白）套在不同的資料形狀上——那一支處理的是
    `{格名: {by, at}}` 的簽核格，這裡處理的是收款人清單，形狀不同所以
    沒有直接呼叫它，但查詢與落回邏輯不重寫第二次判斷式，只是換一種
    輸入輸出包裝。

    `QS1-a §3③`：`modules/payroll/api/bonus.py` 的 `list_awards()`／`get_award()`
    也用它給每一列分潤明細補 `displayName`——原本沒有底線是因為只有
    `bonus_pdf.py` 自己用，現在是共用工具，底線拿掉（同 `resolve_display_
    names()` 當初從 `_` 改成公開名字的理由：保留底線會誤導成「模組內部
    專用，不可外部 import」）。
    """
    names = {u for u in (usernames or ()) if u}
    if not names:
        return {}
    placeholders = ",".join("?" for _ in names)
    rows = conn.execute(
        "SELECT username, display_name FROM users WHERE username IN (%s)"
        % placeholders, tuple(names)).fetchall()
    return {r["username"]: (r["display_name"] or r["username"]) for r in rows}


def _award_html(award_id):
    """回 `(award, html)`；找不到回 `(None, None)`。**預覽與匯出共用這一支**
    —— 版面只有一份（`SPEC-BN11-BN12 §4 ②`：兩份版面的失敗模式是
    「預覽對、印出來不對」，而那要印出來才發現）。
    """
    import datetime as _dt
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM bonus_awards WHERE id = ?",
                           (award_id,)).fetchone()
        if row is None:
            return None, None
        award = dict(row)
        lines = [dict(r) for r in conn.execute(
            "SELECT * FROM bonus_award_lines WHERE award_id = ? ORDER BY id",
            (award_id,))]
        signatures = _pdf_parts()[0](conn, bonus_signatures_of(award))
        display_names = display_names_for(
            conn, (ln.get("username") for ln in lines))
        settle = _settlement_of(conn, award.get("quote_no"))
    finally:
        conn.close()
    exported_at = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    return award, build_award_html(award, lines, signatures, display_names,
                                   exported_at, settle=settle)


def preview_award_html(award_id):
    """`BN12`：預覽稿 HTML（**不看簽核狀態**；閘門在匯出端點，不在這裡）。"""
    _award, html_text = _award_html(award_id)
    return html_text


def export_award_pdf(award_id):
    """回 `(award, pdf_bytes)`；找不到這張單回 `(None, None)`。

    ⚠️ 呼叫端（`modules/payroll/api/bonus.py`）自己先呼叫 `can_export()` 判斷放不放
    行——這支只負責**組出 PDF**，不做閘門判斷（同 `export_voucher_pdf()`
    與 `download_voucher_pdf()` 的分工：閘門在 router，內容產生在
    helpers）。
    """
    award, html_text = _award_html(award_id)
    if award is None:
        return None, None
    return award, _pdf_parts()[2](html_text)
