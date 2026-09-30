# -*- coding: utf-8 -*-
"""`gl.source_status` 提供者（IP-106 暫定號）：這筆來源在總帳是否已入帳（MONEY-FLOWS §9 L3）。

給各來源模組的寫入端點用——使用者改動**已入帳**的來源前／後，回應帶一句非阻擋的提示
（「已入帳：修改會在下次總帳引擎執行時產生沖轉草稿」）。只讀、不寫、不 commit。

`fn(conn, source_type, source_key, prefix=False) -> [{event_code, status, voucher_no, event_date}]`
狀態只回 `posted`（已過帳）與 `drift`（來源已變、舊傳票仍在）；草稿（`drafted`）不算入帳——草稿改了引擎會自動重建。
`prefix=True`：`source_key` 當前綴比對（例：案件的所有收款事件 `MQ-…::`）。表不存在／查詢失敗 ⇒ `[]`（沒有總帳＝沒有可提示的）。"""


def source_status(conn, source_type, source_key, prefix=False):
    try:
        if prefix:
            key_cond, arg = "e.source_key LIKE ? ESCAPE '\\'", str(source_key).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        else:
            key_cond, arg = "e.source_key = ?", str(source_key)
        rows = conn.execute(
            "SELECT e.event_code, e.status, e.event_date, v.voucher_no FROM gl_source_events e "
            "LEFT JOIN vouchers_all v ON v.id = e.voucher_id "
            "WHERE e.source_type = ? AND " + key_cond + " AND e.status IN ('posted', 'drift') ORDER BY e.id",
            (source_type, arg)).fetchall()
    except Exception:                                        # noqa: BLE001 — 沒有總帳表（模組剛裝／舊庫）⇒ 沒有可提示的
        return []
    return [{"event_code": r["event_code"], "status": r["status"], "voucher_no": r["voucher_no"] or "",
             "event_date": r["event_date"]} for r in rows]
