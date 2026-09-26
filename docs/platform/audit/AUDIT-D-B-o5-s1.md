# 稽核：B 的 O5-S1——e2e 字型替身、登入改等就緒、golden 的 Referer 過濾（wip/b-o5-s1 4e6d97d3；合回前）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d：動到 fixture 層（conftest 的 `E2E_CONTEXT_HOOKS`），完整稽核。稽核者 D 沒有寫過任何受稽核的程式碼。
> 對象：`22c58bba`、`4e6d97d3`。內容：
> - 每題的 context 把 `**/fonts/*` 換成 648 bytes 的替身；標 `real_fonts` 的題照舊拿真字型。
> - `wait_logged_in` 只等 DOMContentLoaded＋`#app-topbar`。
> - golden 不記 Referer 是 `/index.html` 的請求。
>
> 稽核樹 `D:\MOTRIX-PLATFORM-D`（detached）；e2e 用 `-n 2`，golden 用 `-n 0`。

## 0. 結論

- **必修 0、觀察 1**。
- 主持問的「判準是否變寬」：**沒有**。golden 從來沒有守首頁的請求；案件頁的請求照樣記得到。證據見 §2。

## 1. 實測

| 項目 | 結果 |
|---|---|
| 本包改到的 e2e 檔（15 檔）＋generated_maps（`-n 2`） | 71 過 |
| golden 未突變，單獨連跑 5 次 | 5/5 過 |
| `**/fonts/*` 是否蓋到 API 路徑 | `git grep` 找不到任何含 `/fonts/` 的 API 或前端路徑，只有 `../fonts/` 的 CSS 引用 |
| 突變 F1：`real_fonts` 標記失效 | 紅（`test_real_fonts_marker_gets_the_real_files`） |
| 突變 F2：不掛替身 | 紅（`test_fonts_are_served_as_a_tiny_stub`） |

## 2. golden 的 Referer 過濾（主持指定）

- 時序：golden 是「登入 → `wait_for_url(index)`（等 load）→ 掛上 `_Net` → `goto(case-management)`」。
- 只有首頁在 `_Net` 掛上之後、換頁之前發出的請求，Referer 才會是 `/index.html`：全站的 `Referrer-Policy` 是 `same-origin`，同源請求會送完整路徑。
- 案件頁自己發的請求，Referer 都是 case-management.html，不受過濾影響。

| # | 突變 | 本包（替身字型） | origin/platform（真字型，改動前） |
|---|---|---|---|
| G1 | 案件頁多發一支 `GET /api/zzprobe-golden` | **紅**（API 清單） | — |
| G2 | 首頁解析時多發一支 GET | 綠 | — |
| G3 | 首頁 load 後 50ms 再多發一支 GET | 3 次都沒有在 API 清單紅（1 次紅在「財務」分頁的文字步驟，與探針無關） | 3 次都沒有在 API 清單紅（1 次紅在「出貨單」分頁的文字步驟） |
| G4 | 拿掉 Referer 過濾 | **API 清單紅 2/3** ⇒ 過濾確實需要，B 的診斷成立 | — |

- 結論：首頁多打的 API，改動前的 golden 也抓不到（G3 在 origin 上沒有紅在 API 清單）。所以這個過濾沒有放掉原本守得住的東西。
- 主持提議的「讓首頁多發一支 GET，golden 要能抓到」，在改動前後都不成立，因為那不在 golden 的範圍。
- 如果首頁的請求集合需要守，應該另外寫一支首頁題，不要靠案件頁 golden 的時序碰巧。這是新的需求，不列為本包的缺陷。

## 3. 觀察

**O5S1-O1　golden 的文字步驟偶發紅，只出現在「首頁注入延遲 fetch」的突變執行裡**
- 案件頁子分頁在網路靜止 600ms 後仍顯示「載入中…」，例如「待辦事項」「財務」「出貨單」。
- 統計：未突變 5 次 0 紅；G1、G2、G4 共 5 次 0 次文字紅；G3 系列 7 次（含 origin 3 次）出現 3 次文字紅。
- 判斷：這是突變製造的時序擾動，不是本包造成的，origin 上也一樣。不過它顯示 `settle()` 只看網路靜止、不看 Alpine 的載入旗標，是 golden 本身的一個弱點。之後如果 golden 在全量偶發紅，先往這裡查。

## 4. 回覆欄

（必修 0，不需回覆。）
