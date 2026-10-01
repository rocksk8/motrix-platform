# 第二十九班：建包與出包步驟（預先排好；W4b 整理，2026-10-01）

> 來源（讀過的）：`docs/platform/plans/HANDOFF-HOST-20261001.md`「出包流程」、`docs/platform/PLAYBOOK.md` §D／§D-1a／§G6、`backend/tools/build_deploy_package.ps1`（參數與 Step 1～7）、`backend/tools/delivery.py`（子命令與資料夾結構）、`tools/platform/train_number.py`、`docs/platform/prod-tasks/20261001-train28-apply.md`（步驟檔格式）、記憶檔 `feedback_build_gates_time_and_integration`。
> 標記：**【已查】**＝這次實際看過檔案／路徑；**【未驗】**＝照文件推得、這次沒做；**【待定】**＝要主持／使用者決定。沒有任何一步在本檔寫作時執行。

## 0. 現況（查過）
- 正式機基準：`origin/platform:backend/tests/_prod_baseline.py` 的 `BASELINE = "0bb4834e"`；git tag `prod/0bb4834e` 存在（04:36 +0800 的 merge）；其餘 prod tag：0c20864a（第 24 班，較舊）、138f3303、6341ea16、eeebd109。**【已查】**
- `origin/platform` = `ad418e88`，是 `wip/train-29-int1` 的祖先；int1 目前 `7ae24919`（16 個分支皆為其祖先，見主持的核對表）。**【已查】**
- 簽章金鑰：`D:\MOTRIX-KEYS\delivery\delivery_signing_key.pem` **存在**（只確認路徑，未讀內容）；同資料夾 `delivery_public_key.pem.txt`。**【已查】**
- 交付資料夾（雲端）：`G:\我的雲端硬碟\MOTRIX-交付`（實際有 `incoming`／`packages`／`rejected`／`company-confirmation`／`交接_20261001`／`正式機回報`；`results\` 由正式機寫回時建立，這次沒看到該資料夾）。正式機看的是 `H:\我的雲端硬碟\MOTRIX-交付`。**【已查】**
- 上一包輸出：`D:\MOTRIX-PLATFORM\deploy_packages\20261001_050838_0bb4834e\`（內含 `backend`、`frontend`、`docs`、`product`、`deploy_manifest.json`…）。**【已查】**
- 已知列車層級紅（取號後會消失，非缺陷）：`MOTRIX_TRAIN=1` 下 `test_l1_interface_snapshot` 兩題（`(next)` 佔位）；accounting CHANGELOG 重複 1.1.46（`test_changelog_sections`，主持說取號會修）。**【未驗：取號後是否真的清掉，要在步驟 3 的 pre_train_check 看】**

## 1. 全部命令（照順序；Python 一律 `D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe`，下稱 `$PY`）

### 1.0 開工前檢查（唯讀）
```
git fetch origin --tags
git merge-base --is-ancestor <每個要上的分支 origin tip> origin/wip/train-29-int1   # 逐一，全部要 YES（主持的清單）
git rev-parse --short origin/wip/train-29-int1                                        # 記下要出貨的 SHA
```
- 清單以主持最後一輪為準（至少：w4-g2-5b、w1-a2-2、w1-a2-4、w1-a2-4-ui、w2-expense-a2-w2b、fix/module-delete-ownership、w3-dept-dim-c7、w3-etype-editor-a3、w3-map-zoom-2e、fix/login-approval-popup、fix/bs-autoload、fix/contractor-bank-mask(-2)、fix/manifest-vr3、w1-attach-p3-a3、w4-diff-buckets、pre-train-check、fix/filehub-guards、w1-a2-4-emptycat、fix/upload-path-guard）。**【待定：最後一輪才算數】**

### 1.1 取號與產生檔（在整合樹，所有分支都合完之後）
```
cd <整合樹根>
$PY tools/platform/train_number.py assign --base origin/platform      # 改寫佔位版號／migration 號／manifest；冪等
$PY tools/platform/train_number.py --check                            # 要 exit 0
$env:PYTHONUTF8="1"; $PY tools/platform/dep_scan.py                   # 重產 dep_graph.json
$PY tools/platform/unit_index.py                                      # 重產 UNIT-INDEX.md
$PY tools/platform/test_map.py                                        # 重產 test_map.json
git add -A; git commit -m "train 29: assign numbers + regen"
```
- 取號前提：G1 快照的介面必須已是目前介面，否則拒絕 ⇒ 先 `$PY backend/tests/platform/_l1_interface.py --update --pending`。**【已查：train_number.py 說明文字；未驗：本班是否需要】**
- 取號會動 `module.json`、各模組 `CHANGELOG.md`、`core/CHANGELOG.md`、`version_manifest.json`、G1 快照、`registry.CORE_VERSION`。

### 1.2 整合預演（先於建包；已失敗十次的教訓）
```
cd <整合樹根>
$PY tools/platform/pre_train_check.py wip/train-29-int1 --workers 2        # 約 13～14 分；全機測試鎖最多 2 組
# 加 --changed-modules 可另跑「動到的模組自己的 tests/」（pre-train-check 分支已合入 int1）
```
- 紅燈**依歸屬**分回作者；清零才往下。一次只放一組全量（別的視窗不得同時跑）。**【已查：用法；本班 ptc 已跑兩次：7ae24919＝3 紅（filehub）】**
- 預演在拋棄式樹 `D:\開發測試檔\pre-train-<分支>-<時間>` 做；中止時要自己清那棵樹與 `%TEMP%\motrix-pytest-pretrain-*`（只清自己的）。

### 1.3 快轉 platform → 凍結（見 §2）
```
git push origin wip/train-29-int1:platform        # ff；非 ff 會被拒（不可強推）【待定：由誰推、是否走月台流程】
# 此時不打 prod/<sha> tag；prod tag 在正式機確認部署後才打
```
- 注意：寫本檔時 `origin/platform` 是 int1 的祖先，故為快轉。**【已查】**

### 1.4 建包（約 35～40 分；開發機執行）
```
cd D:\MOTRIX-PLATFORM          # 【待定：要在哪一棵樹建？腳本打包「它所在的 git repo、目前 HEAD 已 commit 的內容」，且 git status 必須乾淨】
git checkout <platform 快轉後的 SHA>   # 與 §1.3 同一個 SHA；先 `git status` 要乾淨
powershell -ExecutionPolicy Bypass -File backend\tools\build_deploy_package.ps1 -Product full
#   常用開關：-ForceTests（一律重跑、不沿用 12 小時內同指紋的綠）；-OutDir <絕對路徑>；-KeepPackages 2；-MaxAgeDays 7
#   -WaitForOtherTests <分>：盤點時等別的 pytest 結束；-NoPreflight 關掉開跑前的行程盤點
```
- 腳本步驟（只列重點）：Step 1 git 乾淨→Step 1.5 部署腳本語法→Step 1.6／2.52 版本紀錄與 `version_manifest.json` 日期檢查→Step 2.5 釘 Python→Step 2.55 規格覆蓋率→Step 3 測試（非 e2e＋e2e 兩段；建包期間持有「獨佔測試鎖」）→Step 3.1 測試未弄髒工作樹→Step 4 讀最新版本→Step 5 `git archive` 匯出→5.5 `.build_commit`→5.55 `export_ignore.json`→5.6 精簡 `version_manifest.json`→Step 6 `deploy_manifest.json`→Step 7 清過舊的包（保留 2 份、超過 7 天刪）。**【已查】**
- 驗證放行方式：沒動到底層可走「範圍驗證」（PLAYBOOK §D-1a）；**第 29 班動到 L0／L1（core、helpers）⇒ 預期 `mode=full`**，不要指望範圍驗證。**【未驗：實際判定由 scope_gate 決定】**
- 建包前先確認：沒有別的視窗在跑全量（獨佔鎖會讓別人排隊 90 分鐘上限）；日期不跨午夜／月底（見 §3）。

### 1.5 發布與簽章
```
$PY backend\tools\delivery.py publish --pkg D:\MOTRIX-PLATFORM\deploy_packages\<包資料夾> `
    --root "G:\我的雲端硬碟\MOTRIX-交付" `
    --private-key D:\MOTRIX-KEYS\delivery\delivery_signing_key.pem [--keep 3]
$PY backend\tools\delivery.py scan --root "G:\我的雲端硬碟\MOTRIX-交付"       # 確認 packages\ 出現新包
```
- 發布以「整個目錄改名」收尾：`incoming\<包>.partial` → `packages\<包>`；`packages\<包>\` 內有 `payload\`、`delivery.json`、`package.sha256`、`package.sha256.sig`。**【已查：delivery.py 說明】**
- 包名格式 `YYYYMMDD_HHMMSS_<sha8>_<product>`（例 `20261001_053734_0bb4834e_full`）。**【已查：NAME_RE】**
- 私鑰**不讀不印不上雲**；只傳路徑給 `--private-key`。

### 1.6 解凍與後續
解凍通知 → W4 稽核、W3 演練 → 寫給正式機 Claude 的步驟檔（仿 `docs/platform/prod-tasks/20261001-train28-apply.md`，同步雲端 `給正式機Claude_第二十九班更新步驟.md`）→ 正式機 Claude 套用 → 部署後主持打 `prod/<新 sha>` tag、把 `_prod_baseline.py` 的 `BASELINE` 前移（只能往後代移）。**【已查：文件說明；未驗：實際順序以主持為準】**

## 2. 凍結程序（凍結是一段期間，不是一個瞬間）
- 範圍：從 §1.3 快轉 platform 開始，到 §1.5 發布完成＋解凍通知為止。
- 期間禁止：任何視窗推 `platform`、改整合樹／建包樹、跑全量測試（建包持獨佔鎖；別人排隊）、對 `D:\MOTRIX-PLATFORM` 共用樹做 checkout／commit。
- 開始前：主持廣播凍結（靠工作目錄辨認，不靠名字）；確認沒有殘留的 pytest／xdist／playwright 行程與 `%TEMP%\motrix-pytest-*-full` 鎖。
- 結束（成敗都要）：建包一結束 5 分鐘內貼失敗清單／成功 SHA，依歸屬一次派完，**解凍通知**。三連敗就停下做根因分類。**【已查：記憶檔 feedback_build_gates_time_and_integration】**
- ⚠️ 腳本要求 `git status` 乾淨；測試不可在工作樹留檔（Step 3.1 RG19 會報）。

## 3. 必要環境
| 項目 | 值／規則 | 狀態 |
|---|---|---|
| Python | 腳本自挑（Step 2.5，會驗依賴齊全）；工具指令一律 `D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe`；可用 `-WhichPython` 乾跑看會挑哪支 | 已查 |
| `PYTHONUTF8=1`／`PYTHONIOENCODING=utf-8` | 這台 locale 是 cp932，不設則中文輸出會 UnicodeEncodeError | 已查 |
| 建包 log 編碼 | **UTF-16**（PowerShell 重導向）：用 `Get-Content -Encoding Unicode` 讀；用 grep/監看時比對字串會失效，且別讓監看指令的字串含自己 | 已查（交接文件／記憶） |
| 簽章私鑰 | `D:\MOTRIX-KEYS\delivery\delivery_signing_key.pem`（存在；不讀） | 已查 |
| 驗章公鑰 | 內建在 `delivery.py` 的 `DELIVERY_PUBKEY_PEM`（正式機用已安裝版本內建的，不用包帶的） | 已查 |
| 交付資料夾 | `G:\我的雲端硬碟\MOTRIX-交付` 必須已存在（程式不自動建；不存在 ⇒ 拒絕） | 已查（存在） |
| 測試鎖 | 全機 2 格；建包持獨佔；`MOTRIX_PYTEST_LOCK` 可改鎖檔路徑（預設 `%TEMP%\motrix-pytest-full-regression.lock`） | 已查 |
| 固定測試日期 | 建包時腳本設 `MOTRIX_TEST_TODAY`＝commit 當日（時鐘守門分支 `wip/clock-gates-2` **本班不上**，此條目前**不適用**）；跨午夜／月底／每月 1 號是已知風險日 | 已查：決議本班不含時鐘守門 |
| `-ClockDate` | 時鐘守門併入後才有效；本班不上 ⇒ 不使用 | — |
| 磁碟 | 包約數十 MB～上百 MB；暫存 `%TEMP%`、basetemp 用完刪；`deploy_packages` 保留 2 份 | 未驗：實際大小 |

## 4. 預期輸出
1. `train_number.py assign`：改寫的檔案清單；`--check` exit 0。
2. `pre_train_check`：`✔` 各步驟，pytest 摘要 `N passed, 0 failed`（最近一次 7ae24919：`3 failed, 2331 passed`，3 紅＝filehub，待 a3 的 `fix/filehub-guards`）。
3. 建包：`D:\MOTRIX-PLATFORM\deploy_packages\<yyyyMMdd_HHmmss>_<sha8>\`，內含 `backend\`、`frontend\`、`docs\`、`product\`、`deploy_manifest.json`（欄位：`commit`、`commit_short`、`branch`、`product`、`built_at`、`version_manifest_latest`、`durations_sec`、`tests`、`verification{mode,scoped,stages}`、`env`）、`backend\.build_commit`、`backend\export_ignore.json`、精簡後的 `backend\version_manifest.json`。**【已查：腳本 Step 5～6；包資料夾以上一包的清單核對】**
4. `delivery.py publish`：`G:\…\MOTRIX-交付\packages\<包>\`（`payload\`＋`delivery.json`＋`package.sha256`＋`package.sha256.sig`），exit 0；`scan` 能列出。
5. 步驟檔：`docs/platform/prod-tasks/<日期>-train29-apply.md`＋雲端副本。
6. 正式機結果：`results\<包>.result.json`（正式機寫回）；部署後 `backend\.deployed_commit.json`。

## 5. 失敗時的處置（簡）
- 建包 Step 1 失敗（git 不乾淨）：先看是不是上一次測試留的檔（RG19），不要 `git clean` 別人的東西。
- 建包測試紅：貼清單→依歸屬派→同一輪修完再重建；偶發題只准走 `known_flakes.json` 登記＋隔離重跑通過。
- 發布失敗：`incoming\<包>.partial` 殘留 ⇒ 正式機不看；確認後只刪自己這一包的 partial。
- 任何一步判不出來 ⇒ 不猜，回報主持。

## 6. 待主持／使用者決定
1. 建包在哪一棵樹、誰執行（腳本要求 `$repoRoot` 乾淨且 HEAD＝要出貨的 SHA；`D:\MOTRIX-PLATFORM` 是多視窗共用樹）。
2. 快轉 platform 與建包的先後（本檔採「先 ff platform、再建包」，與交接文件一致）。
3. 是否沿用「12 小時內同指紋的綠」（預設會沿用；本班 L0／L1 變動多，建議 `-ForceTests`）。
4. 時鐘守門本班不上 ⇒ 若建包可能跨午夜，要在建包前備好當日 `version_manifest` 條目或提前出貨。
