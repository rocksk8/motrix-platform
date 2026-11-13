# -*- coding: utf-8 -*-
"""case v10（2026-11-13，估價單）：`quotations` 加 `doc_type`（單據類型：quote＝報價單、estimate＝估價單）。

- doc_type：'quote'（報價單，預設）｜'estimate'（估價單）。**舊資料一律是 'quote'**（欄位預設值＋NOT NULL，既有列不用補值）。
  流程（簽核、狀態、權限、轉單、業績）兩種完全相同，只有單號字首（MQ／估價單字首）、標題與通知用語不同。
- 只新增欄位、冪等；表不在 ⇒ 回原因字串＝未完成（下次啟動再補）；不自己 commit、不 import 會演進的程式碼。
- 回退：只進不退；舊程式不認得這一欄、整列讀取照常、INSERT 不帶它也有預設值 'quote' ⇒ 回滾程式碼不需動資料。
"""


def up(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(quotations)").fetchall()}
    if not cols:
        return "quotations 表不存在，單據類型欄位這次不補、下次啟動再試"
    if "doc_type" not in cols:
        conn.execute("ALTER TABLE quotations ADD COLUMN doc_type TEXT NOT NULL DEFAULT 'quote'")
    return None
