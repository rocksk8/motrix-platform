# M02 業務開發 · 規格條件

> 2026-09-26 建立（主持裁示：每個模組都要有 SPEC.md，PLAYBOOK §B 步驟 7）。**拿掉本模組時，本檔與本模組的測試一起消失**。
> 格式同 `modules/tender_radar/SPEC.md`（`backend/tests/test_spec_coverage_2026_09_21.py` 讀 `STATE.md` 加上各模組的 `SPEC.md`）。

## 規格條件

本模組沒有專屬編號。搬遷時查過 `docs/windows/STATE.md`：提到業務開發的只有標案雷達「一鍵轉 dev_case」（屬 M11，未做）、排程清點與頁面樣式的註記，沒有以本模組命名的規格條件。
行為的依據是既有測試（`tests/test_dev_case_*`、`tests/test_row_access_*`）與串接點 IP-11（`docs/platform/INTEGRATION-POINTS.md`）。
