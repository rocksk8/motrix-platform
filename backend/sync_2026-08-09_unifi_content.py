"""一次性內容同步腳本：把 2026-08-09 這批在開發機用 API 直接寫入的 UniFi 選型資料庫內容
（交換器選型導覽新增 5 款產品、網路架構選型導覽校正 1 筆價格備註）同步到正式機。

**背景**：這批內容是透過 `/api/switch-guide/*`／`/api/netarch-guide/*` 直接寫進開發機
`motrix_erp.db`，不是改 seed 檔——`switch_guide`／`netarch_guide` 這兩個類別在正式機早已
存在資料，migration 的種子載入邏輯只在資料表全空時才會執行，所以這批內容**不會**隨著這次
部署包（`apply_update.ps1`）自動出現在正式機，需要另外跑這支腳本補上。（相對地，本次新增的
「監控系統」「門禁系統」兩個全新類別，第一批資料是包在 migration/seed.py 裡，部署時會自動
灌入，不受此限。）

冪等：所有寫入前都先比對 `brand`+`model`（或 `netarch_products.id` 對應的 `brand`+`model`）
是否已存在，已存在就跳過，可重複執行不會產生重複資料。

用法（於正式機 backend/ 目錄下執行，`apply_update.ps1` 套用完成之後）：
    python sync_2026-08-09_unifi_content.py

詳見 SWITCH-GUIDE-CONTENT.md §5「2026-08-09b」與 NETARCH-GUIDE-CONTENT.md §5「2026-08-09」條目。
"""
import json
import sqlite3

DB_PATH = "motrix_erp.db"

# [category_code, brand, model, url, label, price_note, specs]
SWITCH_PRODUCTS = [
    ("MANAGED_L3", "UniFi", "Pro 24 PoE",
     "https://techspecs.ui.com/unifi/switching/usw-pro-24-poe", "",
     "US$699（2026-08 查價）",
     [["埠數", "24× GbE（16× 802.3at PoE+ ＋ 8× 802.3bt PoE++）＋ 2× 10G SFP+"],
      ["PoE 埠數／預算", "24 埠，總 400W"],
      ["交換容量", "88 Gbps（Non-blocking 44 Gbps）"],
      ["轉發速率", "65 Mpps"],
      ["管理層級", "完整 L3（DHCP Server／Relay、Inter-VLAN Routing）"],
      ["備註", "UniFi OS／Network App 統一管理，跟 Aruba／Cisco／HPE 各自獨立管理平台不同，適合已用 UniFi 全線設備的案場"]]),
    ("MANAGED_L3", "UniFi", "Enterprise 48 PoE",
     "https://techspecs.ui.com/unifi/switching/usw-enterprise-48-poe", "",
     "US$1,599（2026-08 查價，官網 techspecs 已標記 Vintage，下單前建議先向代理商核實現貨/是否已有後續機種）",
     [["埠數", "48× 2.5GbE ＋ 4× 10G SFP+"],
      ["PoE 埠數／預算", "48 埠 802.3at PoE+，總 720W"],
      ["交換容量", "320 Gbps"],
      ["轉發速率", "238.09 Mpps"],
      ["管理層級", "完整 L3"],
      ["備註", "內建 1.3吋 LCM 觸控螢幕顯示系統/連線狀態；同分類目前唯一大埠數（48埠）且 PoE 預算最高（720W）的選項，適合中大型機房主幹"]]),
    ("SMART_L2PLUS", "UniFi", "Flex 2.5G 8 PoE",
     "https://techspecs.ui.com/unifi/switching/usw-flex-2-5g-8-poe", "",
     "US$199（2026-08 查價，PSU 另購約 US$79，實際部署成本約 US$278）",
     [["埠數", "8× 2.5GbE PoE++ ＋ 1× 10GbE RJ45/SFP+ combo 上行"],
      ["供電方式", "PoE+++ 供電或另購 AC 電源轉接器"],
      ["管理層級", "簡易網管，UniFi Network App 管理"],
      ["備註", "體積小巧可壁掛/桌上型部署，適合小空間但需要 2.5GbE 高速上行的情境"]]),
    ("SMART_L2PLUS", "UniFi", "24 PoE",
     "https://techspecs.ui.com/unifi/switching/usw-24-poe", "",
     "US$488（2026-08 查價）",
     [["埠數", "24× GbE（16× 802.3at PoE+）＋ 2× SFP"],
      ["PoE 埠數／預算", "16 埠，總 95W"],
      ["交換容量", "52 Gbps（Non-blocking 26 Gbps）"],
      ["轉發速率", "38.69 Mpps"],
      ["管理層級", "L2 簡易網管，UniFi Network App 管理"],
      ["備註", "靜音無風扇設計，內建 1.3吋 LCM 觸控螢幕；同分類目前埠數最多的 UniFi 選項，適合埠數需求大但不到 L3 規格的情境"]]),
    ("MANAGED_L3", "UniFi", "Pro Max 24 PoE",
     "https://techspecs.ui.com/unifi/switching/usw-pro-max-24-poe", "",
     "US$799~1,136（2026-08 查價，第三方通路區間，官網未列牌價）",
     [["埠數", "16× PoE++ RJ45 ＋ 8× PoE+ RJ45 ＋ 8× 2.5GbE PoE++ RJ45 ＋ 2× 10G SFP+ 上行（共 24 埠）"],
      ["PoE 埠數／預算", "總 400W，PoE++ 埠最高 64W／埠"],
      ["交換容量", "112 Gbps（Non-blocking 56 Gbps）"],
      ["轉發速率", "83 Mpps"],
      ["管理層級", "完整 L3（DHCP Server／Relay、Inter-VLAN Routing、靜態 IPv4 路由）"],
      ["備註", "Pro 24 PoE 的新一代升級款，PoE 預算與埠數混合規格（PoE+++/PoE+/2.5GbE 三種埠型）更豐富，適合需要更高 PoE 供電密度的案場"]]),
]

# (brand, model, new_price_note) — netarch_products，用 brand+model 比對，不依賴 id
NETARCH_PRICE_FIXES = [
    ("UniFi", "U6-Pro", "US$159（2026-08 查價，第三方通路約略區間，官網未列牌價，區間約 US$159~209）"),
]


def sync_switch_products(conn):
    added, skipped = 0, 0
    for category_code, brand, model, url, label, price_note, specs in SWITCH_PRODUCTS:
        exists = conn.execute(
            "SELECT 1 FROM switch_products WHERE category_code=? AND brand=? AND model=?",
            (category_code, brand, model),
        ).fetchone()
        if exists:
            skipped += 1
            continue
        max_sort = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) AS m FROM switch_products WHERE category_code=?",
            (category_code,),
        ).fetchone()["m"]
        conn.execute(
            "INSERT INTO switch_products (category_code, brand, model, url, label, price_note, specs_json, sort_order) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (category_code, brand, model, url, label, price_note, json.dumps(specs, ensure_ascii=False), max_sort + 1),
        )
        added += 1
    conn.commit()
    print(f"switch_products：新增 {added} 筆，略過（已存在）{skipped} 筆")


def sync_netarch_prices(conn):
    updated, skipped = 0, 0
    for brand, model, new_price_note in NETARCH_PRICE_FIXES:
        row = conn.execute(
            "SELECT id, price_note FROM netarch_products WHERE brand=? AND model=?", (brand, model)
        ).fetchone()
        if not row:
            print(f"  ⚠ netarch_products 找不到 {brand} {model}，略過（可能型號已改版，請人工確認）")
            continue
        if row["price_note"] == new_price_note:
            skipped += 1
            continue
        conn.execute("UPDATE netarch_products SET price_note=? WHERE id=?", (new_price_note, row["id"]))
        updated += 1
    conn.commit()
    print(f"netarch_products：更新 {updated} 筆，略過（內容已相同）{skipped} 筆")


def main():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    sync_switch_products(con)
    sync_netarch_prices(con)
    con.close()
    print("完成。")


if __name__ == "__main__":
    main()
