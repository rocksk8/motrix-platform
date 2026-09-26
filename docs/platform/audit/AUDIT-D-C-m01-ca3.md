# 稽核：C 的 M01 ③——13 個提供者改由 ModuleSpec 宣告（wip/c-m01-ca3 8999d769；疊在 c-case404 6ddb817c 上）（D，2026-09-27 01:40）

> 標準等級。稽核者 D 沒有寫過任何受稽核的程式碼。
> 內容：M01 的 13 個提供者改由 `ModuleSpec.providers` 宣告，刪除 import 時登記（`registry.provide`）；ATT 的 `helpers/case_attachments.py` 移入 `modules/case/attachments.py`；契約題 `test_case_module_spec.py`。

## 0. 結論

- **必修 1、建議 1、觀察 3**。
- C 只跑了 tests/platform（1251）。依主持指示，D 把 modtest 選題補跑列為驗證項，必修就是在選題裡抓到的，**不在 tests/platform 裡**。

## 1. 實測

| 項目 | D 的驗證 | 結果 |
|---|---|---|
| 宣告與刪除一一對應 | ModuleSpec 的 13 列 ⇔ 被刪的 13 處 `registry.provide` | 成立 |
| 執行期提供者（6ddb817c ⇔ 8999d769，M01 在） | `registry.providers(cap)` 全部相同；唯一差別是 `attachments.for_document\|case` 的實作位置，從 `helpers.case_attachments` 改成 `modules.case.attachments` | 成立 |
| import 時登記表 | `_LEGACY_PROVIDERS` 裡 case 的項目 0 筆。剩下的 approval.reassign\|voucher、attachments.for_document\|arap、calendar.writeback\|invoice_voucher／payment_request 屬其他模組，不在本包範圍 | 成立 |
| 舊路徑殘留 | 產品碼與測試都沒有 import `helpers.case_attachments`（`voucher_attachments.case_attachments` 是同名的不同函式） | 成立 |
| 突變（D2） | MS1：ModuleSpec 少宣告 `case.doc_version` ⇒ **紅**（declares_every／none_of_them 兩題）；MS2：`modules/case/quotations.py` 加回 import 時的 `registry.provide` ⇒ **紅**（no_import_time／none_of_them 兩題）⇒ 2/2 紅 | 成立 |
| 真刪 M01（D2，tests/platform） | 1159 過、11 skip、66 failed＋14 errors＝**80 紅，與 ② 的 80 相同**；新增的 skip 是 test_case404 4 題與 test_case_module_spec 3 題，都附「M01 不在這個安裝包（§B-11）」的理由；`test_attachments_providers` 需要 M01 的項目 8→9 | 成立 |
| **modtest 選題**（`--changed-since 6ddb817c`，工作樹疊 b-modtest-batch-2 f3be5cd2 的 modtest.py／test_map.py，`-n 2`） | 609／683 檔分 2 批：第 1 批 3148 過 **2 紅**；第 2 批 1793 過 **1 紅**；總摘要 4941 過、3 紅、56 skip，exit 1；沒有「選到的檔沒有結果」 | 見 §2 |

### modtest 3 紅逐題判讀（每題都在乾淨的 D2 上重跑：8999d769 與基底 6ddb817c）

| 題 | 8999d769 | 6ddb817c | 判定 |
|---|---|---|---|
| `modules/netplan/tests/test_netplan_case_access.py::test_reverse_without_m01_plans_work_but_cannot_bind` | 紅 | 過 | **本包造成 ⇒ CA3-M1** |
| `tests/platform/test_env_and_load_guards.py::test_partial_cap_uses_the_e2e_cap_when_e2e_is_picked` | 過 | — | D 的量測裝置造成：疊上的新版 modtest（不看檔名）配 8999d769 的舊題（期望看檔名）。不歸本包 |
| `tests/test_version_manifest_2026_09_22.py::test_vr1_the_manifest_is_not_older_than_the_newest_commit` | 紅 | 紅 | 基底就紅（版本紀錄停在 09-26，最新 commit 在 09-27），與本包無關 ⇒ 觀察 CA3-O1 |

## 2. 發現

**CA3-M1（必修）　netplan 的反向題仍然從 import 時登記表拿掉 `case.access`**
- `test_netplan_case_access.py::_drop` 用 `monkeypatch.delitem(registry._LEGACY_PROVIDERS, ("case.access", "case"))`。③ 把 `case.access` 改成 ModuleSpec 宣告後，這個鍵已經不在該表 ⇒ `KeyError`。
- 這題有斷言 `single_provider("case.access") is None`，所以壞掉時是大聲紅，不是假綠。
- 修法：改用 `test_case_stage_connectors._without` 的作法，兩張表都查：`_LEGACY_PROVIDERS` 有就刪，否則刪已載入模組的 `spec.providers`。
- C 只跑 tests/platform，這題在 `modules/netplan/tests`，所以沒看到。

**CA3-S1（建議）　「拿掉一個提供者」有 3 種寫法，各模組各寫一份**
- 全 repo 模擬「提供者不在」的寫法有三種：
  - ① 只 `delitem(_LEGACY_PROVIDERS, key)`：netplan，也就是 CA3-M1；
  - ② 過濾 `_LEGACY_PROVIDERS`，並另外把 `registry.providers` 改成回空：arap bonus_payouts_absent、payroll bonus_payout_connectors、subcontract dispatch_row、tests/platform dispatch_connector；
  - ③ 過濾後斷言 `single_provider is None`：payroll voucher 兩檔。
- D 原先懷疑 ② 與 ③ 會在能力改成 ModuleSpec 宣告後靜默失效，逐檔查過後**不成立**：② 另外改了 `providers`，③ 有事後斷言；bonus.*、dispatch.row 已經在 ModuleSpec，題目照樣有效。
- 會踩到的只有 ①，而且是大聲紅。建議把 `test_case_stage_connectors._without`（兩張表都查、拿掉後斷言）下沉成共用夾具，之後搬遷不必逐檔追。

**觀察**
- **CA3-O1**：`test_vr1`（版本紀錄落後最新 commit 的日期）在基底 6ddb817c 就紅，與本包無關。列車合回時要補版本紀錄。
- **CA3-O2**：`docs/platform/plans/ATTACHMENTS-PLAN.md` 第 44、93 行仍寫 M01 提供者在 `helpers/case_attachments.py`；M01-PLAN ⑤ 的「已知例外＋到期守門」依 CHANGELOG 已不需要。兩處文件建議順手更新。
- **CA3-O3（給 B／主持）**：modtest 差異題**不指定 `-n` 就是串行**（`partial_cap` 只會壓上限，不會補上 -n）。D 第一次沒帶 `-n` 跑，7 分鐘只跑到 8%，改 `-- -n 2` 後兩批合計 39 分鐘。選題 609 檔時，建議預設就帶上限值。
