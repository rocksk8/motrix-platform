# 第 31 班 31-C 稽核計畫（叫料審核／叫料匯款申請；作者 d7；稽核 c7）

被稽核：wip/t31-material-d7 @73e82a57（整合建包後以包內 SHA 為準）。規格：`modules/case/CHANGELOG.md`（next）與 `docs/platform/plans/MATERIAL-ORDER-APPROVAL-DESIGN.md`。
方法同第 30 班派發稽核：讀碼＋獨立探針（不重複作者的 material_* 測試），單檔單程序、不用 `-n`；斷言打在 DB／伺服器回應。migration 用**真基底庫**（prod/47db5613＋第 30 班）升級兩次。

## 讀碼階段已記下的待驗假說（尚未用探針證實）
- **H1 舊單實質編輯回草稿＝成本消失（同 dispatch S-1）**：寫入閘對「舊單（無疊加列）」的實質欄位變更走 `on_substantive_change`（舊單→草稿）。已出貨／已到料的舊叫料單被更正金額後，權責成本／總帳 E12 不再計入，直到重新送審核准。CHANGELOG 已預告「上線時報表數字可能變動」；要確認：舊單已有**已付**金額（舊「登記已付」資料）被實質編輯時，會不會出現「已付>0 的草稿單」、以及現金口徑是否仍計入。
- **H2 後門面**：`_gate_orders` 以資料庫現值為底；`actor=None`（系統／已結案變更核准套用）略過「誰能改」。要確認 actor=None 只有內部呼叫者能走，沒有任何使用者可控的路徑能讓 actor 變 None；以及**所有**寫入叫料／物流旗標的端點都過閘（含：報價單整份存檔、建立、複製／轉案、匯入、`PATCH /case-record`、已結案變更套用、其他模組直接寫 `data_json` 的路徑）。
- **H3 物流旗標**：只檢查 false→true；旗標由其他欄位推導（例如 `status`、`arrivedAt`）？同一 `materials[]` 列換 `orderItemId` 指到別案的已核准叫料單（`order_ids` 只含本案，已擋；驗證跨案連結）。`devices` 序號在被拒時維持原值（驗證實測）。
- **H4 has_payments 守門**：實質欄位變更／刪除／取消／作廢在「已有匯款申請」時被擋；`has_live_payments` 與 `has_any_payments` 的差異（作廢後可否改？作廢但已有付款明細呢？）。
- **H5 額度鎖（跨申請累計上限）**：兩個同時建立的申請各 70% 小計 ⇒ 不可雙雙成功（寫鎖是否涵蓋「讀已用額度→寫入」）；$0 叫料單不可開申請；舊單額度扣歷史已付；`overCapReason` 僅 superadmin；作廢／退回釋出額度（退回後再送審會不會超額）。
- **H6 自簽／自審**：與派發同一引擎（申請人也在簽核層／唯一簽核人可自簽——第 30 班觀察 O-1）；叫料匯款「多付審核」`remit.reviews`：登錄人不能自審（驗證出納端：登錄付款明細的人 ≠ 核可多付的人，含 superadmin）。
- **H7 個資（F2）**：收款帳戶只存申請 `snapshot_json`；稽核 `detail`、通知信、簽核佇列詳情、PDF、一般備份／JSON 匯出、錯誤訊息**全文不含帳號全碼**；畫面只給末四碼；`GET /api/material-suppliers` 只回 id／code／name；非有權者的遮蔽。
- **H8 PAID_VIA_REMITTANCE_ONLY=True**：上線後沒有任何路徑還能直接寫 `paidStatus/paidAmount/paidDate`（專屬 PATCH、case-record、報價單存檔、匯入、`cashier.js` 變更的呼叫端）；舊單歷史已付在第一張申請時凍結。
- **H9 下游一致性**：營運報表、應計（recognition）、總帳 E12／E12b、案件頁／精算合計對「草稿、已退回、已取消不計；待審核計入並標示；已核准與舊單照舊」是否同一條規則；現金口徑改讀付款明細後與舊單 JSON 讀法的切換邊界（同一張單不會兩邊都算或都不算）。
- **H10 角色矩陣**：superadmin、admin（有／無 project_manage 與財務檢視）、出納、一般 user（申請人）、簽核鏈成員、無關 user、停用帳號 × 每個端點（submit／approve／reject／withdraw／cancel／receive／payments create／patch／void、suppliers、列表）。
- **H11 migration 0004／0005**：真基底庫升級兩次：舊列不變、疊加表空（＝全部舊單）、唯一索引（`UNIQUE(quote_no,item_id,seq)`）、`integrity_check`、FK；回滾到舊程式能啟動且舊功能不壞。
- **H12 到貨確認不簽核**：記錄日期＋確認人＋時間；`DELETE …/receive`（撤銷）在已有「已到料」旗標或已有付款時的行為；誰能確認／撤銷。

## 探針與通過條件（整合建包後執行）
對每個假說寫 1～3 題獨立探針（`backend/tests/test_probe_t31c_material_c7.py`；刻意紅的題只在稽核分支、不進列車），輸出 PASS/FAIL＋必修／建議／觀察三級；以作者測試結果為基礎、只補縫。**不跑全量**。

## 依賴
整合建包後（platform 含 31-C）；與 a3 的演練錯開瀏覽器時段；不使用 `-n`。
