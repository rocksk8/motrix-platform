# M01 案件 · 規格條件

> 2026-09-26 建立（主持裁示：每個模組都要有 SPEC.md，PLAYBOOK §B 步驟 7）。**拿掉本模組時，本檔與本模組的測試一起消失**。
> 格式同 `modules/tender_radar/SPEC.md`（`backend/tests/test_spec_coverage_2026_09_21.py` 讀 `STATE.md` 加上各模組的 `SPEC.md`）。

## 規格條件

本模組沒有專屬編號。本模組的條件以跨模組編號記在 `docs/windows/STATE.md`（報價、案件、簽核的 AS／AT／AC 等系列），搬遷時照舊留在 STATE.md；
反向控制（拿掉本模組跑 test_spec_coverage）若抓到題全在本模組的編號，再移進本檔（比照 M07 的 BN、M04 的 EM12）。

行為的依據是本模組的測試與串接點（`docs/platform/INTEGRATION-POINTS.md`）。

## 行為條件（2026-10-05，預定付款日與行事曆；依據＝測試）

- 預定付款日只影響提醒與行事曆，不影響金額、付款判準（付款日空白＝待付款）、報表與總帳。
- 提醒只對「已核准、未付款、未作廢、要出納付款的類型、有合法預定日」發；沒填 ⇒ 不發；非工作日不寄、提前到前一個工作日；同一（案件, 種類, 預定日, 寄信日）只寄一次；信內不放金額。
- 行事曆事件不含任何金額（標題與說明）；跟著現況走（upsert／delete），任何一條路徑只要在 commit 後對齊即收斂；事件種類關閉＝零 Google 流量。
- 依據：`tests/test_payable_planned_pay_date_2026_10_05.py`、`tests/test_receipt_calendar_2026_10_05.py`、`backend/tests/test_calendar_upsert_2026_10_05.py`。

## 登記

```
C_OWNED M01 第十三班列車：題名 test_m01_*（本模組的自我代稱，例如「驗 M01 自己不再直寫別的模組表」），不是 CORE-SPEC 條件編號；test_approval_providers.py、tests/platform/test_approval_parse_l1.py、test_case_stage_connectors.py、test_supply_connectors.py
```


## 行為條件（第 46～51 班；依據＝測試，完整說明見 README「第 46～51 班追加」）

- 利潤口徑 2 只在 `overhead_rule_mode=v2` 且有 `overhead_migration_done` 標記時生效；每張單的管銷比率只有最高管理者能改；已精算／已結案的存檔、重算與遷移一律略過（數字、標籤、PDF 與切換前逐位相同）。
- 戳記（`tot.formulaVer`、`tot.overheadPct`、`tot._legacy`、`tot._recalc`、精算 summary 的 `formulaVer`／`overheadPct`／`origFormulaVer`／`origOverheadPct`）只由伺服器蓋，用戶端送的值一律丟棄；標籤與數字永遠看同一份戳記。
- 請求本文的旗標只收真布林（含整數 0／1），其他型別 ⇒ 422 且不寫入。
- 採購單廠商收款帳號在清單、我的申請、變更申請提議只給末四碼；完整帳號只給財務角色與最高管理者且每次查看留稽核；擋付款開關預設關、只對切換時間點之後建立的採購單生效，兩條付款日寫入路徑套同一道檢查。
- 出納改預定付款日：同時被登錄付款 ⇒ 409；日期沒變 ⇒ 不寫、不稽核、不通知。
