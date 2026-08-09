"""一次性內容同步腳本（第三批）：Omada 官網完整品項總表掃描新增的 17 款
（Wi-Fi 6 補 8 款、Wi-Fi 7 補 9 款）同步到正式機。原因同
`sync_2026-08-09_unifi_content.py` 檔頭說明。

冪等：用 (family_code, gen_name, brand, model) 比對是否已存在，可重複執行。

用法（於正式機 backend/ 目錄下執行，`apply_update.ps1` 套用完成之後，
建議接在 `sync_2026-08-09b_brand_depth.py` 之後執行）：
    python sync_2026-08-09c_omada_full_sweep.py

詳見 NETARCH-GUIDE-CONTENT.md §5「2026-08-09e」條目。
"""
import sqlite3

DB_PATH = "motrix_erp.db"

# (family_code, gen_name, brand, model, url, label, price_note)
NETARCH_NEW = [
    ("WIFI", "Wi-Fi 6", "Omada", "EAP673",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-ceiling-mount/eap673/",
     "1500ft²/250+併發客戶端",
     "洽詢報價（官網未列牌價，同代 EAP670 零售價約 US$135 可供參考，2026-08 查價）"),
    ("WIFI", "Wi-Fi 6", "Omada", "EAP653",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-ceiling-mount/eap653/",
     "天花板/牆面/接線盒/T-Bar 多種安裝套件", "US$79.99（原價 US$114.99，2026-08 查價）"),
    ("WIFI", "Wi-Fi 6", "Omada", "EAP653 UR",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-ceiling-mount/eap653-ur/",
     "UR=Ultra Range 延伸覆蓋，最大2000ft²", "US$119.99~325.55（2026-08 查價，通路區間差異大）"),
    ("WIFI", "Wi-Fi 6", "Omada", "EAP650 D120-Outdoor",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-outdoor/eap650-d120-outdoor/",
     "戶外指向型天線，水平120°/垂直30°波束", "US$108.49~268.99（2026-08 查價）"),
    ("WIFI", "Wi-Fi 6", "Omada", "EAP650 D30-Outdoor",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-outdoor/eap650-d30-outdoor/",
     "4支內建雙頻高增益指向天線，適合倉儲場景", "MSRP約 US$262.99（2026-08 查價，單一通路引用）"),
    ("WIFI", "Wi-Fi 6", "Omada", "EAP603-Outdoor",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-outdoor/eap603-outdoor/",
     "IP65防水、6kV雷擊防護，-30~70°C，全向戶外覆蓋", "洽詢報價（官網未列牌價，2026-08 查價）"),
    ("WIFI", "Wi-Fi 6", "Omada", "EAP650-Desktop",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-desktop/eap650-desktop/",
     "桌上型/壁掛兩用，免安裝，適合零售/辦公/飯店", "US$129.99（2026-08 查價）"),
    ("WIFI", "Wi-Fi 6", "Omada", "EAP650GP-Desktop",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-gpon/eap650gp-desktop/",
     "GPON一體式桌上型AP，適合飯店客房/MDU",
     "洽詢報價（MSRP 約 US$175，海外通路換算，2026-08 查價，建議核實）"),
    ("WIFI", "Wi-Fi 7", "Omada", "EAP770",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-ceiling-mount/eap770/",
     "Omada 7 Pro，BE11000 天花板吸頂", "洽詢報價（官網未列牌價，2026-08 查價）"),
    ("WIFI", "Wi-Fi 7", "Omada", "EAP783",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-ceiling-mount/eap783/",
     "旗艦款BE22000天花板吸頂，企業級高密度部署，2x10G埠", "US$499.99~699.99（2026-08 查價）"),
    ("WIFI", "Wi-Fi 7", "Omada", "EAP727",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-ceiling-mount/eap727/",
     "Omada 7 UR，BE5000延伸覆蓋型天花板吸頂",
     "約 US$190~200（2026-08 查價，澳洲通路換算，建議以美國通路覆核）"),
    ("WIFI", "Wi-Fi 7", "Omada", "EAP723",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-ceiling-mount/eap723/",
     "Omada 7入門款，BE5000天花板吸頂，無6GHz頻段", "US$89.99~146.99（2026-08 查價，通路而異）"),
    ("WIFI", "Wi-Fi 7", "Omada", "EAP720",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-ceiling-mount/eap720/",
     "與EAP723同硬體規格，差異僅為隨附電源變壓器，屬獨立SKU", "US$195.21（2026-08 查價，Newegg）"),
    ("WIFI", "Wi-Fi 7", "Omada", "EAP725-Wall",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-wall-plate/eap725-wall/",
     "牆插型，適合飯店/宿舍/公寓單房部署", "US$139.99（2026-08 查價）"),
    ("WIFI", "Wi-Fi 7", "Omada", "EAP772-Outdoor",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-outdoor/eap772-outdoor/",
     "首款戶外Wi-Fi 7含6GHz頻段（AFC解鎖），IP68，300m²全向覆蓋", "US$249.99（2026-08 查價）"),
    ("WIFI", "Wi-Fi 7", "Omada", "EAP775-Outdoor",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-outdoor/eap775-outdoor/",
     "Omada 7 Pro Outdoor，可切換指向性/全向天線模式；官網顯示 Coming Soon 尚未上市",
     "洽詢報價（尚未上市，2026-08 查價）"),
    ("WIFI", "Wi-Fi 7", "Omada", "EAP725-Outdoor",
     "https://www.omadanetworks.com/us/business-networking/omada-wifi-outdoor/eap725-outdoor/",
     "Omada 7 Outdoor，IP66，可切換指向性/全向天線", "US$195.21~224.78（2026-08 查價）"),
]


def sync_netarch(conn):
    added, skipped = 0, 0
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
    conn.commit()
    print(f"netarch_products：新增 {added} 筆，略過 {skipped} 筆")


def main():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    sync_netarch(con)
    con.close()
    print("完成。")


if __name__ == "__main__":
    main()
