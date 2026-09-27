# M01 案件 · 規格條件

> 2026-09-26 建立（主持裁示：每個模組都要有 SPEC.md，PLAYBOOK §B 步驟 7）。**拿掉本模組時，本檔與本模組的測試一起消失**。
> 格式同 `modules/tender_radar/SPEC.md`（`backend/tests/test_spec_coverage_2026_09_21.py` 讀 `STATE.md` 加上各模組的 `SPEC.md`）。

## 規格條件

本模組沒有專屬編號。本模組的條件以跨模組編號記在 `docs/windows/STATE.md`（報價、案件、簽核的 AS／AT／AC 等系列），搬遷時照舊留在 STATE.md；
反向控制（拿掉本模組跑 test_spec_coverage）若抓到題全在本模組的編號，再移進本檔（比照 M07 的 BN、M04 的 EM12）。

行為的依據是本模組的測試與串接點（`docs/platform/INTEGRATION-POINTS.md`）。

## 登記

```
C_OWNED M01 第十三班列車：題名 test_m01_*（本模組的自我代稱，例如「驗 M01 自己不再直寫別的模組表」），不是 CORE-SPEC 條件編號；test_approval_providers.py、tests/platform/test_approval_parse_l1.py、test_case_stage_connectors.py、test_supply_connectors.py
```

