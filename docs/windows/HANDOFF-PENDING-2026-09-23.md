# 待辦移交清單（2026-09-23 晚，hichan-0a 彙整）

> 用途：把「原本待完成的事項」交給另一個視窗接手；本視窗改做平台化盤點。
> 量測時 HEAD＝`6e09acc`。每一項的權威細節在「來源」欄那份檔，**以那份為準**，本檔只做索引與分派。
> 協定照 `MULTIWIN-PROTOCOL.md`：§3 檔案歸屬、§6b 停手回報、§5u `git -C <絕對路徑>`。

---

## 甲、視窗可以直接接手（不需要使用者裁示）

| # | 事項 | 現況（量的） | 來源 | 歸屬 |
|---|---|---|---|---|
| T1 | **建包被規格覆蓋率守門擋下 ⇒ 升級檔沒有匯出** | 守門列 31 個編號：丁 9（撞名，登記 `AMBIGUOUS_ACK`）／丙 9（題名不帶編號，**要逐支打開驗**）／乙 5（真欠帳，**不可登記掉，要補題**）／甲 8（沒做） | `docs/windows/GATE-BLOCK-2026-09-23.md` | 登記與補題＝C；甲類要不要做＝A |
| T2 | T1 解除後重跑 `build_deploy_package.ps1`，**只到匯出升級檔為止，不部署** | 最後一次成功建包之後又有大量 commit | `HANDOVER-2026-09-23.md` §0 ① | A 派、D 量 |
| T3 | `test_navigation_destination_2026_09_23.py` 4 支紅（EM10） | HEAD 上就紅（基準見 `TEST-BASELINE-2026-09-23.md:66`）；母體 144 vs 規格 46 的洞還沒驗 | `STATE.md` 搜 `EM10`、`SPEC-EM10` | 實作＝B；驗母體＝C |
| T4 | `test_homoglyphs_in_docs` 紅：`docs/windows/KNOWN-GAPS.md:173`、`:176` 的「剥」應為「剝」 | 2 處，HEAD 上就紅 | 測試輸出 | A（文件） |
| T5 | **變更摘要斷檔**：`docs/quick/changelog.md` 最新一則是 09-16，`version_manifest.json` 最新一筆是 09-14；09-17 起有 1,319 個 commit 沒進任何一份 | `git log --since=2026-09-17 --oneline \| wc -l` | QUICK 維護規則 | A（changelog）；manifest＝B（`backend/`） |
| T6 | `HANDOVER-2026-09-23.md` 標著「編寫中」，有「待補」節 | 第 8 行 | 該檔 | A |
| T7 | `NEXT-SESSION.md` 停在 2026-09-12（寫的是 v76→v77 部署），**已過期但檔頭寫著「開工第一份要讀」** | 第 1 行 | 該檔 | A：改寫或標註過期並指向 HANDOVER |
| T8 | `MOTRIX-ERP-QUICK.md` 檔頭「文件版本 2026-09-16」過期 | 第 4 行 | — | A，併 T5 一起做 |

建議順序：**T4 → T1 → T2**（T4 一分鐘，且讓全套測試少一支已知紅燈；T2 依賴 T1）；T5～T8 可以跟 T1 並行。

## 乙、要使用者裁示（視窗不可代裁，只能整理選項）

| 事項 | 數量 | 來源 |
|---|---|---|
| 出貨阻擋 IA1／IA2／WL7／JV27 | 4 | `HANDOVER-2026-09-23.md` §0b |
| 待裁示（每條已附預設決定，只回不同意的） | 18 | `PENDING-RULINGS.md` |
| 只有使用者在正式機上查得到的 | 11（共 21 條） | `KNOWN-GAPS.md` |

> `HANDOVER` §0a（出貨包含內部文件）：`.gitattributes` 的 `**` 寫法已生效——
> 2026-09-23 `git check-attr export-ignore` 對 `docs/windows/STATE.md`、`backend/tests/conftest.py`、`docs/quick/changelog.md` 皆回 `set`；
> `git archive ced0ae8` 實測包內 `docs/quick`＋`MOTRIX-ERP-QUICK.md` 0 筆（對照組 `backend/main.py` 1 筆）。
> **仍待**：打開真正由 `build_deploy_package.ps1` 產出的包驗 `STATE.md` 不在（隨 T2 一起做）。

## 丙、我沒查什麼

- 丙類 9 個、甲類 8 個的逐項真偽：沒查，照 GATE-BLOCK 的分類轉列。
- `PENDING-RULINGS` 18 條的內容：沒讀，只轉列數量。
- T5 的 1,319 個 commit 中有多少是功能變更（相對於文件）：沒分。
