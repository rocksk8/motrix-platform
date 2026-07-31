"""One-time seed data for the netarch_* tables (migration _m031_netarch_guide).

網路架構選型導覽：技術族系 → 世代／規格 → 產品連結。
第一批資料：Wi-Fi 無線網路（Wi-Fi 6 / 6E / 7）、行動網路（4G LTE / 5G Sub-6 / 5G mmWave），
以 UniFi／Omada／Peplink／Netgear 四家實際產品驗證欄位設計（2026-07 查證）。
之後新增族系／世代／產品一律透過 /api/netarch-guide/* API，不要回頭改這個 seed 檔。
"""

FAMILIES_JSON = """
[
["WIFI", "Wi-Fi 無線網路", "室內外無線覆蓋，含企業級 AP／Mesh"],
["CELLULAR", "行動網路（4G／5G）", "車載/備援/主用行動網路連線，含路由器與 CPE"]
]
"""

# [family_code, gen_name, key_specs, upgrade_note, typical_scenario, tags, price_range, dependency_note, watch_note]
GENERATIONS_JSON = """
[
["WIFI", "Wi-Fi 6", "雙頻（2.4G／5G）、最高 160MHz 頻寬、OFDMA、MU-MIMO", "（基準世代）", "一般辦公室、中密度場所", "標準,主流", "NT$3,000–15,000（AP）", "需 PoE+ 供電", ""],
["WIFI", "Wi-Fi 6E", "在 Wi-Fi 6 基礎上新增 6GHz 頻段", "多一個乾淨頻段，緩解 2.4／5GHz 壅塞干擾", "高密度場所、對延遲敏感的應用", "高密度,過渡世代", "NT$8,000–20,000（AP）", "用戶端裝置需支援 6GHz 才吃得到好處", "非所有 Wi-Fi 6E AP 都保證性能大幅提升，需搭配支援 6GHz 的終端裝置才有意義"],
["WIFI", "Wi-Fi 7", "三頻（2.4／5／6GHz）、最高 320MHz 頻寬、MLO 多鏈路同傳", "頻寬倍增於 Wi-Fi 6E；MLO 可同時用多頻段傳輸，大幅降低延遲與提升穩定度", "大型企業、高密度場所、AR/VR、8K 影音等頻寬敏感應用", "高密度,企業級,未來性", "NT$12,000–35,000（AP）", "需 PoE++ 供電；上行需 2.5GbE 以上才能發揮頻寬", "U7/EAP77x 系列需要 PoE+/++ 交換器與 2.5GbE 以上上行才能發揮完整效能，若只有一般 GbE 交換器等於降規使用"],
["CELLULAR", "4G LTE", "理論下行約 150Mbps~1Gbps（依 Cat 等級）", "（基準世代）", "一般備援網路、中低頻寬需求場域", "備援,成本優先", "NT$5,000–15,000（路由器）", "", ""],
["CELLULAR", "5G Sub-6", "理論下行可達數 Gbps，延遲較 4G 大幅降低", "頻寬與延遲大幅提升，可支援更多連網裝置", "需要高頻寬備援或作為主用網路的場域", "主用網路,高頻寬", "NT$15,000–40,000（路由器）", "", "實際速率受電信商基地台部署與訊號強度影響很大，現場實測比看規格更準"],
["CELLULAR", "5G mmWave", "理論下行可達 8Gbps 以上", "極致頻寬，適合短距高流量熱點", "室內短距高頻寬熱點（如展場、大型會議室）", "極高頻寬,短距", "NT$25,000–60,000（路由器）", "建議搭配 Sub-6 做基礎覆蓋", "mmWave 覆蓋距離短、穿牆能力差，不適合作為廣域覆蓋的唯一方案"]
]
"""

# [family_code, gen_name（對應上面的世代名稱）, brand, model, url, label, price_note]
PRODUCTS_JSON = """
[
["WIFI", "Wi-Fi 6", "UniFi", "U6-Pro", "https://store.ui.com/us/en/products/u6-pro", "UniFi U6 Pro 原廠頁", "US$159"],
["WIFI", "Wi-Fi 6", "Omada", "EAP670 等 WiFi 6 系列", "https://www.omadanetworks.com/us/business-networking/omada/wifi/wifi-6/", "Omada WiFi 6 產品分類頁", ""],
["WIFI", "Wi-Fi 7", "UniFi", "U7-Pro", "https://store.ui.com/us/en/products/u7-pro", "UniFi U7 Pro 原廠頁（PoE+／2.5GbE 上行）", "US$189"],
["WIFI", "Wi-Fi 7", "Omada", "EAP773", "https://www.omadanetworks.com/us/business-networking/omada-wifi-ceiling-mount/eap773/", "Omada EAP773 原廠頁（BE11000／10G Port）", ""],
["CELLULAR", "5G Sub-6", "Peplink", "MAX BR1 Pro 5G", "https://www.peplink.com/products/mobile-routers/max-br1-pro-5g/", "Peplink MAX BR1 Pro 5G 原廠頁（2.5GbE WAN／Wi-Fi 6）", ""],
["CELLULAR", "5G Sub-6", "Netgear", "Nighthawk M6 Pro", "https://www.netgear.com/se/home/mobile-wifi/hotspots/mr6450/", "Netgear M6 Pro 原廠頁（Sub-6／WiFi 6E）", ""],
["CELLULAR", "5G mmWave", "Netgear", "Nighthawk M6 Pro", "https://www.netgear.com/se/home/mobile-wifi/hotspots/mr6450/", "Netgear M6 Pro 原廠頁（mmWave＋Sub-6 雙連接）", ""]
]
"""
