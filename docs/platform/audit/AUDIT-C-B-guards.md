# 稽核：B 的 G1～G4 準則守門與 9c① 選配打包（C 稽核，2026-09-25）

> 依 PLAYBOOK §E、CORE-SPEC §9d（D6：C 審 B）。
> 對象：
> - G1／G2：`50e730bd`、`f9b219e5`
> - G3／G4：`6c0d22b3`
> - 9c①：`36cd77bd`、`08ef4fc5`
>
> 稽核基準 platform `e1c16008`。
> 分級：**必修**（不修不能關）／**建議**／**觀察**。關閉規則：被稽核者回覆後，由 C 確認才關。
> `L1I`＝`backend/tests/platform/_l1_interface.py`、`PS`＝`tools/platform/product_select.py`、`PD`＝`tools/platform/product_drill.py`。
> 反向控制都有實跑：
> - 直接呼叫：`aud/rc_direct.py`
> - 突變：`aud/rc_mut.py`（突變 → 跑守門題 → `git reset --hard`，結束時確認工作樹乾淨、HEAD 不變）
>
> 兩支腳本都放在 C 的 scratchpad，在 detached 稽核樹 `D:\MOTRIX-PLATFORM-C2` 上跑。

## 0. 結論

- 每一道守門的**正對照都會轉紅**，機制本身沒問題：
  - G1：公開函式改名
  - G3：表改成 T3
  - G4：模組程式改了、版號沒升
  - 9c①：刪掉 L0／L1 必要檔
- 問題在**範圍**。每一道守門都有一整類變更不在它看的範圍裡，而那一類正是最常改的地方。
- **必修 2 項**：
  - G-1：G1 看不到跨模組最常用的公開 API（底線開頭的 `_require_user` 等）。
  - P-1：9c① 驗包放過「沒有 module.json 的模組資料夾」與前端必要檔。
- 建議 5 項、觀察 4 項。
- 基準：`test_l1_interface_snapshot`、`test_module_package_files`、`test_module_data_classes`、`test_module_changelog_follows_code`、`test_product_select`，連同主持的三檔一起跑，共 **93 passed**。

## 1. 逐項驗收

| 項目 | 規格 | 驗收 | 證據 |
|---|---|---|---|
| G1 L1 公開介面快照 | L1 介面改變 ⇒ 升 CORE_VERSION＋CHANGELOG | ⚠ | 正對照：`doc_template.render` 改名 ⇒ 紅（B1+）。主版號／次版號判定正確（刪除、改名、插在中間、拿掉預設值 ⇒ major）。範圍缺口見 G-1、G-2 |
| G2 模組包裝檔 | README／CHANGELOG／module.json；CHANGELOG 頂端＝version | ✅ | 觀察 O-1 |
| G3 data 分類 vs 備份 | 宣告的分類與備份行為一致 | ⚠ | 正對照：tender_hits 改 T3 ⇒ 紅（B3+）。完整性缺口見 G-3 |
| G4 CHANGELOG 跟著程式 | 模組程式改了 ⇒ 要有新版號條目 | ⚠ | 正對照：改 `match.py` 並 commit ⇒ 紅（B4+）。git 不可用時 fail-closed。範圍缺口見 G-4 |
| 9c① 產品選配 | 沒選的模組不進包；lock＝包內；缺 L0／L1 必要檔 ⇒ 擋 | ⚠ | 正對照：刪掉包內 `archive.py` ⇒ `check` 報缺（B6+）。列了不存在的模組 ⇒ SelectError。缺口見 P-1 |
| 9c① 演練 | 每個產品設定檔都要能打包、啟動，**並通過該組合的測試**（CORE-SPEC:130） | ⚠ | PD 會對每個包啟動並驗端點在或不在，但不跑測試，見 P-2 |

## 2. 發現

### 必修

**G-1　G1 看不到底線開頭、但實際是跨模組公開的 API**
- 位置：L1I:66，`not node.name.startswith("_")`。
- 實際情況：
  - `_require_user`、`_tok`、`_audit` 等列在 `helpers/__init__.py:129` 的 `__all__` 裡。
  - routers 與 modules 共 26 個檔直接 import `_require_user`。
  - 快照 `l1_interface_snapshot.json` 裡沒有 `_require_user`（實查）。
- 反向控制（實跑 B1）：把 `helpers/auth.py:203` 的 `module` 參數刪掉，`test_interface_matches_snapshot` 仍然 **1 passed**。
  - 這個參數是 §9c 模組權限在用的。刪掉之後，所有傳 `module=` 的呼叫端執行時都會 TypeError，而 G1 綠燈、版號不動。
- 為什麼是必修：G1 要守的正是這種改動，也就是 L2 模組依賴的 L1 簽章。L2 用得最多的那一個，恰好在它的盲區。
- 建議修法：
  - 公開與否以「列在 `__all__`，或被 L1 以外的單位 import」為準，不以底線判斷。
  - 最小修法：把 `helpers/__init__.py` 的 `__all__` 全部納入快照。

**P-1　9c① 驗包的「包內實際模組」與「必要檔」範圍都比規格窄**
- 位置：`PS.module_dirs` 只算有 `module.json` 的資料夾（PS:64）；`required_l1_files` 只涵蓋 plat／core／helper／router 四類與 `core/*.py`（PS:144-160）。
- 反向控制（都有實跑）：
  - B5：在包內建 `backend/modules/x_leftover/api.py`（不放 module.json），`check()` 回 `[]`。
    - 沒選到的模組程式碼照樣出貨，違反「整個資料夾不進包」。
    - 典型情境：module.json 改名或打錯字，模組就從「模組」變成「一般資料夾」，連同程式碼一起出貨。
  - B6：`required_l1_files()` 不含 `frontend/pages/login.html`、`helpers/__init__.py`。刪掉包內的 `helpers/__init__.py` 之後，`check()` 仍回 `[]`。這個包在正式機上一啟動就會 ImportError。
- 為什麼是必修：CORE-SPEC §9c① 寫的是「缺任何一個必要 L0／L1 檔 ⇒ 擋下」，這道擋關（verify_package (7) 🔴）目前是依賴 CI 的安全網。
- 建議修法：
  - 有 module.json 的資料夾照現在的方式核對；`modules/` 底下其他任何非 `__pycache__` 的資料夾一律報錯。
  - 必要檔改由 modules.json 的全部 L1 單位推導（含 `js:`／`page:`，以及套件的 `__init__.py`）。
  - 用 repo 的清單核對包內，不要用 repo 的 glob（O-4）。

### 建議

**G-2　G1 其他看不到的變更**
- 以下都用 `interface_of` 直接比對（實跑），描述相同：
  - `async def` 與 `def`
  - 預設值 `y=1` 與 `y=2`
  - 僅限位置參數 `def f(x, /, y)` 與 `def f(x, y)`
- `async` 改 `def` 會讓所有 `await` 呼叫端壞掉，應該算 major。
- 附註：用真實檔案突變（拿掉 `helpers/uploads.py` 的 async）得到的是 **collection error**，不是守門抓到——函式內有 `await`，拿掉 async 會變成語法錯誤。那個紅燈不能算 G1 的證據（記憶〈突變測試的假陽性〉）。
- 建議修法：描述加上 `async` 前綴與 posonly 標記。預設值是否納入由 B 決定；不納入就在 CHANGELOG 規則裡寫明「預設值語意改變要自己升版」。

**G-3　G3 只驗「有宣告的」，不驗「全部都宣告了」**
- 反向控制（實跑 B3）：從 tender_radar 的 `data.tables` 拿掉 `tender_hits`（頂層 `tables` 仍列著），結果 **12 passed**。
- 一張沒有宣告分類的表，就不在任何一條備份規則之下。
- 另外兩處沒有接上：
  - `archive._F2_FIELDS`（表內個資欄位分流）
  - `PII_ROUTED_SETTINGS` 是寫死的，不是從 archive 推導，archive 拿掉分流也仍是綠。
- 建議修法：
  - 反向控制：模組的頂層 `tables`，以及它的 migration 實際建立的表，必須等於 `data.tables` 的 name 集合。
  - `PII_ROUTED_SETTINGS` 改從 archive 取。

**G-4　G4 不看模組的前端頁面與 module.json**
- 反向控制（實跑）：
  - B4：修改 `frontend/pages/tender-radar.html` 並 commit，結果 7 passed。
  - B4b：修改 `module.json` 並 commit，結果 7 passed。
- 模組的頁面不在 `modules/<key>/` 底下；module.json 則整個被排除（`provides`、`permissions`、`data` 改了都不用升版）。
- 對「可獨立販售、單獨更新」（P7 更新包）來說，這兩類變更客戶都會實際收到。
- 建議修法：
  - 納入 module.json 的 `pages[].path`。
  - module.json 只排除 `version` 這一個欄位的變動，其他欄位要計入。

**G-5　L1 的行為改變沒有任何 CHANGELOG 守門**
- G1 只看簽章，G4 只看 L2 模組；L1 函式的內容改了（簽章不變），兩道都不管。
- 這是設計上的取捨，但要寫明，否則會被當成已守門。
- 建議修法：在 CORE-SPEC §9d 寫明「L1 行為改變靠 CHANGELOG 自律＋全量」，或另加一條「L1 檔變動 ⇒ `backend/core/CHANGELOG.md` 同一 commit 必須有改動」。

**P-2　9c① 演練不跑該組合的測試**
- 規格要求（CORE-SPEC:130）：每種產品設定檔都要「通過該組合的測試」。
- PD 實際的檢查：
  - 啟動、ping、改密碼、`/auth/me` 正對照
  - 依 lock 驗端點在或不在（PD:116-133，其中 `/tenders` 寫死在 PD:122）
- 它沒有呼叫 pytest，也沒有自動化測試呼叫 PD（實查）。
- 建議修法（擇一）：
  - 由 PD 在包的複本上跑 `modtest` 選出的受影響題，例如 core-only 就跑 L1 題，並排除已移除的模組。
  - 修改規格措辭，把現況寫成「端點煙霧測試」，並把缺口列進 ROADMAP。

### 觀察

- **O-1**　G2 在沒有模組時是 skip 不是失敗；它不檢查 `key` 是否等於資料夾名（載入器在執行時才擋）。
- **O-2**　`changelog_top_version` 的正則 `\d+\.\d+\b` 會把 `## 1.4.1` 讀成 1.4（實跑）。目前 L1 都是兩段版號，所以沒有影響。
- **O-3**　快照檔不存在時，`--update` 直接寫入、不檢查版號；手動改快照 JSON 也能繞過。沒有任何一題拿 git 歷史比對「快照變了 ⇒ CORE_VERSION 也要變」。
- **O-4**　`required_l1_files` 的 `core/*.py` 用的是 repo 的 glob、不是包內的。repo 多了一支 core 檔、包裡卻沒有時，會正確地報缺；反過來，包裡多出 repo 沒有的檔，則不會發現。

## 3. 反向控制紀錄（C 實跑）

| # | 突變／輸入 | 守門 | 結果 | 判讀 |
|---|---|---|---|---|
| B1 | `_require_user` 刪 `module` 參數 | G1 | 綠 | 缺口 G-1 |
| B1+ | `doc_template.render` 改名 | G1 | 紅 | 正對照 ✓ |
| B2 | 拿掉 `save_document_files` 的 async | G1 | collection error | 不能算證據（語法錯）；以 `interface_of` 直接比對確認缺口 G-2 |
| B3 | `data.tables` 拿掉 tender_hits | G3 | 綠 | 缺口 G-3 |
| B3+ | tender_hits 改 T3 | G3 | 紅 | 正對照 ✓ |
| B4 | 改 tender-radar.html 並 commit | G4 | 綠 | 缺口 G-4 |
| B4b | 改 module.json 並 commit | G4 | 綠 | 缺口 G-4 |
| B4+ | 改 match.py 並 commit | G4 | 紅 | 正對照 ✓ |
| B5 | 包內留下沒有 module.json 的 modules/x_leftover | 9c① check | `[]` | 缺口 P-1 |
| B6 | 刪包內 helpers/__init__.py | 9c① check | `[]` | 缺口 P-1 |
| B6+ | 刪包內 archive.py | 9c① check | 報缺 | 正對照 ✓ |

## 4. 回覆與關閉

| 編號 | 級別 | 狀態 |
|---|---|---|
| G-1 | 必修 | 開 |
| P-1 | 必修 | 開 |
| G-2～G-5、P-2 | 建議 | 開 |
| O-1～O-4 | 觀察 | 開 |
