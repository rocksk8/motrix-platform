# -*- coding: utf-8 -*-
"""總帳功能旗標：未完成的功能先註冊、以旗標關閉；完成一批就開一項，不必再動選單或全域設定。

「總帳作業」頁（ledger-hub.html）只顯示已開啟的功能頁籤；旗標存在 gl_settings（key＝feature.<名稱>），預設全部關閉。
超級管理者才能開關（開關是上線動作）。頁籤內容由 accounting 模組自己的前端提供，之後各批只改 accounting 的程式與 JS。
"""

#: 功能鍵 → (名稱, 對應批次, 說明)。順序＝頁籤順序。
FEATURES = {
    "engine_drafts": ("分錄草稿", "C1", "各來源模組的自動分錄草稿：檢視、整批確認、過帳"),
    "withholding": ("扣繳與補充保費", "C3", "勞報單／獎金的代扣稅款與二代健保：應繳未繳、繳庫紀錄"),
    "inventory_cost": ("存貨成本", "C4", "移動加權平均、存貨異動明細與對帳、呆滯清單"),
    "tax401": ("營業稅 401", "C5", "銷項／進項彙總、對帳、雙月稅額結轉"),
    "fixed_assets": ("固定資產", "C6", "資產卡、直線折舊（管理／稅務）、處分、折舊表"),
    "invoice_adjustments": ("發票折讓／作廢", "C7", "銷貨折讓與退回、發票作廢、折讓證明單"),
    "custom_records": ("自訂模組入帳", "C7", "建構器自訂單據的入帳對應與反轉"),
    "backfill": ("補登多年", "C8", "過往年度補登、歷史草稿補產、期初核對"),
    "source_annotations": ("來源憑證補登", "C1", "會計補登進項稅額實際值、發票種類、保固旗標等來源資料"),
}
_PREFIX = "feature."


def flags(conn):
    """回 `{鍵: bool}`（沒有紀錄＝關）。"""
    on = {r[0][len(_PREFIX):]: r[1] == "1" for r in conn.execute("SELECT key, value FROM gl_settings WHERE key LIKE 'feature.%'")}
    return {k: bool(on.get(k)) for k in FEATURES}


def set_flag(conn, key, enabled):
    if key not in FEATURES:
        raise KeyError(key)
    conn.execute("INSERT INTO gl_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (_PREFIX + key, "1" if enabled else "0"))


def listing(conn):
    f = flags(conn)
    return [{"key": k, "label": v[0], "batch": v[1], "description": v[2], "enabled": f[k]} for k, v in FEATURES.items()]
