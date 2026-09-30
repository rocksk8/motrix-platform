# -*- coding: utf-8 -*-
"""M07 → M06 總帳事件提供者（`gl.events`，IP-GL1，契約 v1）：勞報單（個人承攬）應付 E06 與付款 E06b。設計：proposal-gl/02-events-engine.md §4。

- E06（依簽回日／勞報日認列，已簽回與已付款的勞報單）：借 勞務費用＝給付總額／貸 代扣所得稅、代扣二代健保、其他應付款＝實付。
  扣繳金額與規則版本以勞報單凍結值為準（`tax_rules_version`），總帳不重算。實付與「給付總額－扣繳」不一致（來源資料自相矛盾）⇒ 以給付總額－扣繳
  平帳並在 notice 明說，不自行改來源。
- E06b（依付款日，已付款）：借 其他應付款／貸 銀行＝實付（付款日缺 ⇒ 不產生並 notice；`voucher_no` 是出納填的既有手工傳票，若已有
  手工付款傳票，會計改用「補登」擋掉重複——本批不自動偵測）。
- 對象：以受款人編號（`C<contractor_id>`）與姓名為對象，**不帶身分證字號**進總帳。
- 退回簽回（unsign）⇒ 狀態離開已簽回 ⇒ 事件消失 ⇒ 引擎判來源消失、產生反向草稿；作廢僅在簽回前，尚無分錄。
- E07 獎金（既有 `bonus_vouchers` 開的核准應付傳票與發放傳票）：以 `mode=native` 登記「這張傳票就是這個事件」（`bonus_case_awards.accrual_voucher_id`／
  `payment_voucher_id`，日期＝傳票日期），引擎不重複產生、不改動；傳票作廢或重開後指向新傳票 ⇒ 舊列 superseded、新列 native。
只讀，不寫資料。
"""
from core import registry
import json

from db import get_db
from helpers.legal_params import round_half_up


def _i(x):
    return int(round_half_up(x or 0))


def _paid_via_remit(raw):
    try:
        return bool((json.loads(raw or "{}") or {}).get("paid_via_remit"))
    except (TypeError, ValueError):
        return False


def gl_events(start, end, *, changed_since=""):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT slip_no, contractor_id, contractor_name, income_type, gross_amount, tax_withheld, nhi_supplement, net_amount, "
            "slip_date, status, tax_rules_version, signed_at, payment_date, data_json FROM payslips "
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
        if r["status"] == "已付款" and not _paid_via_remit(r["data_json"]):        # 由承攬商匯款單付款者，付款分錄是匯款單的 E05（不重複）
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
    native = _bonus_native(start, end, notices)
    events += native
    return {"events": events, "notice": " ".join(notices)}


def _bonus_withholding(conn, award_id):
    """已發放獎金的扣繳快照（發放當下寫的）⇒ [{kind, party_key, gross, amount, income_type}]；沒有快照（舊資料）⇒ []。"""
    from modules.payroll import bonus_payouts
    snap = bonus_payouts.paid_snapshot(conn, award_id) or {}
    out = []
    for ln in snap.get("lines") or []:
        for kind, key in (("income_tax", "withholding"), ("nhi", "nhiPremium")):
            amt = ln.get(key)
            if isinstance(amt, int) and not isinstance(amt, bool) and amt > 0:
                out.append({"kind": kind, "party_key": ln.get("username") or "", "gross": int(ln.get("gross") or 0), "amount": amt, "income_type": "bonus"})
    return out


def _bonus_native(start, end, notices):
    """獎金核准／發放已開的傳票 ⇒ mode=native 事件。會計模組不在（讀不到傳票）⇒ 不登記並 notice。"""
    status = registry.single_provider("voucher.status")
    conn = get_db()
    try:
        try:
            rows = conn.execute("SELECT id, quote_no, accrual_voucher_id, payment_voucher_id FROM bonus_case_awards "
                                "WHERE accrual_voucher_id>0 OR payment_voucher_id>0 ORDER BY id").fetchall()
        except Exception:                                                          # noqa: BLE001  獎金表不存在（舊庫）
            return []
        if rows and status is None:
            notices.append("會計模組未提供傳票狀態：獎金既有傳票不登記。")
            return []
        out, gone = [], 0
        for r in rows:
            for kind, code, vid in (("accrual", "E07a", r["accrual_voucher_id"]), ("payment", "E07b", r["payment_voucher_id"])):
                if not vid:
                    continue
                v = status(conn, vid)
                if v is None:
                    gone += 1
                    continue
                if v.get("voided") and kind != "payment":
                    gone += 1
                    continue
                d = v.get("date") or ""
                if not d or not (start <= d <= end):
                    continue
                meta = {"award_id": r["id"]}
                if kind == "payment":                              # 發放：帶每人代扣稅款／補充保費，供總帳扣繳清單（作廢的傳票也照送，讓引擎移除未繳庫的列）
                    meta["wh_prefix"] = "%d::" % r["id"]
                    meta["withholding"] = _bonus_withholding(conn, r["id"])
                out.append({"source_type": "bonus_" + kind, "source_key": str(r["id"]), "event_code": code, "event_date": d,
                            "doc_no": v["voucher_no"], "case_no": r["quote_no"], "party": {"key": "", "name": ""}, "tax_code": "",
                            "mode": "native", "native_voucher_id": int(vid), "meta": meta})
        return out
    finally:
        conn.close()
