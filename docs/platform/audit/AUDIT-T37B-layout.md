# 稽核：t37b 精算頁版面 hotfix（rev-7f 稽核，2026-10-04）

> 對象：`origin/train/t37b-hotfix` `3b107abf`（＝platform `1a06c6db`＋前端版面修正，作者 hichan-05）。自己的樹 `D:\開發測試檔\aud-7g`，`.venv312`、`-n 0／2`、basetemp 在 `%TEMP%`。未碰正式機、未建包。探針另存 `AUDIT-T37B-layout-probe.py.txt`，截圖在 `shots-t37b/`。

## 0. 結論
**必修 0、建議 2、觀察 3。可以上車。**
1. 差異只有 CSS／標記，沒有任何金額公式、getter、金額類 `x-text` 被改；唯一的 JS 變動是把毛利／淨利兩張摘要卡的字串拆成 `value`＋`value2` 兩段顯示。
2. 新 e2e 是真測試：還原成 `1a06c6db` 的 `settlement.html` 後**紅**（1 failed），還原回來綠。
3. 我用更惡劣的資料（稅前 NT$ 88,253,000、長客戶名／長專案名）在 1280／1440／1920／420 跑：**新版摘要卡零裁切、頁面零橫向捲動；舊版在同資料下 3 個寬度摘要卡內容超出、420 頁面橫向溢出 26px**。修正有效。

## 1. diff 逐行核對（`git diff 1a06c6db 3b107abf -- frontend/pages/settlement.html`，22 行改動）
| 類別 | 項目 | 判定 |
|---|---|---|
| CSS | `.stl-main` 置中（`margin-left: calc(...)`、`max-width:1400px`、`box-sizing`）；`.stl-kpis` 改 `auto-fit,minmax(210px,1fr)`；`.stl-k__v` 改 `clamp`＋flex 換行；`.stl-k__v2`、`overflow-wrap`；刪掉 900px 以下 2 欄規則 | 僅版面 |
| 標記 | `.stl-k__v` 由單一 `x-text="k.value"` 改為 `<span x-text="k.value">`＋`<span x-show="k.value2" x-text="k.value2">` | 綁定新增 `x-show`（顯示用）；無 `x-html` |
| JS | `stripKpis` 毛利、淨利兩項：`value: signed(x) + ' ／ ' + pctTxt(...)` ⇒ `value: signed(x)`、`value2: pctTxt(...)` | **資料呈現拆欄，數值與公式不變**；分隔符「／」不再顯示（標籤仍是「毛利／毛利比」） |
| 其他 | 無任何公式、getter、`fmt`、`calcSummary` 變動；無新增 `#RRGGBB`（diff 內 hex 命中 0）；無 `x-html`（命中 0） | 通過 |
- 列印 CSS：`@media print` 區塊（`:150-156`）**逐字未動**；但 `.stl-kpis` 的欄數規則改了，列印時摘要卡由「5 欄一列」變成依 210px 自動換行（A4 約 3＋2）。e2e 驗到 `position:static`、工具列隱藏，**沒驗卡片欄數**（見 S-2）。

## 2. 反向控制（第 3 項）
- 在 3b107abf 把 `settlement.html` 換成 `1a06c6db` 版本、跑 `test_e2e_settlement_layout_2026_10_04.py`：**1 failed**。還原後 `git status` 乾淨。
- 同一支題在 3b107abf：passed（連同 bn11 標籤守門、`test_legal_amount_rounding_guard` 共 19 passed）。
- 注意：該題在 1440 寬、`tot.pretax=8,837,550` 下判裁切；我的探針用 88,253,000＋長名稱，舊版也紅，見 §4。

## 3. 其他讀者（第 4 項）
- `payroll` bn11 守門：讀 `settlement.html` 內 `SETTLEMENT_ROWS` 11 個標籤逐字存在——**passed**（本次沒動這些文字）。
- `test_legal_amount_rounding_guard`（掃 `settlement.html` 有無 `Math.round`）：passed。
- 讀 `stl-k-*` 的題：`test_e2e_settlement_dispatch_offset_2026_10_04.py:286-288` 只驗卡片可見、有 `title`、報價卡含 `20,000`——不依賴被拆開的毛利／淨利字串，未受影響（該檔我未重跑，讀碼判斷；e2e 版面題與守門題已跑）。
- 無任何 Python 讀 `stripKpis`／`stl-k__v` 文字。

## 4. 響應式實測（第 5 項；資料：稅前 NT$ 88,253,000、淨利 78,533,042、客戶名 40 字、專案名 60 字）
| 寬度 | 新版 | 舊版（1a06c6db） |
|---|---|---|
| 1280／1440／1920 | 無橫向捲動；摘要卡 0 處裁切；一列 5 張（1280 以上） | 毛利、淨利卡內容超出卡片（`236>214`、`226>214`），金額與比例被切 |
| 1024／1100 | 無溢出；摘要卡**2 列**，sticky 摘要列高 159px（單列 84px） | 未測 |
| 420 | 頁面無橫向捲動；5 張卡直排，摘要列高 387px（`position:static`，不 sticky） | 頁面橫向溢出 26px；`.stl-main` 446>420；卡片超出 |
- 圖表（SVG）與需處理面板：1280 全頁截圖檢視，圖表長條與右端數字完整、需處理面板文字完整換行；無裁切。
- 表格：420 時 `.stl-table` 寬 550–978px（超過視窗），頁面不橫向捲動（在卡片內被收），**新舊版相同**：「四之一」「二之二」等表格最右欄（毛利／毛利比）被截在卡片外、品名欄被擠成一字一行（見 `shots-t37b/new-420-full.png`）。

## 5. 發現
**S-1（建議）｜900–1250px 寬度 sticky 摘要列變 2 列、高 159px。** `.stl-strip` 在 >900px 是 `position: sticky`（`:119`），卡片最小 210px，≈1250px 以下一列放不下 ⇒ 兩列常駐、吃掉約 160px 可視高度（筆電 1024×768 約兩成）。e2e 只守 ≥1440 一列。提案：900–1250 區間把 sticky 關掉（或只 sticky 精簡的單列），或在該區間把卡片縮成 2 欄 3 列且不 sticky。S。

**S-2（建議）｜列印時摘要卡的欄數隨之改變，沒有守門。** 列印區塊沒動，但 `.stl-kpis` 的欄數改成自動換行；A4（內容寬約 186mm）會變 3＋2 兩列，而且 `.stl-k__v` 在列印時用 `clamp(...vw...)`，字級依視窗寬度——列印預覽的實際外觀**未驗證**。主管簽核用，建議在列印媒體固定 `grid-template-columns: repeat(5,1fr)`＋固定字級，並補一題 `emulate_media('print')` 下的欄數。S。

**N-1（觀察）｜420 寬度長專案名稱在頂列溢出並疊在摘要卡上**（`shots-t37b/new-420-full.png` 頂部）。**新舊版相同**，不是本次回歸；`.stl-toolbar` 的標題沒有換行／截斷。
**N-2（觀察）｜420 寬度的寬表格被卡片截斷、品名一字一行**（同上，新舊相同）。建議之後給表格容器 `overflow-x:auto`。
**N-3（觀察）｜毛利／淨利卡的「／」分隔符在畫面上消失**，改靠 `value2` 另起一段（寬度夠時同行、不夠時換行）。語意清楚、無資料影響；但若有人用截圖或讀畫面文字比對「金額 ／ 比例」會對不上（我查無此類測試）。

## 6. 清理
`%TEMP%\motrix-pytest-aud7g`、探針輸出目錄已刪；樹內 `git status` 僅本報告、探針檔、截圖。（過程中看到另一組 `motrix-pytest-scopegate-modtest-*` 暫存，不是我建的，沒動。）
