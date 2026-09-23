# MOTRIX ERP — 模組：報價／簽核／成本公式（§5 總述、§5.1–§5.3、§7.2、§7.13、§10）

> 自 `MOTRIX-ERP-QUICK.md` 拆出（2026-09-23）。§ 編號沿用原編號，程式註解裡的「QUICK.md §N」依中樞檔的對照表找到本檔。
> 內容逐字搬移，未改寫；相對連結已改為自本目錄起算。

---

## §5 · 核心業務流程

---

### §5.1 · 報價狀態機

```
草稿 → 待審核（送出）→ 已送出（簽核完成）
         ↑ 解鎖編輯儲存後強制回到待審核
```

- 單號：`MQ-YYYYMM-NNN`（`/api/next-quote-no`）
- 僅**草稿**可刪；其他狀態回 403
- **已送出**預設鎖定；superadmin 解鎖密碼後可改，儲存後重鎖並重送審
- 送出前驗證：`customerName` + `projectName` + **至少一項品項說明**不得空白
- 防重複送出：`submitting` flag，按鈕期間不可再觸發

---

### §5.2 · 案件進度 dealTag

```
未提供 → 已提供 → 未成案
                 → 已成案（確認後 UI 鎖定）
                 → 已結案（僅案件管理「完結案」）
```

- 欄位同步：`quotations.deal_tag`
- 日誌：`data_json.statusLog[]`；**`delegateNote` 寫入 audit_log**
- **未成案 / 已成案**（設為）：限 admin+ 操作
- **已成案**：報價單須先完成簽核（`status=='已送出'`）才可標記，否則 400（前後端雙重 guard，2026-08-05b）
- **已成案 → 其他（降級）**：限 **admin+**（前後端雙重 guard）
- **已結案（完結案）**：限 **superadmin**（2026-09-13 使用者裁示；前端「完結案」按鈕與
  「全部進度完成」的自動提示同步只給 superadmin）。先前是 admin+，與「已結案只有
  superadmin 能降級」不對稱——按得下去的人比按得回來的人多
- **已結案 → 其他**：限 **superadmin**
- **完結案前置條件（五項，任一未達成即 400 並通知相關簽核人＋最高管理員）**：
  ①執行管理進度 100% ②款項明細全部收齊 ③相關單據簽核完成（報價單／承攬商匯款申請／
  開票申請憑據／出貨單／請款單／**完工單**）④**成本精算已完結**（`settlement.status=='finalized'`）
  ⑤**額外支出無送審中**。③的完工單與④⑤是 2026-09-13 使用者裁示「結案前要確認案件進度、
  精算等這些全數完成」時補的——完工單是 DB v77 才有的模組，當初沒跟著加進清單。
  沒有精算資料／沒有階段／沒有款項的舊案件一律視為「無需檢查」，不會因為後來才有的
  欄位而永遠結不了案
- UI revert：取消確認時用 `$nextTick` 回滾 `_prevDealTag`

---

### §5.2b · 報價清單動態徽章（quotations.html）

`dealDisplayStatus(q)` 回傳 `{text, cls}`，依 `status + deal_tag` 組合：

| status | deal_tag | text | cls |
|--------|----------|------|-----|
| 草稿 | — | 草稿 | badge--draft |
| 待審核 | — | 審核中 | badge--pending |
| 簽核中 | — | 簽核中 | badge--signing |
| 已核准 | — | 已核准 | badge--approved |
| 已取消 | — | 已取消 | badge--danger |
| 已拒絕 | — | 已退回 | badge--rejected |
| 已送出/已確認 | 未提供/已提供 | 報價中 | badge--sent |
| 已送出/已確認 | 已提供 | 待決定 | badge--sent |
| 已送出/已確認 | 已成案 | 執行中 | badge--running |
| 已送出/已確認 | 未成案 | 未成案 | badge--lost |
| 已送出/已確認 | 已結案 | 已結案 | badge--settled |

---

### §5.2c · 報價單 PDF 匯出

**工具列按鈕邏輯**（三擇一顯示）：

| 條件 | 按鈕 | 說明 |
|------|------|------|
| `!q.quoteNo`（新增未儲存） | 預覽報價單（neutral） | 讓使用者確認版型格式 |
| `q.dealTag === '未成案'` | 預覽報價單（紅色） | 禁止匯出 |
| 其餘已儲存且非未成案 | 匯出 PDF（`directExport()`） | 系統後端產生，瀏覽器直接下載 |

管理員另有 **匯出次數** 獨立按鈕（`showExportLog()`，僅 admin+）。

---

### §5.3 · 簽核（tiers 並行層）

```
設定：system_settings.approval_flow → { tiers:[{order, approvers:[]}] }
送出：快照至 data_json.approval.tiers[]
規則：同層全員 approved → currentTier++；末層完成 → status=已送出 + PDF
退回：清除 approval，status=草稿
舊 steps[]：執行期動態轉 tiers
```

- 有流程：允許自簽（比對當層 username）
- 無流程（預設超管）：**禁止申請人自簽**
- 代理送審：`approval.delegateSubmitter` + `delegateNote` 同步寫入 audit_log

**系統內建組織鏈（2026-09-15 改版，`includeSubmitterManagerTier` 預設開）**

```
申請人部門主管  ──不是本人──▶ 就這一層，結束
      │本人
      ▼
處主管（該部門所屬處）──不是本人──▶ 第二層，結束
      │本人
      ▼
到頂：兩層都本人自簽 + 送出時知會其他在職 superadmin（approval_notice）
```

- 本人要簽的層標 `selfApproval:true`；`_exclude_requester()` **不剔除**這種項目
- 前端 `canApprove()`／`isCurrentTierApprover()` 有簽核層時不再排除申請人
  （排除規則只留在無簽核層的 superadmin fallback）
- 自訂層的 `department_manager`／`division_manager` 解析到申請人本人時同樣改為
  自簽（舊行為是靜默剔除 → 整層消失）
- 一次簽多層：同一人（或其代理人）連續當好幾層、且「簽下去該層就完成」時，
  前端在確認視窗講清楚並帶 `cascade:true`，後端 `cascade_self_tiers()` 一次蓋完

---

### §7.2 · 報價 / 簽核 / 精算

| Method | Path | 說明 |
|--------|------|------|
| GET | /next-quote-no | 認證必填 |
| GET/POST | /quotations | 列表（角色過濾）／建立 |
| POST | /quotations/case-activity | 案件管理列表「有新動態」提示用；body `{quote_nos:[...]}`，回傳各單號 case_updates/work_logs/daily_task_completions 三來源最新時間；非 admin 沿用 `/quotations` 同款角色過濾 |
| GET/PUT/DELETE | /quotations/{no} | DELETE 僅草稿；PUT 鎖定狀態需解鎖 |
| PATCH | /quotations/{no}/status | superadmin + 白名單狀態 |
| PATCH | /quotations/{no}/deal-tag | 同步 `deal_tag`；已成案降級需 admin+；已結案需 superadmin |
| PATCH | /quotations/{no}/case-record | 樂觀鎖 `_expectedUpdatedAt` → 409 |
| PATCH | /quotations/{no}/payment/{idx} | 收款標記；樂觀鎖 `_expectedUpdatedAt` → 409 |
| GET/PUT | /quotations/{no}/settlement | 精算；finalized 後非 superadmin 不可改 |
| GET | /quotations/{no}/finance-summary | 案件財務「應收應付總覽」彙總（2026-09-09）：應收/已收/未收＋承攬商匯款申請的已核准未匯款/已匯款/簽核中＋開票申請/請款單唯讀清單＋精算額外支出小計。**後三者刻意不併入合計**，理由見端點 docstring |
| GET | /quotations/{no}/pdf-download | Edge PDF |
| POST | /quotations/{no}/export | 記錄匯出人/時間 |
| GET | /quotations/{no}/updates | 動態 Tab 合併 feed（comments+work_logs+daily_tasks） |
| POST | /quotations/{no}/updates | 發布手動留言 |
| DELETE | /quotations/{no}/updates/{id} | 刪除留言（發文者或 admin+）|
| GET | /approval-queue | **admin+ 看全部；其他角色只回「自己送審的」與「簽核鏈裡有自己的」**（2026-09-15，`_queue_visible_to()`，過濾只有一處、套在組好的 items 上，新增單據類型自動被蓋到）|
| GET | /approval-queue/detail?type&id | 一筆待簽核項目的完整內容：屬於哪個案件、內容欄位、明細、**夾帶檔案**（含預覽類型）、**編修後的結果**。清單刻意不帶這些（上百筆會變慢），點開才拿 |
| POST | /quotations/{no}/approve \| reject | 並行層簽核 |
| POST | /approval-queue/reassign | **轉簽**（限 superadmin）：把一筆待簽核換人。`reason` 必填（空白→400）；只換**當層第一個尚未簽核**的人，已簽過的與後面幾層不動；非待審核／簽核中→409。支援 quotation／contractor_voucher／invoice_voucher／payment_request／shipping_note／completion_note |
| GET | /approval-history?month&q&scope&limit&offset | **簽核歷史**：建在 `audit_log` 上（不另開表）。`scope=mine` 任何人看自己、`scope=all` 限 admin+；`q` 同時比對單號／標籤（含客戶名）／備註內容／簽核人；回傳含 `months[]` 每月筆數 |

---

### §7.13 · 簽核代理人（DB v67，2026-08-28）

| Method | Path | 說明 |
|--------|------|------|
| GET | /approval-delegates | 列表（需登入） |
| POST | /approval-delegates | 新建委託（任何人可自助設定，superadmin 可代設） |
| PATCH | /approval-delegates/{delegate_id}/deactivate | 停用委託 |

核心解析邏輯 `helpers/tiered_approval.py::active_delegators_for()`；`check_approve_permission()`/`check_reject_permission()` 新增可選 `conn` 參數才會檢查代理權，5 個 router／10 個呼叫點皆已接上。

---

## §10 · 成本公式（報價）

```
售價 = CEILING(成本 × 1.05 / (1 − 毛利率), 5)
管銷分攤 = 稅前售價 × 10%
公益捐款 = 直接毛利 × 1%
```

`FORM_VERSION`：模板版號常數（如 V1.1），與單筆資料無關；**quotation-form.html 或其邏輯任何改動都須遞增**——小改版（欄位微調/樣式/文案）+0.1，大改版（版型結構/新增區塊/流程變更）+1。
