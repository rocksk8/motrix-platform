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
- 守門：`backend/tests/platform/test_module_boundaries.py`（L2 之間的 import 只准減少）。

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
  module.json      key／name／version／core 範圍／license_key／permissions／data／provides／pages
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
```

**選配（CORE-SPEC §9c，2026-09-25）**
- `license_key`：授權金鑰 `modules` 清單比對用的值（授權單位＝模組，不是權限 key）；沒寫 ⇒ 等於資料夾名；清單 `"*"` ＝全開。⚠ 未守門（「每個 module.json 都有 license_key」由 G2 補）
- `pages`：本模組的頁面。模組這次沒有載入（未授權／停用／載入失敗）⇒ 側欄藏起這些入口。守門：`tests/platform/test_module_selection.py`、`tests/test_e2e_module_settings_2026_09_25.py`
- 優先順序：不在包內＞未授權＞管理者停用；未授權與停用都**不 import** 模組（路由不掛、排程不跑、提供者不登記），資料不動。管理者啟停**重啟後生效**。守門：同上（含子行程真的重啟）
- 因此模組**不可以**在 import 以外的地方偷偷做事（例如別的模組直接 import 它）——不 import 就要等於不存在。

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
- 動到 fixture 層（conftest、pytest.ini、requirements）⇒ 一律全量。
- pytest 一律帶自己的 `--basetemp`，跑完刪掉。
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

