"""CORS 白名單改用環境變數（2026-09-11）。

`DR-SOP.md` §5 長期把「CORS 白名單寫死 IP，換機器/換 IP 需改 code 重新部署」
列為待改進。改成 `MOTRIX_CORS_ORIGINS` 之後，這支測試釘住兩件事：

1. **沒設環境變數時，行為與改動前逐字相同**——這是最重要的一條。預設值必須是
   原本那六筆，不能是空清單；空清單會讓正式機所有跨來源請求被擋，而且症狀
   （瀏覽器 console 的 CORS 錯誤）跟「服務掛了」看起來很像，很難第一時間聯想到。
2. 有設的時候**完全取代**預設清單，不是附加——這是安全邊界，附加語意會讓人
   以為「我只列了一筆」實際上舊的六筆還開著。

⚠️ `main` 一律在測試函式內部 import，不能寫在模組層：`conftest.py` 的 `_app`
fixture 會在 `main` 已經被提早 import 時直接 fail（那道守門是防止測試寫進真實
`motrix_erp.db` / `db_backups/` 的，很重要）。所有測試都掛 `client` fixture，
讓路徑先被導向隔離目錄，之後再 import 才安全。
"""

EXPECTED_DEFAULTS = [
    "http://localhost:666",
    "http://127.0.0.1:666",
    "http://172.16.10.177:666",
    "https://localhost:666",
    "https://127.0.0.1:666",
    "https://172.16.10.177:666",
]


def test_default_matches_pre_change_hardcoded_list(client):
    """沒設環境變數 → 原本那六筆，順序也一樣。"""
    import main
    assert main._resolve_cors_origins("") == EXPECTED_DEFAULTS


def test_none_and_whitespace_fall_back_to_defaults(client):
    """空字串、只有空白、只有逗號，都要退回預設值而不是變成空清單。"""
    import main
    for raw in ("", "   ", ",", " , , "):
        assert main._resolve_cors_origins(raw) == EXPECTED_DEFAULTS, f"raw={raw!r}"


def test_env_value_replaces_defaults_entirely(client):
    """有設就完全取代，不是附加。"""
    import main
    got = main._resolve_cors_origins("https://erp.miactw.com:666")
    assert got == ["https://erp.miactw.com:666"]
    assert not any(o in got for o in EXPECTED_DEFAULTS)


def test_env_value_is_comma_separated_and_trimmed(client):
    import main
    got = main._resolve_cors_origins(" https://a:666 , https://b:666 ,, https://c:666 ")
    assert got == ["https://a:666", "https://b:666", "https://c:666"]


def test_running_app_actually_uses_resolved_list(client):
    """不只測純函式——確認 app 真的把解析結果掛進 CORSMiddleware。

    只驗證函式而不驗證接線，會漏掉「函式寫對了但 add_middleware() 還是傳舊清單」
    這種改到一半的情況。"""
    import main
    cors = [m for m in main.app.user_middleware if m.cls.__name__ == "CORSMiddleware"]
    assert len(cors) == 1, f"預期剛好一個 CORSMiddleware，實際 {len(cors)}"
    configured = cors[0].kwargs.get("allow_origins")
    assert configured == main._cors_origins
    # 這台開發機沒設環境變數，所以應該就是預設六筆
    assert configured == EXPECTED_DEFAULTS
