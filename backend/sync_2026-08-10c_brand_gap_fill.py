"""一次性內容同步腳本：把 2026-08-10 這批 Netgear／D-Link／Aruba／Peplink 交換器補齊
內容同步到正式機。

**背景**：這批型號原本記錄在 `SWITCH-BRAND-REFERENCE.md`（人工核對用參考清單，稍早另一次
對話查證）與 `switch_guide_patch_2026-08.py`（寫入腳本），2026-08-10 使用者確認後於開發機
執行過 `switch_guide_patch_2026-08.py`，直接寫入 `switch_products` 表（不是改
`switch_guide_seed.py`）。switch_guide 類別在正式機早已存在資料，migration 的種子載入邏輯
只在資料表全空時才會執行，故這批內容不會隨部署包自動出現在正式機，需要另外跑這支腳本補上。

冪等：用 (brand, model) 查重（跨分類比對，比照 `switch_guide_patch_2026-08.py` 原始腳本的
查重邏輯——該腳本只用 brand+model 判斷是否已存在，不看分類，因為同一型號理論上不該同時掛在
兩個分類下），已存在就跳過，可重複執行不會產生重複資料。清單裡的 TP-Link Omada SG3428／
S7500-24Y4C 兩筆，在開發機因為已被同日稍早的 Omada 全系列擴充以更完整的規格收錄在
OMADA_ACCESS／OMADA_CAMPUS 分類下，執行時會被跳過（brand+model 已存在，不論在哪個分類）。

用法（於正式機 backend/ 目錄下執行，apply_update.ps1 套用完成之後）：
    python sync_2026-08-10c_brand_gap_fill.py

詳見 SWITCH-GUIDE-CONTENT.md §5「2026-08-10c」條目。
"""
import json
import sqlite3

DB_PATH = "motrix_erp.db"

# [category_code, brand, model, url, label, price_note]
NEW_PRODUCTS = [
    # ---- 非網管 UNMANAGED ----
    ["UNMANAGED", "Netgear", "GS748PP", "https://www.netgear.com/business/wired/switches/",
     "Netgear GS748PP 官網系列頁（48埠／PoE+非網管）", "US$749.99（2026-08 官網查價）"],
    ["UNMANAGED", "Netgear", "GS105PP", "https://www.netgear.com/business/wired/switches/",
     "Netgear GS105PP 官網系列頁（5埠／PoE+非網管）", "US$114.99（2026-08 官網查價）"],
    ["UNMANAGED", "D-Link", "DES-1024A", "https://www.dlink.com/en/products/des-1024a-24-port-fast-ethernet-unmanaged-switch",
     "D-Link DES-1024A 原廠頁（24埠 Fast Ethernet 100M，非Gigabit，勿標錯速率）", "洽詢經銷商（2026-08 查證未列牌價）"],
    ["UNMANAGED", "D-Link", "DES-1016D", "https://www.dlink.com/en/products/des-1016d-16-port-fast-ethernet-unmanaged-switch",
     "D-Link DES-1016D 原廠頁（16埠 Fast Ethernet 100M，非Gigabit）", "洽詢經銷商（2026-08 查證未列牌價）"],
    ["UNMANAGED", "Aruba", "Instant On 1430 8G PoE (R8R46A)", "https://www.arubainstanton.com/products/switches/1430-series/",
     "Aruba Instant On 1430 系列原廠頁（8埠／Class4 PoE非網管）", "US$100~150（2026-08 查價，第三方通路約略區間）"],

    # ---- 簡易網管 / L2+ SMART_L2PLUS ----
    ["SMART_L2PLUS", "Netgear", "GS324TPv2", "https://www.netgear.com/business/wired/switches/",
     "Netgear GS324TPv2 官網系列頁（24埠 PoE+／2 SFP，Smart Managed）", "US$249.99（2026-08 官網查價）"],
    ["SMART_L2PLUS", "D-Link", "DGS-1210-26", "https://www.dlink.com/en/products/dgs-1210-26--26-port-gigabit-smart-managed-switch",
     "D-Link DGS-1210-26 原廠頁（26埠 Gigabit Smart Managed L2+）", "洽詢經銷商（2026-08 查證未列牌價）"],
    ["SMART_L2PLUS", "Aruba", "Instant On 1930 24G 4SFP+ 195W PoE (JL683A)", "https://www.arubainstanton.com/products/switches/1930-series/",
     "Aruba Instant On 1930 系列原廠頁（24埠／195W PoE／4 SFP+，L2+）", "US$400~550（2026-08 查價，第三方通路約略區間）"],
    ["SMART_L2PLUS", "TP-Link", "Omada SG3428", "https://www.omadanetworks.com/us/business-networking/all-omada-switch/",
     "TP-Link Omada Access 系列原廠頁（SG3428，24埠+4 SFP，L2+全網管）", "洽詢經銷商（2026-08 查證未列牌價）"],
    ["SMART_L2PLUS", "Peplink", "SD Switch 24-Port (PLS-24-H2G-410W)", "https://www.peplink.com/products/wifi-poe/switch-series/",
     "Peplink SD Switch 24埠原廠頁（PoE+ 410W，InControl2雲端管理L2）", "洽詢經銷商（2026-08 查證未列牌價）"],

    # ---- L3 全網管 / 核心 MANAGED_L3 ----
    ["MANAGED_L3", "Netgear", "M4300-12X12F (XSM4324S)", "https://www.netgear.com/support/product/m4300-12x12f",
     "Netgear M4300-12X12F 原廠頁（24埠10G，12x10GBASE-T+12xSFP+，L3可堆疊）", "洽詢經銷商（2026-08 查證未列牌價）"],
    ["MANAGED_L3", "Netgear", "M4500-48XF8C (XSM4556)", "https://www.netgear.com/business/wired/switches/fully-managed/m4500/",
     "Netgear M4500-48XF8C 原廠頁（48x10G/25G SFP28 + 8x100G QSFP28，Netgear最高階核心機種）", "洽詢經銷商（2026-08 查證未列牌價）"],
    ["MANAGED_L3", "D-Link", "DGS-1520-52MP", "https://shop.us.dlink.com/collections/enterprise-switches",
     "D-Link Enterprise 系列頁（DGS-1520-52MP，52埠／740W PoE，L3可堆疊，現行主力）", "洽詢經銷商（2026-08 查證未列牌價）"],
    ["MANAGED_L3", "TP-Link", "Omada S7500-24Y4C", "https://www.omadanetworks.com/us/business-networking/all-omada-switch/",
     "TP-Link Omada Campus 系列原廠頁（S7500-24Y4C，24x25G+4x100G，真正核心層，2Tbps）", "洽詢經銷商（2026-08 查證未列牌價）"],
]


def sync_products(conn):
    added, skipped = 0, 0
    existing = {(r["brand"], r["model"]) for r in conn.execute("SELECT brand, model FROM switch_products").fetchall()}
    for category_code, brand, model, url, label, price_note in NEW_PRODUCTS:
        if (brand, model) in existing:
            skipped += 1
            continue
        if not conn.execute("SELECT 1 FROM switch_categories WHERE code=?", (category_code,)).fetchone():
            print(f"  ⚠ switch_categories 找不到 {category_code}，略過 {brand} {model}")
            continue
        max_sort = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) AS m FROM switch_products WHERE category_code=?",
            (category_code,),
        ).fetchone()["m"]
        conn.execute(
            "INSERT INTO switch_products (category_code, brand, model, url, label, price_note, specs_json, sort_order) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (category_code, brand, model, url, label, price_note, json.dumps([], ensure_ascii=False), max_sort + 1),
        )
        added += 1
    conn.commit()
    print(f"switch_products：新增 {added} 筆，略過（已存在）{skipped} 筆")


def main():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    sync_products(con)
    con.close()
    print("完成。")


if __name__ == "__main__":
    main()
