"""一次性 Google 行事曆 OAuth 授權腳本（2026-08-21）。

必須在正式機本機執行（RDP 進去，用跟 email 通知同一組 Gmail 帳號登入瀏覽器），
因為 Google 的 Desktop app OAuth 流程走 loopback redirect（http://127.0.0.1:PORT），
瀏覽器完成同意後要能連回本機這支腳本開的暫時性 HTTP server 才能拿到授權碼。

事前準備：
  1. 到 https://console.cloud.google.com 建一個專案，啟用 "Google Calendar API"
  2. 建立憑證 → OAuth 用戶端 ID → 應用程式類型選「電腦版應用程式 Desktop app」
  3. 先透過系統的「Google 行事曆設定」頁面（superadmin）把 Client ID / Client Secret
     存起來（也可以用 --client-id / --client-secret 參數直接帶給這支腳本）

用法：
    cd backend
    python scripts/setup_google_calendar_oauth.py
    # 或指定尚未存到系統設定裡的憑證：
    python scripts/setup_google_calendar_oauth.py --client-id XXX --client-secret YYY

跑完後 refresh_token 會直接寫回 system_settings.google_calendar，之後系統背景
執行緒會自動用它換發短效 access_token，不需要再次人工介入（除非撤銷授權）。
"""
import argparse
import json
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from helpers.settings import _get_setting, _set_setting  # noqa: E402

_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SCOPE     = "https://www.googleapis.com/auth/calendar.events"
_PORT      = 8765

_result = {"code": None, "error": None}


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        qs = urllib.parse.parse_qs(parsed.query)
        _result["code"]  = (qs.get("code") or [None])[0]
        _result["error"] = (qs.get("error") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if _result["code"]:
            self.wfile.write("<h2>授權完成，可以關閉這個分頁，回到終端機視窗查看結果。</h2>".encode("utf-8"))
        else:
            self.wfile.write(f"<h2>授權失敗：{_result['error']}</h2>".encode("utf-8"))
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def log_message(self, fmt, *args):
        pass  # 安靜一點，不要把 http.server 預設的存取 log 洗版終端機


def _post_form(url: str, data: dict) -> dict:
    payload = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=payload, method="POST",
                                  headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-id")
    parser.add_argument("--client-secret")
    parser.add_argument("--calendar-id", default=None,
                         help="要寫入事件的行事曆 ID，預設沿用系統設定裡已存的值（未設定則用 primary）")
    parser.add_argument("--port", type=int, default=_PORT)
    args = parser.parse_args()

    cfg = _get_setting("google_calendar", {}) or {}
    client_id     = args.client_id or cfg.get("client_id") or ""
    client_secret = args.client_secret or cfg.get("client_secret") or ""
    calendar_id   = args.calendar_id or cfg.get("calendar_id") or "primary"
    if not client_id or not client_secret:
        print("錯誤：缺少 Client ID / Client Secret。")
        print("請先到系統的「Google 行事曆設定」頁面（superadmin）填寫並儲存，")
        print("或用 --client-id / --client-secret 參數直接帶給這支腳本。")
        sys.exit(1)

    redirect_uri = f"http://127.0.0.1:{args.port}/callback"
    auth_params = {
        "client_id":     client_id,
        "redirect_uri":  redirect_uri,
        "response_type": "code",
        "scope":         _SCOPE,
        "access_type":   "offline",
        "prompt":        "consent",  # 強制每次都吐 refresh_token，不會因為之前同意過就省略
    }
    auth_url = f"{_AUTH_URL}?{urllib.parse.urlencode(auth_params)}"

    print("=" * 70)
    print("Google 行事曆一次性授權")
    print("=" * 70)
    print(f"請用 email 通知設定裡那組 Gmail 帳號登入，開啟以下網址完成授權：\n")
    print(auth_url)
    print(f"\n（會自動嘗試在本機瀏覽器開啟；若沒有跳出，請手動複製上面網址開啟）")
    print(f"等待授權中…（本機 127.0.0.1:{args.port}）\n")

    server = HTTPServer(("127.0.0.1", args.port), _CallbackHandler)
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass
    server.serve_forever()

    if not _result["code"]:
        print(f"授權失敗：{_result['error']}")
        sys.exit(1)

    print("已取得授權碼，正在換發 refresh_token…")
    token_resp = _post_form(_TOKEN_URL, {
        "client_id":     client_id,
        "client_secret": client_secret,
        "code":          _result["code"],
        "grant_type":    "authorization_code",
        "redirect_uri":  redirect_uri,
    })
    refresh_token = token_resp.get("refresh_token")
    if not refresh_token:
        print(f"換發失敗，回應內容：{token_resp}")
        print("常見原因：這個 Google 帳號先前已同意過且未強制 prompt=consent——")
        print("這支腳本已經帶 prompt=consent，理論上應該還是會拿到；若持續失敗，")
        print("可到 Google 帳戶「第三方應用程式存取權」先移除這個應用程式的授權再重跑一次。")
        sys.exit(1)

    new_cfg = {**cfg, "client_id": client_id, "client_secret": client_secret,
               "calendar_id": calendar_id, "refresh_token": refresh_token}
    _set_setting("google_calendar", new_cfg)
    print("\n授權完成！refresh_token 已寫入系統設定，之後全自動運作，不需要再次執行這支腳本。")
    print(f"目前寫入的 calendar_id：{calendar_id}")
    print("可到「Google 行事曆設定」頁面確認狀態顯示為「已連接」，並用「建立測試事件」按鈕驗證。")


if __name__ == "__main__":
    main()
