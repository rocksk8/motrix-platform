"""應收收入與銷項發票的資料收集（L1；2026-09-26 自 routers/reports.py 下沉，M08 搬遷 ③）。

為什麼在 L1：這兩份資料是**純資料收集、多個模組在用**——出納（M05 `cashier`：收入清單）、會計匯出（M06
`accounting_export`：T100 收款事件）、營運報表（M08：當月／今年度收支、稅務匯出）。放在 reports 時，
M05／M06 在 import 時就載入 M08 ⇒ 拿掉 M08 出納與會計匯出直接 ImportError（主持裁示 a，ROADMAP A8b）。
**中繼**：資料擁有權在 M05（ROADMAP A8b），M05 搬遷時收回 M05。
⚠ 依賴 M01 的計算（payment_item_amounts、quote_tax_type、tax_split、invoice_amounts）與 quotations 表：
M01 搬遷時改用 M01 公開的 provider（ROADMAP M01 條目）。

函式本體與原本逐字相同，只改名成公開名稱；reports.py 保留舊的底線名稱作為別名。
"""
import json
from typing import Optional

from db import get_db
from helpers import payment_item_amounts
from helpers.tax_calc import quote_tax_type, tax_split, LEGACY_TAX_NOTE, invoice_amounts   # T：L1（第六班合回後補：receivables 在第六班才進 platform）

__all__ = ["collect_income_items", "collect_tax_invoices", "round_half_up_invoice"]


def round_half_up_invoice(n) -> int:
    """財政部統一發票金額計算慣例是「四捨五入」（.5 一律進位），Python 內建
    `round()` 是「銀行家捨入」（.5 進位到最近偶數）——兩者只在剛好卡在 .5
    邊界時才會差 1 元，但既然這裡的數字要拿去對真實開立的發票金額，就該用
    跟開票軟體一致的規則，不要假設「大部分時候一樣」就夠了。
    X-VAT（2026-09-26）：轉呼叫 L1 `legal_params.round_half_up`（金額捨入唯一來源）。"""
    from helpers.legal_params import round_half_up
    return round_half_up(n)


def collect_tax_invoices(year: Optional[int] = None, month: Optional[int] = None) -> list:
    """收集所有已填發票號碼的收款品項（案件管理財務Tab item.invoiceNo，自由文字，
    使用者開立發票後手動填入）＝銷項發票清單，供記帳士/稅務申報使用。

    未填 invoiceNo 的收款品項（尚未開發票）不列入。金額欄位：item 的 amount 為
    報價單「含稅總價」的一部分（見 payment_item_amounts() docstring），這裡換算
    5% 稅額拆出未稅/稅額/含稅三欄；若日後改用非 5% 稅率，此處需一併調整。

    2026-09-02 修復（反派/國稅局視角複查發現）：taxExempt（已核准稅額沖銷）
    品項過去在這裡被列成「稅額=0、未稅=含稅」，等於把一筆已經開立發票、已經
    對國稅局產生銷項稅額的交易，在申報用文件上回溯性地變成免稅交易——但
    這個迴圈本身已經先過濾掉沒填 invoiceNo 的品項，能走到這裡的一定是「已經
    開立過統一發票」的款項，taxExempt 只是之後才核准的內部應收帳款減讓（公司
    決定不跟客戶收那筆稅額），不會、也不能追溯改變已經開立當下就確定的法定
    稅捐義務。改用 apply_tax_exempt=False 取得「原始開立金額」（不套用沖銷
    折算）永遠照標準 5% 拆稅公式計算，taxExempt 對「客戶還欠多少」（AR帳齡/
    收款率/dashboard）的影響維持不變，只是不再讓它同時改寫稅務匯出的數字。

    2026-09-02 追加：year/month 期別篩選改用 invoiceDate（發票開立日期，
    2026-09-02 新增欄位，選填）而不是 receivedAt（款項收款日）——依加值型及
    非加值型營業稅法，發票該歸入哪個申報期別是看開立日，不是看客戶什麼時候
    把錢匯進來，兩者常常不同月甚至跨期別。缺漏 invoiceDate 的舊資料退回
    receivedAt（維持既有行為，不會讓歷史資料憑空消失）。回傳的 "date" 欄位
    刻意維持 receivedAt 不變——accounting_export.py 的 T100 現金基礎傳票要的
    就是「現金真的進帳」那天，跟這裡的期別篩選是兩個不同問題，不能共用同一
    個日期：新增獨立的 "invoiceDate" 欄位供期別篩選跟稅務匯出 Excel 顯示用。"""
    conn = get_db()
    rows = conn.execute("""
        SELECT quote_no, customer_name, total, pretax,
               json_extract(data_json,'$.customerTaxId') AS tax_id,
               json_extract(data_json,'$.taxRate') AS tax_rate,
               json_extract(data_json,'$.taxType') AS tax_type,
               json_extract(data_json,'$.caseRecord.payment.items') AS pay_json
        FROM quotations
        WHERE json_extract(data_json,'$.caseRecord.payment.items') IS NOT NULL
    """).fetchall()
    conn.close()

    out = []
    for row in rows:
        try:
            items = json.loads(row["pay_json"] or "[]")
        except Exception:
            items = []
        if not items:
            continue
        amounts = payment_item_amounts(row["total"] or 0, items, row["pretax"], apply_tax_exempt=False)
        # AC1（2026-09-24）：稅別依法規；應稅＝round(該期銷售額 × 5%)，零稅率／免稅＝0。
        #   該期銷售額＝round(報價未稅 × 期別比例)（期別比例＝該期含稅／報價含稅）。
        #   舊 1～4% 單：**不改數字**（沿用原本的 5% 倒推），標「非法定稅率，請會計確認」。
        #   ⚠️ 與實際發票可能差 ±1 元：收款項沒有記載發票上的稅額，以發票為準（交付說明）。
        tax_type = quote_tax_type({"taxType": row["tax_type"], "taxRate": row["tax_rate"]})
        q_total  = float(row["total"] or 0)
        q_pretax = float(row["pretax"] or 0) or q_total
        for idx, pi in enumerate(items):
            inv_no = (pi.get("invoiceNo") or "").strip()
            if not inv_no:
                continue
            received_at  = pi.get("receivedAt") or ""
            invoice_date = pi.get("invoiceDate") or received_at
            if year and invoice_date[:4] != str(year):
                continue
            if month and invoice_date[5:7] != f"{month:02d}":
                continue
            amt_incl   = amounts[idx]
            tax_note   = ""
            recorded   = invoice_amounts(pi)
            if recorded:
                # 收款登錄時填了發票上的未稅／稅額 ⇒ 以發票為準（使用者選 (a)）
                amt_pretax, tax_amt = recorded
                amt_incl = amt_pretax + tax_amt
            elif tax_type == "legacy":
                tax_amt    = round_half_up_invoice(amt_incl - amt_incl / 1.05)
                amt_pretax = amt_incl - tax_amt
                tax_note   = "舊稅率 %s%%（已停用）：%s" % (row["tax_rate"], LEGACY_TAX_NOTE)
            else:
                sales = (q_pretax * amt_incl / q_total) if q_total else amt_incl
                amt_pretax, tax_amt = tax_split(sales, tax_type)
                amt_incl = amt_pretax + tax_amt
            out.append({
                "invoiceNo":     inv_no,
                "date":          received_at,
                "invoiceDate":   invoice_date,
                "quoteNo":       row["quote_no"],
                "customer":      row["customer_name"] or "",
                "taxId":         row["tax_id"] or "",
                "amountPretax":  amt_pretax,
                "taxAmount":     tax_amt,
                "amountTotal":   amt_incl,
                "taxType":       tax_type,
                "taxNote":       tax_note,
                # 收款進帳的 MOTRIX 銀行帳戶（2026-09-01 新增，供 accounting_export.py
                # 依銀行帳戶分開設定 T100 科目代號用；既有呼叫端如 tax-export 不讀這兩個
                # 新 key，多帶不影響既有行為）
                "bankAccountName": pi.get("bankAccountName") or "",
                "bankAccountCode": pi.get("bankAccountCode") or "",
            })
    out.sort(key=lambda r: (r["invoiceDate"], r["quoteNo"]))
    return out


def collect_income_items(d0: str, d1: str, department_id: Optional[int] = None) -> list:
    """輕量版收入明細撈取（2026-08-30 新增，供《當月收支》《今年度收支》兩張
    新報表用）：只找「已收款」品項落在 [d0,d1] 區間內的，不像 _collect() 還要
    順便算案件績效／業務員／部門／保固／精算快照過期等一大包——那些跟收支
    報表無關，這裡刻意獨立一支輕量查詢，避免《月支出》報表每次都多跑一次
    昂貴的 _collect()（尤其「今年度」範圍要另外抓一次，跟主報表選取的期間
    未必相同）。欄位形狀比照 _collect() 的 periodItems，供 Excel/PDF 共用同一套
    表格欄位。"""
    conn = get_db()
    rows = conn.execute("""
        SELECT quote_no, customer_name, project_name, sales_person, sales_person_id,
               total, pretax,
               json_extract(data_json,'$.caseRecord') AS cr_json
        FROM quotations
        WHERE COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') IN ('已成案','已結案')
    """).fetchall()
    dept_by_user = {}
    if department_id:
        dept_by_user = {r["id"]: r["department_id"] for r in conn.execute("SELECT id, department_id FROM users").fetchall()}
    conn.close()

    items = []
    for row in rows:
        if department_id and dept_by_user.get(row["sales_person_id"]) != department_id:
            continue
        cr = {}
        if row["cr_json"]:
            try:
                cr = json.loads(row["cr_json"])
            except Exception:
                pass
        pay = (cr.get("payment") or {}).get("items", [])
        if not pay:
            continue
        amounts = payment_item_amounts(row["total"] or 0, pay, row["pretax"])
        for idx, pi in enumerate(pay):
            if not pi.get("received"):
                continue
            rat = (pi.get("receivedAt") or "")[:10]
            if not (d0 <= rat <= d1):
                continue
            amt = amounts[idx]
            aa  = pi.get("actualAmount")
            fee = pi.get("feeAmount") or 0
            # 統一用 actualAmount（實收金額），未填則退回系統試算金額
            gross_amt = aa if aa is not None else amt
            items.append({
                "quoteNo":      row["quote_no"],
                "customer":     row["customer_name"] or "",
                "project":      row["project_name"]  or "",
                "salesPerson":  row["sales_person"]  or "",
                "type":         pi.get("type", f"第{idx+1}期"),
                "amount":       gross_amt,
                "receivedAt":   rat,
                "actualAmount": aa,
                "feeAmount":    fee,
                "netAmount":    gross_amt - fee,
                "invoiceNo":    pi.get("invoiceNo", ""),
            })
    items.sort(key=lambda x: x["receivedAt"], reverse=True)
    return items
