# 稽核：B54 緊急修補——啟動時第一輪背景工作改非同步（wip/b-warm-async b13cd5c3，基底 5625411e）（D，2026-09-28）

> 起因：正式機 14:39 套用 8b04d99d ⇒ `unhealthy_rolled_back`（已回到 822286ed、服務正常）。新版在 daily checks 之後，於 main.py:676 同步呼叫 `schedule_geocode_warm()`，第一輪跑到每日上限才返回（B50 之後查無不再讓迴圈停下）⇒ 84 秒沒有 startup complete。演練沒抓到：演練安裝設了 `MOTRIX_DISABLE_SCHEDULERS=1`。
> 範圍：10b10d14（geo）、b13cd5c3（tender_radar）。只讀碼；題目與突變在拋棄式樹跑，已清掉。

## 0. 結論

- **必修 0、建議 2、觀察 2。可以進緊急包。**
- 相關四個題檔 80 過。突變「第一輪改回同步」：
  - geo ⇒ 5 紅
  - tender_radar ⇒ 2 紅（真的 `import main` 子行程整合題抓得到）

## 1. 主持指定

**① 延後 30 秒會不會讓既有行為失效**
- `schedule_geocode_warm` 只有 main.py:676 呼叫；`schedule_tender_scan` 只經 `ModuleSpec.schedulers`（start_schedulers）。沒有任何路徑要求「開機當下」就要有第一輪的結果：
  - 地圖取點本來就只讀快取（MP8）
  - 待辦筆數與「還在定位中」會照實顯示
  - 標案的「立即掃描」不經這一支
- 之後每一輪原本就在背景 Timer 跑 ⇒ 沒有新增的併發型態
- 第一輪的 Timer 執行緒 context 是空的，`_WARM_SKIP_GOOGLE`、`without_google_content` 都在輪內設、輪內還原
- 唯一差別：服務若在 30 秒內反覆重啟，第一輪會一直延後。反覆重啟本身就會被健檢抓到，可以接受
- **成立**

**② version_manifest 沿用 28g＋新增 28h，在「回滾過的版本」下會不會誤擋或誤放**
- `apply_update` 的 duplicate_version 比的是 **commit**（`.deployed_commit.json`），不看版本紀錄；正式機現在是 822286ed，新包的 commit 不同 ⇒ 不會誤擋
- `delivery.verify_staged` 的退版提示比的是 built_at，新包比較晚 ⇒ 不會誤判退版
- 失敗那一次，程式卡在 :676，而 `_sync_module_versions()` 在 :711 ⇒ 沒有跑到；自動回滾也把資料庫換回了快照 ⇒ 正式機的 module_versions 裡沒有 28g
- 新包上線後，版本紀錄頁會同時列 28g 與 28h。兩者的功能都隨這一包上線，所以正確
- **成立**

**③ 不修的部分**
- crm、analytics 的排程啟動時本來就用背景執行緒補跑，不是同一型
- 仍然同步的是 archive 的 `_ensure_archive_dirs`／`_schedule_daily`／`_schedule_weekly`（main.py:655-657；主持實測 16～24 秒）與 `schedule_daily_checks`。在健檢時限內，**本次可以不修**；風險見 B54-S2

## 2. 建議

**B54-S1　雲端 packages\ 裡失敗的那一包（20260928_142529_8b04d99d_full）要撤下**
- 它的簽章合法，commit 也不等於正式機現在的 822286ed ⇒ 驗證照樣通過，可以被再套一次，而它一定會再卡住啟動
- `prune` 只刪有結果檔的**舊**包，不會因為失敗就撤下
- 建議：發布新包時，把它移出 `packages\`（例如移到 `rejected\`；UPDATE-DELIVERY 5-4 規劃過這個目錄）
- 這是雲端上的寫入動作，由主持／使用者執行

**B54-S2　啟動路徑上仍有依賴外部 I／O 的同步呼叫**
- archive 的 daily／weekly 排程在啟動時同步執行，會碰雲端存檔路徑
- 雲端硬碟掛著但很慢，或同步卡住時，同一種「好的包被自動回滾」會再發生
- 建議下一輪：
  - 移到背景（形狀同本包）
  - 補一題：真的 `import main`、排程全開、各排程都換成「睡 N 秒」⇒ import 在時限內完成（本包的整合題只換了 geo 與 tender，其他排程是 stub）

## 3. 觀察

- **B54-O1**：演練第五輪（排程開著、MOTRIX_GEO=1、有待辦、Nominatim 連不到，仍要在健檢時限內起來）正好補上這次的盲點。建議再加一種：雲端存檔路徑慢或不在（B54-S2 的情境）
- **B54-O2**：這次的根因是「演練與正式機設定不同」（DISABLE_SCHEDULERS）。建議把「演練安裝與正式機不同的環境變數」列成清單，放進演練報告的固定欄位，讓每一條差異都要有人說明為什麼可以

## 4. 最終審：第十六班（緊急）部署包 54a2d6b6（D，2026-09-28）

**判定：可上正式機。**

- **B54 在包裡**：`helpers/geo.py`、`modules/tender_radar/source.py` 在 54a2d6b6 與 D 審過的 b13cd5c3 內容相同
- **包**（D:\MOTRIX-DRILLS\t16-package\20260928_154134_54a2d6b6），逐檔對 `ls-tree 54a2d6b6`：

| 項目 | 結果 |
|---|---|
| 包內檔數 | 547 |
| 與 blob 相同 | 520 |
| 只差換行 | 23，全在 `.gitattributes` 規則內 |
| 內容不同 | 1：version_manifest 投影，424 筆語意相等；最新一筆是「標案雷達 2026-09-28h」 |
| 建包產生 | 3（.build_commit＝54a2d6b6） |
| pyc | 0 |
| 建包後的改動 | 沒有 |

- **雲端**（packages\20260928_154638_54a2d6b6_full）：547 檔與本機包逐檔相同；package.sha256 的 SHA-256＝7B44DCB9…5064，與主持的相同；私鑰沒有讀
- **第五輪演練**（排程開著、GEO=1、雲端存檔關、150 筆查無）：
  - T14 success
  - **T15 反向控制**：健檢 20 次都沒有回應（87 秒）⇒ `unhealthy_rolled_back`＝重現了正式機的事故 ⇒ 這一輪演練抓得到這一型問題
  - **T16 success**：健檢第 1 次（3 秒）就過；server.log 顯示背景定位在跑（Nominatim 連不到的錯誤照記）時，`/api/ping` 照常回 200
  - pkgs\T16 排除 pyc 後與最終包位元組相同；安裝目錄 399 個程式檔（扣掉 autostart.bat）與最終包相同
- **誘餌消失**：
  - 三份套用紀錄的「結束」清單（T14 5 個、T15 10 個、T16 5 個 PID）都沒有 38720／33004；Stop-InstallService 每停一個都會印出來 ⇒ 不是產品停的
  - decoy1（`other\backend\autostart.bat`，每 30 秒 ping 的無窮迴圈）與 decoy2（`sleep 7200`，15:02 起跑，本來會活到 17:02）的命令列，分別含演練路徑與 `--port 6782`，都符合 drill_stop 的清除條件；演練服務在 15:46:25 收掉
  - ⇒ 是收尾時被演練工具依設計清掉的。**不必再追**。建議演練在每條路之後就記誘餌還在不在（第二輪也提過）
  - 〔**更正**（D，2026-09-28，依主持回報）：上一行的推論是錯的。主持在 T16 套用剛結束時（約 15:42）就查到兩個誘餌 alive=False，早於 15:46 的收尾 ⇒ 不是 drill_stop 清掉的。**仍然成立的只有「不是產品停的」**：三份「結束」清單都沒有它們，而 Stop-InstallService 每停一個都會印出來。死因目前**未解釋**（第二輪的觀察也一樣）。建議不要反推，改成下一次演練讓誘餌自己記心跳：誘餌每秒把時間寫進 `decoy_<pid>.beat`，每條路的前後各記一次最後心跳 ⇒ 就能知道它死在哪一步之間。不擋上線〕
- **上線條件**：照安裝指示（MOTRIX-交付\CLAUDE-正式機安裝指示_54a2d6b6.md；第 3 步 robocopy 加 `/XD __pycache__`＝AH-O3）；先複製包裡的 tools
- **提醒**：套用成功後，請確認正式機背景定位的首輪真的在約 30 秒後起跑（warm_status 的 last_run_at 有更新），不是只看服務起來
