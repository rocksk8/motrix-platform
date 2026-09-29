# 稽核：第二十二班最終審（origin/platform b6182dbf，部署包 20260929_161131_b6182dbf_full）（D，2026-09-29）

> 依 8c34f08a：建包測試（非 e2e 6156 過、e2e 567 過）採信，未重跑；D 只做包與來源的獨立比對。

## 0. 判定
- **包：可上正式機。** 必修 0；觀察 3
- 正式機安裝指示與 apply 演練（path1／2／3）尚未出，出來後另審

## 1. 內容範圍（29e435df..b6182dbf）
產品檔（排除 docs、tests、.md）共 14 個，**全部逐位元組等於獨立審過的來源**：
| 檔 | 來源（已審） |
|---|---|
| lodging：`__init__`／`api`／`module.json`／`pages/lodging-overlay.js`／`source.py`、`frontend/pages/lodging-records.html` | wip/l-lodging-daily-2 c1a86740（lodging 1.2.1，複核必修 0） |
| tender_radar：`__init__`／`api`／`listing`／`module.json`／`source.py`、`frontend/pages/tender-radar.html` | wip/tr-precompute-3 91a8fa44（tender_radar 1.5.1，TR-M1 複核通過） |
| `tools/platform/final_drill.py` | 只改預設演練根目錄與說明（D:\開發測試檔\），無邏輯變動 |
| `backend/version_manifest.json` | 見 §2 |
`backend/main.py`、`core/`、`helpers/`、`tools/`（含 apply／rollback 腳本）**與第二十一班相同、未動**（本班不含第二十三班的 rowaccess／startup-timing 包）。簿記：`tests/_prod_baseline.py` 基準 54a2d6b6 → 29e435df（測試用，不進行為）。

## 2. 包的驗證（D 獨立重做）
| 項目 | 結果 |
|---|---|
| 簽章 | 以 `helpers/company_setup.PUBKEYS`（內嵌交付公鑰）驗 `signed_bytes(delivery.json, package.sha256)` ⇒ **通過** |
| `package.sha256` 的 SHA256 | 68B75F85…（與 hichan-90 提供的一致） |
| 檔數／逐檔雜湊 | 清單 592、payload 592；雜湊不符 0、清單有而包沒有 0、包有而清單沒有 0 |
| `delivery.json` | kind=full、commit=b6182dbf…、files=592、`apply_script_version`=**2026-09-28k**（≥28k ✔；ps1 內 `$ApplyScriptVersion = "2026-09-28k"`，`tools/` 與第二十一班相同） |
| 逐檔對 git blob（b6182dbf） | 564 相同、24 只差 CRLF、1 不同＝`version_manifest.json`、3 為建包產生（`deploy_manifest.json`、`backend/.build_commit`、`backend/modules.lock.json`） |
| `.build_commit` | b6182dbfaca2…（與 delivery.json 一致） |
| pyc／F3 類檔（`.install_identity`、確認檔、放行檔、初始帳密、資料庫、私鑰） | 包內 0 |
| 雲端 payload vs stage（stage-t22） | 592 對 592，只在一邊 0、內容不同 0 |
| `version_manifest` | 432 筆（第二十一班 430 ＋ 2）、與 git 順序相同、**除 `time` 欄投影外內容相同**；最上兩筆：附近旅宿 2026-09-29d（改名、系統群組、每日自動更新、當天連續失敗 3 次停）、標案雷達 2026-09-29c（清單預算＋搜尋停手才送）；內文只述功能，無識別值 |
| ship_tier `--prod 29e435df` | **等級 3**（manifest 一次夾帶兩個模組、final_drill 屬建包／更新工具）⇒ 完整包合理 ✔ |

## 3. 觀察（不擋）
- **T22F-O1　本機建包目錄仍有 3 個 pyc**（`deploy-out-t22\20260929_153109_b6182dbf\backend\core\__pycache__\{paths,upgrade,__init__}.cpython-312.pyc`）：與第二十一班 T21F-S1 同源（發布流程從包目錄 import `core`）。雲端（正式機要拿的）與 stage 都是 pyc 0 ⇒ 不影響交付；「發布工具改 `-B`／設 `PYTHONDONTWRITEBYTECODE`」仍是待辦。
- **T22F-O2　docs 整包出貨**：`docs/platform/prod-tasks/20260929-tender-radar-measure.md`（含正式機安裝路徑 `C:\Users\Motrix\Desktop\V9.0`）與 D 的稽核文件隨包出貨，屬「販售包去識別化」暫緩中的已知類別，本包正式機自用，不擋；販售包前要處理。
- **T22F-O3　時間戳**：`built_at` 15:31:12、包名／發布 16:11:31／16:11:44，相隔約 40 分鐘（建包 → 驗證 → 發布）；delivery.json 的 commit 與 `.build_commit` 一致，確認 b6182dbf 為建包當下的 HEAD。無影響。

## 4. 待審
正式機安裝指示（步驟檔）與 apply 演練 path1／2／3 結果：hichan-90 完成後我再審（比照第二十一班 §3、§6、§7）。RA-M1（rowaccess）依主持裁示暫緩。

---
## 5. 演練與正式機步驟檔審查（origin/platform docs/platform/prod-tasks/20260929-train22-apply.md，ec8c8177；D，2026-09-29）

**判定：步驟檔必修 2 項，修完可交正式機。** 演練本身通過（path1 15 步、path2、path3 全 ok，secrets_left=[]；path3 refused_company_setup／not_applied／服務照常）。

已驗（無問題）：雲端檔與 origin/platform 文字相同；包名、`package.sha256` 雜湊 68B75F85B22EB143…49FE（與實際相符）、檔數 592；`delivery.py stage --root --name --staging`／`verify --staged --install-root` 參數與程式相符；回滾指令 `rollback_update.ps1 -SnapshotTimestamp <ts> -Yes` 參數存在、未帶 `-IncludeDatabase`；`apply_update_<ts>.result.json` 有 `timestamp` 欄且與 `rollback_snapshots\<ts>` 同戳；`module_states.json` 有 `started_at`／`modules[].state/version`；沒有要正式機 Claude 重啟排程或刪雲端確認檔的步驟（雲端殘留檔明寫由使用者刪）；路徑寫 H:。

### T22S-M1 步驟 4 與開頭規則互相矛盾
第 12 行：「手動回滾／`-IncludeDatabase`… **一律先回報、等使用者同意**」；步驟 4 卻直接命令「執行 rollback_update.ps1 … -Yes」。正式機 Claude 只能二擇一：違反第 12 行，或停住不回滾。**修法**：步驟 4 第 0 句明寫「先回報使用者失敗的檢查與證據，取得同意後才執行」，或在第 12 行明列「步驟 4 的只回程式回滾已由使用者預先授權」（要有使用者原話出處）。

### T22S-M2 套用後判準 #7／#8／#9 不是「機械可判定」，且會產生假不過 ⇒ 觸發不必要的回滾
- **#8（自 t0 起 ERROR／Traceback 為 0）與演練觀察不一致**：path2 演練的 server.log 在 t0（16:20:36）之後就有 ERROR 行（16:20:36 `信件類型 'monthly_report'：沒有啟用中、設定了 email … 超級管理員 ⇒ 不寄`，同類的 company_setup 告警訊息在其他時點也以 ERROR 記錄）；正式機若沒有啟用中且設 email 的超級管理員，每次啟動都會有這類 ERROR，與版本好壞無關。`apply_update.ps1` 自己的錯誤掃描只看「最後一次 Uvicorn running on 之後」並濾掉已知良性的 `ConnectionResetError` 區塊，本表卻掃整段 t0 之後、無濾除。**修法**：#8 改成與腳本一致（只看最後一次 `Uvicorn running on` 之後、排除 `_call_connection_lost` 良性區塊），或改成「列出 ERROR／Traceback 行數與前 5 行回報，不作為回滾條件；只有 Traceback 且指向 lodging／tender_radar／main 才算不過」。
- **#7 的基準沒有地方記**：「模組總數與套用前相同（套用前先記下數量）」，但步驟 0 沒有「記下套用前 `module_states.json` 的模組數與各模組 state」這一項；`module_states.json` 會在重啟時被覆寫，套用後就沒有基準可比。**修法**：步驟 0 加第 6 項：記下套用前 `modules` 數與每個模組的 key／state；判準改「與套用前相同（除 lodging→1.2.1、tender_radar→1.5.1 的版本外）」，不要寫死「皆 loaded」（正式機可能有 unlicensed／disabled 的既有狀態）。
- **#9「只有一組 uvicorn 行程」**：演練停服回報每個伺服器停了**兩個** PID（例 `STOPPED 20672,37004`、`9868,43988`）⇒ 一個服務對應兩個行程（launcher＋子行程）是常態，「一組」無法機械判定。**修法**：改成「埠 666 有在監聽，且監聽的 PID 只有一個」。

## 6. 建議（不擋）
- **T22S-S1**：步驟 2 沒有第二十一班已採納的 T21P2-S1（`$env:PYTHONDONTWRITEBYTECODE = "1"`）；不加只是 pyc 會寫進包再隨 robocopy 進正式機（同 T21F-S1，功能無害），求一致可補。
- **T22S-O1（觀察）**：演練用的是本機建包目錄（含 3 個 pyc）而非雲端 stage 過的那份；兩者除 pyc 外相同，不影響結論。path2 為了在演練金鑰下走通，「清 backfill 設定列」重走 upgrade_backfill，比正式機真實狀態（29e435df 已補過確認紀錄）更嚴；本班 `main.py`／`helpers/`／`core/` 都沒動 ⇒ 公司閘門程式與已上線版本相同，以差異推論真實路徑更容易通過，不擋。

## 7. 複核 T22S-M1／M2／S1（步驟檔 origin/platform c48cf4ee；main 553fa1d7、雲端皆與其位元組相同）— 通過，必修 0
- **M1** ✔：「你可以自己做的」明列步驟 4 的只回程式回滾為唯一例外，附使用者原話（2026-09-29：「有問題就回滾等我確認，沒問題直接上線」），限定不帶 `-IncludeDatabase`、回滾後停下等確認；步驟 4 開頭重述此例外；連資料庫回滾仍一律先問。（「正式機使用者已同意 hichan-3d 指示適用同一規則」為主持轉述，D 無從獨立驗證，已如實標示出處。）
- **M2** ✔：#8 改為只看最後一次 `Uvicorn running on` 之後、濾 ConnectionResetError 良性區塊，只有指向 lodging／tender_radar／main 的 Traceback 才算不過，其餘 ERROR 列前 5 行與總數、不作回滾條件（與演練 path2 觀察的 monthly_report ERROR 一致）；步驟 0 新增第 5 項記下套用前 `module_states.json`（模組數與各模組 key／version／state），#7 改「與套用前相同，唯一允許 lodging→1.2.1、tender_radar→1.5.1」；#9 改「埠 666 監聽 PID 只有一個」；回滾觸發句同步（#1～#7、#9 任一不過，或 #8 有指向三者的 Traceback）。步驟 0 重新編號後無殘留舊參照。
- **S1** ✔：步驟 2 已在套用前設 `$env:PYTHONDONTWRITEBYTECODE = '1'`。
- 觀察（不擋）：#8 只掃 `Uvicorn running on` 之後，import 期的 Traceback 看不到，但那種情形服務起不來，會被 #2（ping）與 #7（模組狀態）抓到。

## 8. 急件複核：正式機 verify_package 4a 在非 git 安裝目錄必 FAIL（步驟檔 origin/platform 5828b43f；main a3f7af93、雲端皆位元組相同）— 通過，必修 0
- **重現**：把第二十一班雲端包 payload（＝正式機現況 29e435df 的內容）複製到非 git 目錄當「安裝目錄」，用其 `backend/tools/verify_package.py` 對本班 payload 跑 `--expect-db-version 116` ⇒ exit 1，**剛好 2 項 FAIL**，都是 `排除清單 vs MUST_EXIST`（`backend/autostart.bat`、`DEPLOY.md`），訊息含 `returned non-zero exit status 128`；其餘（含 (4b) autostart 內容、(5b) 版本紀錄、(6) db 版本 116＝期望值、(7) 產品選配）皆過。與正式機回報一致；暫存目錄已刪。
- **判準可機械判定**：結尾 `🔴 共 N 項 FAIL：` 與 `✅ 全部通過（0 項 FAIL）` 的字串與程式相符；真的違反排除規則時的訊息是「…（git check-attr 回傳 <值>）」，不含 128／not a git repository，不會被誤放行；「正對照不成立／整份報告作廢」字串與程式相符。
- **路徑與參數**：`<staging>\<包>\payload`＝`delivery.verify_package_cmd` 的 payload；`--expect-db-version 116`＝已安裝 db.py（29e435df）的 CURRENT_VERSION＝包內 116（本班無 migration）；用已安裝版 `verify_package.py`（受信任的是正式機上的程式）與 `delivery.verify_package_cmd` 一致。
- **沒漏掉原有檢查**：`delivery verify --skip-verify-package` 只略過第 5 項（結構）；簽章、逐檔雜湊、檔數、腳本版本、已是這一版／退版判斷都照跑；第 5 項改由步驟檔單獨執行並依上列判準判讀。
- 併入的更正：步驟 0 第 6 項「量測第 2 節需使用者操作、不阻擋套用」與量測檔一致，不擋。
- **不擋的觀察**：第二十一班終審／本班演練都在 git 工作樹內跑 verify_package，所以沒發現這項（同意主持登記「演練改用非 git 安裝目錄」）；下一版修 `verify_package` 的 4a（非 git 時改用包內宣告，或明確標示略過而非 FAIL）。

## 9. 急件複核：步驟 2 少了 `payload\`（正式機 package_invalid；步驟檔 origin/platform 1a87ac3a；main fcb1e3c7、雲端皆位元組相同）— 通過，必修 0
- **兩行與 `delivery.apply_staged` 一致**：`Copy-Item …\<包名>\payload\backend\tools\*`＝`shutil.copytree(payload\backend\tools → install\backend\tools, dirs_exist_ok=True)`（AH-M2）；`apply_update.ps1 -PackagePath …\<包名>\payload -Yes`＝`apply_cmd(install_root, payload, "apply_update")`（`-PackagePath` 為 payload，`-Yes`）。
- **同錯掃描**：步驟檔內所有 staging 路徑——步驟 1 的 `delivery.py verify --staged <包名>`（`--staged` 本來就是含 `delivery.json` 的 staging 根，正確）、`verify_package.py <包名>\payload`（正確）、步驟 2 兩行（已改）；步驟 3 判準、步驟 4 回滾（用 `apply_update_*.result.json` 的 timestamp，不涉及 staging）、步驟 5 回報（只複製 log 與結果檔）皆無 staging 路徑 ⇒ 無其他同錯。
- **演練為何沒抓到**：`drill_t22.py` 的「staging」是 `shutil.copytree(a.pkg → <root>\staging\<包名>)`，`a.pkg` 是建包輸出目錄（＝`payload` 的內容，`deploy_manifest.json`／`backend\tools` 在第一層），再以 `-PackagePath staging` 呼叫演練副本 apply_update——**從未走 `delivery.py stage`，沒有 `payload\` 這一層**，所以「staging 結構」在演練裡跟正式機不同；且演練不是照步驟檔的命令行執行（由 Python 內部組命令）。與上一則 4a 的「演練在 git 工作樹內」同類：**演練環境與正式機步驟檔的實際指令／目錄結構不一致**。下一版題：演練必須由 `delivery.py stage` → `verify` → 步驟檔逐行命令（可從步驟檔的 code block 機械抽取執行）走，安裝目錄用非 git 目錄。
- **建議 T22S-S2（不擋）**：步驟 2 的更正說明段落含控制字元——`\payload\backend\tools\*` 中的 `\b`、`\t` 被寫成退格（0x08）與 Tab，顯示成 `payloadackend    ools`（bytes 偏移約 3671／3678）；不在 code block 內，指令本身正確，但閱讀者會困惑。建議把該行改成用 Write 工具（或雙反斜線）重寫。
