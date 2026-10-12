# 文件清查（第55班；唯讀，只提案，刪不刪由使用者決定）

> 基底 `origin/platform` c14f0a1df（M1-a 已上線基準）。方法：`git ls-files` 取根目錄與 `docs/**` 的 `.md`（377 份，8741 KB）；每份算最後 commit 日期，並在全部追蹤的文字檔（py、js、html、json、ps1、bat、sh、md）裡搜檔名與相對路徑，分成測試／工具／程式／其他文件／兩份產生索引；再逐一人工核對『誰真的開檔讀它』。不跑 pytest、不建包、不刪檔、不寫共用樹。

## 0. 結論

| 判定 | 份數 | 容量 |
|---|---:|---:|
| KEEP（含 KEEP\*：測試或工具真的開檔讀） | 308 | 7291 KB |
| ARCHIVE（建議搬 `docs/platform/archive/`，git mv 保留歷史） | 68 | 1447 KB |
| SAFE-TO-DELETE | 1 | 2 KB |

1. **真正能安全刪的只有 1 份**；其餘『沒人讀』的檔多半是已完工的規格、報告、步驟檔，價值在歷史追溯，建議搬 archive 而不是刪。
2. 建議搬的 68 份共約 1447 KB；大宗是 docs/quick 兩份已封閉期間的更新紀錄（346KB）、RUN-LOG（105KB）、DOC-CLEANUP-INVENTORY-T48（52KB）、prod-tasks 十份舊班步驟檔（約 240KB）。
3. 第48班清理已搬 45 份到 archive 並設 export-ignore；本次是第二輪，不含那 45 份。
4. 一個會影響客戶包的事實：`docs/platform/**`（除 archive）沒有 export-ignore，`audit/` 112 份、`plans/` 57 份、`prod-tasks/` 14 份目前都會進客戶包（第48班結果文件已列為待裁示，至今未決）。ARCHIVE 搬移會順便讓其中一部分不再出貨。
5. 現行文件有 197 條反引號路徑指向不存在的檔（`final_verify.find_dangling_links` 實測），多數是歷史文件；CORE-SPEC、INTEGRATION-POINTS、UPDATE-DELIVERY、RUN-PLAN 等現行文件各有 1～2 條，見 §5.2。

## 1. 搬移前必須知道的硬性事項（避免清理反而紅燈）

- `tools/platform/final_verify_allow.json` 的 root_files 列了根目錄允許的追蹤檔（含 14 份 md）；搬走或新增根目錄 md 要同步改這份，否則 final_verify 紅。
- `tools/platform/final_verify.py` 掃 docs/quick 與 docs/platform（排除 archive、windows、audit）的 markdown 連結與反引號路徑；被搬走檔案的現行引用要在同一個 commit 修正，或加進 allow-list 的 dangling 項。
- HG1（`test_homoglyphs_in_docs`）掃 `docs/**/*.md`、MD1（`test_md_split_identifiers`）掃編號宣告列：搬進 archive 仍會被掃；本文件也遵守（單行表格、不拆編號）。
- `docs/windows/**`、`docs/platform/archive/**`、`docs/quick/**` 已 export-ignore（`.gitattributes` 與 final_verify V2.4 成對檢查）；搬進 archive 用 git mv，並維持 archive 的 export-ignore 規則。第48班實例與陷阱見 `DOC-CLEANUP-RESULT-T48.md`。
- CACHE-INDEX 來源檔 6 份（CORE-SPEC、MULTIWIN-PROTOCOL、MODULE-GUIDE、PLAYBOOK、quick/architecture、FINANCE-INTEGRATION）：改動它們要重產 CACHE-INDEX，否則 `test_cache_index_fresh` 紅。
- 受保護：`docs/windows/STATE.md`、`SCOPE.md`、各模組 `CHANGELOG.md`／`SPEC.md`、`RUN-PLAN.md`、`docs/platform/audit/*` 全部判 KEEP，不提案移動。我另外核對過所有 `open()`／`read_text()` 類引用，除 §2 列的之外沒有其他被開檔讀的文件。

## 2. 硬讀清單（測試／工具真的開檔；不可動）

| 檔案 | 誰讀 |
|---|---|
| `docs/windows/STATE.md` | test_spec_coverage 讀；MD1／HG1 掃 |
| `docs/windows/SCOPE.md` | test_spec_coverage 讀；MD1／HG1 掃 |
| `docs/platform/RUN-PLAN.md` | test_core_only_rc 讀 |
| `docs/platform/PLAYBOOK.md` | test_core_only_rc 讀；CACHE-INDEX 來源檔 |
| `docs/platform/CACHE-INDEX.md` | test_cache_index_fresh、final_verify 讀 |
| `docs/platform/CORE-SPEC.md` | CACHE-INDEX 來源檔（test_cache_index_fresh 比來源 commit） |
| `docs/platform/MODULE-GUIDE.md` | test_l1_interface_snapshot 讀；CACHE-INDEX 來源檔 |
| `docs/platform/FINANCE-INTEGRATION.md` | CACHE-INDEX 來源檔 |
| `docs/quick/architecture.md` | CACHE-INDEX 來源檔 |
| `MULTIWIN-PROTOCOL.md` | CACHE-INDEX 來源檔；HG1／MD1 掃 |
| `docs/platform/UNIT-INDEX.md` | 產生檔；test_unit_cards、test_regen_all 讀 |
| `docs/platform/INTEGRATION-POINTS.md` | test_integration_points_registered、final_verify V3.4b 讀 |
| `docs/platform/MONEY-FLOWS.md` | test_money_flows_registered 讀 |
| `docs/platform/UPDATE-DELIVERY.md` | test_apply_module_update_ps1／test_module_update_delivery 讀 |
| `docs/platform/MODULE-UPDATE-DELIVERY.md` | 同上 |
| `docs/platform/THIRD-PARTY-LICENSES.md` | test_font_license 讀 |
| `CHANGELOG.md` | 版本槽測試與 core_bump、final_verify 讀 |
| `DEPLOY.md` | test_verify_package_export_ignore_list 讀 |
| `docs/platform/audit/*.md`（112 份） | `tools/platform/mustfix_scan.py`、`test_mustfix_closure_scan` |
| `backend/modules/*/SPEC.md`、`CHANGELOG.md` | `test_spec_coverage`、changelog 版本槽測試（模組內文件，不在本次清查範圍） |
| `docs/**/*.md` 全部 | HG1 同形字掃描；`docs/windows` 與 `docs/platform/archive` 另有 export-ignore 檢查 |

未列在上面的文件，經逐檔核對，測試／工具對它們只有註解或 docstring 提及，不開檔。

## 3. ARCHIVE 建議（68 份，1447 KB）

分批建議：第一批 prod-tasks 十份＋quick 兩份舊 changelog＋RUN-LOG＋DOC-CLEANUP 兩份（最大容量、最低風險）；第二批 plans 各班備註；第三批 docs/windows 完工規格；根目錄四份（動 root_files allow-list）最後做。

| 路徑 | KB | 最後 commit | 理由與證據 |
|---|---:|---|---|
| `GITFLOW.md` | 2 | 2026-07-22 | START-HERE 第8節已標過期（舊 master 時代）；已 export-ignore；root_files allow-list 要同步改 |
| `MODULE-AUDIT-2026-09-13.md` | 26 | 2026-09-14 | 09-13 模組稽核 26KB，一次性；測試 docstring 提及（不開檔） |
| `WEEKLY-AUDIT-2026-09-07_2026-09-10.md` | 45 | 2026-09-11 | 09-11 週稽核報告 45KB，一次性；只有 allow-list 與註解提及 |
| `docs/platform/BUILD-VERIFY-OPTIMIZATION-T47.md` | 13 | 2026-10-08 | 第47班建包優化報告，已併 PLAYBOOK |
| `docs/platform/IMPROVEMENT-REPORT.md` | 56 | 2026-09-28 | 56KB 09-28 改善報告；僅稽核文件與程式註解引用 |
| `docs/platform/RUN-LOG.md` | 105 | 2026-09-27 | 105KB 流水帳，09-27 止；進度已由 RUN-PLAN 第6節與 runplan 封存接手 |
| `docs/platform/plans/DOC-CLEANUP-INVENTORY-T48.md` | 52 | 2026-10-09 | 一次性清查（52KB）；含約 40 條指向已搬／已刪檔的連結，是 final_verify 連結檢查的最大噪音源 |
| `docs/platform/plans/DOC-CLEANUP-RESULT-T48.md` | 3 | 2026-10-09 | 一次性結果報告，零引用；本身含 5 條失效連結 |
| `docs/platform/plans/DOCSYNC-N39-T52.md` | 6 | 2026-10-10 | 同上（平台層） |
| `docs/platform/plans/DOCSYNC-T52.md` | 2 | 2026-10-10 | 一次性文件同步報告 |
| `docs/platform/plans/ENDPOINT-AUDIT-W1A-T48.md` | 9 | 2026-10-09 | 第48班端點稽核結果，零引用 |
| `docs/platform/plans/ENDPOINT-AUDIT-W1B-T48.md` | 6 | 2026-10-09 | 同上 |
| `docs/platform/plans/ENDPOINT-AUDIT-W1C-T48.md` | 7 | 2026-10-09 | 同上 |
| `docs/platform/plans/GENERATED-FILES-PROPOSAL.md` | 8 | 2026-09-26 | 產生檔提案，已實作（tools/platform/regen_all）；僅測試 docstring 引用 |
| `docs/platform/plans/HANDOFF-AB-T47.md` | 6 | 2026-10-09 | 第47班交接，班已結 |
| `docs/platform/plans/OVERHEAD-25PCT-CUTOVER-RUNBOOK-T48.md` | 7 | 2026-10-09 | 切換已於 10-10 00:59 完成；需連動改 START-HERE 必讀第7項 |
| `docs/platform/plans/PO-VENDOR-BANK-GAP-T47.md` | 3 | 2026-10-08 | 缺口紀錄，已被 docs/platform/PO-VENDOR-BANK-GAP-T47.md（選項與裁示）承接；兩檔同名易混 |
| `docs/platform/plans/R2-STEP2-IMPLEMENTATION-NOTES.md` | 5 | 2026-10-09 | R2 步驟2 實作備註，已併 |
| `docs/platform/plans/T46-BASELINE-118-RELEASE-NOTES.md` | 1 | 2026-10-08 | 第46班發行備註，已上線 |
| `docs/platform/plans/T47-POLICY-QUESTIONS.md` | 5 | 2026-10-08 | 第47班待裁題，裁示已記在 USER-DECISIONS |
| `docs/platform/plans/T48C-RELEASE-NOTES.md` | 7 | 2026-10-09 | 第48c班發行備註，已上線；僅 train50 步驟檔引用 |
| `docs/platform/plans/VISIBILITY-TIGHTENING-T49.md` | 2 | 2026-10-09 | 第49班可見範圍收緊備註，已併 MODULE-GUIDE 14.2 |
| `docs/platform/prod-tasks/20261006-train42-apply.md` | 11 | 2026-10-06 | 第42班步驟檔，已上線；正式機權威副本在雲端交付夾 |
| `docs/platform/prod-tasks/20261006-train43-apply.md` | 29 | 2026-10-06 | 同上（第43班） |
| `docs/platform/prod-tasks/20261007-train44-apply.md` | 20 | 2026-10-07 | 同上（第44班） |
| `docs/platform/prod-tasks/20261007-train45-apply.md` | 25 | 2026-10-08 | 同上（第45班） |
| `docs/platform/prod-tasks/20261008-train46-apply.md` | 32 | 2026-10-08 | 同上（第46班） |
| `docs/platform/prod-tasks/20261009-train47-apply.md` | 23 | 2026-10-09 | 同上（第47班） |
| `docs/platform/prod-tasks/20261009-train48a-apply.md` | 23 | 2026-10-09 | 同上（48a）；內含已不存在的路徑 tools/overhead_migrate.py |
| `docs/platform/prod-tasks/20261009-train49-apply.md` | 24 | 2026-10-09 | 同上（第49班） |
| `docs/platform/prod-tasks/20261010-train50-apply.md` | 27 | 2026-10-09 | 同上（第50班）；含失效路徑 tools/overhead_migrate.py |
| `docs/platform/prod-tasks/20261010-train51-apply.md` | 25 | 2026-10-10 | 同上（第51班） |
| `docs/platform/runplan/RUN-PLAN-ARCHIVE-2026-09-26_2026-09-27.md` | 58 | 2026-09-30 | RUN-PLAN 封存段（58KB）；test_core_only_rc 與 core_only_rc 工具提到 runplan，搬前先核對是否讀此目錄 |
| `docs/quick/changelog-2026-07-18_2026-09-08.md` | 150 | 2026-09-23 | 150KB 已封閉期間的更新紀錄；僅 QUICK 索引引用 |
| `docs/quick/changelog-2026-09-08_2026-09-14.md` | 196 | 2026-09-23 | 196KB 已封閉期間的更新紀錄（全倉最大的非 STATE 文件） |
| `docs/windows/AUDIT-2026-09-22.md` | 9 | 2026-09-22 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/AUDIT-SPEC-COVERAGE.md` | 13 | 2026-09-23 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/DELIVERY-NOTE-2026-09-22-PM.md` | 6 | 2026-09-22 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/DELIVERY-NOTE-2026-09-23.md` | 7 | 2026-09-23 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/DELIVERY-NOTE-DRAFT.md` | 22 | 2026-09-22 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/DELIVERY-NOTES-2026-09-25.md` | 10 | 2026-09-25 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/DEV-TEST-CHECKLIST-2026-09-25.md` | 18 | 2026-09-24 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/HEALTH-2026-09-22.md` | 8 | 2026-09-22 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/PIP-AUDIT-2026-09-22.md` | 2 | 2026-09-22 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/PLAN-TEST-PERF-e2e-classify.md` | 9 | 2026-09-25 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-AC2-RECOGNITION.md` | 4 | 2026-09-24 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-BN16.md` | 16 | 2026-09-23 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-BN20.md` | 8 | 2026-09-23 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-CU5-8.md` | 3 | 2026-09-24 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-EM11.md` | 7 | 2026-09-23 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-EM12.md` | 8 | 2026-09-23 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-EM13.md` | 17 | 2026-09-23 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-EM2-ROLE-LABELS.md` | 17 | 2026-09-23 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-EM7.md` | 13 | 2026-09-23 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-IA1.md` | 16 | 2026-09-23 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-JV10-JV11.md` | 14 | 2026-09-23 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-JV21.md` | 20 | 2026-09-23 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-JV25.md` | 7 | 2026-09-23 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-JV6.md` | 14 | 2026-09-23 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-MG3.md` | 17 | 2026-09-23 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-MG4.md` | 11 | 2026-09-23 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-PK1.md` | 16 | 2026-09-23 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-QL25-LOCATION-SNAPSHOT.md` | 23 | 2026-09-23 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-QN1-QUOTE-RENAME.md` | 21 | 2026-09-23 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-SL1.md` | 9 | 2026-09-23 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-UP1.md` | 9 | 2026-09-23 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-UP2.md` | 11 | 2026-09-23 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-UP3.md` | 9 | 2026-09-23 | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |

## 3.1 搬移時現行文件要同步修的引用（final_verify 會掃到）

| 被搬的檔 | 現行引用它的文件 |
|---|---|
| `GITFLOW.md` | `docs/quick/architecture.md`、`docs/quick/known-limits.md` |
| `MODULE-AUDIT-2026-09-13.md` | `MOTRIX-ERP-QUICK.md`、`SELLABLE-AND-MOBILE-SPEC.md`、`docs/quick/known-limits.md`、`docs/quick/security.md` |
| `WEEKLY-AUDIT-2026-09-07_2026-09-10.md` | `MOTRIX-ERP-QUICK.md`、`docs/quick/changelog.md`、`docs/quick/ops-deploy.md` |
| `docs/platform/IMPROVEMENT-REPORT.md` | `docs/platform/CORE-SPEC.md`、`docs/platform/PLAYBOOK.md`、`docs/platform/RUN-PLAN.md` |
| `docs/platform/RUN-LOG.md` | `docs/platform/CORE-SPEC.md`、`docs/platform/PLAYBOOK.md` |
| `docs/platform/plans/OVERHEAD-25PCT-CUTOVER-RUNBOOK-T48.md` | `docs/platform/MONEY-FLOWS.md`、`docs/platform/PROD-DEV-CHANNEL.md`、`docs/platform/RUN-PLAN.md` |
| `docs/platform/plans/PO-VENDOR-BANK-GAP-T47.md` | `docs/platform/PO-VENDOR-BANK-GAP-T47.md` |
| `docs/platform/plans/VISIBILITY-TIGHTENING-T49.md` | `docs/platform/MODULE-GUIDE.md` |
| `docs/platform/prod-tasks/20261006-train43-apply.md` | `docs/platform/RUN-PLAN.md` |
| `docs/platform/prod-tasks/20261007-train44-apply.md` | `docs/platform/RUN-PLAN.md` |
| `docs/platform/prod-tasks/20261007-train45-apply.md` | `docs/platform/RUN-PLAN.md` |
| `docs/platform/prod-tasks/20261008-train46-apply.md` | `docs/platform/PROD-DEV-CHANNEL.md` |
| `docs/platform/runplan/RUN-PLAN-ARCHIVE-2026-09-26_2026-09-27.md` | `docs/platform/RUN-PLAN.md` |
| `docs/quick/changelog-2026-07-18_2026-09-08.md` | `MOTRIX-ERP-QUICK.md`、`docs/quick/changelog.md` |
| `docs/quick/changelog-2026-09-08_2026-09-14.md` | `MOTRIX-ERP-QUICK.md`、`docs/quick/changelog.md` |

未列的 ARCHIVE 項目沒有現行文件引用，可直接 git mv。

## 4. SAFE-TO-DELETE 建議（1 份）

| 路徑 | KB | 最後 commit | 證據 |
|---|---:|---|---|
| `docs/windows/DATA-EM7-39.md` | 2 | 2026-09-23 | EM7 的 39 筆原始掃描輸出；全倉零引用（連檔名主體都無），可由掃描指令重現，SPEC-EM7 才是結論文件 |

其餘 ARCHIVE 候選都有結論文件或裁示記錄附在別處，但仍有歷史價值；我刻意不判 SAFE-TO-DELETE。

## 5. 與現況矛盾／過期的內容

### 5.1 桌面導引 `MOTRIX-PLATFORM-START-HERE.md`（不在 repo；10-10 02:30 版）

| 段落 | 目前寫 | 實際（git 核對 c14f0a1df） |
|---|---|---|
| 第1節 基準 | origin/platform 為 cab72495d、tag prod/18aed9a3、第50班 | c14f0a1df、tag prod/4eb52138（M1-a 已上線）；schema 仍 118 |
| 第1節 進行中／排隊 | 第51、52班 | 已進入 M1-a／M2；第51～53班步驟檔都在 prod-tasks |
| 第1節 營業利益口徑 | 已切 v2 | 仍正確但屬歷史事實，可縮成一行 |
| 第2節-3 最新步驟檔 | 20261010-train50-apply.md | 最新是 20261011-m1a-apply.md（與 train53） |
| 第5節 必讀第7項 | OVERHEAD-25PCT-*、T48C-RELEASE-NOTES 等 | 若採用本提案搬移，必讀要連動改；建議換成設定中心、權限矩陣、擇一方案等現行設計 |
| 第8節 過期清單 | 提到根目錄 NEXT-SESSION.md | 該檔已在第48班搬 archive；GITFLOW.md 仍在根目錄（本提案列 ARCHIVE） |
| 全文 | 沒有 M2／M3、設定中心、權限矩陣、刪除暫存區 | 這四條是 10-10 起的主線，導引完全沒提 |

### 5.2 repo 內文件

- `MULTIWIN-PROTOCOL.md`（76KB）指向 docs/windows/STATE.md 屬 V9 時代協定；它是 CACHE-INDEX 來源檔且被 HG1／MD1 掃，不可刪、改動要重產 CACHE-INDEX。建議只更新首段指向。
- `docs/platform/RUN-PLAN.md` 有一條壞路徑：`docs/platform/prod-tasks/archive/docs/platform/prod-tasks/20260929-train22-apply.md`（第48班搬移時路徑被重複前綴；實際在 `docs/platform/archive/docs/platform/prod-tasks/`）。
- 現行文件的失效反引號路徑（只列副檔名為程式／文件者，且排除歷史文件）：

| 文件 | 失效路徑 | 處置建議 |
|---|---|---|
| `docs/platform/CORE-SPEC.md` | `tools/verify_package.py` | 核對現位置後更正 |
| `docs/platform/INTEGRATION-POINTS.md` | `tools/check_approval_queue_coverage.py` | 核對現位置後更正 |
| `docs/platform/MODULE-UPDATE-DELIVERY.md` | `backend/tools/module_update.py` | 實際為 tools/platform/module_update.py |
| `docs/platform/UPDATE-DELIVERY.md` | `tools/platform/deliver.py` | 核對現名 |
| `docs/platform/DATA-COMPAT.md` | `tools/apply_update.ps1` | 核對現位置 |
| `docs/platform/STAGE-C-DESIGN.md` | `frontend/static/menu-icons.js` | 核對現名 |
| `docs/platform/plans/OVERHEAD-25PCT-OPERATING-PROFIT-DESIGN-T48.md` | `tools/platform/overhead_rollback.py、frontend/static/profit-labels.js` | 核對；若已移除註明『已落地並移除』 |
| `docs/platform/plans/SETTLEMENT-ACTUALS-SPEC.md` | `docs/platform/audit/AUDIT-0C-settlement-recon.md` | audit 內不存在此檔 |
| `docs/platform/plans/USER-DECISIONS.md` | `TRAIN31-BACKLOG.md 等三檔` | 三檔已不存在；註明已刪或已併 |
| `docs/quick/mod-case.md` | `backend/routers/accounting_export.py` | 已進 modules/accounting |
| `docs/quick/mod-selection-guides.md` | `6 個 guide_seed.py／guide.html` | 核對是否仍存在 |
| `docs/quick/architecture.md` | `frontend/js/case-management.js` | 核對現名 |

其餘約 100 條在歷史文件（quick 兩份舊 changelog、WEEKLY-AUDIT、DOC-CLEANUP-INVENTORY-T48、根目錄舊規格）；那些文件多數已建議 ARCHIVE，搬走即可消音，不需逐條修。

### 5.3 docs/quick（17 份；多數最後 commit 為 09-23，此後各模組已大量變動）

`mod-case.md`（39KB，10-03）、`security.md`、`ops-deploy.md`（30KB）、`ops-backup.md` 自 09-23 後未更新，而 case 模組之後經歷第40班到 M1 多班變更。這些文件已 export-ignore，風險是誤導讀者而非出貨。建議：指派更新，或併入 archive 並在 CACHE-INDEX 移除對應條目。本次判 KEEP（有 CACHE-INDEX 與 QUICK 索引依賴），列入 §7 待裁示。

## 6. 超過 40KB 的文件（應拆或壓縮）

| 檔案 | KB | 受保護 | 建議 |
|---|---:|---|---|
| `docs/windows/STATE.md` | 2251 | 是 | 2.2MB、約 4 萬行；被 test_spec_coverage 與 MD1 逐行解析。只能由 A 線設計『分卷加索引』並同步改解析器，不可由清理順手拆 |
| `docs/quick/changelog-2026-09-08_2026-09-14.md` | 196 | 否 | 已建議 ARCHIVE（見第3節） |
| `docs/windows/C.md` | 167 | 否 | 167KB 歷史收尾紀錄；程式註解提及；建議整檔搬 archive 並把註解改指 git 歷史 |
| `docs/quick/changelog-2026-07-18_2026-09-08.md` | 150 | 否 | 已建議 ARCHIVE（見第3節） |
| `docs/platform/INTEGRATION-POINTS.md` | 145 | 是 | 145KB；被測試與 final_verify 逐名稱比對，拆分需改兩處解析；可先在 CACHE-INDEX 補章節索引 |
| `docs/quick/changelog.md` | 132 | 否 | 可拆，優先度低 |
| `docs/platform/RUN-LOG.md` | 105 | 否 | 已建議 ARCHIVE（見第3節） |
| `docs/platform/RUN-PLAN.md` | 104 | 是 | 104KB；test_core_only_rc 讀；第6節進度只增不減，建議每班把舊條目移 runplan/ 封存（機制已存在） |
| `docs/windows/SCOPE.md` | 97 | 是 | 同 STATE：被 test_spec_coverage 解析，拆分要連解析器一起改 |
| `docs/windows/B.md` | 96 | 否 | 96KB 同上 |
| `docs/windows/HANDOFF-PENDING-2026-09-23.md` | 84 | 否 | 84KB 一次性交接，已被後續取代 |
| `docs/platform/PLAYBOOK.md` | 82 | 是 | 82KB；CACHE-INDEX 來源；可按列車、守門、建包拆 3 份，要重產 CACHE-INDEX |
| `MULTIWIN-PROTOCOL.md` | 76 | 是 | 76KB；CACHE-INDEX 來源；V9 時代協定，建議瘦身到現行三分之一 |
| `docs/platform/CORE-SPEC.md` | 74 | 是 | 74KB；CACHE-INDEX 來源；使用者裁示表為權威，宜單獨成檔 |
| `docs/platform/COMPANY-SETUP-GATE.md` | 67 | 否 | 67KB；設計已落地，建議留 10KB 設計理由，其餘搬 archive |
| `docs/windows/SPEC-CM12-P4-UI.md` | 60 | 否 | 60KB；測試註解提及；已完工規格，建議 archive |
| `docs/platform/runplan/RUN-PLAN-ARCHIVE-2026-09-26_2026-09-27.md` | 58 | 否 | 已建議 ARCHIVE（見第3節） |
| `SELLABLE-AND-MOBILE-SPEC.md` | 57 | 否 | 57KB；09-21 規格；已 export-ignore；建議 archive |
| `docs/platform/IMPROVEMENT-REPORT.md` | 56 | 否 | 已建議 ARCHIVE（見第3節） |
| `docs/platform/CUSTOMIZATION-SPEC.md` | 56 | 否 | 56KB；大量註解引用；建議保留並加章節索引 |
| `docs/platform/archive/docs/PLATFORM-FOUNDATION.md` | 55 | 否 | 已封存，不處理 |
| `docs/platform/plans/DOC-CLEANUP-INVENTORY-T48.md` | 52 | 否 | 已建議 ARCHIVE（見第3節） |
| `docs/platform/MODULE-GUIDE.md` | 51 | 是 | 51KB；CACHE-INDEX 來源且被測試讀；若再新增第14節條目，建議把第14節獨立成端點規則檔 |
| `docs/platform/MODULE-UPDATE-DELIVERY.md` | 50 | 是 | 50KB；測試讀；保留，可加章節索引 |
| `docs/platform/LODGING-NEARBY.md` | 47 | 否 | 47KB 設計已落地；建議瘦身 |
| `WEEKLY-AUDIT-2026-09-07_2026-09-10.md` | 45 | 否 | 已建議 ARCHIVE（見第3節） |
| `docs/platform/FINAL-DRILL-REPORT.md` | 45 | 否 | 45KB 一次性演練報告；工具測試提及檔名，archive 前先確認 final_drill 工具不開檔 |
| `docs/platform/audit/AUDIT-D-B55-module-delivery.md` | 44 | 是 | 可拆，優先度低 |
| `MOTRIX-ERP-ARCHITECTURE-MAP.md` | 44 | 否 | 44KB；V9 架構圖，原版只維護；保留 |
| `docs/platform/audit/AUDIT-D-E4-company-gate.md` | 42 | 是 | 可拆，優先度低 |
| `docs/platform/BENCHMARK.md` | 41 | 否 | 41KB；09-25 效能基準；確認後可 archive |
| `docs/platform/plans/DISPATCH-APPROVAL-DESIGN.md` | 39 | 否 | 可拆，優先度低 |
| `docs/quick/mod-case.md` | 39 | 否 | 可拆，優先度低 |

## 7. 待使用者裁示

1. 是否同意第二輪 ARCHIVE（第3節，68 份）？可分批，先搬 prod-tasks 十份與 quick 兩份舊 changelog（最安全、容量最大）。
2. `docs/platform/{audit,plans,prod-tasks}` 要不要整個 export-ignore（客戶包不含內部稽核與規劃）？承接第48班未裁示題。
3. docs/quick 17 份（09-23 後未更新）：指派更新，還是併入 archive？
4. 桌面導引改版由誰做；建議 M2 上線後一次改，補上 M2／M3、設定中心、權限矩陣、刪除暫存區四條主線。
5. STATE.md（2.2MB）與 SCOPE.md 的分卷：需 A 線連同解析器設計，本次不處理。

## 8. 完整清單（377 份）

判定 KEEP\* 表示測試或工具開檔讀。

| 路徑 | KB | 最後 commit | 判定 | 說明 |
|---|---:|---|---|---|
| `AGENT-HANDOFF-TEMPLATE.md` | 2 | 2026-09-10 | KEEP | 被 2 個檔提及（測試0／工具1／程式1；多為註解或 allow-list，非開檔）；文件互引 5 |
| `CHANGELOG.md` | 1 | 2026-09-23 | KEEP* | 硬讀：版本槽測試與 core_bump、final_verify 讀 |
| `DEPLOY.md` | 21 | 2026-09-23 | KEEP* | 硬讀：test_verify_package_export_ignore_list 讀 |
| `DR-SOP.md` | 20 | 2026-10-09 | KEEP | 被 9 個檔提及（測試1／工具1／程式7；多為註解或 allow-list，非開檔）；文件互引 11 |
| `GITFLOW.md` | 2 | 2026-07-22 | ARCHIVE | START-HERE 第8節已標過期（舊 master 時代）；已 export-ignore；root_files allow-list 要同步改 |
| `HTTPS-DEPLOY-CHECKLIST.md` | 3 | 2026-08-28 | KEEP | 被 2 個檔提及（測試0／工具1／程式1；多為註解或 allow-list，非開檔）；文件互引 4 |
| `LETSENCRYPT-PUBLIC-CERT-PLAN.md` | 11 | 2026-09-11 | KEEP | 被 2 個檔提及（測試0／工具1／程式1；多為註解或 allow-list，非開檔）；文件互引 6 |
| `MODULE-AUDIT-2026-09-13.md` | 26 | 2026-09-14 | ARCHIVE | 09-13 模組稽核 26KB，一次性；測試 docstring 提及（不開檔） |
| `MOTRIX-ERP-ARCHITECTURE-MAP.md` | 44 | 2026-10-09 | KEEP | 被 2 個檔提及（測試0／工具1／程式1；多為註解或 allow-list，非開檔）；文件互引 8 |
| `MOTRIX-ERP-QUICK.md` | 28 | 2026-09-23 | KEEP | 被 33 個檔提及（測試9／工具1／程式23；多為註解或 allow-list，非開檔）；文件互引 36 |
| `MULTIWIN-PROTOCOL.md` | 76 | 2026-09-30 | KEEP* | 硬讀：CACHE-INDEX 來源檔；HG1／MD1 掃 |
| `NETWORK-PLAN-MODULE-DESIGN.md` | 28 | 2026-08-26 | KEEP | 被 6 個檔提及（測試1／工具1／程式4；多為註解或 allow-list，非開檔）；文件互引 4 |
| `PASSKEY-CA-ROLLOUT.md` | 16 | 2026-09-11 | KEEP | 被 3 個檔提及（測試0／工具1／程式2；多為註解或 allow-list，非開檔）；文件互引 8 |
| `SELLABLE-AND-MOBILE-SPEC.md` | 57 | 2026-09-21 | KEEP | 被 2 個檔提及（測試0／工具1／程式1；多為註解或 allow-list，非開檔）；文件互引 5 |
| `WEEKLY-AUDIT-2026-09-07_2026-09-10.md` | 45 | 2026-09-11 | ARCHIVE | 09-11 週稽核報告 45KB，一次性；只有 allow-list 與註解提及 |
| `docs/MOTRIX_ERP_System_Plan.md` | 32 | 2026-09-06 | KEEP | 被 1 個檔提及（測試0／工具0／程式1；多為註解或 allow-list，非開檔）；文件互引 3 |
| `docs/UI-REDESIGN-PLAN.md` | 22 | 2026-10-09 | KEEP | 被 2 個檔提及（測試0／工具0／程式2；多為註解或 allow-list，非開檔）；文件互引 4 |
| `docs/platform/BENCHMARK.md` | 41 | 2026-09-25 | KEEP | 被 1 個檔提及（測試0／工具0／程式1；多為註解或 allow-list，非開檔）；文件互引 4 |
| `docs/platform/BUILD-VERIFY-OPTIMIZATION-T47.md` | 13 | 2026-10-08 | ARCHIVE | 第47班建包優化報告，已併 PLAYBOOK |
| `docs/platform/BUILDER-UX.md` | 27 | 2026-09-30 | KEEP | 被 4 個檔提及（測試2／工具0／程式2；多為註解或 allow-list，非開檔）；文件互引 3 |
| `docs/platform/CACHE-INDEX.md` | 6 | 2026-09-30 | KEEP* | 硬讀：test_cache_index_fresh、final_verify 讀 |
| `docs/platform/COMPANY-SETUP-GATE.md` | 67 | 2026-09-29 | KEEP | 被 2 個檔提及（測試0／工具0／程式2；多為註解或 allow-list，非開檔）；文件互引 4 |
| `docs/platform/CORE-SPEC.md` | 74 | 2026-10-08 | KEEP* | 硬讀：CACHE-INDEX 來源檔（test_cache_index_fresh 比來源 commit） |
| `docs/platform/CUSTOMIZATION-SPEC.md` | 56 | 2026-09-26 | KEEP | 檔名主體被 88 個程式／測試註解引用；文件互引 2 |
| `docs/platform/D7-CHECKLIST.md` | 10 | 2026-10-08 | KEEP | 檔名主體被 3 個程式／測試註解引用；文件互引 1 |
| `docs/platform/DATA-COMPAT.md` | 24 | 2026-10-08 | KEEP | 檔名主體被 9 個程式／測試註解引用；文件互引 2 |
| `docs/platform/DEPENDENCY-MAP.md` | 21 | 2026-09-26 | KEEP | 檔名主體被 19 個程式／測試註解引用；文件互引 4 |
| `docs/platform/FINAL-DRILL-REPORT.md` | 45 | 2026-09-27 | KEEP | 被 1 個檔提及（測試0／工具1／程式0；多為註解或 allow-list，非開檔）；文件互引 6 |
| `docs/platform/FINANCE-INTEGRATION.md` | 15 | 2026-10-02 | KEEP* | 硬讀：CACHE-INDEX 來源檔 |
| `docs/platform/GOOGLE-BASEMAP.md` | 13 | 2026-09-28 | KEEP | 被 2 個檔提及（測試1／工具0／程式1；多為註解或 allow-list，非開檔）；文件互引 4 |
| `docs/platform/IMPROVEMENT-REPORT.md` | 56 | 2026-09-28 | ARCHIVE | 56KB 09-28 改善報告；僅稽核文件與程式註解引用 |
| `docs/platform/INTEGRATION-POINTS.md` | 145 | 2026-10-11 | KEEP* | 硬讀：test_integration_points_registered、final_verify V3.4b 讀 |
| `docs/platform/LEDGER-ACCEPTANCE.md` | 9 | 2026-10-01 | KEEP | 被 1 個檔提及（測試1／工具0／程式0；多為註解或 allow-list，非開檔）；文件互引 3 |
| `docs/platform/LODGING-NEARBY.md` | 47 | 2026-09-29 | KEEP | 被 9 個檔提及（測試3／工具0／程式6；多為註解或 allow-list，非開檔）；文件互引 7 |
| `docs/platform/MODULE-GUIDE.md` | 51 | 2026-10-10 | KEEP* | 硬讀：test_l1_interface_snapshot 讀；CACHE-INDEX 來源檔 |
| `docs/platform/MODULE-UPDATE-DELIVERY.md` | 50 | 2026-09-29 | KEEP* | 硬讀：同上 |
| `docs/platform/MODULE-UPDATE-PROD-INSTRUCTIONS.md` | 10 | 2026-09-29 | KEEP | 被 2 個檔提及（測試0／工具1／程式1；多為註解或 allow-list，非開檔）；文件互引 1 |
| `docs/platform/MONEY-FLOWS.md` | 29 | 2026-10-10 | KEEP* | 硬讀：test_money_flows_registered 讀 |
| `docs/platform/PLAYBOOK.md` | 82 | 2026-10-10 | KEEP* | 硬讀：test_core_only_rc 讀；CACHE-INDEX 來源檔 |
| `docs/platform/PO-VENDOR-BANK-GAP-T47.md` | 5 | 2026-10-08 | KEEP | 檔名主體被 1 個程式／測試註解引用；文件互引 3 |
| `docs/platform/PROD-DEV-CHANNEL.md` | 12 | 2026-10-10 | KEEP | 被 1 個檔提及（測試0／工具0／程式1；多為註解或 allow-list，非開檔）；文件互引 5 |
| `docs/platform/ROADMAP.md` | 28 | 2026-09-27 | KEEP | 檔名主體被 28 個程式／測試註解引用；文件互引 4 |
| `docs/platform/RUN-LOG.md` | 105 | 2026-09-27 | ARCHIVE | 105KB 流水帳，09-27 止；進度已由 RUN-PLAN 第6節與 runplan 封存接手 |
| `docs/platform/RUN-PLAN.md` | 104 | 2026-10-11 | KEEP* | 硬讀：test_core_only_rc 讀 |
| `docs/platform/STAGE-C-DESIGN.md` | 15 | 2026-09-26 | KEEP | 被 3 個檔提及（測試0／工具0／程式3；多為註解或 allow-list，非開檔）；文件互引 3 |
| `docs/platform/TAX401-OFFICIAL-FIELDS.md` | 9 | 2026-10-01 | KEEP | 被 1 個檔提及（測試0／工具0／程式1；多為註解或 allow-list，非開檔）；文件互引 4 |
| `docs/platform/THIRD-PARTY-LICENSES.md` | 1 | 2026-09-30 | KEEP* | 硬讀：test_font_license 讀 |
| `docs/platform/TRAIN-PREFLIGHT-T47.md` | 7 | 2026-10-08 | KEEP | 被 1 個檔提及（測試0／工具1／程式0；多為註解或 allow-list，非開檔）；文件互引 3 |
| `docs/platform/UNIT-INDEX.md` | 15 | 2026-10-10 | KEEP* | 硬讀：產生檔；test_unit_cards、test_regen_all 讀 |
| `docs/platform/UPDATE-DELIVERY.md` | 18 | 2026-09-29 | KEEP* | 硬讀：test_apply_module_update_ps1／test_module_update_delivery 讀 |
| `docs/platform/UPGRADE-RUNBOOK.md` | 28 | 2026-10-08 | KEEP | 被 2 個檔提及（測試0／工具1／程式1；多為註解或 allow-list，非開檔）；文件互引 3 |
| `docs/platform/plans/ATTACHMENTS-PLAN.md` | 8 | 2026-09-26 | KEEP | 被 1 個檔提及（測試1／工具0／程式0；多為註解或 allow-list，非開檔）；文件互引 5 |
| `docs/platform/plans/AUTHOR-GATE-DESIGN.md` | 9 | 2026-10-02 | KEEP | 被 1 個檔提及（測試0／工具1／程式0；多為註解或 allow-list，非開檔）；文件互引 1 |
| `docs/platform/plans/BUILD-OPT-ITEM3-INCREMENTAL-DESIGN.md` | 33 | 2026-10-02 | KEEP | 被 2 個檔提及（測試0／工具2／程式0；多為註解或 allow-list，非開檔）；文件互引 1 |
| `docs/platform/plans/BUILD-OPTIMIZATION-2.md` | 32 | 2026-10-02 | KEEP | 被 2 個檔提及（測試0／工具1／程式1；多為註解或 allow-list，非開檔）；文件互引 1 |
| `docs/platform/plans/BUILDER-ATTACH-EXISTING-MODULE-SPEC.md` | 3 | 2026-10-01 | KEEP | 文件互引 3 |
| `docs/platform/plans/BUILDER-B-DESIGN.md` | 11 | 2026-10-01 | KEEP | 被 6 個檔提及（測試3／工具0／程式3；多為註解或 allow-list，非開檔）；文件互引 2 |
| `docs/platform/plans/CHARITY-QUOTE-1PCT-CUTOVER-RUNBOOK-T52.md` | 6 | 2026-10-10 | KEEP | 文件互引 3 |
| `docs/platform/plans/CHARITY-QUOTE-1PCT-DESIGN-T52.md` | 7 | 2026-10-10 | KEEP | 被 4 個檔提及（測試1／工具0／程式3；多為註解或 allow-list，非開檔）；文件互引 4 |
| `docs/platform/plans/D12-VERIFY-GUIDE.md` | 7 | 2026-10-03 | KEEP | 被 1 個檔提及（測試1／工具0／程式0；多為註解或 allow-list，非開檔）；文件互引 3 |
| `docs/platform/plans/DISPATCH-APPROVAL-DESIGN.md` | 39 | 2026-10-01 | KEEP | 被 2 個檔提及（測試0／工具0／程式2；多為註解或 allow-list，非開檔）；文件互引 2 |
| `docs/platform/plans/DOC-CLEANUP-INVENTORY-T48.md` | 52 | 2026-10-09 | ARCHIVE | 一次性清查（52KB）；含約 40 條指向已搬／已刪檔的連結，是 final_verify 連結檢查的最大噪音源 |
| `docs/platform/plans/DOC-CLEANUP-RESULT-T48.md` | 3 | 2026-10-09 | ARCHIVE | 一次性結果報告，零引用；本身含 5 條失效連結 |
| `docs/platform/plans/DOCSYNC-N39-T52.md` | 6 | 2026-10-10 | ARCHIVE | 同上（平台層） |
| `docs/platform/plans/DOCSYNC-T52.md` | 2 | 2026-10-10 | ARCHIVE | 一次性文件同步報告 |
| `docs/platform/plans/DRAFT-CONCURRENCY-DESIGN.md` | 7 | 2026-10-02 | KEEP | 被 1 個檔提及（測試1／工具0／程式0；多為註解或 allow-list，非開檔）；文件互引 3 |
| `docs/platform/plans/E2E-SLEEP-HAZARD-AUDIT.md` | 5 | 2026-10-02 | KEEP | 被 1 個檔提及（測試1／工具0／程式0；多為註解或 allow-list，非開檔）；文件互引 1 |
| `docs/platform/plans/ENDPOINT-AUDIT-W1A-T48.md` | 9 | 2026-10-09 | ARCHIVE | 第48班端點稽核結果，零引用 |
| `docs/platform/plans/ENDPOINT-AUDIT-W1B-T48.md` | 6 | 2026-10-09 | ARCHIVE | 同上 |
| `docs/platform/plans/ENDPOINT-AUDIT-W1C-T48.md` | 7 | 2026-10-09 | ARCHIVE | 同上 |
| `docs/platform/plans/FINAL-VERIFY-T48.md` | 4 | 2026-10-09 | KEEP | 被 1 個檔提及（測試0／工具1／程式0；多為註解或 allow-list，非開檔） |
| `docs/platform/plans/FINANCE-ROLE-GOLIVE.md` | 10 | 2026-10-05 | KEEP | 檔名主體被 8 個程式／測試註解引用；文件互引 1 |
| `docs/platform/plans/FORM-DESIGNER-DESIGN.md` | 26 | 2026-10-02 | KEEP | 被 2 個檔提及（測試0／工具0／程式2；多為註解或 allow-list，非開檔）；文件互引 1 |
| `docs/platform/plans/FORM-DESIGNER-PREVIEW-GUIDE.md` | 6 | 2026-10-02 | KEEP | 被 1 個檔提及（測試1／工具0／程式0；多為註解或 allow-list，非開檔）；文件互引 2 |
| `docs/platform/plans/GENERATED-FILES-PROPOSAL.md` | 8 | 2026-09-26 | ARCHIVE | 產生檔提案，已實作（tools/platform/regen_all）；僅測試 docstring 引用 |
| `docs/platform/plans/GOLDEN-DRIFT-T52.md` | 6 | 2026-10-10 | KEEP | 檔名主體被 2 個程式／測試註解引用 |
| `docs/platform/plans/HANDOFF-AB-T47.md` | 6 | 2026-10-09 | ARCHIVE | 第47班交接，班已結 |
| `docs/platform/plans/M01-PLAN.md` | 25 | 2026-09-27 | KEEP | 檔名主體被 46 個程式／測試註解引用；文件互引 1 |
| `docs/platform/plans/M06-PLAN.md` | 21 | 2026-09-26 | KEEP | 檔名主體被 3 個程式／測試註解引用；文件互引 4 |
| `docs/platform/plans/NOTE-DASHBOARD-CACHE-T40.md` | 1 | 2026-10-05 | KEEP | 文件互引 2 |
| `docs/platform/plans/NOTE-REPORT-LABELS-T38.md` | 4 | 2026-10-04 | KEEP | 文件互引 4 |
| `docs/platform/plans/OVERHEAD-25PCT-CUTOVER-RUNBOOK-T48.md` | 7 | 2026-10-09 | ARCHIVE | 切換已於 10-10 00:59 完成；需連動改 START-HERE 必讀第7項 |
| `docs/platform/plans/OVERHEAD-25PCT-OPERATING-PROFIT-DESIGN-T48.md` | 33 | 2026-10-09 | KEEP | 被 4 個檔提及（測試2／工具0／程式2；多為註解或 allow-list，非開檔）；文件互引 5 |
| `docs/platform/plans/PAYSLIP-BYPASS-T54.md` | 2 | 2026-10-10 | KEEP | 文件互引 1 |
| `docs/platform/plans/PAYSLIP-LEDGER-OPTIONS-T46.md` | 3 | 2026-10-08 | KEEP | 被 1 個檔提及（測試1／工具0／程式0；多為註解或 allow-list，非開檔）；文件互引 2 |
| `docs/platform/plans/PAYSLIP-PERSON-LINK-T48.md` | 9 | 2026-10-09 | KEEP | 被 3 個檔提及（測試1／工具0／程式2；多為註解或 allow-list，非開檔）；文件互引 2 |
| `docs/platform/plans/PO-BANK-BLOCK-T48.md` | 4 | 2026-10-09 | KEEP | 被 2 個檔提及（測試1／工具0／程式1；多為註解或 allow-list，非開檔）；文件互引 2 |
| `docs/platform/plans/PO-VENDOR-BANK-GAP-T47.md` | 3 | 2026-10-08 | ARCHIVE | 缺口紀錄，已被 docs/platform/PO-VENDOR-BANK-GAP-T47.md（選項與裁示）承接；兩檔同名易混 |
| `docs/platform/plans/PREPUSH-USAGE-T51.md` | 1 | 2026-10-10 | KEEP | 無外部引用；現行設計／操作文件 |
| `docs/platform/plans/R2-STEP2-IMPLEMENTATION-NOTES.md` | 5 | 2026-10-09 | ARCHIVE | R2 步驟2 實作備註，已併 |
| `docs/platform/plans/REASSIGN-RULES-T54.md` | 1 | 2026-10-11 | KEEP | 無外部引用；現行設計／操作文件 |
| `docs/platform/plans/RECYCLE-BIN-P0-STATE-T53.md` | 5 | 2026-10-10 | KEEP | 被 2 個檔提及（測試0／工具0／程式2；多為註解或 allow-list，非開檔）；文件互引 2 |
| `docs/platform/plans/RECYCLE-BIN-P1-CASE-T53.md` | 3 | 2026-10-10 | KEEP | 被 1 個檔提及（測試0／工具0／程式1；多為註解或 allow-list，非開檔） |
| `docs/platform/plans/SETTLEMENT-ACTUALS-SPEC.md` | 21 | 2026-10-03 | KEEP | 被 2 個檔提及（測試0／工具0／程式2；多為註解或 allow-list，非開檔）；文件互引 3 |
| `docs/platform/plans/SHIPPING-MATERIAL-LINK-CONTRACT-S1.md` | 7 | 2026-10-03 | KEEP | 被 5 個檔提及（測試1／工具0／程式4；多為註解或 allow-list，非開檔）；文件互引 4 |
| `docs/platform/plans/SPEEDUP-PIPELINE-T51-USAGE.md` | 2 | 2026-10-10 | KEEP | 無外部引用；現行設計／操作文件 |
| `docs/platform/plans/T46-BASELINE-118-RELEASE-NOTES.md` | 1 | 2026-10-08 | ARCHIVE | 第46班發行備註，已上線 |
| `docs/platform/plans/T47-POLICY-QUESTIONS.md` | 5 | 2026-10-08 | ARCHIVE | 第47班待裁題，裁示已記在 USER-DECISIONS |
| `docs/platform/plans/T48-SMALL-ITEMS.md` | 1 | 2026-10-08 | KEEP | 文件互引 1 |
| `docs/platform/plans/T48C-RELEASE-NOTES.md` | 7 | 2026-10-09 | ARCHIVE | 第48c班發行備註，已上線；僅 train50 步驟檔引用 |
| `docs/platform/plans/T52-NOTES.md` | 3 | 2026-10-10 | KEEP | 無外部引用；現行設計／操作文件 |
| `docs/platform/plans/USER-DECISIONS.md` | 17 | 2026-10-04 | KEEP | 檔名主體被 1 個程式／測試註解引用；文件互引 3 |
| `docs/platform/plans/VISIBILITY-TIGHTENING-T49.md` | 2 | 2026-10-09 | ARCHIVE | 第49班可見範圍收緊備註，已併 MODULE-GUIDE 14.2 |
| `docs/platform/plans/expense-a2/GL-BASE-HOOKS.md` | 9 | 2026-10-01 | KEEP | 被 1 個檔提及（測試0／工具0／程式1；多為註解或 allow-list，非開檔）；文件互引 2 |
| `docs/platform/plans/expense-a2/expense-forms-design-ae.md` | 19 | 2026-10-01 | KEEP | 被 2 個檔提及（測試1／工具0／程式1；多為註解或 allow-list，非開檔）；文件互引 1 |
| `docs/platform/plans/expense-a2/plan-expense-a2.md` | 38 | 2026-10-09 | KEEP | 被 4 個檔提及（測試1／工具0／程式3；多為註解或 allow-list，非開檔）；文件互引 2 |
| `docs/platform/plans/expense-a2/proposal-expense-forms.md` | 29 | 2026-10-09 | KEEP | 被 1 個檔提及（測試0／工具0／程式1；多為註解或 allow-list，非開檔）；文件互引 2 |
| `docs/platform/plans/expense-types-designer-shots/README.md` | 1 | 2026-10-02 | KEEP | 被 8 個檔提及（測試6／工具0／程式2；多為註解或 allow-list，非開檔）；文件互引 15 |
| `docs/platform/prod-tasks/20261006-train42-apply.md` | 11 | 2026-10-06 | ARCHIVE | 第42班步驟檔，已上線；正式機權威副本在雲端交付夾 |
| `docs/platform/prod-tasks/20261006-train43-apply.md` | 29 | 2026-10-06 | ARCHIVE | 同上（第43班） |
| `docs/platform/prod-tasks/20261007-train44-apply.md` | 20 | 2026-10-07 | ARCHIVE | 同上（第44班） |
| `docs/platform/prod-tasks/20261007-train45-apply.md` | 25 | 2026-10-08 | ARCHIVE | 同上（第45班） |
| `docs/platform/prod-tasks/20261008-train46-apply.md` | 32 | 2026-10-08 | ARCHIVE | 同上（第46班） |
| `docs/platform/prod-tasks/20261009-train47-apply.md` | 23 | 2026-10-09 | ARCHIVE | 同上（第47班） |
| `docs/platform/prod-tasks/20261009-train48a-apply.md` | 23 | 2026-10-09 | ARCHIVE | 同上（48a）；內含已不存在的路徑 tools/overhead_migrate.py |
| `docs/platform/prod-tasks/20261009-train49-apply.md` | 24 | 2026-10-09 | ARCHIVE | 同上（第49班） |
| `docs/platform/prod-tasks/20261010-train50-apply.md` | 27 | 2026-10-09 | ARCHIVE | 同上（第50班）；含失效路徑 tools/overhead_migrate.py |
| `docs/platform/prod-tasks/20261010-train51-apply.md` | 25 | 2026-10-10 | ARCHIVE | 同上（第51班） |
| `docs/platform/prod-tasks/20261010-train52-apply.md` | 23 | 2026-10-10 | KEEP | 無外部引用；現行設計／操作文件 |
| `docs/platform/prod-tasks/20261011-m1a-apply.md` | 25 | 2026-10-11 | KEEP | 無外部引用；現行設計／操作文件 |
| `docs/platform/prod-tasks/20261011-train53-apply.md` | 29 | 2026-10-11 | KEEP | 無外部引用；現行設計／操作文件 |
| `docs/platform/prod-tasks/TEMPLATE-apply.md` | 3 | 2026-10-08 | KEEP | 文件互引 4 |
| `docs/platform/runplan/RUN-PLAN-ARCHIVE-2026-09-26_2026-09-27.md` | 58 | 2026-09-30 | ARCHIVE | RUN-PLAN 封存段（58KB）；test_core_only_rc 與 core_only_rc 工具提到 runplan，搬前先核對是否讀此目錄 |
| `docs/platform/states/STATES-DATA-OPS.md` | 29 | 2026-09-26 | KEEP | 檔名主體被 4 個程式／測試註解引用；文件互引 2 |
| `docs/platform/states/STATES-PLATFORM.md` | 32 | 2026-09-26 | KEEP | 被 1 個檔提及（測試1／工具0／程式0；多為註解或 allow-list，非開檔）；文件互引 4 |
| `docs/quick/api-core.md` | 6 | 2026-09-23 | KEEP | 文件互引 1 |
| `docs/quick/architecture.md` | 19 | 2026-10-09 | KEEP* | 硬讀：CACHE-INDEX 來源檔 |
| `docs/quick/changelog-2026-07-18_2026-09-08.md` | 150 | 2026-09-23 | ARCHIVE | 150KB 已封閉期間的更新紀錄；僅 QUICK 索引引用 |
| `docs/quick/changelog-2026-09-08_2026-09-14.md` | 196 | 2026-09-23 | ARCHIVE | 196KB 已封閉期間的更新紀錄（全倉最大的非 STATE 文件） |
| `docs/quick/changelog.md` | 132 | 2026-10-09 | KEEP | 檔名主體被 37 個程式／測試註解引用；文件互引 8 |
| `docs/quick/data-model.md` | 11 | 2026-09-23 | KEEP | 文件互引 1 |
| `docs/quick/known-limits.md` | 36 | 2026-10-09 | KEEP | 被 1 個檔提及（測試1／工具0／程式0；多為註解或 allow-list，非開檔）；文件互引 1 |
| `docs/quick/mod-case.md` | 39 | 2026-10-03 | KEEP | 檔名主體被 2 個程式／測試註解引用；文件互引 1 |
| `docs/quick/mod-contractor.md` | 17 | 2026-10-01 | KEEP | 文件互引 3 |
| `docs/quick/mod-crm.md` | 2 | 2026-09-23 | KEEP | 文件互引 1 |
| `docs/quick/mod-inventory.md` | 4 | 2026-09-23 | KEEP | 檔名主體被 1 個程式／測試註解引用；文件互引 1 |
| `docs/quick/mod-quotation.md` | 9 | 2026-09-23 | KEEP | 被 1 個檔提及（測試1／工具0／程式0；多為註解或 allow-list，非開檔）；文件互引 1 |
| `docs/quick/mod-selection-guides.md` | 8 | 2026-09-23 | KEEP | 文件互引 1 |
| `docs/quick/mod-shipping.md` | 4 | 2026-09-23 | KEEP | 文件互引 1 |
| `docs/quick/ops-backup.md` | 17 | 2026-09-23 | KEEP | 文件互引 1 |
| `docs/quick/ops-deploy.md` | 30 | 2026-09-23 | KEEP | 文件互引 1 |
| `docs/quick/security.md` | 21 | 2026-09-23 | KEEP | 檔名主體被 16 個程式／測試註解引用；文件互引 1 |
| `docs/reference/README.md` | 2 | 2026-09-22 | KEEP | 被 8 個檔提及（測試6／工具0／程式2；多為註解或 allow-list，非開檔）；文件互引 15 |
| `docs/windows/A-2.md` | 7 | 2026-09-23 | KEEP | 文件互引 3；windows 目錄（已 export-ignore） |
| `docs/windows/ACC-BN6.md` | 13 | 2026-09-23 | KEEP | 檔名主體被 4 個程式／測試註解引用；文件互引 1；windows 目錄（已 export-ignore） |
| `docs/windows/AUDIT-2026-09-22.md` | 9 | 2026-09-22 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/AUDIT-SPEC-COVERAGE.md` | 13 | 2026-09-23 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/B.md` | 96 | 2026-09-23 | KEEP | 被 11 個檔提及（測試6／工具0／程式5；多為註解或 allow-list，非開檔）；文件互引 6；windows 目錄（已 export-ignore） |
| `docs/windows/BACKLOG.md` | 7 | 2026-09-22 | KEEP | 文件互引 9；windows 目錄（已 export-ignore） |
| `docs/windows/C.md` | 167 | 2026-09-23 | KEEP | 被 35 個檔提及（測試21／工具2／程式12；多為註解或 allow-list，非開檔）；文件互引 60；windows 目錄（已 export-ignore） |
| `docs/windows/CM12-P3-COLOR-TOKENS.md` | 6 | 2026-09-24 | KEEP | 被 2 個檔提及（測試1／工具0／程式1；多為註解或 allow-list，非開檔）；windows 目錄（已 export-ignore） |
| `docs/windows/D.md` | 15 | 2026-09-23 | KEEP | 文件互引 9；windows 目錄（已 export-ignore） |
| `docs/windows/DATA-EM7-39.md` | 2 | 2026-09-23 | SAFE-TO-DELETE | EM7 的 39 筆原始掃描輸出；全倉零引用（連檔名主體都無），可由掃描指令重現，SPEC-EM7 才是結論文件 |
| `docs/windows/DELIVERY-NOTE-2026-09-22-PM.md` | 6 | 2026-09-22 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/DELIVERY-NOTE-2026-09-23.md` | 7 | 2026-09-23 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/DELIVERY-NOTE-DRAFT.md` | 22 | 2026-09-22 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/DELIVERY-NOTES-2026-09-25.md` | 10 | 2026-09-25 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/DEV-TEST-CHECKLIST-2026-09-25.md` | 18 | 2026-09-24 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/GATE-BLOCK-2026-09-23.md` | 6 | 2026-09-23 | KEEP | 被 1 個檔提及（測試1／工具0／程式0；多為註解或 allow-list，非開檔）；文件互引 2；windows 目錄（已 export-ignore） |
| `docs/windows/HANDOFF-PENDING-2026-09-23.md` | 84 | 2026-09-25 | KEEP | 被 13 個檔提及（測試13／工具0／程式0；多為註解或 allow-list，非開檔）；文件互引 9；windows 目錄（已 export-ignore） |
| `docs/windows/HANDOVER-2026-09-23.md` | 21 | 2026-09-23 | KEEP | 被 1 個檔提及（測試0／工具0／程式1；多為註解或 allow-list，非開檔）；文件互引 4；windows 目錄（已 export-ignore） |
| `docs/windows/HEALTH-2026-09-22.md` | 8 | 2026-09-22 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/KNOWN-GAPS.md` | 9 | 2026-09-24 | KEEP | 被 1 個檔提及（測試0／工具0／程式1；多為註解或 allow-list，非開檔）；文件互引 4；windows 目錄（已 export-ignore） |
| `docs/windows/PENDING-RULINGS.md` | 12 | 2026-09-23 | KEEP | 被 1 個檔提及（測試0／工具0／程式1；多為註解或 allow-list，非開檔）；文件互引 4；windows 目錄（已 export-ignore） |
| `docs/windows/PIP-AUDIT-2026-09-22.md` | 2 | 2026-09-22 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/PIPELINE.md` | 17 | 2026-09-22 | KEEP | 檔名主體被 4 個程式／測試註解引用；文件互引 2；windows 目錄（已 export-ignore） |
| `docs/windows/PLAN-TEST-PERF-e2e-classify.md` | 9 | 2026-09-25 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/PLAN-TEST-PERF.md` | 29 | 2026-09-25 | KEEP | 檔名主體被 12 個程式／測試註解引用；文件互引 1；windows 目錄（已 export-ignore） |
| `docs/windows/SCOPE.md` | 97 | 2026-10-09 | KEEP* | 硬讀：test_spec_coverage 讀；MD1／HG1 掃 |
| `docs/windows/SPEC-AC2-RECOGNITION.md` | 4 | 2026-09-24 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-AS1-AS2-JV8.md` | 11 | 2026-09-23 | KEEP | 被 1 個檔提及（測試1／工具0／程式0；多為註解或 allow-list，非開檔）；文件互引 1；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-BN1-PLAN.md` | 15 | 2026-09-23 | KEEP | 被 1 個檔提及（測試1／工具0／程式0；多為註解或 allow-list，非開檔）；文件互引 2；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-BN11-BN12.md` | 17 | 2026-09-23 | KEEP | 被 4 個檔提及（測試2／工具0／程式2；多為註解或 allow-list，非開檔）；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-BN14.md` | 16 | 2026-09-23 | KEEP | 被 3 個檔提及（測試1／工具0／程式2；多為註解或 allow-list，非開檔）；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-BN16.md` | 16 | 2026-09-23 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-BN17.md` | 15 | 2026-09-23 | KEEP | 被 2 個檔提及（測試2／工具0／程式0；多為註解或 allow-list，非開檔）；文件互引 2；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-BN18.md` | 20 | 2026-09-23 | KEEP | 被 2 個檔提及（測試1／工具0／程式1；多為註解或 allow-list，非開檔）；文件互引 2；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-BN2-BN5.md` | 13 | 2026-09-23 | KEEP | 被 3 個檔提及（測試1／工具0／程式2；多為註解或 allow-list，非開檔）；文件互引 1；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-BN20.md` | 8 | 2026-09-23 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-BN21.md` | 12 | 2026-09-23 | KEEP | 被 4 個檔提及（測試1／工具0／程式3；多為註解或 allow-list，非開檔）；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-BN6-BN7.md` | 12 | 2026-09-23 | KEEP | 被 5 個檔提及（測試2／工具0／程式3；多為註解或 allow-list，非開檔）；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-BN8.md` | 20 | 2026-09-23 | KEEP | 被 3 個檔提及（測試1／工具0／程式2；多為註解或 allow-list，非開檔）；文件互引 2；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-BONUS.md` | 22 | 2026-09-24 | KEEP | 被 4 個檔提及（測試1／工具0／程式3；多為註解或 allow-list，非開檔）；文件互引 1；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-CA1-CUSTOM-ACCOUNTS.md` | 12 | 2026-09-23 | KEEP | 被 1 個檔提及（測試0／工具0／程式1；多為註解或 allow-list，非開檔）；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-CM12-P4-UI.md` | 60 | 2026-09-24 | KEEP | 被 2 個檔提及（測試1／工具0／程式1；多為註解或 allow-list，非開檔）；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-CU5-8.md` | 3 | 2026-09-24 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-EM1.md` | 14 | 2026-09-23 | KEEP | 被 1 個檔提及（測試1／工具0／程式0；多為註解或 allow-list，非開檔）；文件互引 1；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-EM10-NAVIGATION.md` | 14 | 2026-09-23 | KEEP | 被 1 個檔提及（測試1／工具0／程式0；多為註解或 allow-list，非開檔）；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-EM11.md` | 7 | 2026-09-23 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-EM12.md` | 8 | 2026-09-23 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-EM13.md` | 17 | 2026-09-23 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-EM2-ROLE-LABELS.md` | 17 | 2026-09-23 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-EM3.md` | 9 | 2026-09-23 | KEEP | 被 2 個檔提及（測試1／工具0／程式1；多為註解或 allow-list，非開檔）；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-EM7.md` | 13 | 2026-09-23 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-EM9-SILENT-FAILURE.md` | 15 | 2026-09-23 | KEEP | 被 1 個檔提及（測試1／工具0／程式0；多為註解或 allow-list，非開檔）；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-HISTORY.md` | 7 | 2026-09-23 | KEEP | 被 1 個檔提及（測試1／工具0／程式0；多為註解或 allow-list，非開檔）；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-IA1.md` | 16 | 2026-09-23 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-IA2.md` | 11 | 2026-09-23 | KEEP | 被 1 個檔提及（測試0／工具0／程式1；多為註解或 allow-list，非開檔）；文件互引 1；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-JV10-JV11.md` | 14 | 2026-09-23 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-JV16-JV17.md` | 12 | 2026-09-23 | KEEP | 被 2 個檔提及（測試0／工具0／程式2；多為註解或 allow-list，非開檔）；文件互引 1；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-JV18.md` | 17 | 2026-09-23 | KEEP | 被 1 個檔提及（測試1／工具0／程式0；多為註解或 allow-list，非開檔）；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-JV21.md` | 20 | 2026-09-23 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-JV22.md` | 15 | 2026-09-23 | KEEP | 被 2 個檔提及（測試2／工具0／程式0；多為註解或 allow-list，非開檔）；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-JV24.md` | 27 | 2026-09-23 | KEEP | 被 1 個檔提及（測試1／工具0／程式0；多為註解或 allow-list，非開檔）；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-JV25.md` | 7 | 2026-09-23 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-JV26.md` | 7 | 2026-09-23 | KEEP | 被 1 個檔提及（測試1／工具0／程式0；多為註解或 allow-list，非開檔）；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-JV28-ATTACHMENT-PREVIEW.md` | 12 | 2026-09-24 | KEEP | 被 9 個檔提及（測試9／工具0／程式0；多為註解或 allow-list，非開檔）；文件互引 3；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-JV3-ATTACHMENTS.md` | 22 | 2026-09-23 | KEEP | 被 2 個檔提及（測試1／工具0／程式1；多為註解或 allow-list，非開檔）；文件互引 1；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-JV5-PDF.md` | 11 | 2026-09-23 | KEEP | 被 2 個檔提及（測試1／工具0／程式1；多為註解或 allow-list，非開檔）；文件互引 2；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-JV6.md` | 14 | 2026-09-23 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-MG3.md` | 17 | 2026-09-23 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-MG4.md` | 11 | 2026-09-23 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-PK1.md` | 16 | 2026-09-23 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-QL25-LOCATION-SNAPSHOT.md` | 23 | 2026-09-23 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-QN1-QUOTE-RENAME.md` | 21 | 2026-09-23 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-QS1-a.md` | 15 | 2026-09-23 | KEEP | 被 1 個檔提及（測試0／工具0／程式1；多為註解或 allow-list，非開檔）；文件互引 2；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-QS1.md` | 16 | 2026-09-23 | KEEP | 被 1 個檔提及（測試1／工具0／程式0；多為註解或 allow-list，非開檔）；文件互引 1；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-SL1.md` | 9 | 2026-09-23 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-T100-CONFIG.md` | 6 | 2026-09-23 | KEEP | 被 1 個檔提及（測試1／工具0／程式0；多為註解或 allow-list，非開檔）；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-UP1.md` | 9 | 2026-09-23 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-UP2.md` | 11 | 2026-09-23 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-UP3.md` | 9 | 2026-09-23 | ARCHIVE | 09-22～09-25 完工規格／交付單／稽核紀錄；程式與測試零引用，僅 STATE／SCOPE／同目錄互引（文字提及，不開檔） |
| `docs/windows/SPEC-VOUCHER-HISTORY.md` | 28 | 2026-09-23 | KEEP | 被 5 個檔提及（測試2／工具0／程式3；多為註解或 allow-list，非開檔）；文件互引 2；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-VOUCHER.md` | 11 | 2026-09-23 | KEEP | 被 13 個檔提及（測試6／工具0／程式7；多為註解或 allow-list，非開檔）；文件互引 2；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-WD1-WORDING.md` | 9 | 2026-09-23 | KEEP | 被 1 個檔提及（測試1／工具0／程式0；多為註解或 allow-list，非開檔）；文件互引 1；windows 目錄（已 export-ignore） |
| `docs/windows/SPEC-WL7.md` | 17 | 2026-09-23 | KEEP | 被 2 個檔提及（測試1／工具0／程式1；多為註解或 allow-list，非開檔）；文件互引 1；windows 目錄（已 export-ignore） |
| `docs/windows/STATE.md` | 2251 | 2026-10-09 | KEEP* | 硬讀：test_spec_coverage 讀；MD1／HG1 掃 |
| `docs/windows/TEST-BASELINE-2026-09-23.md` | 6 | 2026-09-23 | KEEP | 被 1 個檔提及（測試0／工具0／程式1；多為註解或 allow-list，非開檔）；文件互引 4；windows 目錄（已 export-ignore） |
| `docs/windows/TEST-CONFIDENCE.md` | 4 | 2026-09-23 | KEEP | 被 1 個檔提及（測試0／工具0／程式1；多為註解或 allow-list，非開檔）；文件互引 1；windows 目錄（已 export-ignore） |
| `docs/windows/tools/README.md` | 17 | 2026-09-23 | KEEP | 被 8 個檔提及（測試6／工具0／程式2；多為註解或 allow-list，非開檔）；文件互引 15；windows 目錄（已 export-ignore） |

另有 `docs/platform/archive/**` 35 份（第48班已封存，KEEP）與 `docs/platform/audit/**` 112 份（硬讀，KEEP\*），不逐列。
