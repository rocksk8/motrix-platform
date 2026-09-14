"""One-time seed data for the access_* tables (migration _m040_access_guide).

門禁系統選型導覽：元件分類 × 場域情境（矩陣式交叉，跟交換器/監控系統選型導覽同一種資料形狀）。
第一批資料：5 個場域情境 × 4 個元件分類，以 UniFi Access 產品線實際產品驗證欄位設計
（2026-08 查證）。UniFi Access 是讀頭＋控制主機＋軟體三件式架構，所有分類都需要一台執行
UniFi Access App 的 UniFi OS Console（如 Cloud Gateway／Dream Machine）才能運作，非純硬體
獨立系統，各分類 watch_note 皆已註記此相依性。
之後新增情境／分類／適配度／產品一律透過 /api/access-guide/* API，不要回頭改這個 seed 檔。
"""

# [code, name, description]
SCENARIOS_JSON = """
[
["SINGLE_DOOR", "單一門禁", "小型辦公室／店面單一出入口，只需管理一扇門"],
["MULTI_DOOR_OFFICE", "多門辦公室／商辦大樓", "多扇門／多樓層需要集中管理權限與通行紀錄"],
["WAREHOUSE_DOCK", "倉儲／工廠出入口", "裝卸月台／員工通道等多個出入口，人員/車輛進出頻繁"],
["GATE_GARAGE", "車輛閘門／車庫", "電動閘門、車道柵欄、地下車庫捲門等車輛出入控制"],
["RETROFIT_EXISTING", "既有配線改裝案場", "已有傳統門禁系統配線（Wiegand/OSDP 讀頭），只想換控制主機與後台軟體"]
]
"""

# [code, name, key_specs, tags, price_range, dependency_note, watch_note]
CATEGORIES_JSON = """
[
["ALLINONE_HUB", "一體式讀頭主機", "讀頭與控制器合一，單一 PoE 埠供電，走線與安裝最簡單", "單門,快速部署", "US$129（2026-08 查價）", "需搭配電鎖（磁力鎖/電插鎖）與門禁五金", "需搭配一台執行 UniFi Access App 的 UniFi OS Console（如 Cloud Gateway／Dream Machine）才能運作，非純硬體獨立系統；多門場景需一門一台，管理上不如集中控制器整合"],
["MULTI_DOOR_HUB", "多門控制器", "獨立控制主機，可接多支讀頭／門，支援既有 Wiegand／OSDP 讀頭協定", "集中管理,可擴充,相容既有配線", "US$280~洽詢報價（依門數，2026-08 查價）", "需另外選配讀頭（本類別或既有第三方讀頭）與電鎖", "同樣需搭配 UniFi OS Console；DC 供電型號（如 Retrofit Hub）與 PoE 供電型號（如 Enterprise Hub）的現場配線需求不同，選型前要先確認案場既有電源條件"],
["READER", "獨立讀頭", "純讀頭，本身不能獨立控制門鎖，需搭配控制器使用", "NFC,藍牙,可搭配既有控制器", "US$99~洽詢報價（2026-08 查價）", "必須搭配 MULTI_DOOR_HUB 或既有第三方門禁控制器才能運作，非獨立方案", "Pro 款含螢幕與攝影機可做訪客對講/人臉輔助辨識，Lite 款純刷卡感應，選型前先確認場景是否需要對講功能"],
["GATE_CONTROLLER", "閘道／車庫控制器", "繼電器輸出控制電動閘門／車道柵欄／車庫捲門", "車輛出入,繼電器輸出", "洽詢報價（2026-08 查價，官網未列牌價）", "需搭配既有電動閘門/柵欄機的繼電器介面，非門禁本體，只負責觸發開關訊號", "需搭配一台執行 UniFi Access App 的 UniFi OS Console；車牌辨識需另外搭配 UniFi Protect 攝影機（見監控系統選型導覽），本身不含辨識能力"]
]
"""

# [scenario_code, category_code, fit_level（適合/可用/不建議）, fit_note]
FIT_JSON = """
[
["SINGLE_DOOR", "ALLINONE_HUB", "適合", "單一 PoE 埠即可完成部署，是單門場景最簡單省事的方案"],
["SINGLE_DOOR", "MULTI_DOOR_HUB", "可用", "技術上可行但殺雞用牛刀，多花錢在用不到的第二門控制能力"],
["SINGLE_DOOR", "READER", "可用", "仍需另外準備控制器才能運作，等於要兩件才夠，單門通常直接選一體式主機更省事"],
["SINGLE_DOOR", "GATE_CONTROLLER", "不建議", "閘道控制器是為車輛閘門設計的繼電器輸出，不是一般門禁應用"],
["MULTI_DOOR_OFFICE", "ALLINONE_HUB", "可用", "多扇門要多台，每台仍是獨立單門方案，管理上不如集中控制器整合方便"],
["MULTI_DOOR_OFFICE", "MULTI_DOOR_HUB", "適合", "多門辦公室的標準配置，一台控制器集中管理多扇門的權限與通行紀錄"],
["MULTI_DOOR_OFFICE", "READER", "適合", "標準做法：控制器＋多支讀頭分散裝在各門口，是本情境最常見的配置模式"],
["MULTI_DOOR_OFFICE", "GATE_CONTROLLER", "不建議", "辦公室門禁不涉及車輛閘門控制"],
["WAREHOUSE_DOCK", "ALLINONE_HUB", "可用", "單一出入口可用，但倉儲通常有多個裝卸門，集中管理效益不如多門控制器"],
["WAREHOUSE_DOCK", "MULTI_DOOR_HUB", "適合", "多個裝卸月台/員工通道共用一台控制器集中管理，是本情境的標準做法"],
["WAREHOUSE_DOCK", "READER", "適合", "需搭配控制器一起選型，讀頭本身要考慮戶外/半戶外防護等級"],
["WAREHOUSE_DOCK", "GATE_CONTROLLER", "可用", "若倉儲場站有車輛出入閘道則適用，純人員出入口不需要"],
["GATE_GARAGE", "ALLINONE_HUB", "不建議", "一體式讀頭主機是為一般門禁設計，沒有繼電器輸出可控制閘門機"],
["GATE_GARAGE", "MULTI_DOOR_HUB", "不建議", "多門控制器同樣是為門禁讀頭/電鎖設計，非為閘門繼電器輸出而生"],
["GATE_GARAGE", "READER", "可用", "可搭配 Gate Hub 做車輛/人員身分驗證後才觸發開閘，但讀頭本身不觸發閘門"],
["GATE_GARAGE", "GATE_CONTROLLER", "適合", "本情境的專屬選項，繼電器輸出直接對接既有電動閘門/柵欄機控制介面"],
["RETROFIT_EXISTING", "ALLINONE_HUB", "不建議", "一體式主機是全新讀頭+控制器合一設計，無法沿用既有讀頭與配線"],
["RETROFIT_EXISTING", "MULTI_DOOR_HUB", "適合", "本情境的核心選項——Retrofit Hub 系列專為既有 Wiegand/OSDP 讀頭與配線相容設計，只換主機與後台軟體"],
["RETROFIT_EXISTING", "READER", "可用", "若既有讀頭也要一併換新才需要，單純換控制器可沿用既有讀頭不必選購"],
["RETROFIT_EXISTING", "GATE_CONTROLLER", "不建議", "既有配線改裝通常指的是門禁讀頭系統，車輛閘門是另一套獨立評估"]
]
"""

# [category_code, brand, model, url, label, price_note, specs_json]
PRODUCTS_JSON = """
[
["ALLINONE_HUB", "UniFi", "Access Ultra", "https://techspecs.ui.com/unifi/door-access/ua-ultra", "UniFi Access Ultra 原廠規格頁", "US$129（2026-08 查價）", "[[\\"型態\\", \\"讀頭＋控制器合一\\"], [\\"供電\\", \\"單一 PoE 埠\\"], [\\"讀卡方式\\", \\"NFC／藍牙\\"], [\\"適用門數\\", \\"1 門\\"], [\\"其他\\", \\"需搭配電鎖與 UniFi OS Console\\"]]"],
["MULTI_DOOR_HUB", "UniFi", "Retrofit Hub 2", "https://techspecs.ui.com/unifi/door-access/ua-retrofit-hub-2", "UniFi Access Retrofit Hub 原廠規格頁", "US$280（2026-08 查價，第三方通路，官網未列牌價）", "[[\\"適用門數\\", \\"2 門（進出各一）\\"], [\\"供電\\", \\"DC 供電（12/24V）\\"], [\\"相容讀頭協定\\", \\"Wiegand／OSDP\\"], [\\"支援人數\\", \\"最多 10,000 使用者\\"], [\\"其他\\", \\"專為既有配線改裝設計，需搭配 UniFi OS Console\\"]]"],
["MULTI_DOOR_HUB", "UniFi", "Enterprise Access Hub (EAH-8)", "https://techspecs.ui.com/unifi/door-access/eah-8", "UniFi Enterprise Access Hub 原廠規格頁", "洽詢報價（2026-08 查價，官網未列牌價）", "[[\\"適用門數\\", \\"最多 8 門（進出各一時為 4 門）\\"], [\\"其他\\", \\"與 Retrofit Hub 2 同為多門控制器，本款門數規模更大，適合大型商辦/廠區；需搭配 UniFi OS Console\\"]]"],
["READER", "UniFi", "Access Reader Lite", "https://techspecs.ui.com/unifi/door-access/ua-reader-lite", "UniFi Access Reader Lite 原廠規格頁", "US$99（2026-08 查價）", "[[\\"讀卡方式\\", \\"NFC／藍牙\\"], [\\"螢幕\\", \\"無\\"], [\\"其他\\", \\"純感應讀頭，需搭配 MULTI_DOOR_HUB 或既有控制器才能運作\\"]]"],
["READER", "UniFi", "Access Reader Pro", "https://techspecs.ui.com/unifi/door-access/ua-reader-pro", "UniFi Access Reader Pro 原廠規格頁", "洽詢報價（2026-08 查價，官網未列牌價）", "[[\\"讀卡方式\\", \\"NFC／藍牙\\"], [\\"螢幕\\", \\"含觸控螢幕與攝影機\\"], [\\"其他\\", \\"可做訪客對講/人臉輔助辨識，同樣需搭配控制器才能運作\\"]]"],
["GATE_CONTROLLER", "UniFi", "Hub Gate", "https://techspecs.ui.com/unifi/door-access/ua-hub-gate", "UniFi Access Hub Gate 原廠規格頁", "洽詢報價（2026-08 查價，官網未列牌價）", "[[\\"型態\\", \\"閘道/車庫繼電器輸出控制器\\"], [\\"其他\\", \\"需搭配既有電動閘門/柵欄機的繼電器介面，車牌辨識需另外搭配 UniFi Protect 攝影機\\"]]"]
]
"""
