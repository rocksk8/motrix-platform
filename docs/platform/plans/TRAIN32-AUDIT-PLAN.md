# 第 32 包稽核計畫（稽核員 c7；作者 d7／2e／a3；基準 prod/a5dea50c）

被稽核：第 32 包（整合樹 `wip/train-32-int1`@f6873ae3，共 36 個提交、98 檔、+2710/−330；包建好後以包內 SHA 為準）。
方法同第 30／31 班：讀碼＋獨立探針（只補作者沒打到的縫，不重跑作者測試、不跑全量）；單檔單程序、不用 `-n`；斷言打在 DB／伺服器回應／真 DOM。等主持通知「第 32 包已發布」才執行。
**我是稽核員、不是這些項目的作者**；設計器（c7）本班只有 +13 行（選項上限 500 與提示），不在本計畫範圍，視為作者自審項。

## 0. 先記下的讀碼觀察
- **第 32 班沒有 migration**（`git diff a5dea50c..HEAD` 無 migrations 檔）⇒ 升級探針的預期是「除 `module_schema_versions` 外每張表逐列相同」；新功能只用既有欄位與 JSON 鍵。
- **d7 的三個 31-C 修正項（ack fail-closed、手續費上限、完整帳號端點可見性）不在整合樹的程式裡**：整合樹對 `material_payments.py`／`material_payment_cashier.py`／`material_payment.py` 的差異只有改字與「已對應採購單不可開匯款申請」一項。若包內仍沒有，稽核報告把這三項標為「**未修**（第 31 班建議 S-1／S-2／O-2 延續）」，不當作新缺陷。
- 派發 S-2（審核中取消）修正 `fix/t32-dispatch-cancel-2e`、S-1（舊單修改不重設）`fix/t32-dispatch-s1-2e`、改字 `wip/t32-wording-d7`、尚未送審 `wip/t32-unsent-d7`、連結接縫 `wip/t32-seam-d7`、S4a～e `wip/t32-s4a-2e`、請購單明細 `wip/t32-prpo-s1-2e`、applicant 說明 `wip/t32-applicant-help-a3` 都已在整合樹；`fix/t32-xe-e2e-harden`、`wip/t32-builder-mount-mywork-a3` 尚未合入（不在本包）。

## 1. 升級（真基準庫）
`docs/platform/audit/train32-probes/t32_mig_probe.py`：prod/a5dea50c 的程式＋loader 建庫，放入 31-C 的資料（材料申請審核列〔已核准／草稿〕、匯款申請含 `snapshot_json` 帳號、舊單材料、舊派發單與新派發草稿、已發布的 `expense_type travel v1` 含舊英文 help 字串、另一份草稿），用第 32 包程式升級兩次。
通過條件：每張舊表逐列雜湊相同（僅 `module_schema_versions` 可變）、欄位集合不變、無新表；已發布 travel v1 位元不變（只有程式預設那份的 applicant.help 改字，已發布版是發布當時的副本）；integrity ok、FK 0；第二次升級零變更。

## 2. 探針清單（逐項；括號＝作者已有測試，我只補縫）
### A. 材料申請連結（S4a～e＋seam）
| # | 探針 | 通過條件 |
|---|---|---|
| A1 | **po_line_taken 並發**：兩個同時送審，連到同一採購單行 | 恰一個 200、一個 400 `po_line_taken`；活的連結只有 1 筆（寫鎖內判定，不靠先讀後寫） |
| A2 | **bad_link 面**：連到他案的採購單、已作廢／駁回／草稿的採購單、不存在的單號、行號越界／負數／字串 | 一律 `bad_link`，該列被拒、不留殘列／草稿；`case-record` 整份存檔後門同樣被擋；`poLine` 一律整數 |
| A3 | **連結後不可開匯款申請**（409）；**有匯款申請不可改連結**（`has_payments`，專屬端點與 `case-record` 兩路） | 資料不變、回 `rejected[]` |
| A4 | **連結失效回金額**：已連有效採購單的材料申請不重複計入報表／GL；採購單作廢後金額回來、`noPo` 標記出現 | 報表（權責／現金）與總帳 E12／E12b 三處同一口徑；一筆採購只算一次 |
| A5 | **帶入扣量**：報價品項剩餘量＝計畫量−（已核准／待審核／簽核中／舊單材料申請＋採購單），草稿／已退回／已取消不計；超出需填原因 | 數字逐筆手算相符；`GET …/purchase-items`、送審上限、picker 三處同一份數字 |
| A6 | **權限／遮蔽**：`material-po-lines`、`link-status` 對無財務檢視者隱藏金額、外人 404；`case_read_scope.json` 登記 | 角色矩陣 |
| A7 | 簽核詳情「採購單連結／超出計畫」欄位不含金額洩漏、不被 XSS（`approval-queue.html` 輸出用 `x-text`） | 靜態＋注入字串 |

### B. 尚未送審（草稿）
| # | 探針 | 通過條件 |
|---|---|---|
| B1 | 一張草稿＋一張已核准：**報表（權責／現金）、總帳 E12／E12b、簽核佇列、`/api/approval-queue/count`（紅點）、匯款申請資格（409）、額度、案件頁「材料申請總額」** 都不含草稿 | 逐面斷言（作者只驗部分面） |
| B2 | 重整後新增未存的列不殘留；缺供應商等守門拒絕時一鍵送審不留殘列 | DB 無殘列／草稿審核列 |
| B3 | 離頁提示：`sidebar.js` 的 `motrixDirtyProbe` 掛鉤——其他頁行為不變；案件頁有未存材料申請時，成功的背景請求（心跳、已讀）**不**清掉警告；掛鉤丟例外時不拖垮 sidebar | e2e＋反向控制 |
| B4 | 已退回／待審核／已核准的標示不變（「尚未送審」只給新列與草稿） | 狀態矩陣 |

### C. 派發
| # | 探針 | 通過條件 |
|---|---|---|
| C1 | **舊單編輯不重設（S-1 裁示）**：舊單（`approval_status=''`）改承攬商／品項／人員／稅率 ⇒ 仍 `''`、`approval_json.legacyModified`（修改人／最後時間／次數／第一次時間）、稽核 `vendor.dispatch.legacy_edit`（前後金額）、成本檢視／應計／總帳 E04／匯款申請照舊計入 | 第 30 班探針 F1 反向：成本**不再消失** |
| C2 | 已核准派發實質編輯仍回草稿（不變）；非實質欄位不寫 `legacyModified`；次數累加；`dispatch.row.legacyModified/At` 新鍵 | 矩陣 |
| C3 | 有匯款申請的舊單仍不可編輯；`legacyModified` 不被使用者偽造（PUT body 帶也沒用） | 403／忽略 |
| C4 | **S-2 取消審核中的派發**：取消時關掉審核中那段、不在待簽佇列、紅點消失；`/approve` 對已取消 ⇒ 409 | 第 30 班探針 F2 反向 |
| C5 | UI：「舊單已修改」徽章與存檔提示只在舊單被修改後出現 | e2e 抽查 |

### D. 改字（叫料→材料申請）
| # | 探針 | 通過條件 |
|---|---|---|
| D1 | 全樹掃描：前端 html／js、後端回應文字（`HTTPException`、`_notify`、`_audit`、信件模板、PDF 字樣、報表欄名）中「叫料」殘留 | 只允許識別字（`material_order`、`materialOrders`…）與歷史資料；畫面上 0 |
| D2 | 實際打幾個端點（建立／送審／核准／退回／匯款）看回應與稽核 `detail`、通知內容、簽核佇列 `typeLabel`／`title` | 文字都是「材料申請」；舊稽核列照舊顯示（不回溯改） |
| D3 | 「已叫料」旗標顯示「已申購」、旗標被擋提示新文案；預設階段「材料申請出貨」只用於新案件 | 新舊案件各一 |
| D4 | 閘門邏輯不變（改字不改行為）：31-C 的 31 題探針（我的 `test_probe_t31c_material_c7.py`）原樣在新樹上重跑 | 結果與第 31 包一致（含 S-1／S-2／O-2 的狀態） |

### E. d7 的 31-C 修正項（若包內有）
| # | 探針 | 通過條件 |
|---|---|---|
| E1 | ack fail-closed：把 `privacy_notice.record_purpose_ack` 換成丟例外 | 建立回 5xx／409 且**無申請列**；有告知紀錄才算建立 |
| E2 | 手續費：`fee=1e12`（實付 100）與實付 1e15 | 手續費有上限或進審核；不直接入報表支出 |
| E3 | `payee-bank` 完整帳號端點：sa／admin（無出納）／admin2／cashier／boss／eng／out | 依裁示的角色集合；未裁示前列出矩陣 |

### F. 簽核佇列 `tags[]`（L1 加法）
| # | 探針 | 通過條件 |
|---|---|---|
| F1 | 每種佇列提供者（報價、材料、派發、請款、憑據…）的項目都有 `tags` 且是 list；沒帶＝`[]`；既有鍵不變 | 契約形狀；L1 快照只新增 |
| F2 | `tone` 只允許 `warn`／`info`；未申請採購單者有 warn 標註、已連結／舊單／$0 沒有；**標註文字不含金額、帳號、人名** | 資料外洩面 |
| F3 | 前端卡片與列表列用 `x-text`／轉義輸出 tags（注入字串探針） | 靜態＋e2e |
| F4 | 提供者丟壞 `tags`（None、字串、含非 dict）時不拖垮佇列頁 | 容錯 |

### G. 其他本班異動（抽查）
| # | 探針 | 通過條件 |
|---|---|---|
| G1 | 四份出貨請款類型預設定義與 a5dea50c 相比**只有 `applicant.help` 一個字串不同**；已發布的公司版（v≥1）位元不變；仍釘在 v0 的舊單據驗證與輸出不變 | JSON 逐鍵差異＝4 處 help |
| G2 | 請購單明細（32-S1）：`purchase_items`／`quotation-form.html`／`procurement.html` 的權限與金額遮蔽 | 角色矩陣（無財務檢視者看不到金額） |
| G3 | 帳務：`ledger/contract.py`、`voucher_attachments.py`、`ledger_annotations.py`、`recognition_basis.py` 的異動範圍與測試 | 讀碼＋作者測試抽查 |
| G4 | `core/CHANGELOG`／各模組 CHANGELOG 版號與 `version_manifest`（VR3 一模組一筆、(next) 已取號） | 機械守門 |

## 3. 突變（確認守門會紅；突變前先 commit）
M1 `po_line_taken` 檢查拿掉；M2 `MG.LINK_VALIDATOR` 不掛；M3 草稿也計入報表（`recognition` 把草稿算進去）；M4 `legacyModified` 不寫；M5 舊單編輯又回草稿；M6 `queue_tags` 回含金額文字；M7 `base_item` 不補 `tags`；M8 簽核佇列把草稿列入。
每個要對應一題會紅；沒有就列「守門有洞」。

## 4. 輸出
`docs/platform/audit/AUDIT-C7-train32.md`：PASS／must-fix／should-fix／觀察分開；「作者自審」項（設計器 +13 行）單列；未涵蓋清單；執行紀錄（各探針檔題數）。限時 90 分鐘，機器空時單程序執行。
