"""一次性內容同步腳本：把 2026-08-10 這批 SOYAL 門禁產品同步到正式機。

**背景**：門禁系統選型導覽（access_guide）原本只有 UniFi／Akuvox 兩品牌，使用者要求補上
SOYAL（台灣廠商，soyal.com.tw）。委派 background subagent 深度研究其官網（傳統多層 PHP
型錄，逐一點入產品詳細頁確認非停產型號），新增 READER/ALLINONE_HUB/MULTI_DOOR_HUB 三個
既有分類的 SOYAL 型號，並新建 ACCESSORY 分類（電子鎖/按鈕/電源/卡片/網卡模組等週邊配件，
與既有 4 分類「門禁決策主體」選型邏輯不同，詳見 ACCESS-GUIDE-CONTENT.md §1）。

這批內容是透過 /api/access-guide/* 直接寫進開發機 motrix_erp.db（不是改 access_guide_seed.py），
access_guide 類別在正式機早已存在資料，migration 的種子載入邏輯只在資料表全空時才會執行，
故這批內容不會隨部署包自動出現在正式機，需要另外跑這支腳本補上。

冪等：
  - access_categories 用 code 比對，已存在就跳過
  - access_fit 用 (scenario_code, category_code) 比對，已存在就跳過
  - access_products 用 (category_code, brand, model) 比對，已存在就跳過
可重複執行不會產生重複資料。

用法（於正式機 backend/ 目錄下執行，apply_update.ps1 套用完成之後）：
    python sync_2026-08-10_soyal_access.py

詳見 ACCESS-GUIDE-CONTENT.md §5「2026-08-10」條目。
"""
import json
import sqlite3

DB_PATH = "motrix_erp.db"

CATEGORY = dict(code='ACCESSORY', name='門禁配件（鎖具／按鈕／電源／卡片／網卡模組）', keySpecs='涵蓋電子鎖（陽極鎖/磁力鎖）、開門按鈕、開關電源供應器、感應卡片、控制器專用網卡/PoE模組等週邊配件，依子類型規格差異大', tags='配件耗材,鎖具,電源,卡片', priceRange='官網未列價格（2026-08 查詢 soyal.com.tw），需洽代理商/經銷商報價', dependencyNote='多數配件需搭配對應的控制器/讀頭主機使用（如 DMOD-POE1204B 僅適用 AR-716-E16），選型前先確認主機型號是否相容', watchNote='本分類涵蓋多種不同性質的週邊，選型邏輯與 READER/MULTI_DOOR_HUB/ALLINONE_HUB（門禁決策主體）不同，是配套耗材/週邊而非主控設備；比較時建議依規格欄位分辨鎖具/按鈕/電源/卡片/網卡模組等子類型，不要直接跨子類型比較')

FIT = [
    ('SINGLE_DOOR', '適合', '配件（鎖具/按鈕/電源/卡片）是單一門禁系統的必要組成，幾乎每個單門案場都會用到'),
    ('MULTI_DOOR_OFFICE', '適合', '多門案場同樣需要對應數量的鎖具/按鈕/電源等配件，且常需搭配控制器專用網卡/PoE模組'),
    ('WAREHOUSE_DOCK', '適合', '倉儲/工廠出入口同樣需要鎖具/按鈕等配件，大門常需較大出力的磁力鎖款式'),
    ('GATE_GARAGE', '可用', '部分配件（如電源供應器）適用，但鎖具/按鈕主要針對一般門禁，車輛閘門通常另外搭配車道柵欄機系統'),
    ('RETROFIT_EXISTING', '適合', '配件常用於既有系統升級/局部更換，例如既有鎖具老化汰換或加裝控制器網卡模組'),
]

PRODUCTS = [
    dict(categoryCode='ACCESSORY', brand='SOYAL', model='AR-0180M', url='https://www.soyal.com.tw/product.php?act=view&id=86', label='磁力鎖180磅', priceNote='官網未列價格（2026-08 查詢 soyal.com.tw），需洽代理商/經銷商報價', specs=[['吸力', '180磅（80kg）'], ['電壓', '12-24VDC'], ['壽命', '50萬次'], ['用途', '逃生防煙門系統']]),
    dict(categoryCode='ACCESSORY', brand='SOYAL', model='AR-0600M-270', url='https://www.soyal.com.tw/product.php?act=view&id=94', label='磁力鎖600磅', priceNote='官網未列價格（2026-08 查詢 soyal.com.tw），需洽代理商/經銷商報價', specs=[['吸力', '600磅（270kg）'], ['電壓', '12/24VDC可選'], ['特色', '防殘磁設計＋防鎖體掉落專利'], ['側板厚度', '8mm']]),
    dict(categoryCode='ACCESSORY', brand='SOYAL', model='AR-1207A', url='https://www.soyal.com.tw/product.php?act=view&id=25', label='智慧型防盜陽極鎖·斷電開', priceNote='官網未列價格（2026-08 查詢 soyal.com.tw），需洽代理商/經銷商報價', specs=[['型式', '斷電開（Fail-Safe）'], ['材質', '304不鏽鋼鎖舌/鋅合金本體'], ['電壓', 'DC12-24V'], ['壽命', '50萬次'], ['特色', '門磁＋鎖舌雙偵測＋防撬警報']]),
    dict(categoryCode='ACCESSORY', brand='SOYAL', model='AR-888-PBI-S', url='https://www.soyal.com.tw/product.php?act=view&id=72', label='崁入式紅外線開門按鈕', priceNote='官網未列價格（2026-08 查詢 soyal.com.tw），需洽代理商/經銷商報價', specs=[['感應距離', '2-10cm（4段可調）'], ['電壓', 'DC9-24V'], ['安裝方式', '崁入式（強化玻璃面板）'], ['特色', '非接觸式/雙色LED']]),
    dict(categoryCode='ACCESSORY', brand='SOYAL', model='LRS-100-12', url='https://www.soyal.com.tw/product.php?act=view&id=253', label='100W開關電源供應器12V', priceNote='官網未列價格（2026-08 查詢 soyal.com.tw），需洽代理商/經銷商報價', specs=[['輸出電壓', '12VDC'], ['輸出電流', '8.5A'], ['額定功率', '102W'], ['效率', '88%'], ['保護機制', '短路/過載/過壓保護']]),
    dict(categoryCode='ACCESSORY', brand='SOYAL', model='AR-TAGCI', url='https://www.soyal.com.tw/product.php?act=view&id=228', label='感應卡片·ISO薄卡', priceNote='官網未列價格（2026-08 查詢 soyal.com.tw），需洽代理商/經銷商報價', specs=[['頻率', '125kHz/13.56MHz/雙頻可選'], ['卡片格式', 'EM4001/EM4095 或 Mifare/ISO15693/DESFire'], ['外型', 'ISO標準薄卡']]),
    dict(categoryCode='ACCESSORY', brand='SOYAL', model='DMOD-POE1204B', url='https://www.soyal.com.tw/product.php?act=view&id=269', label='AR-716-E16專用TCP/IP網卡+內建PoE', priceNote='官網未列價格（2026-08 查詢 soyal.com.tw），需洽代理商/經銷商報價', specs=[['適用主機', 'AR-716-E16'], ['功能', 'TCP/IP聯網＋PoE供電'], ['PoE標準', 'IEEE802.3af/at'], ['PoE輸出', '12VDC/24W'], ['尺寸', '57×35×20mm']]),
    dict(categoryCode='ALLINONE_HUB', brand='SOYAL', model='AR-725-H', url='https://www.soyal.com.tw/product.php?act=view&id=65', label='觸摸式背光鍵盤RFID感應控制器', priceNote='官網未列價格（2026-08 查詢 soyal.com.tw），需洽代理商/經銷商報價', specs=[['讀取頻率', '125kHz(EM)/13.56MHz(Mifare/NFC)'], ['通訊介面', 'RS-485 9600bps(SSC加密)/UART'], ['繼電器輸出', '門鎖繼電器×1（0.1-600秒可調）'], ['鍵盤', '觸控背光面板']]),
    dict(categoryCode='ALLINONE_HUB', brand='SOYAL', model='AR-837-EF9DO', url='https://www.soyal.com.tw/product.php?act=view&id=51', label='液晶顯示門禁控制器·指紋型', priceNote='官網未列價格（2026-08 查詢 soyal.com.tw），需洽代理商/經銷商報價', specs=[['辨識方式', '光學指紋＋雙頻RFID(125kHz/13.56MHz)'], ['指紋容量', '9,000枚/4,500人'], ['驗證速度', '<0.7秒（1:1000比對）'], ['通訊介面', 'RS-485/TCP-IP（可選PoE模組）'], ['繼電器輸出', '門鎖×1＋警報×1'], ['防水等級', 'IP55'], ['人員容量', '16,000人（可擴至65,000）']]),
    dict(categoryCode='ALLINONE_HUB', brand='SOYAL', model='AR-837-EA', url='https://www.soyal.com.tw/product.php?act=view&id=46', label='真人臉部辨識RFID雙頻感應多功能控制器', priceNote='官網未列價格（2026-08 查詢 soyal.com.tw），需洽代理商/經銷商報價', specs=[['辨識方式', '臉型辨識/讀卡/密碼可組合'], ['臉部容量', '1,000人'], ['卡片容量', '16,000~65,000人'], ['通訊介面', 'RS-485＋TCP/IP(10/100M)＋TTL UART'], ['繼電器輸出', '電鎖/警報/警戒/反脅迫多組'], ['可獨立作業', '是（單機/連網自動切換）']]),
    dict(categoryCode='MULTI_DOOR_HUB', brand='SOYAL', model='AR-716-E16', url='https://www.soyal.com.tw/product.php?act=view&id=49', label='網路型多門控制器·16門', priceNote='官網未列價格（2026-08 查詢 soyal.com.tw），需洽代理商/經銷商報價', specs=[['門數', '16~32門（可擴充）'], ['通訊介面', 'RS-485 9600bps + TCP/IP 10/100M（外接網卡）'], ['內建PoE', '否（需選配DMOD-POE1204B）'], ['後備電源', '需外接AR-716-PU-M'], ['讀頭介面', 'RS485×2通道（每通道8台）+ Wiegand×2'], ['容量', '63組時段/255組門群']]),
    dict(categoryCode='MULTI_DOOR_HUB', brand='SOYAL', model='AR-716-E18', url='https://www.soyal.com.tw/product.php?act=view&id=18', label='網路型多門控制器·18門', priceNote='官網未列價格（2026-08 查詢 soyal.com.tw），需洽代理商/經銷商報價', specs=[['門數', '18門'], ['通訊介面', 'RS-485 9600bps/TCP-IP 10/100M（外接模組）'], ['後備電源', '支援UPS（電池外購）'], ['讀頭介面', 'RS485×2通道（每通道8台）+ Wiegand×2'], ['使用人數', '15,000'], ['進出紀錄', '11,000筆'], ['內建繼電器', '電鎖×2＋警報×1']]),
    dict(categoryCode='MULTI_DOOR_HUB', brand='SOYAL', model='AR-716-E16-1608R-PU', url='https://www.soyal.com.tw/product.php?act=view&id=241', label='IP 10門中控式後備電源控制器', priceNote='官網未列價格（2026-08 查詢 soyal.com.tw），需洽代理商/經銷商報價', specs=[['門數', '10門'], ['通訊介面', 'TCP/IP + RS-485×1（9600-19200bps，支援Modbus RTU）'], ['後備電源', '內建中控式後備電源'], ['數位輸入', '16（光耦隔離）'], ['繼電器輸出', '8'], ['工作溫度', '-20~70°C']]),
    dict(categoryCode='READER', brand='SOYAL', model='AR-101-U', url='https://www.soyal.com.tw/product.php?act=view&id=58', label='迷你雙頻智慧讀頭', priceNote='官網未列價格（2026-08 查詢 soyal.com.tw），需洽代理商/經銷商報價', specs=[['讀取頻率', '125kHz(EM)+13.56MHz(Mifare/NFC/DESFire EV1)雙頻'], ['通訊介面', 'RS-485 9600bps / UART'], ['繼電器輸出', '無（純讀頭）'], ['尺寸', '37×37×31mm'], ['工作電壓', '12-24VDC']]),
    dict(categoryCode='READER', brand='SOYAL', model='AR-723-U', url='https://www.soyal.com.tw/product.php?act=view&id=81', label='感應式迷你讀頭', priceNote='官網未列價格（2026-08 查詢 soyal.com.tw），需洽代理商/經銷商報價', specs=[['讀取頻率', '125kHz(EM)/13.56MHz(Mifare/ISO14443)'], ['通訊介面', 'RS-485 9600bps + Wiegand輸出'], ['繼電器輸出', '無（純讀頭）'], ['尺寸', '81×43×18mm']]),
    dict(categoryCode='READER', brand='SOYAL', model='AR-721-K', url='https://www.soyal.com.tw/product.php?act=view&id=80', label='按鍵型多功能讀頭', priceNote='官網未列價格（2026-08 查詢 soyal.com.tw），需洽代理商/經銷商報價', specs=[['讀取頻率', '125kHz(EM)/13.56MHz(Mifare ISO14443/7816-4)'], ['通訊介面', 'RS-485 9600bps(SSC加密)/UART'], ['鍵盤', '有（密碼通行）'], ['尺寸', '111×77×26mm']]),
]

def sync_category(conn):
    if conn.execute("SELECT 1 FROM access_categories WHERE code=?", (CATEGORY["code"],)).fetchone():
        print(f"access_categories：{CATEGORY['code']} 已存在，略過")
        return
    max_sort = conn.execute("SELECT COALESCE(MAX(sort_order), -1) AS m FROM access_categories").fetchone()["m"]
    conn.execute(
        "INSERT INTO access_categories (code, name, key_specs, tags, price_range, dependency_note, watch_note, sort_order, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,datetime('now'))",
        (CATEGORY["code"], CATEGORY["name"], CATEGORY["keySpecs"], CATEGORY["tags"], CATEGORY["priceRange"],
         CATEGORY["dependencyNote"], CATEGORY["watchNote"], max_sort + 1),
    )
    conn.commit()
    print(f"access_categories：新增 {CATEGORY['code']}")


def sync_fit(conn):
    added, skipped = 0, 0
    max_sort = conn.execute("SELECT COALESCE(MAX(sort_order), -1) AS m FROM access_fit").fetchone()["m"]
    for scenario_code, fit_level, fit_note in FIT:
        if conn.execute(
            "SELECT 1 FROM access_fit WHERE scenario_code=? AND category_code=?", (scenario_code, CATEGORY["code"])
        ).fetchone():
            skipped += 1
            continue
        max_sort += 1
        conn.execute(
            "INSERT INTO access_fit (scenario_code, category_code, fit_level, fit_note, sort_order, updated_at) "
            "VALUES (?,?,?,?,?,datetime('now'))",
            (scenario_code, CATEGORY["code"], fit_level, fit_note, max_sort),
        )
        added += 1
    conn.commit()
    print(f"access_fit：新增 {added} 筆，略過（已存在）{skipped} 筆")


def sync_products(conn):
    added, skipped = 0, 0
    for p in PRODUCTS:
        if conn.execute(
            "SELECT 1 FROM access_products WHERE category_code=? AND brand=? AND model=?",
            (p["categoryCode"], p["brand"], p["model"]),
        ).fetchone():
            skipped += 1
            continue
        max_sort = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) AS m FROM access_products WHERE category_code=?",
            (p["categoryCode"],),
        ).fetchone()["m"]
        conn.execute(
            "INSERT INTO access_products (category_code, brand, model, url, label, price_note, specs_json, sort_order) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (p["categoryCode"], p["brand"], p["model"], p["url"], p["label"], p["priceNote"],
             json.dumps(p["specs"], ensure_ascii=False), max_sort + 1),
        )
        added += 1
    conn.commit()
    print(f"access_products：新增 {added} 筆，略過（已存在）{skipped} 筆")


def main():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    sync_category(con)
    sync_fit(con)
    sync_products(con)
    con.close()
    print("完成。")


if __name__ == "__main__":
    main()
