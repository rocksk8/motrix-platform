# 稽核：法規 R1～R3（法規參數版本化、零稅率／免稅依據、個資蒐集告知）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。
> 對象：`b547b4d3`、`f0904f0d`（R1）、`4c075adb`（R2）、`eed638ca`（R3）、`b8788ba5`、`f41398b9`、`d151b925`、`a76c1ab0`（IP-7）、`26040832`（bonus_insured_multiple）、`efddd6cd`（章節改號）。規格：CUSTOMIZATION-SPEC §9、MODULE-GUIDE §11、INTEGRATION-POINTS IP-7。
> 稽核基準 origin/platform `09f8fc70`，稽核樹 `D:\MOTRIX-PLATFORM-D`（detached），Python `D:\MOTRIX-PLATFORM\.venv312`（只用、未改）。測試一律單程序、低優先權、`--basetemp=%TEMP%\motrix-pytest-D-adhoc`。
> 分級：**必修**（不修不能關）／**建議**／**觀察**。關閉規則：被稽核者回覆後，由 D 確認才關。
> 縮寫：`LP`＝`backend/helpers/legal_params.py`、`PN`＝`backend/helpers/privacy_notice.py`、`PS`＝`backend/routers/payslips.py`、`PF`＝`frontend/pages/payslip-form.html`。

## 0. 結論

- 規格逐條大致落實：依單據日期選版本、單據凍結（快照）、已生效的版本不能改刪、門檻＝最低工資守門、跨年提示、零稅率／免稅依據、告知書與「已告知」紀錄。R 系列 4 檔 **63 passed**。D 自做突變 16 項：14 紅、2 存活（見 §3、S-6）。
- 法規數字與官方出處核對結果見 §2：扣繳率、門檻、費率、上限、最低工資、§7 九款、個資法 §8 六款都**相符**。沒有取得逐字官方表格或條文的，都標為「未核對」。
- **必修 2 項**：
  1. D-1：補充保費的捨入方式錯誤，而且前後端不一致。健保署規定「角以下四捨五入」；後端用 Python `round()`（銀行家捨入），前端用 `Math.round`。給付 35,000 元時，畫面顯示 739，存檔卻是 738。
  2. D-2：「已告知紀錄不能被覆蓋或清除」在並行修改時不成立：修改勞報單是「交易外讀取舊單 → 整包寫回」，實測已記錄的告知紀錄會被清掉。
- 建議 6 項、觀察 5 項。突變 16 項：14 紅、2 存活（S-6）。

## 1. 逐項驗收（CUSTOMIZATION-SPEC §9）

| 規則 | 驗收 | 證據 |
|---|---|---|
| 9.1 服務／相容 V9 `tax_rules` | ✅ | LP:319-332；沒有 `tax_rules_versions` 時，舊鍵視為 2026-01-01 生效的一版 |
| 9.1 選版（早於最早一版 ⇒ 拒絕） | ✅ | LP:91-103；`test_a_slip_dated_before_the_first_version_is_refused`；突變 M01 紅 |
| 9.1 單據凍結、前端快照不採用 | ⚠ 循序 ✅、並行 ❌ | PS:329-349、`_freeze_rules` 覆蓋前端送來的值；突變 M02、M12、M16 紅。並行修改見 D-2 |
| 9.1 已生效版本不能改刪 | ✅（有缺口，見 O-1） | LP:193-217；突變 M03 紅 |
| 9.1 獎金門檻倍數必填、舊資料補 4 | ✅ | LP:165-167、310-316；突變 M11、M15 見 §3 |
| 9.1 門檻＝最低工資守門 | ✅ | LP:113-124；PUT 400；突變 M04 紅 |
| 9.1 跨年提示 | ✅ | LP:220-252；突變 M09 紅 |
| 9.1 權限（superadmin；試算另允許 payslip 模組） | ✅ | `routers/legal_params.py:19,49`；`test_legal_params_endpoints_are_superadmin_only` |
| 9.1 預設只放 115 年、116 年不預設 | ✅ | LP:26-62；勞動部 2026-09-24 審議會決議「將由勞動部陳報行政院核定」，確實尚未核定 |
| 9.2 選項、何時必填、應稅移除依據 | ✅ | LP:260-305、`helpers/quotations.py::validate_tax_basis`；突變 M07、M08 紅 |
| 9.2 開票申請補填 | ✅ | `routers/invoice_vouchers.py:376-390`；突變 M13 見 §3 |
| 9.3 範本涵蓋 §8 I 六款 | ✅ | PN:21-40，逐款對照 §2 表的 L-10 |
| 9.3 列印告知書 | ✅（日期見 S-2） | `frontend/static/privacy-notice.js`；輸出前逐欄 escape |
| 9.3 已告知由伺服器蓋、不可覆蓋 | ⚠ 循序 ✅、並行 ❌、損毀 ❌ | PN:72-78、PS:81-91；突變 M05、M06、M10 見 §3。並行見 D-2，損毀見 S-3 |
| 9.3 不擋存檔 | ✅ | 沒勾選照存 |
| MODULE-GUIDE §11 守門 | ✅（範圍見 O-3） | `tests/platform/test_legal_params_single_source.py` |
| IP-7 契約 | ⚠ | 契約寫「CORE_VERSION 1.5」，R 實際合回在 1.7（`backend/core/CHANGELOG.md` 1.7 節）；`bonus_insured_multiple` 是後加的必填欄位，契約版本仍是 1（O-4） |
| L1 行為改變寫 CHANGELOG（§9d 檢查項） | ✅ | CHANGELOG 1.7 列出全部新增介面 |

## 2. 法規正確性（官方出處核對，查核日 2026-09-26）

| # | 項目 | 系統值 | 官方 | 判定 | 出處 |
|---|---|---|---|---|---|
| L-1 | 執行業務報酬（9A／9B）扣繳率（居住者） | 10% | 「執行業務者之報酬按給付額扣取百分之十。」 | ✅ 逐字 | 各類所得扣繳率標準 §2 I ⑧ https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=G0340028&flno=2 |
| L-2 | 兼職薪資／非每月給付的薪資（50）扣繳率 | 5% | 「兼職所得及非每月給付之薪資，扣繳義務人按給付額扣取百分之五。」 | ✅ 逐字 | 薪資所得扣繳辦法 §6 II https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=G0340013 |
| L-3 | 兼職薪資起扣標準（115 年） | 90,501 | 未達「薪資所得扣繳稅額表無配偶及受扶養親屬者之起扣點」免扣（辦法 §7 II ①）；115 年 90,501 | ⚠ **數字未核對逐字**：條文逐字取得；表格數字 PDF 轉檔後欄位遺失，只有多個二手來源一致 | 財政部 114.12.4 台財稅字第 11404675280 號公告 |
| L-4 | 9A／9B 起扣 20,010 | 20,010 | 「每次應扣繳稅額不超過新臺幣二千元者，免予扣繳。」條文寫的是**稅額**，不是給付額 | ✅ 逐字（換算條件見 O-5：20,010 只在稅額「元以下捨去」時成立，而捨入規則未核對） | 同標準 §13 https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=G0340028&flno=13 |
| L-5 | 扣繳稅額元以下 | `math.floor` | 查不到官方條文 | **未核對** | — |
| L-6 | 補充保費費率 | 2.11% | 2.11%（自 110.1.1 起） | ✅ | 衛福部公告 https://www.mohw.gov.tw/cp-16-57420-1.html |
| L-7 | 補充保費單次門檻 9A／9B | ≥ 20,000 | 「單次給付金額達新臺幣二萬元者，應…扣取」 | ✅ 逐字 | 扣取及繳納補充保險費辦法 §4 I https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=L0060027&flno=4 |
| L-8 | 兼職薪資補充保費門檻＝最低工資 | ≥ 29,500 | 免扣：「非所屬投保單位給付且未達中央勞動主管機關公告基本工資之薪資收入」（同辦法 §4 II ⑦）；115 年最低工資 29,500 元／時薪 196 元 | ✅ 逐字（條文用詞仍是「基本工資」） | 勞動部歷年調整 https://www.mol.gov.tw/1607/28162/28166/28180/70460/76761/ |
| L-9 | 單次上限 1,000 萬 | 10,000,000 | 「單次給付金額逾新臺幣一千萬元之部分…免予扣取」 | ✅ 逐字 | 健保法 §31 I 但書 https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=L0060001&flno=31 |
| L-10 | 獎金門檻 | 投保金額 × 4 | 「所屬投保單位給付全年累計逾當月投保金額四倍部分之獎金」；超過部分全數計收，不受 2 萬元門檻限制 | ✅ 逐字（A 的 U4 實作時要注意「全數計收、不看 2 萬」） | 健保法 §31 I ①、辦法 §4 I 但書 |
| L-11 | 職業工會會員免扣 | 50、9A、9B 都免 | 50：健保法 §31 I ②「但第二類被保險人之薪資所得，不在此限」（職業工會會員＝第二類）；9A／9B：辦法 §4 II ③「無一定雇主或自營作業而參加職業工會者之執行業務收入」 | ✅ 逐字（D 探針一度懷疑 50 不該免，查證後確認系統正確） | 同上 |
| L-12 | 補充保費捨入 | 後端 `round()`（銀行家）／前端 `Math.round` | 「保險費之繳納，以元為單位，角以下 4 捨 5 入。」 | ❌ **D-1** | 健保署 Q&A https://www.nhi.gov.tw/ch/cp-2947-71ec6-3150-1.html |
| L-13 | 非居住者：薪資 18%（1.5 倍基本工資以下 6%）、執行業務 20%、稿費每次 5,000 以下免扣 | 同左 | 本次未查 | **未核對** | — |
| L-14 | 營業稅法 §7 零稅率 | 9 款 | 9 款，款名與系統摘要相符 | ✅ 逐字 | https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=G0340080&flno=7 |
| L-15 | 營業稅法 §8 免稅 | 「第一項＋說明必填」 | 32 款（第 7 款已刪除）；逐字已經可以取得 | ✅（可改善，見 S-4） | https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=G0340080&flno=8 |
| L-16 | 個資法 §8 I 六款 | 範本 6 項 | 名稱、目的、類別、期間／地區／對象／方式、§3 權利、不提供的影響 | ✅ 逐字 | https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode=I0050021&flno=8 |
| L-17 | 116 年最低工資 30,900 | 不預設 | 審議會決議，「將由勞動部陳報行政院核定」 | ✅ | https://www.mol.gov.tw/1607/1632/1633/99195/post |

## 3. 反向控制與突變（D 自做，每項做完都用 `git checkout` 還原）

執行器：scratchpad `mutate.py`（每項斷言原字串恰好出現 1 次 → 替換 → 跑 R 系列 4 檔 → `git checkout -- <檔>` → 核對內容已還原）。

| 突變 | 結果 | 題數 | 轉紅的題（前 2） |
|---|---|---|---|
| M01-選版忽略日期 | 🔴 紅 | 5 failed, 58 passed | `test_rules_are_picked_by_effective_date`、`test_a_slip_dated_before_the_first_version_is_refused` |
| M02-修改一律重算 | 🔴 紅 | 2 failed, 61 passed | `test_editing_an_old_slip_keeps_its_version_unless_recalc_is_chosen`、`test_editing_a_legacy_slip_without_snapshot_uses_its_version_number` |
| M03-已生效可改 | 🔴 紅 | 1 failed, 62 passed | `test_an_effective_version_cannot_be_changed_or_deleted` |
| M04-門檻守門關閉 | 🔴 紅 | 2 failed, 61 passed | `test_guard_rejects_a_version_whose_threshold_differs_from_minimum_wage`、`test_put_rejects_the_threshold_mismatch` |
| M05-已告知可覆蓋（merge_ack） | 🔴 紅 | 2 failed, 61 passed | `test_recorded_ack_cannot_be_overwritten_or_cleared`、`test_merge_ack_keeps_the_existing_record` |
| M06-收前端偽造紀錄 | 🔴 紅 | 1 failed, 62 passed | `test_without_ack_nothing_is_recorded_and_forged_record_is_dropped` |
| M07-依據檢查關閉 | 🔴 紅 | 9 failed, 54 passed | `test_tax_basis_error[…]` 等 |
| M08-報價一律當草稿 | 🔴 紅 | 3 failed, 60 passed | `test_submitting_a_zero_rated_quote_without_basis_is_refused`、`test_exempt_under_article_8_requires_the_item_number` |
| M09-跨年提示關閉 | 🔴 紅 | 2 failed, 61 passed | `test_next_year_missing_from_december[…]`、`test_status_endpoint_reports_next_year_missing_in_december` |
| M10-承攬商紀錄可覆蓋（record_ack） | 🔴 紅 | 1 failed, 62 passed | `test_contractor_ack_is_recorded_once_and_audited` |
| M11-舊資料不補倍數 | 🔴 紅 | 7 failed, 56 passed | `test_db_seed_matches_the_default_version_and_passes_the_guard`、`test_bonus_insured_multiple_is_required` |
| M12-修改舊單不用快照（改用版本號查） | 🟢 **存活** | 63 passed | — ⇒ S-6 |
| M13-開票申請不擋 | 🔴 紅 | 1 failed, 62 passed | `test_invoice_request_on_an_old_quote_without_basis_needs_one` |
| M14-新單用今天而非單據日期 | 🔴 紅 | 2 failed, 61 passed | `test_new_slip_uses_the_version_of_its_date_and_stores_it` 等 |
| M15-倍數不驗 | 🔴 紅 | 1 failed, 62 passed | `test_bonus_insured_multiple_is_required` |
| M16-建立時收前端快照 | 🟢 **存活** | 63 passed | — ⇒ S-6 |

14 紅、2 存活。基準（未突變）R 系列 4 檔 63 passed（01:05）。

探針（`tests/test_zz_auditD_probe_r.py`，暫存、不 commit，跑完已刪）：

| 探針 | 結果 |
|---|---|
| 9A 給付 35,000 | 後端存 **738**；前端 `Math.round(738.5)`＝739；健保署規定 739 ⇒ D-1 |
| 兼職薪資 40,000＋職業工會 | 免扣。查證後判定正確（L-11） |
| 並行：A 修改（沒勾）卡在 `_calc`，同時 B 勾了「已告知」，之後放行 A | 最後 `privacyNotice` **＝None** ⇒ D-2 |
| `privacy_notice_acks` 設定值損毀後，再記錄一筆 | 回 200，整份被覆寫成只剩新的一筆 ⇒ S-3 |
| 今天 2026-09-25 新增一版 `effectiveFrom=2026-03-01`（費率改成 5%） | 被接受；之後開立的 4 月勞報單套用新版 ⇒ O-1 |

## 4. 發現

### 必修

**D-1　補充保費的捨入方式錯誤，而且前後端不一致**
- 位置：PS:127 `nhi_supplement = round(base * nhi_rate)`（Python 對 .5 採銀行家捨入，捨入到偶數）；PF:617 `Math.round(...)`（四捨五入）。
- 法規：健保署「以元為單位，角以下 4 捨 5 入」（L-12）。
- 影響：給付金額 20,000～2,000,000 之間共有 **99 個金額**，兩種捨入的結果不同（D 逐一比對）。例如 35,000 → 738（應為 739）、55,000 → 1,160（應為 1,161）。畫面試算、存檔、勞報單 PDF、申報金額會差 1 元；使用者看到的是 739，重新整理之後變成 738。
- 重現：`python -c "print(round(35000*0.0211))"` ⇒ 738；API：建立一張 9A、給付 35,000 的勞報單，`calc.nhiSupplement` 是 738。
- 建議修法：用 `Decimal(gross) * Decimal(str(rate))` 搭配 `quantize(Decimal(1), ROUND_HALF_UP)`；前端也改用同一套整數運算，避開浮點誤差，並補一題 .5 邊界題（35,000）。扣繳稅額的 `floor` 在 5%、6%、10%、18%、20% × 1～2,000,000 的範圍內都沒有浮點誤差（D 逐一比對），但它的法源未核對（L-5）。
- 附註：這個算法沿襲自 V9，但它屬於本次要求的「法規正確性」範圍。它也會影響 U4 獎金的補充保費，請 A 一併採用同一個捨入函式，建議放在 L1 `legal_params`，做成唯一來源。

**D-2　並行修改會清掉已記錄的「已告知」紀錄（同一條路徑也會蓋掉快照）**
- 位置：PS:318-321 在交易外讀取 `data_json`，PS:361 整包 `UPDATE`，中間沒有 `begin_write`（`core/txn.py` 的 lost-update 規則：「凡是讀 → 改 → 整包寫回的路徑，讀之前都要先呼叫這裡」）。
- 規格：CUSTOMIZATION-SPEC §9.3「已記錄的不能被覆蓋或清除」。
- 重現：見 §3 並行探針（用 monkeypatch 讓 `_calc` 等待一個 Event，模擬兩位管理者同時編輯）。結果 `privacyNotice` 從有紀錄變成 None。
- 建議修法：讀舊單之前先 `begin_write(conn)`，讀、合併、寫在同一個連線與交易裡；補一題並行反向控制（可以直接用 D 的探針）。

### 建議

- **S-1　開單日期預設用的是 UTC 日期**：PF:558 `new Date().toISOString().slice(0,10)`。台灣 00:00～07:59 開的新單，日期會是前一天。R1 讓這個日期決定法規版本：1 月 1 日早上開的單會套用前一年的規則。這行沿襲自 V9（`2c5f02f7`），是 R1 讓影響變大。建議改用本地日期。
- **S-2　告知書上的日期同樣是 UTC**：`frontend/static/privacy-notice.js:18`（R3 新寫的）。清晨列印的告知書會印成前一天，而它是當事人簽名的日期欄。
- **S-3　告知紀錄的設定值讀不懂時，會被整份覆寫**：PN:96-101 讀到 `ValueError` 或不是 dict 時，當成 `{}`，然後寫回只剩新的一筆 ⇒ 其他人員的告知紀錄全部消失，損毀的原始內容也被蓋掉。依〈降級之後它還是會動〉：讀不懂應該拒絕寫入並告警，不可以用空值寫回。
- **S-4　§8 免稅款次已經可以取得逐字條文**：32 款（第 7 款已刪除）。可以做成下拉選單，說明欄改成選填，只有「其他法律規定」才必填，減少手填錯誤。RUN-PLAN §4「使用者須知」寫的「沒有取得逐字條文」可以更新。
- **S-6　單據凍結有兩條路徑沒有題目守（突變 M12、M16 存活）**：
  - M12：修改舊單時不用快照、改用版本號查，全部綠。原因是題目裡的版本內容從沒變過，快照與查表結果相同。會出差別的真實情境：先開一張日期在**尚未生效版本**（例：2027）的單，之後管理者修改那一版（未生效的可以改），再修改那張單 ⇒ 規格要求沿用快照。
  - M16：**建立**時採用前端送來的 `taxRulesSnapshot`，全部綠。`test_a_snapshot_sent_by_the_client_is_ignored` 只驗了修改（PUT）；產品碼現在是對的（`_freeze_rules` 覆蓋），但沒有題目守。
  - 建議各補一題，並用這兩個突變證明題目會紅。
- **S-5　告知紀錄只存文字雜湊，沒有保存文字**：PN:63-69 只存 16 碼雜湊。公司日後修改告知文字，就無法用雜湊找回當時告知的內容，紀錄的舉證力有限。建議把每一版告知文字存在設定裡，以雜湊為鍵。

### 觀察

- **O-1　可以新增「過去生效」的版本**：已生效的版本不能改刪，但可以在它們之間插入一版 `effectiveFrom` 在過去的版本。插入之後，同一段日期的新單改用新版；舊單有快照，不受影響。規格的「要更正就新增一版」依賴這個行為，所以不是缺陷。但如果要整年更正，同一個生效日會被「生效日重複」擋下，只能用 01-02 這類日期。建議在規格寫明更正的做法，PUT 時也提示「這一版會改變 X 日以後新開單據的適用規則」。
- **O-2　法規版本依「開單日期」而不是「給付日」**：扣繳義務在給付時發生，起扣標準也是看給付年度。12 月底開單、1 月給付的單會套錯年度。畫面上的文字已經從規格寫的「依給付日」改成「開單日期」，但兩者是不是同一件事，沒有寫下來。建議在規格註明「開單日期＝給付日」，或者另外加一個給付日欄位。
- **O-3　單一來源守門只看 4 個數字，註解剝除也粗略**：`LEGAL_NUMBERS`＝90501／29500／0.0211／20010。20000、0.05、0.10、10000000 這些數字寫死在模組裡時抓不到；剝除註解時，一行裡只要出現 `//`（例如 `"https://…"`）就截斷，後面的程式碼也跟著看不到。U4 獎金是第二個使用方，要注意不要在 bonus 裡寫死 4 倍或 2.11%。
- **O-4　IP-7 的契約版本號與 CORE 版號不一致**：IP-7 寫「1（CORE_VERSION 1.5）」，實際在 1.7。`bonus_insured_multiple` 是後加的**必填**欄位（讀取時補值，但 PUT 缺這個欄位會回 400），契約版本卻沒有升。
- **O-5　9A／9B 起扣 20,010 的前提是「稅額元以下捨去」**：條文寫的是「應扣繳稅額 ≤ 2,000 免扣」。給付 20,001～20,009 元時，捨去 ⇒ 2,000 ⇒ 免扣；四捨五入 ⇒ 20,005 起就是 2,001 ⇒ 應扣。捨入規則查不到官方條文（L-5），建議請會計確認。

## 5. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | D 確認 |
|---|---|---|---|
| D-1 | | | |
| D-2 | | | |
| S-1 | | | |
| S-2 | | | |
| S-3 | | | |
| S-4 | | | |
| S-5 | | | |
| S-6 | | | |
| O-1～O-5 | | | |
