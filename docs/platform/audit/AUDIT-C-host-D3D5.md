# 稽核：主持的部署儀表板 D3／D5（C 稽核，2026-09-25）

> 依 PLAYBOOK §E、CORE-SPEC §9d（D6：C 審主持）。對象：commit `a64cdcd3`（D5 正式機模組狀態）、`0d55250f`（D3 選配打包＋prod_env.json）；稽核基準 platform `e1c16008`。
> 分級：**必修**（不修不能關）／**建議**／**觀察**。關閉規則：被稽核者回覆後，由 C 確認才關。
> 路徑前綴 `backend/`；`DD`＝`tools/deploy_dashboard.py`、`DI`＝`tools/deploy_insights.py`、`PHF`＝`tools/_prod_health_facts.ps1`、`PS`＝`tools/platform/product_select.py`（repo 根）。
> 反向控制腳本：C 的 scratchpad `aud/rc_direct.py`（直接呼叫產品程式）、`aud/rc_mut.py`（突變→跑守門題→`git reset --hard`），在 detached 稽核樹 `D:\MOTRIX-PLATFORM-C2` 執行；暫存都建在 scratchpad 且已刪。

## 0. 結論

- **必修 2 項**：
  1. D-1：D3 部署包列表讀錯 lock 的位置，每個新包都顯示「沒有模組清單」。測試把 lock 放在同一個錯的位置，所以是綠燈。
  2. D-2：D5 讀到非預期型別時整個健康檢查崩潰，前一次的「通過」照樣有效。
- 建議 4 項、觀察 3 項。
- 驗證：
  - 受稽核測試 `tests/platform/test_deploy_dashboard_{modules,products,health}.py`（連同 B 的守門一起跑）共 **93 passed**。
  - 以下兩條都是實跑確認的：**唯讀沒有守門**（D5，突變 H4）、**D3 的綠燈證明的不是出貨路徑**（H1）。

## 1. 逐項驗收

| 項目 | 規格（CORE-SPEC §9e） | 驗收 | 證據 |
|---|---|---|---|
| D5 已安裝版本／lock／停用清單／載入狀態 | 唯讀；只提醒不擋 | ⚠ | 讀取確實唯讀：DB 用 `?mode=ro`（PHF:70），程式碼經 stdin 傳入，遠端不寫檔。單元素陣列不會被 ConvertTo-Json 拆開（C 對假安裝實跑，`installed`／`logLines` 皆為 list）。但「未授權」顯示不出來（D-3），異常型別會崩潰（D-2） |
| D5 不擋部署 | 只提醒 | ✅ | `evaluate_health` 的模組警示只進 `warnings`（DI:183-185）；`test_module_warnings_do_not_block_deploy` |
| D3 `-Product` 驗證 | 產品名稱白名單 | ✅ | `_is_safe_name`＋`product/*.json` 白名單；`..\\full`、`full; rm` 回 400（`test_unknown_or_unsafe_product_is_refused`） |
| D3 列表顯示 modules.lock | 舊包明標沒有清單 | ❌ | 見 D-1 |
| prod_env.json | 健康檢查順帶存 Python 版本＋pip freeze | ✅（附條件） | 位置固定 `tools/prod_env.json`，已 gitignore。清洗見 D-5 |

## 2. 發現

### 必修

**D-1　D3 部署包列表去包的根目錄找 lock，但打包寫在 `backend/` 底下**
- 位置：
  - DD:828 讀 `d / "modules.lock.json"`。
  - PS:140 寫的是 `<包>/backend/modules.lock.json`。verify_package、product_drill（`product_drill.py:62`）和 PHF（先找根目錄、再找 `backend`）都認 `backend/`。
- 後果：每個選配過的新包，在列表上都會顯示成「舊包：沒有模組清單」。這正是 D3 要解決的問題，而畫面顯示的結論恰好相反。
- 為什麼測試是綠的：`test_packages_show_their_module_lock` 自己把 lock 寫在包的根目錄（`test_deploy_dashboard_products.py:66`），所以驗到的是測試自己擺的位置，不是出貨的位置。
- 反向控制（實跑 H1）：
  1. 複製 backend，以 `PS.apply(pkg, load_product("full"))` 做出真的包：lock 寫在 `backend\modules.lock.json`，`PS.check` 回 `[]`。
  2. 再呼叫 `DD.list_packages()`：得到 `lock = None`。
- 建議修法：
  - 列表改讀 `d/"backend"/"modules.lock.json"`。
  - 測試改用 `PS.apply` 產生包、不自己擺檔，這樣位置錯了才會紅。
  - 路徑常數與 PS 共用 `LOCK_NAME`，放在同一個地方。

**D-2　`summarize_modules` 遇到非預期型別會丟例外 ⇒ `/api/prod-health` 回 500，上一次的通過仍然有效**
- 反向控制（實跑 H3）：
  - `disabledRaw='null'` ⇒ `TypeError: 'NoneType' object is not iterable`（DI 的 `set(_json.loads(raw))` 只接 `ValueError`）。
  - `lockRaw='[]'` ⇒ `AttributeError: 'list' object has no attribute 'get'`。
- 為什麼是必修：
  - 這兩個值都來自正式機的檔案和資料庫。管理頁或手動修資料時寫成 `null`、lock 被截斷或寫錯，都是正式機上實際會發生的情況。
  - 健康檢查掛掉時 `_last_health` 不會更新，10 分鐘內前一次的「通過」照樣放行部署。等於正式機愈不正常，放行靠的愈是舊結果。
  - 產品本身的載入器對同一個值做了正規化並接住 `TypeError`（`helpers/module_switches.py:20-23`）。儀表板與產品對同一份資料的容錯不一致。
- 建議修法：
  - 每一種事實各自 try，接 `Exception`，轉成「讀不懂」的警示，不要讓整個健康檢查失敗。
  - 補題：`disabledRaw` 為 `null`／`{}`／`"x"`，`lockRaw` 為 `[]`／`"x"`，`installed` 為 dict。

### 建議

**D-3　「未授權」狀態永遠顯示成「不明」**
- 載入器的 log 格式是 `模組 %s 未載入（未授權）：%s`（`core/loader.py:86`），DI 的正規式 `未載入[：:]` 卻要求「未載入」後面緊接冒號。PHF 的篩選正規式抓得到這一行，但 DI 解析不出來。
- 反向控制（實跑 H2）：傳入 `WARNING 模組 m 未載入（未授權）：授權檔沒有 m`，得到 `state: 不明（沒有啟動紀錄）`。
- 後果：DI 裡 `"未授權" not in why` 這段是死碼；§9e D5 要求顯示的「未授權」狀態出不來。
- 建議修法：
  - 正規式改為 `未載入(?:（([^）]*)）)?[：:]\s*(.*)$`。
  - 更好的做法是讓載入器輸出固定的機器可讀欄位（例如 `state=unlicensed`），不要讓兩邊各自解析中文句子。
  - 補題，直接用 `loader.py` 產生的真實 log 行。

**D-4　D5 的唯讀沒有守門；WAL 庫可能仍會被寫入**
- 反向控制（實跑 H4）：把 PHF 的 `+ "?mode=ro"` 拿掉，`test_deploy_dashboard_modules.py` 仍是 **5 passed**。
- 原因：測試只比對 SELECT 之後內容沒變，而任何 SELECT 都不會改內容。
- 另外，正式庫是 WAL 模式（`db.py:184`），測試用的是非 WAL 庫。在 WAL 模式下，唯讀連線仍可能建立或寫入 `-shm`，這一點 C 沒有實測。
- 建議修法：
  - 測試的假庫改成 WAL，並斷言「連線字串含 `mode=ro`」，或斷言「以唯讀連線執行 INSERT 會失敗」。
  - 在 PHF 的註解明寫：服務停著時，可能會留下 `-shm`。

**D-5　pip freeze 原樣落地、原樣回傳給瀏覽器，沒有清洗**
- PHF:86。以 `pkg @ git+https://user:token@…` 或 `-e` 形式安裝的套件，會把帳密帶進 `prod_env.json`，以及頁面的 facts。
- 一般的 freeze 不會帶 index URL，所以列為建議。修法：去掉 URL 裡的 `user:pass@`，只保留 `名稱==版本`。

**D-6　DB 讀取失敗而且 stderr 是空的，或 DB 檔不存在時，完全靜默**
- 反向控制（實跑 H5）：
  - `disabledRaw=None, disabledError=None`（DB 不存在）⇒ warnings 為 `[]`。
  - `disabledError=""`（python 以非 0 結束但沒有輸出）⇒ warnings 為 `[]`。
- 第二種情況會發生，例如 PATH 上的 `python` 是 Store 別名殼：exit 49，而且不寫 stderr（記憶〈python3 被 Microsoft Store 別名殼攔截〉）。
- 讀不到不等於沒有停用（記憶〈唯讀動作：拒絕 vs 略過〉）。
- 建議修法：
  - PHF 分三種狀態記錄：`disabledRaw`、`disabledError`，以及 `dbMissing`。
  - DI 只要「兩者皆無」就出警示。
  - 錯誤訊息為空時，改寫成「exit N，沒有輸出」。

### 觀察

- **C-1**　PHF 用 PATH 上的 `python` 讀 DB 並跑 pip freeze，不是服務實際使用的那一支 python。
  - 如果正式機服務跑在 venv，prod_env.json 記到的就不是服務的套件。
  - U10 取得正式機實況後，要確認 venv 對齊時讀的是哪一支。
- **C-2**　健康檢查 `subprocess.run(timeout=90)` 現在還多跑了 pip freeze。正式機慢的時候，逾時空間變小；C 沒有實測。
- **C-3**　`logLines` 取的是最後 3000 行裡最後 40 筆符合的行，跨多次啟動時以最後出現的為準。
  - 某模組在最近一次啟動沒有出現，例如資料夾被移除，就會顯示更早那次啟動的狀態。
  - 建議只取最後一次啟動標記之後的行。

## 3. 重現

```
# 基準（C：93 passed，含 B 的守門題）
cd backend && python -m pytest -q -p no:cacheprovider --basetemp=<自己的暫存> tests/platform/test_deploy_dashboard_modules.py tests/platform/test_deploy_dashboard_products.py tests/platform/test_deploy_dashboard_health.py
# D-2
python -c "import sys;sys.path.insert(0,'backend/tools');import deploy_insights as i;i.summarize_modules({'installed':[],'lockRaw':None,'disabledRaw':'null','logLines':[]})"
# D-3
python -c "import sys;sys.path.insert(0,'backend/tools');import deploy_insights as i;print(i.summarize_modules({'installed':[{'key':'m','version':'1'}],'lockRaw':None,'logLines':['模組 m 未載入（未授權）：x']})['rows'])"
```

## 4. 回覆與關閉

| 編號 | 級別 | 狀態 |
|---|---|---|
| D-1 | 必修 | ✅ 關閉（C 2026-09-25 於 platform `fbc653cf` 重跑 H1：真的 `apply` 出來的包 ⇒ 列表讀到 `{product: full, …}`） |
| D-2 | 必修 | ✅ 關閉（重跑 H3：`disabledRaw='null'`、`lockRaw='[]'` ⇒ 不丟例外，轉成「讀不懂」警示） |
| D-3 | 建議 | ✅ 關閉（重跑 H2：`未載入（未授權）：…` ⇒ 狀態「未授權」） |
| D-4 | 建議 | ✅ 關閉（重跑 H4 突變：拿掉 `?mode=ro` ⇒ 1 紅，原本 5 綠）；`-shm` 已接受。**實測證據（C 2026-09-26，D7 預演）**：WAL 模式的庫，只要沒有其他連線開著（`-wal`／`-shm` 不存在），以 `mode=ro` 開啟就會在資料庫目錄**建出** `-wal` 與 `-shm`（`tests/platform/test_final_drill_tool.py::test_ro_backup_does_not_touch_the_source[True]` 在直接用 `mode=ro` 時紅）。對正式機 D5 的影響：服務停著時讀一次停用清單，會在 `backend/` 留下兩個空的側檔，內容不變；仍屬已接受的範圍。要做到一個位元組都不寫，作法是先複製 .db＋-wal 再讀複本（D7 工具已這樣做） |
| D-5 | 建議 | ✅ 關閉（讀碼：PHF 只留 `名稱==版本`，`@ URL` 改成 `<url 已移除>`，其他行丟掉） |
| D-6 | 建議 | ✅ 關閉（重跑 H5：DB 不存在 ⇒「原因不明」警示；exit 非 0 無輸出 ⇒「（沒有訊息）」警示） |
| C-1 | 觀察 | ✅ 關閉（主持已修，且是 U10 實際成因） |
| C-2、C-3 | 觀察 | ✅ 關閉（接受：C-2 下次實跑觀察；C-3 移到階段 S） |

### 主持回覆（2026-09-25，wip/h-d3d5-fix）

| 編號 | 處理 | 突變驗證 |
|---|---|---|
| D-1 | 列表改讀 `<包>/backend/<LOCK_NAME>`，檔名從 `product_select.LOCK_NAME` 取（同一個定義）。測試改用 `product_select.apply` 產生真的包，不自己擺檔；另補「檔名與打包端相同」一題 | 改回讀包根目錄 ⇒ 紅 |
| D-2 | installed、lock、停用清單、logLines 各自容錯，型別不對就轉成「讀不懂」警示，不丟例外；補 13 種異常型別參數化題，以及「單一模組被 ConvertTo-Json 拆成物件照樣列出」 | 拿掉 lock 型別檢查 ⇒ 3 紅；拿掉停用清單型別檢查 ⇒ 紅；拿掉 dict 拆封 ⇒ 紅 |
| D-3 | 正規式接受 `未載入（標記）：`，標記是「未授權」時狀態就顯示「未授權」；測試從 `core/loader.py` 原始碼取真正的格式字串，不自己編 | 改回舊正規式 ⇒ 3 紅。loader 輸出機器可讀欄位的建議記進階段 S，不在這次做 |
| D-4 | 假庫改成 WAL；斷言 PHF 讀 DB 的連線字串含 `?mode=ro` | 未另做突變（斷言對象是腳本文字，拿掉 `?mode=ro` 必紅）。服務停著時可能留下 `-shm`，已接受，不另處理 |
| D-5 | pip freeze 只留 `名稱==版本`；`名稱 @ URL` 改成 `名稱 @ <url 已移除>`；其他行（例如 `-e`）丟掉。事實題斷言沒有 `://` | — |
| D-6 | PHF 另外輸出 `dbMissing`；python 以非 0 結束而且沒有輸出時，改寫成「python exit N，沒有輸出」。DI 在「DB 不存在」「錯誤訊息是空的」「兩者皆無」三種情況都出警示 | 拿掉「原因不明」那一支 ⇒ 紅 |
| C-1 | **已修，並且是 U10 的實際成因**：2026-09-25 22:05 使用者第一次按健康檢查，WinRM 有連上，但 `prod_env.json` 沒有寫出。原因是 PHF 用 PATH 上的 `python`，而 WinRM 工作階段沒有使用者層的 PATH；讀不到版本時，儀表板又靜默略過不寫檔。修法：python 改從 `backend/autostart.bat` 的 uvicorn.exe 路徑推得（正式機是 `…\Python312`），找不到才用 PATH；回傳 `pythonPath`、`pythonSource`、`pythonError`。儀表板在沒拿到版本或寫檔失敗時都會出警示 | 關掉 autostart 推導 ⇒ 紅；拿掉「沒取得版本」警示 ⇒ 紅 |
| C-2 | 未實測；pip freeze 通常只要數秒。先觀察下次實跑耗時，不調整 | — |
| C-3 | 同意，移到階段 S（啟動標記要 loader 配合輸出） | — |
| 附帶 | pythonw 啟動時 `print` 會因為沒有 stdout 而使伺服器起不來（22:0x 實測），已加上防護。這一項**沒有自動測試**，下次用 pythonw 重啟時人工確認 | — |
