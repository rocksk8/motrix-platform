# -*- coding: utf-8 -*-
"""e2e 共用：33-M1 之後材料申請只能從「已核准的採購單明細」帶入——這裡用 API 開一張採購單並送審（flow 沒設簽核層＝送審即核准）。
回 `(extra_expense_id, docCode)`；採購單明細的行號是 1（單行）。呼叫端自己準備報價單與登入。"""


def approved_po(ctx, base, headers, quote_no, summary, qty, unit_cost, applicant, unit="台", item_id=None):
    from helpers import _get_setting, _set_setting
    prev = _get_setting("unified_approval_flow", None)
    _set_setting("unified_approval_flow", {"includeSubmitterManagerTier": False, "tiers": []})
    line = {"category": "雜項", "summary": summary, "qty": qty, "unit": unit, "unitCost": unit_cost}
    if item_id:
        line["itemId"] = item_id
    r = ctx.request.post("%s/api/quotations/%s/extra-expenses" % (base, quote_no), headers=headers,
                         data={"kind": "purchase_order", "lines": [line], "payeeName": "某人", "payeeType": "employee", "data": {"applicant": applicant}})
    assert r.status == 201, r.text()
    eid, doc = r.json()["id"], r.json()["docCode"]
    s = ctx.request.post("%s/api/quotations/%s/extra-expenses/%s/submit" % (base, quote_no, eid), headers=headers)
    assert s.status == 200, s.text()
    if prev is not None:
        _set_setting("unified_approval_flow", prev)          # 還原呼叫端原本的簽核流程（這張採購單已核准，不受影響）
    return eid, doc
