"""一次性內容同步腳本：把 2026-08-10 這批 Omada 交換器選型導覽擴充內容同步到正式機。

**背景**：交換器選型導覽（switch_guide）原本只有 2 款 Omada 型號（SMART_L2PLUS 分類），
使用者指名 Omada 官網實際分成 8 大系列（Campus/Aggregation/Access Max/Access Pro/
Access Plus/Access/Agile/工業型），要求全部補齊。這批內容是透過 /api/switch-guide/*
直接寫進開發機 motrix_erp.db（不是改 switch_guide_seed.py），switch_guide 類別在正式機
早已存在資料，migration 的種子載入邏輯只在資料表全空時才會執行，故這批內容不會隨部署包
自動出現在正式機，需要另外跑這支腳本補上。

**分類設計**（詳見 SWITCH-GUIDE-CONTENT.md §1／§5「2026-08-10」條目）：既有 switch_categories
4 分類是跨品牌通用能力分級，這次額外新增 7 個 OMADA_ 前綴的 Omada 專屬系列分類（不是跨品牌
通用分類，這是詢問過使用者、刻意的設計取捨）；Omada 工業型（IES 系列 4 款）則併入既有的
通用 INDUSTRIAL 分類，與 Sbjlink/Moxa/Cisco IE-1000/Hirschmann 並列比較。

冪等：
  - switch_categories 用 code 比對，已存在就跳過（不覆蓋，避免蓋掉正式機上可能已有的人工修改）
  - switch_fit 用 (scenario_code, category_code) 比對，已存在就跳過
  - switch_products 用 (category_code, brand, model) 比對，已存在就跳過
可重複執行不會產生重複資料。

用法（於正式機 backend/ 目錄下執行，apply_update.ps1 套用完成之後）：
    python sync_2026-08-10_omada_switch_expansion.py

詳見 SWITCH-GUIDE-CONTENT.md §5「2026-08-10」條目。
"""
import json
import sqlite3

DB_PATH = "motrix_erp.db"

CATEGORIES = [
    dict(code='OMADA_CAMPUS', name='Omada Campus 園區堆疊 L3 交換器', keySpecs='24-48埠 GbE/2.5G/10G下行 + 4-6埠 10G/25G/100G上行，全L3 Managed，實體堆疊最多12台，M-LAG，部分PoE++（最高約1,534W）', tags='企業級,園區核心/匯聚層,可堆疊', priceRange='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', dependencyNote='定位為大型企業/校園網路的核心層或匯聚層，通常需搭配 Omada 硬體控制器/雲端管理及機架環境', watchNote='規格與價位皆高於一般商用機架式（MANAGED_L3分類），中小型專案容易 over-spec；與 MANAGED_L3 差異在原生支援實體堆疊與 M-LAG，跨機箱形成單一邏輯交換矩陣'),
    dict(code='OMADA_AGGREGATION', name='Omada Aggregation 光纖匯聚交換器', keySpecs='8-32埠全 10G/25G SFP+ 光纖埠，部分L3 Managed，無PoE供電（純光纖埠不具供電對象），機架式', tags='光纖骨幹,匯聚層,無PoE', priceRange='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', dependencyNote='多用於連接多台接取層交換器（Access系列）上行至核心層，需搭配光纖模組(SFP+/SFP28)與對應佈線', watchNote='純光纖設計，若專案接取設備仍以 RJ45 銅纜為主，需額外規劃光電轉換或改選 Access Plus/Pro 系列'),
    dict(code='OMADA_ACCESS_MAX', name='Omada Access Max 全10G接取交換器', keySpecs='全10G下行埠（RJ45或PoE++），搭配10G SFP+上行，PoE預算最高約770W，L2+管理，雲端集中管理', tags='Wi-Fi 7旗艦AP,10G到桌,高階接取層', priceRange='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', dependencyNote='官方定位為搭配旗艦級 Wi-Fi 7 AP 部署，需確認AP端也支援10G才能發揮效益', watchNote='屬本類別中埠級規格最高的接取層產品，若後端AP或用戶端設備仍是GbE，10G埠效益有限，容易over-spec'),
    dict(code='OMADA_ACCESS_PRO', name='Omada Access Pro 2.5G多G接取交換器', keySpecs='2.5G下行埠（多為PoE+/PoE++）+ 10G SFP+上行，PoE預算最高約770W(V2)，桌上型/機架型皆有', tags='Wi-Fi 6/入門Wi-Fi 7,2.5G多G,PoE++', priceRange='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', dependencyNote='官方定位對應 Wi-Fi 6 與入門 Wi-Fi 7 AP 的2.5G上行需求，埠數涵蓋8-24埠多種規模', watchNote='型號後綴 -M2 代表2.5G版本，選型時注意與同埠數GbE版本（Access Plus系列）的價差是否符合AP實際頻寬需求'),
    dict(code='OMADA_ACCESS_PLUS', name='Omada Access Plus 高密度GbE接取交換器', keySpecs='GbE下行埠（多PoE+/PoE++選項）+ 4-6埠10G SFP+上行，部分為Stackable(Lite) L3 Managed，埠數涵蓋24-48埠', tags='高密度邊緣層,GbE+10G上行,PoE選項多', priceRange='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', dependencyNote='系列內同時包含「Stackable Lite L3」（如 SG5452X 系列）與一般「Static Routing L2+」（如 SG3428X 系列）兩種管理層級，選型前需確認客戶是否真的需要堆疊功能', watchNote='同埠數下依 PoE 供電等級（PoE+/PoE++）與是否支援 Stackable 分出多種售價層級，報價前務必確認客戶實際需求對應到哪一個確切型號，避免直接套用整條產品線的價格區間'),
    dict(code='OMADA_ACCESS', name='Omada Access 基本接取交換器', keySpecs='基本GbE PoE/PoE+接取層交換器，埠數5-52埠選擇豐富，多數具Static Routing輕量L3功能，部分具戶外防水版本', tags='接取層主力,埠數選擇多,平價', priceRange='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', dependencyNote='本類別是 Omada 接取層最主力、型號數量最多的產品線，一般辦公室/店面/教室佈線首選', watchNote='SG2005P-PD 為系列中唯一具戶外防水設計的迷你款（明確 IP 等級未列出，需另外查證），其餘型號均為室內設計，勿誤用於戶外情境'),
    dict(code='OMADA_AGILE', name='Omada Agile 平價雲端網管交換器', keySpecs='GbE或2.5G(M2版本)下行埠，支援VLAN/QoS/迴圈防護/流量控制等基本網管功能，桌上型/壁掛/機架型皆有，多為外接變壓器供電', tags='非網管升級首選,平價,雲端網管入門', priceRange='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', dependencyNote='官方定位為「從非網管升級到雲端網管」的入門款，功能較 Access 系列陽春（無 Static Routing），但比 UNMANAGED 分類多了 VLAN/QoS 等基本網管能力', watchNote='與 UNMANAGED 分類的邊界：Agile 系列仍需透過 Omada App/雲端做基本設定，並非完全免設定隨插即用；與 Access 系列的邊界：Agile 不具備 Static Routing／ERPS 等進階功能'),
]

FIT = [
    ('OFFICE', 'OMADA_CAMPUS', '可用', '大型企業/多棟辦公園區的核心層可考慮，一般中小型辦公室規格與預算都嚴重過剩'),
    ('OFFICE', 'OMADA_AGGREGATION', '不建議', '純光纖匯聚交換器，一般辦公室機房不需要獨立匯聚層，直接用 Access 系列接上行即可'),
    ('OFFICE', 'OMADA_ACCESS_MAX', '可用', '若辦公室已佈建 Wi-Fi 7 旗艦AP需要10G上行可考慮，一般辦公室GbE AP已足夠'),
    ('OFFICE', 'OMADA_ACCESS_PRO', '適合', '2.5G多埠對應主流 Wi-Fi 6/7 AP 上行需求，中大型辦公室/會議室密集AP部署的理想選擇'),
    ('OFFICE', 'OMADA_ACCESS_PLUS', '適合', 'GbE埠數多、4-6埠10G上行，適合多樓層/高密度辦公室的接取層主幹'),
    ('OFFICE', 'OMADA_ACCESS', '適合', '基本GbE PoE接取層主力，埠數選擇豐富，多數中小型辦公室的預設選擇'),
    ('OFFICE', 'OMADA_AGILE', '適合', '小型辦公室/分支據點從非網管升級的入門選項，VLAN/QoS 已能滿足基本需求'),
    ('RETAIL', 'OMADA_CAMPUS', '不建議', '規格與空間需求都遠超單一店面所需，機架/堆疊架構對小坪數店面不適用'),
    ('RETAIL', 'OMADA_AGGREGATION', '不建議', '純光纖匯聚無PoE，店面POS/監控設備多需GbE PoE直接供電，此分類不適用'),
    ('RETAIL', 'OMADA_ACCESS_MAX', '不建議', '10G到桌對零售店面的POS/監控需求過度，預算效益不佳'),
    ('RETAIL', 'OMADA_ACCESS_PRO', '可用', '若店面有高密度監控/Wi-Fi 6 AP需2.5G上行可考慮，一般店面多數不需要'),
    ('RETAIL', 'OMADA_ACCESS_PLUS', '可用', '旗艦店/大坪數展示空間可用，一般小型店面弱電間空間有限，容易over-spec'),
    ('RETAIL', 'OMADA_ACCESS', '適合', '埠數選擇多、體積小的桌上型款式符合店面弱電間空間限制，PoE可直接供電POS/監控'),
    ('RETAIL', 'OMADA_AGILE', '適合', '平價雲端網管，連鎖店標準化佈建、VLAN隔離POS/監控/客用WiFi的常見選擇'),
    ('WAREHOUSE', 'OMADA_CAMPUS', '可用', '大型物流園區多棟倉庫的核心層可考慮，一般單一倉儲規格過剩'),
    ('WAREHOUSE', 'OMADA_AGGREGATION', '可用', '大型倉儲多棟/多樓層間光纖骨幹匯聚可用，中小型倉儲用不到獨立匯聚層'),
    ('WAREHOUSE', 'OMADA_ACCESS_MAX', '不建議', '倉儲場域的AP/掃描設備多為GbE即可，10G到端點過度且無PoE++以外優勢'),
    ('WAREHOUSE', 'OMADA_ACCESS_PRO', '可用', '若需高密度 Wi-Fi 6 AP覆蓋大坪數倉儲、且上行頻寬吃緊可考慮2.5G版本'),
    ('WAREHOUSE', 'OMADA_ACCESS_PLUS', '適合', '高密度邊緣部署設計本就針對大坪數場域，PoE預算足以支援多顆AP/攝影機'),
    ('WAREHOUSE', 'OMADA_ACCESS', '適合', 'AMR/掃描設備與監控多為GbE供電需求，埠數選擇多可依倉儲分區彈性部署'),
    ('WAREHOUSE', 'OMADA_AGILE', '可用', '小型倉儲/衛星倉可用平價方案，大型倉儲建議上 Access Plus 以上等級'),
    ('FACTORY', 'OMADA_CAMPUS', '可用', '大型廠區多棟廠房的核心/匯聚層可考慮，一般單一產線不需要'),
    ('FACTORY', 'OMADA_AGGREGATION', '可用', '多產線/多廠房間骨幹匯聚可用，需搭配光纖佈線規劃'),
    ('FACTORY', 'OMADA_ACCESS_MAX', '不建議', '一般產線設備不需10G頻寬，且無寬溫/防塵認證，不適合產線環境'),
    ('FACTORY', 'OMADA_ACCESS_PRO', '可用', '若產線需高密度AP/攝影機可考慮，但屬商用等級，非嚴苛環境仍建議評估 INDUSTRIAL 分類'),
    ('FACTORY', 'OMADA_ACCESS_PLUS', '可用', 'PoE預算充足適合多攝影機/感測器供電，但同樣是商用等級，非嚴苛環境限定使用'),
    ('FACTORY', 'OMADA_ACCESS', '不建議', '商用室內等級無寬溫/防塵/防震認證，產線電磁干擾與稼動率要求高的環境建議改選 INDUSTRIAL 分類'),
    ('FACTORY', 'OMADA_AGILE', '不建議', '入門商用等級不具備工業環境所需的寬溫與可靠度設計，不適合產線'),
    ('OUTDOOR', 'OMADA_CAMPUS', '不建議', '機架式商用等級，無戶外防護認證'),
    ('OUTDOOR', 'OMADA_AGGREGATION', '不建議', '純光纖機架式，無戶外防護認證'),
    ('OUTDOOR', 'OMADA_ACCESS_MAX', '不建議', '無戶外防護認證'),
    ('OUTDOOR', 'OMADA_ACCESS_PRO', '不建議', '無戶外防護認證'),
    ('OUTDOOR', 'OMADA_ACCESS_PLUS', '不建議', '無戶外防護認證'),
    ('OUTDOOR', 'OMADA_ACCESS', '可用', '系列內 SG2005P-PD 具戶外防水設計，可作小型戶外點位供電，其餘型號均為室內款式不適用'),
    ('OUTDOOR', 'OMADA_AGILE', '不建議', '無戶外防護認證，戶外情境請優先查場域選型導覽或本模組既有 INDUSTRIAL 分類'),
]

PRODUCTS = [
    dict(categoryCode='OMADA_CAMPUS', brand='TP-Link', model='Omada S7500-24Y4C', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '24× 25G SFP28 + 4× 100G QSFP28'], ['PoE 埠數／預算', '無'], ['管理層級', '全 L3 Managed'], ['堆疊', '實體堆疊最多 12 台，支援 M-LAG'], ['電源', '熱插拔冗餘電源'], ['說明', 'Campus 24埠25G堆疊式L3核心/匯聚交換器，4埠100G上行']]),
    dict(categoryCode='OMADA_CAMPUS', brand='TP-Link', model='Omada S7500-26XF6Y', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '26× 10G SFP+ + 6× 25G SFP28'], ['PoE 埠數／預算', '無'], ['管理層級', '全 L3 Managed'], ['堆疊', '實體堆疊最多 12 台，支援 M-LAG'], ['電源', '熱插拔冗餘電源'], ['說明', 'Campus 26埠10G堆疊式L3匯聚交換器，6埠25G上行']]),
    dict(categoryCode='OMADA_CAMPUS', brand='TP-Link', model='Omada S6500-48MPP6Y', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '48× 2.5G PoE++ + 6× 25G SFP28'], ['PoE 埠數／預算', '最高約 1,484W'], ['管理層級', '全 L3 Managed'], ['堆疊', '實體堆疊最多 12 台，支援 M-LAG'], ['電源', '熱插拔冗餘電源'], ['說明', 'Campus 48埠2.5G堆疊式L3 PoE++交換器，6埠25G上行']]),
    dict(categoryCode='OMADA_CAMPUS', brand='TP-Link', model='Omada S6500-24MPP4Y', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '24× 2.5G PoE++ + 4× 25G SFP28'], ['PoE 埠數／預算', '最高約 1,534W'], ['管理層級', '全 L3 Managed'], ['堆疊', '實體堆疊最多 12 台，支援 M-LAG'], ['電源', '熱插拔冗餘電源'], ['說明', 'Campus 24埠2.5G堆疊式L3 PoE++交換器，4埠25G上行']]),
    dict(categoryCode='OMADA_CAMPUS', brand='TP-Link', model='Omada S6500-48GP6XF', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '48× GbE PoE+ + 6× 10G SFP+'], ['PoE 埠數／預算', '最高約 1,440W'], ['管理層級', '全 L3 Managed'], ['堆疊', '實體堆疊最多 12 台，支援 M-LAG'], ['電源', '熱插拔冗餘電源'], ['說明', 'Campus 48埠GbE堆疊式L3 PoE+交換器，6埠10G上行']]),
    dict(categoryCode='OMADA_CAMPUS', brand='TP-Link', model='Omada S6500-48G6XF', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '48× GbE + 6× 10G SFP+'], ['PoE 埠數／預算', '無'], ['管理層級', '全 L3 Managed'], ['堆疊', '實體堆疊最多 12 台，支援 M-LAG'], ['電源', '固定電源'], ['說明', 'Campus 48埠GbE堆疊式L3交換器（無PoE版），6埠10G上行']]),
    dict(categoryCode='OMADA_CAMPUS', brand='TP-Link', model='Omada S6500-24GP4XF', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '24× GbE PoE+ + 4× 10G SFP+'], ['PoE 埠數／預算', '最高約 720W'], ['管理層級', '全 L3 Managed'], ['堆疊', '實體堆疊最多 12 台，支援 M-LAG'], ['電源', '熱插拔冗餘電源'], ['說明', 'Campus 24埠GbE堆疊式L3 PoE+交換器，4埠10G上行']]),
    dict(categoryCode='OMADA_CAMPUS', brand='TP-Link', model='Omada S6500-24G4XF', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '24× GbE + 4× 10G SFP+'], ['PoE 埠數／預算', '無'], ['管理層級', '全 L3 Managed'], ['堆疊', '實體堆疊最多 12 台，支援 M-LAG'], ['電源', '固定電源'], ['說明', 'Campus 24埠GbE堆疊式L3交換器（無PoE版），4埠10G上行']]),
    dict(categoryCode='OMADA_AGGREGATION', brand='TP-Link', model='Omada SX6632YF', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '26× 10G SFP+ + 6× 25G SFP28'], ['PoE 埠數／預算', '無（純光纖）'], ['管理層級', '全 L3 Managed'], ['堆疊', '實體堆疊，支援 M-LAG'], ['說明', 'Aggregation 26埠10G堆疊式L3匯聚交換器，6埠25G上行']]),
    dict(categoryCode='OMADA_AGGREGATION', brand='TP-Link', model='Omada SX3032F', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '32× 10G SFP+'], ['PoE 埠數／預算', '無（純光纖）'], ['管理層級', 'L2+/L3（依官網描述）'], ['說明', 'Aggregation 32埠10GE SFP+全光纖交換器']]),
    dict(categoryCode='OMADA_AGGREGATION', brand='TP-Link', model='Omada SX3016F', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '16× 10G SFP+'], ['PoE 埠數／預算', '無（純光纖）'], ['管理層級', 'L2+/L3（依官網描述）'], ['說明', 'Aggregation 16埠10GE SFP+全光纖交換器']]),
    dict(categoryCode='OMADA_AGGREGATION', brand='TP-Link', model='Omada SX3008F', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '8× 10G SFP+'], ['PoE 埠數／預算', '無（純光纖）'], ['管理層級', 'L2+ Managed'], ['說明', 'Aggregation 8埠10GE SFP+ L2+全光纖交換器']]),
    dict(categoryCode='OMADA_AGGREGATION', brand='TP-Link', model='Omada SG3428XF', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '20× GbE SFP + 4× GbE Combo + 4× 10G SFP+'], ['PoE 埠數／預算', '無（純光纖）'], ['管理層級', 'L2+/L3（依官網描述）'], ['說明', 'Aggregation 24埠GbE SFP交換器，4埠10G SFP+上行']]),
    dict(categoryCode='OMADA_ACCESS_MAX', brand='TP-Link', model='Omada SX3832MPP', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '24× 10G PoE++ + 8× 10G SFP+'], ['PoE 埠數／預算', '770W'], ['管理層級', 'L2+ Managed，Static Routing/ERPS'], ['說明', 'Access Max 32埠全10G交換器，24埠PoE++，雲端集中管理']]),
    dict(categoryCode='OMADA_ACCESS_MAX', brand='TP-Link', model='Omada SX3832', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '24× 10G RJ45 + 8× 10G SFP+'], ['PoE 埠數／預算', '無'], ['管理層級', 'L2+ Managed，Static Routing/ERPS'], ['說明', 'Access Max 32埠全10G交換器（無PoE版），雲端集中管理']]),
    dict(categoryCode='OMADA_ACCESS_MAX', brand='TP-Link', model='Omada SX3206HPP', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '4× 10G PoE++ + 2× 10G SFP+'], ['PoE 埠數／預算', '200W，單埠最高60W'], ['管理層級', 'L2+ Managed，Static Routing/ERPS'], ['說明', 'Access Max 6埠全10G小型交換器，4埠PoE++，雲端集中管理']]),
    dict(categoryCode='OMADA_ACCESS_PRO', brand='TP-Link', model='Omada SG3428XPP-M2', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '8× 2.5G PoE++ + 16× 2.5G PoE+ + 4× 10G SFP+上行'], ['PoE 埠數／預算', '770W(V2)'], ['管理層級', 'Access Pro 系列'], ['說明', '24埠2.5G + 4埠10G SFP+，24埠PoE++']]),
    dict(categoryCode='OMADA_ACCESS_PRO', brand='TP-Link', model='Omada SG3428X-M2', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '24× 2.5G + 4× 10G SFP+上行'], ['PoE 埠數／預算', '無'], ['管理層級', 'Access Pro 系列'], ['說明', '24埠2.5G交換器（無PoE版），4埠10G SFP+上行']]),
    dict(categoryCode='OMADA_ACCESS_PRO', brand='TP-Link', model='Omada SG3218XP-M2', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '16× 2.5G（4× PoE++ + 12× PoE+）+ 2× 10G SFP+上行'], ['PoE 埠數／預算', '240W'], ['管理層級', 'Access Pro 系列'], ['說明', '16埠2.5G + 2埠10G SFP+，混合PoE++/PoE+']]),
    dict(categoryCode='OMADA_ACCESS_PRO', brand='TP-Link', model='Omada SG3210XHP-M2', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '8× 2.5G PoE+ + 2× 10G SFP+上行'], ['PoE 埠數／預算', '240W'], ['管理層級', 'Access Pro 系列'], ['說明', '8埠2.5G PoE+ + 2埠10G SFP+']]),
    dict(categoryCode='OMADA_ACCESS_PRO', brand='TP-Link', model='Omada SG3210X-M2', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '8× 2.5G + 2× 10G SFP+上行'], ['PoE 埠數／預算', '無'], ['管理層級', 'Access Pro 系列'], ['說明', '8埠2.5G交換器（無PoE版），2埠10G SFP+上行，桌上/機架皆可']]),
    dict(categoryCode='OMADA_ACCESS_PRO', brand='TP-Link', model='Omada SG2210XMP-M2', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '8× 2.5G PoE+ + 2× 10G SFP+上行'], ['PoE 埠數／預算', '160W'], ['管理層級', 'Access Pro 系列（Fanless）'], ['說明', '8埠2.5G PoE+ + 2埠10G SFP+，桌上/壁掛型無風扇設計']]),
    dict(categoryCode='OMADA_ACCESS_PLUS', brand='TP-Link', model='Omada SG6654XHP', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '48× GbE PoE+ + 6× 10G SFP+上行'], ['PoE 埠數／預算', '最高1,440W'], ['管理層級', 'Stackable L3 Managed'], ['堆疊', '支援堆疊，選配雙冗餘電源'], ['說明', '48埠GbE堆疊式L3 PoE+交換器']]),
    dict(categoryCode='OMADA_ACCESS_PLUS', brand='TP-Link', model='Omada SG6654X', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '48× GbE + 6× 10G SFP+上行'], ['PoE 埠數／預算', '無'], ['管理層級', 'Stackable L3 Managed'], ['堆疊', '支援堆疊，雙冗餘電源'], ['說明', '48埠GbE堆疊式L3交換器（無PoE版）']]),
    dict(categoryCode='OMADA_ACCESS_PLUS', brand='TP-Link', model='Omada SG6428XHP', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '24× GbE PoE+ + 4× 10G SFP+上行'], ['PoE 埠數／預算', '最高720W'], ['管理層級', 'Stackable L3 Managed'], ['堆疊', '支援堆疊，選配雙冗餘電源'], ['說明', '24埠GbE堆疊式L3 PoE+交換器']]),
    dict(categoryCode='OMADA_ACCESS_PLUS', brand='TP-Link', model='Omada SG6428X', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '24× GbE + 4× 10G SFP+上行'], ['PoE 埠數／預算', '無'], ['管理層級', 'Stackable L3 Managed'], ['堆疊', '支援堆疊，雙冗餘電源'], ['說明', '24埠GbE堆疊式L3交換器（無PoE版）']]),
    dict(categoryCode='OMADA_ACCESS_PLUS', brand='TP-Link', model='Omada SG5452XMPP', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '8× GbE PoE++ + 40× GbE PoE+ + 4× 10G SFP+上行'], ['PoE 埠數／預算', '770W'], ['管理層級', 'Stackable Lite L3 Managed'], ['堆疊', '支援堆疊'], ['說明', '48埠GbE堆疊Lite L3 PoE++交換器']]),
    dict(categoryCode='OMADA_ACCESS_PLUS', brand='TP-Link', model='Omada SG5452X', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '48× GbE + 4× 10G SFP+上行'], ['PoE 埠數／預算', '無'], ['管理層級', 'Stackable Lite L3 Managed'], ['堆疊', '支援堆疊'], ['說明', '48埠GbE堆疊Lite L3交換器（無PoE版）']]),
    dict(categoryCode='OMADA_ACCESS_PLUS', brand='TP-Link', model='Omada SG5428XMPP', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '8× GbE PoE++ + 16× GbE PoE+ + 4× 10G SFP+上行'], ['PoE 埠數／預算', '500W'], ['管理層級', 'Stackable Lite L3 Managed'], ['堆疊', '支援堆疊'], ['說明', '24埠GbE堆疊Lite L3 PoE++交換器']]),
    dict(categoryCode='OMADA_ACCESS_PLUS', brand='TP-Link', model='Omada SG5428X', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '24× GbE + 4× 10G SFP+上行'], ['PoE 埠數／預算', '無'], ['管理層級', 'Stackable Lite L3 Managed'], ['堆疊', '支援堆疊'], ['說明', '24埠GbE堆疊Lite L3交換器（無PoE版）']]),
    dict(categoryCode='OMADA_ACCESS_PLUS', brand='TP-Link', model='Omada SG3452XMPP', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '8× GbE PoE++ + 40× GbE PoE+ + 4× 10G SFP+上行'], ['PoE 埠數／預算', '750W'], ['管理層級', 'L2+ Managed，Static Routing/ERPS'], ['說明', '48埠GbE + 4埠10G SFP+，混合PoE++/PoE+']]),
    dict(categoryCode='OMADA_ACCESS_PLUS', brand='TP-Link', model='Omada SG3452XP', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '48× GbE PoE+ + 4× 10G SFP+上行'], ['PoE 埠數／預算', '500W'], ['管理層級', 'L2+ Managed，Static Routing/ERPS'], ['說明', '48埠GbE PoE+ + 4埠10G SFP+']]),
    dict(categoryCode='OMADA_ACCESS_PLUS', brand='TP-Link', model='TL-SG3452X', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '48× GbE + 4× 10G SFP+上行'], ['PoE 埠數／預算', '無'], ['管理層級', 'JetStream L2+ Managed'], ['交換容量', '176 Gbps'], ['說明', 'JetStream系列48埠GbE L2+交換器，非Omada雲端管理平台，4埠10G SFP+上行']]),
    dict(categoryCode='OMADA_ACCESS_PLUS', brand='TP-Link', model='Omada SG3428XMPP', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '8× GbE PoE++ + 16× GbE PoE+ + 4× 10G SFP+上行'], ['PoE 埠數／預算', '500W'], ['管理層級', 'L2+ Managed，Static Routing/ERPS'], ['說明', '24埠GbE + 4埠10G SFP+，混合PoE++/PoE+']]),
    dict(categoryCode='OMADA_ACCESS_PLUS', brand='TP-Link', model='Omada SG3428XMP', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '24× GbE PoE+ + 4× 10G SFP+上行'], ['PoE 埠數／預算', '384W'], ['管理層級', 'L2+ Managed，Static Routing/ERPS'], ['說明', '24埠GbE PoE+ + 4埠10G SFP+']]),
    dict(categoryCode='OMADA_ACCESS_PLUS', brand='TP-Link', model='Omada SG3428X', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '24× GbE + 4× 10G SFP+上行'], ['PoE 埠數／預算', '無'], ['管理層級', 'L2+ Managed，Static Routing/ERPS'], ['說明', '24埠GbE交換器（無PoE版），4埠10G SFP+上行']]),
    dict(categoryCode='OMADA_ACCESS', brand='TP-Link', model='Omada SG2005P-PD', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '4× GbE PoE+輸出 + 1× GbE PoE++輸入(受電)'], ['PoE 埠數／預算', '64W'], ['防護', '戶外防水設計'], ['說明', '5埠迷你戶外防水交換器，PoE passthrough供電，系列中唯一戶外款']]),
    dict(categoryCode='OMADA_ACCESS', brand='TP-Link', model='Omada SG3452P', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '48× GbE PoE+ + 4× GbE SFP上行'], ['PoE 埠數／預算', '384W'], ['管理層級', 'Static Routing/ERPS'], ['說明', '52埠GbE PoE+接取交換器']]),
    dict(categoryCode='OMADA_ACCESS', brand='TP-Link', model='Omada SG3452', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '48× GbE + 4× GbE SFP上行'], ['PoE 埠數／預算', '無'], ['管理層級', 'Static Routing/ERPS'], ['說明', '52埠GbE接取交換器（無PoE版），無風扇靜音設計']]),
    dict(categoryCode='OMADA_ACCESS', brand='TP-Link', model='Omada SG3428MP', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '24× GbE PoE+ + 4× GbE SFP上行'], ['PoE 埠數／預算', '384W'], ['管理層級', 'Static Routing/ERPS'], ['說明', '28埠GbE PoE+接取交換器']]),
    dict(categoryCode='OMADA_ACCESS', brand='TP-Link', model='Omada SG3428', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '24× GbE + 4× GbE SFP上行'], ['PoE 埠數／預算', '無'], ['管理層級', 'Static Routing/ERPS'], ['說明', '28埠GbE接取交換器（無PoE版），無風扇靜音設計']]),
    dict(categoryCode='OMADA_ACCESS', brand='TP-Link', model='Omada SG3210', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '8× GbE + 2× GbE SFP上行'], ['PoE 埠數／預算', '無'], ['管理層級', 'Static Routing/ERPS'], ['說明', '8埠GbE小型接取交換器，無風扇靜音設計']]),
    dict(categoryCode='OMADA_ACCESS', brand='TP-Link', model='TL-SG3210', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '8× GbE + 2× GbE SFP上行'], ['PoE 埠數／預算', '無'], ['管理層級', 'JetStream L2+ Managed'], ['交換容量', '20 Gbps'], ['說明', 'JetStream系列8埠小型交換器，非Omada雲端管理平台']]),
    dict(categoryCode='OMADA_ACCESS', brand='TP-Link', model='Omada SG2452LP', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '48× GbE（32× PoE+）+ 4× GbE SFP上行'], ['PoE 埠數／預算', '230W'], ['管理層級', 'Static Routing'], ['說明', '52埠GbE接取交換器，32埠PoE+']]),
    dict(categoryCode='OMADA_ACCESS', brand='TP-Link', model='Omada SG2428P', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '24× GbE PoE+ + 4× GbE SFP上行'], ['PoE 埠數／預算', '250W'], ['管理層級', 'Static Routing'], ['說明', '28埠GbE PoE+接取交換器']]),
    dict(categoryCode='OMADA_ACCESS', brand='TP-Link', model='Omada SG2428LP', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '24× GbE（16× PoE+）+ 4× GbE SFP上行'], ['PoE 埠數／預算', '150W'], ['管理層級', 'Static Routing'], ['說明', '28埠GbE接取交換器，16埠PoE+']]),
    dict(categoryCode='OMADA_ACCESS', brand='TP-Link', model='Omada SG2218P', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '16× GbE PoE+ + 2× GbE SFP上行'], ['PoE 埠數／預算', '150W'], ['管理層級', 'Static Routing'], ['說明', '18埠GbE PoE+接取交換器']]),
    dict(categoryCode='OMADA_ACCESS', brand='TP-Link', model='Omada SG2218', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '16× GbE + 2× GbE SFP上行'], ['PoE 埠數／預算', '無'], ['管理層級', 'Static Routing'], ['說明', '16埠GbE接取交換器（無PoE版），無風扇靜音設計']]),
    dict(categoryCode='OMADA_ACCESS', brand='TP-Link', model='Omada SG2016P', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '16× GbE（8× PoE+）'], ['PoE 埠數／預算', '120W'], ['管理層級', 'Static Routing'], ['說明', '16埠GbE接取交換器，8埠PoE+，無風扇靜音設計']]),
    dict(categoryCode='OMADA_ACCESS', brand='TP-Link', model='Omada SG2210MP', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '8× GbE PoE+ + 2× GbE SFP上行'], ['PoE 埠數／預算', '150W'], ['管理層級', 'Static Routing'], ['說明', '10埠GbE PoE+接取交換器']]),
    dict(categoryCode='OMADA_ACCESS', brand='TP-Link', model='Omada SG2210P', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '8× GbE PoE+ + 2× GbE SFP'], ['PoE 埠數／預算', '61W'], ['管理層級', 'Static Routing'], ['說明', '10埠GbE PoE+小型接取交換器，無風扇靜音設計']]),
    dict(categoryCode='OMADA_ACCESS', brand='TP-Link', model='Omada SG2008P', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '8× GbE（4× PoE+）'], ['PoE 埠數／預算', '62W'], ['管理層級', 'Static Routing'], ['說明', '8埠GbE接取交換器，4埠PoE+，無風扇靜音設計']]),
    dict(categoryCode='OMADA_ACCESS', brand='TP-Link', model='Omada SG2008', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '8× GbE'], ['PoE 埠數／預算', '無'], ['管理層級', 'Static Routing'], ['說明', '8埠GbE接取交換器（無PoE版），無風扇靜音設計']]),
    dict(categoryCode='OMADA_ACCESS', brand='TP-Link', model='Omada SG2206MP', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '5× GbE（4× PoE+）+ 1× GbE SFP上行'], ['PoE 埠數／預算', '63W'], ['管理層級', 'Static Routing'], ['說明', '6埠GbE小型接取交換器，4埠PoE+']]),
    dict(categoryCode='OMADA_AGILE', brand='TP-Link', model='Omada ES210XPP-M2', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '8× 2.5G PoE++ + 1× 10G RJ45 + 1× 10G SFP+上行'], ['PoE 埠數／預算', '200W'], ['安裝', '桌上/壁掛，無風扇'], ['說明', '10埠2.5G雲端網管交換器，8埠PoE++']]),
    dict(categoryCode='OMADA_AGILE', brand='TP-Link', model='Omada ES210X-M2', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '8× 2.5G + 2× 10G SFP+上行'], ['PoE 埠數／預算', '無'], ['安裝', '桌上/壁掛，無風扇'], ['說明', '10埠2.5G雲端網管交換器（無PoE版）']]),
    dict(categoryCode='OMADA_AGILE', brand='TP-Link', model='Omada ES206XPP-M2', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '4× 2.5G PoE++ + 1× 10G SFP+上行'], ['PoE 埠數／預算', '120W'], ['安裝', '桌上/壁掛，無風扇'], ['說明', '6埠2.5G雲端網管交換器，4埠PoE++']]),
    dict(categoryCode='OMADA_AGILE', brand='TP-Link', model='Omada ES206X-M2', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '1× 2.5G + 1× 10G SFP+上行'], ['PoE 埠數／預算', '無'], ['安裝', '桌上/壁掛，無風扇'], ['說明', '6埠2.5G雲端網管交換器（無PoE版）']]),
    dict(categoryCode='OMADA_AGILE', brand='TP-Link', model='Omada ES228GMP', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '5× 2.5G'], ['PoE 埠數／預算', '384W'], ['安裝', '機架式'], ['說明', '28埠雲端網管交換器，含5埠2.5G']]),
    dict(categoryCode='OMADA_AGILE', brand='TP-Link', model='Omada ES228GP', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '5× 2.5G'], ['PoE 埠數／預算', '250W'], ['安裝', '機架式'], ['說明', '28埠雲端網管交換器，含5埠2.5G，較低PoE預算版']]),
    dict(categoryCode='OMADA_AGILE', brand='TP-Link', model='Omada ES224G', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '24× GbE'], ['PoE 埠數／預算', '無'], ['安裝', '桌上/機架，無風扇'], ['說明', '24埠GbE雲端網管交換器（無PoE版）']]),
    dict(categoryCode='OMADA_AGILE', brand='TP-Link', model='Omada ES220GMP', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '16× GbE'], ['PoE 埠數／預算', '250W'], ['安裝', '桌上/機架，無風扇'], ['說明', '20埠GbE雲端網管交換器']]),
    dict(categoryCode='OMADA_AGILE', brand='TP-Link', model='Omada ES220GP', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '16× GbE PoE+'], ['PoE 埠數／預算', '150W'], ['安裝', '桌上/機架，無風扇'], ['說明', '20埠GbE PoE+雲端網管交換器']]),
    dict(categoryCode='OMADA_AGILE', brand='TP-Link', model='Omada ES216G', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '16× GbE'], ['PoE 埠數／預算', '無'], ['安裝', '桌上/壁掛，無風扇'], ['說明', '16埠GbE雲端網管交換器（無PoE版）']]),
    dict(categoryCode='OMADA_AGILE', brand='TP-Link', model='Omada ES210GMP', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '8× GbE PoE+'], ['PoE 埠數／預算', '123W'], ['安裝', '桌上/壁掛，無風扇'], ['說明', '10埠GbE PoE+雲端網管交換器']]),
    dict(categoryCode='OMADA_AGILE', brand='TP-Link', model='Omada ES210GP', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '8× GbE PoE+'], ['PoE 埠數／預算', '63W'], ['安裝', '桌上/壁掛，無風扇'], ['說明', '10埠GbE PoE+雲端網管交換器，較低PoE預算版']]),
    dict(categoryCode='OMADA_AGILE', brand='TP-Link', model='Omada ES208GP', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '8× GbE PoE+'], ['PoE 埠數／預算', '64W'], ['安裝', '桌上/壁掛，無風扇'], ['說明', '8埠GbE PoE+雲端網管交換器']]),
    dict(categoryCode='OMADA_AGILE', brand='TP-Link', model='Omada ES208G', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '8× GbE'], ['PoE 埠數／預算', '無'], ['安裝', '桌上/壁掛，無風扇'], ['說明', '8埠GbE雲端網管交換器（無PoE版）']]),
    dict(categoryCode='OMADA_AGILE', brand='TP-Link', model='Omada ES206GP', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '4× GbE PoE+'], ['PoE 埠數／預算', '65W'], ['安裝', '桌上/壁掛，無風扇'], ['說明', '6埠GbE PoE+雲端網管交換器']]),
    dict(categoryCode='OMADA_AGILE', brand='TP-Link', model='Omada ES205GP', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '4× GbE PoE+'], ['PoE 埠數／預算', '65W'], ['安裝', '桌上/壁掛，無風扇'], ['說明', '5埠GbE PoE+雲端網管交換器']]),
    dict(categoryCode='OMADA_AGILE', brand='TP-Link', model='Omada ES205G', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '5× GbE'], ['PoE 埠數／預算', '無'], ['安裝', '桌上/壁掛，無風扇'], ['說明', '5埠GbE雲端網管交換器（無PoE版）']]),
    dict(categoryCode='INDUSTRIAL', brand='TP-Link', model='Omada IES210GPP', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '8× GbE（2× PoE++ + 6× PoE+）+ 2× GbE Combo上行'], ['PoE 埠數／預算', '240W'], ['工作溫度', '-40~75°C'], ['外殼', 'IP40 鋁合金外殼'], ['管理層級', '工業型 Easy Managed，雲端集中管理'], ['說明', '10埠工業型GbE交換器，8埠PoE+/PoE++混合']]),
    dict(categoryCode='INDUSTRIAL', brand='TP-Link', model='Omada IES206GPP', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '4× GbE（1× PoE++ + 3× PoE+）+ 2× GbE上行'], ['PoE 埠數／預算', '120W'], ['工作溫度', '-40~75°C'], ['外殼', 'IP40 鋁合金外殼'], ['管理層級', '工業型 Easy Managed，雲端集中管理'], ['說明', '6埠工業型GbE交換器，4埠PoE+/PoE++混合']]),
    dict(categoryCode='INDUSTRIAL', brand='TP-Link', model='Omada IES208G', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '6× GbE + 2× GbE Combo上行'], ['PoE 埠數／預算', '無'], ['工作溫度', '-40~75°C'], ['外殼', 'IP40 鋁合金外殼'], ['管理層級', '工業型 Easy Managed，雲端集中管理'], ['說明', '8埠工業型GbE交換器（無PoE版）']]),
    dict(categoryCode='INDUSTRIAL', brand='TP-Link', model='Omada IES206G', url='https://www.omadanetworks.com/us/business-networking/omada/switch/', label='', priceNote='官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價', specs=[['埠數', '4× GbE + 2× GbE上行'], ['PoE 埠數／預算', '無'], ['工作溫度', '-40~75°C'], ['外殼', 'IP40 鋁合金外殼'], ['管理層級', '工業型 Easy Managed，雲端集中管理'], ['說明', '6埠工業型GbE交換器（無PoE版）']]),
]

def sync_categories(conn):
    added, skipped = 0, 0
    max_sort = conn.execute("SELECT COALESCE(MAX(sort_order), -1) AS m FROM switch_categories").fetchone()["m"]
    for c in CATEGORIES:
        if conn.execute("SELECT 1 FROM switch_categories WHERE code=?", (c["code"],)).fetchone():
            skipped += 1
            continue
        max_sort += 1
        conn.execute(
            "INSERT INTO switch_categories (code, name, key_specs, tags, price_range, dependency_note, watch_note, sort_order, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,datetime('now'))",
            (c["code"], c["name"], c["keySpecs"], c["tags"], c["priceRange"], c["dependencyNote"], c["watchNote"], max_sort),
        )
        added += 1
    conn.commit()
    print(f"switch_categories：新增 {added} 筆，略過（已存在）{skipped} 筆")


def sync_fit(conn):
    added, skipped = 0, 0
    max_sort = conn.execute("SELECT COALESCE(MAX(sort_order), -1) AS m FROM switch_fit").fetchone()["m"]
    for scenario_code, category_code, fit_level, fit_note in FIT:
        if conn.execute(
            "SELECT 1 FROM switch_fit WHERE scenario_code=? AND category_code=?", (scenario_code, category_code)
        ).fetchone():
            skipped += 1
            continue
        max_sort += 1
        conn.execute(
            "INSERT INTO switch_fit (scenario_code, category_code, fit_level, fit_note, sort_order, updated_at) "
            "VALUES (?,?,?,?,?,datetime('now'))",
            (scenario_code, category_code, fit_level, fit_note, max_sort),
        )
        added += 1
    conn.commit()
    print(f"switch_fit：新增 {added} 筆，略過（已存在）{skipped} 筆")


def sync_products(conn):
    added, skipped = 0, 0
    for p in PRODUCTS:
        if conn.execute(
            "SELECT 1 FROM switch_products WHERE category_code=? AND brand=? AND model=?",
            (p["categoryCode"], p["brand"], p["model"]),
        ).fetchone():
            skipped += 1
            continue
        max_sort = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) AS m FROM switch_products WHERE category_code=?",
            (p["categoryCode"],),
        ).fetchone()["m"]
        conn.execute(
            "INSERT INTO switch_products (category_code, brand, model, url, label, price_note, specs_json, sort_order) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (p["categoryCode"], p["brand"], p["model"], p["url"], p["label"], p["priceNote"],
             json.dumps(p["specs"], ensure_ascii=False), max_sort + 1),
        )
        added += 1
    conn.commit()
    print(f"switch_products：新增 {added} 筆，略過（已存在）{skipped} 筆")


def main():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    sync_categories(con)
    sync_fit(con)
    sync_products(con)
    con.close()
    print("完成。")


if __name__ == "__main__":
    main()
