"""一次性內容同步腳本（第二批）：把 2026-08-09 這輪「每個品牌都要有完整深度」擴充
（netarch_guide 大量新增/修正、monitor_guide 新增 Hikvision、access_guide 新增 Akuvox）
同步到正式機。原因同 `sync_2026-08-09_unifi_content.py` 檔頭說明——這批內容是透過 API
直接寫進開發機 `motrix_erp.db`，不是改 seed 檔，不會隨部署包自動出現在正式機。

冪等：`netarch_products` 用 (family_code, gen_name, brand, model) 比對是否已存在（不用
生成的 `generation_id` 數字，避免兩台機器 migration 插入順序若有差異導致 id 對不上）；
`monitor_products`／`access_products` 用 (category_code, brand, model) 比對，可重複執行。

用法（於正式機 backend/ 目錄下執行，`apply_update.ps1` 套用完成之後，
建議接在 `sync_2026-08-09_unifi_content.py` 之後執行）：
    python sync_2026-08-09b_brand_depth.py

詳見 NETARCH-GUIDE-CONTENT.md §5「2026-08-09c」、MONITOR-GUIDE-CONTENT.md §5「2026-08-09b」、
ACCESS-GUIDE-CONTENT.md §5「2026-08-09b」條目。
"""
import json
import sqlite3

DB_PATH = "motrix_erp.db"

# (family_code, gen_name, brand, model, url, label, price_note) — 新增
NETARCH_NEW = [
    ("CELLULAR", "5G Sub-6", "Peplink", "MAX BR2 Pro 5G",
     "https://www.peplink.com/products/mobile-routers/max-br2-pro/", "",
     "US$2,899（Westward Sales 經銷商報價，2026-08 查價；官網未列牌價）"),
    ("CELLULAR", "4G LTE", "Peplink", "MAX Transit Duo Pro",
     "https://www.peplink.com/products/mobile-routers/max-transit-duo-pro/", "",
     "US$1,199（Westward Sales 經銷商報價，2026-08 查價；官網未列牌價）"),
    ("WIFI", "Wi-Fi 6", "Omada", "EAP670",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-ceiling-mount/eap670/", "",
     "US$155~170（2026-08 查價，Amazon/Newegg/CDW 零售區間，非公開官方牌價）"),
    ("WIFI", "Wi-Fi 6", "Omada", "EAP650",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-ceiling-mount/eap650/",
     "入門款，與 EAP670 形成價格帶區隔", "US$89.99~121.99（2026-08 查價，CDW/Amazon 零售區間）"),
    ("WIFI", "Wi-Fi 7", "Omada", "EAP787",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-ceiling-mount/eap787/", "",
     "US$249.99（2026 官方建議售價 SRP，另 2026-08 零售查價約 US$230~280）"),
    ("WIFI", "Wi-Fi 7", "Omada", "EAP775-Wall",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-wall-plate/eap775-wall/",
     "牆面插座型，適合會議室/客房情境", "約US$250~280（2026-08 查價，歐美零售區間，找不到單一官方公開牌價）"),
    ("CELLULAR", "4G LTE", "Netgear", "Nighthawk AX4 (LAX20)",
     "https://www.netgear.com/mobile-wifi/routers/lax20/", "",
     "US$170~200（2026-08 查價；Micro Center US$199.99）"),
    ("WIFI", "Wi-Fi 6E", "Netgear", "Orbi RBRE960",
     "https://www.netgear.com/home/wifi/mesh/rbre960/", "可擴充 Mesh 系統",
     "US$600~700（2026-08 查價；Dell 官方通路 US$599.99）"),
    ("WIFI", "Wi-Fi 6", "Ruckus", "R350",
     "https://www.ruckusnetworks.com/products/wireless-access-points/r350/", "",
     "US$495~695（2026-08 查價，型號 901-R350-US02）"),
    ("WIFI", "Wi-Fi 6E", "Ruckus", "R560",
     "https://www.ruckusnetworks.com/products/wireless-access-points/r560/", "內建 BLE/Zigbee IoT",
     "US$843~1,755（2026-08 查價，型號 901-R560-US00，代理商折扣差異大）"),
    ("WIFI", "Wi-Fi 7", "Ruckus", "R770",
     "https://www.ruckusnetworks.com/products/wireless-access-points/r770/", "",
     "US$2,500~3,103（2026-08 查價，型號 901-R770-US00）"),
    ("CELLULAR", "4G LTE", "Teltonika", "RUT200",
     "https://www.teltonika-networks.com/products/routers/rut200", "",
     "US$102.60~114.94（2026-08 查價）"),
    ("CELLULAR", "5G Sub-6", "Teltonika", "RUTM50",
     "https://www.teltonika-networks.com/products/routers/rutm50", "",
     "US$499~599（2026-08 查價，促銷價/牌價依代理商而異）"),
    ("CELLULAR", "5G Sub-6", "Askey", "RTL0310",
     "https://www.askey.com/products-detail/rtl0310/", "5G NR CPE",
     "US$999（4gltemall 代理商通路報價，2026-08 查價；官網未公開牌價，屬電信客製化產品）"),
    ("CELLULAR", "4G LTE", "Askey", "RTL0120",
     "https://www.askey.com/products-detail/rtl0120/", "4G/LTE CPE Pro",
     "洽詢報價（電信通路/客製化產品，無公開零售牌價）"),
    ("CELLULAR", "5G Sub-6", "Inseego", "5G MiFi M2000",
     "https://inseego.com/company/press-releases/introducing-inseego-5g-mifir-m2000-mobile-hotspot-global-markets/", "",
     "US$89.5~129.99（Walmart/Newegg 等通路，2026-08 查價；電信通路裝置，無統一官方牌價）"),
    ("CELLULAR", "4G LTE", "ZTE", "MF283",
     "https://www.4gltemall.com/zte-mf283-4g-lte-wireless-gateway.html",
     "規格資料來源為經銷商，非 ZTE 官方公開牌價", "US$189（特價，原價 US$369，2026-08 查價）"),
    ("CELLULAR", "5G mmWave", "ZTE", "MC889",
     "https://www.4gltemall.com/zte-mc889.html",
     "戶外壁掛/桿裝型，PoE 供電，IP65；規格資料來源為經銷商", "US$799（2026-08 查價）"),
    ("CELLULAR", "4G LTE", "Cisco", "ISR1100-4GLTENA",
     "https://www.cisco.com/c/en/us/products/collateral/routers/1000-series-integrated-services-routers-isr/datasheet-c78-742893.html",
     "辦公室/分公司桌上型定位，與既有 IR1101 工業型形成對比",
     "US$1,000~2,000（2026-08 查價，多家經銷商報價，未見統一公開牌價）"),
    ("CELLULAR", "5G Sub-6", "Cisco", "IR8140H-P-K9",
     "https://www.cisco.com/c/en/us/products/collateral/routers/catalyst-ir8100-heavy-duty-series-routers/nb-06-cat-ir8140-hd-ser-rout-ds-cte-en.html",
     "工業戶外機型，需另加購 P-5GS6-GL 5G 插拔模組",
     "主機 US$1,400~2,500＋模組 US$700~1,600（2026-08 查價，兩者須合購才具 5G 能力）"),
    ("WIFI", "Wi-Fi 6", "Cisco Meraki", "MR46",
     "https://meraki.cisco.com/product/wi-fi/indoor-access-points/mr46/", "規格較既有 MR36 高一階",
     "US$1,300~1,700（2026-08 查價，價格浮動大；訂閱制雲端授權另計）"),
    ("WIFI", "Wi-Fi 6E", "Cisco Meraki", "Catalyst CW9162I-MR",
     "https://www.cdw.com/product/cisco-meraki-catalyst-9162-wireless-access-point-wi-fi-6e-cloud-manag/7175629",
     "可雙模由 Meraki 雲端或 Catalyst 9800 WLC 管理，規格較既有 MR57 低一階",
     "US$1,655（2026-08 查價，未含訂閱授權）"),
    ("WIFI", "Wi-Fi 7", "Cisco Meraki", "CW9176I",
     "https://www.cisco.com/site/us/en/products/networking/wireless/access-points/meraki-access-points/cw9176i.html",
     "規格較既有旗艦 CW9178I 低一階，仍高於入門機型",
     "洽詢報價（2026-08 查價，英國經銷商約合 US$1,400~1,500，美國多家僅提供詢價；訂閱制雲端授權另計）"),
    ("WIFI", "Wi-Fi 6", "Omada", "EAP610",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-ceiling-mount/eap610/",
     "入門級 AX1800 吸頂", "US$89.99~114.98（2026-08 查價）"),
    ("WIFI", "Wi-Fi 6", "Omada", "EAP613",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-ceiling-mount/eap613/",
     "超薄型 AX1800 吸頂", "US$87.99~104.52（2026-08 查價）"),
    ("WIFI", "Wi-Fi 6", "Omada", "EAP620 HD",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-ceiling-mount/eap620-hd/",
     "高密度部署 AX1800 吸頂", "US$124.99（2026-08 查價）"),
    ("WIFI", "Wi-Fi 6", "Omada", "EAP660 HD",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-ceiling-mount/eap660-hd/",
     "高密度部署 AX3600 吸頂", "US$179.99~224.93（2026-08 查價）"),
    ("WIFI", "Wi-Fi 6", "Omada", "EAP683 UR",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-ceiling-mount/eap683-ur/",
     "超廣覆蓋(Ultra-Range) AX6000 吸頂旗艦", "US$235.99（2026-08 查價）"),
    ("WIFI", "Wi-Fi 6", "Omada", "EAP615-Wall",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-wall-plate/eap615-wall/",
     "AX1800 客房/辦公室牆插型", "US$98.49~106.59（2026-08 查價）"),
    ("WIFI", "Wi-Fi 6", "Omada", "EAP655-Wall",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-wall-plate/eap655-wall/",
     "中高階 AX3000 牆插型", "US$134.99（2026-08 查價）"),
    ("WIFI", "Wi-Fi 6", "Omada", "EAP610-Outdoor",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-outdoor/eap610-outdoor/",
     "入門級 AX1800 室內外兩用", "US$129.00~148.05（2026-08 查價）"),
    ("WIFI", "Wi-Fi 6", "Omada", "EAP625-Outdoor HD",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-outdoor/eap625-outdoor-hd/",
     "高密度部署 AX1800 戶外型", "US$173.08~215.26（2026-08 查價）"),
    ("WIFI", "Wi-Fi 6", "Omada", "EAP650-Outdoor",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-outdoor/eap650-outdoor/",
     "中高階 AX3000 室內外兩用", "US$261.99（2026-08 查價）"),
]

# (brand, model, new_price_note, new_url_or_None) — netarch_products 既有筆的價格/網址修正
NETARCH_FIXES = [
    ("Peplink", "MAX BR1 Pro 5G",
     "US$999（Westward Sales／888VoIP／RV Mobile Internet 等多方經銷商一致標價，2026-08 查價；官網未列牌價）",
     None),
    ("Netgear", "Nighthawk M6 Pro",
     "US$900~1000（2026-08 查價；官方上市價/多家評測 US$999.99，Best Buy 現貨 US$899.99）",
     "https://www.netgear.com/mobile-wifi/hotspots/mr6550/"),
]

# [category_code, brand, model, url, label, price_note, specs]
MONITOR_NEW = [
    ("BULLET", "Hikvision", "DS-2CD2T47G2-LSU/SL(4mm)",
     "https://www.a1securitycameras.com/hikvision-ds-2cd2t47g2-lsu-sl-4mm-colorvu-4mp-strobe-light-and-audible-warning-bullet-ip-security-camera-4mm-fixed-lens-white.html",
     "", "US$283.54（2026-08 查價，特價，原價 US$330.00）",
     [["解析度", "4MP (2688×1520)"], ["鏡頭", "4mm 定焦"], ["白光補光距離", "約40m（ColorVu 全彩夜視，非紅外線）"],
      ["防護等級", "IP67"], ["AI 偵測", "AcuSense 人形／車輛偵測，過濾誤報"],
      ["其他", "主動聲光警戒（閃光燈+警報聲），內建麥克風，需搭配 Hikvision NVR/主機錄影"]]),
    ("DOME", "Hikvision", "DS-2CD2147G2-LSU(2.8mm)",
     "https://www.a1securitycameras.com/hikvision-ds-2cd2147g2-lsu-4mp-outdoor-dome-ip-security-camera-with-built-in-microphone-colorvu.html",
     "", "US$281.83（2026-08 查價）",
     [["解析度", "4MP (2688×1520)"], ["鏡頭", "2.8mm 定焦，112° 水平視角"], ["白光補光距離", "約30m"],
      ["防護等級", "IP67＋IK10 防暴"], ["AI 偵測", "AcuSense 深度學習人形／車輛偵測"],
      ["其他", "130dB WDR，內建麥克風，需搭配 Hikvision NVR/主機錄影"]]),
    ("TURRET", "Hikvision", "DS-2CD2347G2-LU(4mm)",
     "https://networkcamerastore.com/products/hikvision-ds-2cd2347g2-lu-4mm-ottr4mm4mp-24hr-7color-mic",
     "", "US$301.03（2026-08 查價，特價，原價 US$376.00）",
     [["解析度", "4MP (2688×1520)"], ["鏡頭", "4mm 定焦，F1.0 大光圈"],
      ["白光補光距離", "約40m，最低照度 0.0005 Lux（免紅外線全彩）"], ["防護等級", "IP67"],
      ["AI 偵測", "AcuSense 人形／車輛分類偵測"], ["其他", "內建麥克風，需搭配 Hikvision NVR/主機錄影"]]),
    ("PTZ", "Hikvision", "DS-2DE4425IW-DE",
     "https://www.a1securitycameras.com/hikvision-ds-2de4425iw-de-4mp-night-vision-outdoor-ptz-ip-security-camera-25x-optical-zoom.html",
     "", "US$578.55（2026-08 查價，特價，原價 US$870.00）",
     [["解析度", "4MP (2560×1440)"], ["變焦", "25倍光學變焦（4.8-120mm）＋16倍數位變焦"],
      ["紅外線補光距離", "100m"], ["防護等級", "IP66，工作溫度 -30~65°C"],
      ["AI 偵測", "AcuSense 人形／車輛分類偵測"], ["其他", "360° 連續旋轉雲台，需搭配 Hikvision NVR/主機錄影"]]),
    ("PANORAMIC", "Hikvision", "DS-2CD6365G0E-IVS(1.27mm)",
     "https://www.surveillance-video.com/camera-ds-2cd6365g0e-ivs-1-27mm.html",
     "可切換 180°壁掛/360°天花板/桌面 三種安裝模式", "US$479.50（2026-08 查價，特價，原價 US$562.35）",
     [["解析度", "6MP (3072×2048)"], ["鏡頭", "1.27mm 魚眼，360° 全景"], ["紅外線補光距離", "15m"],
      ["防護等級", "IP66＋IK10"], ["AI 偵測", "行為分析／異常偵測（DeepinView）"],
      ["其他", "內建加熱器，工作溫度 -40~60°C，需搭配 Hikvision NVR/主機錄影"]]),
]

# [category_code, brand, model, url, label, price_note, specs]
ACCESS_NEW = [
    ("ALLINONE_HUB", "Akuvox", "A02", "https://akuvoxdealer.com/products/copy-of-akuvox-a02",
     "IP Access Control Terminal", "US$475.00（2026-08 查價）",
     [["型態", "讀頭＋控制器合一"], ["供電", "802.3af PoE 單一網路埠"],
      ["讀卡方式", "125kHz EM／13.56MHz RFID／NFC／PIN 密碼鍵盤"], ["適用門數", "1 門"],
      ["其他", "IP65 防水，需自備電鎖與繼電器；可選配 Akuvox SmartPlus 雲端平台"]]),
    ("MULTI_DOOR_HUB", "Akuvox", "A095", "https://akuvoxdealer.com/products/akuvox-a095",
     "4-Door Access Controller，本身不含讀頭需外接", "US$1,155.00（2026-08 查價）",
     [["適用門數", "4 門"], ["供電", "PoE+（802.3at），可直接供電電鎖"],
      ["連線", "Ethernet(PoE+)／Wi-Fi 6／選配 LTE"], ["讀頭介面", "OSDP 2.0／Wiegand／RS485（需另購讀頭）"],
      ["其他", "支援多門互鎖、反潛回"]]),
    ("READER", "Akuvox", "ACR-CRM11", "https://akuvoxdealer.com/products/akuvox-acr-crm11",
     "Slim RFID Access Control Reader w/ Keypad", "US$149.00（2026-08 查價）",
     [["型態", "獨立讀頭，需搭配控制器（如 A095 或第三方 Wiegand 控制器）"],
      ["供電", "12V DC／200mA 外接電源（非 PoE）"], ["讀卡方式", "125kHz＋13.56MHz RFID／內建數字鍵盤 PIN"],
      ["輸出介面", "Wiegand 26／34"], ["其他", "鋁合金金屬機身，IP65 防水"]]),
]


def sync_netarch(conn):
    added, skipped, updated = 0, 0, 0
    for family_code, gen_name, brand, model, url, label, price_note in NETARCH_NEW:
        gen = conn.execute(
            "SELECT id FROM netarch_generations WHERE family_code=? AND gen_name=?",
            (family_code, gen_name),
        ).fetchone()
        if not gen:
            print(f"  ⚠ 找不到世代 {family_code}/{gen_name}，略過 {brand} {model}")
            continue
        exists = conn.execute(
            "SELECT 1 FROM netarch_products WHERE generation_id=? AND brand=? AND model=?",
            (gen["id"], brand, model),
        ).fetchone()
        if exists:
            skipped += 1
            continue
        max_sort = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) AS m FROM netarch_products WHERE generation_id=?",
            (gen["id"],),
        ).fetchone()["m"]
        conn.execute(
            "INSERT INTO netarch_products (generation_id, brand, model, url, label, price_note, sort_order) "
            "VALUES (?,?,?,?,?,?,?)",
            (gen["id"], brand, model, url, label, price_note, max_sort + 1),
        )
        added += 1
    for brand, model, new_price_note, new_url in NETARCH_FIXES:
        row = conn.execute(
            "SELECT id, price_note, url FROM netarch_products WHERE brand=? AND model=?", (brand, model)
        ).fetchone()
        if not row:
            print(f"  ⚠ netarch_products 找不到 {brand} {model}，略過修正")
            continue
        target_url = new_url if new_url else row["url"]
        if row["price_note"] == new_price_note and row["url"] == target_url:
            skipped += 1
            continue
        conn.execute("UPDATE netarch_products SET price_note=?, url=? WHERE id=?", (new_price_note, target_url, row["id"]))
        updated += 1
    conn.commit()
    print(f"netarch_products：新增 {added} 筆，更新 {updated} 筆，略過 {skipped} 筆")


def sync_monitor(conn):
    added, skipped = 0, 0
    for category_code, brand, model, url, label, price_note, specs in MONITOR_NEW:
        exists = conn.execute(
            "SELECT 1 FROM monitor_products WHERE category_code=? AND brand=? AND model=?",
            (category_code, brand, model),
        ).fetchone()
        if exists:
            skipped += 1
            continue
        max_sort = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) AS m FROM monitor_products WHERE category_code=?",
            (category_code,),
        ).fetchone()["m"]
        conn.execute(
            "INSERT INTO monitor_products (category_code, brand, model, url, label, price_note, specs_json, sort_order) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (category_code, brand, model, url, label, price_note, json.dumps(specs, ensure_ascii=False), max_sort + 1),
        )
        added += 1
    conn.commit()
    print(f"monitor_products：新增 {added} 筆，略過 {skipped} 筆")


def sync_access(conn):
    added, skipped = 0, 0
    for category_code, brand, model, url, label, price_note, specs in ACCESS_NEW:
        exists = conn.execute(
            "SELECT 1 FROM access_products WHERE category_code=? AND brand=? AND model=?",
            (category_code, brand, model),
        ).fetchone()
        if exists:
            skipped += 1
            continue
        max_sort = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) AS m FROM access_products WHERE category_code=?",
            (category_code,),
        ).fetchone()["m"]
        conn.execute(
            "INSERT INTO access_products (category_code, brand, model, url, label, price_note, specs_json, sort_order) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (category_code, brand, model, url, label, price_note, json.dumps(specs, ensure_ascii=False), max_sort + 1),
        )
        added += 1
    conn.commit()
    print(f"access_products：新增 {added} 筆，略過 {skipped} 筆")


def main():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    sync_netarch(con)
    sync_monitor(con)
    sync_access(con)
    con.close()
    print("完成。")


if __name__ == "__main__":
    main()
