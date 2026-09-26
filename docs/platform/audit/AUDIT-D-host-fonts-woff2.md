# 抽查：主持的 h-fonts-woff2——字型 otf 轉 woff2（wip/h-fonts-woff2 94a78b4c；合回前）（D，2026-09-26）

> 依 PLAYBOOK §G4：只轉字型格式＋CSS 引用＋授權檔＋測試，走抽查（看 diff、跑受影響題、做 1 個突變）。
> 對象：`20c4be8d`（/fonts/ 7 天快取）、`7728934b`（重產產生檔）、`94a78b4c`（4 支 otf → woff2、OFL.txt、fonts/README.md、style.css 改引用）。

## 0. 結論

- **必修 0、建議 0、觀察 2**。

## 1. 抽查

| 項目 | 結果 |
|---|---|
| diff | CSS 4 處 `@font-face` 全改 woff2；repo 內沒有其他地方引用 `.otf`（歷史 changelog 除外） |
| 檔頭 | 4 支 woff2 開頭皆 `wOF2` |
| 受影響題 `test_font_cache_headers` | 3 過 |
| 突變 FW1：Bold 改回引用已刪的 `.otf` | 紅（`test_css_references_only_existing_fonts...`） |
| 字符數與對照表逐一相同 | **D 未獨立驗**：venv 沒有 fontTools，依規則不在共用 venv 安裝 |

## 2. 觀察

**FW-O1　woff2 送出的 Content-Type 是 `application/octet-stream`，同時帶 `nosniff`**
- TestClient 實測。原因是這台機器的 `mimetypes` 認不得 `.woff2`，而 Windows 的 mimetypes 會讀登錄檔，所以不同機器的結果可能不同。
- Chrome 與 Firefox 的 nosniff 只擋 script 和 style，字型照樣會載入，所以不影響顯示。otf 原本也是一樣，不是這包造成的退步。
- 如果要讓結果固定，可以在 main 加一行 `mimetypes.add_type("font/woff2", ".woff2")`。

**FW-O2　test_map.json 在 94a78b4c 又過期了**（origin/platform 一致）。7728934b 重產之後，94a78b4c 又改了輸入；交給列車重產。
