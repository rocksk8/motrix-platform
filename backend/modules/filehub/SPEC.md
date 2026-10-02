# M13 檔案中心（filehub）· 規格條件

> 2026-10-01 建立（第 29 班；設計 `proposal-attachments-search-preview` §4）。本模組**不建表、不存檔案、不做權限判斷**：
> 全系統上傳檔案的分類搜尋頁（`file-center.html`）與案件頁「全部附件」頁籤，資料來自各擁有模組以 `attachments.catalog` 提供者（IP-105）
> 提供的 `search`／`count`。拿掉本模組時，本檔與本模組的測試一起消失；各提供者的 `search`／`count` 留在擁有模組、不受影響。
> 格式同 `modules/accounting/SPEC.md`（`backend/tests/test_spec_coverage_2026_09_21.py` 讀各模組的 `SPEC.md`）。

## 用途與 API

- `GET /api/filehub/search`：把所有 `attachments.catalog` 提供者的 `search`／`count` 合併、依上傳時間由新到舊排序、分頁（`page ≤ 20`、`size ≤ 50`）。
  條件：`q`（檔名／單號／案件號／客戶／案名）、`types`、`exts`、`date_from`／`date_to`、`uploader`、`quote_no`、`doc_no`、`customer`。
  回應：`items`、`facets`（`byType`／`byExt`／`byModule`）、`categories`、`unavailable`、`hasMore`。
- 開檔不在本模組：一律走 L1 `GET /api/attachments/open`（提供者驗權；看不到＝404）；預覽用共用元件 `MotrixFilePreview`。
- 權限模型＝`own_rule`（`docs/platform/case_read_scope.json`）：每個提供者套**原單據自己的讀取規則**；全域瀏覽（不帶 `quote_no`）另要「檔案中心」模組（`file_center`）或最高管理者；帶 `quote_no`（案件頁頁籤）任何登入者可呼叫，結果仍只含他在原單據頁打得開的檔。

## 規格條件

- **FHB1.** 搜尋項目只有固定鍵（`ITEM_KEYS`），**沒有 `path`**：搜尋結果不可以把「猜不到的路徑」變成「列得出來」。
- **FHB2.** 看不到的檔不列、不計數、檔名不出現在任何欄位（`items`／`facets`／`categories`／`unavailable`）；也不回「因權限未列出 N 個」——`q` 可任意輸入，回個數本身就是外洩。
- **FHB3.** 搜尋與各提供者 `open()` 用**同一道**可讀規則，含「路徑綁單據」（`upload_path_key`）：路徑被塞進別張單據資料夾的檔，既打不開也不列出來。
- **FHB4.** 費用單據（`kind≠''`）的附件＝金額：案件的一般讀者（非申請人／簽核人／出納財務／管理員）不列、不計數、打不開；舊版額外支出（`kind=''`）不受影響。
- **FHB5.** 每個已登記的 `attachments.catalog` 提供者都有 `search` 與 `count`；缺的或壞掉的只少自己那一類，並在 `unavailable` 明說（不是 0 筆）。
- **FHB6.** 擁有模組不在／未載入 ⇒ `unavailable` 明說那一類沒有列入搜尋（缺席不可以跟「沒有檔案」長一樣）。
- **FHB7.** 全域瀏覽需要「檔案中心」模組權限（或最高管理者）；帶 `quote_no` 的查詢（案件頁「全部附件」）不需要，但結果同樣只含呼叫者有權限的檔；未登入 401。
- **FHB8.** 項目不帶收款銀行／帳號等個資欄位（單據上有收款帳號時，回應任何地方都找不到那串數字）。
- **FHB9.** 結果列主動作「開啟檔案」＝直接打開上傳的檔（圖片／PDF 於新分頁、其他類型走預覽窗），取檔仍是 L1 `attachments/open`（同一道可讀規則、使用者自己的 token，沒有新路徑）；取不到（已刪除／無權限）明確訊息、不留空白分頁；舊跳轉降為次要連結「前往原單據」。

## 非目標

- 不做全文檢索（只比對檔名與單據欄位）、不存縮圖、不提供下載（下載走 `attachments/open`）。
- 不改任何擁有模組的上傳流程；新增一種上傳點＝在擁有模組登記提供者，本模組不用改。

## 測試（洩漏守門）

`backend/tests/test_filehub_search_2026_09_30.py`（合併、篩選、分頁、缺席明說）、`test_filehub_leak_a3_2026_10_01.py`（無權限者零命中零計數、路徑被塞入、金額類單據、費用單據附件遮蔽、突變題）、`test_e2e_filehub_2026_09_30.py`（頁面與案件頁頁籤）。
