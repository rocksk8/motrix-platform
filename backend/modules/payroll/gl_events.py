# -*- coding: utf-8 -*-
"""M07 → M06 總帳事件提供者（`gl.events`，IP-GL1，契約 v1）：勞報單（個人承攬）應付 E06 與付款 E06b。設計：proposal-gl/02-events-engine.md §4。

- E06（依簽回日／勞報日認列，已簽回與已付款的勞報單）：借 勞務費用＝給付總額／貸 代扣所得稅、代扣二代健保、其他應付款＝實付。
  扣繳金額與規則版本以勞報單凍結值為準（`tax_rules_version`），總帳不重算。實付與「給付總額－扣繳」不一致（來源資料自相矛盾）⇒ 以給付總額－扣繳
  平帳並在 notice 明說，不自行改來源。
- E06b（依付款日，已付款）：借 其他應付款／貸 銀行＝實付（付款日缺 ⇒ 不產生並 notice；`voucher_no` 是出納填的既有手工傳票，若已有
  手工付款傳票，會計改用「補登」擋掉重複——本批不自動偵測）。
- 對象：以受款人編號（`C<contractor_id>`）與姓名為對象，**不帶身分證字號**進總帳。
- 退回簽回（unsign）⇒ 狀態離開已簽回 ⇒ 事件消失 ⇒ 引擎判來源消失、產生反向草稿；作廢僅在簽回前，尚無分錄。
只讀，不寫資料。
"""
from db import get_db
from helpers.legal_params import round_half_up


def _i(x):
    return int(round_half_up(x or 0))


def gl_events(start, end, *, changed_since=""):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT slip_no, contractor_id, contractor_name, income_type, gross_amount, tax_withheld, nhi_supplement, net_amount, "
            "slip_date, status, tax_rules_version, signed_at, payment_date FROM payslips "
            "WHERE status IN ('已簽回','已付款') ORDER BY slip_no").fetchall()
    finally:
        conn.close()
    events, notices = [], []
    mismatch = nodate = nopay = 0
    for r in rows:
        gross, tax, nhi = _i(r["gross_amount"]), _i(r["tax_withheld"]), _i(r["nhi_supplement"])
        if gross <= 0:
            continue
        net = gross - tax - nhi
        if net < 0:
            notices.append("勞報單 %s 扣繳合計大於給付總額：不產生分錄，請檢查勞報單。" % r["slip_no"])
            continue
        if abs(_i(r["net_amount"]) - net) > 0:
            mismatch += 1
        party = {"key": ("C%s" % r["contractor_id"]) if r["contractor_id"] else (r["contractor_name"] or ""), "name": r["contractor_name"] or ""}
        d = (r["slip_date"] or "")[:10] or (r["signed_at"] or "")[:10]
        if not (r["slip_date"] or "")[:10]:
            nodate += 1
        memo = "勞報單 %s %s" % (r["slip_no"], r["contractor_name"] or "")
        if d and start <= d <= end:
            lines = [{"role": "EXP_LABOR", "side": "D", "amount": gross, "memo": memo}]
            if tax:
                lines.append({"role": "WITHHOLD_TAX", "side": "C", "amount": tax, "memo": "代扣所得稅（%s 類）" % r["income_type"]})
            if nhi:
                lines.append({"role": "WITHHOLD_NHI", "side": "C", "amount": nhi, "memo": "代扣二代健保"})
            lines.append({"role": "OTHER_PAYABLE", "side": "C", "amount": net, "memo": memo})
            events.append({
                "source_type": "payslip", "source_key": r["slip_no"], "event_code": "E06", "event_date": d,
                "doc_no": r["slip_no"], "case_no": "", "party": party, "tax_code": "", "mode": "snapshot", "lines": lines,
                "meta": {"income_type": r["income_type"], "tax_rules_version": r["tax_rules_version"], "date_from_signed": not (r["slip_date"] or "")[:10]}})
        if r["status"] == "已付款":
            pd = (r["payment_date"] or "")[:10]
            if not pd:
                nopay += 1
            elif net > 0 and start <= pd <= end:
                events.append({
                    "source_type": "payslip_payment", "source_key": r["slip_no"], "event_code": "E06b", "event_date": pd,
                    "doc_no": r["slip_no"], "case_no": "", "party": party, "tax_code": "", "mode": "snapshot",
                    "lines": [{"role": "OTHER_PAYABLE", "side": "D", "amount": net, "memo": memo},
                              {"role": "BANK", "side": "C", "amount": net, "memo": memo}], "meta": {}})
    if mismatch:
        notices.append("%d 張勞報單的實付與「給付總額－扣繳」不一致：分錄以給付總額－扣繳平帳，請檢查勞報單。" % mismatch)
    if nodate:
        notices.append("%d 張勞報單沒有勞報日期：暫以簽回日認列。" % nodate)
    if nopay:
        notices.append("%d 張已付款勞報單沒有付款日期：不產生付款分錄。" % nopay)
    return {"events": events, "notice": " ".join(notices)}
