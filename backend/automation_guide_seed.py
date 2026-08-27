"""One-time seed data for the automation_* tables (migration _m065_automation_guide)。

自動化系統選型導覽：倉儲/產線自動化設備分類 × 場域情境（矩陣式交叉，跟交換器/監控/門禁/
閘道器選型導覽同一種資料形狀）。第一批資料只建立情境×分類骨架＋適配矩陣，**刻意不塞入
具體品牌/型號/報價**——這批需要實際 WebSearch 查證（比照 monitor_guide 過去的作法：先上線
骨架，品牌深度後續逐批補），這次上線範圍只到「類別可以運作」為止，PRODUCTS_JSON 先留空。
之後新增情境／分類／適配度／產品一律透過 /api/automation-guide/* API，不要回頭改這個 seed 檔。
"""

# [code, name, description]
SCENARIOS_JSON = """
[
["WAREHOUSE_PICKING", "倉儲/物流中心揀貨搬運", "貨架間穿梭搬運物料箱/棧板，動線可能隨庫位調整而變動"],
["PRODUCTION_LINE", "產線工站上下料/組裝", "固定工站間的精密取放、鎖附、焊接等重複性動作"],
["MIXED_TRAFFIC_FACILITY", "人車混流廠區/走道", "廠區走道、通道與行人/堆高機共用空間，需要感知避障能力"],
["HEAVY_PAYLOAD_YARD", "重件/棧板搬運場域", "大型物料或整棧板重物的長距離搬運，對承重要求高"]
]
"""

# [code, name, key_specs, tags, price_range, dependency_note, watch_note]
CATEGORIES_JSON = """
[
["AGV", "AGV 循軌導引搬運車", "沿磁條/QR Code/雷射反射板等固定路徑導引移動，路徑可預期、定位精度穩定", "固定路徑,可預期動線,重複性搬運", "洽詢報價（依承重/導引方式規格報價）", "需場地佈建磁條/QR Code 或反射板等導引設施，路徑變更需重新施工", "路徑固定，倉儲貨架/產線佈局若常變動，改線成本較高；需評估與既有堆高機/人員動線的交會點安全"],
["AMR", "AMR 自主移動機器人", "透過 SLAM 建圖與感測器即時避障，免佈建軌道即可動態規劃路徑", "動態避障,免佈建軌道,彈性路線", "洽詢報價（依承重/感測器規格報價）", "需完整場域地圖建置與 Wi-Fi 覆蓋供多機調度/後台管理", "承重上限通常低於同噸位 AGV 車型；多機協作需搭配調度管理軟體，非單機即可發揮最大效益"],
["COBOT", "協作型機械手臂", "具力量/速度限制與安全感應，可在無防護圍籬下與人員同場域作業", "人機協作,免圍籬,快速部署", "洽詢報價（依負載/臂展規格報價）", "負載能力通常低於工業型機械手臂，需依作業精度/重量重新評估治具與夾爪", "仍需依實際作業風險評估（如高速/尖銳工具）決定是否額外加裝防護，並非完全零風險場域"],
["INDUSTRIAL_ARM", "工業型機械手臂", "高負載/高速重複動作，定位精度高，適合大量生產的固定站台作業", "高負載,高速,高精度", "洽詢報價（依負載/軸數規格報價）", "須搭配安全圍籬/光柵等防護措施，不可與人員共域作業", "現場需要獨立防護空間與電力/氣壓等基礎設施評估，導入前期土建/工安評估成本較高"]
]
"""

# [scenario_code, category_code, fit_level（適合/可用/不建議）, fit_note]
FIT_JSON = """
[
["WAREHOUSE_PICKING", "AGV", "適合", "固定動線、可預期路徑，磁條/QR Code 導引適合重複性揀貨路線"],
["WAREHOUSE_PICKING", "AMR", "適合", "貨架配置常隨庫存調整而變動，SLAM 動態導航彈性較高，不用重新佈建軌道"],
["WAREHOUSE_PICKING", "COBOT", "可用", "可用於揀貨站台的精細取放輔助，但不負責長距離搬運"],
["WAREHOUSE_PICKING", "INDUSTRIAL_ARM", "不建議", "工業型手臂多為固定站台高速作業，非揀貨搬運取向"],
["PRODUCTION_LINE", "AGV", "可用", "可用於站間物料接駁，但精密取放/組裝非其強項"],
["PRODUCTION_LINE", "AMR", "可用", "同樣適合站間物流接駁，但不負責工站內的取放/組裝動作"],
["PRODUCTION_LINE", "COBOT", "適合", "產線工站取放/鎖附的標準應用，可與人員共站作業"],
["PRODUCTION_LINE", "INDUSTRIAL_ARM", "適合", "高速高負載重複性動作（焊接/搬運/上下料）的主力方案"],
["MIXED_TRAFFIC_FACILITY", "AGV", "不建議", "固定路徑/軌道對人車混流環境的即時避障能力不足，安全風險較高"],
["MIXED_TRAFFIC_FACILITY", "AMR", "適合", "具備動態避障與感知能力，是人車混流環境的標準選擇"],
["MIXED_TRAFFIC_FACILITY", "COBOT", "可用", "多用於固定站台而非移動路徑，需搭配站台防護配置"],
["MIXED_TRAFFIC_FACILITY", "INDUSTRIAL_ARM", "不建議", "需要安全圍籬隔離，不適合開放式人車混流空間"],
["HEAVY_PAYLOAD_YARD", "AGV", "適合", "重負載車型配合固定動線，適合棧板/重件的重複搬運路線"],
["HEAVY_PAYLOAD_YARD", "AMR", "可用", "部分機型支援重負載，但可承重上限通常低於專用 AGV 車型"],
["HEAVY_PAYLOAD_YARD", "COBOT", "不建議", "協作型手臂負載通常較輕，非為重件搬運設計"],
["HEAVY_PAYLOAD_YARD", "INDUSTRIAL_ARM", "可用", "高負載機型可用於重件上下料，但屬固定站台方案，需另搭配移載平台才能做場域間搬運"]
]
"""

# [category_code, brand, model, url, label, price_note, specs_json]
# 刻意留空：品牌/型號需要實際 WebSearch 查證（跟其他選型類別過去的做法一致），
# 由後續獨立的內容擴充任務補上，不在這次上線範圍內。
PRODUCTS_JSON = "[]"
