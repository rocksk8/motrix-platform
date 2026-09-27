# 稽核：品牌設定、全新安裝預設、本公司字串守門（wip/h-branding 653662a1，主持子代理；基底 c006a2a0）（D，2026-09-27 23:59）

> 完整等級、讀碼優先；動到 conftest（fixture 層）。

## 0. 結論

- **必修 0、建議 1、觀察 2**。

## 1. 主持重點

| 項目 | D 的驗證 | 結果 |
|---|---|---|
| 上傳安全 | `helpers/branding.py`：格式只看檔頭（副檔名與 Content-Type 不看）；SVG／以 `<` 開頭的內容一律拒收；解碼只用檔頭判斷出的那一種解碼器（`formats=[fmt]`）；解碼前以檔頭尺寸擋解壓縮炸彈（單邊 4096、總像素上限），檔案上限 2MB；重新編碼時只複製像素建新圖（EXIF／ICC／文字區塊不帶過去、夾帶在 PNG 後的內容一併消失）；存放路徑固定 `uploads/branding/<種類>.png`，種類白名單。端點：上傳／恢復預設只限 superadmin、展示帳號拒絕、寫 audit；讀取公開、一律 `image/png`。突變 BR1「收 SVG」⇒ 紅；BR2「不重新編碼」⇒ 紅（3） | 成立 |
| 本公司字串守門與例外 | 掃 backend／frontend／tools 的文字檔；次數要完全相符；例外只能屬於五種類別、`frontend/` 不准登記；正對照（已知凍結 migration 那筆必須找到）＋兩種反向控制。突變 BR6「前端寫進公司網域」⇒ 紅。D 另查掃描範圍外的檔：`.vbs`、`.pyw`、字型都沒有本公司字樣；圖檔只有三張依使用者裁示保留的預設圖 | 成立（建議 BR-S1） |
| 全新安裝預設 admin 與 install_info | users 表空且無 install_info ⇒ 先寫 install_info 再建 `admin`（中斷也認得是全新安裝）；既有安裝（含正式機、V9 升級）⇒ 照舊只認 `jeff`，已存在就完全不動；不再每次啟動把 jeff 的 email 補回本公司信箱。保護點：原本寫死 `'jeff'` 的只有「刪除」「停用」兩個端點，現在一對一改成 `builtin_admin_username()`；後端其餘 `'jeff'` 只在凍結 migration（全新安裝沒有 jeff，不觸發）；前端改看後端的 `builtinAdmin`。突變 BR3「全新安裝仍建 jeff」⇒ 紅；BR4「刪除保護改回寫死 jeff」⇒ 紅 | 成立 |
| 版本紀錄的安裝基準 | 全新安裝只列安裝基準（manifest 最新一筆）之後的系統紀錄；既有安裝基準為空 ⇒ 全部顯示；`version_sort_key` 與最新版本共用（序號 `aa` > `z`）。突變 BR5「不過濾」⇒ 紅 | 成立 |
| conftest（fixture 層） | 新增一行把 `helpers.branding.UPLOADS_ROOT` 導到每題的 tmp（否則上傳題會把圖寫進開發機真的 `uploads/branding/`，變成開發機的 LOGO）；與既有三份 UPLOADS_ROOT 的做法一致 | 成立 |
| 其餘 | 相關題 159 過（品牌、安裝預設、字串守門、公司聯絡、升級工具、品牌 e2e）；突變 6/6 紅 | 成立 |
| CORE | 暫用 1.57，與建構器（f84fb2df）撞號 ⇒ 後合回的那包跑 `core_bump` 取 1.58 | 上車時處理 |

## 2. 發現

**BR-S1（建議）　字串守門的副檔名清單漏了 `.vbs`、`.pyw`**
- 兩者都是文字檔、會隨安裝包出貨（`backend/autostart_hidden.vbs`、`create_shortcut.vbs`、`tools/deploy_dashboard_ctl.pyw`）。現在沒有本公司字樣，但之後寫進去不會被掃到。
- 建議把掃描改成「git 追蹤的非二進位檔」，而不是列舉副檔名。

**觀察**
- **BR-O1**：預設管理員受保護的只有「刪除」「停用」；降級（改角色）、改帳號名稱從來沒有保護（改版前的 `jeff` 也一樣），不是本包造成的。全新安裝的預設管理員若被降級，系統可能沒有 superadmin。建議下一輪評估。
- **BR-O2**：三張預設圖（logo、logo-white、favicon）仍帶本公司字樣，依使用者裁示保留，客戶上傳後即取代；已登記在 `KEPT_DEFAULT_IMAGES`。
