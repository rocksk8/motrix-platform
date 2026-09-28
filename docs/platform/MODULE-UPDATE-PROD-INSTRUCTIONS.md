# 給正式機 Claude 的指示範本：套用單模組更新包

> 🔴 **稽核 D S5-O1：§5 的回滾參數（`〈A 定稿後填〉`）填入之前，這份範本不可以交給正式機。**

> B55 S7（設計 docs/platform/MODULE-UPDATE-DELIVERY.md §8 的全文版）。每次出單模組包時，主持把 `〈〉` 的欄位填好、
> 連同包名交給使用者，由使用者貼給正式機的 Claude。**正式機目前沒有本機儀表板**（主持裁示 2026-09-28）⇒ 全程是正式機 Claude
> 在使用者面前執行下列指令，套用那一步由使用者本人說「套用」之後才做。
> 對齊：套用腳本 `apply_module_update.ps1`（A，S5）的參數與出口以 A 的定稿為準；`module_update.py`／`delivery.py` 的輸出見設計 §10。

---

## 範本（從這一行以下整段貼給正式機 Claude）

你在 MOTRIX 正式機（安裝目錄 `C:\Users\Motrix\Desktop\V9.0`，以下稱 `<ROOT>`）。這次的工作是**套用一個單模組更新包**，
只做下面列的步驟與使用者要求的動作：**不修改任何程式、不跑測試、不刪檔、不重啟服務**（重啟由套用腳本自己做）。
遇到任何一步的結果和這份指示描述的不一樣，就停下來、把畫面原文回報給使用者，不自己想辦法繞過。

- 包名：`〈yyyymmdd_HHMMSS_<commit8>_mod-<模組>〉`
- 模組：`〈模組代號〉`（〈顯示名〉）版本 `〈舊版〉 → 〈新版〉`
- 這個包是對正式機 commit `〈prod_base_commit 前 8 碼〉` 做的
- 交付資料夾：`〈我的雲端硬碟\MOTRIX-交付〉`（以下稱 `<交付>`）
- 預估：驗證 2 分鐘內、套用 3 分鐘內（含重啟與健康檢查）

### 1. 先確認正式機現況（只讀）

1. `python <ROOT>\tools\platform\module_update.py list --root <ROOT> --json`
   - 印出最後一行 `MODULE_UPDATE_RESULT {...}`。確認 `deployed_commit` 的前 8 碼＝上面寫的 `〈prod_base_commit 前 8 碼〉`。
     **不一樣 ⇒ 停**：這個包不是對目前這一版做的（回報使用者，請開發機重新出貨）。
   - 看 `modules.〈模組〉.version` 是不是 `〈舊版〉`。
2. 健康：瀏覽器或 `python <ROOT>\backend\tools\_healthcheck_ping.py https://127.0.0.1:666/api/ping 5`（沒有憑證就用 http）回 OK；
   `<ROOT>\backend\logs\server.log` 最後 50 行沒有新的 Traceback。有異常 ⇒ 先回報，不套用。
3. `<ROOT>\backend\.apply.lock` **不應該存在**。存在 ⇒ 停，回報內容（另一個套用在跑，或上次中斷留下的）。

### 2. 取包、驗證（只讀，不動安裝目錄）

1. `python <ROOT>\backend\tools\delivery.py scan --root "<交付>"`：列表裡要有這個包名，`kind` 是 `module`、`module.key` 是 `〈模組〉`。
2. `python <ROOT>\backend\tools\delivery.py stage --root "<交付>" --name 〈包名〉 --staging <ROOT>\..\motrix-staging`
   - 印 `DELIVERY_STAGE_OK <staging 路徑>`。印「同步中」⇒ 等 5 分鐘再試（雲端還沒同步完），最多 3 次。
3. `python <ROOT>\backend\tools\delivery.py verify --staged <staging 路徑> --install-root <ROOT>`
   - 最後一行必須是 `DELIVERY_VERIFY_OK`。`notes` 會有一句「單模組更新：〈模組〉 〈舊版〉 → 〈新版〉」（帶 migration 時會註明）。
   - `DELIVERY_VERIFY_FAIL` ⇒ **停**，把 `problems` 原文回報。常見的：
     - 「簽章不符」：包不是開發機發布的，或被改過 ⇒ 不套用。
     - 「正式機沒有單模組套用工具／比這個包需要的舊」：要先套一次完整包 ⇒ 回報。
     - 「這個包是對正式機 … 做的」：基準不符 ⇒ 請開發機重新出貨。
     - 「單模組套用前檢查不通過：…」：後面是 `module_update` 的原因（授權、版本不高於已安裝、有中斷的套用…）⇒ 原文回報。
4. 把「模組、舊版 → 新版、是否帶 migration、出貨前測試摘要（delivery.json 的 `module.tests.line`）」唸給使用者，
   **問使用者要不要套用**。使用者沒有明確說「套用」就不往下。

### 3. 套用（使用者說「套用」之後）

1. 記下開始時間，然後執行（這一步會**停服約 1 分鐘**：只停這個安裝的服務，套用完自動重啟並健康檢查）：
   `powershell -ExecutionPolicy Bypass -File <ROOT>\backend\tools\apply_module_update.ps1 -PackagePath <staging 路徑>\payload -Yes`
   - `-Yes` 是因為使用者已經在對話裡確認過；不要在沒有確認時加。
   - 跑的是**正式機已安裝的**那一份腳本（單模組包不帶任何工具）。
2. 等它結束。10 分鐘還沒結束 ⇒ 回報「仍在執行」，讀 `<ROOT>\backend\logs\apply_module_update_*.log` 最後 30 行給使用者看；
   **不要中止它**（中止會留下中斷的套用，要另外回滾）。
3. 讀最後一行 `::RESULT:: v=2 status=… rolled_back=… service=… exit=…`，以及
   `<ROOT>\backend\logs\apply_module_update_<時間>.result.json`，照下表告訴使用者：

| status | 意思 | 下一步 |
|---|---|---|
| `success` | 已套用，新版本已載入，服務正常 | 做第 4 節寫回 |
| `module_preflight_failed` 而訊息是「有中斷的套用（備份 …）」 | 上一次套用中途中斷（備份還在）；**所有模組**都不能套，完整包也不行 | 不要自己處理：回報使用者，照 §5 用套用腳本的回滾模式回到套用前（稽核 D S5-S2） |
| `module_preflight_failed` 而訊息是「有中斷的套用」，照 §5 回滾時又回 `backup_corrupt`（紀錄檔 apply.json 讀不懂） | 套用被擋、回滾也做不了：只能人工處理（稽核 D W-O1） | **回報開發機，由開發機指示人工檢查；正式機 Claude 不可自行刪除或修改任何紀錄檔**（`<ROOT>\module_backups\` 底下的任何檔都不要動） |
| `module_preflight_failed`、`duplicate_version`、`bad_args`、`package_invalid`、`apply_locked`、`apply_locked_stale` | 沒有套用（正式機沒被碰） | 原文回報；`apply_locked_stale` 要人確認後才可以刪鎖檔 |
| `backup_failed`、`migration_dryrun_failed`、`module_load_dryrun_failed` | 套用前的檢查擋下，正式機沒被碰 | 原文回報（開發機要修模組） |
| `module_copy_failed`（rolled_back＝restored） | 換檔中途失敗，已自動還原到套用前 | 原文回報 |
| `unhealthy_rolled_back`、`module_unhealthy_rolled_back`（rolled_back＝restored） | 新版本起不來或模組沒載入，已自動回滾到套用前，服務正常 | 原文回報（開發機要修模組） |
| 上面兩行但 rolled_back＝`restored_unhealthy` | 已回滾，但服務健康檢查沒通過 | **立刻**回報使用者；用瀏覽器確認系統能不能用 |
| `module_restore_failed` | 自動回滾本身失敗：該模組已被**停用**、其他功能照常 | 立刻回報；模組管理頁會看到它停用；等開發機指示，不要自己啟用 |
| `unhealthy_not_rolled_back` | （只在加了 -SkipAutoRollback 時）健檢失敗而沒有回滾 | 這份指示不會用到這個參數；出現就立刻回報 |
| `unhandled_exception`、其他 | 非預期 | 立刻回報原文與 result.json |

4. 任何失敗都**不要重跑**套用；等開發機看過原因。

### 4. 寫回結果（不論成功或失敗都要做）

`python <ROOT>\backend\tools\delivery.py writeback --root "<交付>" --name 〈包名〉 --install-root <ROOT> --script apply_module_update --since <開始時間的 epoch 秒>`

- `--since` 必填（套用開始的時間）：不給會拿到別次套用的結果檔（稽核 D W-M1）。寫回前會比對結果檔的模組、版本、基準 commit 與這個包的 delivery.json，不符 ⇒ 一律寫成 failed 並列出不符處。
- 印 `DELIVERY_WRITEBACK_OK succeeded|failed <路徑>`：開發機會從交付資料夾讀到結果（只有結果欄位，不含 log 與資料）。
- 成功時再跑一次第 1 節的 `list --json`，確認 `modules.〈模組〉.version` 已是 `〈新版〉`、`overlays` 有這個模組。

### 5. 手動回滾（只在使用者要求時）

- 單模組包的回滾要停服、還原、重啟、健康檢查——**用套用腳本的回滾模式**：`〈A 定稿後填：apply_module_update.ps1 的回滾參數〉`。
- 不要直接執行 `module_update.py rollback`（它只還原檔案，不停服、不重啟、不還原資料庫）。
- 回滾會被拒絕的情形（原文回報即可）：之後又套過別的模組包或完整包（`state_changed`、`base_changed`）、備份損壞（`backup_corrupt`）。

### 6. 不要做的事

- 不要改 `<ROOT>` 底下任何檔、不要刪 `.apply.lock`（除非使用者看過內容後明確要求）、不要重啟服務或排程工作。
- 不要把 log、資料庫、設定檔內容貼到對話以外的地方。
- 驗證沒通過時不要找別的方式套用（例如手動複製模組資料夾）。

---

## 附註（給主持，不貼給正式機）

- **S4-O1**：若日後正式機有了本機儀表板（D6-O1），舊版儀表板不認得 `kind`，會把模組包當一般包列出；按下套用時，舊版 `delivery.verify_staged` 找不到 `apply_update.ps1` ⇒ 驗證不過、擋下（fail-closed），不會誤套。新版儀表板照 `verified["kind"]` 分派。
- 填範本的資料來源：包名、`module.*`、`min_apply_module_script` 都在交付資料夾 `packages\<包名>\delivery.json`；`〈舊版〉` 從開發機 prod-status 的 `delivered.moduleOverlays`（有覆蓋時）或完整包的 lock 取得。
- `〈A 定稿後填〉`：A 的 S5（wip/a-module-apply-ps1）定案後，補上回滾模式的參數與 log 檔名格式。
