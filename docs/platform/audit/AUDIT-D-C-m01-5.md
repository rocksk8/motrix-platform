# 稽核：C 的 M01 ④ 修正——M4-M1／M2／M3（wip/c-m01-5 a1e0a45b；疊在 221adaa0 上，基底未變）（D，2026-09-27 11:02）

> 複核 AUDIT-D-C-m01-4 的三項必修。主持指定的複核重點：M01 在時題數不變。
> 反向控制用 sparse 工作樹（`!/backend/modules/case/`）；基準是 AUDIT-D-C-m01-4 §5。

## 0. 結論

- **M4-M1、M4-M2 關閉；M4-M3 的範圍與「M01 在時題數不變」成立；新必修 1（M5-M1）**。
- M5-M1 的源頭是主持當初的指示（「檔頭加 pytestmark」），主持已更正為「只標真的需要 M01 的題」，改派子代理修，C 不動。D 提供的逐題清單在 `docs/platform/audit/AUDIT-D-C-m01-5-red-nodeids.txt`（b5da1bad）。

## 1. 實測

| 項目 | D 的驗證 | 結果 |
|---|---|---|
| M4-M1：SO 提示 | e2e 改驗 DOM：提示可見、文字正確、選單 disabled；正對照改用 route 回 200。突變 SO1「提示不顯示」、SO2「選單不停用」⇒ **紅**（上一輪都存活） | **關閉** |
| M4-M2：§2-C 別組頁面 | 新題 `test_e2e_pages_without_case_module_2026_09_27`（網路規劃、請款單、出納、營運報表，各含正對照「看不到的案件」的 404 不算）。突變：N1 規劃提示不顯示、N2 搜尋不停用、N3 所有 404 都當模組不在、P1 請款提示不顯示、C1 出納照舊顯示 detail、R1 報表照舊泛用錯誤 ⇒ **6/6 紅** | **關閉** |
| M4-M3 範圍 | 標了 `requires_module／skip_module_unless("case")` 的 211 檔＝D 的 212 檔扣掉 SO 那檔（SO 那檔本來就要在 M01 不在時照跑）⇒ 範圍一致 | 成立 |
| M01 不在：只剩允許的紅 | 非 e2e（tests＋modules 全部）：3658 過、1255 略過、**9 紅＝§B-11 允許的 5 題＋M01 在時也紅的 4 題**（cm12×2、subproc_helper、vr1）；e2e：275 過、220 略過、**0 紅** | 成立 |
| **M01 在：題數不變**（主持重點） | 非 e2e：D 基準的 134 檔**逐檔通過數完全相同**（1256）；另有 6 檔（e2e 清單中含非 e2e 題的）全過；唯一的略過 `test_case_page_p4b_dialogs:82` 是既有的（221adaa0 就有）。e2e：78 檔中 77 檔與基準相同；`test_e2e_inflight_report[n2]` 在高負載時逾時 120s，單獨重跑 20/20 過 | **成立** |
| M4-S1 | 附件兩題的略過理由已改準確；「改驗 fail-closed」註明另補題 | 關閉（補題留建議） |

## 2. 發現

**M5-M1（必修，主持已接受並改派子代理）　整檔標記藏掉了在 M01 不在時本來會過的題**
- 209 檔用檔頭 `pytestmark`。依 221adaa0 真刪的結果，其中 **81 檔、462 題在 M01 不在時本來會過**，現在整檔略過。
- 例如：
  - `test_custom_modules_engine` 58 題只紅 2（L1 自訂模組引擎）；
  - `test_quote_json_lost_update` 43／1、`test_core` 38／1、`test_privacy_notice_forms` 34／5、`test_online_activity` 26／2、`test_high_risk_routes` 21／1。
- 另 10 檔用 `skip_module_unless` 整檔略過（137 題）。主持對模組層 import 的裁示是「改成延後 import」。
- 旁證：
  - M01 不在時，e2e 通過數由 312（221adaa0）降為 275；
  - C 自報非 e2e「5 過、1140 略過」。
- 修法：只在 D 清單上的題加 `@requires_module`；整檔都在清單上的才保留檔頭標記。那 10 檔把 import 移進函式後，重跑真刪決定逐題標記。
- 複核會驗兩件事：M01 在時逐檔通過數不變（§1 的基準）；M01 不在時，清單以外的題全部照跑、0 紅。

**觀察**
- **M5-O1**：`test_e2e_inflight_report[n2]` 在負載下被逾時砍掉，又在受測樹留下 `test_zz_td_probe_*.py`（M4-O3 重現）。這是 b-probe-tmp 前的寫法，該包合回後就消失。
