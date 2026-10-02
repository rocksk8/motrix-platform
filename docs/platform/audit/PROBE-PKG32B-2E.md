# 第 32 包重建（52033606）探針差異部分（2e；2026-10-02）

只重跑出納差額審核／手續費與 payload 比對；其餘（材料申請連結、尚未送審、派發舊單、改字）沿用 `PROBE-PKG32-2E.md`，並在本 commit 上重跑該兩檔探針（10 題）全綠。

## payload ↔ commit 樹（payload `D:\MOTRIX-PLATFORM\deploy_packages\20261002_200815_52033606`，`.build_commit`＝52033606580d419ca0705ae067b96bf04068ef30）
837 檔：807 逐位相同、25 只差換行（CRLF 腳本／文字檔）、內容差異 1＝`backend/version_manifest.json`（481 筆、順序相同；51 筆舊條目多 `time` 鍵，其餘語意逐筆相同）、只在 payload 4 檔＝建包產生（`.build_commit`、`export_ignore.json`、`modules.lock.json`、`deploy_manifest.json`）。與上一包比對結果形狀完全相同（除 version_manifest 外全同，符合預期）。

## 出納差額審核與手續費（`test_probe_pkg32b_cashier_2e.py`，3 題，全綠）
- 邊界：fee＝500.00 不進審核；500.01、501 進審核；fee＝0 不審；`hasFee=false` 時帶 fee 不算。
- fee > 實付（700.01 對 700）400；負數、非數字被拒（400/422）；被拒的都沒有留下付款明細。**觀察**：fee＝實付（700 對 700）目前回 200（接受）。
- 審核項目：只有手續費偏高的明細進審核（fee 600、paidAt、diff 0、reason 含「手續費偏高」）；正常那筆不進；多付＋手續費偏高並存的明細兩欄都在、diff 只算多付（550 手續費、多付 600）；多筆明細各自帶自己的 paidAt。
- **反向控制**：把 `material_payment_cashier.py` 換回作廢包（745f3c2d）的版本，審核項目缺 `fee` 鍵（KeyError）⇒ 本探針紅；換回新版 ⇒ 綠（還原後工作樹無修改）。證明探針抓得到 M-1 的退化。
