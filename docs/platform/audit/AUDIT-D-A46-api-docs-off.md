# 稽核：A46 API 文件頁預設關閉（wip/a-api-docs-off a1a62dd1，基底 f04a245a）（D，2026-09-28）

## 0. 結論

- **必修 0、建議 1、觀察 1。可以上車。**
- D 在拋棄式 worktree 重跑同一組題（tests/platform＋docs_off＋非 /api 白名單＋payroll 審批題）：**1611 passed、4 skipped**，與 A 回報一致；暫存已清

## 1. 主持指定

**① 旗標只認字面 "1"：成立。**
- `main._docs_kwargs`：`environ.get("MOTRIX_API_DOCS") == "1"` ⇒ 三個 url 全開；否則三個都是 None（FastAPI 不註冊路由；oauth2-redirect 跟著 docs_url 一起不註冊）
- 題目涵蓋 None、""、"0"、"true"、"yes"、" 1"（前置空白）⇒ 全關；反向控制：旗標為 "1" 時同一支函式建出的 app 四條都 200
- 不看安裝路徑 ✔（記憶〈不可以用安裝路徑猜正式機〉）
- 關掉的是對外路由，程式內 `app.openapi()` 仍可用（有題）

**② 有沒有前端或工具依賴 /openapi.json：只有 final_drill，已處理。**
- 全 repo（排除 docs 與 .md）grep `openapi`／`/docs`／`/redoc`：
  - `tools/platform/final_drill.py`：GET 全掃靠 `/openapi.json` 列路徑 ⇒ `smoke()` 起的演練服務帶 `MOTRIX_API_DOCS=1`（有題驗原始碼）
  - payroll 審批題：改 `client.app.openapi()`（不經 HTTP）
  - `backend/tools/check_endpoint_entrypoints.py:46`：只是分類標籤字串，不發請求
  - 前端 0 處
- 非 /api 白名單拿掉四條；正對照題的 `- {四條}` 保留（合成 app 不受旗標影響），正確

**③ 4 個 skip 是什麼：都與 A46 無關。**

| skip | 原因 |
|---|---|
| `test_generated_maps.py:48`、`:58` | 產生檔只由列車提交（PLAYBOOK §G3），是否最新只在 `MOTRIX_TRAIN=1` 驗 |
| `test_unit_cards.py:118` | 同上（UNIT-INDEX） |
| `test_module_boundaries.py:300` | 「基線裡沒有仍存在的邊可拿來突變」——守門的**正對照被跳過**（見 A46-O1） |

## 2. 建議

- **A46-S1　測試要不受開發機的旗標影響**：main.py 的註解寫「開發機要看文件時自己設」。D 以 `MOTRIX_API_DOCS=1` 跑 docs_off＋白名單兩個檔 ⇒ **5 紅**（四條 404 題＋白名單題），全量測試與建包都會被擋。conftest 已經在 import main 之前 `pop("MOTRIX_CLOUD_ARCHIVE")`（:329），同一處加 `MOTRIX_API_DOCS` 即可（記憶〈環境變數旗標會漏進子 pytest〉）

## 3. 觀察

- **A46-O1**：`test_module_boundaries.py:300` 的正對照在目前基線上沒有可突變的邊，所以跳過。檔案不在 A46 範圍內（既有狀況）；但「正對照跳過」等於這道邊界守門的自我驗證沒有執行。建議之後改成用合成的邊做正對照，不依賴基線裡剛好有邊
