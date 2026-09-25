"""（自 tests/test_netguard_2026_09_21.py 拆出，2026-09-25）產品側：`fetch_detail` 的雷達開關檢查。

NETGUARD 本身的守門留在原檔；這兩題驗的是 M11 標案雷達的行為，跟著模組走。
"""
import modules.tender_radar.source as ts

FAKE_URL = "https://example.invalid/netguard-self-test"

# ══════════════════════════════════════════════════════════════════════
# 產品側：`fetch_detail` 沒有開關檢查
# ══════════════════════════════════════════════════════════════════════

def test_fetch_detail_respects_the_radar_switch(monkeypatch):
    """🔴 `radar_on()` 是關的時候，直接呼叫 `fetch_detail` **不可以連外**。

    ## 現況（B 讀出來，我複核過）

        run_scan()      第一行  if not radar_on(): return     ✅ 有守
        fetch_detail()  沒有任何開關檢查                       🔴 沒有

    > **B：「今天只有 `_fetch_details` 會叫它，而它在 `run_scan` 底下 ⇒ 目前安全。
    > 但那是**呼叫端剛好都在守衛底下**，不是那個函式本身安全。」**

    🔑 那跟 `DEFAULT_SCAN_HOUR` 靠「寫入端剛好擋了範圍」活下來是同一個形狀：
    **一個不變量由呼叫端維持，而呼叫端會增加。**
    ⚠️ 而這個不變量是「這台機器不會在沒有人知道的情況下對外連線」——
    它是整條線最外層的那個承諾。

    📌 這一題**不靠 NETGUARD 的紅**（那是 fixture 收尾時的事），
    而是直接觀測「有沒有嘗試」—— 觀測點在被測對象的下游，不在測試框架裡。
    """
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", False)
    monkeypatch.delenv("MOTRIX_TENDER_RADAR", raising=False)
    assert ts.radar_on() is False, "前提不成立：雷達應該是關的"

    attempts = []

    def _record(req, *a, **kw):
        attempts.append(req if isinstance(req, str) else getattr(req, "full_url", ""))
        raise OSError("不連出去")

    monkeypatch.setattr(ts.urllib.request, "urlopen", _record)
    ts.fetch_detail("https://web.pcc.gov.tw/tps/QueryTender/query/x")

    assert not attempts, (
        f"雷達是關的，而 `fetch_detail` 還是嘗試連出去了：{attempts}\n"
        "⇒ 那個函式本身沒有守衛，它只是**剛好**都被守衛底下的人呼叫。"
        "而呼叫端會增加 —— 下一個呼叫者不會知道自己需要先檢查開關。"
    )


def test_fetch_detail_still_works_when_the_radar_is_on(monkeypatch):
    """對照組：**雷達開著時它要真的去抓**。

    ⚠️ 沒有這一題，一個 `def fetch_detail(...): return None, "disabled"` 的實作
    會讓上一題全綠 —— 而詳細頁從此再也抓不到，地點永遠是 NULL。
    🔑 「不該做的時候不做」與「該做的時候要做」是兩件事。
    """
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    attempts = []

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"<html>ok</html>"

        def geturl(self):
            return FAKE_URL

    def _ok(req, *a, **kw):
        attempts.append(req if isinstance(req, str) else getattr(req, "full_url", ""))
        return _Resp()

    monkeypatch.setattr(ts.urllib.request, "urlopen", _ok)
    html, _second = ts.fetch_detail("https://web.pcc.gov.tw/tps/QueryTender/query/x")
    assert attempts, "雷達開著，而 `fetch_detail` 一次都沒有嘗試連線"
    assert html is not None, "雷達開著卻沒有拿到內容"
