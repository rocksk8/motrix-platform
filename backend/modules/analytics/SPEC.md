# M08 營運分析 · 規格條件

> MODULE-GUIDE §5。**拿掉本模組時，本檔與本模組的測試一起消失**；`test_spec_coverage` 讀 `STATE.md` 加上各模組的 `SPEC.md`。

## 規格條件

本模組沒有專屬編號（拿掉本模組時 test_spec_coverage 仍綠，2026-09-26 驗：刪 modules/analytics 的樹上 `tests/test_spec_coverage_2026_09_21.py` 15 過）。
營運報表、首頁統計相關的規格條件仍登記在 `docs/windows/STATE.md`，由 L1 或其他模組的測試引用；若日後有只由本模組測試命名的編號，比照 `modules/tender_radar/SPEC.md` 搬進本節。

## 範圍

首頁統計（`/api/dashboard/*`）、設備與料件彙總（`/api/devices`、`/api/materials-summary`）、營運報表與匯出、銀行對帳（`/api/reports/*`，T100 匯出除外——屬 M06）。

## 登記

無。
