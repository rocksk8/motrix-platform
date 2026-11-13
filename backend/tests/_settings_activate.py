# -*- coding: utf-8 -*-
"""測試用：把設定中心的待生效變更「立刻生效」（模擬：第二位最高管理者核准＋確認期間已過）。

S5 起，獎金傳票科目／法規參數／T100 匯出科目／管銷口徑的舊端點改走 `settings_registry.publish()`——任何實質變更都是待生效。
舊測試「PUT 之後立刻讀」改成 PUT → `activate_now()` → 讀。**只給測試用**（正式程式沒有這條捷徑）。
"""


def activate_now(group=None, now="2099-12-31T00:00:00"):
    """補齊雙人核准票數、再把到期的待生效寫進定義版本與舊儲存。`group`＝只處理這個群組（None＝全部）。回處理的明細列數。"""
    import db
    from helpers import config_ledger as L
    from helpers import settings_registry as R
    conn = db.get_db()
    try:
        for r in L.pending(conn):
            if not str(r["domain"]).startswith("setting:") or (group and r["key"] != group):
                continue
            need = int(r.get("approvals_required") or 0) - len(r.get("approvals") or [])
            for i in range(max(0, need)):
                L.approve(conn, r["id"], "s5-test-approver-%d" % i)
        conn.commit()
        n = R.materialize_due(conn, now=now)
        conn.commit()
    finally:
        conn.close()
    R.invalidate()
    return n


def set_tax_versions(versions):
    """測試用：取代舊的 `legal_params.save_versions`——發布 `tax_rules` 並立刻生效。"""
    from helpers import settings_registry as R
    R.publish("tax_rules", {"versions": versions}, user="s5-test", reason="測試設定法規參數")
    activate_now("tax_rules")
