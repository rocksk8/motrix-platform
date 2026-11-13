# 系統選單頁面截圖（唯讀擷取）

- 來源：本機隔離 dev 實例（pytest e2e fixture 起的 uvicorn、全新暫存 DB、superadmin 帳號 `h1_sa`），repo 版本 333ee073b（train/t79-int）。
- 瀏覽器：Playwright chromium、1440x900、淺色模式；每頁等 networkidle 後再等 1 秒。預設 full_page。
- 資料是空庫：無案件、無使用者以外資料，所以許多清單為空狀態。
- `_capture-notes.json`：擷取時記下的頁面標題、前 300 字、HTTP>=400／console error。

## 檔案對照

| 檔案 | 頁面 | 內容 |
|---|---|---|
| 00-menu-closed.png | index.html 頂欄（視窗，非整頁） | 主導覽列：儀表板／客戶與業務／案件／採購與庫存／報表／財務會計／勞務管理／我的工作／系統。「系統」是單一連結（`<a href=pages/system-hub.html>`），沒有下拉箭頭 |
| 00-menu-open.png | 同上，滑鼠停在「系統」 | 沒有出現下拉面板（「系統」群組在導覽列被收成單一連結，沒有子選單）。畫面與 closed 相同，僅「系統」文字轉紅 |
| 00b-menu-open-on-subpage-users.png | users.html（視窗） | 站在系統底下的子頁：「系統」底線標示目前位置；左側出現「系統」分類欄（8 個分類＋數量）；內容區頂有「← 系統」麵包屑 |
| 00c-menu-other-group-open-for-comparison.png | index.html，滑鼠停在「勞務管理」 | 對照：其他群組是下拉面板（外包名冊、勞報單） |
| 01-system-hub.png | system-hub.html | 系統中心：左側 8 分類（帳號與權限 5、簽核與流程 3、通知與信件 3、資料與備份 5、稽核與紀錄 3、公司與參數設定 5、模組與擴充 2、系統狀態與版本 2）；右側顯示所選分類的卡片（標題＋說明＋「影響：…」）；頂部搜尋框；藍色首次使用提示（「我知道了」）；底部一行說明可到設定中心調整是否列出無權限項目 |
| 01-system-hub-mobile.png | system-hub.html，390x844 | 手機寬度：主導覽列橫向捲動（右側被截斷於「報表」）；左側分類欄改為頁籤列（橫向捲動，截斷於「資…」）；卡片單欄 |
| 01c-users-mobile.png | users.html，390x844（視窗） | 手機寬度下系統子頁的外框 |
| 02-settings-center.png | settings-center.html | 設定中心：左側設定群組清單（約 50 個群組，另有「即將推出」區，每項標「預計 MS2～MS6 版提供」）；預設選第一組「變更管制」。整頁 2884px 高 |
| 02b-settings-center-group-login.png | 同上，選「登入與密碼」 | 兩個欄位（密碼最少碼數、登入有效天數）；有「目前設定／待生效／版本與變更紀錄／預設組」四個頁籤 |
| 02c-settings-center-group-retention.png | 同上，選「保存期限」 | 保存期限群組的欄位 |
| 03-notification-settings.png | notification-settings.html | Gmail SMTP 通知設定；「設定狀態：尚有 4 項待完成」 |
| 04-mail-settings.png | mail-settings.html | 信件與通知收件設定：每種信件一列的大表（信件／行事曆勾選、預設收件人、影響／建議處理、收件人下拉、儲存）。整頁 13654px 高，**改為視窗截圖（整頁 >1.5MB）** |
| 05-storage-settings.png | storage-settings.html | 儲存位置：雲端存檔根目錄、個資資料夾、更新交付資料夾 |
| 06-google-calendar-settings.png | google-calendar-settings.html | 依事件種類勾選自動建立的行事曆事件（分類：金額單據、案件…，各項標「預設開」） |
| 07-company-profile-settings.png | company-profile-settings.html | 公司資料：品牌與公司名稱、LOGO／favicon 上傳、基本資料與收款帳戶。整頁 6402px 高 |
| 08-module-settings.png | module-settings.html | 模組管理表（模組／版本／目前狀態／重啟後）；有「授權檢查未啟用（開發模式）」提示 |
| 09-legal-params.png | legal-params.html | 法規參數（勞報單扣繳率等）版本表；有一則警示「已進入 10 月，2027 年的法規參數…還沒有設定」 |
| 10-users.png | users.html | 使用者管理：統計卡、自訂角色管理、角色名稱設定、使用者表（依組織架構分組，目前全在「未分類」），每位使用者顯示一長串模組權限標籤；有「尚未設定組織架構」警示條 |
| 11-duty-roles.png | duty-roles.html | 職責角色說明與角色清單 |
| 12-org-structure.png | org-structure.html | 組織架構：空狀態「尚未建立任何處…」；有清單檢視／組織圖切換、返回使用者管理 |
| 13-approval-settings.png | approval-settings.html | 簽核流程設定：套用範圍（統一流程／獨立設定）、各單據流程；頁頂有「第一次來？」提示 |
| 14-expense-types.png | expense-types.html | 支出申請類型表（purchase_req、purchase_order、travel、petty_cash；版本欄顯示「程式預設（草稿欄位待確認）」） |
| 15-remit-kinds-settings.png | remit-kinds-settings.html | 匯款款別設定表（目前使用：出貨預設） |
| 16-audit-log.png | audit-log.html | 歷史紀錄：「共 1 筆操作紀錄」，下拉含大量動作類型 |
| 17-module-versions.png | module-versions.html | 版本紀錄：「依模組／時間軸」切換、「+ 新增」；空狀態「無符合結果／從左側選擇模組以查看版本歷史」 |
| 18-online-stats.png | online-stats.html | 在線時數統計：目前在線 1 人；「0 位成員有紀錄」；操作軌跡區。整頁 4122px 高 |
| 19-schema-status.png | schema-status.html | Schema 狀態：118/118「最新」＋migration 歷史清單（每筆含長篇說明文字）。整頁 14615px 高，**改為視窗截圖** |
| 20-module-builder.png | module-builder.html | 模組建構器：「開啟或建立模組」輸入列；空狀態「還沒有任何自訂模組」 |
| 21-file-center.png | file-center.html | 檔案中心：左側來源分類（各 0）、篩選列（PDF／圖片／日期／搜尋）、預設只查近 90 天 |
| 22-recycle-bin.png | recycle-bin.html | 刪除暫存區：0 筆；顯示隔離目錄路徑與儲存設定 |
| 23-lodging-records.png | lodging-records.html | 旅宿檔案更新：「尚未下載旅宿資料」；「旅宿資料下載未開啟（伺服器需設定 MOTRIX_LODGING_FETCH=1 並重啟）」；查詢紀錄空 |
| 24-shipping-export-history.png | shipping-export-history.html | 出貨單歷史紀錄：年份／月份篩選；「尚無符合條件的匯出紀錄」 |

## 擷取時看到的事項

- 「系統」在主導覽列是單一連結，滑過、點擊都沒有下拉；點擊直接進 system-hub.html（驗證：點擊後網址為 /pages/system-hub.html）。系統底下 24 頁的分類只在 system-hub 與子頁左側「系統」分類欄呈現。
- 所有頁都沒有 pageerror。HTTP 404（console error）只出現在 expense-types、remit-kinds-settings、module-builder，網址形如 `/api/def-governance/<kind>/_probe/ledger?scope=company`。
- full_page 截圖在長頁（例：02 設定中心）中，頂欄與左側分類欄是 fixed 元素，會出現在整頁圖的中間位置而非頂端（截圖工具的呈現，非實際版面）；設定中心截圖頂部約 100px 為空白（頂欄被移到圖中間）。
- 設定中心 02b：兩個數字輸入框在截圖時為空白，旁邊文字顯示「目前：8 碼」「目前：30 天」。
- 英文／技術字樣：schema-status 頁標題「Schema 狀態」、migration 名稱（`_m118_payslip_signed_paid` 等）與 SQL／程式字樣出現在說明文字中；expense-types 的代碼欄顯示 purchase_req 等；remit-kinds 代碼 deposit；mail-settings 每列顯示信件代碼（payslip_payable 等）；module-settings 顯示模組代碼（accounting）。
- 無獨立原始 JSON 框、無紅色錯誤橫幅；警示／提示條：legal-params（未設定 2027 參數）、users（尚未設定組織架構）、module-settings（授權檢查未啟用）、mail-settings（Google 行事曆未連線）。
- 頁頭樣式不一致處（事實）：多數頁有「← 系統／系統設定」眉標；audit-log、schema-status、lodging-records、shipping-export-history 只有「← 系統」；file-center、recycle-bin 眉標為「系統」。
- 手機寬度（390）的 01c／01 圖中，主導覽列是橫向捲動，沒有漢堡鈕（嘗試找 toggle 元素找不到）。
