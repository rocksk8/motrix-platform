# -*- coding: utf-8 -*-
"""case v9（2026-10-14，案件階段樣板 S-ST2）：`case_stages` 加 `stage_key`（階段種類鍵；選填）。

- stage_key：由「套用階段樣板」寫入的種類鍵（小寫英數底線）；NULL＝手動新增的階段／舊案件（舊列全部維持 NULL，不補值）。
  只用於日後依種類分組的報表與「補上缺少的階段」；結案關卡、提醒、認列、獎金等消費者一律不讀它。
- `ratio_bp` V9 基準（db.py）已經有；這裡只在欄位意外不存在時補上（冪等，NULL＝未設，不是 0）。
- 只新增欄位、冪等；表不在 ⇒ 回原因字串＝未完成（下次啟動再補）；不自己 commit、不 import 會演進的程式碼。
- 回退：只進不退；舊程式不認得這一欄、SELECT * 照常、INSERT 不帶它也是 NULL ⇒ 回滾程式碼不需動資料。
"""


def up(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(case_stages)").fetchall()}
    if not cols:
        return "case_stages 表不存在，階段種類鍵欄位這次不補、下次啟動再試"
    if "ratio_bp" not in cols:
        conn.execute("ALTER TABLE case_stages ADD COLUMN ratio_bp INTEGER")
    if "stage_key" not in cols:
        conn.execute("ALTER TABLE case_stages ADD COLUMN stage_key TEXT")
    return None
