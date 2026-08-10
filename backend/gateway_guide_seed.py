"""閘道器與控制器選型導覽 — 第一批種子資料（僅在 gateway_scenarios 為空時，由
db.py 的 _m041_gateway_guide migration 執行一次）。之後新增內容一律透過管理後台／
API 寫入，不要回頭改這個檔案。資料形狀與 switch_guide／monitor_guide／access_guide
相同：情境 × 分類矩陣。詳見 GATEWAY-GUIDE-CONTENT.md。
"""

SCENARIOS_JSON = r"""
[
  ["OFFICE", "辦公室／機房", "一般辦公環境或小型機房，溫控與電力穩定，安裝空間通常有限"],
  ["RETAIL", "零售店面", "店面／展示空間，弱電間狹小、常與監控/POS 共用網路，人員進出頻繁"],
  ["WAREHOUSE", "物流倉儲", "倉儲/物流場站，涵蓋面積大、常需搭配 AMR/掃描設備，粉塵與溫差較office大"],
  ["FACTORY", "工廠產線", "產線/機電整合環境，PoE 供電需求高（攝影機/感測器/AP），電磁干擾與稼動率要求高"],
  ["OUTDOOR", "戶外／路側基礎設施", "戶外桿件、園區道路、半戶外雨遮等，溫濕度與防護門檻高，多數已在場域選型導覽涵蓋範圍內"]
]
"""

CATEGORIES_JSON = r"""
[
  ["OMADA_GW_WIRED", "Omada 有線 VPN 閘道器",
   "5-9埠GbE/2.5G/10G WAN/LAN，多WAN負載平衡最高10埠，全系列支援IPSec/PPTP/L2TP/WireGuard等VPN協定，雲端集中管理",
   "基礎必備,多WAN備援,VPN",
   "官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價",
   "需搭配 Omada SDN 生態系（App/雲端或硬體控制器）才能發揮集中管理效益，單機也可獨立設定使用",
   "同系列依埠數/頻寬（GbE vs 2.5G vs 10G）與WAN負載平衡埠數分出多種等級，選型時依實際WAN備援需求與連線裝置數挑選，避免直接套用整條產品線報價"],
  ["OMADA_GW_WIFI", "Omada Wi-Fi 整合閘道器",
   "路由器內建 Wi-Fi 6 AP（AX3000），6埠GbE（含1埠SFP），最高5埠WAN負載平衡，支援多種VPN協定",
   "路由+WiFi二合一,小型辦公/店面,省空間",
   "官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價",
   "適合不需要獨立AP、僅需單一設備涵蓋小坪數WiFi的場景；坪數較大或需漫遊(Mesh)覆蓋時仍建議另外佈建獨立 Omada AP",
   "目前官網僅單一型號（ER706W），選型彈性小於有線閘道器系列"],
  ["OMADA_GW_4G5G", "Omada 4G/5G 行動網路閘道器",
   "4G+ Cat6行動網路（最高300Mbps）+ Wi-Fi 6，部分型號具PoE供電輸出，行動網路與固網WAN自動備援/負載平衡",
   "行動網路備援,戶外可選,PoE供電",
   "官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價",
   "定位為主要WAN線路（固網）的備援/輔助方案，或作為無固網環境的主要連網手段；ER703WP-4G-Outdoor 具戶外防護，其餘為室內款",
   "目前官網僅列4G(Cat6)型號，尚無5G型號；速率上限300Mbps低於固網頻寬，作為長期主要WAN需評估頻寬是否足夠"],
  ["OMADA_GW_INTEGRATED", "Omada 整合型 3-in-1 閘道器",
   "單機整合控制器＋路由閘道＋PoE交換器三種功能，12埠GbE，最高4埠WAN，PoE預算110W，高安全VPN",
   "三合一,小型部署首選,免另購控制器",
   "官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價",
   "內建控制器功能，不需另外採購 OC200/300 等硬體控制器；適合裝置數量少、預算有限的小型專案",
   "PoE預算僅110W，若場域AP/攝影機供電需求較高（如多台4K攝影機或高功率AP）需另評估獨立交換器方案；目前官網僅單一型號（ER7212PC）"],
  ["OMADA_CONTROLLER", "Omada 硬體控制器",
   "集中管理 Omada AP／交換器／閘道器；依管理容量分四級：OC200(約25台)/OC220(約130台)/OC300(約700台)/OC400(1,000+ AP)",
   "集中管理,可管理容量分級,雲端存取",
   "官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價",
   "管理對象需為 Omada 品牌的 AP/交換器/閘道器；若專案已用 ER7212PC 等內建控制器功能的整合型閘道器，不需要再另購硬體控制器",
   "OC200/OC220 支援 PoE 直接供電（免額外變壓器），OC300/OC400 需搭配獨立電源；選型依實際管理裝置總數對照容量分級，避免超出容量規格導致效能下降"]
]
"""

FIT_JSON = r"""
[
  ["OFFICE", "OMADA_GW_WIRED", "適合", "各類辦公室最基本的閘道器需求，依規模挑選對應埠數/頻寬型號"],
  ["OFFICE", "OMADA_GW_WIFI", "適合", "小型辦公室單一設備整合路由+WiFi，省去額外佈建AP的成本"],
  ["OFFICE", "OMADA_GW_4G5G", "不建議", "辦公室通常已有穩定固網，非必要不需4G備援與內建天線的額外成本"],
  ["OFFICE", "OMADA_GW_INTEGRATED", "適合", "3合1整合路由+控制器+PoE交換器，小型辦公室一台搞定，適合無獨立機房的場地"],
  ["OFFICE", "OMADA_CONTROLLER", "適合", "通常安裝於總部/主辦公室機房，統一管理旗下所有場域的AP/交換器/閘道器"],

  ["RETAIL", "OMADA_GW_WIRED", "適合", "店面基本閘道器需求，依店面規模與WAN備援需求挑選埠數"],
  ["RETAIL", "OMADA_GW_WIFI", "適合", "小型店面整合路由+WiFi，省去弱電間空間與額外設備"],
  ["RETAIL", "OMADA_GW_4G5G", "可用", "快閃店/短期展店或固網申裝前的過渡期可用4G備援，一般常態店面不需要"],
  ["RETAIL", "OMADA_GW_INTEGRATED", "適合", "小坪數店面弱電間空間有限，3合1單機省空間又好維護"],
  ["RETAIL", "OMADA_CONTROLLER", "不建議", "單店規模用不到獨立控制器，應由總部集中管理"],

  ["WAREHOUSE", "OMADA_GW_WIRED", "適合", "倉儲基本閘道器需求，視倉儲規模挑選WAN負載平衡埠數"],
  ["WAREHOUSE", "OMADA_GW_WIFI", "可用", "小型倉儲辦公區可用，大坪數倉儲AP覆蓋需求建議另外佈建獨立AP搭配交換器"],
  ["WAREHOUSE", "OMADA_GW_4G5G", "可用", "偏遠倉儲固網不穩定時可作WAN備援，非必要不需要"],
  ["WAREHOUSE", "OMADA_GW_INTEGRATED", "可用", "小型倉儲附設辦公室可用，PoE預算(110W)對大型倉儲AP/攝影機數量而言偏低"],
  ["WAREHOUSE", "OMADA_CONTROLLER", "可用", "大型物流園區若設備數量多，可考慮設置獨立控制器就近管理"],

  ["FACTORY", "OMADA_GW_WIRED", "適合", "廠區基本閘道器需求，視產線規模挑選埠數與WAN負載平衡"],
  ["FACTORY", "OMADA_GW_WIFI", "不建議", "內建WiFi單一AP覆蓋範圍有限，產線環境電磁干擾與空間需求建議另外佈建獨立AP"],
  ["FACTORY", "OMADA_GW_4G5G", "可用", "偏遠廠區或固網申裝前可作WAN備援，一般廠區不需要"],
  ["FACTORY", "OMADA_GW_INTEGRATED", "不建議", "PoE預算(110W)對產線多攝影機/AP/感測器需求明顯不足，且非工業等級"],
  ["FACTORY", "OMADA_CONTROLLER", "可用", "大型廠區若設備數量多，可考慮設置獨立控制器就近管理"],

  ["OUTDOOR", "OMADA_GW_WIRED", "可用", "室內設計，可安裝於機房遠端管理戶外設備，本身不直接曝露戶外"],
  ["OUTDOOR", "OMADA_GW_WIFI", "不建議", "室內設計無戶外防護，且單一內建AP不適合戶外覆蓋"],
  ["OUTDOOR", "OMADA_GW_4G5G", "適合", "ER703WP-4G-Outdoor 為系列中唯一戶外防護款，適合路側/戶外據點的行動網路備援與WiFi涵蓋"],
  ["OUTDOOR", "OMADA_GW_INTEGRATED", "不建議", "室內設計無戶外防護"],
  ["OUTDOOR", "OMADA_CONTROLLER", "不建議", "室內設計無戶外防護，且戶外據點慣例由遠端控制器統一管理"]
]
"""

_PRICE = "官網未列價格（2026-08 查詢 omadanetworks.com），需洽代理商/經銷商報價"
_URL = "https://www.omadanetworks.com/us/business-networking/omada/router/"
_URL_CTRL = "https://www.omadanetworks.com/us/business-networking/omada-controller-hardware/"

PRODUCTS_JSON = r"""
[
  ["OMADA_GW_WIRED", "TP-Link", "Omada ER8411", "%(URL)s", "",
   "%(PRICE)s",
   "[[\"埠數\", \"2× 10G SFP+（WAN/LAN）+ 9× GbE（1× SFP、8× RJ45）\"], [\"USB\", \"2× USB 3.0\"], [\"WAN負載平衡\", \"最多10埠WAN\"], [\"連接裝置數\", \"最多1,000台\"], [\"VPN\", \"High-Security VPN\"], [\"說明\", \"全系列埠數/頻寬最高款，陖2埠10G SFP+，適合大型網路主閘道\"]]"],
  ["OMADA_GW_WIRED", "TP-Link", "Omada ER7412-M2", "%(URL)s", "",
   "%(PRICE)s",
   "[[\"埠數\", \"2× 2.5G RJ45 WAN/LAN + 10× GbE（2× SFP、8× RJ45）\"], [\"WAN負載平衡\", \"Multi-WAN Load Balance\"], [\"VPN\", \"High-Security VPN\"], [\"說明\", \"2.5G多WAN閘道器，適合中型辦公室/場域多線路備援\"]]"],
  ["OMADA_GW_WIRED", "TP-Link", "Omada ER707-M2", "%(URL)s", "",
   "%(PRICE)s",
   "[[\"埠數\", \"2× 2.5G RJ45（WAN/WAN-LAN）+ 5× GbE（1× SFP、4× RJ45）\"], [\"WAN負載平衡\", \"最多6埠WAN\"], [\"VPN\", \"High-Security VPN\"], [\"說明\", \"2.5G入門款多WAN閘道器\"]]"],
  ["OMADA_GW_WIRED", "TP-Link", "Omada ER7406", "%(URL)s", "",
   "%(PRICE)s",
   "[[\"埠數\", \"6× GbE（1× SFP、5× RJ45）\"], [\"WAN負載平衡\", \"最多5埠WAN\"], [\"VPN\", \"High-Security VPN\"], [\"安裝\", \"機架式/桌上型兩用\"], [\"說明\", \"GbE全埠閘道器，支援機架式安裝\"]]"],
  ["OMADA_GW_WIRED", "TP-Link", "Omada ER7206", "%(URL)s", "",
   "%(PRICE)s",
   "[[\"埠數\", \"6× GbE（5× RJ45、1× SFP）\"], [\"WAN負載平衡\", \"最多5埠WAN\"], [\"VPN\", \"High-Security VPN\"], [\"安裝\", \"桌上/壁掛/機架三用\"], [\"說明\", \"現行主力款，安裝彈性高\"]]"],
  ["OMADA_GW_WIRED", "TP-Link", "Omada ER605", "%(URL)s", "",
   "%(PRICE)s",
   "[[\"埠數\", \"5× GbE\"], [\"WAN\", \"最多3埠WAN + 1埠USB WAN\"], [\"VPN\", \"High-Security VPN\"], [\"WAN功能\", \"Multi-WAN Load Balance\"], [\"說明\", \"入門款小型閘道器，小型辦公室/店面首選\"]]"],

  ["OMADA_GW_WIFI", "TP-Link", "Omada ER706W", "%(URL_WIFI)s", "",
   "%(PRICE)s",
   "[[\"產品名稱\", \"Omada Gigabit AX3000 Wi-Fi 6 VPN Gateway\"], [\"Wi-Fi標準\", \"AX3000 Wi-Fi 6\"], [\"Wi-Fi速度\", \"最高3.0 Gbps（2,402 Mbps@5GHz，574 Mbps@2.4GHz）\"], [\"埠數\", \"6× GbE（含1× SFP）\"], [\"WAN負載平衡\", \"最多5埠WAN\"], [\"VPN\", \"IPSec/PPTP/L2TP/GRE/WireGuard/OpenVPN/SSL VPN\"]]"],

  ["OMADA_GW_4G5G", "TP-Link", "Omada ER703WP-4G-Outdoor", "%(URL_4G)s", "",
   "%(PRICE)s",
   "[[\"產品名稱\", \"Omada 4G+ Cat6 AX3000 Wi-Fi 6 Outdoor/Indoor Gateway\"], [\"行動網路\", \"4G+ Cat6，最高300 Mbps\"], [\"Wi-Fi\", \"AX3000 Wi-Fi 6\"], [\"電源\", \"1× GbE PoE入 + 2× GbE PoE出\"], [\"WAN\", \"4G與固網WAN自動備援/負載平衡\"], [\"防護\", \"戶外/室內兩用，系列中唯一戶外款\"]]"],
  ["OMADA_GW_4G5G", "TP-Link", "Omada ER706WP-4G", "%(URL_4G)s", "",
   "%(PRICE)s",
   "[[\"產品名稱\", \"Omada 4G+ Cat6 AX3000 Wi-Fi 6 Gigabit VPN Gateway with 4-Port PoE+\"], [\"行動網路\", \"4G+ Cat6，最高300 Mbps\"], [\"Wi-Fi\", \"3 Gbps Wi-Fi 6（HE160）\"], [\"電源\", \"4× GbE PoE+，45W PoE預算\"], [\"埠數\", \"1× SFP WAN/LAN + 5× RJ45\"], [\"天線\", \"5× 高增益可拆卸天線\"]]"],
  ["OMADA_GW_4G5G", "TP-Link", "Omada ER706W-4G", "%(URL_4G)s", "",
   "%(PRICE)s",
   "[[\"產品名稱\", \"Omada 4G+ Cat6 AX3000 Wi-Fi 6 Gigabit VPN Gateway\"], [\"行動網路\", \"4G+ Cat6，最高300 Mbps\"], [\"Wi-Fi\", \"3 Gbps Wi-Fi 6\"], [\"埠數\", \"1× WAN + 5× WAN/LAN\"], [\"天線\", \"5× 高增益可拆卸天線\"]]"],

  ["OMADA_GW_INTEGRATED", "TP-Link", "Omada ER7212PC", "%(URL_INT)s", "",
   "%(PRICE)s",
   "[[\"功能\", \"控制器 + 閘道器 + PoE交換器三合一\"], [\"埠數\", \"12× GbE\"], [\"WAN\", \"最多4埠\"], [\"PoE預算\", \"110W\"], [\"VPN\", \"High-Security VPN\"], [\"說明\", \"內建控制器功能，不需另購硬體控制器\"]]"],

  ["OMADA_CONTROLLER", "TP-Link", "Omada OC400", "%(URL_CTRL)s", "",
   "%(PRICE)s",
   "[[\"網路埠\", \"2× 10G SFP+ + 4× GbE RJ45\"], [\"USB\", \"2× USB 3.0\"], [\"管理容量\", \"最多1,000台AP、2× 200台交換器、100台閘道器\"], [\"雲端存取\", \"Cloud Access\"], [\"說明\", \"容量最高款，適合大型部署\"]]"],
  ["OMADA_CONTROLLER", "TP-Link", "Omada OC300", "%(URL_CTRL)s", "",
   "%(PRICE)s",
   "[[\"網路埠\", \"2× 10/100/1000 Mbps\"], [\"USB\", \"1× USB 3.0\"], [\"管理容量\", \"最多700台裝置（500 AP / 100 閘道器 / 100 交換器）\"], [\"雲端存取\", \"Cloud Access\"], [\"說明\", \"中高階容量，適合中型部署\"]]"],
  ["OMADA_CONTROLLER", "TP-Link", "Omada OC220", "%(URL_CTRL)s", "",
   "%(PRICE)s",
   "[[\"管理容量\", \"最多130台 AP/交換器/閘道器\"], [\"供電\", \"802.3af/at PoE 或 Micro-USB\"], [\"網路埠\", \"2× GbE\"], [\"散熱\", \"無風扇靜音設計\"], [\"說明\", \"支援PoE直接供電，免另外接變壓器\"]]"],
  ["OMADA_CONTROLLER", "TP-Link", "Omada OC200", "%(URL_CTRL)s", "",
   "%(PRICE)s",
   "[[\"網路埠\", \"2× 10/100/1000 Mbps\"], [\"供電\", \"802.3af/at PoE 或 Micro-USB\"], [\"管理容量\", \"建議管琥25台裝置\"], [\"雲端存取\", \"Cloud Access\"], [\"說明\", \"入門款，小型專案首選\"]]"]
]
""" % {
    "URL": _URL,
    "URL_WIFI": "https://www.omadanetworks.com/us/business-networking/omada-router-wifi-router/",
    "URL_4G": "https://www.omadanetworks.com/us/business-networking/omada-router-5g-4g-wifi-router/",
    "URL_INT": "https://www.omadanetworks.com/us/business-networking/omada-router-integrated-router/",
    "URL_CTRL": _URL_CTRL,
    "PRICE": _PRICE,
}
