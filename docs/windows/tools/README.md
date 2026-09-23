# 稽核工具（從各視窗的 scratchpad 搶救出來的）

> 2026-09-23：使用者要切換 B／C／D 的模型。scratchpad 是 **session 綁定**的，
> 換 session 就不見 ⇒ 由 A 複製進 repo 保存。
> ⚠️ 這些是**一次性稽核腳本**，不是產品碼，也不在 CI 裡。**它們不保證還能跑**
> （路徑、SHA、資料都會過期）——留著是為了**下一次要量同一件事時不必重寫**。

| 檔 | 做什麼 | 已知限制 |
|---|---|---|
| `port_provenance.ps1` | `BR2` 反查：埠 → 祖先鏈 → 啟動方式 → 推定 commit → 判「間隔」 | 見下 |
| `em4_scan2.py` | `EM4` v2（**被 v4 當模組 import，不要單獨改它**） | L1-L6 |
| `em4_scan4.py` | `EM4` v4（加「值裡有沒有理由」；`exec` 進 v2 用它的函式） | L1-L6 |
| `em7_review.py` | `EM7` 18 處逐一讀 ＋ 函式層 L7 證據 | L7-L10 |
| `em7_negctrl.py` | 收緊「迴圈有在數」的判準（找出那 5 個） | L9 |
| `br3_scan.py` | 模組層 `if`/`try` 包住路由註冊 | L1-L4 |
| `json_layer_scan2.py` | JSON 鍵層「產品能不能寫」（三來源：Python／DB 欄位／前端） | — |

## 🔴 `port_provenance.ps1` 的五個已知限制
```
L1 「載入版本」是由 **CreationDate 推定**，不是問行程 => **BR1 的 build_info 才是權威**
L2 對**不載入 repo 程式碼**的行程照樣算落後 => 那一欄無意義
L3 祖先鏈斷掉時回「未知」並**保守假設 expect=true** => 偏向多報（8765 就是）
L4 只掃**指定的埠**，不會自己發現「還有哪些行程在跑」
L5 ⚠️ **只寫在這裡，沒進過任何輸出**：它用
   `git rev-list -1 --before=<CreationDate>` **只看當前分支**
   => 若那次啟動的是**別的分支或別的工作樹**，推定會**靜默錯**
```

## ⚙️ `EM4` 的正對照本體**沒有複製**，而它取得回來
```
ctrl_voucher_pdf_old.py = git show a9e1119^:backend/helpers/voucher_pdf.py
```
🔑 **那是刻意的**：檔案會過期，而**那條 git 指令永遠取得到同一份**。

## ☠️ 三個「怎麼判的」，不知道會重踩
```
1. **.ps1 一定要補 BOM** —— Write 工具建的 .ps1 在 PS5.1 下用 cp932 讀 => **整份語法錯**
   修法 [System.IO.File]::WriteAllText(..., New-Object System.Text.UTF8Encoding($true))
   並用 [Parser]::ParseFile() 驗到 0 錯
2. **邏輯不要放進 Bash heredoc** —— `r"[\\/]"` 的反斜線被吃掉一層
   => 排除 tests／tools／snapshots 的過濾器**整個失效，而輸出看起來正常**
   => 所有掃描器都改成**寫成 .py 檔再執行**
3. **db 一律先複製到 scratchpad 再開** —— 直接開會產生 `-wal`／`-shm`，
   而那會**移動別人正在量的數字**（實際發生過：驗包的計數從 38 被推到 94）
   ⚠️ 用完要刪（D 停工時刪了 **39 個副本**，含正式機副本，內含真實個資）
```

## 📌 試過而**沒命中**的 pattern（避免重跑）
```
6667 的啟動入口   現役 .bat/.ps1/.py/.vbs/.md 全掃 => **只有** tests/_ports.py 的埠排除清單
                  與視窗文件的「不要碰」=> **查不到任何入口**（不是「沒有」，是查不到）
reset-today 前端  reset-today／reset_today／tender-radar/reset／resetToday **四種全 0**
                  前端實際打的：watches5／tenders2／schedule2／status1／scan1
EM7 其他形狀      模組層 if/try 包 include_router 0／包 import routers 0／
                  條件式 APIRouter() 0／從 app.routes 移除 0
```

## ⚠️ 兩個交集（不處理會讓「總共幾個問題」灌水）
```
licensing.py:598 _stable_machine_id  同時在 EM4(37) 與 EM7 => **已從 EM7 扣掉**
archive.py 的 prune 4 處             EM7 第一級，而 G:\每日備份 實查 62／not-a-date **0**
                                     => 機制成立而尚未發生 => 排序在 ②③ 之後
```
