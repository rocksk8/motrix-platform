# 模組開發準則（所有新增／修正／追加都依此進行）

> 對象：開發者與 AI session。規格細節見 `CORE-SPEC.md`，使用者裁示以該檔「使用者裁示」為準。
> 本檔的每一條規則都要有對應的守門測試；沒有守門的規則，在表內標「⚠ 未守門」。

## 0. 核心概念

1. **底層不動，模組各自長。** L0 平台（`backend/core/`）與 L1 共用核心是所有模組的地基；模組只能「使用」底層，不能改寫底層。
2. **一個模組＝一個資料夾。** 程式、頁面、測試、說明、更新紀錄都在 `backend/modules/<key>/` 裡；讀一個模組只需要讀那個資料夾。
3. **拿掉模組只會少一個功能。** 刪掉任一模組資料夾，伺服器照常啟動，其他模組的測試照常通過。

## 1. 分層與相依

| 層 | 位置 | 可以 import | 不可以 import |
|---|---|---|---|
| L0 平台 | `backend/core/` | 標準函式庫 | L1、L2 |
| L1 共用核心 | `backend/core/`、`helpers/`、`db.py`（逐步收斂進 `core/`） | L0 | 任何 L2 |
| L2 業務模組 | `backend/modules/<key>/` | L0、L1、自己 | 其他 L2 |

- 模組需要別的模組的能力時，二選一：
  - 這個能力大家都要 ⇒ 下沉到 L1；
  - 只有少數模組要 ⇒ 對方用 `core.registry` 的 provider 或事件公開，**對方不在時，呼叫方只能少一項功能，不可以壞掉**。
- 每一個串接點都要登記在 `docs/platform/INTEGRATION-POINTS.md`，寫明六件事：形式／語法／回傳／對方不在時／契約版本／守門。
  - 登記表與程式碼一致：程式碼 `provide()`／`ModuleSpec(providers=…)` 的 capability ＝登記表中「形式＝provider」各節標題的 capability；`single_provider()`／`providers()` 取用的都必須已登記。守門：`backend/tests/platform/test_integration_points_registered.py`（CORE-SPEC §5；稽核 X-2）。
  - 對方不在時要**明說**（回應帶 `notice` 或 `unavailable`，頁面顯示），不可以跟「0 筆」「沒有」長得一樣。守門：各串接點的反向控制題。
- 守門：`backend/tests/platform/test_module_boundaries.py`（L2 之間的 import 只准減少）。

### 1.1 案件資料的讀取權限範圍（CORE-SPEC 使用者裁示「案件子資料的權限範圍」，2026-09-26）

| 類別 | 規則 | 目前的路徑 |
|---|---|---|
| row_access（逐案） | 案件本身（`case`／`dev_case`）：admin+、該案業務、協作者；經 `helpers.row_access` 或共用守門（`_guard_case`／`guard_case_access`） | 案件本體與執行面共 23 條（報價單、階段、精算、動態、PDF、完工單、出貨單、三種憑證流、叫料、網路規劃書、待辦…），完整清單見 `docs/platform/case_read_scope.json` |
| module（只受模組權限） | 案件底下的**子資料**：有該模組權限即可看全部案件的子資料（採購、會計、出納依職務需要）。**使用者裁示維持現狀**，改動要再問使用者 | `GET /api/network-plans`（`routers/network_plans.py`）<br>`GET /api/contractor-dispatches`（`routers/vendor_contractors.py`）<br>`GET /by-case/{quote_no}`（`routers/vouchers.py`）<br>`GET /summary-sources`（`routers/vouchers.py`） |
| own_rule（模組自有規則） | 模組依自己的規格決定可見範圍（例：獎金分潤只給最高管理者、出納與名單本人，SPEC-BONUS §七） | `GET /awards/plan/{quote_no}`（`routers/bonus.py`）<br>`GET /base/{quote_no}`（`routers/bonus.py`）<br>`GET /cases/{quote_no}`（`routers/bonus.py`） |

- 機器可讀的唯一來源：`docs/platform/case_read_scope.json`（每一條 GET、路徑或參數帶 `quote_no` 的讀取路徑，都要歸在其中一類）。
- 守門：`backend/tests/platform/test_case_read_scope.py`——新增的讀取路徑沒有歸類 ⇒ 紅；標 row_access 而處理函式沒有呼叫逐案守門 ⇒ 紅。

## 2. 底層穩定契約（「底層不會變動」的具體意思）

- L0＋L1 對外公開的介面（函式名稱、參數、回傳形狀、資料表欄位）以 `core.registry.CORE_VERSION` 標版本。
- **同一主版號內只准新增，不准修改或刪除。** 要改或刪 ⇒ 主版號 +1，並且每個模組的 `module.json` 的 `core` 範圍都要重新確認。
- 模組以 `"core": ">=1.0,<2.0"` 宣告相容範圍；載入器看不懂範圍或範圍不相容 ⇒ 不載入，並寫明原因，不猜。
- 守門：`backend/tests/platform/test_l1_interface_snapshot.py`（G1）——modules.json 的 L1 Python 單位（plat:／core:／helper:）之公開函式／類別／dataclass 欄位簽章與大寫常數名稱（**範圍 2，2026-09-25 稽核 G-1／G-2**：「公開」＝不以底線開頭，或列在 `helpers/__init__.py` 的 `__all__`，或被 L1 以外的產品碼 import——例如 `_require_user`；描述含 `async` 與僅限位置參數 `/`；**預設值的內容不納入**，預設值語意改變要自己升版並寫 CHANGELOG），與快照 `l1_interface_snapshot.json` 比對；有差異就紅。修法：升 `CORE_VERSION`、寫 `core/CHANGELOG.md`、跑 `_l1_interface.py --update`（版號不足會拒絕重產）。另驗 CHANGELOG 最上面的版號＝`CORE_VERSION`。快照的判定範圍（`scope_version`）變動時，`--update` 要附 `--reason`，快照記下 `scope_history`（原因、新看得見的名稱），且同一個 commit 必須修改本節或 CORE-SPEC（守門驗 git 歷史）；範圍變大不等於介面新增，不要求升版。
- ⚠ 未守門：回傳形狀（靜態讀不出來）、L1 router 的 HTTP 端點、L1 資料表欄位（已排入 ROADMAP 階段 G：G1b）

## 3. 資料分類與存放規則

### 3.1 位置

- 所有資料位置一律向 `core.paths` 取得。模組內**禁止**用 `__file__` 推算資料位置（守門：`__file__` 資料路徑掃描）。
- 模組資料夾內**不放任何資料檔**（刪模組不可以連帶刪到資料）。
- 正式機既有資料原地讀取；搬遷是逐項可選，不在升級時一次搬（CORE-SPEC 裁示）。

### 3.2 檔案分類（每一類決定存哪裡、上不上雲、進不進每日匯出）

| 類別 | 例子 | 本機 | 雲端 | 每日 JSON 匯出 |
|---|---|---|---|---|
| **F1 一般業務文件** | 報價單、出貨單、完工單、請款單等 PDF；一般附件 | ✅ | ✅ 一般單據鏡像 | 只匯出檔案路徑，不匯出內容 |
| **F2 含個資文件** | 勞報單存檔、身分證件與存摺掃描 | ✅ | ✅ **獨立、權限更窄的資料夾**，與 F1 分開 | ❌ 不可夾帶內容（含 base64） |
| **F3 憑證與祕密** | TOTP secret、session、授權金鑰、SMTP 密碼、初始帳號憑證檔 | ✅ | ❌ 永不上雲 | ❌ 永不匯出 |
| **F4 可重建／暫存** | log、快取（地理編碼等）、暫存檔 | ✅ | ❌ | ❌ |

**F2 雲端資料夾規則**（2026-09-25 勞報單案例）：
- F2 資料放在與一般存檔**並列**的獨立頂層資料夾（例：`系統存檔_個資\勞報單存檔`），不放在一般鏡像底下；這樣分享一般存檔時不會一併帶到個資。
- **這個資料夾由人預先建立並設好權限，程式永遠不自動建立。** 程式自動建立的資料夾會繼承上層較寬的分享權限，而且建立會成功、不會報錯，權限變寬了也沒有人會發現。
- 資料夾不存在 ⇒ 不上傳，並發出告警（邊緣觸發，每天最多一封）：「個資資料夾未建立，○○只有本機一份」。
- 開發機、demo、測試一律不上傳（沿用 `.no_cloud_archive`、所有權標記、demo 隔離）。
- 寫進個資資料夾時，**只准在它底下逐層建子資料夾**（`archive._pii_ensure_dir`／`_pii_copy_file`：`os.mkdir`，不用 `makedirs`）；根目錄在寫入當下不存在 ⇒ 失敗並告警，不建回來（稽核 X-9b S-5：「先檢查、再 makedirs」在兩步之間資料夾消失時會把它建回來）。守門：`test_pii_archive_mirror_2026_09_25.py` 的 `*vanishing*` 四題。⚠ 未守門：**新增**的個資寫入路徑有沒有走這兩支 helper（ROADMAP G6b）。
- **F2 值被複製進別的表**（例：建立單據時把外包人員帳戶凍結進 `snapshot_json`）⇒ 那張表也是含 F2 的表，要在 `archive._F2_FIELDS` 宣告（`columns`／`json`／`json_list`），一般份拿掉、完整列進個資資料夾（稽核 X-9b M-3）。守門：`test_general_tree_has_no_f2_copied_into_other_tables`——走真正的建立 API → 每日＋週備份 → 掃一般樹：哨兵值不可以出現；所有 JSON 欄位裡 F2 鍵名有值的位置，都要在測試的允許清單裡（有人決定過），而且清單每一條都要真的出現。
- **協力廠商（承攬商本身）的銀行帳戶一律當個資（F2）**（稽核 X-9b O-9，2026-09-25 使用者表單裁示「當成個資分流」；CORE-SPEC 使用者裁示表）：對象可能是個人工作室，不逐筆判斷。範圍＝戶名、帳號、存摺影像（`vendor_contractors.data_json` 與承攬付款憑據 `snapshot_json` 最上層）；銀行代碼／名稱／分行是機構資訊，留在一般份。守門同上一條：哨兵值（外包人員與協力廠商帳戶）走真實 API → 每日＋週＋月備份 → 掃一般樹，不可以出現（與允許清單無關）；允許清單目前是空的。突變：放回允許清單、拿掉宣告 ⇒ 皆紅。

### 3.3 資料表分類

| 類別 | 說明 | 每日 JSON 匯出 |
|---|---|---|
| **T1 業務資料** | 單據、主檔、紀錄 | ✅ 必須匯出 |
| **T2 含祕密欄位** | 例如 users 的 totp_secret | ✅ 匯出，但必須排除祕密欄位 |
| **T3 可重建** | 快取、計數、暫存 | ❌ |

- **每一張表都要明確決定分類**，不能預設（守門：`test_system_audit` 的表分類）。
- 表只由擁有它的模組直接寫入；其他模組透過擁有者公開的介面讀寫（守門：邊界測試 ③）。

### 3.4 模組要怎麼宣告

在 `module.json` 寫出本模組擁有的檔案與表，以及它們的分類：

```json
"data": {
  "tables": [{"name": "tenders", "class": "T1"}],
  "files":  [{"key": "payslip_archive", "class": "F2", "setting": "payslip_archive_path"}]
}
```

守門：`test_module_data_classes.py`（G3）——T1／T2 必須在每日 JSON 備份、T3 必須在排除清單且不在備份、F2 檔案必須有 archive 的個資分流、每一項都要有分類。
⚠ 未守門：T2 的祕密欄位是否真的從匯出排除（G3b）。

### 3.5 開發機標記（永不進部署包）

| 標記檔（放在安裝根目錄） | 作用 |
|---|---|
| `.no_email_send` | 不寄通知信（也可以改設 `MOTRIX_EMAIL_SEND=off`） |
| `.no_cloud_archive` | 不寫雲端 |

新開發機的第一件事就是放這兩個檔。守門：`verify_package` 的 dev-marker 規則。

### 3.6 判定規則

- 禁止用安裝路徑（例如 `\V9.0\`）判斷是不是正式機，一律用明確旗標（守門：V9.0 字樣掃描）。
- 守門類檢查預設是「記 ERROR 照常寫入」，只有設了明確旗標才會中斷，不可以擋住客戶正常存檔。

## 4. 資料庫與 migration

- V9 的 migration v1～v116 是凍結的基準，**不可以修改**。
- 模組自己的新表用模組自己的 migration，放在 `modules/<key>/migrations/NNNN_<desc>.py`，版本記在 `module_schema_versions` 表。
- migration 只准新增，不准改動或刪除欄位（這樣才能回退到 V9 的程式）。
- V9 維護期間若新增 migration，必須用同一個版號、同樣的內容追進新版。
- 凍結的歷史 migration 不可以呼叫會繼續演進的程式碼。

## 5. 模組資料夾標準結構

```
modules/<key>/
  module.json      key／name／version／core 範圍／license_key／permissions／data／provides／pages／customization
  __init__.py      MODULE = ModuleSpec(...)（routers、schedulers、providers、runtime_switches）
  api.py           端點（只 import core／helpers／db 與本模組）
  *.py             業務邏輯
  migrations/      本模組的新表
  pages/           前端頁面（搬移中，見路線圖階段 C）
  tests/           本模組測試（modtest 以此為邊界）
  README.md        給使用者與開發者看：功能、端點、資料分類、串接點、對方不在時的行為
  CHANGELOG.md     本模組自己的更新紀錄（最上面的 `## X.Y.Z` ＝ module.json 的 version）
                   ↑ README／CHANGELOG／module.json 的 data 與 license_key 由 test_module_package_files.py（G2）守門
  SPEC.md          規格條件（機器讀）：## 規格條件（編號宣告，格式同 STATE.md）／## 範圍（### THIS／NEXT／EXEMPT）／
                   ## 登記（C_OWNED／KNOWN／AMBIGUOUS_ACK）；test_spec_coverage 讀它，拿掉模組時跟著消失
                   ↑ 每個模組都要有（主持裁示 2026-09-26）；沒有專屬編號也要在「## 規格條件」寫明「本模組沒有專屬編號」（G2 守門）
```

**可自訂點（CUSTOMIZATION-SPEC P3，§3.9；2026-09-26）**
- `customization`：排版器（P9）唯一能動的點——列表欄位、表單區塊、按鈕、頁內選單、匯出、輸出版型；欄位標 `core`（核心：不可隱藏、不可改名）。**每個模組都要寫**，沒有的類別寫空清單。側欄選單項不在這裡寫（在 `pages[].menu`，STAGE-C）。
- 格式錯誤 ⇒ loader 不載入並列出位置（守門：`tests/platform/test_platform_catalog.py`）；缺 `customization` ⇒ G2 紅（`test_module_package_files.py`）。
- 登記的端點要是模組真的有的路由、輸出版型要真的存在；否則能力目錄不列那個點（守門：`test_platform_catalog.py::test_every_loaded_module_lists_all_its_points_without_problems`）。
- 取點只有一個入口 `core.catalog.layout_points()`、排版守門只有 `core.catalog.check_layout()`；`customization._raw_points` 在產品碼別處呼叫 ⇒ 紅（守門：`test_platform_catalog.py::test_only_one_way_to_get_points`）。
- ⚠ 未守門：登記內容與頁面實際畫面一致（P9 改由登記渲染之前）。

**選配（CORE-SPEC §9c，2026-09-25）**
- `license_key`：授權金鑰 `modules` 清單比對用的值（授權單位＝模組，不是權限 key）；沒寫 ⇒ 等於資料夾名；清單 `"*"` ＝全開。⚠ 未守門（「每個 module.json 都有 license_key」由 G2 補）
- `pages`：本模組的頁面。模組這次沒有載入（未授權／停用／載入失敗）⇒ 側欄藏起這些入口。守門：`tests/platform/test_module_selection.py`、`tests/test_e2e_module_settings_2026_09_25.py`
- 優先順序：不在包內＞未授權＞管理者停用；未授權與停用都**不 import** 模組（路由不掛、排程不跑、提供者不登記），資料不動。管理者啟停**重啟後生效**。守門：同上（含子行程真的重啟）
- 因此模組**不可以**在 import 以外的地方偷偷做事（例如別的模組直接 import 它）——不 import 就要等於不存在。
- **路由不可以與 L1 或其他模組重複**（STATES-PLATFORM P-LD-07）：模組路由在所有 L1 router 之後由 `core.loader.mount_modules(app)` 掛上；同方法同路徑（路徑參數視為相同）⇒ 後到的模組整個不掛、狀態「載入失敗」＋原因。模組的排程與啟動提示只對掛上的模組執行。守門：`tests/platform/test_core_loader.py::test_mount_modules_*`、`::test_main_mounts_modules_after_every_l1_router`
- **頁面要登記在 `frontend/static/sidebar.js` 的 `MODULE_PAGES`**（頁面 → 模組 key）：入口只在模組「已載入」時顯示（不在安裝包＝不顯示）；直接打網址進入未載入模組的頁面 ⇒ 提示頁（停用／未授權／載入失敗／未安裝），不是 404；`record-link.js` 不產生指向未載入模組的連結。守門：`tests/platform/test_module_selection.py::test_every_module_page_is_declared_in_sidebar`、`tests/test_states_platform_entries_2026_09_25.py`
- **停用清單讀不到不等於沒有停用**（P-SW-05）：主庫被鎖或內容壞掉 ⇒ 沿用上次成功讀到的清單（主庫旁 `<db>.modules_disabled.json`，F4）；沒有快取 ⇒ 所有模組暫不載入（寧可少開，不可多開），模組管理頁頂端標示。守門：`tests/platform/test_module_selection.py::test_locked_db_uses_last_good_list_then_all_disabled`、子行程 `test_after_restart_…[unreadable]`
- L1 若直接讀某個模組的表（過渡期，例：地圖讀 `tenders`），必須先看 `core.registry.is_loaded(<key>)`，未載入 ⇒ 不列並說明原因。⚠ 未守門（ROADMAP 階段 G：G7；地圖這一處有 `tests/test_states_platform_entries_2026_09_25.py`，但沒有掃描「L1 讀 L2 表而沒看載入狀態」的通用守門）

## 6. 更新紀錄與版本（各模組獨立）

- **每個模組的更新記在自己的 `modules/<key>/CHANGELOG.md`**，版本號記在自己的 `module.json` 的 `version`（語意化版號：修正 +0.0.1、新增功能 +0.1、不相容 +1.0）。
- L0／L1 的更新記在 `backend/core/CHANGELOG.md`，並同步 `CORE_VERSION`。
- 格式（最新的放最上面）：

  ```
  ## 1.0.1 — 2026-09-25 18:30
  - 修正：……（一行一件事，寫具體改了什麼）
  ```

- 系統的「版本紀錄」頁從各模組的 CHANGELOG 彙整產生，不再手動維護一份集中的清單。⚠ 未實作（V9 的 `version_manifest.json` 在過渡期仍然同步，已排入路線圖）
- 查詢某個模組的歷史，只需要讀那個模組的 CHANGELOG。
- 守門：`test_module_changelog_follows_code.py`（G4）——模組程式（扣掉 tests／README／SPEC／CHANGELOG／module.json）最後一次改動之後，CHANGELOG 最上面必須有新寫進去的版號條目；工作樹有未提交的程式改動而 CHANGELOG 沒改也紅。版號升的幅度是否合理不判斷。

## 7. 測試

- 改 L2 模組 ⇒ 只跑該模組的測試加契約測試：`python tools/platform/modtest.py`。
- 改 L1 ⇒ 範圍接近全量，是結構造成的，就接受全量。
- 動到 fixture 層（conftest、pytest.ini、requirements）⇒ ~~一律全量~~〔更正 2026-09-26（主持，§G3）：各線不自己跑全量——差異題＋tests/platform＋改到頁面的 e2e 照跑，**全量由列車跑一次**；月台登記註明 fixture 層、排在列車最前面。`modtest` 閘門過了回 exit 3＝要註明〕。
- pytest 一律帶自己的 `--basetemp`，跑完刪掉。
- 測試一律跑在主工作樹的專案 `.venv`（只照 `backend/requirements*.txt` 安裝；`python tools/platform/project_env.py create`）；`modtest` 預設用它，找不到會警告。與正式機環境的差異用 `project_env.py check`（讀 `backend/tools/prod_env.json`）。
- 守門：`tests/platform/test_requirements_cover_imports.py`——產品碼 import 的第三方套件要能從 requirements.txt 裝到；測試要能從 requirements＋requirements-dev 裝到（含相依）。
- 測試函式不要取成 `test_<字母><數字>_…` 這種形式（例：`test_l2_…`）：`test_spec_coverage` 會把它當成規格條件編號。
- 守門的正對照不可以綁在特定的 L2 模組上（拿掉那個模組，守門就會失效）；改用合成的假模組，或「任取一個已載入的模組」。
  - 子行程要換模組樹：在 `import main` 之前改 `core.loader.MODULES_DIR`／`MODULES_PACKAGE`（`load_all()` 在呼叫當下才讀；例：`tests/platform/child_module_gate.py`）。「任取」找不到時用 `pytest.skip` 說明原因，不可以紅。
  - L1 的測試設定（`backend/conftest.py`）不可以 import L2 模組；模組自己的夾具放 `modules/<key>/tests/conftest.py`。
  - 守門：`test_module_selection.py::test_conftest_names_no_l2_module`；§9c 的守門檔另有 `::test_no_real_l2_module_named_here`。⚠ 未守門：其他守門檔是否點名 L2 模組（沒有全庫掃描）。

## 8. 新增一個模組的步驟

1. 在 `docs/platform/modules.json` 登記 key 與成員（先登記，改的時候才會有人問「這樣還拆得開嗎」）。
2. 照 §5 建立資料夾；寫 `module.json`（含 `data` 分類）、`README.md`、`CHANGELOG.md`。
3. 需要其他模組的能力 ⇒ 照 §1 處理，並登記串接點。
4. 資料照 §3 分類；位置向 `core.paths` 取得。
5. 反向控制：刪掉資料夾 ⇒ 伺服器照常啟動、其餘測試照常通過。

## 9. 產品選配（匯出，CORE-SPEC §9c①）

- 產品設定檔 `product/<名稱>.json`：`{"name", "description", "modules": [...]}`；`["*"]`＝包裡現有的全部模組，`[]`＝只有 L0／L1。列了包裡沒有的模組 ⇒ 打包中止（不猜、不略過）。
- 打包：`build_deploy_package.ps1 -Product <名稱>`（預設 full）。沒選到的 `backend/modules/<key>/` 整個資料夾與它 `module.json` 宣告的頁面（`pages[].path`）不進包；包內寫 `backend/modules.lock.json`（lock_version／kind／product／core_version／各模組 version、core、內容 sha256／excluded／removed_pages）。
- 模組要能被選配，`module.json` 必須宣告 `version`、`core`、`pages`、`provides.api_prefixes`（演練依 api_prefixes 驗證端點在或不在）。
- 守門：`verify_package.py` (7)＝`tools/platform/product_select.py check`（lock＝包內模組、版本與雜湊一致、L0／L1 必要檔齊全、`tools/platform/upgrade.py` 在包裡）；單元 `tests/platform/test_product_select.py`。
- 演練：`python tools/platform/product_drill.py --pkg <包> --port <埠>`：暫存位置啟動、改掉臨時密碼、`/api/auth/me` 正對照、已安裝模組的端點與頁面 200、被排除的 404。
  ⚠ 它是**端點煙霧測試**，不跑 pytest（稽核 P-2）。「該組合的測試」另外跑：full＝打包時的全量；其他產品＝在 worktree 刪掉被排除的模組後跑全部測試（只剩「modules.json 列了但掃描不到」那一題紅是預期的）。由演練工具自動跑組合測試，列在 ROADMAP。
- ⚠ 未守門：頁面尚未搬進模組資料夾（階段 C）前，頁面是否屬於某模組只看 `module.json` 的 `pages` 宣告。

## 10. 模組更新包（P7，CUSTOMIZATION-SPEC §7）

- 單一模組為單位：`python tools/platform/module_update.py build --key <key>`（只取已 commit 的 `modules/<key>/`＋宣告的頁面，不含 tests／SPEC）→ `check` → `apply --root <安裝目錄>`（先備份到 `module_backups/<key>/<時間>/`）→ 需要時 `rollback`。**套用與回滾後都要重啟服務才生效**。
- 套用前檢查全部通過才動手：包的雜湊、安裝目錄有 `modules.lock.json`、`CORE_VERSION` 滿足模組 `core` 範圍、只准升版、模組帶 `migrations/` 一律拒絕（P7b 未做）。任一不過，安裝目錄完全不動。
- 要能被獨立更新，模組的 `module.json` 必須正確宣告 `version`、`core`、`pages`（G2、G4 守著版號與 CHANGELOG）。
- 守門：`tests/platform/test_module_update.py`（合成 repo 與安裝目錄：打包→套用→回滾雜湊逐一相等；每一條套用前檢查都有反向控制；repo 現有模組的正對照）。
- ⚠ 未守門：正式機上的「停服務→套用→重啟→健康檢查→失敗自動回滾」流程由儀表板串接（主持）。

## 11. 法規參數與法規欄位（CUSTOMIZATION-SPEC §9）

- 扣繳率、起扣標準、補充保費門檻、最低工資一律向 L1 `helpers.legal_params` 依**單據日期**取版本，模組不寫死數字；單據存版本號與參數快照，修改舊單沿用快照，除非使用者明確選擇重算。守門：`tests/platform/test_legal_params_single_source.py`（法規數字只能出現在 legal_params 與凍結的 db.py 種子）。
- 法規金額（補充保費、扣繳稅額）的捨入一律用 L1 `legal_params.round_half_up`（四捨五入到元）／`floor_amount`（元以下捨去），前端用 `static/legal-round.js`；讀法規參數的程式不可以直接 `round()`／`math.floor()`／`Math.round()`（內建 round 是銀行家捨入：35,000 × 2.11% 會變 738，應為 739）。守門：`tests/platform/test_legal_amount_rounding_guard.py`（2026-09-26，稽核 D-1）。
- **所有金額**（營業稅、開票申請、請款單、報價收款期別、外包派發稅額、成本精算、報表整數化）的捨入也一律用 `legal_params.round_half_up`（`helpers.quotations.round_half_up` 轉呼叫它；元以下兩位用 `round_half_up(x, 100) / 100`），前端用 `MotrixLegalRound.halfUp`（頁面要載入 `static/legal-round.js`）。不可以用內建 `round()`（10,015 × 30% ＝ 3,004.5 會變 3,004）或 `Math.round(a * b)`（0.7 × 45 會變 31）。守門：同一檔的「擴大範圍」段——開票／請款／報價／外包稅額／成本精算的檔案清單（`MONEY_PY_FILES`／`MONEY_JS_FILES`）禁止 `round(`／`Math.round(`，非金額在同一行標 `/* 非金額 */`；清單內的檔搬進模組時要跟著改清單（X-VAT，2026-09-26）。⚠ 未涵蓋：`:,.0f` 等格式化字串（顯示用，同樣是銀行家捨入）、公式引擎 `round()`（L1 formula，語意待決）。
- 讀舊單 → 合併 → 整包寫回的法規單據（例：勞報單的已告知紀錄、快照）必須在 `core.txn.write_txn` 裡讀。守門：`tests/test_legal_audit_d_r1_r3_2026_09_26.py` 的並行題（只守勞報單；其他單據沿用 core.txn 的 lost-update 規則，⚠ 沒有全域守門）。
- 每一版「兼職薪資補充保費門檻＝當年最低工資」。守門：`tests/test_legal_params_r1_2026_09_25.py`（預設值、種子、PUT 驗證）。
- 零稅率／免稅送出時必填依據（`tax_basis_error`）；免稅依據是營業稅法 §8 第一項逐字條文的逐款下拉（`ARTICLE_8_ITEMS`，出處 `ARTICLE_8_SOURCE`；條文修正時改這張表）。守門：`tests/test_tax_basis_r2_2026_09_25.py`。
- 蒐集個資的表單提供告知（列印或「已告知」紀錄），紀錄由伺服器蓋時間與人員、不可覆蓋；新紀錄同時把告知全文存進 `privacy_notice_texts`（雜湊 → 全文，只增不改）；紀錄的設定值讀不懂 ⇒ 拒絕寫入（`AcksCorrupted`），不可以當成空的覆寫。守門：`tests/test_privacy_notice_r3_2026_09_25.py`。其他表單的告知：`tests/test_privacy_notice_forms_2026_09_26.py`，清單與守門見下一條。
- **蒐集自然人個資的表單都要有告知**（2026-09-26）：清單 `docs/platform/pii_forms.json` 列出「有個資輸入欄位的頁面 ⇒ 決定」，每一頁剛好一種：`notice`（頁面有告知區塊＝`data-privacy-card`／`data-print-notice`／`data-privacy-ack`／`data-privacy-missing`＋載入 `static/privacy-notice.js`，並列出伺服器紀錄端點 `ack_api`）、`covered_by`（個資由另一張 `notice` 表單帶入）、`not_natural_person`（法人資料）。後兩種要逐欄列 `fields`、寫 `reason`；身分證號、生日不可以用後兩種帶過。紀錄一律走 `helpers.privacy_notice.record_purpose_ack`（設定鍵 `privacy_notice_acks`），告知文字依用途（`PURPOSES`：承攬／聯絡人／帳號）分開。新增這類表單：照抄 `contractors.html`（單一當事人）或 `customers.html`（多位聯絡人，`MotrixPrivacyNotice.contactsState()`）或 `network-plan-form.html`（單據上手動輸入的聯絡人，`subjectState()`，紀錄鍵含姓名、只接受已存檔的那一位）的區塊，並在清單加一條。**主持裁示 2026-09-26：單據上可以手動輸入聯絡人 ⇒ 就是在蒐集個資，要 `notice`，不可以用 `covered_by` 帶過**（`covered_by` 只給「只能從主檔選、不能手打」的欄位）。守門：`tests/platform/test_pii_forms_notice.py`（掃描規則 `tests/platform/_pii_forms.py`：`x-model` 綁定最後一段的個資字尾）——新頁面有個資欄位而清單沒有決定、`notice` 頁拿掉區塊或端點、豁免頁多一個個資欄位、過期的決定 ⇒ 紅；正對照＝暫存頁面＋承攬人員名冊；反向控制＝「全部寫成豁免」要紅。⚠ 守不到：不經 `x-model` 的輸入；`covered_by` 的欄位實際上能不能手打（守門只看有沒有決定，「能不能手打」要人判斷）。

## 12. 信件與通知（CORE-SPEC「使用者裁示」信件與通知的收件人、用語，2026-09-26）

**登記**
- 每一種寄出去的信都要在 `backend/helpers/mail_types.py` 登記（模組自己的信在模組載入時 `mail_types.register(...)`，例：`modules/tender_radar/notify.py`）：key、名稱、分類（業務／簽核／系統技術）、預設群組收件人（none／admins／superadmins）、事件收件人說明、影響、建議處理。
- 系統技術類（備份、磁碟、憑證、標案雷達抓取或解析失敗、地圖額度、測試信）預設**只寄超級管理員**；登記時預設群組不是 superadmins 會直接報錯。找不到超級管理員時不退回一般管理員（記 ERROR）。
- 收件人一律經 `email_notify` 的 `_lookup_emails(帳號, key)`（事件收件人）或 `_group_emails(key)`（群組收件人；`_admin_emails`／`_superadmin_emails` 是相容名稱，實際群組由登記表決定）。未登記的 key：執行時記 ERROR、只寄超級管理員。
- 超級管理員在「信件與通知收件設定」頁（`pages/mail-settings.html`）逐類覆寫：照預設／僅超級管理員／指定帳號與角色。個人只能在使用者管理中**退訂**自己收得到的類型；收不到的類型不能勾選。

**用語**
- 主旨：`mail_types.subject(key, 事由)` ⇒「【MOTRIX 系統通知】分類－事由」。不可以自己寫前綴。
- 內文：`email_notify._build_html(key, 標題, …, intro=事由說明)` 固定呈現「事由、影響、建議處理、發送時間與來源」；影響與建議處理預設取登記表，個別信件可傳入更具體的說明。
- 用正式、陳述事實的書面語；不寫猜測、口語或情緒化的字眼與符號。禁用詞（守門清單）：多半、不會自己好、看起來、好像、應該、大概、其實、不用擔心、救不回、吧、喔、啦、唷、你（用「您」）、⚠、☠、🔴、📌、——。
- 信中不放敏感金額（例：獎金分潤），請收件人登入查看。

**守門**：`backend/tests/platform/test_mail_registry.py`——收件人呼叫要帶已登記的字面 key、寄送的主旨要由 `subject()` 產生、`_build_html` 第一個參數是已登記的 key、信件字串不含禁用詞；行為題涵蓋預設群組、僅超級管理員、指定帳號／角色、未登記 fail closed、系統技術類一般管理員不收、個人退訂只能移除。
