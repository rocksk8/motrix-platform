# 稽核：C 的 M07 薪資獎金搬進 modules/payroll（PLAYBOOK §B；合回前稽核）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。只審新版（CORE-SPEC 35014aaa）。
> 對象：`origin/wip/c-m07` **`4a731b1f`**（10 個 commit：前置 `93507a6f`、搬遷 `45bf8aaa`、後續 `490c86fc`～`4a731b1f`）。月台登記 platform `1ec4f4a7`。
> 反向控制範圍：`tests/platform`＋所有提到該模組的測試檔（PLAYBOOK §B-11）。
> 稽核樹 `D:\MOTRIX-PLATFORM-D`（在自己的樹刪掉模組資料夾；主持 2026-09-26 裁示「刪資料夾或 sparse 都可以」）、`-D2`（模組在時的基準），都是 detached；Python `D:\MOTRIX-PLATFORM\.venv312`（只用、未改）。
> 分級：**必修**／**建議**／**觀察**。關閉規則：被稽核者回覆後，由 D 確認才關。

## 0. 結論

- **必修 0 項**。§B-11 反向控制第一次提交就通過，這是階段 B 第一個這樣的模組。另外，C 在上一包 M04 的反向控制學到的作法（sparse 樹、有旗標與無旗標兩輪都跑、收集錯誤也要拆）這次全部照做了。
- 建議 2 項、觀察 2 項。

## 1. 反向控制（§B-11，新範圍）

| 輪次 | 樹 | 範圍 | 結果 |
|---|---|---|---|
| 模組在（基準） | D2 `4a731b1f` | tests/platform＋`modules/payroll/tests`＋24 檔 | **1512 passed**、exit 0 |
| 刪掉模組（`--continue-on-collection-errors`） | D `4a731b1f`，`rm -rf backend/modules/payroll` | tests/platform＋24 檔 | **1193 passed、2 failed（皆 §B-11 允許）、1 skipped** |
| 刪掉模組（`--collect-only`，不加旗標） | 同上 | 同上 | **1196 tests collected**、exit 0 ⇒ 沒有收集錯誤 |

C 登記的是 sparse 樹兩輪都 1583 過，只紅允許的 2 題（範圍較大）。D 用不同的刪法與範圍獨立重做，結論一致。

## 2. D 的突變

| # | 突變 | 題 | 結果 |
|---|---|---|---|
| P7a | IP-16 使用方（`routers/system.py::get_bonus_module_status`）在 M07 不在時回 `enabled: True` | `tests/platform/test_bonus_module_status_connector.py`＋模組內 2 檔 | 紅 |
| P7b | 同上，回 `enabled: False` 但不帶 `notice` | 同上 | 紅 |
| P7c | `pii_forms` 的 `api_module` 一律豁免（模組在也不比對端點） | `tests/platform/test_pii_forms_notice.py` | 紅（4） |
| P7d | `api_module` 從不豁免（模組不在也比對） | 同上 | 紅（`test_api_module_only_waives_the_endpoint_when_that_module_is_absent`） |

## 3. 發現

### 必修

（無）

### 建議

- **M07-S1　INTEGRATION-POINTS 的結構化欄位仍然指向搬走的路徑**：D 把登記表裡所有 `.py` 路徑逐一對照 `4a731b1f`。寫在「原本…」敘述裡的舊路徑是對的；但以下出現在「使用方／守門／單據凍結」欄位：
  - IP-2 使用方的 `routers/bonus.py`，應為 `modules/payroll/api/bonus.py`。
  - IP-2 守門的 `backend/tests/platform/test_voucher_connectors.py`，已搬進模組。
  - IP-4 守門的 `test_voucher_status_connectors.py`，已搬進模組。
  - IP-7 單據凍結的 `routers/payslips.py::update_payslip`。
  - IP-8 與 IP-16 那一節守門的 `backend/tests/platform/test_bonus_payout_connectors.py`，已搬進模組。

  這與 AUDIT-D-C-M04-move 的 M04-S1 屬於同一類。**第二次出現了**，建議落實 M04-S1 提的守門：模組在時，登記表結構化欄位裡的路徑要存在。
- **M07-S2　`api_module` 的豁免只信任宣告**：`pii_forms.json` 寫了 `api_module: X`，而 X 不在時，就不比對端點。如果把 L1 的端點誤標成某個模組，這個模組拿掉時就會被錯誤豁免。建議在模組在時，順便驗證 `ack_api` 確實出現在 X 自己的 router 檔裡（`source_tree.router_files()` 中屬於 `modules/X/` 的那幾支），不能只是出現在任何一支 router 裡。

### 觀察

- **O-1　SPEC.md 把 BN1～BN19、QS1a 從 STATE.md 原文照搬**：拿掉模組時，這些條件跟著模組消失，符合「拿掉本模組時本檔與測試一起消失」。STATE.md 那一側有沒有留下「已移到 modules/payroll/SPEC.md」的指標，D 沒有逐條核對；`test_spec_coverage` 在 C 的閘門裡是綠的。
- **O-2　「IP-9 不在時不另加提示」**：README 寫 M08 報表在 M07 不在時少了獎金這一類，「不另加提示」，理由是本模組不在時沒有應列而未列的支出。但「曾經安裝後停用、資料還在」的情形，README 指向 INTEGRATION-POINTS 的說明。這是設計決定，D 記錄在這裡，不要求修改。

## 4. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | D 確認 |
|---|---|---|---|
| M07-S1～S2 | | | |
| O-1～O-2 | | | |

〔10:28 補〕c-m04-2（dd7aecf0）新增的守門 `test_every_provider_file_in_the_registry_exists` 只驗「提供方」欄，M07-S1 的 6 處都在「使用方／守門／單據凍結」欄 ⇒ 仍看不到；建議把同一條檢查擴到這幾欄。

## 5. D 複核 M07-S1／S2（2026-09-26 13:16，`wip/c-m07-s12b` `f72566d9`）

〔回覆欄在分支上由 C 填寫；為免合回時衝突，D 的確認寫在本節，列車合回後以本節為準〕

- **M07-S1 ✅ 關閉（f72566d9）**：`missing_provider_files` 讀 `PATH_ROWS`（提供方／使用方／守門／單據凍結）四欄的每一列；切節改成每個 `## ` 標題（原本只切 `## IP-`，`## U4` 會併進前一節）。D 突變：退回只驗提供方 ⇒ 紅；切節退回 `## IP-` ⇒ 2 紅。C 合回後實測抓到 7 處（D 列的 6 處＋IP-9 使用方 routers/reports.py），全改到新位置。
- **M07-S2 ✅ 關閉（f72566d9）**：`api_module` 宣告的模組在時，`ack_api` 必須在那個模組自己的 router 裡。D 突變「不驗擁有」⇒ `test_api_module_must_own_the_endpoint` 紅。
- 切節改動沒有波及 X-2：`absent_module_capabilities` 仍只處理 `## IP-` 節；D 重跑 X2a（模組在也豁免）、X2e（混合提供方也豁免）⇒ 皆紅。
- 基準 `test_integration_points_registered`＋`test_pii_forms_notice` 41 passed（-n 4）；拿掉全部 L2 ⇒ 35 passed、6 skipped，無新紅燈。
- **O-1 ✅**：STATE.md:28952（BN1～BN18）、:42072（QS1a）與 SCOPE.md:19 都有指向 `backend/modules/payroll/SPEC.md` 的指標。**O-2**：C 建議「報表在沒有 bonus 提供者時一律附一句說明」，屬設計取捨，交主持排；D 同意。

