"""建立或更新 `claude` 自動化帳號的 API session token。

用途：`create_claude_account.py` 只建立帳號，密碼僅供留存記錄、不透過一般登入流程使用
（見該檔案 docstring）。這支腳本直接在 sessions 表插入一筆綁定 claude 帳號的 token，
比照一般登入的 30 天效期（routers/auth.py auth_login()），執行後印出 token，供後續
API 呼叫使用。

冪等：每次執行都會先清掉該帳號現有的 session 再核發一筆新的，避免閒置 token 堆積；
不影響其他使用者的 session。兩台機器（開發機／正式機）都要各自在其 backend/ 目錄下
執行一次，token 不共用（各機器的 sessions 表是各自獨立的 SQLite 檔案）。

用法（於該機器 backend/ 目錄下執行）：
    python issue_claude_session.py
"""
import secrets
import sqlite3
import sys
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = "motrix_erp.db"
_EXPIRE_DAYS = 30


def main():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    user = cur.execute("SELECT id, username FROM users WHERE username='claude'").fetchone()
    if not user:
        print("找不到 claude 帳號，請先在這台機器執行 create_claude_account.py")
        con.close()
        return

    cur.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))

    now = datetime.now()
    token = secrets.token_hex(32)
    expires_at = (now + timedelta(days=_EXPIRE_DAYS)).isoformat()
    cur.execute(
        "INSERT INTO sessions (token, user_id, username, created_at, expires_at, last_active) VALUES (?,?,?,?,?,?)",
        (token, user["id"], user["username"], now.isoformat(), expires_at, now.isoformat()),
    )
    con.commit()
    con.close()

    print("已核發 claude 帳號 session token：")
    print(f"  token      = {token}")
    print(f"  expires_at = {expires_at}")
    print()
    print("請妥善保存此 token（勿寫入會被 git 追蹤的檔案），API 呼叫時放入標頭：")
    print(f"  Authorization: Bearer {token}")


if __name__ == "__main__":
    main()
