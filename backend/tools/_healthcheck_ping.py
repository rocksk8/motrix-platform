"""健康檢查用的極簡 HTTP/HTTPS ping 工具，供 apply_update.ps1 的 Test-Ping 呼叫。

2026-09-08：apply_update.ps1 原本用 curl.exe 做這支健康檢查（HTTPS 情境下用
-k 跳過自簽憑證驗證，因為 Windows PowerShell 5.1 沒有 Invoke-WebRequest
-SkipCertificateCheck 參數）。但同一晚連續三次部署，套用後健康檢查都判定
失敗（healthy=False，一次真的抓到 6 筆 log 錯誤、兩次是 0 筆），觸發不必要
的自動回滾；事後用完全相同的 curl.exe 呼叫（含直接呼叫／巢狀一層呼叫、不同
timeout）獨立重測，每次都正常回應 200——代表問題只會在部署當下的即時狀態
出現，任何事後模擬都測不到。

同一段時間，開發機這邊用 Python requests 打同一支正式機端點（deploy
dashboard 的背景狀態輪詢）每次都正確回報真實狀態，跟 curl.exe 的健康檢查
形成明顯對照。curl.exe 在 Windows 上預設走 Schannel（實測 -v 輸出可見自簽
憑證連線會發生兩次 TLS renegotiation），懷疑是 Schannel 在這個環境下的
穩定性問題；Python 的 ssl 模組走 OpenSSL，不經過 Schannel，改用這支腳本
統一 HTTP/HTTPS 兩種情境的健康檢查，繞開這整條路徑。

用法：python _healthcheck_ping.py <url> <timeout_seconds>
exit 0 = 收到 200；exit 1 = 任何失敗（連線失敗／逾時／非 200）。
"""
import ssl
import sys
import urllib.request


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: _healthcheck_ping.py <url> <timeout_seconds>", file=sys.stderr)
        return 1
    url = sys.argv[1]
    timeout = float(sys.argv[2])

    # 只用於本機 loopback 健康檢查（見 apply_update.ps1），自簽憑證沒有
    # 受信任的 CA，這裡略過驗證；不影響其他任何對外連線的憑證驗證。
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(url, timeout=timeout, context=ctx) as resp:
            status = getattr(resp, "status", None)
            if status is None:
                status = resp.getcode()
            if status == 200:
                return 0
            print(f"HEALTHCHECK_FAIL: unexpected status {status}")
            return 1
    except Exception as e:
        # 2026-09-08：印到 stdout 而非 stderr——呼叫端（apply_update.ps1／
        # rollback_update.ps1／_dashboard_remote.ps1）過去用 2>$null 把
        # stderr 整個丟掉，導致每次失敗只看得到 exit code、看不到原因，
        # 是這一晚反覆盲猜根因的主因之一。印到 stdout 才能確保不管呼叫端
        # 有沒有記得改，這行都會被撈到。
        print(f"HEALTHCHECK_FAIL: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
