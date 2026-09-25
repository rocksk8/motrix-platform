"""One-time seed data for the switch_* tables (migration _m032_switch_guide).

商用／工業網路交換器選型導覽：產品分類 × 行業情境（矩陣式交叉，非族系演進、非場域三級）。
第一批資料：5 個行業情境 × 4 個產品分類，以 TP-Link／UniFi／Aruba Instant On／Sbjlink／Moxa
實際產品驗證欄位設計（2026-07 查證）。
之後新增情境／分類／適配度／產品一律透過 /api/switch-guide/* API，不要回頭改這個 seed 檔。
"""

# [code, name, description]
SCENARIOS_JSON = """
[
["OFFICE", "辦公室／機房", "一般辦公環境或小型機房，溫控與電力穩定，安裝空間通常有限"],
["RETAIL", "零售店面", "店面／展示空間，弱電間狹小、常與監控/POS 共用網路，人員進出頻繁"],
["WAREHOUSE", "物流倉儲", "倉儲/物流場站，涵蓋面積大、常需搭配 AMR/掃描設備，粉塵與溫差較office大"],
["FACTORY", "工廠產線", "產線/機電整合環境，PoE 供電需求高（攝影機/感測器/AP），電磁干擾與稼動率要求高"],
["OUTDOOR", "戶外／路側基礎設施", "戶外桿件、園區道路、半戶外雨遮等，溫濕度與防護門檻高，多數已在場域選型導覽涵蓋範圍內"]
]
"""

# [code, name, key_specs, tags, price_range, dependency_note, watch_note]
CATEGORIES_JSON = """
[
["UNMANAGED", "非網管型", "隨插即用，無 VLAN／監控介面，僅基本 PoE 供電", "入門,低成本", "NT$800–3,000（8 埠桌上型，2026-07 查價）", "", "故障時無法遠端診斷，只能到現場拔插排除"],
["SMART_L2PLUS", "簡易網管 Smart／L2+", "Web GUI 管理、VLAN、基本 QoS、靜態路由", "中小型部署,性價比", "NT$3,500–8,000（8~10 埠 PoE+，2026-07 查價）", "多數品牌需搭配雲端/App 帳號才能遠端管理", "非全部型號支援離線本機管理，斷網時設定介面可能受限"],
["MANAGED_L3", "全網管 L2/L3 機架式", "動態路由、堆疊、ACL、SNMP、雙電源選配", "企業級,可擴充", "NT$15,000–50,000+（24 埠等級，2026-07 查價）", "通常需搭配機架與獨立電力迴路；多品牌管理平台需額外授權", "功能強大但設定複雜度高，小型專案容易 over-spec"],
["INDUSTRIAL", "工業導軌寬溫", "DIN 導軌安裝、寬溫 -40~75°C、雙電源輸入、部分具網管", "嚴苛環境,高可靠度", "US$300–2,500+（依埠數與網管與否，2026-07 查價）", "與場域選型導覽的 A/B/C/D/E 場域門檻高度重疊，實際專案請先查場域選型導覽對應場域的匯集層／環境端網路建議，本類別僅作一般性起點參考", "同規格下價格顯著高於商用機種，非嚴苛環境不建議直接選用，是本清單中最容易 over-spec 的一級"]
]
"""

# [scenario_code, category_code, fit_level（適合/可用/不建議）, fit_note]
FIT_JSON = """
[
["OFFICE", "UNMANAGED", "可用", "小型辦公室分支點可用，但超過約 10 人建議至少上 Smart 等級以利故障排除"],
["OFFICE", "SMART_L2PLUS", "適合", "辦公室的甜蜜點：VLAN 分隔訪客/內部網路、PoE 供電 AP 與電話機，多數專案的預設選擇"],
["OFFICE", "MANAGED_L3", "可用", "大型辦公室或多樓層跨 VLAN 路由才需要，中小型辦公室通常 over-spec"],
["OFFICE", "INDUSTRIAL", "不建議", "辦公室溫控環境用不到寬溫與導軌安裝，純粹增加成本"],
["RETAIL", "UNMANAGED", "不建議", "店面常與監控/POS 共用網路，缺乏 VLAN 隔離會讓刷卡機與客用 WiFi 在同一廣播網域，資安疑慮大"],
["RETAIL", "SMART_L2PLUS", "適合", "VLAN 隔離 POS/監控/客用 WiFi 是店面標配需求，Smart 等級的 PoE 預算通常足夠監控攝影機"],
["RETAIL", "MANAGED_L3", "可用", "連鎖店多店集中管理才需要，單店通常不需要到 L3"],
["RETAIL", "INDUSTRIAL", "不建議", "店面環境不需要寬溫與工業防護，弱電間空間有限時導軌型反而不好安裝"],
["WAREHOUSE", "UNMANAGED", "不建議", "倉儲網路節點多、範圍大，缺乏網管介面時排查斷線非常耗時"],
["WAREHOUSE", "SMART_L2PLUS", "可用", "小型倉儲或單一樓管可用，但 AMR/RFID 掃描設備多時建議上 L3 做流量隔離"],
["WAREHOUSE", "MANAGED_L3", "適合", "大型倉儲的標準配置，堆疊功能可支援跨區域擴充，AMR 車隊上線後流量隔離很重要"],
["WAREHOUSE", "INDUSTRIAL", "可用", "溫層交界/裝卸月台等半戶外節點需要工業導軌型，詳見場域選型導覽 A3/B 系列場域的環境端網路建議"],
["FACTORY", "UNMANAGED", "不建議", "產線 PoE 供電的攝影機/感測器數量多，非網管型無法做 PoE 用電監控，跳電找不到是哪個埠"],
["FACTORY", "SMART_L2PLUS", "可用", "小型產線或辦公併行產線可用，但電磁干擾環境的可靠度不如工業機種"],
["FACTORY", "MANAGED_L3", "可用", "產線資訊系統（MES/SCADA）需要 VLAN 隔離 OT/IT 網路時適用，但機殼防護仍需另外處理"],
["FACTORY", "INDUSTRIAL", "適合", "產線的電磁干擾/粉塵/振動門檻通常已達工業導軌型的適用範圍，實際場域門檻請對照場域選型導覽 D/E 系列"],
["OUTDOOR", "UNMANAGED", "不建議", "戶外溫濕度與防護等級，商用非網管機種完全不合格"],
["OUTDOOR", "SMART_L2PLUS", "不建議", "商用機殼防護等級（多為 IP20）不適合戶外，即便裝防水箱也難處理散熱"],
["OUTDOOR", "MANAGED_L3", "不建議", "機架式設計本身就不是為戶外環境設計，同樣不適合"],
["OUTDOOR", "INDUSTRIAL", "適合", "戶外節點的唯一合理選項；實際場域（半戶外/全戶外/港區鹽霧等）的精確規格請直接查場域選型導覽對應場域，不要在本類別重新選型"]
]
"""

# [category_code, brand, model, url, label, price_note]
PRODUCTS_JSON = """
[
["UNMANAGED", "TP-Link", "TL-SG1008P", "https://www.tp-link.com/us/service-provider/unmanaged-switch/tl-sg1008p/", "TP-Link TL-SG1008P 原廠頁（8 埠／4 PoE+／64W）", "US$75（2026-07 查價）"],
["SMART_L2PLUS", "UniFi", "Switch Lite 8 PoE", "https://store.ui.com/us/en/products/usw-lite-8-poe", "UniFi USW-Lite-8-PoE 原廠頁（8 埠／4 PoE+／52W）", "US$109（2026-07 查價）"],
["SMART_L2PLUS", "TP-Link", "Omada TL-SG2210P", "https://www.omadanetworks.com/us/business-networking/omada-switch-access/tl-sg2210p/", "Omada TL-SG2210P 原廠頁（8 埠 PoE+／2 SFP／61W）", "US$120（2026-07 查價，第三方通路，官網未列牌價）"],
["MANAGED_L3", "Aruba", "Instant On 1960 24G", "https://www.arubainstanton.com/products/switches/1960-series/", "Aruba Instant On 1960 系列原廠頁（24 埠／2x10GbE／L3 Lite）", "US$450~600（2026-07 查價，第三方通路約略區間，官網未列牌價）"],
["INDUSTRIAL", "Sbjlink", "RPT-M1810GP-T-X2", "https://www.sbjlink.com/products_view.php?id=188", "Sbjlink 產品頁＋規格書（沿用場域選型導覽已驗證型號）", "洽詢原廠報價（工業產品無公開牌價）"],
["INDUSTRIAL", "Moxa", "EDS-P510A-8PoE-2GTXSFP-T", "https://www.moxa.com/en/products/industrial-network-infrastructure/ethernet-switches/poe-switches/eds-p510a-series", "Moxa EDS-P510A 系列原廠頁（10 埠／8 PoE／2 SFP Combo）", "US$2,050（2026-07 查價）"]
]
"""
