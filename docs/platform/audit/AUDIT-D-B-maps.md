# 稽核：B 的產生檔一致性守門（wip/b-maps；合回前，第六班候選）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。
> 對象：`origin/wip/b-maps` `d25f7ef3`（基底 `bf64e82b`）：新增 `tests/platform/test_generated_maps.py`（dep_graph.json、test_map.json 必須等於現場重產；modules.json 歸屬錯誤必須是 0）；`_boundaries.OWNED_KINDS` 改取 `dep_scan.ASSIGNED_KINDS`；modules.json 拿掉 M12 的 `/api/settings`；dep_scan 寫檔固定 LF。
> 稽核樹 `D:\MOTRIX-PLATFORM-D`（detached），Python `D:\MOTRIX-PLATFORM\.venv312`（只用、未改）。

## 0. 結論

**必修 2 項**，合回前要修：

- BM-M1：dep_graph.json 內含工作樹資料夾名稱，所以這道守門只在產生它的那一棵樹綠。
- BM-M2：拿掉任何一個模組，三題新守門全紅，而且都不在允許清單上。照 §G3，core-only 每一班都會紅。

另有建議 1 項。「OWNED_KINDS 單一定義」「LF 行尾」這兩項成立。

## 1. 實測（`tests/platform/test_generated_maps.py`，7 題）

| 情境 | 結果 |
|---|---|
| D 樹 `d25f7ef3`，模組全在 | **1 failed**：`test_dep_graph_json_is_current` |
| 拿掉 netplan | **3 failed**：`test_dep_graph_json_is_current`、`test_test_map_json_is_current`、`test_modules_json_has_no_ownership_errors` |
| 拿掉全部 L2（core-only） | **3 failed**（同上） |

模組全在時為什麼紅：D 在 D 樹現場重產 dep_graph，與提交的那一份逐行比對，唯一的差別是

```
- "root": "MOTRIX-PLATFORM-B18rc",
+ "root": "MOTRIX-PLATFORM-D",
```

原因是 `tools/platform/dep_scan.py:559` 寫的是 `"root": ROOT.name`，也就是產生它的那一棵工作樹的資料夾名稱。origin 上目前那一份寫的是 `"MOTRIX-PLATFORM-TRAIN5"`。

## 2. 發現

### 必修

**BM-M1　dep_graph.json 內含工作樹名稱 ⇒ 守門只在產生它的那一棵樹綠**
- 在列車樹、各線的樹、D 的稽核樹、core-only 的拋棄式樹都會紅；而誰重產一次，檔案就換一次名字。
- 修法：拿掉 `root` 欄位，或者改成固定值（例如 repo 名稱）。改完重產並提交。補一題：在名字不同的目錄下重產，結果要一樣（可以在合成樹或 `use_root` 上驗）。

**BM-M2　三題新守門都會隨模組在不在而改變 ⇒ 第一班 core-only 就紅**
- 拿掉任何一個模組，dep_graph 與 test_map 會少掉那個模組的單位，modules.json 會出現「列了但掃描不到」。這和 UNIT-INDEX 是同一類的「產生檔一致性題」，但這三題不在 §B-11 的允許清單裡，也不在 `core_only_rc.ALLOWED` 或已知紅清單裡。
- b-g1 已經把「每一班列車都跑 core-only，除允許清單外必須全綠」寫進 §G3。這一包合回之後，每一班都會多出 3 題紅，重演 G-M1。
- 修法（二選一，由主持裁示）：
  - (a) 把這三題列進 §B-11 的允許清單，以及 `core_only_rc.ALLOWED`（產生檔一致性題本來就是這一類；`test_allowed_is_exactly_the_playbook_b11_list` 要一起改）。
  - (b) 改成模組感知：只比對「目前在的模組」與 L1 的部分。
- 不論選哪一個，都要用 `core_only_rc.py` 實跑一次，附上 JSON 結果行。

### 建議

- **BM-S1　dep_graph 的「過期偵測」反向控制沒有走實際的比對路徑**：`test_rc_stale_dep_graph_is_detected` 比的是記憶體裡兩份合成的文字，不讀檔、也不呼叫 `test_dep_graph_json_is_current` 的比對。test_map 那一題是把 `TM.OUT` 換成過期檔，走實際路徑，dep_graph 應該比照：把 `D.OUT` 換成一份過期的檔，斷言比對結果不相等。

### 觀察

- **O-1　OWNED_KINDS 單一定義**：`test_boundaries_owned_kinds_follow_dep_scan` 守住了兩份定義一致；`test_rc_an_unassigned_js_is_an_ownership_error` 用合成的 js 單位證明歸屬題看得到 js。✅
- **O-2　dep_scan 掃的是工作樹**：這三題也會因為工作樹裡的未追蹤檔而紅（`rglob` 會掃到）。拋棄式樹、列車樹是乾淨的，影響不大；但各線在自己的樹上跑時，可能被自己的草稿檔弄紅（MEMORY〈工作樹≠repo〉）。

## 3. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | D 確認 |
|---|---|---|---|
| BM-M1 | | | |
| BM-M2 | | | |
| BM-S1 | | | |
