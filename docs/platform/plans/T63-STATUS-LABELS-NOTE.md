# T63 狀態顯示尾巴（status-display leftovers）：耦合清單與範圍

> 日期：2026-10-14　分支 `wip/t63-status-labels-r1`（基底 `origin/wip/t62-int-c1` 1632e94fb）　僅讀碼；本批只做 py_compile／import 檢查，不跑 pytest。
> 前置：S-X2（`helpers/status_display.py`、`static/status-chip.js`、`GET /api/status-display`；設計 `STATUS-DISPLAY-INVENTORY-T62.md`）。**沿用同一張受治理的表**：鍵由程式擁有、值永遠是原始值、旗標 `builder_status_display.enabled` 預設關、關＝與今天逐位元相同。
> 來源：hichan-6c 對帳 `t62-vs-six-slices.md` 第 2 列與「Genuinely NOT in T62 #5」：PDF 浮水印字、`notif.js`、dev-crm／approval-queue／devices 頁、「SQL／GL／獎金仍用原始值」的守門測試。

## 0. 逐點查證結果（結論先行）
只有 **dev-crm** 真的有「原始狀態值直接印在畫面上」的徽章，可以接；其餘四處查證後**不是狀態徽章**，不接（理由見 §2）。守門測試（§3）全新增。

| # | 位置 | 今天印的是什麼 | 決定 |
|---|---|---|---|
| 1 | `pages/dev-crm.html`（開發案件 CRM） | 案件狀態徽章 `c.status`（:621-622）、詳情徽章 `selectedCase.status`（:766-767）、歷史列 `hc.status`（:1080）、記錄狀態快照 `log.statusSnapshot`（:982）、漏斗標籤「未成案」（:490-493）、兩個狀態 `<select>` 的選項文字（:935、:1088，**文字＝值**，要拆開） | **接（只換字，色與 class 不動）** |
| 2 | `static/notif.js` `actionLabel`（:503-531） | 稽核**動作代碼**的中文（`quotation.approve→簽核通過`、`deal_tag.change→案件進度` …），不是狀態值 | **不接**：動作名稱不是狀態鍵；通知本文由伺服器產生（S-X3 通知用語範本已涵蓋） |
| 3 | `pages/approval-queue.html` | 沒有任何「原始狀態值」徽章。只有：確認視窗句子的 `finalStatus`（'已核准'／'已送出'／'待發放'，:1765-1768，句內文字）、靜態說明句（'已拒絕' 狀態 :1028）、簽核人進度（'已簽核'／'等待簽核中'，由 `a.status==='approved'` 衍生）、自訂模組 `item.statusLabel`（伺服器回的另一個領域） | **不接**：句子與衍生進度不是狀態徽章（同 `INVENTORY §7.2.1` 的文字規則）；自訂模組有自己的標籤 |
| 4 | `pages/devices.html` | 「保固狀態」`wbLabel(d)`（:483 `已過期 N 天` 等），由到期日**計算**出來；統計格 `expired` 等是篩選軸 | **不接**：衍生狀態（同出納「已逾預定日」的處理），不是資料庫狀態值；也不在 `STATUS_KEYS` |
| 5 | PDF／畫面預覽「浮水印」`pdf_gen._quote_watermark_kwargs`（:639-651）與 `_unapproved_banner` | 浮水印文字是**固定句子**（「報價單預覽稿　尚未正式生效」「本案報價未成立　僅供存查備存」），不是狀態值；橫幅只印 `status or "草稿"`（客戶可見的未核准警示） | **不接，維持固定語彙（PM 已決定不可設定）**：①`pdf_gen.py:1971` 明定「核可狀態由程式決定、不由版型決定」，未核准警示的字若可被改名，客戶可能看不出文件尚未核准；②盤點 §2B 已定「郵件／PDF／錯誤訊息是固定語彙，第二期選配」；③客戶可見文字的任何變更＝放寬（G-A 的頁尾／浮水印已走第二位核准）。見 §4 |

## 1. 接 dev-crm：做法與耦合
- **新鍵（程式登錄，仍是 display-only）**：`洽談中`、`成案`、`暫擱置`（群組 `devcase`，語意 plain，預設色調 neutral）。`未成案` **沿用既有的 deal 鍵**（同一個字、同一個意思）；管理者改了『未成案』的名稱，dev-crm 也跟著（可接受，編輯器的群組說明明說）。
- **情境**：dev-crm 用既有情境 `case`（開發案件是成案前的階段），不新增情境槽（新增情境會動 `CONTEXTS`、編輯器與公開回應形狀，不值得）。
- **官方用語保護**：三個新鍵（與沿用的『未成案』）都不是 approved／paid 語意；名稱不可含官方用語的規則照舊（plain 鍵）。
- **只換字**：徽章 class（`dc-badge--won/lost/hold/talk`）不動（色調對應留下一批，與 `rb-*` 同理）。
- **邏輯不動**：`c.status==='成案'`、`filterStatus`、`caseCount()`、`changeStatus(status)`（PATCH body 送原始值）、`hasTemp()`、`/api/dev-cases/{id}/status` 與 SQL 一律用原始值。顯示字只進 `x-text`，**不進任何比較、篩選、請求本文**。
- **`<select>` 選項**：`<option>洽談中</option>` 的值＝文字。改成 `<option value="洽談中" x-text="stLabel('洽談中')">洽談中</option>`（靜態文字保留當後備；`x-model` 綁的仍是原始值）。
- **載入**：頁面加 `static/public-flags.js`、`static/status-chip.js`，`init()` 內 `if (window.MotrixStatus) window.MotrixStatus.init()`（旗標關 ⇒ 不發 `/api/status-display`、什麼都不改）。
- **OFF 證明**：`stLabel(raw, fallback)` 在表未載入時回 `fallback`／原值，每個改過的運算式與原運算式逐字相同（守門測試以 node 驗）。

## 2. 後端耦合（必須維持原始值，不可讀這張表）
沿用 `INVENTORY §2A`：`deal_tag`（`arap/gl_events.py`、`arap/receivables.py`、`arap/api/cashier.py`、`case/recognition.py`、`case/api/settlement_api.py`、`case/api/quotations.py`、`payroll/api/bonus.py`、`db.py`、`pdf_gen.py`）與審核狀態（`helpers/approval_queue.py`、結案閘門、`accounting/voucher.py`、`db.py` CHECK）。dev-case 狀態另有 `/api/dev-cases/*` 路由與 SQL（`洽談中／成案／未成案／暫擱置`），同樣一律用原始值。

## 3. 守門測試：`backend/tests/test_status_display_canonical_lint_2026_10_14.py`
1. **後端**：除白名單（`helpers/status_display.py`、`routers/status_display.py`、`core/*` 登錄與設定中心的編輯面）外，任何後端模組（含 `modules/arap`、`modules/accounting`、`modules/payroll`、`modules/case`、`db.py`、SQL 字串）**不得 import `helpers.status_display`**——SQL／總帳／獎金不可能讀到顯示名稱。
2. **前端**：所有頁面與 `js/*.js` 中，`MotrixStatus.label(`／`stLabel(`／`statusLabel(` 的呼叫**不得出現在判斷或請求位置**：`x-show`／`x-if`／`:disabled`／`:hidden`、`===`／`!==`／`==`／`!=` 的任一側、`.filter(`／`.find(`／`.some(`／`.includes(`、`JSON.stringify({ status`、`body:`；只能出現在 `x-text`、`:title`、`:placeholder`、文字內插。
3. **正對照（positive control）**：測試內附一段故意違規的範例字串，lint 函式必須抓到（避免掃描器本身壞掉而假綠）；dev-crm 的改動也必須被掃到（掃描檔案數 > 0 且包含 `dev-crm.html`）。
4. **dev-crm 黃金對照**：node 驗每個新運算式在表未載入時等於原運算式；`<option>` 的 `value` 等於原文字。
5. **鍵集合**：`STATUS_KEYS` 含三個新鍵（洽談中／成案／暫擱置）、`未成案` 沒有重複登錄；新鍵的預設標籤＝鍵本身（今天的字）。
（本批不跑 pytest；以 `py_compile`、`import`、直接呼叫 lint 函式與 node 小檢查確認，完整測試待整合者放行後再跑。）

## 4. 決定與待裁示
- **PDF 未核准橫幅與浮水印字：已決定不開放設定**（PM 決定，2026-10-14，安全考量：客戶可見的核可狀態由程式決定，不可被改名）。維持固定語彙；不接、不列入第二期。
- dev-crm 色調（`dc-badge--*`）要不要也走 `st-chip` 色調表？待裁示；建議下一批與 `rb-*` 一併決定。

## 5. 不改的東西
金額、稅、單號、權限、API 回應形狀、SQL、資料庫值；`CONTEXTS`；狀態的鍵；schema 版本（無 migration）。
