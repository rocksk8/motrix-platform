# -*- coding: utf-8 -*-
"""case v13（2026-11-17，備註事項 B／規格 PDF 併入）：`quotations` 加 `spec_files_json`。

- 欄位：`spec_files_json TEXT NOT NULL DEFAULT '[]'`（與 `signed_files_json` 同形狀：一個 JSON 陣列、每筆是一個上傳檔的 metadata
  `{id, name, path, size, pages, status, uploadedAt, uploadedBy}`；`status` ∈ ok／encrypted／broken／empty）。
  既有列自動得到 `'[]'`（SQLite 的 ADD COLUMN … DEFAULT 會回填），不用另外補值。
- 只新增欄位、冪等（欄位已在就不動）；表不在 ⇒ 回原因字串＝未完成（下次啟動再補）；不自己 commit、不 import 會演進的程式碼。
- 欄位**不進內容指紋**（它不在 `data_json` 裡；被選進合併的檔案 id 清單才在 `data_json.mergeFiles`，由報價單本身的存檔流程處理）。
- 回退：只進不退。舊程式不認得這一欄：SELECT 指名欄位的讀取不受影響、INSERT 不帶它＝預設 `'[]'`；
  只有整列 `SELECT *` 轉 dict 的地方會多一個 `spec_files_json` 鍵（無害）。⇒ 回滾程式碼不需要動資料庫。
"""


def up(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(quotations)").fetchall()}
    if not cols:
        return "quotations 表不存在，規格文件欄位這次不補、下次啟動再試"
    if "spec_files_json" not in cols:
        conn.execute("ALTER TABLE quotations ADD COLUMN spec_files_json TEXT NOT NULL DEFAULT '[]'")
    return None
