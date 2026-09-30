# 字型

- **LINE Seed TW**（Thin／Regular／Bold／ExtraBold），版權 LY Corporation，授權 **SIL Open Font License 1.1**（見 `OFL.txt`；依據：字型檔 name table nameID 13／14，以及使用者 2026-09-26 表單確認 U19）。
- 2026-09-26 由原始 otf（v1.400）**只轉格式**成 woff2（fontTools 4.66，未做子集：字符 14038、字碼對照 13918 與原檔逐一相同），4 支合計 21.2 MB → 13.65 MB。原始 otf 在 git 歷史裡。
- 隨產品散布字型時，`OFL.txt` 必須一起附上（OFL §2）；不可以單獨販售字型本身（OFL §1）。
- 不要做常用字子集：客戶名稱、地址常有罕用字，子集會讓它們變成方框。

## 官方來源查證（2026-09-30）

| 項目 | 結果 |
|---|---|
| 官方頁面 | <https://seed.line.me/index_tw.html>（LINE Seed 官方網站，繁中頁）；存取日 **2026-09-30** |
| 頁面所載授權 | 「SIL Open Font License, Version 1.1」；全文連結 <https://scripts.sil.org/OFL> |
| 著作權人 | LY Corp.（頁面：LINE Seed 的所有內容與著作權屬 LY Corp.；字型檔內 nameID 0：© LY Corporation） |
| 商用 | 個人與商業用途皆可；除 LY Corp. 外，第三方不得**單獨銷售字型檔案本身**；商業使用**建議**標示字體來源或歸屬 |
| 官方 GitHub | <https://github.com/line/seed>，授權檔 `OFL.txt`（原始檔 <https://raw.githubusercontent.com/line/seed/main/OFL.txt>，存取日 2026-09-30） |
| 逐字比對 | 本目錄 `OFL.txt` 的授權本文（自「SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007」起）與官方 GitHub 的 `OFL.txt` 空白正規化後**逐字相同**（2026-09-30 比對） |
| 結論 | **相符**：授權確為 SIL OFL 1.1；本目錄的授權檔隨字型出貨（OFL §2 已滿足）。 |

**歸屬標示（建議，非必要）**：官方建議商業使用時標示來源。目前產品畫面沒有標示；若要加，建議放在「關於／系統資訊」頁一行：「字型：LINE Seed TW © LY Corporation，SIL Open Font License 1.1」。這是產品決定，不影響授權合規。

**限制提醒**：OFL 允許修改與再散布，但衍生字型不可使用保留字型名稱（本字型 metadata 未宣告保留名稱）；本專案只做了格式轉換（otf → woff2），沒有改字形。
