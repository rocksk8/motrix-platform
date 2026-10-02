# drill_train33 乾跑手冊（da 執行；埠 6760 由 da 獨占，a3 不起演練）

前置：候選包已簽章放在交付資料夾；`D:\開發測試檔\drill-t29` 沒有殘留（前一次跑完會自清）；沒有其他視窗佔 6760。

指令（.venv312 的 python；工具從 drill/train33 取）：
```
D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe tools\platform\drill_train33.py ^
  --delivery-root <交付資料夾> --name <包名> --new-commit <SHA> ^
  --expect-schema subcontract=5 --expect-schema case=5 --expect-db-version 116 --runs A,C,E,B
```
（schema／db 版本不給也會用 TRAIN 預設：subcontract=5、case=5、db 116；基線預設 52033606。）

判讀：報告在 `%TEMP%\motrix-drill-t29\<時間>.report.json`。
- runs.A／E：`ok` 為 true，且 checks 內 19a–19h 與 checks31 的通用題全為 true（19b 要求基線有 dispatch_id 單欄 UNIQUE、套用後沒有、兩條部分唯一索引在）。
- runs.C：`ok` 為 true，且 `train33_voucher_shape_after_C.ok`（舊形狀：有 dispatch_id UNIQUE、無 kind 欄）；否則工具印 FAIL 並以非 0 結束。
- runs.B：舊程式對已遷移的庫仍可用（legacy_flow）。
- 失敗先看 19a（舊列逐欄）與 19d（分期流程）的 detail。

只種子不套用（驗基線／種子 SQL，約 1–2 分鐘）：加 `--seed-only`（不需 --delivery-root）。
清理：預設跑完自清；中途中斷請手動刪 `D:\開發測試檔\drill-t29\<時間>` 並確認 6760 已釋放。
