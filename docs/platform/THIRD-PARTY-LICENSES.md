# 第三方授權清單（隨產品散布的元件）

> 建立 2026-09-30。原則：**隨產品散布的第三方元件，授權檔要跟元件放在一起，來源與查證日期記在這裡**。新增元件時在下表加一列；守門：`tests/platform/test_font_license_2026_09_30.py`（字型）。

| 元件 | 位置 | 授權 | 授權檔 | 來源與查證 |
|---|---|---|---|---|
| LINE Seed TW 字型（Thin／Regular／Bold／ExtraBold，woff2） | `frontend/fonts/` | SIL Open Font License 1.1 | `frontend/fonts/OFL.txt`（與字型同資料夾） | 官方 <https://seed.line.me/index_tw.html>（存取 2026-09-30）；官方 GitHub <https://github.com/line/seed> 的 `OFL.txt` 與本專案授權本文逐字相同；細節見 `frontend/fonts/README.md`「官方來源查證」 |
| Leaflet、Leaflet.markercluster | `frontend/static/vendor/` | 見各資料夾 | 各資料夾的 `PROVENANCE.md`／授權檔 | 由 `verify_package.py` (5) 比對雜湊 |
| Chart.js、SheetJS 等前端函式庫 | `frontend/static/vendor/` | 見各檔頭 | 檔頭授權註解 | 各檔內註解 |

## 字型的義務摘要（OFL 1.1）

- 散布字型（含隨產品出貨）時，必須附上 OFL 全文與著作權聲明 ⇒ `frontend/fonts/OFL.txt` 必須跟著字型出貨（不在 export-ignore；sale 包剪裁設定也不剪 `frontend/`）。
- 不可單獨販售字型檔案本身（產品整體販售允許）。
- 衍生字型不可使用保留字型名稱；本專案只做格式轉換，未改字形。
- 商業使用建議標示來源（LY Corp. 官方建議，非授權條件）。
