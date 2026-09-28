# 模組建構器第三輪：功能清單與同類產品調查（BUILDER-MARKET-RESEARCH）

> 2026-09-28 19:26 H3 起草（主持 hichan-28 派工）。依據：CORE-SPEC 裁示表「模組建構器第三輪：表單設計器（給未來管理者）」「建構器第三輪裁示」「建構器第三輪暫緩＋同類調查」三列（origin/platform 2e32977f）；設計見同分支 `docs/platform/BUILDER-FORMS-V3.md`（下稱 V3）。
> 範圍：**只做調查，不寫產品碼、不開實作**；等使用者說明後再定範圍。
> 規則：所有廠商資料取自官方文件／官方說明頁，查閱日期一律 **2026-09-28**；摘要為本檔自己的話；查不到或需付費才能看到的寫「未查證」，不推測。價格僅記官方頁當日公開值，會變動。
> 參考截圖 `D:\MOTRIX-DRILLS\handoff\builder-ref\forms-reference-1.png` 為第三方產品，**不進 repo、不進包**；本檔與日後實作都不得複製他牌 UI、圖示、文案。

---

## 1. 要做的事與要開發的功能

優先度：**P0**＝「報銷申請」能從建立表單→填單→送審→核准→輸出一路走完的必要項；**P1**＝同一輪應做、缺了可用但不完整；**P2**＝下一輪或待使用者確認。「來源」欄：使用者原話要求①～⑥、V3 差距編號 G*、19:15 裁示。

| # | 功能 | 內容 | 來源 | 優先 | 調查結論（§2） |
|---|---|---|---|---|---|
| F1 | 代號全自動 | 模組 key、權限 key、欄位 key、狀態／轉換 key 系統產生；改名不動代號；刪除不回收號碼 | ①、G1–G5 | P0 | 同類多為「自動產生＋可改」；我們決定不可改（§3 B1） |
| F2 | 進階唯讀檢視 | 系統代號摺疊、唯讀，供除錯與客服 | 裁示① | P1 | Jotform、Odoo 同型做法 |
| F3 | 單號前綴 | 自動產生、可改、發布後鎖定 | 裁示② | P1 | — |
| F4 | 右側「新增元素」面板 | 頁籤：新增元素／元素集合／屬性；完整預覽改由「預覽」按鈕拉出 | 參考圖、裁示⑥、G32 | P0 | 面板左右各家不一（Kintone、Zoho 在左；SurveyJS 可設定） |
| F5 | 段落／說明文字 | 不收值的純文字元素 | ③、G8 | P1 | Kintone「標籤」、Vital 等皆有 |
| F6 | 文字（單行／多行） | 多行、最長字數 | ③、G9–G10 | P0 | 普遍 |
| F7 | 數值 | 小數位、最小／最大 | ③、G11 | P1 | 普遍 |
| F8 | 金額 | 專屬型別、不可負、捨入一致 | ③、G12 | P0 | Frappe Currency、Odoo Monetary 有獨立型別 |
| F9 | 日期／日期時間＋「填單當下」 | 預設：無／填單當下／指定；可鎖定 | ③、G13–G15 | P0 | Kintone、Ragic、Zoho、Jotform、SurveyJS 均有；Jotform 有前端決定的已知陷阱（§3 N6） |
| F10 | 人員＋自動帶入申請人 | 預設：無／申請人；可鎖定；可選範圍 | ③、G16–G17 | P0 | Kintone「登入使用者」預設＋限定可選範圍最接近 |
| F11 | 下拉／單選／多選／是否 | 單選以顯示方式區分；多選存陣列 | ③、G18–G20 | P1 | 普遍 |
| F12 | 附件／圖片 | 獨立存放區、依模組權限的下載端點、檔頭檢查、檔數與大小上限 | ③、裁示③、G21–G22 | P0（收據） | 各家皆有；雲端產品存自家雲碟，我們是地端，不可依賴 |
| F13 | 明細列（重複列） | 報銷多筆；最少／最多列；新增一列 | ③、G26 | P0 | Kintone Table、Ragic 子表格、Zoho subform、Frappe Child Table、SurveyJS 動態矩陣、Form.io Data Grid |
| F14 | 自動加總 | 結構化設定「哪個明細．哪一欄．加總／平均／最大／最小／筆數」 | ③、G24 | P0 | SurveyJS column totals 五種聚合最接近 |
| F15 | 公式 | 以名稱籌碼編輯，存 key；白名單函式 | ③、G23 | P1 | 不採 JavaScript 計算（§3 N3） |
| F16 | 按鈕 | 只准 catalog 動作：轉換、新增一列、儲存草稿 | ③、裁示⑦、G25 | P1 | Odoo 把簽核掛在按鈕上，可參考 |
| F17 | 元素集合／範本 | 本輪只出內建「報銷申請」「費用申請」；管理者自存下一輪 | ④、裁示④、G27 | P0（內建）／P2（自存） | 同類普遍有範本庫；Google 有組織範本審核模式 |
| F18 | 分頁／區塊／兩欄 | 執行頁＝同一頁分段；區塊可設 1／2 欄；元素可佔整列 | ⑤、裁示⑤、G28–G30 | P1 | Zoho 1／2／3 欄；Forms 類的「區段」多用於跳題 |
| F19 | 表單標題與說明、⋮ 選單（複製／移動／刪除） | — | 參考圖、G31、G33 | P2 | — |
| F20 | 簽核串接 | 沿用既有狀態／分層／`when`；**調查新增建議**：以表單「人員」欄指定簽核人、以金額欄做門檻 | ⑥ | P1 | Ragic、Kintone、Jotform、鼎新皆支援欄位指定或金額分層（§3 B7） |
| F21 | 輸出 | 明細自動用既有 `items_table`＋`totals` | ⑥ | P1 | — |
| F22 | 權限 | 模組權限自動綁定；附件讀取與讀單同權限；鎖定欄由伺服器寫 | ①、裁示③ | P0 | — |
| F23 | catalog 唯一型別來源＋守門 | 元素、型別規格、範本、按鈕動作全由 catalog 提供；頁內不寫清單 | ⑥、G36 | P0 | SurveyJS 的「工具箱／屬性格可由設定產生」與此同向 |
| F24 | 既有草稿／已發布模組相容 | 只加不改；不做資料遷移 | ⑥、G35 | P0 | — |
| F25 | 條件顯示（欄位依他欄值顯示／隱藏） | **V3 未列**；同類幾乎全有 | 調查新增 | P2 | 待使用者決定（§5 Q4） |
| F26 | 行動端元件（手寫簽名、拍照、條碼） | **V3 未列** | 調查新增 | P2 | 台灣 BPM 廠商（Agentflow、Vital）列為賣點 |

不在本輪（裁示⑧）：分享、多語系、網格（矩陣選擇）、取消發布。

---

## 2. 同類產品調查

### 2.1 來源（查閱日期皆 2026-09-28）

| # | 產品 | 類別 | 官方網址（主要） |
|---|---|---|---|
| 1 | Microsoft Forms | 國際商用 | https://support.microsoft.com/en-us/forms/add-questions-that-allow-for-file-uploads-in-microsoft-forms ；https://support.microsoft.com/en-us/forms/use-branching-logic-in-microsoft-forms |
| 2 | Microsoft Power Apps（canvas） | 國際商用 | https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/working-with-forms ；https://learn.microsoft.com/en-us/power-apps/guidance/coding-guidelines/code-readability ；https://learn.microsoft.com/en-us/power-automate/get-started-approvals ；https://www.microsoft.com/en-us/power-platform/products/power-apps/pricing |
| 3 | Google Forms | 國際商用 | https://support.google.com/docs/answer/7322334 ；https://support.google.com/docs/answer/141062 ；https://support.google.com/a/users/answer/9308885 |
| 4 | Zoho Creator | 國際商用 | https://help.zoho.com/portal/en/kb/creator/developer-guide/forms/the-concept-of-forms/articles/form-builder ；https://help.zoho.com/portal/en/kb/creator/developer-guide/forms/add-and-manage-fields/articles/fields-date-time-set-initial-value ；https://www.zoho.com/creator/pricing.html |
| 5 | Jotform | 國際商用 | https://www.jotform.com/help/146-how-to-find-field-ids-and-names/ ；https://www.jotform.com/help/282-how-to-set-up-the-configurable-list-widget/ ；https://www.jotform.com/help/343-how-to-perform-form-calculation-in-the-input-table-field/ ；https://www.jotform.com/help/1414-how-to-set-up-an-approval-element-in-jotform-workflows/ ；https://www.jotform.com/form-templates/ ；https://www.jotform.com/pricing/ |
| 6 | Kintone | 國際商用（日） | https://us.kintone.help/k/en/app/form/design/set_form ；https://us.kintone.help/k/en/user/app_settings/form/form_parts/user_selection.html ；https://us.kintone.help/k/en/user/app_settings/form/autocalc/table_autocalc.html ；https://us.kintone.help/k/en/app/form/autocalc/ref_data/fieldcode ；https://get.kintone.help/k/en/app/form/form_parts/date.html ；https://us.kintone.help/k/en/app/form/form_parts/attachment ；https://get.kintone.help/k/en/user/app_settings/process/requiredsettings_process.html ；https://www.kintone.com/en-us/features/app-templates/ ；https://www.kintone.com/en-us/pricing/ |
| 7 | Airtable Interfaces／Forms | 國際商用 | https://support.airtable.com/articles/9641542433-airtable-interface-layout-form ；https://support.airtable.com/articles/9431794285-building-and-sharing-forms-in-airtable |
| 8 | Notion Forms | 國際商用 | https://www.notion.com/help/forms |
| 9 | Ragic | 台灣 | https://ragic.com/intl/zh-TW/doc/50/1 ；https://www.ragic.com/intl/zh-TW/doc/34 ；https://www.ragic.com/intl/zh-TW/doc/26 ；https://ragic.com/intl/zh-TW/doc/15 ；https://www.ragic.com/intl/zh-TW/pricing |
| 10 | SurveyCake | 台灣 | https://www.surveycake.com/tw/featureinfo?f=file-upload ；https://www.surveycake.com/zh-tw/pricing |
| 11 | 華苓 Agentflow | 台灣 BPM | https://www.flowring.com/agentflow/ |
| 12 | 叡揚 Vital BizForm | 台灣 | https://www.gsscloud.com/tw/vital-bizform |
| 13 | 鼎新 EasyFlow／BPM | 台灣 ERP／BPM | https://www.digiwin.com.tw/software/BPM/BPM |
| 14 | SurveyJS（Form Library＋Survey Creator） | 開源＋商用 | https://surveyjs.io/survey-creator/documentation/overview ；https://surveyjs.io/survey-creator/documentation/end-user-guide/how-to-use-column-totals-in-matrix-questions ；https://surveyjs.io/form-library/documentation/design-survey/conditional-logic ；https://surveyjs.io/licensing ；https://surveyjs.io/pricing |
| 15 | Form.io | 開源＋商用 | https://github.com/formio/formio.js ；https://github.com/formio/formio ；https://help.form.io/form-building/data-components ；https://help.form.io/form-building/component-settings |
| 16 | Formily（Alibaba） | 開源 | https://github.com/alibaba/formily |
| 17 | Frappe／ERPNext | 開源 | https://docs.frappe.io/framework/user/en/basics/doctypes/fieldtypes ；https://docs.frappe.io/framework/v14/user/en/basics/doctypes/docfield ；https://docs.frappe.io/framework/user/en/basics/doctypes/child-doctype ；https://github.com/frappe/frappe ；https://github.com/frappe/erpnext |
| 18 | Odoo Studio | 商用（Enterprise 限定） | https://www.odoo.com/documentation/19.0/applications/studio/fields.html ；https://www.odoo.com/documentation/19.0/applications/studio/approval_rules.html ；https://www.odoo.com/page/editions |
| 參考 | W3C WCAG 2.2 SC 2.5.7 | 標準 | https://www.w3.org/WAI/WCAG22/Understanding/dragging-movements.html |

共 18 家：官方文件有實質內容 18 家；其中台灣 BPM 三家（Agentflow、Vital、鼎新）只有產品頁、無公開操作手冊，細節多為「未查證」。

### 2.2 對照表 A：設計器與欄位

記號：✔ 有（官方文件寫明）；△ 部分／需額外設定；✘ 官方文件寫明沒有或題型清單未列；？ 未查證。

| 產品 | 元素面板位置 | 欄位代號對設定者 | 預設「填單當下」 | 人員自動帶入 | 金額型別 | 附件 | 明細列 | 明細加總 |
|---|---|---|---|---|---|---|---|---|
| MS Forms | ？ | ？（無代號概念的文件） | ？ | ？ | ✘ | ✔ 限組織內、每題≤10 檔、存 OneDrive | ✘ | ✘ |
| Power Apps | Insert＋右側屬性窗格 | 可見：控制項自動命名（例 EditForm1），官方建議手動改名 | △ Default 屬性寫公式 | △ 公式（函式未逐字查證） | ？ | ？ | △ Gallery／可編輯表格 | △ 公式 Sum |
| Google Forms | ？ | ？ | ✘ 文件未提預設值 | ✘ | ✘ | ✔ 需 Google 登入、存 Drive | ✘ | ✘ |
| Zoho Creator | 左：欄位面板；中：1／2／3 欄；右：屬性 | 可見可改（Field link name） | ✔ 初值 `zoho.currentdate` | △ `zoho.loginuser` 變數（腳本／規則） | ？ | ？ | ✔ Subform | ？（Creator 內建聚合未查證；CRM 子表單有） |
| Jotform | 「Add Element」面板 | **藏在 Advanced › Field Details**，可改 | ✔ Default Date＝Current | ？ | ？ | ？ | ✔ Configurable List（最少／最多列） | ✔ Form Calculation 可引用表格子欄 |
| Kintone | 左：欄位清單拖到右側表單 | 可見可改；改代碼時公式自動跟著改 | ✔ 勾選「預設為建立日期」 | ✔ 預設「登入使用者」＋限定可選範圍 | ？ | ✔ 單檔≤1GB | ✔ Table | ✔ `SUM(欄)`、列內計算 |
| Airtable | 欄位間「＋」插入 | ？ | ？ | ？ | ？ | ✔ 可限 MIME | ✘ 表單內不能新建連結紀錄 | ✘ |
| Notion | ？ | 題目＝資料庫屬性；可關閉「與屬性名同步」 | ？ | ？（有 People 題型） | ？ | ？ | ✘ | ✘ |
| Ragic | 試算表式設計模式 | ？ | ✔ `$DATE`／`$DATETIME` | ✔ `$USERNAME`／`$USERID`，可配唯讀 | ？ | ？ | ✔ 子表格（水平排標頭即建立） | ✔ 子表格公式 |
| SurveyCake | ？ | ？ | ？ | ？ | ✘ | ✔ PRO 起，存綁定的 Google 雲端硬碟，1／10／50MB | ✘ | ✘ |
| Agentflow | 拖拉元件 | ？ | ？ | ？ | ？ | ✔ 檔案上傳、拍照 | ？ | ？ |
| Vital BizForm | 所見即所得拖拉 | ？ | ？ | ？ | ？ | ✔ 圖片上傳 | ✔ 明細可加總 | ✔ |
| 鼎新 EasyFlow | Web 設計工具、RWD | ？ | ？ | ？ | ？ | ？ | △「支援明細」 | ？ |
| SurveyJS | 工具箱＋屬性格（兩者可設定顯示哪些） | 可見（`name` 必須唯一） | ✔ `defaultValueExpression: today()` | ？ | ？ | ✔（題型） | ✔ 動態矩陣／動態面板 | ✔ sum／count／min／max／avg |
| Form.io | 拖拉 builder | 可見：Property Name 依標籤自動駝峰、須唯一 | ？ | ？ | ？ | ？ | ✔ Data Grid／Edit Grid | △ Calculated Value（JavaScript） |
| Formily | 拖拉 Designer | ？ | ？ | ？ | ？ | ？ | ？ | ？ |
| Frappe／ERPNext | Form Builder | 可見：fieldname 與 label 分離 | ？ | ？ | ✔ Currency | ✔ Attach／Attach Image | ✔ Table（子 DocType） | ？ |
| Odoo Studio | 「Add」分頁拖曳 | **技術名 `x_studio_` 前綴，開發者模式才看得到／可改** | ？ | ？ | ✔ Monetary | ✔ File／Image | ✔ One2Many | ？ |

### 2.3 對照表 B：組織、範本、流程、授權

| 產品 | 條件顯示 | 分頁／區段／欄數 | 範本 | 簽核串接 | 授權與價格（官方公開值） |
|---|---|---|---|---|---|
| MS Forms | ✔ 分支（只能往後跳） | ✔ 區段 | ？ | △ 另用 Power Automate | ？ |
| Power Apps | ✔ 公式 | 多畫面 | ？ | △ Power Automate「Start and wait for an approval」，需 Dataverse | Premium 每人每月約 US$20；per app 自 2026-01-02 起部分通路不再新售 |
| Google Forms | ✔ 依答案跳區段（僅單選、下拉） | ✔ 區段 | ✔ 組織範本庫；管理員可設開放／審核／限管理員 | ✘ | ？ |
| Zoho Creator | ？ | ✔ 1／2／3 欄 | ✔ 可從範本建立 | ✔ 內建 approvals＋Blueprint（全方案） | 每人計價，三方案；金額本次讀取前後不一致 ⇒ 未查證 |
| Jotform | ？ | ？ | ✔ 20,000＋，含費用報銷類 | ✔ Workflows Approval：多步／平行、簽核人對應表單欄位、升級、逾期 | 依表單數與月提交數分級：免費、US$39、49、129／月、企業洽詢 |
| Kintone | ？ | 群組、標籤、空白 | ✔ 50＋範本，含 Expense Report；可把 app 存成範本 | ✔ 流程管理：狀態＋處理人＋動作；分支條件；全員／任一核准 | 每人每月：Professional US$16（原 24）、Custom US$20（原 28），最少 5 人（折扣限首購） |
| Airtable | ✔ 條件群組限 Business 以上 | ✔ 群組 | ？ | ✘ 表單文件未見 | 表單全方案；進階功能分級（金額未查證） |
| Notion | ✔ 限 Business／Enterprise | ？ | ？ | ✘ | 表單全方案；金額未查證 |
| Ragic | ？ | ？ | ？ | ✔ 固定人員、直屬主管、主管的主管、欄位指定、Email 外部；條件規則跳關；會簽／擇辦 | 每人每月：免費、簡易 5、專業 19、企業 55；另有依同時上線計價方案；**簽核需專業版以上**（幣別未查證） |
| SurveyCake | ✔ 跳題／接題（PRO，僅單選多選） | ？ | ？ | ✘ 定價頁未提 | 每月 NT$：PRO 1,099（年繳 750）、TEAM 3,399（年繳 2,150）、企業洽詢 |
| Agentflow | ？ | ？ | ✔ 範本庫 | ✔ 會簽、串簽、動態加簽、抽單、退回、跨流程 | 未公開 |
| Vital BizForm | ？ | ？ | ✔ 用印、報價、請購等 | ✔ 多關卡、代理人 | 未公開 |
| 鼎新 EasyFlow | ？ | RWD | ✔ 內建 164 張（OA、ISO 類） | ✔ 依金額分層、行動簽核、LINE、ERP 串接 | 未公開 |
| SurveyJS | ✔ 表達式 | ✔ 頁／面板 | ？ | ✘（需自接） | Form Library MIT；Creator 每開發者一次性 US$589／1,059／2,359 起，含 12 個月更新 |
| Form.io | ？ | ？ | ？ | ？ | formio.js（含 builder）MIT；伺服器 OSL-3.0；企業版另售 |
| Formily | ？ | ？ | ？ | ✘ | MIT；React／Vue 生態 |
| Frappe／ERPNext | ✔ `depends_on`、`mandatory_depends_on`、`read_only_depends_on` | Section／Column | ？ | ？（本次未查） | Frappe MIT；ERPNext GPL-3.0 |
| Odoo Studio | ？ | ？ | ？ | ✔ 簽核規則掛在按鈕上（Add an approval step）、指定群組 | Studio 僅 Enterprise |

### 2.4 各家重點（只記與我們有關的）

- **Kintone**：最接近使用者描述。左清單拖到右表單、欄位可調寬度；日期勾一個框就是「建立日期」、人員欄預設「登入使用者」且可限定可選名單；Table 欄位內可逐列計算、表外用 `SUM(欄)` 加總；流程管理＝狀態＋處理人＋動作。代號（field code）可見可改，改了公式會自動跟著改。
- **Ragic**：預設值用系統變數字串（建立日期、建立者、序號、最後修改者），常配「唯讀」；子表格用試算表方式建立；簽核人可取「直屬主管」「表單欄位」，可設金額門檻跳關。簽核綁在較高方案。
- **Jotform**：每欄都有 Unique Name，但放在 Advanced 分頁最底的 Field Details，平常看不到——「隱藏代號＋進階可看」的現成例子。已知陷阱：預先填好的連結會把「當天」固定成建立連結那天（官方回答中說明），證明「當下」要在送出時決定。
- **Odoo Studio**：技術名自動加 `x_studio_` 前綴，開發者模式才看得到——與我們裁示①相同取向；簽核規則掛在按鈕。Studio 只在 Enterprise 版。
- **SurveyJS**：工具箱與屬性格可由設定（UI preset JSON）決定顯示哪些型別與屬性——與我們「catalog 產生面板」同向；明細表欄合計提供五種聚合，選單式設定，不必寫式子。
- **Form.io**：Property Name 依標籤自動產生；計算值用 JavaScript，彈性大但安全面不可取。
- **Notion**：題目直接對應資料庫屬性，可讓題目文字與屬性名不同步——名稱與內部識別分離的另一種做法。
- **Airtable**：表單內不能新建連結紀錄，所以做不出「表單內加明細」；報銷類需求無法只靠表單完成。
- **台灣 BPM（Agentflow、Vital、鼎新）**：賣點集中在簽核型態（會簽、加簽、代理人、依金額分層、行動簽核／LINE）、內建表單範本數量、行動端元件（手寫簽名、拍照）；表單設計器細節無公開文件。

---

## 3. 可借鏡的設計方法與不宜採用之處

相容性：**相容**＝只動 `ui` 或 L1 既有設計內；**L1**＝需改 L1（升 CORE 次版號）；**L0**＝需改 L0；**不相容**＝與現行架構衝突。

### 3.1 可借鏡

| # | 方法 | 出處 | 我們的做法 | 相容性 |
|---|---|---|---|---|
| B1 | 代號與名稱分離、代號藏在「進階」 | Jotform（Advanced › Field Details）、Odoo（`x_studio_`＋開發者模式）、Notion（題目與屬性名可不同步） | 已裁示：進階區**唯讀**；比他牌更嚴——不可改（索引跨定義版本共用，改名會讓新舊單混義，V3 §2） | 相容（`ui` 層） |
| B2 | 預設值用「勾選／下拉」選「建立當下」「登入使用者」，不讓設定者打變數 | Kintone（勾選建立日期、選登入使用者） | 屬性面板給下拉：無／填單當下／指定；存成物件 token `{"$":"today"}`（V3 §3.3），UI 不出現符號 | L1（`custom_modules` 解析 token） |
| B3 | 「當下」與「申請人」由伺服器在送出時決定並可鎖定 | 反例 Jotform 已知陷阱；Ragic 預設值＋唯讀 | `locked` 欄伺服器忽略送來的值 | L1 |
| B4 | 人員欄可限定可選範圍 | Kintone Preset users | 第一版全部帳號；範圍（部門／群組）列 P2 | 相容（加 prop） |
| B5 | 明細合計用選單設定聚合方式 | SurveyJS column totals（加總／筆數／最小／最大／平均）、Kintone `SUM` | 「加總」元素選來源表＋欄＋方式，產生 `total()` 等白名單函式 | L1（`formula.FUNCTIONS`） |
| B6 | 明細資料結構：存成單據內 JSON 陣列 | SurveyJS 動態矩陣、Form.io Data Grid（皆為陣列值） | 採陣列＋索引只記列數（V3 §3.5）；**不採** Frappe 式獨立子表——後者利於跨單報表，但要改 L0 schema。若日後要「明細層級報表」，另開題 | 相容／L1 |
| B7 | 簽核人取自表單欄位、依金額分層 | Ragic（欄位指定、條件跳關、直屬主管）、Jotform（簽核人對應欄位）、鼎新（依金額分層） | 既有 `when` 已可用金額；**新增建議**：簽核層可指定「表單內人員欄」為簽核人；「直屬主管」需組織主管資料（現況未查，列 §5 Q2） | L1 |
| B8 | 元素面板、屬性面板由設定產生 | SurveyJS 工具箱／屬性格可設定 | catalog `formElements`＋`fieldTypeSpecs` 產生面板，守門雙向（V3 §7.2） | L1（catalog 登記） |
| B9 | 範本＝可插入的片段，插入後與範本脫鉤 | Kintone（從範本建 app、app 存成範本）、Google（組織範本庫＋審核模式） | 內建範本為程式資料；管理者自存（下一輪）可參考 Google 三段審核：開放／需核可／僅超管 | 內建：L1；自存：**L0**（`definitions.KINDS`） |
| B10 | 拖曳之外必有單指／鍵盤替代 | WCAG 2.2 SC 2.5.7（AA） | 點元素＝加到目前區塊末；卡片上下移按鈕、⋮ 選單「移到…」；Alt+↑↓ 沿用 | 相容 |
| B11 | 欄數可指定、手機一律單欄 | Zoho（1／2／3 欄） | 區塊 `cols: 1|2`；手機 1 欄 | 相容（`ui`） |
| B12 | 附件：每欄檔數上限、類型限制 | MS Forms（每題≤10 檔）、Airtable（MIME 限制） | `maxFiles≤10`、類型取 catalog 白名單交集＋檔頭檢查 | L1 |

### 3.2 不宜採用

| # | 做法 | 出處 | 不採的理由 |
|---|---|---|---|
| N1 | 預設值讓設定者輸入變數字串（如 `$DATE`） | Ragic | 違反「代號不必填、不必看」；打錯即靜默變成字面值 |
| N2 | 代號可改 | Kintone、Jotform、Odoo、Zoho | 我們的值索引以 key 跨版本共用；只提供唯讀 |
| N3 | 計算值用 JavaScript | Form.io Calculated Value | 等同讓管理者在伺服器／他人瀏覽器執行程式；維持 AST 白名單、不放寬節點 |
| N4 | 試算表式設計（在儲存格打標頭建欄位） | Ragic | 與使用者要的「拖曳元素即時顯示」心智模型不同；手機難操作 |
| N5 | 「當天」在前端或預填連結時決定 | Jotform 已知問題 | 會被固定成錯的日期、也可被竄改；一律伺服器決定 |
| N6 | 附件存到第三方雲碟 | MS Forms（OneDrive）、Google Forms、SurveyCake（Google 雲端硬碟） | 地端可販售產品不可依賴外部雲；已裁示獨立存放區＋權限端點 |
| N7 | 明細靠「連結另一張表」，表單內不能新增 | Airtable | 報銷要在同一張單內加多列 |
| N8 | 分支只能往後跳頁 | MS Forms | 我們執行頁是同頁分段；若做條件顯示（F25），用欄位層顯示／隱藏，不用跳頁 |
| N9 | 按鈕可綁任意動作／連結 | Power Apps（OnSelect 任意公式） | 已裁示只准 catalog 動作 |

---

## 4. 授權與條款注意

| 元件 | 授權（官方頁） | 對可販售產品的影響 | 建議 |
|---|---|---|---|
| SurveyJS Form Library | MIT | 可內嵌出貨，保留授權聲明 | 授權上可行；但它自帶渲染與型別體系，與我們 Alpine 執行頁、`custom-records.html` 渲染分支重疊 |
| SurveyJS Survey Creator（設計器） | 商用，每開發者一次性授權；官方稱免版稅再散布；更新與支援需年續 | 可販售，但每位開發者要買、續約才有新版；授權範圍（終端管理者使用設計器是否需額外授權）依官方 FAQ 摘要為「只需開發者授權」，**簽約前需法務逐字確認** | 不推薦：型別清單、JSON 格式都會變成他牌的，與「catalog 唯一來源」衝突 |
| Form.io formio.js（含 builder） | MIT | 可內嵌 | 同上；且計算值以 JavaScript 為核心（N3） |
| Form.io 伺服器 | OSL-3.0（copyleft） | 衍生作品需同授權；網路提供服務的適用範圍**未查證**，需法務 | 不採 |
| Formily | MIT | 可內嵌 | 需引入 React 或 Vue；不相容現行前端 |
| Frappe Framework | MIT | 可參考與取用 | 只借鏡設計（`depends_on` 三件組） |
| ERPNext | GPL-3.0 | 混入閉源販售品有傳染風險 | 不取用程式碼 |
| Odoo Studio | Enterprise 專屬 | 不可取用 | 只參考公開文件的概念 |
| 各家商用 SaaS（MS、Google、Zoho、Jotform、Kintone、Airtable、Notion、Ragic、SurveyCake、台灣 BPM） | 專有 | — | 只可參考概念；**UI 版面、圖示、配色、文案、範本內容一律不可照抄**；參考截圖不進 repo、不進包；內建範本的欄位與說明文字自己寫 |

結論：本輪**不引入任何第三方表單設計器**，沿用 V3 的自建路線（Alpine＋catalog＋既有 `custom-layout.js` 純函式）；開源專案只借鏡資料結構與互動模式。

---

## 5. 請使用者回答的問題

1. **第一版範圍**：§1 的 P0（代號自動、右側面板、金額、填單當下、申請人、附件、明細＋加總、內建兩個範本、權限、相容）是否就是第一版？附件（S5，約 1.5 人天）要不要延到第二版以縮短首發？
2. **簽核人來源**：除現有分層外，要不要支援「由表單內人員欄指定簽核人」與「申請人的直屬主管」？（後者需要組織主管資料，現況未盤點）
3. **管理者自存範本**（下一輪）：是否需要超級管理員核可才能給其他人用？
4. **條件顯示**（F25，同類幾乎全有、V3 未列）：要不要列入第三輪？
5. **行動端元件**（F26：手寫簽名、拍照）：是否有需求？
6. **是否考慮採購第三方設計器**（例 SurveyJS Creator）以加速？推薦：不採（§4）。

---

## 6. 調查限制

- 價格為 2026-09-28 官方頁公開值，含首購折扣者已註明；Zoho Creator、Airtable、Notion 金額未查證；台灣 BPM 三家未公開。
- 表中「？」皆為本次在官方公開文件中未找到或未逐字確認，不代表產品沒有。
- 未登入任何產品試用；未查看需付費或需登入才能看的內容。
