"""一次性腳本：補上 claude 帳號的 gateway_guide_edit 權限模組旗標。

用途：`create_claude_account.py` 建立 claude 帳號時只給了當時既有的 4 個 *_guide_edit
模組，後來新增 gateway_guide 類別，MODULES 清單更新了但既有帳號不會自動補上新旗標
（該腳本是冪等的，帳號已存在就只回報現況、不更新）。這支腳本直接把 claude 帳號的
modules 補齊成最新清單。

用法（把這個檔案放進 backend/ 目錄，跟 motrix_erp.db 同一層，不管在哪個目錄下執行都會
自動抓自己所在資料夾裡的 db，不受目前工作目錄影響）：
    python fix_claude_modules.py
"""
import json
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "motrix_erp.db")
MODULES = ["switch_guide_edit", "netarch_guide_edit", "monitor_guide_edit", "access_guide_edit", "gateway_guide_edit"]


def main():
    if not os.path.exists(DB_PATH):
        print(f"找不到資料庫檔案：{DB_PATH}")
        print("請確認這個 .py 檔跟 motrix_erp.db 放在同一個資料夾（backend/）")
        return
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    user = cur.execute("SELECT id, modules FROM users WHERE username='claude'").fetchone()
    if not user:
        print("找不到 claude 帳號，請先執行 create_claude_account.py")
        con.close()
        return

    print(f"更新前 modules：{user['modules']}")
    cur.execute("UPDATE users SET modules=? WHERE username='claude'", (json.dumps(MODULES, ensure_ascii=False),))
    con.commit()
    con.close()

    print(f"更新後 modules：{json.dumps(MODULES, ensure_ascii=False)}")
    print("完成。")


if __name__ == "__main__":
    main()
