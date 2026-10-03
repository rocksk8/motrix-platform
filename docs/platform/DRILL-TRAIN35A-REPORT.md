# 第 35a 班套用演練報告（d5；2026-10-03 21:0x）

**結論：PASS。** 工具 `tools/platform/drill_train35a.py`（分支 `drill/train35a-d5`，由 `origin/drill/train34` 改成 35a；**沒有改動共用工具**）。
基線＝prod/6927e222（第 34 班）＋合成種子（量級同 drill_train34）；新版＝35a 候選包 commit 326e6676（full；db_version 116 不變；case schema 6 不變）。
演練全在 `D:\開發測試檔\d5-drill35a-run\`、埠 6765（只綁 127.0.0.1）；沒有碰正式機、沒有碰 `D:\MOTRIX-PLATFORM`、沒有用 G: 雲端檔、沒有用正式金鑰。

## ⚠ 與正式機步驟的差異（一定要讀）
- **簽章**：主持給的是 build 產物（未簽）。演練用**拋棄式金鑰**簽發到演練專用交付資料夾，驗章用該演練公鑰（`deliver35` 傳 `pubkey_pem`）。
  所以**正式金鑰簽章的驗證沒有在這次演練中驗到**（正式機上 `delivery.py verify` 用已安裝版本內建公鑰驗；是主持簽的包，由正式機步驟 1 把關）。
- 基線資料是**合成的**（不是正式機 DB 副本）：repo 沒有正式機 DB，也不可以用；形狀與量級仿 train34 演練。
- B 的「程式檔逐檔相同」比對範圍：安裝目錄 backend／frontend／tools／product＋根目錄檔共 879 個，**排除**執行期東西（logs、uploads、db_backups、`rollback_snapshots`＝apply 的備份、`*.db*`、`.deployed_commit.json`、module_states.json、憑證檔）以及演練會改寫 `$ProdRoot`／`$Port` 兩行的 `backend/tools/*.ps1`（腳本另由 drill_train_apply 逐行比對改寫前後）。

## 指令與結果（A→B 一輪；另補跑 A→C→E→B 一輪，結果相同）
```
python tools\platform\drill_train35a.py --delivery-root <演練交付資料夾> --name 20261003_205718_326e6676_full --new-commit 326e6676 ^
   --pubkey-file <演練公鑰.pem> --drill-root D:\開發測試檔\d5-drill35a-run --port 6765 --runs A,B      → exit 0（80 秒）
python tools\platform\drill_train35a.py … --runs A,C,E,B                                              → exit 0（120 秒）
```
1. 取包：`delivery.py stage`／`verify_staged`（演練公鑰）→ `verify_ok=true`、problems 空；`verify_package.py <payload> --expect-db-version 116` → rc 0「✅ 全部通過（0 項 FAIL）」（db 116／len(_MIGRATIONS) 116／包 vs 工作樹相同；產品 full，13 個模組）。
2. 套用（`apply_update.ps1 -PackagePath <payload> -Yes`，與 train34 步驟檔 2 相同；先複製包內 tools）：
   `::RESULT:: v=2 status=success rolled_back=applied service=up exit=0`（24.6 秒；script_version 2026-09-28k；commit 326e667608e7…）。
3. 套用後檢查（A 26／26、E 23／23 全過）；35a 專屬：
   - `35a_1`：財務使用者 GET settlement-actuals ⇒ 200；與套用前相比**只多了 `description`、`quantity`、`unit` 三種鍵，其餘每個值逐位相同、沒有鍵消失；totals 完全相同**
     （itemActualTotal 11025、extraTotal 4700、materialUnassignedTotal 250、purchasedTotal 4950、pendingTotal 900、dispatchTotal 10500、totalActualCost 26475）；
     未對應材料列帶 `quantity=2`、`unit=台`、品名；7 筆額外支出列都有 `description`。
   - `35a_2`：非財務使用者（engineer、僅 case_manage、被指派該案）⇒ **403**「此帳號沒有檢視財務金額的權限…」；回應不含 quantity／unit／description／totals。
   - `35a_3`：安裝檔與伺服器實際送出的 `case-management.html` 都含 `data-testid="cm-tab-settlement"`；`settlement.html` 200 且含 `matLabel`／`extLabel`。
   - `35a_4`（S1）：把 6 種髒數量（'²'、None、''、'nan'、'abc'、'1e999'）寫進材料申請 ⇒ 端點仍 200、quantity 皆為 null（測完還原）。
   - 其餘：版本、ping、模組載入（只有 case 1.0.120→1.0.121 變化、13 個模組全 loaded、`unexpected` 空）、log 無 traceback、單一監聽行程、schema（case=6、subcontract=5、db 116；沒有任何 schema 縮水）、重啟冪等、API 文件關閉。
   - 略過的舊班次專屬題（理由寫在報告 `35a_0_stale_checks_skipped`）：15_designer_default_off（D12 已預設開）、16_subcontract_schema_stays_3（已是 5）、16_material_tables_exist_and_empty（本班種子寫了材料審核列）、9c_legacy_dispatch_untouched（第 30 班專屬）。
4. 只回程式的回滾（`rollback_update.ps1 -SnapshotTimestamp <時間戳> -Yes`，不帶 `-IncludeDatabase`）：
   `::RESULT:: v=2 status=rollback_ok rolled_back=restored service=up exit=0`（14 秒）；`.deployed_commit.json` 的 commit＝6927e222…、ping 200；
   **程式檔逐檔雜湊與基線相同（879／879，差異 0、基線有而現在無 0、現在有而基線無 0）**。
5. 補跑：C（資料庫回滾）後 commit＝基線、schema＝基線、筆數＝基線、舊資料不變；E（回滾後重套）`status=success`、檢查全過；B 同上。

## 我在演練工具上踩到的兩個坑（已改在 drill_train35a.py，沒動共用工具）
- 演練驗章要傳 **bytes** 公鑰（`delivery.verify_signature` 的 `load_pem_public_key`）；傳字串會被當成「簽章不符」。
- 程式檔雜湊必須排除 `rollback_snapshots`（apply 自己的備份）。

## 未涵蓋
正式金鑰簽章／正式機真實資料形狀／正式機 Claude 權限分類器行為（步驟 2 被擋下時的處置）——都只能在正式機驗。
