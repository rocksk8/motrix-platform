# M07 薪資獎金 · 規格條件

> 2026-09-26 建立（主持裁示：每個模組都要有 SPEC.md，PLAYBOOK §B 步驟 7）。**拿掉本模組時，本檔與本模組的測試一起消失**。
> 格式同 `modules/tender_radar/SPEC.md`（`backend/tests/test_spec_coverage_2026_09_21.py` 讀 `STATE.md` 加上各模組的 `SPEC.md`）。

## 規格條件

本模組沒有專屬編號。搬遷時查過 `docs/windows/STATE.md`：獎金分潤與勞報單的條件以跨模組編號記在 STATE.md 與 SPEC-BONUS（BN1～BN21、U4、R1～R3 等），不是以本模組命名的編號，照舊留在原處。
行為的依據是本模組的測試（`modules/payroll/tests/`）與串接點 IP-8／IP-9／IP-16（`docs/platform/INTEGRATION-POINTS.md`）。
