# -*- coding: utf-8 -*-
"""還原用：把某一天的備份資料夾解成「真正存放內容的資料夾」（資料沒變的日子只留 `SAME_AS.json`，不重複寫整庫與 JSON）。

用法（backend 目錄）：
    python tools/find_backup.py <某一天的備份資料夾>
    例：python tools/find_backup.py db_backups\2026-09-27
        python tools/find_backup.py "G:\我的雲端硬碟\系統存檔\每日備份\2026-09-27"

輸出：真正的資料夾、其中的 motrix_erp.db（若有）。找不到（標記指向的那一天已不存在）⇒ 明說並以非 0 結束，不假裝有。
規則與 DR-SOP.md「同上一份」一節相同。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main(argv) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    day_dir = os.path.abspath(argv[1])
    if not os.path.isdir(day_dir):
        print("找不到資料夾：%s" % day_dir)
        return 1
    from archive import resolve_same_as, SAME_AS_FILE
    real = resolve_same_as(day_dir)
    if not real:
        print("這一天（%s）是「同上一份」，但標記指向的那一天已經不存在——內容找不到，請改用更早或更晚、有實體檔的一天。" % day_dir)
        return 1
    same = os.path.normcase(real) != os.path.normcase(day_dir)
    print("實體資料夾：%s%s" % (real, "（%s 指向這裡）" % SAME_AS_FILE if same else ""))
    db_path = os.path.join(real, "motrix_erp.db")
    if os.path.isfile(db_path):
        print("整庫檔：%s（%d bytes）" % (db_path, os.path.getsize(db_path)))
    else:
        print("（這一層沒有整庫檔；JSON 備份請直接用上面那個資料夾裡的 *.json）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
