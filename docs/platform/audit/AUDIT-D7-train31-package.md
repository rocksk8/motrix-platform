# 第 31 包完整性唯讀稽核（d7；同第 30 班規格）
包：`packages\20261002_134219_a5dea50c_full`（commit a5dea50c4710ba3c7c9034067b23ad95a6332b51）。**結果：PASS。**
- `package.sha256` 的 SHA256＝`438D0FE0BFAAFB7B32647EE56F3A5DC7116F938D89FF0EE26BBC5BEB12D6449F`（重算相符）；824 行＝824 個 payload 檔＝`delivery.files` 824；`bytes` 34,996,294 相符；824 個檔案雜湊全部重算，不符 0。`delivery.json`：format 1、kind／product full、apply_script_version 2026-09-28k。
- 簽章：以內建 `DELIVERY_PUBKEY_PEM` 驗 Ed25519 ＝ True；反向控制：竄改 `package.sha256` 一個位元組 ⇒ False；竄改 `delivery.json` ⇒ False。（未碰簽章私鑰。）
- 與 6b5d2865 包的差異：新增 42、移除 0、變更 54。新增含 31-C 的 `material_approval／material_guard／material_notify／material_payment／material_payment_cashier`、兩支 api、遷移 0004／0005、`helpers/prefill_sources.py`、`purchase_items.py`、設計文件。
- 禁止內容掃描（含正對照：植入 5 個禁入物全中且無多餘）：命中 5 筆＝與第 30 包相同的 5 處「D:\MOTRIX-KEYS」路徑字串（`backend/tools/delivery.py` 與 4 份文件），無金鑰內容、無私鑰區塊；無 *.db／sqlite、無 tests 路徑、無 tmp／log／jsonl／credentials 殘留。
- `export_ignore.json`（commit a5dea50c，1264 條）：0 條仍在 payload 內。
- 官方 `verify_package.py` 對 payload、`--expect-db-version 116`（116 取自 commit a5dea50c 的 `db.py` CURRENT_VERSION，獨立於包）：正對照成立、db 版本 116＝116、0 FAIL、exit 0。
