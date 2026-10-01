# 第 29 班第二稽核者報告（A29-B，2026-10-01）

被稽核：包 `20261001_212935_47db5613_full`（commit 47db5613）中 c7 為作者的五條線。方法：合成資料、單檔探針、突變；不跑全量；暫存已刪。探針：`backend/tests/_probes/test_probe_*.py`（本分支，可重現）。清單：`docs/platform/plans/TRAIN29-AUDIT-2.md`。

## 必修（先看）
| # | 發現 | 證據 | 建議 |
|---|---|---|---|
| **F1** | **勞報單（payslips）詳情與 PDF 對 admin（有 `payslip` 模組）回傳個人外包人員完整銀行帳號**；c7 的遮蔽（協力廠商／憑據／名冊／佇列／PDF）沒涵蓋這條路 | 探針 `test_probe_bank_sweep.py`：`GET /api/payslips/PS-SW-1` 與 `/pdf-download`，帳號 `11122233344455` 對 `sw_admin`（admin＋payslip 等）全碼可見（superadmin 同樣可見＝正對照）；`/api/payslips` 清單與 cashier 的 payslip-queue 沒洩漏。檔：`modules/payroll/api/payslips.py`（路由約 326、539 行） | 若使用者的裁示「承攬商／外包人員帳號只有最高管理者看完整」涵蓋勞報單 ⇒ 詳情與 PDF 比照遮蔽（admin 看 `****末四碼`；編輯送回遮蔽值＝保留舊值）；若勞報單作業人員需要完整帳號 ⇒ 由使用者明確裁示例外並寫進規則。**需裁示或修正，二擇一前不可宣稱「帳號只有最高管理者看得到」。** |

## 測試缺口（非洩漏）
- **G1**：c7 的 `test_bank_account_mask_2026_10_01.py` 沒抓到「PDF 不遮蔽」：突變 M-A6（`generate_contractor_voucher_pdf_bytes(..., mask_bank=False)`）該檔 **9 passed（假綠燈）**；我的掃描探針對同一突變紅。建議把 PDF 文字抽取（pypdf）比對加進該檔。
- **G2**：`bank_mask.keep_if_masked` 是死碼（突變 M-A8 綠＝沒人呼叫）；實際守門是 `vendor_contractors.py` 內嵌的 `is_masked_value` 判斷（突變 M-A8b 紅）。建議刪死碼或改成呼叫它，免得日後有人只改一邊。

## 逐項結果
| 項目 | 結果 | 說明 |
|---|---|---|
| Q1 外包人員名冊（`contractors`）帳號 | ✅ 已修 | `/api/contractors`、`/{id}`、`/export`（xlsx 以 openpyxl 解析）對 admin／持 `contractor_list` 的非 admin 皆遮蔽；superadmin 完整（正對照） |
| Q2 憑據 snapshot／PDF／簽核佇列／詳情 | ✅（PDF 缺測見 G1） | 角色（admin、非 superadmin 簽核人、cashier＋finance、contractor_list 持有者）× 24 個輸出面掃描：除 F1 外 0 洩漏；存摺影像 0 洩漏 |
| Q3 arap／會計 | ✅ | 只處理公司端銀行科目，沒有收款人帳號 |
| Q4 刪模組檔案路徑跳脫 | ✅ 已修 | 同一探針：根目錄內檔被刪、絕對路徑與 `../` 檔案都沒被刪（`custom_files._safe_physical_path`） |
| Q5 標已讀範圍 | ✅ | 只標自己、同類型、同單；其他類型／其他單不動 |
| Q6 橫幅／角標與佇列 | 已接受（第 31 班待辦） | 同層第二簽核人 count＝1 但簽核 403；已記 TRAIN31-BACKLOG |
| 部門跟業務負責人 | ✅ | 獨立重算（receivables-monthly）：全部 123,000＝部門 A 100,000＋部門 B 3,000＋未分類 20,000；帳號／純名字（未分類）／沒填（退回開單者）三種都對 |
| 刪除模組（含選單位置） | ✅ | 未登入 401、user／admin 403、superadmin 200；再刪 404；送審中 409；有單據 409＋筆數、`with_records=1` 才刪；怪 key 不丟 500；稽核每次一筆；刪後定義列 0 |
| manifest VR3 | ✅ | 已出貨 462 條逐字相同（0 缺／改）；未出貨 6 條、模組無重複；合併後的「模組建構器」條目含刪除模組＋選單位置兩段內容 |
| 作者測試 | ✅ | `test_bank_account_mask_2026_10_01`＋payroll 帳號測試 31 passed |
| 突變（遮蔽線）| 6 條：4 紅、2 綠 | 綠＝G1、G2（見上）；其餘 M-A1／A2／A5／A7 紅 |

## 判定
**A29-B VERDICT: PASS WITH ACCEPTED RISK (user ruling 2026-10-01: F1 deferred to train 31)**
- F1（勞報單詳情／PDF 對 admin 回完整帳號）＝現行正式機行為、非本班回歸；使用者裁示本班照出，第 31 班修（遮蔽詳情與 PDF；admin 看 `****末四碼`；遮蔽值送回＝保留舊值）。
- 其餘四條線＋Q1／Q4 PASS；G1（PDF 遮蔽斷言用 pypdf）、G2（`keep_if_masked` 死碼）已登記 TRAIN31-BACKLOG。
