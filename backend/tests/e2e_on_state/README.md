# tests/e2e_on_state — ON 狀態真瀏覽器 e2e（T62 版面線）

**已寫、未跑。** 需要 playwright＋chromium；題目標 `@pytest.mark.e2e`，找不到 playwright 自動略過。
旗標與版面一律走真的設定／定義 API（見 `_common.py`），不直接寫庫。

| 檔 | 場景 |
|---|---|
| `test_case_page_on_state.py` | C-1 區塊隱藏／排序／改名、C-2 分頁列、C-3 執行子分頁、C-4 被隱藏區塊的資料照樣自動存檔、C-5 核心項目不能隱藏／改名 |
| `test_quotation_pages_on_state.py` | Q-1 表單區塊、Q-2 被隱藏欄位值照樣存檔、Q-3 自訂欄位存檔／還原／旗標關閉、Q-4 報價單清單欄位（順序固定、核心欄不可隱藏） |
| `test_off_state_golden.py` | 報價單表單、報價單清單的 OFF golden（畫面文字＋請求清單）；`MOTRIX_RECORD_GOLDEN=1` 錄製，基底樹與合入後各錄一份必須相同 |

第一次實跑：選擇器與種子是對照原始碼寫的，以畫面為準校正；`golden/` 目前是空的。
