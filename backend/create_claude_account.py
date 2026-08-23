"""一次性建立 `claude` 低權限自動化帳號（比照 2026-08-08 `automation` 帳號的建立精神）。

用途：AI 對話工作階段需要透過 API／直接寫 session 對這台機器的資料庫做選型資料庫
（env_guide／netarch_guide／switch_guide／monitor_guide／access_guide）等內容維護，
過去曾經因為本機沒有已知密碼帳號而借用真人帳號（corbin）的 session，導致稽核紀錄與
系統通知信誤植為該真人所為——2026-08-09 已在開發機建立專用 `claude` 帳號解決，這支
腳本是把同一件事在正式機重做一次。

role='viewer'（2026-08-24 安全審查修正，原本用 'admin' 並不是真的最小權限：全系統
至少 15+ 個端點只檢查 `role in ("superadmin","admin")`、完全不看 `modules` 清單，
role='admin' 因此能存取稽核記錄／財務儀表板／承攬商財稅資料等文件從未打算開放的
範圍。`helpers/auth.py::_require_user()` 的 module 檢查邏輯只要求 `role != superadmin`
就會生效，跟 role 實際是 admin 還是 viewer 無關，所以降級不影響下面這 5 個
`*_guide_edit` 模組原本能打的端點）＋只給選型資料庫相關的 *_guide_edit 模組旗標，
不具備使用者管理／簽核／刪除資料等完整超管能力。密碼為隨機字串，僅供留存記錄用——
實際使用方式是之後需要時直接在 sessions 表插入綁定此帳號 id 的 token，不透過一般登入。

冪等：若 `claude` 帳號已存在，不會重複建立，只會回報現況。

用法（於正式機 backend/ 目錄下執行）：
    python create_claude_account.py
"""
import json
import secrets
import sqlite3
from datetime import datetime

from helpers.auth import _hash_pw

DB_PATH = "motrix_erp.db"
MODULES = ["switch_guide_edit", "netarch_guide_edit", "monitor_guide_edit", "access_guide_edit", "gateway_guide_edit"]


def main():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    existing = cur.execute("SELECT id, modules FROM users WHERE username='claude'").fetchone()
    if existing:
        print(f"claude 帳號已存在（id={existing['id']}），未重複建立。")
        print(f"目前 modules：{existing['modules']}")
        print("如需補上新模組旗標，請手動 UPDATE users SET modules=... WHERE username='claude'。")
        con.close()
        return

    now = datetime.now().isoformat()
    password = secrets.token_urlsafe(24)
    pw_hash = _hash_pw(password)
    cur.execute(
        """INSERT INTO users (username, password_hash, display_name, role, email, phone, modules, active, created_at, must_change_password)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        ("claude", pw_hash, "Claude", "viewer", "", "", json.dumps(MODULES, ensure_ascii=False), 1, now, 0),
    )
    user_id = cur.lastrowid
    con.commit()
    con.close()

    print("已建立 claude 帳號：")
    print(f"  user_id  = {user_id}")
    print(f"  role     = viewer")
    print(f"  modules  = {MODULES}")
    print(f"  password = {password}  （僅供留存記錄，正常不會用來互動登入）")
    print()
    print("之後需要用這個帳號執行 API 動作時，直接在 sessions 表插入一筆綁定此 user_id 的")
    print("token（比照 secrets.token_hex(32)），不需要透過登入流程。")


if __name__ == "__main__":
    main()
