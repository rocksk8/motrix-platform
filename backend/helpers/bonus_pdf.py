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
`JV15` 才補回「已過帳也放」那一格。獎金單今天**沒有「已過帳」這個終態**
（`BN8` 的狀態機只有草稿／待審核／簽核中／已核准四個）——這裡的閘門
只寫上面三條，**不是漏寫第四條**。⚠️ **若獎金單未來加了終態**（例如
接了自動回填 `voucher_no_payment` 之後的某種「已請款」狀態），
`can_export()` 要回來補「終態也放行」那一格，不然會重蹈
`JV11 -> JV15` 的覆轍（`test_bonus_award_pdf_export_2026_09_23.py`
檔頭原話）。
"""
import logging

from db import get_db
from helpers.bonus import bonus_signatures_of
from helpers.voucher import resolve_display_names
from helpers.voucher_pdf import _company_name, _render, _fmt_money

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
    """基點 -> 人看得懂的百分比字串。與 `routers/bonus.py::_pct_text()` 同一條
    規則（那一支不對外公開，這裡只是同樣的格式化，不是重複的業務規則）。
    """
    return ("%g%%" % ((int(bp or 0)) / 100.0))


def _esc(s):
    import html
    return html.escape(str(s if s is not None else ""))


def build_award_html(award, lines, signatures, display_names, exported_at):
    """組出要餵給 Edge 的 HTML。**只有一張表，沒有附件頁。**

    `display_names`：`{username: 顯示名稱}`，收款人那一欄用它——與簽核
    格同一條規則（`§6②` 逐字：內部帳號印在對外／對稽核的憑證上，
    使用者要看到的是姓名），只是套用在收款人清單而不是簽核格上。
    """
    e = _esc
    total = sum(int(ln.get("amount") or 0) for ln in lines or ())

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
  .sheet {{ padding: {m}pt {m}pt 0 {m}pt; }}
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
  .signs {{ display: flex; margin-top: 12pt; border: 0.6pt solid #000; }}
  .sig {{ flex: 1; border-right: 0.6pt solid #000; padding: 5pt 6pt;
          font-size: 9.2pt; min-height: 26pt; }}
  .sig:last-child {{ border-right: none; }}
  .sig span {{ color: #444; margin-right: 6pt; }}
  .sig i {{ display: block; font-style: normal; color: #444; font-size: 8pt; }}
  .foot {{ margin-top: 10pt; font-size: 7.5pt; color: #444; }}
</style></head><body>
<div class="sheet">
  <div class="org">{org}</div>
  <div class="doc">獎金分潤單</div>
  <div class="head"><div>案件編號　{quote}</div><div>基數　{base}</div>
    <div>狀態　{status}</div></div>
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
        rows="".join(rows), signs=sign_html,
        foot=e("匯出時間 %s" % exported_at))


def _display_names_for(conn, usernames):
    """`{username}` 集合 -> `{username: 顯示名稱}`，查不到就落回 username 本身。

    與 `helpers/voucher.py::resolve_display_names()` 是**同一條規則**
    （查不到落回帳號，不印空白）套在不同的資料形狀上——那一支處理的是
    `{格名: {by, at}}` 的簽核格，這裡處理的是收款人清單，形狀不同所以
    沒有直接呼叫它，但查詢與落回邏輯不重寫第二次判斷式，只是換一種
    輸入輸出包裝。
    """
    names = {u for u in (usernames or ()) if u}
    if not names:
        return {}
    placeholders = ",".join("?" for _ in names)
    rows = conn.execute(
        "SELECT username, display_name FROM users WHERE username IN (%s)"
        % placeholders, tuple(names)).fetchall()
    return {r["username"]: (r["display_name"] or r["username"]) for r in rows}


def export_award_pdf(award_id):
    """回 `(award, pdf_bytes)`；找不到這張單回 `(None, None)`。

    ⚠️ 呼叫端（`routers/bonus.py`）自己先呼叫 `can_export()` 判斷放不放
    行——這支只負責**組出 PDF**，不做閘門判斷（同 `export_voucher_pdf()`
    與 `download_voucher_pdf()` 的分工：閘門在 router，內容產生在
    helpers）。
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
        signatures = resolve_display_names(conn, bonus_signatures_of(award))
        display_names = _display_names_for(
            conn, (ln.get("username") for ln in lines))
    finally:
        conn.close()

    exported_at = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    html_text = build_award_html(award, lines, signatures, display_names,
                                 exported_at)
    return award, _render(html_text)
