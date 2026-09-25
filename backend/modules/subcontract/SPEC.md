# M04 外包工班 · 規格條件

> 2026-09-26 建立（主持裁示：每個模組都要有 SPEC.md，PLAYBOOK §B 步驟 7）。**拿掉本模組時，本檔與本模組的測試一起消失**。
> 格式同 `modules/tender_radar/SPEC.md`（`backend/tests/test_spec_coverage_2026_09_21.py` 讀 `STATE.md` 加上各模組的 `SPEC.md`）。

## 規格條件

本模組沒有專屬編號。搬遷時查過 `docs/windows/STATE.md`：外包相關的條件（派工、匯款申請、個資分流）都以跨模組編號記在 STATE.md（例如 AC2 日期欄、T9 匯入報價單、X-9b 個資），不是以本模組命名的編號，照舊留在 STATE.md。
行為的依據是既有測試與串接點 IP-1／IP-12／IP-13／IP-14（`docs/platform/INTEGRATION-POINTS.md`）。
